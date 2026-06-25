"""Spreadsheet preprocessing, profiling, and reusable local caching."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import random
import shutil
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from collections.abc import Callable
from typing import Any

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from openpyxl import load_workbook

from config.settings import settings


logger = logging.getLogger(__name__)


class ProcessingCancelled(Exception):
    """Raised when the user cancels an in-flight import."""


class SchemaContamination(Exception):
    """Raised when a later streamed value does not fit the inferred schema."""

    def __init__(self, column: str, value: Any) -> None:
        self.column = column
        self.value = value
        super().__init__(f"Column {column!r} contains a conflicting value: {value!r}")


@dataclass
class SheetMeta:
    sheet_name: str
    rows: int
    cols: int
    columns: list[str]
    dtypes: dict[str, str]
    null_counts: dict[str, int]
    head_sample: list[dict[str, Any]]
    describe: dict[str, Any]
    unique_values: dict[str, list[str]]
    sheet_id: str = ""
    cache_path: str = ""
    sample_cache_path: str = ""
    unique_counts: dict[str, int] = field(default_factory=dict)
    unique_rates: dict[str, float] = field(default_factory=dict)
    type_profiles: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "sheet": self.sheet_name,
            "sheet_id": self.sheet_id,
            "shape": [self.rows, self.cols],
            "columns": self.columns,
            "dtypes": self.dtypes,
            "null_counts": self.null_counts,
            "unique_counts": self.unique_counts,
            "unique_rates": self.unique_rates,
            "type_profiles": self.type_profiles,
            "sample": self.head_sample,
            "describe": self.describe,
            "unique_values": self.unique_values,
        }


@dataclass
class FileMeta:
    file_path: str
    file_name: str
    file_size_kb: float
    sheet_count: int
    sheets: list[SheetMeta] = field(default_factory=list)
    dataset_id: str = ""
    display_name: str = ""
    source_fingerprint: str = ""
    profile_mode: str = "full"
    profile_sample_rows: int = 0

    @property
    def runtime_key(self) -> str:
        return self.dataset_id or self.file_name

    def to_prompt_dict(self) -> dict[str, Any]:
        dataset_key = self.runtime_key
        return {
            "file": self.file_name,
            "display_name": self.display_name or self.file_name,
            "dataset_id": dataset_key,
            "runtime_access": {
                "preferred": f'data.get("{dataset_key}", "<sheet_id>")',
                "compatible": f'dfs["{dataset_key}"]["<sheet_id>"]',
            },
            "size_kb": round(self.file_size_kb, 1),
            "profile_mode": self.profile_mode,
            "profile_sample_rows": self.profile_sample_rows,
            "sheets": [sheet.to_prompt_dict() for sheet in self.sheets],
        }


class Preprocessor:
    """Read workbooks, build caches, and prepare profile metadata."""

    def __init__(self) -> None:
        self._preview_rows = settings.PREVIEW_ROWS
        self._max_cols_describe = settings.MAX_COLS_DESCRIBE
        self._max_unique_values = settings.MAX_PROFILE_UNIQUES
        self._sample_rows = settings.SAMPLE_ROWS_PER_SHEET
        self._batch_rows = settings.IMPORT_BATCH_ROWS
        self._schema_sample_rows = settings.IMPORT_SCHEMA_SAMPLE_ROWS
        self._row_group_size = settings.IMPORT_ROW_GROUP_SIZE

    def process(
        self,
        file_path: str,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        cancel_callback: Callable[[], bool] | None = None,
    ) -> FileMeta:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File does not exist: {file_path}")
        if path.suffix.lower() not in {".xlsx", ".xls", ".xlsm"}:
            raise ValueError(f"Unsupported file type: {path.suffix}")

        size_bytes = path.stat().st_size
        if size_bytes > settings.MAX_DATASET_BYTES:
            raise ValueError("File exceeds the 2 GiB per-dataset limit.")

        self._raise_if_cancelled(cancel_callback)
        settings.DATASET_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        settings.DUCKDB_TEMP_DIR.mkdir(parents=True, exist_ok=True)
        self._ensure_free_disk_space(path)

        fingerprint = self._fingerprint(path)
        dataset_id = f"ds_{fingerprint[:12]}"
        size_kb = size_bytes / 1024
        self._emit_progress(progress_callback, "inspecting", 5, path.name)
        logger.info(
            "Starting preprocessing for %s size=%.2fMB dataset_id=%s",
            path,
            size_bytes / (1024 * 1024),
            dataset_id,
        )

        if path.suffix.lower() == ".xls" and size_kb >= settings.LARGE_EXCEL_MB * 1024:
            raise ValueError(
                "Large legacy .xls files cannot be streamed safely. Save the workbook "
                "as .xlsx and import it again."
            )

        if path.suffix.lower() in {".xlsx", ".xlsm"} and self._should_stream_xlsx(
            path,
            size_kb,
            cancel_callback=cancel_callback,
        ):
            self._emit_progress(progress_callback, "importing", 10, path.name)
            sheets = self._process_large_xlsx(
                path,
                dataset_id,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )
            profile_mode = "sampled"
        else:
            sheets = self._process_small_workbook(
                path,
                dataset_id,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )
            profile_mode = "full"

        self._emit_progress(progress_callback, "ready", 100, path.name)
        file_meta = FileMeta(
            file_path=str(path.resolve()),
            file_name=path.name,
            display_name=path.name,
            dataset_id=dataset_id,
            source_fingerprint=fingerprint,
            file_size_kb=size_kb,
            sheet_count=len(sheets),
            sheets=sheets,
            profile_mode=profile_mode,
            profile_sample_rows=(
                self._sample_rows if profile_mode == "sampled" else sum(sheet.rows for sheet in sheets)
            ),
        )
        self._write_dataset_manifest(dataset_id, file_meta)
        logger.info(
            "Finished preprocessing for %s dataset_id=%s profile_mode=%s sheets=%s",
            path.name,
            dataset_id,
            profile_mode,
            len(sheets),
        )
        return file_meta

    def _process_small_workbook(
        self,
        path: Path,
        dataset_id: str,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None,
        cancel_callback: Callable[[], bool] | None,
    ) -> list[SheetMeta]:
        with pd.ExcelFile(path) as workbook:
            sheets: list[SheetMeta] = []
            sheet_names = list(workbook.sheet_names)
            for index, sheet_name in enumerate(sheet_names, start=1):
                self._raise_if_cancelled(cancel_callback)
                self._emit_progress(
                    progress_callback,
                    "profiling",
                    10 + int(index / max(1, len(sheet_names)) * 80),
                    sheet_name,
                )
                sheets.append(self._process_sheet(workbook, sheet_name, dataset_id))
            return sheets

    def _process_sheet(
        self,
        workbook: pd.ExcelFile,
        sheet_name: str,
        dataset_id: str,
    ) -> SheetMeta:
        dataframe = workbook.parse(sheet_name)
        dataframe, type_profiles = self._normalize_dataframe_for_parquet(
            dataframe,
            sheet_name=sheet_name,
        )
        sheet_hash = hashlib.sha256(f"{dataset_id}:{sheet_name}".encode("utf-8")).hexdigest()[:12]
        sheet_id = f"sh_{sheet_hash}"

        cache_dir = settings.DATASET_CACHE_DIR / dataset_id
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{sheet_id}.parquet"
        sample_cache_path = cache_dir / f"{sheet_id}.sample.parquet"
        self._write_dataframe_parquet_atomically(dataframe, cache_path)
        self._write_dataframe_parquet_atomically(
            self._representative_sample(dataframe),
            sample_cache_path,
        )

        numeric_columns = dataframe.select_dtypes(include="number").columns[: self._max_cols_describe]
        describe_raw = dataframe[numeric_columns].describe().to_dict() if len(numeric_columns) else {}
        describe = {
            str(column): {
                str(name): round(float(value), 4)
                for name, value in statistics.items()
            }
            for column, statistics in describe_raw.items()
        }

        unique_counts = {
            str(column): int(dataframe[column].nunique(dropna=True))
            for column in dataframe.columns
        }
        denominator = max(1, len(dataframe))
        unique_rates = {
            column: round(count / denominator, 6)
            for column, count in unique_counts.items()
        }

        return SheetMeta(
            sheet_name=sheet_name,
            sheet_id=sheet_id,
            cache_path=str(cache_path),
            sample_cache_path=str(sample_cache_path),
            rows=len(dataframe),
            cols=len(dataframe.columns),
            columns=[str(column) for column in dataframe.columns],
            dtypes={str(column): str(dtype) for column, dtype in dataframe.dtypes.items()},
            null_counts={
                str(column): int(count)
                for column, count in dataframe.isnull().sum().items()
                if count > 0
            },
            head_sample=(
                dataframe.head(self._preview_rows).fillna("").astype(str).to_dict(orient="records")
            ),
            describe=describe,
            unique_values=self._collect_unique_values(dataframe),
            unique_counts=unique_counts,
            unique_rates=unique_rates,
            type_profiles=type_profiles,
        )

    def _process_large_xlsx(
        self,
        path: Path,
        dataset_id: str,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        cancel_callback: Callable[[], bool] | None = None,
    ) -> list[SheetMeta]:
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            sheets = []
            worksheets = list(workbook.worksheets)
            for index, worksheet in enumerate(worksheets, start=1):
                self._raise_if_cancelled(cancel_callback)
                self._emit_progress(
                    progress_callback,
                    "importing",
                    10 + int(index / max(1, len(worksheets)) * 65),
                    str(worksheet.title),
                )
                sheet_meta = self._stream_sheet_to_cache(
                    worksheet,
                    dataset_id,
                    cancel_callback=cancel_callback,
                )
                sheets.append(sheet_meta)
                self._emit_progress(
                    progress_callback,
                    "profiling",
                    75 + int(index / max(1, len(worksheets)) * 20),
                    str(worksheet.title),
                )
            return sheets
        finally:
            workbook.close()

    def _stream_sheet_to_cache(
        self,
        worksheet: Any,
        dataset_id: str,
        *,
        cancel_callback: Callable[[], bool] | None,
        forced_text_columns: set[str] | None = None,
    ) -> SheetMeta:
        forced_text_columns = set(forced_text_columns or ())
        sheet_name = str(worksheet.title)
        sheet_hash = hashlib.sha256(f"{dataset_id}:{sheet_name}".encode("utf-8")).hexdigest()[:12]
        sheet_id = f"sh_{sheet_hash}"
        cache_dir = settings.DATASET_CACHE_DIR / dataset_id
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_path = cache_dir / f"{sheet_id}.parquet"
        sample_cache_path = cache_dir / f"{sheet_id}.sample.parquet"
        temp_cache_path = cache_dir / f"{sheet_id}.partial.parquet"
        temp_sample_path = cache_dir / f"{sheet_id}.sample.partial.parquet"

        self._cleanup_partial_files(temp_cache_path, temp_sample_path)
        logger.info("Streaming sheet %s into parquet cache %s", sheet_name, cache_path)

        row_iterator = worksheet.iter_rows(values_only=True)
        first_row = next(row_iterator, None)
        if first_row is None:
            empty = pd.DataFrame()
            self._write_dataframe_parquet_atomically(empty, cache_path)
            self._write_dataframe_parquet_atomically(empty, sample_cache_path)
            return SheetMeta(
                sheet_name=sheet_name,
                sheet_id=sheet_id,
                cache_path=str(cache_path),
                sample_cache_path=str(sample_cache_path),
                rows=0,
                cols=0,
                columns=[],
                dtypes={},
                null_counts={},
                head_sample=[],
                describe={},
                unique_values={},
            )

        headers = self._normalize_headers(first_row)
        seed_rows: list[list[Any]] = []
        for _ in range(self._schema_sample_rows):
            raw = next(row_iterator, None)
            if raw is None:
                break
            seed_rows.append(self._normalize_row(raw, len(headers)))

        schema = self._infer_arrow_schema(
            headers,
            seed_rows,
            forced_text_columns=forced_text_columns,
        )
        writer = pq.ParquetWriter(
            temp_cache_path,
            schema=schema,
            compression="zstd",
            use_dictionary=True,
        )
        rows_seen = 0
        null_counts = Counter()
        head_rows: list[dict[str, Any]] = []
        reservoir: list[dict[str, Any]] = []
        reservoir_rng = random.Random(42)
        text_uniques: dict[str, set[str]] = {header: set() for header in headers}

        contamination: SchemaContamination | None = None
        try:
            batch: list[list[Any]] = []
            pending = list(seed_rows)
            while True:
                self._raise_if_cancelled(cancel_callback)
                while pending and len(batch) < self._batch_rows:
                    batch.append(pending.pop(0))
                while len(batch) < self._batch_rows:
                    raw = next(row_iterator, None)
                    if raw is None:
                        break
                    batch.append(self._normalize_row(raw, len(headers)))
                if not batch:
                    break

                table, records = self._batch_to_arrow_table(headers, schema, batch)
                writer.write_table(table, row_group_size=self._row_group_size)
                rows_seen = self._update_stream_profile(
                    records,
                    rows_seen,
                    null_counts,
                    head_rows,
                    reservoir,
                    reservoir_rng,
                    text_uniques,
                )
                batch = []
        except SchemaContamination as exc:
            contamination = exc
            logger.warning(
                "Type contamination detected dataset_id=%s sheet=%s column=%s value=%r; "
                "restarting that column as text",
                dataset_id,
                sheet_name,
                exc.column,
                exc.value,
            )
        except Exception:
            logger.exception("Large-sheet import failed for %s/%s", dataset_id, sheet_name)
            raise
        finally:
            writer.close()

        if contamination is not None:
            self._cleanup_partial_files(temp_cache_path, temp_sample_path)
            forced_text_columns.add(contamination.column)
            return self._stream_sheet_to_cache(
                worksheet,
                dataset_id,
                cancel_callback=cancel_callback,
                forced_text_columns=forced_text_columns,
            )

        sample_df = pd.DataFrame(reservoir, columns=headers) if reservoir else pd.DataFrame(columns=headers)
        self._write_dataframe_parquet_atomically(sample_df, temp_sample_path)
        unique_counts = self._approx_unique_counts(temp_cache_path, headers)
        unique_rates = {
            column: round(count / max(1, rows_seen), 6)
            for column, count in unique_counts.items()
        }
        dtypes = {field.name: str(field.type) for field in schema}
        type_profiles = self._build_type_profiles(sample_df, dtypes)
        describe = self._describe_sample(sample_df, dtypes)
        unique_values = self._collect_unique_values(sample_df)

        self._finalize_atomic_cache(temp_cache_path, cache_path)
        self._finalize_atomic_cache(temp_sample_path, sample_cache_path)

        logger.info(
            "Completed streaming sheet %s rows=%s cols=%s",
            sheet_name,
            rows_seen,
            len(headers),
        )
        return SheetMeta(
            sheet_name=sheet_name,
            sheet_id=sheet_id,
            cache_path=str(cache_path),
            sample_cache_path=str(sample_cache_path),
            rows=rows_seen,
            cols=len(headers),
            columns=headers,
            dtypes=dtypes,
            null_counts={key: int(value) for key, value in null_counts.items() if value > 0},
            head_sample=[
                {column: "" if value is None else str(value) for column, value in row.items()}
                for row in head_rows
            ],
            describe=describe,
            unique_values=unique_values,
            unique_counts=unique_counts,
            unique_rates=unique_rates,
            type_profiles=type_profiles,
        )

    @staticmethod
    def _should_stream_xlsx(
        path: Path,
        size_kb: float,
        *,
        cancel_callback: Callable[[], bool] | None = None,
    ) -> bool:
        if size_kb >= settings.LARGE_EXCEL_MB * 1024:
            return True
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            for worksheet in workbook.worksheets:
                if cancel_callback and cancel_callback():
                    raise ProcessingCancelled("Dataset import cancelled")
                if int(worksheet.max_row or 0) >= settings.LARGE_DATASET_ROWS:
                    return True
            return False
        finally:
            workbook.close()

    def _ensure_free_disk_space(self, path: Path) -> None:
        try:
            usage = shutil.disk_usage(settings.DATASET_CACHE_DIR)
        except FileNotFoundError:
            settings.DATASET_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            usage = shutil.disk_usage(settings.DATASET_CACHE_DIR)

        estimated_need = self._estimate_required_disk_bytes(path)
        logger.info(
            "Disk check for %s free=%s required=%s",
            path.name,
            usage.free,
            estimated_need,
        )
        if usage.free < estimated_need:
            required_gb = estimated_need / (1024**3)
            free_gb = usage.free / (1024**3)
            raise ValueError(
                "Not enough free disk space for import. "
                f"Need about {required_gb:.1f} GB free, found {free_gb:.1f} GB."
            )

    @staticmethod
    def _estimate_required_disk_bytes(path: Path) -> int:
        source_size = path.stat().st_size
        zip_uncompressed = 0
        if path.suffix.lower() in {".xlsx", ".xlsm"}:
            try:
                with zipfile.ZipFile(path) as archive:
                    zip_uncompressed = sum(info.file_size for info in archive.infolist())
            except zipfile.BadZipFile:
                logger.warning("Could not inspect ZIP members for %s", path)
        estimated = max(
            settings.IMPORT_MIN_FREE_DISK_BYTES,
            int(source_size * settings.IMPORT_SOURCE_SIZE_MULTIPLIER),
            int(zip_uncompressed * settings.IMPORT_UNCOMPRESSED_MULTIPLIER),
        )
        return estimated

    @staticmethod
    def _normalize_headers(values: tuple[Any, ...]) -> list[str]:
        seen: dict[str, int] = {}
        headers: list[str] = []
        for index, value in enumerate(values, start=1):
            base = str(value).strip() if value is not None else ""
            base = base or f"Column_{index}"
            seen[base] = seen.get(base, 0) + 1
            headers.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
        return headers

    @staticmethod
    def _normalize_row(values: Any, width: int) -> list[Any]:
        row = list(values[:width]) if values is not None else []
        if len(row) < width:
            row.extend([None] * (width - len(row)))
        return row

    def _batch_to_arrow_table(
        self,
        headers: list[str],
        schema: pa.Schema,
        rows: list[list[Any]],
    ) -> tuple[pa.Table, list[dict[str, Any]]]:
        records: list[dict[str, Any]] = []
        columns: dict[str, list[Any]] = {header: [] for header in headers}
        for row in rows:
            record: dict[str, Any] = {}
            for index, header in enumerate(headers):
                field = schema.field(index)
                value = self._coerce_scalar(
                    row[index],
                    field.type,
                    column=header,
                )
                columns[header].append(value)
                record[header] = value
            records.append(record)
        arrays = [pa.array(columns[field.name], type=field.type) for field in schema]
        return pa.Table.from_arrays(arrays, schema=schema), records

    def _infer_arrow_schema(
        self,
        headers: list[str],
        sample_rows: list[list[Any]],
        *,
        forced_text_columns: set[str] | None = None,
    ) -> pa.Schema:
        forced_text_columns = forced_text_columns or set()
        fields = []
        for index, header in enumerate(headers):
            observed = [row[index] for row in sample_rows if row[index] not in (None, "")]
            arrow_type = (
                pa.string()
                if header in forced_text_columns
                else self._infer_arrow_type(observed)
            )
            fields.append(pa.field(header, arrow_type))
        return pa.schema(fields)

    @staticmethod
    def _infer_arrow_type(values: list[Any]) -> pa.DataType:
        if not values:
            return pa.string()
        kinds = set()
        for value in values:
            if isinstance(value, bool):
                kinds.add("bool")
            elif isinstance(value, int) and not isinstance(value, bool):
                kinds.add("int")
            elif isinstance(value, float):
                kinds.add("float")
            elif isinstance(value, datetime):
                kinds.add("datetime")
            elif isinstance(value, date):
                kinds.add("date")
            elif isinstance(value, time):
                kinds.add("time")
            else:
                kinds.add("string")
        if kinds <= {"bool"}:
            return pa.bool_()
        if kinds <= {"bool", "int"}:
            return pa.int64()
        if kinds <= {"bool", "int", "float"}:
            return pa.float64()
        if kinds <= {"datetime"}:
            return pa.timestamp("us")
        if kinds <= {"date"}:
            return pa.date32()
        return pa.string()

    @staticmethod
    def _coerce_scalar(
        value: Any,
        arrow_type: pa.DataType,
        *,
        column: str = "",
    ) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            if stripped == "":
                return None
            value = stripped
        try:
            if pa.types.is_boolean(arrow_type):
                if isinstance(value, str):
                    normalized = value.lower()
                    if normalized in {"true", "1", "yes", "y"}:
                        return True
                    if normalized in {"false", "0", "no", "n"}:
                        return False
                    raise SchemaContamination(column, value)
                return bool(value)
            if pa.types.is_integer(arrow_type):
                if isinstance(value, bool):
                    return int(value)
                if isinstance(value, (int, float)) and math.isfinite(float(value)):
                    return int(value)
                raise SchemaContamination(column, value)
            if pa.types.is_floating(arrow_type):
                if isinstance(value, bool):
                    return float(int(value))
                if isinstance(value, (int, float)) and math.isfinite(float(value)):
                    return float(value)
                raise SchemaContamination(column, value)
            if pa.types.is_timestamp(arrow_type):
                if isinstance(value, datetime):
                    return value
                if isinstance(value, date):
                    return datetime.combine(value, time.min)
                raise SchemaContamination(column, value)
            if pa.types.is_date32(arrow_type):
                if isinstance(value, datetime):
                    return value.date()
                if isinstance(value, date):
                    return value
                raise SchemaContamination(column, value)
            if isinstance(value, (datetime, date, time)):
                return value.isoformat()
            return str(value)
        except SchemaContamination:
            raise
        except Exception:
            return None

    def _normalize_dataframe_for_parquet(
        self,
        dataframe: pd.DataFrame,
        *,
        sheet_name: str,
    ) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
        normalized = dataframe.copy()
        for column in normalized.select_dtypes(include=["object", "string"]).columns:
            series = normalized[column]
            normalized[column] = series.map(
                lambda value: None if pd.isna(value) else str(value)
            ).astype("string")
        profiles = self._build_type_profiles(
            normalized,
            {str(column): str(dtype) for column, dtype in normalized.dtypes.items()},
        )
        polluted = [
            column
            for column, profile in profiles.items()
            if int(profile.get("invalid_count", 0)) > 0
        ]
        if polluted:
            logger.warning(
                "Preserved mixed-type values as text sheet=%s columns=%s",
                sheet_name,
                polluted,
            )
        return normalized, profiles

    @staticmethod
    def _build_type_profiles(
        dataframe: pd.DataFrame,
        dtypes: dict[str, str],
    ) -> dict[str, dict[str, Any]]:
        profiles: dict[str, dict[str, Any]] = {}
        for column in dataframe.columns:
            dtype = str(dtypes.get(str(column), ""))
            lowered = dtype.lower()
            if not any(token in lowered for token in ("object", "string", "str")):
                continue
            series = dataframe[column]
            non_null = series.dropna()
            if non_null.empty:
                continue
            text = non_null.astype(str).str.strip()
            non_empty = text[text != ""]
            if non_empty.empty:
                continue
            numeric = pd.to_numeric(
                non_empty.str.replace(",", "", regex=False),
                errors="coerce",
            )
            valid_count = int(numeric.notna().sum())
            invalid = non_empty[numeric.isna()]
            invalid_count = int(len(invalid))
            rate = valid_count / max(1, len(non_empty))
            if valid_count < 2 or rate < 0.6:
                continue
            profiles[str(column)] = {
                "storage_type": "string",
                "inferred_type": "numeric",
                "non_empty_count": int(len(non_empty)),
                "valid_count": valid_count,
                "invalid_count": invalid_count,
                "conversion_rate": round(rate, 6),
                "invalid_examples": list(dict.fromkeys(invalid.astype(str).tolist()))[:5],
            }
        return profiles

    def _update_stream_profile(
        self,
        records: list[dict[str, Any]],
        rows_seen: int,
        null_counts: Counter,
        head_rows: list[dict[str, Any]],
        reservoir: list[dict[str, Any]],
        reservoir_rng: random.Random,
        text_uniques: dict[str, set[str]],
    ) -> int:
        for record in records:
            rows_seen += 1
            for column, value in record.items():
                if value is None:
                    null_counts[column] += 1
                elif isinstance(value, str) and len(text_uniques[column]) <= self._max_unique_values:
                    text_uniques[column].add(value)
            if len(head_rows) < self._preview_rows:
                head_rows.append(record.copy())
            if len(reservoir) < self._sample_rows:
                reservoir.append(record.copy())
            else:
                replacement_index = reservoir_rng.randint(0, rows_seen - 1)
                if replacement_index < self._sample_rows:
                    reservoir[replacement_index] = record.copy()
        return rows_seen

    def _approx_unique_counts(self, parquet_path: Path, columns: list[str]) -> dict[str, int]:
        if not columns:
            return {}
        connection = self._duckdb_connection()
        try:
            aggregates = [
                f"APPROX_COUNT_DISTINCT({self._quote(column)})"
                for column in columns
            ]
            values = connection.execute(
                "SELECT " + ",".join(aggregates) + " FROM read_parquet(?)",
                [str(parquet_path)],
            ).fetchone()
            return {
                column: int((values[index] or 0) if values else 0)
                for index, column in enumerate(columns)
            }
        finally:
            connection.close()

    def _describe_sample(self, sample: pd.DataFrame, dtypes: dict[str, str]) -> dict[str, Any]:
        if sample.empty:
            return {}
        numeric_columns = []
        for column, dtype in dtypes.items():
            upper = dtype.upper()
            if any(token in upper for token in ("INT", "DOUBLE", "FLOAT", "DECIMAL")):
                numeric_columns.append(column)
        numeric_columns = numeric_columns[: self._max_cols_describe]
        if not numeric_columns:
            return {}
        describe = sample[numeric_columns].describe().to_dict()
        return {
            str(column): {
                str(name): round(float(value), 4)
                for name, value in statistics.items()
                if pd.notna(value)
            }
            for column, statistics in describe.items()
        }

    def _collect_unique_values(self, dataframe: pd.DataFrame) -> dict[str, list[str]]:
        values: dict[str, list[str]] = {}
        text_columns = dataframe.select_dtypes(include=["object", "string"]).columns
        for column in text_columns:
            series = dataframe[column].dropna().astype(str)
            unique = sorted(series.unique().tolist())
            if 0 < len(unique) <= self._max_unique_values:
                values[str(column)] = unique
        return values

    @staticmethod
    def _representative_sample(dataframe: pd.DataFrame) -> pd.DataFrame:
        target = max(1, settings.SAMPLE_ROWS_PER_SHEET)
        if len(dataframe) <= target:
            return dataframe.copy()
        edge = min(1000, target // 4)
        edge_indices = set(dataframe.head(edge).index) | set(dataframe.tail(edge).index)
        remaining = dataframe.loc[~dataframe.index.isin(edge_indices)]
        random_count = min(max(0, target - len(edge_indices)), len(remaining))
        sampled = pd.concat(
            [
                dataframe.loc[sorted(edge_indices)],
                remaining.sample(n=random_count, random_state=42),
            ]
        )
        return sampled.head(target)

    @staticmethod
    def _write_dataframe_parquet_atomically(dataframe: pd.DataFrame, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".partial")
        temporary.unlink(missing_ok=True)
        dataframe.to_parquet(temporary, index=False)
        temporary.replace(path)

    @staticmethod
    def _finalize_atomic_cache(temporary: Path, final_path: Path) -> None:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.unlink(missing_ok=True)
        temporary.replace(final_path)

    @staticmethod
    def _cleanup_partial_files(*paths: Path) -> None:
        for path in paths:
            path.unlink(missing_ok=True)

    def _write_dataset_manifest(self, dataset_id: str, file_meta: FileMeta) -> None:
        manifest_path = settings.DATASET_CACHE_DIR / dataset_id / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "dataset_id": file_meta.dataset_id,
            "file_name": file_meta.file_name,
            "file_path": file_meta.file_path,
            "source_fingerprint": file_meta.source_fingerprint,
            "profile_mode": file_meta.profile_mode,
            "profile_sample_rows": file_meta.profile_sample_rows,
            "sheet_count": file_meta.sheet_count,
            "sheets": [sheet.to_prompt_dict() for sheet in file_meta.sheets],
        }
        manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _fingerprint(path: Path) -> str:
        stat = path.stat()
        payload = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _quote(identifier: str) -> str:
        return '"' + str(identifier).replace('"', '""') + '"'

    @staticmethod
    def _emit_progress(
        callback: Callable[[dict[str, Any]], None] | None,
        stage: str,
        percent: int,
        detail: str,
    ) -> None:
        if callback is not None:
            callback(
                {
                    "stage": stage,
                    "percent": max(0, min(100, int(percent))),
                    "detail": detail,
                }
            )

    @staticmethod
    def _raise_if_cancelled(cancel_callback: Callable[[], bool] | None) -> None:
        if cancel_callback and cancel_callback():
            logger.info("Dataset import cancelled by user")
            raise ProcessingCancelled("Dataset import cancelled")

    @staticmethod
    def _duckdb_connection() -> duckdb.DuckDBPyConnection:
        settings.DUCKDB_TEMP_DIR.mkdir(parents=True, exist_ok=True)
        connection = duckdb.connect()
        temp_dir = str(settings.DUCKDB_TEMP_DIR).replace("'", "''")
        connection.execute(f"SET memory_limit='{settings.DUCKDB_MEMORY_LIMIT}'")
        connection.execute(f"SET threads={max(1, settings.DUCKDB_THREADS)}")
        connection.execute(f"SET temp_directory='{temp_dir}'")
        connection.execute(f"SET max_temp_directory_size='{settings.DUCKDB_MAX_TEMP_SIZE}'")
        connection.execute(
            "SET preserve_insertion_order="
            + ("true" if settings.DUCKDB_PRESERVE_INSERTION_ORDER == "true" else "false")
        )
        return connection
