"""
dify/workflow.py
────────────────
Analysis workflow orchestration.
LLM intent → LLM validation → LLM code → LLM code verification → Python execution.
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

    def generate_only(
        self,
        files_meta: list[FileMeta],
        user_query: str,
        event_callback: EventCallback | None = None,
    ) -> WorkflowResult:
        """Understand intent, validate it, generate code, and verify code."""
        try:
            self._emit(event_callback, "status", "Understanding user intent")
            intent = self._call_json_stage(
                self._prompt_builder.build_intent_prompt(files_meta, user_query),
                required_fields=[
                    "status",
                    "understanding",
                    "requested_entities",
                    "candidate_columns",
                    "uncertainties",
                ],
                stage_name="intent",
            )
            self._emit(
                event_callback,
                "intent_result",
                "Intent understood",
                delta=json.dumps(intent, ensure_ascii=False, indent=2),
            )

            self._emit(event_callback, "status", "Validating intent against data")
            validation = self._call_json_stage(
                self._prompt_builder.build_validation_prompt(
                    files_meta, user_query, intent
                ),
                required_fields=[
                    "status",
                    "evidence",
                    "blocking_issue",
                    "question",
                    "options",
                    "confirmed_intent",
                ],
                stage_name="intent validation",
            )
            self._emit(
                event_callback,
                "validation_result",
                "Intent validation completed",
                delta=json.dumps(validation, ensure_ascii=False, indent=2),
            )

            if validation.get("status") != "ready":
                return self._clarification_result(intent, validation)

            confirmed_intent = validation.get("confirmed_intent")
            if not isinstance(confirmed_intent, dict) or not validation.get("evidence"):
                validation["status"] = "needs_clarification"
                validation["blocking_issue"] = (
                    validation.get("blocking_issue")
                    or "验证结果缺少足够的数据证据，不能安全继续。"
                )
                validation["question"] = (
                    validation.get("question")
                    or "请补充你希望如何分析这份数据。"
                )
                return self._clarification_result(intent, validation)

            self._emit(event_callback, "status", "Generating verified Python code")
            code = self._call_llm(
                self._prompt_builder.build_analysis_prompt(
                    files_meta, user_query, confirmed_intent
                ),
                event_callback=event_callback,
            )

            self._emit(event_callback, "status", "Validating generated code safety")
            validation_result = self._validator.validate(code)
            validation_result.raise_if_unsafe()

            self._emit(event_callback, "status", "Verifying code against intent")
            code_verification = self._call_json_stage(
                self._prompt_builder.build_code_verification_prompt(
                    user_query, confirmed_intent, code
                ),
                required_fields=["status", "issues", "fix_instruction"],
                stage_name="code verification",
            )
            self._emit(
                event_callback,
                "code_verification",
                "Code verification completed",
                delta=json.dumps(code_verification, ensure_ascii=False, indent=2),
            )

            if code_verification.get("status") != "ready":
                return WorkflowResult(
                    success=False,
                    code=code,
                    execution=None,
                    error=(
                        code_verification.get("fix_instruction")
                        or "生成代码未通过意图验证。"
                    ),
                    intent_result=intent,
                    validation_result=validation,
                    code_verification=code_verification,
                )

            self._emit(event_callback, "status", "Generated code is ready")
            return WorkflowResult(
                success=True,
                code=code,
                execution=None,
                intent_result=intent,
                validation_result=validation,
                code_verification=code_verification,
            )

        except SecurityError as e:
            return WorkflowResult(
                success=False,
                code="",
                execution=None,
                error=f"❌ 安全检查失败: {str(e)}",
            )
        except JsonContractError as e:
            return WorkflowResult(
                success=False,
                code="",
                execution=None,
                error=f"❌ LLM 结构化输出无效: {str(e)}",
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

    def _clarification_result(
        self,
        intent: dict[str, Any],
        validation: dict[str, Any],
    ) -> WorkflowResult:
        options = validation.get("options")
        if not isinstance(options, list):
            options = []
        question = validation.get("question") or validation.get("blocking_issue")
        if not question:
            question = "这个分析请求还不够明确，请补充你希望如何分析。"
        return WorkflowResult(
            success=False,
            code="",
            execution=None,
            error=validation.get("blocking_issue", ""),
            intent_result=intent,
            validation_result=validation,
            needs_clarification=True,
            clarification_question=str(question),
            clarification_options=[
                option for option in options if isinstance(option, dict)
            ],
        )

    def _call_json_stage(
        self,
        prompt: dict,
        required_fields: list[str],
        stage_name: str,
    ) -> dict[str, Any]:
        raw = self._call_llm(prompt, event_callback=None)
        try:
            return self._parse_json_object(raw, required_fields)
        except JsonContractError as first_error:
            repair_prompt = self._prompt_builder.build_json_repair_prompt(
                raw, str(first_error)
            )
            repaired = self._call_llm(repair_prompt, event_callback=None)
            try:
                return self._parse_json_object(repaired, required_fields)
            except JsonContractError as second_error:
                raise JsonContractError(
                    f"{stage_name} JSON 修复失败: {second_error}"
                ) from second_error

    def _parse_json_object(
        self,
        raw: str,
        required_fields: list[str],
    ) -> dict[str, Any]:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            raise JsonContractError(f"不是合法 JSON: {e}") from e

        if not isinstance(parsed, dict):
            raise JsonContractError("JSON 顶层必须是对象")

        missing = [field for field in required_fields if field not in parsed]
        if missing:
            raise JsonContractError(f"缺少字段: {', '.join(missing)}")

        return parsed

    def _call_llm(
        self,
        prompt: dict,
        event_callback: EventCallback | None = None,
    ) -> str:
        return self._client.generate_code(prompt, event_callback=event_callback)

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
