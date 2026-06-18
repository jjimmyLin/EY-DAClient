from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def prevent_live_overview_requests(monkeypatch):
    """UI unit tests must not start real provider requests."""
    from ui.main_window import MainWindow

    monkeypatch.setattr(
        MainWindow,
        "_start_overview_worker",
        lambda self, dataset_name, file_meta: None,
    )
