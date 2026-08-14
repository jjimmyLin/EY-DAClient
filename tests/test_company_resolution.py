from __future__ import annotations

import json
import threading

import httpx
from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
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


def _thread_is_stopped(thread) -> bool:
    try:
        return not thread.isRunning()
    except RuntimeError:
        return True


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


def test_company_resolution_client_parses_streaming_selection_result(
    monkeypatch,
):
    def handler(request: httpx.Request) -> httpx.Response:
        started = {
            "event": "workflow_started",
            "task_id": "resolution-task-1",
            "workflow_run_id": "resolution-run-1",
            "data": {"id": "resolution-run-1"},
        }
        finished = {
            "event": "workflow_finished",
            "task_id": "resolution-task-1",
            "workflow_run_id": "resolution-run-1",
            "data": _resolution_response(
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
            )["data"],
        }
        body = "\n\n".join(
            "data: " + json.dumps(event, ensure_ascii=False)
            for event in (started, finished)
        )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            text=body + "\n\n",
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
    ).resolve("沃尔玛")

    assert result.requires_selection
    assert len(result.candidates) == 2
    assert result.workflow_run_id == "resolution-run-1"


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


def test_ambiguous_company_selection_transitions_after_thread_cleanup(
    qapp,
    monkeypatch,
):
    import ui.main_window as main_window_module

    resolution = CompanyResolutionResult.from_workflow_response(
        _resolution_response(
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
    )
    captured_requests = []
    callback_threads: list[int] = []

    class StubCompanyResolutionWorker(QObject):
        event = Signal(dict)
        finished = Signal(object)
        error = Signal(str)
        cancelled = Signal()

        def __init__(self, company_query: str) -> None:
            super().__init__()
            self.cancelled_requested = False

        @Slot()
        def run(self) -> None:
            self.finished.emit(resolution)

        def cancel(self) -> None:
            self.cancelled_requested = True

    class StubMetricDiscoveryWorker(QObject):
        event = Signal(dict)
        finished = Signal(object)
        error = Signal(str)

        def __init__(self, request) -> None:
            super().__init__()
            self.request = request

        @Slot()
        def run(self) -> None:
            captured_requests.append(self.request)
            self.error.emit("synthetic completion")

        def cancel(self) -> None:
            pass

    original_dialog_exec = CompanySelectionDialog.exec

    def auto_select_first_candidate(dialog) -> int:
        def confirm() -> None:
            dialog._cards[0].radio.click()
            dialog.confirm_button.click()

        QTimer.singleShot(0, confirm)
        return original_dialog_exec(dialog)

    monkeypatch.setattr(
        main_window_module,
        "CompanyResolutionWorker",
        StubCompanyResolutionWorker,
    )
    monkeypatch.setattr(
        main_window_module,
        "MetricDiscoveryWorker",
        StubMetricDiscoveryWorker,
    )
    monkeypatch.setattr(
        main_window_module.CompanySelectionDialog,
        "exec",
        auto_select_first_candidate,
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

    window = MainWindow()
    main_thread_id = threading.get_ident()
    original_finished = window._on_company_resolution_finished

    def record_finished(result, pipeline_generation=None) -> None:
        callback_threads.append(threading.get_ident())
        assert window._company_resolution_thread is None
        original_finished(result, pipeline_generation)

    monkeypatch.setattr(
        window,
        "_on_company_resolution_finished",
        record_finished,
    )
    resolution_threads = []
    for expected_count in range(1, 4):
        request = MetricDiscoveryRequest(
            company_information={"company_name": "沃尔玛"},
            indicator_guidance={"indicator_count": 5},
            public_research_enabled=True,
        )
        window.metric_page.show_busy()
        window._start_metric_discovery(request)
        resolution_threads.append(window._company_resolution_thread)

        elapsed = 0
        while len(captured_requests) < expected_count and elapsed < 3000:
            qapp.processEvents()
            QTest.qWait(10)
            elapsed += 10
        qapp.processEvents()

        elapsed = 0
        while window._metric_tasks.all_runtimes() and elapsed < 3000:
            qapp.processEvents()
            QTest.qWait(10)
            elapsed += 10

    assert callback_threads == [main_thread_id] * 3
    assert all(_thread_is_stopped(thread) for thread in resolution_threads)
    assert len(captured_requests) == 3
    for selected_request in captured_requests:
        assert selected_request.company_information["company_name"] == (
            "沃尔玛（中国）投资有限公司"
        )
        assert selected_request.company_information["company_query"] == "沃尔玛"
    assert window.metric_page.company_name.text() == (
        "沃尔玛（中国）投资有限公司"
    )
    window.close()


def test_system_resume_rejects_pending_company_selection_and_releases_ui(
    qapp,
    monkeypatch,
):
    monkeypatch.setattr(settings, "reload", lambda: None)
    candidates = (
        CompanyCandidate.from_payload(
            _candidate("沃尔玛（中国）投资有限公司", "1")
        ),
        CompanyCandidate.from_payload(
            _candidate("沃尔玛华东百货有限公司", "2")
        ),
    )
    request = MetricDiscoveryRequest(
        company_information={"company_name": "沃尔玛"},
        indicator_guidance={"indicator_count": 5},
        public_research_enabled=True,
    )
    window = MainWindow()
    dialog = CompanySelectionDialog("沃尔玛", candidates, window)
    window._pending_metric_request = request
    window._company_selection_dialog = dialog
    window.metric_page.show_busy()
    dialog.show()
    qapp.processEvents()

    window._on_system_resumed(3600)
    qapp.processEvents()

    assert dialog.result() == 0
    assert window._pending_metric_request is None
    assert not window.metric_page._busy
    assert window.metric_page.generate_button.isEnabled()
    window.close()
