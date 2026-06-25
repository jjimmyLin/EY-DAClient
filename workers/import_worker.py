"""Background spreadsheet import and profiling worker."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot

from core.preprocessor import Preprocessor, ProcessingCancelled


logger = logging.getLogger(__name__)


class ImportWorker(QObject):
    progress = Signal(str, dict)
    file_finished = Signal(str, object)
    file_failed = Signal(str, str)
    finished = Signal()

    def __init__(self, file_paths: list[str]) -> None:
        super().__init__()
        self._file_paths = list(file_paths)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        logger.info("Import worker cancellation requested for %s file(s)", len(self._file_paths))

    @Slot()
    def run(self) -> None:
        preprocessor = Preprocessor()
        for file_path in self._file_paths:
            if self._cancelled:
                break
            try:
                logger.info("Import worker starting %s", file_path)
                file_meta = preprocessor.process(
                    file_path,
                    progress_callback=lambda event, path=file_path: (
                        self.progress.emit(path, event)
                    ),
                    cancel_callback=lambda: self._cancelled,
                )
                if not self._cancelled:
                    self.file_finished.emit(file_path, file_meta)
                    logger.info("Import worker finished %s", file_path)
            except ProcessingCancelled as exc:
                logger.info("Import worker cancelled during %s", file_path)
                self.file_failed.emit(file_path, str(exc))
                break
            except Exception as exc:
                logger.exception("Import worker failed for %s", file_path)
                self.file_failed.emit(file_path, str(exc))
        self.finished.emit()
