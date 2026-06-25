"""Data-first landing page with restrained, task-oriented motion."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    Qt,
    Signal,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


SUPPORTED_DATASET_SUFFIXES = {".xlsx", ".xls", ".xlsm"}


class DatasetDropZone(QFrame):
    clicked = Signal()
    files_dropped = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("datasetDropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(148)
        self.setAccessibleName("Add Excel datasets")
        self.setToolTip("Select Excel workbooks or drag them into this area")

        self._hover_t = 0.0
        self._hover_animation = QVariantAnimation(self)
        self._hover_animation.setDuration(150)
        self._hover_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_animation.valueChanged.connect(self._apply_hover_value)
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(10)
        self._shadow.setOffset(0, 3)
        self._shadow.setColor(QColor(15, 23, 42, 14))
        self.setGraphicsEffect(self._shadow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 22, 32, 22)
        layout.setSpacing(6)

        self.signal_label = QLabel("+")
        self.signal_label.setObjectName("portalDropGlyph")
        self.signal_label.setAlignment(Qt.AlignCenter)

        self.title_label = QLabel("Add Excel datasets")
        self.title_label.setObjectName("portalDropTitle")
        self.title_label.setAlignment(Qt.AlignCenter)

        note = QLabel("Click to browse, or drag and drop files here")
        note.setObjectName("portalDropNote")
        note.setAlignment(Qt.AlignCenter)

        limit = QLabel(".xlsx · .xls · .xlsm   |   up to 2 GB per file")
        limit.setObjectName("portalDropLimit")
        limit.setAlignment(Qt.AlignCenter)

        layout.addStretch()
        layout.addWidget(self.signal_label)
        layout.addWidget(self.title_label)
        layout.addWidget(note)
        layout.addWidget(limit)
        layout.addStretch()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.clicked.emit()
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:
        if self.isEnabled():
            self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate_hover(0.0)
        super().leaveEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self.isEnabled() and self._accepted_paths(event.mimeData().urls()):
            self.setProperty("dragActive", True)
            self.style().unpolish(self)
            self.style().polish(self)
            self._animate_hover(1.0)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._set_drag_inactive()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = self._accepted_paths(event.mimeData().urls())
        self._set_drag_inactive()
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()

    def _animate_hover(self, target: float) -> None:
        self._hover_animation.stop()
        self._hover_animation.setStartValue(self._hover_t)
        self._hover_animation.setEndValue(target)
        self._hover_animation.start()

    def _apply_hover_value(self, value) -> None:
        self._hover_t = float(value)
        self._shadow.setBlurRadius(10 + 10 * self._hover_t)
        self._shadow.setOffset(0, 3 + 2 * self._hover_t)
        self._shadow.setColor(
            QColor(26, 115, 232, int(14 + 18 * self._hover_t))
        )

    def _set_drag_inactive(self) -> None:
        self.setProperty("dragActive", False)
        self.style().unpolish(self)
        self.style().polish(self)
        self._animate_hover(0.0)

    @staticmethod
    def _accepted_paths(urls) -> list[str]:
        return [
            url.toLocalFile()
            for url in urls
            if url.isLocalFile()
            and Path(url.toLocalFile()).suffix.lower() in SUPPORTED_DATASET_SUFFIXES
        ]


class PortalTip(QFrame):
    def __init__(self, title: str, description: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("portalTip")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(3)
        title_label = QLabel(title)
        title_label.setObjectName("portalTipTitle")
        description_label = QLabel(description)
        description_label.setObjectName("portalTipDescription")
        description_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(description_label)


class DataPortalPage(QWidget):
    add_requested = Signal()
    files_dropped = Signal(list)
    analysis_requested = Signal()
    cleaning_requested = Signal()
    library_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("dataPortalPage")
        self._ready_count = 0
        self._entrance_played = False

        root = QVBoxLayout(self)
        root.setContentsMargins(56, 28, 56, 28)
        root.setSpacing(0)
        root.addStretch()

        self.content = QWidget()
        self.content.setObjectName("portalContent")
        self.content.setMaximumWidth(780)
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        eyebrow = QLabel("DATA WORKSPACE")
        eyebrow.setObjectName("portalEyebrow")
        eyebrow.setAlignment(Qt.AlignCenter)
        title = QLabel("Start with your data")
        title.setObjectName("portalTitle")
        title.setAlignment(Qt.AlignCenter)
        subtitle = QLabel(
            "Import the workbooks you want to clean or analyze. "
            "Your full data stays in the local processing workflow."
        )
        subtitle.setObjectName("portalSubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setWordWrap(True)
        content_layout.addWidget(eyebrow)
        content_layout.addWidget(title)
        content_layout.addWidget(subtitle)
        content_layout.addSpacing(6)

        self.primary_row = QWidget()
        self.primary_row.setObjectName("portalPrimaryRow")
        primary_layout = QHBoxLayout(self.primary_row)
        primary_layout.setContentsMargins(0, 0, 0, 0)
        primary_layout.setSpacing(16)

        self.drop_zone = DatasetDropZone()
        self.drop_zone.clicked.connect(self.add_requested)
        self.drop_zone.files_dropped.connect(self.files_dropped)

        self.capability_panel = QFrame()
        self.capability_panel.setObjectName("capabilityPanel")
        self.capability_panel.setMaximumWidth(0)
        capability_layout = QVBoxLayout(self.capability_panel)
        capability_layout.setContentsMargins(4, 12, 0, 12)
        capability_layout.setSpacing(4)
        prompt = QLabel("CHOOSE A MODE")
        prompt.setObjectName("portalCapabilityPrompt")
        self.analysis_card = QPushButton("Analyze")
        self.analysis_card.setObjectName("portalModeAction")
        self.analysis_card.setCursor(Qt.PointingHandCursor)
        self.cleaning_card = QPushButton("Clean")
        self.cleaning_card.setObjectName("portalModeAction")
        self.cleaning_card.setCursor(Qt.PointingHandCursor)
        self.analysis_card.clicked.connect(self.analysis_requested)
        self.cleaning_card.clicked.connect(self.cleaning_requested)
        capability_layout.addStretch()
        capability_layout.addWidget(prompt)
        capability_layout.addSpacing(4)
        capability_layout.addWidget(self.analysis_card)
        capability_layout.addWidget(self.cleaning_card)
        capability_layout.addStretch()

        primary_layout.addWidget(self.drop_zone, stretch=1)
        primary_layout.addWidget(self.capability_panel)
        content_layout.addWidget(self.primary_row)

        self.import_progress = QProgressBar()
        self.import_progress.setObjectName("portalProgress")
        self.import_progress.setTextVisible(False)
        self.import_progress.setVisible(False)
        content_layout.addWidget(self.import_progress)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(2, 0, 2, 0)
        self.status_label = QLabel("Ready for your first dataset")
        self.status_label.setObjectName("portalStatus")
        self.library_button = QPushButton("View datasets")
        self.library_button.setObjectName("portalLibraryButton")
        self.library_button.setCursor(Qt.PointingHandCursor)
        self.library_button.clicked.connect(self.library_requested)
        self.library_button.setVisible(False)
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        status_row.addWidget(self.library_button)
        content_layout.addLayout(status_row)

        tips_header = QLabel("HOW FILES ARE HANDLED")
        tips_header.setObjectName("portalTipsHeader")
        content_layout.addWidget(tips_header)

        self.tips_panel = QFrame()
        self.tips_panel.setObjectName("portalTipsPanel")
        tips_layout = QHBoxLayout(self.tips_panel)
        tips_layout.setContentsMargins(0, 0, 0, 0)
        tips_layout.setSpacing(8)
        tips = [
            (
                "Small files stay interactive",
                "Excel files under 100 MB are prepared for quick, "
                "responsive analysis.",
            ),
            (
                "Large files continue in the background",
                "Files from 100 MB up to 2 GB use guarded background "
                "processing so the app remains usable.",
            ),
            (
                "Select the scope that matches your task",
                "Analyze up to 3 workbooks together. Cleaning works on "
                "one workbook at a time.",
            ),
        ]
        for title, description in tips:
            tips_layout.addWidget(PortalTip(title, description), stretch=1)
        content_layout.addWidget(self.tips_panel)

        self.capability_panel.setVisible(False)

        root.addWidget(self.content, alignment=Qt.AlignHCenter)
        root.addStretch()

        self._capability_opacity = QGraphicsOpacityEffect(self.capability_panel)
        self.capability_panel.setGraphicsEffect(self._capability_opacity)
        self._ready_layout_t = 0.0
        self._layout_animation = QVariantAnimation(self)
        self._layout_animation.setDuration(240)
        self._layout_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._layout_animation.valueChanged.connect(
            self._apply_ready_layout_progress
        )
        self._layout_animation.finished.connect(
            self._finish_ready_layout_animation
        )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._entrance_played = True

    def set_import_progress(self, label: str, percent: int) -> None:
        self.import_progress.setVisible(True)
        self.import_progress.setRange(0, 100)
        self.import_progress.setValue(percent)
        self.status_label.setText(f"{label} · {percent}%")
        self.drop_zone.setEnabled(False)

    def set_library_state(self, ready_count: int, pending_count: int = 0) -> None:
        self._ready_count = ready_count
        self.drop_zone.setEnabled(pending_count == 0)
        self.library_button.setVisible(ready_count + pending_count > 0)

        if pending_count:
            self.status_label.setText(
                f"{ready_count} ready · {pending_count} processing"
            )
        else:
            self.import_progress.setVisible(False)
            self.status_label.setText(
                "Ready for your first dataset"
                if ready_count == 0
                else f"{ready_count} dataset"
                f"{'s' if ready_count != 1 else ''} ready"
            )

        should_show = ready_count > 0
        self._animate_ready_layout(should_show)

    def _animate_ready_layout(self, ready: bool) -> None:
        target = 1.0 if ready else 0.0
        if abs(self._ready_layout_t - target) < 0.001:
            self._apply_ready_layout_progress(target)
            self._finish_ready_layout_animation()
            return
        if ready:
            self.capability_panel.setVisible(True)
        self._layout_animation.stop()
        self._layout_animation.setStartValue(self._ready_layout_t)
        self._layout_animation.setEndValue(target)
        self._layout_animation.start()

    def _apply_ready_layout_progress(self, value) -> None:
        self._ready_layout_t = float(value)
        self.drop_zone.setMaximumWidth(
            int(780 - (780 - 520) * self._ready_layout_t)
        )
        self.capability_panel.setMaximumWidth(
            int(244 * self._ready_layout_t)
        )
        self._capability_opacity.setOpacity(self._ready_layout_t)

    def _finish_ready_layout_animation(self) -> None:
        if self._ready_layout_t < 0.001:
            self.capability_panel.setVisible(False)


DATA_PORTAL_STYLE = """
QWidget#dataPortalPage { background: #ffffff; }
QWidget#portalContent { background: transparent; }
QLabel#portalEyebrow {
    color: #1a73e8; font-size: 9px; font-weight: 700; letter-spacing: 1px;
}
QLabel#portalTitle { color: #202124; font-size: 28px; font-weight: 650; }
QLabel#portalSubtitle { color: #5f6368; font-size: 12px; font-weight: 400; }
QFrame#datasetDropZone {
    background: #fafbfc; border: 1px dashed #aeb4bc; border-radius: 14px;
}
QFrame#datasetDropZone:hover, QFrame#datasetDropZone[dragActive="true"] {
    background: #f3f7fd; border: 2px solid #1a73e8;
}
QFrame#datasetDropZone:disabled {
    background: #f8f9fa; border-color: #d6d9dd;
}
QLabel#portalDropGlyph {
    color: #1a73e8; font-size: 26px; font-weight: 400;
}
QLabel#portalDropTitle { color: #202124; font-size: 15px; font-weight: 600; }
QLabel#portalDropNote { color: #5f6368; font-size: 11px; font-weight: 400; }
QLabel#portalDropLimit { color: #8a9097; font-size: 9px; font-weight: 500; }
QLabel#portalStatus { color: #5f6368; font-size: 10px; font-weight: 500; }
QPushButton#portalLibraryButton {
    color: #1a73e8; background: transparent; border: none;
    padding: 4px 0; font-size: 10px; font-weight: 600;
}
QPushButton#portalLibraryButton:hover { color: #174ea6; }
QProgressBar#portalProgress {
    min-height: 4px; max-height: 4px; border: none;
    background: #e5e7eb; border-radius: 2px;
}
QProgressBar#portalProgress::chunk { background: #1a73e8; border-radius: 2px; }
QLabel#portalTipsHeader {
    color: #8a9097; font-size: 8px; font-weight: 700; letter-spacing: 1px;
}
QFrame#portalTipsPanel {
    background: transparent; border: none;
}
QFrame#portalTip {
    background: #f8f9fa; border: 1px solid #e8eaed; border-radius: 9px;
}
QLabel#portalTipTitle { color: #202124; font-size: 10px; font-weight: 650; }
QLabel#portalTipDescription {
    color: #6b7280; font-size: 9px; font-weight: 400;
}
QLabel#portalCapabilityPrompt {
    color: #8a9097; font-size: 8px; font-weight: 700; letter-spacing: 1px;
}
QFrame#capabilityPanel {
    background: transparent; border: none;
}
QPushButton#portalModeAction {
    text-align: left; color: #202124; background: transparent;
    border: none; border-bottom: 1px solid #e8eaed;
    padding: 10px 4px; font-size: 18px; font-weight: 600;
}
QPushButton#portalModeAction:hover {
    color: #1a73e8; border-bottom-color: #aecbfa;
}
QPushButton#portalModeAction:pressed { color: #174ea6; }
"""
