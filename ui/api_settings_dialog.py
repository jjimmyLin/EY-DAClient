"""
ui/api_settings_dialog.py
─────────────────────────
Global API provider settings dialog.

Secrets are intentionally not edited here. Users add keys to .env manually;
this dialog only writes non-secret provider/model choices.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config.settings import settings


class ApiSettingsDialog(QDialog):
    """Dialog for global LLM provider/model selection."""

    settings_saved = Signal()

    _PROVIDERS = [
        ("dify", "Dify (original workflow)"),
        ("gemini", "Google Gemini"),
        ("deepseek", "DeepSeek"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        settings.reload()
        self.setWindowTitle("API Settings")
        self.setModal(True)
        self.setMinimumWidth(460)

        self._provider_combo = QComboBox()
        self._gemini_model_combo = QComboBox()
        self._deepseek_model_combo = QComboBox()
        self._provider_stack = QStackedWidget()
        self._status_labels: dict[str, QLabel] = {}

        self._init_ui()
        self._load_values()
        self._refresh_status()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        form = QFormLayout()
        for provider, label in self._PROVIDERS:
            self._provider_combo.addItem(label, provider)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("Provider", self._provider_combo)
        layout.addLayout(form)

        self._provider_stack.addWidget(self._build_dify_page())
        self._provider_stack.addWidget(self._build_gemini_page())
        self._provider_stack.addWidget(self._build_deepseek_page())
        layout.addWidget(self._provider_stack)

        status_group = QGroupBox("Configuration status")
        status_layout = QVBoxLayout(status_group)
        for provider, label in self._PROVIDERS:
            status = QLabel()
            status.setWordWrap(True)
            self._status_labels[provider] = status
            status_layout.addWidget(QLabel(label))
            status_layout.addWidget(status)
        layout.addWidget(status_group)

        note = QLabel(
            "API keys are read from .env and are not shown or saved by this dialog."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_dify_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        text = QLabel(
            "Uses DIFY_API_KEY and DIFY_WEBHOOK_URL from .env. No model is "
            "configured here because Dify owns the workflow/provider routing."
        )
        text.setWordWrap(True)
        layout.addWidget(text)
        return page

    def _build_gemini_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self._gemini_model_combo.setEditable(True)
        for model in self._unique([
            settings.GEMINI_MODEL,
            "gemini-3.5-flash",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
        ]):
            self._gemini_model_combo.addItem(model)
        form.addRow("Model", self._gemini_model_combo)
        return page

    def _build_deepseek_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self._deepseek_model_combo.setEditable(True)
        for model in self._unique([
            settings.DEEPSEEK_MODEL,
            "deepseek-v4-flash",
            "deepseek-v4-pro",
        ]):
            self._deepseek_model_combo.addItem(model)
        form.addRow("Model", self._deepseek_model_combo)
        return page

    def _load_values(self) -> None:
        for idx, (provider, _label) in enumerate(self._PROVIDERS):
            if provider == settings.LLM_PROVIDER:
                self._provider_combo.setCurrentIndex(idx)
                self._provider_stack.setCurrentIndex(idx)
                break
        self._gemini_model_combo.setCurrentText(settings.GEMINI_MODEL)
        self._deepseek_model_combo.setCurrentText(settings.DEEPSEEK_MODEL)

    def _refresh_status(self) -> None:
        settings.reload()
        status = settings.provider_status()
        for provider, values in status.items():
            missing = [key for key, present in values.items() if not present]
            if missing:
                self._status_labels[provider].setText(
                    "Missing in .env: " + ", ".join(missing)
                )
            else:
                self._status_labels[provider].setText("Ready")

    def _on_provider_changed(self, index: int) -> None:
        self._provider_stack.setCurrentIndex(index)

    def _save(self) -> None:
        provider = self._provider_combo.currentData()
        gemini_model = self._gemini_model_combo.currentText().strip()
        deepseek_model = self._deepseek_model_combo.currentText().strip()

        updates = {"LLM_PROVIDER": provider}
        if gemini_model:
            updates["GEMINI_MODEL"] = gemini_model
        if deepseek_model:
            updates["DEEPSEEK_MODEL"] = deepseek_model
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
