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
    if isinstance(value, dict):
        return {
            str(key): _json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
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
class AnswerResult:
    answer_id: str
    question: str
    answer: str
    supporting_metrics: list[str] = field(default_factory=list)
    supporting_tables: list[str] = field(default_factory=list)
    supporting_charts: list[str] = field(default_factory=list)
    supporting_insights: list[str] = field(default_factory=list)
    confidence_or_notes: str = ""


@dataclass
class AnalysisResult:
    summary: str = ""
    answers: list[AnswerResult] = field(default_factory=list)
    metrics: list[MetricResult] = field(default_factory=list)
    tables: list[TableResult] = field(default_factory=list)
    charts: list[ChartResult] = field(default_factory=list)
    insights: list[InsightResult] = field(default_factory=list)
    audit: list[dict[str, Any]] = field(default_factory=list)
    completed_requirements: list[str] = field(default_factory=list)
    raw_output: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def answer_result(self, answer_index: int) -> "AnalysisResult":
        """Return a focused result containing one answer and its references."""
        answer = self.answers[answer_index]

        def selected(items: list[Any], names: list[str], attr: str) -> list[Any]:
            wanted = {str(name) for name in names if str(name).strip()}
            if not wanted:
                return []
            return [
                item
                for item in items
                if str(getattr(item, attr, "")) in wanted
            ]

        return AnalysisResult(
            summary="",
            answers=[answer],
            metrics=selected(
                self.metrics,
                answer.supporting_metrics,
                "label",
            ),
            tables=selected(
                self.tables,
                answer.supporting_tables,
                "title",
            ),
            charts=selected(
                self.charts,
                answer.supporting_charts,
                "title",
            ),
            insights=selected(
                self.insights,
                answer.supporting_insights,
                "title",
            ),
            audit=list(self.audit),
            completed_requirements=[
                item
                for item in self.completed_requirements
                if str(item) == answer.answer_id
            ],
            raw_output="",
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "AnalysisResult":
        payload = payload or {}
        return cls(
            summary=str(payload.get("summary") or ""),
            answers=[
                AnswerResult(
                    answer_id=str(
                        item.get("answer_id")
                        or item.get("id")
                        or f"answer_{index}"
                    ),
                    question=str(item.get("question") or ""),
                    answer=str(item.get("answer") or item.get("summary") or ""),
                    supporting_metrics=[
                        str(value)
                        for value in item.get("supporting_metrics", []) or []
                    ],
                    supporting_tables=[
                        str(value)
                        for value in item.get("supporting_tables", []) or []
                    ],
                    supporting_charts=[
                        str(value)
                        for value in item.get("supporting_charts", []) or []
                    ],
                    supporting_insights=[
                        str(value)
                        for value in item.get("supporting_insights", []) or []
                    ],
                    confidence_or_notes=str(
                        item.get("confidence_or_notes")
                        or item.get("notes")
                        or ""
                    ),
                )
                for index, item in enumerate(
                    payload.get("answers", []) or [],
                    start=1,
                )
                if isinstance(item, dict)
            ],
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
            audit=[
                item
                for item in payload.get("audit", [])
                if isinstance(item, dict)
            ],
            completed_requirements=[
                str(item)
                for item in payload.get("completed_requirements", [])
                if str(item).strip()
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

    def add_answer(
        self,
        answer_id: Any,
        question: Any,
        answer: Any,
        *,
        supporting_metrics: Any = None,
        supporting_tables: Any = None,
        supporting_charts: Any = None,
        supporting_insights: Any = None,
        confidence_or_notes: Any = "",
        notes: Any = "",
    ) -> None:
        self._result.answers.append(
            AnswerResult(
                answer_id=str(answer_id).strip(),
                question=str(question).strip(),
                answer=str(answer).strip(),
                supporting_metrics=[
                    str(value)
                    for value in supporting_metrics or []
                    if str(value).strip()
                ],
                supporting_tables=[
                    str(value)
                    for value in supporting_tables or []
                    if str(value).strip()
                ],
                supporting_charts=[
                    str(value)
                    for value in supporting_charts or []
                    if str(value).strip()
                ],
                supporting_insights=[
                    str(value)
                    for value in supporting_insights or []
                    if str(value).strip()
                ],
                confidence_or_notes=str(
                    confidence_or_notes or notes or ""
                ).strip(),
            )
        )

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

    def mark_requirement(self, requirement_id: Any) -> None:
        value = str(requirement_id).strip()
        if value and value not in self._result.completed_requirements:
            self._result.completed_requirements.append(value)

    def add_audit(self, record: dict[str, Any]) -> None:
        if isinstance(record, dict):
            self._result.audit.append(
                {
                    str(key): _json_value(value)
                    for key, value in record.items()
                }
            )

    def extend_audit(self, records: Any) -> None:
        for record in records or []:
            self.add_audit(record)

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
