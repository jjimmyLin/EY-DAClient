from __future__ import annotations

import pandas as pd

import dify.workflow as workflow_module
from core.analysis_contract import AnalysisPlanValidator
from core.executor import Executor
from core.preprocessor import Preprocessor
from config.settings import settings
from dify.workflow import AnalysisWorkflow


def _write(path, frame, sheet_name="Data"):
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_excel(path, index=False, sheet_name=sheet_name)
    return Preprocessor().process(str(path))


def _source(file_meta, columns):
    sheet = file_meta.sheets[0]
    return {
        "dataset_id": file_meta.runtime_key,
        "sheet_id": sheet.sheet_id,
        "columns": columns,
    }


def _join(left, right, relationship="one_to_one"):
    return {
        "left": {
            "dataset_id": left.runtime_key,
            "sheet_id": left.sheets[0].sheet_id,
            "column": "id",
        },
        "right": {
            "dataset_id": right.runtime_key,
            "sheet_id": right.sheets[0].sheet_id,
            "column": "id",
        },
        "how": "inner",
        "expected_relationship": relationship,
        "many_to_many_confirmed": False,
    }


def _plan(files, formula):
    return {
        "task_summary": "Cross-dataset calculation",
        "requirements": [
            {
                "id": "R1",
                "objective": "Calculate the combined metric",
                "sources": [
                    _source(files[0], ["id", "a"]),
                    _source(files[1], ["id", "b"]),
                    *(
                        [_source(files[2], ["id", "c"])]
                        if len(files) > 2
                        else []
                    ),
                ],
                "joins": [
                    _join(files[0], files[1]),
                    *(
                        [_join(files[0], files[2])]
                        if len(files) > 2
                        else []
                    ),
                ],
                "grain": "id",
                "formula": formula,
                "output_type": "table",
            }
        ],
        "warnings": [],
        "clarification_required": False,
        "clarification_question": "",
        "clarification_options": [],
    }


def test_same_named_files_receive_distinct_runtime_ids(tmp_path):
    first = _write(
        tmp_path / "one" / "same.xlsx",
        pd.DataFrame({"id": [1], "value": [10]}),
    )
    second = _write(
        tmp_path / "two" / "same.xlsx",
        pd.DataFrame({"id": [1], "value": [20]}),
    )

    assert first.runtime_key != second.runtime_key
    manifest = Executor._build_manifest([first, second])
    assert manifest[0]["aliases"] == []
    assert manifest[1]["aliases"] == []


def test_large_xlsx_streaming_path_creates_parquet_cache(
    tmp_path,
    monkeypatch,
):
    workbook = tmp_path / "streamed.xlsx"
    pd.DataFrame(
        {"id": range(100), "value": range(100)}
    ).to_excel(workbook, index=False, sheet_name="Data")
    monkeypatch.setattr(settings, "LARGE_EXCEL_MB", 0)

    file_meta = Preprocessor().process(str(workbook))

    sheet = file_meta.sheets[0]
    assert sheet.rows == 100
    assert sheet.columns == ["id", "value"]
    assert sheet.cache_path.endswith(".parquet")
    assert sheet.sample_cache_path.endswith(".sample.parquet")
    assert pd.read_parquet(sheet.cache_path)["value"].sum() == 4950


def test_two_dataset_join_executes_with_audit(tmp_path):
    first = _write(
        tmp_path / "a.xlsx",
        pd.DataFrame({"id": [1, 2], "a": [10, 20]}),
    )
    second = _write(
        tmp_path / "b.xlsx",
        pd.DataFrame({"id": [1, 2], "b": [3, 4]}),
    )
    plan = _plan([first, second], "a + b")
    code = f"""
ANALYSIS_SPEC = {{"requirements": ["R1"], "datasets": ["{first.runtime_key}", "{second.runtime_key}"]}}
a = data.get("{first.runtime_key}", "{first.sheets[0].sheet_id}", columns=["id", "a"])
b = data.get("{second.runtime_key}", "{second.sheets[0].sheet_id}", columns=["id", "b"])
joined = data.merge(a, b, left_name="{first.runtime_key}", right_name="{second.runtime_key}", on="id", how="inner")
joined["combined"] = joined["a"] + joined["b"]
result.set_summary("Combined two datasets.")
result.add_table("Combined", joined)
result.mark_requirement("R1")
"""

    execution = Executor().run(
        code,
        [first, second],
        analysis_plan=plan,
    )

    assert execution.success, execution.stderr
    assert execution.analysis_result.tables[0].rows == [
        [1, 10, 3, 13],
        [2, 20, 4, 24],
    ]
    assert any(
        item.get("kind") == "join"
        for item in execution.analysis_result.audit
    )


def test_three_dataset_formula_aligns_by_business_key(tmp_path):
    first = _write(
        tmp_path / "a.xlsx",
        pd.DataFrame({"id": [2, 1], "a": [20.0, 10.0]}),
    )
    second = _write(
        tmp_path / "b.xlsx",
        pd.DataFrame({"id": [1, 2], "b": [2.0, 4.0]}),
    )
    third = _write(
        tmp_path / "c.xlsx",
        pd.DataFrame({"id": [2, 1], "c": [2.0, 4.0]}),
    )
    plan = _plan([first, second, third], "(a + b) / c")
    code = f"""
ANALYSIS_SPEC = {{"requirements": ["R1"], "datasets": ["{first.runtime_key}", "{second.runtime_key}", "{third.runtime_key}"]}}
a = data.get("{first.runtime_key}", "{first.sheets[0].sheet_id}", columns=["id", "a"])
b = data.get("{second.runtime_key}", "{second.sheets[0].sheet_id}", columns=["id", "b"])
c = data.get("{third.runtime_key}", "{third.sheets[0].sheet_id}", columns=["id", "c"])
ab = data.merge(a, b, left_name="{first.runtime_key}", right_name="{second.runtime_key}", on="id", how="inner")
abc = data.merge(ab, c, left_name="{first.runtime_key}", right_name="{third.runtime_key}", on="id", how="inner")
abc["metric"] = (abc["a"] + abc["b"]) / abc["c"]
result.set_summary("Three datasets aligned by id.")
result.add_table("Metric", abc.sort_values("id"))
result.mark_requirement("R1")
"""

    execution = Executor().run(
        code,
        [first, second, third],
        analysis_plan=plan,
    )

    assert execution.success, execution.stderr
    rows = execution.analysis_result.tables[0].rows
    assert rows[0][-1] == 3.0
    assert rows[1][-1] == 12.0


def test_duckdb_sql_joins_cached_sources_without_preloading_frames(tmp_path):
    first = _write(
        tmp_path / "a.xlsx",
        pd.DataFrame({"id": [1, 2], "a": [10, 20]}),
    )
    second = _write(
        tmp_path / "b.xlsx",
        pd.DataFrame({"id": [1, 2], "b": [3, 4]}),
    )
    plan = _plan([first, second], "sum(a + b)")
    code = f'''
ANALYSIS_SPEC = {{"requirements": ["R1"], "datasets": ["{first.runtime_key}", "{second.runtime_key}"]}}
combined = data.sql(
    "SELECT a.id, a.a + b.b AS combined FROM a JOIN b USING (id)",
    sources={{
        "a": ("{first.runtime_key}", "{first.sheets[0].sheet_id}"),
        "b": ("{second.runtime_key}", "{second.sheets[0].sheet_id}")
    }}
)
result.set_summary("DuckDB joined cached sources.")
result.add_metric("Total", combined["combined"].sum())
result.mark_requirement("R1")
'''

    execution = Executor().run(
        code,
        [first, second],
        analysis_plan=plan,
    )

    assert execution.success, execution.stderr
    assert execution.analysis_result.metrics[0].value == 37
    assert execution.analysis_result.audit[0]["kind"] == "sql"


def test_multi_dataset_plan_without_alignment_is_rejected(tmp_path):
    first = _write(
        tmp_path / "a.xlsx",
        pd.DataFrame({"id": [1], "a": [10]}),
    )
    second = _write(
        tmp_path / "b.xlsx",
        pd.DataFrame({"id": [1], "b": [2]}),
    )
    plan = _plan([first, second], "a + b")
    plan["requirements"][0]["joins"] = []

    validation = AnalysisPlanValidator().validate(plan, [first, second])

    assert not validation.is_valid
    assert "no explicit join/alignment rule" in "\n".join(validation.issues)


class _FakeClient:
    def __init__(self, code, plan):
        self.code = code
        self.plan = plan

    def generate_analysis(self, prompt, event_callback=None):
        return {"code": self.code, "plan": self.plan}


def test_prepare_uses_sample_but_full_execution_uses_all_rows(
    tmp_path,
    monkeypatch,
):
    frame = pd.DataFrame(
        {
            "id": range(6000),
            "a": range(6000),
            "b": range(6000),
        }
    )
    file_meta = _write(tmp_path / "large.xlsx", frame)
    plan = {
        "task_summary": "Count rows",
        "requirements": [
            {
                "id": "R1",
                "objective": "Count rows",
                "sources": [_source(file_meta, ["id"])],
                "joins": [],
                "grain": "dataset",
                "formula": "count rows",
                "output_type": "metric",
            }
        ],
        "warnings": [],
        "clarification_required": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    code = f"""
ANALYSIS_SPEC = {{"requirements": ["R1"], "datasets": ["{file_meta.runtime_key}"]}}
df = data.get("{file_meta.runtime_key}", "{file_meta.sheets[0].sheet_id}", columns=["id"])
result.set_summary("Counted rows.")
result.add_metric("Rows", len(df))
result.mark_requirement("R1")
"""
    monkeypatch.setattr(
        workflow_module,
        "get_client",
        lambda cancellation_token=None: _FakeClient(code, plan),
    )
    workflow = AnalysisWorkflow()

    prepared = workflow.prepare_analysis([file_meta], "Count rows")
    full = workflow.execute_with_repair(
        prepared.code,
        [file_meta],
        "Count rows",
        analysis_plan=plan,
        sample=False,
    )

    assert prepared.success
    assert prepared.preflight_only
    assert prepared.execution.analysis_result.metrics[0].value == 5000
    assert full.success
    assert full.execution.analysis_result.metrics[0].value == 6000
