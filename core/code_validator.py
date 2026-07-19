"""
core/code_validator.py
──────────────────────
AST 静态分析，在执行前验证代码安全性。
阻止危险的导入和函数调用。
"""

from __future__ import annotations
import ast
from dataclasses import dataclass


# Generated analysis code only needs numerical and plotting libraries.
_ALLOWED_IMPORTS = {
    "collections",
    "datetime",
    "decimal",
    "itertools",
    "math",
    "matplotlib",
    "numpy",
    "pandas",
    "statistics",
}

# 禁止调用的内置函数
_BANNED_BUILTINS = {
    "exec", "eval", "compile", "__import__",
    "open", "input", "breakpoint", "getattr", "setattr", "delattr",
    "globals", "locals", "vars",
}

# 禁止访问的特殊属性
_BANNED_ATTRS = {
    "__class__", "__bases__", "__subclasses__",
    "__globals__", "__builtins__", "__code__", "__dict__",
    "builtins", "os", "pathlib", "socket", "subprocess", "sys",
}

_BANNED_CALLS = {
    # pandas readers and writers
    "read_csv", "read_excel", "read_json", "read_html", "read_sql",
    "read_sql_query", "read_sql_table", "read_parquet", "read_pickle",
    "read_feather", "read_orc", "read_sas", "read_spss", "read_stata",
    "read_xml", "read_fwf", "read_clipboard",
    "ExcelFile", "HDFStore",
    "to_csv", "to_excel", "to_json", "to_html", "to_sql",
    "to_parquet", "to_pickle", "to_feather", "to_orc", "to_stata",
    "to_xml", "to_clipboard",
    # pathlib and generic filesystem methods
    "read_text", "read_bytes", "write_text", "write_bytes",
    "mkdir", "unlink", "rmdir", "touch",
    # numpy and matplotlib filesystem methods
    "load", "save", "savez", "savez_compressed", "loadtxt", "savetxt",
    "genfromtxt", "fromfile", "tofile", "memmap", "savefig",
    "system", "popen", "spawn", "startfile",
}

_BANNED_NAMES = {"__builtins__", "__loader__", "__spec__"}


@dataclass
class ValidationResult:
    """代码验证结果"""
    is_safe: bool
    violations: list[str]

    def raise_if_unsafe(self) -> None:
        """如果代码不安全，抛出异常"""
        if not self.is_safe:
            joined = "\n  • ".join(self.violations)
            raise SecurityError(f"代码验证失败:\n  • {joined}")


class SecurityError(Exception):
    """代码安全错误"""
    pass


class CodeValidator:
    """代码安全验证器"""

    def validate(self, code: str) -> ValidationResult:
        """
        验证代码的安全性。
        解析代码树，检查危险的导入和函数调用。
        
        Args:
            code: Python 代码字符串
            
        Returns:
            ValidationResult 对象
        """
        violations: list[str] = []

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return ValidationResult(
                is_safe=False,
                violations=[f"语法错误: {str(e)}"]
            )

        # 遍历 AST 节点
        for node in ast.walk(tree):
            
            # ── 检查 import 语句 ──
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root not in _ALLOWED_IMPORTS:
                        violations.append(f"不允许导入: `{alias.name}`")

            # ── 检查 from...import 语句 ──
            elif isinstance(node, ast.ImportFrom):
                module = (node.module or "").split(".")[0]
                if module not in _ALLOWED_IMPORTS:
                    violations.append(
                        f"不允许导入: `from {node.module} import ...`"
                    )

            # ── 检查函数调用 ──
            elif isinstance(node, ast.Call):
                func_name = self._get_call_name(node)
                if func_name in _BANNED_BUILTINS or func_name in _BANNED_CALLS:
                    violations.append(f"禁止调用: `{func_name}()`")

            # ── 检查属性访问（Dunder 属性逃逸） ──
            elif isinstance(node, ast.Attribute):
                if node.attr in _BANNED_ATTRS:
                    violations.append(
                        f"禁止访问: `{node.attr}`"
                    )

            elif isinstance(node, ast.Name):
                if node.id in _BANNED_NAMES:
                    violations.append(f"禁止访问: `{node.id}`")

        return ValidationResult(
            is_safe=len(violations) == 0,
            violations=violations
        )

    @staticmethod
    def _get_call_name(node: ast.Call) -> str:
        """从 Call 节点提取函数名"""
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        return ""
