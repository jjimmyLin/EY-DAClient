from __future__ import annotations

import json

import pytest
import httpx

from dify.client import DifyClient, DifyClientError
from core.preprocessor import FileMeta
from core.prompt_builder import PromptBuilder


def _client() -> DifyClient:
    return DifyClient()


def test_build_inputs_uses_only_published_workflow_contract():
    client = _client()
    prompt = {
        "task_type": "analysis",
        "context": "ctx",
        "query": "sum sales",
    }
    parameters = {
        "user_input_form": [
            {"select": {"variable": "task_type", "required": True}},
            {"paragraph": {"variable": "context", "required": False}},
            {"paragraph": {"variable": "query", "required": True}},
        ]
    }

    inputs = client._build_inputs(prompt, parameters)

    assert inputs == {
        "task_type": "analysis",
        "context": "ctx",
        "query": "sum sales",
    }


def test_build_inputs_passes_task_type_when_workflow_supports_it():
    client = _client()
    prompt = {
        "context": "ctx",
        "query": "overview",
        "task_type": "overview",
    }
    parameters = {
        "user_input_form": [
            {"paragraph": {"variable": "context", "required": False}},
            {"text-input": {"variable": "query", "required": True}},
            {"text-input": {"variable": "task_type", "required": True}},
        ]
    }

    inputs = client._build_inputs(prompt, parameters)

    assert inputs["task_type"] == "overview"
    assert inputs["query"] == "overview"


def test_build_inputs_rejects_legacy_single_text_field():
    client = _client()
    prompt = {
        "system": "sys",
        "context": "ctx",
        "query": "sum sales",
    }
    parameters = {
        "user_input_form": [
            {"paragraph": {"variable": "request_text", "required": True}},
        ]
    }

    with pytest.raises(DifyClientError) as exc_info:
        client._build_inputs(prompt, parameters)

    assert "task_type, context, and query" in str(exc_info.value)


def test_extract_code_raises_on_failed_workflow():
    client = _client()

    with pytest.raises(DifyClientError) as exc_info:
        client.extract_code_from_response(
            {
                "data": {
                    "status": "failed",
                    "error": "bad inputs",
                    "outputs": {},
                }
            }
        )

    assert "bad inputs" in str(exc_info.value)


def test_overview_prompt_fits_configured_dify_input_limits():
    prompt = PromptBuilder.build_dataset_overview_prompt(
        FileMeta(
            file_path="C:/test.xlsx",
            file_name="test.xlsx",
            file_size_kb=1.0,
            sheet_count=0,
            sheets=[],
        )
    )

    assert set(prompt) == {"task_type", "context", "query"}
    assert prompt["task_type"] == "overview"
    assert "test.xlsx" in prompt["context"]
    assert prompt["query"]


def test_build_inputs_uses_dify_published_length_limit():
    client = _client()
    prompt = {
        "task_type": "analysis",
        "context": "metadata",
        "query": "x" * 501,
    }
    parameters = {
        "user_input_form": [
            {"text-input": {"variable": "task_type", "required": True}},
            {"paragraph": {"variable": "context", "required": True}},
            {
                "paragraph": {
                    "variable": "query",
                    "required": True,
                    "max_length": 500,
                }
            },
        ]
    }

    with pytest.raises(DifyClientError) as exc_info:
        client._build_inputs(prompt, parameters)

    assert "501 / 500" in str(exc_info.value)


def test_extract_analysis_reads_code_and_structured_plan():
    client = _client()
    generated = client.extract_analysis_from_response(
        {
            "data": {
                "status": "succeeded",
                "outputs": {
                    "code": "print('ok')",
                    "analysis_plan": {
                        "task_summary": "Sales review",
                        "requirements": [{"id": "A", "objective": "Total"}],
                    },
                },
            }
        }
    )

    assert generated["code"] == "print('ok')"
    assert generated["plan"]["requirements"][0]["id"] == "A"


def test_extract_analysis_never_treats_plan_as_code():
    client = _client()

    with pytest.raises(DifyClientError) as exc_info:
        client.extract_analysis_from_response(
            {
                "data": {
                    "status": "succeeded",
                    "outputs": {
                        "analysis_plan": '{"task_summary":"Only a plan"}',
                    },
                }
            }
        )

    assert "did not contain Python code" in str(exc_info.value)


def test_extract_overview_accepts_direct_object_outputs():
    client = _client()
    outputs = {
        "dataset_kind": "销售数据",
        "topic": "产品销售",
        "summary": "产品销售概览",
        "rows": 10,
        "columns": 3,
        "sheet_count": 1,
        "suggestions": ["A", "B", "C", "D"],
    }

    generated = client.extract_analysis_from_response(
        {"data": {"status": "succeeded", "outputs": outputs}}
    )

    assert json.loads(generated["code"]) == outputs


def test_extract_analysis_unwraps_structured_output_plan():
    client = _client()
    generated = client.extract_analysis_from_response(
        {
            "data": {
                "status": "succeeded",
                "outputs": {
                    "code": "print('ok')",
                    "analysis_plan": {
                        "structured_output": {
                            "task_summary": "Review",
                            "requirements": [],
                            "warnings": [],
                        }
                    },
                },
            }
        }
    )

    assert generated["plan"]["task_summary"] == "Review"


def test_streaming_http_error_reads_body_before_accessing_text(monkeypatch):
    client = _client()
    request = httpx.Request("POST", "https://example.test/workflows/run")
    response = httpx.Response(
        400,
        request=request,
        stream=httpx.ByteStream(b'{"message":"query exceeds max length"}'),
    )

    class StreamContext:
        def __enter__(self):
            return response

        def __exit__(self, exc_type, exc, traceback):
            return False

    class FakeHttpClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def stream(self, *args, **kwargs):
            return StreamContext()

        def close(self):
            pass

    monkeypatch.setattr(httpx, "Client", FakeHttpClient)

    with pytest.raises(DifyClientError) as exc_info:
        client._run_workflow_streaming({"inputs": {}})

    assert exc_info.value.status_code == 400
    assert "query exceeds max length" in str(exc_info.value)
