"""Dify generation, strict validation, sample preflight, and local execution."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from config.settings import settings
from core.analysis_contract import (
    AnalysisContractError,
    AnalysisPlanValidator,
    GeneratedCodeContractValidator,
)
from core.code_validator import CodeValidator, SecurityError
from core.executor import ExecutionResult, Executor
from core.preprocessor import FileMeta
from core.prompt_builder import PromptBuilder
from llm import LLMError, get_client
from llm.cancellation import CancellationToken

WorkflowEvent = dict[str, object]
EventCallback = Callable[[WorkflowEvent], None]


@dataclass
class WorkflowResult:
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
    analysis_plan: dict[str, Any] | None = None
    preflight_only: bool = False


class JsonContractError(Exception):
    pass


class AnalysisWorkflow:
    def __init__(
        self,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        self._cancellation_token = cancellation_token or CancellationToken()
        self._client = get_client(cancellation_token=self._cancellation_token)
        self._validator = CodeValidator()
        self._plan_validator = AnalysisPlanValidator()
        self._code_contract = GeneratedCodeContractValidator()
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
        return self.execute_with_repair(
            generated.code,
            files_meta,
            user_query,
            analysis_plan=generated.analysis_plan,
            sample=False,
        )

    def prepare_analysis(
        self,
        files_meta: list[FileMeta],
        user_query: str,
        event_callback: EventCallback | None = None,
    ) -> WorkflowResult:
        generated = self.generate_only(
            files_meta,
            user_query,
            event_callback=event_callback,
        )
        if generated.needs_clarification:
            return generated
        if not generated.success and not generated.code:
            return generated
        preflight = self.execute_with_repair(
            generated.code,
            files_meta,
            user_query,
            analysis_plan=generated.analysis_plan,
            event_callback=event_callback,
            sample=True,
        )
        preflight.preflight_only = True
        return preflight

    def overview_only(
        self,
        file_meta: FileMeta,
        event_callback: EventCallback | None = None,
    ) -> WorkflowResult:
        try:
            self._emit(event_callback, "status", "Preparing dataset overview")
            raw = self._client.generate_code(
                self._prompt_builder.build_dataset_overview_prompt(file_meta),
                event_callback=event_callback,
            )
            overview = self._parse_overview(raw, file_meta)
            self._emit(event_callback, "status", "Dataset overview is ready")
            return WorkflowResult(True, "", None, overview_result=overview)
        except Exception as exc:
            return WorkflowResult(False, "", None, error=str(exc))

    def generate_only(
        self,
        files_meta: list[FileMeta],
        user_query: str,
        event_callback: EventCallback | None = None,
    ) -> WorkflowResult:
        code = ""
        plan: dict[str, Any] = {}
        try:
            self._emit(event_callback, "status", "Preparing analysis request")
            prompt = self._prompt_builder.build_analysis_prompt(
                files_meta,
                user_query,
            )
            if hasattr(self._client, "generate_analysis"):
                generated = self._client.generate_analysis(
                    prompt,
                    event_callback=event_callback,
                )
                plan = generated.get("plan") or {}
                if generated.get("clarification_required"):
                    return WorkflowResult(
                        success=False,
                        code="",
                        execution=None,
                        analysis_plan=plan,
                        needs_clarification=True,
                        clarification_question=str(
                            generated.get("clarification_question") or ""
                        ),
                        clarification_options=[
                            item
                            for item in generated.get(
                                "clarification_options",
                                [],
                            )
                            if isinstance(item, dict)
                        ],
                    )
                code = str(generated.get("code") or "")
            else:
                code = self._client.generate_code(
                    prompt,
                    event_callback=event_callback,
                )

            self._emit(event_callback, "status", "Validating generated code")
            safety = self._validator.validate(code)
            safety.raise_if_unsafe()
            self._emit(event_callback, "status", "Validating analysis plan")
            self._plan_validator.validate(plan, files_meta).raise_if_invalid()
            self._code_contract.validate(
                code,
                files_meta,
                plan,
            ).raise_if_invalid()
            self._emit(event_callback, "status", "Code is ready for preflight")
            return WorkflowResult(
                True,
                code,
                None,
                analysis_plan=plan,
                validation_result={"is_safe": True, "violations": []},
            )
        except AnalysisContractError as exc:
            return WorkflowResult(
                False,
                code,
                None,
                error=f"Analysis contract validation failed: {exc}",
                analysis_plan=plan,
            )
        except SecurityError as exc:
            return WorkflowResult(
                False,
                code,
                None,
                error=f"Security validation failed: {exc}",
                analysis_plan=plan,
            )
        except LLMError as exc:
            return WorkflowResult(
                False,
                "",
                None,
                error=f"LLM API error: {exc}",
                analysis_plan=plan,
            )

    def execute_only(
        self,
        code: str,
        files_meta: list[FileMeta],
        event_callback: EventCallback | None = None,
        *,
        analysis_plan: dict[str, Any] | None = None,
        sample: bool = False,
    ) -> WorkflowResult:
        phase = "sample preflight" if sample else "full local analysis"
        self._emit(event_callback, "status", f"Executing {phase}")
        try:
            safety = self._validator.validate(code)
            safety.raise_if_unsafe()
            self._plan_validator.validate(
                analysis_plan,
                files_meta,
            ).raise_if_invalid()
            self._code_contract.validate(
                code,
                files_meta,
                analysis_plan or {},
            ).raise_if_invalid()
        except (AnalysisContractError, SecurityError) as exc:
            return WorkflowResult(
                False,
                code,
                None,
                error=str(exc),
                analysis_plan=analysis_plan or {},
                preflight_only=sample,
            )

        execution = self._executor.run(
            code,
            files_meta,
            sample=sample,
            analysis_plan=analysis_plan,
        )
        self._emit(
            event_callback,
            "execution_output" if execution.success else "execution_error",
            "Preflight finished" if sample else "Execution finished",
            delta=execution.stdout if execution.success else execution.stderr,
            section="execution",
        )
        return WorkflowResult(
            execution.success,
            code,
            execution,
            error="" if execution.success else execution.stderr,
            analysis_plan=analysis_plan or {},
            preflight_only=sample,
        )

    def execute_with_repair(
        self,
        code: str,
        files_meta: list[FileMeta],
        user_query: str,
        analysis_plan: dict[str, Any] | None = None,
        event_callback: EventCallback | None = None,
        *,
        sample: bool = False,
    ) -> WorkflowResult:
        current_code = code
        last_result: WorkflowResult | None = None
        for attempt in range(self._max_retries + 1):
            self._cancellation_token.raise_if_cancelled()
            last_result = self.execute_only(
                current_code,
                files_meta,
                event_callback=event_callback,
                analysis_plan=analysis_plan,
                sample=sample,
            )
            last_result.retries_used = attempt
            if last_result.success:
                self._emit(
                    event_callback,
                    "status",
                    (
                        "Corrected code passed sample preflight"
                        if attempt and sample
                        else "Code passed sample preflight"
                        if sample
                        else "Full analysis completed"
                    ),
                )
                return last_result
            if attempt >= self._max_retries:
                break

            repair_number = attempt + 1
            self._emit(
                event_callback,
                "status",
                f"Requesting code correction ({repair_number}/{self._max_retries})",
            )
            try:
                repair_prompt = self._prompt_builder.build_repair_prompt(
                    files_meta,
                    user_query,
                    current_code,
                    last_result.error,
                    analysis_plan,
                    repair_number,
                )
                if hasattr(self._client, "generate_analysis"):
                    repaired = self._client.generate_analysis(
                        repair_prompt,
                        event_callback=event_callback,
                    )
                    current_code = str(repaired.get("code") or "")
                else:
                    current_code = self._client.generate_code(
                        repair_prompt,
                        event_callback=event_callback,
                    )
                self._validate_code(
                    current_code,
                    files_meta,
                    analysis_plan or {},
                )
            except (LLMError, SecurityError, AnalysisContractError) as exc:
                return WorkflowResult(
                    False,
                    current_code,
                    last_result.execution,
                    error=f"Automatic code correction failed: {exc}",
                    retries_used=repair_number,
                    analysis_plan=analysis_plan or {},
                    preflight_only=sample,
                )

        assert last_result is not None
        last_result.code = current_code
        last_result.error = (
            f"Code failed after {self._max_retries} correction attempt(s).\n"
            f"{last_result.error}"
        )
        return last_result

    def _validate_code(
        self,
        code: str,
        files_meta: list[FileMeta],
        plan: dict[str, Any],
    ) -> None:
        safety = self._validator.validate(code)
        safety.raise_if_unsafe()
        contract = self._code_contract.validate(code, files_meta, plan)
        contract.raise_if_invalid()

    @staticmethod
    def _parse_overview(
        raw_text: str,
        file_meta: FileMeta,
    ) -> dict[str, Any]:
        cleaned = raw_text.strip()
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise JsonContractError("Dataset overview did not return JSON")
        payload = json.loads(cleaned[start : end + 1])
        suggestions = payload.get("suggestions") or []
        first_sheet = file_meta.sheets[0] if file_meta.sheets else None

        def integer(value: Any, fallback: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return fallback

        return {
            "dataset_kind": str(payload.get("dataset_kind") or "Dataset"),
            "topic": str(payload.get("topic") or "Business data"),
            "summary": str(payload.get("summary") or "No summary returned."),
            "rows": integer(
                payload.get("rows"),
                first_sheet.rows if first_sheet else 0,
            ),
            "columns": integer(
                payload.get("columns"),
                first_sheet.cols if first_sheet else 0,
            ),
            "sheet_count": integer(
                payload.get("sheet_count"),
                file_meta.sheet_count,
            ),
            "suggestions": [
                str(item).strip()
                for item in suggestions
                if str(item).strip()
            ][:4],
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
