"""
dify/client.py
Low-level HTTP client for the Dify Workflow API.
"""

from __future__ import annotations

import getpass
import json
import platform
from collections.abc import Callable
from typing import Any

import httpx

from config.settings import settings
from dify.reliable_workflow import (
    ReliableWorkflowRunner,
    RemoteRunHandle,
    WorkflowTransportError,
)
from llm import LLMError
from llm.cancellation import CancellationToken, RequestCancelled

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

    def __init__(
        self,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        self._base_url = settings.DIFY_BASE_URL.rstrip("/")
        self._api_key = settings.DIFY_API_KEY
        self._timeout = settings.DIFY_TIMEOUT
        self._max_retries = 3
        self._retry_delay = 1
        self._cancellation_token = cancellation_token or CancellationToken()
        self._run_handle = RemoteRunHandle()
        self._workflow_runner = ReliableWorkflowRunner(
            base_url=self._base_url,
            api_key=self._api_key,
            timeout=self._timeout,
            cancellation_token=self._cancellation_token,
            handle=self._run_handle,
        )

    def generate_code(
        self,
        prompt: dict,
        event_callback: EventCallback | None = None,
    ) -> str:
        return self.generate_analysis(
            prompt,
            event_callback=event_callback,
        )["code"]

    def generate_analysis(
        self,
        prompt: dict,
        event_callback: EventCallback | None = None,
    ) -> dict[str, Any]:
        payload = self._build_workflow_payload(prompt)

        self._emit(event_callback, "status", "Sending Dify workflow request")
        response = self._run_workflow_streaming(payload, event_callback=event_callback)
        self._emit(event_callback, "status", "Dify workflow response received")

        generated = self.extract_analysis_from_response(response)
        code = generated["code"]
        if generated.get("clarification_required"):
            return generated
        self._emit(
            event_callback,
            "content_delta",
            "Dify generated code received",
            delta=code,
            section="code",
        )

        if not code:
            raise DifyClientError(400, "Dify did not return Python code")
        return generated

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
            self._cancellation_token.raise_if_cancelled()
            try:
                with httpx.Client(timeout=self._timeout) as client:
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

                if response.is_success:
                    try:
                        body = response.json()
                    except ValueError as exc:
                        raise DifyClientError(
                            502,
                            "Dify returned invalid JSON.",
                        ) from exc
                    if not isinstance(body, dict):
                        raise DifyClientError(
                            502,
                            "Dify returned an invalid response.",
                        )
                    return body
                if (
                    response.status_code in {429, 500, 502, 503, 504}
                    and attempt < self._max_retries - 1
                ):
                    self._cancellation_token.wait(
                        self._retry_delay * (attempt + 1)
                    )
                    continue
                raise DifyClientError(response.status_code, response.text)
            except httpx.TimeoutException:
                if self._cancellation_token.is_cancelled:
                    raise RequestCancelled("Request cancelled")
                if attempt < self._max_retries - 1:
                    self._cancellation_token.wait(self._retry_delay)
                    continue
                raise DifyClientError(408, "Request timed out")
            except httpx.RequestError as exc:
                if self._cancellation_token.is_cancelled:
                    raise RequestCancelled("Request cancelled") from exc
                if attempt < self._max_retries - 1:
                    self._cancellation_token.wait(self._retry_delay)
                    continue
                raise DifyClientError(0, str(exc))

    def _run_workflow_streaming(
        self,
        payload: dict,
        event_callback: EventCallback | None = None,
    ) -> dict:
        """Start a workflow once and recover the same run after stream loss."""
        try:
            return self._workflow_runner.run(
                payload,
                event_callback=lambda event: self._handle_reliable_event(
                    event,
                    event_callback,
                ),
            )
        except WorkflowTransportError as exc:
            raise DifyClientError(exc.status_code, str(exc)) from exc

    def cancel_remote(self) -> bool:
        return self._workflow_runner.stop_remote()

    def _handle_reliable_event(
        self,
        event_payload: dict[str, Any],
        callback: EventCallback | None,
    ) -> None:
        event = str(event_payload.get("event") or "")
        data = event_payload.get("data") or {}
        if not isinstance(data, dict):
            data = {}
        if event == "workflow_started":
            self._emit(callback, "status", "Dify workflow started")
        elif event == "node_started":
            title = str(data.get("title") or "")
            if title:
                self._emit(callback, "status", f"Running node: {title}")
        elif event == "text_chunk":
            text = str(data.get("text") or "")
            if text:
                self._emit(
                    callback,
                    "content_delta",
                    "Dify text chunk received",
                    delta=text,
                    section="code",
                )
        elif event == "client_reconnecting":
            self._emit(
                callback,
                "status",
                "Dify connection interrupted; recovering the existing run",
            )

    def _build_inputs(self, prompt: dict, parameters: dict) -> dict[str, str]:
        fields = self._extract_input_fields(parameters)
        names = {field["variable"] for field in fields}
        contract = {"task_type", "context", "query"}
        missing = contract - names
        if missing:
            available = ", ".join(sorted(names)) or "<none>"
            raise DifyClientError(
                400,
                "Dify workflow must define task_type, context, and query inputs. "
                f"Missing: {', '.join(sorted(missing))}. Available: {available}",
            )

        limits: dict[str, int] = {}
        for field in fields:
            try:
                limits[str(field["variable"])] = int(
                    field.get("max_length") or 0
                )
            except (TypeError, ValueError):
                limits[str(field["variable"])] = 0

        values = {
            name: str(prompt.get(name) or "")
            for name in contract
        }
        query_limit = limits.get("query", 0)
        if query_limit > 0 and len(values["query"]) > query_limit:
            try:
                context_payload = json.loads(values["context"])
            except json.JSONDecodeError as exc:
                raise DifyClientError(
                    400,
                    "Long requests require JSON context so the full query can "
                    "be transferred without truncation.",
                ) from exc
            context_payload["user_query_full"] = values["query"]
            context_payload["query_transport"] = (
                "The complete user request is in context.user_query_full."
            )
            values["context"] = json.dumps(
                context_payload,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            values["query"] = (
                "Use context.user_query_full as the complete original request."
            )

        inputs: dict[str, str] = {}
        for field in fields:
            name = str(field["variable"])
            if name not in contract:
                continue
            value = values[name]
            max_length = limits.get(name, 0)
            if (
                name == "context"
                and max_length > 0
                and len(value) > max_length
            ):
                from core.prompt_builder import PromptBuilder

                try:
                    value = PromptBuilder.compact_context(value, max_length)
                except ValueError as exc:
                    raise DifyClientError(400, str(exc)) from exc
            if max_length > 0 and len(value) > max_length:
                raise DifyClientError(
                    400,
                    f"{name} exceeds the Dify input limit "
                    f"({len(value)} / {max_length} characters).",
                )
            inputs[name] = value
        return inputs

    @staticmethod
    def _extract_input_fields(parameters: dict) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []
        for item in parameters.get("user_input_form", []) or []:
            if not isinstance(item, dict):
                continue
            for field_type, field_cfg in item.items():
                if field_type not in ("text-input", "paragraph", "select"):
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
                        "max_length": field_cfg.get("max_length"),
                    }
                )
        return fields

    @staticmethod
    def _build_user_id() -> str:
        user_name = getpass.getuser().strip() or "local"
        machine_name = platform.node().strip() or "client"
        return f"{user_name}@{machine_name}"

    def extract_code_from_response(self, response: dict) -> str:
        return self.extract_analysis_from_response(response)["code"]

    def extract_analysis_from_response(self, response: dict) -> dict[str, Any]:
        data = response.get("data") or {}
        status = str(data.get("status", "")).lower()
        if status and status != "succeeded":
            raise DifyClientError(400, str(data.get("error", "Workflow failed")))

        outputs = data.get("outputs") or {}
        code = ""
        plan: Any = None

        if isinstance(outputs, dict):
            plan = outputs.get("analysis_plan") or outputs.get("plan")
            overview_keys = {
                "dataset_kind",
                "topic",
                "summary",
                "rows",
                "columns",
                "sheet_count",
                "suggestions",
            }
            if overview_keys.issubset(outputs):
                code = json.dumps(outputs, ensure_ascii=False)
            code = (
                code
                or outputs.get("code")
                or outputs.get("result")
                or outputs.get("answer")
                or outputs.get("text")
                or ""
            )
            if not code:
                code = next(
                    (
                        value
                        for key, value in outputs.items()
                        if key not in {"analysis_plan", "plan"}
                        if isinstance(value, str) and value.strip()
                    ),
                    "",
                )
        elif isinstance(outputs, str):
            code = outputs

        code = code or response.get("answer") or response.get("code") or ""
        if isinstance(code, (dict, list)):
            code = json.dumps(code, ensure_ascii=False)

        if isinstance(plan, str):
            try:
                plan = json.loads(plan)
            except json.JSONDecodeError:
                plan = {"summary": plan, "requirements": []}
        if isinstance(plan, dict) and isinstance(plan.get("structured_output"), dict):
            plan = plan["structured_output"]
        if not isinstance(plan, dict):
            plan = {}

        clarification_required = bool(
            plan.get("clarification_required")
            or (
                isinstance(outputs, dict)
                and outputs.get("clarification_required")
            )
        )
        clarification_question = str(
            plan.get("clarification_question")
            or (
                outputs.get("clarification_question", "")
                if isinstance(outputs, dict)
                else ""
            )
            or ""
        )
        clarification_options = (
            plan.get("clarification_options")
            or (
                outputs.get("clarification_options", [])
                if isinstance(outputs, dict)
                else []
            )
            or []
        )
        if clarification_required:
            return {
                "code": "",
                "plan": plan,
                "clarification_required": True,
                "clarification_question": clarification_question,
                "clarification_options": clarification_options,
            }
        if not code:
            error = str(data.get("error", "Response did not contain Python code"))
            raise DifyClientError(400, error)

        return {
            "code": self._strip_code_fences(str(code)),
            "plan": plan,
            "clarification_required": False,
            "clarification_question": "",
            "clarification_options": [],
        }

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
