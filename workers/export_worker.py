"""Background worker for analysis result exports."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot

from core.analysis_export import AnalysisExportService
from core.analysis_result import AnalysisResult


logger = logging.getLogger(__name__)


class AnalysisExportWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        result: AnalysisResult,
        output_path: str,
        metadata: dict | None = None,
    ) -> None:
        super().__init__()
        self._result = result
        self._output_path = output_path
        self._metadata = dict(metadata or {})
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        try:
            output_path = AnalysisExportService().export_excel(
                self._result,
                self._output_path,
                metadata=self._metadata,
                cancel_callback=lambda: self._cancelled,
            )
            self.finished.emit(output_path)
        except Exception as exc:
            if not self._cancelled:
                logger.exception(
                    "Analysis export worker failed output=%s",
                    self._output_path,
                )
            self.failed.emit(str(exc))
