"""Compact floating feedback card shown after a successful analysis."""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class ExperienceFeedbackCard(QFrame):
    """A small, non-modal consent prompt that never blocks result review."""

    useful = Signal()
    dismissed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("experienceFeedbackCard")
        self.setFixedSize(340, 126)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.hide()
        self._target_geometry = QRect()
        self._generation = 0
        self._acknowledging = False
        self._animation = QPropertyAnimation(self, b"geometry", self)
        self._animation.setDuration(180)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(15, 23, 42, 52))
        self.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(6)

        self.title_label = QLabel("你认为本次分析是否对你有用？")
        self.title_label.setObjectName("experienceFeedbackTitle")
        self.subtitle_label = QLabel("确认后将脱敏提取可复用经验，用于改进后续同类分析。")
        self.subtitle_label.setObjectName("experienceFeedbackSubtitle")
        self.subtitle_label.setWordWrap(True)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 4, 0, 0)
        actions.setSpacing(8)
        actions.addStretch()
        self.dismiss_button = QPushButton("暂不")
        self.dismiss_button.setObjectName("experienceDismissButton")
        self.dismiss_button.setCursor(Qt.PointingHandCursor)
        self.dismiss_button.setFixedSize(58, 30)
        self.useful_button = QPushButton("有用")
        self.useful_button.setObjectName("experienceUsefulButton")
        self.useful_button.setCursor(Qt.PointingHandCursor)
        self.useful_button.setFixedSize(66, 30)
        actions.addWidget(self.dismiss_button)
        actions.addWidget(self.useful_button)

        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        layout.addLayout(actions)

        self.useful_button.clicked.connect(self._accept)
        self.dismiss_button.clicked.connect(self._dismiss)
        self.setStyleSheet(
            """
            QFrame#experienceFeedbackCard {
                background-color: #FFFFFF;
                border: 1px solid #D7DCE2;
                border-radius: 8px;
            }
            QLabel#experienceFeedbackTitle {
                color: #202124;
                font-size: 13px;
                font-weight: 600;
            }
            QLabel#experienceFeedbackSubtitle {
                color: #687078;
                font-size: 11px;
                font-weight: 400;
            }
            QPushButton#experienceUsefulButton {
                color: #FFFFFF;
                background-color: #1A73E8;
                border: none;
                border-radius: 6px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton#experienceUsefulButton:hover {
                background-color: #1765CC;
            }
            QPushButton#experienceDismissButton {
                color: #4B5563;
                background-color: transparent;
                border: 1px solid #D7DCE2;
                border-radius: 6px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton#experienceDismissButton:hover {
                background-color: #F3F4F6;
                color: #202124;
            }
            """
        )

    def show_prompt(self, target_geometry: QRect) -> None:
        self._generation += 1
        self._acknowledging = False
        self._target_geometry = QRect(target_geometry)
        self.title_label.setText("你认为本次分析是否对你有用？")
        self.subtitle_label.setText(
            "确认后将脱敏提取可复用经验，用于改进后续同类分析。"
        )
        self.dismiss_button.show()
        self.useful_button.show()
        self.setFixedSize(target_geometry.size())
        self.setGeometry(
            target_geometry.adjusted(0, 12, 0, 12)
        )
        self.show()
        self.raise_()
        self._animation.stop()
        self._animation.setStartValue(self.geometry())
        self._animation.setEndValue(target_geometry)
        self._animation.start()

    def update_target_geometry(self, target_geometry: QRect) -> None:
        self._target_geometry = QRect(target_geometry)
        if self._acknowledging:
            target_geometry = QRect(
                target_geometry.right() - 209,
                target_geometry.top(),
                210,
                76,
            )
        if (
            self.isVisible()
            and self._animation.state() != QAbstractAnimation.Running
        ):
            self.setFixedSize(target_geometry.size())
            self.setGeometry(target_geometry)

    def show_thanks(self) -> None:
        self._acknowledging = True
        self._animation.stop()
        self.title_label.setText("谢谢！")
        self.subtitle_label.setText("你的反馈已收到。")
        self.dismiss_button.hide()
        self.useful_button.hide()
        old_geometry = self.geometry()
        self.setFixedSize(210, 76)
        self.move(old_geometry.right() - self.width(), old_geometry.top())
        self.raise_()
        generation = self._generation
        QTimer.singleShot(
            1400,
            lambda current=generation: self._hide_if_current(current),
        )

    def hide_prompt(self) -> None:
        self._generation += 1
        self._acknowledging = False
        self._animation.stop()
        self.hide()

    def _hide_if_current(self, generation: int) -> None:
        if generation == self._generation:
            self.hide()

    def _accept(self) -> None:
        self.useful_button.setEnabled(False)
        self.dismiss_button.setEnabled(False)
        self.useful.emit()
        self.show_thanks()
        self.useful_button.setEnabled(True)
        self.dismiss_button.setEnabled(True)

    def _dismiss(self) -> None:
        self.dismissed.emit()
        self.hide_prompt()
