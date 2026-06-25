"""Deterministic spreadsheet dirty-data detection and cleaning."""

from __future__ import annotations

import logging
import math
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import duckdb
import pandas as pd
import pyarrow.parquet as pq
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from config.settings import settings
from core.preprocessor import FileMeta, ProcessingCancelled, SheetMeta


logger = logging.getLogger(__name__)


@dataclass
class CleaningIssue:
    issue_id: str
    title: str
    count: int
    columns: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    detail: str = ""
    sheet_columns: dict[str, list[str]] = field(default_factory=dict)
    column_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    column_methods: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    estimated_changes: int = 0


@dataclass
class CleaningProfile:
    dataset_id: str
    rows: int
    columns: int
    sheets: int
    issues: list[CleaningIssue]


@dataclass
class CleaningResult:
    dataset_id: str
    output_path: str
    rows_before: int
    rows_after: int
    actions: list[str]


class CleaningService:
    """Profile and clean cached Parquet sheets without AI assistance."""

    FORMULA_PREFIXES = ("=", "+", "-", "@")
    MAX_EXCEL_TEXT = 32_767

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._connection_lock = threading.Lock()
        self._active_connection: duckdb.DuckDBPyConnection | None = None

    def cancel(self) -> None:
        self._cancelled.set()
        with self._connection_lock:
            connection = self._active_connection
        if connection is not None:
            try:
                connection.interrupt()
            except Exception:
                logger.debug("DuckDB interruption failed", exc_info=True)

    def profile(
        self,
        file_meta: FileMeta,
        *,
        progress_callback: Callable[[int, str], None] | None = None,
        cancel_callback: Callable[[], bool] | None = None,
    ) -> CleaningProfile:
        self._check_cancel(cancel_callback)
        issues: list[CleaningIssue] = []
        total_rows = sum(sheet.rows for sheet in file_meta.sheets)
        total_columns = sum(sheet.cols for sheet in file_meta.sheets)

        missing_columns: list[str] = []
        missing_column_counts: dict[str, dict[str, int]] = {}
        missing_column_methods: dict[str, dict[str, list[str]]] = {}
        missing_count = 0
        duplicate_count = 0
        blank_row_count = 0
        empty_columns: list[str] = []
        mixed_numeric_columns: list[str] = []
        mixed_numeric_count = 0
        mixed_column_counts: dict[str, dict[str, int]] = {}
        mixed_column_methods: dict[str, dict[str, list[str]]] = {}

        connection = self._connect()
        try:
            for sheet_index, sheet in enumerate(file_meta.sheets, start=1):
                self._check_cancel(cancel_callback)
                if progress_callback:
                    progress_callback(
                        int((sheet_index - 1) / max(1, len(file_meta.sheets)) * 85),
                        f"Scanning {sheet.sheet_name}",
                    )
                source = self._sql_string(sheet.cache_path)
                # DuckDB cannot COUNT(DISTINCT *) directly; group by all columns.
                if sheet.columns and sheet.rows:
                    quoted = ", ".join(self._quote(column) for column in sheet.columns)
                    duplicate_count += int(
                        self._execute(
                            connection,
                            "SELECT COALESCE(SUM(group_count), 0) FROM ("
                            f"SELECT COUNT(*) AS group_count "
                            f"FROM read_parquet('{source}') "
                            f"GROUP BY {quoted} HAVING COUNT(*) > 1"
                            ") duplicate_groups"
                        ).fetchone()[0]
                    )
                    blank_condition = " AND ".join(
                        self._blank_value_expression(column, sheet.dtypes.get(column, ""))
                        for column in sheet.columns
                    )
                    text_columns = [
                        column
                        for column in sheet.columns
                        if self._is_text_dtype(sheet.dtypes.get(column, ""))
                    ]
                    blank_value = self._execute(
                        connection,
                        "SELECT COUNT(*) FILTER (WHERE "
                        f"{blank_condition}) FROM read_parquet(?)",
                        [sheet.cache_path],
                    ).fetchone()
                    blank_row_count += int((blank_value or [0])[0] or 0)
                    for offset in range(0, len(text_columns), 100):
                        self._check_cancel(cancel_callback)
                        column_batch = text_columns[offset : offset + 100]
                        aggregates = []
                        for column in column_batch:
                            quoted_column = self._quote(column)
                            numeric_expression = self._numeric_cast_expression(
                                quoted_column
                            )
                            aggregates.extend(
                                [
                                    "COUNT(*) FILTER (WHERE "
                                    f"{quoted_column} IS NOT NULL AND "
                                    f"TRIM(CAST({quoted_column} AS VARCHAR)) != '')",
                                    "COUNT(*) FILTER (WHERE "
                                    f"{numeric_expression} IS NOT NULL)",
                                ]
                            )
                        aggregate_values = self._execute(
                            connection,
                            "SELECT "
                            + ", ".join(aggregates)
                            + " FROM read_parquet(?)",
                            [sheet.cache_path],
                        ).fetchone()
                        for batch_index, column in enumerate(column_batch):
                            value_index = batch_index * 2
                            non_empty = int(aggregate_values[value_index] or 0)
                            valid_numeric = int(
                                aggregate_values[value_index + 1] or 0
                            )
                            invalid_numeric = max(0, non_empty - valid_numeric)
                            conversion_rate = valid_numeric / max(1, non_empty)
                            if (
                                valid_numeric >= 2
                                and invalid_numeric > 0
                                and conversion_rate >= 0.6
                            ):
                                qualified = f"{sheet.sheet_name}.{column}"
                                sheet.type_profiles[column] = {
                                    "storage_type": "string",
                                    "inferred_type": "numeric",
                                    "non_empty_count": non_empty,
                                    "valid_count": valid_numeric,
                                    "invalid_count": invalid_numeric,
                                    "conversion_rate": round(conversion_rate, 6),
                                    "invalid_examples": list(
                                        sheet.type_profiles.get(column, {}).get(
                                            "invalid_examples",
                                            [],
                                        )
                                    )[:5],
                                }
                                mixed_numeric_count += invalid_numeric
                                mixed_numeric_columns.append(qualified)
                                mixed_column_counts.setdefault(
                                    sheet.sheet_name,
                                    {},
                                )[column] = invalid_numeric
                                mixed_column_methods.setdefault(
                                    sheet.sheet_name,
                                    {},
                                )[column] = [
                                    "invalid_to_null",
                                    "invalid_zero",
                                    "invalid_mean",
                                    "invalid_median",
                                    "invalid_mode",
                                    "drop_invalid_rows",
                                    "keep_text",
                                ]

                for column in sheet.columns:
                    nulls = int(sheet.null_counts.get(column, 0))
                    qualified = f"{sheet.sheet_name}.{column}"
                    if nulls:
                        missing_count += nulls
                        missing_columns.append(qualified)
                        missing_column_counts.setdefault(sheet.sheet_name, {})[
                            column
                        ] = nulls
                        methods = ["drop_rows"]
                        if self._is_numeric_dtype(
                            sheet.dtypes.get(column, "")
                        ):
                            methods.extend(
                                ["fill_zero", "fill_mean", "fill_median"]
                            )
                        methods.append("fill_mode")
                        missing_column_methods.setdefault(sheet.sheet_name, {})[
                            column
                        ] = methods
                    if sheet.rows and nulls >= sheet.rows:
                        empty_columns.append(qualified)
        finally:
            self._clear_active_connection(connection)
            connection.close()
        if progress_callback:
            progress_callback(100, "Scan complete")

        if missing_count:
            missing_methods = list(
                dict.fromkeys(
                    method
                    for sheet_methods in missing_column_methods.values()
                    for methods in sheet_methods.values()
                    for method in methods
                )
            )
            issues.append(
                CleaningIssue(
                    "missing_values",
                    "Missing values",
                    missing_count,
                    missing_columns,
                    missing_methods,
                    "Choose one deterministic treatment for applicable columns.",
                    column_counts=missing_column_counts,
                    column_methods=missing_column_methods,
                    estimated_changes=missing_count,
                )
            )
        if duplicate_count:
            issues.append(
                CleaningIssue(
                    "duplicate_rows",
                    "Duplicate rows",
                    duplicate_count,
                    methods=[
                        "duplicate_keep_first",
                        "duplicate_keep_last",
                        "duplicate_remove_all",
                    ],
                    estimated_changes=duplicate_count,
                )
            )
        if any(sheet.columns and sheet.rows for sheet in file_meta.sheets):
            issues.append(
                CleaningIssue(
                    "key_duplicates",
                    "Duplicate key values",
                    0,
                    methods=[
                        "key_keep_first",
                        "key_keep_last",
                        "key_remove_all",
                    ],
                    detail=(
                        "Choose one or more key columns. Duplicate values are "
                        "evaluated independently within each sheet."
                    ),
                    sheet_columns={
                        sheet.sheet_name: list(sheet.columns)
                        for sheet in file_meta.sheets
                        if sheet.columns
                    },
                    estimated_changes=0,
                )
            )
        if blank_row_count:
            issues.append(
                CleaningIssue(
                    "blank_rows",
                    "Completely blank rows",
                    blank_row_count,
                    methods=["drop_blank_rows"],
                    estimated_changes=blank_row_count,
                )
            )
        if empty_columns:
            issues.append(
                CleaningIssue(
                    "empty_columns",
                    "Completely empty columns",
                    len(empty_columns),
                    empty_columns,
                    ["drop_empty_columns"],
                    estimated_changes=len(empty_columns),
                )
            )
        if mixed_numeric_count:
            issues.append(
                CleaningIssue(
                    "mixed_numeric_values",
                    "Invalid values in numeric columns",
                    mixed_numeric_count,
                    mixed_numeric_columns,
                    [
                        "invalid_to_null",
                        "invalid_zero",
                        "invalid_mean",
                        "invalid_median",
                        "invalid_mode",
                        "drop_invalid_rows",
                        "keep_text",
                    ],
                    "Mostly numeric columns contain text or other invalid values.",
                    column_counts=mixed_column_counts,
                    column_methods=mixed_column_methods,
                    estimated_changes=mixed_numeric_count,
                )
            )

        logger.info(
            "Cleaning profile complete dataset_id=%s rows=%s issues=%s",
            file_meta.dataset_id,
            total_rows,
            len(issues),
        )
        return CleaningProfile(
            dataset_id=file_meta.dataset_id,
            rows=total_rows,
            columns=total_columns,
            sheets=len(file_meta.sheets),
            issues=issues,
        )

    def clean(
        self,
        file_meta: FileMeta,
        selections: dict[str, Any],
        output_path: str,
        *,
        progress_callback: Callable[[int, str], None] | None = None,
        cancel_callback: Callable[[], bool] | None = None,
    ) -> CleaningResult:
        if not selections:
            raise ValueError("Select at least one cleaning action.")
        self._validate_selections(file_meta, selections)
        destination = Path(output_path)
        source_path = Path(file_meta.file_path)
        if self._same_path(source_path, destination):
            raise ValueError(
                "The cleaned workbook cannot overwrite the original dataset. "
                "Choose a different file name or folder."
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        settings.DUCKDB_TEMP_DIR.mkdir(parents=True, exist_ok=True)
        self._ensure_cleaning_disk_space(file_meta, destination)
        partial = destination.with_suffix(destination.suffix + ".partial")
        partial.unlink(missing_ok=True)

        workbook = Workbook(write_only=True)
        rows_after = 0
        actions: list[str] = []
        try:
            with tempfile.TemporaryDirectory(
                prefix="ey-clean-",
                dir=settings.DUCKDB_TEMP_DIR,
            ) as temp_dir:
                for index, sheet in enumerate(file_meta.sheets, start=1):
                    self._check_cancel(cancel_callback)
                    if progress_callback:
                        progress_callback(
                            int((index - 1) / max(1, len(file_meta.sheets)) * 70),
                            f"Transforming {sheet.sheet_name}",
                        )
                    cleaned_cache = Path(temp_dir) / f"sheet-{index}.parquet"
                    self._clean_sheet_to_parquet(
                        sheet,
                        selections,
                        cleaned_cache,
                        cancel_callback=cancel_callback,
                    )
                    parquet_file = pq.ParquetFile(cleaned_cache)
                    try:
                        rows_after += parquet_file.metadata.num_rows
                        if parquet_file.metadata.num_rows > 1_048_576:
                            raise ValueError(
                                f"Sheet {sheet.sheet_name!r} exceeds Excel's "
                                "1,048,576-row limit after cleaning."
                            )
                        worksheet = workbook.create_sheet(
                            self._safe_sheet_name(sheet.sheet_name, index)
                        )
                        worksheet.append(
                            [
                                self._excel_value(column)
                                for column in parquet_file.schema_arrow.names
                            ]
                        )
                        for batch in parquet_file.iter_batches(batch_size=10_000):
                            self._check_cancel(cancel_callback)
                            for row in batch.to_pylist():
                                worksheet.append(
                                    [
                                        self._excel_value(row[column])
                                        for column in parquet_file.schema_arrow.names
                                    ]
                                )
                    finally:
                        parquet_file.close()
                    if progress_callback:
                        progress_callback(
                            70 + int(index / max(1, len(file_meta.sheets)) * 25),
                            f"Writing {sheet.sheet_name}",
                        )
            self._check_cancel(cancel_callback)
            workbook.save(partial)
            self._check_cancel(cancel_callback)
            partial.replace(destination)
            actions = [f"{issue}: {method}" for issue, method in selections.items()]
        except Exception:
            partial.unlink(missing_ok=True)
            logger.exception("Cleaning failed dataset_id=%s output=%s", file_meta.dataset_id, output_path)
            raise

        result = CleaningResult(
            dataset_id=file_meta.dataset_id,
            output_path=str(destination),
            rows_before=sum(sheet.rows for sheet in file_meta.sheets),
            rows_after=rows_after,
            actions=actions,
        )
        logger.info(
            "Cleaning completed dataset_id=%s rows_before=%s rows_after=%s output=%s",
            file_meta.dataset_id,
            result.rows_before,
            result.rows_after,
            result.output_path,
        )
        return result

    def _clean_sheet_to_parquet(
        self,
        sheet: SheetMeta,
        selections: dict[str, Any],
        destination: Path,
        *,
        cancel_callback: Callable[[], bool] | None = None,
    ) -> None:
        kept_columns = [
            column
            for column in sheet.columns
            if not (
                selections.get("empty_columns") == "drop_empty_columns"
                and sheet.null_counts.get(column, 0) >= sheet.rows
            )
        ]
        if not kept_columns:
            raise ValueError(f"Sheet {sheet.sheet_name!r} contains no usable columns.")

        missing_methods = self._column_methods_for_sheet(
            selections.get("missing_values"),
            sheet,
        )
        mixed_numeric_methods = self._column_methods_for_sheet(
            selections.get("mixed_numeric_values"),
            sheet,
        )
        duplicate_method = selections.get("duplicate_rows")
        key_duplicate_config = selections.get("key_duplicates") or {}
        key_duplicate_method = (
            key_duplicate_config.get("method")
            if isinstance(key_duplicate_config, dict)
            else None
        )
        configured_key_columns = (
            key_duplicate_config.get("columns", {})
            if isinstance(key_duplicate_config, dict)
            else {}
        )
        configured_for_sheet = configured_key_columns.get(sheet.sheet_name, [])
        unavailable_key_columns = [
            column for column in configured_for_sheet if column not in kept_columns
        ]
        if unavailable_key_columns:
            raise ValueError(
                "Key columns cannot be removed by another selected rule: "
                + ", ".join(unavailable_key_columns)
            )
        key_columns = [
            column
            for column in configured_for_sheet
            if column in kept_columns
        ]
        polluted_numeric_columns = {
            column
            for column, profile in sheet.type_profiles.items()
            if profile.get("inferred_type") == "numeric"
            and int(profile.get("invalid_count", 0)) > 0
        }
        expressions: list[str] = []
        for column in kept_columns:
            quoted = self._quote(column)
            expression = quoted
            dtype = sheet.dtypes.get(column, "")
            native_numeric = self._is_numeric_dtype(dtype)
            mixed_numeric_method = mixed_numeric_methods.get(column)
            missing_method = missing_methods.get(column)
            if (
                column in polluted_numeric_columns
                and mixed_numeric_method
                and mixed_numeric_method != "keep_text"
            ):
                numeric_expression = self._numeric_cast_expression(quoted)
                original_blank = self._blank_value_expression(column, dtype)
                invalid_replacement = self._numeric_replacement_expression(
                    mixed_numeric_method,
                    numeric_expression,
                )
                missing_replacement = self._missing_replacement_expression(
                    missing_method,
                    quoted,
                    numeric_expression=numeric_expression,
                    numeric=True,
                )
                expression = (
                    f"CASE WHEN {original_blank} THEN {missing_replacement} "
                    f"WHEN {numeric_expression} IS NULL THEN {invalid_replacement} "
                    f"ELSE {numeric_expression} END"
                )
            elif missing_method == "fill_zero" and native_numeric:
                expression = f"COALESCE({expression}, 0)"
            elif (
                missing_method in {"fill_mean", "fill_median"}
                and native_numeric
            ):
                aggregate = "AVG" if missing_method == "fill_mean" else "MEDIAN"
                expression = (
                    f"COALESCE({expression}, "
                    f"(SELECT {aggregate}({quoted}) FROM source_data))"
                )
            elif missing_method == "fill_mode":
                expression = (
                    f"COALESCE({expression}, (SELECT {quoted} FROM source_data "
                    f"WHERE {quoted} IS NOT NULL GROUP BY {quoted} "
                    f"ORDER BY COUNT(*) DESC, CAST({quoted} AS VARCHAR) ASC LIMIT 1))"
                )
            expressions.append(f"{expression} AS {quoted}")

        where = ""
        where_conditions = [
            f"{self._quote(column)} IS NOT NULL"
            for column, method in missing_methods.items()
            if method == "drop_rows" and column in kept_columns
        ]
        if selections.get("blank_rows") == "drop_blank_rows":
            non_blank_conditions = [
                f"NOT ({self._blank_value_expression(column, sheet.dtypes.get(column, ''))})"
                for column in kept_columns
            ]
            if non_blank_conditions:
                where_conditions.append("(" + " OR ".join(non_blank_conditions) + ")")
        for column, method in mixed_numeric_methods.items():
            if method == "drop_invalid_rows" and column in polluted_numeric_columns:
                quoted = self._quote(column)
                where_conditions.append(
                    f"({quoted} IS NULL OR TRIM(CAST({quoted} AS VARCHAR)) = '' "
                    f"OR {self._numeric_cast_expression(quoted)} IS NOT NULL)"
                )
        if where_conditions:
            where = " WHERE " + " AND ".join(where_conditions)
        source = self._sql_string(sheet.cache_path)
        target = self._sql_string(str(destination))
        projected_columns = ", ".join(self._quote(column) for column in kept_columns)
        row_helper = "__ey_clean_source_row__"
        while row_helper in kept_columns:
            row_helper += "_"
        quoted_row_helper = self._quote(row_helper)
        transformed = (
            f"SELECT {', '.join(expressions)}, {quoted_row_helper} "
            "FROM source_data"
            f"{where}"
        )
        raw_columns = ", ".join(
            self._quote(column)
            for column in sheet.columns
        )
        if "file_row_number" not in sheet.columns:
            source_cte = (
                "source_data AS ("
                f"SELECT {raw_columns}, file_row_number AS {quoted_row_helper} "
                f"FROM read_parquet('{source}', file_row_number=true)"
                ")"
            )
        else:
            source_cte = (
                "raw_source AS ("
                f"SELECT * FROM read_parquet('{source}')"
                "), source_data AS ("
                f"SELECT *, ROW_NUMBER() OVER () AS {quoted_row_helper} "
                "FROM raw_source"
                ")"
            )
        cte_parts = [source_cte, f"transformed AS ({transformed})"]
        current_relation = "transformed"
        if duplicate_method in {
            "duplicate_keep_first",
            "duplicate_keep_last",
            "duplicate_remove_all",
        }:
            duplicate_filter = self._duplicate_filter(
                duplicate_method,
                projected_columns,
                quoted_row_helper,
            )
            cte_parts.append(
                "full_row_deduplicated AS ("
                f"SELECT * FROM {current_relation} "
                f"QUALIFY {duplicate_filter}"
                ")"
            )
            current_relation = "full_row_deduplicated"
        if key_duplicate_method and key_columns:
            key_partition = ", ".join(self._quote(column) for column in key_columns)
            key_filter = self._duplicate_filter(
                key_duplicate_method.replace("key_", "duplicate_"),
                key_partition,
                quoted_row_helper,
            )
            missing_key_filter = " OR ".join(
                self._blank_value_expression(
                    column,
                    sheet.dtypes.get(column, ""),
                )
                for column in key_columns
            )
            cte_parts.append(
                "key_deduplicated AS ("
                f"SELECT * FROM {current_relation} "
                f"QUALIFY ({missing_key_filter}) OR ({key_filter})"
                ")"
            )
            current_relation = "key_deduplicated"
        final_select = (
            f"SELECT {projected_columns} FROM {current_relation} "
            f"ORDER BY {quoted_row_helper}"
        )
        query = (
            "COPY ("
            f"WITH {', '.join(cte_parts)} "
            f"{final_select}"
            ") "
            f"TO '{target}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        connection = self._connect()
        try:
            self._check_cancel(cancel_callback)
            self._execute(connection, query)
            self._check_cancel(cancel_callback)
        finally:
            self._clear_active_connection(connection)
            connection.close()

    @staticmethod
    def _connect() -> duckdb.DuckDBPyConnection:
        settings.DUCKDB_TEMP_DIR.mkdir(parents=True, exist_ok=True)
        connection = duckdb.connect()
        connection.execute(f"SET threads={max(1, settings.DUCKDB_THREADS)}")
        connection.execute(f"SET memory_limit='{settings.DUCKDB_MEMORY_LIMIT}'")
        temp_dir = str(settings.DUCKDB_TEMP_DIR).replace("'", "''")
        connection.execute(f"SET temp_directory='{temp_dir}'")
        connection.execute(
            f"SET max_temp_directory_size='{settings.DUCKDB_MAX_TEMP_SIZE}'"
        )
        connection.execute("SET preserve_insertion_order=true")
        return connection

    def _execute(
        self,
        connection: duckdb.DuckDBPyConnection,
        query: str,
        parameters: list[Any] | None = None,
    ):
        self._check_cancel()
        with self._connection_lock:
            self._active_connection = connection
        try:
            return connection.execute(query, parameters or [])
        except Exception as exc:
            if self._cancelled.is_set():
                raise ProcessingCancelled("Cleaning cancelled.") from exc
            raise
        finally:
            self._clear_active_connection(connection)

    def _clear_active_connection(
        self,
        connection: duckdb.DuckDBPyConnection,
    ) -> None:
        with self._connection_lock:
            if self._active_connection is connection:
                self._active_connection = None

    @staticmethod
    def _quote(value: str) -> str:
        return '"' + str(value).replace('"', '""') + '"'

    @staticmethod
    def _sql_string(value: str) -> str:
        return str(value).replace("'", "''")

    @staticmethod
    def _is_text_dtype(dtype: str) -> bool:
        lowered = str(dtype).lower()
        return any(token in lowered for token in ("object", "string", "str"))

    @staticmethod
    def _is_numeric_dtype(dtype: str) -> bool:
        lowered = str(dtype).lower()
        return any(
            token in lowered
            for token in ("int", "float", "double", "decimal", "number")
        )

    @staticmethod
    def _numeric_cast_expression(quoted_column: str) -> str:
        return (
            "TRY_CAST(REPLACE(TRIM(CAST("
            f"{quoted_column} AS VARCHAR)), ',', '') AS DOUBLE)"
        )

    @staticmethod
    def _numeric_replacement_expression(
        method: str,
        numeric_expression: str,
    ) -> str:
        if method == "invalid_to_null":
            return "NULL"
        if method == "invalid_zero":
            return "0"
        if method in {"invalid_mean", "invalid_median"}:
            aggregate = "AVG" if method == "invalid_mean" else "MEDIAN"
            return (
                f"(SELECT {aggregate}({numeric_expression}) FROM source_data "
                f"WHERE {numeric_expression} IS NOT NULL)"
            )
        if method == "invalid_mode":
            return (
                f"(SELECT {numeric_expression} FROM source_data "
                f"WHERE {numeric_expression} IS NOT NULL "
                f"GROUP BY {numeric_expression} "
                f"ORDER BY COUNT(*) DESC, {numeric_expression} ASC LIMIT 1)"
            )
        raise ValueError(f"Unsupported invalid numeric treatment: {method}")

    @staticmethod
    def _missing_replacement_expression(
        method: str | None,
        quoted_column: str,
        *,
        numeric_expression: str,
        numeric: bool,
    ) -> str:
        if not method or method == "drop_rows":
            return "NULL"
        if method == "fill_zero" and numeric:
            return "0"
        if method in {"fill_mean", "fill_median"} and numeric:
            aggregate = "AVG" if method == "fill_mean" else "MEDIAN"
            return (
                f"(SELECT {aggregate}({numeric_expression}) FROM source_data "
                f"WHERE {numeric_expression} IS NOT NULL)"
            )
        if method == "fill_mode":
            mode_expression = numeric_expression if numeric else quoted_column
            return (
                f"(SELECT {mode_expression} FROM source_data "
                f"WHERE {mode_expression} IS NOT NULL "
                f"GROUP BY {mode_expression} "
                f"ORDER BY COUNT(*) DESC, CAST({mode_expression} AS VARCHAR) ASC "
                "LIMIT 1)"
            )
        return "NULL"

    @classmethod
    def _blank_value_expression(cls, column: str, dtype: str) -> str:
        quoted = cls._quote(column)
        if cls._is_text_dtype(dtype):
            return (
                f"({quoted} IS NULL OR "
                f"TRIM(CAST({quoted} AS VARCHAR)) = '')"
            )
        return f"{quoted} IS NULL"

    @staticmethod
    def _duplicate_filter(
        method: str,
        partition: str,
        row_helper: str,
    ) -> str:
        if method == "duplicate_keep_first":
            return (
                f"ROW_NUMBER() OVER (PARTITION BY {partition} "
                f"ORDER BY {row_helper} ASC) = 1"
            )
        if method == "duplicate_keep_last":
            return (
                f"ROW_NUMBER() OVER (PARTITION BY {partition} "
                f"ORDER BY {row_helper} DESC) = 1"
            )
        if method == "duplicate_remove_all":
            return f"COUNT(*) OVER (PARTITION BY {partition}) = 1"
        raise ValueError(f"Unsupported duplicate treatment: {method}")

    @staticmethod
    def _validate_selections(
        file_meta: FileMeta,
        selections: dict[str, Any],
    ) -> None:
        allowed_column_methods = {
            "missing_values": {
                "drop_rows",
                "fill_zero",
                "fill_mean",
                "fill_median",
                "fill_mode",
            },
            "mixed_numeric_values": {
                "invalid_to_null",
                "invalid_zero",
                "invalid_mean",
                "invalid_median",
                "invalid_mode",
                "drop_invalid_rows",
                "keep_text",
            },
        }
        for issue_id in ("missing_values", "mixed_numeric_values"):
            config = selections.get(issue_id)
            if not config:
                continue
            if isinstance(config, str):
                if config not in allowed_column_methods[issue_id]:
                    raise ValueError(
                        f"Unsupported {issue_id} treatment: {config}"
                    )
                continue
            if not isinstance(config, dict) or not isinstance(
                config.get("columns"),
                dict,
            ):
                raise ValueError(f"{issue_id} column configuration is invalid.")
            available = {
                sheet.sheet_name: set(sheet.columns)
                for sheet in file_meta.sheets
            }
            configured_count = 0
            for sheet_name, methods in config["columns"].items():
                if sheet_name not in available or not isinstance(methods, dict):
                    raise ValueError("Selected columns are no longer available.")
                unknown = set(methods) - available[sheet_name]
                if unknown:
                    raise ValueError(
                        f"Unknown column(s) in {sheet_name}: "
                        + ", ".join(sorted(unknown))
                    )
                invalid_methods = {
                    str(method)
                    for method in methods.values()
                    if method not in allowed_column_methods[issue_id]
                }
                if invalid_methods:
                    raise ValueError(
                        f"Unsupported {issue_id} treatment(s): "
                        + ", ".join(sorted(invalid_methods))
                    )
                configured_count += len(methods)
                if issue_id == "mixed_numeric_values":
                    sheet = next(
                        item
                        for item in file_meta.sheets
                        if item.sheet_name == sheet_name
                    )
                    not_mixed = [
                        column
                        for column in methods
                        if not (
                            sheet.type_profiles.get(column, {}).get(
                                "inferred_type"
                            )
                            == "numeric"
                            and int(
                                sheet.type_profiles.get(column, {}).get(
                                    "invalid_count",
                                    0,
                                )
                            )
                            > 0
                        )
                    ]
                    if not_mixed:
                        raise ValueError(
                            f"Column(s) are no longer mixed numeric fields in "
                            f"{sheet_name}: "
                            + ", ".join(sorted(not_mixed))
                        )
            if configured_count == 0:
                raise ValueError(
                    f"Choose at least one column for {issue_id}."
                )
        sheets_by_name = {
            sheet.sheet_name: sheet
            for sheet in file_meta.sheets
        }
        missing_config = selections.get("missing_values")
        mixed_config = selections.get("mixed_numeric_values")
        if isinstance(missing_config, dict):
            mixed_columns = (
                mixed_config.get("columns", {})
                if isinstance(mixed_config, dict)
                else {}
            )
            for sheet_name, methods in missing_config.get(
                "columns",
                {},
            ).items():
                sheet = sheets_by_name[sheet_name]
                for column, method in methods.items():
                    if method not in {"fill_zero", "fill_mean", "fill_median"}:
                        continue
                    if CleaningService._is_numeric_dtype(
                        sheet.dtypes.get(column, "")
                    ):
                        continue
                    inferred_numeric = (
                        sheet.type_profiles.get(column, {}).get("inferred_type")
                        == "numeric"
                    )
                    mixed_method = mixed_columns.get(sheet_name, {}).get(column)
                    if (
                        not inferred_numeric
                        or not mixed_method
                        or mixed_method == "keep_text"
                    ):
                        raise ValueError(
                            f"{sheet_name}.{column} must first use a numeric "
                            "conversion treatment before numeric missing-value "
                            "filling can be applied."
                        )
        simple_allowed = {
            "blank_rows": {"drop_blank_rows"},
            "empty_columns": {"drop_empty_columns"},
            "duplicate_rows": {
                "duplicate_keep_first",
                "duplicate_keep_last",
                "duplicate_remove_all",
            },
        }
        for issue_id, allowed in simple_allowed.items():
            method = selections.get(issue_id)
            if method and method not in allowed:
                raise ValueError(
                    f"Unsupported {issue_id} treatment: {method}"
                )
        key_config = selections.get("key_duplicates")
        if not key_config:
            return
        if not isinstance(key_config, dict):
            raise ValueError("Key duplicate configuration is invalid.")
        method = key_config.get("method")
        if method not in {"key_keep_first", "key_keep_last", "key_remove_all"}:
            raise ValueError("Choose how duplicate key values should be handled.")
        configured = key_config.get("columns")
        if not isinstance(configured, dict):
            raise ValueError("Choose at least one key column.")
        available = {
            sheet.sheet_name: set(sheet.columns)
            for sheet in file_meta.sheets
        }
        selected_count = 0
        for sheet_name, columns in configured.items():
            if sheet_name not in available or not isinstance(columns, list):
                raise ValueError("The selected key columns are no longer available.")
            unknown = set(columns) - available[sheet_name]
            if unknown:
                raise ValueError(
                    f"Unknown key column(s) in {sheet_name}: "
                    + ", ".join(sorted(unknown))
                )
            selected_count += len(columns)
        if selected_count == 0:
            raise ValueError("Choose at least one key column.")

    def _check_cancel(
        self,
        callback: Callable[[], bool] | None = None,
    ) -> None:
        if self._cancelled.is_set() or (callback and callback()):
            raise ProcessingCancelled("Cleaning cancelled.")

    @staticmethod
    def _safe_sheet_name(name: str, index: int) -> str:
        cleaned = re.sub(r"[\[\]:*?/\\]", "_", str(name)).strip()[:31]
        return cleaned or f"Sheet{index}"

    def _excel_value(self, value: Any) -> Any:
        if value is None or pd.isna(value):
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if hasattr(value, "to_pydatetime"):
            value = value.to_pydatetime()
        if isinstance(value, str):
            value = ILLEGAL_CHARACTERS_RE.sub("", value)
            if len(value) > self.MAX_EXCEL_TEXT:
                value = value[: self.MAX_EXCEL_TEXT - 3] + "..."
            if value.startswith(self.FORMULA_PREFIXES):
                value = "'" + value
        return value

    @staticmethod
    def _same_path(first: Path, second: Path) -> bool:
        try:
            return first.resolve(strict=False) == second.resolve(strict=False)
        except OSError:
            return str(first.absolute()).casefold() == str(second.absolute()).casefold()

    @staticmethod
    def _column_methods_for_sheet(
        configuration: Any,
        sheet: SheetMeta,
    ) -> dict[str, str]:
        if isinstance(configuration, str):
            return {
                column: configuration
                for column in sheet.columns
                if not (
                    configuration == "drop_rows"
                    and sheet.rows
                    and sheet.null_counts.get(column, 0) >= sheet.rows
                )
            }
        if not isinstance(configuration, dict):
            return {}
        columns = configuration.get("columns", {})
        methods = columns.get(sheet.sheet_name, {}) if isinstance(columns, dict) else {}
        return {
            str(column): str(method)
            for column, method in methods.items()
            if column in sheet.columns and method
        }

    @staticmethod
    def _ensure_cleaning_disk_space(
        file_meta: FileMeta,
        destination: Path,
    ) -> None:
        source_bytes = max(
            int(file_meta.file_size_kb * 1024),
            sum(
                Path(sheet.cache_path).stat().st_size
                for sheet in file_meta.sheets
                if sheet.cache_path and Path(sheet.cache_path).exists()
            ),
        )
        required = max(
            settings.CLEANING_MIN_FREE_DISK_BYTES,
            int(source_bytes * settings.CLEANING_SOURCE_SIZE_MULTIPLIER),
        )
        locations = {
            settings.DUCKDB_TEMP_DIR.resolve(),
            destination.parent.resolve(),
        }
        for location in locations:
            location.mkdir(parents=True, exist_ok=True)
            free = shutil.disk_usage(location).free
            logger.info(
                "Cleaning disk check path=%s free=%s required=%s",
                location,
                free,
                required,
            )
            if free < required:
                raise OSError(
                    f"Insufficient disk space for cleaning in {location}. "
                    f"At least {required / (1024 ** 3):.1f} GiB free is required."
                )
