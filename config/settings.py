"""
config/settings.py
──────────────────
中央配置管理。所有模块从这里读取配置。
"""

import os
from dotenv import load_dotenv
from config.devops_access import DEVOPS_DENIED_MESSAGE, is_devops_machine
from config.runtime_paths import app_log_file, env_file, project_root

ENV_FILE = env_file()

# 加载明确解析后的 .env，确保 UI 写入和运行时读取是同一个文件。
load_dotenv(dotenv_path=ENV_FILE, override=True)


class Settings:
    """应用全局配置"""
    
    # ── 项目路径 ──────────────────────────────────────────
    PROJECT_ROOT = project_root()
    ENV_FILE = ENV_FILE

    # ── LLM 提供商选择 ─────────────────────────────────────
    # 可选值: "dify" (默认), "gemini"
    VALID_LLM_PROVIDERS = ("dify", "gemini")
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "dify").strip().lower()
    if LLM_PROVIDER == "gemini" and not is_devops_machine():
        LLM_PROVIDER = "dify"

    # ── Dify 配置 ──────────────────────────────────────────
    DIFY_BASE_URL = os.getenv(
        "DIFY_BASE_URL",
        "https://ai-platform-uat.ey.net/v1",
    )
    DIFY_API_KEY = os.getenv("DIFY_API_KEY", "")
    DIFY_TIMEOUT = int(os.getenv("DIFY_TIMEOUT", "60"))

    # ── Gemini (Google AI Studio) 配置 ─────────────────────
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    GEMINI_BASE_URL = os.getenv(
        "GEMINI_BASE_URL",
        "https://generativelanguage.googleapis.com/v1beta",
    )
    GEMINI_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "120"))
    GEMINI_THINKING_BUDGET = int(os.getenv("GEMINI_THINKING_BUDGET", "2048"))
    GEMINI_MODEL_FALLBACKS = [
        m.strip()
        for m in os.getenv(
            "GEMINI_MODEL_FALLBACKS",
            "gemini-3.5-flash,gemini-2.5-flash,gemini-2.5-pro,gemini-2.0-flash,gemini-2.0-flash-lite",
        ).split(",")
        if m.strip()
    ]
    GEMINI_THINKING_MODELS = ("gemini-2.5-",)
    GEMINI_THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "").strip().lower()

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
    LOG_FILE = app_log_file()
    
    @classmethod
    def validate_provider_name(cls) -> None:
        """只验证 provider 名称，允许缺少 API key 时进入 UI 设置。"""
        if cls.LLM_PROVIDER not in cls.VALID_LLM_PROVIDERS:
            raise EnvironmentError(
                f"❌ 未知的 LLM_PROVIDER: {cls.LLM_PROVIDER!r}。"
                f"请设置为 {', '.join(cls.VALID_LLM_PROVIDERS)}。"
            )
        if cls.LLM_PROVIDER == "gemini" and not is_devops_machine():
            raise EnvironmentError(DEVOPS_DENIED_MESSAGE)

    @classmethod
    def validate_selected_provider(cls) -> None:
        """分析前验证当前 provider 所需配置。"""
        cls.validate_provider_name()

        if cls.LLM_PROVIDER == "gemini":
            if not cls.GEMINI_API_KEY:
                raise EnvironmentError(
                    "GEMINI_API_KEY 未设置。请在 DevOps 设置中填写有效的 API key。"
                )
            cls.validate_gemini_api_key(cls.GEMINI_API_KEY)
        elif cls.LLM_PROVIDER == "dify":
            if not cls.DIFY_API_KEY:
                raise EnvironmentError(
                    "DIFY_API_KEY 未设置。请检查 API 设置。"
                )
            if not cls.DIFY_BASE_URL:
                raise EnvironmentError(
                    "DIFY_BASE_URL 未设置。请检查 API 设置。"
                )

    @staticmethod
    def validate_gemini_api_key(value: str) -> None:
        """Reject values that cannot be used as an HTTP header API key."""
        key = value.strip()
        if not key:
            raise ValueError("DevOps API key is required.")
        if not key.isascii() or any(character.isspace() for character in key):
            raise ValueError(
                "DevOps API key is invalid. Enter the original ASCII key without spaces."
            )

    @classmethod
    def reload(cls) -> None:
        """从 .env / 环境变量重新加载运行时配置。"""
        load_dotenv(dotenv_path=cls.ENV_FILE, override=True)
        provider = os.getenv("LLM_PROVIDER", cls.LLM_PROVIDER).strip().lower()
        if provider == "gemini" and not is_devops_machine():
            provider = "dify"
        cls.update_runtime(
            provider=provider,
            gemini_model=os.getenv("GEMINI_MODEL", cls.GEMINI_MODEL).strip(),
        )
        cls.DIFY_BASE_URL = os.getenv("DIFY_BASE_URL", cls.DIFY_BASE_URL)
        cls.DIFY_API_KEY = os.getenv("DIFY_API_KEY", "")
        cls.DIFY_TIMEOUT = int(os.getenv("DIFY_TIMEOUT", str(cls.DIFY_TIMEOUT)))
        cls.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
        cls.GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", cls.GEMINI_BASE_URL)
        cls.GEMINI_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", str(cls.GEMINI_TIMEOUT)))
        cls.GEMINI_THINKING_BUDGET = int(
            os.getenv("GEMINI_THINKING_BUDGET", str(cls.GEMINI_THINKING_BUDGET))
        )
        cls.GEMINI_THINKING_LEVEL = os.getenv(
            "GEMINI_THINKING_LEVEL", cls.GEMINI_THINKING_LEVEL
        ).strip().lower()
        cls.GEMINI_MODEL_FALLBACKS = cls._csv(
            os.getenv(
                "GEMINI_MODEL_FALLBACKS",
                ",".join(cls.GEMINI_MODEL_FALLBACKS),
            )
        )

    @classmethod
    def update_runtime(
        cls,
        provider: str | None = None,
        gemini_model: str | None = None,
    ) -> None:
        """更新当前进程内非密钥配置。"""
        if provider is not None:
            normalized_provider = provider.strip().lower()
            if normalized_provider == "gemini" and not is_devops_machine():
                raise PermissionError(DEVOPS_DENIED_MESSAGE)
            cls.LLM_PROVIDER = normalized_provider
        if gemini_model is not None and gemini_model.strip():
            cls.GEMINI_MODEL = gemini_model.strip()
        cls.validate_provider_name()

    @classmethod
    def provider_status(cls) -> dict[str, dict[str, bool]]:
        """返回各 provider 必需配置是否存在，不暴露密钥值。"""
        return {
            "dify": {
                "DIFY_API_KEY": bool(cls.DIFY_API_KEY),
                "DIFY_BASE_URL": bool(cls.DIFY_BASE_URL),
            },
            "gemini": {"GEMINI_API_KEY": bool(cls.GEMINI_API_KEY)},
        }

    @staticmethod
    def _csv(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    @staticmethod
    def _env_bool(key: str, default: bool) -> bool:
        value = os.getenv(key)
        if value is None:
            return default
        return value.strip().lower() in ("1", "true", "yes", "on")

    @classmethod
    def write_non_secret_env(cls, updates: dict[str, str]) -> None:
        """Write managed settings to .env, removing duplicate managed keys."""
        allowed = {
            "LLM_PROVIDER",
            "GEMINI_MODEL",
            "GEMINI_API_KEY",
            "GEMINI_BASE_URL",
            "GEMINI_TIMEOUT",
            "GEMINI_THINKING_BUDGET",
            "GEMINI_THINKING_LEVEL",
            "GEMINI_MODEL_FALLBACKS",
            "DIFY_API_KEY",
            "DIFY_BASE_URL",
            "DIFY_TIMEOUT",
        }
        invalid = set(updates) - allowed
        if invalid:
            raise ValueError(f"Refusing to write secret/unknown keys: {sorted(invalid)}")

        env_path = cls.ENV_FILE
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.touch(exist_ok=True)
        lines = env_path.read_text(encoding="utf-8").splitlines()

        written: set[str] = set()
        new_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                new_lines.append(line)
                continue

            key = line.split("=", 1)[0].strip()
            if key not in updates:
                new_lines.append(line)
                continue

            if key in written:
                continue

            new_lines.append(f"{key}={updates[key]}")
            written.add(key)

        for key, value in updates.items():
            if key not in written:
                new_lines.append(f"{key}={value}")

        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # Backwards-compatible alias for older callers.
    validate = validate_selected_provider


# 单例实例
settings = Settings()
