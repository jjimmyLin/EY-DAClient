"""
dify/workflow.py
────────────────
Analysis workflow orchestration.
LLM code generation → Python safety validation → local Python execution.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from config.settings import settings
from core.code_validator import CodeValidator, SecurityError
from core.executor import ExecutionResult, Executor
from core.preprocessor import FileMeta
from core.prompt_builder import PromptBuilder
from llm import LLMError, get_client

WorkflowEvent = dict[str, object]
EventCallback = Callable[[WorkflowEvent], None]


@dataclass
class WorkflowResult:
    """Workflow result."""

    success: bool
    code: str
    execution: ExecutionResult | None
    error: str = ""
    retries_used: int = 0
    intent_result: dict[str, Any] | None = None
    validation_result: dict[str, Any] | None = None
    code_verification: dict[str, Any] | None = None
    needs_clarification: bool = False
    clarification_question: str = ""
    clarification_options: list[dict[str, Any]] = field(default_factory=list)
    overview_result: dict[str, Any] | None = None


class JsonContractError(Exception):
    """Raised when an LLM JSON response cannot be parsed or validated."""


class AnalysisWorkflow:
    """Data-analysis workflow."""

    def __init__(self) -> None:
        self._client = get_client()
        self._validator = CodeValidator()
        self._executor = Executor()
        self._prompt_builder = PromptBuilder()
        self._max_retries = settings.MAX_CODE_RETRIES

    def run(
        self,
        files_meta: list[FileMeta],
        user_query: str,
    ) -> WorkflowResult:
        generated = self.generate_only(files_meta, user_query)
        if not generated.success:
            return generated
        return self.execute_only(generated.code, files_meta)

    def overview_only(
        self,
        file_meta: FileMeta,
        event_callback: EventCallback | None = None,
    ) -> WorkflowResult:
        """Generate a lightweight overview for one uploaded dataset."""
        fallback = self._fallback_overview(file_meta)
        try:
            self._emit(event_callback, "status", "Preparing dataset overview")
            raw = self._call_llm(
                self._prompt_builder.build_dataset_overview_prompt(file_meta),
                event_callback=event_callback,
            )
            overview = self._parse_overview(raw, file_meta)
            self._emit(event_callback, "status", "Dataset overview is ready")
            return WorkflowResult(
                success=True,
                code="",
                execution=None,
                overview_result=overview,
            )
        except Exception as exc:
            fallback["summary"] = (
                f"{fallback['summary']} AI overview is temporarily unavailable."
            )
            return WorkflowResult(
                success=True,
                code="",
                execution=None,
                error=str(exc),
                overview_result=fallback,
            )

    def generate_only(
        self,
        files_meta: list[FileMeta],
        user_query: str,
        event_callback: EventCallback | None = None,
    ) -> WorkflowResult:
        """Generate Python code for the current dataset and query."""
        try:
            self._emit(event_callback, "status", "Preparing analysis request")
            code = self._call_llm(
                self._prompt_builder.build_analysis_prompt(files_meta, user_query),
                event_callback=event_callback,
            )

            self._emit(event_callback, "status", "Validating generated code safety")
            validation_result = self._validator.validate(code)
            validation_result.raise_if_unsafe()

            self._emit(event_callback, "content_delta", "Generated Python code", delta=code, section="code")
            self._emit(event_callback, "status", "Code is ready for review")
            return WorkflowResult(
                success=True,
                code=code,
                execution=None,
                validation_result={"is_safe": validation_result.is_safe, "violations": validation_result.violations},
            )

        except SecurityError as e:
            return WorkflowResult(
                success=False,
                code="",
                execution=None,
                error=f"❌ 安全检查失败: {str(e)}",
            )
        except LLMError as e:
            return WorkflowResult(
                success=False,
                code="",
                execution=None,
                error=f"❌ LLM API 错误: {str(e)}",
            )

    def execute_only(
        self,
        code: str,
        files_meta: list[FileMeta],
        event_callback: EventCallback | None = None,
    ) -> WorkflowResult:
        """Execute approved code."""
        self._emit(event_callback, "status", "Executing approved code")
        result = self._executor.run(code, files_meta)
        self._emit(
            event_callback,
            "execution_output" if result.success else "execution_error",
            "Execution finished" if result.success else "Execution failed",
            delta=result.stdout if result.success else result.stderr,
            section="execution",
        )
        return WorkflowResult(
            success=result.success,
            code=code,
            execution=result,
            error="" if result.success else (result.stderr or "执行失败"),
        )

    def _call_llm(
        self,
        prompt: dict,
        event_callback: EventCallback | None = None,
    ) -> str:
        return self._client.generate_code(prompt, event_callback=event_callback)

    @staticmethod
    def _parse_overview(raw_text: str, file_meta: FileMeta) -> dict[str, Any]:
        cleaned = raw_text.strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise JsonContractError("Dataset overview did not return JSON")

        payload = json.loads(cleaned[start : end + 1])
        suggestions = payload.get("suggestions") or []
        if not isinstance(suggestions, list):
            suggestions = []

        first_sheet = file_meta.sheets[0] if file_meta.sheets else None
        return {
            "dataset_kind": str(payload.get("dataset_kind") or "Dataset"),
            "topic": str(payload.get("topic") or "General business data"),
            "summary": str(payload.get("summary") or "No overview summary returned."),
            "rows": int(payload.get("rows") or (first_sheet.rows if first_sheet else 0)),
            "columns": int(payload.get("columns") or (first_sheet.cols if first_sheet else 0)),
            "sheet_count": int(payload.get("sheet_count") or file_meta.sheet_count),
            "suggestions": [str(item).strip() for item in suggestions if str(item).strip()][:4],
        }

    @staticmethod
    def _fallback_overview(file_meta: FileMeta) -> dict[str, Any]:
        first_sheet = file_meta.sheets[0] if file_meta.sheets else None
        row_count = first_sheet.rows if first_sheet else 0
        col_count = first_sheet.cols if first_sheet else 0
        columns = first_sheet.columns if first_sheet else []
        numeric = []
        text_like = []
        for sheet in file_meta.sheets:
            for name, dtype in sheet.dtypes.items():
                if dtype.startswith(("int", "float")) and name not in numeric:
                    numeric.append(name)
                elif name not in text_like:
                    text_like.append(name)
        metric = numeric[0] if numeric else "the main metric"
        dimension = text_like[0] if text_like else "a category field"

        suggestions = [
            f"Summarize the main patterns in {metric}.",
            f"Compare {metric} across {dimension}.",
            "Check for missing values and unusual records.",
            "Highlight the most important trends or outliers.",
        ]

        return {
            "dataset_kind": "Spreadsheet dataset",
            "topic": f"This file appears to cover {', '.join(columns[:3]) or 'business records'}.",
            "summary": (
                f"{file_meta.file_name} contains {row_count} rows and {col_count} columns"
                f" across {file_meta.sheet_count} sheet(s)."
            ),
            "rows": row_count,
            "columns": col_count,
            "sheet_count": file_meta.sheet_count,
            "suggestions": suggestions,
        }

    @staticmethod
    def _emit(
        event_callback: EventCallback | None,
        event_type: str,
        message: str,
        **extra: object,
    ) -> None:
        if event_callback is None:
            return
        event: WorkflowEvent = {"type": event_type, "message": message}
        event.update(extra)
        event_callback(event)
