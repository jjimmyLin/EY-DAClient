from __future__ import annotations

import threading
from typing import Protocol

from llm import LLMError


class Closable(Protocol):
    def close(self) -> None: ...


class RequestCancelled(LLMError):
    """Raised when a background LLM request is cancelled by the UI."""


class CancellationToken:
    """Thread-safe cancellation state with active HTTP client interruption."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._active_client: Closable | None = None

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()
        with self._lock:
            client = self._active_client
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise RequestCancelled("Request cancelled")

    def set_active_client(self, client: Closable) -> None:
        self.raise_if_cancelled()
        with self._lock:
            self._active_client = client
        if self.is_cancelled:
            self.cancel()
            self.raise_if_cancelled()

    def clear_active_client(self, client: Closable) -> None:
        with self._lock:
            if self._active_client is client:
                self._active_client = None

    def wait(self, seconds: float) -> None:
        if self._event.wait(seconds):
            self.raise_if_cancelled()
