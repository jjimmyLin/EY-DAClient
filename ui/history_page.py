from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QPushButton,
)


class HistoryPage(QWidget):
    task_open_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("historyPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        
        # Header & Back Button
        header_layout = QHBoxLayout()
        self.title = QLabel("Task History")
        self.title.setStyleSheet("font-size: 20px; font-weight: bold; color: #111827;")
        self.btn_back = QPushButton("Back")
        self.btn_back.setFixedSize(80, 32)
        
        header_layout.addWidget(self.title)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_back)
        layout.addLayout(header_layout)

        # Lists Container
        lists_layout = QHBoxLayout()
        
        # Unfinished Tasks Column
        unfin_col = QVBoxLayout()
        unfin_col.addWidget(QLabel("UNFINISHED TASKS"))
        self.unfinished_list = QListWidget()
        unfin_col.addWidget(self.unfinished_list)
        
        # Finished Tasks Column
        fin_col = QVBoxLayout()
        fin_col.addWidget(QLabel("FINISHED TASKS"))
        self.finished_list = QListWidget()
        fin_col.addWidget(self.finished_list)
        
        lists_layout.addLayout(unfin_col)
        lists_layout.addLayout(fin_col)
        layout.addLayout(lists_layout)

        self.unfinished_list.itemDoubleClicked.connect(self._emit_task_open)
        self.finished_list.itemDoubleClicked.connect(self._emit_task_open)

        self.set_tasks([], [])

    def set_tasks(self, unfinished_tasks: list[dict], finished_tasks: list[dict]) -> None:
        """Refresh both history columns."""
        self._populate_list(
            self.unfinished_list,
            unfinished_tasks,
            empty_text="No unfinished tasks",
        )
        self._populate_list(
            self.finished_list,
            finished_tasks,
            empty_text="No finished tasks",
        )

    def _populate_list(
        self,
        list_widget: QListWidget,
        tasks: list[dict],
        empty_text: str,
    ) -> None:
        list_widget.clear()

        if not tasks:
            item = QListWidgetItem(empty_text)
            item.setForeground(QColor("#9CA3AF"))
            list_widget.addItem(item)
            return

        for task in tasks:
            item = QListWidgetItem(self._format_task(task))
            item.setToolTip(str(task.get("query", "")))
            item.setData(Qt.UserRole, task.get("id"))
            list_widget.addItem(item)

    def _emit_task_open(self, item: QListWidgetItem) -> None:
        task_id = item.data(Qt.UserRole)
        if task_id is not None:
            self.task_open_requested.emit(int(task_id))

    def _format_task(self, task: dict) -> str:
        dataset = task.get("dataset") or "Unknown dataset"
        query = task.get("query") or "Untitled task"
        status = task.get("status") or "Unknown"
        timestamp = task.get("updated_at") or task.get("created_at") or ""

        if len(query) > 72:
            query = query[:69] + "..."

        lines = [
            query,
            f"{dataset} · {status}",
        ]
        if timestamp:
            lines.append(timestamp)
        return "\n".join(lines)
