from __future__ import annotations

import pandas as pd

import dify.workflow as workflow_module
from core.analysis_contract import AnalysisPlanValidator, GeneratedCodeContractValidator
from core.executor import Executor
from core.preprocessor import Preprocessor
from config.settings import settings
from dify.workflow import AnalysisWorkflow


def _write(path, frame, sheet_name="Data"):
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_excel(path, index=False, sheet_name=sheet_name)
    return Preprocessor().process(str(path))


def _write_workbook(path, sheets):
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path) as writer:
        for sheet_name, frame in sheets.items():
            frame.to_excel(writer, index=False, sheet_name=sheet_name)
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
result.add_answer("R1", "a + b", "Combined values were calculated by id.", supporting_tables=["Combined"])
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


def test_same_schema_sheets_are_detected_as_append_group(tmp_path):
    file_meta = _write_workbook(
        tmp_path / "je.xlsx",
        {
            "JE_1": pd.DataFrame(
                {
                    "entry_id": [1, 2],
                    "amount": [10.0, 20.0],
                    "account": ["1001", "1002"],
                }
            ),
            "JE_2": pd.DataFrame(
                {
                    "entry_id": [3],
                    "amount": [30.0],
                    "account": ["1003"],
                }
            ),
            "Config": pd.DataFrame({"key": ["currency"], "value": ["CNY"]}),
        },
    )

    assert len(file_meta.sheet_groups) == 1
    group = file_meta.sheet_groups[0]
    assert group.group_type == "same_schema_append"
    assert group.sheet_names == ["JE_1", "JE_2"]
    assert group.columns == ["entry_id", "amount", "account"]
    assert group.total_rows == 3
    assert group.group_id.startswith("sg_")
    assert file_meta.to_prompt_dict()["sheet_groups"][0]["group_id"] == group.group_id
    assert Executor._build_manifest([file_meta])[0]["sheet_groups"][0]["group_id"] == group.group_id


def test_union_sheet_group_executes_with_audit_and_contract(tmp_path):
    file_meta = _write_workbook(
        tmp_path / "je.xlsx",
        {
            "JE_1": pd.DataFrame(
                {
                    "entry_id": [1, 2],
                    "amount": [10.0, 20.0],
                    "account": ["1001", "1002"],
                }
            ),
            "JE_2": pd.DataFrame(
                {
                    "entry_id": [3],
                    "amount": [30.0],
                    "account": ["1003"],
                }
            ),
        },
    )
    group = file_meta.sheet_groups[0]
    sources = [
        {
            "dataset_id": file_meta.runtime_key,
            "sheet_id": sheet_id,
            "columns": ["entry_id", "amount"],
        }
        for sheet_id in group.sheet_ids
    ]
    plan = {
        "task_summary": "Analyze all JE rows",
        "requirements": [
            {
                "id": "R1",
                "objective": "Calculate total amount across the workbook",
                "sources": sources,
                "joins": [],
                "combines": [
                    {
                        "type": "union_all",
                        "dataset_id": file_meta.runtime_key,
                        "group_id": group.group_id,
                        "sheet_ids": group.sheet_ids,
                        "columns": ["entry_id", "amount"],
                        "reason": "JE sheets are row partitions with the same schema.",
                    }
                ],
                "grain": "all JE rows",
                "formula": "sum(amount)",
                "output_type": "metric",
            }
        ],
        "warnings": [],
        "clarification_required": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    code = f"""
je = data.union_sheets("{file_meta.runtime_key}", group_id="{group.group_id}", columns=["entry_id", "amount"])
total = je["amount"].sum()
result.set_summary(f"Total amount is {{total}} across {{len(je)}} rows.")
result.add_metric("Total amount", total)
result.add_metric("Rows", len(je))
result.add_table("JE union", je.sort_values("entry_id"))
result.add_answer("R1", "Total amount across workbook", f"Total amount is {{total}}.", supporting_metrics=["Total amount", "Rows"], supporting_tables=["JE union"])
result.mark_requirement("R1")
"""

    plan_validation = AnalysisPlanValidator().validate(plan, [file_meta])
    code_validation = GeneratedCodeContractValidator().validate(
        code,
        [file_meta],
        plan,
    )
    execution = Executor().run(code, [file_meta], analysis_plan=plan)

    assert plan_validation.is_valid, plan_validation.issues
    assert code_validation.is_valid, code_validation.issues
    assert execution.success, execution.stderr
    assert execution.analysis_result.metrics[0].value == 60.0
    assert execution.analysis_result.metrics[1].value == 3
    assert execution.analysis_result.tables[0].columns == [
        "entry_id",
        "amount",
        "source_sheet",
        "source_sheet_id",
    ]
    assert execution.analysis_result.audit[0]["kind"] == "union"
    assert execution.analysis_result.audit[0]["group_id"] == group.group_id


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
result.add_answer("R1", "(a + b) / c", "Metric was calculated after aligning all datasets by id.", supporting_tables=["Metric"])
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
result.add_answer("R1", "sum(a + b)", "The total combined value is 37.", supporting_metrics=["Total"])
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


def test_large_cross_dataset_merge_with_projected_columns_is_allowed(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "BACKGROUND_ANALYSIS_ROWS", 2)
    monkeypatch.setattr(settings, "LARGE_DATASET_COLUMN_GUARD", 2)
    first = _write(
        tmp_path / "a.xlsx",
        pd.DataFrame({"id": [1, 2, 3], "a": [10, 20, 30], "extra": [0, 0, 0]}),
    )
    second = _write(
        tmp_path / "b.xlsx",
        pd.DataFrame({"id": [1, 2, 3], "b": [3, 4, 5], "extra": [0, 0, 0]}),
    )
    plan = _plan([first, second], "a + b")
    code = f"""
ANALYSIS_SPEC = {{"requirements": ["R1"], "datasets": ["{first.runtime_key}", "{second.runtime_key}"]}}
a = data.get("{first.runtime_key}", "{first.sheets[0].sheet_id}", columns=["id", "a"])
b = data.get("{second.runtime_key}", "{second.sheets[0].sheet_id}", columns=["id", "b"])
joined = data.merge(a, b, left_name="{first.runtime_key}", right_name="{second.runtime_key}", on="id", how="inner")
joined["combined"] = joined["a"] + joined["b"]
result.set_summary("Projected large datasets were merged explicitly.")
result.add_table("Combined", joined)
result.add_answer("R1", "a + b", "Combined values were calculated by id.", supporting_tables=["Combined"])
result.mark_requirement("R1")
"""

    execution = Executor().run(
        code,
        [first, second],
        analysis_plan=plan,
    )

    assert execution.success, execution.stderr
    assert execution.analysis_result.tables[0].rows[-1] == [3, 30, 5, 35]
    assert any(
        item.get("kind") == "join"
        for item in execution.analysis_result.audit
    )


def test_missing_analysis_spec_and_answer_falls_back_to_plan_summary(tmp_path):
    file_meta = _write(
        tmp_path / "single.xlsx",
        pd.DataFrame({"id": [1, 2], "amount": [10, 20]}),
    )
    plan = {
        "task_summary": "Sum amount",
        "requirements": [
            {
                "id": "R1",
                "objective": "Calculate total amount",
                "sources": [_source(file_meta, ["amount"])],
                "joins": [],
                "grain": "dataset",
                "formula": "sum(amount)",
                "output_type": "metric",
            }
        ],
        "warnings": [],
        "clarification_required": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    code = f"""
df = data.get("{file_meta.runtime_key}", "{file_meta.sheets[0].sheet_id}", columns=["amount"])
total = df["amount"].sum()
result.set_summary(f"Total amount is {{total}}.")
result.add_metric("Total amount", total)
result.mark_requirement("R1")
"""

    execution = Executor().run(
        code,
        [file_meta],
        analysis_plan=plan,
    )

    assert execution.success, execution.stderr
    assert execution.analysis_result.answers
    assert execution.analysis_result.answers[0].answer_id == "R1"
    assert execution.analysis_result.answers[0].supporting_metrics == [
        "Total amount"
    ]


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
    assert "no explicit join/alignment or append/union rule" in "\n".join(
        validation.issues
    )


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
result.add_answer("R1", "Count rows", f"Rows counted: {{len(df)}}.", supporting_metrics=["Rows"])
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
