"""
Runtime path helpers for source and PyInstaller builds.

Keep writable config and logs out of the PyInstaller bundle on Windows.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "EY-DAClient"


def is_frozen() -> bool:
    """Return True when running from a PyInstaller-built executable."""
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    """Repository root in source mode; bundle root in frozen mode."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _windows_roaming_dir() -> Path:
    base = os.getenv("APPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / "AppData" / "Roaming" / APP_NAME


def _windows_local_dir() -> Path:
    base = os.getenv("LOCALAPPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / "AppData" / "Local" / APP_NAME


def user_config_dir() -> Path:
    """Directory for user-editable runtime config."""
    if is_frozen() and sys.platform.startswith("win"):
        return _windows_roaming_dir()
    return project_root()


def user_log_dir() -> Path:
    """Directory for app and crash logs."""
    if is_frozen() and sys.platform.startswith("win"):
        return _windows_local_dir() / "logs"
    return project_root() / "logs"


def user_cache_dir() -> Path:
    """Directory for reusable local dataset caches."""
    if is_frozen() and sys.platform.startswith("win"):
        return _windows_local_dir() / "cache"
    return project_root() / ".cache"


def dataset_cache_dir() -> Path:
    return user_cache_dir() / "datasets"


def duckdb_temp_dir() -> Path:
    return user_cache_dir() / "duckdb-temp"


def env_file() -> Path:
    """Resolved .env location used by both readers and writers."""
    return user_config_dir() / ".env"


def app_log_file() -> Path:
    return user_log_dir() / "app.log"


def faulthandler_log_file() -> Path:
    return user_log_dir() / "faulthandler.log"
