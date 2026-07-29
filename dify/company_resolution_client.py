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
from llm.cancellation import CancellationToken, RequestCancelled


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
            "response_mode": "blocking",
            "user": self._build_user_id(),
        }
        response = self._request(payload)
        try:
            result = CompanyResolutionResult.from_workflow_response(response)
        except CompanyResolutionContractError as exc:
            raise CompanyResolutionClientError(
                str(exc),
                status_code=400,
            ) from exc
        self._emit(event_callback, "status", "工商主体判定完成")
        return result

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/workflows/run"
        self._cancellation_token.raise_if_cancelled()
        try:
            with httpx.Client(
                timeout=self._http_timeout(),
                transport=self._transport,
            ) as client:
                self._cancellation_token.set_active_client(client)
                try:
                    response = client.post(
                        url,
                        headers=headers,
                        json=payload,
                    )
                finally:
                    self._cancellation_token.clear_active_client(client)
        except httpx.TimeoutException as exc:
            if self._cancellation_token.is_cancelled:
                raise RequestCancelled("Request cancelled") from exc
            raise CompanyResolutionClientError(
                "The company-resolution workflow timed out.",
                status_code=408,
            ) from exc
        except httpx.RequestError as exc:
            if self._cancellation_token.is_cancelled:
                raise RequestCancelled("Request cancelled") from exc
            raise CompanyResolutionClientError(
                f"The company-resolution workflow is unavailable: {exc}."
            ) from exc

        self._cancellation_token.raise_if_cancelled()
        if not response.is_success:
            raise CompanyResolutionClientError(
                f"Dify company-resolution workflow error "
                f"{response.status_code}: {response.text[:300]}",
                status_code=response.status_code,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise CompanyResolutionClientError(
                "The company-resolution workflow returned invalid JSON."
            ) from exc
        if not isinstance(body, dict):
            raise CompanyResolutionClientError(
                "The company-resolution workflow returned an invalid response."
            )
        return body

    def _http_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=min(20, self._timeout),
            read=self._timeout,
            write=min(30, self._timeout),
            pool=min(20, self._timeout),
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
