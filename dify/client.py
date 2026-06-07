"""
dify/client.py
──────────────
低级 HTTP 客户端，与 Dify REST API 通信。
处理所有请求、重试、认证逻辑。
"""

from __future__ import annotations
import httpx
import time
from typing import Any
from config.settings import settings
from llm import LLMError


class DifyClientError(LLMError):
    """Dify API 错误"""

    def __init__(self, status_code: int, body: str) -> None:
        self.body = body
        super().__init__(
            f"Dify API 错误 {status_code}: {body[:200]}",
            status_code=status_code,
        )


class DifyClient:
    """Dify HTTP 客户端"""
    
    def __init__(self) -> None:
        self._base_url = settings.DIFY_BASE_URL.rstrip("/")
        self._api_key = settings.DIFY_API_KEY
        self._timeout = settings.DIFY_TIMEOUT
        self._max_retries = 3
        self._retry_delay = 1  # 秒

    def generate_code(self, prompt: dict) -> str:
        """统一接口：根据提示词生成 Python 代码。

        与 GeminiClient.generate_code 保持一致，便于 workflow 透明切换提供商。

        Args:
            prompt: 包含 system、context、query 的字典（PromptBuilder 输出）。

        Returns:
            生成的 Python 代码字符串。

        Raises:
            DifyClientError: API 调用失败或未返回代码。
        """
        payload = {
            "inputs": {
                "system": prompt.get("system", ""),
                "context": prompt.get("context", ""),
                "query": prompt.get("query", ""),
            },
            "response_mode": "blocking",
            "user": "local-client",
        }

        response = self.post_webhook(payload)
        code = self.extract_code_from_response(response)

        if not code:
            raise DifyClientError(400, "Dify 未返回代码")

        return code

    def post_webhook(self, payload: dict) -> dict:
        """
        通过 Webhook 调用 Dify 工作流。
        
        Args:
            payload: 请求体，包含 inputs（包括 system、context、query）
            
        Returns:
            解析后的 JSON 响应
            
        Raises:
            DifyClientError: API 返回错误
        """
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        
        url = settings.DIFY_WEBHOOK_URL
        
        for attempt in range(self._max_retries):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.post(url, headers=headers, json=payload)
                
                if response.is_success:
                    return response.json()
                
                # 如果不是成功响应，抛出错误
                raise DifyClientError(response.status_code, response.text)
                
            except httpx.TimeoutException:
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay)
                    continue
                raise DifyClientError(408, "请求超时")
            
            except httpx.RequestError as e:
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay)
                    continue
                raise DifyClientError(0, str(e))

    def post(self, endpoint: str, payload: dict) -> dict:
        """
        通用 POST 方法（备用，用于非 Webhook 端点）。
        
        Args:
            endpoint: API 端点，例如 "workflows/{id}/run"
            payload: 请求体
            
        Returns:
            解析后的 JSON 响应
        """
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        
        url = f"{self._base_url}/{endpoint.lstrip('/')}"
        
        for attempt in range(self._max_retries):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.post(url, headers=headers, json=payload)
                
                if response.is_success:
                    return response.json()
                
                raise DifyClientError(response.status_code, response.text)
                
            except (httpx.TimeoutException, httpx.RequestError):
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay)
                    continue
                raise DifyClientError(0, "网络错误")

    def extract_code_from_response(self, response: dict) -> str:
        """
        从 Dify 响应中提取 Python 代码。
        
        Args:
            response: Dify API 返回的响应
            
        Returns:
            Python 代码字符串
            
        Raises:
            ValueError: 无法从响应中提取代码
        """
        try:
            # 尝试不同的响应格式
            code = (
                response.get("data", {}).get("outputs", {}).get("code") or
                response.get("answer") or
                response.get("code") or
                ""
            )
            
            if not code:
                raise ValueError("响应中未找到代码")
            
            # 移除 markdown 代码块符号
            code = self._strip_code_fences(code)
            return code
            
        except (KeyError, TypeError) as e:
            raise ValueError(f"无法解析 Dify 响应: {str(e)}")

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """移除 Markdown 代码块符号"""
        lines = text.strip().splitlines()
        
        # 移除开头的 ``` 或 ```python
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        
        # 移除结尾的 ```
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        
        return "\n".join(lines).strip()