from pathlib import Path

import pandas as pd
import pytest

from config.settings import settings
from core.preprocessor import Preprocessor
from workers.import_worker import ImportWorker


def test_preprocessor_rejects_files_over_configured_limit(
    tmp_path,
    monkeypatch,
):
    workbook = tmp_path / "too-large.xlsx"
    workbook.write_bytes(b"x" * 16)
    monkeypatch.setattr(settings, "MAX_DATASET_BYTES", 8)

    with pytest.raises(ValueError, match="2 GiB"):
        Preprocessor().process(str(workbook))


def test_background_import_emits_progress_and_profile(tmp_path):
    workbook = tmp_path / "demo.xlsx"
    pd.DataFrame({"id": [1, 2], "value": [10, 20]}).to_excel(
        workbook,
        index=False,
    )
    worker = ImportWorker([str(workbook)])
    progress = []
    completed = []
    failures = []
    worker.progress.connect(lambda path, event: progress.append((path, event)))
    worker.file_finished.connect(
        lambda path, meta: completed.append((Path(path).name, meta))
    )
    worker.file_failed.connect(lambda path, error: failures.append((path, error)))

    worker.run()

    assert not failures
    assert completed[0][0] == "demo.xlsx"
    assert completed[0][1].profile_mode == "full"
    assert progress
    assert progress[-1][1]["stage"] == "ready"
