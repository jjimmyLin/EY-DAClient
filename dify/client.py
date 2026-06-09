"""
dify/client.py
Low-level HTTP client for the Dify Workflow API.
"""

from __future__ import annotations

import getpass
import json
import platform
import time
from collections.abc import Callable
from typing import Any

import httpx

from config.settings import settings
from llm import LLMError

WorkflowEvent = dict[str, object]
EventCallback = Callable[[WorkflowEvent], None]


class DifyClientError(LLMError):
    """Dify API error."""

    def __init__(self, status_code: int, body: str) -> None:
        self.body = body
        super().__init__(
            f"Dify API error {status_code}: {body[:300]}",
            status_code=status_code,
        )


class DifyClient:
    """Dify Workflow API client."""

    def __init__(self) -> None:
        self._base_url = settings.DIFY_BASE_URL.rstrip("/")
        self._api_key = settings.DIFY_API_KEY
        self._timeout = settings.DIFY_TIMEOUT
        self._max_retries = 3
        self._retry_delay = 1

    def generate_code(
        self,
        prompt: dict,
        event_callback: EventCallback | None = None,
    ) -> str:
        payload = self._build_workflow_payload(prompt)

        self._emit(event_callback, "status", "Sending Dify workflow request")
        response = self._run_workflow_streaming(payload, event_callback=event_callback)
        self._emit(event_callback, "status", "Dify workflow response received")

        code = self.extract_code_from_response(response)
        self._emit(
            event_callback,
            "content_delta",
            "Dify generated code received",
            delta=code,
            section="code",
        )

        if not code:
            raise DifyClientError(400, "Dify did not return Python code")
        return code

    def _build_workflow_payload(self, prompt: dict) -> dict:
        parameters = self.get_parameters()
        return {
            "inputs": self._build_inputs(prompt, parameters),
            "response_mode": "streaming",
            "user": self._build_user_id(),
        }

    def get_parameters(self) -> dict:
        return self.get("parameters")

    def get(self, endpoint: str) -> dict:
        return self._request_json("GET", endpoint)

    def _request_json(
        self,
        method: str,
        endpoint: str,
        payload: dict | None = None,
    ) -> dict:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/{endpoint.lstrip('/')}"

        for attempt in range(self._max_retries):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.request(
                        method,
                        url,
                        headers=headers,
                        json=payload,
                    )

                if response.is_success:
                    return response.json()
                raise DifyClientError(response.status_code, response.text)
            except httpx.TimeoutException:
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay)
                    continue
                raise DifyClientError(408, "Request timed out")
            except httpx.RequestError as exc:
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay)
                    continue
                raise DifyClientError(0, str(exc))

    def _run_workflow_streaming(
        self,
        payload: dict,
        event_callback: EventCallback | None = None,
    ) -> dict:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/workflows/run"
        timeout = httpx.Timeout(
            connect=self._timeout,
            read=self._timeout,
            write=self._timeout,
            pool=self._timeout,
        )

        for attempt in range(self._max_retries):
            try:
                with httpx.Client(timeout=timeout) as client:
                    with client.stream(
                        "POST",
                        url,
                        headers=headers,
                        json=payload,
                    ) as response:
                        if not response.is_success:
                            raise DifyClientError(response.status_code, response.text)

                        return self._collect_stream(response, event_callback)
            except httpx.TimeoutException:
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay)
                    continue
                raise DifyClientError(408, "Request timed out")
            except httpx.RequestError as exc:
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay)
                    continue
                raise DifyClientError(0, str(exc))

        raise DifyClientError(0, "Unknown Dify streaming error")

    def _collect_stream(
        self,
        response: httpx.Response,
        event_callback: EventCallback | None = None,
    ) -> dict:
        text_chunks: list[str] = []
        workflow_data: dict[str, Any] | None = None
        task_id = ""
        workflow_run_id = ""

        for raw_line in response.iter_lines():
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

            event = str(chunk.get("event", ""))
            task_id = str(chunk.get("task_id", task_id))
            workflow_run_id = str(chunk.get("workflow_run_id", workflow_run_id))
            data = chunk.get("data") or {}

            if event == "workflow_started":
                self._emit(event_callback, "status", "Dify workflow started")
                continue

            if event == "node_started":
                title = str(data.get("title", ""))
                if title:
                    self._emit(event_callback, "status", f"Running node: {title}")
                continue

            if event == "text_chunk":
                text = str(data.get("text", ""))
                if text:
                    text_chunks.append(text)
                    self._emit(
                        event_callback,
                        "content_delta",
                        "Dify text chunk received",
                        delta=text,
                        section="code",
                    )
                continue

            if event == "node_finished":
                if str(data.get("status", "")).lower() == "failed":
                    error = str(data.get("error", "Workflow node failed"))
                    raise DifyClientError(400, error)
                continue

            if event == "workflow_finished":
                workflow_data = dict(data)
                break

        if workflow_data is None:
            raise DifyClientError(400, "No workflow_finished event received from Dify")

        status = str(workflow_data.get("status", "")).lower()
        if status and status != "succeeded":
            error = str(workflow_data.get("error", "Workflow execution failed"))
            raise DifyClientError(400, error)

        outputs = workflow_data.get("outputs")
        if not outputs and text_chunks:
            outputs = {"text": "".join(text_chunks)}
        elif isinstance(outputs, str):
            outputs = {"text": outputs}

        workflow_data["outputs"] = outputs or {}
        return {
            "workflow_run_id": workflow_run_id,
            "task_id": task_id,
            "data": workflow_data,
        }

    def _build_inputs(self, prompt: dict, parameters: dict) -> dict[str, str]:
        fields = self._extract_text_fields(parameters)
        names = {field["variable"] for field in fields}
        inputs: dict[str, str] = {}

        for name in names:
            value = prompt.get(name)
            if isinstance(value, str) and value.strip():
                inputs[name] = value

        if "query" in names:
            inputs["query"] = prompt.get("query", "")
            return inputs

        combined_prompt = self._combine_prompt(prompt)
        candidate = self._pick_text_field(fields, exclude=set(inputs))
        if candidate is None:
            available = ", ".join(sorted(names)) or "<none>"
            raise DifyClientError(
                400,
                "Dify input variables are not compatible with this client. "
                f"Available text variables: {available}",
            )

        inputs[candidate] = combined_prompt
        return inputs

    @staticmethod
    def _extract_text_fields(parameters: dict) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []
        for item in parameters.get("user_input_form", []) or []:
            if not isinstance(item, dict):
                continue
            for field_type, field_cfg in item.items():
                if field_type not in ("text-input", "paragraph"):
                    continue
                if not isinstance(field_cfg, dict):
                    continue
                variable = str(field_cfg.get("variable", "")).strip()
                if not variable:
                    continue
                fields.append(
                    {
                        "type": field_type,
                        "variable": variable,
                        "required": bool(field_cfg.get("required")),
                    }
                )
        return fields

    @staticmethod
    def _pick_text_field(
        fields: list[dict[str, Any]],
        exclude: set[str],
    ) -> str | None:
        candidates = [field for field in fields if field["variable"] not in exclude]
        required = [field for field in candidates if field.get("required")]
        if len(required) == 1:
            return str(required[0]["variable"])
        if len(candidates) == 1:
            return str(candidates[0]["variable"])
        query_like = [
            field for field in candidates
            if str(field["variable"]).lower() in {"query", "prompt", "input"}
        ]
        if len(query_like) == 1:
            return str(query_like[0]["variable"])
        return None

    @staticmethod
    def _combine_prompt(prompt: dict) -> str:
        return (
            "System instructions:\n"
            f"{prompt.get('system', '').strip()}\n\n"
            "Dataset context:\n"
            f"{prompt.get('context', '').strip()}\n\n"
            "User request:\n"
            f"{prompt.get('query', '').strip()}"
        ).strip()

    @staticmethod
    def _build_user_id() -> str:
        user_name = getpass.getuser().strip() or "local"
        machine_name = platform.node().strip() or "client"
        return f"{user_name}@{machine_name}"

    def extract_code_from_response(self, response: dict) -> str:
        data = response.get("data") or {}
        status = str(data.get("status", "")).lower()
        if status and status != "succeeded":
            raise DifyClientError(400, str(data.get("error", "Workflow failed")))

        outputs = data.get("outputs") or {}
        code = ""

        if isinstance(outputs, dict):
            code = (
                outputs.get("code")
                or outputs.get("result")
                or outputs.get("answer")
                or outputs.get("text")
                or ""
            )
            if not code:
                code = next(
                    (
                        value for value in outputs.values()
                        if isinstance(value, str) and value.strip()
                    ),
                    "",
                )
        elif isinstance(outputs, str):
            code = outputs

        code = code or response.get("answer") or response.get("code") or ""
        if not code:
            error = str(data.get("error", "Response did not contain Python code"))
            raise DifyClientError(400, error)

        return self._strip_code_fences(code)

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        lines = text.strip().splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()

    @staticmethod
    def _emit(
        event_callback: EventCallback | None,
        event_type: str,
        message: str,
        **extra: object,
    ) -> None:
        if event_callback is None:
            return
        event: WorkflowEvent = {"type": event_type, "message": message}
        event.update(extra)
        event_callback(event)
