from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class OverviewPopover(QFrame):
    """Compact anchored popover for dataset overview."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._overview = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.surface = QFrame(self)
        self.surface.setObjectName("overviewPopoverSurface")
        outer.addWidget(self.surface)

        layout = QVBoxLayout(self.surface)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.title_label = QLabel("Dataset Overview")
        self.title_label.setObjectName("overviewPopoverTitle")
        header.addWidget(self.title_label)
        header.addStretch()
        layout.addLayout(header)

        self.topic_label = QLabel("Quick summary")
        self.topic_label.setObjectName("overviewPopoverTopic")
        self.topic_label.setWordWrap(True)
        layout.addWidget(self.topic_label)

        self.summary_label = QLabel("Overview is unavailable.")
        self.summary_label.setObjectName("overviewPopoverSummary")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        highlight_row = QHBoxLayout()
        highlight_row.setSpacing(8)
        self.badge_kind = QLabel("Overview")
        self.badge_kind.setObjectName("overviewBadgeKind")
        self.badge_topic = QLabel("Ready to inspect")
        self.badge_topic.setObjectName("overviewBadgeTopic")
        highlight_row.addWidget(self.badge_kind)
        highlight_row.addWidget(self.badge_topic, stretch=1)
        layout.addLayout(highlight_row)

        self.metrics_grid = QGridLayout()
        self.metrics_grid.setHorizontalSpacing(10)
        self.metrics_grid.setVerticalSpacing(10)
        self.metric_cards: list[QFrame] = []
        for index, label in enumerate(("Rows", "Columns", "Sheets")):
            card = QFrame()
            card.setObjectName("overviewMetricCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(2)
            title = QLabel(label)
            title.setObjectName("overviewMetricLabel")
            value = QLabel("-")
            value.setObjectName("overviewMetricValue")
            card_layout.addWidget(title)
            card_layout.addWidget(value)
            self.metrics_grid.addWidget(card, 0, index)
            self.metric_cards.append(card)
        layout.addLayout(self.metrics_grid)

        section_title = QLabel("Suggested Questions")
        section_title.setObjectName("overviewSectionTitle")
        layout.addWidget(section_title)

        self.suggestions_box = QWidget()
        self.suggestions_layout = QVBoxLayout(self.suggestions_box)
        self.suggestions_layout.setContentsMargins(0, 0, 0, 0)
        self.suggestions_layout.setSpacing(8)
        layout.addWidget(self.suggestions_box)

        self.setStyleSheet(
            """
            QFrame#overviewPopoverSurface {
                background-color: rgba(255, 255, 255, 252);
                border: 1px solid #DCE7F6;
                border-radius: 18px;
            }
            QLabel#overviewPopoverTitle {
                color: #111827;
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#overviewPopoverTopic {
                color: #1D4ED8;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#overviewPopoverSummary {
                color: #1F2937;
                font-size: 12px;
                line-height: 1.55;
            }
            QLabel#overviewBadgeKind {
                color: #1D4ED8;
                background-color: #EFF6FF;
                border: 1px solid #BFDBFE;
                border-radius: 999px;
                padding: 4px 9px;
                font-size: 11px;
                font-weight: 700;
            }
            QLabel#overviewBadgeTopic {
                color: #374151;
                background-color: #F8FAFC;
                border: 1px solid #E5E7EB;
                border-radius: 999px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QFrame#overviewMetricCard {
                background-color: #F8FAFC;
                border: 1px solid #DDE7F4;
                border-radius: 12px;
            }
            QLabel#overviewMetricLabel {
                color: #6B7280;
                font-size: 11px;
                font-weight: 600;
            }
            QLabel#overviewMetricValue {
                color: #0F172A;
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#overviewSectionTitle {
                color: #4B5563;
                font-size: 11px;
                font-weight: 700;
            }
            QLabel#overviewSuggestionPill {
                color: #111827;
                background-color: #F8FAFC;
                border: 1px solid #E5E7EB;
                border-radius: 12px;
                padding: 10px 12px;
                font-size: 12px;
                line-height: 1.45;
            }
            """
        )
        self.resize(404, 318)

    def setOverview(self, overview: dict) -> None:
        self._overview = overview
        dataset_kind = overview.get("dataset_kind") or "Dataset Overview"
        topic = overview.get("topic") or "Quick summary"
        self.title_label.setText(dataset_kind)
        self.topic_label.setText(topic)
        self.badge_kind.setText(dataset_kind)
        self.badge_topic.setText(topic)
        self.summary_label.setText(
            overview.get("summary") or "Overview is unavailable."
        )

        values = [
            str(overview.get("rows", "-")),
            str(overview.get("columns", "-")),
            str(overview.get("sheet_count", "-")),
        ]
        for card, value in zip(self.metric_cards, values):
            labels = card.findChildren(QLabel, "overviewMetricValue")
            if labels:
                labels[0].setText(value)

        while self.suggestions_layout.count():
            item = self.suggestions_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        suggestions = overview.get("suggestions") or []
        if suggestions:
            for suggestion in suggestions[:4]:
                label = QLabel(str(suggestion))
                label.setObjectName("overviewSuggestionPill")
                label.setWordWrap(True)
                self.suggestions_layout.addWidget(label)
        else:
            empty = QLabel("No suggested questions yet.")
            empty.setObjectName("overviewSuggestionPill")
            self.suggestions_layout.addWidget(empty)

        self.adjustSize()

    def showFor(self, anchor: QWidget, boundary: QWidget | None = None) -> None:
        self.adjustSize()
        anchor_rect = anchor.rect()
        global_anchor = anchor.mapToGlobal(anchor_rect.topRight())
        x = global_anchor.x() + 12
        y = global_anchor.y() - 4

        if boundary is not None:
            frame = boundary.frameGeometry()
            if x + self.width() > frame.right() - 16:
                x = anchor.mapToGlobal(anchor_rect.topLeft()).x() - self.width() - 12
            y = max(frame.top() + 56, min(y, frame.bottom() - self.height() - 20))

        self.move(QPoint(x, y))
        self.show()
        self.raise_()
