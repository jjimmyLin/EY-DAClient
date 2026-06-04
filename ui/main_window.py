import sys
from PySide6.QtCore import Qt, QPoint
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

        sidebar_layout.addWidget(QLabel("CONTEXT DATA"))
        sidebar_layout.addWidget(self.upload_btn)
        sidebar_layout.addWidget(self.dataset_list, stretch=3)
        sidebar_layout.addWidget(self.history_btn)

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

        self.result_output = QTextEdit()
        self.result_output.setObjectName("resultOutput")
        self.result_output.setReadOnly(True)
        self.result_output.setPlaceholderText(
            "Analysis results will appear here..."
        )

        canvas_layout.addWidget(self.result_output)

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

        command_layout.addWidget(self.prompt_input)
        command_layout.addWidget(self.run_btn)

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

        self.history_btn.clicked.connect(lambda: self.page_container.setCurrentIndex(1))
        self.history_page.btn_back.clicked.connect(lambda: self.page_container.setCurrentIndex(0))

        self._apply_style()

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
        
        for file_path in files:
            try:
                file_meta = preprocessor.process(file_path)
                file_name = file_path.split('/')[-1]
                
                self.loaded_files[file_name] = file_meta
                self.dataset_list.addItem(file_name)
                self.log_output.append(f"✓ Loaded: {file_name}")
            except Exception as e:
                self.log_output.append(f"✗ Error loading {file_path}: {str(e)}")

    def _on_analyze_clicked(self):
        """Handle analyze button click"""
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
            self.result_output.setText("⏳ Analyzing...")
            self.log_output.append(f"Analyzing: {file_name}")
            
            from dify.workflow import AnalysisWorkflow
            workflow = AnalysisWorkflow()
            result = workflow.run([file_meta], query)
            
            if result.success:
                output_text = result.execution.stdout if result.execution else ""
                self.result_output.setText(output_text)
                self.log_output.append("✓ Analysis completed")
            else:
                error_text = result.execution.stderr if result.execution else result.error
                self.result_output.setText(f"Error:\n{error_text}")
                self.log_output.append(f"✗ Analysis failed: {result.error}")
                
        except Exception as e:
            self.result_output.setText(f"Exception: {str(e)}")
            self.log_output.append(f"✗ Exception: {str(e)}")

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
                font-family: "Segoe UI", "Arial", sans-serif;
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
                font-family: "Segoe UI";
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
            QPushButton#historyBtn {
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
            QPushButton#historyBtn:hover {
                background-color: #F3F4F6;
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
                font-family: Consolas;
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
        """)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())