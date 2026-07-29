from __future__ import annotations

import json

import httpx
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from config.settings import settings
from core.company_resolution import (
    CompanyCandidate,
    CompanyResolutionResult,
)
from core.metric_discovery import MetricDiscoveryRequest
from dify.company_resolution_client import CompanyResolutionDifyClient
from ui.company_selection_dialog import CompanySelectionDialog
from ui.main_window import MainWindow


def _resolution_response(payload: dict) -> dict:
    return {
        "workflow_run_id": "resolution-run-1",
        "data": {
            "status": "succeeded",
            "outputs": {"company_resolution": payload},
        },
    }


def _candidate(name: str, company_id: str) -> dict[str, str]:
    return {
        "company_name": name,
        "company_id": company_id,
        "credit_code": f"CREDIT-{company_id}",
        "status": "存续",
        "legal_representative": "测试法人",
        "established_date": "2003-01-01",
    }


def test_company_resolution_contract_parses_selection_candidates():
    response = _resolution_response(
        {
            "schema_version": "company_resolution.result.v1",
            "resolution_status": "selection_required",
            "requires_selection": True,
            "original_query": "沃尔玛",
            "resolved_company_name": "",
            "selected_company": {},
            "candidates": [
                _candidate("沃尔玛（中国）投资有限公司", "1"),
                _candidate("沃尔玛华东百货有限公司", "2"),
            ],
            "message": "请选择工商主体",
        }
    )

    result = CompanyResolutionResult.from_workflow_response(response)

    assert result.requires_selection is True
    assert result.original_query == "沃尔玛"
    assert len(result.candidates) == 2
    assert result.candidates[0].company_name == "沃尔玛（中国）投资有限公司"


def test_company_resolution_client_sends_only_company_query(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json=_resolution_response(
                {
                    "schema_version": "company_resolution.result.v1",
                    "resolution_status": "direct_match",
                    "requires_selection": False,
                    "original_query": "示例公司",
                    "resolved_company_name": "示例公司有限公司",
                    "selected_company": {
                        "company_name": "示例公司有限公司",
                        "credit_code": "TEST-CODE",
                    },
                    "candidates": [],
                    "message": "已识别",
                }
            ),
        )

    monkeypatch.setattr(settings, "reload", lambda: None)
    monkeypatch.setattr(
        settings,
        "DIFY_COMPANY_RESOLUTION_BASE_URL",
        "https://dify.test/v1",
    )
    monkeypatch.setattr(
        settings,
        "DIFY_COMPANY_RESOLUTION_API_KEY",
        "app-resolution-test",
    )
    monkeypatch.setattr(settings, "DIFY_COMPANY_RESOLUTION_TIMEOUT", 30)

    result = CompanyResolutionDifyClient(
        transport=httpx.MockTransport(handler)
    ).resolve("示例公司")

    assert result.resolution_status == "direct_match"
    assert captured["inputs"] == {"company_query": "示例公司"}
    assert captured["response_mode"] == "streaming"


def test_metric_request_preserves_query_and_selected_company():
    request = MetricDiscoveryRequest(
        company_information={"company_name": "沃尔玛"},
        indicator_guidance={"indicator_count": 5},
        public_research_enabled=True,
    )
    selected = _candidate("沃尔玛（中国）投资有限公司", "1")

    resolved = request.with_selected_company(
        selected,
        original_query="沃尔玛",
    )

    assert resolved.request_id == request.request_id
    assert resolved.company_information["company_name"] == (
        "沃尔玛（中国）投资有限公司"
    )
    assert resolved.company_information["company_query"] == "沃尔玛"
    assert resolved.company_information["selected_company"]["company_id"] == "1"


def test_company_selection_dialog_requires_explicit_choice(qapp):
    candidates = (
        CompanyCandidate.from_payload(
            _candidate("沃尔玛（中国）投资有限公司", "1")
        ),
        CompanyCandidate.from_payload(
            _candidate("沃尔玛华东百货有限公司", "2")
        ),
    )
    dialog = CompanySelectionDialog("沃尔玛", candidates)
    dialog.show()
    qapp.processEvents()

    assert not dialog.confirm_button.isEnabled()
    QTest.mouseClick(dialog._cards[0].radio, Qt.LeftButton)
    qapp.processEvents()

    assert dialog.confirm_button.isEnabled()
    assert dialog.selected_candidate() == candidates[0]
    dialog.close()


def test_metric_submission_uses_resolution_preflight_when_configured(
    qapp,
    monkeypatch,
):
    captured = {}
    window = MainWindow()
    request = MetricDiscoveryRequest(
        company_information={"company_name": "沃尔玛"},
        indicator_guidance={"indicator_count": 5},
        public_research_enabled=True,
    )
    monkeypatch.setattr(settings, "reload", lambda: None)
    monkeypatch.setattr(
        settings,
        "company_resolution_workflow_status",
        lambda: {
            "DIFY_COMPANY_RESOLUTION_API_KEY": True,
            "DIFY_COMPANY_RESOLUTION_BASE_URL": True,
        },
    )
    monkeypatch.setattr(
        window,
        "_start_company_resolution",
        lambda query: captured.update(query=query),
    )

    window._start_metric_discovery(request)

    assert captured == {"query": "沃尔玛"}
    assert window._pending_metric_request is request
    window.close()


def test_direct_match_updates_form_and_metric_request(
    qapp,
    monkeypatch,
):
    window = MainWindow()
    request = MetricDiscoveryRequest(
        company_information={"company_name": "沃尔玛"},
        indicator_guidance={"indicator_count": 5},
        public_research_enabled=True,
    )
    result = CompanyResolutionResult.from_workflow_response(
        _resolution_response(
            {
                "schema_version": "company_resolution.result.v1",
                "resolution_status": "direct_match",
                "requires_selection": False,
                "original_query": "沃尔玛",
                "resolved_company_name": "沃尔玛（中国）投资有限公司",
                "selected_company": _candidate(
                    "沃尔玛（中国）投资有限公司",
                    "1",
                ),
                "candidates": [],
                "message": "已识别",
            }
        )
    )
    captured = {}
    window._pending_metric_request = request
    monkeypatch.setattr(
        window,
        "_launch_metric_worker",
        lambda pending: captured.update(request=pending),
    )

    window._on_company_resolution_finished(result)
    qapp.processEvents()

    resolved_request = captured["request"]
    assert resolved_request.company_information["company_name"] == (
        "沃尔玛（中国）投资有限公司"
    )
    assert resolved_request.company_information["company_query"] == "沃尔玛"
    assert window.metric_page.company_name.text() == (
        "沃尔玛（中国）投资有限公司"
    )
    window.close()
