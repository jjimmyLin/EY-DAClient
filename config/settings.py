"""Central runtime settings loaded from the resolved .env file."""

from __future__ import annotations

import os

from dotenv import load_dotenv

from config.devops_access import DEVOPS_DENIED_MESSAGE, is_devops_machine
from config.runtime_paths import (
    app_log_file,
    dataset_cache_dir,
    duckdb_temp_dir,
    env_file,
    project_root,
)


ENV_FILE = env_file()
load_dotenv(dotenv_path=ENV_FILE, override=True)

_BUILT_IN_EXPERIENCE_BASE_URL = "https://ai-platform-uat.ey.net/v1"
_BUILT_IN_EXPERIENCE_API_KEY = "app-kwvXgMWHQ6dKxxOzfDaaGltY"


class Settings:
    """Application-wide configuration surface."""

    PROJECT_ROOT = project_root()
    ENV_FILE = ENV_FILE

    VALID_LLM_PROVIDERS = ("dify", "gemini")
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "dify").strip().lower()
    if LLM_PROVIDER == "gemini" and not is_devops_machine():
        LLM_PROVIDER = "dify"

    DIFY_BASE_URL = os.getenv(
        "DIFY_BASE_URL",
        "https://ai-platform-uat.ey.net/v1",
    )
    DIFY_API_KEY = os.getenv("DIFY_API_KEY", "")
    DIFY_TIMEOUT = int(os.getenv("DIFY_TIMEOUT", "60"))

    EXPERIENCE_LEARNING_ENABLED = os.getenv(
        "EXPERIENCE_LEARNING_ENABLED",
        "true",
    ).strip().lower() in {"1", "true", "yes", "on"}
    DIFY_EXPERIENCE_BASE_URL = _BUILT_IN_EXPERIENCE_BASE_URL
    DIFY_EXPERIENCE_API_KEY = _BUILT_IN_EXPERIENCE_API_KEY
    DIFY_EXPERIENCE_TIMEOUT = int(
        os.getenv("DIFY_EXPERIENCE_TIMEOUT", "120")
    )
    EXPERIENCE_MAX_PAYLOAD_CHARS = int(
        os.getenv("EXPERIENCE_MAX_PAYLOAD_CHARS", "40000")
    )
    EXPERIENCE_TENANT_ID = os.getenv(
        "EXPERIENCE_TENANT_ID",
        "ey-da-client",
    )
    EXPERIENCE_PROJECT_ID = os.getenv(
        "EXPERIENCE_PROJECT_ID",
        "ey-intelligent-da-client",
    )
    EXPERIENCE_USER_ID = os.getenv("EXPERIENCE_USER_ID", "")
    APP_VERSION = os.getenv("APP_VERSION", "development")
    ANALYSIS_WORKFLOW_VERSION = os.getenv(
        "ANALYSIS_WORKFLOW_VERSION",
        "unspecified",
    )

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    GEMINI_BASE_URL = os.getenv(
        "GEMINI_BASE_URL",
        "https://generativelanguage.googleapis.com/v1beta",
    )
    GEMINI_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "120"))
    GEMINI_THINKING_BUDGET = int(os.getenv("GEMINI_THINKING_BUDGET", "2048"))
    GEMINI_MODEL_FALLBACKS = [
        value.strip()
        for value in os.getenv(
            "GEMINI_MODEL_FALLBACKS",
            (
                "gemini-3.5-flash,gemini-2.5-flash,gemini-2.5-pro,"
                "gemini-2.0-flash,gemini-2.0-flash-lite"
            ),
        ).split(",")
        if value.strip()
    ]
    GEMINI_THINKING_MODELS = ("gemini-2.5-",)
    GEMINI_THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "").strip().lower()

    EXEC_TIMEOUT_SEC = int(os.getenv("EXEC_TIMEOUT_SEC", "30"))
    EXEC_MAX_MEM_MB = int(os.getenv("EXEC_MAX_MEM_MB", "512"))
    BACKGROUND_EXEC_MAX_MEM_MB = int(
        os.getenv("BACKGROUND_EXEC_MAX_MEM_MB", "4096")
    )
    BACKGROUND_EXEC_TIMEOUT_SEC = int(
        os.getenv("BACKGROUND_EXEC_TIMEOUT_SEC", "3600")
    )
    MAX_CODE_RETRIES = int(os.getenv("MAX_CODE_RETRIES", "3"))
    SAMPLE_ROWS_PER_SHEET = int(os.getenv("SAMPLE_ROWS_PER_SHEET", "5000"))
    LARGE_DATASET_ROWS = int(os.getenv("LARGE_DATASET_ROWS", "100000"))
    LARGE_EXCEL_MB = int(os.getenv("LARGE_EXCEL_MB", "20"))
    MAX_DATASET_BYTES = int(
        os.getenv("MAX_DATASET_BYTES", str(1 * 1024 * 1024 * 1024))
    )
    MAX_SELECTED_DATASETS = int(os.getenv("MAX_SELECTED_DATASETS", "3"))
    BACKGROUND_ANALYSIS_MB = int(os.getenv("BACKGROUND_ANALYSIS_MB", "100"))
    BACKGROUND_ANALYSIS_ROWS = int(
        os.getenv("BACKGROUND_ANALYSIS_ROWS", "300000")
    )

    PREVIEW_ROWS = int(os.getenv("PREVIEW_ROWS", "5"))
    MAX_COLS_DESCRIBE = int(os.getenv("MAX_COLS_DESCRIBE", "30"))
    DATASET_CACHE_DIR = dataset_cache_dir()
    DUCKDB_TEMP_DIR = duckdb_temp_dir()
    IMPORT_BATCH_ROWS = int(os.getenv("IMPORT_BATCH_ROWS", "20000"))
    IMPORT_SCHEMA_SAMPLE_ROWS = int(os.getenv("IMPORT_SCHEMA_SAMPLE_ROWS", "2000"))
    IMPORT_ROW_GROUP_SIZE = int(os.getenv("IMPORT_ROW_GROUP_SIZE", "50000"))
    IMPORT_MIN_FREE_DISK_BYTES = int(
        os.getenv("IMPORT_MIN_FREE_DISK_BYTES", str(10 * 1024 * 1024 * 1024))
    )
    IMPORT_SOURCE_SIZE_MULTIPLIER = float(
        os.getenv("IMPORT_SOURCE_SIZE_MULTIPLIER", "8")
    )
    IMPORT_UNCOMPRESSED_MULTIPLIER = float(
        os.getenv("IMPORT_UNCOMPRESSED_MULTIPLIER", "1.5")
    )
    CLEANING_MIN_FREE_DISK_BYTES = int(
        os.getenv("CLEANING_MIN_FREE_DISK_BYTES", str(4 * 1024 * 1024 * 1024))
    )
    CLEANING_SOURCE_SIZE_MULTIPLIER = float(
        os.getenv("CLEANING_SOURCE_SIZE_MULTIPLIER", "3")
    )
    MAX_PROFILE_UNIQUES = int(os.getenv("MAX_PROFILE_UNIQUES", "30"))

    DUCKDB_THREADS = int(os.getenv("DUCKDB_THREADS", "4"))
    DUCKDB_MEMORY_LIMIT = os.getenv("DUCKDB_MEMORY_LIMIT", "4GB")
    DUCKDB_MAX_TEMP_SIZE = os.getenv("DUCKDB_MAX_TEMP_SIZE", "40GB")
    DUCKDB_PRESERVE_INSERTION_ORDER = os.getenv(
        "DUCKDB_PRESERVE_INSERTION_ORDER",
        "false",
    ).strip().lower()
    MAX_QUERY_RESULT_ROWS = int(os.getenv("MAX_QUERY_RESULT_ROWS", "10000"))
    LARGE_DATASET_COLUMN_GUARD = int(
        os.getenv("LARGE_DATASET_COLUMN_GUARD", "12")
    )

    WINDOW_WIDTH = int(os.getenv("WINDOW_WIDTH", "1000"))
    WINDOW_HEIGHT = int(os.getenv("WINDOW_HEIGHT", "600"))

    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = app_log_file()

    @classmethod
    def validate_provider_name(cls) -> None:
        if cls.LLM_PROVIDER not in cls.VALID_LLM_PROVIDERS:
            raise EnvironmentError(
                f"Unknown LLM_PROVIDER: {cls.LLM_PROVIDER!r}. "
                f"Expected one of: {', '.join(cls.VALID_LLM_PROVIDERS)}."
            )
        if cls.LLM_PROVIDER == "gemini" and not is_devops_machine():
            raise EnvironmentError(DEVOPS_DENIED_MESSAGE)

    @classmethod
    def validate_selected_provider(cls) -> None:
        cls.validate_provider_name()
        if cls.LLM_PROVIDER == "gemini":
            if not cls.GEMINI_API_KEY:
                raise EnvironmentError(
                    "GEMINI_API_KEY is not configured. Open settings and provide it."
                )
            cls.validate_gemini_api_key(cls.GEMINI_API_KEY)
        elif cls.LLM_PROVIDER == "dify":
            if not cls.DIFY_API_KEY:
                raise EnvironmentError(
                    "DIFY_API_KEY is not configured. Check API settings."
                )
            if not cls.DIFY_BASE_URL:
                raise EnvironmentError(
                    "DIFY_BASE_URL is not configured. Check API settings."
                )

    @staticmethod
    def validate_gemini_api_key(value: str) -> None:
        key = value.strip()
        if not key:
            raise ValueError("DevOps API key is required.")
        if not key.isascii() or any(character.isspace() for character in key):
            raise ValueError(
                "DevOps API key is invalid. Use the original ASCII key without spaces."
            )

    @classmethod
    def reload(cls) -> None:
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
        cls.EXPERIENCE_LEARNING_ENABLED = cls._env_bool(
            "EXPERIENCE_LEARNING_ENABLED",
            cls.EXPERIENCE_LEARNING_ENABLED,
        )
        cls.DIFY_EXPERIENCE_BASE_URL = _BUILT_IN_EXPERIENCE_BASE_URL
        cls.DIFY_EXPERIENCE_API_KEY = _BUILT_IN_EXPERIENCE_API_KEY
        cls.DIFY_EXPERIENCE_TIMEOUT = int(
            os.getenv(
                "DIFY_EXPERIENCE_TIMEOUT",
                str(cls.DIFY_EXPERIENCE_TIMEOUT),
            )
        )
        cls.EXPERIENCE_MAX_PAYLOAD_CHARS = int(
            os.getenv(
                "EXPERIENCE_MAX_PAYLOAD_CHARS",
                str(cls.EXPERIENCE_MAX_PAYLOAD_CHARS),
            )
        )
        cls.EXPERIENCE_TENANT_ID = os.getenv(
            "EXPERIENCE_TENANT_ID",
            cls.EXPERIENCE_TENANT_ID,
        )
        cls.EXPERIENCE_PROJECT_ID = os.getenv(
            "EXPERIENCE_PROJECT_ID",
            cls.EXPERIENCE_PROJECT_ID,
        )
        cls.EXPERIENCE_USER_ID = os.getenv("EXPERIENCE_USER_ID", "")
        cls.APP_VERSION = os.getenv("APP_VERSION", cls.APP_VERSION)
        cls.ANALYSIS_WORKFLOW_VERSION = os.getenv(
            "ANALYSIS_WORKFLOW_VERSION",
            cls.ANALYSIS_WORKFLOW_VERSION,
        )
        cls.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
        cls.GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", cls.GEMINI_BASE_URL)
        cls.GEMINI_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", str(cls.GEMINI_TIMEOUT)))
        cls.GEMINI_THINKING_BUDGET = int(
            os.getenv("GEMINI_THINKING_BUDGET", str(cls.GEMINI_THINKING_BUDGET))
        )
        cls.GEMINI_THINKING_LEVEL = os.getenv(
            "GEMINI_THINKING_LEVEL",
            cls.GEMINI_THINKING_LEVEL,
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
        if provider is not None:
            normalized = provider.strip().lower()
            if normalized == "gemini" and not is_devops_machine():
                raise PermissionError(DEVOPS_DENIED_MESSAGE)
            cls.LLM_PROVIDER = normalized
        if gemini_model is not None and gemini_model.strip():
            cls.GEMINI_MODEL = gemini_model.strip()
        cls.validate_provider_name()

    @classmethod
    def provider_status(cls) -> dict[str, dict[str, bool]]:
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
        return value.strip().lower() in {"1", "true", "yes", "on"}

    @classmethod
    def write_non_secret_env(cls, updates: dict[str, str]) -> None:
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

    validate = validate_selected_provider


settings = Settings()
