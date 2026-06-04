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
from dify.client import DifyClient, DifyClientError
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
        self._client = DifyClient()
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
        
        # ── 步骤 2：首次调用 Dify ──
        try:
            code = self._call_dify(prompt)
        except DifyClientError as e:
            return WorkflowResult(
                success=False,
                code="",
                execution=None,
                error=f"❌ Dify API 错误: {str(e)}",
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

            # ── 执行失败，请求 Dify 修复 ──
            retry_prompt = self._prompt_builder.build_error_retry_prompt(
                code, execution_result.stderr, user_query
            )

            try:
                code = self._call_dify(retry_prompt)
                retries += 1
            except DifyClientError as e:
                return WorkflowResult(
                    success=False,
                    code=code,
                    execution=execution_result,
                    error=f"❌ 重试时 Dify API 错误: {str(e)}",
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

    def _call_dify(self, prompt: dict) -> str:
        """
        调用 Dify Webhook 生成代码。
        
        Args:
            prompt: 包含 system、context、query 的字典
            
        Returns:
            生成的 Python 代码
            
        Raises:
            DifyClientError: API 调用失败
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

        # 调用 Dify Webhook
        response = self._client.post_webhook(payload)

        # 从响应中提取代码
        code = self._client.extract_code_from_response(response)

        if not code:
            raise DifyClientError(400, "Dify 未返回代码")

        return code