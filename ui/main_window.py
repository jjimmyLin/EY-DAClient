import logging
import re
import sys
from datetime import datetime
from functools import partial
from pathlib import Path
from PySide6.QtCore import (
    Qt,
    QPoint,
    QRect,
    QSize,
    QThread,
    QTimer,
    QEvent,
    QEasingCurve,
    QPropertyAnimation,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QIcon,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QPolygon,
)
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
    QProgressBar,
    QStyle,
    QMenu,
    QMessageBox,
    QInputDialog,
)
from ui.history_page import HistoryPage
from ui.decision_panel import DecisionPanel, OptionItem, DECISION_PANEL_STYLE
from ui.api_settings_dialog import ApiSettingsDialog
from ui.floating_controls import (
    CircularStatusButton,
    DatasetRowWidget,
    SuggestionPopover,
)
from ui.overview_popover import OverviewPopover
from ui.experience_feedback import ExperienceFeedbackCard
from ui.result_panel import AnalysisResultPanel, RESULT_PANEL_STYLE
from ui.cleaning_page import CleaningPage, CLEANING_PAGE_STYLE
from ui.data_portal import DataPortalPage, DATA_PORTAL_STYLE
from ui.data_portal import SUPPORTED_DATASET_SUFFIXES
from ui.metric_discovery_page import MetricDiscoveryPage
from core.analysis_result import AnalysisResult
from core.experience_payload import new_analysis_run_id, new_analysis_session_id
from config.settings import settings
from services.experience_service import ExperienceService
from workers.analysis_worker import AnalysisWorker
from workers.experience_worker import ExperienceSubmissionQueue
from workers.import_worker import ImportWorker
from workers.cleaning_worker import CleaningExecutionWorker, CleaningProfileWorker
from workers.export_worker import AnalysisExportWorker
from workers.metric_discovery_worker import MetricDiscoveryWorker


logger = logging.getLogger(__name__)


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
        layout.setContentsMargins(16, 0, 0, 0)
        layout.setSpacing(12)

        self.logo_label = QLabel()
        self.logo_label.setObjectName("titleBarLogo")
        self.logo_label.setFixedSize(34, 28)
        self.logo_label.setPixmap(self._build_logo_pixmap())
        self.logo_label.setToolTip("EY")

        self.session_label = QLabel("")
        self.session_label.setObjectName("titleBarSessionText")

        layout.addWidget(self.logo_label)
        self.menu_layout = QHBoxLayout()
        self.menu_layout.setContentsMargins(4, 0, 0, 0)
        self.menu_layout.setSpacing(2)
        layout.addLayout(self.menu_layout)
        layout.addWidget(self.session_label)
        layout.addStretch()

        self.actions_layout = QHBoxLayout()
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setSpacing(8)
        layout.addLayout(self.actions_layout)

        # Window controls use native line icons and edge-to-edge hover states.
        self.btn_minimize = QPushButton()
        self.btn_minimize.setObjectName("btnMinimize")
        self.btn_minimize.setIcon(self._build_window_icon("minimize"))
        self.btn_minimize.setIconSize(QSize(12, 12))
        self.btn_minimize.setFixedSize(44, 44)
        self.btn_minimize.setCursor(Qt.PointingHandCursor)
        self.btn_minimize.setToolTip("Minimize")
        self.btn_minimize.clicked.connect(self.window().showMinimized)

        self.btn_maximize = QPushButton()
        self.btn_maximize.setObjectName("btnMaximize")
        self.btn_maximize.setIconSize(QSize(11, 11))
        self.btn_maximize.setFixedSize(44, 44)
        self.btn_maximize.setCursor(Qt.PointingHandCursor)
        self.btn_maximize.setToolTip("Maximize")
        self.btn_maximize.clicked.connect(self._toggle_maximize)
        self._sync_maximize_icon()

        self.btn_close = QPushButton()
        self.btn_close.setObjectName("btnClose")
        self.btn_close.setIcon(self._build_window_icon("close"))
        self.btn_close.setIconSize(QSize(11, 11))
        self.btn_close.setFixedSize(44, 44)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setToolTip("Close")
        self.btn_close.clicked.connect(self.window().close)

        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(0)
        controls_layout.addWidget(self.btn_minimize)
        controls_layout.addWidget(self.btn_maximize)
        controls_layout.addWidget(self.btn_close)
        layout.addLayout(controls_layout)

    @staticmethod
    def _build_logo_pixmap() -> QPixmap:
        pixmap = QPixmap(34, 28)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#FFE600"))
        painter.drawPolygon(
            QPolygon(
                [
                    QPoint(2, 8),
                    QPoint(32, 1),
                    QPoint(32, 7),
                ]
            )
        )
        painter.setPen(QColor("#2E2E38"))
        font = painter.font()
        font.setFamily("Arial")
        font.setPointSize(12)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRect(1, 8, 32, 19), Qt.AlignCenter, "EY")
        painter.end()
        return pixmap

    def add_action_widget(self, widget: QWidget) -> None:
        self.actions_layout.addWidget(widget)

    def add_menu_widget(self, widget: QWidget) -> None:
        self.menu_layout.addWidget(widget)

    def _sync_maximize_icon(self) -> None:
        maximized = self.window().isMaximized()
        self.btn_maximize.setIcon(
            self._build_window_icon("restore" if maximized else "maximize")
        )
        self.btn_maximize.setToolTip("Restore" if maximized else "Maximize")

    @staticmethod
    def _build_window_icon(kind: str) -> QIcon:
        pixmap = QPixmap(14, 14)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor("#4B5563"), 1.25))
        if kind == "minimize":
            painter.drawLine(3, 8, 11, 8)
        elif kind == "maximize":
            painter.drawRect(3, 3, 8, 8)
        elif kind == "restore":
            painter.drawRect(4, 2, 7, 7)
            painter.drawRect(2, 4, 7, 7)
        else:
            painter.drawLine(3, 3, 11, 11)
            painter.drawLine(11, 3, 3, 11)
        painter.end()
        return QIcon(pixmap)

    def _toggle_maximize(self):
        if self.window().isMaximized():
            self.window().showNormal()
            self.window().setFixedSize(1000, 600)
        else:
            self.window().setMinimumSize(800, 600)
            self.window().setMaximumSize(16777215, 16777215)
            self.window().showMaximized()
        self._sync_maximize_icon()

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
                self._sync_maximize_icon()

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
        self.setWindowOpacity(0.0)
        
        self.loaded_files = {}  # Store display key -> FileMeta mapping
        self._pending_files_meta = None
        self._pending_query = None
        self._analysis_thread = None
        self._analysis_worker = None
        self._overview_thread = None
        self._overview_worker = None
        self._import_thread = None
        self._import_worker = None
        self._cleaning_thread = None
        self._cleaning_worker = None
        self._export_thread = None
        self._export_worker = None
        self._metric_thread = None
        self._metric_worker = None
        self._experience_submissions = ExperienceSubmissionQueue(self)
        self._experience_submissions.submitted.connect(
            self._on_experience_submission_finished
        )
        self._experience_submissions.failed.connect(
            self._on_experience_submission_failed
        )
        self._experience_prompt_task_id = None
        self._dataset_states = {}
        self._selected_datasets = set()
        self._active_mode = ""
        self._background_analysis_mode = False
        self._background_execute_pending = False
        self._active_worker_mode = ""
        self._transcript = {}
        self._task_history = []
        self._active_task_id = None
        self._generated_code = ""
        self._analysis_plan = {}
        self._current_analysis_result = None
        self._refresh_result_export_state()
        self._verified_code = ""
        self._verified_execution = None
        self._last_applied_code = ""
        self._task_open = False
        self._dataset_overviews = {}
        self._dataset_row_widgets = {}
        self._overview_loading_dataset = None
        self._overview_loading_meta = None
        self._suggestion_buttons = []
        self._suggestion_hide_timer = QTimer(self)
        self._suggestion_hide_timer.setSingleShot(True)
        self._suggestion_hide_timer.setInterval(160)
        self._suggestion_hide_timer.timeout.connect(self._maybe_hide_suggestion_popover)
        self._context_panel_open = False
        self._context_click_guard_active = False
        self._context_animation = None
        self._composer_collapsed = False
        self._composer_animation = None
        self._startup_revealed = False
        self._startup_animation = QPropertyAnimation(
            self,
            b"windowOpacity",
            self,
        )
        self._startup_animation.setDuration(160)
        self._startup_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._activity_pulse_t = 0.0
        self._activity_progress_value = 0
        self._activity_pulse = QVariantAnimation(self)
        self._activity_pulse.setDuration(1600)
        self._activity_pulse.setStartValue(0.0)
        self._activity_pulse.setEndValue(1.0)
        self._activity_pulse.setLoopCount(-1)
        self._activity_pulse.setEasingCurve(QEasingCurve.InOutSine)
        self._activity_pulse.valueChanged.connect(self._on_activity_pulse)
        self._activity_progress_animation = QVariantAnimation(self)
        self._activity_progress_animation.setDuration(220)
        self._activity_progress_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._activity_progress_animation.valueChanged.connect(self._on_activity_progress_changed)

        self._init_ui()
        self._center_on_screen()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._center_on_screen()
        if not self._startup_revealed:
            self._startup_revealed = True
            QTimer.singleShot(0, self._reveal_startup_window)

    def _center_on_screen(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def _reveal_startup_window(self) -> None:
        self._startup_animation.stop()
        self._startup_animation.setStartValue(self.windowOpacity())
        self._startup_animation.setEndValue(1.0)
        self._startup_animation.start()

    def _init_ui(self):

        root_widget = QWidget()
        root_widget.setObjectName("rootWidget")

        self.setCentralWidget(root_widget)

        root_layout = QVBoxLayout(root_widget)

        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        app_surface = QFrame()
        self.app_surface = app_surface
        app_surface.setObjectName("appSurface")
        surface_layout = QVBoxLayout(app_surface)
        surface_layout.setContentsMargins(1, 1, 1, 1)
        surface_layout.setSpacing(0)
        root_layout.addWidget(app_surface)

        self.title_bar = TitleBar(self)
        surface_layout.addWidget(self.title_bar)

        self.task_title_label = self.title_bar.session_label

        self.file_menu_btn = self._make_title_menu_button("File")
        self.view_menu_btn = self._make_title_menu_button("View")
        self.help_menu_btn = self._make_title_menu_button("Help")
        self.title_bar.add_menu_widget(self.file_menu_btn)
        self.title_bar.add_menu_widget(self.view_menu_btn)
        self.title_bar.add_menu_widget(self.help_menu_btn)
        self.history_btn = self._make_title_menu_button("History")
        self.history_btn.setToolTip("Task history")
        self.settings_btn = self._make_title_menu_button("Config")
        self.settings_btn.setToolTip("API and application settings")
        self.title_bar.add_menu_widget(self.history_btn)
        self.title_bar.add_menu_widget(self.settings_btn)
        self._build_title_menus()

        self.mode_button = QPushButton("Mode")
        self.mode_button.setObjectName("modeSelectorButton")
        self.mode_button.setCursor(Qt.PointingHandCursor)
        mode_menu = QMenu(self.mode_button)
        self.mode_analysis_action = QAction("Data Analysis", self)
        self.mode_cleaning_action = QAction("Data Cleaning", self)
        self.mode_metric_action = QAction("Business Indicators", self)
        self.mode_analysis_action.triggered.connect(self._show_analysis_workspace)
        self.mode_cleaning_action.triggered.connect(self._show_cleaning_page)
        self.mode_metric_action.triggered.connect(self._show_metric_page)
        mode_menu.addAction(self.mode_analysis_action)
        mode_menu.addAction(self.mode_cleaning_action)
        mode_menu.addAction(self.mode_metric_action)
        self.mode_button.setMenu(mode_menu)
        self.dataset_library_btn = QPushButton("Datasets · 0")
        self.dataset_library_btn.setObjectName("datasetLibraryButton")
        self.dataset_library_btn.setCursor(Qt.PointingHandCursor)
        self.dataset_library_btn.clicked.connect(self._toggle_context_panel)
        self.title_bar.add_action_widget(self.mode_button)
        self.title_bar.add_action_widget(self.dataset_library_btn)
        self.mode_button.setVisible(False)
        self.dataset_library_btn.setVisible(False)

        self.app_stack = QStackedWidget()
        surface_layout.addWidget(self.app_stack)

        self.start_page = DataPortalPage()
        self.start_page.add_requested.connect(self._on_upload_clicked)
        self.start_page.files_dropped.connect(self._queue_dataset_files)
        self.start_page.analysis_requested.connect(self._start_new_task)
        self.start_page.cleaning_requested.connect(self._start_cleaning)
        self.start_page.metric_requested.connect(self._show_metric_page)
        self.start_page.library_requested.connect(self._toggle_context_panel)

        workspace_root = QWidget()
        self.workspace_root = workspace_root
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
        # Navigation rail and contextual data panel
        # =========================================================================

        self.left_shell = QFrame(app_surface)
        self.left_shell.setObjectName("datasetLibraryOverlay")
        self.left_shell.setFixedWidth(342)
        self.left_shell.setVisible(False)
        left_shell_layout = QHBoxLayout(self.left_shell)
        left_shell_layout.setContentsMargins(1, 1, 1, 1)
        left_shell_layout.setSpacing(0)

        navigation_rail = QFrame()
        navigation_rail.setObjectName("navigationRail")
        navigation_rail.setFixedWidth(48)
        navigation_rail.setVisible(False)
        rail_layout = QVBoxLayout(navigation_rail)
        rail_layout.setContentsMargins(6, 10, 6, 10)
        rail_layout.setSpacing(6)

        self.nav_analysis_btn = self._make_nav_button(
            QStyle.SP_FileDialogContentsView,
            "Dataset library",
        )
        self.nav_clean_btn = self._make_nav_button(
            QStyle.SP_BrowserReload,
            "Data cleaning",
        )
        self.nav_metric_btn = self._make_nav_button(
            QStyle.SP_FileDialogInfoView,
            "Business analysis indicators",
        )
        rail_layout.addWidget(self.nav_analysis_btn)
        rail_layout.addWidget(self.nav_clean_btn)
        rail_layout.addWidget(self.nav_metric_btn)
        rail_layout.addStretch()

        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(340)
        self.sidebar.setVisible(True)

        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(14, 16, 14, 16)
        sidebar_layout.setSpacing(12)

        context_header = QHBoxLayout()
        context_title = QLabel("DATASET LIBRARY")
        context_title.setObjectName("contextPanelTitle")
        self.context_close_btn = QPushButton("×")
        self.context_close_btn.setObjectName("contextCloseBtn")
        self.context_close_btn.setFixedSize(24, 24)
        self.context_close_btn.setCursor(Qt.PointingHandCursor)
        self.context_close_btn.setToolTip("Close dataset panel")
        context_header.addWidget(context_title)
        context_header.addStretch()
        context_header.addWidget(self.context_close_btn)
        sidebar_layout.addLayout(context_header)

        self.upload_btn = QPushButton("+ Add Dataset")
        self.upload_btn.setObjectName("uploadBtn")
        self.upload_btn.setCursor(Qt.PointingHandCursor)
        self.upload_btn.clicked.connect(self._on_upload_clicked)

        self.dataset_selection_label = QLabel("Analysis scope: 0 of 3 selected")
        self.dataset_selection_label.setObjectName("datasetSelectionLabel")

        self.dataset_list = QListWidget()
        self.dataset_list.setObjectName("datasetList")

        self.api_status_label = QLabel()
        self.api_status_label.setObjectName("apiStatusLabel")
        self.api_status_label.setWordWrap(True)

        sidebar_layout.addWidget(self.upload_btn)
        sidebar_layout.addWidget(self.dataset_selection_label)
        sidebar_layout.addWidget(self.dataset_list, stretch=1)
        sidebar_layout.addWidget(self.api_status_label)

        left_shell_layout.addWidget(navigation_rail)
        left_shell_layout.addWidget(self.sidebar)
        dataset_shadow = QGraphicsDropShadowEffect(self)
        dataset_shadow.setBlurRadius(34)
        dataset_shadow.setOffset(0, 10)
        dataset_shadow.setColor(QColor(2, 12, 24, 105))
        self.left_shell.setGraphicsEffect(dataset_shadow)

        # =========================================================================
        # Workspace (Page 1)
        # =========================================================================

        self.workspace = QWidget()
        self.workspace.setObjectName("workspace")

        workspace_layout = QVBoxLayout(self.workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)

        self.canvas_container = QWidget()
        self.canvas_container.setObjectName("canvasContainer")
        canvas_layout = QVBoxLayout(self.canvas_container)
        canvas_layout.setContentsMargins(24, 16, 24, 18)
        canvas_layout.setSpacing(10)

        workspace_header = QHBoxLayout()
        workspace_header.setContentsMargins(2, 0, 2, 0)
        workspace_header.setSpacing(8)
        header_text = QVBoxLayout()
        header_text.setContentsMargins(0, 0, 0, 0)
        header_text.setSpacing(1)
        self.workspace_title_label = QLabel("")
        self.workspace_title_label.setObjectName("workspaceTitle")
        self.workspace_scope_label = QLabel("")
        self.workspace_scope_label.setObjectName("workspaceScope")
        header_text.addWidget(self.workspace_title_label)
        header_text.addWidget(self.workspace_scope_label)
        workspace_header.addLayout(header_text)
        workspace_header.addStretch()
        self.header_export_btn = QPushButton("Export")
        self.header_export_btn.setObjectName("workspaceActionBtn")
        self.header_export_btn.setCursor(Qt.PointingHandCursor)
        self.header_export_btn.setVisible(False)
        self.header_export_btn.clicked.connect(self._on_export_result_clicked)
        workspace_header.addWidget(self.header_export_btn)
        canvas_layout.addLayout(workspace_header)

        self.result_output = AnalysisResultPanel()
        self.result_output.setObjectName("resultOutput")
        self.result_output.clear()

        self.code_editor = QPlainTextEdit()
        self.code_editor.setObjectName("codeEditor")
        self.code_editor.setPlaceholderText(
            "Generated Python code appears here and can be edited before Apply."
        )
        self.code_editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.code_editor.setTabStopDistance(
            4 * self.code_editor.fontMetrics().horizontalAdvance(" ")
        )
        self.code_editor.textChanged.connect(self._on_code_text_changed)

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
        self.code_apply_btn = QPushButton("Apply")
        self.code_apply_btn.setObjectName("codeApplyBtn")
        self.code_apply_btn.setCursor(Qt.PointingHandCursor)
        self.code_apply_btn.setVisible(False)
        self.code_apply_btn.clicked.connect(self._on_apply_clicked)
        code_header.addWidget(code_label)
        code_header.addStretch()
        code_header.addWidget(self.code_reset_btn)
        code_header.addWidget(self.code_apply_btn)

        code_panel_layout.addLayout(code_header)
        self.analysis_plan_label = QLabel()
        self.analysis_plan_label.setObjectName("analysisPlanLabel")
        self.analysis_plan_label.setWordWrap(True)
        self.analysis_plan_label.setVisible(False)
        code_panel_layout.addWidget(self.analysis_plan_label)
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

        self.activity_strip = QFrame()
        self.activity_strip.setObjectName("activityStrip")
        activity_layout = QHBoxLayout(self.activity_strip)
        activity_layout.setContentsMargins(12, 7, 12, 7)
        activity_layout.setSpacing(10)
        self.activity_label = QLabel("Working")
        self.activity_label.setObjectName("activityLabel")
        self.activity_progress = QProgressBar()
        self.activity_progress.setObjectName("activityProgress")
        self.activity_progress.setRange(0, 0)
        self.activity_progress.setTextVisible(False)
        self.activity_progress.setFixedHeight(4)
        self.activity_progress.setProperty("busyPulse", 0.0)
        activity_shadow = QGraphicsDropShadowEffect(self)
        activity_shadow.setBlurRadius(14)
        activity_shadow.setOffset(0, 0)
        activity_shadow.setColor(QColor(26, 115, 232, 0))
        self.activity_strip.setGraphicsEffect(activity_shadow)
        self._activity_shadow = activity_shadow
        activity_layout.addWidget(self.activity_label)
        activity_layout.addWidget(self.activity_progress, stretch=1)
        self.activity_strip.setVisible(False)

        canvas_layout.addWidget(self.activity_strip)
        canvas_layout.addWidget(self.canvas_stack)

        # =========================================================================
        # Command Bar
        # =========================================================================

        self.command_bar = QFrame(self.workspace)
        self.command_bar.setObjectName("commandBar")
        command_shadow = QGraphicsDropShadowEffect(self)
        command_shadow.setBlurRadius(18)
        command_shadow.setOffset(0, 5)
        command_shadow.setColor(QColor(15, 23, 42, 24))
        self.command_bar.setGraphicsEffect(command_shadow)

        command_layout = QHBoxLayout(self.command_bar)
        command_layout.setContentsMargins(14, 9, 12, 9)
        command_layout.setSpacing(10)

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
        self.prompt_count_label = QLabel("0 characters")
        self.prompt_count_label.setObjectName("promptCountLabel")
        suggestion_bar.addWidget(self.prompt_count_label)
        self.composer_close_btn = QPushButton("×")
        self.composer_close_btn.setObjectName("composerCloseBtn")
        self.composer_close_btn.setCursor(Qt.PointingHandCursor)
        self.composer_close_btn.setToolTip("Close question input")
        self.composer_close_btn.setFixedSize(26, 26)
        self.composer_close_btn.clicked.connect(self._collapse_composer)
        suggestion_bar.addWidget(self.composer_close_btn)

        self.prompt_input = QTextEdit()
        self.prompt_input.setObjectName("promptInput")
        self.prompt_input.setAcceptRichText(False)
        self.prompt_input.setLineWrapMode(QTextEdit.WidgetWidth)
        self.prompt_input.setPlaceholderText(
            "Ask a question about your data or request an analysis..."
        )
        self.prompt_input.setMinimumHeight(72)
        self.prompt_input.setMaximumHeight(168)
        self.prompt_input.textChanged.connect(self._on_prompt_text_changed)
        command_stack.addLayout(suggestion_bar)
        command_stack.addWidget(self.prompt_input)

        self.suggestion_popover = SuggestionPopover(self)
        self.suggestion_popover.suggestion_selected.connect(self._apply_suggestion)
        self.suggestion_popover.installEventFilter(self)
        self.overview_popover = OverviewPopover(self)
        self.experience_feedback = ExperienceFeedbackCard(self.workspace)
        self.experience_feedback.useful.connect(self._on_experience_useful)
        self.experience_feedback.dismissed.connect(self._on_experience_dismissed)

        self.run_btn = QPushButton("Analyze")
        self.run_btn.setObjectName("runBtn")
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.setFixedSize(100, 48)
        self.run_btn.clicked.connect(self._on_analyze_clicked)

        command_layout.addLayout(command_stack, stretch=1)
        command_layout.addWidget(self.run_btn, alignment=Qt.AlignVCenter)

        workspace_layout.addWidget(self.canvas_container, stretch=1)

        self.activity_drawer = QFrame()
        self.activity_drawer.setObjectName("activityDrawer")
        activity_drawer_layout = QVBoxLayout(self.activity_drawer)
        activity_drawer_layout.setContentsMargins(0, 0, 0, 0)
        activity_drawer_layout.setSpacing(0)
        self.activity_toggle_btn = QPushButton("Activity")
        self.activity_toggle_btn.setObjectName("activityToggleBtn")
        self.activity_toggle_btn.setCursor(Qt.PointingHandCursor)
        self.activity_toggle_btn.setFixedHeight(26)
        self.activity_toggle_btn.clicked.connect(self._toggle_activity_drawer)
        self.log_output = QTextEdit()
        self.log_output.setObjectName("logOutput")
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(150)
        self.log_output.setVisible(False)
        activity_drawer_layout.addWidget(self.activity_toggle_btn)
        activity_drawer_layout.addWidget(self.log_output)
        workspace_layout.addWidget(self.activity_drawer)

        self.composer_status_btn = QPushButton("Ask another question", self.workspace)
        self.composer_status_btn.setObjectName("composerToggleBtn")
        self.composer_status_btn.setFixedSize(158, 40)
        self.composer_status_btn.setCursor(Qt.PointingHandCursor)
        self.composer_status_btn.setToolTip("Open question input")
        self.composer_status_btn.setVisible(False)
        self.composer_status_btn.clicked.connect(self._toggle_composer)
        self.workspace.installEventFilter(self)

        # =========================================================================
        # Page Stack & Splitter Assembly
        # =========================================================================

        self.page_container = QStackedWidget()
        self.history_page = HistoryPage()
        self.cleaning_page = CleaningPage()
        self.metric_page = MetricDiscoveryPage()

        self.page_container.addWidget(self.workspace)
        self.page_container.addWidget(self.history_page)
        self.page_container.addWidget(self.cleaning_page)
        self.page_container.addWidget(self.metric_page)

        self.main_splitter.addWidget(self.page_container)
        self.main_splitter.setCollapsible(0, False)

        self.history_btn.clicked.connect(self._show_history_page)
        self.nav_analysis_btn.clicked.connect(self._show_analysis_context)
        self.nav_clean_btn.clicked.connect(self._show_cleaning_page)
        self.nav_metric_btn.clicked.connect(self._show_metric_page)
        self.context_close_btn.clicked.connect(self._close_context_panel)
        self.history_page.btn_back.clicked.connect(lambda: self.page_container.setCurrentIndex(0))
        self.history_page.task_open_requested.connect(self._open_history_task)
        self.cleaning_page.profile_requested.connect(self._start_cleaning_profile)
        self.cleaning_page.execute_requested.connect(self._start_cleaning_execution)
        self.cleaning_page.cancel_requested.connect(self._cancel_cleaning)
        self.metric_page.analysis_requested.connect(
            self._start_metric_discovery
        )
        self.metric_page.cancel_requested.connect(self._cancel_metric_discovery)
        self.settings_btn.clicked.connect(self._on_settings_clicked)
        self.dataset_list.currentItemChanged.connect(self._on_dataset_selection_changed)
        app_surface.installEventFilter(self)

        self._apply_style()
        self._refresh_api_status()
        self._refresh_overview_ui()
        self._show_start_page()
        QTimer.singleShot(0, self._position_floating_composer)
        QTimer.singleShot(0, self._position_experience_feedback)

    def _make_title_menu_button(self, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("titleMenuBtn")
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedHeight(26)
        return button

    def _build_title_menus(self) -> None:
        file_menu = QMenu(self)
        self.new_analysis_action = QAction("New Analysis", self)
        self.new_analysis_action.setShortcut(QKeySequence("Ctrl+N"))
        self.new_analysis_action.triggered.connect(self._request_new_analysis)
        add_action = QAction("Add Dataset...", self)
        add_action.setShortcut(QKeySequence("Ctrl+O"))
        add_action.triggered.connect(self._on_upload_clicked)
        self.export_result_action = QAction("Export Result...", self)
        self.export_result_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.export_result_action.setEnabled(False)
        self.export_result_action.triggered.connect(self._on_export_result_clicked)
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(self.new_analysis_action)
        file_menu.addAction(add_action)
        file_menu.addAction(self.export_result_action)
        file_menu.addSeparator()
        file_menu.addAction(exit_action)
        self.file_menu_btn.setMenu(file_menu)

        view_menu = QMenu(self)
        self.view_context_action = QAction("Dataset Library", self)
        self.view_context_action.setShortcut(QKeySequence("Ctrl+B"))
        self.view_context_action.triggered.connect(self._toggle_context_panel)
        self.view_activity_action = QAction("Activity", self)
        self.view_activity_action.setShortcut(QKeySequence("Ctrl+J"))
        self.view_activity_action.triggered.connect(self._toggle_activity_drawer)
        view_menu.addAction(self.view_context_action)
        view_menu.addAction(self.view_activity_action)
        self.view_menu_btn.setMenu(view_menu)

        help_menu = QMenu(self)
        guide_action = QAction("Quick Guide", self)
        guide_action.triggered.connect(self._show_quick_guide)
        about_action = QAction("About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(guide_action)
        help_menu.addSeparator()
        help_menu.addAction(about_action)
        self.help_menu_btn.setMenu(help_menu)

    def _show_quick_guide(self) -> None:
        QMessageBox.information(
            self,
            "Quick Guide",
            "1. Add datasets to the shared Dataset Library.\n"
            "2. For analysis, select up to three datasets and ask a question.\n"
            "3. For cleaning, choose one dataset from the same library.\n"
            "4. Review generated analysis code when needed, then Apply.\n\n"
            "Dataset metadata and the request are sent to Dify. "
            "The full dataset is analyzed locally.",
        )

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About",
            "EY Data Analysis Assistant\n"
            "Dify-guided analysis with auditable local Python execution.",
        )

    def _request_new_analysis(self) -> None:
        has_work = bool(
            self._generated_code
            or self._current_analysis_result
            or self.prompt_input.toPlainText().strip()
        )
        if self._task_open and has_work:
            choice = QMessageBox.question(
                self,
                "New Analysis",
                "Start a new analysis?\n\n"
                "The current session will remain available in History.",
                QMessageBox.Cancel | QMessageBox.Yes,
                QMessageBox.Cancel,
            )
            if choice != QMessageBox.Yes:
                return
        self._start_new_task()

    def _show_code_workspace(self) -> None:
        if not self.analysis_tabs.tabBar().isTabVisible(self.python_tab_index):
            return
        self.page_container.setCurrentIndex(0)
        self.analysis_tabs.setCurrentIndex(self.python_tab_index)

    def _make_nav_button(
        self,
        icon_role: QStyle.StandardPixmap,
        tooltip: str,
    ) -> QPushButton:
        button = QPushButton()
        button.setIcon(self.style().standardIcon(icon_role))
        button.setIconSize(QSize(16, 16))
        button.setObjectName("navigationRailButton")
        button.setFixedSize(36, 36)
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(tooltip)
        return button

    def _show_analysis_context(self) -> None:
        self.page_container.setCurrentIndex(0)
        self._toggle_context_panel()

    def _show_analysis_workspace(self) -> None:
        if not self._task_open:
            self._start_new_task()
            return
        self.app_stack.setCurrentIndex(1)
        self._show_mode_page(self.workspace)
        self._set_active_mode("analysis")
        self._set_task_title()
        self.nav_clean_btn.setProperty("active", False)
        self.nav_clean_btn.style().unpolish(self.nav_clean_btn)
        self.nav_clean_btn.style().polish(self.nav_clean_btn)
        QTimer.singleShot(0, self._position_floating_composer)
        QTimer.singleShot(0, self._position_experience_feedback)

    def _show_cleaning_page(self) -> None:
        self.app_stack.setCurrentIndex(1)
        self._set_task_controls_enabled(True)
        self._set_active_mode("cleaning")
        self._show_mode_page(self.cleaning_page)
        self._close_context_panel()
        self._set_task_title()
        self.nav_clean_btn.setProperty("active", True)
        self.nav_clean_btn.style().unpolish(self.nav_clean_btn)
        self.nav_clean_btn.style().polish(self.nav_clean_btn)

    def _show_metric_page(self) -> None:
        self.app_stack.setCurrentIndex(1)
        self._set_task_controls_enabled(True)
        self._set_active_mode("metric")
        self._show_mode_page(self.metric_page)
        self._close_context_panel()
        self.task_title_label.setText("Business indicator discovery")
        self.task_title_label.setVisible(True)
        self.nav_metric_btn.setProperty("active", True)
        self.nav_metric_btn.style().unpolish(self.nav_metric_btn)
        self.nav_metric_btn.style().polish(self.nav_metric_btn)

    def _show_mode_page(self, page: QWidget) -> None:
        current = self.page_container.currentWidget()
        self.page_container.setCurrentWidget(page)
        if current is page:
            return
        previous = getattr(self, "_mode_transition_animation", None)
        if previous is not None:
            previous.stop()
        end_position = page.pos()
        animation = QPropertyAnimation(page, b"pos", self)
        animation.setDuration(160)
        animation.setStartValue(end_position + QPoint(12, 0))
        animation.setEndValue(end_position)
        animation.setEasingCurve(QEasingCurve.OutCubic)

        def finish() -> None:
            page.move(end_position)
            self._mode_transition_animation = None

        animation.finished.connect(finish)
        self._mode_transition_animation = animation
        animation.start()

    def _start_metric_discovery(self, request) -> None:
        if self._metric_thread is not None:
            return
        thread = QThread(self)
        worker = MetricDiscoveryWorker(request)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.event.connect(self.metric_page.handle_event)
        worker.finished.connect(self._on_metric_discovery_finished)
        worker.error.connect(self._on_metric_discovery_failed)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_metric_discovery)
        self._metric_thread = thread
        self._metric_worker = worker
        thread.start()

    def _on_metric_discovery_finished(self, result) -> None:
        self.metric_page.show_result(result)
        self.log_output.append(
            f"Business indicator generation completed: "
            f"{len(result.indicators)} indicator(s)."
        )

    def _on_metric_discovery_failed(self, error: str) -> None:
        self.metric_page.show_error(error)
        self.log_output.append(f"Business indicator generation failed: {error}")

    def _cancel_metric_discovery(self) -> None:
        if self._metric_worker is None:
            return
        self._metric_worker.cancel()
        self.metric_page.cancel_button.setEnabled(False)
        self.metric_page.busy_label.setText("正在取消本次生成")

    def _cleanup_metric_discovery(self) -> None:
        self._metric_thread = None
        self._metric_worker = None

    def _toggle_context_panel(self) -> None:
        if self._context_panel_open:
            self._close_context_panel()
            return
        self._context_panel_open = True
        self._set_context_click_guard_enabled(True)
        self._animate_context_panel(True)

    def _close_context_panel(self) -> None:
        self._set_context_click_guard_enabled(False)
        self._context_panel_open = False
        self.overview_popover.hide()
        self._animate_context_panel(False)

    def _set_context_click_guard_enabled(self, enabled: bool) -> None:
        if self._context_click_guard_active == enabled:
            return
        app = QApplication.instance()
        if app is None:
            return
        if enabled:
            app.installEventFilter(self)
        else:
            app.removeEventFilter(self)
        self._context_click_guard_active = enabled

    def _animate_context_panel(self, opening: bool) -> None:
        if self._context_animation is not None:
            self._context_animation.stop()
        self._position_dataset_overlay()
        open_pos = self.left_shell.pos()
        closed_pos = QPoint(self.app_surface.width() + 18, open_pos.y())
        if opening:
            self.left_shell.move(closed_pos)
            self.left_shell.show()
            self.left_shell.raise_()
        animation = QPropertyAnimation(self.left_shell, b"pos", self)
        animation.setStartValue(self.left_shell.pos())
        animation.setEndValue(open_pos if opening else closed_pos)
        animation.setDuration(240)
        animation.setEasingCurve(QEasingCurve.OutCubic)

        def finish() -> None:
            if not opening:
                self.left_shell.hide()
            self._context_animation = None

        animation.finished.connect(finish)
        self._context_animation = animation
        animation.start()

    def _position_dataset_overlay(self) -> None:
        if not hasattr(self, "app_surface"):
            return
        height = max(360, self.app_surface.height() - self.title_bar.height() - 24)
        self.left_shell.setFixedHeight(height)
        self.left_shell.move(
            max(12, self.app_surface.width() - self.left_shell.width() - 16),
            self.title_bar.height() + 10,
        )

    def _toggle_activity_drawer(self) -> None:
        expanded = not self.log_output.isVisible()
        self.log_output.setVisible(expanded)
        self.activity_toggle_btn.setText(
            "Activity  ▾" if expanded else "Activity"
        )
        QTimer.singleShot(0, self._position_floating_composer)

    def _expanded_composer_rect(self) -> QRect:
        width = min(760, max(460, self.workspace.width() - 96))
        height = max(132, min(236, self.command_bar.sizeHint().height()))
        bottom_gap = self.activity_drawer.sizeHint().height() + 16
        return QRect(
            max(24, (self.workspace.width() - width) // 2),
            max(18, self.workspace.height() - height - bottom_gap),
            width,
            height,
        )

    def _collapsed_composer_rect(self) -> QRect:
        width = 158
        height = 40
        bottom_gap = self.activity_drawer.sizeHint().height() + 16
        return QRect(
            max(24, (self.workspace.width() - width) // 2),
            max(18, self.workspace.height() - height - bottom_gap),
            width,
            height,
        )

    def _position_floating_composer(self) -> None:
        if not hasattr(self, "command_bar"):
            return
        if self._composer_animation is not None:
            self._composer_animation.stop()
        if self._composer_collapsed:
            self.command_bar.hide()
            self.composer_status_btn.setGeometry(self._collapsed_composer_rect())
            self.composer_status_btn.show()
            self.composer_status_btn.raise_()
        else:
            self.composer_status_btn.hide()
            self.command_bar.show()
            self.command_bar.setGeometry(self._expanded_composer_rect())
            self.command_bar.raise_()

    def _position_experience_feedback(self) -> None:
        if not hasattr(self, "experience_feedback"):
            return
        width = min(340, max(280, self.workspace.width() - 32))
        height = 126
        x = max(16, self.workspace.width() - width - 22)
        y = 58
        self.experience_feedback.setFixedSize(width, height)
        self.experience_feedback.update_target_geometry(
            QRect(x, y, width, height)
        )

    def _animate_composer(self, target: QRect, finished) -> None:
        if self._composer_animation is not None:
            self._composer_animation.stop()
        animation = QPropertyAnimation(self.command_bar, b"geometry", self)
        animation.setDuration(210)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.setStartValue(self.command_bar.geometry())
        animation.setEndValue(target)
        animation.finished.connect(finished)
        self._composer_animation = animation
        animation.start()

    def _collapse_composer(self, state: str = "ready") -> None:
        if self._composer_collapsed:
            self._set_composer_state(state)
            return
        self._composer_collapsed = True
        self._set_composer_state(state)

        def finish() -> None:
            self.command_bar.hide()
            self.composer_status_btn.setGeometry(self._collapsed_composer_rect())
            self.composer_status_btn.show()
            self.composer_status_btn.raise_()

        self._animate_composer(self._collapsed_composer_rect(), finish)

    def _expand_composer(self, pin: bool = False) -> None:
        del pin
        if not self._composer_collapsed:
            self.command_bar.raise_()
            return
        self._composer_collapsed = False
        self.composer_status_btn.hide()
        self.command_bar.setGeometry(self._collapsed_composer_rect())
        self.command_bar.show()
        self.command_bar.raise_()
        self._animate_composer(self._expanded_composer_rect(), lambda: None)

    def _toggle_composer(self) -> None:
        if self._composer_collapsed:
            self._expand_composer()
            self.prompt_input.setFocus()
        else:
            self._collapse_composer()

    def _set_composer_state(self, state: str) -> None:
        states = {
            "busy": ("Analysis is running", "Analysis is running"),
            "code": ("Ask another question", "Open question input"),
            "done": ("Ask another question", "Open question input"),
            "error": ("Revise question", "Open question input"),
            "ready": ("Ask a question", "Open question input"),
        }
        label, tooltip = states.get(state, states["ready"])
        self.composer_status_btn.setText(label)
        self.composer_status_btn.setToolTip(tooltip)
        self.composer_status_btn.setProperty("state", state)
        self.composer_status_btn.style().unpolish(self.composer_status_btn)
        self.composer_status_btn.style().polish(self.composer_status_btn)

    def _on_upload_clicked(self):
        """Queue spreadsheet import and profiling off the UI thread."""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Excel Files",
            "",
            "Excel Files (*.xlsx *.xls *.xlsm);;All Files (*)"
        )
        
        if not files:
            return
        self._queue_dataset_files(files)

    def _queue_dataset_files(self, files: list[str]) -> None:
        from pathlib import Path

        if self._import_thread is not None:
            QMessageBox.information(
                self,
                "Import in progress",
                "Wait for the current import to finish before adding more files.",
            )
            return

        validation_errors = []
        resolved_files = []
        for file_path in files:
            path = Path(file_path)
            if path.suffix.lower() not in SUPPORTED_DATASET_SUFFIXES:
                validation_errors.append(
                    f"• {path.name}: unsupported file type "
                    "(use .xlsx, .xls, or .xlsm)"
                )
                continue
            try:
                size_bytes = path.stat().st_size
            except OSError as exc:
                validation_errors.append(
                    f"• {path.name}: file cannot be accessed ({exc})"
                )
                continue
            if size_bytes > settings.MAX_DATASET_BYTES:
                validation_errors.append(
                    f"• {path.name}: exceeds the 1 GB per-file limit"
                )
                continue
            resolved_files.append((path, str(path.resolve())))

        if validation_errors:
            message = (
                "Nothing was imported because this selection contains "
                "unsupported files:\n\n"
                + "\n".join(validation_errors)
            )
            QMessageBox.warning(self, "Files cannot be imported", message)
            self.log_output.append(message.replace("\n", " "))
            return

        accepted = []
        for path, resolved_path in resolved_files:
            known_paths = {
                str(state.get("file_path"))
                for state in self._dataset_states.values()
            } | {meta.file_path for meta in self.loaded_files.values()}
            if resolved_path in known_paths:
                self.log_output.append(
                    f"Please do not add the same file again: {path.name}"
                )
                continue
            display_name = self._dataset_display_name_for_all(path.name)
            self._dataset_states[display_name] = {
                "state": "queued",
                "file_path": resolved_path,
                "percent": 0,
            }
            self._add_dataset_item(display_name, selected=False)
            row_widget = self._dataset_row_widgets[display_name]
            row_widget.setDatasetState("Queued for profiling")
            row_widget.setSelectionEnabled(
                False,
                "Available after profiling completes.",
            )
            accepted.append(resolved_path)

        if not accepted:
            return
        self._refresh_global_dataset_surfaces()
        self._start_import_worker(accepted)
        self.log_output.append(
            f"Queued {len(accepted)} dataset(s) for background profiling."
        )

    def _start_import_worker(self, file_paths: list[str]) -> None:
        thread = QThread(self)
        worker = ImportWorker(file_paths)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_import_progress)
        worker.file_finished.connect(self._on_import_file_finished)
        worker.file_failed.connect(self._on_import_file_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_import_worker)
        self._import_thread = thread
        self._import_worker = worker
        thread.start()

    def _dataset_name_for_path(self, file_path: str) -> str | None:
        from pathlib import Path

        resolved = str(Path(file_path).resolve())
        for name, state in self._dataset_states.items():
            if state.get("file_path") == resolved:
                return name
        return None

    def _on_import_progress(self, file_path: str, event: dict) -> None:
        name = self._dataset_name_for_path(file_path)
        if not name:
            return
        stage = str(event.get("stage") or "profiling")
        percent = int(event.get("percent") or 0)
        self._dataset_states[name].update(state=stage, percent=percent)
        label = {
            "inspecting": "Inspecting",
            "importing": "Caching",
            "profiling": "Profiling",
            "ready": "Ready",
        }.get(stage, stage.title())
        self._dataset_row_widgets[name].setDatasetState(
            f"{label} · {percent}%"
        )
        self._set_activity_message(f"{label} {name} ({percent}%)", progress=percent)
        self.activity_strip.setVisible(True)
        self.start_page.set_import_progress(f"{label} {name}", percent)

    def _on_import_file_finished(self, file_path: str, file_meta) -> None:
        name = self._dataset_name_for_path(file_path)
        if not name:
            return
        file_meta.display_name = name
        self.loaded_files[name] = file_meta
        self._dataset_states[name].update(state="ready", percent=100)
        rows = sum(sheet.rows for sheet in file_meta.sheets)
        row_widget = self._dataset_row_widgets[name]
        row_widget.setDatasetState(
            f"Sampled profile · {rows:,} rows"
            if file_meta.profile_mode == "sampled"
            else f"{file_meta.file_size_kb / 1024:.1f} MB · {rows:,} rows"
        )
        selection_limit = (
            1 if self._active_mode == "cleaning" else settings.MAX_SELECTED_DATASETS
        )
        if len(self._selected_datasets) < selection_limit:
            self._set_dataset_analysis_selected(name, True)
        self._ensure_dataset_overview(name, force=False)
        self.log_output.append(f"Loaded in background: {name}")
        if self.dataset_list.currentRow() < 0:
            self.dataset_list.setCurrentItem(self._find_dataset_item(name))
        self._refresh_dataset_selection_ui()
        self._refresh_global_dataset_surfaces()

    def _on_import_file_failed(self, file_path: str, error: str) -> None:
        name = self._dataset_name_for_path(file_path)
        if not name:
            return
        cancelled = "cancelled" in str(error).lower()
        self._dataset_states[name].update(
            state="cancelled" if cancelled else "failed",
            error=error,
        )
        row_widget = self._dataset_row_widgets[name]
        row_widget.setDatasetState("Import cancelled" if cancelled else "Import failed")
        row_widget.setSelectionEnabled(False, error)
        self.log_output.append(
            f"{'Cancelled' if cancelled else 'Error loading'} {name}: {error}"
        )
        self._refresh_global_dataset_surfaces()

    def _cleanup_import_worker(self) -> None:
        self._import_thread = None
        self._import_worker = None
        if self._analysis_thread is None:
            self.activity_strip.setVisible(False)
        self._refresh_global_dataset_surfaces()

    def _on_dataset_selection_changed(self, current, previous) -> None:
        del previous
        current_name = current.text() if current else None
        self._sync_dataset_row_selection(current_name)
        self._refresh_overview_ui(current_name)
        if current_name:
            self._ensure_dataset_overview(current_name, force=False)

    @staticmethod
    def _is_widget_or_child(widget: QWidget | None, ancestor: QWidget | None) -> bool:
        if widget is None or ancestor is None:
            return False
        current = widget
        while current is not None:
            if current is ancestor:
                return True
            current = current.parentWidget()
        return False

    @staticmethod
    def _contains_global_point(widget: QWidget | None, point: QPoint) -> bool:
        if widget is None or not widget.isVisible():
            return False
        top_left = widget.mapToGlobal(QPoint(0, 0))
        return QRect(top_left, widget.size()).contains(point)

    def _maybe_close_context_panel_from_click(self, watched, event) -> None:
        if not self._context_panel_open:
            return
        if event.type() != QEvent.MouseButtonPress:
            return
        if hasattr(event, "button") and event.button() != Qt.LeftButton:
            return

        clicked_widget = (
            watched if isinstance(watched, QWidget)
            else QApplication.widgetAt(event.globalPosition().toPoint())
        )
        global_pos = event.globalPosition().toPoint()
        if clicked_widget is None or clicked_widget.window() is not self:
            return
        protected_widgets = (
            self.left_shell,
            self.dataset_library_btn,
            getattr(self.start_page, "library_button", None),
            self.overview_popover,
        )
        if any(
            self._is_widget_or_child(clicked_widget, protected)
            for protected in protected_widgets
        ):
            return
        if any(
            self._contains_global_point(protected, global_pos)
            for protected in protected_widgets
        ):
            return
        self._close_context_panel()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonPress:
            self._maybe_close_context_panel_from_click(watched, event)

        workspace = getattr(self, "workspace", None)
        workspace_root = getattr(self, "workspace_root", None)
        app_surface = getattr(self, "app_surface", None)
        if watched is workspace and event.type() == QEvent.Resize:
            QTimer.singleShot(0, self._position_floating_composer)
            QTimer.singleShot(0, self._position_experience_feedback)
        elif watched is workspace_root and event.type() == QEvent.Resize:
            QTimer.singleShot(0, self._position_dataset_overlay)
        elif watched is app_surface and event.type() == QEvent.Resize:
            QTimer.singleShot(0, self._position_dataset_overlay)
        elif watched is self.suggestion_btn:
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

    def _add_dataset_item(
        self,
        dataset_name: str,
        *,
        selected: bool = True,
    ) -> None:
        from PySide6.QtWidgets import QListWidgetItem

        item = QListWidgetItem()
        item.setText(dataset_name)
        item.setSizeHint(QSize(0, 58))
        self.dataset_list.addItem(item)

        row_widget = DatasetRowWidget(dataset_name, self.dataset_list)
        row_widget.activated.connect(self._on_dataset_row_activated)
        row_widget.overview_requested.connect(self._show_overview_for_dataset)
        row_widget.delete_requested.connect(self._remove_dataset)
        row_widget.selection_changed.connect(
            self._on_dataset_analysis_selection_changed
        )
        row_widget.setAnalysisSelected(selected)
        self.dataset_list.setItemWidget(item, row_widget)
        self._dataset_row_widgets[dataset_name] = row_widget
        if selected:
            self._selected_datasets.add(dataset_name)
        self._refresh_dataset_selection_ui()
        self._sync_dataset_row_selection(self._current_dataset_name())

    def _on_dataset_analysis_selection_changed(
        self,
        dataset_name: str,
        selected: bool,
    ) -> None:
        if selected and dataset_name not in self.loaded_files:
            self._set_dataset_analysis_selected(dataset_name, False)
            return
        limit = 1 if self._active_mode == "cleaning" else settings.MAX_SELECTED_DATASETS
        if self._active_mode == "cleaning" and selected:
            for name in list(self._selected_datasets):
                if name != dataset_name:
                    self._set_dataset_analysis_selected(name, False)
        if (
            selected
            and dataset_name not in self._selected_datasets
            and len(self._selected_datasets) >= limit
        ):
            self._set_dataset_analysis_selected(dataset_name, False)
            self.log_output.append(
                (
                    "Data cleaning can use one target dataset."
                    if self._active_mode == "cleaning"
                    else "Each analysis can use at most 3 datasets."
                )
            )
            return
        self._set_dataset_analysis_selected(dataset_name, selected)
        self._refresh_dataset_selection_ui()
        self._sync_cleaning_target()

    def _on_dataset_row_activated(self, dataset_name: str) -> None:
        self._select_dataset_by_name(dataset_name)
        if dataset_name not in self.loaded_files:
            return
        if self._active_mode == "cleaning":
            self._on_dataset_analysis_selection_changed(dataset_name, True)
        else:
            self._on_dataset_analysis_selection_changed(
                dataset_name,
                dataset_name not in self._selected_datasets,
            )

    def _set_dataset_analysis_selected(
        self,
        dataset_name: str,
        selected: bool,
    ) -> None:
        widget = self._dataset_row_widgets.get(dataset_name)
        if widget is not None:
            widget.setAnalysisSelected(selected)
        if selected:
            self._selected_datasets.add(dataset_name)
        else:
            self._selected_datasets.discard(dataset_name)

    def _refresh_dataset_selection_ui(self) -> None:
        if not hasattr(self, "dataset_selection_label"):
            return
        count = len(self._selected_datasets)
        limit = 1 if self._active_mode == "cleaning" else settings.MAX_SELECTED_DATASETS
        self.dataset_selection_label.setText(
            (
                f"Cleaning target: {count} of 1 selected"
                if self._active_mode == "cleaning"
                else f"Analysis scope: {count} of {settings.MAX_SELECTED_DATASETS} selected"
            )
        )
        at_limit = count >= limit
        for name, widget in self._dataset_row_widgets.items():
            ready = name in self.loaded_files
            selected = name in self._selected_datasets
            widget.setAnalysisSelected(selected)
            widget.setSelectionEnabled(
                ready and (
                    self._active_mode == "cleaning"
                    or selected
                    or not at_limit
                ),
                (
                    (
                        "Select another row to replace the cleaning target."
                        if self._active_mode == "cleaning"
                        else "Each analysis can use at most 3 datasets."
                    )
                    if ready and at_limit and not selected
                    else "Include this dataset in analysis"
                ),
            )

    def _selected_files_meta(self) -> list:
        return [
            self.loaded_files[name]
            for name in self.loaded_files
            if name in self._selected_datasets
        ]

    @staticmethod
    def _uses_background_analysis(files_meta: list) -> bool:
        return any(
            file_meta.file_size_kb >= settings.BACKGROUND_ANALYSIS_MB * 1024
            or sum(sheet.rows for sheet in file_meta.sheets)
            >= settings.BACKGROUND_ANALYSIS_ROWS
            for file_meta in files_meta
        )

    def _remove_dataset(self, dataset_name: str) -> None:
        item = self._find_dataset_item(dataset_name)
        if item is None:
            return
        if dataset_name not in self.loaded_files:
            self._dataset_states.pop(dataset_name, None)
            self._selected_datasets.discard(dataset_name)
            row_widget = self._dataset_row_widgets.pop(dataset_name, None)
            self.dataset_list.takeItem(self.dataset_list.row(item))
            if row_widget is not None:
                row_widget.deleteLater()
            self._refresh_dataset_selection_ui()
            self._refresh_global_dataset_surfaces()
            return

        removed_meta = self.loaded_files.pop(dataset_name)
        self._selected_datasets.discard(dataset_name)
        self._dataset_states.pop(dataset_name, None)
        self._dataset_overviews.pop(dataset_name, None)
        row_widget = self._dataset_row_widgets.pop(dataset_name, None)

        if (
            self._overview_loading_dataset == dataset_name
            and self._overview_loading_meta is removed_meta
            and self._overview_worker is not None
        ):
            self._overview_worker.cancel()

        row = self.dataset_list.row(item)
        self.dataset_list.takeItem(row)
        if row_widget is not None:
            row_widget.deleteLater()

        if self._pending_files_meta:
            self._pending_files_meta = [
                meta
                for meta in self._pending_files_meta
                if meta.file_path != removed_meta.file_path
            ] or None
            if self._pending_files_meta is None:
                self._pending_query = None
                self._generated_code = ""
                self._analysis_plan = {}
                self._current_analysis_result = None
                self._refresh_result_export_state()
                self._verified_code = ""
                self._verified_execution = None
                self._render_analysis_plan()
                self.code_editor.clear()
                self._set_python_tab_visible(False)
                self._show_analyze_action()

        self.overview_popover.hide()
        self._hide_suggestion_popover()

        if self.dataset_list.count():
            next_row = min(row, self.dataset_list.count() - 1)
            self.dataset_list.setCurrentRow(next_row)
        else:
            self.dataset_list.setCurrentRow(-1)
            self.result_output.set_empty_state("Add a dataset to continue.")

        self._sync_dataset_row_selection(self._current_dataset_name())
        self._refresh_overview_ui()
        self.log_output.append(f"Removed dataset: {dataset_name}")
        self._refresh_dataset_selection_ui()
        self._refresh_global_dataset_surfaces()

    def _refresh_global_dataset_surfaces(self) -> None:
        names = list(self.loaded_files)
        count = len(names)
        pending = sum(
            1
            for state in self._dataset_states.values()
            if state.get("state") not in {"ready", "failed", "cancelled"}
        )
        self.start_page.set_library_state(count, pending)
        self.dataset_library_btn.setText(f"Datasets · {count + pending}")
        self._sync_mode_selector_state()
        self.new_analysis_action.setEnabled(count > 0)
        self._sync_cleaning_target()
        self._refresh_workspace_header()
        if (
            self._task_open
            and self._active_mode == "analysis"
            and self._current_analysis_result is None
        ):
            if count == 0:
                self.result_output.set_empty_state("Add a dataset to continue.")
            elif not self._generated_code and self._analysis_thread is None:
                self.result_output.set_empty_state(
                    "Enter a question to analyze the selected datasets."
                )

    def _sync_cleaning_target(self) -> None:
        target = next(
            (name for name in self.loaded_files if name in self._selected_datasets),
            None,
        )
        self.cleaning_page.set_target_dataset(target)

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
            if (
                self._overview_loading_dataset == dataset_name
                and self._overview_loading_meta is file_meta
            ):
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
        self._overview_loading_meta = file_meta
        thread.start()

    def _on_overview_event(self, event: dict) -> None:
        message = str(event.get("message", ""))
        if message and event.get("type") == "status":
            self.log_output.append(message)

    def _on_overview_finished(self, result) -> None:
        dataset_name = self._overview_loading_dataset
        current_meta = self.loaded_files.get(dataset_name) if dataset_name else None
        if (
            dataset_name is not None
            and current_meta is self._overview_loading_meta
        ):
            data = result.overview_result or {}
            self._dataset_overviews[dataset_name] = {
                "state": "ready" if result.success and data else "error",
                "data": data if result.success else {},
                "error": result.error,
            }
            if result.error:
                self.log_output.append(f"Overview detail: {result.error}")
        self._refresh_overview_ui(dataset_name)

    def _on_overview_error(self, error: str) -> None:
        dataset_name = self._overview_loading_dataset
        current_meta = self.loaded_files.get(dataset_name) if dataset_name else None
        if (
            dataset_name is not None
            and current_meta is self._overview_loading_meta
        ):
            self._dataset_overviews[dataset_name] = {
                "state": "error",
                "data": {},
                "error": error,
            }
        if current_meta is self._overview_loading_meta:
            self.log_output.append(f"Overview detail: {error}")
        self._refresh_overview_ui(dataset_name)

    def _cleanup_overview_worker(self) -> None:
        self._overview_thread = None
        self._overview_worker = None
        self._overview_loading_dataset = None
        self._overview_loading_meta = None
        self._refresh_overview_ui()
        for queued_name, queued_state in self._dataset_overviews.items():
            if (queued_state or {}).get("state") == "queued":
                self._ensure_dataset_overview(queued_name, force=True)
                break

    def _refresh_overview_ui(self, dataset_name: str | None = None) -> None:
        self._refresh_workspace_header()
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
                row_widget.setRetry("Retry dataset overview")
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

    def _refresh_workspace_header(self) -> None:
        if not hasattr(self, "workspace_scope_label"):
            return
        count = len(self.loaded_files)
        if count == 0:
            scope = ""
        elif count == 1:
            scope = next(iter(self.loaded_files))
        else:
            scope = f"{count} datasets in analysis context"
        self.workspace_scope_label.setText(scope)
        self.workspace_scope_label.setVisible(bool(scope))

        if count == 0 or (
            self._pending_files_meta is None
            and self._current_analysis_result is None
        ):
            self.workspace_title_label.clear()
            self.workspace_title_label.setVisible(False)
            return

        task = self._find_history_task(self._active_task_id)
        query = str((task or {}).get("query") or "").strip()
        if query:
            compact = query if len(query) <= 72 else query[:69] + "..."
            self.workspace_title_label.setText(compact)
        else:
            self.workspace_title_label.clear()
        self.workspace_title_label.setVisible(
            bool(self.workspace_title_label.text())
        )

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

    def _on_prompt_text_changed(self) -> None:
        length = len(self.prompt_input.toPlainText())
        self.prompt_count_label.setText(
            f"{length:,} character" if length == 1 else f"{length:,} characters"
        )
        document_height = self.prompt_input.document().size().height()
        target_height = max(72, min(168, int(document_height) + 24))
        self.prompt_input.setFixedHeight(target_height)
        QTimer.singleShot(0, self._position_floating_composer)

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
            f"概括 {metric} 的主要分布和变化特征。",
            f"比较不同 {dimension} 下的 {metric}。",
            "检查数据中的缺失值和异常记录。",
            "总结这个数据集中最重要的发现。",
        ]
        return suggestions

    def _on_analyze_clicked(self):
        """Generate analysis code and prepare it for review/editing."""
        if not self._task_open:
            return

        query = self.prompt_input.toPlainText().strip()
        selected_files = self._selected_files_meta()
        if not selected_files:
            self.log_output.append("Select at least one ready dataset.")
            return

        if not query:
            self.log_output.append("Please enter an analysis question.")
            return

        try:
            settings.reload()
            settings.validate_selected_provider()
        except EnvironmentError as e:
            self.log_output.append(f"✗ API configuration error: {e}")
            self._refresh_api_status()
            return

        self._generated_code = ""
        self._analysis_plan = {}
        self._current_analysis_result = None
        self._refresh_result_export_state()
        self._verified_code = ""
        self._verified_execution = None
        self._last_applied_code = ""
        self._render_analysis_plan()
        self.code_editor.clear()
        self._set_python_tab_visible(False)
        self._show_analyze_action()
        self._pending_query = query
        self._pending_files_meta = selected_files
        selected_names = [
            name for name in self.loaded_files if name in self._selected_datasets
        ]
        dataset_label = ", ".join(selected_names)
        self._background_analysis_mode = self._uses_background_analysis(
            selected_files
        )
        self._create_history_task(dataset_label, query)
        self.log_output.append(
            f"Using mode: {self._current_model_label()}"
        )
        self.log_output.append(
            "Background analysis queued..."
            if self._background_analysis_mode
            else "Generating Python code..."
        )
        self.result_output.setText("Waiting for analysis result.")
        self._collapse_composer("busy")
        self._close_context_panel()
        self._run_generate()

    def _on_decision_made(self, option: OptionItem) -> None:
        """Resume analysis after the user resolves an ambiguous data plan."""
        self.canvas_stack.setCurrentIndex(0)
        clarification = option.description or option.label
        original_query = self._pending_query or self.prompt_input.toPlainText().strip()
        self._pending_query = (
            f"{original_query}\n\n"
            f"User clarification: {option.label}. {clarification}"
        ).strip()
        self.prompt_input.setPlainText(self._pending_query)
        self.log_output.append(f"Clarification selected: {option.label}")
        self._collapse_composer("busy")
        self._run_generate()

    def _on_decision_skipped(self) -> None:
        """Return to the prompt without guessing an ambiguous relationship."""
        self.canvas_stack.setCurrentIndex(0)
        self._expand_composer()
        self.log_output.append("Clarification cancelled.")

    def _on_settings_clicked(self) -> None:
        dialog = ApiSettingsDialog(self)
        dialog.settings_saved.connect(self._refresh_api_status)
        if dialog.exec():
            self.log_output.append(
                f"Settings saved for {self._current_model_label()} mode."
            )
            self._refresh_api_status()

    def _show_start_page(self) -> None:
        self._dismiss_experience_prompt(record=True)
        self._task_open = False
        self._active_task_id = None
        self.app_stack.setCurrentIndex(0)
        self._set_active_mode("")
        self.mode_button.setVisible(False)
        self.dataset_library_btn.setVisible(False)
        self.view_context_action.setEnabled(False)
        self._refresh_global_dataset_surfaces()
        self._set_python_tab_visible(False)
        self._refresh_overview_ui(None)
        self._set_task_title()
        self._set_task_controls_enabled(False)

    def _start_new_task(self) -> None:
        if self._analysis_thread is not None:
            return

        self._dismiss_experience_prompt(record=True)
        active_task = self._find_history_task(self._active_task_id)
        if active_task and not active_task.get("finished"):
            self._update_history_task("Closed", "Started over", finished=True)

        self._refresh_dataset_selection_ui()
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
        self._last_applied_code = ""
        self._analysis_plan = {}
        self._current_analysis_result = None
        self._verified_code = ""
        self._verified_execution = None
        self._background_analysis_mode = False
        self._background_execute_pending = False
        self._render_analysis_plan()
        self._active_worker_mode = ""
        self._active_task_id = None
        self._reset_transcript()
        self._refresh_overview_ui()
        self._refresh_global_dataset_surfaces()

        self._task_open = True
        self.app_stack.setCurrentIndex(1)
        self._show_mode_page(self.workspace)
        self._set_active_mode("analysis")
        self.nav_clean_btn.setProperty("active", False)
        self.nav_clean_btn.style().unpolish(self.nav_clean_btn)
        self.nav_clean_btn.style().polish(self.nav_clean_btn)
        self._set_task_controls_enabled(True)
        self._set_task_title()
        self.log_output.append("New task started.")
        self.result_output.set_empty_state(
            "Choose datasets from the shared library to begin."
            if self.loaded_files
            else "Add a dataset to begin."
        )
        self._composer_collapsed = False
        self.command_bar.show()
        self.composer_status_btn.hide()
        self._close_context_panel()
        self._toggle_context_panel()
        QTimer.singleShot(0, self._position_floating_composer)

    def _start_cleaning(self) -> None:
        self._show_cleaning_page()

    def _set_active_mode(self, mode: str) -> None:
        self._active_mode = mode
        if mode == "cleaning":
            preferred = self._current_dataset_name()
            if preferred not in self.loaded_files:
                preferred = next(
                    (name for name in self.loaded_files if name in self._selected_datasets),
                    None,
                )
            if preferred is None:
                preferred = next(iter(self.loaded_files), None)
            self._selected_datasets.clear()
            if preferred:
                self._selected_datasets.add(preferred)
        labels = {
            "analysis": "Mode: Data Analysis",
            "cleaning": "Mode: Data Cleaning",
            "metric": "Mode: Business Indicators",
        }
        self.mode_button.setText(labels.get(mode, "Mode"))
        self._sync_mode_selector_state()
        for button, active in (
            (self.nav_clean_btn, mode == "cleaning"),
            (self.nav_metric_btn, mode == "metric"),
        ):
            button.setProperty("active", active)
            button.style().unpolish(button)
            button.style().polish(button)
        self._refresh_dataset_selection_ui()
        self._sync_cleaning_target()

    def _sync_mode_selector_state(self) -> None:
        """Keep mode navigation independent from dataset availability."""
        in_feature = self.app_stack.currentIndex() == 1
        selector_available = in_feature and bool(self._active_mode)

        self.mode_button.setVisible(selector_available)
        self.mode_button.setEnabled(selector_available)
        self.dataset_library_btn.setVisible(
            selector_available
            and self._active_mode in {"analysis", "cleaning"}
        )
        self.view_context_action.setEnabled(
            selector_available
            and self._active_mode in {"analysis", "cleaning"}
        )

        # Analysis and cleaning both have useful empty states where users can
        # open the Dataset Library and import the data they need.
        self.mode_analysis_action.setEnabled(
            selector_available and self._active_mode != "analysis"
        )
        self.mode_cleaning_action.setEnabled(
            selector_available
            and self._active_mode != "cleaning"
        )
        self.mode_metric_action.setEnabled(
            selector_available and self._active_mode != "metric"
        )

    def _start_cleaning_profile(self, dataset_name: str) -> None:
        if self._cleaning_thread is not None:
            return
        file_meta = self.loaded_files.get(dataset_name)
        if file_meta is None:
            self.cleaning_page.show_error("The selected dataset is no longer available.")
            return
        self.cleaning_page.show_busy("Scanning cached data for supported issues...")
        thread = QThread(self)
        worker = CleaningProfileWorker(dataset_name, file_meta)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.cleaning_page.set_progress)
        worker.finished.connect(self._on_cleaning_profile_finished)
        worker.failed.connect(self._on_cleaning_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_cleaning_worker)
        self._cleaning_thread = thread
        self._cleaning_worker = worker
        thread.start()

    def _start_cleaning_execution(
        self,
        dataset_name: str,
        selections: dict,
        output_path: str,
    ) -> None:
        if self._cleaning_thread is not None:
            return
        file_meta = self.loaded_files.get(dataset_name)
        if file_meta is None:
            self.cleaning_page.show_error("The selected dataset is no longer available.")
            return
        self.cleaning_page.show_busy("Cleaning in the background...", determinate=True)
        thread = QThread(self)
        from pathlib import Path

        if Path(output_path).resolve(strict=False) == Path(
            file_meta.file_path
        ).resolve(strict=False):
            self.cleaning_page.show_error(
                "The cleaned workbook cannot overwrite the original dataset."
            )
            return
        worker = CleaningExecutionWorker(
            dataset_name,
            file_meta,
            selections,
            output_path,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.cleaning_page.set_progress)
        worker.finished.connect(self._on_cleaning_execution_finished)
        worker.failed.connect(self._on_cleaning_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_cleaning_worker)
        self._cleaning_thread = thread
        self._cleaning_worker = worker
        thread.start()

    def _on_cleaning_profile_finished(self, dataset_name: str, profile) -> None:
        if dataset_name != self.cleaning_page.target_dataset:
            self.log_output.append(
                f"Ignored stale cleaning scan for {dataset_name}."
            )
            return
        self.cleaning_page.show_profile(profile)
        detected = sum(
            1
            for issue in profile.issues
            if issue.issue_id != "key_duplicates" and issue.count > 0
        )
        self.log_output.append(
            f"Cleaning scan completed: {detected} issue type(s) found."
        )

    def _on_cleaning_execution_finished(self, dataset_name: str, result) -> None:
        if dataset_name != self.cleaning_page.target_dataset:
            self.log_output.append(
                f"Cleaning completed for {dataset_name}: {result.output_path}"
            )
            return
        self.cleaning_page.show_result(result)
        self.log_output.append(f"Cleaned workbook saved: {result.output_path}")

    def _on_cleaning_failed(self, dataset_name: str, error: str) -> None:
        if dataset_name != self.cleaning_page.target_dataset:
            self.log_output.append(
                f"Cleaning operation for {dataset_name} failed: {error}"
            )
            return
        if "cancel" in error.lower():
            self.cleaning_page.show_cancelled()
            self.log_output.append(f"Cleaning operation cancelled: {dataset_name}")
        else:
            self.cleaning_page.show_error(error)
            self.log_output.append(f"Data cleaning failed: {error}")

    def _cancel_cleaning(self) -> None:
        if self._cleaning_worker is None:
            return
        self._cleaning_worker.cancel()
        self.cleaning_page.summary_label.setText("Cancelling cleaning operation...")
        self.cleaning_page.cancel_button.setEnabled(False)
        self.log_output.append("Cleaning cancellation requested.")

    def _cleanup_cleaning_worker(self) -> None:
        self._cleaning_thread = None
        self._cleaning_worker = None
        self.cleaning_page.cancel_button.setEnabled(True)

    def _stop_overview_worker(self) -> None:
        worker = self._overview_worker
        thread = self._overview_thread
        if worker is not None:
            worker.cancel()
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(3000)

    def closeEvent(self, event) -> None:
        self._experience_submissions.shutdown()
        if self._metric_worker is not None:
            self._metric_worker.cancel()
        if self._metric_thread is not None and self._metric_thread.isRunning():
            self._metric_thread.quit()
            self._metric_thread.wait(3000)
        if self._export_worker is not None:
            self._export_worker.cancel()
        if self._export_thread is not None and self._export_thread.isRunning():
            self._export_thread.quit()
            self._export_thread.wait(3000)
        if self._cleaning_worker is not None:
            self._cleaning_worker.cancel()
        if self._cleaning_thread is not None and self._cleaning_thread.isRunning():
            self._cleaning_thread.quit()
            self._cleaning_thread.wait(3000)
        if self._import_worker is not None:
            self._import_worker.cancel()
        if self._import_thread is not None and self._import_thread.isRunning():
            self._import_thread.quit()
            self._import_thread.wait(3000)
        if self._analysis_worker is not None:
            self._analysis_worker.cancel()
        if self._analysis_thread is not None and self._analysis_thread.isRunning():
            self._analysis_thread.quit()
            self._analysis_thread.wait(3000)
        self._stop_overview_worker()
        self.overview_popover.hide()
        self._hide_suggestion_popover()
        self.experience_feedback.hide_prompt()
        self._set_context_click_guard_enabled(False)
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape and self._context_panel_open:
            self._close_context_panel()
            event.accept()
            return
        super().keyPressEvent(event)

    def _close_task(self) -> None:
        if self._analysis_thread is not None:
            self.log_output.append("Task is still running. Please wait until it finishes.")
            return

        active_task = self._find_history_task(self._active_task_id)
        if active_task and not active_task.get("finished"):
            self._update_history_task("Closed", finished=True)

        self._dismiss_experience_prompt(record=True)
        self._show_start_page()

    def _set_task_controls_enabled(self, enabled: bool) -> None:
        self.history_btn.setVisible(enabled)
        self.settings_btn.setVisible(enabled)
        self.upload_btn.setEnabled(True)
        self.dataset_list.setEnabled(True)
        self.prompt_input.setEnabled(enabled)
        self.run_btn.setEnabled(enabled)
        self.code_apply_btn.setEnabled(enabled and self.code_apply_btn.isVisible())
        self.code_editor.setEnabled(enabled)
        self.code_reset_btn.setEnabled(enabled)

    def _show_history_page(self) -> None:
        self._dismiss_experience_prompt(record=True)
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
            "analysis_plan": {},
            "analysis_result": {},
            "code": "",
            "result": "Waiting for analysis result.",
            "error": "",
            "analysis_session_id": new_analysis_session_id(),
            "analysis_run_id": "",
            "analysis_verified": False,
            "repair_count": 0,
            "manual_edit": False,
            "experience_prompted": False,
            "experience_consent": None,
            "experience_status": "not_started",
            "experience_submitted_at": "",
            "experience_error": "",
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

        self._dismiss_experience_prompt(record=True)
        files_meta = list(task.get("files_meta") or [])
        task_dataset_names = []
        for file_meta in files_meta:
            display_name = self._library_name_for_meta(file_meta)
            if display_name is None:
                display_name = self._dataset_display_name_for_all(
                    file_meta.display_name or file_meta.file_name
                )
                file_meta.display_name = display_name
                self.loaded_files[display_name] = file_meta
                self._dataset_states[display_name] = {
                    "state": "ready",
                    "file_path": file_meta.file_path,
                    "percent": 100,
                }
                self._add_dataset_item(display_name, selected=False)
            task_dataset_names.append(display_name)

        self._selected_datasets.clear()
        for display_name in task_dataset_names[: settings.MAX_SELECTED_DATASETS]:
            self._set_dataset_analysis_selected(display_name, True)
        self._refresh_dataset_selection_ui()
        if task_dataset_names:
            self._select_dataset_by_name(task_dataset_names[0])
        self._refresh_global_dataset_surfaces()

        code = task.get("code") or task.get("generated_code") or ""
        result = task.get("result") or "Session reopened."
        error = task.get("error") or ""

        self._active_task_id = task_id
        self._pending_files_meta = files_meta or None
        self._pending_query = task.get("query", "")
        self._generated_code = task.get("generated_code") or code
        self._analysis_plan = task.get("analysis_plan") or {}
        result_payload = task.get("analysis_result") or {}
        self._current_analysis_result = (
            AnalysisResult.from_dict(result_payload)
            if result_payload
            else None
        )
        self._refresh_result_export_state()
        self._active_worker_mode = ""
        self._reset_transcript()
        self.prompt_input.setPlainText(task.get("query", ""))
        self.code_editor.setPlainText(code)
        if self._current_analysis_result is not None:
            self.result_output.set_result(self._current_analysis_result)
        else:
            self.result_output.setPlainText(result)
        self._render_analysis_plan()
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
        """Generate, preflight, and repair code before presenting it."""
        if not self._pending_query or not self._pending_files_meta:
            return

        self._reset_transcript()
        self._append_system_event("Generating and validating code...")
        self._start_analysis_worker(
            mode="prepare",
            files_meta=self._pending_files_meta,
            user_query=self._pending_query,
        )

    def _show_analyze_action(self) -> None:
        self.run_btn.setVisible(True)
        self.run_btn.setEnabled(True)
        self.run_btn.setText("Analyze")
        self.code_apply_btn.setVisible(False)

    def _show_apply_action(self, retry: bool = False) -> None:
        self._set_python_tab_visible(True)
        self.run_btn.setVisible(True)
        self.code_apply_btn.setVisible(True)
        self.code_apply_btn.setEnabled(True)
        self.code_apply_btn.setText("Apply again" if retry else "Apply")

    def _on_apply_clicked(self):
        """Execute the code currently in the editor."""
        if not self._pending_files_meta:
            return

        code = self.code_editor.toPlainText().strip()
        if not code:
            self.result_output.setText("No Python code is available to execute yet.")
            return

        if (
            code == self._verified_code
            and self._verified_execution is not None
            and self._verified_execution.success
        ):
            self.log_output.append("Using locally validated analysis result.")
            cached_execution = self._verified_execution
            self._verified_execution = None
            self._present_execution_result(code, cached_execution)
            return

        self._append_system_event("Executing approved code...")
        self._last_applied_code = code
        self.code_apply_btn.setVisible(False)
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
            user_query=self._pending_query or "",
            code=code,
            analysis_plan=self._analysis_plan,
        )

    def _start_analysis_worker(
        self,
        mode: str,
        files_meta: list,
        user_query: str = "",
        code: str = "",
        analysis_plan: dict | None = None,
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
            analysis_plan=analysis_plan,
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
            self._set_activity_message(message)
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
        if self._active_worker_mode in {"prepare", "generate"}:
            if result.needs_clarification:
                self._analysis_plan = result.analysis_plan or {}
                options = [
                    OptionItem(
                        label=str(item.get("label") or item.get("id") or "Option"),
                        description=str(item.get("description") or ""),
                        data=item,
                    )
                    for item in result.clarification_options
                ]
                self.decision_panel.show_decision(
                    title="Confirm how the datasets should be combined",
                    description=(
                        result.clarification_question
                        or "The dataset relationship is ambiguous."
                    ),
                    options=options,
                    allow_skip=True,
                    skip_label="Back to request",
                )
                self.canvas_stack.setCurrentIndex(1)
                self._set_composer_state("ready")
                self._update_history_task(
                    "Needs clarification",
                    result.clarification_question,
                    finished=False,
                    analysis_plan=self._analysis_plan,
                    result=result.clarification_question,
                )
            elif result.success:
                self._generated_code = result.code
                self._analysis_plan = result.analysis_plan or {}
                self._verified_code = result.code
                self._verified_execution = (
                    None if result.preflight_only else result.execution
                )
                self._render_analysis_plan()
                self.code_editor.setPlainText(result.code)
                self.code_editor.document().setModified(False)
                if result.retries_used:
                    self.log_output.append(
                        f"Code was automatically corrected {result.retries_used} time(s)."
                    )
                if self._background_analysis_mode:
                    self._background_execute_pending = True
                    self._append_system_event(
                        "Sample preflight passed. Full analysis is queued in the background."
                    )
                    self._transcript["execution"] = (
                        "The large-dataset preflight passed. Full local analysis "
                        "will continue automatically; code remains available in "
                        "the Python tab."
                    )
                    self._set_python_tab_visible(True)
                    self.analysis_tabs.setCurrentIndex(0)
                    self.run_btn.setVisible(True)
                    self.run_btn.setEnabled(False)
                    self.run_btn.setText("Queued")
                    self.code_apply_btn.setVisible(False)
                    self._update_history_task(
                        "Queued",
                        finished=False,
                        generated_code=result.code,
                        code=result.code,
                        analysis_plan=self._analysis_plan,
                        repair_count=int(result.retries_used or 0),
                        result=self._transcript["execution"],
                        error="",
                    )
                    self._render_transcript()
                    self._set_busy(False)
                    return
                self._append_system_event(
                    "Code passed sample preflight. Review it before Apply."
                )
                self.log_output.append(
                    "Code passed sample preflight and is ready for full execution."
                )
                self._transcript["execution"] = (
                    "Python code passed representative sample preflight. "
                    "Review it, then click Apply to run the complete datasets."
                )
                self._set_python_tab_visible(True)
                self.analysis_tabs.setCurrentIndex(self.python_tab_index)
                self._show_apply_action()
                self._set_composer_state("code")
                self._update_history_task(
                    "Awaiting Apply",
                    generated_code=result.code,
                    code=result.code,
                    analysis_plan=self._analysis_plan,
                    repair_count=int(result.retries_used or 0),
                    result="Python code passed sample preflight and is ready for Apply.",
                    error="",
                )
            else:
                self._verified_code = ""
                self._verified_execution = None
                self._set_composer_state("error")
                self._append_system_event(f"Code preparation failed: {result.error}")
                self.log_output.append(f"Code preparation failed: {result.error}")
                if result.code:
                    self._generated_code = result.code
                    self._analysis_plan = result.analysis_plan or {}
                    self.code_editor.setPlainText(result.code)
                    self._render_analysis_plan()
                    self._transcript["execution"] = (
                        "Automatic correction could not produce runnable code. "
                        "Review the Python code or click Apply again to retry."
                    )
                    self._set_python_tab_visible(True)
                    self.analysis_tabs.setCurrentIndex(1)
                    self._show_apply_action(retry=True)
                    self._update_history_task(
                        "Needs correction",
                        result.error,
                        finished=False,
                        generated_code=result.code,
                        code=result.code,
                        analysis_plan=self._analysis_plan,
                        result=self._transcript["execution"],
                        error=result.error,
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
                        result.error,
                        finished=True,
                        result=(
                            "Code generation failed. Check settings and try Analyze again."
                        ),
                        error=result.error,
                    )

        elif self._active_worker_mode == "execute":
            if result.success:
                task = self._find_history_task(self._active_task_id)
                if task is not None:
                    task["repair_count"] = (
                        int(task.get("repair_count") or 0)
                        + int(result.retries_used or 0)
                    )
                if result.code != self.code_editor.toPlainText().strip():
                    self.log_output.append(
                        f"Edited code was automatically corrected "
                        f"{result.retries_used} time(s)."
                    )
                    self.code_editor.setPlainText(result.code)
                    self._generated_code = result.code
                    self.code_editor.document().setModified(False)
                self._verified_code = result.code
                self._verified_execution = None
                self._present_execution_result(result.code, result.execution)
            else:
                self._verified_code = ""
                self._verified_execution = None
                self._set_composer_state("error")
                if result.code and result.code != self.code_editor.toPlainText().strip():
                    self.code_editor.setPlainText(result.code)
                    self._generated_code = result.code
                    self.code_editor.document().setModified(False)
                error_text = (
                    result.execution.stderr if result.execution else result.error
                )
                self._append_system_event("Execution failed")
                self.log_output.append(f"Execution detail: {error_text}")
                self._transcript["execution"] = (
                    "The Python code could not be executed after automatic correction.\n"
                    "Review or reset the code, then click Apply again."
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

    def _present_execution_result(self, code: str, execution) -> None:
        self._last_applied_code = code.strip()
        output_text = execution.stdout if execution else ""
        analysis_result = (
            execution.analysis_result
            if execution
            else AnalysisResult(summary=output_text, raw_output=output_text)
        )
        self._current_analysis_result = analysis_result
        self._refresh_result_export_state()
        self._append_system_event("Execution completed")
        self.log_output.append("Execution completed.")
        self._transcript["execution"] = (
            output_text or "Execution completed with no stdout."
        )
        self.result_output.set_result(analysis_result)
        self._set_python_tab_visible(True)
        task = self._find_history_task(self._active_task_id)
        analysis_run_id = new_analysis_run_id()
        manual_edit = bool(
            task
            and task.get("generated_code")
            and code.strip() != str(task.get("generated_code") or "").strip()
        )
        analysis_verified = bool(
            execution is not None
            and execution.success
            and not execution.preflight_only
        )
        self._update_history_task(
            "Completed",
            finished=True,
            code=code,
            generated_code=self._generated_code or code,
            result=self._transcript["execution"],
            analysis_result=analysis_result.to_dict(),
            analysis_run_id=analysis_run_id,
            analysis_verified=analysis_verified,
            manual_edit=manual_edit,
            error="",
        )
        self.analysis_tabs.setCurrentIndex(0)
        self.code_apply_btn.setVisible(False)
        self._set_composer_state("done")
        if analysis_verified:
            completed_task_id = self._active_task_id
            QTimer.singleShot(
                320,
                partial(
                    self._show_experience_prompt_if_eligible,
                    completed_task_id,
                ),
            )

    def _show_experience_prompt_if_eligible(
        self,
        task_id: int | None,
    ) -> None:
        if task_id is None or task_id != self._active_task_id:
            return
        if (
            not self._task_open
            or self.page_container.currentWidget() is not self.workspace
        ):
            return
        task = self._find_history_task(task_id)
        if not ExperienceService.should_prompt(task):
            return

        task["experience_prompted"] = True
        task["experience_status"] = "prompted"
        task["experience_error"] = ""
        task["updated_at"] = self._history_timestamp()
        self._experience_prompt_task_id = task_id
        self._refresh_history_page()

        width = min(340, max(280, self.workspace.width() - 32))
        target = QRect(
            max(16, self.workspace.width() - width - 22),
            58,
            width,
            126,
        )
        self.experience_feedback.show_prompt(target)

    def _on_experience_useful(self) -> None:
        task_id = self._experience_prompt_task_id
        task = self._find_history_task(task_id)
        self._experience_prompt_task_id = None
        if task is None:
            return

        task["experience_consent"] = True
        task["experience_status"] = "queued"
        task["experience_error"] = ""
        task["updated_at"] = self._history_timestamp()
        self._refresh_history_page()

        try:
            analysis_result = AnalysisResult.from_dict(
                task.get("analysis_result") or {}
            )
            payload = ExperienceService.build_payload(
                task=task,
                analysis_result=analysis_result,
            )
        except Exception as exc:
            logger.exception(
                "Unable to prepare experience payload task_id=%s",
                task_id,
            )
            self._update_experience_task(
                task_id,
                experience_status="failed",
                experience_error=str(exc),
            )
            return
        self._enqueue_experience_submission(task_id, payload)

    def _on_experience_dismissed(self) -> None:
        task_id = self._experience_prompt_task_id
        self._experience_prompt_task_id = None
        task = self._find_history_task(task_id)
        if task is None:
            return
        self._update_experience_task(
            task_id,
            experience_consent=False,
            experience_status="dismissed",
            experience_error="",
        )

    def _dismiss_experience_prompt(self, *, record: bool) -> None:
        task_id = self._experience_prompt_task_id
        self._experience_prompt_task_id = None
        if hasattr(self, "experience_feedback"):
            self.experience_feedback.hide_prompt()
        if not record:
            return
        task = self._find_history_task(task_id)
        if task is None or task.get("experience_status") != "prompted":
            return
        self._update_experience_task(
            task_id,
            experience_consent=False,
            experience_status="dismissed",
            experience_error="",
        )

    def _enqueue_experience_submission(
        self,
        task_id: int,
        payload: dict,
    ) -> None:
        self._update_experience_task(
            task_id,
            experience_status="submitting",
            experience_error="",
        )
        self._experience_submissions.enqueue(task_id, payload)

    def _on_experience_submission_finished(self, task_id: int, result) -> None:
        self._update_experience_task(
            task_id,
            experience_status="submitted",
            experience_submitted_at=datetime.now().isoformat(timespec="seconds"),
            experience_error="",
            experience_workflow_run_id=result.workflow_run_id,
            experience_knowledge_status=result.knowledge_write_status,
            experience_candidate_count=result.candidate_count,
            experience_uploaded_count=result.uploaded_count,
            experience_failed_count=result.failed_count,
        )
        logger.info(
            "Experience learning completed task_id=%s status=%s uploaded=%s",
            task_id,
            result.knowledge_write_status,
            result.uploaded_count,
        )

    def _on_experience_submission_failed(self, task_id: int, error: str) -> None:
        self._update_experience_task(
            task_id,
            experience_status="failed",
            experience_error=error,
        )
        logger.warning(
            "Experience learning failed task_id=%s error=%s",
            task_id,
            error,
        )

    def _update_experience_task(self, task_id: int | None, **updates) -> None:
        task = self._find_history_task(task_id)
        if task is None:
            return
        task.update(updates)
        task["updated_at"] = self._history_timestamp()
        self._refresh_history_page()

    def _on_worker_error(self, error: str) -> None:
        self._append_system_event(f"Worker error: {error}")
        self.log_output.append(f"Worker detail: {error}")
        self._set_composer_state("error")
        if self._active_worker_mode == "execute":
            self._transcript["execution"] = (
                "The Python code could not be executed.\n"
                "Review or reset the code, then click Apply again."
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
        if self._background_execute_pending:
            self._background_execute_pending = False
            self._append_system_event("Running full analysis in the background...")
            self._start_analysis_worker(
                mode="execute",
                files_meta=self._pending_files_meta or [],
                user_query=self._pending_query or "",
                code=self._generated_code,
                analysis_plan=self._analysis_plan,
            )

    def _set_busy(self, busy: bool) -> None:
        self.run_btn.setEnabled(not busy)
        self.upload_btn.setEnabled(not busy)
        self.settings_btn.setEnabled(not busy)
        self.history_btn.setEnabled(not busy)
        self.code_reset_btn.setEnabled(not busy)
        self.code_editor.setEnabled(not busy)
        self.code_apply_btn.setEnabled(not busy)
        if busy:
            self.run_btn.setText("Working")
            self._set_composer_state("busy")
            if not self.activity_label.text():
                self.activity_label.setText("Working")
            self.activity_strip.setVisible(True)
            self._start_activity_pulse()
        else:
            self.run_btn.setText("Analyze")
            self.activity_strip.setVisible(False)
            self._stop_activity_pulse()
            self._activity_progress_animation.stop()
            self.activity_progress.setRange(0, 0)
            self.activity_progress.setValue(0)

    def _set_activity_message(self, message: str, progress: int | None = None) -> None:
        if not message:
            return
        self.activity_label.setText(message)
        compact = message if len(message) <= 72 else message[:69] + "..."
        self.activity_toggle_btn.setText(f"Activity · {compact}")
        if self._analysis_thread is not None:
            self.activity_strip.setVisible(True)
        if progress is None:
            self._activity_progress_animation.stop()
            self.activity_progress.setRange(0, 0)
        else:
            progress = max(0, min(100, int(progress)))
            self.activity_progress.setRange(0, 100)
            self._activity_progress_animation.stop()
            self._activity_progress_animation.setStartValue(self._activity_progress_value)
            self._activity_progress_animation.setEndValue(progress)
            self._activity_progress_animation.start()
        self._start_activity_pulse()

    def _start_activity_pulse(self) -> None:
        if self._activity_pulse.state() != QVariantAnimation.Running:
            self._activity_pulse.start()

    def _stop_activity_pulse(self) -> None:
        if self._activity_pulse.state() == QVariantAnimation.Running:
            self._activity_pulse.stop()
        self._activity_pulse_t = 0.0
        self.activity_strip.setProperty("pulse", 0.0)
        self.activity_progress.setProperty("busyPulse", 0.0)
        self._activity_shadow.setColor(QColor(26, 115, 232, 0))
        self.activity_strip.style().unpolish(self.activity_strip)
        self.activity_strip.style().polish(self.activity_strip)
        self.activity_progress.style().unpolish(self.activity_progress)
        self.activity_progress.style().polish(self.activity_progress)

    def _on_activity_pulse(self, value) -> None:
        self._activity_pulse_t = float(value)
        self.activity_strip.setProperty("pulse", self._activity_pulse_t)
        self.activity_progress.setProperty("busyPulse", self._activity_pulse_t)
        pulse = 1.0 - abs(1.0 - self._activity_pulse_t * 2.0)
        self._activity_shadow.setColor(QColor(26, 115, 232, int(18 + pulse * 34)))
        self.activity_strip.style().unpolish(self.activity_strip)
        self.activity_strip.style().polish(self.activity_strip)
        self.activity_progress.style().unpolish(self.activity_progress)
        self.activity_progress.style().polish(self.activity_progress)

    def _on_activity_progress_changed(self, value) -> None:
        self._activity_progress_value = int(value)
        self.activity_progress.setValue(self._activity_progress_value)

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
        if self._current_analysis_result is not None:
            self.result_output.set_result(self._current_analysis_result)
            return
        execution_text = self._transcript["execution"].strip()
        if execution_text:
            self.result_output.setPlainText(execution_text)

    def _on_export_result_clicked(self) -> None:
        if self._current_analysis_result is None or self._export_thread is not None:
            return
        export_result, export_scope = self._select_result_for_export()
        if export_result is None:
            return
        default_name = self._default_export_name(export_scope)
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export analysis result",
            default_name,
            "Excel Workbook (*.xlsx)",
        )
        if not output_path:
            return
        if Path(output_path).suffix.lower() != ".xlsx":
            output_path += ".xlsx"
        self._start_result_export(
            output_path,
            export_result=export_result,
            export_scope=export_scope,
        )

    def _select_result_for_export(self) -> tuple[AnalysisResult | None, str]:
        result = self._current_analysis_result
        if result is None:
            return None, "All results"
        if len(result.answers) <= 1:
            return result, "All results"

        options = ["All results"]
        options.extend(
            f"Result {index}: {answer.question[:80]}"
            for index, answer in enumerate(result.answers, start=1)
        )
        current_index = 0
        selected_index = self.result_output.selected_answer_index()
        if selected_index is not None:
            current_index = selected_index + 1

        choice, accepted = QInputDialog.getItem(
            self,
            "Choose export scope",
            "Export which result?",
            options,
            current_index,
            False,
        )
        if not accepted:
            return None, ""
        if choice == options[0]:
            return result, "All results"
        answer_index = options.index(choice) - 1
        return result.answer_result(answer_index), choice.split(":", 1)[0]

    def _default_export_name(self, export_scope: str = "All results") -> str:
        scope = next(
            (
                meta.display_name or meta.file_name
                for meta in (self._pending_files_meta or [])
            ),
            "analysis",
        )
        stem = Path(scope).stem
        if export_scope and export_scope != "All results":
            stem = f"{stem}-{export_scope.lower().replace(' ', '-')}"
        safe_stem = re.sub(r'[<>:"/\\|?*]+', "_", stem).strip(" ._")
        safe_stem = safe_stem or "analysis"
        timestamp = datetime.now().strftime("%Y%m%d-%H%M")
        return str(Path.home() / "Documents" / f"{safe_stem}-result-{timestamp}.xlsx")

    def _start_result_export(
        self,
        output_path: str,
        *,
        export_result: AnalysisResult | None = None,
        export_scope: str = "All results",
    ) -> None:
        if self._current_analysis_result is None or self._export_thread is not None:
            return
        result = export_result or self._current_analysis_result
        metadata = {
            "Datasets": ", ".join(
                meta.display_name or meta.file_name
                for meta in (self._pending_files_meta or [])
            ),
            "Request": self._pending_query or "",
            "Export scope": export_scope,
            "Task ID": self._active_task_id or "",
        }
        thread = QThread(self)
        worker = AnalysisExportWorker(
            result,
            output_path,
            metadata,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_result_export_finished)
        worker.failed.connect(self._on_result_export_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_result_export)
        self._export_thread = thread
        self._export_worker = worker
        self._refresh_result_export_state()
        self.header_export_btn.setText("Exporting...")
        self.log_output.append(f"Export started: {output_path}")
        thread.start()

    def _on_result_export_finished(self, output_path: str) -> None:
        self.header_export_btn.setText("Exported")
        self.log_output.append(f"Analysis result exported: {output_path}")
        self._append_system_event(f"Result exported to {output_path}")
        QTimer.singleShot(1200, self._reset_export_button_text)

    def _on_result_export_failed(self, error: str) -> None:
        self.header_export_btn.setText("Export failed")
        self.log_output.append(f"Analysis result export failed: {error}")
        QTimer.singleShot(1600, self._reset_export_button_text)
        QMessageBox.warning(
            self,
            "Export failed",
            f"The analysis result could not be exported.\n\n{error}",
        )

    def _cleanup_result_export(self) -> None:
        self._export_thread = None
        self._export_worker = None
        self._refresh_result_export_state()

    def _reset_export_button_text(self) -> None:
        if self._export_thread is None:
            self.header_export_btn.setText("Export")

    def _refresh_result_export_state(self) -> None:
        available = self._current_analysis_result is not None
        running = self._export_thread is not None
        if hasattr(self, "header_export_btn"):
            self.header_export_btn.setVisible(available)
            self.header_export_btn.setEnabled(available and not running)
        if hasattr(self, "export_result_action"):
            self.export_result_action.setEnabled(available and not running)

    def _render_analysis_plan(self) -> None:
        plan = self._analysis_plan or {}
        requirements = plan.get("requirements") or []
        warnings = [
            str(item).strip()
            for item in (plan.get("warnings") or [])
            if str(item).strip()
        ]
        summary = str(
            plan.get("task_summary") or plan.get("summary") or ""
        ).strip()
        objectives = []
        for requirement in requirements:
            if isinstance(requirement, dict):
                objective = str(
                    requirement.get("objective")
                    or requirement.get("description")
                    or ""
                ).strip()
            else:
                objective = str(requirement).strip()
            if objective:
                objectives.append(objective)

        parts = []
        if summary:
            parts.append(summary)
        if objectives:
            visible = objectives[:4]
            parts.append(" · ".join(visible))
            if len(objectives) > len(visible):
                parts.append(f"+{len(objectives) - len(visible)} more")
        if warnings:
            parts.append("Attention: " + " · ".join(warnings[:2]))
            if len(warnings) > 2:
                parts.append(f"+{len(warnings) - 2} warnings")

        self.analysis_plan_label.setText(
            "Plan  " + "  |  ".join(parts) if parts else ""
        )
        self.analysis_plan_label.setVisible(bool(parts))

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

    def _dataset_display_name_for_all(self, base_name: str) -> str:
        from pathlib import Path

        existing = set(self.loaded_files) | set(self._dataset_states)
        if base_name not in existing:
            return base_name
        path = Path(base_name)
        index = 2
        while True:
            candidate = f"{path.stem} ({index}){path.suffix}"
            if candidate not in existing:
                return candidate
            index += 1

    def _reset_code_to_generated(self) -> None:
        if not self._generated_code:
            return
        self.code_editor.setPlainText(self._generated_code)
        self.code_editor.document().setModified(False)
        self._set_python_tab_visible(True)
        self.analysis_tabs.setCurrentIndex(1)
        if self._pending_files_meta:
            self._show_apply_action(retry=True)

    def _on_code_text_changed(self) -> None:
        code = self.code_editor.toPlainText().strip()
        python_available = self.analysis_tabs.tabBar().isTabVisible(
            self.python_tab_index
        )
        if self._pending_files_meta and code and code != self._last_applied_code:
            if not python_available:
                return
            self._show_apply_action(retry=self._current_analysis_result is not None)
        elif code == self._last_applied_code or not code:
            self.code_apply_btn.setVisible(False)

    def _set_python_tab_visible(self, visible: bool) -> None:
        self.analysis_tabs.tabBar().setTabVisible(self.python_tab_index, visible)
        self.analysis_tabs.tabBar().setVisible(visible)
        if not visible:
            self.analysis_tabs.setCurrentIndex(0)

    def _library_name_for_meta(self, file_meta) -> str | None:
        for display_name, current in self.loaded_files.items():
            if (
                file_meta.dataset_id
                and current.dataset_id
                and file_meta.dataset_id == current.dataset_id
            ):
                return display_name
            if current.file_path == file_meta.file_path:
                return display_name
        return None

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

            QPushButton#titleMenuBtn {
                background-color: transparent;
                color: #3C4043;
                border: none;
                border-radius: 4px;
                padding: 2px 7px;
                font-size: 11px;
                font-weight: 500;
            }

            QPushButton#titleMenuBtn:hover,
            QPushButton#titleMenuBtn::menu-indicator {
                background-color: #E8EAED;
            }

            QPushButton#titleMenuBtn::menu-indicator {
                image: none;
                width: 0;
            }

            QPushButton#modeSelectorButton {
                color: #52616D;
                background: #FFFFFF;
                border: 1px solid #DADCE0;
                border-radius: 11px;
                padding: 5px 13px;
                font-size: 10px;
                font-weight: 650;
            }

            QPushButton#modeSelectorButton:hover {
                color: #174EA6;
                background: #E8F0FE;
                border-color: #D2E3FC;
            }

            QPushButton#modeSelectorButton:disabled {
                color: #B3BCC3;
                background: #F1F3F4;
            }

            QPushButton#modeSelectorButton::menu-indicator {
                subcontrol-position: right center;
                subcontrol-origin: padding;
                right: 5px;
            }

            QPushButton#datasetLibraryButton {
                color: #3C4043;
                background: #FFFFFF;
                border: 1px solid #DADCE0;
                border-radius: 12px;
                padding: 5px 11px;
                font-size: 10px;
                font-weight: 700;
            }

            QPushButton#datasetLibraryButton:hover {
                color: #174EA6;
                background: #E8F0FE;
                border-color: #D2E3FC;
            }

            QMenu {
                background-color: #FFFFFF;
                color: #202124;
                border: 1px solid #DADCE0;
                border-radius: 6px;
                padding: 5px;
                font-size: 11px;
            }

            QMenu::item {
                padding: 6px 28px 6px 10px;
                border-radius: 4px;
            }

            QMenu::item:selected {
                background-color: #E8F0FE;
                color: #174EA6;
            }

            QMenu::item:disabled {
                color: #9AA0A6;
            }

            QMenu::separator {
                height: 1px;
                background: #E8EAED;
                margin: 4px 6px;
            }

            QPushButton#btnMinimize,
            QPushButton#btnMaximize,
            QPushButton#btnClose {
                background-color: transparent;
                border: none;
                border-radius: 0;
                color: #5F6368;
                padding: 0;
                margin: 0;
            }

            QPushButton#btnMinimize:hover,
            QPushButton#btnMaximize:hover {
                background-color: #E9EAEC;
                color: #202124;
            }

            QPushButton#btnClose:hover {
                background-color: #E5484D;
                color: #FFFFFF;
            }

            /* ========================================================================= */
            /* Sidebar */
            /* ========================================================================= */

            QWidget#leftShell {
                background-color: #F8F9FA;
                border-right: 1px solid #E5E7EB;
            }

            QFrame#navigationRail {
                background-color: #F3F4F6;
                border-right: 1px solid #E5E7EB;
            }

            QPushButton#navigationRailButton {
                background-color: transparent;
                color: #5F6368;
                border: 1px solid transparent;
                border-radius: 7px;
                font-family: "Segoe UI Emoji", "Segoe UI Symbol", "Segoe UI";
                font-size: 14px;
                font-weight: 400;
                padding: 0;
            }

            QPushButton#navigationRailButton:hover,
            QPushButton#navigationRailButton[active="true"] {
                background-color: #E8F0FE;
                border-color: #D2E3FC;
                color: #1A73E8;
            }

            QPushButton#navigationRailButton:disabled {
                color: #BDC1C6;
                background-color: transparent;
            }

            QWidget#sidebar {
                background-color: #F8F9FA;
                border: none;
                border-radius: 17px;
            }

            QFrame#datasetLibraryOverlay {
                background-color: rgba(248, 249, 250, 250);
                border: 1px solid #DADCE0;
                border-radius: 18px;
            }

            QLabel#contextPanelTitle {
                color: #5F6368;
                font-size: 10px;
                font-weight: 700;
            }

            QPushButton#contextCloseBtn {
                color: #5F6368;
                background: transparent;
                border: none;
                border-radius: 5px;
                font-size: 15px;
                padding: 0;
            }

            QPushButton#contextCloseBtn:hover {
                background-color: #E8EAED;
                color: #202124;
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
                background-color: #F8F9FA;
                border: none;
                border-top: 1px solid #E5E7EB;
                font-family: "Courier New";
                font-size: 11px;
                color: #6B7280;
                padding: 8px 14px;
            }

            QFrame#activityDrawer {
                background-color: #F8F9FA;
                border-top: 1px solid #E5E7EB;
            }

            QPushButton#activityToggleBtn {
                background-color: transparent;
                color: #5F6368;
                border: none;
                text-align: left;
                padding: 0 12px;
                font-size: 10px;
                font-weight: 600;
            }

            QPushButton#activityToggleBtn:hover {
                background-color: #F1F3F4;
                color: #202124;
            }

            QFrame#separator {
                color: #E5E7EB;
            }

            /* Result Output */

            QLabel#workspaceTitle {
                color: #202124;
                font-size: 13px;
                font-weight: 650;
            }

            QLabel#workspaceScope {
                color: #6B7280;
                font-size: 10px;
                font-weight: 500;
            }

            QPushButton#workspaceActionBtn {
                background-color: #FFFFFF;
                color: #3C4043;
                border: 1px solid #DADCE0;
                border-radius: 6px;
                padding: 5px 9px;
                font-size: 11px;
                font-weight: 600;
            }

            QPushButton#workspaceActionBtn:hover {
                background-color: #F1F3F4;
            }

            QTextEdit#resultOutput {
                border: none;
                background-color: transparent;
                font-size: 15px;
                line-height: 1.6;
                color: #111827;
            }

            QFrame#activityStrip {
                background-color: #F8FAFD;
                border: 1px solid #E3E8F0;
                border-radius: 7px;
            }

            QLabel#activityLabel {
                color: #3C4043;
                font-size: 11px;
                font-weight: 600;
            }

            QProgressBar#activityProgress {
                background-color: #E8EAED;
                border: none;
                border-radius: 2px;
            }

            QProgressBar#activityProgress::chunk {
                background-color: #1A73E8;
                border-radius: 2px;
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

            QLabel#analysisPlanLabel {
                color: #4B5563;
                background-color: #F8F9FA;
                border: 1px solid #E5E7EB;
                border-radius: 6px;
                padding: 8px 10px;
                font-size: 11px;
                font-weight: 500;
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

            QPushButton#codeApplyBtn {
                background-color: #1A73E8;
                color: #FFFFFF;
                font-size: 11px;
                font-weight: 600;
                border: none;
                border-radius: 5px;
                padding: 3px 12px;
                min-height: 22px;
                max-height: 22px;
            }

            QPushButton#codeApplyBtn:hover {
                background-color: #1765CC;
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
                background-color: rgba(255, 255, 255, 248);
                border: 1px solid #DADCE0;
                border-radius: 12px;
            }

            QTextEdit#promptInput {
                background-color: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 8px;
                font-size: 14px;
                color: #111827;
                padding: 9px 10px;
            }

            QTextEdit#promptInput:focus {
                border-color: #1A73E8;
            }

            QLabel#promptCountLabel {
                color: #9AA0A6;
                font-size: 10px;
                font-weight: 500;
            }

            QPushButton#composerCloseBtn {
                background-color: transparent;
                color: #6B7280;
                border: none;
                border-radius: 5px;
                font-size: 18px;
                font-weight: 400;
                padding: 0;
            }

            QPushButton#composerCloseBtn:hover {
                background-color: #F1F3F4;
                color: #202124;
            }

            QPushButton#composerToggleBtn {
                background-color: #FFFFFF;
                color: #374151;
                border: 1px solid #DADCE0;
                border-radius: 20px;
                padding: 0 18px;
                font-size: 12px;
                font-weight: 600;
            }

            QPushButton#composerToggleBtn:hover {
                background-color: #F8F9FA;
                border-color: #C7CCD1;
                color: #1A73E8;
            }

            QPushButton#composerToggleBtn[state="busy"] {
                color: #6B7280;
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

        """ + DECISION_PANEL_STYLE + RESULT_PANEL_STYLE + CLEANING_PAGE_STYLE + DATA_PORTAL_STYLE)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
