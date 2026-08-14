"""Application-wide font configuration for the Chinese Windows UI."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication


CHINESE_UI_FONT_FAMILIES = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "Segoe UI",
    "sans-serif",
)


def configure_application_font(app: QApplication) -> None:
    """Apply explicit Chinese UI fallbacks without changing the system size."""
    font = app.font()
    font.setFamilies(list(CHINESE_UI_FONT_FAMILIES[:-1]))
    app.setFont(font)
