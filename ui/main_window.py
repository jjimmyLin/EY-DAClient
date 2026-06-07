import sys
from datetime import datetime
from PySide6.QtCore import Qt, QPoint, QThread
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
    QListWidget,
    QFrame,
    QSplitter,
    QStackedWidget,
    QFileDialog
)
from ui.history_page import HistoryPage
from ui.decision_panel import DecisionPanel, OptionItem, DECISION_PANEL_STYLE
from ui.api_settings_dialog import ApiSettingsDialog
from config.settings import settings
from workers.analysis_worker import AnalysisWorker


class TitleBar(QWidget):
    """
    Modern custom title bar.
    Supports:
    - Dragging
    - Minimize
    - Maximize / Restore
    - Close
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("titleBar")
        self.setFixedHeight(44)

        self._drag_pos = QPoint()
        self._is_dragging = False

        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(12)

        # Logo
        self.logo_label = QLabel("✦")
        self.logo_label.setObjectName("titleBarLogo")

        # Title
        self.title_label = QLabel(self.window().windowTitle())
        self.title_label.setObjectName("titleBarText")

        layout.addWidget(self.logo_label)
        layout.addWidget(self.title_label)
        layout.addStretch()

        # Minimize
        self.btn_minimize = QPushButton("—")
        self.btn_minimize.setObjectName("btnMinimize")
        self.btn_minimize.setFixedSize(28, 28)
        self.btn_minimize.setCursor(Qt.PointingHandCursor)
        self.btn_minimize.clicked.connect(self.window().showMinimized)

        # Maximize
        self.btn_maximize = QPushButton("🗖")
        self.btn_maximize.setObjectName("btnMaximize")
        self.btn_maximize.setFixedSize(28, 28)
        self.btn_maximize.setCursor(Qt.PointingHandCursor)
        self.btn_maximize.clicked.connect(self._toggle_maximize)

        # Close
        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("btnClose")
        self.btn_close.setFixedSize(28, 28)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.window().close)

        layout.addWidget(self.btn_minimize)
        layout.addWidget(self.btn_maximize)
        layout.addWidget(self.btn_close)

    def _toggle_maximize(self):
        if self.window().isMaximized():
            self.window().showNormal()
            self.window().setFixedSize(1000, 600)
            self.btn_maximize.setText("🗖")
        else:
            self.window().setMinimumSize(800, 600)
            self.window().setMaximumSize(16777215, 16777215)
            self.window().showMaximized()
            self.btn_maximize.setText("⧉")

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._is_dragging = True
            self._drag_pos = (
                event.globalPosition().toPoint()
                - self.window().frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_dragging and event.buttons() == Qt.LeftButton:
            if self.window().isMaximized():
                ratio = event.position().x() / self.width()
                self.window().showNormal()
                self.window().setFixedSize(1000, 600)
                new_x = int(self.window().width() * ratio)
                self._drag_pos = QPoint(
                    new_x,
                    int(event.position().y())
                )
                self.btn_maximize.setText("▢")

            self.window().move(
                event.globalPosition().toPoint() - self._drag_pos
            )
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._is_dragging = False
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._toggle_maximize()
            event.accept()


class MainWindow(QMainWindow):
    """
    Main application window.
    Frameless modern AI workspace UI.
    """

    def __init__(self):
        super().__init__()

        self.setWindowTitle("AI Data Analysis Assistant")
        self.resize(1000, 600)
        self.setFixedSize(1000, 600)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        
        self.loaded_files = {}  # Store file_path -> FileMeta mapping
        self._pending_code = None
        self._pending_files_meta = None
        self._pending_query = None
        self._base_query = None
        self._decision_context = ""
        self._selected_model = None
        self._analysis_thread = None
        self._analysis_worker = None
        self._active_worker_mode = ""
        self._transcript = {}
        self._task_history = []
        self._active_task_id = None

        self._init_ui()

    def _init_ui(self):

        root_widget = QWidget()
        root_widget.setObjectName("rootWidget")

        self.setCentralWidget(root_widget)

        root_layout = QVBoxLayout(root_widget)

        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.title_bar = TitleBar(self)
        root_layout.addWidget(self.title_bar)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setHandleWidth(1)
        root_layout.addWidget(self.main_splitter)

        # =========================================================================
        # Sidebar
        # =========================================================================

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(200)
        sidebar.setMaximumWidth(360)

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(20, 24, 20, 24)
        sidebar_layout.setSpacing(16)

        self.upload_btn = QPushButton("+ Add Dataset")
        self.upload_btn.setObjectName("uploadBtn")
        self.upload_btn.setCursor(Qt.PointingHandCursor)
        self.upload_btn.clicked.connect(self._on_upload_clicked)

        self.dataset_list = QListWidget()
        self.dataset_list.setObjectName("datasetList")

        self.history_btn = QPushButton("View History")
        self.history_btn.setObjectName("historyBtn")
        self.history_btn.setCursor(Qt.PointingHandCursor)

        self.settings_btn = QPushButton("API Settings")
        self.settings_btn.setObjectName("settingsBtn")
        self.settings_btn.setCursor(Qt.PointingHandCursor)

        self.api_status_label = QLabel()
        self.api_status_label.setObjectName("apiStatusLabel")
        self.api_status_label.setWordWrap(True)

        sidebar_layout.addWidget(QLabel("CONTEXT DATA"))
        sidebar_layout.addWidget(self.upload_btn)
        sidebar_layout.addWidget(self.dataset_list, stretch=3)
        sidebar_layout.addWidget(self.history_btn)
        sidebar_layout.addWidget(self.settings_btn)
        sidebar_layout.addWidget(self.api_status_label)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("separator")
        sidebar_layout.addWidget(sep)

        self.log_output = QTextEdit()
        self.log_output.setObjectName("logOutput")
        self.log_output.setReadOnly(True)

        sidebar_layout.addWidget(QLabel("SYSTEM LOGS"))
        sidebar_layout.addWidget(self.log_output, stretch=2)

        # =========================================================================
        # Workspace (Page 1)
        # =========================================================================

        workspace = QWidget()
        workspace.setObjectName("workspace")

        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)

        canvas_container = QWidget()
        canvas_layout = QVBoxLayout(canvas_container)
        canvas_layout.setContentsMargins(40, 40, 40, 20)

        self.canvas_stack = QStackedWidget()

        self.result_output = QTextEdit()
        self.result_output.setObjectName("resultOutput")
        self.result_output.setReadOnly(True)
        self.result_output.setPlaceholderText(
            "Analysis results will appear here..."
        )

        self.decision_panel = DecisionPanel()
        self.decision_panel.decision_made.connect(self._on_decision_made)
        self.decision_panel.decision_skipped.connect(self._on_decision_skipped)

        self.canvas_stack.addWidget(self.result_output)    # index 0
        self.canvas_stack.addWidget(self.decision_panel)   # index 1

        canvas_layout.addWidget(self.canvas_stack)

        # =========================================================================
        # Command Bar
        # =========================================================================

        command_bar = QFrame()
        command_bar.setObjectName("commandBar")

        command_layout = QHBoxLayout(command_bar)
        command_layout.setContentsMargins(16, 12, 16, 12)
        command_layout.setSpacing(12)

        self.prompt_input = QTextEdit()
        self.prompt_input.setObjectName("promptInput")
        self.prompt_input.setPlaceholderText(
            "Ask a question about your data or request an analysis..."
        )
        self.prompt_input.setMaximumHeight(80)

        self.run_btn = QPushButton("Analyze")
        self.run_btn.setObjectName("runBtn")
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.setFixedSize(100, 48)
        self.run_btn.clicked.connect(self._on_analyze_clicked)

        self.apply_btn = QPushButton("▶ Apply")
        self.apply_btn.setObjectName("applyBtn")
        self.apply_btn.setCursor(Qt.PointingHandCursor)
        self.apply_btn.setFixedSize(100, 48)
        self.apply_btn.clicked.connect(self._on_apply_clicked)
        self.apply_btn.setVisible(False)

        command_layout.addWidget(self.prompt_input)
        command_layout.addWidget(self.run_btn)
        command_layout.addWidget(self.apply_btn)

        workspace_layout.addWidget(canvas_container, stretch=1)

        command_wrapper = QWidget()
        wrapper_layout = QVBoxLayout(command_wrapper)
        wrapper_layout.setContentsMargins(40, 0, 40, 40)
        wrapper_layout.addWidget(command_bar)

        workspace_layout.addWidget(command_wrapper)

        # =========================================================================
        # Page Stack & Splitter Assembly
        # =========================================================================

        self.page_container = QStackedWidget()
        self.history_page = HistoryPage()

        self.page_container.addWidget(workspace)
        self.page_container.addWidget(self.history_page)

        self.main_splitter.addWidget(sidebar)
        self.main_splitter.addWidget(self.page_container)
        self.main_splitter.setCollapsible(0, False)
        self.main_splitter.setSizes([260, 740])

        self.history_btn.clicked.connect(self._show_history_page)
        self.history_page.btn_back.clicked.connect(lambda: self.page_container.setCurrentIndex(0))
        self.settings_btn.clicked.connect(self._on_settings_clicked)

        self._apply_style()
        self._refresh_api_status()

    def _on_upload_clicked(self):
        """Handle file upload and display in sidebar"""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Excel Files",
            "",
            "Excel Files (*.xlsx *.xls);;All Files (*)"
        )
        
        if not files:
            return
        
        from core.preprocessor import Preprocessor
        preprocessor = Preprocessor()
        last_loaded_row = None
        
        for file_path in files:
            try:
                file_meta = preprocessor.process(file_path)
                file_name = file_path.split('/')[-1]
                
                self.loaded_files[file_name] = file_meta
                self.dataset_list.addItem(file_name)
                last_loaded_row = self.dataset_list.count() - 1
                self.log_output.append(f"✓ Loaded: {file_name}")
            except Exception as e:
                self.log_output.append(f"✗ Error loading {file_path}: {str(e)}")

        if last_loaded_row is not None:
            self.dataset_list.setCurrentRow(last_loaded_row)
            selected_name = self.dataset_list.item(last_loaded_row).text()
            self.log_output.append(f"Selected dataset: {selected_name}")

    def _on_analyze_clicked(self):
        """Generate analysis code using the globally configured API provider."""
        selected_item = self.dataset_list.currentItem()
        query = self.prompt_input.toPlainText().strip()

        if not selected_item:
            self.result_output.setText("Please select a dataset first")
            return

        if not query:
            self.result_output.setText("Please enter an analysis question")
            return

        file_name = selected_item.text()
        file_meta = self.loaded_files.get(file_name)

        if not file_meta:
            self.result_output.setText("File metadata not found")
            return

        try:
            settings.reload()
            settings.validate_selected_provider()
        except EnvironmentError as e:
            self.result_output.setText(
                f"API configuration error:\n{e}\n\nOpen API Settings and add the missing value to .env."
            )
            self.log_output.append(f"✗ API configuration error: {e}")
            self._refresh_api_status()
            return

        self.apply_btn.setVisible(False)
        self._pending_query = query
        self._base_query = query
        self._pending_files_meta = [file_meta]
        self._decision_context = ""
        self._selected_model = None
        self._create_history_task(file_name, query)
        self.log_output.append(
            f"Using provider: {settings.LLM_PROVIDER} ({self._current_model_label()})"
        )
        self._run_generate()

    def _on_decision_made(self, option: OptionItem) -> None:
        """用户在决策面板中选了一个选项。"""
        self.canvas_stack.setCurrentIndex(0)
        if self._decision_context == "clarification":
            chosen = option.data if isinstance(option.data, dict) else {}
            label = chosen.get("label") or option.label
            description = chosen.get("description") or option.description
            base_query = self._base_query or self._pending_query or ""
            self._pending_query = (
                f"{base_query}\n\n"
                f"用户已选择澄清选项：{label}\n"
                f"选项说明：{description}"
            )
            self._decision_context = ""
            self.log_output.append(f"Clarification selected: {label}")
            self._run_generate()
            return

        self._selected_model = option.data
        self.log_output.append(f"User selected model: {option.label}")
        self._run_generate()

    def _on_decision_skipped(self) -> None:
        """用户跳过了决策面板（自动选择）。"""
        self.canvas_stack.setCurrentIndex(0)
        if self._decision_context == "clarification":
            self._decision_context = ""
            self.log_output.append("Clarification skipped")
            return

        self._selected_model = None
        self.log_output.append("Auto-selecting model")
        self._run_generate()

    def _on_settings_clicked(self) -> None:
        dialog = ApiSettingsDialog(self)
        dialog.settings_saved.connect(self._refresh_api_status)
        if dialog.exec():
            self.log_output.append(
                f"API settings saved: {settings.LLM_PROVIDER} ({self._current_model_label()})"
            )
            self._refresh_api_status()

    def _show_history_page(self) -> None:
        self._refresh_history_page()
        self.page_container.setCurrentIndex(1)

    def _create_history_task(self, dataset: str, query: str) -> None:
        if self._active_task_id is not None:
            self._update_history_task(
                "Finished",
                "Replaced before execution",
                finished=True,
            )

        task_id = len(self._task_history) + 1
        now = self._history_timestamp()
        self._task_history.append({
            "id": task_id,
            "dataset": dataset,
            "query": query,
            "status": "Generating code",
            "created_at": now,
            "updated_at": now,
            "finished": False,
        })
        self._active_task_id = task_id
        self._refresh_history_page()

    def _update_history_task(
        self,
        status: str,
        detail: str = "",
        finished: bool = False,
    ) -> None:
        if self._active_task_id is None:
            return

        for task in self._task_history:
            if task["id"] != self._active_task_id:
                continue
            task["status"] = f"{status}: {detail}" if detail else status
            task["updated_at"] = self._history_timestamp()
            task["finished"] = finished
            break

        if finished:
            self._active_task_id = None
        self._refresh_history_page()

    def _refresh_history_page(self) -> None:
        unfinished = [
            task for task in reversed(self._task_history)
            if not task.get("finished")
        ]
        finished = [
            task for task in reversed(self._task_history)
            if task.get("finished")
        ]
        self.history_page.set_tasks(unfinished, finished)

    def _history_timestamp(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M")

    def _refresh_api_status(self) -> None:
        settings.reload()
        status = settings.provider_status().get(settings.LLM_PROVIDER, {})
        missing = [key for key, present in status.items() if not present]
        if missing:
            self.api_status_label.setText(
                f"API: {settings.LLM_PROVIDER} · missing {', '.join(missing)}"
            )
        else:
            self.api_status_label.setText(
                f"API: {settings.LLM_PROVIDER} · {self._current_model_label()}"
            )

    def _current_model_label(self) -> str:
        if settings.LLM_PROVIDER == "gemini":
            return settings.GEMINI_MODEL
        if settings.LLM_PROVIDER == "deepseek":
            return settings.DEEPSEEK_MODEL
        return "workflow"

    def _run_generate(self):
        """生成代码并展示，等待用户点击 Apply 后再执行。"""
        if not self._pending_query or not self._pending_files_meta:
            return

        self._reset_transcript()
        self._append_system_event("Generating code...")
        self._start_analysis_worker(
            mode="generate",
            files_meta=self._pending_files_meta,
            user_query=self._pending_query,
        )

    def _on_apply_clicked(self):
        """执行用户已审核的代码。"""
        if not self._pending_code or not self._pending_files_meta:
            return

        self._append_system_event("Executing approved code...")
        self.apply_btn.setVisible(False)
        self._update_history_task("Executing")
        self._start_analysis_worker(
            mode="execute",
            files_meta=self._pending_files_meta,
            code=self._pending_code,
        )

    def _start_analysis_worker(
        self,
        mode: str,
        files_meta: list,
        user_query: str = "",
        code: str = "",
    ) -> None:
        if self._analysis_thread is not None:
            return

        self._active_worker_mode = mode
        self._set_busy(True)

        thread = QThread(self)
        worker = AnalysisWorker(
            mode=mode,
            files_meta=files_meta,
            user_query=user_query,
            code=code,
        )
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.event.connect(self._on_worker_event)
        worker.finished.connect(self._on_worker_finished)
        worker.error.connect(self._on_worker_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_worker)

        self._analysis_thread = thread
        self._analysis_worker = worker
        thread.start()

    def _on_worker_event(self, event: dict) -> None:
        event_type = event.get("type", "status")
        message = str(event.get("message", ""))
        delta = str(event.get("delta", ""))

        if message and event_type == "status":
            self._append_system_event(message)
            self.log_output.append(message)
        elif event_type == "thinking_delta":
            self._transcript["thinking"] += delta
        elif event_type == "content_delta":
            self._transcript["code"] += delta
        elif event_type == "tool_delta":
            self._transcript["tools"] += delta
        elif event_type == "intent_result":
            self._transcript["intent"] = delta
            if message:
                self._append_system_event(message)
        elif event_type == "validation_result":
            self._transcript["validation"] = delta
            if message:
                self._append_system_event(message)
        elif event_type == "code_verification":
            self._transcript["code_verification"] = delta
            if message:
                self._append_system_event(message)
        elif event_type in ("execution_output", "execution_error"):
            self._transcript["execution"] += delta
            if message:
                self._append_system_event(message)
        else:
            if message:
                self._append_system_event(message)

        self._render_transcript()

    def _on_worker_finished(self, result) -> None:
        if self._active_worker_mode == "generate":
            self._transcript["intent"] = self._format_json(result.intent_result)
            self._transcript["validation"] = self._format_json(
                result.validation_result
            )
            self._transcript["code_verification"] = self._format_json(
                result.code_verification
            )

            if result.needs_clarification:
                self._pending_code = None
                self.apply_btn.setVisible(False)
                self._append_system_event("Intent needs clarification before code generation.")
                self.log_output.append("⚠ Intent needs clarification")
                self._update_history_task("Needs clarification")
                self._show_clarification(result)

            elif result.success:
                self._pending_code = result.code
                self._transcript["code"] = result.code
                self._append_system_event("Code generated and verified. Review and click Apply.")
                self.log_output.append("✓ Code generated and verified — review and click Apply")
                self.apply_btn.setVisible(True)
                self._update_history_task("Awaiting Apply")
            else:
                self._append_system_event(f"Generation failed: {result.error}")
                self.log_output.append(f"✗ Generation failed: {result.error}")
                self._pending_query = None
                self._pending_files_meta = None
                self._transcript["execution"] = result.error
                self._update_history_task("Failed", result.error, finished=True)

        elif self._active_worker_mode == "execute":
            if result.success:
                output_text = result.execution.stdout if result.execution else ""
                self._transcript["execution"] = output_text
                self._append_system_event("Execution completed")
                self.log_output.append("✓ Execution completed")
                self._update_history_task("Completed", finished=True)
            else:
                error_text = (
                    result.execution.stderr if result.execution else result.error
                )
                self._transcript["execution"] = error_text
                self._append_system_event("Execution failed")
                self.log_output.append(f"✗ Execution failed: {result.error}")
                self._update_history_task("Failed", result.error, finished=True)
            self._pending_code = None
            self._pending_files_meta = None

        self._render_transcript()
        self._set_busy(False)

    def _on_worker_error(self, error: str) -> None:
        self._append_system_event(f"Worker error: {error}")
        self._transcript["execution"] = error
        self.log_output.append(f"✗ Worker error: {error}")
        self._render_transcript()
        self._pending_query = None
        self._pending_files_meta = None
        self._update_history_task("Failed", error, finished=True)
        self._set_busy(False)

    def _cleanup_worker(self) -> None:
        self._analysis_thread = None
        self._analysis_worker = None
        self._active_worker_mode = ""

    def _set_busy(self, busy: bool) -> None:
        self.run_btn.setEnabled(not busy)
        self.upload_btn.setEnabled(not busy)
        self.settings_btn.setEnabled(not busy)
        if busy:
            self.run_btn.setText("Working")
            self.apply_btn.setEnabled(False)
        else:
            self.run_btn.setText("Analyze")
            self.apply_btn.setEnabled(True)

    def _reset_transcript(self) -> None:
        self._transcript = {
            "system": [],
            "intent": "",
            "validation": "",
            "code_verification": "",
            "thinking": "",
            "tools": "",
            "code": "",
            "execution": "",
        }
        self._render_transcript()

    def _append_system_event(self, message: str) -> None:
        if not self._transcript:
            self._reset_transcript()
        self._transcript["system"].append(message)

    def _render_transcript(self) -> None:
        if not self._transcript:
            return
        sections = []
        system_text = "\n".join(f"- {item}" for item in self._transcript["system"])
        sections.append("## System Status\n" + (system_text or "- Idle"))
        if self._transcript["intent"]:
            sections.append("## 意图理解\n" + self._transcript["intent"].strip())
        if self._transcript["validation"]:
            sections.append("## 验证结果\n" + self._transcript["validation"].strip())
        if self._transcript["code"]:
            sections.append("## Generated Code\n" + self._transcript["code"].strip())
        if self._transcript["code_verification"]:
            sections.append(
                "## 代码验证\n" + self._transcript["code_verification"].strip()
            )
        if self._transcript["execution"]:
            sections.append("## Execution\n" + self._transcript["execution"].strip())
        self.result_output.setPlainText("\n\n".join(sections))

    def _show_clarification(self, result) -> None:
        options = []
        for option in result.clarification_options:
            label = str(option.get("label") or option.get("id") or "Option")
            description = str(option.get("description") or "")
            tag = "recommended" if option.get("recommended") else ""
            options.append(
                OptionItem(
                    label=label,
                    description=description,
                    tag=tag,
                    data=option,
                )
            )

        if not options:
            options.append(
                OptionItem(
                    label="补充说明",
                    description=result.clarification_question,
                    tag="recommended",
                    data={
                        "label": "补充说明",
                        "description": result.clarification_question,
                    },
                )
            )

        self._decision_context = "clarification"
        self.canvas_stack.setCurrentIndex(1)
        self.decision_panel.show_decision(
            title="Clarify Analysis",
            description=result.clarification_question,
            options=options,
            allow_skip=False,
        )

    @staticmethod
    def _format_json(value) -> str:
        if not value:
            return ""
        import json

        return json.dumps(value, ensure_ascii=False, indent=2)


    def _apply_style(self):

        self.setStyleSheet("""
            QWidget#rootWidget {
                background-color: #F9FAFB;
                border: 1px solid #E5E7EB;
                border-radius: 4px;
            }

            QMainWindow {
                background-color: #F9FAFB;
            }

            /* ========================================================================= */
            /* Title Bar 按钮完美对齐修复版 */
            /* ========================================================================= */

            QPushButton#btnMinimize,
            QPushButton#btnMaximize,
            QPushButton#btnClose {
                background-color: transparent;
                border: none;
                border-radius: 6px;
                color: #6B7280;
                font-family: "Arial";
                font-size: 11px;
                font-weight: normal;
                
                padding: 0px;
                margin: 0px;
                text-align: center;
            }

            QPushButton#btnMinimize:hover,
            QPushButton#btnMaximize:hover {
                background-color: #E5E7EB;
                color: #111827;
            }

            QPushButton#btnClose:hover {
                background-color: #FEE2E2;
                color: #DC2626;
            }

            /* ========================================================================= */
            /* Sidebar */
            /* ========================================================================= */

            QWidget#sidebar {
                background-color: #F9FAFB;
                border-right: 1px solid #E5E7EB;
            }

            QWidget#workspace {
                background-color: #FFFFFF;
                border-left: 1px solid #E5E7EB;
            }

            QLabel {
                font-family: "Arial";
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1px;
                color: #6B7280;
            }

            QSplitter::handle {
                background-color: #E5E7EB;
            }

            /* Buttons */
            QPushButton#uploadBtn,
            QPushButton#historyBtn,
            QPushButton#settingsBtn {
                background-color: #FFFFFF;
                color: #111827;
                font-size: 13px;
                font-weight: 600;
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                padding: 8px;
                height: 32px;
            }

            QPushButton#uploadBtn:hover,
            QPushButton#historyBtn:hover,
            QPushButton#settingsBtn:hover {
                background-color: #F3F4F6;
            }

            QLabel#apiStatusLabel {
                color: #6B7280;
                font-size: 12px;
                line-height: 1.4;
            }

            /* Dataset List */

            QListWidget#datasetList {
                background-color: transparent;
                border: none;
                font-size: 13px;
                color: #374151;
            }

            QListWidget#datasetList::item {
                padding: 8px;
                border-radius: 6px;
                margin-bottom: 2px;
            }

            QListWidget#datasetList::item:hover {
                background-color: #E5E7EB;
            }

            QListWidget#datasetList::item:selected {
                background-color: #DBEAFE;
                color: #1D4ED8;
                font-weight: 600;
            }

            /* Logs */

            QTextEdit#logOutput {
                background-color: transparent;
                border: none;
                font-family: "Courier New";
                font-size: 11px;
                color: #9CA3AF;
            }

            QFrame#separator {
                color: #E5E7EB;
            }

            /* Result Output */

            QTextEdit#resultOutput {
                border: none;
                background-color: transparent;
                font-size: 15px;
                line-height: 1.6;
                color: #111827;
            }

            /* ========================================================================= */
            /* Command Bar */
            /* ========================================================================= */

            QFrame#commandBar {
                background-color: #F9FAFB;
                border: 1px solid #E5E7EB;
                border-radius: 16px;
            }

            QTextEdit#promptInput {
                background-color: transparent;
                border: none;
                font-size: 14px;
                color: #111827;
                padding: 4px;
            }

            QPushButton#runBtn {
                background-color: #111827;
                color: #FFFFFF;
                font-size: 14px;
                font-weight: 600;
                border-radius: 8px;
                border: none;
            }

            QPushButton#runBtn:hover {
                background-color: #374151;
            }

            QPushButton#runBtn:pressed {
                background-color: #000000;
            }

            QPushButton#applyBtn {
                background-color: #059669;
                color: #FFFFFF;
                font-size: 14px;
                font-weight: 600;
                border-radius: 8px;
                border: none;
            }

            QPushButton#applyBtn:hover {
                background-color: #047857;
            }

            QPushButton#applyBtn:pressed {
                background-color: #065F46;
            }
        """ + DECISION_PANEL_STYLE)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
