"""Reliable, cancellation-aware transport for Dify Workflow applications."""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from llm.cancellation import CancellationToken, RequestCancelled


logger = logging.getLogger(__name__)

WorkflowEventCallback = Callable[[dict[str, Any]], None]


class WorkflowTransportError(RuntimeError):
    """A classified Dify transport or workflow failure."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 0,
        code: str = "",
        category: str = "unknown",
        retryable: bool = False,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.category = category
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True)
class RemoteRunSnapshot:
    user: str
    task_id: str
    workflow_run_id: str


class RemoteRunHandle:
    """Thread-safe identifiers for one remote workflow execution."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._user = ""
        self._task_id = ""
        self._workflow_run_id = ""

    def reset(self, user: str) -> None:
        with self._lock:
            self._user = str(user or "").strip()
            self._task_id = ""
            self._workflow_run_id = ""

    def update(
        self,
        *,
        task_id: str = "",
        workflow_run_id: str = "",
    ) -> RemoteRunSnapshot:
        with self._lock:
            if task_id:
                self._task_id = str(task_id).strip()
            if workflow_run_id:
                self._workflow_run_id = str(workflow_run_id).strip()
            return RemoteRunSnapshot(
                self._user,
                self._task_id,
                self._workflow_run_id,
            )

    def snapshot(self) -> RemoteRunSnapshot:
        with self._lock:
            return RemoteRunSnapshot(
                self._user,
                self._task_id,
                self._workflow_run_id,
            )


class ReliableWorkflowRunner:
    """Start once, resume dropped SSE streams, and stop cancelled runs."""

    _TERMINAL_STATUSES = {
        "succeeded",
        "failed",
        "stopped",
        "partial-succeeded",
        "paused",
    }
    _TRANSIENT_STATUSES = {404, 429, 500, 502, 503, 504}

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: int | float,
        cancellation_token: CancellationToken,
        transport: httpx.BaseTransport | None = None,
        handle: RemoteRunHandle | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = max(1.0, float(timeout))
        self._cancellation_token = cancellation_token
        self._transport = transport
        self.handle = handle or RemoteRunHandle()

    def run(
        self,
        payload: dict[str, Any],
        *,
        event_callback: WorkflowEventCallback | None = None,
    ) -> dict[str, Any]:
        """Start the workflow exactly once and recover the same run if possible."""
        user = str(payload.get("user") or "").strip()
        self.handle.reset(user)
        deadline = time.monotonic() + self._timeout
        try:
            try:
                result = self._open_stream(
                    "POST",
                    "workflows/run",
                    json_payload=payload,
                    event_callback=event_callback,
                )
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                if self._cancellation_token.is_cancelled:
                    raise RequestCancelled("Request cancelled") from exc
                return self._recover_or_raise(
                    exc,
                    deadline=deadline,
                    event_callback=event_callback,
                )

            self._cancellation_token.raise_if_cancelled()
            if result is not None:
                return result
            return self._recover_or_raise(
                None,
                deadline=deadline,
                event_callback=event_callback,
            )
        except RequestCancelled:
            self.stop_remote()
            raise
        except WorkflowTransportError:
            raise
        except Exception as exc:
            if self._cancellation_token.is_cancelled:
                self.stop_remote()
                raise RequestCancelled("Request cancelled") from exc
            self.stop_remote()
            logger.exception("Unexpected Dify workflow transport failure")
            raise WorkflowTransportError(
                "Unexpected Dify workflow transport failure "
                f"({type(exc).__name__}): {exc}",
                category="unexpected",
            ) from exc

    def stop_remote(self) -> bool:
        """Best-effort remote stop using a fresh client, independent of cancellation."""
        snapshot = self.handle.snapshot()
        if not snapshot.task_id:
            return False
        headers = self._headers()
        url = (
            f"{self._base_url}/workflows/tasks/"
            f"{snapshot.task_id}/stop"
        )
        try:
            with httpx.Client(
                timeout=httpx.Timeout(5.0),
                transport=self._transport,
            ) as client:
                response = client.post(
                    url,
                    headers=headers,
                    json={"user": snapshot.user},
                )
            if response.is_success:
                logger.info(
                    "Stopped Dify workflow task task_id=%s run_id=%s",
                    snapshot.task_id,
                    snapshot.workflow_run_id,
                )
                return True
            logger.warning(
                "Dify stop rejected status=%s task_id=%s run_id=%s",
                response.status_code,
                snapshot.task_id,
                snapshot.workflow_run_id,
            )
        except Exception:
            logger.exception(
                "Unable to stop Dify workflow task task_id=%s run_id=%s",
                snapshot.task_id,
                snapshot.workflow_run_id,
            )
        return False

    def _recover_or_raise(
        self,
        cause: Exception | None,
        *,
        deadline: float,
        event_callback: WorkflowEventCallback | None,
    ) -> dict[str, Any]:
        snapshot = self.handle.snapshot()
        if not snapshot.workflow_run_id:
            if isinstance(cause, httpx.TimeoutException):
                raise WorkflowTransportError(
                    "The workflow timed out before Dify returned a run ID. "
                    "The request was not replayed to avoid a duplicate run.",
                    status_code=408,
                    category="network_timeout",
                    retryable=True,
                ) from cause
            detail = f": {cause}" if cause is not None else ""
            raise WorkflowTransportError(
                "The workflow stream ended before Dify returned a run ID"
                f"{detail}. The request was not replayed to avoid a duplicate run.",
                category="stream_interrupted",
                retryable=True,
            ) from cause

        recovery_grace = min(60.0, max(15.0, self._timeout / 4))
        deadline = max(deadline, time.monotonic() + recovery_grace)
        self._emit_client_event(
            event_callback,
            "client_reconnecting",
            message="The connection was interrupted; recovering the Dify run.",
        )
        result = self._resume_stream(
            deadline=deadline,
            event_callback=event_callback,
        )
        if result is not None:
            return self._confirm_recovered_result(
                result,
                deadline=deadline,
            )
        return self._poll_result(deadline=deadline)

    def _resume_stream(
        self,
        *,
        deadline: float,
        event_callback: WorkflowEventCallback | None,
    ) -> dict[str, Any] | None:
        snapshot = self.handle.snapshot()
        if not snapshot.workflow_run_id:
            return None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            return self._open_stream(
                "GET",
                f"workflow/{snapshot.workflow_run_id}/events",
                params={
                    "user": snapshot.user,
                    "include_state_snapshot": "true",
                },
                event_callback=event_callback,
            )
        except WorkflowTransportError as exc:
            if exc.status_code not in self._TRANSIENT_STATUSES:
                raise
            logger.info(
                "Dify stream resume unavailable status=%s run_id=%s; polling",
                exc.status_code,
                snapshot.workflow_run_id,
            )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            logger.info(
                "Dify stream resume failed run_id=%s error=%s; polling",
                snapshot.workflow_run_id,
                exc,
            )
        return None

    def _confirm_recovered_result(
        self,
        streamed_result: dict[str, Any],
        *,
        deadline: float,
    ) -> dict[str, Any]:
        """Confirm a recovered terminal event, falling back to the event payload."""
        try:
            return self._poll_result(deadline=deadline, single_attempt=True)
        except WorkflowTransportError as exc:
            if exc.status_code not in self._TRANSIENT_STATUSES:
                raise
            return streamed_result
        except (httpx.TimeoutException, httpx.RequestError):
            return streamed_result

    def _poll_result(
        self,
        *,
        deadline: float,
        single_attempt: bool = False,
    ) -> dict[str, Any]:
        snapshot = self.handle.snapshot()
        while time.monotonic() < deadline:
            self._cancellation_token.raise_if_cancelled()
            try:
                detail = self._request_json(
                    "GET",
                    f"workflows/run/{snapshot.workflow_run_id}",
                )
            except WorkflowTransportError as exc:
                if exc.status_code not in self._TRANSIENT_STATUSES:
                    raise
                if single_attempt:
                    raise
                self._wait_with_jitter(0.8)
                continue
            except (httpx.TimeoutException, httpx.RequestError):
                if single_attempt:
                    raise
                self._wait_with_jitter(0.8)
                continue

            status = str(detail.get("status") or "").strip().lower()
            if status in self._TERMINAL_STATUSES:
                return self._terminal_response(detail)
            if single_attempt:
                raise WorkflowTransportError(
                    "The recovered workflow detail is not terminal yet.",
                    status_code=404,
                    category="server_transient",
                    retryable=True,
                )
            self._wait_with_jitter(0.8)

        raise WorkflowTransportError(
            "The workflow timed out while recovering the Dify result.",
            status_code=408,
            category="network_timeout",
            retryable=True,
        )

    def _open_stream(
        self,
        method: str,
        endpoint: str,
        *,
        json_payload: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        event_callback: WorkflowEventCallback | None = None,
    ) -> dict[str, Any] | None:
        self._cancellation_token.raise_if_cancelled()
        url = f"{self._base_url}/{endpoint.lstrip('/')}"
        with httpx.Client(
            timeout=self._http_timeout(),
            transport=self._transport,
        ) as client:
            self._cancellation_token.set_active_client(client)
            try:
                with client.stream(
                    method,
                    url,
                    headers=self._headers(stream=True),
                    json=json_payload,
                    params=params,
                ) as response:
                    if not response.is_success:
                        response.read()
                        raise self._response_error(response)
                    content_type = response.headers.get(
                        "content-type",
                        "",
                    ).lower()
                    if "application/json" in content_type:
                        response.read()
                        try:
                            body = response.json()
                        except ValueError as exc:
                            raise WorkflowTransportError(
                                "Dify returned invalid workflow JSON.",
                                category="protocol_error",
                            ) from exc
                        if not isinstance(body, dict):
                            raise WorkflowTransportError(
                                "Dify returned an invalid workflow response.",
                                category="protocol_error",
                            )
                        data = body.get("data")
                        if isinstance(data, dict):
                            self.handle.update(
                                task_id=str(body.get("task_id") or ""),
                                workflow_run_id=str(
                                    body.get("workflow_run_id")
                                    or data.get("id")
                                    or ""
                                ),
                            )
                        return body
                    return self._collect_stream(
                        response,
                        event_callback=event_callback,
                    )
            finally:
                self._cancellation_token.clear_active_client(client)

    def _collect_stream(
        self,
        response: httpx.Response,
        *,
        event_callback: WorkflowEventCallback | None,
    ) -> dict[str, Any] | None:
        text_chunks: list[str] = []
        for raw_line in response.iter_lines():
            self._cancellation_token.raise_if_cancelled()
            line = raw_line.strip()
            if not line or not line.startswith("data:"):
                continue
            payload_text = line[5:].strip()
            if not payload_text:
                continue
            try:
                chunk = json.loads(payload_text)
            except json.JSONDecodeError:
                logger.warning(
                    "Ignoring malformed Dify SSE event prefix=%r",
                    payload_text[:160],
                )
                continue
            if not isinstance(chunk, dict):
                continue

            event = str(chunk.get("event") or "").strip()
            data = chunk.get("data") or {}
            if not isinstance(data, dict):
                data = {}
            task_id = str(chunk.get("task_id") or "").strip()
            workflow_run_id = str(
                chunk.get("workflow_run_id")
                or (data.get("id") if event == "workflow_started" else "")
                or ""
            ).strip()
            snapshot = self.handle.update(
                task_id=task_id,
                workflow_run_id=workflow_run_id,
            )
            chunk["task_id"] = snapshot.task_id
            chunk["workflow_run_id"] = snapshot.workflow_run_id
            if event_callback is not None:
                event_callback(chunk)

            if event == "text_chunk":
                text = str(data.get("text") or "")
                if text:
                    text_chunks.append(text)
                continue
            if event == "error":
                raise WorkflowTransportError(
                    str(
                        data.get("message")
                        or chunk.get("message")
                        or "Dify workflow stream failed."
                    ),
                    status_code=self._as_int(
                        data.get("status") or chunk.get("status")
                    ),
                    code=str(data.get("code") or chunk.get("code") or ""),
                    category="workflow_error",
                )
            if event == "node_finished":
                if str(data.get("status") or "").lower() == "failed":
                    raise WorkflowTransportError(
                        str(data.get("error") or "Dify workflow node failed."),
                        status_code=400,
                        category="workflow_failed",
                    )
                continue
            if event == "workflow_finished":
                result = self._terminal_response(data)
                outputs = result["data"].get("outputs")
                if not outputs and text_chunks:
                    result["data"]["outputs"] = {"text": "".join(text_chunks)}
                elif isinstance(outputs, str):
                    result["data"]["outputs"] = {"text": outputs}
                return result
        return None

    def _terminal_response(self, detail: dict[str, Any]) -> dict[str, Any]:
        status = str(detail.get("status") or "").strip().lower()
        if status and status != "succeeded":
            raise WorkflowTransportError(
                str(detail.get("error") or f"Dify workflow ended with {status}."),
                status_code=400,
                category="workflow_failed",
            )
        snapshot = self.handle.update(
            workflow_run_id=str(detail.get("id") or "").strip()
        )
        return {
            "workflow_run_id": snapshot.workflow_run_id,
            "task_id": snapshot.task_id,
            "data": dict(detail),
        }

    def _request_json(
        self,
        method: str,
        endpoint: str,
    ) -> dict[str, Any]:
        self._cancellation_token.raise_if_cancelled()
        url = f"{self._base_url}/{endpoint.lstrip('/')}"
        with httpx.Client(
            timeout=self._http_timeout(),
            transport=self._transport,
        ) as client:
            self._cancellation_token.set_active_client(client)
            try:
                response = client.request(
                    method,
                    url,
                    headers=self._headers(),
                )
            finally:
                self._cancellation_token.clear_active_client(client)
        self._cancellation_token.raise_if_cancelled()
        if not response.is_success:
            raise self._response_error(response)
        try:
            body = response.json()
        except ValueError as exc:
            raise WorkflowTransportError(
                "Dify returned invalid JSON while recovering the workflow.",
                category="protocol_error",
            ) from exc
        if not isinstance(body, dict):
            raise WorkflowTransportError(
                "Dify returned an invalid workflow response.",
                category="protocol_error",
            )
        return body

    def _response_error(self, response: httpx.Response) -> WorkflowTransportError:
        code = ""
        message = response.text[:300]
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if isinstance(payload, dict):
            code = str(payload.get("code") or "")
            message = str(payload.get("message") or message)
        retryable = response.status_code == 429 or response.status_code >= 500
        return WorkflowTransportError(
            message or f"Dify returned HTTP {response.status_code}.",
            status_code=response.status_code,
            code=code,
            category=self._status_category(response.status_code),
            retryable=retryable,
        )

    def _http_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=min(15.0, self._timeout),
            read=min(45.0, max(20.0, self._timeout)),
            write=min(30.0, self._timeout),
            pool=min(15.0, self._timeout),
        )

    def _headers(self, *, stream: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if stream:
            headers["Accept"] = "text/event-stream"
        return headers

    def _wait_with_jitter(self, base: float) -> None:
        self._cancellation_token.wait(base + random.uniform(0.0, base / 4))

    def _emit_client_event(
        self,
        callback: WorkflowEventCallback | None,
        event: str,
        *,
        message: str,
    ) -> None:
        if callback is None:
            return
        snapshot = self.handle.snapshot()
        callback(
            {
                "event": event,
                "task_id": snapshot.task_id,
                "workflow_run_id": snapshot.workflow_run_id,
                "data": {"message": message},
            }
        )

    @staticmethod
    def _status_category(status_code: int) -> str:
        if status_code in {401, 403}:
            return "authentication"
        if status_code == 429:
            return "rate_limited"
        if status_code >= 500:
            return "server_transient"
        if status_code >= 400:
            return "validation"
        return "unknown"

    @staticmethod
    def _as_int(value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
