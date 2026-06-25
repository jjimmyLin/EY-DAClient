"""
llm/gemini_client.py
────────────────────
Google AI Studio (Gemini) 的低级 HTTP 客户端。
通过 generateContent REST API 生成 Python 代码。

接口与 DifyClient 保持一致：``generate_code(prompt: dict) -> str``。

功能：
- 自动模型回退：429/403/503 时按优先级尝试下一个模型。
- 启动时探测可用模型，过滤掉不可用的。
- 按模型启用/关闭 thinking（2.5 系列启用，2.0 系列不支持）。
- 全链路日志：系统提示词、思考链、生成代码、回退事件。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

import httpx

from config.settings import settings
from llm import LLMError
from llm.cancellation import CancellationToken, RequestCancelled

logger = logging.getLogger(__name__)
WorkflowEvent = dict[str, object]
EventCallback = Callable[[WorkflowEvent], None]


class GeminiClientError(LLMError):
    """Gemini API 错误"""

    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(
            f"Gemini API 错误 {status_code}: {body[:300]}",
            status_code=status_code,
        )
        self.body = body


_FALLBACK_STATUS_CODES = (429, 403, 503)


class GeminiClient:
    """Gemini HTTP 客户端（支持多模型回退）"""

    def __init__(
        self,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        self._base_url = settings.GEMINI_BASE_URL.rstrip("/")
        self._api_key = settings.GEMINI_API_KEY
        self._model = settings.GEMINI_MODEL
        self._timeout = settings.GEMINI_TIMEOUT
        self._max_retries = 3
        self._retry_delay = 1
        self._current_model = self._model
        self._available_models: list[str] | None = None
        self._cancellation_token = cancellation_token or CancellationToken()

    # =========================================================
    # Public API
    # =========================================================

    def check_available_models(self) -> list[dict]:
        """探测所有候选模型的可用性，返回详情列表。

        Returns:
            [{"name": "gemini-2.5-flash", "available": True, "thinking": True}, ...]
        """
        candidates: list[str] = []
        seen: set[str] = set()
        for m in [self._model] + settings.GEMINI_MODEL_FALLBACKS:
            if m not in seen:
                seen.add(m)
                candidates.append(m)

        logger.info("=== 探测可用模型 ===")
        results: list[dict] = []
        for m in candidates:
            available = self._check_model_available(m)
            results.append({
                "name": m,
                "available": available,
                "thinking": m.startswith(settings.GEMINI_THINKING_MODELS),
            })
        logger.info("探测结果: %s", results)
        return results

    def set_model(self, model: str) -> None:
        """用户手动选定模型后调用，跳过自动回退逻辑。"""
        self._model = model
        self._current_model = model
        self._available_models = [model]
        logger.info("用户手动选定模型: %s", model)

    def generate_code(
        self,
        prompt: dict,
        event_callback: EventCallback | None = None,
    ) -> str:
        """根据提示词生成 Python 代码。

        Args:
            prompt: 包含 system、context、query 的字典。

        Returns:
            生成的 Python 代码字符串（已去除 markdown 代码块符号）。
        """
        from core.prompt_builder import PromptBuilder

        request_prompt = dict(prompt)
        request_prompt["system"] = PromptBuilder.devops_system_prompt(
            str(prompt.get("task_type") or "analysis")
        )

        logger.info("=== 开始代码生成 ===")
        logger.info("系统提示词:\n%s", request_prompt["system"])
        logger.info("上下文长度: %d 字符", len(prompt.get("context", "")))
        logger.info("用户查询: %s", prompt.get("query", ""))

        self._emit(event_callback, "status", "Sending Gemini request")
        response = self._post_generate_content(request_prompt)
        self._emit(event_callback, "status", "Gemini response received")
        text, thinking = self._extract_text(response)

        if thinking:
            logger.info("=== 思考链 (模型: %s) ===\n%s", self._current_model, thinking)
            self._emit(
                event_callback,
                "thinking_delta",
                "Gemini thinking received",
                delta=thinking,
                section="thinking",
            )

        code = self._strip_code_fences(text)

        if not code:
            raise GeminiClientError(400, "Gemini 未返回代码内容")

        logger.info("=== 生成完成 (模型: %s) ===\n%s", self._current_model, code)
        self._emit(
            event_callback,
            "content_delta",
            "Gemini generated code received",
            delta=code,
            section="code",
        )
        return code

    def generate_analysis(
        self,
        prompt: dict,
        event_callback: EventCallback | None = None,
    ) -> dict:
        """DevOps adapter that follows the same plan-then-code contract as Dify."""
        task_type = str(prompt.get("task_type") or "analysis")
        if task_type != "analysis":
            return {
                "code": self.generate_code(
                    prompt,
                    event_callback=event_callback,
                ),
                "plan": {},
            }

        plan_prompt = dict(prompt)
        plan_prompt["system"] = (
            "Return one valid JSON analysis plan only. Parse context as JSON. "
            "Use only supplied dataset_id, sheet_id, columns, and relationship "
            "evidence. Required top-level keys: task_summary, requirements, "
            "warnings, clarification_required, clarification_question, "
            "clarification_options. Each requirement needs id, objective, "
            "sources, joins, grain, formula, output_type. Never guess an "
            "ambiguous cross-dataset relationship; request clarification."
        )
        self._emit(event_callback, "status", "Generating DevOps analysis plan")
        response = self._post_generate_content(plan_prompt)
        plan_text, _ = self._extract_text(response)
        plan = self._parse_json_object(plan_text)
        if plan.get("clarification_required"):
            return {
                "code": "",
                "plan": plan,
                "clarification_required": True,
                "clarification_question": str(
                    plan.get("clarification_question") or ""
                ),
                "clarification_options": plan.get(
                    "clarification_options",
                    [],
                ),
            }

        code_prompt = dict(prompt)
        code_prompt["context"] = (
            f"{prompt.get('context', '')}\n\n"
            "CONFIRMED_ANALYSIS_PLAN="
            + json.dumps(plan, ensure_ascii=False, separators=(",", ":"))
        )
        code = self.generate_code(
            code_prompt,
            event_callback=event_callback,
        )
        return {
            "code": code,
            "plan": plan,
            "clarification_required": False,
        }

    @staticmethod
    def _parse_json_object(text: str) -> dict:
        cleaned = str(text).strip()
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise GeminiClientError(
                400,
                "DevOps analysis planner did not return JSON",
            )
        try:
            payload = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise GeminiClientError(
                400,
                f"Invalid DevOps analysis plan JSON: {exc}",
            ) from exc
        if not isinstance(payload, dict):
            raise GeminiClientError(400, "DevOps analysis plan must be an object")
        return payload

    # =========================================================
    # Model Fallback
    # =========================================================

    def _check_model_available(self, model: str) -> bool:
        """通过 GET models/{model} 检查模型是否可用。"""
        self._cancellation_token.raise_if_cancelled()
        settings.validate_gemini_api_key(self._api_key)
        url = f"{self._base_url}/models/{model}"
        headers = {"x-goog-api-key": self._api_key}
        try:
            with httpx.Client(timeout=10) as client:
                self._cancellation_token.set_active_client(client)
                try:
                    resp = client.get(url, headers=headers)
                finally:
                    self._cancellation_token.clear_active_client(client)
            self._cancellation_token.raise_if_cancelled()
            if resp.is_success:
                logger.info("模型可用: %s", model)
                return True
            logger.warning("模型不可用: %s (HTTP %d)", model, resp.status_code)
            return False
        except (httpx.TimeoutException, httpx.RequestError) as e:
            if self._cancellation_token.is_cancelled:
                raise RequestCancelled("Request cancelled") from e
            logger.warning("模型探测失败: %s (%s)", model, e)
            return False

    def _build_model_list(self) -> list[str]:
        """构建模型尝试顺序：主模型在前，其余候选按配置排列，去重。
        首次调用时会探测可用性并缓存结果。"""
        if self._available_models is not None:
            return self._available_models

        candidates: list[str] = []
        seen: set[str] = set()
        for m in [self._model] + settings.GEMINI_MODEL_FALLBACKS:
            if m not in seen:
                seen.add(m)
                candidates.append(m)

        logger.info("=== 探测可用模型 ===")
        available: list[str] = []
        for m in candidates:
            self._cancellation_token.raise_if_cancelled()
            if self._check_model_available(m):
                available.append(m)

        if not available:
            logger.warning("所有候选模型均不可用，将使用完整列表尝试")
            available = candidates

        logger.info("可用模型列表: %s", available)
        self._available_models = available
        return available

    def _post_generate_content(self, prompt: dict) -> dict:
        """尝试所有候选模型，返回第一个成功的响应。"""
        settings.validate_selected_provider()
        models = self._build_model_list()
        last_error: GeminiClientError | None = None

        for model in models:
            self._cancellation_token.raise_if_cancelled()
            try:
                return self._try_model(prompt, model)
            except GeminiClientError as e:
                if e.status_code in _FALLBACK_STATUS_CODES:
                    logger.warning(
                        "模型 %s 不可用 (HTTP %d)，尝试下一个模型...",
                        model,
                        e.status_code,
                    )
                    last_error = e
                    continue
                raise

        raise last_error  # type: ignore[misc]

    def _try_model(self, prompt: dict, model: str) -> dict:
        """用指定模型调用 generateContent，包含 5xx 重试逻辑。"""
        self._cancellation_token.raise_if_cancelled()
        settings.validate_gemini_api_key(self._api_key)
        self._current_model = model
        url = f"{self._base_url}/models/{model}:generateContent"
        headers = {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
        }
        body = self._build_request_body(prompt, model)

        logger.info("调用模型: %s", model)
        logger.debug("请求体: %s", json.dumps(body, ensure_ascii=False)[:500])

        for attempt in range(self._max_retries):
            self._cancellation_token.raise_if_cancelled()
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    self._cancellation_token.set_active_client(client)
                    try:
                        response = client.post(url, headers=headers, json=body)
                    finally:
                        self._cancellation_token.clear_active_client(client)
                self._cancellation_token.raise_if_cancelled()

                if response.is_success:
                    return response.json()

                if response.status_code in _FALLBACK_STATUS_CODES:
                    raise GeminiClientError(response.status_code, response.text)

                if 400 <= response.status_code < 500:
                    raise GeminiClientError(response.status_code, response.text)

                # 其他 5xx 服务器错误：重试
                if attempt < self._max_retries - 1:
                    self._cancellation_token.wait(self._retry_delay)
                    continue
                raise GeminiClientError(response.status_code, response.text)

            except httpx.TimeoutException:
                if self._cancellation_token.is_cancelled:
                    raise RequestCancelled("Request cancelled")
                if attempt < self._max_retries - 1:
                    self._cancellation_token.wait(self._retry_delay)
                    continue
                raise GeminiClientError(408, "请求超时")

            except httpx.RequestError as e:
                if self._cancellation_token.is_cancelled:
                    raise RequestCancelled("Request cancelled") from e
                if attempt < self._max_retries - 1:
                    self._cancellation_token.wait(self._retry_delay)
                    continue
                raise GeminiClientError(0, str(e))

        raise GeminiClientError(0, "未知网络错误")

    # =========================================================
    # Request / Response
    # =========================================================

    def _build_request_body(self, prompt: dict, model: str) -> dict:
        """构建 generateContent 请求体，按模型决定是否启用 thinking。"""
        user_text = (
            f"{prompt.get('context', '')}\n\n{prompt.get('query', '')}".strip()
        )

        generation_config: dict = {"temperature": 0}

        if model.startswith("gemini-3.") and settings.GEMINI_THINKING_LEVEL:
            generation_config["thinkingConfig"] = {
                "thinkingLevel": settings.GEMINI_THINKING_LEVEL
            }
        elif model.startswith(settings.GEMINI_THINKING_MODELS):
            budget = settings.GEMINI_THINKING_BUDGET
            if budget > 0:
                generation_config["thinkingConfig"] = {
                    "thinkingBudget": budget
                }
            else:
                generation_config["thinkingConfig"] = {"thinkingBudget": 0}

        body: dict = {
            "contents": [
                {"role": "user", "parts": [{"text": user_text}]},
            ],
            "generationConfig": generation_config,
        }

        system_text = prompt.get("system", "")
        if system_text:
            body["systemInstruction"] = {"parts": [{"text": system_text}]}

        return body

    def _extract_text(self, response: dict) -> tuple[str, str]:
        """从 Gemini 响应中提取代码文本和思考链。

        Returns:
            (code_text, thinking_text) 元组。
        """
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

        thinking_parts: list[str] = []
        content_parts: list[str] = []

        for part in parts:
            if not isinstance(part, dict):
                continue
            if part.get("thought"):
                thinking_parts.append(part.get("text", ""))
            else:
                content_parts.append(part.get("text", ""))

        thinking_text = "\n".join(thinking_parts).strip()
        text = "".join(content_parts).strip()

        if not text:
            raise GeminiClientError(
                400,
                f"响应文本为空 (finishReason={finish_reason})。"
                f"若为 MAX_TOKENS，请调整 thinkingBudget 或增大输出预算。",
            )

        return text, thinking_text

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """移除 Markdown 代码块符号。"""
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
