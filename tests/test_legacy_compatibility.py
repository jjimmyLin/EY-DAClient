import importlib

import pandas as pd

from services.dify_service import DifyService
from services.profiling_service import ProfilingService


def test_legacy_modules_import_cleanly():
    for module_name in (
        "app.app",
        "services.dify_service",
        "services.profiling_service",
        "workers.profiling_worker",
    ):
        importlib.import_module(module_name)


def test_legacy_dify_service_uses_blocking_payload(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr("services.dify_service.httpx.post", fake_post)
    service = DifyService("secret", "https://example.test/workflows/run")

    assert service.run_workflow("summarize", [{"file": "demo.xlsx"}]) == {
        "ok": True
    }
    assert captured["url"] == "https://example.test/workflows/run"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["json"]["response_mode"] == "blocking"


def test_legacy_profiling_service_returns_prompt_profile(tmp_path):
    workbook = tmp_path / "demo.xlsx"
    pd.DataFrame({"region": ["East", "West"], "amount": [10, 20]}).to_excel(
        workbook,
        index=False,
    )

    profile = ProfilingService().generate_profile(str(workbook))

    assert profile["file"] == "demo.xlsx"
    assert profile["dataset_id"].startswith("ds_")
    assert profile["sheets"][0]["columns"] == ["region", "amount"]
