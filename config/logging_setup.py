"""
config/logging_setup.py
───────────────────────
初始化 Python logging，供所有模块使用。
"""

import logging
import sys
from config.runtime_paths import app_log_file


def setup_logging(log_level: str | None = None) -> None:
    """配置根 logger：文件 + 控制台双输出。"""
    log_file = app_log_file()
    log_file.parent.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] pid=%(process)d "
        "thread=%(threadName)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(getattr(logging, (log_level or "INFO").upper(), logging.INFO))

    existing_file_handlers = [
        h for h in root.handlers
        if isinstance(h, logging.FileHandler)
        and getattr(h, "baseFilename", None) == str(log_file)
    ]
    if not existing_file_handlers:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    if getattr(sys, "frozen", False) and sys.platform.startswith("win"):
        return

    if not any(
        isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
        for h in root.handlers
    ):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(fmt)
        root.addHandler(stream_handler)
