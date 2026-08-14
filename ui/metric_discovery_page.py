"""Single-page UI for business-analysis indicator generation."""

from __future__ import annotations

import re

from PySide6.QtCore import (
    QElapsedTimer,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QGuiApplication,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config.settings import settings
from core.metric_catalogs import (
    ANALYSIS_DIRECTION_OPTIONS,
    ANALYSIS_FOCUS_OPTIONS,
    BUSINESS_MODEL_OPTIONS,
    CUSTOMER_TYPE_OPTIONS,
    INDUSTRY_OPTIONS,
    PRODUCT_SERVICE_OPTIONS,
)
from core.metric_discovery import (
    MetricDiscoveryContractError,
    MetricDiscoveryRequest,
    MetricDiscoveryResult,
    ReferenceAttachment,
    SUPPORTED_REFERENCE_SUFFIXES,
)
from core.company_resolution import CompanyCandidate


class FlowLayout(QLayout):
    """Small wrapping layout used for checkable option chips."""

    def __init__(self, parent=None, margin: int = 0, spacing: int = 7) -> None:
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self._items = []

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(
            margins.left() + margins.right(),
            margins.top() + margins.bottom(),
        )

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(),
            margins.top(),
            -margins.right(),
            -margins.bottom(),
        )
        x = effective.x()
        y = effective.y()
        line_height = 0
        spacing = self.spacing()
        for item in self._items:
            widget = item.widget()
            # isVisible() is false while the parent window is being laid out for
            # the first time.  Skipping those widgets collapses the entire chip
            # host until the window is resized or maximized.
            if widget is not None and widget.isHidden():
                continue
            hint = item.sizeHint()
            next_x = x + hint.width() + spacing
            if next_x - spacing > effective.right() and line_height > 0:
                x = effective.x()
                y += line_height + spacing
                next_x = x + hint.width() + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


class ResearchEnhancementCard(QFrame):
    """Clickable setting surface for the optional public-research feature."""

    clicked = Signal()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class MetricToggleSwitch(QCheckBox):
    """Compact painted switch that keeps native checkbox semantics."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(38, 22)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        if not self.isEnabled():
            track_color = QColor("#E5E6EB")
            thumb_color = QColor("#F7F8FA")
        elif self.isChecked():
            track_color = QColor("#4080FF" if self.underMouse() else "#165DFF")
            thumb_color = QColor("#FFFFFF")
        else:
            track_color = QColor("#A9AEB8" if self.underMouse() else "#C9CDD4")
            thumb_color = QColor("#FFFFFF")

        if self.hasFocus():
            painter.setPen(QPen(QColor("#BEDAFF"), 1.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(0.5, 0.5, 37.0, 21.0), 10.5, 10.5)

        painter.setPen(Qt.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(QRectF(1.5, 2.0, 35.0, 18.0), 9.0, 9.0)

        thumb_x = 20.5 if self.isChecked() else 3.5
        painter.setBrush(thumb_color)
        painter.drawEllipse(QRectF(thumb_x, 4.0, 14.0, 14.0))
        painter.end()


class MetricCheckbox(QCheckBox):
    """Arco-inspired checkbox with stable geometry across Windows themes."""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    def sizeHint(self) -> QSize:
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        return QSize(text_width + 38, 29)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        if self.underMouse() and self.isEnabled():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#F7F8FA"))
            painter.drawRoundedRect(
                QRectF(0.5, 1.0, self.width() - 1.0, self.height() - 2.0),
                5.0,
                5.0,
            )

        box_size = 15.0
        box_x = 6.0
        box_y = (self.height() - box_size) / 2.0
        box_rect = QRectF(box_x, box_y, box_size, box_size)
        checked = self.checkState() == Qt.Checked

        if not self.isEnabled():
            border_color = QColor("#E5E6EB")
            fill_color = QColor("#F7F8FA")
            text_color = QColor("#C9CDD4")
        elif checked:
            border_color = QColor("#165DFF")
            fill_color = QColor("#165DFF")
            text_color = QColor("#1D2129")
        else:
            border_color = QColor(
                "#86909C" if self.underMouse() else "#C9CDD4"
            )
            fill_color = QColor("#FFFFFF")
            text_color = QColor("#4E5969")

        painter.setPen(QPen(border_color, 1.2))
        painter.setBrush(fill_color)
        painter.drawRoundedRect(box_rect, 2.5, 2.5)

        if checked:
            check_pen = QPen(QColor("#FFFFFF"), 1.7)
            check_pen.setCapStyle(Qt.RoundCap)
            check_pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(check_pen)
            painter.drawLine(
                QPointF(box_x + 3.2, box_y + 7.8),
                QPointF(box_x + 6.2, box_y + 10.6),
            )
            painter.drawLine(
                QPointF(box_x + 6.2, box_y + 10.6),
                QPointF(box_x + 12.0, box_y + 4.7),
            )

        if self.hasFocus():
            painter.setPen(QPen(QColor("#94BFFF"), 1.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(
                box_rect.adjusted(-2.0, -2.0, 2.0, 2.0),
                4.0,
                4.0,
            )

        painter.setPen(text_color)
        painter.setFont(self.font())
        painter.drawText(
            QRectF(28.0, 0.0, self.width() - 28.0, self.height()),
            Qt.AlignLeft | Qt.AlignVCenter,
            self.text(),
        )
        painter.end()


class ChipMultiSelect(QWidget):
    """Unlimited optional multi-select rendered as a checkbox group."""

    changed = Signal()

    def __init__(
        self,
        title: str,
        options: tuple[str, ...],
        *,
        hint: str = "",
        other_label: str = "其他",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._buttons: dict[str, MetricCheckbox] = {}
        self._other_label = other_label
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        heading = QLabel(title)
        heading.setObjectName("metricFieldLabel")
        layout.addWidget(heading)
        if hint:
            help_label = QLabel(hint)
            help_label.setObjectName("metricFieldHint")
            help_label.setWordWrap(True)
            layout.addWidget(help_label)

        self.chip_host = QWidget()
        self.chip_host.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Minimum,
        )
        self.flow = FlowLayout(self.chip_host)
        for option in (*options, other_label):
            button = MetricCheckbox(option)
            button.setObjectName("metricChoiceCheckbox")
            button.setAccessibleName(f"{title}：{option}")
            button.toggled.connect(self._on_toggled)
            self._buttons[option] = button
            self.flow.addWidget(button)

        layout.addWidget(self.chip_host)

        self.other_input = QLineEdit()
        self.other_input.setObjectName("metricOtherInput")
        self.other_input.setPlaceholderText(
            "输入其他内容，多个内容用逗号分隔"
        )
        self.other_input.setVisible(False)
        self.other_input.textChanged.connect(self.changed)
        layout.addWidget(self.other_input)

        self.selection_row = QWidget()
        selection_layout = QHBoxLayout(self.selection_row)
        selection_layout.setContentsMargins(0, 0, 0, 0)
        selection_layout.setSpacing(6)
        self.selection_status = QLabel("")
        self.selection_status.setObjectName("metricSelectionSummary")
        self.clear_button = QPushButton("清空")
        self.clear_button.setObjectName("metricInlineAction")
        self.clear_button.setCursor(Qt.PointingHandCursor)
        self.clear_button.clicked.connect(self.clear)
        selection_layout.addWidget(self.selection_status)
        selection_layout.addStretch()
        selection_layout.addWidget(self.clear_button)
        self.selection_row.setVisible(False)
        layout.addWidget(self.selection_row)

    def sizeHint(self) -> QSize:
        layout = self.layout()
        width = max(self.width(), 360)
        hint = layout.sizeHint()
        return QSize(hint.width(), layout.heightForWidth(width))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def selected_values(self) -> list[str]:
        return [
            option
            for option, button in self._buttons.items()
            if option != self._other_label and button.isChecked()
        ]

    def custom_values(self) -> list[str]:
        if not self._buttons[self._other_label].isChecked():
            return []
        return _split_custom_values(self.other_input.text())

    def _on_toggled(self) -> None:
        self.other_input.setVisible(
            self._buttons[self._other_label].isChecked()
        )
        selected_count = sum(
            button.isChecked()
            for button in self._buttons.values()
        )
        self.selection_status.setText(f"已选 {selected_count} 项")
        self.selection_row.setVisible(selected_count > 0)
        self.chip_host.updateGeometry()
        self.changed.emit()

    def clear(self) -> None:
        for button in self._buttons.values():
            button.setChecked(False)
        self.other_input.clear()


class HoverCategoryButton(QPushButton):
    """Category row that opens its children on hover or click."""

    hovered = Signal()

    def enterEvent(self, event) -> None:
        self.hovered.emit()
        super().enterEvent(event)


class SelectTriggerButton(QPushButton):
    """Select trigger with a restrained, right-aligned vector chevron."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._popup_open = False
        self.setProperty("open", False)
        self.setProperty("placeholder", True)

    def set_popup_open(self, popup_open: bool) -> None:
        if self._popup_open == popup_open:
            return
        self._popup_open = popup_open
        self.setProperty("open", popup_open)
        self._refresh_style()
        self.update()

    def set_placeholder(self, placeholder: bool) -> None:
        if self.property("placeholder") == placeholder:
            return
        self.setProperty("placeholder", placeholder)
        self._refresh_style()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if not self.isEnabled():
            color = QColor("#C9CDD4")
        elif self._popup_open:
            color = QColor("#165DFF")
        elif self.underMouse():
            color = QColor("#4E5969")
        else:
            color = QColor("#86909C")
        pen = QPen(color, 1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)

        center_x = self.width() - 19.0
        center_y = self.height() / 2.0
        if self._popup_open:
            left = QPointF(center_x - 4.0, center_y + 2.0)
            middle = QPointF(center_x, center_y - 2.0)
            right = QPointF(center_x + 4.0, center_y + 2.0)
        else:
            left = QPointF(center_x - 4.0, center_y - 2.0)
            middle = QPointF(center_x, center_y + 2.0)
            right = QPointF(center_x + 4.0, center_y - 2.0)
        painter.drawLine(left, middle)
        painter.drawLine(middle, right)
        painter.end()

    def _refresh_style(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)


class DropdownMultiSelect(QWidget):
    """Non-native multi-select with optional hover-driven categories."""

    changed = Signal()

    def __init__(
        self,
        title: str,
        options,
        *,
        placeholder: str,
        hint: str = "",
        hierarchical: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._hierarchical = hierarchical
        self._placeholder = placeholder
        self._selected: set[str] = set()
        self._other_enabled = False
        if hierarchical:
            grouped: dict[str, list[str]] = {}
            for category, label in options:
                grouped.setdefault(category, []).append(label)
            self._groups = tuple(
                (category, tuple(labels))
                for category, labels in grouped.items()
            )
            self._option_order = tuple(label for _, label in options)
        else:
            flat_options = tuple(options)
            self._groups = (("", flat_options),)
            self._option_order = flat_options

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        heading = QLabel(title)
        heading.setObjectName("metricFieldLabel")
        layout.addWidget(heading)
        if hint:
            help_label = QLabel(hint)
            help_label.setObjectName("metricFieldHint")
            help_label.setWordWrap(True)
            layout.addWidget(help_label)

        field_row = QHBoxLayout()
        field_row.setSpacing(7)
        self.select_button = SelectTriggerButton()
        self.select_button.setObjectName("metricMultiSelectButton")
        self.select_button.setCursor(Qt.PointingHandCursor)
        self.select_button.setAccessibleName(f"选择{title}")
        self.select_button.clicked.connect(self._open_popup)
        self.other_input = QLineEdit()
        self.other_input.setObjectName("metricOtherInput")
        self.other_input.setPlaceholderText("输入其他内容")
        self.other_input.setVisible(False)
        self.other_input.textChanged.connect(self.changed)
        field_row.addWidget(self.select_button, stretch=1)
        field_row.addWidget(self.other_input, stretch=1)
        layout.addLayout(field_row)
        self._refresh_button()

    def selected_values(self) -> list[str]:
        return [
            option
            for option in self._option_order
            if option in self._selected
        ]

    def custom_values(self) -> list[str]:
        if not self._other_enabled:
            return []
        return _split_custom_values(self.other_input.text())

    def clear(self) -> None:
        self._selected.clear()
        self._set_other_enabled(False)
        self.other_input.clear()
        self._refresh_button()
        self.changed.emit()

    def _set_checked(self, value: str, checked: bool) -> None:
        if checked:
            self._selected.add(value)
        else:
            self._selected.discard(value)
        self._refresh_button()
        self.changed.emit()

    def _set_other_enabled(self, enabled: bool) -> None:
        self._other_enabled = enabled
        self.other_input.setVisible(enabled)
        self._refresh_button()
        self.updateGeometry()
        self.changed.emit()

    def _refresh_button(self) -> None:
        selected = self.selected_values()
        count = len(selected) + int(self._other_enabled)
        if not count:
            label = self._placeholder
        elif len(selected) <= 2 and not self._other_enabled:
            label = "、".join(selected)
        else:
            label = f"已选 {count} 项"
        self.select_button.set_placeholder(not count)
        self.select_button.setText(label)

    def _open_popup(self) -> None:
        popup = MultiSelectPopup(self)
        self.select_button.set_popup_open(True)
        try:
            popup.open_below(self.select_button)
        finally:
            self.select_button.set_popup_open(False)


class MultiSelectPopup(QDialog):
    """Popup used by flat and hierarchical multi-select fields."""

    def __init__(self, owner: DropdownMultiSelect) -> None:
        super().__init__(owner, Qt.Popup | Qt.FramelessWindowHint)
        self.owner = owner
        self.setObjectName("metricMultiSelectPopupWindow")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._category_buttons: dict[str, HoverCategoryButton] = {}

        outer = QVBoxLayout(self)
        # A graphics shadow on a translucent Qt.Popup is clipped by the native
        # popup window on some Windows scale factors, leaving a dark bar on the
        # right and bottom edges.  The panel border gives a cleaner, stable
        # boundary without relying on an effect outside the popup's geometry.
        outer.setContentsMargins(3, 3, 3, 3)
        self.panel = QFrame()
        self.panel.setObjectName("metricMultiSelectPopup")
        outer.addWidget(self.panel)

        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(9, 9, 9, 9)
        panel_layout.setSpacing(7)
        header = QHBoxLayout()
        title = QLabel(owner._title)
        title.setObjectName("metricDropdownTitle")
        self.count_label = QLabel()
        self.count_label.setObjectName("metricSelectionSummary")
        clear_button = QPushButton("清空")
        clear_button.setObjectName("metricInlineAction")
        clear_button.setCursor(Qt.PointingHandCursor)
        clear_button.clicked.connect(self._clear)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.count_label)
        header.addWidget(clear_button)
        panel_layout.addLayout(header)

        content = QHBoxLayout()
        content.setSpacing(7)
        if owner._hierarchical:
            categories_scroll = QScrollArea()
            categories_scroll.setObjectName("metricDropdownScroll")
            categories_scroll.setWidgetResizable(True)
            categories_scroll.setHorizontalScrollBarPolicy(
                Qt.ScrollBarAlwaysOff
            )
            categories_scroll.setFixedWidth(168)
            categories_host = QWidget()
            categories_layout = QVBoxLayout(categories_host)
            categories_layout.setContentsMargins(0, 0, 0, 0)
            categories_layout.setSpacing(2)
            for category, _labels in owner._groups:
                button = HoverCategoryButton(f"{category}  ›")
                button.setObjectName("metricCategoryOption")
                button.setCursor(Qt.PointingHandCursor)
                button.hovered.connect(
                    lambda value=category: self._show_category(value)
                )
                button.clicked.connect(
                    lambda _checked=False, value=category: self._show_category(
                        value
                    )
                )
                self._category_buttons[category] = button
                categories_layout.addWidget(button)
            categories_layout.addStretch()
            categories_scroll.setWidget(categories_host)
            content.addWidget(categories_scroll)

        self.children_scroll = QScrollArea()
        self.children_scroll.setObjectName("metricDropdownScroll")
        self.children_scroll.setWidgetResizable(True)
        self.children_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )
        self.children_host = QWidget()
        self.children_layout = QVBoxLayout(self.children_host)
        self.children_layout.setContentsMargins(2, 2, 2, 2)
        self.children_layout.setSpacing(3)
        self.children_scroll.setWidget(self.children_host)
        content.addWidget(self.children_scroll, stretch=1)
        panel_layout.addLayout(content, stretch=1)

        footer = QFrame()
        footer.setObjectName("metricDropdownOtherRow")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(8, 6, 8, 6)
        self.other_checkbox = QCheckBox("其他")
        self.other_checkbox.setObjectName("metricDropdownCheck")
        self.other_checkbox.setChecked(owner._other_enabled)
        self.other_checkbox.toggled.connect(owner._set_other_enabled)
        self.other_checkbox.toggled.connect(self._refresh_count)
        footer_layout.addWidget(self.other_checkbox)
        footer_layout.addStretch()
        panel_layout.addWidget(footer)

        first_category = owner._groups[0][0]
        self._show_category(first_category)
        self._refresh_count()

    def open_below(self, button: QPushButton) -> None:
        width = 570 if self.owner._hierarchical else max(
            button.width() + 20,
            370,
        )
        self.setFixedSize(width, 410)
        anchor = button.mapToGlobal(QPoint(0, button.height() + 3))
        screen = QGuiApplication.screenAt(anchor)
        if screen is not None:
            available = screen.availableGeometry()
            x = min(anchor.x(), available.right() - self.width())
            y = anchor.y()
            if y + self.height() > available.bottom():
                y = button.mapToGlobal(QPoint(0, 0)).y() - self.height()
            self.move(max(available.left(), x), max(available.top(), y))
        else:
            self.move(anchor)
        self.exec()

    def _show_category(self, category: str) -> None:
        labels = next(
            labels
            for group, labels in self.owner._groups
            if group == category
        )
        _clear_layout(self.children_layout)
        for label in labels:
            checkbox = QCheckBox(label)
            checkbox.setObjectName("metricDropdownCheck")
            checkbox.setChecked(label in self.owner._selected)
            checkbox.toggled.connect(
                lambda checked, value=label: self._toggle_value(
                    value,
                    checked,
                )
            )
            self.children_layout.addWidget(checkbox)
        self.children_layout.addStretch()
        for value, button in self._category_buttons.items():
            button.setProperty("active", value == category)
            button.style().unpolish(button)
            button.style().polish(button)

    def _toggle_value(self, value: str, checked: bool) -> None:
        self.owner._set_checked(value, checked)
        self._refresh_count()

    def _clear(self) -> None:
        self.owner.clear()
        self.other_checkbox.blockSignals(True)
        self.other_checkbox.setChecked(False)
        self.other_checkbox.blockSignals(False)
        current = next(
            (
                category
                for category, button in self._category_buttons.items()
                if button.property("active")
            ),
            self.owner._groups[0][0],
        )
        self._show_category(current)
        self._refresh_count()

    def _refresh_count(self, *_args) -> None:
        count = len(self.owner._selected) + int(self.owner._other_enabled)
        self.count_label.setText(f"已选 {count} 项")


class ModernSelect(QWidget):
    """Styled single-select that does not use the native combo popup."""

    changed = Signal()

    def __init__(
        self,
        options: tuple[tuple[str, object, str], ...],
        *,
        placeholder: str = "系统自动确定",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._options = options
        self._value = None
        self._placeholder = placeholder
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.button = SelectTriggerButton()
        self.button.setObjectName("metricModernSelect")
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setAccessibleName("打开选择列表")
        self.button.clicked.connect(self._open_popup)
        layout.addWidget(self.button)
        self._refresh_button()

    def value(self):
        return self._value

    def set_value(self, value) -> None:
        if not any(option_value == value for _, option_value, _ in self._options):
            raise ValueError(f"Unknown select value: {value!r}")
        self._value = value
        self._refresh_button()
        self.changed.emit()

    def clear(self) -> None:
        self.set_value(None)

    def _refresh_button(self) -> None:
        matched_label = next(
            (
                option_label
                for option_label, value, _ in self._options
                if value == self._value
            ),
            None,
        )
        self.button.set_placeholder(matched_label is None)
        self.button.setText(matched_label or self._placeholder)

    def _open_popup(self) -> None:
        popup = QDialog(self, Qt.Popup | Qt.FramelessWindowHint)
        popup.setObjectName("metricModernSelectPopup")
        popup.setAttribute(Qt.WA_TranslucentBackground, True)

        shadow_host = QFrame()
        shadow_host.setObjectName("metricSelectPopup")
        popup_layout = QVBoxLayout(popup)
        popup_layout.setContentsMargins(3, 3, 3, 3)
        popup_layout.addWidget(shadow_host)
        options_layout = QVBoxLayout(shadow_host)
        options_layout.setContentsMargins(7, 7, 7, 7)
        options_layout.setSpacing(3)

        for label, value, description in self._options:
            option = QPushButton(
                f"{label}\n{description}" if description else label
            )
            option.setObjectName("metricSelectOption")
            option.setProperty("selected", value == self._value)
            option.setCursor(Qt.PointingHandCursor)
            option.setAccessibleName(label)
            option.setMinimumHeight(48 if description else 38)
            option.clicked.connect(
                lambda _checked=False, selected=value, dialog=popup: (
                    self._select_value(selected),
                    dialog.accept(),
                )
            )
            options_layout.addWidget(option)

        popup.setFixedWidth(max(self.button.width() + 20, 360))
        popup.adjustSize()
        anchor = self.button.mapToGlobal(QPoint(0, self.button.height() + 3))
        screen = QGuiApplication.screenAt(anchor)
        if screen is not None:
            available = screen.availableGeometry()
            x = min(anchor.x(), available.right() - popup.width())
            y = anchor.y()
            if y + popup.height() > available.bottom():
                y = self.button.mapToGlobal(QPoint(0, 0)).y() - popup.height()
            popup.move(max(available.left(), x), max(available.top(), y))
        else:
            popup.move(anchor)
        self.button.set_popup_open(True)
        try:
            popup.exec()
        finally:
            self.button.set_popup_open(False)

    def _select_value(self, value) -> None:
        self._value = value
        self._refresh_button()
        self.changed.emit()


class ConditionalChoiceField(QWidget):
    """Required single choice shown only when its business scenario applies."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        heading = QLabel("是否使用达人推广？")
        heading.setObjectName("metricFieldLabel")
        hint = QLabel(
            "包括达人直播带货、短视频或图文种草、达人橱窗/推广链接，"
            "以及通过MCN机构开展的达人合作。"
        )
        hint.setObjectName("metricFieldHint")
        hint.setWordWrap(True)
        self.selector = ModernSelect(
            (
                ("请选择", None, "该信息用于决定是否生成达人推广专项指标"),
                ("是", "yes", "按达人推广专项指标剧本生成并核查"),
                ("否", "no", "不生成达人专属指标"),
                ("暂不确定", "unknown", "仅生成待确认的条件性指标"),
            )
        )
        self.selector.changed.connect(self.changed)
        layout.addWidget(heading)
        layout.addWidget(hint)
        layout.addWidget(self.selector)

    def value(self) -> str | None:
        value = self.selector.value()
        return str(value) if value is not None else None

    def clear(self) -> None:
        self.selector.clear()


class IndicatorCountField(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        label = QLabel("指标数量")
        label.setObjectName("metricFieldLabel")
        self.selector = ModernSelect(
            (
                ("系统自动确定", None, "生成 5—10 项指标"),
                ("5 项", 5, ""),
                ("8 项", 8, ""),
                ("10 项", 10, ""),
                ("其他", "__other__", "自定义 5—10 项"),
            )
        )
        self.selector.changed.connect(self._on_changed)
        self.custom_spin = QSpinBox()
        self.custom_spin.setRange(5, 10)
        self.custom_spin.setValue(7)
        self.custom_spin.setPrefix("自定义 ")
        self.custom_spin.setSuffix(" 项")
        self.custom_spin.setVisible(False)
        self.custom_spin.valueChanged.connect(self.changed)
        layout.addWidget(label)
        layout.addWidget(self.selector)
        layout.addWidget(self.custom_spin)

    def value(self) -> int | None:
        data = self.selector.value()
        if data == "__other__":
            return self.custom_spin.value()
        return int(data) if data is not None else None

    def clear(self) -> None:
        self.selector.clear()
        self.custom_spin.setValue(7)
        self.custom_spin.setVisible(False)

    def _on_changed(self) -> None:
        self.custom_spin.setVisible(self.selector.value() == "__other__")
        self.changed.emit()


class ReferenceDropZone(QFrame):
    """Document-only drop zone kept separate from the Excel dataset library."""

    changed = Signal()
    validation_failed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("metricDropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(68)
        self._attachments: list[ReferenceAttachment] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        title = QLabel("拖入资料或点击选择文件")
        title.setObjectName("metricDropTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

    def attachments(self) -> tuple[ReferenceAttachment, ...]:
        return tuple(self._attachments)

    def add_files(self, paths: list[str]) -> None:
        errors = []
        known = {attachment.path.casefold() for attachment in self._attachments}
        for raw_path in paths:
            try:
                attachment = ReferenceAttachment.from_path(raw_path)
            except MetricDiscoveryContractError as exc:
                errors.append(str(exc))
                continue
            if attachment.path.casefold() in known:
                continue
            if len(self._attachments) >= settings.METRIC_MAX_REFERENCE_FILES:
                errors.append(
                    "最多添加 "
                    f"{settings.METRIC_MAX_REFERENCE_FILES} 份参考资料。"
                )
                break
            if attachment.size_bytes > settings.METRIC_MAX_REFERENCE_FILE_BYTES:
                limit_mb = settings.METRIC_MAX_REFERENCE_FILE_BYTES // (1024 * 1024)
                errors.append(
                    f"{attachment.name}: 文件超过 {limit_mb} MB 限制。"
                )
                continue
            self._attachments.append(attachment)
            known.add(attachment.path.casefold())
        if errors:
            self.validation_failed.emit("\n".join(errors))
        self.changed.emit()

    def remove_paths(self, paths: set[str]) -> None:
        self._attachments = [
            attachment
            for attachment in self._attachments
            if attachment.path not in paths
        ]
        self.changed.emit()

    def clear(self) -> None:
        if not self._attachments:
            return
        self._attachments.clear()
        self.changed.emit()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isEnabled():
            extensions = " ".join(
                f"*{suffix}" for suffix in sorted(SUPPORTED_REFERENCE_SUFFIXES)
            )
            paths, _ = QFileDialog.getOpenFileNames(
                self,
                "选择参考资料",
                "",
                f"支持的文档 ({extensions});;所有文件 (*)",
            )
            if paths:
                self.add_files(paths)
        super().mousePressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if paths:
            self.add_files(paths)
        event.acceptProposedAction()


class MetricResultCard(QFrame):
    """Expandable, copyable rendering for one data-based indicator."""

    def __init__(self, indicator, position: int, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("metricResultCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        index_badge = QLabel(f"M{position:02d}")
        index_badge.setObjectName("metricResultIndex")
        self.toggle = QPushButton(
            f"›  {indicator.title}"
        )
        self.toggle.setObjectName("metricResultToggle")
        self.toggle.setCheckable(True)
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.setAccessibleName(f"展开指标：{indicator.title}")
        badges = QLabel(
            f"{indicator.category}  ·  优先级 {indicator.priority}  ·  "
            f"资料难度 {indicator.data_acquisition_difficulty}"
        )
        badges.setObjectName("metricResultBadges")
        header.addWidget(index_badge)
        header.addWidget(self.toggle, stretch=1)
        header.addWidget(badges)
        layout.addLayout(header)

        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(9, 2, 4, 4)
        body_layout.setSpacing(8)
        body_layout.addWidget(
            _result_section("适用依据", indicator.target_basis)
        )
        if indicator.regulatory_references:
            body_layout.addWidget(
                _result_section(
                    "第5号文依据",
                    "、".join(indicator.regulatory_references),
                    accent=True,
                )
            )
        scope_lines = []
        if indicator.population_definition:
            scope_lines.append(f"总体范围：{indicator.population_definition}")
        if indicator.coverage_period:
            scope_lines.append(f"覆盖期间：{indicator.coverage_period}")
        if scope_lines:
            body_layout.addWidget(
                _result_section("核查范围与期间", "\n".join(scope_lines))
            )
        if indicator.exception_rules:
            body_layout.addWidget(
                _result_section(
                    "异常判定规则",
                    "\n".join(f"• {item}" for item in indicator.exception_rules),
                )
            )
        if indicator.follow_up_procedures:
            body_layout.addWidget(
                _result_section(
                    "异常后续核查",
                    "\n".join(
                        f"{index}. {item}"
                        for index, item in enumerate(
                            indicator.follow_up_procedures,
                            start=1,
                        )
                    ),
                )
            )
        if indicator.expected_evidence:
            body_layout.addWidget(
                _result_section(
                    "预期核查证据",
                    "\n".join(f"• {item}" for item in indicator.expected_evidence),
                )
            )
        if indicator.scope_limitations:
            body_layout.addWidget(
                _result_section(
                    "范围限制",
                    "\n".join(f"• {item}" for item in indicator.scope_limitations),
                )
            )
        for requirement in indicator.data_requirements:
            fields = "、".join(requirement.get("required_fields") or [])
            keys = "、".join(requirement.get("join_keys") or [])
            lines = []
            if requirement.get("business_purpose"):
                lines.append(f"用途：{requirement.get('business_purpose')}")
            lines.extend(
                [
                    f"颗粒度：{requirement.get('grain', '')}",
                    f"必需字段：{fields}",
                ]
            )
            if requirement.get("recommended_period"):
                lines.append(
                    f"建议期间：{requirement.get('recommended_period')}"
                )
            if keys:
                lines.append(f"关联键：{keys}")
            if requirement.get("scope_and_completeness"):
                lines.append(
                    "范围要求："
                    + str(requirement.get("scope_and_completeness"))
                )
            body_layout.addWidget(
                _result_section(
                    f"所需数据 · {requirement.get('dataset_name', '')}",
                    "\n".join(lines),
                    accent=True,
                )
            )
        body_layout.addWidget(
            _result_section(
                "向客户索取资料的建议",
                indicator.client_request_guidance,
                accent=True,
            )
        )
        body_layout.addWidget(
            _result_section("核查目标", indicator.analysis_objective)
        )
        if indicator.definition:
            body_layout.addWidget(
                _result_section("指标定义", indicator.definition)
            )
        if indicator.formula:
            body_layout.addWidget(
                _result_section("计算口径", indicator.formula)
            )
        grain_text = indicator.analysis_grain
        if indicator.dimensions:
            grain_text = (
                grain_text
                + ("\n" if grain_text else "")
                + "分析维度：" + "、".join(indicator.dimensions)
            )
        if grain_text:
            body_layout.addWidget(_result_section("分析颗粒度", grain_text))
        body_layout.addWidget(
            _result_section(
                "分析方法",
                "\n".join(
                    f"{index}. {step}"
                    for index, step in enumerate(
                        indicator.analysis_method,
                        start=1,
                    )
                ),
            )
        )
        if indicator.key_scope_questions:
            body_layout.addWidget(
                _result_section(
                    "需要进一步确认的口径",
                    "\n".join(f"• {item}" for item in indicator.key_scope_questions),
                )
            )
        if indicator.potential_anomalies:
            body_layout.addWidget(
                _result_section(
                    "可能识别的异常",
                    "\n".join(f"• {item}" for item in indicator.potential_anomalies),
                )
            )
        if indicator.evidence_basis:
            body_layout.addWidget(
                _result_section(
                    "信息依据",
                    "\n".join(f"• {item}" for item in indicator.evidence_basis),
                )
            )
        if indicator.assumptions:
            body_layout.addWidget(
                _result_section(
                    "指标假设",
                    "\n".join(f"• {item}" for item in indicator.assumptions),
                )
            )
        copy_button = QPushButton("复制资料索取建议")
        copy_button.setObjectName("metricSecondaryButton")
        copy_button.setCursor(Qt.PointingHandCursor)
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(
                indicator.client_request_guidance
            )
        )
        body_layout.addWidget(copy_button, alignment=Qt.AlignLeft)
        self.body.setVisible(False)
        layout.addWidget(self.body)
        self.toggle.toggled.connect(self._toggle_body)

    def _toggle_body(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        text = self.toggle.text()
        self.toggle.setText(("⌄" if expanded else "›") + text[1:])


class MetricDiscoveryPage(QWidget):
    """One-page form and result surface for the indicator feature."""

    analysis_requested = Signal(object)
    cancel_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("metricDiscoveryPage")
        self.setStyleSheet(METRIC_DISCOVERY_STYLE)
        self._busy = False
        self._last_result: MetricDiscoveryResult | None = None
        self._busy_message = ""
        self._last_elapsed_seconds = 0.0
        self._elapsed_timer = QElapsedTimer()
        self._elapsed_ui_timer = QTimer(self)
        self._elapsed_ui_timer.setInterval(1000)
        self._elapsed_ui_timer.timeout.connect(self._refresh_elapsed_display)
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self._hide_feedback)
        self._build_ui()
        self._connect_change_signals()
        self._refresh_summary()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("metricPageHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 14, 24, 14)
        title = QLabel("商业分析指标生成")
        title.setObjectName("metricPageTitle")
        self.generate_button = QPushButton()
        self.generate_button.setObjectName("metricHeaderGenerate")
        self.generate_button.setFixedSize(40, 40)
        self.generate_button.setIcon(_generate_action_icon())
        self.generate_button.setIconSize(QSize(21, 21))
        self.generate_button.setToolTip("开始分析并生成指标")
        self.generate_button.setAccessibleName("开始分析并生成指标")
        self.generate_button.setCursor(Qt.PointingHandCursor)
        self.generate_button.clicked.connect(self._submit)
        self.reset_button = QPushButton("重置")
        self.reset_button.setObjectName("metricResetButton")
        self.reset_button.setMinimumHeight(38)
        self.reset_button.setCursor(Qt.PointingHandCursor)
        self.reset_button.setToolTip("清空当前填写内容、附件和生成结果")
        self.reset_button.clicked.connect(self._confirm_reset)
        self.return_result_button = QPushButton("←  返回结果")
        self.return_result_button.setObjectName("metricBackButton")
        self.return_result_button.setCursor(Qt.PointingHandCursor)
        self.return_result_button.setVisible(False)
        self.return_result_button.clicked.connect(self._show_last_result)
        self.edit_button = QPushButton("调整指标")
        self.edit_button.setObjectName("metricSecondaryButton")
        self.edit_button.setCursor(Qt.PointingHandCursor)
        self.edit_button.setVisible(False)
        self.edit_button.clicked.connect(self._show_form)
        header_layout.addWidget(title, stretch=1)
        header_layout.addWidget(self.return_result_button)
        header_layout.addWidget(self.reset_button)
        header_layout.addWidget(self.generate_button)
        header_layout.addWidget(self.edit_button)
        root.addWidget(header)

        self.page_stack = QStackedWidget()
        self.page_stack.addWidget(self._build_form_page())
        self.result_scroll = QScrollArea()
        self.result_scroll.setObjectName("metricResultScroll")
        self.result_scroll.setWidgetResizable(True)
        self.result_host = QWidget()
        self.result_host.setObjectName("metricResultHost")
        self.result_layout = QVBoxLayout(self.result_host)
        self.result_layout.setContentsMargins(28, 18, 28, 28)
        self.result_layout.setSpacing(14)
        self.result_scroll.setWidget(self.result_host)
        self.page_stack.addWidget(self.result_scroll)
        root.addWidget(self.page_stack, stretch=1)

    def _build_form_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("metricFormPage")
        page_layout = QGridLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setObjectName("metricFormScroll")
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignTop)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.form_scroll = scroll
        host = QWidget()
        host.setObjectName("metricFormHost")
        host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.form_host = host
        layout = QVBoxLayout(host)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)

        columns = QHBoxLayout()
        columns.setSpacing(12)
        self.company_card = self._build_company_card()
        self.guidance_card = self._build_guidance_card()
        columns.addWidget(self.company_card, stretch=1)
        columns.addWidget(self.guidance_card, stretch=1)
        layout.addLayout(columns)
        self.attachment_card = self._build_attachment_card()
        layout.addWidget(self.attachment_card)
        scroll.setWidget(host)
        page_layout.addWidget(scroll, 0, 0)

        floating_controls = QWidget()
        floating_controls.setObjectName("metricFloatingControls")
        floating_layout = QVBoxLayout(floating_controls)
        floating_layout.setContentsMargins(0, 0, 14, 14)
        floating_layout.setSpacing(7)
        self.feedback_label = QLabel("")
        self.feedback_label.setObjectName("metricFeedback")
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setMinimumWidth(340)
        self.feedback_label.setMaximumWidth(430)
        self.feedback_label.setVisible(False)
        floating_layout.addWidget(self.feedback_label)

        self.busy_frame = QFrame()
        self.busy_frame.setObjectName("metricBusyFrame")
        self.busy_frame.setMinimumWidth(400)
        self.busy_frame.setMaximumWidth(430)
        busy_layout = QHBoxLayout(self.busy_frame)
        busy_layout.setContentsMargins(12, 9, 12, 9)
        self.busy_label = QLabel("正在生成")
        self.busy_label.setObjectName("metricBusyLabel")
        self.busy_progress = QProgressBar()
        self.busy_progress.setRange(0, 0)
        self.busy_progress.setTextVisible(False)
        self.busy_progress.setFixedHeight(5)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("metricSecondaryButton")
        self.cancel_button.clicked.connect(self.cancel_requested)
        busy_layout.addWidget(self.busy_label)
        busy_layout.addWidget(self.busy_progress, stretch=1)
        busy_layout.addWidget(self.cancel_button)
        self.busy_frame.setVisible(False)
        floating_layout.addWidget(self.busy_frame)

        page_layout.addWidget(
            floating_controls,
            0,
            0,
            alignment=Qt.AlignRight | Qt.AlignBottom,
        )
        return page

    def _build_company_card(self) -> QFrame:
        card = _form_card(
            "1  公司/行业基础信息",
            "填写已掌握的公司和业务信息",
            equal_height=True,
        )
        layout = card.layout()
        self.company_name = QLineEdit()
        self.company_name.setObjectName("metricTextInput")
        self.company_name.setClearButtonEnabled(True)
        self.company_name.setPlaceholderText("公司全称、简称或品牌名称")
        layout.addWidget(_labeled_widget("公司名称", self.company_name))

        research_box = ResearchEnhancementCard()
        research_box.setObjectName("metricResearchBox")
        research_layout = QHBoxLayout(research_box)
        research_layout.setContentsMargins(12, 12, 12, 12)
        research_layout.setSpacing(12)

        research_copy = QVBoxLayout()
        research_copy.setContentsMargins(0, 0, 0, 0)
        research_copy.setSpacing(5)
        research_title_row = QHBoxLayout()
        research_title_row.setContentsMargins(0, 0, 0, 0)
        research_title_row.setSpacing(7)
        research_title = QLabel("企业情报增强")
        research_title.setObjectName("metricResearchTitle")
        research_badge = QLabel("天眼查 AI")
        research_badge.setObjectName("metricResearchBadge")
        research_title_row.addWidget(
            research_title,
            alignment=Qt.AlignVCenter,
        )
        research_title_row.addWidget(
            research_badge,
            alignment=Qt.AlignVCenter,
        )
        research_title_row.addStretch()
        research_hint = QLabel(
            "通过天眼查 AI 与公开信息检索，补充公司背景与行业信息"
        )
        research_hint.setObjectName("metricResearchHint")
        research_hint.setWordWrap(True)
        research_copy.addLayout(research_title_row)
        research_copy.addWidget(research_hint)

        self.public_research = MetricToggleSwitch()
        self.public_research.setObjectName("metricPublicResearch")
        self.public_research.setAccessibleName("企业情报增强")
        self.public_research.setToolTip(
            "启用后将通过天眼查 AI 与公开信息检索，补充公司背景与行业信息"
        )
        self._research_box = research_box
        research_box.setCursor(Qt.PointingHandCursor)
        research_box.setToolTip(self.public_research.toolTip())
        research_box.clicked.connect(self.public_research.toggle)
        self.public_research.toggled.connect(
            self._sync_research_enhancement_state
        )
        research_layout.addLayout(research_copy, stretch=1)
        research_layout.addWidget(
            self.public_research,
            alignment=Qt.AlignVCenter,
        )
        layout.addWidget(research_box)
        self._sync_research_enhancement_state(False)

        self.industries = DropdownMultiSelect(
            "所属行业",
            INDUSTRY_OPTIONS,
            placeholder="选择所属行业",
            hierarchical=True,
        )
        layout.addWidget(self.industries)

        self.business_models = DropdownMultiSelect(
            "主要经营方式",
            BUSINESS_MODEL_OPTIONS,
            placeholder="选择主要经营方式",
        )
        layout.addWidget(self.business_models)

        self.influencer_promotion = ConditionalChoiceField()
        self.influencer_promotion.setVisible(False)
        layout.addWidget(self.influencer_promotion)

        self.products_services = DropdownMultiSelect(
            "主要产品或服务",
            PRODUCT_SERVICE_OPTIONS,
            placeholder="选择主要产品或服务",
            hierarchical=True,
        )
        layout.addWidget(self.products_services)

        self.customer_types = DropdownMultiSelect(
            "主要客户类型",
            CUSTOMER_TYPE_OPTIONS,
            placeholder="选择主要客户类型",
        )
        layout.addWidget(self.customer_types)

        self.additional_information = QPlainTextEdit()
        self.additional_information.setObjectName("metricLongInput")
        self.additional_information.setMaximumHeight(82)
        self.additional_information.setPlaceholderText(
            "可填写增长情况、客户集中、经销模式、项目背景等任何已知信息"
        )
        layout.addWidget(
            _labeled_widget(
                "其他已知信息",
                self.additional_information,
            )
        )
        return card

    def _build_guidance_card(self) -> QFrame:
        card = _form_card(
            "2  指标生成指引",
            "选择核查方向与重点",
            equal_height=True,
        )
        layout = card.layout()

        regulatory_box = ResearchEnhancementCard()
        regulatory_box.setObjectName("metricResearchBox")
        regulatory_layout = QHBoxLayout(regulatory_box)
        regulatory_layout.setContentsMargins(12, 12, 12, 12)
        regulatory_layout.setSpacing(12)

        regulatory_copy = QVBoxLayout()
        regulatory_copy.setContentsMargins(0, 0, 0, 0)
        regulatory_copy.setSpacing(5)
        regulatory_title_row = QHBoxLayout()
        regulatory_title_row.setContentsMargins(0, 0, 0, 0)
        regulatory_title_row.setSpacing(7)
        regulatory_title = QLabel("发行类第5号针对分析")
        regulatory_title.setObjectName("metricResearchTitle")
        regulatory_badge = QLabel("监管规则适用指引")
        regulatory_badge.setObjectName("metricResearchBadge")
        regulatory_title_row.addWidget(
            regulatory_title,
            alignment=Qt.AlignVCenter,
        )
        regulatory_title_row.addWidget(
            regulatory_badge,
            alignment=Qt.AlignVCenter,
        )
        regulatory_title_row.addStretch()
        regulatory_hint = QLabel("强化IT审计指标、核查范围与证据要求")
        regulatory_hint.setObjectName("metricResearchHint")
        regulatory_hint.setWordWrap(True)
        regulatory_copy.addLayout(regulatory_title_row)
        regulatory_copy.addWidget(regulatory_hint)

        self.regulatory_analysis = MetricToggleSwitch()
        self.regulatory_analysis.setObjectName("metricRegulatoryAnalysis")
        self.regulatory_analysis.setAccessibleName("发行类第5号针对分析")
        self.regulatory_analysis.setToolTip(
            "按《监管规则适用指引——发行类第5号》强化IT审计指标、"
            "核查范围、异常跟进与证据要求"
        )
        self._regulatory_box = regulatory_box
        regulatory_box.setCursor(Qt.PointingHandCursor)
        regulatory_box.setToolTip(self.regulatory_analysis.toolTip())
        regulatory_box.clicked.connect(self.regulatory_analysis.toggle)
        self.regulatory_analysis.toggled.connect(
            self._sync_regulatory_analysis_state
        )
        regulatory_layout.addLayout(regulatory_copy, stretch=1)
        regulatory_layout.addWidget(
            self.regulatory_analysis,
            alignment=Qt.AlignVCenter,
        )
        layout.addWidget(regulatory_box)
        self._sync_regulatory_analysis_state(False)

        self.directions = ChipMultiSelect(
            "分析方向",
            ANALYSIS_DIRECTION_OPTIONS,
            hint="重点分析的业务领域",
        )
        layout.addWidget(self.directions)
        self.focuses = ChipMultiSelect(
            "核查重点",
            ANALYSIS_FOCUS_OPTIONS,
            hint="指标需要识别的问题",
        )
        layout.addWidget(self.focuses)

        self.indicator_count = IndicatorCountField()
        layout.addWidget(self.indicator_count)
        return card

    def _build_attachment_card(self) -> QFrame:
        card = _form_card(
            "3  附件资料",
            "PDF、Word、PowerPoint、TXT、Markdown",
        )
        layout = card.layout()
        self.drop_zone = ReferenceDropZone()
        self.drop_zone.validation_failed.connect(self._show_form_error)
        layout.addWidget(self.drop_zone)

        self.attachment_list = QListWidget()
        self.attachment_list.setObjectName("metricAttachmentList")
        self.attachment_list.setMaximumHeight(88)
        self.attachment_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.attachment_list.setVisible(False)
        layout.addWidget(self.attachment_list)
        remove_button = QPushButton("移除所选文件")
        remove_button.setObjectName("metricSecondaryButton")
        remove_button.setCursor(Qt.PointingHandCursor)
        remove_button.clicked.connect(self._remove_selected_attachments)
        self.remove_attachment_button = remove_button
        remove_button.setVisible(False)
        layout.addWidget(remove_button, alignment=Qt.AlignRight)
        return card

    def _connect_change_signals(self) -> None:
        self.company_name.textChanged.connect(self._refresh_summary)
        self.industries.changed.connect(self._refresh_summary)
        self.business_models.changed.connect(
            self._sync_influencer_promotion_visibility
        )
        self.business_models.changed.connect(self._refresh_summary)
        self.influencer_promotion.changed.connect(self._refresh_summary)
        self.products_services.changed.connect(self._refresh_summary)
        self.customer_types.changed.connect(self._refresh_summary)
        self.additional_information.textChanged.connect(self._refresh_summary)
        self.public_research.toggled.connect(self._refresh_summary)
        self.regulatory_analysis.toggled.connect(self._refresh_summary)
        self.directions.changed.connect(self._refresh_summary)
        self.focuses.changed.connect(self._refresh_summary)
        self.indicator_count.changed.connect(self._refresh_summary)
        self.drop_zone.changed.connect(self._refresh_attachment_list)

    def _sync_research_enhancement_state(self, enabled: bool) -> None:
        self._research_box.setProperty("enhanced", enabled)
        self._research_box.style().unpolish(self._research_box)
        self._research_box.style().polish(self._research_box)

    def _sync_regulatory_analysis_state(self, enabled: bool) -> None:
        self._regulatory_box.setProperty("enhanced", enabled)
        self._regulatory_box.style().unpolish(self._regulatory_box)
        self._regulatory_box.style().polish(self._regulatory_box)

    def _sync_influencer_promotion_visibility(self) -> None:
        enabled = "电商销售" in self.business_models.selected_values()
        if not enabled:
            self.influencer_promotion.clear()
        self.influencer_promotion.setVisible(enabled)
        self.influencer_promotion.updateGeometry()

    def build_request(self) -> MetricDiscoveryRequest:
        business_models = self.business_models.selected_values()
        company_information = {
            "company_name": self.company_name.text().strip(),
            "industries": self.industries.selected_values(),
            "industry_custom": self.industries.custom_values(),
            "business_models": business_models,
            "business_model_custom": self.business_models.custom_values(),
            "products_services": self.products_services.selected_values(),
            "products_services_custom": self.products_services.custom_values(),
            "customer_types": self.customer_types.selected_values(),
            "customer_type_custom": self.customer_types.custom_values(),
            "additional_information": (
                self.additional_information.toPlainText().strip()
            ),
        }
        if "电商销售" in business_models:
            company_information["ecommerce_marketing"] = {
                "uses_influencer_promotion": (
                    self.influencer_promotion.value()
                ),
                "user_confirmed": (
                    self.influencer_promotion.value() is not None
                ),
                "scope_definition": [
                    "达人直播带货",
                    "达人短视频或图文种草",
                    "达人橱窗、商品链接或专属推广链接",
                    "MCN机构或达人合作投放",
                ],
            }
        request = MetricDiscoveryRequest(
            company_information=company_information,
            indicator_guidance={
                "directions": self.directions.selected_values(),
                "direction_custom": self.directions.custom_values(),
                "focuses": self.focuses.selected_values(),
                "focus_custom": self.focuses.custom_values(),
                "indicator_count": self.indicator_count.value(),
            },
            attachments=self.drop_zone.attachments(),
            public_research_enabled=self.public_research.isChecked(),
            regulatory_analysis_enabled=self.regulatory_analysis.isChecked(),
        )
        request.validate()
        return request

    def show_busy(self, message: str = "正在准备指标生成请求") -> None:
        self._busy = True
        self._busy_message = message
        self._elapsed_timer.start()
        self._elapsed_ui_timer.start()
        self.feedback_label.setVisible(False)
        self._refresh_elapsed_display()
        self.busy_progress.setRange(0, 0)
        self.busy_frame.setVisible(True)
        self.generate_button.setEnabled(False)
        self.reset_button.setEnabled(False)
        self.return_result_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

    def handle_event(self, event: dict) -> None:
        self._busy_message = str(event.get("message") or "正在生成")
        self._refresh_elapsed_display()
        current = event.get("current")
        total = event.get("total")
        if isinstance(current, int) and isinstance(total, int) and total > 0:
            self.busy_progress.setRange(0, total)
            self.busy_progress.setValue(current)
        else:
            self.busy_progress.setRange(0, 0)

    def show_error(self, message: str) -> None:
        self._busy = False
        self._elapsed_ui_timer.stop()
        self._elapsed_timer.invalidate()
        self.busy_frame.setVisible(False)
        self.generate_button.setEnabled(True)
        self.reset_button.setEnabled(True)
        self.return_result_button.setEnabled(True)
        cancelled = "cancel" in message.lower() or "取消" in message
        self._show_form_error(
            "已取消本次生成。" if cancelled else message,
            auto_hide_ms=3600 if cancelled else 0,
        )

    def apply_company_selection(
        self,
        candidate: CompanyCandidate,
        original_query: str,
    ) -> None:
        """Reflect the confirmed legal entity in the editable form."""
        self.company_name.setText(candidate.company_name)
        if original_query.strip() and (
            original_query.strip() != candidate.company_name
        ):
            self.company_name.setToolTip(
                f"由“{original_query.strip()}”确认的工商主体"
            )
        else:
            self.company_name.setToolTip("已确认工商主体")

    def resume_after_company_selection_cancel(self) -> None:
        """Return to the form without treating an explicit edit as a failure."""
        self._busy = False
        self._elapsed_ui_timer.stop()
        self._elapsed_timer.invalidate()
        self.busy_frame.setVisible(False)
        self.generate_button.setEnabled(True)
        self.reset_button.setEnabled(True)
        self.return_result_button.setEnabled(True)
        self.feedback_label.setVisible(False)
        self.company_name.setFocus()
        self.company_name.selectAll()

    def show_result(self, result: MetricDiscoveryResult) -> None:
        self._busy = False
        self._last_result = result
        if self._elapsed_timer.isValid():
            self._last_elapsed_seconds = self._elapsed_timer.elapsed() / 1000
        else:
            self._last_elapsed_seconds = 0.0
        self._elapsed_ui_timer.stop()
        self._elapsed_timer.invalidate()
        self.busy_frame.setVisible(False)
        self.generate_button.setEnabled(True)
        self.reset_button.setEnabled(True)
        self.return_result_button.setEnabled(True)
        _clear_layout(self.result_layout)

        hero = QFrame()
        hero.setObjectName("metricResultHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(20, 18, 20, 18)
        hero_layout.setSpacing(8)
        hero_top = QHBoxLayout()
        status = QLabel("生成完成")
        status.setObjectName("metricResultStatus")
        self.result_duration_label = QLabel(
            f"耗时 {_format_result_elapsed(self._last_elapsed_seconds)}"
        )
        self.result_duration_label.setObjectName("metricResultDuration")
        hero_top.addWidget(status, alignment=Qt.AlignLeft)
        hero_top.addStretch()
        hero_top.addWidget(self.result_duration_label)
        hero_layout.addLayout(hero_top)

        count = QLabel(f"{len(result.indicators)} 项数据核查指标")
        count.setObjectName("metricResultCount")
        hero_layout.addWidget(count)
        summary = QLabel(result.summary)
        summary.setObjectName("metricResultSummary")
        summary.setWordWrap(True)
        hero_layout.addWidget(summary)

        result_meta = QHBoxLayout()
        indicator_meta = QLabel(f"指标 {len(result.indicators)} 项")
        indicator_meta.setObjectName("metricResultMeta")
        request_meta = QLabel(
            f"资料需求 {len(result.consolidated_data_requests)} 类"
        )
        request_meta.setObjectName("metricResultMeta")
        result_meta.addWidget(indicator_meta)
        result_meta.addWidget(request_meta)
        result_meta.addStretch()
        hero_layout.addLayout(result_meta)
        self.result_layout.addWidget(hero)

        if result.regulatory_review:
            applicability = _regulatory_applicability_text(
                result.regulatory_review
            )
            if applicability:
                self.result_layout.addWidget(
                    _result_section(
                        "发行类第5号 · 适用性判断",
                        applicability,
                        accent=True,
                    )
                )
            non_data_procedures = result.regulatory_review.get(
                "non_data_procedures"
            ) or []
            if non_data_procedures:
                self.result_layout.addWidget(
                    _result_section(
                        "非数据核查程序",
                        "\n".join(
                            f"• {item}" for item in non_data_procedures
                        ),
                    )
                )
            scope_limitations = result.regulatory_review.get(
                "scope_limitations"
            ) or []
            if scope_limitations:
                self.result_layout.addWidget(
                    _result_section(
                        "专项核查范围限制",
                        "\n".join(f"• {item}" for item in scope_limitations),
                    )
                )

        if result.source_notes:
            self.result_layout.addWidget(
                _result_section(
                    "信息来源",
                    "\n".join(f"• {item}" for item in result.source_notes),
                )
            )
        if result.assumptions:
            assumption = QLabel(
                "分析假设：" + "；".join(result.assumptions)
            )
            assumption.setObjectName("metricResultAssumption")
            assumption.setWordWrap(True)
            self.result_layout.addWidget(assumption)

        if result.consolidated_data_requests:
            request_header = QHBoxLayout()
            title = QLabel("客户资料清单")
            title.setObjectName("metricResultSectionTitle")
            request_count = QLabel(
                f"{len(result.consolidated_data_requests)} 类"
            )
            request_count.setObjectName("metricSectionCount")
            copy_all = QPushButton("复制全部资料清单")
            copy_all.setObjectName("metricSecondaryButton")
            copy_all.setCursor(Qt.PointingHandCursor)
            copy_all.clicked.connect(
                lambda: QApplication.clipboard().setText(
                    _consolidated_request_text(
                        result.consolidated_data_requests
                    )
                )
            )
            request_header.addWidget(title)
            request_header.addWidget(request_count)
            request_header.addStretch()
            request_header.addWidget(copy_all)
            self.result_layout.addLayout(request_header)
            for request in result.consolidated_data_requests:
                name = str(
                    request.get("dataset_name")
                    or request.get("name")
                    or "资料需求"
                )
                fields = request.get("required_fields") or []
                text = str(request.get("description") or "")
                if fields:
                    text += ("\n" if text else "") + "必需字段：" + "、".join(
                        str(field) for field in fields
                    )
                self.result_layout.addWidget(
                    _result_section(name, text, accent=True)
                )

        indicators_header = QHBoxLayout()
        indicators_title = QLabel("分析指标")
        indicators_title.setObjectName("metricResultSectionTitle")
        indicators_count = QLabel(f"{len(result.indicators)} 项")
        indicators_count.setObjectName("metricSectionCount")
        indicators_header.addWidget(indicators_title)
        indicators_header.addWidget(indicators_count)
        indicators_header.addStretch()
        self.result_layout.addLayout(indicators_header)
        for index, indicator in enumerate(result.indicators, start=1):
            card = MetricResultCard(indicator, index)
            self.result_layout.addWidget(card)
        self.result_layout.addStretch()
        self.page_stack.setCurrentIndex(1)
        self.result_scroll.verticalScrollBar().setValue(0)
        self.generate_button.setVisible(False)
        self.return_result_button.setVisible(False)
        self.edit_button.setVisible(True)

    def _show_form(self) -> None:
        self.page_stack.setCurrentIndex(0)
        self.edit_button.setVisible(False)
        self.return_result_button.setVisible(self._last_result is not None)
        self.generate_button.setVisible(True)
        self.form_scroll.setFocus()

    def _show_last_result(self) -> None:
        if self._last_result is None or self._busy:
            return
        self.page_stack.setCurrentIndex(1)
        self.generate_button.setVisible(False)
        self.return_result_button.setVisible(False)
        self.edit_button.setVisible(True)
        self.result_scroll.setFocus()

    def _refresh_elapsed_display(self) -> None:
        if not self._elapsed_timer.isValid():
            return
        elapsed_seconds = self._elapsed_timer.elapsed() // 1000
        minutes, seconds = divmod(elapsed_seconds, 60)
        self.busy_label.setText(
            f"{self._busy_message}  ·  {minutes:02d}:{seconds:02d}"
        )

    def _submit(self) -> None:
        if self._busy:
            return
        try:
            request = self.build_request()
        except MetricDiscoveryContractError as exc:
            self._show_form_error(str(exc))
            return
        self._hide_feedback()
        self.show_busy()
        self.analysis_requested.emit(request)

    def _show_form_error(
        self,
        message: str,
        *,
        auto_hide_ms: int = 0,
    ) -> None:
        self._feedback_timer.stop()
        self.feedback_label.setText(_friendly_metric_error(message))
        self.feedback_label.setVisible(True)
        if auto_hide_ms > 0:
            self._feedback_timer.start(auto_hide_ms)

    def _hide_feedback(self) -> None:
        self._feedback_timer.stop()
        self.feedback_label.clear()
        self.feedback_label.setVisible(False)

    def _confirm_reset(self) -> None:
        if self._busy:
            return
        if self._has_form_content() or self._last_result is not None:
            answer = QMessageBox.question(
                self,
                "重置指标生成",
                "清空当前填写内容、附件和生成结果？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        self.reset()

    def reset(self) -> None:
        """Return the indicator feature to a clean initial state."""
        if self._busy:
            return
        self.company_name.clear()
        self.company_name.setToolTip("")
        self.public_research.setChecked(False)
        self.regulatory_analysis.setChecked(False)
        self.industries.clear()
        self.business_models.clear()
        self.products_services.clear()
        self.customer_types.clear()
        self.additional_information.clear()
        self.directions.clear()
        self.focuses.clear()
        self.indicator_count.clear()
        self.drop_zone.clear()
        self._last_result = None
        self._last_elapsed_seconds = 0.0
        self.page_stack.setCurrentIndex(0)
        self.edit_button.setVisible(False)
        self.return_result_button.setVisible(False)
        self.generate_button.setVisible(True)
        self.form_scroll.verticalScrollBar().setValue(0)
        self._show_form_error("已重置指标生成内容。", auto_hide_ms=3000)
        self.company_name.setFocus()

    def _refresh_attachment_list(self) -> None:
        self.attachment_list.clear()
        for attachment in self.drop_zone.attachments():
            size_mb = attachment.size_bytes / (1024 * 1024)
            item = QListWidgetItem(
                f"{attachment.name}    {size_mb:.1f} MB"
            )
            item.setData(Qt.UserRole, attachment.path)
            item.setToolTip(attachment.path)
            self.attachment_list.addItem(item)
        visible = self.attachment_list.count() > 0
        self.attachment_list.setVisible(visible)
        self.remove_attachment_button.setVisible(visible)
        self._refresh_summary()

    def _remove_selected_attachments(self) -> None:
        paths = {
            str(item.data(Qt.UserRole))
            for item in self.attachment_list.selectedItems()
        }
        if paths:
            self.drop_zone.remove_paths(paths)

    def _refresh_summary(self) -> None:
        has_input = self._has_form_content()
        self.generate_button.setAccessibleDescription(
            "已填写分析信息" if has_input else "尚未填写分析信息"
        )
        if has_input and self.feedback_label.isVisible() and not self._busy:
            self._hide_feedback()

    def _has_form_content(self) -> bool:
        return any(
            (
                bool(self.company_name.text().strip()),
                bool(
                    self.industries.selected_values()
                    or self.industries.custom_values()
                ),
                bool(
                    self.business_models.selected_values()
                    or self.business_models.custom_values()
                ),
                bool(
                    self.products_services.selected_values()
                    or self.products_services.custom_values()
                ),
                bool(
                    self.customer_types.selected_values()
                    or self.customer_types.custom_values()
                ),
                bool(self.additional_information.toPlainText().strip()),
                bool(
                    self.directions.selected_values()
                    or self.directions.custom_values()
                ),
                bool(
                    self.focuses.selected_values()
                    or self.focuses.custom_values()
                ),
                self.influencer_promotion.value() is not None,
                self.indicator_count.value() is not None,
                bool(self.drop_zone.attachments()),
                self.regulatory_analysis.isChecked(),
            )
        )


def _generate_action_icon() -> QIcon:
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    # Lucide "chart-no-axes-column-increasing" icon (ISC License).
    pen = QPen(QColor("#FFFFFF"), 2.1)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.drawLine(5, 21, 5, 15)
    painter.drawLine(12, 21, 12, 9)
    painter.drawLine(19, 21, 19, 3)
    painter.end()
    return QIcon(pixmap)


def _form_card(
    title: str,
    subtitle: str,
    *,
    equal_height: bool = False,
) -> QFrame:
    card = QFrame()
    card.setObjectName("metricFormCard")
    card.setSizePolicy(
        QSizePolicy.Preferred,
        QSizePolicy.Expanding if equal_height else QSizePolicy.Maximum,
    )
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)
    layout.setAlignment(Qt.AlignTop)
    title_label = QLabel(title)
    title_label.setObjectName("metricCardTitle")
    subtitle_label = QLabel(subtitle)
    subtitle_label.setObjectName("metricCardSubtitle")
    subtitle_label.setWordWrap(True)
    layout.addWidget(title_label)
    layout.addWidget(subtitle_label)
    return card


def _labeled_widget(label: str, widget: QWidget) -> QWidget:
    host = QWidget()
    host.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(5)
    layout.setAlignment(Qt.AlignTop)
    title = QLabel(label)
    title.setObjectName("metricFieldLabel")
    layout.addWidget(title)
    layout.addWidget(widget)
    return host


def _result_section(title: str, text: str, accent: bool = False) -> QFrame:
    frame = QFrame()
    frame.setObjectName(
        "metricResultAccentSection" if accent else "metricResultSection"
    )
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(10, 8, 10, 8)
    layout.setSpacing(3)
    heading = QLabel(title)
    heading.setObjectName("metricResultSectionTitle")
    body = QLabel(text or "—")
    body.setObjectName("metricResultSectionBody")
    body.setWordWrap(True)
    body.setTextInteractionFlags(Qt.TextSelectableByMouse)
    layout.addWidget(heading)
    layout.addWidget(body)
    return frame


def _consolidated_request_text(requests) -> str:
    blocks = []
    for index, request in enumerate(requests, start=1):
        name = str(
            request.get("dataset_name")
            or request.get("name")
            or "资料需求"
        )
        lines = [f"{index}. {name}"]
        for label, key in (
            ("用途", "description"),
            ("颗粒度", "grain"),
            ("建议期间", "recommended_period"),
            ("范围要求", "scope_and_completeness"),
        ):
            value = request.get(key)
            if value:
                lines.append(f"{label}：{value}")
        fields = request.get("required_fields") or []
        if fields:
            lines.append(
                "必需字段：" + "、".join(str(field) for field in fields)
            )
        keys = request.get("join_keys") or []
        if keys:
            lines.append(
                "关联键：" + "、".join(str(key) for key in keys)
            )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _regulatory_applicability_text(review: dict) -> str:
    rows = review.get("applicability_assessment") or []
    lines = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        section = str(row.get("section") or "").strip()
        status = str(row.get("status") or "待确认").strip()
        basis = str(row.get("basis") or "").strip()
        if not section:
            continue
        line = f"{section}：{status}"
        if basis:
            line += f"；{basis}"
        lines.append(line)
    return "\n".join(lines)


def _friendly_metric_error(message: str) -> str:
    """Convert backend/workflow details into a short actionable UI message."""
    text = str(message or "").strip()
    if not text:
        return "指标生成失败，请稍后重试。"

    lowered = text.casefold()
    if "provide at least one company detail" in lowered:
        return "请填写一项公司信息、分析要求，或添加一份资料。"
    if "indicator count must" in lowered:
        return "指标数量需为 5—10 之间的整数。"
    if "spreadsheet data belongs" in lowered:
        name = text.split(":", 1)[0]
        return f"{name}：Excel、CSV 请在数据分析页面添加。"
    if "unsupported reference type" in lowered:
        name = text.split(":", 1)[0]
        return f"{name}：不支持该文件格式。"
    if "file is unavailable" in lowered or "file cannot be read" in lowered:
        name = text.split(":", 1)[0]
        return f"{name}：文件无法读取。"

    truncation_markers = (
        "指标生成结果疑似因输出长度限制被截断",
        "output length",
        "maximum output",
        "max_tokens",
        "finish_reason: length",
    )
    if any(marker in lowered for marker in truncation_markers):
        return (
            "Dify 生成的指标结果可能因输出长度限制被截断。"
            "请缩短单次生成内容，或提高模型节点的最大输出长度后重试。"
        )

    json_markers = (
        "jsondecodeerror",
        "指标生成结果不是合法json",
        "expecting ',' delimiter",
        "expecting property name",
        "unterminated string",
        "invalid json",
    )
    if any(marker in lowered for marker in json_markers):
        return (
            "Dify 生成的指标结果格式不完整，未能完成解析。"
            "请检查指标生成节点的结构化输出、最大输出长度和字段长度限制后重试。"
        )

    if "regulatory_review" in lowered or "regulatory indicator" in lowered:
        return (
            "第5号文专项结果不完整。请确认已按项目说明更新并发布 Dify "
            "指标工作流后重试。"
        )
    if "regulatory applicability assessment" in lowered:
        return (
            "第5号文适用性判断未覆盖全部章节。请检查 Dify 指标工作流的"
            "专项输出契约。"
        )

    sandbox_markers = (
        "process exited with code",
        "sandbox-python",
        "traceback (most recent call last)",
        'file "<fd3>"',
    )
    if any(marker in lowered for marker in sandbox_markers):
        return (
            "Dify 工作流内部节点执行失败。请在 Dify 运行日志中检查失败节点，"
            "修正后重新运行。"
        )

    # Never render an unbounded backend traceback inside the desktop form.
    max_length = 500
    if len(text) > max_length:
        return f"{text[:max_length]}……"
    return text


def _split_custom_values(text: str) -> list[str]:
    values = []
    seen = set()
    for part in re.split(r"[,，;；\n]+", text):
        value = part.strip()
        if not value or value.casefold() in seen:
            continue
        seen.add(value.casefold())
        values.append(value)
    return values


def _clear_layout(layout: QLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if child_layout is not None:
            _clear_layout(child_layout)
        if widget is not None:
            widget.hide()
            widget.deleteLater()


def _format_result_elapsed(seconds: float) -> str:
    total_seconds = max(0, round(seconds))
    if total_seconds < 1:
        return "不足 1 秒"
    minutes, remaining_seconds = divmod(total_seconds, 60)
    if minutes:
        return f"{minutes} 分 {remaining_seconds:02d} 秒"
    return f"{remaining_seconds} 秒"


METRIC_DISCOVERY_STYLE = """
QWidget#metricDiscoveryPage, QWidget#metricFormPage, QWidget#metricFormHost,
QWidget#metricResultHost {
    background: #F7F9FC;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
}
QFrame#metricPageHeader {
    background: #FFFFFF;
    border-bottom: 1px solid #E4E9F0;
}
QLabel#metricPageTitle {
    color: #172033;
    font-size: 20px;
    font-weight: 600;
}
QScrollArea#metricFormScroll, QScrollArea#metricResultScroll {
    background: #F7F9FC;
    border: none;
}
QFrame#metricFormCard {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 10px;
}
QLabel#metricCardTitle {
    color: #1D2939;
    font-size: 14px;
    font-weight: 600;
}
QLabel#metricCardSubtitle, QLabel#metricFieldHint {
    color: #7A8594;
    font-size: 11px;
    font-weight: 400;
}
QLabel#metricFieldLabel {
    color: #344054;
    font-size: 12px;
    font-weight: 500;
}
QLineEdit#metricTextInput, QLineEdit#metricOtherInput,
QLineEdit#metricDialogSearch, QPlainTextEdit#metricLongInput,
QPlainTextEdit#metricCatalogCustom, QSpinBox {
    color: #1F2937;
    background: #FFFFFF;
    border: 1px solid #CDD5DF;
    border-radius: 7px;
    padding: 7px 9px;
    min-height: 24px;
    font-size: 12px;
}
QLineEdit#metricTextInput:focus, QLineEdit#metricOtherInput:focus,
QLineEdit#metricDialogSearch:focus, QPlainTextEdit#metricLongInput:focus,
QPlainTextEdit#metricCatalogCustom:focus, QSpinBox:focus {
    border-color: #1A73E8;
}
QCheckBox#metricChoiceCheckbox {
    background: transparent;
    border: none;
    padding: 0;
    font-size: 11px;
    font-weight: 500;
}
QPushButton#metricInlineAction {
    color: #1765CC;
    background: transparent;
    border: none;
    padding: 5px 3px;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#metricInlineAction:hover {
    color: #0B57D0;
    text-decoration: underline;
}
QPushButton#metricMultiSelectButton,
QPushButton#metricModernSelect {
    text-align: left;
    color: #1D2129;
    background: #FFFFFF;
    border: 1px solid #C9CDD4;
    border-radius: 7px;
    padding: 8px 34px 8px 12px;
    min-height: 20px;
    font-size: 12px;
    font-weight: 500;
}
QPushButton#metricMultiSelectButton[placeholder="true"],
QPushButton#metricModernSelect[placeholder="true"] {
    color: #86909C;
    font-weight: 400;
}
QPushButton#metricMultiSelectButton:hover,
QPushButton#metricModernSelect:hover {
    color: #1D2129;
    border-color: #86909C;
    background: #F7F8FA;
}
QPushButton#metricMultiSelectButton:focus,
QPushButton#metricModernSelect:focus,
QPushButton#metricMultiSelectButton[open="true"],
QPushButton#metricModernSelect[open="true"] {
    color: #1D2129;
    border-color: #165DFF;
    background: #FFFFFF;
}
QPushButton#metricMultiSelectButton:disabled,
QPushButton#metricModernSelect:disabled {
    color: #C9CDD4;
    border-color: #E5E6EB;
    background: #F7F8FA;
}
QLabel#metricSelectionSummary {
    color: #667085;
    font-size: 11px;
    font-weight: 400;
}
QFrame#metricResearchBox {
    background: #F7F8FA;
    border: 1px solid #E5E6EB;
    border-radius: 9px;
}
QFrame#metricResearchBox:hover {
    background: #F2F3F5;
    border-color: #C9CDD4;
}
QFrame#metricResearchBox[enhanced="true"] {
    background: #F2F7FF;
    border-color: #94BFFF;
}
QLabel#metricResearchTitle {
    color: #1D2129;
    font-size: 12px;
    font-weight: 500;
}
QLabel#metricResearchHint {
    color: #86909C;
    font-size: 11px;
    font-weight: 400;
}
QLabel#metricResearchBadge {
    color: #165DFF;
    background: #E8F3FF;
    border-radius: 7px;
    padding: 1px 6px;
    font-size: 9px;
    font-weight: 500;
}
QFrame#metricSelectPopup {
    background: #FFFFFF;
    border: 1px solid #C9CDD4;
    border-radius: 8px;
}
QFrame#metricMultiSelectPopup {
    background: #FFFFFF;
    border: 1px solid #C9CDD4;
    border-radius: 8px;
}
QLabel#metricDropdownTitle {
    color: #1D2939;
    font-size: 13px;
    font-weight: 700;
}
QScrollArea#metricDropdownScroll {
    background: #FFFFFF;
    border: 1px solid #E5EAF0;
    border-radius: 7px;
}
QPushButton#metricCategoryOption {
    color: #475467;
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 8px 9px;
    text-align: left;
    font-size: 11px;
}
QPushButton#metricCategoryOption:hover,
QPushButton#metricCategoryOption[active="true"] {
    color: #174EA6;
    background: #E8F0FE;
    font-weight: 650;
}
QCheckBox#metricDropdownCheck {
    color: #344054;
    background: transparent;
    border-radius: 6px;
    padding: 7px 8px;
    spacing: 8px;
    font-size: 11px;
}
QCheckBox#metricDropdownCheck:hover {
    color: #174EA6;
    background: #F2F7FE;
}
QFrame#metricDropdownOtherRow {
    background: #F8FAFC;
    border: 1px solid #E5EAF0;
    border-radius: 7px;
}
QPushButton#metricSelectOption {
    color: #344054;
    background: transparent;
    border: none;
    border-radius: 7px;
    padding: 7px 10px;
    text-align: left;
    font-size: 11px;
    font-weight: 500;
}
QPushButton#metricSelectOption:hover {
    color: #174EA6;
    background: #F2F7FE;
}
QPushButton#metricSelectOption[selected="true"] {
    color: #174EA6;
    background: #E8F0FE;
    font-weight: 650;
}
QFrame#metricDropZone {
    background: #FAFBFC;
    border: 1px solid #C9D2DE;
    border-radius: 8px;
}
QFrame#metricDropZone:hover {
    background: #F2F7FE;
    border-color: #1A73E8;
}
QLabel#metricDropTitle {
    color: #344054;
    font-size: 12px;
    font-weight: 650;
}
QLabel#metricDialogTitle {
    color: #1D2939;
    font-size: 16px;
    font-weight: 700;
}
QListWidget#metricAttachmentList, QListWidget#metricCatalogList,
QListWidget#metricCatalogCategories {
    color: #344054;
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 4px;
    font-size: 12px;
}
QListWidget#metricCatalogList::item {
    padding: 8px 7px;
    border-radius: 5px;
}
QListWidget#metricCatalogList::item:hover {
    background: #F6F9FD;
}
QListWidget#metricCatalogCategories::item {
    padding: 8px 9px;
    border-radius: 6px;
}
QListWidget#metricCatalogCategories::item:selected {
    color: #174EA6;
    background: #E8F0FE;
    font-weight: 650;
}
QPushButton#metricPrimaryButton {
    color: #FFFFFF;
    background: #1A73E8;
    border: none;
    border-radius: 7px;
    padding: 10px 18px;
    font-size: 12px;
    font-weight: 700;
}
QPushButton#metricPrimaryButton:hover { background: #1765CC; }
QPushButton#metricPrimaryButton:disabled { background: #AFC9EC; }
QPushButton#metricSecondaryButton {
    color: #344054;
    background: #FFFFFF;
    border: 1px solid #D0D7E2;
    border-radius: 6px;
    padding: 7px 11px;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#metricSecondaryButton:hover {
    color: #174EA6;
    border-color: #8AB4F8;
    background: #F4F8FE;
}
QPushButton#metricBackButton {
    color: #165DFF;
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 7px 9px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#metricBackButton:hover {
    color: #0E42D2;
    background: #F2F3F5;
}
QPushButton#metricBackButton:disabled {
    color: #C9CDD4;
    background: transparent;
}
QPushButton#metricResetButton {
    color: #4E5969;
    background: #FFFFFF;
    border: 1px solid #C9CDD4;
    border-radius: 7px;
    padding: 7px 12px;
    font-size: 12px;
    font-weight: 500;
}
QPushButton#metricResetButton:hover {
    color: #165DFF;
    border-color: #94BFFF;
    background: #F2F7FF;
}
QPushButton#metricResetButton:disabled {
    color: #C9CDD4;
    border-color: #E5E6EB;
    background: #F7F8FA;
}
QWidget#metricFloatingControls {
    background: transparent;
}
QPushButton#metricHeaderGenerate {
    color: #FFFFFF;
    background: #1A73E8;
    border: none;
    border-radius: 20px;
}
QPushButton#metricHeaderGenerate:hover {
    background: #1765CC;
}
QPushButton#metricHeaderGenerate:pressed {
    background: #0B57D0;
}
QPushButton#metricHeaderGenerate:disabled {
    background: #AFC9EC;
}
QLabel#metricFeedback {
    color: #9B1C1C;
    background: #FEF2F2;
    border: 1px solid #FECACA;
    border-radius: 6px;
    padding: 7px 10px;
    font-size: 11px;
    font-weight: 550;
}
QFrame#metricBusyFrame {
    background: #F5F9FF;
    border: 1px solid #D7E5F9;
    border-radius: 7px;
}
QLabel#metricBusyLabel {
    color: #344054;
    font-size: 11px;
    font-weight: 600;
}
QProgressBar {
    border: none;
    background: #DDE6F1;
    border-radius: 2px;
}
QProgressBar::chunk {
    background: #1A73E8;
    border-radius: 2px;
}
QCheckBox#metricPublicResearch {
    background: transparent;
    border: none;
    padding: 0;
}
QFrame#metricResultHero {
    background: #FFFFFF;
    border: 1px solid #E5E6EB;
    border-radius: 12px;
}
QLabel#metricResultStatus {
    color: #00B42A;
    background: #E8FFEA;
    border-radius: 8px;
    padding: 3px 9px;
    font-size: 10px;
    font-weight: 700;
}
QLabel#metricResultDuration {
    color: #4E5969;
    font-size: 11px;
    font-weight: 500;
}
QLabel#metricResultMeta, QLabel#metricSectionCount {
    color: #4E5969;
    background: #F2F3F5;
    border-radius: 8px;
    padding: 3px 8px;
    font-size: 10px;
    font-weight: 600;
}
QFrame#metricResultCard {
    background: #FFFFFF;
    border: 1px solid #E5E6EB;
    border-radius: 10px;
}
QFrame#metricResultCard:hover {
    border-color: #A9C7FF;
}
QLabel#metricResultIndex {
    color: #165DFF;
    background: #E8F3FF;
    border-radius: 8px;
    padding: 4px 7px;
    font-size: 10px;
    font-weight: 700;
}
QPushButton#metricResultToggle {
    color: #1D2129;
    background: transparent;
    border: none;
    text-align: left;
    font-size: 13px;
    font-weight: 700;
    padding: 4px 0;
}
QPushButton#metricResultToggle:hover { color: #165DFF; }
QLabel#metricResultBadges {
    color: #4E5969;
    background: #F2F3F5;
    border-radius: 9px;
    padding: 4px 8px;
    font-size: 10px;
    font-weight: 600;
}
QLabel#metricResultCount {
    color: #1D2129;
    font-size: 20px;
    font-weight: 700;
}
QLabel#metricResultSummary {
    color: #4E5969;
    font-size: 12px;
    font-weight: 400;
}
QLabel#metricResultAssumption {
    color: #7A4D00;
    background: #FFF7E8;
    border: 1px solid #FFCF8B;
    border-radius: 8px;
    padding: 9px 11px;
    font-size: 11px;
    font-weight: 500;
}
QFrame#metricResultSection {
    background: #F7F8FA;
    border: 1px solid #E5E6EB;
    border-radius: 8px;
}
QFrame#metricResultAccentSection {
    background: #F2F7FF;
    border: 1px solid #BEDAFF;
    border-radius: 8px;
}
QLabel#metricResultSectionTitle {
    color: #1D2129;
    font-size: 13px;
    font-weight: 700;
}
QLabel#metricResultSectionBody {
    color: #4E5969;
    font-size: 11px;
    font-weight: 400;
}
"""
