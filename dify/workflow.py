"""
dify/workflow.py
────────────────
Analysis workflow orchestration.
LLM code generation → Python safety validation → local Python execution.
"""

from __future__ import annotations

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
