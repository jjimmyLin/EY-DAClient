"""Contracts for business-analysis indicator discovery.

The indicator workflow is intentionally isolated from the existing data-analysis
workflow.  The desktop sends one JSON payload plus an optional Dify file-list
input, and expects a strictly data-based metric pack in return.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


REQUEST_SCHEMA_VERSION = "metric_discovery.request.v1"
RESPONSE_SCHEMA_VERSION = "metric_discovery.result.v1"

SUPPORTED_REFERENCE_SUFFIXES = {
    ".doc",
    ".docx",
    ".md",
    ".pdf",
    ".ppt",
    ".pptx",
    ".rtf",
    ".txt",
}
SPREADSHEET_SUFFIXES = {".csv", ".xls", ".xlsb", ".xlsm", ".xlsx"}


class MetricDiscoveryContractError(ValueError):
    """Raised when a request or result violates the workflow contract."""


@dataclass(frozen=True)
class ReferenceAttachment:
    """Local reference material selected for one indicator request."""

    path: str
    name: str
    suffix: str
    size_bytes: int

    @classmethod
    def from_path(cls, file_path: str | Path) -> "ReferenceAttachment":
        path = Path(file_path).expanduser()
        suffix = path.suffix.lower()
        if suffix in SPREADSHEET_SUFFIXES:
            raise MetricDiscoveryContractError(
                f"{path.name}: spreadsheet data belongs in the data-analysis module."
            )
        if suffix not in SUPPORTED_REFERENCE_SUFFIXES:
            supported = ", ".join(sorted(SUPPORTED_REFERENCE_SUFFIXES))
            raise MetricDiscoveryContractError(
                f"{path.name}: unsupported reference type. Supported: {supported}."
            )
        if not path.is_file():
            raise MetricDiscoveryContractError(
                f"{path.name or path}: the file is unavailable."
            )
        try:
            size_bytes = path.stat().st_size
        except OSError as exc:
            raise MetricDiscoveryContractError(
                f"{path.name}: the file cannot be read."
            ) from exc
        return cls(
            path=str(path.resolve()),
            name=path.name,
            suffix=suffix,
            size_bytes=size_bytes,
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "extension": self.suffix,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class MetricDiscoveryRequest:
    """A complete, versioned request passed to the Dify metric workflow."""

    company_information: dict[str, Any]
    indicator_guidance: dict[str, Any]
    attachments: tuple[ReferenceAttachment, ...] = ()
    public_research_enabled: bool = False
    request_id: str = field(default_factory=lambda: str(uuid4()))
    submitted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def validate(self) -> None:
        count = self.indicator_guidance.get("indicator_count")
        if count is not None:
            try:
                normalized = int(count)
            except (TypeError, ValueError) as exc:
                raise MetricDiscoveryContractError(
                    "Indicator count must be a whole number from 5 to 10."
                ) from exc
            if not 5 <= normalized <= 10:
                raise MetricDiscoveryContractError(
                    "Indicator count must be between 5 and 10."
                )

        if not self.has_meaningful_input():
            raise MetricDiscoveryContractError(
                "Provide at least one company detail, indicator preference, "
                "or reference document before generating indicators."
            )

    def has_meaningful_input(self) -> bool:
        if self.attachments:
            return True
        if _contains_meaningful_value(self.company_information):
            return True
        return _contains_meaningful_value(self.indicator_guidance)

    def to_payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": REQUEST_SCHEMA_VERSION,
            "request_id": self.request_id,
            "submitted_at": self.submitted_at,
            "locale": "zh-CN",
            "company_information": self.company_information,
            "indicator_guidance": self.indicator_guidance,
            "reference_files": [
                attachment.metadata() for attachment in self.attachments
            ],
            "research_preferences": {
                "public_information_enabled": self.public_research_enabled,
                "company_data_role": (
                    "Use public company data only as supplementary identity and "
                    "business context. Do not treat registered business scope as "
                    "proof of the actual business model."
                ),
            },
            "output_requirements": {
                "language": "zh-CN",
                "indicator_count": self.indicator_guidance.get(
                    "indicator_count"
                ),
                "minimum_indicator_count": 5,
                "maximum_indicator_count": 10,
                "data_based_only": True,
                "each_indicator_must_include": [
                    "target_basis",
                    "analysis_objective",
                    "definition",
                    "analysis_method",
                    "analysis_grain",
                    "data_requirements",
                    "client_request_guidance",
                    "key_scope_questions",
                    "potential_anomalies",
                    "data_acquisition_difficulty",
                    "priority",
                ],
                "data_requirement_must_include": [
                    "dataset_name",
                    "business_purpose",
                    "grain",
                    "recommended_period",
                    "required_fields",
                    "join_keys",
                    "scope_and_completeness",
                ],
                "reject_generic_metrics_without_requestable_data": True,
                "merge_data_requests_across_indicators": True,
            },
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_payload(),
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def with_selected_company(
        self,
        selected_company: dict[str, Any],
        *,
        original_query: str | None = None,
    ) -> "MetricDiscoveryRequest":
        """Return the same request anchored to a user-confirmed legal entity."""
        company_name = str(
            selected_company.get("company_name") or ""
        ).strip()
        if not company_name:
            raise MetricDiscoveryContractError(
                "The selected company has no registered name."
            )
        company_information = dict(self.company_information)
        source_query = str(
            original_query
            or company_information.get("company_query")
            or company_information.get("company_name")
            or ""
        ).strip()
        company_information["company_query"] = source_query
        company_information["company_name"] = company_name
        company_information["selected_company"] = {
            key: str(selected_company.get(key) or "").strip()
            for key in (
                "company_name",
                "company_id",
                "credit_code",
                "status",
                "legal_representative",
                "established_date",
            )
        }
        return replace(self, company_information=company_information)


@dataclass(frozen=True)
class MetricIndicator:
    indicator_id: str
    title: str
    category: str
    priority: str
    target_basis: str
    analysis_objective: str
    definition: str
    formula: str
    analysis_grain: str
    dimensions: tuple[str, ...]
    analysis_method: tuple[str, ...]
    data_requirements: tuple[dict[str, Any], ...]
    client_request_guidance: str
    key_scope_questions: tuple[str, ...]
    potential_anomalies: tuple[str, ...]
    data_acquisition_difficulty: str
    evidence_basis: tuple[str, ...]
    assumptions: tuple[str, ...]


@dataclass(frozen=True)
class MetricDiscoveryResult:
    """Validated result returned by the dedicated Dify workflow."""

    summary: str
    indicators: tuple[MetricIndicator, ...]
    consolidated_data_requests: tuple[dict[str, Any], ...]
    assumptions: tuple[str, ...]
    source_notes: tuple[str, ...]
    workflow_run_id: str = ""
    raw_outputs: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_workflow_response(
        cls,
        response: dict[str, Any],
    ) -> "MetricDiscoveryResult":
        data = response.get("data") or {}
        if not isinstance(data, dict):
            raise MetricDiscoveryContractError(
                "The metric workflow response has no data object."
            )
        status = str(data.get("status") or "").strip().lower()
        if status and status != "succeeded":
            raise MetricDiscoveryContractError(
                str(data.get("error") or "The metric workflow failed.")
            )
        outputs = data.get("outputs") or {}
        if not isinstance(outputs, dict):
            raise MetricDiscoveryContractError(
                "The metric workflow outputs must be an object."
            )
        payload = _extract_result_payload(outputs)
        indicators_raw = payload.get("indicators") or []
        if not isinstance(indicators_raw, list):
            raise MetricDiscoveryContractError(
                "The metric workflow must return an indicators array."
            )
        if not 5 <= len(indicators_raw) <= 10:
            raise MetricDiscoveryContractError(
                "The metric workflow must return between 5 and 10 indicators; "
                f"received {len(indicators_raw)}."
            )

        indicators = tuple(
            _parse_indicator(item, index)
            for index, item in enumerate(indicators_raw, start=1)
        )
        consolidated = payload.get("consolidated_data_requests") or []
        if not isinstance(consolidated, list):
            consolidated = []
        return cls(
            summary=_as_text(
                payload.get("summary")
                or payload.get("business_summary")
                or "已生成可用于数据核查的分析指标。"
            ),
            indicators=indicators,
            consolidated_data_requests=tuple(
                item for item in consolidated if isinstance(item, dict)
            ),
            assumptions=_string_tuple(payload.get("assumptions")),
            source_notes=_string_tuple(payload.get("source_notes")),
            workflow_run_id=_as_text(
                response.get("workflow_run_id") or data.get("id")
            ),
            raw_outputs=outputs,
        )


def _extract_result_payload(outputs: dict[str, Any]) -> dict[str, Any]:
    for key in ("metric_pack", "result", "structured_output", "answer"):
        candidate = outputs.get(key)
        if isinstance(candidate, dict):
            return candidate
        if isinstance(candidate, str) and candidate.strip():
            text = _strip_json_fence(candidate)
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    if isinstance(outputs.get("indicators"), list):
        return outputs
    raise MetricDiscoveryContractError(
        "The metric workflow did not return metric_pack JSON."
    )


def _parse_indicator(item: Any, index: int) -> MetricIndicator:
    if not isinstance(item, dict):
        raise MetricDiscoveryContractError(
            f"Indicator {index} must be an object."
        )
    title = _as_text(item.get("title") or item.get("indicator_name"))
    target_basis = _as_text(
        item.get("target_basis")
        or item.get("rationale")
        or item.get("applicability")
    )
    objective = _as_text(
        item.get("analysis_objective")
        or item.get("objective")
        or item.get("verification_question")
    )
    method = _string_tuple(
        item.get("analysis_method")
        or item.get("method_steps")
        or item.get("method")
    )
    requirements = item.get("data_requirements") or item.get("datasets") or []
    guidance = _as_text(
        item.get("client_request_guidance")
        or item.get("request_guidance")
        or item.get("recommended_request_wording")
    )
    missing = []
    if not title:
        missing.append("title")
    if not target_basis:
        missing.append("target_basis")
    if not objective:
        missing.append("analysis_objective")
    if not method:
        missing.append("analysis_method")
    if not isinstance(requirements, list) or not requirements:
        missing.append("data_requirements")
    if not guidance:
        missing.append("client_request_guidance")
    if missing:
        raise MetricDiscoveryContractError(
            f"Indicator {index} is not data-based; missing "
            + ", ".join(missing)
            + "."
        )

    normalized_requirements = tuple(
        _parse_data_requirement(requirement, index, req_index)
        for req_index, requirement in enumerate(requirements, start=1)
    )
    return MetricIndicator(
        indicator_id=_as_text(item.get("indicator_id") or f"M{index:02d}"),
        title=title,
        category=_as_text(item.get("category") or "综合分析"),
        priority=_as_text(item.get("priority") or "中"),
        target_basis=target_basis,
        analysis_objective=objective,
        definition=_as_text(item.get("definition")),
        formula=_as_text(item.get("formula") or item.get("calculation")),
        analysis_grain=_as_text(
            item.get("analysis_grain") or item.get("grain")
        ),
        dimensions=_string_tuple(item.get("dimensions")),
        analysis_method=method,
        data_requirements=normalized_requirements,
        client_request_guidance=guidance,
        key_scope_questions=_string_tuple(
            item.get("key_scope_questions")
            or item.get("scope_questions")
        ),
        potential_anomalies=_string_tuple(
            item.get("potential_anomalies")
            or item.get("anomalies")
        ),
        data_acquisition_difficulty=_as_text(
            item.get("data_acquisition_difficulty")
            or item.get("difficulty")
            or "待评估"
        ),
        evidence_basis=_string_tuple(
            item.get("evidence_basis") or item.get("sources")
        ),
        assumptions=_string_tuple(item.get("assumptions")),
    )


def _parse_data_requirement(
    item: Any,
    indicator_index: int,
    requirement_index: int,
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise MetricDiscoveryContractError(
            f"Indicator {indicator_index} data requirement "
            f"{requirement_index} must be an object."
        )
    dataset_name = _as_text(
        item.get("dataset_name")
        or item.get("name")
        or item.get("table_name")
    )
    grain = _as_text(item.get("grain") or item.get("data_grain"))
    required_fields = _string_tuple(
        item.get("required_fields") or item.get("fields")
    )
    missing = []
    if not dataset_name:
        missing.append("dataset_name")
    if not grain:
        missing.append("grain")
    if not required_fields:
        missing.append("required_fields")
    if missing:
        raise MetricDiscoveryContractError(
            f"Indicator {indicator_index} data requirement "
            f"{requirement_index} is incomplete; missing "
            + ", ".join(missing)
            + "."
        )
    normalized = dict(item)
    normalized["dataset_name"] = dataset_name
    normalized["grain"] = grain
    normalized["required_fields"] = list(required_fields)
    normalized["join_keys"] = list(
        _string_tuple(item.get("join_keys") or item.get("keys"))
    )
    return normalized


def _contains_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_contains_meaningful_value(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_meaningful_value(item) for item in value)
    if isinstance(value, bool):
        return value
    return True


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ()
        parts = [
            re.sub(r"^\s*(?:[-*•]|\d+[.)、])\s*", "", line).strip()
            for line in stripped.splitlines()
        ]
        return tuple(part for part in parts if part)
    if isinstance(value, (list, tuple, set)):
        return tuple(
            text
            for item in value
            if (text := _as_text(item))
        )
    text = _as_text(value)
    return (text,) if text else ()


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _strip_json_fence(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and lines[0].lstrip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()
