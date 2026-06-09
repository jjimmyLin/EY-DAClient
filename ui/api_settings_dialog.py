"""
ui/api_settings_dialog.py
Global API settings dialog.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config.devops_access import DEVOPS_DENIED_MESSAGE, is_devops_machine
from config.runtime_paths import env_file
from config.settings import settings


class ApiSettingsDialog(QDialog):
    """Dialog for Dify and machine-scoped DevOps configuration."""

    settings_saved = Signal()

    _PROVIDERS = [
        ("dify", "Dify"),
        ("gemini", "DevOps"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        settings.reload()
        self._devops_allowed = is_devops_machine()
        self._available_providers = [
            item
            for item in self._PROVIDERS
            if item[0] != "gemini" or self._devops_allowed
        ]
        self.setWindowTitle("API Settings")
        self.setModal(True)
        self.setMinimumWidth(540)

        self._provider_combo = QComboBox()
        self._provider_stack = QStackedWidget()
        self._status_labels: dict[str, QLabel] = {}

        self._dify_api_key = QLineEdit()
        self._dify_base_url = QLineEdit()
        self._dify_timeout = QLineEdit()

        self._devops_api_key = QLineEdit()
        self._devops_base_url = QLineEdit()
        self._devops_timeout = QLineEdit()

        self._init_ui()
        self._load_values()
        self._refresh_status()
        self._apply_style()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        header = QLabel(
            f"Settings are stored in {env_file()}\n"
            "The app uses Dify as the production analysis path."
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        if not self._devops_allowed:
            notice = QLabel(DEVOPS_DENIED_MESSAGE)
            notice.setObjectName("devopsDeniedNotice")
            notice.setWordWrap(True)
            layout.addWidget(notice)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        for provider, label in self._available_providers:
            self._provider_combo.addItem(label, provider)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("Active mode", self._provider_combo)
        layout.addLayout(form)

        for provider, _label in self._available_providers:
            if provider == "dify":
                self._provider_stack.addWidget(self._build_dify_page())
            elif provider == "gemini":
                self._provider_stack.addWidget(self._build_devops_page())
        layout.addWidget(self._provider_stack, stretch=1)

        status_group = QGroupBox("Configuration status")
        status_layout = QVBoxLayout(status_group)
        for provider, label in self._available_providers:
            title = QLabel(label)
            status = QLabel()
            status.setWordWrap(True)
            self._status_labels[provider] = status
            status_layout.addWidget(title)
            status_layout.addWidget(status)
        layout.addWidget(status_group)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_dify_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self._dify_api_key.setEchoMode(QLineEdit.Password)
        self._dify_base_url.setClearButtonEnabled(True)
        self._dify_timeout.setMaximumWidth(120)

        form.addRow("Dify API key", self._dify_api_key)
        form.addRow("Base URL", self._dify_base_url)
        form.addRow("Timeout (sec)", self._dify_timeout)

        note = QLabel(
            "The app calls Base URL + /workflows/run automatically."
        )
        note.setWordWrap(True)
        form.addRow(note)
        return page

    def _build_devops_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self._devops_api_key.setEchoMode(QLineEdit.Password)
        self._devops_base_url.setClearButtonEnabled(True)
        self._devops_timeout.setMaximumWidth(120)

        form.addRow("DevOps API key", self._devops_api_key)
        form.addRow("Base URL", self._devops_base_url)
        form.addRow("Timeout (sec)", self._devops_timeout)

        note = QLabel("Use this only for approved local debugging.")
        note.setWordWrap(True)
        form.addRow(note)
        return page

    def _load_values(self) -> None:
        selected_provider = settings.LLM_PROVIDER
        if selected_provider == "gemini" and not self._devops_allowed:
            selected_provider = "dify"

        for idx, (provider, _label) in enumerate(self._available_providers):
            if provider == selected_provider:
                self._provider_combo.setCurrentIndex(idx)
                self._provider_stack.setCurrentIndex(idx)
                break

        self._dify_api_key.setText(settings.DIFY_API_KEY)
        self._dify_base_url.setText(settings.DIFY_BASE_URL)
        self._dify_timeout.setText(str(settings.DIFY_TIMEOUT))

        self._devops_api_key.setText(settings.GEMINI_API_KEY)
        self._devops_base_url.setText(settings.GEMINI_BASE_URL)
        self._devops_timeout.setText(str(settings.GEMINI_TIMEOUT))

    def _refresh_status(self) -> None:
        settings.reload()
        status = settings.provider_status()
        friendly = {
            "dify": ("Dify", ("DIFY_API_KEY", "DIFY_BASE_URL")),
            "gemini": ("DevOps", ("GEMINI_API_KEY",)),
        }

        for provider, values in status.items():
            if provider not in self._status_labels:
                continue
            label, required = friendly[provider]
            missing = [
                key for key, present in values.items()
                if not present and key in required
            ]
            if missing:
                self._status_labels[provider].setText(
                    "Missing: " + ", ".join(missing)
                )
            else:
                self._status_labels[provider].setText(f"Ready for {label}")

    def _on_provider_changed(self, index: int) -> None:
        self._provider_stack.setCurrentIndex(index)

    def _save(self) -> None:
        provider = str(self._provider_combo.currentData())
        if provider == "gemini" and not self._devops_allowed:
            self._provider_combo.setCurrentIndex(0)
            self._provider_stack.setCurrentIndex(0)
            provider = "dify"

        updates = {
            "LLM_PROVIDER": provider,
            "DIFY_API_KEY": self._dify_api_key.text().strip(),
            "DIFY_BASE_URL": self._dify_base_url.text().strip(),
            "DIFY_TIMEOUT": self._dify_timeout.text().strip(),
            "GEMINI_API_KEY": self._devops_api_key.text().strip(),
            "GEMINI_MODEL": "gemini-3.5-flash",
            "GEMINI_BASE_URL": self._devops_base_url.text().strip(),
            "GEMINI_TIMEOUT": self._devops_timeout.text().strip(),
        }
        updates = {key: value for key, value in updates.items() if value != ""}
        settings.write_non_secret_env(updates)

        settings.reload()
        settings.update_runtime(
            provider=provider,
            gemini_model="gemini-3.5-flash",
        )
        self.settings_saved.emit()
        self.accept()

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QDialog {
                background-color: #FFFFFF;
                font-family: "Segoe UI";
            }
            QLabel {
                color: #3C4043;
                font-size: 12px;
            }
            QLineEdit,
            QComboBox {
                border: 1px solid #DADCE0;
                border-radius: 6px;
                padding: 6px 8px;
                min-height: 24px;
                color: #202124;
                background-color: #FFFFFF;
            }
            QLineEdit:focus,
            QComboBox:focus {
                border-color: #1A73E8;
            }
            QGroupBox {
                border: 1px solid #E8EAED;
                border-radius: 8px;
                margin-top: 10px;
                padding: 10px;
                color: #202124;
                font-weight: 600;
            }
            QPushButton {
                border-radius: 6px;
                padding: 6px 12px;
            }
            QLabel#devopsDeniedNotice {
                background-color: #FEF7E0;
                color: #5F4300;
                border: 1px solid #F9DE8B;
                border-radius: 6px;
                padding: 8px 10px;
                font-weight: 600;
            }
        """)
