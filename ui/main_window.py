import sys
from datetime import datetime
from PySide6.QtCore import Qt, QPoint, QRect, QSize, QThread, QTimer, QEvent
from PySide6.QtGui import QColor, QCursor, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QPushButton,
    QPlainTextEdit,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
    QListWidget,
    QFrame,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QFileDialog,
    QGraphicsDropShadowEffect,
)
from ui.history_page import HistoryPage
from ui.decision_panel import DecisionPanel, OptionItem, DECISION_PANEL_STYLE
from ui.api_settings_dialog import ApiSettingsDialog
from ui.floating_controls import DatasetRowWidget, SuggestionPopover
from ui.overview_popover import OverviewPopover
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
        self.logo_label = QLabel("EY")
        self.logo_label.setObjectName("titleBarLogo")

        # Title
        self.title_label = QLabel(self.window().windowTitle())
        self.title_label.setObjectName("titleBarText")

        self.session_label = QLabel("")
        self.session_label.setObjectName("titleBarSessionText")

        layout.addWidget(self.logo_label)
        layout.addWidget(self.title_label)
        layout.addWidget(self.session_label)
        layout.addStretch()

        self.actions_layout = QHBoxLayout()
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setSpacing(8)
        layout.addLayout(self.actions_layout)

        # Minimize
        self.btn_minimize = QPushButton("−")
        self.btn_minimize.setObjectName("btnMinimize")
        self.btn_minimize.setFixedSize(28, 28)
        self.btn_minimize.setCursor(Qt.PointingHandCursor)
        self.btn_minimize.clicked.connect(self.window().showMinimized)

        # Maximize
        self.btn_maximize = QPushButton("□")
        self.btn_maximize.setObjectName("btnMaximize")
        self.btn_maximize.setFixedSize(28, 28)
        self.btn_maximize.setCursor(Qt.PointingHandCursor)
        self.btn_maximize.clicked.connect(self._toggle_maximize)

        # Close
        self.btn_close = QPushButton("×")
        self.btn_close.setObjectName("btnClose")
        self.btn_close.setFixedSize(28, 28)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.window().close)

        layout.addWidget(self.btn_minimize)
        layout.addWidget(self.btn_maximize)
        layout.addWidget(self.btn_close)

    def add_action_widget(self, widget: QWidget) -> None:
        self.actions_layout.addWidget(widget)

    def _toggle_maximize(self):
        if self.window().isMaximized():
            self.window().showNormal()
            self.window().setFixedSize(1000, 600)
            self.btn_maximize.setText("□")
        else:
            self.window().setMinimumSize(800, 600)
            self.window().setMaximumSize(16777215, 16777215)
            self.window().showMaximized()
            self.btn_maximize.setText("□")

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
                self.btn_maximize.setText("□")

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
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        
        self.loaded_files = {}  # Store display key -> FileMeta mapping
        self._pending_files_meta = None
        self._pending_query = None
        self._analysis_thread = None
        self._analysis_worker = None
        self._overview_thread = None
        self._overview_worker = None
        self._active_worker_mode = ""
        self._transcript = {}
        self._task_history = []
        self._active_task_id = None
        self._generated_code = ""
        self._task_open = False
        self._dataset_overviews = {}
        self._dataset_row_widgets = {}
        self._overview_loading_dataset = None
        self._suggestion_buttons = []
        self._suggestion_hide_timer = QTimer(self)
        self._suggestion_hide_timer.setSingleShot(True)
        self._suggestion_hide_timer.setInterval(160)
        self._suggestion_hide_timer.timeout.connect(self._maybe_hide_suggestion_popover)

        self._init_ui()

    def _init_ui(self):

        root_widget = QWidget()
        root_widget.setObjectName("rootWidget")

        self.setCentralWidget(root_widget)

        root_layout = QVBoxLayout(root_widget)

        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        app_surface = QFrame()
        app_surface.setObjectName("appSurface")
        surface_layout = QVBoxLayout(app_surface)
        surface_layout.setContentsMargins(1, 1, 1, 1)
        surface_layout.setSpacing(0)
        root_layout.addWidget(app_surface)

        self.title_bar = TitleBar(self)
        surface_layout.addWidget(self.title_bar)

        self.task_title_label = self.title_bar.session_label

        self.start_over_btn = QPushButton("Start Over")
        self.start_over_btn.setObjectName("titleActionBtn")
        self.start_over_btn.setCursor(Qt.PointingHandCursor)
        self.start_over_btn.clicked.connect(self._start_new_task)
        self.title_bar.add_action_widget(self.start_over_btn)

        self.history_btn = QPushButton("History")
        self.history_btn.setObjectName("titleActionBtn")
        self.history_btn.setCursor(Qt.PointingHandCursor)
        self.title_bar.add_action_widget(self.history_btn)

        self.settings_btn = QPushButton("🔧")
        self.settings_btn.setObjectName("titleGearBtn")
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.title_bar.add_action_widget(self.settings_btn)

        self.app_stack = QStackedWidget()
        surface_layout.addWidget(self.app_stack)

        self.start_page = QWidget()
        self.start_page.setObjectName("startPage")
        start_layout = QVBoxLayout(self.start_page)
        start_layout.setContentsMargins(80, 80, 80, 80)
        start_layout.setSpacing(18)
        start_layout.addStretch()

        self.start_task_btn = QPushButton("New Task")
        self.start_task_btn.setObjectName("startTaskBtn")
        self.start_task_btn.setCursor(Qt.PointingHandCursor)
        self.start_task_btn.setFixedSize(140, 40)
        self.start_task_btn.clicked.connect(self._start_new_task)

        start_button_row = QHBoxLayout()
        start_button_row.addStretch()
        start_button_row.addWidget(self.start_task_btn)
        start_button_row.addStretch()

        caution = QLabel("Code runs locally after Apply.")
        caution.setObjectName("startCaution")
        caution.setAlignment(Qt.AlignCenter)

        start_layout.addLayout(start_button_row)
        start_layout.addWidget(caution)
        start_layout.addStretch()

        workspace_root = QWidget()
        workspace_root.setObjectName("workspaceRoot")
        workspace_root_layout = QVBoxLayout(workspace_root)
        workspace_root_layout.setContentsMargins(0, 0, 0, 0)
        workspace_root_layout.setSpacing(0)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setHandleWidth(1)
        workspace_root_layout.addWidget(self.main_splitter)

        self.app_stack.addWidget(self.start_page)
        self.app_stack.addWidget(workspace_root)

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

        self.api_status_label = QLabel()
        self.api_status_label.setObjectName("apiStatusLabel")
        self.api_status_label.setWordWrap(True)

        sidebar_layout.addWidget(QLabel("CONTEXT DATA"))
        sidebar_layout.addWidget(self.upload_btn)
        sidebar_layout.addWidget(self.dataset_list, stretch=3)
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
        canvas_layout.setContentsMargins(40, 28, 40, 20)
        canvas_layout.setSpacing(14)

        self.result_output = QTextEdit()
        self.result_output.setObjectName("resultOutput")
        self.result_output.setReadOnly(True)
        self.result_output.setPlaceholderText(
            "The execution result will appear here first."
        )

        self.code_editor = QPlainTextEdit()
        self.code_editor.setObjectName("codeEditor")
        self.code_editor.setPlaceholderText(
            "Generated Python code appears here and can be edited before Apply."
        )
        self.code_editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.code_editor.setTabStopDistance(
            4 * self.code_editor.fontMetrics().horizontalAdvance(" ")
        )

        code_panel = QWidget()
        code_panel_layout = QVBoxLayout(code_panel)
        code_panel_layout.setContentsMargins(0, 0, 0, 0)
        code_panel_layout.setSpacing(8)

        code_header = QHBoxLayout()
        code_label = QLabel("Editable Python")
        code_label.setObjectName("codePanelLabel")
        self.code_reset_btn = QPushButton("Reset")
        self.code_reset_btn.setObjectName("codeResetBtn")
        self.code_reset_btn.setCursor(Qt.PointingHandCursor)
        self.code_reset_btn.clicked.connect(self._reset_code_to_generated)
        code_header.addWidget(code_label)
        code_header.addStretch()
        code_header.addWidget(self.code_reset_btn)

        code_panel_layout.addLayout(code_header)
        code_panel_layout.addWidget(self.code_editor)

        self.analysis_tabs = QTabWidget()
        self.analysis_tabs.setObjectName("analysisTabs")
        self.analysis_tabs.addTab(self.result_output, "Result")
        self.python_tab_index = self.analysis_tabs.addTab(code_panel, "Python")

        self.decision_panel = DecisionPanel()
        self.decision_panel.decision_made.connect(self._on_decision_made)
        self.decision_panel.decision_skipped.connect(self._on_decision_skipped)

        self.canvas_stack = QStackedWidget()
        self.canvas_stack.addWidget(self.analysis_tabs)       # index 0
        self.canvas_stack.addWidget(self.decision_panel)      # index 1

        canvas_layout.addWidget(self.canvas_stack)

        # =========================================================================
        # Command Bar
        # =========================================================================

        command_bar = QFrame()
        command_bar.setObjectName("commandBar")
        command_shadow = QGraphicsDropShadowEffect(self)
        command_shadow.setBlurRadius(28)
        command_shadow.setOffset(0, 8)
        command_shadow.setColor(QColor(15, 23, 42, 30))
        command_bar.setGraphicsEffect(command_shadow)

        command_layout = QHBoxLayout(command_bar)
        command_layout.setContentsMargins(16, 12, 16, 12)
        command_layout.setSpacing(12)

        command_stack = QVBoxLayout()
        command_stack.setContentsMargins(0, 0, 0, 0)
        command_stack.setSpacing(10)

        suggestion_bar = QHBoxLayout()
        suggestion_bar.setContentsMargins(0, 0, 0, 0)
        suggestion_bar.setSpacing(8)

        self.suggestion_btn = QPushButton("Suggestions")
        self.suggestion_btn.setObjectName("suggestionTriggerBtn")
        self.suggestion_btn.setCursor(Qt.PointingHandCursor)
        self.suggestion_btn.setFlat(True)
        self.suggestion_btn.setMinimumHeight(24)
        self.suggestion_btn.setMinimumWidth(0)
        self.suggestion_btn.installEventFilter(self)
        suggestion_bar.addWidget(self.suggestion_btn)
        suggestion_bar.addStretch()

        self.prompt_input = QTextEdit()
        self.prompt_input.setObjectName("promptInput")
        self.prompt_input.setPlaceholderText(
            "Ask a question about your data or request an analysis..."
        )
        self.prompt_input.setMaximumHeight(80)
        command_stack.addLayout(suggestion_bar)
        command_stack.addWidget(self.prompt_input)

        self.suggestion_popover = SuggestionPopover(self)
        self.suggestion_popover.suggestion_selected.connect(self._apply_suggestion)
        self.suggestion_popover.installEventFilter(self)
        self.overview_popover = OverviewPopover(self)

        self.run_btn = QPushButton("Analyze")
        self.run_btn.setObjectName("runBtn")
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.setFixedSize(100, 48)
        self.run_btn.clicked.connect(self._on_analyze_clicked)

        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("applyBtn")
        self.apply_btn.setCursor(Qt.PointingHandCursor)
        self.apply_btn.setFixedSize(100, 48)
        self.apply_btn.clicked.connect(self._on_apply_clicked)
        self.apply_btn.setVisible(False)

        command_layout.addLayout(command_stack, stretch=1)
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
        self.history_page.task_open_requested.connect(self._open_history_task)
        self.settings_btn.clicked.connect(self._on_settings_clicked)
        self.dataset_list.currentItemChanged.connect(self._on_dataset_selection_changed)

        self._apply_style()
        self._refresh_api_status()
        self._refresh_overview_ui()
        self._show_start_page()

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
        from pathlib import Path
        preprocessor = Preprocessor()
        last_loaded_row = None
        
        for file_path in files:
            try:
                resolved_path = str(Path(file_path).resolve())
                if any(
                    meta.file_path == resolved_path
                    for meta in self.loaded_files.values()
                ):
                    self.log_output.append(
                        f"Please do not add the same file again: {Path(file_path).name}"
                    )
                    continue

                file_meta = preprocessor.process(file_path)
                file_name = self._dataset_display_name(file_path)

                self.loaded_files[file_name] = file_meta
                self._add_dataset_item(file_name)
                last_loaded_row = self.dataset_list.count() - 1
                self._ensure_dataset_overview(file_name, force=False)
                self.log_output.append(f"✓ Loaded: {file_name}")
            except Exception as e:
                self.log_output.append(f"✗ Error loading {file_path}: {str(e)}")

        if last_loaded_row is not None:
            self.dataset_list.setCurrentRow(last_loaded_row)
            selected_name = self.dataset_list.item(last_loaded_row).text()
            self.log_output.append(f"Selected dataset: {selected_name}")
            self._ensure_dataset_overview(selected_name, force=False)

    def _on_dataset_selection_changed(self, current, previous) -> None:
        del previous
        current_name = current.text() if current else None
        self._sync_dataset_row_selection(current_name)
        self._refresh_overview_ui(current_name)
        if current_name:
            self._ensure_dataset_overview(current_name, force=False)

    def eventFilter(self, watched, event):
        if watched is self.suggestion_btn:
            if event.type() == QEvent.Enter:
                self._show_suggestion_popover()
            elif event.type() == QEvent.Leave:
                self._schedule_suggestion_popover_hide()
        elif watched is self.suggestion_popover:
            if event.type() == QEvent.Enter:
                self._cancel_suggestion_popover_hide()
            elif event.type() == QEvent.Leave:
                self._schedule_suggestion_popover_hide()
        return super().eventFilter(watched, event)

    def _current_dataset_name(self) -> str | None:
        item = self.dataset_list.currentItem()
        return item.text() if item else None

    def _current_file_meta(self):
        dataset_name = self._current_dataset_name()
        if not dataset_name:
            return None
        return self.loaded_files.get(dataset_name)

    def _add_dataset_item(self, dataset_name: str) -> None:
        from PySide6.QtWidgets import QListWidgetItem

        item = QListWidgetItem()
        item.setText(dataset_name)
        item.setSizeHint(QSize(0, 44))
        self.dataset_list.addItem(item)

        row_widget = DatasetRowWidget(dataset_name, self.dataset_list)
        row_widget.activated.connect(self._select_dataset_by_name)
        row_widget.overview_requested.connect(self._show_overview_for_dataset)
        self.dataset_list.setItemWidget(item, row_widget)
        self._dataset_row_widgets[dataset_name] = row_widget
        self._sync_dataset_row_selection(self._current_dataset_name())

    def _select_dataset_by_name(self, dataset_name: str) -> None:
        item = self._find_dataset_item(dataset_name)
        if item is not None:
            self.dataset_list.setCurrentItem(item)

    def _sync_dataset_row_selection(self, selected_name: str | None) -> None:
        for dataset_name, row_widget in self._dataset_row_widgets.items():
            row_widget.setSelected(dataset_name == selected_name)

    def _show_overview_for_dataset(self, dataset_name: str) -> None:
        row_widget = self._dataset_row_widgets.get(dataset_name)
        cached = self._dataset_overviews.get(dataset_name) or {}
        if (
            row_widget is not None
            and self.overview_popover.isVisible()
            and self._current_dataset_name() == dataset_name
            and cached.get("state") == "ready"
            and cached.get("data")
        ):
            self.overview_popover.hide()
            return

        item = self._find_dataset_item(dataset_name)
        if item is not None:
            self.dataset_list.setCurrentItem(item)
        self._show_overview_popover(dataset_name)

    def _find_dataset_item(self, dataset_name: str):
        for index in range(self.dataset_list.count()):
            item = self.dataset_list.item(index)
            if item and item.text() == dataset_name:
                return item
        return None

    def _ensure_dataset_overview(self, dataset_name: str, force: bool) -> None:
        file_meta = self.loaded_files.get(dataset_name)
        if file_meta is None:
            return

        cached = self._dataset_overviews.get(dataset_name)
        if (
            not force
            and cached
            and cached.get("state") in {"loading", "queued", "ready"}
        ):
            self._refresh_overview_ui(dataset_name)
            return

        if self._overview_thread is not None:
            if self._overview_loading_dataset == dataset_name:
                return
            self._dataset_overviews[dataset_name] = {"state": "queued"}
            self._refresh_overview_ui(dataset_name)
            return

        self._dataset_overviews[dataset_name] = {"state": "loading"}
        self._overview_loading_dataset = dataset_name
        self._refresh_overview_ui(dataset_name)
        self._start_overview_worker(dataset_name, file_meta)

    def _show_overview_popover(self, dataset_name: str) -> None:
        cached = self._dataset_overviews.get(dataset_name) or {}
        state = cached.get("state")
        if state == "ready" and cached.get("data"):
            row_widget = self._dataset_row_widgets.get(dataset_name)
            if row_widget is not None:
                self.overview_popover.setOverview(cached["data"])
                self.overview_popover.showFor(row_widget.overview_button, self)
            return

        if state != "loading":
            self._ensure_dataset_overview(dataset_name, force=True)

    def _start_overview_worker(self, dataset_name: str, file_meta) -> None:
        thread = QThread(self)
        worker = AnalysisWorker(
            mode="overview",
            files_meta=[file_meta],
        )
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.event.connect(self._on_overview_event)
        worker.finished.connect(self._on_overview_finished)
        worker.error.connect(self._on_overview_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_overview_worker)

        self._overview_thread = thread
        self._overview_worker = worker
        self._overview_loading_dataset = dataset_name
        thread.start()

    def _on_overview_event(self, event: dict) -> None:
        message = str(event.get("message", ""))
        if message and event.get("type") == "status":
            self.log_output.append(message)

    def _on_overview_finished(self, result) -> None:
        dataset_name = self._overview_loading_dataset
        if dataset_name is not None:
            data = result.overview_result or {}
            self._dataset_overviews[dataset_name] = {
                "state": "ready",
                "data": data,
                "error": result.error,
            }
            if result.error:
                self.log_output.append(f"Overview fallback used: {result.error}")
        self._refresh_overview_ui(dataset_name)

    def _on_overview_error(self, error: str) -> None:
        dataset_name = self._overview_loading_dataset
        if dataset_name is not None:
            file_meta = self.loaded_files.get(dataset_name)
            fallback = {}
            if file_meta is not None:
                from dify.workflow import AnalysisWorkflow

                fallback = AnalysisWorkflow._fallback_overview(file_meta)
            self._dataset_overviews[dataset_name] = {
                "state": "ready" if fallback else "error",
                "data": fallback,
                "error": error,
            }
        self.log_output.append(f"Overview detail: {error}")
        self._refresh_overview_ui(dataset_name)

    def _cleanup_overview_worker(self) -> None:
        self._overview_thread = None
        self._overview_worker = None
        self._overview_loading_dataset = None
        self._refresh_overview_ui()
        for queued_name, queued_state in self._dataset_overviews.items():
            if (queued_state or {}).get("state") == "queued":
                self._ensure_dataset_overview(queued_name, force=True)
                break

    def _refresh_overview_ui(self, dataset_name: str | None = None) -> None:
        active_dataset = self._current_dataset_name()
        has_dataset = bool(active_dataset)
        self.suggestion_btn.setVisible(has_dataset)

        if not has_dataset:
            self.overview_popover.hide()
            self._set_suggestion_options([])
            return

        active_ready = False
        for row_name, row_widget in self._dataset_row_widgets.items():
            cached = self._dataset_overviews.get(row_name) or {}
            state = cached.get("state")
            data = cached.get("data") or {}

            if state == "loading":
                row_widget.setBusy(True)
                row_widget.overview_button.setToolTip("Preparing dataset overview")
                continue

            if state == "queued":
                row_widget.setQueued("Another overview is finishing first")
                continue

            if state == "ready" and data:
                row_widget.overview_button.setVisible(True)
                row_widget.setReady(data.get("summary") or "Dataset overview is ready")
                if row_name == active_dataset:
                    active_ready = True
                continue

            if state == "error":
                row_widget.overview_button.setBusy(False)
                row_widget.overview_button.setVisible(False)
                continue

            row_widget.overview_button.setBusy(False)
            row_widget.overview_button.setVisible(False)
            row_widget.setReady("Generate a quick overview for this dataset")

        active_cached = self._dataset_overviews.get(active_dataset) or {}
        active_state = active_cached.get("state")
        active_data = active_cached.get("data") or {}
        if active_state == "ready" and active_data:
            suggestions = active_data.get("suggestions") or self._build_default_suggestions(active_dataset)
            self._set_suggestion_options(suggestions)
        else:
            self._set_suggestion_options([])
            if active_ready:
                self._set_suggestion_options(active_data.get("suggestions") or self._build_default_suggestions(active_dataset))

    def _set_suggestion_options(self, suggestions: list[str]) -> None:
        self._suggestion_buttons = suggestions[:4]
        self.suggestion_btn.setVisible(bool(self._suggestion_buttons))
        self.suggestion_btn.setEnabled(bool(self._suggestion_buttons))
        self.suggestion_btn.setToolTip(
            "Suggested analysis prompts" if self._suggestion_buttons else ""
        )
        self.suggestion_popover.setSuggestions(self._suggestion_buttons)

    def _apply_suggestion(self, suggestion: str) -> None:
        self.prompt_input.setPlainText(suggestion)
        self.prompt_input.setFocus()
        self._hide_suggestion_popover()

    def _show_suggestion_popover(self) -> None:
        if not self._suggestion_buttons or not self.suggestion_btn.isVisible():
            return
        self._cancel_suggestion_popover_hide()
        self.suggestion_popover.showFor(self.suggestion_btn)

    def _schedule_suggestion_popover_hide(self) -> None:
        if self.suggestion_popover.isVisible():
            self._suggestion_hide_timer.start()

    def _cancel_suggestion_popover_hide(self) -> None:
        self._suggestion_hide_timer.stop()
        self.suggestion_popover.cancelHide()

    def _hide_suggestion_popover(self) -> None:
        self._suggestion_hide_timer.stop()
        self.suggestion_popover.hide()

    def _maybe_hide_suggestion_popover(self) -> None:
        cursor_pos = QCursor.pos()
        anchor_rect = QRect(
            self.suggestion_btn.mapToGlobal(QPoint(0, 0)),
            self.suggestion_btn.size(),
        )
        popover_rect = self.suggestion_popover.frameGeometry()
        if anchor_rect.contains(cursor_pos) or popover_rect.contains(cursor_pos):
            self._schedule_suggestion_popover_hide()
            return
        self._hide_suggestion_popover()

    def _build_default_suggestions(self, dataset_name: str | None) -> list[str]:
        if not dataset_name:
            return []
        file_meta = self.loaded_files.get(dataset_name)
        if file_meta is None or not file_meta.sheets:
            return []

        first_sheet = file_meta.sheets[0]
        numeric_cols = [
            name for name, dtype in first_sheet.dtypes.items()
            if dtype.startswith(("int", "float"))
        ]
        text_cols = [
            name for name, dtype in first_sheet.dtypes.items()
            if not dtype.startswith(("int", "float"))
        ]
        metric = numeric_cols[0] if numeric_cols else "the key metric"
        dimension = text_cols[0] if text_cols else "the main category"

        suggestions = [
            f"Give me a quick summary of the main patterns in {metric}.",
            f"Compare {metric} across {dimension}.",
            "Check missing values and unusual records in this dataset.",
            "Tell me the most important insights in this file.",
        ]
        return suggestions

    def _on_analyze_clicked(self):
        """Generate analysis code and prepare it for review/editing."""
        if not self._task_open:
            return

        selected_item = self.dataset_list.currentItem()
        query = self.prompt_input.toPlainText().strip()

        if not selected_item:
            self.log_output.append("Please select a dataset first.")
            return

        if not query:
            self.log_output.append("Please enter an analysis question.")
            return

        file_name = selected_item.text()
        file_meta = self.loaded_files.get(file_name)

        if not file_meta:
            self.log_output.append("File metadata not found.")
            return

        try:
            settings.reload()
            settings.validate_selected_provider()
        except EnvironmentError as e:
            self.log_output.append(f"✗ API configuration error: {e}")
            self._refresh_api_status()
            return

        self._generated_code = ""
        self.code_editor.clear()
        self._set_python_tab_visible(False)
        self._show_analyze_action()
        self._pending_query = query
        self._pending_files_meta = [file_meta]
        self._create_history_task(file_name, query)
        self.log_output.append(
            f"Using mode: {self._current_model_label()}"
        )
        self.log_output.append("Generating Python code...")
        self.result_output.setText("Waiting for analysis result.")
        self._run_generate()

    def _on_decision_made(self, option: OptionItem) -> None:
        """Compatibility hook for legacy decision UI."""
        self.canvas_stack.setCurrentIndex(0)
        self.log_output.append(f"Decision selected: {option.label}")

    def _on_decision_skipped(self) -> None:
        """Compatibility hook for legacy decision UI."""
        self.canvas_stack.setCurrentIndex(0)
        self.log_output.append("Decision skipped")

    def _on_settings_clicked(self) -> None:
        dialog = ApiSettingsDialog(self)
        dialog.settings_saved.connect(self._refresh_api_status)
        if dialog.exec():
            self.log_output.append(
                f"Settings saved for {self._current_model_label()} mode."
            )
            self._refresh_api_status()

    def _show_start_page(self) -> None:
        self._task_open = False
        self._active_task_id = None
        self.app_stack.setCurrentIndex(0)
        self._set_python_tab_visible(False)
        self._refresh_overview_ui(None)
        self._set_task_title()
        self._set_task_controls_enabled(False)

    def _start_new_task(self) -> None:
        if self._analysis_thread is not None:
            return

        active_task = self._find_history_task(self._active_task_id)
        if active_task and not active_task.get("finished"):
            self._update_history_task("Closed", "Started over", finished=True)

        self.loaded_files.clear()
        self._dataset_overviews.clear()
        self._dataset_row_widgets.clear()
        self.dataset_list.clear()
        self.prompt_input.clear()
        self.code_editor.clear()
        self.result_output.clear()
        self.log_output.clear()
        self.overview_popover.hide()
        self._hide_suggestion_popover()
        self._set_python_tab_visible(False)
        self._show_analyze_action()
        self._pending_files_meta = None
        self._pending_query = None
        self._generated_code = ""
        self._active_worker_mode = ""
        self._active_task_id = None
        self._reset_transcript()
        self._refresh_overview_ui()

        self._task_open = True
        self.app_stack.setCurrentIndex(1)
        self.page_container.setCurrentIndex(0)
        self._set_task_controls_enabled(True)
        self._set_task_title()
        self.log_output.append("New task started.")
        self.result_output.setText("Import a dataset, then ask an analysis question.")

    def _close_task(self) -> None:
        if self._analysis_thread is not None:
            self.log_output.append("Task is still running. Please wait until it finishes.")
            return

        active_task = self._find_history_task(self._active_task_id)
        if active_task and not active_task.get("finished"):
            self._update_history_task("Closed", finished=True)

        self._show_start_page()

    def _set_task_controls_enabled(self, enabled: bool) -> None:
        self.start_over_btn.setVisible(enabled)
        self.history_btn.setVisible(enabled)
        self.settings_btn.setVisible(enabled)
        self.upload_btn.setEnabled(enabled)
        self.dataset_list.setEnabled(enabled)
        self.prompt_input.setEnabled(enabled)
        self.run_btn.setEnabled(enabled)
        self.apply_btn.setEnabled(enabled and self.apply_btn.isVisible())
        self.code_editor.setEnabled(enabled)
        self.code_reset_btn.setEnabled(enabled)
        self.start_over_btn.setEnabled(enabled)

    def _show_history_page(self) -> None:
        self._refresh_history_page()
        self.page_container.setCurrentIndex(1)

    def _create_history_task(self, dataset: str, query: str) -> None:
        active_task = self._find_history_task(self._active_task_id)
        if active_task and not active_task.get("finished"):
            self._update_history_task(
                "Finished",
                "Replaced before execution",
                finished=True,
            )

        task_id = len(self._task_history) + 1
        now = self._history_timestamp()
        files_meta = list(self._pending_files_meta or [])
        self._task_history.append({
            "id": task_id,
            "dataset": dataset,
            "query": query,
            "status": "Generating code",
            "status_detail": "",
            "created_at": now,
            "updated_at": now,
            "finished": False,
            "files_meta": files_meta,
            "generated_code": "",
            "code": "",
            "result": "Waiting for analysis result.",
            "error": "",
        })
        self._active_task_id = task_id
        self._set_task_title(task_id)
        self._refresh_history_page()

    def _update_history_task(
        self,
        status: str,
        detail: str = "",
        finished: bool = False,
        **updates,
    ) -> None:
        if self._active_task_id is None:
            return

        task = self._find_history_task(self._active_task_id)
        if task is None:
            return

        task["status"] = status
        task["status_detail"] = detail
        task["updated_at"] = self._history_timestamp()
        task["finished"] = finished
        task.update(updates)
        self._set_task_title(self._active_task_id)
        self._refresh_history_page()

    def _find_history_task(self, task_id: int | None) -> dict | None:
        if task_id is None:
            return None
        for task in self._task_history:
            if task.get("id") == task_id:
                return task
        return None

    def _open_history_task(self, task_id: int) -> None:
        task = self._find_history_task(task_id)
        if task is None or self._analysis_thread is not None:
            return

        files_meta = list(task.get("files_meta") or [])
        self.loaded_files.clear()
        self._dataset_row_widgets.clear()
        self.dataset_list.clear()
        for file_meta in files_meta:
            display_name = self._dataset_display_name(file_meta.file_path)
            self.loaded_files[display_name] = file_meta
            self._add_dataset_item(display_name)

        if self.dataset_list.count():
            self.dataset_list.setCurrentRow(0)

        code = task.get("code") or task.get("generated_code") or ""
        result = task.get("result") or "Session reopened."
        error = task.get("error") or ""

        self._active_task_id = task_id
        self._pending_files_meta = files_meta or None
        self._pending_query = task.get("query", "")
        self._generated_code = task.get("generated_code") or code
        self._active_worker_mode = ""
        self._reset_transcript()
        self.prompt_input.setPlainText(task.get("query", ""))
        self.code_editor.setPlainText(code)
        self.result_output.setPlainText(result)
        self.log_output.clear()
        self.log_output.append(f"Session reopened: Task #{task_id}")
        if error:
            self.log_output.append(f"Last error detail: {error}")

        self._task_open = True
        self.app_stack.setCurrentIndex(1)
        self.page_container.setCurrentIndex(0)
        self._set_task_controls_enabled(True)
        self._set_task_title(task_id)
        self._refresh_overview_ui()

        if code:
            self._set_python_tab_visible(True)
            self._show_apply_action(retry=True)
            self.analysis_tabs.setCurrentIndex(1 if error else 0)
        else:
            self._set_python_tab_visible(False)
            self._show_analyze_action()
            self.analysis_tabs.setCurrentIndex(0)

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

    def _set_task_title(self, task_id: int | None = None) -> None:
        task = self._find_history_task(task_id or self._active_task_id)
        if task is None:
            self.task_title_label.clear()
            self.task_title_label.setVisible(False)
            return
        self.task_title_label.setText(f"Session #{task['id']}")
        self.task_title_label.setVisible(True)

    def _refresh_api_status(self) -> None:
        settings.reload()
        status = settings.provider_status().get(settings.LLM_PROVIDER, {})
        missing = [key for key, present in status.items() if not present]
        if missing:
            self.api_status_label.setText(
                f"Mode: {self._current_model_label()} | missing {', '.join(missing)}"
            )
        else:
            self.api_status_label.setText(
                f"Mode: {self._current_model_label()} | ready"
            )

    def _current_model_label(self) -> str:
        return "DevOps" if settings.LLM_PROVIDER == "gemini" else "Dify"
        if settings.LLM_PROVIDER == "gemini":
            return f"DevOps · {settings.GEMINI_MODEL}"

    def _run_generate(self):
        """生成代码并展示到可编辑区域，等待用户点击 Apply 后再执行。"""
        if not self._pending_query or not self._pending_files_meta:
            return

        self._reset_transcript()
        self._append_system_event("Generating code...")
        self._start_analysis_worker(
            mode="generate",
            files_meta=self._pending_files_meta,
            user_query=self._pending_query,
        )

    def _show_analyze_action(self) -> None:
        self.run_btn.setVisible(True)
        self.run_btn.setEnabled(True)
        self.run_btn.setText("Analyze")
        self.apply_btn.setVisible(False)

    def _show_apply_action(self, retry: bool = False) -> None:
        self._set_python_tab_visible(True)
        self.run_btn.setVisible(False)
        self.apply_btn.setVisible(True)
        self.apply_btn.setEnabled(True)
        self.apply_btn.setText("Apply Again" if retry else "Apply")

    def _on_apply_clicked(self):
        """Execute the code currently in the editor."""
        if not self._pending_files_meta:
            return

        code = self.code_editor.toPlainText().strip()
        if not code:
            self.result_output.setText("No Python code is available to execute yet.")
            return

        self._append_system_event("Executing approved code...")
        self.apply_btn.setText("Running")
        self.apply_btn.setEnabled(False)
        self._update_history_task(
            "Executing",
            finished=False,
            code=code,
            result="Running local analysis.",
            error="",
        )
        self._start_analysis_worker(
            mode="execute",
            files_meta=self._pending_files_meta,
            code=code,
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
            self.log_output.append(message)
        elif event_type == "thinking_delta":
            self._transcript["thinking"] += delta
        elif event_type == "content_delta":
            self._transcript["code"] += delta
            if self._active_worker_mode == "generate":
                self.code_editor.setPlainText(self._transcript["code"])
        elif event_type == "tool_delta":
            self._transcript["tools"] += delta
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
            if result.success:
                self._generated_code = result.code
                self.code_editor.setPlainText(result.code)
                self.code_editor.document().setModified(False)
                self._append_system_event("Code generated. Review and edit it before Apply.")
                self.log_output.append("Code generated and ready for review.")
                self._transcript["execution"] = (
                    "Python code is ready. Review it in the Python tab, then click Apply."
                )
                self._set_python_tab_visible(True)
                self.analysis_tabs.setCurrentIndex(1)
                self._show_apply_action()
                self._update_history_task(
                    "Awaiting Apply",
                    generated_code=result.code,
                    code=result.code,
                    result="Python code is ready. Review it in the Python tab, then click Apply.",
                    error="",
                )
            else:
                self._append_system_event(f"Generation failed: {result.error}")
                self.log_output.append(f"Generation failed: {result.error}")
                self._transcript["execution"] = (
                    "Code generation failed. Check settings and try Analyze again."
                )
                self._pending_query = None
                self._pending_files_meta = None
                self._set_python_tab_visible(False)
                self._show_analyze_action()
                self._update_history_task(
                    "Failed",
                    result.error,
                    finished=True,
                    result="Code generation failed. Check settings and try Analyze again.",
                    error=result.error,
                )

        elif self._active_worker_mode == "execute":
            if result.success:
                output_text = result.execution.stdout if result.execution else ""
                self._append_system_event("Execution completed")
                self.log_output.append("Execution completed.")
                self._transcript["execution"] = output_text or "Execution completed with no stdout."
                self._set_python_tab_visible(True)
                self._update_history_task(
                    "Completed",
                    finished=True,
                    code=self.code_editor.toPlainText().strip(),
                    result=self._transcript["execution"],
                    error="",
                )
                self.analysis_tabs.setCurrentIndex(0)
                self._show_apply_action(retry=True)
            else:
                error_text = (
                    result.execution.stderr if result.execution else result.error
                )
                self._append_system_event("Execution failed")
                self.log_output.append(f"Execution detail: {error_text}")
                self._transcript["execution"] = (
                    "The Python code could not be executed.\n"
                    "Review or reset the code, then click Apply Again."
                )
                self._set_python_tab_visible(True)
                self._update_history_task(
                    "Needs correction",
                    finished=False,
                    code=self.code_editor.toPlainText().strip(),
                    result=self._transcript["execution"],
                    error=error_text,
                )
                self.analysis_tabs.setCurrentIndex(1)
                self._show_apply_action(retry=True)

        self._render_transcript()
        self._set_busy(False)

    def _on_worker_error(self, error: str) -> None:
        self._append_system_event(f"Worker error: {error}")
        self.log_output.append(f"Worker detail: {error}")
        if self._active_worker_mode == "execute":
            self._transcript["execution"] = (
                "The Python code could not be executed.\n"
                "Review or reset the code, then click Apply Again."
            )
            self._set_python_tab_visible(True)
            self.analysis_tabs.setCurrentIndex(1)
            self._show_apply_action(retry=True)
            self._update_history_task(
                "Needs correction",
                finished=False,
                code=self.code_editor.toPlainText().strip(),
                result=self._transcript["execution"],
                error=error,
            )
        else:
            self._transcript["execution"] = (
                "Code generation failed. Check settings and try Analyze again."
            )
            self._pending_query = None
            self._pending_files_meta = None
            self._set_python_tab_visible(False)
            self._show_analyze_action()
            self._update_history_task(
                "Failed",
                error,
                finished=True,
                result="Code generation failed. Check settings and try Analyze again.",
                error=error,
            )
        self._render_transcript()
        self._set_busy(False)

    def _cleanup_worker(self) -> None:
        self._analysis_thread = None
        self._analysis_worker = None
        self._active_worker_mode = ""

    def _set_busy(self, busy: bool) -> None:
        self.run_btn.setEnabled(not busy)
        self.upload_btn.setEnabled(not busy)
        self.settings_btn.setEnabled(not busy)
        self.history_btn.setEnabled(not busy)
        self.start_over_btn.setEnabled(not busy)
        self.code_reset_btn.setEnabled(not busy)
        self.code_editor.setEnabled(not busy)
        if busy:
            self.run_btn.setText("Working")
            self.apply_btn.setEnabled(False)
        else:
            self.run_btn.setText("Analyze")
            self.apply_btn.setEnabled(True)

    def _reset_transcript(self) -> None:
        self._transcript = {
            "system": [],
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
        execution_text = self._transcript["execution"].strip()
        if execution_text:
            self.result_output.setPlainText(execution_text)

    def _dataset_display_name(self, file_path: str) -> str:
        from pathlib import Path

        path = Path(file_path)
        base_name = path.name
        if base_name not in self.loaded_files:
            return base_name

        stem = path.stem
        suffix = path.suffix
        index = 2
        while True:
            candidate = f"{stem} ({index}){suffix}"
            if candidate not in self.loaded_files:
                return candidate
            index += 1

    def _reset_code_to_generated(self) -> None:
        if not self._generated_code:
            return
        self.code_editor.setPlainText(self._generated_code)
        self._set_python_tab_visible(True)
        self.analysis_tabs.setCurrentIndex(1)
        if self._pending_files_meta:
            self._show_apply_action(retry=True)

    def _set_python_tab_visible(self, visible: bool) -> None:
        self.analysis_tabs.tabBar().setTabVisible(self.python_tab_index, visible)
        if not visible:
            self.analysis_tabs.setCurrentIndex(0)

    @staticmethod
    def _format_json(value) -> str:
        if not value:
            return ""
        import json

        return json.dumps(value, ensure_ascii=False, indent=2)


    def _apply_style(self):

        self.setStyleSheet("""
            QWidget#rootWidget {
                background-color: transparent;
            }

            QFrame#appSurface {
                background-color: #F8F9FA;
                border: 1px solid #C9CED6;
                border-radius: 8px;
            }

            QMainWindow {
                background-color: transparent;
            }

            QWidget#titleBar {
                background-color: #F8F9FA;
                border-bottom: 1px solid #E8EAED;
                border-top-left-radius: 7px;
                border-top-right-radius: 7px;
            }

            /* ========================================================================= */
            /* Title Bar 按钮完美对齐修复版 */
            /* ========================================================================= */

            QLabel#titleBarLogo {
                color: #111827;
                font-size: 13px;
                font-weight: 800;
                letter-spacing: 0;
            }

            QLabel#titleBarText {
                color: #202124;
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 0;
            }

            QLabel#titleBarSessionText {
                color: #5F6368;
                font-size: 12px;
                font-weight: 600;
                letter-spacing: 0;
                padding-left: 8px;
                border-left: 1px solid #DADCE0;
            }

            QPushButton#titleActionBtn {
                background-color: transparent;
                color: #3C4043;
                font-size: 12px;
                font-weight: 600;
                border: 1px solid #DADCE0;
                border-radius: 6px;
                padding: 3px 8px;
                min-height: 24px;
                max-height: 24px;
            }

            QPushButton#titleActionBtn:hover {
                background-color: #F1F3F4;
            }

            QPushButton#titleGearBtn {
                background-color: transparent;
                color: #3C4043;
                font-size: 14px;
                font-weight: 600;
                border: 1px solid #DADCE0;
                border-radius: 6px;
                padding: 2px;
                min-width: 28px;
                max-width: 28px;
                min-height: 24px;
                max-height: 24px;
            }

            QPushButton#titleGearBtn:hover {
                background-color: #F1F3F4;
            }

            QPushButton#btnMinimize,
            QPushButton#btnMaximize,
            QPushButton#btnClose {
                background-color: transparent;
                border: none;
                border-radius: 6px;
                color: #5F6368;
                font-family: "Segoe UI Symbol", "Segoe UI";
                font-size: 15px;
                font-weight: normal;
                
                padding: 0px;
                margin: 0px;
                text-align: center;
            }

            QPushButton#btnMinimize:hover,
            QPushButton#btnMaximize:hover {
                background-color: #E8EAED;
                color: #202124;
            }

            QPushButton#btnClose:hover {
                background-color: #FCE8E6;
                color: #C5221F;
            }

            /* ========================================================================= */
            /* Sidebar */
            /* ========================================================================= */

            QWidget#sidebar {
                background-color: #F8F9FA;
                border-right: 1px solid #E8EAED;
                border-bottom-left-radius: 7px;
            }

            QWidget#workspace {
                background-color: #FFFFFF;
                border-left: 1px solid #E5E7EB;
                border-bottom-right-radius: 7px;
            }

            QWidget#workspaceRoot {
                background-color: #FFFFFF;
                border-bottom-left-radius: 7px;
                border-bottom-right-radius: 7px;
            }

            QWidget#startPage {
                background-color: #FFFFFF;
                border-bottom-left-radius: 7px;
                border-bottom-right-radius: 7px;
            }

            QWidget#historyPage {
                background-color: #FFFFFF;
                border-bottom-left-radius: 7px;
                border-bottom-right-radius: 7px;
            }

            QLabel#startTitle {
                color: #111827;
                font-size: 28px;
                font-weight: 700;
                letter-spacing: 0;
            }

            QLabel#startNote {
                color: #374151;
                font-size: 14px;
                font-weight: 400;
                letter-spacing: 0;
            }

            QLabel#startCaution {
                color: #6B7280;
                font-size: 12px;
                font-weight: 400;
                letter-spacing: 0;
            }

            QPushButton#startTaskBtn {
                background-color: #1A73E8;
                color: #FFFFFF;
                font-size: 14px;
                font-weight: 600;
                border-radius: 8px;
                border: none;
            }

            QPushButton#startTaskBtn:hover {
                background-color: #1765CC;
            }

            QLabel {
                font-family: "Segoe UI";
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 0;
                color: #5F6368;
            }

            QSplitter::handle {
                background-color: #E5E7EB;
            }

            /* Buttons */
            QPushButton#uploadBtn,
            QPushButton#historyBtn {
                background-color: #FFFFFF;
                color: #202124;
                font-size: 13px;
                font-weight: 600;
                border: 1px solid #DADCE0;
                border-radius: 6px;
                padding: 8px;
                height: 32px;
            }

            QPushButton#uploadBtn:hover,
            QPushButton#historyBtn:hover {
                background-color: #F1F3F4;
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
                outline: none;
            }

            QListWidget#datasetList::item {
                padding: 0px;
                margin: 0 0 6px 0;
                border: none;
                background: transparent;
            }

            QListWidget#datasetList::item:hover {
                background: transparent;
            }

            QListWidget#datasetList::item:selected {
                background: transparent;
                color: #374151;
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

            QPushButton#suggestionTriggerBtn {
                background-color: #F8FAFC;
                color: #374151;
                border: 1px solid #E5E7EB;
                border-radius: 999px;
                padding: 5px 12px;
                font-size: 12px;
                font-weight: 500;
                min-height: 24px;
            }

            QPushButton#suggestionTriggerBtn:hover {
                background-color: #EFF6FF;
                border-color: #D1D5DB;
                color: #1D4ED8;
            }

            QLabel#codePanelLabel {
                color: #374151;
                font-size: 12px;
                letter-spacing: 0;
            }

            QPushButton#codeResetBtn {
                background-color: transparent;
                color: #5F6368;
                font-size: 11px;
                font-weight: 600;
                border: none;
                border-radius: 4px;
                padding: 2px 6px;
                min-height: 20px;
                max-height: 20px;
            }

            QPushButton#codeResetBtn:hover {
                background-color: #F1F3F4;
                color: #202124;
            }

            QPlainTextEdit#codeEditor {
                background-color: #202124;
                color: #E8EAED;
                border: 1px solid #3C4043;
                border-radius: 6px;
                padding: 12px;
                font-family: "Cascadia Mono", "Consolas", monospace;
                font-size: 12px;
                selection-background-color: #1A73E8;
                selection-color: #FFFFFF;
            }

            QTabWidget#analysisTabs::pane {
                border: none;
                background-color: #FFFFFF;
            }

            QTabWidget#analysisTabs QTabBar::tab {
                background-color: transparent;
                color: #5F6368;
                border: none;
                border-bottom: 2px solid transparent;
                padding: 8px 14px;
                font-size: 12px;
                font-weight: 600;
            }

            QTabWidget#analysisTabs QTabBar::tab:selected {
                color: #1A73E8;
                border-bottom-color: #1A73E8;
            }

            QTabWidget#analysisTabs QTabBar::tab:hover {
                background-color: #F8F9FA;
            }

            /* ========================================================================= */
            /* Command Bar */
            /* ========================================================================= */

            QFrame#commandBar {
                background-color: rgba(255, 255, 255, 0.9);
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
                background-color: #1A73E8;
                color: #FFFFFF;
                font-size: 14px;
                font-weight: 600;
                border-radius: 8px;
                border: none;
            }

            QPushButton#runBtn:hover {
                background-color: #1765CC;
            }

            QPushButton#runBtn:pressed {
                background-color: #185ABC;
            }

            QPushButton#applyBtn {
                background-color: #1A73E8;
                color: #FFFFFF;
                font-size: 14px;
                font-weight: 600;
                border-radius: 8px;
                border: none;
            }

            QPushButton#applyBtn:hover {
                background-color: #1765CC;
            }

            QPushButton#applyBtn:pressed {
                background-color: #185ABC;
            }
        """ + DECISION_PANEL_STYLE)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
