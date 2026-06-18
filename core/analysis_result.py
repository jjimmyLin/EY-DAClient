"""Structured analysis results shared by generated code, executor, and UI."""

from __future__ import annotations

import base64
import io
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        try:
            return _json_value(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    return str(value)


@dataclass
class MetricResult:
    label: str
    value: Any
    unit: str = ""
    detail: str = ""


@dataclass
class TableResult:
    title: str
    columns: list[str]
    rows: list[list[Any]]
    total_rows: int
    truncated: bool = False


@dataclass
class ChartResult:
    title: str
    image_base64: str
    caption: str = ""


@dataclass
class InsightResult:
    title: str
    detail: str
    kind: str = "insight"


@dataclass
class AnalysisResult:
    summary: str = ""
    metrics: list[MetricResult] = field(default_factory=list)
    tables: list[TableResult] = field(default_factory=list)
    charts: list[ChartResult] = field(default_factory=list)
    insights: list[InsightResult] = field(default_factory=list)
    raw_output: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "AnalysisResult":
        payload = payload or {}
        return cls(
            summary=str(payload.get("summary") or ""),
            metrics=[
                MetricResult(**item)
                for item in payload.get("metrics", [])
                if isinstance(item, dict)
            ],
            tables=[
                TableResult(**item)
                for item in payload.get("tables", [])
                if isinstance(item, dict)
            ],
            charts=[
                ChartResult(**item)
                for item in payload.get("charts", [])
                if isinstance(item, dict)
            ],
            insights=[
                InsightResult(**item)
                for item in payload.get("insights", [])
                if isinstance(item, dict)
            ],
            raw_output=str(payload.get("raw_output") or ""),
        )


class ResultCollector:
    """Small SDK exposed to generated analysis code as ``result``."""

    MAX_TABLE_ROWS = 200
    MAX_TABLE_COLUMNS = 30

    def __init__(self) -> None:
        self._result = AnalysisResult()
        self._captured_figures: set[int] = set()

    def set_summary(self, text: Any) -> None:
        self._result.summary = str(text).strip()

    def add_metric(
        self,
        label: Any,
        value: Any,
        unit: Any = "",
        detail: Any = "",
    ) -> None:
        self._result.metrics.append(
            MetricResult(
                label=str(label),
                value=_json_value(value),
                unit=str(unit),
                detail=str(detail),
            )
        )

    def add_table(
        self,
        title: Any,
        data: Any = None,
        *,
        dataframe: Any = None,
    ) -> None:
        if data is None:
            data = dataframe
        if data is None:
            raise TypeError("add_table() requires data or dataframe")

        if hasattr(data, "columns") and hasattr(data, "iloc"):
            total_rows = int(len(data))
            limited = data.iloc[
                : self.MAX_TABLE_ROWS,
                : self.MAX_TABLE_COLUMNS,
            ]
            columns = [str(column) for column in limited.columns]
            rows = [
                [_json_value(value) for value in row]
                for row in limited.itertuples(index=False, name=None)
            ]
            truncated = (
                total_rows > self.MAX_TABLE_ROWS
                or len(data.columns) > self.MAX_TABLE_COLUMNS
            )
        elif hasattr(data, "index") and hasattr(data, "tolist"):
            values = list(data.tolist())
            total_rows = len(values)
            columns = [str(getattr(data, "name", None) or "Value")]
            rows = [[_json_value(value)] for value in values[: self.MAX_TABLE_ROWS]]
            truncated = total_rows > self.MAX_TABLE_ROWS
        else:
            raw_rows = list(data or [])
            total_rows = len(raw_rows)
            if raw_rows and isinstance(raw_rows[0], dict):
                source_columns = list(
                    dict.fromkeys(
                        key
                        for row in raw_rows
                        if isinstance(row, dict)
                        for key in row
                    )
                )[: self.MAX_TABLE_COLUMNS]
                columns = [str(column) for column in source_columns]
                rows = [
                    [_json_value(row.get(column)) for column in source_columns]
                    for row in raw_rows[: self.MAX_TABLE_ROWS]
                    if isinstance(row, dict)
                ]
            else:
                rows = []
                for row in raw_rows[: self.MAX_TABLE_ROWS]:
                    values = (
                        list(row)
                        if isinstance(row, (list, tuple))
                        else [row]
                    )
                    rows.append([_json_value(value) for value in values])
                width = max((len(row) for row in rows), default=0)
                columns = [f"Column {index + 1}" for index in range(width)]
            width = max((len(row) for row in rows), default=0)
            truncated = total_rows > self.MAX_TABLE_ROWS

        self._result.tables.append(
            TableResult(
                title=str(title),
                columns=columns,
                rows=rows,
                total_rows=total_rows,
                truncated=truncated,
            )
        )

    def add_chart(
        self,
        title: Any,
        figure: Any = None,
        caption: Any = "",
        *,
        matplotlib_figure: Any = None,
    ) -> None:
        if figure is None:
            figure = matplotlib_figure
        if figure is None:
            import matplotlib.pyplot as plt

            figure = plt.gcf()
        figure_number = getattr(figure, "number", None)
        image = io.BytesIO()
        figure.savefig(
            image,
            format="png",
            dpi=144,
            bbox_inches="tight",
            facecolor="white",
        )
        self._result.charts.append(
            ChartResult(
                title=str(title),
                image_base64=base64.b64encode(image.getvalue()).decode("ascii"),
                caption=str(caption),
            )
        )
        if isinstance(figure_number, int):
            self._captured_figures.add(figure_number)

    def add_insight(self, title: Any, detail: Any) -> None:
        self._result.insights.append(
            InsightResult(str(title), str(detail), "insight")
        )

    def add_warning(self, title: Any, detail: Any) -> None:
        self._result.insights.append(
            InsightResult(str(title), str(detail), "warning")
        )

    def capture_open_figures(self, pyplot: Any) -> None:
        for figure_number in pyplot.get_fignums():
            if figure_number in self._captured_figures:
                continue
            self.add_chart(
                f"Chart {len(self._result.charts) + 1}",
                pyplot.figure(figure_number),
            )

    def write_json(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self._result.to_dict(), ensure_ascii=False),
            encoding="utf-8",
        )
