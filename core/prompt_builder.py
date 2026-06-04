"""
core/prompt_builder.py
──────────────────────
构建发送给 Dify 的提示词。
纯函数，无副作用。
"""

from __future__ import annotations
import json
from core.preprocessor import FileMeta


# ── 系统提示词模板 ────────────────────────────────────────────
_SYSTEM_PROMPT = """你是一个Python数据分析专家。

接收到的context包含：
- 数据集的shape（行数、列数）
- 列名和数据类型
- 样本数据
- 统计信息

根据这些信息和用户的分析需求，生成对应的Python代码。

代码会通过字典 `dfs` 访问数据：
- 键是文件名（例如 "sales.xlsx"）
- 值是字典，格式为：sheet_name → pandas.DataFrame
- 访问示例：`df = dfs["sales.xlsx"]["Sheet1"]`

要求：
1. 所有结果必须打印到stdout
2. 如果需要图表，使用matplotlib并调用 plt.show()
3. 禁止使用：os、subprocess、sys、open()、requests、socket、pickle、__builtins__

重要：只输出纯Python代码，不要markdown符号(```)，不要任何解释和注释。"""


class PromptBuilder:
    """提示词构建器"""
    
    @staticmethod
    def build_analysis_prompt(
        files_meta: list[FileMeta],
        user_query: str,
    ) -> dict:
        """
        构建数据分析提示词。
        
        Args:
            files_meta: 文件元数据列表
            user_query: 用户的分析问题
            
        Returns:
            包含 system、context、query 的字典，可直接传给 Dify API
        """
        # 构建上下文块
        context_blocks = []
        for fm in files_meta:
            context_blocks.append(
                f"=== 文件: {fm.file_name} ({fm.file_size_kb:.1f} KB) ===\n"
                + json.dumps(fm.to_prompt_dict(), ensure_ascii=False, indent=2)
            )

        context = "\n\n".join(context_blocks)

        return {
            "system": _SYSTEM_PROMPT,
            "context": context,
            "query": user_query,
        }

    @staticmethod
    def build_error_retry_prompt(
        original_code: str,
        error_message: str,
        user_query: str,
    ) -> dict:
        """
        构建错误重试提示词。
        当代码执行失败时，将失败信息发送回 Dify 要求修复。
        
        Args:
            original_code: 失败的代码
            error_message: 错误信息（traceback）
            user_query: 原始用户问题
            
        Returns:
            修复提示词
        """
        return {
            "system": _SYSTEM_PROMPT,
            "context": (
                f"以下代码在执行时失败了。\n\n"
                f"--- 失败的代码 ---\n{original_code}\n\n"
                f"--- 错误信息 ---\n{error_message}"
            ),
            "query": (
                f"请修复上面的代码使其能正确执行。\n"
                f"原始任务：{user_query}"
            ),
        }

    @staticmethod
    def build_report_prompt(
        analysis_output: str,
        user_query: str,
    ) -> dict:
        """
        构建报告生成提示词（Sprint 3）。
        
        Args:
            analysis_output: 分析结果的stdout
            user_query: 用户的原始问题
            
        Returns:
            报告生成提示词
        """
        return {
            "system": (
                "你是一个商务分析师。"
                "将原始分析结果转化为专业的、易读的报告。"
                "包括：概述、关键发现、解释、可行建议。"
            ),
            "query": (
                f"用户的问题：{user_query}\n\n"
                f"分析结果：\n{analysis_output}\n\n"
                f"请生成一份专业的分析报告。"
            ),
        }