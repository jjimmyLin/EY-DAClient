"""Privacy-bounded payload construction for reusable analysis experience."""

from __future__ import annotations

import getpass
import hashlib
import json
import platform
import re
import uuid
from collections.abc import Iterable
from typing import Any

from config.settings import settings
from core.analysis_result import AnalysisResult
from core.preprocessor import FileMeta, Preprocessor


SCHEMA_VERSION = "1.0"
POLICY_VERSION = "experience-policy-v1"
FORBIDDEN_KEYS = {
    "raw_data",
    "raw_rows",
    "sample_rows",
    "data_preview",
    "full_code",
    "generated_code",
    "python_code",
    "stdout",
    "stderr",
    "local_path",
    "absolute_path",
    "file_path",
    "api_key",
    "authorization",
    "password",
    "secret",
    "chain_of_thought",
}

_WINDOWS_PATH = re.compile(r"(?i)\b[a-z]:\\(?:[^\\\r\n]+\\)*[^\\\r\n]*")
_POSIX_USER_PATH = re.compile(r"(?i)(?:/users|/home)/[^/\s]+(?:/[^\s]*)?")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_ -]?key|authorization|password|secret|token)\b"
    r"\s*[:=]\s*[^\s,;]+"
)
_LONG_TOKEN = re.compile(r"\b[A-Za-z0-9_-]{40,}\b")
_RESULT_NUMBER = re.compile(
    r"(?<![A-Za-z])(?:[$¥€£]\s*)?-?\d[\d,]*(?:\.\d+)?%?"
)


class ExperiencePayloadError(ValueError):
    """The local session cannot be shared under the experience policy."""


def new_analysis_session_id() -> str:
    return f"session_{uuid.uuid4().hex}"


def new_analysis_run_id() -> str:
    return f"run_{uuid.uuid4().hex}"


def build_experience_payload(
    *,
    analysis_session_id: str,
    analysis_run_id: str,
    files_meta: list[FileMeta],
    user_query: str,
    analysis_plan: dict[str, Any],
    analysis_result: AnalysisResult,
    repair_count: int = 0,
    manual_edit: bool = False,
) -> dict[str, Any]:
    """Build the only payload shape permitted to leave the desktop client."""
    if not files_meta:
        raise ExperiencePayloadError("Experience extraction requires dataset metadata.")
    if not user_query.strip():
        raise ExperiencePayloadError("Experience extraction requires a user request.")

    original_query, clarifications = _split_query(user_query)
    dataset_payloads = [_dataset_schema_payload(meta) for meta in files_meta]
    content_hashes = sorted(item["content_hash"] for item in dataset_payloads)
    schema_families = sorted(item["schema_family_id"] for item in dataset_payloads)
    aggregate_schemas = _merge_schemas(dataset_payloads)
    public_datasets = [
        {
            key: value
            for key, value in dataset.items()
            if key != "schemas"
        }
        for dataset in dataset_payloads
    ]

    payload = {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "analysis_session_id": _bounded_text(analysis_session_id, 160),
        "analysis_run_id": _bounded_text(analysis_run_id, 160),
        "actor": {
            "tenant_id": _bounded_text(settings.EXPERIENCE_TENANT_ID, 160),
            "project_id": _bounded_text(settings.EXPERIENCE_PROJECT_ID, 160),
            "user_id": _pseudonymous_user_id(),
        },
        "dataset": {
            "content_hash": _aggregate_identity(content_hashes, "content"),
            "schema_family_id": _aggregate_identity(schema_families, "schema"),
            "dataset_count": len(dataset_payloads),
            "datasets": public_datasets,
            "schemas": aggregate_schemas,
            "sheet_groups": [
                group
                for dataset in dataset_payloads
                for group in dataset["sheet_groups"]
            ],
            "field_roles": _merge_field_roles(dataset_payloads),
        },
        "request": {
            "original_query": _bounded_text(_redact_text(original_query), 8000),
            "clarifications": [
                _bounded_text(_redact_text(item), 2000)
                for item in clarifications[:8]
            ],
            "confirmed_intent": _bounded_text(
                _redact_text(
                    str(
                        analysis_plan.get("task_summary")
                        or analysis_plan.get("summary")
                        or original_query
                    )
                ),
                4000,
            ),
        },
        "plan": _plan_payload(analysis_plan),
        "execution": {
            "success": True,
            "semantic_audit_passed": True,
            "repair_count": max(0, int(repair_count)),
            "repair_summaries": [],
            "audit_operations": _audit_payload(analysis_result.audit),
            "manual_edit": bool(manual_edit),
        },
        "result": {
            "summary_redacted": _bounded_text(
                _redact_result_text(analysis_result.summary),
                3000,
            ),
            "output_kinds": _output_kinds(analysis_result),
            "completed_requirement_ids": [
                _bounded_text(item, 160)
                for item in analysis_result.completed_requirements[:100]
            ],
        },
        "versions": {
            "app_version": _bounded_text(settings.APP_VERSION, 80),
            "analysis_workflow_version": _bounded_text(
                settings.ANALYSIS_WORKFLOW_VERSION,
                120,
            ),
        },
        "payload_compaction": "none",
        "consent_to_extract": True,
    }

    _assert_policy_safe(payload)
    encoded = _encode(payload)
    if len(encoded) > settings.EXPERIENCE_MAX_PAYLOAD_CHARS:
        _compact_payload(payload)
        _assert_policy_safe(payload)
        encoded = _encode(payload)
    if len(encoded) > settings.EXPERIENCE_MAX_PAYLOAD_CHARS:
        _minimize_payload(payload)
        _assert_policy_safe(payload)
        encoded = _encode(payload)
    if len(encoded) > settings.EXPERIENCE_MAX_PAYLOAD_CHARS:
        raise ExperiencePayloadError(
            "Sanitized experience payload exceeds the configured size limit."
        )
    return payload


def _dataset_schema_payload(file_meta: FileMeta) -> dict[str, Any]:
    content_hash = file_meta.content_hash or _fallback_content_hash(file_meta)
    schema_family_id = (
        file_meta.schema_family_id
        or Preprocessor.schema_family_id(file_meta.sheets)
    )
    return {
        "content_hash": content_hash,
        "schema_family_id": schema_family_id,
        "profile_mode": str(file_meta.profile_mode or "unknown"),
        "sheet_count": int(file_meta.sheet_count),
        "schemas": _unique_schema_payloads(file_meta),
        "sheet_groups": [
            {
                "type": str(group.group_type),
                "sheet_count": len(group.sheet_ids),
                "columns": [_bounded_text(column, 240) for column in group.columns],
                "confidence": float(group.confidence),
            }
            for group in file_meta.sheet_groups
        ],
        "field_roles": _file_field_roles(file_meta),
    }


def _unique_schema_payloads(file_meta: FileMeta) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for sheet in file_meta.sheets:
        columns = [
            {
                "name": _bounded_text(column, 240),
                "type": Preprocessor._dtype_family(sheet.dtypes.get(column, "")),
                "roles": sorted(
                    role
                    for role, role_columns in sheet.semantic_roles.items()
                    if column in role_columns
                ),
            }
            for column in sheet.columns
        ]
        signature = json.dumps(
            columns,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        unique.setdefault(
            signature,
            {
                "columns": columns,
                "sheet_count": 0,
            },
        )
        unique[signature]["sheet_count"] += 1
    return list(unique.values())


def _file_field_roles(file_meta: FileMeta) -> dict[str, list[str]]:
    roles: dict[str, set[str]] = {}
    for sheet in file_meta.sheets:
        for role, columns in sheet.semantic_roles.items():
            roles.setdefault(str(role), set()).update(str(column) for column in columns)
    return {
        role: sorted(_bounded_text(column, 240) for column in columns)
        for role, columns in sorted(roles.items())
    }


def _merge_field_roles(
    datasets: list[dict[str, Any]],
) -> dict[str, list[str]]:
    merged: dict[str, set[str]] = {}
    for dataset in datasets:
        for role, columns in dataset["field_roles"].items():
            merged.setdefault(role, set()).update(columns)
    return {role: sorted(columns) for role, columns in sorted(merged.items())}


def _merge_schemas(
    datasets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for dataset in datasets:
        for schema in dataset["schemas"]:
            signature = json.dumps(
                schema["columns"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if signature not in unique:
                unique[signature] = {
                    "columns": schema["columns"],
                    "sheet_count": 0,
                }
            unique[signature]["sheet_count"] += int(schema["sheet_count"])
    return list(unique.values())


def _plan_payload(plan: dict[str, Any]) -> dict[str, Any]:
    requirements = []
    for index, item in enumerate(plan.get("requirements") or [], start=1):
        if not isinstance(item, dict):
            requirements.append(
                {
                    "id": f"R{index}",
                    "objective": _bounded_text(_redact_text(str(item)), 2000),
                }
            )
            continue
        requirements.append(
            {
                "id": _bounded_text(str(item.get("id") or f"R{index}"), 160),
                "objective": _bounded_text(
                    _redact_text(
                        str(item.get("objective") or item.get("description") or "")
                    ),
                    2000,
                ),
                "grain": _bounded_text(_redact_text(str(item.get("grain") or "")), 600),
                "formula": _bounded_text(
                    _redact_text(str(item.get("formula") or "")),
                    1600,
                ),
                "output_type": _bounded_text(str(item.get("output_type") or ""), 120),
                "source_columns": sorted(
                    {
                        _bounded_text(str(column), 240)
                        for source in item.get("sources") or []
                        if isinstance(source, dict)
                        for column in source.get("columns") or []
                    }
                ),
                "joins": _join_payload(item.get("joins") or []),
                "combines": _combine_payload(item.get("combines") or []),
            }
        )
    return {
        "requirements": requirements,
        "method_summary": _bounded_text(
            _redact_text(
                str(plan.get("task_summary") or plan.get("summary") or "")
            ),
            4000,
        ),
        "expected_outputs": sorted(
            {
                item["output_type"]
                for item in requirements
                if item.get("output_type")
            }
        ),
    }


def _join_payload(joins: Iterable[Any]) -> list[dict[str, Any]]:
    result = []
    for join in joins:
        if not isinstance(join, dict):
            continue
        left = join.get("left") if isinstance(join.get("left"), dict) else {}
        right = join.get("right") if isinstance(join.get("right"), dict) else {}
        result.append(
            {
                "how": _bounded_text(str(join.get("how") or "inner"), 60),
                "left_column": _bounded_text(str(left.get("column") or ""), 240),
                "right_column": _bounded_text(str(right.get("column") or ""), 240),
                "expected_relationship": _bounded_text(
                    str(join.get("expected_relationship") or ""),
                    80,
                ),
                "many_to_many_confirmed": bool(
                    join.get("many_to_many_confirmed")
                ),
            }
        )
    return result


def _combine_payload(combines: Iterable[Any]) -> list[dict[str, Any]]:
    result = []
    for combine in combines:
        if not isinstance(combine, dict):
            continue
        result.append(
            {
                "type": _bounded_text(str(combine.get("type") or ""), 80),
                "columns": [
                    _bounded_text(str(column), 240)
                    for column in (combine.get("columns") or [])
                ],
                "sheet_count": len(combine.get("sheet_ids") or []),
            }
        )
    return result


def _audit_payload(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    operations = []
    for record in records:
        if not isinstance(record, dict):
            continue
        kind = str(record.get("kind") or "").lower()
        if kind == "load":
            operations.append(
                {
                    "kind": "load",
                    "sampled": bool(record.get("sampled")),
                    "columns": [
                        _bounded_text(str(column), 240)
                        for column in (record.get("columns") or [])
                    ],
                    "guarded": bool(record.get("guarded")),
                }
            )
        elif kind == "sql":
            operations.append(
                {
                    "kind": "sql",
                    "sampled": bool(record.get("sampled")),
                    "truncated": bool(record.get("truncated")),
                }
            )
        elif kind == "join":
            operations.append(
                {
                    "kind": "join",
                    "how": _bounded_text(str(record.get("how") or ""), 60),
                    "left_on": _safe_scalar_or_list(record.get("left_on")),
                    "right_on": _safe_scalar_or_list(record.get("right_on")),
                    "relationship": _bounded_text(
                        str(record.get("relationship") or ""),
                        80,
                    ),
                    "row_multiplier": _safe_float(record.get("row_multiplier")),
                }
            )
        elif kind == "union":
            operations.append(
                {
                    "kind": "union",
                    "sheet_count": len(record.get("sheet_ids") or []),
                    "columns": [
                        _bounded_text(str(column), 240)
                        for column in (record.get("columns") or [])
                    ],
                    "sampled": bool(record.get("sampled")),
                    "truncated": bool(record.get("truncated")),
                    "guarded": bool(record.get("guarded")),
                }
            )
        elif kind == "runtime":
            operations.append(
                {
                    "kind": "runtime",
                    "sampled": bool(record.get("sampled")),
                }
            )
    return operations[:200]


def _output_kinds(result: AnalysisResult) -> list[str]:
    kinds = []
    for name, values in (
        ("answer", result.answers),
        ("metric", result.metrics),
        ("table", result.tables),
        ("chart", result.charts),
        ("insight", result.insights),
    ):
        if values:
            kinds.append(name)
    return kinds


def _split_query(query: str) -> tuple[str, list[str]]:
    parts = re.split(r"\n\s*\nUser clarification:\s*", query, flags=re.I)
    return parts[0].strip(), [item.strip() for item in parts[1:] if item.strip()]


def _redact_text(value: str) -> str:
    text = str(value or "")
    text = _WINDOWS_PATH.sub("[local path]", text)
    text = _POSIX_USER_PATH.sub("[local path]", text)
    text = _EMAIL.sub("[email]", text)
    text = _SECRET_ASSIGNMENT.sub(r"\1=[redacted]", text)
    return _LONG_TOKEN.sub("[token]", text).strip()


def _redact_result_text(value: str) -> str:
    return _RESULT_NUMBER.sub("[number]", _redact_text(value))


def _pseudonymous_user_id() -> str:
    configured = str(settings.EXPERIENCE_USER_ID or "").strip()
    if configured:
        return _bounded_text(configured, 160)
    identity = (
        f"{getpass.getuser()}@{platform.node()}|"
        f"{settings.EXPERIENCE_TENANT_ID}|{settings.EXPERIENCE_PROJECT_ID}"
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return f"local_{digest}"


def _fallback_content_hash(file_meta: FileMeta) -> str:
    schema = Preprocessor.schema_family_id(file_meta.sheets)
    payload = f"{schema}|{file_meta.file_size_kb}|{file_meta.sheet_count}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _aggregate_identity(values: list[str], namespace: str) -> str:
    if len(values) == 1:
        return values[0]
    canonical = json.dumps(values, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{namespace}_{digest}"


def _bounded_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _safe_scalar_or_list(value: Any) -> str | list[str]:
    if isinstance(value, (list, tuple)):
        return [_bounded_text(item, 240) for item in value[:20]]
    return _bounded_text(value, 240)


def _safe_float(value: Any) -> float | None:
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _compact_payload(payload: dict[str, Any]) -> None:
    """Drop low-value repetition before rejecting an oversized safe payload."""
    payload["payload_compaction"] = "compact"
    request = payload["request"]
    request["original_query"] = request["original_query"][:5000]
    request["clarifications"] = [
        item[:1200]
        for item in request["clarifications"][:5]
    ]
    request["confirmed_intent"] = request["confirmed_intent"][:2000]

    plan = payload["plan"]
    plan["method_summary"] = plan["method_summary"][:2000]
    for requirement in plan["requirements"][:30]:
        requirement["objective"] = requirement["objective"][:1000]
        requirement["grain"] = requirement["grain"][:300]
        requirement["formula"] = requirement["formula"][:800]
        requirement["source_columns"] = requirement["source_columns"][:80]
        requirement["joins"] = requirement["joins"][:20]
        requirement["combines"] = requirement["combines"][:20]
    plan["requirements"] = plan["requirements"][:30]

    dataset = payload["dataset"]
    dataset["schemas"] = [
        {
            "columns": schema["columns"][:80],
            "sheet_count": schema["sheet_count"],
        }
        for schema in dataset["schemas"][:20]
    ]
    for item in dataset["datasets"]:
        item["sheet_groups"] = item["sheet_groups"][:20]
        for group in item["sheet_groups"]:
            group["columns"] = group["columns"][:80]

    payload["execution"]["audit_operations"] = payload["execution"][
        "audit_operations"
    ][:80]
    payload["result"]["summary_redacted"] = payload["result"][
        "summary_redacted"
    ][:1200]


def _encode(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _minimize_payload(payload: dict[str, Any]) -> None:
    """Preserve intent and semantic roles when unusually wide plans remain large."""
    payload["payload_compaction"] = "minimal"
    payload["request"]["original_query"] = payload["request"][
        "original_query"
    ][:3500]
    payload["request"]["clarifications"] = payload["request"][
        "clarifications"
    ][:3]

    requirements = payload["plan"]["requirements"][:20]
    for requirement in requirements:
        requirement["objective"] = requirement["objective"][:400]
        requirement["formula"] = requirement["formula"][:240]
        requirement["source_columns"] = requirement["source_columns"][:15]
        requirement["joins"] = requirement["joins"][:10]
        requirement["combines"] = requirement["combines"][:10]
    payload["plan"]["requirements"] = requirements
    payload["plan"]["method_summary"] = payload["plan"][
        "method_summary"
    ][:1200]

    dataset = payload["dataset"]
    dataset["schemas"] = [
        {
            "columns": [
                {
                    "name": column["name"],
                    "type": column["type"],
                    "roles": column["roles"],
                }
                for column in schema["columns"][:30]
            ],
            "sheet_count": schema["sheet_count"],
        }
        for schema in dataset["schemas"][:8]
    ]
    dataset["field_roles"] = {
        role: columns[:50]
        for role, columns in dataset["field_roles"].items()
    }
    for item in dataset["datasets"]:
        item.pop("sheet_groups", None)
        item.pop("field_roles", None)

    payload["execution"]["audit_operations"] = payload["execution"][
        "audit_operations"
    ][:30]
    payload["result"]["summary_redacted"] = payload["result"][
        "summary_redacted"
    ][:600]


def _assert_policy_safe(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in FORBIDDEN_KEYS:
                location = ".".join((*path, str(key)))
                raise ExperiencePayloadError(
                    f"Experience payload contains forbidden field: {location}"
                )
            _assert_policy_safe(item, (*path, str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_policy_safe(item, (*path, str(index)))
