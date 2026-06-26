"""Rich, scrollable presentation for structured local analysis results."""

from __future__ import annotations

import base64

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSequentialAnimationGroup, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.analysis_result import AnalysisResult, AnswerResult, InsightResult


class AnalysisResultPanel(QWidget):
    """Render summary, metrics, tables, charts, and supporting details."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("analysisResultPanel")
        self._plain_text = ""
        self._reveal_group: QSequentialAnimationGroup | None = None
        self._result: AnalysisResult | None = None
        self._selected_answer_index: int | None = None
        self._switch_group: QButtonGroup | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("resultScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(self.scroll)

        self.content = QWidget()
        self.content.setObjectName("resultContent")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(8, 4, 16, 16)
        self.content_layout.setSpacing(18)
        self.scroll.setWidget(self.content)
        self.set_empty_state("Add a dataset to begin.")

    def clear(self) -> None:
        self._clear_layout()
        self._plain_text = ""
        self._result = None
        self._selected_answer_index = None

    def setText(self, text: str) -> None:
        self.setPlainText(text)

    def setPlainText(self, text: str) -> None:
        self._plain_text = str(text or "")
        self.set_result(AnalysisResult(summary=self._plain_text))

    def toPlainText(self) -> str:
        return self._plain_text

    def setPlaceholderText(self, text: str) -> None:
        if not self._plain_text:
            self.set_empty_state(text)

    def set_empty_state(self, text: str) -> None:
        self._clear_layout()
        self._plain_text = ""
        self._result = None
        self._selected_answer_index = None
        empty = QLabel(str(text or ""))
        empty.setObjectName("resultEmpty")
        empty.setAlignment(Qt.AlignCenter)
        self.content_layout.addWidget(empty)
        self.content_layout.addStretch()

    def setReadOnly(self, value: bool) -> None:
        del value

    def set_result(self, result: AnalysisResult) -> None:
        self._result = result
        self._selected_answer_index = None
        self._render_result(result)

    def selected_answer_index(self) -> int | None:
        return self._selected_answer_index

    def export_result(self) -> AnalysisResult | None:
        if self._result is None:
            return None
        if self._selected_answer_index is None:
            return self._result
        return self._result.answer_result(self._selected_answer_index)

    def show_all_results(self) -> None:
        if self._result is None:
            return
        self._selected_answer_index = None
        self._render_result(self._result)

    def show_answer_result(self, answer_index: int) -> None:
        if self._result is None:
            return
        if answer_index < 0 or answer_index >= len(self._result.answers):
            return
        self._selected_answer_index = answer_index
        self._render_result(self._result.answer_result(answer_index))

    def _render_result(self, result: AnalysisResult) -> None:
        self._clear_layout()
        self._plain_text = result.raw_output or result.summary
        reveal_widgets: list[QWidget] = []

        if self._result is not None and len(self._result.answers) > 1:
            switcher = self._answer_switcher()
            self.content_layout.addWidget(switcher)
            reveal_widgets.append(switcher)

        if result.answers:
            answers_label = self._section_label("Answers")
            self.content_layout.addWidget(answers_label)
            reveal_widgets.append(answers_label)
            for index, answer in enumerate(result.answers, start=1):
                display_index = (
                    self._selected_answer_index + 1
                    if self._selected_answer_index is not None
                    else index
                )
                card = self._answer_card(answer, display_index)
                self.content_layout.addWidget(card)
                reveal_widgets.append(card)

        if result.summary or result.metrics:
            overview_host = QWidget()
            overview_host.setObjectName("resultOverviewGrid")
            overview_layout = QHBoxLayout(overview_host)
            overview_layout.setContentsMargins(0, 0, 0, 0)
            overview_layout.setSpacing(16)

            if result.summary:
                summary_host = QWidget()
                summary_layout = QVBoxLayout(summary_host)
                summary_layout.setContentsMargins(0, 0, 0, 0)
                summary_layout.setSpacing(7)
                summary_layout.addWidget(
                    self._section_label(
                        "Global summary" if result.answers else "Analysis summary",
                        "resultSectionEyebrow",
                    )
                )
                summary = QLabel(result.summary)
                summary.setObjectName("resultSummary")
                summary.setWordWrap(True)
                summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
                summary_layout.addWidget(summary)
                summary_layout.addStretch()
                overview_layout.addWidget(summary_host, stretch=5)

            if result.metrics:
                grid_host = QWidget()
                grid_host.setObjectName("metricGrid")
                grid_layout = QVBoxLayout(grid_host)
                grid_layout.setContentsMargins(0, 0, 0, 0)
                grid_layout.setSpacing(7)
                grid_layout.addWidget(self._section_label("Key metrics"))
                grid = QGridLayout()
                grid.setContentsMargins(0, 0, 0, 0)
                grid.setHorizontalSpacing(8)
                grid.setVerticalSpacing(8)
                for index, metric in enumerate(result.metrics[:9]):
                    card = QFrame()
                    card.setObjectName("metricCard")
                    card_layout = QVBoxLayout(card)
                    card_layout.setContentsMargins(10, 7, 10, 7)
                    card_layout.setSpacing(2)
                    label = QLabel(metric.label)
                    label.setObjectName("metricLabel")
                    value = QLabel(f"{metric.value}{metric.unit}")
                    value.setObjectName("metricValue")
                    value.setTextInteractionFlags(Qt.TextSelectableByMouse)
                    card_layout.addWidget(label)
                    card_layout.addWidget(value)
                    if metric.detail:
                        detail = QLabel(metric.detail)
                        detail.setObjectName("metricDetail")
                        detail.setWordWrap(True)
                        card_layout.addWidget(detail)
                    grid.addWidget(card, index // 2, index % 2)
                grid_layout.addLayout(grid)
                overview_layout.addWidget(grid_host, stretch=4)

            self.content_layout.addWidget(overview_host)
            reveal_widgets.append(overview_host)

        if result.charts:
            visuals_label = self._section_label("Visuals")
            self.content_layout.addWidget(visuals_label)
            reveal_widgets.append(visuals_label)
            for chart in result.charts:
                frame = QFrame()
                frame.setObjectName("resultBlock")
                layout = QVBoxLayout(frame)
                layout.setContentsMargins(14, 12, 14, 14)
                layout.setSpacing(8)
                title = QLabel(chart.title)
                title.setObjectName("resultBlockTitle")
                layout.addWidget(title)
                image = QLabel()
                image.setObjectName("resultChart")
                image.setAlignment(Qt.AlignCenter)
                pixmap = QPixmap()
                try:
                    pixmap.loadFromData(base64.b64decode(chart.image_base64))
                except (ValueError, TypeError):
                    pass
                if not pixmap.isNull():
                    available_width = max(
                        320,
                        min(760, self.scroll.viewport().width() - 48),
                    )
                    image.setPixmap(
                        pixmap.scaled(
                            available_width,
                            420,
                            Qt.KeepAspectRatio,
                            Qt.SmoothTransformation,
                        )
                    )
                else:
                    image.setText("Chart preview is unavailable.")
                layout.addWidget(image)
                if chart.caption:
                    caption = QLabel(chart.caption)
                    caption.setObjectName("resultCaption")
                    caption.setWordWrap(True)
                    layout.addWidget(caption)
                self.content_layout.addWidget(frame)
                reveal_widgets.append(frame)

        if result.tables:
            tables_label = self._section_label("Tables")
            self.content_layout.addWidget(tables_label)
            reveal_widgets.append(tables_label)
            for table in result.tables:
                frame = QFrame()
                frame.setObjectName("resultBlock")
                layout = QVBoxLayout(frame)
                layout.setContentsMargins(14, 12, 14, 14)
                layout.setSpacing(8)

                header = QHBoxLayout()
                title = QLabel(table.title)
                title.setObjectName("resultBlockTitle")
                count = QLabel(
                    f"{len(table.rows)} of {table.total_rows} rows"
                    if table.truncated
                    else f"{table.total_rows} rows"
                )
                count.setObjectName("resultCount")
                header.addWidget(title)
                header.addStretch()
                header.addWidget(count)
                layout.addLayout(header)

                widget = QTableWidget(len(table.rows), len(table.columns))
                widget.setObjectName("resultTable")
                widget.setHorizontalHeaderLabels(table.columns)
                widget.setAlternatingRowColors(True)
                widget.setEditTriggers(QTableWidget.NoEditTriggers)
                widget.setSelectionBehavior(QTableWidget.SelectRows)
                for row_index, row in enumerate(table.rows):
                    for column_index, value in enumerate(row):
                        widget.setItem(
                            row_index,
                            column_index,
                            QTableWidgetItem("" if value is None else str(value)),
                        )
                widget.resizeColumnsToContents()
                widget.horizontalHeader().setStretchLastSection(True)
                widget.setSortingEnabled(True)
                widget.setMinimumHeight(150)
                widget.setMaximumHeight(380)
                widget.verticalHeader().setDefaultSectionSize(24)
                layout.addWidget(widget)
                self.content_layout.addWidget(frame)
                reveal_widgets.append(frame)

        if result.insights:
            findings_label = self._section_label("Findings")
            self.content_layout.addWidget(findings_label)
            reveal_widgets.append(findings_label)
            for insight in result.insights:
                row = self._insight_row(insight)
                self.content_layout.addWidget(row)
                reveal_widgets.append(row)

        if result.raw_output and result.raw_output != result.summary:
            details_button = QToolButton()
            details_button.setObjectName("resultDetailsButton")
            details_button.setText("Execution details")
            details_button.setCheckable(True)
            details_button.setArrowType(Qt.RightArrow)
            details = QTextEdit()
            details.setObjectName("resultRawOutput")
            details.setReadOnly(True)
            details.setPlainText(result.raw_output)
            details.setVisible(False)
            details.setMaximumHeight(180)

            def toggle_details(checked: bool) -> None:
                details_button.setArrowType(
                    Qt.DownArrow if checked else Qt.RightArrow
                )
                details.setVisible(checked)

            details_button.toggled.connect(toggle_details)
            self.content_layout.addWidget(details_button)
            self.content_layout.addWidget(details)
            reveal_widgets.extend([details_button, details])

        if self.content_layout.count() == 0:
            empty = QLabel("No analysis result is available yet.")
            empty.setObjectName("resultEmpty")
            empty.setAlignment(Qt.AlignCenter)
            self.content_layout.addWidget(empty)
            reveal_widgets.append(empty)

        self.content_layout.addStretch()
        self._animate_result_reveal(reveal_widgets)

    def _answer_switcher(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("answerSwitcher")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(6)

        label = QLabel("Results")
        label.setObjectName("answerSwitcherLabel")
        layout.addWidget(label)

        self._switch_group = QButtonGroup(frame)
        self._switch_group.setExclusive(True)

        all_button = self._answer_switch_button("All")
        all_button.setChecked(self._selected_answer_index is None)
        self._switch_group.addButton(all_button, -1)
        layout.addWidget(all_button)

        assert self._result is not None
        for index, answer in enumerate(self._result.answers):
            button = self._answer_switch_button(str(index + 1))
            button.setToolTip(answer.question or f"Result {index + 1}")
            button.setChecked(self._selected_answer_index == index)
            self._switch_group.addButton(button, index)
            layout.addWidget(button)

        self._switch_group.idClicked.connect(
            lambda button_id: (
                self.show_all_results()
                if button_id < 0
                else self.show_answer_result(button_id)
            )
        )
        layout.addStretch()
        return frame

    @staticmethod
    def _answer_switch_button(text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("answerSwitchButton")
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)
        button.setMinimumHeight(26)
        return button

    def _clear_layout(self) -> None:
        if self._reveal_group is not None:
            self._reveal_group.stop()
            self._reveal_group.deleteLater()
            self._reveal_group = None
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _animate_result_reveal(self, widgets: list[QWidget]) -> None:
        reveal_targets = [widget for widget in widgets if widget is not None and widget.isVisible()]
        if not reveal_targets:
            return
        group = QSequentialAnimationGroup(self)
        for widget in reveal_targets:
            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(0.0)
            widget.setGraphicsEffect(effect)
            animation = QPropertyAnimation(effect, b"opacity", group)
            animation.setStartValue(0.0)
            animation.setEndValue(1.0)
            animation.setDuration(150)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            group.addAnimation(animation)
        self._reveal_group = group
        group.start()

    @staticmethod
    def _section_label(
        text: str,
        object_name: str = "resultSectionLabel",
    ) -> QLabel:
        label = QLabel(text)
        label.setObjectName(object_name)
        return label

    @staticmethod
    def _answer_card(answer: AnswerResult, index: int) -> QFrame:
        frame = QFrame()
        frame.setObjectName("answerCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        number = QLabel(str(index))
        number.setObjectName("answerNumber")
        title = QLabel(answer.question or f"Question {index}")
        title.setObjectName("answerQuestion")
        title.setWordWrap(True)
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        header.addWidget(number, alignment=Qt.AlignTop)
        header.addWidget(title, stretch=1)
        layout.addLayout(header)

        body = QLabel(answer.answer or "No direct answer was returned.")
        body.setObjectName("answerBody")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(body)

        references = []
        for label, values in (
            ("Metric", answer.supporting_metrics),
            ("Table", answer.supporting_tables),
            ("Chart", answer.supporting_charts),
            ("Finding", answer.supporting_insights),
        ):
            references.extend(f"{label}: {value}" for value in values)
        if references:
            support_row = QHBoxLayout()
            support_row.setContentsMargins(0, 0, 0, 0)
            support_row.setSpacing(6)
            for reference in references[:8]:
                pill = QLabel(reference)
                pill.setObjectName("answerSupportPill")
                pill.setTextInteractionFlags(Qt.TextSelectableByMouse)
                support_row.addWidget(pill)
            support_row.addStretch()
            layout.addLayout(support_row)

        if answer.confidence_or_notes:
            notes = QLabel(answer.confidence_or_notes)
            notes.setObjectName("answerNotes")
            notes.setWordWrap(True)
            notes.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(notes)

        return frame

    @staticmethod
    def _insight_row(insight: InsightResult) -> QFrame:
        frame = QFrame()
        frame.setObjectName(
            "warningRow" if insight.kind == "warning" else "insightRow"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        title = QLabel(insight.title)
        title.setObjectName("insightTitle")
        detail = QLabel(insight.detail)
        detail.setObjectName("insightDetail")
        detail.setWordWrap(True)
        detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(title)
        layout.addWidget(detail)
        return frame


RESULT_PANEL_STYLE = """
QScrollArea#resultScroll, QWidget#resultContent {
    background: #FFFFFF;
    border: none;
}
QLabel#resultSectionEyebrow, QLabel#resultSectionLabel {
    color: #5F6368;
    font-size: 11px;
    font-weight: 700;
}
QLabel#resultSummary {
    color: #202124;
    font-size: 14px;
    font-weight: 500;
    line-height: 1.5;
}
QFrame#answerSwitcher {
    background: #F8F9FA;
    border: 1px solid #E8EAED;
    border-radius: 8px;
}
QLabel#answerSwitcherLabel {
    color: #5F6368;
    font-size: 11px;
    font-weight: 700;
}
QPushButton#answerSwitchButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 13px;
    color: #5F6368;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 650;
}
QPushButton#answerSwitchButton:hover {
    background: #EEF3FD;
    border-color: #D2E3FC;
    color: #1A73E8;
}
QPushButton#answerSwitchButton:checked {
    background: #E8F0FE;
    border-color: #AECBFA;
    color: #1A73E8;
}
QFrame#answerCard {
    background: #FFFFFF;
    border: 1px solid #DADCE0;
    border-left: 3px solid #1A73E8;
    border-radius: 8px;
}
QLabel#answerNumber {
    background: #E8F0FE;
    color: #1A73E8;
    border-radius: 10px;
    min-width: 20px;
    max-width: 20px;
    min-height: 20px;
    max-height: 20px;
    font-size: 11px;
    font-weight: 700;
    qproperty-alignment: AlignCenter;
}
QLabel#answerQuestion {
    color: #202124;
    font-size: 13px;
    font-weight: 650;
}
QLabel#answerBody {
    color: #3C4043;
    font-size: 13px;
    font-weight: 400;
    line-height: 1.45;
}
QLabel#answerSupportPill {
    background: #F1F3F4;
    color: #5F6368;
    border: 1px solid #E8EAED;
    border-radius: 10px;
    padding: 3px 7px;
    font-size: 10px;
    font-weight: 600;
}
QLabel#answerNotes {
    color: #6B7280;
    font-size: 11px;
    font-weight: 500;
}
QFrame#metricCard {
    background: #F8F9FA;
    border: 1px solid #E8EAED;
    border-radius: 8px;
}
QLabel#metricLabel, QLabel#metricDetail, QLabel#resultCount,
QLabel#resultCaption {
    color: #6B7280;
    font-size: 11px;
    font-weight: 500;
}
QLabel#metricValue {
    color: #202124;
    font-size: 18px;
    font-weight: 650;
}
QFrame#resultBlock {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
}
QLabel#resultBlockTitle, QLabel#insightTitle {
    color: #202124;
    font-size: 13px;
    font-weight: 650;
}
QLabel#resultChart {
    background: #FFFFFF;
    min-height: 180px;
}
QTableWidget#resultTable {
    background: #FFFFFF;
    alternate-background-color: #F8F9FA;
    border: 1px solid #E8EAED;
    border-radius: 4px;
    gridline-color: #EEF0F2;
    color: #202124;
    font-size: 11px;
}
QTableWidget#resultTable QHeaderView::section {
    background: #F1F3F4;
    color: #3C4043;
    border: none;
    border-right: 1px solid #E0E3E7;
    border-bottom: 1px solid #DADCE0;
    padding: 6px;
    font-weight: 650;
}
QFrame#insightRow, QFrame#warningRow {
    border: 1px solid #DDE4EE;
    border-left: 3px solid #1A73E8;
    border-radius: 6px;
    background: #F8FBFF;
}
QFrame#warningRow {
    border-left-color: #F9AB00;
    background: #FFFBF2;
}
QLabel#insightDetail {
    color: #4B5563;
    font-size: 12px;
    font-weight: 400;
}
QToolButton#resultDetailsButton {
    border: none;
    background: transparent;
    color: #5F6368;
    font-size: 11px;
    font-weight: 600;
    text-align: left;
}
QTextEdit#resultRawOutput {
    border: 1px solid #E5E7EB;
    border-radius: 6px;
    background: #F8F9FA;
    color: #4B5563;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
}
QLabel#resultEmpty {
    color: #9AA0A6;
    font-size: 13px;
    font-weight: 500;
    min-height: 240px;
}
"""
