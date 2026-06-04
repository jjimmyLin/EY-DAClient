"""
core/executor.py
────────────────
在隔离的子进程中执行代码。
加载 DataFrame，捕获输出，处理超时和内存限制。
"""

from __future__ import annotations
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from core.preprocessor import FileMeta
from config.settings import settings


@dataclass
class ExecutionResult:
    """代码执行结果"""
    success: bool
    stdout: str
    stderr: str
    elapsed_sec: float
    timed_out: bool = False
    chart_paths: list[str] = field(default_factory=list)

    @property
    def output(self) -> str:
        """便捷属性：返回主要输出"""
        return self.stdout if self.success else self.stderr


class Executor:
    """代码执行器"""

    def __init__(self) -> None:
        self._timeout = settings.EXEC_TIMEOUT_SEC
        self._max_retries = settings.MAX_CODE_RETRIES

    def run(
        self,
        code: str,
        files_meta: list[FileMeta],
    ) -> ExecutionResult:
        """
        执行 Python 代码。
        
        Args:
            code: 要执行的 Python 代码
            files_meta: 文件元数据列表（用于加载 DataFrame）
            
        Returns:
            ExecutionResult 对象
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            # 生成引导脚本
            script_path = Path(tmp_dir) / "analysis.py"
            script_path.write_text(
                self._build_bootstrap(code, files_meta),
                encoding="utf-8",
            )
            
            # 在子进程中执行
            return self._run_subprocess(str(script_path))

    # ─────────────────────────────────────────────────────────────────

    def _build_bootstrap(self, code: str, files_meta: list[FileMeta]) -> str:
        """
        构建完整的执行脚本。
        包括导入、加载 DataFrame、执行用户代码。
        
        步骤：
          1. 导入必要的库
          2. 加载 Excel 文件到 DataFrame
          3. 组装 `dfs` 字典
          4. 执行用户代码
        """
        load_lines: list[str] = []
        dfs_entries: list[str] = []

        # ── 为每个文件生成加载代码 ──
        for fm in files_meta:
            safe_var = self._safe_var(fm.file_name)
            
            # 加载 Excel 文件
            load_lines.append(
                f'{safe_var}_xl = pd.ExcelFile({fm.file_path!r})'
            )
            
            # 为每个 Sheet 加载 DataFrame
            sheet_dict_entries = []
            for sheet in fm.sheets:
                sheet_var = f"{safe_var}_{self._safe_var(sheet.sheet_name)}"
                load_lines.append(
                    f'{sheet_var} = {safe_var}_xl.parse({sheet.sheet_name!r})'
                )
                sheet_dict_entries.append(
                    f'    {sheet.sheet_name!r}: {sheet_var}'
                )
            
            # 为这个文件构建字典
            dfs_entries.append(
                f"  {fm.file_name!r}: {{\n"
                + ",\n".join(sheet_dict_entries)
                + "\n  }"
            )

        # ── 构建 dfs 字典 ──
        dfs_block = "dfs = {\n" + ",\n".join(dfs_entries) + "\n}"

        # ── 完整的引导脚本 ──
        bootstrap = "\n".join([
            "import pandas as pd",
            "import matplotlib",
            "matplotlib.use('Agg')  # 无头模式",
            "import matplotlib.pyplot as plt",
            "import warnings",
            "warnings.filterwarnings('ignore')",
            "",
            *load_lines,
            "",
            dfs_block,
            "",
            "# ── 用户代码开始 ──",
            code,
            "# ── 用户代码结束 ──",
        ])

        return bootstrap

    def _run_subprocess(self, script_path: str) -> ExecutionResult:
        """
        在子进程中执行脚本。
        
        Args:
            script_path: 脚本文件路径
            
        Returns:
            ExecutionResult 对象
        """
        start = time.monotonic()
        timed_out = False
        stdout = ""
        stderr = ""

        try:
            result = subprocess.run(
                [sys.executable, script_path],
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            stdout = result.stdout
            stderr = result.stderr
            success = result.returncode == 0

        except subprocess.TimeoutExpired:
            stdout = ""
            stderr = (
                f"⏱️ 执行超时（超过 {self._timeout} 秒）。\n"
                f"代码可能陷入无限循环或执行时间过长。"
            )
            success = False
            timed_out = True

        except Exception as e:
            stdout = ""
            stderr = f"❌ 执行错误: {str(e)}"
            success = False

        elapsed = round(time.monotonic() - start, 2)

        return ExecutionResult(
            success=success,
            stdout=stdout,
            stderr=stderr,
            elapsed_sec=elapsed,
            timed_out=timed_out,
        )

    @staticmethod
    def _safe_var(name: str) -> str:
        """
        将文件名/Sheet名转换为有效的 Python 变量名。
        
        例如：
          "sales report.xlsx" → "sales_report_xlsx"
          "Q1-2024" → "Q1_2024"
        """
        import re
        
        # 替换非字母数字字符为下划线
        s = re.sub(r"[^\w]", "_", name)
        
        # 去掉开头的数字
        s = s.lstrip("0123456789") or "df"
        
        return s