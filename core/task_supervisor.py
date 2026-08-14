"""Small task lifecycle coordinator used by the Qt main window."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any


logger = logging.getLogger(__name__)


class TaskState(str, Enum):
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUPERSEDED = "superseded"
    FINISHED = "finished"


@dataclass
class TaskRuntime:
    generation: int
    thread: Any
    worker: Any
    relay: Any = None
    state: TaskState = TaskState.RUNNING


class TaskSupervisor:
    """Keep one foreground task while safely tracking retiring workers."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._lock = threading.Lock()
        self._next_generation = 0
        self._active_generation: int | None = None
        self._runtimes: dict[int, TaskRuntime] = {}

    @property
    def active_generation(self) -> int | None:
        with self._lock:
            return self._active_generation

    @property
    def active_runtime(self) -> TaskRuntime | None:
        with self._lock:
            if self._active_generation is None:
                return None
            return self._runtimes.get(self._active_generation)

    def activate(self, thread: Any, worker: Any) -> TaskRuntime:
        with self._lock:
            self._next_generation += 1
            runtime = TaskRuntime(
                generation=self._next_generation,
                thread=thread,
                worker=worker,
            )
            self._runtimes[runtime.generation] = runtime
            self._active_generation = runtime.generation
            return runtime

    def is_active(self, generation: int) -> bool:
        with self._lock:
            return self._active_generation == generation

    def retire_active(
        self,
        *,
        superseded: bool = False,
    ) -> TaskRuntime | None:
        with self._lock:
            if self._active_generation is None:
                return None
            runtime = self._runtimes.get(self._active_generation)
            self._active_generation = None
            if runtime is not None:
                runtime.state = (
                    TaskState.SUPERSEDED
                    if superseded
                    else TaskState.CANCELLING
                )
            return runtime

    def finish(self, generation: int) -> bool:
        """Remove a runtime and return whether it was still foreground."""
        with self._lock:
            runtime = self._runtimes.pop(generation, None)
            was_active = self._active_generation == generation
            if was_active:
                self._active_generation = None
            if runtime is not None:
                runtime.state = TaskState.FINISHED
            return was_active

    def all_runtimes(self) -> tuple[TaskRuntime, ...]:
        with self._lock:
            return tuple(self._runtimes.values())

    def cancel_all(self) -> None:
        for runtime in self.all_runtimes():
            try:
                runtime.worker.cancel()
            except Exception:
                logger.exception(
                    "Unable to cancel %s generation=%s",
                    self.name,
                    runtime.generation,
                )
