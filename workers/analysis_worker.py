"""
workers/analysis_worker.py
──────────────────────────
Background worker for analysis generation and execution.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from core.preprocessor import FileMeta
from dify.workflow import AnalysisWorkflow, WorkflowResult
from llm.cancellation import CancellationToken, RequestCancelled


class AnalysisWorker(QObject):
    """Run analysis workflow steps off the Qt UI thread."""

    event = Signal(dict)
    finished = Signal(object)
    error = Signal(str)

    def __init__(
        self,
        mode: str,
        files_meta: list[FileMeta],
        user_query: str = "",
        code: str = "",
        analysis_plan: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self._mode = mode
        self._files_meta = files_meta
        self._user_query = user_query
        self._code = code
        self._analysis_plan = analysis_plan or {}
        self._cancellation_token = CancellationToken()

    def cancel(self) -> None:
        self._cancellation_token.cancel()

    @Slot()
    def run(self) -> None:
        try:
            workflow = AnalysisWorkflow(cancellation_token=self._cancellation_token)
            if self._mode == "prepare":
                result = workflow.prepare_analysis(
                    self._files_meta,
                    self._user_query,
                    event_callback=self.event.emit,
                )
            elif self._mode == "generate":
                result = workflow.generate_only(
                    self._files_meta,
                    self._user_query,
                    event_callback=self.event.emit,
                )
            elif self._mode == "overview":
                if not self._files_meta:
                    result = WorkflowResult(
                        success=False,
                        code="",
                        execution=None,
                        error="No dataset available for overview",
                    )
                else:
                    result = workflow.overview_only(
                        self._files_meta[0],
                        event_callback=self.event.emit,
                    )
            elif self._mode == "execute":
                result = workflow.execute_with_repair(
                    self._code,
                    self._files_meta,
                    self._user_query,
                    analysis_plan=self._analysis_plan,
                    event_callback=self.event.emit,
                )
            else:
                result = WorkflowResult(
                    success=False,
                    code=self._code,
                    execution=None,
                    error=f"Unknown analysis worker mode: {self._mode}",
                )

            if not self._cancellation_token.is_cancelled:
                self.finished.emit(result)
            else:
                self.error.emit("Request cancelled")
        except RequestCancelled:
            self.error.emit("Request cancelled")
        except Exception as exc:
            self.error.emit(str(exc))
