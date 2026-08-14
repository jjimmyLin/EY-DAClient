"""Deterministic structural checks that run before remote analysis."""

from __future__ import annotations

import csv
from dataclasses import dataclass

from core.preprocessor import FileMeta


@dataclass(frozen=True)
class StructuralDataIssue:
    """A dataset shape that cannot safely be interpreted as tabular data."""

    code: str
    dataset_id: str
    sheet_id: str
    message: str


def find_structural_data_issue(
    files_meta: list[FileMeta],
) -> StructuralDataIssue | None:
    """Detect a delimited record stream stored inside one worksheet column.

    The check is intentionally conservative: the header and at least two sample
    values must parse into the same number of fields. This avoids rejecting
    legitimate free-text columns that merely contain an occasional pipe.
    """

    for file_meta in files_meta:
        for sheet in file_meta.sheets:
            if sheet.cols != 1 or len(sheet.columns) != 1:
                continue
            column = str(sheet.columns[0])
            header_fields = _pipe_fields(column)
            if len(header_fields) < 6:
                continue

            sample_counts = []
            for row in sheet.head_sample:
                value = row.get(column)
                if value is None or not str(value).strip():
                    continue
                sample_counts.append(len(_pipe_fields(str(value))))

            if len(sample_counts) < 2:
                continue
            matching = sum(
                count == len(header_fields)
                for count in sample_counts
            )
            if matching / len(sample_counts) < 0.8:
                continue

            dataset_id = file_meta.runtime_key
            sheet_id = sheet.sheet_id or sheet.sheet_name
            return StructuralDataIssue(
                code="single_column_delimited_records",
                dataset_id=dataset_id,
                sheet_id=sheet_id,
                message=(
                    f"Dataset {dataset_id}/{sheet_id} contains "
                    f"{len(header_fields)} pipe-delimited fields stored inside "
                    "one worksheet column. The data must be split into real "
                    "columns before analysis; no Dify workflow was started."
                ),
            )
    return None


def _pipe_fields(value: str) -> list[str]:
    try:
        return next(
            csv.reader(
                [value],
                delimiter="|",
                quotechar='"',
                strict=True,
            )
        )
    except (csv.Error, StopIteration):
        return [value]
