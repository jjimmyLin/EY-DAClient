"""
llm/deepseek_client.py
──────────────────────
DeepSeek OpenAI-compatible HTTP client.

Implements the shared interface: ``generate_code(prompt: dict) -> str``.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable

import httpx

from config.settings import settings
from llm import LLMError

logger = logging.getLogger(__name__)
WorkflowEvent = dict[str, object]
EventCallback = Callable[[WorkflowEvent], None]


class DeepSeekClientError(LLMError):
    """DeepSeek API error."""

    def __init__(self, status_code: int, body: str) -> None:
        self.body = body
        super().__init__(
            f"DeepSeek API 错误 {status_code}: {body[:300]}",
            status_code=status_code,
        )


_FALLBACK_STATUS_CODES = (429, 403, 503)


class DeepSeekClient:
    """DeepSeek chat completions client."""

    def __init__(self) -> None:
        self._base_url = settings.DEEPSEEK_BASE_URL.rstrip("/")
        self._api_key = settings.DEEPSEEK_API_KEY
        self._model = settings.DEEPSEEK_MODEL
        self._timeout = settings.DEEPSEEK_TIMEOUT
        self._max_retries = 3
        self._retry_delay = 1
        self._available_models: list[str] | None = None
        self._current_model = self._model

    def check_available_models(self) -> list[dict]:
        """Return configured DeepSeek candidates.

        DeepSeek's public docs do not require probing for this workflow, so this
        returns configured candidates as selectable/available metadata.
        """
        candidates = self._build_model_list(probe=False)
        return [
            {
                "name": model,
                "available": True,
                "thinking": settings.DEEPSEEK_THINKING_ENABLED,
            }
            for model in candidates
        ]

    def set_model(self, model: str) -> None:
        self._model = model
        self._current_model = model
        self._available_models = [model]
        logger.info("用户手动选定 DeepSeek 模型: %s", model)

    def generate_code(
        self,
        prompt: dict,
        event_callback: EventCallback | None = None,
    ) -> str:
        logger.info("=== 开始 DeepSeek 代码生成 ===")
        logger.info("上下文长度: %d 字符", len(prompt.get("context", "")))
        logger.info("用户查询: %s", prompt.get("query", ""))
        self._emit(event_callback, "status", "DeepSeek request started")

        if settings.DEEPSEEK_STREAM:
            text = self._stream_chat_completion(prompt, event_callback)
        else:
            response = self._post_chat_completion(prompt, event_callback)
            text = self._extract_text(response, event_callback)

        code = self._strip_code_fences(text)

        if not code:
            raise DeepSeekClientError(400, "DeepSeek 未返回代码内容")

        self._emit(event_callback, "status", "DeepSeek generation completed")
        logger.info("=== DeepSeek 生成完成 (模型: %s) ===\n%s", self._current_model, code)
        return code

    def _build_model_list(self, probe: bool = True) -> list[str]:
        if self._available_models is not None:
            return self._available_models

        candidates: list[str] = []
        seen: set[str] = set()
        for model in [self._model] + settings.DEEPSEEK_MODEL_FALLBACKS:
            if model and model not in seen:
                seen.add(model)
                candidates.append(model)

        self._available_models = candidates
        return candidates

    def _post_chat_completion(
        self,
        prompt: dict,
        event_callback: EventCallback | None = None,
    ) -> dict:
        settings.validate_selected_provider()

        last_error: DeepSeekClientError | None = None
        for model in self._build_model_list():
            try:
                return self._try_model(prompt, model, stream=False, event_callback=event_callback)
            except DeepSeekClientError as e:
                if e.status_code in _FALLBACK_STATUS_CODES:
                    logger.warning(
                        "DeepSeek 模型 %s 不可用 (HTTP %s)，尝试下一个模型...",
                        model,
                        e.status_code,
                    )
                    last_error = e
                    continue
                raise

        raise last_error or DeepSeekClientError(0, "DeepSeek 无可用模型")

    def _stream_chat_completion(
        self,
        prompt: dict,
        event_callback: EventCallback | None,
    ) -> str:
        settings.validate_selected_provider()

        last_error: DeepSeekClientError | None = None
        for model in self._build_model_list():
            try:
                return self._try_model_stream(prompt, model, event_callback)
            except DeepSeekClientError as e:
                if e.status_code in _FALLBACK_STATUS_CODES:
                    logger.warning(
                        "DeepSeek 流式模型 %s 不可用 (HTTP %s)，尝试下一个模型...",
                        model,
                        e.status_code,
                    )
                    last_error = e
                    continue
                raise

        raise last_error or DeepSeekClientError(0, "DeepSeek 无可用模型")

    def _try_model(
        self,
        prompt: dict,
        model: str,
        stream: bool,
        event_callback: EventCallback | None,
    ) -> dict:
        self._current_model = model
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = self._build_request_body(prompt, model, stream)

        for attempt in range(self._max_retries):
            try:
                self._emit(
                    event_callback,
                    "status",
                    f"Sending DeepSeek request to {model}",
                )
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.post(url, headers=headers, json=body)

                if response.is_success:
                    self._emit(event_callback, "status", "DeepSeek response received")
                    return response.json()

                if response.status_code in _FALLBACK_STATUS_CODES:
                    raise DeepSeekClientError(response.status_code, response.text)

                if 400 <= response.status_code < 500:
                    raise DeepSeekClientError(response.status_code, response.text)

                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay)
                    continue
                raise DeepSeekClientError(response.status_code, response.text)

            except httpx.TimeoutException:
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay)
                    continue
                raise DeepSeekClientError(408, "请求超时")

            except httpx.RequestError as e:
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay)
                    continue
                raise DeepSeekClientError(0, str(e))

        raise DeepSeekClientError(0, "未知网络错误")

    def _try_model_stream(
        self,
        prompt: dict,
        model: str,
        event_callback: EventCallback | None,
    ) -> str:
        self._current_model = model
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = self._build_request_body(prompt, model, stream=True)
        reasoning_content = ""
        content = ""

        self._emit(event_callback, "status", f"Streaming DeepSeek response from {model}")
        try:
            with httpx.Client(timeout=self._timeout) as client:
                with client.stream("POST", url, headers=headers, json=body) as response:
                    if not response.is_success:
                        text = response.read().decode("utf-8", errors="replace")
                        raise DeepSeekClientError(response.status_code, text)

                    for line in response.iter_lines():
                        if not line:
                            continue
                        if not line.startswith("data:"):
                            continue
                        payload = line.removeprefix("data:").strip()
                        if payload == "[DONE]":
                            break
                        try:
                            chunk = json.loads(payload)
                        except json.JSONDecodeError:
                            continue

                        delta = (
                            ((chunk.get("choices") or [{}])[0]).get("delta") or {}
                        )
                        thinking_delta = delta.get("reasoning_content") or ""
                        content_delta = delta.get("content") or ""
                        tool_delta = delta.get("tool_calls")

                        if thinking_delta:
                            reasoning_content += thinking_delta
                            self._emit(
                                event_callback,
                                "thinking_delta",
                                "Receiving DeepSeek thinking",
                                delta=thinking_delta,
                                section="thinking",
                            )
                        if tool_delta:
                            self._emit(
                                event_callback,
                                "tool_delta",
                                "Receiving tool call delta",
                                delta=json.dumps(tool_delta, ensure_ascii=False),
                                section="tools",
                            )
                        if content_delta:
                            content += content_delta
                            self._emit(
                                event_callback,
                                "content_delta",
                                "Receiving generated code",
                                delta=content_delta,
                                section="code",
                            )

            if reasoning_content:
                logger.info(
                    "=== DeepSeek 思考链 (模型: %s) ===\n%s",
                    self._current_model,
                    reasoning_content,
                )
            if not content:
                raise DeepSeekClientError(400, "DeepSeek 流式响应未返回 content")
            return content

        except httpx.TimeoutException:
            raise DeepSeekClientError(408, "请求超时")
        except httpx.RequestError as e:
            raise DeepSeekClientError(0, str(e))

    def _build_request_body(self, prompt: dict, model: str, stream: bool) -> dict:
        body: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt.get("system", "")},
                {
                    "role": "user",
                    "content": (
                        f"{prompt.get('context', '')}\n\n{prompt.get('query', '')}"
                    ).strip(),
                },
            ],
            "stream": stream,
        }
        if settings.DEEPSEEK_THINKING_ENABLED:
            body["thinking"] = {"type": "enabled"}
            body["reasoning_effort"] = settings.DEEPSEEK_REASONING_EFFORT
        else:
            body["thinking"] = {"type": "disabled"}
            body["temperature"] = 0
        return body

    def _extract_text(
        self,
        response: dict,
        event_callback: EventCallback | None = None,
    ) -> str:
        try:
            choices = response.get("choices") or []
            if not choices:
                raise DeepSeekClientError(
                    400, f"响应中没有 choices: {str(response)[:300]}"
                )
            message = choices[0].get("message") or {}
            reasoning = message.get("reasoning_content") or ""
            if reasoning:
                logger.info(
                    "=== DeepSeek 思考链 (模型: %s) ===\n%s",
                    self._current_model,
                    reasoning,
                )
                self._emit(
                    event_callback,
                    "thinking_delta",
                    "DeepSeek thinking received",
                    delta=reasoning,
                    section="thinking",
                )
            text = message.get("content", "")
            if text:
                self._emit(
                    event_callback,
                    "content_delta",
                    "DeepSeek content received",
                    delta=text,
                    section="code",
                )
            if not text:
                finish_reason = choices[0].get("finish_reason")
                raise DeepSeekClientError(
                    400, f"响应文本为空 (finish_reason={finish_reason})"
                )
            return text
        except (AttributeError, TypeError) as e:
            raise DeepSeekClientError(400, f"无法解析 DeepSeek 响应: {e}")

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

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        lines = text.strip().splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
