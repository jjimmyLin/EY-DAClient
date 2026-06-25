from __future__ import annotations

import pandas as pd

import dify.workflow as workflow_module
from core.executor import Executor
from core.code_validator import CodeValidator
from core.preprocessor import Preprocessor
from core.prompt_builder import PromptBuilder
from dify.workflow import AnalysisWorkflow


class FakeClient:
    def __init__(self, responses, plan=None):
        self.responses = list(responses)
        self.prompts = []
        self.plan = plan or {}

    def generate_code(self, prompt: dict, event_callback=None) -> str:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("FakeClient has no queued response")
        return self.responses.pop(0)

    def generate_analysis(self, prompt: dict, event_callback=None) -> dict:
        return {
            "code": self.generate_code(prompt, event_callback),
            "plan": self.plan,
        }


def _write_demo_workbook(path):
    df = pd.DataFrame(
        [
            {"price": None, "product": "A", "quantity": 2},
            {"price": 12.0, "product": "B", "quantity": 3},
            {"price": 3.0, "product": "C", "quantity": 21},
            {"price": 4.0, "product": "D", "quantity": 4},
        ]
    )
    df.to_excel(path, index=False, sheet_name="Sheet1")


def _files_meta(tmp_path):
    workbook = tmp_path / "TEST.xlsx"
    _write_demo_workbook(workbook)
    return [Preprocessor().process(str(workbook))]


def _analysis_plan(files_meta, columns=None):
    file_meta = files_meta[0]
    sheet = file_meta.sheets[0]
    return {
        "task_summary": "Test analysis",
        "requirements": [
            {
                "id": "R1",
                "objective": "Complete the requested analysis",
                "sources": [
                    {
                        "dataset_id": file_meta.runtime_key,
                        "sheet_id": sheet.sheet_id,
                        "columns": columns or ["price", "quantity"],
                    }
                ],
                "joins": [],
                "grain": "source row",
                "formula": "Defined by the request",
                "output_type": "metric",
            }
        ],
        "warnings": [],
        "clarification_required": False,
        "clarification_question": "",
        "clarification_options": [],
    }


def test_preprocessor_adds_bounded_unique_value_evidence(tmp_path):
    files_meta = _files_meta(tmp_path)

    unique_values = files_meta[0].sheets[0].unique_values

    assert "product" in unique_values
    assert "A" in unique_values["product"]
    assert "D" in unique_values["product"]


def test_analysis_prompt_uses_direct_code_generation_contract(tmp_path):
    query = "Calculate total revenue. " * 40
    prompt = PromptBuilder.build_analysis_prompt(
        _files_meta(tmp_path),
        query,
        confirmed_intent={"metric": "revenue"},
    )

    assert set(prompt) == {"task_type", "context", "query"}
    assert prompt["task_type"] == "analysis"
    assert prompt["query"] == query.strip()
    assert len(prompt["query"]) > 256
    assert '"metric":"revenue"' in prompt["context"]
    assert "TEST.xlsx" in prompt["context"]


def test_workflow_generates_code_from_single_backend_call(tmp_path, monkeypatch):
    files_meta = _files_meta(tmp_path)
    dataset_id = files_meta[0].runtime_key
    sheet_id = files_meta[0].sheets[0].sheet_id
    code = (
        f'ANALYSIS_SPEC = {{"requirements": ["R1"], "datasets": ["{dataset_id}"]}}\n'
        f'df = data.get("{dataset_id}", "{sheet_id}")\n'
        'print("rows:", len(df))\n'
        'print("total:", (df["price"] * df["quantity"]).sum())\n'
        'result.mark_requirement("R1")'
    )
    fake = FakeClient([code], _analysis_plan(files_meta))
    monkeypatch.setattr(
        workflow_module,
        "get_client",
        lambda cancellation_token=None: fake,
    )

    result = AnalysisWorkflow().generate_only(
        files_meta,
        "Calculate total revenue",
    )

    assert result.success
    assert result.code == code
    assert fake.responses == []
    assert len(fake.prompts) == 1


def test_workflow_blocks_unsafe_generated_code(tmp_path, monkeypatch):
    files_meta = _files_meta(tmp_path)
    fake = FakeClient(
        ["import os\nprint(os.getcwd())"],
        _analysis_plan(files_meta),
    )
    monkeypatch.setattr(
        workflow_module,
        "get_client",
        lambda cancellation_token=None: fake,
    )

    result = AnalysisWorkflow().generate_only(
        files_meta,
        "Show working directory",
    )

    assert not result.success
    assert "安全" in result.error or "security" in result.error.lower()


def test_workflow_run_executes_generated_code_locally(tmp_path, monkeypatch):
    files_meta = _files_meta(tmp_path)
    dataset_id = files_meta[0].runtime_key
    sheet_id = files_meta[0].sheets[0].sheet_id
    code = (
        f'ANALYSIS_SPEC = {{"requirements": ["R1"], "datasets": ["{dataset_id}"]}}\n'
        f'df = data.get("{dataset_id}", "{sheet_id}")\n'
        'valid = df[df["price"].notna()]\n'
        'print("audited columns: price, quantity")\n'
        'print("total:", (valid["price"] * valid["quantity"]).sum())\n'
        'result.mark_requirement("R1")'
    )
    fake = FakeClient([code], _analysis_plan(files_meta))
    monkeypatch.setattr(
        workflow_module,
        "get_client",
        lambda cancellation_token=None: fake,
    )

    result = AnalysisWorkflow().run(files_meta, "Calculate total revenue")

    assert result.success
    assert result.execution is not None
    assert "audited columns: price, quantity" in result.execution.stdout
    assert "total: 115.0" in result.execution.stdout


def test_workflow_repairs_runtime_error_and_revalidates_locally(
    tmp_path,
    monkeypatch,
):
    files_meta = _files_meta(tmp_path)
    dataset_id = files_meta[0].runtime_key
    sheet_id = files_meta[0].sheets[0].sheet_id
    broken_code = f"""
ANALYSIS_SPEC = {{"requirements": ["R1"], "datasets": ["{dataset_id}"]}}
df = data.get("{dataset_id}", "{sheet_id}")
summary = (
    df.groupby("product", as_index=False)["quantity"]
    .sum()
    .reset_index()
)
summary.columns = ["product", "quantity"]
result.add_table("Quantity", dataframe=summary)
result.mark_requirement("R1")
"""
    repaired_code = f"""
ANALYSIS_SPEC = {{"requirements": ["R1"], "datasets": ["{dataset_id}"]}}
df = data.get("{dataset_id}", "{sheet_id}")
summary = (
    df.groupby("product", as_index=False)["quantity"]
    .sum()
    .reset_index(drop=True)
)
result.set_summary("Repair completed.")
result.add_table("Quantity", dataframe=summary)
result.mark_requirement("R1")
"""
    fake = FakeClient(
        [broken_code, repaired_code],
        _analysis_plan(files_meta, ["product", "quantity"]),
    )
    monkeypatch.setattr(
        workflow_module,
        "get_client",
        lambda cancellation_token=None: fake,
    )

    result = AnalysisWorkflow().prepare_analysis(
        files_meta,
        "Summarize quantity by product",
    )

    assert result.success
    assert result.code == repaired_code
    assert result.retries_used == 1
    assert result.execution is not None
    assert result.execution.analysis_result.summary == "Repair completed."
    assert fake.prompts[1]["task_type"] == "repair"
    assert "Length mismatch" in fake.prompts[1]["context"]
    assert fake.prompts[1]["query"] == "Summarize quantity by product"


def test_total_price_demo_python_execution_keeps_missing_price_exception(tmp_path):
    files_meta = _files_meta(tmp_path)
    code = """
df = dfs["TEST.xlsx"]["Sheet1"].copy()
df["total"] = df["price"] * df["quantity"]
valid_rows = df[df["price"].notna() & df["quantity"].notna()]
invalid_rows = df[df["price"].isna() | df["quantity"].isna()].copy()
invalid_rows["issue"] = "price or quantity missing; excluded from total"
print("detail:")
print(df[["product", "price", "quantity", "total"]].to_string(index=False))
print("\\naudited total:", valid_rows["total"].sum())
print("\\ninvalid rows:")
print(invalid_rows[["product", "price", "quantity", "issue"]].to_string(index=False))
"""

    result = Executor().run(code, files_meta)

    assert result.success
    assert "audited total: 115.0" in result.stdout
    assert "A" in result.stdout
    assert "NaN" in result.stdout
    assert "excluded from total" in result.stdout


def test_executor_returns_structured_metrics_tables_and_charts(tmp_path):
    files_meta = _files_meta(tmp_path)
    code = """
df = dfs["TEST.xlsx"]["Sheet1"].copy()
df["revenue"] = df["price"] * df["quantity"]
total = df["revenue"].sum()
result.set_summary("Revenue analysis completed.")
result.add_metric("Total revenue", total, " CNY")
result.add_table("Revenue by product", df[["product", "revenue"]])
fig, ax = plt.subplots()
df.plot.bar(x="product", y="revenue", ax=ax, legend=False)
result.add_chart("Revenue by product", fig)
result.add_insight("Top-line result", f"Total revenue is {total}.")
"""

    execution = Executor().run(code, files_meta)

    assert execution.success
    assert execution.analysis_result.summary == "Revenue analysis completed."
    assert execution.analysis_result.metrics[0].value == 115.0
    assert execution.analysis_result.tables[0].total_rows == 4
    assert execution.analysis_result.charts[0].image_base64
    assert execution.analysis_result.insights[0].title == "Top-line result"


def test_code_validator_blocks_file_io_and_unsafe_runtime_access():
    unsafe_samples = [
        "pd.read_excel('C:/secret.xlsx')",
        "from pathlib import Path\nPath('C:/secret.txt').read_text()",
        "import numpy as np\nnp.load('C:/secret.npy')",
        "df.to_csv('C:/export.csv')",
        "__builtins__['open']('C:/secret.txt').read()",
        "pd.io.common.os.system('whoami')",
    ]

    for code in unsafe_samples:
        validation = CodeValidator().validate(code)
        assert not validation.is_safe, code


def test_execute_only_revalidates_user_edited_code(tmp_path):
    workflow = AnalysisWorkflow()
    files_meta = _files_meta(tmp_path)

    result = workflow.execute_only(
        "pd.read_excel('C:/secret.xlsx')",
        files_meta,
        analysis_plan=_analysis_plan(files_meta),
    )

    assert not result.success
    assert result.execution is None
    assert "read_excel" in result.error
