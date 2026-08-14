from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QMessageBox, QInputDialog, QWidget

from core.preprocessor import FileMeta, SheetMeta
from core.analysis_result import (
    AnalysisResult,
    AnswerResult,
    InsightResult,
    MetricResult,
    TableResult,
)
from config.settings import settings
from core.executor import ExecutionResult
from ui.fonts import CHINESE_UI_FONT_FAMILIES, configure_application_font
from ui.main_window import MainWindow


def test_application_uses_explicit_chinese_ui_font_fallbacks(qapp):
    original_font = qapp.font()
    try:
        configure_application_font(qapp)
        assert qapp.font().families() == list(
            CHINESE_UI_FONT_FAMILIES[:-1]
        )
        assert qapp.font().families()[0] == "Microsoft YaHei UI"
    finally:
        qapp.setFont(original_font)


def test_start_page_is_data_first_and_unlocks_capabilities(qapp):
    window = MainWindow()
    window.show()
    qapp.processEvents()

    assert not hasattr(window, "start_task_btn")
    assert not hasattr(window, "start_clean_btn")
    assert window.start_page.drop_zone.isVisible()
    assert not window.start_page.capability_panel.isVisible()
    tip_text = " ".join(
        label.text()
        for label in window.start_page.tips_panel.findChildren(type(window.start_page.status_label))
    )
    assert "Small files are interactive" in tip_text
    assert "Under 100 MB" in tip_text
    assert "Up to 1 GB" in tip_text
    assert "Analyze up to 3 workbooks together" in tip_text
    assert "Cleaning operates on one workbook" in tip_text
    assert not window.mode_button.isVisible()
    assert not window.dataset_library_btn.isVisible()

    window.loaded_files["ready.xlsx"] = FileMeta(
        file_path="C:/ready.xlsx",
        file_name="ready.xlsx",
        file_size_kb=1,
        sheet_count=0,
        sheets=[],
        dataset_id="ds_ready",
    )
    window._refresh_global_dataset_surfaces()
    QTest.qWait(280)
    qapp.processEvents()

    assert window.start_page.capability_panel.isVisible()
    assert window.start_page.analysis_card.text() == "Analyze Workbooks"
    assert window.start_page.cleaning_card.text() == "Clean Workbooks"
    assert window.start_page.capability_panel.maximumWidth() >= 255
    assert window.start_page.capability_panel.x() > window.start_page.drop_zone.x()
    assert not window.mode_button.isVisible()
    assert not window.dataset_library_btn.isVisible()
    window.close()


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


def test_multiline_prompt_resizes_and_composer_remains_centered(qapp):
    window = MainWindow()
    window.show()
    window._start_new_task()
    qapp.processEvents()

    initial_height = window.prompt_input.height()
    window.prompt_input.setPlainText(
        "Compare revenue by region.\n"
        "Then explain the strongest changes.\n"
        "Include a compact summary table."
    )
    qapp.processEvents()
    window._position_floating_composer()

    assert window.prompt_input.height() > initial_height
    assert window.prompt_input.height() <= 168
    expected_x = (window.workspace.width() - window.command_bar.width()) // 2
    assert abs(window.command_bar.x() - expected_x) <= 1
    window.close()


def test_import_validation_rejects_unsupported_batch_without_starting_worker(
    qapp,
    monkeypatch,
    tmp_path,
):
    window = MainWindow()
    unsupported = tmp_path / "notes.csv"
    unsupported.write_text("a,b\n1,2", encoding="utf-8")
    valid = tmp_path / "valid.xlsx"
    valid.write_bytes(b"valid")
    warnings = []
    started = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args: warnings.append(args[2]),
    )
    monkeypatch.setattr(
        window,
        "_start_import_worker",
        lambda files: started.append(files),
    )

    window._queue_dataset_files([str(valid), str(unsupported)])

    assert not started
    assert not window._dataset_states
    assert warnings
    assert "notes.csv" in warnings[0]
    assert "unsupported file type" in warnings[0]
    window.close()


def test_import_validation_rejects_oversized_file_without_starting_worker(
    qapp,
    monkeypatch,
    tmp_path,
):
    window = MainWindow()
    oversized = tmp_path / "oversized.xlsx"
    oversized.write_bytes(b"12345")
    warnings = []
    started = []
    monkeypatch.setattr(settings, "MAX_DATASET_BYTES", 4)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args: warnings.append(args[2]),
    )
    monkeypatch.setattr(
        window,
        "_start_import_worker",
        lambda files: started.append(files),
    )

    window._queue_dataset_files([str(oversized)])

    assert not started
    assert not window._dataset_states
    assert warnings
    assert "oversized.xlsx" in warnings[0]
    assert "exceeds the 1 GB per-file limit" in warnings[0]
    window.close()


def test_preflight_ready_queues_execution_and_apply_tracks_later_edits(qapp):
    window = MainWindow()
    window.show()
    window._start_new_task()
    window._pending_files_meta = [
        FileMeta(
            file_path="C:/ready.xlsx",
            file_name="ready.xlsx",
            file_size_kb=1,
            sheet_count=0,
            sheets=[],
            dataset_id="ds_ready",
        )
    ]
    window._active_worker_mode = "prepare"

    result = SimpleNamespace(
        needs_clarification=False,
        success=True,
        code="print('ready')",
        analysis_plan={"requirements": []},
        execution=None,
        preflight_only=True,
        retries_used=0,
        error="",
    )
    window._on_worker_finished(result)
    qapp.processEvents()

    assert window.analysis_tabs.currentIndex() == 0
    assert window._auto_execute_pending
    assert window.analysis_tabs.tabBar().isTabVisible(window.python_tab_index)
    assert not window.code_apply_btn.isVisible()
    assert not window.run_btn.isEnabled()
    assert window.run_btn.text() == "Queued"
    assert window.code_apply_btn.parent() is not window.command_bar

    window._present_execution_result(
        window.code_editor.toPlainText(),
        ExecutionResult(
            success=True,
            stdout="ok",
            stderr="",
            elapsed_sec=0.1,
            analysis_result=AnalysisResult(summary="Done"),
        ),
    )
    assert not window.code_apply_btn.isVisible()

    window.analysis_tabs.setCurrentIndex(window.python_tab_index)
    window.code_editor.insertPlainText("\n# edited")
    qapp.processEvents()
    assert window.code_apply_btn.isVisible()
    window.close()


def test_preflight_cleanup_starts_full_execution(qapp, monkeypatch):
    window = MainWindow()
    window._start_new_task()
    file_meta = FileMeta(
        file_path="C:/ready.xlsx",
        file_name="ready.xlsx",
        file_size_kb=1,
        sheet_count=0,
        sheets=[],
        dataset_id="ds_ready",
    )
    window._pending_files_meta = [file_meta]
    window._pending_query = "Analyze the data"
    window._generated_code = "print('ready')"
    window._analysis_plan = {"requirements": []}
    window._auto_execute_pending = True
    runtime = window._analysis_tasks.activate(
        SimpleNamespace(),
        SimpleNamespace(),
    )
    calls = []
    monkeypatch.setattr(
        window,
        "_start_analysis_worker",
        lambda **kwargs: calls.append(kwargs),
    )

    window._cleanup_worker(runtime.generation)

    assert not window._auto_execute_pending
    assert calls == [
        {
            "mode": "execute",
            "files_meta": [file_meta],
            "user_query": "Analyze the data",
            "code": "print('ready')",
            "analysis_plan": {"requirements": []},
        }
    ]
    window.close()


def test_failed_preparation_never_enables_apply(qapp):
    window = MainWindow()
    window.show()
    window._start_new_task()
    window._pending_files_meta = [
        FileMeta(
            file_path="C:/invalid.xlsx",
            file_name="invalid.xlsx",
            file_size_kb=1,
            sheet_count=0,
            sheets=[],
            dataset_id="ds_invalid",
        )
    ]
    window._pending_query = "Analyze invalid data"
    window._active_worker_mode = "prepare"

    result = SimpleNamespace(
        needs_clarification=False,
        success=False,
        code="import re\nprint('invalid')",
        analysis_plan={"requirements": []},
        execution=None,
        preflight_only=True,
        retries_used=1,
        failure_kind="security",
        error="Security validation failed",
    )
    window._on_worker_finished(result)
    qapp.processEvents()

    assert not window._code_apply_allowed
    assert not window.code_apply_btn.isVisible()
    window.code_editor.insertPlainText("\n# edited")
    qapp.processEvents()
    assert not window.code_apply_btn.isVisible()
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

    window._context_panel_open = True
    window._close_context_panel()
    qapp.processEvents()
    assert not window.overview_popover.isVisible()

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


def test_removing_analysis_source_clears_title_and_import_message(qapp):
    window = MainWindow()
    window.show()
    file_meta = FileMeta(
        file_path="C:/analysis.xlsx",
        file_name="analysis.xlsx",
        file_size_kb=8.0,
        sheet_count=0,
        sheets=[],
        dataset_id="ds_analysis",
    )
    window.loaded_files["analysis.xlsx"] = file_meta
    window._add_dataset_item("analysis.xlsx", selected=True)
    window._start_new_task()
    window._pending_files_meta = [file_meta]
    window._pending_query = "Analyze revenue"
    window._create_history_task("analysis.xlsx", "Analyze revenue")
    window._current_analysis_result = AnalysisResult(summary="Completed")
    window.result_output.set_result(window._current_analysis_result)
    window._refresh_workspace_header()
    assert window.workspace_title_label.text() == "Analyze revenue"

    window._remove_dataset("analysis.xlsx")
    qapp.processEvents()

    assert window.workspace_title_label.text() == ""
    assert not window.workspace_title_label.isVisible()
    result_labels = [
        label.text()
        for label in window.result_output.findChildren(
            type(window.workspace_title_label)
        )
    ]
    assert "Add a dataset to continue." in result_labels
    assert "Please import a dataset first." not in result_labels
    window.close()


def test_main_window_opens_centered_after_hidden_first_frame(qapp):
    window = MainWindow()
    assert window.windowOpacity() == 0.0
    window.show()
    QTest.qWait(240)
    qapp.processEvents()

    available = window.screen().availableGeometry()
    delta = window.frameGeometry().center() - available.center()
    assert abs(delta.x()) <= 1
    assert abs(delta.y()) <= 1
    assert window.windowOpacity() == 1.0
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
            answers=[
                AnswerResult(
                    "A",
                    "Calculate revenue by product",
                    "Product A leads with 80 CNY.",
                    supporting_metrics=["Total revenue"],
                    supporting_tables=["Revenue by product"],
                    supporting_insights=["Leading product"],
                ),
                AnswerResult(
                    "B",
                    "Highlight the leading product",
                    "Product A contributes the largest share.",
                    supporting_insights=["Leading product"],
                ),
            ],
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
    assert window.result_output.findChild(QWidget, "answerSwitcher")
    switch_buttons = window.result_output.findChildren(
        type(window.header_export_btn),
        "answerSwitchButton",
    )
    assert [button.text() for button in switch_buttons[:3]] == ["All", "1", "2"]

    switch_buttons[1].click()
    qapp.processEvents()
    answer_questions = [
        label.text()
        for label in window.result_output.findChildren(
            type(window.analysis_plan_label),
            "answerQuestion",
        )
    ]
    assert answer_questions == ["Calculate revenue by product"]

    window.close()


def test_analysis_result_enables_basic_excel_export(qapp, monkeypatch, tmp_path):
    window = MainWindow()
    window.show()
    window._start_new_task()
    window._current_analysis_result = AnalysisResult(summary="Ready to export")
    window._refresh_result_export_state()
    destination = tmp_path / "result"
    started = []
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(destination), "Excel Workbook (*.xlsx)"),
    )
    monkeypatch.setattr(
        window,
        "_start_result_export",
        lambda output_path, **kwargs: started.append((output_path, kwargs)),
    )

    window._on_export_result_clicked()
    qapp.processEvents()

    assert window.header_export_btn.isVisible()
    assert window.export_result_action.isEnabled()
    assert started[0][0] == str(destination) + ".xlsx"
    assert started[0][1]["export_scope"] == "All results"
    window.close()


def test_analysis_result_export_can_select_one_answer(qapp, monkeypatch, tmp_path):
    window = MainWindow()
    window.show()
    window._start_new_task()
    window._current_analysis_result = AnalysisResult(
        summary="All done.",
        answers=[
            AnswerResult("R1", "Question one", "Answer one"),
            AnswerResult("R2", "Question two", "Answer two"),
        ],
    )
    window.result_output.set_result(window._current_analysis_result)
    window._refresh_result_export_state()
    destination = tmp_path / "selected-result.xlsx"
    started = []

    monkeypatch.setattr(
        QInputDialog,
        "getItem",
        lambda *args, **kwargs: ("Result 2: Question two", True),
    )
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(destination), "Excel Workbook (*.xlsx)"),
    )
    monkeypatch.setattr(
        window,
        "_start_result_export",
        lambda output_path, **kwargs: started.append((output_path, kwargs)),
    )

    window._on_export_result_clicked()

    assert started[0][0] == str(destination)
    assert started[0][1]["export_scope"] == "Result 2"
    selected = started[0][1]["export_result"]
    assert selected.answers[0].answer_id == "R2"
    assert selected.answers[0].answer == "Answer two"
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


def test_analysis_selection_is_limited_to_three_datasets(qapp):
    window = MainWindow()
    window._start_new_task()
    for index in range(4):
        name = f"dataset-{index}.xlsx"
        window.loaded_files[name] = FileMeta(
            file_path=f"C:/{name}",
            file_name=name,
            file_size_kb=1.0,
            sheet_count=0,
            sheets=[],
        )
        window._add_dataset_item(name, selected=index < 3)

    fourth = window._dataset_row_widgets["dataset-3.xlsx"]
    assert len(window._selected_datasets) == 3
    assert not fourth.selection_box.isEnabled()

    window._on_dataset_analysis_selection_changed("dataset-0.xlsx", False)
    window._on_dataset_analysis_selection_changed("dataset-3.xlsx", True)

    assert len(window._selected_datasets) == 3
    assert "dataset-3.xlsx" in window._selected_datasets
    assert "dataset-0.xlsx" not in window._selected_datasets
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
    window._code_apply_allowed = True
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
    QTest.qWait(220)
    qapp.processEvents()

    assert window.left_shell.isVisible()
    assert window.left_shell.width() == 342

    window._close_context_panel()
    window._collapse_composer("done")
    QTest.qWait(260)
    qapp.processEvents()

    assert not window.left_shell.isVisible()
    assert window.left_shell.width() == 342
    assert not window.command_bar.isVisible()
    assert window.composer_status_btn.isVisible()

    window.composer_status_btn.click()
    QTest.qWait(260)
    qapp.processEvents()

    assert window.command_bar.isVisible()
    assert not window.composer_status_btn.isVisible()

    window.composer_close_btn.click()
    QTest.qWait(260)
    qapp.processEvents()
    assert not window.command_bar.isVisible()
    assert window.composer_status_btn.isVisible()
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
    QTest.qWait(220)
    qapp.processEvents()

    assert not hasattr(window, "nav_data_btn")
    assert not hasattr(window, "nav_history_btn")
    assert window.history_btn.parent() is window.title_bar
    assert window.settings_btn.parent() is window.title_bar
    assert window.history_btn.text() == "History"
    assert window.settings_btn.text() == "Config"
    assert window.title_bar.actions_layout.count() == 2
    assert window.dataset_library_btn.text().startswith("Datasets")

    window.dataset_library_btn.click()
    QTest.qWait(280)
    qapp.processEvents()
    assert window.left_shell.isVisible()

    window.dataset_library_btn.click()
    QTest.qWait(280)
    qapp.processEvents()
    assert not window.left_shell.isVisible()

    window._expand_composer(pin=True)
    window._position_floating_composer()
    qapp.processEvents()

    expected_x = (window.workspace.width() - window.command_bar.width()) // 2
    assert abs(window.command_bar.x() - expected_x) <= 1
    window.close()


def test_dataset_library_closes_when_clicking_outside(qapp):
    window = MainWindow()
    window.show()
    window._start_new_task()
    window.loaded_files["ready.xlsx"] = FileMeta(
        file_path="C:/ready.xlsx",
        file_name="ready.xlsx",
        file_size_kb=1,
        sheet_count=1,
        sheets=[],
    )
    window._add_dataset_item("ready.xlsx")
    window.dataset_list.setCurrentRow(0)
    window._dataset_overviews["ready.xlsx"] = {
        "state": "ready",
        "data": {
            "dataset_kind": "Workbook",
            "topic": "Ready dataset",
            "summary": "A ready workbook.",
            "rows": 1,
            "columns": 1,
            "sheet_count": 1,
            "suggestions": [],
        },
    }
    window._close_context_panel()
    QTest.qWait(280)
    qapp.processEvents()

    window.dataset_library_btn.click()
    QTest.qWait(280)
    qapp.processEvents()
    assert window.left_shell.isVisible()
    assert window._context_click_guard_active

    QTest.mouseClick(window.dataset_selection_label, Qt.LeftButton)
    qapp.processEvents()
    assert window.left_shell.isVisible()
    assert window._context_click_guard_active

    window._show_overview_for_dataset("ready.xlsx")
    qapp.processEvents()
    assert window.overview_popover.isVisible()

    QTest.mouseClick(window.workspace, Qt.LeftButton, pos=QPoint(24, 24))
    QTest.qWait(280)
    qapp.processEvents()

    assert not window.left_shell.isVisible()
    assert not window._context_click_guard_active
    assert not window.overview_popover.isVisible()
    window.close()


def test_mode_dropdown_switches_between_analysis_and_cleaning(qapp):
    window = MainWindow()
    window.show()
    window.loaded_files["ready.xlsx"] = FileMeta(
        file_path="C:/ready.xlsx",
        file_name="ready.xlsx",
        file_size_kb=1,
        sheet_count=0,
        sheets=[],
        dataset_id="ds_ready",
    )
    window._start_new_task()
    qapp.processEvents()

    assert window.mode_button.isVisible()
    assert window.mode_button.text() == "Mode: Data Analysis"
    assert not window.dataset_library_btn.isHidden()

    window.mode_cleaning_action.trigger()
    QTest.qWait(220)
    qapp.processEvents()
    assert window.page_container.currentWidget() is window.cleaning_page
    assert window.mode_button.text() == "Mode: Data Cleaning"
    assert len(window._selected_datasets) == 1
    assert window.cleaning_page.target_label.text() == "ready.xlsx"

    window.mode_analysis_action.trigger()
    QTest.qWait(220)
    qapp.processEvents()
    assert window.page_container.currentWidget() is window.workspace
    assert window.mode_button.text() == "Mode: Data Analysis"
    window.close()


def test_dataset_rows_use_highlight_selection_and_cleaning_allows_one(qapp):
    window = MainWindow()
    for index in range(3):
        name = f"dataset-{index}.xlsx"
        window.loaded_files[name] = FileMeta(
            file_path=f"C:/{name}",
            file_name=name,
            file_size_kb=1,
            sheet_count=0,
            sheets=[],
            dataset_id=f"ds_{index}",
        )
        window._add_dataset_item(name, selected=index < 2)

    assert all(
        not widget.selection_box.isVisible()
        for widget in window._dataset_row_widgets.values()
    )

    window._show_cleaning_page()
    window._on_dataset_row_activated("dataset-2.xlsx")

    assert window._selected_datasets == {"dataset-2.xlsx"}
    assert window.cleaning_page.target_label.text() == "dataset-2.xlsx"
    assert window._dataset_row_widgets["dataset-2.xlsx"]._scope_selected
    assert not window._dataset_row_widgets["dataset-0.xlsx"]._scope_selected
    window.close()


def test_minimal_desktop_menus_expose_only_global_commands(qapp):
    window = MainWindow()
    window.show()

    assert window.file_menu_btn.text() == "File"
    assert window.view_menu_btn.text() == "View"
    assert window.help_menu_btn.text() == "Help"
    assert [action.text() for action in window.file_menu_btn.menu().actions()] == [
        "New Analysis",
        "Add Dataset...",
        "Export Result...",
        "",
        "Exit",
    ]
    assert [action.text() for action in window.view_menu_btn.menu().actions()] == [
        "Dataset Library",
        "Activity",
    ]

    window._generated_code = "print('ok')"
    window._set_python_tab_visible(True)

    assert window.analysis_tabs.tabBar().isTabVisible(window.python_tab_index)
    assert not hasattr(window, "view_code_action")
    assert not hasattr(window, "header_code_btn")
    window.close()
