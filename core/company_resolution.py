"""Contracts for deterministic company-entity resolution."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


COMPANY_RESOLUTION_SCHEMA_VERSION = "company_resolution.result.v1"


class CompanyResolutionContractError(ValueError):
    """Raised when the company-resolution workflow returns invalid data."""


@dataclass(frozen=True)
class CompanyCandidate:
    """One user-selectable legal entity returned by the lookup workflow."""

    company_name: str
    company_id: str = ""
    credit_code: str = ""
    status: str = ""
    legal_representative: str = ""
    established_date: str = ""

    @classmethod
    def from_payload(cls, payload: Any) -> "CompanyCandidate":
        if not isinstance(payload, dict):
            raise CompanyResolutionContractError(
                "A company candidate must be an object."
            )
        company_name = _as_text(payload.get("company_name"))
        if not company_name:
            raise CompanyResolutionContractError(
                "A company candidate is missing company_name."
            )
        return cls(
            company_name=company_name,
            company_id=_as_text(payload.get("company_id")),
            credit_code=_as_text(payload.get("credit_code")).upper(),
            status=_as_text(payload.get("status")),
            legal_representative=_as_text(
                payload.get("legal_representative")
            ),
            established_date=_as_text(payload.get("established_date")),
        )

    def to_payload(self) -> dict[str, str]:
        return {
            "company_name": self.company_name,
            "company_id": self.company_id,
            "credit_code": self.credit_code,
            "status": self.status,
            "legal_representative": self.legal_representative,
            "established_date": self.established_date,
        }


@dataclass(frozen=True)
class CompanyResolutionResult:
    """Normalized output from the dedicated company-resolution workflow."""

    resolution_status: str
    requires_selection: bool
    original_query: str
    resolved_company_name: str
    selected_company: CompanyCandidate | None
    candidates: tuple[CompanyCandidate, ...]
    message: str = ""
    query_type: str = ""
    workflow_run_id: str = ""
    raw_outputs: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_workflow_response(
        cls,
        response: dict[str, Any],
    ) -> "CompanyResolutionResult":
        data = response.get("data") or {}
        if not isinstance(data, dict):
            raise CompanyResolutionContractError(
                "The company-resolution workflow response has no data object."
            )
        status = _as_text(data.get("status")).lower()
        if status and status != "succeeded":
            raise CompanyResolutionContractError(
                _as_text(data.get("error"))
                or "The company-resolution workflow failed."
            )
        outputs = data.get("outputs") or {}
        if not isinstance(outputs, dict):
            raise CompanyResolutionContractError(
                "The company-resolution workflow outputs must be an object."
            )
        payload = _extract_payload(outputs)
        schema_version = _as_text(payload.get("schema_version"))
        if (
            schema_version
            and schema_version != COMPANY_RESOLUTION_SCHEMA_VERSION
        ):
            raise CompanyResolutionContractError(
                f"Unsupported company-resolution schema: {schema_version}."
            )

        resolution_status = _as_text(
            payload.get("resolution_status")
        ).lower()
        allowed_statuses = {
            "direct_match",
            "selection_required",
            "not_found",
            "search_error",
        }
        if resolution_status not in allowed_statuses:
            raise CompanyResolutionContractError(
                "The company-resolution workflow returned an unknown status."
            )

        candidates: list[CompanyCandidate] = []
        seen: set[str] = set()
        candidates_raw = payload.get("candidates") or []
        if not isinstance(candidates_raw, list):
            raise CompanyResolutionContractError(
                "Company candidates must be an array."
            )
        for item in candidates_raw:
            candidate = CompanyCandidate.from_payload(item)
            identity = (
                candidate.company_id.casefold()
                if candidate.company_id
                else candidate.company_name.casefold()
            )
            if identity in seen:
                continue
            seen.add(identity)
            candidates.append(candidate)
            if len(candidates) >= 5:
                break

        selected_payload = payload.get("selected_company")
        selected_company = None
        if isinstance(selected_payload, dict) and _as_text(
            selected_payload.get("company_name")
        ):
            selected_company = CompanyCandidate.from_payload(selected_payload)

        resolved_company_name = _as_text(
            payload.get("resolved_company_name")
        )
        requires_selection = bool(payload.get("requires_selection"))
        if resolution_status == "direct_match":
            if not resolved_company_name:
                if selected_company is not None:
                    resolved_company_name = selected_company.company_name
                else:
                    raise CompanyResolutionContractError(
                        "A direct company match has no resolved company name."
                    )
            if selected_company is None:
                selected_company = CompanyCandidate(
                    company_name=resolved_company_name
                )
            requires_selection = False
        elif resolution_status == "selection_required":
            if not candidates:
                raise CompanyResolutionContractError(
                    "Selection is required but no company candidates were returned."
                )
            requires_selection = True
        else:
            requires_selection = False

        return cls(
            resolution_status=resolution_status,
            requires_selection=requires_selection,
            original_query=_as_text(payload.get("original_query")),
            query_type=_as_text(payload.get("query_type")),
            resolved_company_name=resolved_company_name,
            selected_company=selected_company,
            candidates=tuple(candidates),
            message=_as_text(payload.get("message")),
            workflow_run_id=_as_text(
                response.get("workflow_run_id") or data.get("id")
            ),
            raw_outputs=outputs,
        )


def _extract_payload(outputs: dict[str, Any]) -> dict[str, Any]:
    for key in ("company_resolution", "resolution_result", "result"):
        candidate = outputs.get(key)
        if isinstance(candidate, dict):
            return candidate
        if isinstance(candidate, str) and candidate.strip():
            try:
                parsed = json.loads(_strip_json_fence(candidate))
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    if "resolution_status" in outputs:
        return outputs
    raise CompanyResolutionContractError(
        "The workflow did not return company_resolution."
    )


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _strip_json_fence(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and lines[0].lstrip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()
