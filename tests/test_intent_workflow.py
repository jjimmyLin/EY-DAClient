from __future__ import annotations

import pandas as pd

import dify.workflow as workflow_module
from core.executor import Executor
from core.code_validator import CodeValidator
from core.preprocessor import Preprocessor
from core.prompt_builder import PromptBuilder
from dify.workflow import AnalysisWorkflow


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def generate_code(self, prompt: dict, event_callback=None) -> str:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("FakeClient has no queued response")
        return self.responses.pop(0)


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
    assert '"metric": "revenue"' in prompt["context"]
    assert "TEST.xlsx" in prompt["context"]


def test_workflow_generates_code_from_single_backend_call(tmp_path, monkeypatch):
    code = (
        'df = dfs["TEST.xlsx"]["Sheet1"]\n'
        'print("rows:", len(df))\n'
        'print("total:", (df["price"] * df["quantity"]).sum())'
    )
    fake = FakeClient([code])
    monkeypatch.setattr(
        workflow_module,
        "get_client",
        lambda cancellation_token=None: fake,
    )

    result = AnalysisWorkflow().generate_only(
        _files_meta(tmp_path),
        "Calculate total revenue",
    )

    assert result.success
    assert result.code == code
    assert fake.responses == []
    assert len(fake.prompts) == 1


def test_workflow_blocks_unsafe_generated_code(tmp_path, monkeypatch):
    fake = FakeClient(["import os\nprint(os.getcwd())"])
    monkeypatch.setattr(
        workflow_module,
        "get_client",
        lambda cancellation_token=None: fake,
    )

    result = AnalysisWorkflow().generate_only(
        _files_meta(tmp_path),
        "Show working directory",
    )

    assert not result.success
    assert "安全" in result.error or "security" in result.error.lower()


def test_workflow_run_executes_generated_code_locally(tmp_path, monkeypatch):
    code = (
        'df = dfs["TEST.xlsx"]["Sheet1"]\n'
        'valid = df[df["price"].notna()]\n'
        'print("audited columns: price, quantity")\n'
        'print("total:", (valid["price"] * valid["quantity"]).sum())'
    )
    fake = FakeClient([code])
    monkeypatch.setattr(
        workflow_module,
        "get_client",
        lambda cancellation_token=None: fake,
    )

    result = AnalysisWorkflow().run(_files_meta(tmp_path), "Calculate total revenue")

    assert result.success
    assert result.execution is not None
    assert "audited columns: price, quantity" in result.execution.stdout
    assert "total: 115.0" in result.execution.stdout


def test_workflow_repairs_runtime_error_and_revalidates_locally(
    tmp_path,
    monkeypatch,
):
    broken_code = """
df = dfs["TEST.xlsx"]["Sheet1"]
summary = (
    df.groupby("product", as_index=False)["quantity"]
    .sum()
    .reset_index()
)
summary.columns = ["product", "quantity"]
result.add_table("Quantity", dataframe=summary)
"""
    repaired_code = """
df = dfs["TEST.xlsx"]["Sheet1"]
summary = (
    df.groupby("product", as_index=False)["quantity"]
    .sum()
    .reset_index(drop=True)
)
result.set_summary("Repair completed.")
result.add_table("Quantity", dataframe=summary)
"""
    fake = FakeClient([broken_code, repaired_code])
    monkeypatch.setattr(
        workflow_module,
        "get_client",
        lambda cancellation_token=None: fake,
    )

    result = AnalysisWorkflow().prepare_analysis(
        _files_meta(tmp_path),
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

    result = workflow.execute_only(
        "pd.read_excel('C:/secret.xlsx')",
        _files_meta(tmp_path),
    )

    assert not result.success
    assert result.execution is None
    assert "安全检查失败" in result.error
