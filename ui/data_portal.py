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
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

SUPPORTED_DATASET_SUFFIXES = {".xlsx", ".xls", ".xlsm"}
MAX_DATASET_BYTES = 1 * 1024 * 1024 * 1024


class DatasetDropZone(QFrame):
    clicked = Signal()
    files_dropped = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("datasetDropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(160)
        
        # Default state text
        self._default_title = "Add Excel datasets"
        self._default_glyph = "+"

        self._hover_t = 0.0
        self._drag_state = "none" # none, valid, invalid
        
        self._hover_animation = QVariantAnimation(self)
        self._hover_animation.setDuration(200)
        self._hover_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_animation.valueChanged.connect(self._apply_hover_value)
        
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(10)
        self._shadow.setOffset(0, 3)
        self._shadow.setColor(QColor(15, 23, 42, 14))
        self.setGraphicsEffect(self._shadow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(8)

        self.signal_label = QLabel(self._default_glyph)
        self.signal_label.setObjectName("portalDropGlyph")
        self.signal_label.setAlignment(Qt.AlignCenter)

        self.title_label = QLabel(self._default_title)
        self.title_label.setObjectName("portalDropTitle")
        self.title_label.setAlignment(Qt.AlignCenter)

        self.note_label = QLabel("Click to browse, or drag and drop files here")
        self.note_label.setObjectName("portalDropNote")
        self.note_label.setAlignment(Qt.AlignCenter)

        self.limit_label = QLabel(".xlsx · .xls · .xlsm   |   up to 1 GB per file")
        self.limit_label.setObjectName("portalDropLimit")
        self.limit_label.setAlignment(Qt.AlignCenter)

        layout.addStretch()
        layout.addWidget(self.signal_label)
        layout.addWidget(self.title_label)
        layout.addWidget(self.note_label)
        layout.addWidget(self.limit_label)
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
        if not self.isEnabled():
            return
            
        urls = event.mimeData().urls()
        paths = self._local_paths(urls)
        if paths and not self._validation_errors(paths):
            self._drag_state = "valid"
            self.setProperty("dragState", "valid")
        else:
            self._drag_state = "invalid"
            self.setProperty("dragState", "invalid")
            self.title_label.setText("File cannot be imported")
            self.signal_label.setText("×")

        self._refresh_style()
        self._animate_hover(1.0)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._reset_drag_state()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = self._local_paths(event.mimeData().urls())
        self._reset_drag_state()
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
        self._shadow.setBlurRadius(10 + 15 * self._hover_t)
        self._shadow.setOffset(0, 3 + 4 * self._hover_t)
        
        if self._drag_state == "invalid":
            self._shadow.setColor(QColor(217, 48, 37, int(14 + 30 * self._hover_t))) # Red shadow
        else:
            self._shadow.setColor(QColor(26, 115, 232, int(14 + 20 * self._hover_t))) # Blue shadow

    def _reset_drag_state(self) -> None:
        self._drag_state = "none"
        self.setProperty("dragState", "none")
        self.title_label.setText(self._default_title)
        self.signal_label.setText(self._default_glyph)
        self._refresh_style()
        if not self.underMouse():
            self._animate_hover(0.0)

    def _refresh_style(self):
        self.style().unpolish(self)
        self.style().polish(self)

    @staticmethod
    def _local_paths(urls) -> list[str]:
        return [
            url.toLocalFile()
            for url in urls
            if url.isLocalFile()
        ]

    @staticmethod
    def _validation_errors(paths: list[str]) -> list[str]:
        errors = []
        for file_path in paths:
            path = Path(file_path)
            if path.suffix.lower() not in SUPPORTED_DATASET_SUFFIXES:
                errors.append(f"{path.name}: unsupported file type")
                continue
            try:
                if path.stat().st_size > MAX_DATASET_BYTES:
                    errors.append(f"{path.name}: exceeds 1 GB")
            except OSError:
                errors.append(f"{path.name}: file is unavailable")
        return errors


class PortalTip(QFrame):
    def __init__(self, title: str, description: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("portalTip")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        title_label = QLabel(title)
        title_label.setObjectName("portalTipTitle")
        description_label = QLabel(description)
        description_label.setObjectName("portalTipDescription")
        description_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(description_label)
        layout.addStretch()


class DataPortalPage(QWidget):
    add_requested = Signal()
    files_dropped = Signal(list)
    analysis_requested = Signal()
    cleaning_requested = Signal()
    library_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("dataPortalPage")
        self.setStyleSheet(DATA_PORTAL_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(56, 24, 56, 24)
        root.setSpacing(0)
        root.addStretch()

        self.content = QWidget()
        self.content.setObjectName("portalContent")
        self.content.setMaximumWidth(820)
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        eyebrow = QLabel("DATA WORKSPACE")
        eyebrow.setObjectName("portalEyebrow")
        eyebrow.setAlignment(Qt.AlignCenter)
        title = QLabel("Start with your data")
        title.setObjectName("portalTitle")
        title.setAlignment(Qt.AlignCenter)
        subtitle = QLabel(
            "Import the workbooks you want to clean or analyze. "
            "Your full data stays safely in your local environment."
        )
        subtitle.setObjectName("portalSubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setWordWrap(True)
        
        content_layout.addWidget(eyebrow)
        content_layout.addWidget(title)
        content_layout.addWidget(subtitle)
        content_layout.addSpacing(12)

        self.primary_row = QWidget()
        self.primary_row.setObjectName("portalPrimaryRow")
        primary_layout = QHBoxLayout(self.primary_row)
        primary_layout.setContentsMargins(0, 0, 0, 0)
        primary_layout.setSpacing(20)

        self.drop_zone = DatasetDropZone()
        self.drop_zone.clicked.connect(self.add_requested)
        self.drop_zone.files_dropped.connect(self.files_dropped)

        self.capability_panel = QFrame()
        self.capability_panel.setObjectName("capabilityPanel")
        self.capability_panel.setMaximumWidth(0)
        capability_layout = QVBoxLayout(self.capability_panel)
        capability_layout.setContentsMargins(4, 0, 0, 0)
        capability_layout.setSpacing(8)
        
        prompt = QLabel("NEXT STEPS")
        prompt.setObjectName("portalCapabilityPrompt")
        
        self.analysis_card = QPushButton("Analyze Workbooks")
        self.analysis_card.setObjectName("portalModeAction")
        self.analysis_card.setCursor(Qt.PointingHandCursor)
        
        self.cleaning_card = QPushButton("Clean Workbooks")
        self.cleaning_card.setObjectName("portalModeAction")
        self.cleaning_card.setCursor(Qt.PointingHandCursor)
        
        self.analysis_card.clicked.connect(self.analysis_requested)
        self.cleaning_card.clicked.connect(self.cleaning_requested)
        
        capability_layout.addStretch()
        capability_layout.addWidget(prompt)
        capability_layout.addWidget(self.analysis_card)
        capability_layout.addWidget(self.cleaning_card)
        capability_layout.addStretch()

        primary_layout.addWidget(self.drop_zone, stretch=1)
        primary_layout.addWidget(self.capability_panel)
        content_layout.addWidget(self.primary_row)

        # STABLE LAYOUT: Use QStackedWidget to prevent jumping
        self.status_stack = QStackedWidget()
        self.status_stack.setFixedHeight(46)
        
        # Stack 1: Standard Status
        self.status_widget = QWidget()
        status_layout = QHBoxLayout(self.status_widget)
        status_layout.setContentsMargins(4, 0, 4, 0)
        self.status_label = QLabel("Ready for your first dataset")
        self.status_label.setObjectName("portalStatus")
        self.library_button = QPushButton("View datasets →")
        self.library_button.setObjectName("portalLibraryButton")
        self.library_button.setCursor(Qt.PointingHandCursor)
        self.library_button.clicked.connect(self.library_requested)
        self.library_button.setVisible(False)
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(self.library_button)
        
        # Stack 2: Progress Bar
        self.progress_widget = QWidget()
        progress_layout = QVBoxLayout(self.progress_widget)
        progress_layout.setContentsMargins(4, 4, 4, 4)
        progress_layout.setSpacing(3)
        self.import_progress = QProgressBar()
        self.import_progress.setObjectName("portalProgress")
        self.import_progress.setTextVisible(False)
        self.progress_label = QLabel("Importing...")
        self.progress_label.setObjectName("portalStatus")
        
        prog_row = QHBoxLayout()
        prog_row.addWidget(self.progress_label)
        prog_row.addWidget(self.import_progress, stretch=1)
        progress_layout.addLayout(prog_row)

        self.status_stack.addWidget(self.status_widget)
        self.status_stack.addWidget(self.progress_widget)
        self.status_stack.setCurrentIndex(0)
        
        content_layout.addWidget(self.status_stack)
        content_layout.addSpacing(16)

        tips_header = QLabel("HOW FILES ARE HANDLED")
        tips_header.setObjectName("portalTipsHeader")
        content_layout.addWidget(tips_header)

        self.tips_panel = QFrame()
        self.tips_panel.setObjectName("portalTipsPanel")
        tips_layout = QHBoxLayout(self.tips_panel)
        tips_layout.setContentsMargins(0, 0, 0, 0)
        tips_layout.setSpacing(12)
        tips = [
            ("Small files are interactive", "Under 100 MB, files are prepared instantly for responsive analysis."),
            ("Large files run securely", "Up to 1 GB, files use guarded background processing so the app stays usable."),
            ("Select your required scope", "Analyze up to 3 workbooks together. Cleaning operates on one workbook at a time."),
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
        self._layout_animation.setDuration(300)
        self._layout_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._layout_animation.valueChanged.connect(self._apply_ready_layout_progress)
        self._layout_animation.finished.connect(self._finish_ready_layout_animation)

    def set_import_progress(self, label: str, percent: int) -> None:
        self.status_stack.setCurrentIndex(1)
        self.import_progress.setRange(0, 100)
        self.import_progress.setValue(percent)
        self.progress_label.setText(f"{label} · {percent}%")
        self.drop_zone.setEnabled(False)
        
        # Trigger disabled styles
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)

    def set_library_state(self, ready_count: int, pending_count: int = 0) -> None:
        self.status_stack.setCurrentIndex(0)
        self.drop_zone.setEnabled(pending_count == 0)
        self.library_button.setVisible(ready_count + pending_count > 0)

        # Trigger enabled/disabled styles
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)

        if pending_count:
            self.status_label.setText(f"{ready_count} ready · {pending_count} processing")
        else:
            self.status_label.setText(
                "Ready for your first dataset" if ready_count == 0 
                else f"{ready_count} dataset{'s' if ready_count != 1 else ''} ready"
            )

        should_show = ready_count > 0
        self._animate_ready_layout(should_show)

    def _animate_ready_layout(self, ready: bool) -> None:
        target = 1.0 if ready else 0.0
        if abs(self._ready_layout_t - target) < 0.001:
            return
        if ready:
            self.capability_panel.setVisible(True)
        self._layout_animation.stop()
        self._layout_animation.setStartValue(self._ready_layout_t)
        self._layout_animation.setEndValue(target)
        self._layout_animation.start()

    def _apply_ready_layout_progress(self, value) -> None:
        self._ready_layout_t = float(value)
        # Smoothly expand the capability panel
        self.capability_panel.setMaximumWidth(int(260 * self._ready_layout_t))
        self._capability_opacity.setOpacity(self._ready_layout_t)

    def _finish_ready_layout_animation(self) -> None:
        if self._ready_layout_t < 0.001:
            self.capability_panel.setVisible(False)


DATA_PORTAL_STYLE = """
QWidget#dataPortalPage { 
    background: #ffffff; 
}
QWidget#portalContent { 
    background: transparent; 
}
QLabel#portalEyebrow, QLabel#portalCapabilityPrompt, QLabel#portalTipsHeader {
    color: #1a73e8; 
    font-size: 11px; 
    font-weight: 700; 
    letter-spacing: 1.2px;
}
QLabel#portalCapabilityPrompt, QLabel#portalTipsHeader {
    color: #8a9097;
}
QLabel#portalTitle { 
    color: #202124; 
    font-size: 32px; 
    font-weight: 700; 
    letter-spacing: -0.5px;
}
QLabel#portalSubtitle { 
    color: #5f6368; 
    font-size: 14px; 
    font-weight: 400; 
}

/* DROP ZONE STYLES */
QFrame#datasetDropZone {
    background: #fafbfc; 
    border: 2px dashed #dadce0; 
    border-radius: 16px;
}
QFrame#datasetDropZone:hover {
    background: #f3f7fd; 
    border: 2px solid #aecbfa;
}
QFrame#datasetDropZone[dragState="valid"] {
    background: #e8f0fe; 
    border: 2px solid #1a73e8;
}
QFrame#datasetDropZone[dragState="invalid"] {
    background: #fce8e6; 
    border: 2px solid #d93025;
}
QFrame#datasetDropZone:disabled {
    background: #f8f9fa; 
    border: 2px dashed #e8eaed;
}

/* DROP ZONE TEXT STYLES */
QLabel#portalDropGlyph { color: #1a73e8; font-size: 32px; font-weight: 300; }
QLabel#portalDropTitle { color: #202124; font-size: 18px; font-weight: 600; }
QLabel#portalDropNote { color: #5f6368; font-size: 13px; font-weight: 400; }
QLabel#portalDropLimit { color: #8a9097; font-size: 11px; font-weight: 500; }

QFrame#datasetDropZone[dragState="invalid"] QLabel#portalDropGlyph,
QFrame#datasetDropZone[dragState="invalid"] QLabel#portalDropTitle {
    color: #d93025;
}

QFrame#datasetDropZone:disabled QLabel { 
    color: #bdc1c6; 
}

/* STATUS & LIBRARY */
QLabel#portalStatus { 
    color: #5f6368; 
    font-size: 12px; 
    font-weight: 500; 
}
QPushButton#portalLibraryButton {
    color: #1a73e8; 
    background: transparent; 
    border: none;
    font-size: 12px; 
    font-weight: 600;
}
QPushButton#portalLibraryButton:hover { color: #174ea6; text-decoration: underline; }

/* PROGRESS BAR */
QProgressBar#portalProgress {
    min-height: 6px; 
    max-height: 6px; 
    border: none;
    background: #f1f3f4; 
    border-radius: 3px;
}
QProgressBar#portalProgress::chunk { 
    background: #1a73e8; 
    border-radius: 3px; 
}

/* TIPS PANEL */
QFrame#portalTip {
    background: #f8f9fa; 
    border: 1px solid #e8eaed; 
    border-radius: 12px;
}
QLabel#portalTipTitle { color: #202124; font-size: 13px; font-weight: 600; }
QLabel#portalTipDescription { color: #5f6368; font-size: 12px; font-weight: 400; line-height: 1.4; }

/* CAPABILITY CARDS */
QPushButton#portalModeAction {
    text-align: center; 
    color: #202124; 
    background: #ffffff;
    border: 1px solid #dadce0; 
    border-radius: 8px;
    padding: 14px 16px; 
    font-size: 14px; 
    font-weight: 600;
}
QPushButton#portalModeAction:hover {
    background: #f8f9fa;
    border-color: #1a73e8;
    color: #1a73e8;
}
QPushButton#portalModeAction:pressed { 
    background: #e8f0fe;
    color: #174ea6; 
}
"""
