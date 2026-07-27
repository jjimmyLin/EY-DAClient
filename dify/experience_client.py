"""Dedicated client for the Dify analysis-experience workflow."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from config.settings import settings
from llm.cancellation import CancellationToken, RequestCancelled


class ExperienceClientError(RuntimeError):
    """The experience workflow request or response contract failed."""

    def __init__(self, message: str, *, status_code: int = 0) -> None:
        self.status_code = status_code
        super().__init__(message)


@dataclass
class ExperienceSubmissionResult:
    workflow_run_id: str
    task_id: str
    knowledge_write_status: str
    candidate_count: int = 0
    uploaded_count: int = 0
    failed_count: int = 0
    outputs: dict[str, Any] = field(default_factory=dict)


class ExperienceClient:
    """Call a separate Dify app whose final nodes write to Dify Knowledge."""

    _SUCCESS_STATUSES = {
        "accepted",
        "duplicate",
        "no_candidate",
        "partial",
        "succeeded",
        "uploaded",
    }

    def __init__(
        self,
        cancellation_token: CancellationToken | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = settings.DIFY_EXPERIENCE_BASE_URL.rstrip("/")
        self._api_key = settings.DIFY_EXPERIENCE_API_KEY
        self._timeout = settings.DIFY_EXPERIENCE_TIMEOUT
        self._max_retries = 3
        self._retry_delay = 1.0
        self._transport = transport
        self._cancellation_token = cancellation_token or CancellationToken()

    def submit(
        self,
        session_payload: dict[str, Any],
    ) -> ExperienceSubmissionResult:
        if not self._base_url or not self._api_key:
            raise ExperienceClientError(
                "The experience workflow is not configured."
            )

        encoded = json.dumps(
            session_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(encoded) > settings.EXPERIENCE_MAX_PAYLOAD_CHARS:
            raise ExperienceClientError(
                "The sanitized experience payload exceeds the configured limit."
            )

        response = self._request_json(
            "POST",
            "workflows/run",
            {
                "inputs": {"session_payload": encoded},
                "response_mode": "blocking",
                "user": str(
                    (session_payload.get("actor") or {}).get("user_id")
                    or "local-client"
                ),
            },
        )
        return self._parse_submission(response)

    def _request_json(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/{endpoint.lstrip('/')}"
        timeout = httpx.Timeout(
            connect=min(30, self._timeout),
            read=self._timeout,
            write=self._timeout,
            pool=min(30, self._timeout),
        )

        for attempt in range(self._max_retries):
            self._cancellation_token.raise_if_cancelled()
            try:
                with httpx.Client(
                    timeout=timeout,
                    transport=self._transport,
                ) as client:
                    self._cancellation_token.set_active_client(client)
                    try:
                        response = client.request(
                            method,
                            url,
                            headers=headers,
                            json=payload,
                        )
                    finally:
                        self._cancellation_token.clear_active_client(client)
                self._cancellation_token.raise_if_cancelled()
            except httpx.TimeoutException as exc:
                if self._cancellation_token.is_cancelled:
                    raise RequestCancelled("Request cancelled") from exc
                if attempt < self._max_retries - 1:
                    self._cancellation_token.wait(self._retry_delay)
                    continue
                raise ExperienceClientError(
                    "The experience workflow timed out.",
                    status_code=408,
                ) from exc
            except httpx.RequestError as exc:
                if self._cancellation_token.is_cancelled:
                    raise RequestCancelled("Request cancelled") from exc
                if attempt < self._max_retries - 1:
                    self._cancellation_token.wait(self._retry_delay)
                    continue
                raise ExperienceClientError(
                    f"The experience workflow is unavailable: {exc}",
                ) from exc

            if response.is_success:
                try:
                    body = response.json()
                except ValueError as exc:
                    raise ExperienceClientError(
                        "The experience workflow returned invalid JSON."
                    ) from exc
                if not isinstance(body, dict):
                    raise ExperienceClientError(
                        "The experience workflow returned an invalid response."
                    )
                return body

            if response.status_code == 429 or response.status_code >= 500:
                if attempt < self._max_retries - 1:
                    self._cancellation_token.wait(self._retry_delay)
                    continue
            raise ExperienceClientError(
                f"Dify experience workflow error {response.status_code}: "
                f"{response.text[:300]}",
                status_code=response.status_code,
            )

        raise ExperienceClientError("The experience workflow request failed.")

    def _parse_submission(
        self,
        response: dict[str, Any],
    ) -> ExperienceSubmissionResult:
        data = response.get("data") or {}
        if not isinstance(data, dict):
            raise ExperienceClientError(
                "The experience workflow response has no data object."
            )
        workflow_status = str(data.get("status") or "").strip().lower()
        if workflow_status and workflow_status != "succeeded":
            raise ExperienceClientError(
                str(data.get("error") or "The experience workflow failed.")
            )
        outputs = data.get("outputs") or {}
        if not isinstance(outputs, dict):
            raise ExperienceClientError(
                "The experience workflow outputs must be an object."
            )

        write_status = str(
            outputs.get("knowledge_write_status")
            or outputs.get("learning_status")
            or ""
        ).strip().lower()
        if write_status not in self._SUCCESS_STATUSES:
            raise ExperienceClientError(
                "The experience workflow did not confirm a knowledge-base write. "
                "Return knowledge_write_status from the final Dify node."
            )

        return ExperienceSubmissionResult(
            workflow_run_id=str(
                response.get("workflow_run_id")
                or data.get("id")
                or ""
            ),
            task_id=str(response.get("task_id") or ""),
            knowledge_write_status=write_status,
            candidate_count=_as_int(outputs.get("candidate_count")),
            uploaded_count=_as_int(outputs.get("uploaded_count")),
            failed_count=_as_int(outputs.get("failed_count")),
            outputs=outputs,
        )


def _as_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
