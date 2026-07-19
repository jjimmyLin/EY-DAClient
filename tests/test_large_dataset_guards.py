from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from config.settings import settings
from core.data_access import LocalDataCatalog
from core.preprocessor import Preprocessor, ProcessingCancelled


def test_streaming_import_uses_parquet_cache_and_writes_manifest(tmp_path, monkeypatch):
    workbook = tmp_path / "large.xlsx"
    pd.DataFrame(
        {
            "id": list(range(250)),
            "amount": [value * 1.5 for value in range(250)],
            "region": ["APAC"] * 250,
        }
    ).to_excel(workbook, index=False)

    cache_dir = tmp_path / "cache"
    duckdb_temp = tmp_path / "duckdb-temp"
    monkeypatch.setattr(settings, "DATASET_CACHE_DIR", cache_dir)
    monkeypatch.setattr(settings, "DUCKDB_TEMP_DIR", duckdb_temp)
    monkeypatch.setattr(settings, "LARGE_EXCEL_MB", 0)

    file_meta = Preprocessor().process(str(workbook))

    dataset_dir = cache_dir / file_meta.dataset_id
    assert file_meta.profile_mode == "sampled"
    assert (dataset_dir / "manifest.json").exists()
    assert not any(dataset_dir.glob("*.stream.csv"))
    assert all(Path(sheet.cache_path).exists() for sheet in file_meta.sheets)
    assert all(Path(sheet.sample_cache_path).exists() for sheet in file_meta.sheets)


def test_streaming_import_honors_cancellation(tmp_path, monkeypatch):
    workbook = tmp_path / "cancel.xlsx"
    pd.DataFrame({"id": list(range(120)), "value": list(range(120))}).to_excel(
        workbook,
        index=False,
    )

    cache_dir = tmp_path / "cache"
    duckdb_temp = tmp_path / "duckdb-temp"
    monkeypatch.setattr(settings, "DATASET_CACHE_DIR", cache_dir)
    monkeypatch.setattr(settings, "DUCKDB_TEMP_DIR", duckdb_temp)
    monkeypatch.setattr(settings, "LARGE_EXCEL_MB", 0)
    monkeypatch.setattr(settings, "IMPORT_BATCH_ROWS", 25)

    calls = {"count": 0}

    def cancel_callback() -> bool:
        calls["count"] += 1
        return calls["count"] > 2

    with pytest.raises(ProcessingCancelled):
        Preprocessor().process(str(workbook), cancel_callback=cancel_callback)


def test_streaming_import_restarts_polluted_numeric_column_as_text(
    tmp_path,
    monkeypatch,
):
    workbook = tmp_path / "mixed-large.xlsx"
    pd.DataFrame(
        {
            "price": [10, 20, 30, 40, "价格待定", 60],
            "item": ["A", "B", "C", "D", "E", "F"],
        }
    ).to_excel(workbook, index=False)

    cache_dir = tmp_path / "cache"
    duckdb_temp = tmp_path / "duckdb-temp"
    monkeypatch.setattr(settings, "DATASET_CACHE_DIR", cache_dir)
    monkeypatch.setattr(settings, "DUCKDB_TEMP_DIR", duckdb_temp)
    monkeypatch.setattr(settings, "LARGE_EXCEL_MB", 0)
    monkeypatch.setattr(settings, "IMPORT_SCHEMA_SAMPLE_ROWS", 2)
    monkeypatch.setattr(settings, "IMPORT_BATCH_ROWS", 2)

    file_meta = Preprocessor().process(str(workbook))
    cached = pd.read_parquet(file_meta.sheets[0].cache_path)

    assert cached["price"].tolist() == ["10", "20", "30", "40", "价格待定", "60"]


def test_large_dataset_requires_projected_columns_for_get(tmp_path, monkeypatch):
    parquet_path = tmp_path / "sheet.parquet"
    pd.DataFrame(
        {
            "id": [1, 2, 3],
            "amount": [10, 20, 30],
            "region": ["APAC", "EMEA", "AMER"],
        }
    ).to_parquet(parquet_path, index=False)

    duckdb_temp = tmp_path / "duckdb-temp"
    duckdb_temp.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "DUCKDB_TEMP_DIR", duckdb_temp)
    monkeypatch.setattr(settings, "BACKGROUND_ANALYSIS_ROWS", 2)
    monkeypatch.setattr(settings, "LARGE_DATASET_COLUMN_GUARD", 2)
    monkeypatch.setattr(settings, "MAX_QUERY_RESULT_ROWS", 2)

    catalog = LocalDataCatalog(
        [
            {
                "dataset_id": "ds_large",
                "aliases": [],
                "sheets": [
                    {
                        "sheet_id": "sh_main",
                        "name": "Sheet1",
                        "cache_path": str(parquet_path),
                        "sample_cache_path": str(parquet_path),
                        "rows": 999999,
                        "columns": ["id", "amount", "region"],
                    }
                ],
            }
        ]
    )

    with pytest.raises(ValueError, match="Use data.get"):
        catalog.get("ds_large", "sh_main")

    projected = catalog.get("ds_large", "sh_main", columns=["id", "amount"])
    assert list(projected.columns) == ["id", "amount"]

    result = catalog.sql(
        "SELECT * FROM fact ORDER BY id",
        sources={"fact": ("ds_large", "sh_main")},
    )
    assert len(result) == 2


def test_large_union_sheets_requires_projected_columns(tmp_path, monkeypatch):
    parquet_path = tmp_path / "sheet.parquet"
    pd.DataFrame(
        {
            "id": [1, 2, 3],
            "amount": [10, 20, 30],
            "region": ["APAC", "EMEA", "AMER"],
        }
    ).to_parquet(parquet_path, index=False)

    duckdb_temp = tmp_path / "duckdb-temp"
    duckdb_temp.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "DUCKDB_TEMP_DIR", duckdb_temp)
    monkeypatch.setattr(settings, "BACKGROUND_ANALYSIS_ROWS", 2)
    monkeypatch.setattr(settings, "LARGE_DATASET_COLUMN_GUARD", 2)

    catalog = LocalDataCatalog(
        [
            {
                "dataset_id": "ds_large",
                "aliases": [],
                "sheet_groups": [
                    {
                        "group_id": "sg_je",
                        "type": "same_schema_append",
                        "sheet_ids": ["sh_1", "sh_2"],
                        "sheet_names": ["JE_1", "JE_2"],
                        "columns": ["id", "amount", "region"],
                    }
                ],
                "sheets": [
                    {
                        "sheet_id": "sh_1",
                        "name": "JE_1",
                        "cache_path": str(parquet_path),
                        "sample_cache_path": str(parquet_path),
                        "rows": 999999,
                        "columns": ["id", "amount", "region"],
                    },
                    {
                        "sheet_id": "sh_2",
                        "name": "JE_2",
                        "cache_path": str(parquet_path),
                        "sample_cache_path": str(parquet_path),
                        "rows": 999999,
                        "columns": ["id", "amount", "region"],
                    },
                ],
            }
        ]
    )

    with pytest.raises(ValueError, match="Use data.get"):
        catalog.union_sheets("ds_large", group_id="sg_je")

    projected = catalog.union_sheets(
        "ds_large",
        group_id="sg_je",
        columns=["id", "amount"],
    )
    assert list(projected.columns) == [
        "id",
        "amount",
        "source_sheet",
        "source_sheet_id",
    ]
    assert len(projected) == 6
    assert catalog.audit_records[-1]["kind"] == "union"

    summary = catalog.sql(
        "SELECT COUNT(*) AS rows, SUM(amount) AS total_amount FROM je",
        sheet_groups={"je": ("ds_large", "sg_je")},
    )
    assert summary.loc[0, "rows"] == 6
    assert summary.loc[0, "total_amount"] == 120
    assert catalog.audit_records[-1]["kind"] == "sql"
