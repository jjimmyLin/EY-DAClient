"""
ui/decision_panel.py
────────────────────
可复用的决策面板组件。

用于任何需要用户做选择的场景：
- 模型选择（可用模型列表）
- LLM 不确定时请求用户反馈
- 代码修订方案选择
- 任何需要 human-in-the-loop 的决策点

用法示例：
    panel = DecisionPanel(parent)
    panel.show_decision(
        title="Select Model",
        description="The following models are available:",
        options=[
            OptionItem("gemini-2.5-flash", "Fast, good for most tasks", tag="recommended"),
            OptionItem("gemini-2.5-pro", "Slower but more capable"),
        ],
    )
    panel.decision_made.connect(on_user_chose)   # 收到 OptionItem
    panel.decision_skipped.connect(on_user_skip)  # 用户点了 Skip
"""

from __future__ import annotations

from dataclasses import dataclass, field
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


@dataclass
class OptionItem:
    """一个可选项。"""
    label: str
    description: str = ""
    tag: str = ""           # 如 "recommended", "fast", "fallback"
    data: object = field(default=None, repr=False)  # 自定义载荷


class _OptionCard(QFrame):
    """单个选项卡片。"""

    clicked = Signal()

    def __init__(self, option: OptionItem, parent=None):
        super().__init__(parent)
        self.option = option
        self.setObjectName("optionCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFrameShape(QFrame.StyledPanel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(8)

        name = QLabel(option.label)
        name.setObjectName("optionLabel")
        header.addWidget(name)

        if option.tag:
            tag = QLabel(option.tag)
            tag.setObjectName("optionTag")
            header.addWidget(tag)

        header.addStretch()
        layout.addLayout(header)

        if option.description:
            desc = QLabel(option.description)
            desc.setObjectName("optionDesc")
            desc.setWordWrap(True)
            layout.addWidget(desc)

    def minimumSizeHint(self):
        return self.sizeHint()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class DecisionPanel(QWidget):
    """可复用的决策面板，嵌入到主工作区中。"""

    decision_made = Signal(object)    # 发送被选中的 OptionItem
    decision_skipped = Signal()       # 用户选择跳过

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("decisionPanel")
        self._cards: list[_OptionCard] = []

        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)

        self._container = QWidget()
        self._container.setObjectName("decisionContainer")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(40, 32, 40, 32)
        self._layout.setSpacing(16)
        self._root_layout.addWidget(self._container)

        self.hide()

    # ── public ──────────────────────────────────────────────

    def show_decision(
        self,
        title: str,
        description: str = "",
        options: list[OptionItem] | None = None,
        allow_skip: bool = True,
        skip_label: str = "Skip (auto)",
    ) -> None:
        """展示决策面板。

        Args:
            title: 标题（如 "Select Model"）。
            description: 说明文字。
            options: 可选项列表。
            allow_skip: 是否显示跳过按钮。
            skip_label: 跳过按钮文字。
        """
        self._clear()
        title_label = QLabel(title)
        title_label.setObjectName("decisionTitle")
        self._layout.addWidget(title_label)

        if description:
            desc_label = QLabel(description)
            desc_label.setObjectName("decisionDesc")
            desc_label.setWordWrap(True)
            self._layout.addWidget(desc_label)

        options = options or []
        if options:
            options_scroll = QScrollArea()
            options_scroll.setObjectName("decisionOptionsScroll")
            options_scroll.setFrameShape(QFrame.NoFrame)
            options_scroll.setWidgetResizable(True)
            options_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            options_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            options_scroll.setMinimumHeight(0)

            options_container = QWidget()
            options_container.setObjectName("decisionOptionsContainer")
            options_layout = QVBoxLayout(options_container)
            options_layout.setContentsMargins(0, 0, 0, 0)
            options_layout.setSpacing(12)

            for opt in options:
                card = _OptionCard(opt, self)
                card.clicked.connect(lambda o=opt: self._on_option_clicked(o))
                options_layout.addWidget(card)
                self._cards.append(card)

            options_layout.addStretch()
            options_container.setMinimumHeight(
                options_container.sizeHint().height()
            )
            options_scroll.setWidget(options_container)
            self._layout.addWidget(options_scroll, stretch=1)

        else:
            self._layout.addStretch()

        if allow_skip:
            footer = QHBoxLayout()
            footer.addStretch()
            skip_btn = QPushButton(skip_label)
            skip_btn.setObjectName("decisionSkipBtn")
            skip_btn.setCursor(Qt.PointingHandCursor)
            skip_btn.clicked.connect(self._on_skip)
            footer.addWidget(skip_btn)
            self._layout.addLayout(footer)

        self.show()

    # ── internal ────────────────────────────────────────────

    def _on_option_clicked(self, option: OptionItem) -> None:
        self.hide()
        self.decision_made.emit(option)

    def _on_skip(self) -> None:
        self.hide()
        self.decision_skipped.emit()

    def _clear(self) -> None:
        """清除面板内容，复用同一个实例。"""
        for card in self._cards:
            card.deleteLater()
        self._cards.clear()

        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            sub = item.layout()
            if sub:
                while sub.count():
                    child = sub.takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()


# ── 样式表（可被 MainWindow 合并到全局样式） ────────────────

DECISION_PANEL_STYLE = """
    QWidget#decisionContainer {
        background-color: #FFFFFF;
    }

    QScrollArea#decisionOptionsScroll {
        background-color: transparent;
        border: none;
    }

    QWidget#decisionOptionsContainer {
        background-color: #FFFFFF;
    }

    QLabel#decisionTitle {
        font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
        font-size: 18px;
        font-weight: 700;
        color: #111827;
        padding: 0;
        letter-spacing: 0;
    }

    QLabel#decisionDesc {
        font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
        font-size: 13px;
        font-weight: 400;
        color: #6B7280;
        letter-spacing: 0;
    }

    QFrame#optionCard {
        background-color: #F9FAFB;
        border: 1px solid #E5E7EB;
        border-radius: 10px;
    }

    QFrame#optionCard:hover {
        background-color: #EFF6FF;
        border-color: #3B82F6;
    }

    QLabel#optionLabel {
        font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
        font-size: 14px;
        font-weight: 600;
        color: #111827;
        letter-spacing: 0;
    }

    QLabel#optionTag {
        font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
        font-size: 11px;
        font-weight: 600;
        color: #059669;
        background-color: #ECFDF5;
        border-radius: 4px;
        padding: 2px 8px;
        letter-spacing: 0;
    }

    QLabel#optionDesc {
        font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
        font-size: 12px;
        font-weight: 400;
        color: #6B7280;
        letter-spacing: 0;
    }

    QPushButton#decisionSkipBtn {
        background-color: transparent;
        color: #6B7280;
        font-size: 13px;
        font-weight: 500;
        border: 1px solid #D1D5DB;
        border-radius: 6px;
        padding: 6px 16px;
    }

    QPushButton#decisionSkipBtn:hover {
        background-color: #F3F4F6;
        color: #374151;
    }
"""
