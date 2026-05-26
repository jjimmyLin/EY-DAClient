# ui/main_window.py

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
    QListWidget,
    QFrame,
)


class MainWindow(QMainWindow):
    """
    Main application window.
    """

    def __init__(self):
        super().__init__()

        self.setWindowTitle("AI Data Analysis Assistant")
        self.resize(1400, 900)

        self._init_ui()

    def _init_ui(self):
        """
        Initialize UI layout.
        """

        # =========================
        # Root Widget
        # =========================
        root_widget = QWidget()
        self.setCentralWidget(root_widget)

        root_layout = QHBoxLayout(root_widget)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)

        # =========================
        # Left Panel
        # =========================
        left_panel = QFrame()
        left_panel.setObjectName("leftPanel")
        left_panel.setMinimumWidth(300)

        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(10)

        # Upload Button
        self.upload_btn = QPushButton("Upload Excel Files")

        # Dataset List
        self.dataset_list = QListWidget()

        left_layout.addWidget(QLabel("Datasets"))
        left_layout.addWidget(self.upload_btn)
        left_layout.addWidget(self.dataset_list)

        # =========================
        # Center Panel
        # =========================
        center_panel = QFrame()

        center_layout = QVBoxLayout(center_panel)
        center_layout.setSpacing(10)

        # User Requirement Input
        self.prompt_input = QTextEdit()
        self.prompt_input.setPlaceholderText(
            "Describe your analysis requirements..."
        )
        self.prompt_input.setMinimumHeight(120)

        # Run Button
        self.run_btn = QPushButton("Run Analysis")

        # Result Area
        self.result_output = QTextEdit()
        self.result_output.setReadOnly(True)

        center_layout.addWidget(QLabel("Analysis Request"))
        center_layout.addWidget(self.prompt_input)
        center_layout.addWidget(self.run_btn)
        center_layout.addWidget(QLabel("Results"))
        center_layout.addWidget(self.result_output)

        # =========================
        # Right Panel
        # =========================
        right_panel = QFrame()
        right_panel.setObjectName("rightPanel")
        right_panel.setMinimumWidth(320)

        right_layout = QVBoxLayout(right_panel)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)

        right_layout.addWidget(QLabel("Logs"))
        right_layout.addWidget(self.log_output)

        # =========================
        # Add Panels
        # =========================
        root_layout.addWidget(left_panel, 2)
        root_layout.addWidget(center_panel, 5)
        root_layout.addWidget(right_panel, 2)

        # =========================
        # Style
        # =========================
        self._apply_style()

    def _apply_style(self):
        """
        Apply basic stylesheet.
        """

        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }

            QFrame {
                background-color: white;
                border-radius: 10px;
            }

            QPushButton {
                height: 36px;
                font-size: 14px;
            }

            QTextEdit {
                font-size: 14px;
            }

            QListWidget {
                font-size: 14px;
            }

            QLabel {
                font-size: 14px;
                font-weight: bold;
            }
        """)