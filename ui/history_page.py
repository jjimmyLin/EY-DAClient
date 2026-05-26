# ui/history_page.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QLabel, QPushButton

class HistoryPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        
        # Header & Back Button
        header_layout = QHBoxLayout()
        self.title = QLabel("Task History")
        self.title.setStyleSheet("font-size: 20px; font-weight: bold; color: #111827;")
        self.btn_back = QPushButton("← Back to Workspace")
        self.btn_back.setFixedSize(150, 32)
        
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