"""Dedicated Dify client for business-analysis indicator generation."""

from __future__ import annotations

import getpass
import json
import mimetypes
import platform
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from config.settings import settings
from core.metric_discovery import (
    MetricDiscoveryContractError,
    MetricDiscoveryRequest,
    MetricDiscoveryResult,
)
from llm.cancellation import CancellationToken, RequestCancelled


MetricEventCallback = Callable[[dict[str, object]], None]


class MetricClientError(RuntimeError):
    """The dedicated indicator workflow request or response failed."""

    def __init__(self, message: str, *, status_code: int = 0) -> None:
        self.status_code = status_code
        super().__init__(message)


class MetricDifyClient:
    """Upload reference documents and invoke the isolated Dify Workflow app."""

    PAYLOAD_VARIABLE = "request_payload"
    FILES_VARIABLE = "reference_files"

    def __init__(
        self,
        cancellation_token: CancellationToken | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        settings.reload()
        self._base_url = settings.DIFY_METRIC_BASE_URL.rstrip("/")
        self._api_key = settings.DIFY_METRIC_API_KEY
        self._timeout = settings.DIFY_METRIC_TIMEOUT
        self._transport = transport
        self._max_retries = 3
        self._retry_delay = 1.0
        self._cancellation_token = cancellation_token or CancellationToken()

    def generate(
        self,
        request: MetricDiscoveryRequest,
        event_callback: MetricEventCallback | None = None,
    ) -> MetricDiscoveryResult:
        if not self._base_url or not self._api_key:
            raise MetricClientError(
                "The business indicator workflow is not configured. "
                "Open Config and provide its Dify API key and base URL."
            )
        request.validate()
        self._emit(event_callback, "status", "正在检查指标工作流配置")
        fields = self._get_input_fields()
        self._validate_input_contract(fields, bool(request.attachments))

        uploaded_files: list[dict[str, str]] = []
        total_files = len(request.attachments)
        for index, attachment in enumerate(request.attachments, start=1):
            self._emit(
                event_callback,
                "progress",
                f"正在上传参考资料：{attachment.name}",
                current=index,
                total=total_files,
            )
            uploaded_files.append(self._upload_file(attachment.path))

        payload_text = request.to_json()
        self._validate_payload_limit(payload_text, fields)
        inputs: dict[str, Any] = {
            self.PAYLOAD_VARIABLE: payload_text,
            self.FILES_VARIABLE: uploaded_files,
        }
        self._emit(event_callback, "status", "正在理解业务并生成指标")
        response = self._run_workflow_streaming(
            {
                "inputs": inputs,
                "response_mode": "streaming",
                "user": self._build_user_id(),
            },
            event_callback=event_callback,
        )
        self._emit(event_callback, "status", "正在校验指标完整性")
        try:
            result = MetricDiscoveryResult.from_workflow_response(response)
        except MetricDiscoveryContractError as exc:
            raise MetricClientError(str(exc), status_code=400) from exc
        self._emit(event_callback, "status", "指标生成完成")
        return result

    def _get_input_fields(self) -> list[dict[str, Any]]:
        response = self._request_json("GET", "parameters")
        fields: list[dict[str, Any]] = []
        for item in response.get("user_input_form", []) or []:
            if not isinstance(item, dict):
                continue
            for field_type, config in item.items():
                if not isinstance(config, dict):
                    continue
                variable = str(config.get("variable") or "").strip()
                if not variable:
                    continue
                fields.append(
                    {
                        "type": str(field_type),
                        "variable": variable,
                        "required": bool(config.get("required")),
                        "max_length": config.get("max_length"),
                    }
                )
        return fields

    def _validate_input_contract(
        self,
        fields: list[dict[str, Any]],
        has_attachments: bool,
    ) -> None:
        by_name = {str(field["variable"]): field for field in fields}
        if self.PAYLOAD_VARIABLE not in by_name:
            available = ", ".join(sorted(by_name)) or "<none>"
            raise MetricClientError(
                "The indicator workflow Start node must define a Paragraph "
                f"input named {self.PAYLOAD_VARIABLE}. Available: {available}."
            )
        if self.FILES_VARIABLE not in by_name:
            raise MetricClientError(
                "The indicator workflow Start node must define an optional "
                f"File List input named {self.FILES_VARIABLE}."
            )
        if has_attachments:
            file_type = str(by_name[self.FILES_VARIABLE].get("type") or "")
            if "file" not in file_type.lower():
                raise MetricClientError(
                    f"{self.FILES_VARIABLE} must be configured as a File List."
                )

    def _validate_payload_limit(
        self,
        payload_text: str,
        fields: list[dict[str, Any]],
    ) -> None:
        payload_field = next(
            (
                field
                for field in fields
                if field.get("variable") == self.PAYLOAD_VARIABLE
            ),
            {},
        )
        try:
            maximum = int(payload_field.get("max_length") or 0)
        except (TypeError, ValueError):
            maximum = 0
        if maximum > 0 and len(payload_text) > maximum:
            raise MetricClientError(
                "The complete indicator request exceeds the Dify "
                f"request_payload limit ({len(payload_text)} / {maximum}). "
                "Increase the Paragraph input limit in the workflow."
            )

    def _upload_file(self, file_path: str) -> dict[str, str]:
        path = Path(file_path)
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        url = f"{self._base_url}/files/upload"
        timeout = self._http_timeout()

        self._cancellation_token.raise_if_cancelled()
        try:
            with path.open("rb") as stream:
                with httpx.Client(
                    timeout=timeout,
                    transport=self._transport,
                ) as client:
                    self._cancellation_token.set_active_client(client)
                    try:
                        response = client.post(
                            url,
                            headers=headers,
                            data={"user": self._build_user_id()},
                            files={"file": (path.name, stream, mime_type)},
                        )
                    finally:
                        self._cancellation_token.clear_active_client(client)
        except OSError as exc:
            raise MetricClientError(
                f"Reference file is unavailable: {path.name}."
            ) from exc
        except httpx.TimeoutException as exc:
            if self._cancellation_token.is_cancelled:
                raise RequestCancelled("Request cancelled") from exc
            raise MetricClientError(
                f"Uploading {path.name} timed out.",
                status_code=408,
            ) from exc
        except httpx.RequestError as exc:
            if self._cancellation_token.is_cancelled:
                raise RequestCancelled("Request cancelled") from exc
            raise MetricClientError(
                f"Could not upload {path.name}: {exc}."
            ) from exc

        self._cancellation_token.raise_if_cancelled()
        if not response.is_success:
            raise MetricClientError(
                f"Dify rejected {path.name} ({response.status_code}): "
                f"{response.text[:240]}",
                status_code=response.status_code,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise MetricClientError(
                f"Dify returned invalid upload metadata for {path.name}."
            ) from exc
        upload_id = str(body.get("id") or "").strip()
        if not upload_id:
            raise MetricClientError(
                f"Dify did not return an upload ID for {path.name}."
            )
        return {
            "transfer_method": "local_file",
            "upload_file_id": upload_id,
            "type": "document",
        }

    def _request_json(
        self,
        method: str,
        endpoint: str,
        *,
        json_payload: dict[str, Any] | None = None,
        retryable: bool = True,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/{endpoint.lstrip('/')}"
        maximum_attempts = self._max_retries if retryable else 1
        for attempt in range(maximum_attempts):
            self._cancellation_token.raise_if_cancelled()
            try:
                with httpx.Client(
                    timeout=self._http_timeout(),
                    transport=self._transport,
                ) as client:
                    self._cancellation_token.set_active_client(client)
                    try:
                        response = client.request(
                            method,
                            url,
                            headers=headers,
                            json=json_payload,
                        )
                    finally:
                        self._cancellation_token.clear_active_client(client)
                self._cancellation_token.raise_if_cancelled()
            except httpx.TimeoutException as exc:
                if self._cancellation_token.is_cancelled:
                    raise RequestCancelled("Request cancelled") from exc
                if attempt < maximum_attempts - 1:
                    self._cancellation_token.wait(self._retry_delay)
                    continue
                raise MetricClientError(
                    "The indicator workflow timed out.",
                    status_code=408,
                ) from exc
            except httpx.RequestError as exc:
                if self._cancellation_token.is_cancelled:
                    raise RequestCancelled("Request cancelled") from exc
                if attempt < maximum_attempts - 1:
                    self._cancellation_token.wait(self._retry_delay)
                    continue
                raise MetricClientError(
                    f"The indicator workflow is unavailable: {exc}."
                ) from exc

            if response.is_success:
                try:
                    body = response.json()
                except ValueError as exc:
                    raise MetricClientError(
                        "The indicator workflow returned invalid JSON."
                    ) from exc
                if not isinstance(body, dict):
                    raise MetricClientError(
                        "The indicator workflow returned an invalid response."
                    )
                return body
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < maximum_attempts - 1:
                    self._cancellation_token.wait(self._retry_delay)
                    continue
            raise MetricClientError(
                f"Dify indicator workflow error {response.status_code}: "
                f"{response.text[:300]}",
                status_code=response.status_code,
            )
        raise MetricClientError("The indicator workflow request failed.")

    def _run_workflow_streaming(
        self,
        payload: dict[str, Any],
        *,
        event_callback: MetricEventCallback | None = None,
    ) -> dict[str, Any]:
        """Run once, consume SSE events, and recover without replaying the POST."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        url = f"{self._base_url}/workflows/run"
        stream_state = {
            "task_id": "",
            "workflow_run_id": "",
        }

        self._cancellation_token.raise_if_cancelled()
        try:
            with httpx.Client(
                timeout=self._http_timeout(),
                transport=self._transport,
            ) as client:
                self._cancellation_token.set_active_client(client)
                try:
                    with client.stream(
                        "POST",
                        url,
                        headers=headers,
                        json=payload,
                    ) as response:
                        if not response.is_success:
                            response.read()
                            raise MetricClientError(
                                f"Dify indicator workflow error "
                                f"{response.status_code}: "
                                f"{response.text[:300]}",
                                status_code=response.status_code,
                            )
                        result = self._collect_workflow_stream(
                            response,
                            stream_state=stream_state,
                            event_callback=event_callback,
                        )
                finally:
                    self._cancellation_token.clear_active_client(client)
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            if self._cancellation_token.is_cancelled:
                raise RequestCancelled("Request cancelled") from exc
            result = None
            if not stream_state["workflow_run_id"]:
                if isinstance(exc, httpx.TimeoutException):
                    raise MetricClientError(
                        "The indicator workflow timed out.",
                        status_code=408,
                    ) from exc
                raise MetricClientError(
                    f"The indicator workflow stream was interrupted: {exc}."
                ) from exc

        self._cancellation_token.raise_if_cancelled()
        if result is not None:
            return result

        workflow_run_id = stream_state["workflow_run_id"]
        if not workflow_run_id:
            raise MetricClientError(
                "The indicator workflow stream ended before Dify returned "
                "a workflow run ID."
            )

        self._emit(
            event_callback,
            "status",
            "连接已中断，正在获取云端指标结果",
        )
        return self._poll_workflow_result(
            workflow_run_id,
            task_id=stream_state["task_id"],
            deadline=time.monotonic() + self._timeout,
        )

    def _collect_workflow_stream(
        self,
        response: httpx.Response,
        *,
        stream_state: dict[str, str],
        event_callback: MetricEventCallback | None = None,
    ) -> dict[str, Any] | None:
        """Collect Dify Workflow SSE events until workflow_finished."""
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
                continue
            if not isinstance(chunk, dict):
                continue

            event = str(chunk.get("event") or "")
            data = chunk.get("data") or {}
            if not isinstance(data, dict):
                data = {}

            task_id = str(chunk.get("task_id") or "").strip()
            if task_id:
                stream_state["task_id"] = task_id

            workflow_run_id = str(
                chunk.get("workflow_run_id")
                or (
                    data.get("id")
                    if event == "workflow_started"
                    else ""
                )
                or ""
            ).strip()
            if workflow_run_id:
                stream_state["workflow_run_id"] = workflow_run_id

            if event == "workflow_started":
                self._emit(
                    event_callback,
                    "status",
                    "云端指标工作流已启动",
                )
                continue

            if event == "node_started":
                title = str(data.get("title") or "").strip()
                if title:
                    self._emit(
                        event_callback,
                        "status",
                        f"正在执行：{title}",
                    )
                continue

            if event == "node_finished":
                if str(data.get("status") or "").lower() == "failed":
                    raise MetricClientError(
                        str(data.get("error") or "Workflow node failed"),
                        status_code=400,
                    )
                continue

            if event == "workflow_finished":
                workflow_run_id = str(
                    stream_state["workflow_run_id"]
                    or data.get("id")
                    or ""
                )
                return {
                    "workflow_run_id": workflow_run_id,
                    "task_id": stream_state["task_id"],
                    "data": dict(data),
                }

        return None

    def _poll_workflow_result(
        self,
        workflow_run_id: str,
        *,
        task_id: str,
        deadline: float,
    ) -> dict[str, Any]:
        """Recover a started workflow by querying its run instead of replaying it."""
        terminal_statuses = {
            "succeeded",
            "failed",
            "stopped",
            "partial-succeeded",
            "paused",
        }
        transient_statuses = {404, 429, 500, 502, 503, 504}

        while time.monotonic() < deadline:
            self._cancellation_token.raise_if_cancelled()
            try:
                detail = self._request_json(
                    "GET",
                    f"workflows/run/{workflow_run_id}",
                    retryable=False,
                )
            except MetricClientError as exc:
                if exc.status_code not in transient_statuses:
                    raise
                self._cancellation_token.wait(1.0)
                continue

            status = str(detail.get("status") or "").strip().lower()
            if status in terminal_statuses:
                return {
                    "workflow_run_id": str(
                        detail.get("id") or workflow_run_id
                    ),
                    "task_id": task_id,
                    "data": detail,
                }

            self._cancellation_token.wait(1.0)

        raise MetricClientError(
            "The indicator workflow timed out while waiting for the cloud "
            "result.",
            status_code=408,
        )

    def _http_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=min(30, self._timeout),
            read=self._timeout,
            write=self._timeout,
            pool=min(30, self._timeout),
        )

    @staticmethod
    def _build_user_id() -> str:
        user_name = getpass.getuser().strip() or "local"
        machine_name = platform.node().strip() or "client"
        return f"metric:{user_name}@{machine_name}"

    @staticmethod
    def _emit(
        callback: MetricEventCallback | None,
        event_type: str,
        message: str,
        **extra: object,
    ) -> None:
        if callback is None:
            return
        event: dict[str, object] = {
            "type": event_type,
            "message": message,
        }
        event.update(extra)
        callback(event)
