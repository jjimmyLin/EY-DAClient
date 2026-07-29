from __future__ import annotations

import json
import threading

import httpx
import pytest

from core.executor import Executor
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


class _FakeSignal:
    def __init__(self) -> None:
        self._callbacks = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in tuple(self._callbacks):
            callback(*args)


class _FakeThread:
    def __init__(self, parent=None) -> None:
        self.started = _FakeSignal()
        self.finished = _FakeSignal()
        self.running = False

    def start(self) -> None:
        self.running = True

    def quit(self) -> None:
        self.running = False

    def wait(self, timeout: int) -> bool:
        return True

    def isRunning(self) -> bool:
        return self.running

    def deleteLater(self) -> None:
        pass


class _FakeAnalysisWorker:
    def __init__(self, **kwargs) -> None:
        self.event = _FakeSignal()
        self.finished = _FakeSignal()
        self.error = _FakeSignal()
        self.cancelled = False

    def moveToThread(self, thread) -> None:
        pass

    def run(self) -> None:
        pass

    def cancel(self) -> None:
        self.cancelled = True

    def deleteLater(self) -> None:
        pass


def test_analysis_cancel_allows_immediate_restart_and_ignores_old_cleanup(
    qapp,
    monkeypatch,
):
    import ui.main_window as main_window_module

    window = main_window_module.MainWindow()
    monkeypatch.setattr(main_window_module, "QThread", _FakeThread)
    monkeypatch.setattr(
        main_window_module,
        "AnalysisWorker",
        _FakeAnalysisWorker,
    )

    window._start_analysis_worker(mode="prepare", files_meta=[])
    old_thread = window._analysis_thread
    old_worker = window._analysis_worker

    window._cancel_analysis()
    window._start_analysis_worker(mode="prepare", files_meta=[])
    new_worker = window._analysis_worker
    new_generation = window._analysis_tasks.active_generation
    old_thread.finished.emit()

    assert old_worker.cancelled
    assert new_worker is not old_worker
    assert window._analysis_worker is new_worker
    assert window._analysis_tasks.active_generation == new_generation
    assert window.run_btn.text() == "Working"

    window.close()
