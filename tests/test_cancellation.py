from __future__ import annotations

import pytest

from llm.cancellation import CancellationToken, RequestCancelled


class FakeClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_cancel_closes_active_http_client():
    token = CancellationToken()
    client = FakeClient()
    token.set_active_client(client)

    token.cancel()

    assert client.closed
    assert token.is_cancelled
    with pytest.raises(RequestCancelled):
        token.raise_if_cancelled()


def test_cancel_interrupts_retry_wait():
    token = CancellationToken()
    token.cancel()

    with pytest.raises(RequestCancelled):
        token.wait(30)
