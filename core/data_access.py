"""Lazy cached data access exposed to generated Python analysis code."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Mapping
from typing import Any

import duckdb
import pandas as pd

from config.settings import settings


logger = logging.getLogger(__name__)


class SheetCollection(Mapping[str, pd.DataFrame]):
    def __init__(self, catalog: "LocalDataCatalog", dataset_id: str) -> None:
        self._catalog = catalog
        self._dataset_id = dataset_id

    def __getitem__(self, sheet_key: str) -> pd.DataFrame:
        return self._catalog.get(self._dataset_id, sheet_key)

    def __iter__(self) -> Iterator[str]:
        return iter(self._catalog.sheet_keys(self._dataset_id))

    def __len__(self) -> int:
        return len(self._catalog.sheet_keys(self._dataset_id))


class DatasetCollection(Mapping[str, SheetCollection]):
    def __init__(self, catalog: "LocalDataCatalog") -> None:
        self._catalog = catalog

    def __getitem__(self, dataset_key: str) -> SheetCollection:
        dataset_id = self._catalog.resolve_dataset(dataset_key)
        return SheetCollection(self._catalog, dataset_id)

    def __iter__(self) -> Iterator[str]:
        return iter(self._catalog.dataset_keys())

    def __len__(self) -> int:
        return len(self._catalog.dataset_keys())


class LocalDataCatalog:
    """Load cached Parquet data lazily and audit access patterns."""

    def __init__(
        self,
        manifest: list[dict[str, Any]],
        *,
        sample_rows: int | None = None,
    ) -> None:
        self._manifest = {str(dataset["dataset_id"]): dataset for dataset in manifest}
        self._dataset_aliases: dict[str, str] = {}
        self._sheet_aliases: dict[str, dict[str, str]] = {}
        self._frames: dict[tuple[str, str, tuple[str, ...]], pd.DataFrame] = {}
        self._sample_rows = sample_rows
        self.audit_records: list[dict[str, Any]] = []

        for dataset_id, dataset in self._manifest.items():
            self._dataset_aliases[dataset_id] = dataset_id
            for alias in dataset.get("aliases", []):
                self._dataset_aliases[str(alias)] = dataset_id
            aliases: dict[str, str] = {}
            for sheet in dataset.get("sheets", []):
                sheet_id = str(sheet["sheet_id"])
                aliases[sheet_id] = sheet_id
                aliases[str(sheet["name"])] = sheet_id
            self._sheet_aliases[dataset_id] = aliases

        self.dfs = DatasetCollection(self)

    def resolve_dataset(self, dataset_key: str) -> str:
        key = str(dataset_key)
        if key not in self._dataset_aliases:
            raise KeyError(
                f"Unknown dataset {key!r}. Available IDs: {sorted(self._manifest)}"
            )
        return self._dataset_aliases[key]

    def resolve_sheet(self, dataset_id: str, sheet_key: str) -> str:
        aliases = self._sheet_aliases.get(dataset_id, {})
        key = str(sheet_key)
        if key not in aliases:
            raise KeyError(
                f"Unknown sheet {key!r} for {dataset_id}. "
                f"Available IDs: {sorted(set(aliases.values()))}"
            )
        return aliases[key]

    def dataset_keys(self) -> list[str]:
        return list(self._dataset_aliases)

    def sheet_keys(self, dataset_key: str) -> list[str]:
        dataset_id = self.resolve_dataset(dataset_key)
        return list(self._sheet_aliases[dataset_id])

    def get(
        self,
        dataset_key: str,
        sheet_key: str,
        *,
        columns: list[str] | None = None,
    ) -> pd.DataFrame:
        dataset_id = self.resolve_dataset(dataset_key)
        sheet_id = self.resolve_sheet(dataset_id, sheet_key)
        selected_columns = tuple(str(column) for column in (columns or []))
        cache_key = (dataset_id, sheet_id, selected_columns)
        if cache_key in self._frames:
            return self._frames[cache_key].copy()

        sheet = self._sheet_manifest(dataset_id, sheet_id)
        self._guard_large_projection(sheet, selected_columns)
        source_path = (
            sheet.get("sample_cache_path") if self._sample_rows else sheet.get("cache_path")
        ) or sheet["cache_path"]
        projection = ", ".join(self._quote(column) for column in selected_columns) if selected_columns else "*"
        limit = f" LIMIT {int(self._sample_rows)}" if self._sample_rows else ""
        connection = self._connect()
        try:
            frame = connection.execute(
                f"SELECT {projection} FROM read_parquet(?){limit}",
                [str(source_path)],
            ).df()
        finally:
            connection.close()

        self._frames[cache_key] = frame
        self.audit_records.append(
            {
                "kind": "load",
                "dataset_id": dataset_id,
                "sheet_id": sheet_id,
                "rows": len(frame),
                "sampled": bool(self._sample_rows),
                "columns": list(frame.columns),
                "guarded": bool(self._is_large_sheet(sheet)),
            }
        )
        logger.info(
            "Loaded parquet slice dataset=%s sheet=%s rows=%s cols=%s sampled=%s",
            dataset_id,
            sheet_id,
            len(frame),
            len(frame.columns),
            bool(self._sample_rows),
        )
        return frame.copy()

    def sql(
        self,
        query: str,
        *,
        sources: dict[str, tuple[str, str] | list[str]] | None = None,
        max_rows: int | None = None,
        **tables: pd.DataFrame,
    ) -> pd.DataFrame:
        self._validate_sql(query)
        connection = self._connect()
        source_names: list[str] = []
        result_limit = max_rows if max_rows is not None else settings.MAX_QUERY_RESULT_ROWS
        if result_limit <= 0:
            raise ValueError("data.sql() max_rows must be positive")

        try:
            for alias, reference in (sources or {}).items():
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias):
                    raise ValueError(f"Invalid SQL source alias: {alias!r}")
                dataset_id = self.resolve_dataset(str(reference[0]))
                sheet_id = self.resolve_sheet(dataset_id, str(reference[1]))
                sheet = self._sheet_manifest(dataset_id, sheet_id)
                source_path = (
                    sheet.get("sample_cache_path") if self._sample_rows else sheet.get("cache_path")
                ) or sheet["cache_path"]
                path = str(source_path).replace("'", "''")
                limit = f" LIMIT {int(self._sample_rows)}" if self._sample_rows else ""
                connection.execute(
                    f'CREATE VIEW "{alias}" AS SELECT * FROM read_parquet(\'{path}\'){limit}'
                )
                source_names.append(alias)
            for name, frame in tables.items():
                connection.register(name, frame)

            wrapped_query = f"SELECT * FROM ({query}) AS _analysis_result LIMIT {int(result_limit)}"
            result = connection.execute(wrapped_query).df()
            self.audit_records.append(
                {
                    "kind": "sql",
                    "tables": sorted([*tables, *source_names]),
                    "rows": len(result),
                    "sampled": bool(self._sample_rows),
                    "max_rows": int(result_limit),
                    "truncated": len(result) >= int(result_limit),
                }
            )
            logger.info(
                "Executed audited SQL tables=%s rows=%s sampled=%s limit=%s",
                sorted([*tables, *source_names]),
                len(result),
                bool(self._sample_rows),
                result_limit,
            )
            return result
        finally:
            connection.close()

    def merge(
        self,
        left: pd.DataFrame,
        right: pd.DataFrame,
        *,
        left_name: str,
        right_name: str,
        **kwargs: Any,
    ) -> pd.DataFrame:
        before_left = len(left)
        before_right = len(right)
        merged = left.merge(right, **kwargs)
        on = kwargs.get("on")
        left_on = kwargs.get("left_on", on)
        right_on = kwargs.get("right_on", on)
        relationship = self._relationship(left, right, left_on, right_on)
        self.audit_records.append(
            {
                "kind": "join",
                "left": left_name,
                "right": right_name,
                "how": kwargs.get("how", "inner"),
                "left_on": left_on,
                "right_on": right_on,
                "left_rows": before_left,
                "right_rows": before_right,
                "result_rows": len(merged),
                "row_multiplier": round(len(merged) / max(1, max(before_left, before_right)), 4),
                "relationship": relationship,
            }
        )
        return merged

    def _sheet_manifest(self, dataset_id: str, sheet_id: str) -> dict[str, Any]:
        for sheet in self._manifest[dataset_id].get("sheets", []):
            if str(sheet["sheet_id"]) == sheet_id:
                return sheet
        raise KeyError(f"Missing sheet manifest: {dataset_id}/{sheet_id}")

    def _guard_large_projection(self, sheet: dict[str, Any], selected_columns: tuple[str, ...]) -> None:
        if self._sample_rows:
            return
        if selected_columns:
            return
        if not self._is_large_sheet(sheet):
            return
        raise ValueError(
            "This sheet is large. Use data.get(..., columns=[...]) or data.sql(...) "
            "instead of loading the full sheet into Pandas."
        )

    @staticmethod
    def _is_large_sheet(sheet: dict[str, Any]) -> bool:
        rows = int(sheet.get("rows") or 0)
        columns = sheet.get("columns") or []
        return rows >= settings.BACKGROUND_ANALYSIS_ROWS and len(columns) >= settings.LARGE_DATASET_COLUMN_GUARD

    @staticmethod
    def _validate_sql(query: str) -> None:
        normalized = str(query).lower()
        banned = (
            "attach ",
            "copy ",
            "install ",
            "load ",
            "pragma ",
            "read_",
            "write_",
            "export ",
            "import ",
        )
        if ";" in normalized or any(token in normalized for token in banned):
            raise ValueError(
                "data.sql() accepts one read-only SELECT/WITH statement and does "
                "not allow external readers or database commands"
            )
        if not normalized.lstrip().startswith(("select", "with")):
            raise ValueError("data.sql() requires a SELECT or WITH query")

    @staticmethod
    def _relationship(
        left: pd.DataFrame,
        right: pd.DataFrame,
        left_on: Any,
        right_on: Any,
    ) -> str:
        if not left_on or not right_on:
            return "unknown"
        left_keys = [left_on] if isinstance(left_on, str) else list(left_on)
        right_keys = [right_on] if isinstance(right_on, str) else list(right_on)
        left_unique = not left.duplicated(left_keys).any()
        right_unique = not right.duplicated(right_keys).any()
        if left_unique and right_unique:
            return "one_to_one"
        if left_unique:
            return "one_to_many"
        if right_unique:
            return "many_to_one"
        return "many_to_many"

    @staticmethod
    def _quote(identifier: str) -> str:
        return '"' + str(identifier).replace('"', '""') + '"'

    @staticmethod
    def _connect() -> duckdb.DuckDBPyConnection:
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
