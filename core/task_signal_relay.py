"""Main-thread Qt signal relay for generation-scoped background tasks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Slot


PayloadHandler = Callable[[int, Any], None]
FinishedHandler = Callable[[int], None]


class TaskSignalRelay(QObject):
    """Relay worker signals on this QObject's owning (UI) thread."""

    def __init__(
        self,
        generation: int,
        *,
        event_handler: PayloadHandler | None = None,
        result_handler: PayloadHandler | None = None,
        error_handler: PayloadHandler | None = None,
        cancelled_handler: FinishedHandler | None = None,
        thread_finished_handler: FinishedHandler | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.generation = generation
        self._event_handler = event_handler
        self._result_handler = result_handler
        self._error_handler = error_handler
        self._cancelled_handler = cancelled_handler
        self._thread_finished_handler = thread_finished_handler

    @Slot(dict)
    def handle_event(self, payload: dict) -> None:
        if self._event_handler is not None:
            self._event_handler(self.generation, payload)

    @Slot(object)
    def handle_result(self, payload: object) -> None:
        if self._result_handler is not None:
            self._result_handler(self.generation, payload)

    @Slot(str)
    def handle_error(self, error: str) -> None:
        if self._error_handler is not None:
            self._error_handler(self.generation, error)

    @Slot()
    def handle_cancelled(self) -> None:
        if self._cancelled_handler is not None:
            self._cancelled_handler(self.generation)

    @Slot()
    def handle_thread_finished(self) -> None:
        if self._thread_finished_handler is not None:
            self._thread_finished_handler(self.generation)
