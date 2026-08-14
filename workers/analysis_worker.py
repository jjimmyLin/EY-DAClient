"""
workers/analysis_worker.py
──────────────────────────
Background worker for analysis generation and execution.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from core.preprocessor import FileMeta
from dify.workflow import AnalysisWorkflow, WorkflowResult
from llm.cancellation import CancellationToken, RequestCancelled


logger = logging.getLogger(__name__)


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
        remote_attempts_used: int = 0,
    ) -> None:
        super().__init__()
        self._mode = mode
        self._files_meta = files_meta
        self._user_query = user_query
        self._code = code
        self._analysis_plan = analysis_plan or {}
        self._remote_attempts_used = max(0, int(remote_attempts_used))
        self._cancellation_token = CancellationToken()

    def cancel(self) -> None:
        self._cancellation_token.cancel()
        logger.info("Analysis worker cancellation requested mode=%s", self._mode)

    @Slot()
    def run(self) -> None:
        try:
            logger.info("Analysis worker started mode=%s datasets=%s", self._mode, [file_meta.runtime_key for file_meta in self._files_meta])
            workflow = AnalysisWorkflow(
                cancellation_token=self._cancellation_token,
                remote_attempts_used=self._remote_attempts_used,
            )
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
            result.remote_attempts_used = workflow.remote_attempts_used

            if not self._cancellation_token.is_cancelled:
                logger.info("Analysis worker finished mode=%s success=%s", self._mode, result.success)
                self.finished.emit(result)
            else:
                logger.info("Analysis worker cancelled after mode=%s", self._mode)
                self.error.emit("Request cancelled")
        except RequestCancelled:
            logger.info("Analysis worker raised RequestCancelled mode=%s", self._mode)
            self.error.emit("Request cancelled")
        except Exception as exc:
            logger.exception("Analysis worker failed mode=%s", self._mode)
            self.error.emit(str(exc))
