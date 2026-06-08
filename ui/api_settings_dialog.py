"""
ui/api_settings_dialog.py
Global API settings dialog.

Primary goal:
- keep Dify as the default production path
- make DevOps/Gemini available, but clearly secondary
- allow editing the actual connection fields from the UI
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config.runtime_paths import env_file
from config.settings import settings


class ApiSettingsDialog(QDialog):
    """Dialog for provider selection and API configuration."""

    settings_saved = Signal()

    _PROVIDERS = [
        ("dify", "Dify"),
        ("gemini", "Gemini DevOps"),
        ("deepseek", "DeepSeek"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        settings.reload()
        self.setWindowTitle("API Settings")
        self.setModal(True)
        self.setMinimumWidth(540)

        self._provider_combo = QComboBox()
        self._provider_stack = QStackedWidget()
        self._status_labels: dict[str, QLabel] = {}

        self._dify_api_key = QLineEdit()
        self._dify_webhook_url = QLineEdit()
        self._dify_base_url = QLineEdit()
        self._dify_timeout = QLineEdit()

        self._gemini_api_key = QLineEdit()
        self._gemini_model = QComboBox()
        self._gemini_base_url = QLineEdit()
        self._gemini_timeout = QLineEdit()

        self._deepseek_api_key = QLineEdit()
        self._deepseek_model = QComboBox()
        self._deepseek_base_url = QLineEdit()
        self._deepseek_timeout = QLineEdit()

        self._init_ui()
        self._load_values()
        self._refresh_status()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        header = QLabel(
            f"Settings are stored in {env_file()}\n"
            "Dify is the default product path. Gemini is kept as DevOps mode."
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        for provider, label in self._PROVIDERS:
            self._provider_combo.addItem(label, provider)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("Active mode", self._provider_combo)
        layout.addLayout(form)

        self._provider_stack.addWidget(self._build_dify_page())
        self._provider_stack.addWidget(self._build_gemini_page())
        self._provider_stack.addWidget(self._build_deepseek_page())
        layout.addWidget(self._provider_stack, stretch=1)

        status_group = QGroupBox("Configuration status")
        status_layout = QVBoxLayout(status_group)
        for provider, label in self._PROVIDERS:
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
        self._dify_webhook_url.setClearButtonEnabled(True)
        self._dify_base_url.setClearButtonEnabled(True)
        self._dify_timeout.setMaximumWidth(120)

        form.addRow("Dify API key", self._dify_api_key)
        form.addRow("Webhook URL", self._dify_webhook_url)
        form.addRow("Base URL", self._dify_base_url)
        form.addRow("Timeout (sec)", self._dify_timeout)

        note = QLabel("This is the primary workflow. The app sends dataset metadata and your query to Dify.")
        note.setWordWrap(True)
        form.addRow(note)
        return page

    def _build_gemini_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self._gemini_api_key.setEchoMode(QLineEdit.Password)
        self._gemini_model.setEditable(True)
        self._gemini_base_url.setClearButtonEnabled(True)
        self._gemini_timeout.setMaximumWidth(120)

        for model in self._unique([
            settings.GEMINI_MODEL,
            "gemini-3.5-flash",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
        ]):
            self._gemini_model.addItem(model)

        form.addRow("Gemini API key", self._gemini_api_key)
        form.addRow("Model", self._gemini_model)
        form.addRow("Base URL", self._gemini_base_url)
        form.addRow("Timeout (sec)", self._gemini_timeout)

        note = QLabel("Use this only for DevOps/debugging the API flow.")
        note.setWordWrap(True)
        form.addRow(note)
        return page

    def _build_deepseek_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self._deepseek_api_key.setEchoMode(QLineEdit.Password)
        self._deepseek_model.setEditable(True)
        self._deepseek_base_url.setClearButtonEnabled(True)
        self._deepseek_timeout.setMaximumWidth(120)

        for model in self._unique([
            settings.DEEPSEEK_MODEL,
            "deepseek-v4-flash",
            "deepseek-v4-pro",
        ]):
            self._deepseek_model.addItem(model)

        form.addRow("DeepSeek API key", self._deepseek_api_key)
        form.addRow("Model", self._deepseek_model)
        form.addRow("Base URL", self._deepseek_base_url)
        form.addRow("Timeout (sec)", self._deepseek_timeout)
        return page

    def _load_values(self) -> None:
        for idx, (provider, _label) in enumerate(self._PROVIDERS):
            if provider == settings.LLM_PROVIDER:
                self._provider_combo.setCurrentIndex(idx)
                self._provider_stack.setCurrentIndex(idx)
                break

        self._dify_api_key.setText(settings.DIFY_API_KEY)
        self._dify_webhook_url.setText(settings.DIFY_WEBHOOK_URL)
        self._dify_base_url.setText(settings.DIFY_BASE_URL)
        self._dify_timeout.setText(str(settings.DIFY_TIMEOUT))

        self._gemini_api_key.setText(settings.GEMINI_API_KEY)
        self._gemini_model.setCurrentText(settings.GEMINI_MODEL)
        self._gemini_base_url.setText(settings.GEMINI_BASE_URL)
        self._gemini_timeout.setText(str(settings.GEMINI_TIMEOUT))

        self._deepseek_api_key.setText(settings.DEEPSEEK_API_KEY)
        self._deepseek_model.setCurrentText(settings.DEEPSEEK_MODEL)
        self._deepseek_base_url.setText(settings.DEEPSEEK_BASE_URL)
        self._deepseek_timeout.setText(str(settings.DEEPSEEK_TIMEOUT))

    def _refresh_status(self) -> None:
        settings.reload()
        status = settings.provider_status()
        friendly = {
            "dify": ("Dify primary mode", ("DIFY_API_KEY", "DIFY_WEBHOOK_URL")),
            "gemini": ("Gemini DevOps mode", ("GEMINI_API_KEY",)),
            "deepseek": ("DeepSeek mode", ("DEEPSEEK_API_KEY",)),
        }

        for provider, values in status.items():
            label, required = friendly[provider]
            missing = [key for key, present in values.items() if not present and key in required]
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
        gemini_model = self._gemini_model.currentText().strip()
        deepseek_model = self._deepseek_model.currentText().strip()

        updates = {
            "LLM_PROVIDER": provider,
            "DIFY_API_KEY": self._dify_api_key.text().strip(),
            "DIFY_WEBHOOK_URL": self._dify_webhook_url.text().strip(),
            "DIFY_BASE_URL": self._dify_base_url.text().strip(),
            "DIFY_TIMEOUT": self._dify_timeout.text().strip(),
            "GEMINI_API_KEY": self._gemini_api_key.text().strip(),
            "GEMINI_MODEL": gemini_model,
            "GEMINI_BASE_URL": self._gemini_base_url.text().strip(),
            "GEMINI_TIMEOUT": self._gemini_timeout.text().strip(),
            "DEEPSEEK_API_KEY": self._deepseek_api_key.text().strip(),
            "DEEPSEEK_MODEL": deepseek_model,
            "DEEPSEEK_BASE_URL": self._deepseek_base_url.text().strip(),
            "DEEPSEEK_TIMEOUT": self._deepseek_timeout.text().strip(),
        }
        updates = {key: value for key, value in updates.items() if value != ""}
        settings.write_non_secret_env(updates)

        settings.reload()
        settings.update_runtime(
            provider=provider,
            gemini_model=gemini_model,
            deepseek_model=deepseek_model,
        )
        self.settings_saved.emit()
        self.accept()

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result
