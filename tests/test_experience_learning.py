from __future__ import annotations

import json
import shutil
from types import SimpleNamespace

import httpx
import pandas as pd
import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtTest import QTest

from config.settings import settings
from core.analysis_result import AnalysisResult, AnswerResult
from core.executor import ExecutionResult
from core.experience_payload import FORBIDDEN_KEYS, build_experience_payload
from core.preprocessor import FileMeta, Preprocessor, SheetMeta
from dify.experience_client import ExperienceClient, ExperienceClientError
from services.experience_service import ExperienceService
from ui.experience_feedback import ExperienceFeedbackCard
from ui.main_window import MainWindow
from workers.experience_worker import ExperienceSubmissionQueue


def _sheet_meta() -> SheetMeta:
    return SheetMeta(
        sheet_name="JE",
        sheet_id="sh_je",
        rows=100,
        cols=4,
        columns=["Posting Date", "Account", "Debit", "Credit"],
        dtypes={
            "Posting Date": "datetime64[ns]",
            "Account": "object",
            "Debit": "float64",
            "Credit": "float64",
        },
        null_counts={},
        head_sample=[],
        describe={},
        unique_values={},
        semantic_roles={
            "date": ["Posting Date"],
            "account": ["Account"],
            "debit": ["Debit"],
            "credit": ["Credit"],
            "amount": ["Debit", "Credit"],
        },
    )


def _file_meta() -> FileMeta:
    sheet = _sheet_meta()
    return FileMeta(
        file_path=r"C:\clients\secret\je.xlsx",
        file_name="je.xlsx",
        file_size_kb=120,
        sheet_count=1,
        sheets=[sheet],
        dataset_id="ds_local",
        source_fingerprint="path-bound-value",
        content_hash="a" * 64,
        schema_family_id=Preprocessor.schema_family_id([sheet]),
    )


def _analysis_result() -> AnalysisResult:
    return AnalysisResult(
        summary="Revenue increased by 115.50 and margin reached 12.3%.",
        answers=[
            AnswerResult(
                answer_id="R1",
                question="Compare debit and credit",
                answer="Sensitive numeric answer",
            )
        ],
        completed_requirements=["R1"],
        audit=[
            {
                "kind": "load",
                "dataset_id": "ds_local",
                "sheet_id": "sh_je",
                "rows": 100,
                "columns": ["Debit", "Credit"],
                "sampled": False,
                "guarded": False,
            },
            {
                "kind": "join",
                "left": "journal",
                "right": "account_map",
                "left_on": "Account",
                "right_on": "Account",
                "relationship": "many_to_one",
                "row_multiplier": 1.0,
            },
        ],
        raw_output="This must never leave the client.",
    )


def _walk_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key).lower()
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def test_experience_payload_is_policy_bounded(monkeypatch):
    monkeypatch.setattr(settings, "EXPERIENCE_TENANT_ID", "tenant")
    monkeypatch.setattr(settings, "EXPERIENCE_PROJECT_ID", "project")
    monkeypatch.setattr(settings, "EXPERIENCE_USER_ID", "user-1")
    payload = build_experience_payload(
        analysis_session_id="session-1",
        analysis_run_id="run-1",
        files_meta=[_file_meta()],
        user_query=(
            r"Compare debit and credit in C:\clients\secret\je.xlsx "
            "using api_key=very-secret-value"
        ),
        analysis_plan={
            "task_summary": "Compare journal amounts",
            "requirements": [
                {
                    "id": "R1",
                    "objective": "Compare debit and credit",
                    "sources": [{"columns": ["Debit", "Credit"]}],
                    "grain": "Account",
                    "formula": "Debit - Credit",
                    "output_type": "table",
                }
            ],
        },
        analysis_result=_analysis_result(),
        repair_count=1,
        manual_edit=True,
    )

    encoded = json.dumps(payload, ensure_ascii=False)
    assert payload["consent_to_extract"] is True
    assert payload["dataset"]["content_hash"] == "a" * 64
    assert payload["execution"]["semantic_audit_passed"] is True
    assert payload["execution"]["repair_count"] == 1
    assert payload["execution"]["manual_edit"] is True
    assert set(_walk_keys(payload)).isdisjoint(FORBIDDEN_KEYS)
    assert "very-secret-value" not in encoded
    assert r"C:\clients" not in encoded
    assert "115.50" not in payload["result"]["summary_redacted"]
    assert "This must never leave the client" not in encoded


def test_content_hash_is_copy_stable_and_schema_family_ignores_values(tmp_path):
    first = tmp_path / "first.xlsx"
    copied = tmp_path / "copied.xlsx"
    second = tmp_path / "second.xlsx"
    pd.DataFrame({"Account": ["1000"], "Amount": [10.0]}).to_excel(
        first,
        index=False,
    )
    shutil.copyfile(first, copied)
    pd.DataFrame({"Account": ["2000"], "Amount": [99.0]}).to_excel(
        second,
        index=False,
    )

    first_meta = Preprocessor().process(str(first))
    copied_meta = Preprocessor().process(str(copied))
    second_meta = Preprocessor().process(str(second))

    assert first_meta.content_hash == copied_meta.content_hash
    assert first_meta.source_fingerprint != copied_meta.source_fingerprint
    assert first_meta.schema_family_id == second_meta.schema_family_id
    assert first_meta.content_hash != second_meta.content_hash
    reordered = second_meta.sheets[0]
    reordered.columns = list(reversed(reordered.columns))
    assert first_meta.schema_family_id == Preprocessor.schema_family_id([reordered])


def test_experience_payload_compacts_wide_multi_dataset_sessions(monkeypatch):
    monkeypatch.setattr(settings, "EXPERIENCE_TENANT_ID", "tenant")
    monkeypatch.setattr(settings, "EXPERIENCE_PROJECT_ID", "project")
    monkeypatch.setattr(settings, "EXPERIENCE_USER_ID", "user-1")
    monkeypatch.setattr(settings, "EXPERIENCE_MAX_PAYLOAD_CHARS", 40000)
    files_meta = []
    for dataset_index in range(3):
        columns = [
            f"Dataset {dataset_index} Column {column_index}"
            for column_index in range(120)
        ]
        sheet = SheetMeta(
            sheet_name="Data",
            sheet_id=f"sh_{dataset_index}",
            rows=1000,
            cols=len(columns),
            columns=columns,
            dtypes={column: "object" for column in columns},
            null_counts={},
            head_sample=[],
            describe={},
            unique_values={},
            semantic_roles={"account": columns[:20]},
        )
        files_meta.append(
            FileMeta(
                file_path=f"C:/private/{dataset_index}.xlsx",
                file_name=f"{dataset_index}.xlsx",
                file_size_kb=1000,
                sheet_count=1,
                sheets=[sheet],
                content_hash=str(dataset_index) * 64,
                schema_family_id=Preprocessor.schema_family_id([sheet]),
            )
        )
    requirements = [
        {
            "id": f"R{index}",
            "objective": "Analyze every requested dimension " * 80,
            "sources": [{"columns": files_meta[0].sheets[0].columns}],
            "grain": "Account and period",
            "formula": "Debit minus credit " * 40,
            "output_type": "table",
        }
        for index in range(25)
    ]

    payload = build_experience_payload(
        analysis_session_id="session-wide",
        analysis_run_id="run-wide",
        files_meta=files_meta,
        user_query="Compare all financial dimensions. " * 400,
        analysis_plan={
            "task_summary": "Wide financial analysis " * 200,
            "requirements": requirements,
        },
        analysis_result=_analysis_result(),
    )

    assert len(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    ) <= 40000
    assert payload["request"]["original_query"]
    assert payload["dataset"]["field_roles"]["account"]
    assert payload["plan"]["requirements"]


def test_experience_client_requires_confirmed_knowledge_write(monkeypatch):
    monkeypatch.setattr(settings, "DIFY_EXPERIENCE_BASE_URL", "https://dify.test/v1")
    monkeypatch.setattr(settings, "DIFY_EXPERIENCE_API_KEY", "app-key")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/v1/workflows/run"
        assert body["response_mode"] == "blocking"
        assert json.loads(body["inputs"]["session_payload"])["schema_version"] == "1.0"
        return httpx.Response(
            200,
            json={
                "workflow_run_id": "workflow-1",
                "task_id": "task-1",
                "data": {
                    "status": "succeeded",
                    "outputs": {
                        "knowledge_write_status": "uploaded",
                        "candidate_count": 2,
                        "uploaded_count": 2,
                        "failed_count": 0,
                    },
                },
            },
        )

    result = ExperienceClient(
        transport=httpx.MockTransport(handler)
    ).submit(
        {
            "schema_version": "1.0",
            "actor": {"user_id": "user-1"},
        }
    )

    assert result.workflow_run_id == "workflow-1"
    assert result.knowledge_write_status == "uploaded"
    assert result.uploaded_count == 2


def test_experience_workflow_connection_is_built_in(monkeypatch):
    monkeypatch.setenv(
        "DIFY_EXPERIENCE_BASE_URL",
        "https://should-not-override.test/v1",
    )
    monkeypatch.setenv("DIFY_EXPERIENCE_API_KEY", "should-not-override")

    settings.reload()

    assert settings.DIFY_EXPERIENCE_BASE_URL == (
        "https://ai-platform-uat.ey.net/v1"
    )
    assert settings.DIFY_EXPERIENCE_API_KEY.startswith("app-")
    assert settings.DIFY_EXPERIENCE_API_KEY != "should-not-override"


def test_experience_client_rejects_extraction_only_response(monkeypatch):
    monkeypatch.setattr(settings, "DIFY_EXPERIENCE_BASE_URL", "https://dify.test/v1")
    monkeypatch.setattr(settings, "DIFY_EXPERIENCE_API_KEY", "app-key")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "data": {
                    "status": "succeeded",
                    "outputs": {"candidate_count": 1},
                }
            },
        )
    )

    with pytest.raises(ExperienceClientError, match="knowledge-base write"):
        ExperienceClient(transport=transport).submit(
            {
                "schema_version": "1.0",
                "actor": {"user_id": "user-1"},
            }
        )


def test_feedback_card_is_compact_and_acknowledges_useful(qapp):
    card = ExperienceFeedbackCard()
    accepted = []
    card.useful.connect(lambda: accepted.append(True))
    card.show_prompt(QRect(20, 20, 340, 126))
    qapp.processEvents()

    assert card.isVisible()
    assert card.size().width() == 340
    assert "是否对你有用" in card.title_label.text()

    QTest.mouseClick(card.useful_button, Qt.LeftButton)
    qapp.processEvents()

    assert accepted == [True]
    assert card.title_label.text() == "谢谢！"
    assert not card.useful_button.isVisible()
    card.close()


def test_experience_prompt_requires_verified_full_execution(monkeypatch):
    monkeypatch.setattr(settings, "EXPERIENCE_LEARNING_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "DIFY_EXPERIENCE_BASE_URL",
        "https://dify.test/v1",
    )
    monkeypatch.setattr(settings, "DIFY_EXPERIENCE_API_KEY", "app-key")
    task = {
        "status": "Completed",
        "finished": True,
        "analysis_verified": False,
        "experience_prompted": False,
        "analysis_result": {"summary": "Sample result"},
    }

    assert not ExperienceService.should_prompt(task)
    task["analysis_verified"] = True
    assert ExperienceService.should_prompt(task)


def test_experience_submission_queue_runs_silently_in_order(qapp, monkeypatch):
    submitted_payloads = []

    def submit(payload, *, cancellation_token=None):
        submitted_payloads.append(payload["sequence"])
        return SimpleNamespace(
            workflow_run_id=f"workflow-{payload['sequence']}",
            knowledge_write_status="uploaded",
            candidate_count=1,
            uploaded_count=1,
            failed_count=0,
        )

    monkeypatch.setattr(ExperienceService, "submit", staticmethod(submit))
    queue = ExperienceSubmissionQueue()
    completed = []
    queue.submitted.connect(
        lambda task_id, result: completed.append(
            (task_id, result.workflow_run_id)
        )
    )
    queue.enqueue(1, {"sequence": 1})
    queue.enqueue(2, {"sequence": 2})

    for _ in range(100):
        if len(completed) == 2:
            break
        QTest.qWait(10)
        qapp.processEvents()

    assert submitted_payloads == [1, 2]
    assert completed == [(1, "workflow-1"), (2, "workflow-2")]
    queue.shutdown()


def test_main_window_prompts_once_and_queues_sanitized_payload(
    qapp,
    monkeypatch,
):
    window = MainWindow()
    window.show()
    monkeypatch.setattr(settings, "EXPERIENCE_LEARNING_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "DIFY_EXPERIENCE_BASE_URL",
        "https://dify.test/v1",
    )
    monkeypatch.setattr(settings, "DIFY_EXPERIENCE_API_KEY", "app-key")
    monkeypatch.setattr(settings, "EXPERIENCE_TENANT_ID", "tenant")
    monkeypatch.setattr(settings, "EXPERIENCE_PROJECT_ID", "project")
    monkeypatch.setattr(settings, "EXPERIENCE_USER_ID", "user-1")

    window._start_new_task()
    file_meta = _file_meta()
    window._pending_files_meta = [file_meta]
    window._pending_query = "Compare debit and credit"
    window._create_history_task("je.xlsx", window._pending_query)
    window._generated_code = "result.set_summary('done')"
    task_id = window._active_task_id
    task = window._find_history_task(task_id)
    task["generated_code"] = window._generated_code
    task["analysis_plan"] = {
        "task_summary": "Compare journal amounts",
        "requirements": [
            {
                "id": "R1",
                "objective": "Compare debit and credit",
                "sources": [{"columns": ["Debit", "Credit"]}],
                "output_type": "answer",
            }
        ],
    }
    queued = []
    monkeypatch.setattr(
        window,
        "_enqueue_experience_submission",
        lambda current_task_id, payload: queued.append(
            (current_task_id, payload)
        ),
    )

    execution = ExecutionResult(
        success=True,
        stdout="done",
        stderr="",
        elapsed_sec=0.1,
        analysis_result=_analysis_result(),
    )
    window._present_execution_result(window._generated_code, execution)
    window._show_experience_prompt_if_eligible(task_id)
    qapp.processEvents()

    assert window.experience_feedback.isVisible()
    assert task["experience_status"] == "prompted"

    QTest.mouseClick(window.experience_feedback.useful_button, Qt.LeftButton)
    qapp.processEvents()

    assert len(queued) == 1
    assert queued[0][0] == task_id
    assert queued[0][1]["consent_to_extract"] is True
    assert task["experience_consent"] is True
    assert task["experience_status"] == "queued"

    window._show_experience_prompt_if_eligible(task_id)
    assert task["experience_status"] == "queued"
    window.close()
