"""
llm/gemini_client.py
────────────────────
Google AI Studio (Gemini) 的低级 HTTP 客户端。
通过 generateContent REST API 生成 Python 代码。

接口与 DifyClient 保持一致：``generate_code(prompt: dict) -> str``。

实现要点（均已对照 Google 官方 REST 文档核实）：
- 认证使用 `x-goog-api-key` 请求头（而非 URL 中的 ?key=，避免泄露密钥）。
- 请求体使用 camelCase 字段：systemInstruction / contents / generationConfig。
- 关闭 thinking（thinkingConfig.thinkingBudget = 0）：gemini-2.5-flash 默认开启
  thinking，思考 token 会占用输出预算，常导致空响应 + finishReason=MAX_TOKENS。
- 健壮的响应解析，避免 IndexError，并把 finishReason 写入错误信息。
"""

from __future__ import annotations

import time

import httpx

from config.settings import settings
from llm import LLMError


class GeminiClientError(LLMError):
    """Gemini API 错误"""

    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(
            f"Gemini API 错误 {status_code}: {body[:300]}",
            status_code=status_code,
        )
        self.body = body


class GeminiClient:
    """Gemini HTTP 客户端"""

    def __init__(self) -> None:
        self._base_url = settings.GEMINI_BASE_URL.rstrip("/")
        self._api_key = settings.GEMINI_API_KEY
        self._model = settings.GEMINI_MODEL
        self._timeout = settings.GEMINI_TIMEOUT
        self._max_retries = 3
        self._retry_delay = 1  # 秒

    # =========================================================
    # Public API
    # =========================================================

    def generate_code(self, prompt: dict) -> str:
        """根据提示词生成 Python 代码。

        Args:
            prompt: 包含 system、context、query 的字典（PromptBuilder 输出）。

        Returns:
            生成的 Python 代码字符串（已去除 markdown 代码块符号）。

        Raises:
            GeminiClientError: API 调用失败或响应无有效内容。
        """
        response = self._post_generate_content(prompt)
        text = self._extract_text(response)
        code = self._strip_code_fences(text)

        if not code:
            raise GeminiClientError(400, "Gemini 未返回代码内容")

        return code

    # =========================================================
    # Internal
    # =========================================================

    def _post_generate_content(self, prompt: dict) -> dict:
        """调用 generateContent 端点，返回解析后的 JSON。"""
        url = f"{self._base_url}/models/{self._model}:generateContent"

        headers = {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
        }

        user_text = (
            f"{prompt.get('context', '')}\n\n{prompt.get('query', '')}".strip()
        )

        body: dict = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_text}],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                # 关闭 thinking，避免空响应 / MAX_TOKENS（gemini-2.5-flash 必需）
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }

        system_text = prompt.get("system", "")
        if system_text:
            body["systemInstruction"] = {"parts": [{"text": system_text}]}

        for attempt in range(self._max_retries):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.post(url, headers=headers, json=body)

                if response.is_success:
                    return response.json()

                # 4xx（密钥错误、请求格式错误等）不重试，直接抛出
                if 400 <= response.status_code < 500:
                    raise GeminiClientError(
                        response.status_code, response.text
                    )

                # 5xx 服务器错误：重试
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay)
                    continue
                raise GeminiClientError(response.status_code, response.text)

            except httpx.TimeoutException:
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay)
                    continue
                raise GeminiClientError(408, "请求超时")

            except httpx.RequestError as e:
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay)
                    continue
                raise GeminiClientError(0, str(e))

        # 理论上不会到达
        raise GeminiClientError(0, "未知网络错误")

    def _extract_text(self, response: dict) -> str:
        """从 Gemini 响应中健壮地提取文本内容。"""
        # 1) 提示词被安全策略拦截（没有 candidates）
        feedback = response.get("promptFeedback") or {}
        block_reason = feedback.get("blockReason")
        if block_reason:
            raise GeminiClientError(
                400, f"提示词被拦截 (blockReason={block_reason})"
            )

        candidates = response.get("candidates") or []
        if not candidates:
            raise GeminiClientError(
                400, f"响应中没有 candidates: {str(response)[:300]}"
            )

        candidate = candidates[0]
        finish_reason = candidate.get("finishReason")
        parts = (candidate.get("content") or {}).get("parts") or []

        # 2) 拼接全部 text 片段（而非只取第一个）
        text = "".join(
            part.get("text", "") for part in parts if isinstance(part, dict)
        ).strip()

        # 3) 空文本（常见于 finishReason=MAX_TOKENS / SAFETY）
        if not text:
            raise GeminiClientError(
                400,
                f"响应文本为空 (finishReason={finish_reason})。"
                f"若为 MAX_TOKENS，请确认已关闭 thinking 或增大输出预算。",
            )

        return text

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """移除 Markdown 代码块符号（与 DifyClient 行为一致）。"""
        lines = text.strip().splitlines()

        if lines and lines[0].startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        return "\n".join(lines).strip()
