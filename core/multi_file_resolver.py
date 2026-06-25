"""Cross-dataset relationship profiling for planning and validation."""

from __future__ import annotations

import re
from itertools import combinations
from typing import Any

import duckdb

from core.preprocessor import FileMeta, SheetMeta


class MultiFileResolver:
    """Find evidence-backed candidate joins between imported sheets."""

    def resolve(self, files: list[FileMeta]) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []
        sheets = [
            (file_meta, sheet)
            for file_meta in files
            for sheet in file_meta.sheets
        ]
        for (left_file, left_sheet), (right_file, right_sheet) in combinations(
            sheets,
            2,
        ):
            if left_file.runtime_key == right_file.runtime_key:
                continue
            candidates.extend(
                self._sheet_candidates(
                    left_file,
                    left_sheet,
                    right_file,
                    right_sheet,
                )
            )
        candidates.sort(
            key=lambda item: float(item.get("confidence", 0)),
            reverse=True,
        )
        return {"candidate_joins": candidates[:30]}

    def _sheet_candidates(
        self,
        left_file: FileMeta,
        left_sheet: SheetMeta,
        right_file: FileMeta,
        right_sheet: SheetMeta,
    ) -> list[dict[str, Any]]:
        right_by_normalized = {
            self._normalize(column): column
            for column in right_sheet.columns
        }
        results: list[dict[str, Any]] = []
        for left_column in left_sheet.columns:
            normalized = self._normalize(left_column)
            right_column = right_by_normalized.get(normalized)
            if not right_column:
                continue
            if not self._compatible_types(
                left_sheet.dtypes.get(left_column, ""),
                right_sheet.dtypes.get(right_column, ""),
            ):
                continue

            overlap = self._value_overlap(
                left_sheet,
                left_column,
                right_sheet,
                right_column,
            )
            left_unique = left_sheet.unique_rates.get(left_column, 0) >= 0.98
            right_unique = right_sheet.unique_rates.get(right_column, 0) >= 0.98
            relationship = self._relationship(left_unique, right_unique)
            confidence = 0.55 + min(0.4, overlap * 0.4)
            if left_unique or right_unique:
                confidence += 0.05

            results.append(
                {
                    "left": {
                        "dataset_id": left_file.runtime_key,
                        "sheet_id": left_sheet.sheet_id or left_sheet.sheet_name,
                        "column": left_column,
                    },
                    "right": {
                        "dataset_id": right_file.runtime_key,
                        "sheet_id": right_sheet.sheet_id or right_sheet.sheet_name,
                        "column": right_column,
                    },
                    "value_overlap": round(overlap, 4),
                    "relationship": relationship,
                    "confidence": round(min(confidence, 1.0), 4),
                    "requires_confirmation": (
                        relationship == "many_to_many" or overlap < 0.2
                    ),
                }
            )
        return results

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value).lower())

    @staticmethod
    def _compatible_types(left: str, right: str) -> bool:
        numeric_tokens = ("int", "float", "decimal")
        left_numeric = any(token in left.lower() for token in numeric_tokens)
        right_numeric = any(token in right.lower() for token in numeric_tokens)
        return left_numeric == right_numeric

    @staticmethod
    def _relationship(left_unique: bool, right_unique: bool) -> str:
        if left_unique and right_unique:
            return "one_to_one"
        if left_unique:
            return "one_to_many"
        if right_unique:
            return "many_to_one"
        return "many_to_many"

    @staticmethod
    def _value_overlap(
        left_sheet: SheetMeta,
        left_column: str,
        right_sheet: SheetMeta,
        right_column: str,
    ) -> float:
        if not left_sheet.cache_path or not right_sheet.cache_path:
            return 0.0
        try:
            connection = duckdb.connect()
            try:
                query = """
                    WITH left_values AS (
                        SELECT DISTINCT CAST({left_col} AS VARCHAR) AS value
                        FROM read_parquet(?)
                        WHERE {left_col} IS NOT NULL
                        LIMIT 2000
                    ),
                    right_values AS (
                        SELECT DISTINCT CAST({right_col} AS VARCHAR) AS value
                        FROM read_parquet(?)
                        WHERE {right_col} IS NOT NULL
                        LIMIT 2000
                    )
                    SELECT
                        COUNT(*) FILTER (
                            WHERE r.value IS NOT NULL
                        )::DOUBLE
                        / GREATEST(COUNT(*), 1)
                    FROM left_values l
                    LEFT JOIN right_values r USING (value)
                """.format(
                    left_col=MultiFileResolver._quote(left_column),
                    right_col=MultiFileResolver._quote(right_column),
                )
                value = connection.execute(
                    query,
                    [left_sheet.cache_path, right_sheet.cache_path],
                ).fetchone()[0]
                return float(value or 0)
            finally:
                connection.close()
        except Exception:
            return 0.0

    @staticmethod
    def _quote(identifier: str) -> str:
        return '"' + str(identifier).replace('"', '""') + '"'

    def get_join_suggestion(self, files: list[FileMeta]) -> str:
        candidates = self.resolve(files).get("candidate_joins", [])
        if not candidates:
            return ""
        lines = ["Potential cross-dataset relationships:"]
        for candidate in candidates[:5]:
            left = candidate["left"]
            right = candidate["right"]
            lines.append(
                "- "
                f"{left['dataset_id']}.{left['column']} -> "
                f"{right['dataset_id']}.{right['column']} "
                f"({candidate['relationship']}, "
                f"confidence={candidate['confidence']})"
            )
        return "\n".join(lines)
