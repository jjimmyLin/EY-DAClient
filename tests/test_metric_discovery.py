from __future__ import annotations

import json

import httpx
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QComboBox,
    QLabel,
    QMessageBox,
    QWidget,
)

from config.settings import settings
from core.metric_discovery import (
    INFLUENCER_PLAYBOOK_ID,
    INFLUENCER_REQUIRED_FAMILIES,
    MetricDiscoveryContractError,
    MetricDiscoveryRequest,
    MetricDiscoveryResult,
    ReferenceAttachment,
)
from dify.metric_client import MetricClientError, MetricDifyClient
from ui.main_window import MainWindow
from ui.metric_discovery_page import (
    DropdownMultiSelect,
    MetricDiscoveryPage,
    MetricResultCard,
    MultiSelectPopup,
    _friendly_metric_error,
)


def _valid_indicator(index: int) -> dict:
    return {
        "indicator_id": f"M{index:02d}",
        "title": f"Data-based indicator {index}",
        "category": "收入与销售",
        "priority": "高",
        "target_basis": "The supplied context describes order-based sales.",
        "analysis_objective": "Test the completeness of the sales chain.",
        "definition": "Matched sales-chain amount ratio.",
        "analysis_grain": "订单行级",
        "analysis_method": [
            "Build the complete order population.",
            "Join delivery and invoice detail.",
        ],
        "data_requirements": [
            {
                "dataset_name": "销售订单明细",
                "grain": "一行一条订单行",
                "required_fields": ["订单号", "客户编码", "金额"],
                "join_keys": ["订单号"],
            }
        ],
        "client_request_guidance": "请提供核查期间全部销售订单行明细。",
        "key_scope_questions": ["是否包含取消订单"],
        "potential_anomalies": ["无发货记录的订单"],
        "data_acquisition_difficulty": "中",
    }


def _workflow_response(count: int = 5) -> dict:
    return {
        "workflow_run_id": "run-1",
        "data": {
            "status": "succeeded",
            "outputs": {
                "metric_pack": {
                    "summary": "Ready",
                    "indicators": [
                        _valid_indicator(index)
                        for index in range(1, count + 1)
                    ],
                    "consolidated_data_requests": [],
                }
            },
        },
    }


def _regulatory_workflow_response(count: int = 5) -> dict:
    response = _workflow_response(count)
    metric_pack = response["data"]["outputs"]["metric_pack"]
    for indicator in metric_pack["indicators"]:
        indicator.update(
            {
                "regulatory_references": ["5-12 经销模式"],
                "population_definition": "核查期间全部销售订单及取消订单",
                "coverage_period": "核查期及前后各一个月",
                "exception_rules": ["订单链路任一环节缺失"],
                "follow_up_procedures": ["追查单据并访谈业务负责人"],
                "expected_evidence": ["订单、发货、发票及收款记录"],
                "scope_limitations": [],
            }
        )
    metric_pack["regulatory_review"] = {
        "applicability_assessment": [
            {
                "section": f"5-{index}",
                "status": "待确认",
                "basis": "需结合项目资料确认",
            }
            for index in range(1, 20)
        ],
        "non_data_procedures": ["访谈并执行系统穿行测试"],
        "scope_limitations": [],
    }
    return response


def _workflow_streaming_response(
    count: int = 5,
    *,
    regulatory: bool = False,
) -> httpx.Response:
    response = (
        _regulatory_workflow_response(count)
        if regulatory
        else _workflow_response(count)
    )
    final_data = response["data"]
    chunks = [
        {
            "event": "workflow_started",
            "task_id": "task-1",
            "workflow_run_id": "run-1",
            "data": {"id": "run-1"},
        },
        {
            "event": "node_started",
            "task_id": "task-1",
            "workflow_run_id": "run-1",
            "data": {"title": "生成数据核查指标"},
        },
        {
            "event": "workflow_finished",
            "task_id": "task-1",
            "workflow_run_id": "run-1",
            "data": final_data,
        },
    ]
    content = "".join(
        f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        for chunk in chunks
    )
    return httpx.Response(
        200,
        headers={"Content-Type": "text/event-stream"},
        text=content,
    )


def test_request_preserves_optional_empty_selections_and_custom_values():
    request = MetricDiscoveryRequest(
        company_information={
            "company_name": "Example Co",
            "industries": [],
            "industry_custom": ["Special equipment services"],
            "business_models": [],
        },
        indicator_guidance={
            "directions": [],
            "direction_custom": ["Dealer inventory pressure"],
            "indicator_count": None,
        },
    )

    payload = request.to_payload()

    assert payload["company_information"]["industries"] == []
    assert payload["company_information"]["industry_custom"] == [
        "Special equipment services"
    ]
    assert payload["output_requirements"]["data_based_only"] is True
    assert payload["regulatory_guidance"]["baseline_applies"] is True
    assert payload["regulatory_guidance"]["special_analysis_enabled"] is False
    assert payload["regulatory_guidance"]["covered_sections"] == [
        f"5-{index}" for index in range(1, 20)
    ]


def test_regulatory_request_integrates_special_mode_and_output_contract():
    request = MetricDiscoveryRequest(
        company_information={"company_name": "Example Co"},
        indicator_guidance={"indicator_count": 5},
        regulatory_analysis_enabled=True,
    )

    payload = request.to_payload()

    assert payload["indicator_guidance"]["generation_mode"] == (
        "issuance_guidance_no5_special"
    )
    assert payload["regulatory_guidance"]["special_analysis_enabled"] is True
    assert payload["regulatory_guidance"]["priority_sections"] == [
        "5-11",
        "5-12",
        "5-13",
        "5-14",
    ]
    section_catalog = {
        item["section"]: item
        for item in payload["regulatory_guidance"]["section_catalog"]
    }
    assert section_catalog["5-11"]["title"] == "第三方回款核查"
    assert section_catalog["5-12"]["title"] == "经销模式"
    assert section_catalog["5-13"]["title"] == (
        "通过互联网开展业务相关信息系统核查"
    )
    assert section_catalog["5-14"]["title"] == "信息系统专项核查"
    assert "反舞弊" in section_catalog["5-14"]["audit_focus"]
    assert "regulatory_references" in payload["output_requirements"][
        "each_indicator_must_include"
    ]
    assert payload["output_requirements"][
        "regulatory_review_must_include"
    ] == [
        "applicability_assessment",
        "non_data_procedures",
        "scope_limitations",
    ]


def test_ecommerce_influencer_yes_builds_mandatory_metric_playbook():
    request = MetricDiscoveryRequest(
        company_information={
            "company_name": "Example Co",
            "business_models": ["电商销售"],
            "ecommerce_marketing": {
                "uses_influencer_promotion": "yes",
                "user_confirmed": True,
            },
        },
        indicator_guidance={"indicator_count": 8},
    )

    payload = request.to_payload()
    marketing = payload["company_information"]["ecommerce_marketing"]
    playbook = payload["indicator_guidance"]["metric_playbooks"][0]

    assert marketing["uses_influencer_promotion"] == "yes"
    assert "MCN机构或达人合作投放" in marketing["scope_definition"]
    assert playbook["playbook_id"] == INFLUENCER_PLAYBOOK_ID
    assert playbook["coverage_policy"] == "mandatory"
    assert playbook["required_metric_families"] == list(
        INFLUENCER_REQUIRED_FAMILIES
    )
    assert playbook["metric_family_catalog"]
    assert payload["output_requirements"]["required_metric_families"] == list(
        INFLUENCER_REQUIRED_FAMILIES
    )
    assert "metric_family_id" in payload["output_requirements"][
        "each_indicator_must_include"
    ]


@pytest.mark.parametrize("status", ["no", "unknown"])
def test_ecommerce_influencer_non_yes_modes_are_explicit(status):
    request = MetricDiscoveryRequest(
        company_information={
            "business_models": ["电商销售"],
            "ecommerce_marketing": {
                "uses_influencer_promotion": status,
                "user_confirmed": True,
            },
        },
        indicator_guidance={"indicator_count": 5},
    )

    playbook = request.to_payload()["indicator_guidance"][
        "metric_playbooks"
    ][0]

    assert playbook["user_answer"] == status
    if status == "no":
        assert playbook["enabled"] is False
        assert playbook["forbidden_metric_families"]
    else:
        assert playbook["coverage_policy"] == "conditional"
        assert playbook["recommended_metric_families"]


def test_ecommerce_requires_user_to_answer_influencer_question():
    request = MetricDiscoveryRequest(
        company_information={"business_models": ["电商销售"]},
        indicator_guidance={"indicator_count": 5},
    )

    with pytest.raises(
        MetricDiscoveryContractError,
        match="请确认是否使用达人推广",
    ):
        request.validate()


def test_influencer_result_requires_all_mandatory_metric_families():
    response = _workflow_response()
    indicators = response["data"]["outputs"]["metric_pack"]["indicators"]
    for indicator, family in zip(indicators, INFLUENCER_REQUIRED_FAMILIES):
        indicator["playbook_id"] = INFLUENCER_PLAYBOOK_ID
        indicator["metric_family_id"] = family

    result = MetricDiscoveryResult.from_workflow_response(
        response,
        required_metric_families=INFLUENCER_REQUIRED_FAMILIES,
    )
    assert {item.metric_family_id for item in result.indicators} == set(
        INFLUENCER_REQUIRED_FAMILIES
    )

    indicators[-1]["metric_family_id"] = "promotion_period_efficiency"
    with pytest.raises(MetricDiscoveryContractError, match="专项指标结果不完整"):
        MetricDiscoveryResult.from_workflow_response(
            response,
            required_metric_families=INFLUENCER_REQUIRED_FAMILIES,
        )


def test_influencer_no_rejects_influencer_specific_metric_family():
    response = _workflow_response()
    indicator = response["data"]["outputs"]["metric_pack"]["indicators"][0]
    indicator["playbook_id"] = INFLUENCER_PLAYBOOK_ID
    indicator["metric_family_id"] = "influencer_roi_efficiency"

    with pytest.raises(MetricDiscoveryContractError, match="未使用达人推广"):
        MetricDiscoveryResult.from_workflow_response(
            response,
            forbidden_metric_families=("influencer_roi_efficiency",),
        )


def test_completely_empty_request_is_rejected():
    request = MetricDiscoveryRequest(
        company_information={
            "company_name": "",
            "industries": [],
        },
        indicator_guidance={
            "directions": [],
            "indicator_count": None,
        },
    )

    with pytest.raises(MetricDiscoveryContractError, match="at least one"):
        request.validate()


def test_result_rejects_non_data_based_indicator():
    response = _workflow_response()
    del response["data"]["outputs"]["metric_pack"]["indicators"][0][
        "data_requirements"
    ]

    with pytest.raises(MetricDiscoveryContractError, match="data_requirements"):
        MetricDiscoveryResult.from_workflow_response(response)


def test_result_requires_between_five_and_ten_indicators():
    with pytest.raises(MetricDiscoveryContractError, match="between 5 and 10"):
        MetricDiscoveryResult.from_workflow_response(_workflow_response(4))


def test_regulatory_result_fails_closed_when_published_workflow_is_ordinary():
    with pytest.raises(MetricDiscoveryContractError, match="regulatory_review"):
        MetricDiscoveryResult.from_workflow_response(
            _workflow_response(),
            regulatory_analysis_required=True,
        )


def test_regulatory_result_requires_full_review_and_indicator_evidence():
    response = _regulatory_workflow_response()

    result = MetricDiscoveryResult.from_workflow_response(
        response,
        regulatory_analysis_required=True,
    )

    assert len(result.regulatory_review["applicability_assessment"]) == 19
    assert result.indicators[0].regulatory_references == (
        "5-12 经销模式",
    )
    assert result.indicators[0].expected_evidence

    del response["data"]["outputs"]["metric_pack"][
        "regulatory_review"
    ]["applicability_assessment"][-1]
    with pytest.raises(MetricDiscoveryContractError, match="exactly one entry"):
        MetricDiscoveryResult.from_workflow_response(
            response,
            regulatory_analysis_required=True,
        )


def test_metric_client_sends_one_payload_and_separate_file_list(
    monkeypatch,
):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/parameters"):
            return httpx.Response(
                200,
                json={
                    "user_input_form": [
                        {
                            "paragraph": {
                                "variable": "request_payload",
                                "required": True,
                                "max_length": 60000,
                            }
                        },
                        {
                            "file-list": {
                                "variable": "reference_files",
                                "required": False,
                            }
                        },
                    ]
                },
            )
        if request.url.path.endswith("/workflows/run"):
            captured.update(json.loads(request.content.decode("utf-8")))
            return _workflow_streaming_response()
        return httpx.Response(404)

    monkeypatch.setattr(settings, "reload", lambda: None)
    monkeypatch.setattr(settings, "DIFY_METRIC_BASE_URL", "https://dify.test/v1")
    monkeypatch.setattr(settings, "DIFY_METRIC_API_KEY", "app-test")
    monkeypatch.setattr(settings, "DIFY_METRIC_TIMEOUT", 30)
    request = MetricDiscoveryRequest(
        company_information={"company_name": "Example Co"},
        indicator_guidance={"indicator_count": 5},
    )

    result = MetricDifyClient(
        transport=httpx.MockTransport(handler)
    ).generate(request)

    assert len(result.indicators) == 5
    assert set(captured["inputs"]) == {"request_payload", "reference_files"}
    decoded = json.loads(captured["inputs"]["request_payload"])
    assert decoded["company_information"]["company_name"] == "Example Co"
    assert captured["inputs"]["reference_files"] == []
    assert captured["response_mode"] == "streaming"


def test_metric_client_sends_special_analysis_as_one_integrated_run(
    monkeypatch,
):
    captured = {}
    workflow_runs = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal workflow_runs
        if request.url.path.endswith("/parameters"):
            return httpx.Response(
                200,
                json={
                    "user_input_form": [
                        {
                            "paragraph": {
                                "variable": "request_payload",
                                "required": True,
                            }
                        },
                        {
                            "file-list": {
                                "variable": "reference_files",
                                "required": False,
                            }
                        },
                    ]
                },
            )
        if request.url.path.endswith("/workflows/run"):
            workflow_runs += 1
            captured.update(json.loads(request.content.decode("utf-8")))
            return _workflow_streaming_response(regulatory=True)
        return httpx.Response(404)

    monkeypatch.setattr(settings, "reload", lambda: None)
    monkeypatch.setattr(settings, "DIFY_METRIC_BASE_URL", "https://dify.test/v1")
    monkeypatch.setattr(settings, "DIFY_METRIC_API_KEY", "app-test")
    monkeypatch.setattr(settings, "DIFY_METRIC_TIMEOUT", 30)
    request = MetricDiscoveryRequest(
        company_information={"company_name": "Example Co"},
        indicator_guidance={"indicator_count": 5},
        regulatory_analysis_enabled=True,
    )

    result = MetricDifyClient(
        transport=httpx.MockTransport(handler)
    ).generate(request)

    payload = json.loads(captured["inputs"]["request_payload"])
    assert workflow_runs == 1
    assert len(result.indicators) == 5
    assert payload["regulatory_guidance"]["special_analysis_enabled"] is True
    assert payload["output_requirements"]["regulatory_special_analysis"] is True


def test_metric_client_uploads_documents_with_the_same_end_user(
    monkeypatch,
    tmp_path,
):
    calls = []
    published_user = "metric:test-user@test-machine"
    reference_path = tmp_path / "company-profile.pdf"
    reference_path.write_bytes(b"%PDF-1.4 test")

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/parameters"):
            return httpx.Response(
                200,
                json={
                    "user_input_form": [
                        {
                            "paragraph": {
                                "variable": "request_payload",
                                "required": True,
                                "max_length": 60000,
                            }
                        },
                        {
                            "file-list": {
                                "variable": "reference_files",
                                "required": False,
                            }
                        },
                    ]
                },
            )
        if request.url.path.endswith("/files/upload"):
            assert published_user.encode() in request.content
            assert b"company-profile.pdf" in request.content
            return httpx.Response(201, json={"id": "upload-1"})
        if request.url.path.endswith("/workflows/run"):
            body = json.loads(request.content.decode("utf-8"))
            assert body["user"] == published_user
            assert body["response_mode"] == "streaming"
            assert body["inputs"]["reference_files"] == [
                {
                    "transfer_method": "local_file",
                    "upload_file_id": "upload-1",
                    "type": "document",
                }
            ]
            return _workflow_streaming_response()
        return httpx.Response(404)

    monkeypatch.setattr(settings, "reload", lambda: None)
    monkeypatch.setattr(settings, "DIFY_METRIC_BASE_URL", "https://dify.test/v1")
    monkeypatch.setattr(settings, "DIFY_METRIC_API_KEY", "app-test")
    monkeypatch.setattr(settings, "DIFY_METRIC_TIMEOUT", 30)
    monkeypatch.setattr(
        MetricDifyClient,
        "_build_user_id",
        staticmethod(lambda: published_user),
    )
    request = MetricDiscoveryRequest(
        company_information={"company_name": "Example Co"},
        indicator_guidance={"indicator_count": 5},
        attachments=(ReferenceAttachment.from_path(reference_path),),
    )

    result = MetricDifyClient(
        transport=httpx.MockTransport(handler)
    ).generate(request)

    assert len(result.indicators) == 5
    assert [call.url.path for call in calls] == [
        "/v1/parameters",
        "/v1/files/upload",
        "/v1/workflows/run",
    ]


def test_metric_client_never_replays_a_started_workflow(monkeypatch):
    workflow_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal workflow_attempts
        if request.url.path.endswith("/parameters"):
            return httpx.Response(
                200,
                json={
                    "user_input_form": [
                        {
                            "paragraph": {
                                "variable": "request_payload",
                                "required": True,
                                "max_length": 60000,
                            }
                        },
                        {
                            "file-list": {
                                "variable": "reference_files",
                                "required": False,
                            }
                        },
                    ]
                },
            )
        if request.url.path.endswith("/workflows/run"):
            workflow_attempts += 1
            raise httpx.ReadTimeout("response was not received", request=request)
        return httpx.Response(404)

    monkeypatch.setattr(settings, "reload", lambda: None)
    monkeypatch.setattr(settings, "DIFY_METRIC_BASE_URL", "https://dify.test/v1")
    monkeypatch.setattr(settings, "DIFY_METRIC_API_KEY", "app-test")
    monkeypatch.setattr(settings, "DIFY_METRIC_TIMEOUT", 30)
    request = MetricDiscoveryRequest(
        company_information={"company_name": "Example Co"},
        indicator_guidance={"indicator_count": 5},
    )

    with pytest.raises(MetricClientError, match="timed out"):
        MetricDifyClient(
            transport=httpx.MockTransport(handler)
        ).generate(request)

    assert workflow_attempts == 1


def test_metric_client_recovers_started_workflow_without_replaying_post(
    monkeypatch,
):
    workflow_attempts = 0
    result_queries = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal workflow_attempts, result_queries
        if request.url.path.endswith("/parameters"):
            return httpx.Response(
                200,
                json={
                    "user_input_form": [
                        {
                            "paragraph": {
                                "variable": "request_payload",
                                "required": True,
                                "max_length": 60000,
                            }
                        },
                        {
                            "file-list": {
                                "variable": "reference_files",
                                "required": False,
                            }
                        },
                    ]
                },
            )
        if request.method == "POST" and request.url.path.endswith(
            "/workflows/run"
        ):
            workflow_attempts += 1
            started = {
                "event": "workflow_started",
                "task_id": "task-1",
                "workflow_run_id": "run-1",
                "data": {"id": "run-1"},
            }
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                text=(
                    "data: "
                    + json.dumps(started, ensure_ascii=False)
                    + "\n\n"
                ),
            )
        if request.method == "GET" and request.url.path.endswith(
            "/workflows/run/run-1"
        ):
            result_queries += 1
            return httpx.Response(
                200,
                json={
                    "id": "run-1",
                    **_workflow_response()["data"],
                },
            )
        return httpx.Response(404)

    monkeypatch.setattr(settings, "reload", lambda: None)
    monkeypatch.setattr(settings, "DIFY_METRIC_BASE_URL", "https://dify.test/v1")
    monkeypatch.setattr(settings, "DIFY_METRIC_API_KEY", "app-test")
    monkeypatch.setattr(settings, "DIFY_METRIC_TIMEOUT", 30)
    request = MetricDiscoveryRequest(
        company_information={"company_name": "Example Co"},
        indicator_guidance={"indicator_count": 5},
    )

    result = MetricDifyClient(
        transport=httpx.MockTransport(handler)
    ).generate(request)

    assert len(result.indicators) == 5
    assert result.workflow_run_id == "run-1"
    assert workflow_attempts == 1
    assert result_queries == 1


def test_metric_form_allows_blank_unlimited_and_custom_choices(qapp):
    page = MetricDiscoveryPage()
    page.show()
    qapp.processEvents()

    assert page.industries.selected_values() == []
    assert not page.influencer_promotion.isVisible()
    for button in page.directions._buttons.values():
        button.setChecked(True)
    page.directions.other_input.setText("经销商压货风险, 门店闭店风险")
    page.company_name.setText("Example Co")

    request = page.build_request()

    assert len(request.indicator_guidance["directions"]) == len(
        page.directions._buttons
    ) - 1
    assert request.indicator_guidance["direction_custom"] == [
        "经销商压货风险",
        "门店闭店风险",
    ]
    page.close()


def test_metric_form_reset_clears_inputs_attachments_and_old_result(
    qapp,
    monkeypatch,
    tmp_path,
):
    page = MetricDiscoveryPage()
    reference = tmp_path / "company-profile.pdf"
    reference.write_bytes(b"%PDF-1.4")
    page.company_name.setText("Example Co")
    page.public_research.setChecked(True)
    page.regulatory_analysis.setChecked(True)
    page.industries._set_checked(
        page.industries._option_order[0],
        True,
    )
    page.business_models._set_checked("电商销售", True)
    page.influencer_promotion.selector.set_value("yes")
    next(iter(page.directions._buttons.values())).setChecked(True)
    page.indicator_count.selector.set_value(8)
    page.drop_zone.add_files([str(reference)])
    page._last_result = object()
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.Yes,
    )

    page._confirm_reset()

    assert page.company_name.text() == ""
    assert not page.public_research.isChecked()
    assert not page.regulatory_analysis.isChecked()
    assert page.industries.selected_values() == []
    assert page.directions.selected_values() == []
    assert page.influencer_promotion.value() is None
    assert not page.influencer_promotion.isVisible()
    assert page.indicator_count.value() is None
    assert page.drop_zone.attachments() == ()
    assert page._last_result is None
    assert page.feedback_label.text() == "已重置指标生成内容。"
    assert page._feedback_timer.isActive()
    page.close()


def test_ecommerce_form_shows_requires_and_clears_influencer_choice(qapp):
    page = MetricDiscoveryPage()
    page.show()
    qapp.processEvents()
    page.company_name.setText("Example Co")

    assert not page.influencer_promotion.isVisible()
    page.business_models._set_checked("电商销售", True)
    qapp.processEvents()
    assert page.influencer_promotion.isVisible()

    with pytest.raises(MetricDiscoveryContractError, match="达人推广"):
        page.build_request()

    page.influencer_promotion.selector.set_value("yes")
    request = page.build_request()
    assert request.company_information["ecommerce_marketing"][
        "uses_influencer_promotion"
    ] == "yes"

    page.business_models._set_checked("电商销售", False)
    qapp.processEvents()
    assert not page.influencer_promotion.isVisible()
    assert page.influencer_promotion.value() is None
    assert "ecommerce_marketing" not in page.build_request().company_information
    page.close()


def test_transient_metric_feedback_hides_after_timeout(qapp):
    page = MetricDiscoveryPage()
    page.show()
    page._show_form_error("已取消本次生成。", auto_hide_ms=20)

    QTest.qWait(50)
    qapp.processEvents()

    assert not page.feedback_label.isVisible()
    assert page.feedback_label.text() == ""
    page.close()


def test_metric_form_core_controls_are_visible_in_default_window(qapp):
    window = MainWindow()
    window.show()
    qapp.processEvents()

    QTest.mouseClick(window.start_page.metric_entry_button, Qt.LeftButton)
    qapp.processEvents()
    page = window.metric_page

    first_direction = next(iter(page.directions._buttons.values()))
    assert first_direction.isVisible()
    assert first_direction.height() > 0
    assert page.generate_button.isVisible()
    assert not page.findChildren(QComboBox)
    window.close()


def test_company_fields_use_flat_and_hierarchical_multi_selects(qapp):
    page = MetricDiscoveryPage()

    assert isinstance(page.industries, DropdownMultiSelect)
    assert page.industries._hierarchical is True
    assert page.products_services._hierarchical is True
    assert page.business_models._hierarchical is False
    assert page.customer_types._hierarchical is False
    assert "电商销售" in page.business_models._option_order
    assert "平台付费投流或自播" not in page.business_models._option_order
    assert (
        "达人推广（直播带货或内容种草）"
        not in page.business_models._option_order
    )
    page.close()


def test_research_enhancement_uses_clickable_switch_surface(qapp):
    page = MetricDiscoveryPage()
    page.show()
    qapp.processEvents()

    visible_copy = " ".join(
        label.text() for label in page._research_box.findChildren(QLabel)
    )
    assert "天眼查 AI" in visible_copy
    assert "天眼查 AI" in page.public_research.toolTip()
    assert not page.public_research.isChecked()
    assert not page._research_box.property("enhanced")

    QTest.mouseClick(page._research_box, Qt.LeftButton, pos=QPoint(12, 12))
    qapp.processEvents()

    assert page.public_research.isChecked()
    assert page._research_box.property("enhanced")
    assert page.public_research.accessibleName() == "企业情报增强"
    page.close()


def test_chinese_font_layout_keeps_enhancement_copy_and_reset_separated(qapp):
    page = MetricDiscoveryPage()
    page.resize(1500, 900)
    page.show()
    qapp.processEvents()

    for box in (page._research_box, page._regulatory_box):
        title = box.findChild(QLabel, "metricResearchTitle")
        hint = box.findChild(QLabel, "metricResearchHint")
        assert title is not None
        assert hint is not None
        title_bottom = title.mapTo(box, QPoint(0, title.height())).y()
        hint_top = hint.mapTo(box, QPoint(0, 0)).y()
        assert hint_top - title_bottom >= 4
        assert title.font().weight() <= 500

    reset_text_height = page.reset_button.fontMetrics().height()
    assert page.reset_button.height() >= reset_text_height + 14
    assert page.reset_button.font().weight() <= 500
    page.close()


def test_regulatory_analysis_uses_compact_clickable_switch_and_request(qapp):
    page = MetricDiscoveryPage()
    page.show()
    qapp.processEvents()

    visible_copy = " ".join(
        label.text() for label in page._regulatory_box.findChildren(QLabel)
    )
    assert "监管规则适用指引" in visible_copy
    assert "发行类第5号针对分析" in visible_copy
    assert not page.regulatory_analysis.isChecked()
    assert not page._regulatory_box.property("enhanced")
    assert page._regulatory_box.sizeHint().height() <= (
        page._research_box.sizeHint().height() + 4
    )

    QTest.mouseClick(
        page._regulatory_box,
        Qt.LeftButton,
        pos=QPoint(12, 12),
    )
    qapp.processEvents()

    request = page.build_request()
    assert request.regulatory_analysis_enabled is True
    assert page._regulatory_box.property("enhanced")
    assert "发行类第5号" in page.regulatory_analysis.toolTip()
    page.close()


def test_guidance_checkbox_groups_render_every_option(qapp):
    page = MetricDiscoveryPage()
    page.show()
    qapp.processEvents()

    for field in (page.directions, page.focuses):
        assert not hasattr(field, "expand_button")
        assert all(
            not checkbox.isHidden()
            for checkbox in field._buttons.values()
        )
        assert all(
            checkbox.objectName() == "metricChoiceCheckbox"
            for checkbox in field._buttons.values()
        )

    final_direction = next(reversed(page.directions._buttons.values()))
    QTest.mouseClick(final_direction, Qt.LeftButton)
    qapp.processEvents()
    assert final_direction.isChecked()
    page.close()


def test_company_and_guidance_cards_share_bottom_alignment(qapp):
    page = MetricDiscoveryPage()
    page.resize(1180, 780)
    page.show()
    qapp.processEvents()

    assert abs(
        page.company_card.geometry().bottom()
        - page.guidance_card.geometry().bottom()
    ) <= 1
    assert page.company_card.layout().alignment() & Qt.AlignTop
    assert page.guidance_card.layout().alignment() & Qt.AlignTop
    page.close()


def test_hierarchical_dropdown_switches_children_on_category_hover(qapp):
    page = MetricDiscoveryPage()
    popup = MultiSelectPopup(page.industries)
    first_category, first_labels = page.industries._groups[0]
    second_category, second_labels = page.industries._groups[1]

    assert popup._category_buttons[first_category].property("active")
    popup._category_buttons[second_category].hovered.emit()
    qapp.processEvents()
    visible_options = {
        checkbox.text()
        for checkbox in popup.children_host.findChildren(QCheckBox)
        if not checkbox.isHidden()
    }

    assert set(first_labels).isdisjoint(visible_options)
    assert set(second_labels).issubset(visible_options)
    assert popup._category_buttons[second_category].property("active")
    popup.close()
    page.close()


def test_dropdown_popup_uses_uniform_border_without_clipped_shadow(qapp):
    page = MetricDiscoveryPage()
    popup = MultiSelectPopup(page.industries)

    assert popup.panel.graphicsEffect() is None
    margins = popup.layout().contentsMargins()
    assert len(
        {margins.left(), margins.top(), margins.right(), margins.bottom()}
    ) == 1
    popup.close()
    page.close()


def test_other_selection_reveals_inline_input_and_enters_payload(qapp):
    page = MetricDiscoveryPage()
    page.company_name.setText("Example Co")
    page.industries._set_checked("机械设备制造", True)
    page.industries._set_other_enabled(True)
    page.industries.other_input.setText("新能源工程")

    request = page.build_request()

    assert not page.industries.other_input.isHidden()
    assert request.company_information["industries"] == ["机械设备制造"]
    assert request.company_information["industry_custom"] == ["新能源工程"]
    page.close()


def test_generate_action_is_fixed_in_header_without_bottom_bar(qapp):
    page = MetricDiscoveryPage()
    page.show()
    qapp.processEvents()
    visible_text = {
        label.text()
        for label in page.findChildren(QLabel)
        if label.isVisible()
    }

    assert page.generate_button.parentWidget().objectName() == "metricPageHeader"
    assert page.generate_button.text() == ""
    assert not page.generate_button.icon().isNull()
    assert "生成5--10项数据核查指标和客户资料清单" not in visible_text
    assert page.findChild(QWidget, "metricActionBar") is None
    page.close()


def test_form_content_ends_at_attachment_card_without_scroll_blank(qapp):
    page = MetricDiscoveryPage()
    page.resize(1000, 600)
    page.show()
    qapp.processEvents()
    trailing_space = (
        page.form_host.height()
        - page.attachment_card.geometry().bottom()
        - 1
    )

    assert trailing_space <= 24
    form_cards = page.form_host.findChildren(QWidget, "metricFormCard")
    # The guidance card now contains the regulatory and conditional marketing
    # controls; keep it bounded without compressing Chinese text vertically.
    assert max(card.height() for card in form_cards[:2]) <= 720
    assert page.additional_information.parentWidget().height() <= 130
    assert page.form_scroll.verticalScrollBar().maximum() <= 380
    page.form_scroll.verticalScrollBar().setValue(
        page.form_scroll.verticalScrollBar().maximum()
    )
    qapp.processEvents()
    attachment_bottom = page.attachment_card.mapTo(
        page.form_scroll.viewport(),
        QPoint(0, page.attachment_card.height()),
    ).y()
    assert attachment_bottom <= page.form_scroll.viewport().height() + 24
    page.close()


def test_guidance_card_content_stays_top_aligned(qapp):
    page = MetricDiscoveryPage()
    page.resize(1000, 600)
    page.show()
    qapp.processEvents()
    title = next(
        label
        for label in page.findChildren(QLabel, "metricCardTitle")
        if label.text().startswith("2")
    )
    subtitle = next(
        label
        for label in page.findChildren(QLabel, "metricCardSubtitle")
        if label.text() == "选择核查方向与重点"
    )
    first_content = next(
        label
        for label in page.findChildren(QLabel)
        if label.text() == "发行类第5号针对分析"
    )
    title_bottom = title.mapTo(page, QPoint(0, title.height())).y()
    subtitle_top = subtitle.mapTo(page, QPoint(0, 0)).y()
    subtitle_bottom = subtitle.mapTo(
        page,
        QPoint(0, subtitle.height()),
    ).y()
    first_content_top = first_content.mapTo(page, QPoint(0, 0)).y()

    assert subtitle_top - title_bottom <= 16
    assert first_content_top - subtitle_bottom <= 24
    page.close()


def test_metric_form_copy_is_direct_and_has_no_optional_suffix(qapp):
    page = MetricDiscoveryPage()
    page.show()
    qapp.processEvents()

    visible_copy = [
        widget.text()
        for widget in [
            *page.findChildren(QLabel),
            *page.findChildren(QAbstractButton),
        ]
        if widget.text()
    ]
    joined = "\n".join(visible_copy)

    assert "（选填）" not in joined
    assert "不是" not in joined
    assert "而是" not in joined
    page.close()


def test_portal_metric_entry_does_not_overlap_dataset_drop_zone(qapp):
    window = MainWindow()
    window.show()
    qapp.processEvents()
    page = window.start_page
    title_row = page.findChild(QWidget, "portalTitleRow")

    entry_top_left = page.metric_entry_button.mapTo(page, QPoint(0, 0))
    drop_top_left = page.drop_zone.mapTo(page, QPoint(0, 0))
    entry_bottom = entry_top_left.y() + page.metric_entry_button.height()

    assert title_row is not None
    assert page.metric_entry_button.parentWidget() is title_row
    assert entry_bottom < drop_top_left.y()
    assert page.drop_zone.height() >= page.drop_zone.minimumHeight()
    assert page.drop_zone.limit_label.isVisible()
    window.close()


def test_metric_attachment_area_rejects_excel(qapp, tmp_path):
    page = MetricDiscoveryPage()
    spreadsheet = tmp_path / "client-data.xlsx"
    spreadsheet.write_bytes(b"not really an xlsx")
    errors = []
    page.drop_zone.validation_failed.connect(errors.append)

    page.drop_zone.add_files([str(spreadsheet)])

    assert not page.drop_zone.attachments()
    assert errors
    assert "data-analysis module" in errors[0]
    page.close()


def test_metric_result_renders_expandable_data_request_cards(qapp):
    page = MetricDiscoveryPage()
    result = MetricDiscoveryResult.from_workflow_response(_workflow_response())

    page.show_result(result)
    page.show()
    qapp.processEvents()

    cards = page.result_host.findChildren(MetricResultCard)
    assert len(cards) == 5
    QTest.mouseClick(cards[0].toggle, Qt.LeftButton)
    qapp.processEvents()
    assert cards[0].body.isVisible()
    assert "Data-based indicator 1" in cards[0].toggle.text()
    page.close()


def test_metric_result_renders_regulatory_review_and_indicator_fields(qapp):
    page = MetricDiscoveryPage()
    result = MetricDiscoveryResult.from_workflow_response(
        _regulatory_workflow_response(),
        regulatory_analysis_required=True,
    )

    page.show_result(result)
    page.show()
    qapp.processEvents()

    visible_copy = " ".join(
        label.text() for label in page.result_host.findChildren(QLabel)
    )
    assert "发行类第5号 · 适用性判断" in visible_copy
    assert "5-19：待确认" in visible_copy
    assert "非数据核查程序" in visible_copy

    card = page.result_host.findChildren(MetricResultCard)[0]
    card.toggle.click()
    qapp.processEvents()
    card_copy = " ".join(label.text() for label in card.findChildren(QLabel))
    assert "第5号文依据" in card_copy
    assert "预期核查证据" in card_copy
    page.close()


def test_metric_generation_tracks_elapsed_time_and_shows_result_duration(qapp):
    page = MetricDiscoveryPage()
    result = MetricDiscoveryResult.from_workflow_response(_workflow_response())

    page.show_busy("正在生成")
    QTest.qWait(20)
    page.show_result(result)
    qapp.processEvents()

    assert not page._elapsed_ui_timer.isActive()
    assert page.result_duration_label.text().startswith("耗时 ")
    assert page.result_host.findChild(QWidget, "metricResultHero") is not None
    page.close()


def test_adjusted_metric_form_can_return_to_last_result(qapp):
    page = MetricDiscoveryPage()
    result = MetricDiscoveryResult.from_workflow_response(_workflow_response())
    page.show_result(result)
    page.show()
    qapp.processEvents()

    page.edit_button.click()
    qapp.processEvents()
    assert page.page_stack.currentIndex() == 0
    assert page.return_result_button.isVisible()

    page.return_result_button.click()
    qapp.processEvents()
    assert page.page_stack.currentIndex() == 1
    assert len(page.result_host.findChildren(MetricResultCard)) == 5
    page.close()


def test_business_indicator_mode_is_available_without_datasets(qapp):
    window = MainWindow()
    window.show()
    qapp.processEvents()

    QTest.mouseClick(window.start_page.metric_entry_button, Qt.LeftButton)
    qapp.processEvents()

    assert window.page_container.currentWidget() is window.metric_page
    assert window.mode_button.isVisible()
    assert window.mode_button.text() == "Mode: Business Indicators"
    assert not window.dataset_library_btn.isVisible()
    window.close()


def test_empty_analysis_mode_can_switch_to_indicators_and_back(qapp):
    window = MainWindow()
    window.show()
    window._start_new_task()
    qapp.processEvents()

    assert window._active_mode == "analysis"
    assert window.mode_button.isVisible()
    assert window.mode_button.isEnabled()
    assert window.mode_metric_action.isEnabled()
    assert window.mode_cleaning_action.isEnabled()

    window.mode_metric_action.trigger()
    QTest.qWait(220)
    qapp.processEvents()

    assert window._active_mode == "metric"
    assert window.page_container.currentWidget() is window.metric_page
    assert window.mode_analysis_action.isEnabled()

    window.mode_analysis_action.trigger()
    QTest.qWait(220)
    qapp.processEvents()

    assert window._active_mode == "analysis"
    assert window.page_container.currentWidget() is window.workspace
    assert window.mode_metric_action.isEnabled()
    window.close()


def test_indicator_first_route_fully_initializes_analysis_workspace(qapp):
    window = MainWindow()
    window.show()
    qapp.processEvents()

    QTest.mouseClick(window.start_page.metric_entry_button, Qt.LeftButton)
    qapp.processEvents()
    assert window._active_mode == "metric"
    assert not window._task_open

    window.mode_analysis_action.trigger()
    QTest.qWait(300)
    qapp.processEvents()

    assert window._task_open
    assert window._active_mode == "analysis"
    assert window.page_container.currentWidget() is window.workspace
    assert window.command_bar.geometry() == window._expanded_composer_rect()
    assert window._context_panel_open
    assert window.left_shell.isVisible()
    assert window.dataset_library_btn.isVisible()
    window.close()


def test_indicator_can_switch_to_cleaning_without_datasets(qapp):
    window = MainWindow()
    window.show()
    qapp.processEvents()

    QTest.mouseClick(window.start_page.metric_entry_button, Qt.LeftButton)
    qapp.processEvents()
    assert window.mode_cleaning_action.isEnabled()

    window.mode_cleaning_action.trigger()
    QTest.qWait(220)
    qapp.processEvents()

    assert window._active_mode == "cleaning"
    assert window.page_container.currentWidget() is window.cleaning_page
    assert window.cleaning_page.target_dataset is None
    assert not window.cleaning_page.scan_button.isEnabled()
    assert window.dataset_library_btn.isVisible()
    window.close()


def test_metric_error_hides_invalid_json_traceback():
    raw = """process exited with code 255
Traceback (most recent call last):
  File \"<fd3>\", line 61, in parse_json
json.decoder.JSONDecodeError: Expecting ',' delimiter: line 1030 column 8
ValueError: 指标生成结果不是合法JSON"""

    message = _friendly_metric_error(raw)

    assert message == (
        "Dify 生成的指标结果格式不完整，未能完成解析。"
        "请检查指标生成节点的结构化输出、最大输出长度和字段长度限制后重试。"
    )
    assert "Traceback" not in message


def test_metric_error_distinguishes_output_truncation():
    assert _friendly_metric_error("指标生成结果疑似因输出长度限制被截断") == (
        "Dify 生成的指标结果可能因输出长度限制被截断。"
        "请缩短单次生成内容，或提高模型节点的最大输出长度后重试。"
    )


def test_metric_error_hides_generic_dify_sandbox_traceback():
    message = _friendly_metric_error(
        "process exited with code 255\nTraceback (most recent call last): boom"
    )

    assert message == (
        "Dify 工作流内部节点执行失败。请在 Dify 运行日志中检查失败节点，"
        "修正后重新运行。"
    )


def test_metric_error_caps_unknown_backend_message():
    message = _friendly_metric_error("未知错误" * 300)

    assert len(message) == 502
    assert message.endswith("……")
