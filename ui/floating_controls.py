from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QTimer, QVariantAnimation, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
        int(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


class CircularStatusButton(QPushButton):
    def __init__(self, glyph: str = "i", parent=None):
        super().__init__(parent)
        self._glyph = glyph
        self._busy = False
        self._hover_t = 0.0
        self._spinner_angle = 0
        self.setFixedSize(30, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.setText("")
        self._hover_animation = QVariantAnimation(self)
        self._hover_animation.setDuration(140)
        self._hover_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_animation.valueChanged.connect(self._on_hover_value_changed)
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(32)
        self._spinner_timer.timeout.connect(self._tick_spinner)

    def setBusy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            if not self._spinner_timer.isActive():
                self._spinner_timer.start()
        else:
            self._spinner_timer.stop()
            self._spinner_angle = 0
        self.update()

    def setGlyph(self, glyph: str) -> None:
        self._glyph = glyph
        self.update()

    def isBusy(self) -> bool:
        return self._busy

    def enterEvent(self, event) -> None:
        self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate_hover(0.0)
        super().leaveEvent(event)

    def _animate_hover(self, target: float) -> None:
        self._hover_animation.stop()
        self._hover_animation.setStartValue(self._hover_t)
        self._hover_animation.setEndValue(target)
        self._hover_animation.start()

    def _on_hover_value_changed(self, value) -> None:
        self._hover_t = float(value)
        self.update()

    def _tick_spinner(self) -> None:
        self._spinner_angle = (self._spinner_angle + 24) % 360
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        base_fill = QColor(255, 255, 255, 236)
        hover_fill = QColor(243, 244, 246, 248)
        base_border = QColor("#E5E7EB")
        hover_border = QColor("#CBD5E1")
        glyph_color = QColor("#374151")
        spinner_color = QColor("#1A73E8")

        rect = self.rect().adjusted(1, 1, -1, -1)
        fill = _mix(base_fill, hover_fill, self._hover_t)
        border = _mix(base_border, hover_border, self._hover_t)

        painter.setPen(QPen(border, 1.0))
        painter.setBrush(fill)
        painter.drawEllipse(rect)

        if self._busy:
            spinner_rect = rect.adjusted(7, 7, -7, -7)
            pen = QPen(spinner_color, 2.0)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawArc(spinner_rect, self._spinner_angle * 16, 220 * 16)
            return

        painter.setPen(glyph_color)
        font = painter.font()
        font.setPointSize(9)
        font.setBold(False)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, self._glyph)


class DatasetRowWidget(QFrame):
    activated = Signal(str)
    overview_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, dataset_name: str, parent=None):
        super().__init__(parent)
        self.dataset_name = dataset_name
        self.setObjectName("datasetRowWidget")
        self._selected = False
        self._hovered = False
        self._full_text = dataset_name

        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(40)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(8)

        self.name_label = QLabel()
        self.name_label.setObjectName("datasetRowName")
        self.name_label.setMinimumWidth(0)
        layout.addWidget(self.name_label, stretch=1)

        self.overview_button = CircularStatusButton("i")
        self.overview_button.setFixedSize(22, 22)
        self.overview_button.setToolTip("Dataset overview")
        self.overview_button.clicked.connect(self._emit_overview_requested)
        layout.addWidget(self.overview_button, alignment=Qt.AlignVCenter)

        self.delete_button = QPushButton("×")
        self.delete_button.setObjectName("datasetDeleteButton")
        self.delete_button.setFixedSize(20, 20)
        self.delete_button.setCursor(Qt.PointingHandCursor)
        self.delete_button.setToolTip("Remove dataset")
        self.delete_button.clicked.connect(self._emit_delete_requested)
        layout.addWidget(self.delete_button, alignment=Qt.AlignVCenter)

        self._update_elided_text()
        self._apply_selection_style()

    def _emit_overview_requested(self) -> None:
        self.overview_requested.emit(self.dataset_name)

    def _emit_delete_requested(self) -> None:
        self.delete_requested.emit(self.dataset_name)

    def setSelected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_selection_style()

    def setBusy(self, busy: bool) -> None:
        if busy:
            self.overview_button.setGlyph("i")
        self.overview_button.setBusy(busy)
        self.overview_button.setEnabled(not busy)
        self.overview_button.setVisible(True)

    def setReady(self, tooltip: str) -> None:
        self.overview_button.setGlyph("i")
        self.overview_button.setBusy(False)
        self.overview_button.setEnabled(True)
        self.overview_button.setToolTip(tooltip)
        self.overview_button.setVisible(True)

    def setQueued(self, tooltip: str) -> None:
        self.overview_button.setGlyph("i")
        self.overview_button.setBusy(False)
        self.overview_button.setEnabled(False)
        self.overview_button.setToolTip(tooltip)
        self.overview_button.setVisible(True)

    def setRetry(self, tooltip: str) -> None:
        self.overview_button.setGlyph("↻")
        self.overview_button.setBusy(False)
        self.overview_button.setEnabled(True)
        self.overview_button.setToolTip(tooltip)
        self.overview_button.setVisible(True)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.activated.emit(self.dataset_name)
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._apply_selection_style()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._apply_selection_style()
        super().leaveEvent(event)

    def resizeEvent(self, event) -> None:
        self._update_elided_text()
        super().resizeEvent(event)

    def _update_elided_text(self) -> None:
        metrics = QFontMetrics(self.name_label.font())
        available = max(32, self.width() - 84)
        self.name_label.setText(
            metrics.elidedText(self._full_text, Qt.ElideMiddle, available)
        )

    def _apply_selection_style(self) -> None:
        if self._selected:
            self.setStyleSheet(
                """
                QFrame#datasetRowWidget {
                    background-color: #EFF6FF;
                    border: 1px solid #BFDBFE;
                    border-radius: 12px;
                }
                QLabel#datasetRowName {
                    color: #1D4ED8;
                    font-size: 12px;
                    font-weight: 600;
                }
                QPushButton#datasetDeleteButton {
                    color: #64748B;
                    background-color: transparent;
                    border: none;
                    border-radius: 10px;
                    font-size: 14px;
                    font-weight: 400;
                }
                QPushButton#datasetDeleteButton:hover {
                    color: #B42318;
                    background-color: #FEE4E2;
                }
                """
            )
        elif self._hovered:
            self.setStyleSheet(
                """
                QFrame#datasetRowWidget {
                    background-color: #F8FAFC;
                    border: 1px solid #E5E7EB;
                    border-radius: 12px;
                }
                QLabel#datasetRowName {
                    color: #1F2937;
                    font-size: 12px;
                    font-weight: 500;
                }
                QPushButton#datasetDeleteButton {
                    color: #64748B;
                    background-color: transparent;
                    border: none;
                    border-radius: 10px;
                    font-size: 14px;
                    font-weight: 400;
                }
                QPushButton#datasetDeleteButton:hover {
                    color: #B42318;
                    background-color: #FEE4E2;
                }
                """
            )
        else:
            self.setStyleSheet(
                """
                QFrame#datasetRowWidget {
                    background-color: transparent;
                    border: 1px solid transparent;
                    border-radius: 12px;
                }
                QLabel#datasetRowName {
                    color: #374151;
                    font-size: 12px;
                    font-weight: 500;
                }
                QPushButton#datasetDeleteButton {
                    color: #94A3B8;
                    background-color: transparent;
                    border: none;
                    border-radius: 10px;
                    font-size: 14px;
                    font-weight: 400;
                }
                QPushButton#datasetDeleteButton:hover {
                    color: #B42318;
                    background-color: #FEE4E2;
                }
                """
            )


class SuggestionPopover(QFrame):
    suggestion_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(180)
        self._hide_timer.timeout.connect(self.hide)
        self._surface = QFrame(self)
        self._surface.setObjectName("suggestionPopoverSurface")
        self._layout = QVBoxLayout(self._surface)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(6)
        self._buttons: list[QPushButton] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._surface)
        self.setStyleSheet(
            """
            QFrame#suggestionPopoverSurface {
                background-color: rgba(255, 255, 255, 248);
                border: 1px solid #E5E7EB;
                border-radius: 18px;
            }
            QPushButton#suggestionPopoverItem {
                background-color: #F8FAFC;
                color: #111827;
                border: 1px solid #E5E7EB;
                border-radius: 14px;
                padding: 8px 11px;
                text-align: left;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton#suggestionPopoverItem:hover {
                background-color: #EFF6FF;
                border-color: #BFDBFE;
                color: #1D4ED8;
            }
            """
        )

    def setSuggestions(self, suggestions: list[str]) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._buttons.clear()
        for suggestion in suggestions[:4]:
            button = QPushButton(suggestion)
            button.setObjectName("suggestionPopoverItem")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, text=suggestion: self._emit_and_close(text)
            )
            self._layout.addWidget(button)
            self._buttons.append(button)
        self.adjustSize()

    def showFor(self, anchor: QWidget) -> None:
        if not self._buttons:
            return
        self.adjustSize()
        global_pos = anchor.mapToGlobal(QPoint(0, anchor.height() + 6))
        self.move(global_pos)
        self.show()
        self.raise_()

    def scheduleHide(self) -> None:
        self._hide_timer.start()

    def cancelHide(self) -> None:
        self._hide_timer.stop()

    def enterEvent(self, event) -> None:
        self.cancelHide()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.scheduleHide()
        super().leaveEvent(event)

    def _emit_and_close(self, text: str) -> None:
        self.hide()
        self.suggestion_selected.emit(text)
