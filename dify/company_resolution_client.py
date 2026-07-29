"""Dify client for the deterministic company-resolution workflow."""

from __future__ import annotations

import getpass
import platform
from collections.abc import Callable
from typing import Any

import httpx

from config.settings import settings
from core.company_resolution import (
    CompanyResolutionContractError,
    CompanyResolutionResult,
)
from dify.reliable_workflow import (
    ReliableWorkflowRunner,
    RemoteRunHandle,
    WorkflowTransportError,
)
from llm.cancellation import CancellationToken


CompanyResolutionEventCallback = Callable[[dict[str, object]], None]


class CompanyResolutionClientError(RuntimeError):
    """The company-resolution workflow request or response failed."""

    def __init__(self, message: str, *, status_code: int = 0) -> None:
        self.status_code = status_code
        super().__init__(message)


class CompanyResolutionDifyClient:
    """Invoke the small preflight workflow before metric generation."""

    QUERY_VARIABLE = "company_query"

    def __init__(
        self,
        cancellation_token: CancellationToken | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        settings.reload()
        self._base_url = settings.DIFY_COMPANY_RESOLUTION_BASE_URL.rstrip("/")
        self._api_key = settings.DIFY_COMPANY_RESOLUTION_API_KEY
        self._timeout = settings.DIFY_COMPANY_RESOLUTION_TIMEOUT
        self._transport = transport
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

    def resolve(
        self,
        company_query: str,
        event_callback: CompanyResolutionEventCallback | None = None,
    ) -> CompanyResolutionResult:
        query = str(company_query or "").strip()
        if not query:
            raise CompanyResolutionClientError(
                "A company name is required for entity resolution."
            )
        if not self._base_url or not self._api_key:
            raise CompanyResolutionClientError(
                "The company-resolution workflow is not configured."
            )

        self._emit(event_callback, "status", "正在确认工商主体")
        payload = {
            "inputs": {self.QUERY_VARIABLE: query},
            "response_mode": "streaming",
            "user": self._build_user_id(),
        }
        response = self._request(
            payload,
            event_callback=event_callback,
        )
        try:
            result = CompanyResolutionResult.from_workflow_response(response)
        except CompanyResolutionContractError as exc:
            raise CompanyResolutionClientError(
                str(exc),
                status_code=400,
            ) from exc
        self._emit(event_callback, "status", "工商主体判定完成")
        return result

    def _request(
        self,
        payload: dict[str, Any],
        *,
        event_callback: CompanyResolutionEventCallback | None = None,
    ) -> dict[str, Any]:
        try:
            return self._workflow_runner.run(
                payload,
                event_callback=lambda event: self._handle_workflow_event(
                    event,
                    event_callback,
                ),
            )
        except WorkflowTransportError as exc:
            raise CompanyResolutionClientError(
                str(exc),
                status_code=exc.status_code,
            ) from exc

    def cancel_remote(self) -> bool:
        return self._workflow_runner.stop_remote()

    def _handle_workflow_event(
        self,
        event_payload: dict[str, Any],
        callback: CompanyResolutionEventCallback | None,
    ) -> None:
        event = str(event_payload.get("event") or "")
        data = event_payload.get("data") or {}
        if not isinstance(data, dict):
            data = {}
        if event == "workflow_started":
            self._emit(callback, "status", "Company resolution started")
        elif event == "node_started":
            title = str(data.get("title") or "").strip()
            if title:
                self._emit(callback, "status", f"Running: {title}")
        elif event == "client_reconnecting":
            self._emit(
                callback,
                "status",
                "Recovering the company-resolution workflow",
            )

    @staticmethod
    def _build_user_id() -> str:
        user_name = getpass.getuser().strip() or "local"
        machine_name = platform.node().strip() or "client"
        return f"company-resolution:{user_name}@{machine_name}"

    @staticmethod
    def _emit(
        callback: CompanyResolutionEventCallback | None,
        event_type: str,
        message: str,
    ) -> None:
        if callback is None:
            return
        callback({"type": event_type, "message": message})
