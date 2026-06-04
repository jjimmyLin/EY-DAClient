"""
output/formatter.py
───────────────────
转换执行结果为 UI 友好的格式。
UI 层只消费 FormattedOutput，不直接处理原始输出。
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from core.executor import ExecutionResult


@dataclass
class FormattedOutput:
    """格式化后的分析结果"""
    text_blocks: list[str]              # 输出文本行
    table_data: list[dict] | None       # 检测到的表格数据
    elapsed_sec: float                  # 执行耗时
    retries_used: int = 0               # 使用的重试次数
    code: str = ""                      # 执行的代码
    error: str = ""                     # 错误信息

    @property
    def has_table(self) -> bool:
        """是否包含表格数据"""
        return bool(self.table_data)

    @property
    def has_error(self) -> bool:
        """是否出错"""
        return bool(self.error)

    @property
    def summary(self) -> str:
        """执行摘要"""
        if self.has_error:
            return f"❌ 失败 (重试 {self.retries_used}×)"
        return f"✅ 成功 ({self.elapsed_sec}s)"


class Formatter:
    """输出格式化器"""

    def format(
        self,
        execution: ExecutionResult | None,
        code: str = "",
        error: str = "",
        retries_used: int = 0,
    ) -> FormattedOutput:
        """
        将执行结果转换为格式化输出。
        
        Args:
            execution: ExecutionResult 对象
            code: 执行的代码
            error: 额外的错误信息
            retries_used: 重试次数
            
        Returns:
            FormattedOutput 对象
        """
        if execution is None:
            return FormattedOutput(
                text_blocks=[],
                table_data=None,
                elapsed_sec=0,
                code=code,
                error=error or "未执行",
                retries_used=retries_used,
            )

        # 分割输出行
        text_blocks = [
            line for line in execution.stdout.strip().splitlines()
            if line.strip()
        ]

        # 尝试检测表格
        table_data = self._try_parse_table(execution.stdout)

        return FormattedOutput(
            text_blocks=text_blocks,
            table_data=table_data,
            elapsed_sec=execution.elapsed_sec,
            code=code,
            error=execution.stderr if not execution.success else error,
            retries_used=retries_used,
        )

    @staticmethod
    def _try_parse_table(text: str) -> list[dict] | None:
        """
        尝试检测并解析表格。
        简单启发式：查找看起来像 pandas 输出的列对齐文本。
        
        Sprint 2：可改进为支持 CSV、Markdown 表格等格式
        
        Args:
            text: 输出文本
            
        Returns:
            表格行列表（每行是字典），或 None 如果未检测到
        """
        lines = [l for l in text.splitlines() if l.strip()]
        
        if len(lines) < 2:
            return None

        # 查找分隔线（多个 "-" 和空格）
        sep_idx = next(
            (i for i, l in enumerate(lines)
             if re.fullmatch(r"[-\s]+", l)),
            None
        )

        if sep_idx is None or sep_idx < 1:
            return None

        # 提取列名
        header_line = lines[sep_idx - 1]
        headers = header_line.split()

        if not headers:
            return None

        # 解析数据行
        rows = []
        for row_line in lines[sep_idx + 1:]:
            values = row_line.split()
            if len(values) == len(headers):
                rows.append(dict(zip(headers, values)))

        return rows if rows else None

    @staticmethod
    def format_for_display(formatted: FormattedOutput) -> str:
        """
        将 FormattedOutput 转换为可显示的字符串（用于 UI）。
        
        Args:
            formatted: FormattedOutput 对象
            
        Returns:
            格式化的显示文本
        """
        if formatted.has_error:
            return f"❌ 错误:\n{formatted.error}"

        output_text = "\n".join(formatted.text_blocks)

        # 如果有表格，在文本下方显示
        if formatted.has_table:
            output_text += "\n\n📊 表格数据:\n"
            output_text += Formatter._table_to_string(formatted.table_data)

        # 添加执行信息
        output_text += f"\n\n⏱️ 耗时: {formatted.elapsed_sec}s"
        if formatted.retries_used > 0:
            output_text += f" (重试 {formatted.retries_used}×)"

        return output_text

    @staticmethod
    def _table_to_string(table_data: list[dict]) -> str:
        """将表格数据转换为字符串"""
        if not table_data:
            return ""

        # 获取列名
        headers = list(table_data[0].keys())

        # 计算列宽
        col_widths = {}
        for header in headers:
            col_widths[header] = max(
                len(header),
                max(len(str(row.get(header, ""))) for row in table_data)
            )

        # 构建表格
        lines = []

        # 表头
        header_row = " | ".join(
            header.ljust(col_widths[header]) for header in headers
        )
        lines.append(header_row)
        lines.append("-" * len(header_row))

        # 数据行
        for row in table_data:
            row_text = " | ".join(
                str(row.get(h, "")).ljust(col_widths[h])
                for h in headers
            )
            lines.append(row_text)

        return "\n".join(lines)