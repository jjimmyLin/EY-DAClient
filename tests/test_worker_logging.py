from __future__ import annotations

import logging

import app.main as main_module


def test_worker_failure_persists_app_log(tmp_path, monkeypatch):
    log_file = tmp_path / "logs" / "app.log"
    script_path = tmp_path / "worker_fail.py"
    script_path.write_text(
        "raise RuntimeError('intentional worker smoke failure')",
        encoding="utf-8",
    )
    log_file.parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(main_module, "app_log_file", lambda: log_file)

    root = logging.getLogger()
    handler = logging.FileHandler(log_file, encoding="utf-8")
    root.addHandler(handler)
    monkeypatch.setattr(
        main_module,
        "_flush_and_shutdown_logging",
        lambda: handler.flush(),
    )
    try:
        exit_code = main_module._run_worker(str(script_path))
    finally:
        root.removeHandler(handler)
        handler.close()

    assert exit_code == 1
    content = log_file.read_text(encoding="utf-8")
    assert "Worker failed while executing" in content
    assert "intentional worker smoke failure" in content
