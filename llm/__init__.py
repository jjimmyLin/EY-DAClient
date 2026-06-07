"""
llm 模块 - LLM 提供商集成（Gemini / Dify 共用）
"""


class LLMError(Exception):
    """所有 LLM 客户端错误的统一基类。

    DifyClientError 与 GeminiClientError 都继承自它，
    这样 workflow 只需捕获 LLMError 即可同时覆盖两种提供商。
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


def get_client():
    """根据 settings.LLM_PROVIDER 返回对应的 LLM 客户端实例。

    返回的客户端都实现统一接口：``generate_code(prompt: dict) -> str``。
    """
    from config.settings import settings

    provider = settings.LLM_PROVIDER

    if provider == "gemini":
        from llm.gemini_client import GeminiClient

        return GeminiClient()

    if provider == "dify":
        from dify.client import DifyClient

        return DifyClient()

    raise LLMError(f"未知的 LLM_PROVIDER: {provider!r}")


__all__ = ["LLMError", "get_client"]
