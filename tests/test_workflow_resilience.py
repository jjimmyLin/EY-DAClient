from __future__ import annotations

import json
import threading

import httpx
import pytest
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtTest import QTest

from core.executor import Executor
from core.metric_discovery import MetricDiscoveryRequest
from core.resume_monitor import ResumeMonitor
from core.task_supervisor import TaskState, TaskSupervisor
from dify.reliable_workflow import (
    ReliableWorkflowRunner,
    WorkflowTransportError,
)
from llm.cancellation import CancellationToken, RequestCancelled


class _InterruptedSse(httpx.SyncByteStream):
    def __iter__(self):
        started = {
            "event": "workflow_started",
            "task_id": "task-1",
            "workflow_run_id": "run-1",
            "data": {"id": "run-1"},
        }
        yield (
            "data: " + json.dumps(started) + "\n\n"
        ).encode("utf-8")
        raise httpx.RemoteProtocolError(
            "peer closed connection without sending complete message body"
        )

    def close(self) -> None:
        pass


class _CancelAfterStartedSse(httpx.SyncByteStream):
    def __init__(self, token: CancellationToken) -> None:
        self._token = token

    def __iter__(self):
        started = {
            "event": "workflow_started",
            "task_id": "task-cancel",
            "workflow_run_id": "run-cancel",
            "data": {"id": "run-cancel"},
        }
        yield (
            "data: " + json.dumps(started) + "\n\n"
        ).encode("utf-8")
        self._token.cancel()

    def close(self) -> None:
        pass


class _UnexpectedFailureSse(httpx.SyncByteStream):
    def __iter__(self):
        started = {
            "event": "workflow_started",
            "task_id": "task-unknown",
            "workflow_run_id": "run-unknown",
            "data": {"id": "run-unknown"},
        }
        yield (
            "data: " + json.dumps(started) + "\n\n"
        ).encode("utf-8")
        raise ValueError("unexpected parser failure")

    def close(self) -> None:
        pass


def test_interrupted_stream_recovers_same_run_without_second_post():
    workflow_posts = 0
    resume_requests = 0
    result_requests = 0
    events: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal workflow_posts, resume_requests, result_requests
        if (
            request.method == "POST"
            and request.url.path.endswith("/workflows/run")
        ):
            workflow_posts += 1
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                stream=_InterruptedSse(),
            )
        if request.url.path.endswith("/workflow/run-1/events"):
            resume_requests += 1
            return httpx.Response(
                404,
                json={"message": "event replay unavailable"},
            )
        if request.url.path.endswith("/workflows/run/run-1"):
            result_requests += 1
            return httpx.Response(
                200,
                json={
                    "id": "run-1",
                    "status": "succeeded",
                    "outputs": {"answer": "ok"},
                },
            )
        return httpx.Response(404)

    runner = ReliableWorkflowRunner(
        base_url="https://dify.test/v1",
        api_key="app-test",
        timeout=5,
        cancellation_token=CancellationToken(),
        transport=httpx.MockTransport(handler),
    )

    result = runner.run(
        {
            "inputs": {"query": "test"},
            "response_mode": "streaming",
            "user": "resilience-test",
        },
        event_callback=events.append,
    )

    assert result["data"]["outputs"] == {"answer": "ok"}
    assert workflow_posts == 1
    assert resume_requests == 1
    assert result_requests == 1
    assert any(event["event"] == "client_reconnecting" for event in events)


def test_cancellation_stops_known_remote_task_without_replaying():
    token = CancellationToken()
    workflow_posts = 0
    stopped_tasks: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal workflow_posts
        if (
            request.method == "POST"
            and request.url.path.endswith("/workflows/run")
        ):
            workflow_posts += 1
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                stream=_CancelAfterStartedSse(token),
            )
        if (
            request.method == "POST"
            and request.url.path.endswith("/tasks/task-cancel/stop")
        ):
            stopped_tasks.append(request.url.path)
            return httpx.Response(200, json={"result": "success"})
        if request.url.path.endswith("/workflows/run/run-cancel"):
            return httpx.Response(
                200,
                json={"id": "run-cancel", "status": "stopped"},
            )
        return httpx.Response(404)

    runner = ReliableWorkflowRunner(
        base_url="https://dify.test/v1",
        api_key="app-test",
        timeout=5,
        cancellation_token=token,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RequestCancelled):
        runner.run(
            {
                "inputs": {"query": "test"},
                "response_mode": "streaming",
                "user": "resilience-test",
            }
        )

    assert workflow_posts == 1
    assert stopped_tasks == ["/v1/workflows/tasks/task-cancel/stop"]


def test_unknown_failure_is_classified_and_stops_known_remote_task():
    stop_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal stop_requests
        if request.url.path.endswith("/workflows/run"):
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                stream=_UnexpectedFailureSse(),
            )
        if request.url.path.endswith("/tasks/task-unknown/stop"):
            stop_requests += 1
            return httpx.Response(200, json={"result": "success"})
        if request.url.path.endswith("/workflows/run/run-unknown"):
            return httpx.Response(
                200,
                json={"id": "run-unknown", "status": "stopped"},
            )
        return httpx.Response(404)

    runner = ReliableWorkflowRunner(
        base_url="https://dify.test/v1",
        api_key="app-test",
        timeout=5,
        cancellation_token=CancellationToken(),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(WorkflowTransportError) as exc_info:
        runner.run(
            {
                "inputs": {"query": "test"},
                "response_mode": "streaming",
                "user": "resilience-test",
            }
        )

    assert exc_info.value.category == "unexpected"
    assert "ValueError" in str(exc_info.value)
    assert stop_requests == 1


def test_stop_is_not_reported_complete_until_run_is_terminal():
    statuses = iter(["running", "stopped"])
    status_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal status_requests
        if request.url.path.endswith("/tasks/task-stop/stop"):
            return httpx.Response(200, json={"result": "success"})
        if request.url.path.endswith("/workflows/run/run-stop"):
            status_requests += 1
            return httpx.Response(
                200,
                json={"id": "run-stop", "status": next(statuses)},
            )
        return httpx.Response(404)

    runner = ReliableWorkflowRunner(
        base_url="https://dify.test/v1",
        api_key="app-test",
        timeout=5,
        cancellation_token=CancellationToken(),
        transport=httpx.MockTransport(handler),
    )
    runner.handle.reset("resilience-test")
    runner.handle.update(
        task_id="task-stop",
        workflow_run_id="run-stop",
    )

    assert runner.stop_remote()
    assert status_requests == 2


def test_transport_failure_stops_and_confirms_known_remote_run(monkeypatch):
    stop_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal stop_requests
        if request.url.path.endswith("/tasks/task-timeout/stop"):
            stop_requests += 1
            return httpx.Response(200, json={"result": "success"})
        if request.url.path.endswith("/workflows/run/run-timeout"):
            return httpx.Response(
                200,
                json={"id": "run-timeout", "status": "stopped"},
            )
        return httpx.Response(404)

    runner = ReliableWorkflowRunner(
        base_url="https://dify.test/v1",
        api_key="app-test",
        timeout=5,
        cancellation_token=CancellationToken(),
        transport=httpx.MockTransport(handler),
    )

    def fail_after_start(*args, **kwargs):
        runner.handle.update(
            task_id="task-timeout",
            workflow_run_id="run-timeout",
        )
        raise WorkflowTransportError(
            "recovery timed out",
            status_code=408,
            category="network_timeout",
        )

    monkeypatch.setattr(runner, "_open_stream", fail_after_start)

    with pytest.raises(WorkflowTransportError):
        runner.run(
            {
                "inputs": {"query": "test"},
                "response_mode": "streaming",
                "user": "resilience-test",
            }
        )

    assert stop_requests == 1


def test_task_supervisor_keeps_new_task_active_after_old_cleanup():
    supervisor = TaskSupervisor("analysis")
    old_runtime = supervisor.activate(object(), object())

    retired = supervisor.retire_active(superseded=True)
    new_runtime = supervisor.activate(object(), object())

    assert retired is old_runtime
    assert old_runtime.state is TaskState.SUPERSEDED
    assert supervisor.finish(old_runtime.generation) is False
    assert supervisor.is_active(new_runtime.generation)
    assert supervisor.active_runtime is new_runtime


def test_resume_monitor_emits_only_after_long_event_loop_pause(qapp):
    now = [100.0]
    gaps: list[float] = []
    monitor = ResumeMonitor(
        interval_ms=1000,
        resume_gap_seconds=30,
        clock=lambda: now[0],
    )
    monitor._timer.stop()
    monitor.resumed.connect(gaps.append)

    now[0] = 110.0
    monitor.check_now()
    now[0] = 145.0
    monitor.check_now()

    assert gaps == [35.0]


def test_cancelled_local_execution_terminates_child_process(tmp_path):
    script = tmp_path / "long_running.py"
    script.write_text("while True:\n    pass\n", encoding="utf-8")
    token = CancellationToken()
    cancel_timer = threading.Timer(0.15, token.cancel)
    cancel_timer.start()

    try:
        with pytest.raises(RequestCancelled):
            Executor()._run_subprocess(
                str(script),
                timeout=10,
                memory_limit_mb=256,
                cancellation_token=token,
            )
    finally:
        cancel_timer.cancel()


class _CooperativeAnalysisWorker(QObject):
    event = Signal(dict)
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, **kwargs) -> None:
        super().__init__()
        self._stop = threading.Event()

    @Slot()
    def run(self) -> None:
        self.event.emit(
            {
                "type": "status",
                "message": "fake worker started",
                "worker_thread_id": threading.get_ident(),
            }
        )
        while not self._stop.wait(0.01):
            pass
        self.error.emit("Request cancelled")

    def cancel(self) -> None:
        self._stop.set()


class _CooperativeMetricWorker(QObject):
    event = Signal(dict)
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, request) -> None:
        super().__init__()
        self.request = request
        self._stop = threading.Event()

    @Slot()
    def run(self) -> None:
        self.event.emit(
            {
                "type": "status",
                "message": "fake metric worker started",
                "worker_thread_id": threading.get_ident(),
            }
        )
        while not self._stop.wait(0.01):
            pass
        self.error.emit("Request cancelled")

    def cancel(self) -> None:
        self._stop.set()


def _wait_until(qapp, predicate, timeout_ms: int = 3000) -> bool:
    elapsed = 0
    while elapsed < timeout_ms:
        qapp.processEvents()
        if predicate():
            return True
        QTest.qWait(10)
        elapsed += 10
    qapp.processEvents()
    return bool(predicate())


def _thread_is_stopped(thread) -> bool:
    try:
        return not thread.isRunning()
    except RuntimeError:
        return True


def test_analysis_cancel_allows_immediate_restart_and_ignores_old_cleanup(
    qapp,
    monkeypatch,
):
    import ui.main_window as main_window_module

    window = main_window_module.MainWindow()
    monkeypatch.setattr(
        main_window_module,
        "AnalysisWorker",
        _CooperativeAnalysisWorker,
    )
    main_thread_id = threading.get_ident()
    callback_threads: list[int] = []
    worker_thread_ids: list[int] = []
    original_handler = window._on_worker_event

    def record_event(event: dict) -> None:
        callback_threads.append(threading.get_ident())
        worker_thread_ids.append(int(event["worker_thread_id"]))
        original_handler(event)

    monkeypatch.setattr(window, "_on_worker_event", record_event)

    window._start_analysis_worker(mode="prepare", files_meta=[])
    assert _wait_until(qapp, lambda: len(callback_threads) == 1)
    old_thread = window._analysis_thread
    old_worker = window._analysis_worker

    window._cancel_analysis()
    window._start_analysis_worker(mode="prepare", files_meta=[])
    new_worker = window._analysis_worker
    new_generation = window._analysis_tasks.active_generation
    assert _wait_until(qapp, lambda: len(callback_threads) == 2)
    assert _wait_until(qapp, lambda: _thread_is_stopped(old_thread))

    assert old_worker._stop.is_set()
    assert new_worker is not old_worker
    assert window._analysis_worker is new_worker
    assert window._analysis_tasks.active_generation == new_generation
    assert window.run_btn.text() == "Working"
    assert callback_threads == [main_thread_id, main_thread_id]
    assert all(worker_id != main_thread_id for worker_id in worker_thread_ids)

    window._cancel_analysis()
    assert _wait_until(
        qapp,
        lambda: all(
            not runtime.thread.isRunning()
            for runtime in window._analysis_tasks.all_runtimes()
        ),
    )
    window.close()


def test_metric_cancel_allows_immediate_restart_on_ui_thread(
    qapp,
    monkeypatch,
):
    import ui.main_window as main_window_module

    window = main_window_module.MainWindow()
    monkeypatch.setattr(
        main_window_module,
        "MetricDiscoveryWorker",
        _CooperativeMetricWorker,
    )
    main_thread_id = threading.get_ident()
    callback_threads: list[int] = []
    worker_thread_ids: list[int] = []
    original_handler = window.metric_page.handle_event

    def record_event(event: dict) -> None:
        callback_threads.append(threading.get_ident())
        worker_thread_ids.append(int(event["worker_thread_id"]))
        original_handler(event)

    monkeypatch.setattr(window.metric_page, "handle_event", record_event)
    first_request = MetricDiscoveryRequest(
        company_information={"company_name": "First"},
        indicator_guidance={"indicator_count": 5},
    )
    second_request = MetricDiscoveryRequest(
        company_information={"company_name": "Second"},
        indicator_guidance={"indicator_count": 5},
    )

    window.metric_page.show_busy()
    window._launch_metric_worker(first_request)
    assert _wait_until(qapp, lambda: len(callback_threads) == 1)
    old_thread = window._metric_thread
    old_worker = window._metric_worker

    window._cancel_metric_discovery()
    window.metric_page.show_busy()
    window._launch_metric_worker(second_request)
    new_worker = window._metric_worker
    new_generation = window._metric_tasks.active_generation

    assert _wait_until(qapp, lambda: len(callback_threads) == 2)
    assert _wait_until(qapp, lambda: _thread_is_stopped(old_thread))
    assert old_worker._stop.is_set()
    assert new_worker is not old_worker
    assert window._metric_worker is new_worker
    assert window._metric_tasks.active_generation == new_generation
    assert callback_threads == [main_thread_id, main_thread_id]
    assert all(worker_id != main_thread_id for worker_id in worker_thread_ids)

    window._cancel_metric_discovery()
    assert _wait_until(
        qapp,
        lambda: all(
            _thread_is_stopped(runtime.thread)
            for runtime in window._metric_tasks.all_runtimes()
        ),
    )
    window.close()
