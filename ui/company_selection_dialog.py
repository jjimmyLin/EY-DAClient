"""Centered legal-entity selection dialog for indicator preflight."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.company_resolution import CompanyCandidate


class CompanyCandidateCard(QFrame):
    """One radio-selectable company candidate."""

    selected = Signal(object)

    def __init__(
        self,
        candidate: CompanyCandidate,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.candidate = candidate
        self.setObjectName("companyCandidateCard")
        self.setProperty("selected", False)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(76)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setSpacing(9)
        self.radio = QRadioButton(candidate.company_name)
        self.radio.setObjectName("companyCandidateRadio")
        self.radio.setCursor(Qt.PointingHandCursor)
        self.radio.setAccessibleName(
            f"选择工商主体：{candidate.company_name}"
        )
        self.radio.toggled.connect(self._on_toggled)
        title_row.addWidget(self.radio, stretch=1)

        if candidate.status:
            status = QLabel(candidate.status)
            status.setObjectName("companyCandidateStatus")
            status.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            title_row.addWidget(status)
        layout.addLayout(title_row)

        identity_parts = []
        if candidate.credit_code:
            identity_parts.append(
                f"统一社会信用代码：{candidate.credit_code}"
            )
        if candidate.legal_representative:
            identity_parts.append(
                f"法定代表人：{candidate.legal_representative}"
            )
        if candidate.established_date:
            identity_parts.append(
                f"成立日期：{candidate.established_date}"
            )
        if identity_parts:
            identity = QLabel("  ·  ".join(identity_parts))
            identity.setObjectName("companyCandidateMeta")
            identity.setWordWrap(True)
            identity.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            layout.addWidget(identity)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.radio.setChecked(True)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _on_toggled(self, checked: bool) -> None:
        self.setProperty("selected", checked)
        self.style().unpolish(self)
        self.style().polish(self)
        if checked:
            self.selected.emit(self.candidate)


class CompanySelectionDialog(QDialog):
    """Blocking, centered choice for an ambiguous company query."""

    def __init__(
        self,
        original_query: str,
        candidates: tuple[CompanyCandidate, ...],
        parent=None,
    ) -> None:
        super().__init__(
            parent,
            Qt.Dialog | Qt.FramelessWindowHint,
        )
        self.setObjectName("companySelectionDialog")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        self.setFixedWidth(680)
        self._selected_candidate: CompanyCandidate | None = None
        self._cards: list[CompanyCandidateCard] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        panel = QFrame()
        panel.setObjectName("companySelectionPanel")
        outer.addWidget(panel)

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(22, 18, 22, 18)
        panel_layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        title = QLabel("请选择工商主体")
        title.setObjectName("companySelectionTitle")
        subtitle = QLabel(
            f"“{original_query}”匹配到以下企业，请确认本次分析对象"
        )
        subtitle.setObjectName("companySelectionSubtitle")
        subtitle.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        close_button = QPushButton("×")
        close_button.setObjectName("companySelectionClose")
        close_button.setFixedSize(30, 30)
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.setToolTip("返回修改")
        close_button.setAccessibleName("关闭工商主体选择")
        close_button.clicked.connect(self.reject)
        header.addLayout(title_box, stretch=1)
        header.addWidget(close_button, alignment=Qt.AlignTop)
        panel_layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setObjectName("companySelectionScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(min(350, max(110, len(candidates) * 88)))
        scroll.setMaximumHeight(350)
        host = QWidget()
        host.setObjectName("companySelectionHost")
        candidates_layout = QVBoxLayout(host)
        candidates_layout.setContentsMargins(0, 0, 4, 0)
        candidates_layout.setSpacing(8)

        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        for index, candidate in enumerate(candidates):
            card = CompanyCandidateCard(candidate)
            card.selected.connect(self._select_candidate)
            self._button_group.addButton(card.radio, index)
            self._cards.append(card)
            candidates_layout.addWidget(card)
        candidates_layout.addStretch()
        scroll.setWidget(host)
        panel_layout.addWidget(scroll)

        guidance = QLabel(
            "请选择与本次项目资料和业务范围对应的法律主体。"
        )
        guidance.setObjectName("companySelectionGuidance")
        guidance.setWordWrap(True)
        panel_layout.addWidget(guidance)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        edit_button = QPushButton("返回修改")
        edit_button.setObjectName("companySelectionSecondary")
        edit_button.setCursor(Qt.PointingHandCursor)
        edit_button.clicked.connect(self.reject)
        self.confirm_button = QPushButton("使用该主体并继续")
        self.confirm_button.setObjectName("companySelectionPrimary")
        self.confirm_button.setCursor(Qt.PointingHandCursor)
        self.confirm_button.setEnabled(False)
        self.confirm_button.clicked.connect(self.accept)
        footer.addStretch()
        footer.addWidget(edit_button)
        footer.addWidget(self.confirm_button)
        panel_layout.addLayout(footer)

        self.setStyleSheet(COMPANY_SELECTION_STYLE)

    def selected_candidate(self) -> CompanyCandidate | None:
        return self._selected_candidate

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.adjustSize()
        parent = self.parentWidget()
        if parent is None:
            return
        center = parent.window().frameGeometry().center()
        geometry = self.frameGeometry()
        geometry.moveCenter(center)
        self.move(geometry.topLeft())

    def _select_candidate(self, candidate: CompanyCandidate) -> None:
        self._selected_candidate = candidate
        self.confirm_button.setEnabled(True)


COMPANY_SELECTION_STYLE = """
QDialog#companySelectionDialog {
    background: transparent;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
}
QFrame#companySelectionPanel {
    background: #FFFFFF;
    border: 1px solid #D9DDE5;
    border-radius: 12px;
}
QLabel#companySelectionTitle {
    color: #1D2129;
    font-size: 17px;
    font-weight: 700;
}
QLabel#companySelectionSubtitle {
    color: #4E5969;
    font-size: 12px;
}
QPushButton#companySelectionClose {
    color: #86909C;
    background: transparent;
    border: none;
    border-radius: 6px;
    font-size: 20px;
}
QPushButton#companySelectionClose:hover {
    color: #1D2129;
    background: #F2F3F5;
}
QScrollArea#companySelectionScroll {
    background: transparent;
    border: none;
}
QWidget#companySelectionHost {
    background: #FFFFFF;
}
QFrame#companyCandidateCard {
    background: #FFFFFF;
    border: 1px solid #E5E6EB;
    border-radius: 9px;
}
QFrame#companyCandidateCard:hover {
    background: #F7F8FA;
    border-color: #A9C7FF;
}
QFrame#companyCandidateCard[selected="true"] {
    background: #F2F7FF;
    border: 2px solid #165DFF;
}
QRadioButton#companyCandidateRadio {
    color: #1D2129;
    background: transparent;
    spacing: 9px;
    font-size: 13px;
    font-weight: 650;
}
QRadioButton#companyCandidateRadio::indicator {
    width: 16px;
    height: 16px;
}
QLabel#companyCandidateStatus {
    color: #00A870;
    background: #E8FFEA;
    border-radius: 7px;
    padding: 2px 7px;
    font-size: 10px;
    font-weight: 650;
}
QLabel#companyCandidateMeta {
    color: #86909C;
    font-size: 10px;
}
QLabel#companySelectionGuidance {
    color: #86909C;
    font-size: 11px;
}
QPushButton#companySelectionSecondary,
QPushButton#companySelectionPrimary {
    border-radius: 7px;
    padding: 8px 14px;
    min-height: 20px;
    font-size: 12px;
    font-weight: 650;
}
QPushButton#companySelectionSecondary {
    color: #4E5969;
    background: #FFFFFF;
    border: 1px solid #C9CDD4;
}
QPushButton#companySelectionSecondary:hover {
    color: #165DFF;
    border-color: #94BFFF;
    background: #F7F8FA;
}
QPushButton#companySelectionPrimary {
    color: #FFFFFF;
    background: #165DFF;
    border: 1px solid #165DFF;
}
QPushButton#companySelectionPrimary:hover {
    background: #0E42D2;
    border-color: #0E42D2;
}
QPushButton#companySelectionPrimary:disabled {
    color: #FFFFFF;
    background: #A9C7FF;
    border-color: #A9C7FF;
}
"""
