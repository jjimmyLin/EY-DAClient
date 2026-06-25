"""Flat matrix interface for deterministic data cleaning - COMPACT OPTIMIZED VERSION"""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)


METHOD_LABELS = {
    "drop_rows": "Delete rows",
    "fill_zero": "Fill zero",
    "fill_mean": "Fill mean",
    "fill_median": "Fill median",
    "fill_mode": "Fill mode",
    "duplicate_keep_first": "Keep first",
    "duplicate_keep_last": "Keep last",
    "duplicate_remove_all": "Delete group",
    "key_keep_first": "Keep first",
    "key_keep_last": "Keep last",
    "key_remove_all": "Delete group",
    "drop_blank_rows": "Remove rows",
    "drop_empty_columns": "Delete",
    "invalid_to_null": "Set null",
    "invalid_zero": "Set zero",
    "invalid_mean": "Set mean",
    "invalid_median": "Set median",
    "invalid_mode": "Set mode",
    "drop_invalid_rows": "Delete rows",
    "keep_text": "Keep as text",
}

METHOD_TOOLTIPS = {
    "drop_rows": "Delete rows containing missing values",
    "fill_zero": "Replace missing values with 0",
    "fill_mean": "Replace with column mean (numeric only)",
    "fill_median": "Replace with column median (suitable for skewed data)",
    "fill_mode": "Replace with most frequent value",
    "duplicate_keep_first": "Keep the first row in each fully duplicated group",
    "duplicate_keep_last": "Keep the last row in each fully duplicated group",
    "duplicate_remove_all": "Remove every row belonging to a fully duplicated group",
    "key_keep_first": "Keep the first row for each selected key",
    "key_keep_last": "Keep the last row for each selected key",
    "key_remove_all": "Remove every row whose selected key is duplicated",
    "drop_blank_rows": "Remove rows where every value is blank",
    "drop_empty_columns": "Remove columns that are completely empty",
    "invalid_to_null": "Convert invalid entries to null/NaN",
    "invalid_zero": "Replace invalid entries with 0",
    "invalid_mean": "Replace invalid with column mean",
    "invalid_median": "Replace invalid with column median",
    "invalid_mode": "Replace invalid with most frequent value",
    "drop_invalid_rows": "Delete rows with invalid numeric values",
    "keep_text": "Keep the text as-is (convert column to text type)",
}


RULE_DEFINITIONS = {
    "missing_values": {"title": "Missing values", "detail": "Empty cells", "methods": ["drop_rows", "fill_zero", "fill_mean", "fill_median", "fill_mode"]},
    "blank_rows": {"title": "Completely blank rows", "detail": "Rows without any usable value", "methods": ["drop_blank_rows"]},
    "empty_columns": {"title": "Empty columns", "detail": "Columns without usable values", "methods": ["drop_empty_columns"]},
    "duplicate_rows": {"title": "Duplicate rows", "detail": "Rows repeated across every column", "methods": ["duplicate_keep_first", "duplicate_keep_last", "duplicate_remove_all"]},
    "key_duplicates": {"title": "Duplicate key values", "detail": "Repeated values in user-selected key columns", "methods": ["key_keep_first", "key_keep_last", "key_remove_all"], "requires_columns": True},
    "mixed_numeric_values": {"title": "Invalid numeric values", "detail": "Text or symbols in numeric columns", "methods": ["invalid_to_null", "invalid_zero", "invalid_mean", "invalid_median", "invalid_mode", "drop_invalid_rows", "keep_text"]},
}


class FlatMethodOptions(QWidget):
    changed = Signal()

    def __init__(self, methods: list[str], parent=None) -> None:
        super().__init__(parent)
        self._buttons: dict[str, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._current_selection: str | None = None

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(5)
        layout.setVerticalSpacing(5)
        layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        for method in methods:
            btn = QPushButton(METHOD_LABELS[method])
            btn.setObjectName("cleaningMethodButton")
            btn.setCheckable(True)
            btn.setFixedHeight(25)
            btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            btn.setEnabled(False)
            btn.setToolTip(METHOD_TOOLTIPS.get(method, ""))
            btn.toggled.connect(lambda checked, m=method: self._on_toggled(checked, m))
            self._group.addButton(btn)
            self._buttons[method] = btn
            index = len(self._buttons) - 1
            layout.addWidget(btn, index // 4, index % 4)

    def _on_toggled(self, checked: bool, method: str):
        if checked:
            self._current_selection = method
        self.changed.emit()

    def currentData(self) -> str | None:
        return self._current_selection

    def reset(self) -> None:
        self._current_selection = None
        self._group.setExclusive(False)
        for btn in self._buttons.values():
            btn.setChecked(False)
            btn.setEnabled(False)
        self._group.setExclusive(True)

    def configure(self, allowed_methods: list[str], enabled: bool) -> None:
        allowed = set(allowed_methods)
        self._current_selection = None
        self._group.setExclusive(False)
        for method, btn in self._buttons.items():
            btn.setChecked(False)
            btn.setEnabled(enabled and method in allowed)
        self._group.setExclusive(True)

    def select_first_available(self) -> None:
        for btn in self._buttons.values():
            if btn.isEnabled():
                btn.setChecked(True)
                break


class KeyColumnDialog(QDialog):
    def __init__(
        self,
        sheet_columns: dict[str, list[str]],
        selected: dict[str, list[str]],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select key columns")
        self.resize(430, 420)
        root = QVBoxLayout(self)
        explanation = QLabel(
            "Choose the column or column combination that uniquely identifies "
            "a record in each sheet."
        )
        explanation.setWordWrap(True)
        root.addWidget(explanation)
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.NoSelection)
        for sheet_name, columns in sheet_columns.items():
            header = QListWidgetItem(sheet_name)
            header.setFlags(Qt.NoItemFlags)
            header.setData(Qt.UserRole, None)
            self.list_widget.addItem(header)
            selected_columns = set(selected.get(sheet_name, []))
            for column in columns:
                item = QListWidgetItem(f"    {column}")
                item.setFlags(
                    Qt.ItemIsEnabled
                    | Qt.ItemIsUserCheckable
                )
                item.setCheckState(
                    Qt.Checked if column in selected_columns else Qt.Unchecked
                )
                item.setData(Qt.UserRole, (sheet_name, column))
                self.list_widget.addItem(item)
        root.addWidget(self.list_widget, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def selected_columns(self) -> dict[str, list[str]]:
        selected: dict[str, list[str]] = {}
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            payload = item.data(Qt.UserRole)
            if payload and item.checkState() == Qt.Checked:
                sheet_name, column = payload
                selected.setdefault(sheet_name, []).append(column)
        return selected


class ColumnTreatmentDialog(QDialog):
    def __init__(
        self,
        issue,
        selected: dict[str, dict[str, str]],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Configure {issue.title.lower()}")
        self.resize(560, 440)
        self._selectors: dict[tuple[str, str], QComboBox] = {}
        root = QVBoxLayout(self)
        explanation = QLabel(
            "Choose a treatment for each affected column. Columns set to "
            "'Do not clean' remain unchanged."
        )
        explanation.setWordWrap(True)
        root.addWidget(explanation)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        grid = QGridLayout(content)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 0)
        row = 0
        for sheet_name, counts in issue.column_counts.items():
            sheet_label = QLabel(sheet_name)
            sheet_label.setObjectName("cleaningConfigSheet")
            grid.addWidget(sheet_label, row, 0, 1, 2)
            row += 1
            for column, count in counts.items():
                label = QLabel(f"{column}  ·  {count:,} affected")
                selector = QComboBox()
                selector.setObjectName("cleaningColumnMethod")
                selector.addItem("Do not clean", "")
                for method in issue.column_methods.get(sheet_name, {}).get(
                    column,
                    [],
                ):
                    selector.addItem(METHOD_LABELS[method], method)
                current = selected.get(sheet_name, {}).get(column, "")
                current_index = selector.findData(current)
                selector.setCurrentIndex(max(0, current_index))
                self._selectors[(sheet_name, column)] = selector
                grid.addWidget(label, row, 0)
                grid.addWidget(selector, row, 1)
                row += 1
        grid.setRowStretch(row, 1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def selected_methods(self) -> dict[str, dict[str, str]]:
        selected: dict[str, dict[str, str]] = {}
        for (sheet_name, column), selector in self._selectors.items():
            method = str(selector.currentData() or "")
            if method:
                selected.setdefault(sheet_name, {})[column] = method
        return selected


class CleaningIssueCard(QWidget):
    changed = Signal()

    def __init__(self, issue_id: str, definition: dict, parent=None) -> None:
        super().__init__(parent)
        self.issue_id = issue_id
        self.definition = definition
        self._allowed_methods: list[str] = []
        self._sheet_columns: dict[str, list[str]] = {}
        self._selected_columns: dict[str, list[str]] = {}
        self._issue = None
        self._selected_column_methods: dict[str, dict[str, str]] = {}
        self.setObjectName("cleaningIssueCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setProperty("available", False)
        self.setProperty("ruleState", "pending")
        self.setProperty("selected", False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(7)

        header = QHBoxLayout()
        self.checkbox = QCheckBox()
        self.checkbox.setObjectName("cleaningRuleCheck")
        self.checkbox.setEnabled(False)
        self.checkbox.toggled.connect(self._on_checked)

        info = QVBoxLayout()
        info.setSpacing(3)
        self.title_label = QLabel(definition["title"])
        self.title_label.setObjectName("cleaningMatrixTitle")
        self.detail_label = QLabel(definition["detail"])
        self.detail_label.setObjectName("cleaningMatrixDetail")
        info.addWidget(self.title_label)
        info.addWidget(self.detail_label)
        self.affected_label = QLabel("Scan required")
        self.affected_label.setObjectName("cleaningAffectedSummary")
        info.addWidget(self.affected_label)

        self.status_label = QLabel("Scan required")
        self.status_label.setObjectName("cleaningMatrixStatus")
        self.status_label.setProperty("statusKind", "pending")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        header.addWidget(self.checkbox)
        header.addLayout(info, 1)
        header.addWidget(self.status_label)
        layout.addLayout(header)

        self.treatment_widget = QWidget()
        treatment_layout = QVBoxLayout(self.treatment_widget)
        treatment_layout.setContentsMargins(0, 0, 0, 0)
        treatment_layout.setSpacing(4)

        treatment_label = QLabel("Available treatment")
        treatment_label.setObjectName("treatmentLabel")
        treatment_layout.addWidget(treatment_label)

        self.options = FlatMethodOptions(definition["methods"])
        self.options.changed.connect(self.changed)
        treatment_layout.addWidget(self.options)

        self.column_config = QWidget()
        column_layout = QHBoxLayout(self.column_config)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(6)
        self.configure_columns_button = QPushButton("Configure columns")
        self.configure_columns_button.setObjectName("cleaningConfigButton")
        self.configure_columns_button.setFixedHeight(25)
        self.configure_columns_button.setSizePolicy(
            QSizePolicy.Maximum,
            QSizePolicy.Fixed,
        )
        self.configure_columns_button.clicked.connect(self._configure_columns)
        self.selected_columns_label = QLabel("No key columns selected")
        self.selected_columns_label.setObjectName("cleaningConfigSummary")
        self.selected_columns_label.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Preferred,
        )
        column_layout.addWidget(self.configure_columns_button)
        column_layout.addWidget(self.selected_columns_label, 1)
        treatment_layout.addWidget(self.column_config)
        self.column_config.setVisible(bool(definition.get("requires_columns")))

        layout.addWidget(self.treatment_widget)
        self.configure_columns_button.setEnabled(False)

    def reset(self) -> None:
        self.setProperty("available", False)
        self.setProperty("ruleState", "pending")
        self.setProperty("selected", False)
        self._refresh_style()
        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(False)
        self.checkbox.setEnabled(False)
        self.checkbox.blockSignals(False)
        self.status_label.setText("Scan required")
        self.status_label.setProperty("statusKind", "pending")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self._allowed_methods = []
        self._sheet_columns = {}
        self._selected_columns = {}
        self._selected_column_methods = {}
        self._issue = None
        self.selected_columns_label.setText("No key columns selected")
        self.affected_label.setText("Scan required")
        self.configure_columns_button.setEnabled(False)
        self.options.reset()

    def set_issue(self, issue=None) -> None:
        available = issue is not None
        self._issue = issue
        self.setProperty("available", str(available).lower())
        self.setProperty("ruleState", "available" if available else "unavailable")
        self.setProperty("selected", False)
        self._refresh_style()

        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(False)
        self.checkbox.setEnabled(available)
        self.checkbox.blockSignals(False)

        if available:
            if self.issue_id == "key_duplicates":
                self.status_label.setText("Configure keys")
                self.status_label.setProperty("statusKind", "config")
            else:
                self.status_label.setText(f"{issue.count:,} found")
                self.status_label.setProperty("statusKind", "issue")
            affected_columns = sum(
                len(columns)
                for columns in issue.column_counts.values()
            )
            if affected_columns:
                names = [
                    f"{sheet}.{column}"
                    for sheet, columns in issue.column_counts.items()
                    for column in columns
                ]
                preview = ", ".join(names[:3])
                if len(names) > 3:
                    preview += f" +{len(names) - 3}"
                self.affected_label.setText(
                    f"{preview} · "
                    f"{issue.estimated_changes:,} affected value(s)"
                )
            elif issue.columns:
                preview = ", ".join(issue.columns[:3])
                if len(issue.columns) > 3:
                    preview += f" +{len(issue.columns) - 3}"
                self.affected_label.setText(
                    f"{preview} · "
                    f"{issue.estimated_changes:,} affected item(s)"
                )
            elif self.issue_id == "key_duplicates":
                self.affected_label.setText(
                    "Select key columns; affected rows are evaluated at execution."
                )
            else:
                self.affected_label.setText(
                    f"{issue.estimated_changes:,} affected record(s)"
                )
        else:
            self.status_label.setText("Not applicable")
            self.status_label.setProperty("statusKind", "muted")
            self.affected_label.setText("No matching issue detected")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

        self._allowed_methods = list(issue.methods if issue else [])
        self._sheet_columns = dict(issue.sheet_columns if issue else {})
        self.column_config.setVisible(
            bool(
                self.definition.get("requires_columns")
                or (issue is not None and issue.column_methods)
            )
        )
        self._selected_columns = {}
        self._selected_column_methods = {}
        self.selected_columns_label.setText("No columns configured")
        self.configure_columns_button.setEnabled(False)
        self.options.configure(self._allowed_methods, enabled=False)

    def _on_checked(self, checked: bool) -> None:
        self.setProperty("selected", checked)
        self._refresh_style()
        column_configured = bool(
            self._issue is not None and self._issue.column_methods
        )
        self.options.configure(
            self._allowed_methods,
            enabled=checked and not column_configured,
        )
        self.configure_columns_button.setEnabled(
            checked
            and (
                bool(self._sheet_columns)
                or column_configured
            )
        )
        if checked and not column_configured and not self.options.currentData():
            self.options.select_first_available()
        self.changed.emit()

    def _refresh_style(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _configure_columns(self) -> None:
        if self._issue is not None and self._issue.column_methods:
            dialog = ColumnTreatmentDialog(
                self._issue,
                self._selected_column_methods,
                self,
            )
            if dialog.exec() != QDialog.Accepted:
                return
            self._selected_column_methods = dialog.selected_methods()
            count = sum(
                len(columns)
                for columns in self._selected_column_methods.values()
            )
            estimated = sum(
                self._issue.column_counts.get(sheet, {}).get(column, 0)
                for sheet, columns in self._selected_column_methods.items()
                for column in columns
            )
            self.selected_columns_label.setText(
                f"{count} column(s) configured · "
                f"up to {estimated:,} change(s)"
                if count
                else "No columns configured"
            )
            self.changed.emit()
            return
        dialog = KeyColumnDialog(
            self._sheet_columns,
            self._selected_columns,
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        self._selected_columns = dialog.selected_columns()
        count = sum(len(columns) for columns in self._selected_columns.values())
        self.selected_columns_label.setText(
            f"{count} key column{'s' if count != 1 else ''} selected"
            if count
            else "No key columns selected"
        )
        self.changed.emit()

    def selection_payload(self):
        if not self.checkbox.isChecked():
            return None
        if self._issue is not None and self._issue.column_methods:
            if not any(self._selected_column_methods.values()):
                return None
            return {
                "columns": {
                    sheet: dict(columns)
                    for sheet, columns in self._selected_column_methods.items()
                    if columns
                }
            }
        method = self.options.currentData()
        if not method:
            return None
        if self.issue_id == "key_duplicates":
            if not any(self._selected_columns.values()):
                return None
            return {
                "method": method,
                "columns": {
                    sheet: list(columns)
                    for sheet, columns in self._selected_columns.items()
                    if columns
                },
            }
        return method


class CleaningPage(QWidget):
    profile_requested = Signal(str)
    execute_requested = Signal(str, dict, str)
    cancel_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("cleaningPage")
        self._target_dataset: str | None = None
        self._rule_cards: dict[str, CleaningIssueCard] = {}
        self._issue_rows: dict[str, tuple[QCheckBox, FlatMethodOptions]] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 16)
        root.setSpacing(9)

        # ==================== COMPACT HEADER ====================
        header = QHBoxLayout()
        header.setSpacing(12)

        title_group = QVBoxLayout()
        title_group.setSpacing(2)
        title = QLabel("Data Cleaning")
        title.setObjectName("cleaningTitle")
        subtitle = QLabel("Scan • Review • Clean")
        subtitle.setObjectName("cleaningSubtitle")
        title_group.addWidget(title)
        title_group.addWidget(subtitle)

        # Dataset (更紧凑)
        dataset_group = QHBoxLayout()
        dataset_group.setSpacing(6)
        dataset_caption = QLabel("Dataset:")
        dataset_caption.setObjectName("cleaningDatasetCaption")
        self.target_label = QLabel("None selected")
        self.target_label.setObjectName("cleaningDatasetValue")
        dataset_group.addWidget(dataset_caption)
        dataset_group.addWidget(self.target_label)

        header.addLayout(title_group)
        header.addStretch()
        header.addLayout(dataset_group)
        root.addLayout(header)

        # ==================== COMPACT ACTION BAR ====================
        action_bar = QHBoxLayout()
        action_bar.setSpacing(7)

        self.summary_label = QLabel("Select dataset and scan to start")
        self.summary_label.setObjectName("cleaningSummary")
        self.summary_label.setWordWrap(False)

        self.status_label = QLabel("Not scanned")
        self.status_label.setObjectName("cleaningStatus")

        self.scan_button = QPushButton("Scan")
        self.scan_button.setObjectName("cleaningScanButton")
        self.scan_button.setFixedHeight(28)
        self.scan_button.clicked.connect(self._request_profile)

        self.execute_button = QPushButton("Execute Cleaning")
        self.execute_button.setObjectName("cleaningExecuteButton")
        self.execute_button.setFixedHeight(28)
        self.execute_button.clicked.connect(self._request_execute)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("cleaningCancelButton")
        self.cancel_button.setFixedHeight(28)
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)

        action_bar.addWidget(self.summary_label, 1)
        action_bar.addWidget(self.status_label)
        action_bar.addWidget(self.scan_button)
        action_bar.addWidget(self.execute_button)   # 提前放到 action bar 更紧凑
        action_bar.addWidget(self.cancel_button)
        root.addLayout(action_bar)

        # Progress
        self.progress = QProgressBar()
        self.progress.setObjectName("cleaningProgress")
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        self.progress.setFixedHeight(4)
        root.addWidget(self.progress)

        # ==================== ISSUE CARDS (最大空间) ====================
        scroll = QScrollArea()
        scroll.setObjectName("cleaningScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        self.cards_container = QWidget()
        self.cards_container.setObjectName("cleaningIssueList")
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(3)

        for index, (issue_id, definition) in enumerate(RULE_DEFINITIONS.items()):
            card = CleaningIssueCard(issue_id, definition)
            card.changed.connect(self._refresh_execute_state)
            self.cards_layout.addWidget(card)
            self._rule_cards[issue_id] = card
            self._issue_rows[issue_id] = (card.checkbox, card.options)
            if index < len(RULE_DEFINITIONS) - 1:
                separator = QFrame()
                separator.setObjectName("cleaningIssueSeparator")
                separator.setFrameShape(QFrame.HLine)
                self.cards_layout.addWidget(separator)

        self.cards_layout.addStretch()
        scroll.setWidget(self.cards_container)
        root.addWidget(scroll, stretch=1)

        # Footer（仅保留选中计数）
        footer = QHBoxLayout()
        self.selected_count_label = QLabel("0 rules selected")
        self.selected_count_label.setObjectName("cleaningSelectedCount")
        footer.addWidget(self.selected_count_label)
        footer.addStretch()
        root.addLayout(footer)

    # ==================== 原有接口完全保留 ====================
    def set_target_dataset(self, name: str | None) -> None:
        changed = name != self._target_dataset
        self._target_dataset = name
        self.target_label.setText(name or "None selected")
        self.scan_button.setEnabled(bool(name))
        if changed:
            self._reset_profile()

    @property
    def target_dataset(self) -> str | None:
        return self._target_dataset

    def show_busy(self, message: str, determinate: bool = False) -> None:
        self.scan_button.setEnabled(False)
        self.execute_button.setEnabled(False)
        self.status_label.setText("Processing...")
        self.summary_label.setText(message)
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.cancel_button.setVisible(True)

    def set_progress(self, percent: int, sheet_name: str) -> None:
        self.progress.setValue(percent)
        self.summary_label.setText(f"{sheet_name} · {percent}%")

    def show_profile(self, profile) -> None:
        self.scan_button.setEnabled(True)
        self.progress.setVisible(False)
        self.cancel_button.setVisible(False)
        issues = {issue.issue_id: issue for issue in profile.issues}
        for issue_id, card in self._rule_cards.items():
            card.set_issue(issues.get(issue_id))
        self.summary_label.setText(f"{profile.rows:,} rows · {profile.columns:,} columns · {profile.sheets} sheet(s)")
        detected = sum(
            1
            for issue in profile.issues
            if issue.issue_id != "key_duplicates" and issue.count > 0
        )
        self.status_label.setText(f"{detected} issues")
        self._refresh_execute_state()

    def show_error(self, message: str) -> None:
        self.scan_button.setEnabled(bool(self._target_dataset))
        self.execute_button.setEnabled(False)
        self.progress.setVisible(False)
        self.cancel_button.setVisible(False)
        self.status_label.setText("Failed")
        self.summary_label.setText(message)

    def show_cancelled(self) -> None:
        self.scan_button.setEnabled(bool(self._target_dataset))
        self.execute_button.setEnabled(False)
        self.progress.setVisible(False)
        self.cancel_button.setVisible(False)
        self.status_label.setText("Cancelled")
        self.summary_label.setText("Cleaning operation cancelled.")

    def show_result(self, result) -> None:
        self.scan_button.setEnabled(True)
        self.progress.setVisible(False)
        self.cancel_button.setVisible(False)
        self.execute_button.setEnabled(False)
        self.status_label.setText("Complete")
        self.summary_label.setText(f"{result.rows_before:,} → {result.rows_after:,} rows · Saved")

    def _request_profile(self) -> None:
        if self._target_dataset:
            self.profile_requested.emit(self._target_dataset)

    def _request_execute(self) -> None:
        selections = {
            issue_id: card.selection_payload()
            for issue_id, card in self._rule_cards.items()
            if card.selection_payload() is not None
        }
        if not self._target_dataset or not selections:
            return
        default_name = self._target_dataset.rsplit(".", 1)[0] + "_cleaned.xlsx"
        output_path, _ = QFileDialog.getSaveFileName(self, "Save cleaned workbook", default_name, "Excel Workbook (*.xlsx)")
        if output_path:
            if not output_path.lower().endswith(".xlsx"):
                output_path += ".xlsx"
            self.execute_requested.emit(self._target_dataset, selections, output_path)

    def _reset_profile(self) -> None:
        for card in self._rule_cards.values():
            card.reset()
        self.execute_button.setEnabled(False)
        self.status_label.setText("Not scanned")
        self.selected_count_label.setText("0 rules selected")
        if self._target_dataset:
            self.summary_label.setText("Scan dataset to detect issues.")

    def _refresh_execute_state(self) -> None:
        selected = sum(
            1
            for card in self._rule_cards.values()
            if card.selection_payload() is not None
        )
        self.selected_count_label.setText(f"{selected} rule{'s' if selected != 1 else ''} selected")
        self.execute_button.setEnabled(selected > 0)


# ==================== 紧凑优化样式 ====================
CLEANING_PAGE_STYLE = """
QWidget#cleaningPage { background: #ffffff; }

QLabel#cleaningTitle { color: #202124; font-size: 20px; font-weight: 700; }
QLabel#cleaningSubtitle { color: #5f6368; font-size: 12px; }

QLabel#cleaningDatasetCaption { color: #5f6368; font-size: 9px; font-weight: 600; }
QLabel#cleaningDatasetValue {
    color: #202124; background: transparent; border: none;
    padding: 0; font-size: 11px; font-weight: 600;
}

QLabel#cleaningSummary { color: #5f6368; font-size: 12px; }
QLabel#cleaningStatus {
    color: #5f6368; background: #f1f3f4; border-radius: 5px;
    padding: 3px 8px; font-size: 9px; font-weight: 600;
}

QPushButton#cleaningScanButton,
QPushButton#cleaningExecuteButton {
    color: #ffffff; background: #1a73e8; border: none;
    border-radius: 5px; padding: 4px 11px; font-weight: 600; font-size: 11px;
}

QPushButton#cleaningScanButton:hover,
QPushButton#cleaningExecuteButton:hover { background: #1765cc; }
QPushButton#cleaningCancelButton {
    color: #3c4043; background: #ffffff; border: 1px solid #dadce0;
    border-radius: 5px; padding: 4px 10px; font-weight: 600; font-size: 11px;
}
QPushButton#cleaningCancelButton:hover { background: #f1f3f4; }
QPushButton#cleaningScanButton:disabled,
QPushButton#cleaningExecuteButton:disabled {
    color: #ffffff; background: #bdc1c6;
}

QWidget#cleaningIssueCard {
    background: #ffffff;
    border: 1px solid #e8eaed;
    border-left: 3px solid #dadce0;
    border-radius: 6px;
}
QWidget#cleaningIssueCard[ruleState="pending"] {
    background: #ffffff;
    border-color: #e8eaed;
    border-left-color: #dadce0;
}
QWidget#cleaningIssueCard[ruleState="available"] {
    background: #f8fbff;
    border-color: #d8e6f7;
    border-left-color: #1a73e8;
}
QWidget#cleaningIssueCard[ruleState="unavailable"] {
    background: #f8f9fa;
    border-color: #eef0f2;
    border-left-color: #dadce0;
}
QWidget#cleaningIssueCard[selected="true"] {
    background: #e8f0fe;
    border-color: #8ab4f8;
    border-left-color: #174ea6;
}
QWidget#cleaningIssueCard[ruleState="unavailable"] QLabel#cleaningMatrixTitle,
QWidget#cleaningIssueCard[ruleState="unavailable"] QLabel#cleaningMatrixDetail,
QWidget#cleaningIssueCard[ruleState="unavailable"] QLabel#cleaningAffectedSummary {
    color: #9aa0a6;
}

QFrame#cleaningIssueSeparator {
    color: transparent; background: transparent;
    min-height: 1px; max-height: 1px; border: none;
}

QLabel#cleaningMatrixTitle { color: #202124; font-size: 12px; font-weight: 650; }
QLabel#cleaningMatrixDetail { color: #5f6368; font-size: 10px; }
QLabel#cleaningAffectedSummary {
    color: #6b7280; font-size: 9px; font-weight: 500;
}
QLabel#cleaningMatrixStatus {
    color: #5f6368;
    background: #f1f3f4;
    border-radius: 5px;
    padding: 3px 7px;
    font-size: 9px;
    font-weight: 650;
}
QLabel#cleaningMatrixStatus[statusKind="issue"] {
    color: #b3261e; background: #fce8e6;
}
QLabel#cleaningMatrixStatus[statusKind="config"] {
    color: #174ea6; background: #e8f0fe;
}
QLabel#cleaningMatrixStatus[statusKind="muted"],
QLabel#cleaningMatrixStatus[statusKind="pending"] {
    color: #80868b; background: #f1f3f4;
}

QPushButton#cleaningMethodButton {
    color: #3c4043; background: #ffffff; border: 1px solid #dadce0;
    border-radius: 4px; padding: 3px 8px; font-size: 10px; font-weight: 500;
}
QPushButton#cleaningMethodButton:hover {
    background: #f1f3f4; border-color: #bdc1c6;
}
QPushButton#cleaningMethodButton:checked {
    color: #174ea6; background: #dbe8fd; border-color: #669df6;
    font-weight: 650;
}
QPushButton#cleaningMethodButton:disabled {
    color: #9aa0a6; background: #f8f9fa; border-color: #e8eaed;
}

QPushButton#cleaningConfigButton {
    color: #3c4043; background: #ffffff; border: 1px solid #dadce0;
    border-radius: 4px; padding: 3px 8px; font-size: 10px; font-weight: 600;
}
QPushButton#cleaningConfigButton:hover { background: #f1f3f4; }
QPushButton#cleaningConfigButton:disabled {
    color: #9aa0a6; background: #f8f9fa; border-color: #e8eaed;
}
QLabel#cleaningConfigSummary { color: #5f6368; font-size: 10px; }
QLabel#cleaningConfigSheet {
    color: #202124; font-size: 12px; font-weight: 700;
    padding-top: 8px;
}
QComboBox#cleaningColumnMethod {
    min-width: 180px; padding: 5px 8px;
    border: 1px solid #dadce0; border-radius: 5px;
    background: #ffffff; color: #202124;
}

QLabel#treatmentLabel { color: #5f6368; font-size: 9px; font-weight: 650; }
QLabel#cleaningSelectedCount { color: #5f6368; font-size: 11px; font-weight: 500; }

QProgressBar#cleaningProgress {
    min-height: 4px; max-height: 4px; border: none;
    background: #e5e7eb; border-radius: 2px;
}
QProgressBar#cleaningProgress::chunk { background: #1a73e8; border-radius: 2px; }

QScrollArea#cleaningScroll { background: transparent; border: none; }
QScrollArea#cleaningScroll QWidget#qt_scrollarea_viewport { background: #ffffff; }
QWidget#cleaningIssueList { background: #ffffff; }
"""
