"""Qt worker for silent analysis-experience submission."""

from __future__ import annotations

import logging
from functools import partial
from typing import Any

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from llm.cancellation import CancellationToken, RequestCancelled
from services.experience_service import ExperienceService


logger = logging.getLogger(__name__)


class ExperienceSubmissionWorker(QObject):
    """Submit one consented payload without blocking or disturbing analysis."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__()
        self._payload = payload
        self._cancellation_token = CancellationToken()

    def cancel(self) -> None:
        self._cancellation_token.cancel()

    @Slot()
    def run(self) -> None:
        try:
            result = ExperienceService.submit(
                self._payload,
                cancellation_token=self._cancellation_token,
            )
            if not self._cancellation_token.is_cancelled:
                self.finished.emit(result)
        except RequestCancelled:
            logger.info("Experience submission cancelled")
            self.failed.emit("Request cancelled")
        except Exception as exc:
            logger.exception("Experience submission failed")
            self.failed.emit(str(exc))


class ExperienceSubmissionQueue(QObject):
    """Serialize background submissions and own their Qt thread lifecycle."""

    submitted = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._queue: list[tuple[int, dict[str, Any]]] = []
        self._thread: QThread | None = None
        self._worker: ExperienceSubmissionWorker | None = None

    def enqueue(self, task_id: int, payload: dict[str, Any]) -> None:
        self._queue.append((task_id, payload))
        self._start_next()

    def shutdown(self) -> None:
        self._queue.clear()
        if self._worker is not None:
            self._worker.cancel()
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(3000)

    def _start_next(self) -> None:
        if self._thread is not None or not self._queue:
            return
        task_id, payload = self._queue.pop(0)
        thread = QThread(self)
        worker = ExperienceSubmissionWorker(payload)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(partial(self.submitted.emit, task_id))
        worker.failed.connect(partial(self.failed.emit, task_id))
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup)

        self._thread = thread
        self._worker = worker
        thread.start()

    def _cleanup(self) -> None:
        self._thread = None
        self._worker = None
        QTimer.singleShot(0, self._start_next)
