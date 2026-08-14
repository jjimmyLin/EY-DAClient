from __future__ import annotations

from pathlib import Path
import re
import zipfile

import pandas as pd
import pytest

from config.settings import settings
from core.data_access import LocalDataCatalog
from core.preprocessor import Preprocessor, ProcessingCancelled


def _replace_sheet_dimension(path: Path, dimension: str) -> None:
    rewritten = path.with_suffix(".rewritten.xlsx")
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(rewritten, "w") as target:
        for info in source.infolist():
            payload = source.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                payload, replacements = re.subn(
                    rb"<dimension\b[^>]*/>",
                    f'<dimension ref="{dimension}"/>'.encode("ascii"),
                    payload,
                    count=1,
                )
                assert replacements == 1
            target.writestr(info, payload)
    rewritten.replace(path)


@pytest.mark.parametrize("streaming", [False, True])
def test_headerless_continuation_inherits_schema_without_losing_first_row(
    tmp_path,
    monkeypatch,
    streaming,
):
    workbook = tmp_path / "continued.xlsx"
    first = pd.DataFrame(
        {
            "entry_id": [1, 2, 3],
            "amount": [10.0, 20.0, 30.0],
            "account": ["1001", "1002", "1003"],
        }
    )
    second = pd.DataFrame(
        {
            "entry_id": [4, 5, 6],
            "amount": [40.0, 50.0, 60.0],
            "account": ["1004", "1005", "1006"],
        }
    )
    with pd.ExcelWriter(workbook) as writer:
        first.to_excel(writer, sheet_name="Part1", index=False)
        second.to_excel(
            writer,
            sheet_name="Part2",
            index=False,
            header=False,
        )

    cache_dir = tmp_path / "cache"
    duckdb_temp = tmp_path / "duckdb-temp"
    monkeypatch.setattr(settings, "DATASET_CACHE_DIR", cache_dir)
    monkeypatch.setattr(settings, "DUCKDB_TEMP_DIR", duckdb_temp)
    monkeypatch.setattr(settings, "LARGE_EXCEL_MB", 0 if streaming else 1024)

    file_meta = Preprocessor().process(str(workbook))

    inherited = file_meta.sheets[1]
    assert inherited.columns == list(first.columns)
    assert inherited.rows == len(second)
    assert inherited.header_mode == "inherited"
    assert inherited.header_source_sheet_id == file_meta.sheets[0].sheet_id
    assert inherited.first_row_is_data is True
    assert inherited.continuation_detected is True
    assert pd.read_parquet(inherited.cache_path)["entry_id"].tolist() == [4, 5, 6]
    assert len(file_meta.sheet_groups) == 1
    assert file_meta.sheet_groups[0].group_type == "same_schema_append"
    assert file_meta.sheet_groups[0].total_rows == 6


def test_ambiguous_all_text_sheet_is_not_silently_inherited(
    tmp_path,
    monkeypatch,
):
    workbook = tmp_path / "ambiguous.xlsx"
    first = pd.DataFrame(
        {
            "customer": ["A", "B", "C"],
            "region": ["North", "South", "East"],
        }
    )
    second = pd.DataFrame(
        {
            "customer": ["D", "E", "F"],
            "region": ["West", "North", "South"],
        }
    )
    with pd.ExcelWriter(workbook) as writer:
        first.to_excel(writer, sheet_name="Part1", index=False)
        second.to_excel(
            writer,
            sheet_name="Part2",
            index=False,
            header=False,
        )

    monkeypatch.setattr(settings, "DATASET_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(settings, "DUCKDB_TEMP_DIR", tmp_path / "duckdb-temp")
    monkeypatch.setattr(settings, "LARGE_EXCEL_MB", 1024)

    file_meta = Preprocessor().process(str(workbook))

    assert file_meta.sheets[1].header_mode == "own"
    assert file_meta.sheets[1].continuation_detected is False
    assert file_meta.sheet_groups == []


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
    assert not list(cache_dir.rglob("*.partial*"))


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


def test_streaming_import_ignores_incorrect_declared_dimension(
    tmp_path,
    monkeypatch,
):
    workbook = tmp_path / "incorrect-dimension.xlsx"
    expected = pd.DataFrame(
        {
            "id": range(250),
            "amount": [value * 1.25 for value in range(250)],
            "region": ["APAC"] * 250,
        }
    )
    expected.to_excel(workbook, index=False)
    _replace_sheet_dimension(workbook, "A1")

    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(settings, "DATASET_CACHE_DIR", cache_dir)
    monkeypatch.setattr(settings, "DUCKDB_TEMP_DIR", tmp_path / "duckdb")

    plan = Preprocessor._inspect_xlsx_package(workbook)
    file_meta = Preprocessor().process(str(workbook))
    cached = pd.read_parquet(file_meta.sheets[0].cache_path)

    assert plan.mode == "stream"
    assert plan.worksheets[0].declared_dimension == "A1"
    assert file_meta.sheets[0].rows == len(expected)
    assert file_meta.sheets[0].columns == list(expected.columns)
    assert cached["amount"].sum() == pytest.approx(expected["amount"].sum())


def test_safe_import_reads_excel_once_then_types_local_parquet(
    tmp_path,
    monkeypatch,
):
    workbook = tmp_path / "safe-mode.xlsx"
    pd.DataFrame(
        {
            "id": [1, 2, 3],
            "amount": [10.5, 20.25, 30.75],
            "label": ["A", "B", "C"],
            "active": [True, False, True],
            "posted_on": pd.to_datetime(
                ["2026-01-01", "2026-01-02", "2026-01-03"]
            ),
        }
    ).to_excel(workbook, index=False)

    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(settings, "DATASET_CACHE_DIR", cache_dir)
    monkeypatch.setattr(settings, "DUCKDB_TEMP_DIR", tmp_path / "duckdb")
    monkeypatch.setattr(settings, "IMPORT_SAFE_SOURCE_BYTES", 0)

    plan = Preprocessor._inspect_xlsx_package(workbook)
    file_meta = Preprocessor().process(str(workbook))
    sheet = file_meta.sheets[0]
    cached = pd.read_parquet(sheet.cache_path)

    assert plan.mode == "safe"
    assert sheet.dtypes == {
        "id": "int64",
        "amount": "double",
        "label": "string",
        "active": "bool",
        "posted_on": "timestamp[us]",
    }
    assert cached["id"].tolist() == [1, 2, 3]
    assert cached["amount"].tolist() == [10.5, 20.25, 30.75]
    assert cached["label"].tolist() == ["A", "B", "C"]
    assert cached["active"].tolist() == [True, False, True]
    assert cached["posted_on"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
    ]
    assert not list(cache_dir.rglob("*.raw.partial.parquet"))


def test_memory_budgeted_batches_shrink_for_long_rows(monkeypatch):
    monkeypatch.setattr(settings, "IMPORT_BATCH_ROWS", 100)
    monkeypatch.setattr(settings, "IMPORT_MIN_BATCH_ROWS", 1)
    monkeypatch.setattr(settings, "IMPORT_BATCH_TARGET_BYTES", 64 * 1024)
    processor = Preprocessor()
    rows = iter([(str(index) + "x" * 40_000,) for index in range(5)])

    batches = list(
        processor._iter_normalized_batches(
            rows,
            [],
            width=1,
            sheet_name="LongText",
            cancel_callback=None,
        )
    )

    assert [len(batch) for batch in batches] == [1, 1, 1, 1, 1]


def test_preflight_rejects_workbook_beyond_uncompressed_budget(
    tmp_path,
    monkeypatch,
):
    workbook = tmp_path / "budget.xlsx"
    pd.DataFrame({"id": [1], "value": [2]}).to_excel(workbook, index=False)
    plan = Preprocessor._inspect_xlsx_package(workbook)
    monkeypatch.setattr(
        settings,
        "IMPORT_MAX_UNCOMPRESSED_BYTES",
        plan.uncompressed_bytes - 1,
    )

    with pytest.raises(ValueError, match="expands beyond"):
        Preprocessor._validate_xlsx_import_plan(plan)


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
