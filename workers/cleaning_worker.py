"""Background workers for deterministic data cleaning."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot

from core.cleaning_service import CleaningService
from core.preprocessor import ProcessingCancelled


logger = logging.getLogger(__name__)


class CleaningProfileWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, dataset_name: str, file_meta) -> None:
        super().__init__()
        self.dataset_name = dataset_name
        self.file_meta = file_meta
        self._cancelled = False
        self._service = CleaningService()

    def cancel(self) -> None:
        self._cancelled = True
        self._service.cancel()

    @Slot()
    def run(self) -> None:
        try:
            result = self._service.profile(
                self.file_meta,
                progress_callback=lambda percent, detail: self.progress.emit(
                    percent,
                    detail,
                ),
                cancel_callback=lambda: self._cancelled,
            )
            self.finished.emit(self.dataset_name, result)
        except Exception as exc:
            if not isinstance(exc, ProcessingCancelled):
                logger.exception("Cleaning profile worker failed")
            self.failed.emit(self.dataset_name, str(exc))


class CleaningExecutionWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(str, object)
    failed = Signal(str, str)

    def __init__(
        self,
        dataset_name: str,
        file_meta,
        selections: dict,
        output_path: str,
    ) -> None:
        super().__init__()
        self.dataset_name = dataset_name
        self.file_meta = file_meta
        self.selections = dict(selections)
        self.output_path = output_path
        self._cancelled = False
        self._service = CleaningService()

    def cancel(self) -> None:
        self._cancelled = True
        self._service.cancel()

    @Slot()
    def run(self) -> None:
        try:
            result = self._service.clean(
                self.file_meta,
                self.selections,
                self.output_path,
                progress_callback=lambda percent, sheet: self.progress.emit(percent, sheet),
                cancel_callback=lambda: self._cancelled,
            )
            self.finished.emit(self.dataset_name, result)
        except Exception as exc:
            if not isinstance(exc, ProcessingCancelled):
                logger.exception("Cleaning execution worker failed")
            self.failed.emit(self.dataset_name, str(exc))
