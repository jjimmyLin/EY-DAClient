"""Detect long application pauses such as Windows suspend/resume."""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Signal


class ResumeMonitor(QObject):
    """Emit when the UI event loop has been paused longer than expected."""

    resumed = Signal(float)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        interval_ms: int = 5000,
        resume_gap_seconds: float = 30.0,
        clock=None,
    ) -> None:
        super().__init__(parent)
        self._clock = clock or time.time
        self._resume_gap_seconds = max(
            resume_gap_seconds,
            interval_ms / 1000 * 2,
        )
        self._last_tick = float(self._clock())
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.check_now)
        self._timer.start()

    def check_now(self) -> None:
        now = float(self._clock())
        gap = max(0.0, now - self._last_tick)
        self._last_tick = now
        if gap >= self._resume_gap_seconds:
            self.resumed.emit(gap)

    def reset(self) -> None:
        self._last_tick = float(self._clock())
