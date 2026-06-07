"""
dify/workflow.py
────────────────
完整的分析工作流编排。
协调：Dify API → 代码验证 → 执行 → 错误重试。
"""

from __future__ import annotations
from dataclasses import dataclass
from core.preprocessor import FileMeta
from core.prompt_builder import PromptBuilder
from core.code_validator import CodeValidator, SecurityError
from core.executor import Executor, ExecutionResult
from llm import LLMError, get_client
from config.settings import settings


@dataclass
class WorkflowResult:
    """工作流执行结果"""
    success: bool
    code: str
    execution: ExecutionResult | None
    error: str = ""
    retries_used: int = 0


class AnalysisWorkflow:
    """数据分析工作流"""

    def __init__(self) -> None:
        # 按 settings.LLM_PROVIDER 选择 Gemini 或 Dify 客户端
        # 两者都实现统一接口 generate_code(prompt) -> str
        self._client = get_client()
        self._validator = CodeValidator()
        self._executor = Executor()
        self._prompt_builder = PromptBuilder()
        self._max_retries = settings.MAX_CODE_RETRIES

    def run(
        self,
        files_meta: list[FileMeta],
        user_query: str,
    ) -> WorkflowResult:
        """
        执行完整的分析流程。
        
        流程：
          1. 构建提示词
          2. 调用 Dify 生成代码
          3. 验证代码安全性
          4. 执行代码
          5. 如果失败，自动重试（最多 3 次）
        
        Args:
            files_meta: 文件元数据列表
            user_query: 用户的分析问题
            
        Returns:
            WorkflowResult 对象（无论成功或失败都不抛异常）
        """
        # ── 步骤 1：构建提示词 ──
        prompt = self._prompt_builder.build_analysis_prompt(
            files_meta, user_query
        )
        
        # ── 步骤 2：首次调用 LLM ──
        try:
            code = self._call_llm(prompt)
        except LLMError as e:
            return WorkflowResult(
                success=False,
                code="",
                execution=None,
                error=f"❌ LLM API 错误: {str(e)}",
            )

        retries = 0

        # ── 步骤 3-5：验证、执行、重试循环 ──
        while retries <= self._max_retries:
            
            # 验证代码安全性
            try:
                validation = self._validator.validate(code)
                validation.raise_if_unsafe()
            except SecurityError as e:
                return WorkflowResult(
                    success=False,
                    code=code,
                    execution=None,
                    error=f"❌ 安全检查失败: {str(e)}",
                )

            # 执行代码
            execution_result = self._executor.run(code, files_meta)

            # 如果成功，直接返回
            if execution_result.success:
                return WorkflowResult(
                    success=True,
                    code=code,
                    execution=execution_result,
                    retries_used=retries,
                )

            # 如果已达到重试次数上限，返回失败
            if retries >= self._max_retries:
                return WorkflowResult(
                    success=False,
                    code=code,
                    execution=execution_result,
                    error=f"❌ 执行失败，已重试 {retries} 次",
                    retries_used=retries,
                )

            # ── 执行失败，请求 LLM 修复 ──
            retry_prompt = self._prompt_builder.build_error_retry_prompt(
                code, execution_result.stderr, user_query
            )

            try:
                code = self._call_llm(retry_prompt)
                retries += 1
            except LLMError as e:
                return WorkflowResult(
                    success=False,
                    code=code,
                    execution=execution_result,
                    error=f"❌ 重试时 LLM API 错误: {str(e)}",
                    retries_used=retries,
                )

        # 不应该到达这里，但以防万一
        return WorkflowResult(
            success=False,
            code=code,
            execution=None,
            error="❌ 未知错误",
            retries_used=retries,
        )

    # ─────────────────────────────────────────────────────────────────

    def _call_llm(self, prompt: dict) -> str:
        """
        调用所选 LLM 提供商（Gemini 或 Dify）生成代码。

        Args:
            prompt: 包含 system、context、query 的字典

        Returns:
            生成的 Python 代码

        Raises:
            LLMError: API 调用失败或未返回代码
        """
        return self._client.generate_code(prompt)