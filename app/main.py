"""
main.py
───────
应用入口点。
"""

from __future__ import annotations

import faulthandler
import logging
import multiprocessing
import sys
import threading
import traceback
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.logging_setup import setup_logging
from config.runtime_paths import app_log_file, faulthandler_log_file


_FAULT_LOG_HANDLE = None


def _enable_crash_logging() -> None:
    """Install file-backed logging before importing Qt or app modules."""
    global _FAULT_LOG_HANDLE

    setup_logging()

    fault_log = faulthandler_log_file()
    fault_log.parent.mkdir(parents=True, exist_ok=True)
    _FAULT_LOG_HANDLE = fault_log.open("a", encoding="utf-8")
    faulthandler.enable(file=_FAULT_LOG_HANDLE, all_threads=True)

    sys.excepthook = _log_unhandled_exception
    threading.excepthook = _log_thread_exception
    if hasattr(sys, "unraisablehook"):
        sys.unraisablehook = _log_unraisable_exception

    logging.info(
        "Startup logging initialized. app_log=%s faulthandler_log=%s",
        app_log_file(),
        fault_log,
    )


def _log_unhandled_exception(exc_type, exc_value, exc_traceback) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.critical(
        "Unhandled exception",
        exc_info=(exc_type, exc_value, exc_traceback),
    )


def _log_thread_exception(args: threading.ExceptHookArgs) -> None:
    logging.critical(
        "Unhandled thread exception in %s",
        args.thread.name if args.thread else "<unknown>",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def _log_unraisable_exception(args) -> None:
    logging.critical(
        "Unraisable exception from %r: %s",
        args.object,
        args.err_msg,
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def _flush_and_shutdown_logging() -> None:
    """Persist logs before short-lived worker processes exit."""
    for handler in logging.getLogger().handlers:
        try:
            handler.flush()
        except Exception:
            pass
    logging.shutdown()


def _safe_print_exception() -> None:
    """Print tracebacks only when a windowed executable has usable stderr."""
    if sys.stderr is None:
        return
    try:
        traceback.print_exc()
    except Exception:
        pass


def _append_worker_failure_fallback(script_path: str, traceback_text: str) -> None:
    """Write a last-resort worker failure entry if logging handlers fail."""
    log_file = app_log_file()
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as fallback_log:
            fallback_log.write(
                f"Worker failed while executing: {script_path}\n"
                f"{traceback_text}\n"
            )
    except Exception:
        pass


def _run_worker(script_path: str) -> int:
    """
    Execute generated analysis code in worker mode.

    PyInstaller frozen apps use sys.executable as the app itself. core/executor.py
    starts `<exe> --run-script <script>` so this process runs analysis code
    instead of opening the GUI again.
    """
    log_file = app_log_file()
    log_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        logging.info("Worker started for script: %s", script_path)
        with open(script_path, encoding="utf-8") as script_file:
            source = script_file.read()
        exec(compile(source, script_path, "exec"), {"__name__": "__main__"})
        logging.info("Worker finished successfully: %s", script_path)
        _flush_and_shutdown_logging()
        return 0
    except Exception:
        traceback_text = traceback.format_exc()
        exception_line = traceback_text.strip().splitlines()[-1]
        logging.exception("Worker failed while executing: %s", script_path)
        _safe_print_exception()
        _flush_and_shutdown_logging()

        try:
            content = log_file.read_text(encoding="utf-8")
        except Exception:
            content = ""
        if (
            "Worker failed while executing" not in content
            or exception_line not in content
        ):
            _append_worker_failure_fallback(script_path, traceback_text)
        return 1


def _run_gui() -> int:
    """Start the GUI application with crash-safe logging already active."""
    try:
        # 防御性：multiprocessing 在冻结环境下需要它；源码运行时为无操作。
        multiprocessing.freeze_support()

        from config.settings import settings

        setup_logging(settings.LOG_LEVEL)

        # 只验证 provider 名称。API key 缺失时仍允许打开 UI 设置。
        settings.validate_provider_name()

        from PySide6.QtWidgets import QApplication
        from ui.main_window import MainWindow

        logging.info("Starting GUI")
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        exit_code = app.exec()
        logging.info("GUI exited with code %s", exit_code)
        return exit_code
    except Exception:
        logging.exception("Application startup/runtime failure")
        _safe_print_exception()
        return 1


def main() -> int:
    _enable_crash_logging()

    if len(sys.argv) >= 3 and sys.argv[1] == "--run-script":
        return _run_worker(sys.argv[2])

    return _run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
