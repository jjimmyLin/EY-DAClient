from __future__ import annotations

from core.preprocessor import FileMeta, SheetMeta
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
