"""
ui/api_settings_dialog.py
Global API settings dialog.
"""

from __future__ import annotations

from urllib.parse import urlparse

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
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
        self.setMinimumSize(540, 480)
        self.resize(640, 680)

        self._provider_combo = QComboBox()
        self._provider_stack = QStackedWidget()
        self._status_labels: dict[str, QLabel] = {}

        self._dify_api_key = QLineEdit()
        self._dify_base_url = QLineEdit()
        self._dify_timeout = QLineEdit()
        self._metric_api_key = QLineEdit()
        self._metric_base_url = QLineEdit()
        self._metric_timeout = QLineEdit()
        self._company_resolution_api_key = QLineEdit()
        self._company_resolution_base_url = QLineEdit()
        self._company_resolution_timeout = QLineEdit()

        self._devops_api_key = QLineEdit()
        self._devops_base_url = QLineEdit()
        self._devops_timeout = QLineEdit()

        self._init_ui()
        self._load_values()
        self._refresh_status()
        self._apply_style()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        scroll = QScrollArea()
        scroll.setObjectName("apiSettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)

        content = QWidget()
        content.setObjectName("apiSettingsContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 8, 0)
        content_layout.setSpacing(16)

        header = QLabel(
            f"Settings are stored in {env_file()}\n"
            "The app uses Dify as the production analysis path."
        )
        header.setWordWrap(True)
        content_layout.addWidget(header)

        if not self._devops_allowed:
            notice = QLabel(DEVOPS_DENIED_MESSAGE)
            notice.setObjectName("devopsDeniedNotice")
            notice.setWordWrap(True)
            content_layout.addWidget(notice)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        for provider, label in self._available_providers:
            self._provider_combo.addItem(label, provider)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("Active mode", self._provider_combo)
        content_layout.addLayout(form)

        for provider, _label in self._available_providers:
            if provider == "dify":
                self._provider_stack.addWidget(self._build_dify_page())
            elif provider == "gemini":
                self._provider_stack.addWidget(self._build_devops_page())
        content_layout.addWidget(self._provider_stack)

        status_group = QGroupBox("Configuration status")
        status_layout = QVBoxLayout(status_group)
        for provider, label in self._available_providers:
            title = QLabel(label)
            status = QLabel()
            status.setWordWrap(True)
            self._status_labels[provider] = status
            status_layout.addWidget(title)
            status_layout.addWidget(status)
        content_layout.addWidget(status_group)
        content_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)

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
        self._metric_api_key.setEchoMode(QLineEdit.Password)
        self._metric_base_url.setClearButtonEnabled(True)
        self._metric_timeout.setMaximumWidth(120)
        self._company_resolution_api_key.setEchoMode(QLineEdit.Password)
        self._company_resolution_base_url.setClearButtonEnabled(True)
        self._company_resolution_timeout.setMaximumWidth(120)

        form.addRow("Analysis API key", self._dify_api_key)
        form.addRow("Analysis base URL", self._dify_base_url)
        form.addRow("Analysis timeout (sec)", self._dify_timeout)

        note = QLabel(
            "Business indicators use a separate Dify Workflow app. "
            "Its Start node must define request_payload (Paragraph) and "
            "reference_files (optional File List)."
        )
        note.setWordWrap(True)
        form.addRow(note)
        form.addRow("Indicator API key", self._metric_api_key)
        form.addRow("Indicator base URL", self._metric_base_url)
        form.addRow("Indicator timeout (sec)", self._metric_timeout)
        resolution_note = QLabel(
            "Company resolution runs before indicator generation when "
            "enterprise intelligence is enabled and a company name is present."
        )
        resolution_note.setWordWrap(True)
        form.addRow(resolution_note)
        form.addRow(
            "Company resolution API key",
            self._company_resolution_api_key,
        )
        form.addRow(
            "Company resolution base URL",
            self._company_resolution_base_url,
        )
        form.addRow(
            "Company resolution timeout (sec)",
            self._company_resolution_timeout,
        )
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
        self._metric_api_key.setText(settings.DIFY_METRIC_API_KEY)
        self._metric_base_url.setText(settings.DIFY_METRIC_BASE_URL)
        self._metric_timeout.setText(str(settings.DIFY_METRIC_TIMEOUT))
        self._company_resolution_api_key.setText(
            settings.DIFY_COMPANY_RESOLUTION_API_KEY
        )
        self._company_resolution_base_url.setText(
            settings.DIFY_COMPANY_RESOLUTION_BASE_URL
        )
        self._company_resolution_timeout.setText(
            str(settings.DIFY_COMPANY_RESOLUTION_TIMEOUT)
        )

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
        metric_missing = [
            key
            for key, present in settings.metric_workflow_status().items()
            if not present
        ]
        dify_status = self._status_labels.get("dify")
        if dify_status is not None:
            suffix = (
                "Indicator workflow missing: " + ", ".join(metric_missing)
                if metric_missing
                else "Indicator workflow ready"
            )
            dify_status.setText(f"{dify_status.text()}\n{suffix}")
            resolution_missing = [
                key
                for key, present in (
                    settings.company_resolution_workflow_status().items()
                )
                if not present
            ]
            resolution_suffix = (
                "Company resolution missing: "
                + ", ".join(resolution_missing)
                if resolution_missing
                else "Company resolution ready"
            )
            dify_status.setText(
                f"{dify_status.text()}\n{resolution_suffix}"
            )

    def _on_provider_changed(self, index: int) -> None:
        self._provider_stack.setCurrentIndex(index)

    def _save(self) -> None:
        provider = str(self._provider_combo.currentData())
        if provider == "gemini" and not self._devops_allowed:
            self._provider_combo.setCurrentIndex(0)
            self._provider_stack.setCurrentIndex(0)
            provider = "dify"

        devops_api_key = self._devops_api_key.text().strip()
        dify_base_url = self._dify_base_url.text().strip().rstrip("/")
        if not self._valid_base_url(dify_base_url):
            QMessageBox.warning(
                self,
                "Invalid Base URL",
                "Enter the Dify API base URL, for example "
                "https://host.example/v1. Do not include /workflows/run.",
            )
            self._dify_base_url.setFocus()
            return
        metric_base_url = self._metric_base_url.text().strip().rstrip("/")
        if not self._valid_base_url(metric_base_url):
            QMessageBox.warning(
                self,
                "Invalid Indicator Base URL",
                "Enter the indicator Dify API base URL, for example "
                "https://host.example/v1. Do not include /workflows/run.",
            )
            self._metric_base_url.setFocus()
            return
        company_resolution_base_url = (
            self._company_resolution_base_url.text().strip().rstrip("/")
        )
        if not self._valid_base_url(company_resolution_base_url):
            QMessageBox.warning(
                self,
                "Invalid Company Resolution Base URL",
                "Enter the company-resolution Dify API base URL, for example "
                "https://host.example/v1. Do not include /workflows/run.",
            )
            self._company_resolution_base_url.setFocus()
            return

        try:
            dify_timeout = self._positive_integer(
                self._dify_timeout.text(),
                "Dify timeout",
            )
            devops_timeout = self._positive_integer(
                self._devops_timeout.text(),
                "DevOps timeout",
            )
            metric_timeout = self._positive_integer(
                self._metric_timeout.text(),
                "Indicator timeout",
            )
            company_resolution_timeout = self._positive_integer(
                self._company_resolution_timeout.text(),
                "Company resolution timeout",
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid timeout", str(exc))
            return

        if provider == "gemini":
            try:
                settings.validate_gemini_api_key(devops_api_key)
            except ValueError as exc:
                QMessageBox.warning(self, "Invalid API key", str(exc))
                self._devops_api_key.setFocus()
                return

        updates = {
            "LLM_PROVIDER": provider,
            "DIFY_API_KEY": self._dify_api_key.text().strip(),
            "DIFY_BASE_URL": dify_base_url,
            "DIFY_TIMEOUT": str(dify_timeout),
            "DIFY_METRIC_API_KEY": self._metric_api_key.text().strip(),
            "DIFY_METRIC_BASE_URL": metric_base_url,
            "DIFY_METRIC_TIMEOUT": str(metric_timeout),
            "DIFY_COMPANY_RESOLUTION_API_KEY": (
                self._company_resolution_api_key.text().strip()
            ),
            "DIFY_COMPANY_RESOLUTION_BASE_URL": (
                company_resolution_base_url
            ),
            "DIFY_COMPANY_RESOLUTION_TIMEOUT": str(
                company_resolution_timeout
            ),
            "GEMINI_API_KEY": devops_api_key,
            "GEMINI_MODEL": "gemini-3.5-flash",
            "GEMINI_BASE_URL": self._devops_base_url.text().strip(),
            "GEMINI_TIMEOUT": str(devops_timeout),
        }
        settings.write_non_secret_env(updates)

        settings.reload()
        settings.update_runtime(
            provider=provider,
            gemini_model="gemini-3.5-flash",
        )
        self.settings_saved.emit()
        self.accept()

    @staticmethod
    def _positive_integer(value: str, label: str) -> int:
        try:
            number = int(value.strip())
        except ValueError as exc:
            raise ValueError(f"{label} must be a whole number.") from exc
        if number <= 0:
            raise ValueError(f"{label} must be greater than zero.")
        return number

    @staticmethod
    def _valid_base_url(value: str) -> bool:
        parsed = urlparse(value)
        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.netloc)
            and not parsed.path.rstrip("/").endswith("/workflows/run")
        )

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QDialog {
                background-color: #FFFFFF;
                font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
            }
            QScrollArea#apiSettingsScroll,
            QWidget#apiSettingsContent,
            QScrollArea#apiSettingsScroll QWidget#qt_scrollarea_viewport {
                background-color: #FFFFFF;
                border: none;
            }
            QScrollBar:vertical {
                background: #F5F7FA;
                width: 10px;
                margin: 0;
                border: none;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #C8D0DA;
                min-height: 32px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #9FAAB7;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0;
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
