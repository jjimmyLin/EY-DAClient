# controllers/workflow_controller.py

from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QFileDialog

from services.profiling_service import ProfilingService
from workers.profiling_worker import ProfilingWorker


class WorkflowController:
    """
    Main workflow controller.
    """

    def __init__(self, main_window):

        self.main_window = main_window

        self.dataset_files = []

        self.profiling_service = ProfilingService()

        self.profiling_thread = None
        self.profiling_worker = None

        self._bind_signals()

    # =========================================================
    # Signal Binding
    # =========================================================

    def _bind_signals(self):

        self.main_window.upload_btn.clicked.connect(
            self.select_files
        )

        self.main_window.run_btn.clicked.connect(
            self.run_analysis
        )

    # =========================================================
    # File Upload
    # =========================================================

    def select_files(self):

        files, _ = QFileDialog.getOpenFileNames(
            self.main_window,
            "Select Excel Files",
            "",
            "Excel Files (*.xlsx *.xls *.csv)"
        )

        if not files:
            return

        self.dataset_files = files

        self.main_window.dataset_list.clear()

        for file_path in files:

            file_name = Path(file_path).name

            self.main_window.dataset_list.addItem(
                file_name
            )

        self.log(
            f"Loaded {len(files)} dataset(s)."
        )

    # =========================================================
    # Analysis Workflow
    # =========================================================

    def run_analysis(self):

        if not self.dataset_files:

            self.log("No dataset selected.")
            return

        user_prompt = (
            self.main_window.prompt_input
            .toPlainText()
            .strip()
        )

        if not user_prompt:

            self.log(
                "Analysis request is empty."
            )

            return

        self.log(
            "Starting dataset profiling..."
        )

        # Disable UI

        self.main_window.run_btn.setEnabled(
            False
        )

        # Create Thread

        self.profiling_thread = QThread()

        self.profiling_worker = ProfilingWorker(
            self.dataset_files
        )

        self.profiling_worker.moveToThread(
            self.profiling_thread
        )

        # Connect Signals

        self.profiling_thread.started.connect(
            self.profiling_worker.run
        )

        self.profiling_worker.finished.connect(
            self._on_profiling_finished
        )

        self.profiling_worker.error.connect(
            self._on_profiling_error
        )

        self.profiling_worker.progress.connect(
            self.log
        )

        # Cleanup

        self.profiling_worker.finished.connect(
            self.profiling_thread.quit
        )

        self.profiling_worker.finished.connect(
            self.profiling_worker.deleteLater
        )

        self.profiling_thread.finished.connect(
            self.profiling_thread.deleteLater
        )

        # Start

        self.profiling_thread.start()

    # =========================================================
    # Worker Callbacks
    # =========================================================

    def _on_profiling_finished(
        self,
        profiles
    ):

        output_lines = []

        output_lines.append(
            "=== DATASET PROFILES ===\n"
        )

        for profile in profiles:

            output_lines.append(
                f"File: {profile['file_name']}"
            )

            output_lines.append(
                f"Rows: {profile['row_count']}"
            )

            output_lines.append(
                f"Columns: "
                f"{profile['column_count']}"
            )

            output_lines.append(
                "Column Names:"
            )

            for column in profile["columns"]:

                output_lines.append(
                    f"  - {column}"
                )

            output_lines.append("")

        self.main_window.result_output.setPlainText(
            "\n".join(output_lines)
        )

        self.main_window.run_btn.setEnabled(
            True
        )

        self.log(
            "Profiling completed."
        )

    def _on_profiling_error(
        self,
        message
    ):

        self.main_window.run_btn.setEnabled(
            True
        )

        self.log(
            f"Profiling failed: {message}"
        )

    # =========================================================
    # Logging
    # =========================================================

    def log(self, message):

        self.main_window.log_output.append(
            f"[Workflow] {message}"
        )