"""
config/settings.py
──────────────────
中央配置管理。所有模块从这里读取配置。
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()


class Settings:
    """应用全局配置"""
    
    # ── 项目路径 ──────────────────────────────────────────
    PROJECT_ROOT = Path(__file__).parent.parent
    
    # ── Dify 配置 ──────────────────────────────────────────
    DIFY_BASE_URL = os.getenv("DIFY_BASE_URL", "https://api.dify.ai/v1")
    DIFY_API_KEY = os.getenv("DIFY_API_KEY", "")
    DIFY_WEBHOOK_URL = os.getenv("DIFY_WEBHOOK_URL", "")
    DIFY_TIMEOUT = int(os.getenv("DIFY_TIMEOUT", "60"))
    
    # ── 代码执行沙箱配置 ───────────────────────────────────
    EXEC_TIMEOUT_SEC = int(os.getenv("EXEC_TIMEOUT_SEC", "30"))
    EXEC_MAX_MEM_MB = int(os.getenv("EXEC_MAX_MEM_MB", "512"))
    MAX_CODE_RETRIES = int(os.getenv("MAX_CODE_RETRIES", "3"))
    
    # ── 预处理配置 ─────────────────────────────────────────
    PREVIEW_ROWS = int(os.getenv("PREVIEW_ROWS", "5"))
    MAX_COLS_DESCRIBE = int(os.getenv("MAX_COLS_DESCRIBE", "30"))
    
    # ── UI 配置 ────────────────────────────────────────────
    WINDOW_WIDTH = int(os.getenv("WINDOW_WIDTH", "1000"))
    WINDOW_HEIGHT = int(os.getenv("WINDOW_HEIGHT", "600"))
    
    # ── 日志配置 ───────────────────────────────────────────
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = PROJECT_ROOT / "logs" / "app.log"
    
    @classmethod
    def validate(cls) -> None:
        """启动时验证必需配置"""
        if not cls.DIFY_API_KEY:
            raise EnvironmentError(
                "❌ DIFY_API_KEY 未设置。请检查 .env 文件。"
            )
        if not cls.DIFY_WEBHOOK_URL:
            raise EnvironmentError(
                "❌ DIFY_WEBHOOK_URL 未设置。请检查 .env 文件。"
            )


# 单例实例
settings = Settings()