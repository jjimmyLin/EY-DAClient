from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QEvent
from PySide6.QtTest import QTest

from core.preprocessor import FileMeta, SheetMeta
from core.analysis_result import (
    AnalysisResult,
    InsightResult,
    MetricResult,
    TableResult,
)
from config.settings import settings
from core.executor import ExecutionResult
from ui.main_window import MainWindow


def test_python_tab_stays_hidden_until_code_is_ready(qapp):
    window = MainWindow()

    assert not window.analysis_tabs.tabBar().isTabVisible(window.python_tab_index)

    window._start_new_task()
    assert not window.analysis_tabs.tabBar().isTabVisible(window.python_tab_index)

    window._generated_code = "print('ok')"
    window.code_editor.setPlainText(window._generated_code)
    window._show_apply_action()

    assert window.analysis_tabs.tabBar().isTabVisible(window.python_tab_index)

    window.close()


def test_task_title_does_not_include_error_detail(qapp):
    window = MainWindow()
    window._start_new_task()
    window._pending_files_meta = []
    window._create_history_task("TEST.xlsx", "Check totals")
    window._update_history_task(
        "Failed",
        "Backend stack trace should stay out of the top bar",
        finished=True,
        error="Backend stack trace should stay out of the top bar",
    )

    assert window.task_title_label.text() == "Session #1"
    assert "Backend stack trace" not in window.task_title_label.text()

    window.close()


def test_overview_and_suggestion_chips_follow_selected_dataset(qapp):
    window = MainWindow()
    window.show()
    qapp.processEvents()
    window._start_new_task()

    file_meta = FileMeta(
        file_path="C:/demo.xlsx",
        file_name="demo.xlsx",
        file_size_kb=12.0,
        sheet_count=1,
        sheets=[
            SheetMeta(
                sheet_name="Sheet1",
                rows=12,
                cols=3,
                columns=["region", "sales", "month"],
                dtypes={"region": "object", "sales": "float64", "month": "object"},
                null_counts={},
                head_sample=[],
                describe={},
                unique_values={"region": ["APAC", "EMEA"]},
            )
        ],
    )
    window.loaded_files["demo.xlsx"] = file_meta
    window._add_dataset_item("demo.xlsx")
    window.dataset_list.setCurrentRow(0)
    window._dataset_overviews["demo.xlsx"] = {
        "state": "ready",
        "data": {
            "dataset_kind": "Sales dataset",
            "topic": "Monthly sales by region",
            "summary": "A compact monthly sales file.",
            "rows": 12,
            "columns": 3,
            "sheet_count": 1,
            "suggestions": [
                "Compare sales by region.",
                "Show the monthly sales trend.",
            ],
        },
    }

    window._refresh_overview_ui("demo.xlsx")
    qapp.processEvents()

    row_widget = window._dataset_row_widgets["demo.xlsx"]
    assert row_widget is window.dataset_list.itemWidget(window.dataset_list.item(0))
    assert not row_widget.overview_button.isBusy()
    assert window.suggestion_btn.isVisible()
    assert len(window._suggestion_buttons) == 2

    window._apply_suggestion(window._suggestion_buttons[0])
    assert "Compare sales by region." in window.prompt_input.toPlainText()

    window.close()


def test_each_imported_dataset_can_have_its_own_overview_state(qapp):
    window = MainWindow()
    window.show()
    qapp.processEvents()
    window._start_new_task()

    first = FileMeta(
        file_path="C:/first.xlsx",
        file_name="first.xlsx",
        file_size_kb=8.0,
        sheet_count=1,
        sheets=[
            SheetMeta(
                sheet_name="Sheet1",
                rows=10,
                cols=2,
                columns=["category", "amount"],
                dtypes={"category": "object", "amount": "float64"},
                null_counts={},
                head_sample=[],
                describe={},
                unique_values={"category": ["A", "B"]},
            )
        ],
    )
    second = FileMeta(
        file_path="C:/second.xlsx",
        file_name="second.xlsx",
        file_size_kb=8.0,
        sheet_count=1,
        sheets=[
            SheetMeta(
                sheet_name="Sheet1",
                rows=12,
                cols=2,
                columns=["region", "sales"],
                dtypes={"region": "object", "sales": "float64"},
                null_counts={},
                head_sample=[],
                describe={},
                unique_values={"region": ["APAC", "EMEA"]},
            )
        ],
    )

    window.loaded_files["first.xlsx"] = first
    window.loaded_files["second.xlsx"] = second
    window._add_dataset_item("first.xlsx")
    window._add_dataset_item("second.xlsx")
    window.dataset_list.setCurrentRow(0)
    window._dataset_overviews["first.xlsx"] = {"state": "loading"}
    window._dataset_overviews["second.xlsx"] = {
        "state": "ready",
        "data": {
            "dataset_kind": "Sales dataset",
            "topic": "Regional sales",
            "summary": "Sales by region.",
            "rows": 12,
            "columns": 2,
            "sheet_count": 1,
            "suggestions": ["Compare sales by region."],
        },
    }

    window._refresh_overview_ui("first.xlsx")
    window._refresh_overview_ui("second.xlsx")
    qapp.processEvents()

    assert window._dataset_row_widgets["first.xlsx"].overview_button.isBusy()
    assert not window._dataset_row_widgets["second.xlsx"].overview_button.isBusy()

    window.close()


def test_queued_overview_continues_with_next_dataset(qapp):
    window = MainWindow()
    window.show()
    qapp.processEvents()
    window._start_new_task()

    first = FileMeta(
        file_path="C:/first.xlsx",
        file_name="first.xlsx",
        file_size_kb=8.0,
        sheet_count=1,
        sheets=[
            SheetMeta(
                sheet_name="Sheet1",
                rows=10,
                cols=2,
                columns=["category", "amount"],
                dtypes={"category": "object", "amount": "float64"},
                null_counts={},
                head_sample=[],
                describe={},
                unique_values={"category": ["A", "B"]},
            )
        ],
    )
    second = FileMeta(
        file_path="C:/second.xlsx",
        file_name="second.xlsx",
        file_size_kb=8.0,
        sheet_count=1,
        sheets=[
            SheetMeta(
                sheet_name="Sheet1",
                rows=12,
                cols=2,
                columns=["region", "sales"],
                dtypes={"region": "object", "sales": "float64"},
                null_counts={},
                head_sample=[],
                describe={},
                unique_values={"region": ["APAC", "EMEA"]},
            )
        ],
    )

    window.loaded_files["first.xlsx"] = first
    window.loaded_files["second.xlsx"] = second
    window._dataset_overviews = {
        "first.xlsx": {"state": "ready", "data": {"summary": "ok"}},
        "second.xlsx": {"state": "queued"},
    }

    started = []

    def fake_start(dataset_name, file_meta):
        started.append((dataset_name, file_meta.file_name))

    window._start_overview_worker = fake_start
    window._cleanup_overview_worker()

    assert started == [("second.xlsx", "second.xlsx")]
    assert window._dataset_overviews["second.xlsx"]["state"] == "loading"

    window.close()


def test_failed_overview_shows_retry_without_overview_or_suggestions(qapp):
    window = MainWindow()
    window.show()
    qapp.processEvents()
    window._start_new_task()

    file_meta = FileMeta(
        file_path="C:/retry.xlsx",
        file_name="retry.xlsx",
        file_size_kb=8.0,
        sheet_count=1,
        sheets=[
            SheetMeta(
                sheet_name="Sheet1",
                rows=10,
                cols=2,
                columns=["category", "amount"],
                dtypes={"category": "object", "amount": "float64"},
                null_counts={},
                head_sample=[],
                describe={},
                unique_values={"category": ["A", "B"]},
            )
        ],
    )
    window.loaded_files["retry.xlsx"] = file_meta
    window._add_dataset_item("retry.xlsx")

    started = []

    def fake_start(dataset_name, meta):
        started.append((dataset_name, meta.file_name))

    window._start_overview_worker = fake_start
    window.dataset_list.setCurrentRow(0)
    started.clear()
    window._dataset_overviews["retry.xlsx"] = {
        "state": "error",
        "data": {},
        "error": "network unavailable",
    }

    window._refresh_overview_ui("retry.xlsx")
    qapp.processEvents()

    row_widget = window._dataset_row_widgets["retry.xlsx"]
    assert row_widget.overview_button.isVisible()
    assert row_widget.overview_button.isEnabled()
    assert row_widget.overview_button._glyph == "↻"
    assert not window.overview_popover.isVisible()
    assert not window.suggestion_btn.isVisible()
    assert window._suggestion_buttons == []

    window._show_overview_for_dataset("retry.xlsx")

    assert started == [("retry.xlsx", "retry.xlsx")]
    assert window._dataset_overviews["retry.xlsx"]["state"] == "loading"
    assert row_widget.overview_button.isBusy()
    assert not window.overview_popover.isVisible()
    assert not window.suggestion_btn.isVisible()

    window._overview_loading_dataset = "retry.xlsx"
    window._overview_loading_meta = file_meta
    window._on_overview_finished(
        SimpleNamespace(
            success=True,
            error="",
            overview_result={
                "dataset_kind": "Sales dataset",
                "topic": "Category totals",
                "summary": "A small category and amount dataset.",
                "rows": 10,
                "columns": 2,
                "sheet_count": 1,
                "suggestions": ["Compare amount by category."],
            },
        )
    )
    qapp.processEvents()

    assert row_widget.overview_button._glyph == "i"
    assert not row_widget.overview_button.isBusy()
    assert window.suggestion_btn.isVisible()
    assert window._suggestion_buttons == ["Compare amount by category."]

    window._show_overview_for_dataset("retry.xlsx")
    qapp.processEvents()
    assert window.overview_popover.isVisible()

    window.close()


def test_removing_dataset_cleans_state_and_selects_remaining_dataset(qapp):
    window = MainWindow()
    window.show()
    qapp.processEvents()
    window._start_new_task()

    first = FileMeta(
        file_path="C:/first.xlsx",
        file_name="first.xlsx",
        file_size_kb=8.0,
        sheet_count=1,
        sheets=[],
    )
    second = FileMeta(
        file_path="C:/second.xlsx",
        file_name="second.xlsx",
        file_size_kb=8.0,
        sheet_count=1,
        sheets=[],
    )
    window.loaded_files = {"first.xlsx": first, "second.xlsx": second}
    window._add_dataset_item("first.xlsx")
    window._add_dataset_item("second.xlsx")
    window.dataset_list.setCurrentRow(0)
    window._dataset_overviews["first.xlsx"] = {
        "state": "ready",
        "data": {"summary": "First", "suggestions": ["Inspect first."]},
    }
    window._pending_files_meta = [first]
    window._pending_query = "Inspect first"
    window._generated_code = "print('first')"
    window.code_editor.setPlainText(window._generated_code)

    window._remove_dataset("first.xlsx")
    qapp.processEvents()

    assert "first.xlsx" not in window.loaded_files
    assert "first.xlsx" not in window._dataset_row_widgets
    assert "first.xlsx" not in window._dataset_overviews
    assert window.dataset_list.count() == 1
    assert window._current_dataset_name() == "second.xlsx"
    assert window._pending_files_meta is None
    assert window._pending_query is None
    assert window._generated_code == ""
    assert not window.analysis_tabs.tabBar().isTabVisible(window.python_tab_index)

    window.close()


def test_deleted_dataset_ignores_late_overview_result(qapp):
    window = MainWindow()
    window._start_new_task()
    file_meta = FileMeta(
        file_path="C:/deleted.xlsx",
        file_name="deleted.xlsx",
        file_size_kb=8.0,
        sheet_count=1,
        sheets=[],
    )
    window.loaded_files["deleted.xlsx"] = file_meta
    window._add_dataset_item("deleted.xlsx")
    window._overview_loading_dataset = "deleted.xlsx"
    window._overview_loading_meta = file_meta

    window._remove_dataset("deleted.xlsx")
    window._on_overview_finished(
        SimpleNamespace(
            success=True,
            error="",
            overview_result={"summary": "Late result", "suggestions": ["Late"]},
        )
    )

    assert "deleted.xlsx" not in window.loaded_files
    assert "deleted.xlsx" not in window._dataset_overviews
    assert window.dataset_list.count() == 0

    window.close()


def test_readding_same_dataset_ignores_old_overview_and_queues_new_request(qapp):
    window = MainWindow()
    window._start_new_task()
    old_meta = FileMeta(
        file_path="C:/same.xlsx",
        file_name="same.xlsx",
        file_size_kb=8.0,
        sheet_count=1,
        sheets=[],
    )
    new_meta = FileMeta(
        file_path="C:/same.xlsx",
        file_name="same.xlsx",
        file_size_kb=9.0,
        sheet_count=1,
        sheets=[],
    )

    window.loaded_files["same.xlsx"] = old_meta
    window._add_dataset_item("same.xlsx")
    window._overview_thread = object()
    window._overview_loading_dataset = "same.xlsx"
    window._overview_loading_meta = old_meta
    window._dataset_overviews["same.xlsx"] = {"state": "loading"}
    cancelled = []
    window._overview_worker = SimpleNamespace(
        cancel=lambda: cancelled.append(True)
    )

    window._remove_dataset("same.xlsx")
    assert cancelled == [True]
    window.loaded_files["same.xlsx"] = new_meta
    window._add_dataset_item("same.xlsx")
    window.dataset_list.setCurrentRow(0)
    window._ensure_dataset_overview("same.xlsx", force=False)

    assert window._dataset_overviews["same.xlsx"]["state"] == "queued"

    window._on_overview_finished(
        SimpleNamespace(
            success=True,
            error="",
            overview_result={"summary": "Old result", "suggestions": ["Old"]},
        )
    )

    assert window._dataset_overviews["same.xlsx"]["state"] == "queued"
    assert window._dataset_row_widgets["same.xlsx"].overview_button._glyph == "i"
    assert not window.suggestion_btn.isVisible()

    started = []

    def fake_start(dataset_name, file_meta):
        started.append((dataset_name, file_meta))

    window._start_overview_worker = fake_start
    window._cleanup_overview_worker()

    assert started == [("same.xlsx", new_meta)]
    assert window._dataset_overviews["same.xlsx"]["state"] == "loading"

    window._overview_thread = None
    window.close()


def test_structured_result_and_analysis_plan_render_in_primary_workspace(qapp):
    window = MainWindow()
    window.show()
    window._start_new_task()
    window._analysis_plan = {
        "task_summary": "Review product revenue",
        "requirements": [
            {"id": "A", "objective": "Calculate revenue by product"},
            {"id": "B", "objective": "Highlight the leading product"},
        ],
        "warnings": ["Three rows have missing prices"],
    }
    window._render_analysis_plan()
    window._show_apply_action()
    window.analysis_tabs.setCurrentIndex(window.python_tab_index)
    window.result_output.set_result(
        AnalysisResult(
            summary="Product A leads total revenue.",
            metrics=[MetricResult("Total revenue", 115.0, " CNY")],
            tables=[
                TableResult(
                    "Revenue by product",
                    ["Product", "Revenue"],
                    [["A", 80], ["B", 35]],
                    2,
                )
            ],
            insights=[
                InsightResult(
                    "Leading product",
                    "Product A contributes the largest share.",
                )
            ],
        )
    )
    qapp.processEvents()

    assert window.analysis_plan_label.isVisible()
    assert "Calculate revenue by product" in window.analysis_plan_label.text()
    assert "Three rows have missing prices" in window.analysis_plan_label.text()
    assert window.result_output.findChildren(
        type(window.analysis_plan_label),
        "metricValue",
    )
    assert window.result_output.findChildren(
        type(window.analysis_plan_label),
        "resultBlockTitle",
    )

    window.close()


def test_long_request_input_grows_and_shows_character_count(qapp):
    window = MainWindow()
    window.show()
    window._start_new_task()
    long_request = "\n".join(
        f"{letter}. Analyze requirement {letter} in detail."
        for letter in "ABCDEF"
    )

    window.prompt_input.setPlainText(long_request)
    qapp.processEvents()

    assert window.prompt_count_label.text() == f"{len(long_request):,} characters"
    assert window.prompt_input.height() > 64
    assert window.prompt_input.height() <= 180

    window.close()


def test_analysis_uses_all_imported_datasets(qapp, monkeypatch):
    window = MainWindow()
    window.show()
    window._start_new_task()
    first = FileMeta(
        file_path="C:/first.xlsx",
        file_name="first.xlsx",
        file_size_kb=1.0,
        sheet_count=0,
        sheets=[],
    )
    second = FileMeta(
        file_path="C:/second.xlsx",
        file_name="second.xlsx",
        file_size_kb=1.0,
        sheet_count=0,
        sheets=[],
    )
    window.loaded_files = {"first.xlsx": first, "second.xlsx": second}
    window._add_dataset_item("first.xlsx")
    window._add_dataset_item("second.xlsx")
    window.dataset_list.setCurrentRow(0)
    window.prompt_input.setPlainText("Compare the two datasets")
    monkeypatch.setattr(settings, "reload", lambda: None)
    monkeypatch.setattr(settings, "validate_selected_provider", lambda: None)
    monkeypatch.setattr(window, "_run_generate", lambda: None)

    window._on_analyze_clicked()

    assert window._pending_files_meta == [first, second]
    task = window._find_history_task(window._active_task_id)
    assert task is not None
    assert task["dataset"] == "first.xlsx, second.xlsx"

    window.close()


def test_activity_strip_tracks_background_work(qapp):
    window = MainWindow()
    window.show()
    window._start_new_task()

    window._set_busy(True)
    window._set_activity_message("Sending Dify workflow request")
    qapp.processEvents()

    assert window.activity_strip.isVisible()
    assert window.activity_label.text() == "Sending Dify workflow request"
    assert window.activity_progress.minimum() == 0
    assert window.activity_progress.maximum() == 0

    window._set_busy(False)
    qapp.processEvents()

    assert not window.activity_strip.isVisible()
    window.close()


def test_apply_uses_preflight_result_once(qapp, monkeypatch):
    window = MainWindow()
    window.show()
    window._start_new_task()
    file_meta = FileMeta(
        file_path="C:/test.xlsx",
        file_name="test.xlsx",
        file_size_kb=1.0,
        sheet_count=0,
        sheets=[],
    )
    window._pending_files_meta = [file_meta]
    window._pending_query = "Summarize the data"
    window._create_history_task("test.xlsx", window._pending_query)
    window.code_editor.setPlainText("result.set_summary('Ready')")
    window._verified_code = window.code_editor.toPlainText()
    window._verified_execution = ExecutionResult(
        success=True,
        stdout="",
        stderr="",
        elapsed_sec=0.1,
        analysis_result=AnalysisResult(summary="Ready"),
    )
    monkeypatch.setattr(
        window,
        "_start_analysis_worker",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("cached preflight should avoid re-execution")
        ),
    )

    window._on_apply_clicked()

    assert window._current_analysis_result.summary == "Ready"
    assert window._verified_execution is None
    assert window.analysis_tabs.currentIndex() == 0
    window.close()


def test_result_first_shell_collapses_context_and_floating_composer(qapp):
    window = MainWindow()
    window.show()
    window._start_new_task()
    qapp.processEvents()

    assert window.sidebar.isVisible()
    assert window.left_shell.width() == 268

    window._close_context_panel()
    window._composer_pinned = False
    window._collapse_composer("done")
    QTest.qWait(260)
    qapp.processEvents()

    assert not window.sidebar.isVisible()
    assert window.left_shell.width() == 48
    assert not window.command_bar.isVisible()
    assert window.composer_status_btn.isVisible()

    QTest.qWait(220)
    qapp.sendEvent(window.composer_status_btn, QEvent(QEvent.Enter))
    QTest.qWait(260)
    qapp.processEvents()

    assert window.command_bar.isVisible()
    assert not window.composer_status_btn.isVisible()
    window.close()


def test_activity_log_is_an_on_demand_drawer(qapp):
    window = MainWindow()
    window.show()
    window._start_new_task()

    assert not window.log_output.isVisible()
    window._toggle_activity_drawer()
    qapp.processEvents()
    assert window.log_output.isVisible()

    window._toggle_activity_drawer()
    qapp.processEvents()
    assert not window.log_output.isVisible()
    window.close()


def test_analysis_navigation_owns_dataset_context_and_composer_is_centered(qapp):
    window = MainWindow()
    window.show()
    window._start_new_task()
    window._close_context_panel()
    qapp.processEvents()

    assert not hasattr(window, "nav_data_btn")
    assert not hasattr(window, "nav_history_btn")

    window.nav_analysis_btn.click()
    qapp.processEvents()
    assert window.sidebar.isVisible()

    window.nav_analysis_btn.click()
    qapp.processEvents()
    assert not window.sidebar.isVisible()

    window._composer_pinned = True
    window._expand_composer(pin=True)
    window._position_floating_composer()
    qapp.processEvents()

    expected_x = (window.workspace.width() - window.command_bar.width()) // 2
    assert abs(window.command_bar.x() - expected_x) <= 1
    window.close()
