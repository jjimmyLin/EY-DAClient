"""
core 模块 - 核心业务逻辑
"""

from core.preprocessor import Preprocessor, FileMeta, SheetMeta
from core.prompt_builder import PromptBuilder
from core.code_validator import CodeValidator, SecurityError
from core.executor import Executor, ExecutionResult
from core.data_access import LocalDataCatalog
from core.analysis_contract import (
    AnalysisPlanValidator,
    GeneratedCodeContractValidator,
)
from core.session_manager import SessionManager, Turn

__all__ = [
    "Preprocessor",
    "FileMeta",
    "SheetMeta",
    "PromptBuilder",
    "CodeValidator",
    "SecurityError",
    "Executor",
    "ExecutionResult",
    "LocalDataCatalog",
    "AnalysisPlanValidator",
    "GeneratedCodeContractValidator",
    "SessionManager",
    "Turn",
]
