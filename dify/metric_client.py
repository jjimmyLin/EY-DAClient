"""Dedicated Dify client for business-analysis indicator generation."""

from __future__ import annotations

import getpass
import mimetypes
import platform
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
from dify.reliable_workflow import (
    ReliableWorkflowRunner,
    RemoteRunHandle,
    WorkflowTransportError,
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
        self._run_handle = RemoteRunHandle()
        self._workflow_runner = ReliableWorkflowRunner(
            base_url=self._base_url,
            api_key=self._api_key,
            timeout=self._timeout,
            cancellation_token=self._cancellation_token,
            transport=self._transport,
            handle=self._run_handle,
        )

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
            result = MetricDiscoveryResult.from_workflow_response(
                response,
                regulatory_analysis_required=(
                    request.regulatory_analysis_enabled
                ),
                required_metric_families=(
                    request.required_metric_families()
                ),
                forbidden_metric_families=(
                    request.forbidden_metric_families()
                ),
            )
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
        try:
            return self._workflow_runner.run(
                payload,
                event_callback=lambda event: self._handle_reliable_event(
                    event,
                    event_callback,
                ),
            )
        except WorkflowTransportError as exc:
            raise MetricClientError(
                str(exc),
                status_code=exc.status_code,
            ) from exc

    def cancel_remote(self) -> bool:
        """Best-effort cancellation for a Dify task whose task ID is known."""
        return self._workflow_runner.stop_remote()

    def _handle_reliable_event(
        self,
        event_payload: dict[str, Any],
        callback: MetricEventCallback | None,
    ) -> None:
        event = str(event_payload.get("event") or "")
        data = event_payload.get("data") or {}
        if not isinstance(data, dict):
            data = {}
        remote = {
            "task_id": str(event_payload.get("task_id") or ""),
            "workflow_run_id": str(
                event_payload.get("workflow_run_id") or ""
            ),
        }
        if event == "workflow_started":
            self._emit(
                callback,
                "status",
                "云端指标工作流已启动",
                **remote,
            )
        elif event == "node_started":
            title = str(data.get("title") or "").strip()
            if title:
                self._emit(
                    callback,
                    "status",
                    "正在执行：" + title,
                    **remote,
                )
        elif event == "client_reconnecting":
            self._emit(
                callback,
                "status",
                "连接已中断，正在恢复云端指标任务",
                **remote,
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
