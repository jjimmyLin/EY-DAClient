from __future__ import annotations

import pytest

from dify.client import DifyClient, DifyClientError


def _client() -> DifyClient:
    return DifyClient()


def test_build_inputs_prefers_query_variable():
    client = _client()
    prompt = {
        "system": "sys",
        "context": "ctx",
        "query": "sum sales",
    }
    parameters = {
        "user_input_form": [
            {"paragraph": {"variable": "system", "required": False}},
            {"paragraph": {"variable": "context", "required": False}},
            {"text-input": {"variable": "query", "required": True}},
        ]
    }

    inputs = client._build_inputs(prompt, parameters)

    assert inputs == {
        "system": "sys",
        "context": "ctx",
        "query": "sum sales",
    }


def test_build_inputs_passes_task_type_when_workflow_supports_it():
    client = _client()
    prompt = {
        "system": "sys",
        "context": "ctx",
        "query": "overview",
        "task_type": "dataset_overview",
    }
    parameters = {
        "user_input_form": [
            {"paragraph": {"variable": "system", "required": False}},
            {"paragraph": {"variable": "context", "required": False}},
            {"text-input": {"variable": "query", "required": True}},
            {"text-input": {"variable": "task_type", "required": True}},
        ]
    }

    inputs = client._build_inputs(prompt, parameters)

    assert inputs["task_type"] == "dataset_overview"
    assert inputs["query"] == "overview"


def test_build_inputs_falls_back_to_single_text_field():
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

    inputs = client._build_inputs(prompt, parameters)

    assert set(inputs) == {"request_text"}
    assert "System instructions:" in inputs["request_text"]
    assert "Dataset context:" in inputs["request_text"]
    assert "User request:" in inputs["request_text"]


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
