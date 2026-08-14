"""Contracts for business-analysis indicator discovery.

The indicator workflow is intentionally isolated from the existing data-analysis
workflow.  The desktop sends one JSON payload plus an optional Dify file-list
input, and expects a strictly data-based metric pack in return.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


REQUEST_SCHEMA_VERSION = "metric_discovery.request.v1"
RESPONSE_SCHEMA_VERSION = "metric_discovery.result.v1"

REGULATORY_GUIDANCE_NO5_ID = "csrs_issuance_guidance_no5"
REGULATORY_GUIDANCE_NO5_TITLE = "监管规则适用指引——发行类第5号"
REGULATORY_GUIDANCE_NO5_SECTION_TITLES = {
    "5-1": "增资或转让股份形成的股份支付",
    "5-2": "应收款项减值",
    "5-3": "客户资源或客户关系及企业合并涉及无形资产的判断",
    "5-4": "研发支出资本化",
    "5-5": "科研项目相关政府补助",
    "5-6": "有关涉税事项",
    "5-7": "持续经营能力",
    "5-8": "财务内控不规范情形",
    "5-9": "会计政策、会计估计变更和差错更正",
    "5-10": "现金交易核查",
    "5-11": "第三方回款核查",
    "5-12": "经销模式",
    "5-13": "通过互联网开展业务相关信息系统核查",
    "5-14": "信息系统专项核查",
    "5-15": "资金流水核查",
    "5-16": "尚未盈利或最近一期存在累计未弥补亏损",
    "5-17": "客户集中",
    "5-18": "投资收益占比",
    "5-19": "在审期间分红及转增股本",
}
REGULATORY_GUIDANCE_NO5_SECTIONS = tuple(
    REGULATORY_GUIDANCE_NO5_SECTION_TITLES
)
REGULATORY_GUIDANCE_NO5_SECTION_FOCUSES = {
    "5-1": "核查股份变动商业实质、公允价值、等待期及股份支付会计处理。",
    "5-2": "核查预期信用损失组合、账龄连续性、特殊回款方式及减值充分性。",
    "5-3": "核查客户关系的合同权利和控制、企业合并无形资产识别、估值及减值。",
    "5-4": "核查研发阶段划分、资本化条件证据、费用归集真实性及相关内控。",
    "5-5": "核查科研资金商业实质、收入或政府补助分类、损益列报及披露。",
    "5-6": "核查税收优惠条件及持续性、税率计提、补税与滞纳金会计处理。",
    "5-7": "核查宏观、行业、客户供应商、技术、财务趋势及营运资金对持续经营的影响。",
    "5-8": "核查转贷、无真实背景票据、资金拆借、个人账户、资金占用等不规范事项及整改。",
    "5-9": "核查会计政策估计变更和差错更正的依据、审批、一贯性、内控及盈余操纵风险。",
    "5-10": "核查现金交易必要性、交易对手、业务资金一致性、体外循环及现金内控。",
    "5-11": "核查第三方回款真实性、完整性、商业合理性、关联关系及资金实物流一致性。",
    "5-12": "核查经销商业合理性、内控、终端销售、进销存、返利退货、物流回款及收入真实性。",
    "5-13": "核查互联网业务系统可靠性、用户与交易真实性、支付物流及业务财务数据一致性。",
    "5-14": "核查IT控制、基础数据质量、业务财务资金一致性、多指标复核、反舞弊及异常跟进。",
    "5-15": "核查银行账户完整性、资金流水范围和异常标准、异常往来及体外资金循环。",
    "5-16": "核查未盈利或累计亏损原因、投入产出规律、现金流及持续经营影响。",
    "5-17": "核查客户集中原因、重大依赖、关联关系、合作稳定性及终端客户真实性。",
    "5-18": "核查合并范围外投资收益贡献、主业持续经营、被投资企业相关性及披露。",
    "5-19": "核查在审期间分红或转增的必要性、恰当性、决策程序及财务和股东影响。",
}
REGULATORY_GUIDANCE_NO5_PRIORITY_SECTIONS = (
    "5-11",
    "5-12",
    "5-13",
    "5-14",
)

ECOMMERCE_BUSINESS_MODEL = "电商销售"
INFLUENCER_PLAYBOOK_ID = "ecommerce_influencer_effectiveness.v1"
INFLUENCER_PROMOTION_STATUSES = frozenset({"yes", "no", "unknown"})
INFLUENCER_SCOPE_DEFINITION = (
    "达人直播带货",
    "达人短视频或图文种草",
    "达人橱窗、商品链接或专属推广链接",
    "MCN机构或达人合作投放",
)
INFLUENCER_REQUIRED_FAMILIES = (
    "platform_roi_trend",
    "spend_sales_correlation",
    "influencer_sales_concentration",
    "influencer_roi_efficiency",
    "platform_ledger_reconciliation",
)
INFLUENCER_RECOMMENDED_FAMILIES = (
    "promotion_period_efficiency",
    "influencer_dependency_trend",
    "order_attribution_integrity",
)
INFLUENCER_SPECIFIC_FAMILIES = (
    "influencer_sales_concentration",
    "influencer_roi_efficiency",
    "influencer_dependency_trend",
)
INFLUENCER_METRIC_FAMILY_CATALOG = (
    {
        "family_id": "platform_roi_trend",
        "title": "各平台投流ROI及趋势",
        "definition": "按平台、期间比较归因销售额与推广消耗的投入产出效率。",
        "formula_guidance": "ROI=可归因销售额/推广消耗；同时披露销售额口径和退款处理。",
    },
    {
        "family_id": "spend_sales_correlation",
        "title": "推广消耗与销售表现相关性",
        "definition": "检验推广投入与成交金额、订单量、访客或转化率的同步和滞后关系。",
        "formula_guidance": "分日或分活动计算相关性及滞后相关性；相关性不得表述为因果。",
    },
    {
        "family_id": "influencer_sales_concentration",
        "title": "达人带货销售集中度",
        "definition": "衡量销售额、订单量在头部达人或MCN的集中与依赖程度。",
        "formula_guidance": "Top N达人销售额/达人推广销售额，并披露N、退款及取消订单口径。",
    },
    {
        "family_id": "influencer_roi_efficiency",
        "title": "达人投放ROI与效率分层",
        "definition": "按达人、平台、活动比较费用、归因成交、佣金及退款后的效率。",
        "formula_guidance": "达人ROI=达人归因净销售额/(达人坑位费+佣金+投流等可归集费用)。",
    },
    {
        "family_id": "platform_ledger_reconciliation",
        "title": "平台结算与业务财务对账",
        "definition": "核对平台订单、退款、佣金、投流账单、结算单、收款和财务入账。",
        "formula_guidance": "按订单号、结算单号和期间构建业务—平台—资金—财务差异桥。",
    },
    {
        "family_id": "promotion_period_efficiency",
        "title": "推广期与非推广期效率对比",
        "definition": "比较投放前、中、后的流量、转化、客单价、退款和净销售表现。",
        "formula_guidance": "统一窗口及商品范围，分别列示增量与基准，不直接宣称推广导致增长。",
    },
    {
        "family_id": "influencer_dependency_trend",
        "title": "达人依赖度变化",
        "definition": "跟踪达人推广销售占比、头部达人贡献及合作稳定性的期间变化。",
        "formula_guidance": "达人推广净销售额/全渠道净销售额，并按月或季度展示趋势。",
    },
    {
        "family_id": "order_attribution_integrity",
        "title": "达人订单归因完整性与真实性",
        "definition": "检验达人、内容、链接、订单、支付、退款和结算之间的可追溯性。",
        "formula_guidance": "计算可完整追溯订单占比、重复归因率、缺失归因率及异常退款率。",
    },
)

SUPPORTED_REFERENCE_SUFFIXES = {
    ".doc",
    ".docx",
    ".md",
    ".pdf",
    ".ppt",
    ".pptx",
    ".rtf",
    ".txt",
}
SPREADSHEET_SUFFIXES = {".csv", ".xls", ".xlsb", ".xlsm", ".xlsx"}


class MetricDiscoveryContractError(ValueError):
    """Raised when a request or result violates the workflow contract."""


@dataclass(frozen=True)
class ReferenceAttachment:
    """Local reference material selected for one indicator request."""

    path: str
    name: str
    suffix: str
    size_bytes: int

    @classmethod
    def from_path(cls, file_path: str | Path) -> "ReferenceAttachment":
        path = Path(file_path).expanduser()
        suffix = path.suffix.lower()
        if suffix in SPREADSHEET_SUFFIXES:
            raise MetricDiscoveryContractError(
                f"{path.name}: spreadsheet data belongs in the data-analysis module."
            )
        if suffix not in SUPPORTED_REFERENCE_SUFFIXES:
            supported = ", ".join(sorted(SUPPORTED_REFERENCE_SUFFIXES))
            raise MetricDiscoveryContractError(
                f"{path.name}: unsupported reference type. Supported: {supported}."
            )
        if not path.is_file():
            raise MetricDiscoveryContractError(
                f"{path.name or path}: the file is unavailable."
            )
        try:
            size_bytes = path.stat().st_size
        except OSError as exc:
            raise MetricDiscoveryContractError(
                f"{path.name}: the file cannot be read."
            ) from exc
        return cls(
            path=str(path.resolve()),
            name=path.name,
            suffix=suffix,
            size_bytes=size_bytes,
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "extension": self.suffix,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class MetricDiscoveryRequest:
    """A complete, versioned request passed to the Dify metric workflow."""

    company_information: dict[str, Any]
    indicator_guidance: dict[str, Any]
    attachments: tuple[ReferenceAttachment, ...] = ()
    public_research_enabled: bool = False
    regulatory_analysis_enabled: bool = False
    request_id: str = field(default_factory=lambda: str(uuid4()))
    submitted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def validate(self) -> None:
        count = self.indicator_guidance.get("indicator_count")
        if count is not None:
            try:
                normalized = int(count)
            except (TypeError, ValueError) as exc:
                raise MetricDiscoveryContractError(
                    "Indicator count must be a whole number from 5 to 10."
                ) from exc
            if not 5 <= normalized <= 10:
                raise MetricDiscoveryContractError(
                    "Indicator count must be between 5 and 10."
                )

        business_models = self.company_information.get("business_models") or []
        if ECOMMERCE_BUSINESS_MODEL in business_models:
            ecommerce_marketing = self.company_information.get(
                "ecommerce_marketing"
            )
            if not isinstance(ecommerce_marketing, dict):
                raise MetricDiscoveryContractError(
                    "已选择“电商销售”，请确认是否使用达人推广。"
                )
            status = str(
                ecommerce_marketing.get("uses_influencer_promotion") or ""
            ).strip()
            if status not in INFLUENCER_PROMOTION_STATUSES:
                raise MetricDiscoveryContractError(
                    "已选择“电商销售”，请确认是否使用达人推广。"
                )
            if ecommerce_marketing.get("user_confirmed") is not True:
                raise MetricDiscoveryContractError(
                    "达人推广选项必须由用户明确确认。"
                )

        if not self.has_meaningful_input():
            raise MetricDiscoveryContractError(
                "Provide at least one company detail, indicator preference, "
                "or reference document before generating indicators."
            )

    def has_meaningful_input(self) -> bool:
        if self.regulatory_analysis_enabled:
            return True
        if self.attachments:
            return True
        if _contains_meaningful_value(self.company_information):
            return True
        return _contains_meaningful_value(self.indicator_guidance)

    def to_payload(self) -> dict[str, Any]:
        self.validate()
        company_information = dict(self.company_information)
        indicator_guidance = dict(self.indicator_guidance)
        promotion_status = self.influencer_promotion_status()
        if promotion_status:
            company_information["ecommerce_marketing"] = {
                "uses_influencer_promotion": promotion_status,
                "user_confirmed": True,
                "scope_definition": list(INFLUENCER_SCOPE_DEFINITION),
            }
            existing_playbooks = indicator_guidance.get("metric_playbooks") or []
            if not isinstance(existing_playbooks, list):
                existing_playbooks = []
            indicator_guidance["metric_playbooks"] = [
                item
                for item in existing_playbooks
                if not isinstance(item, dict)
                or item.get("playbook_id") != INFLUENCER_PLAYBOOK_ID
            ] + [_build_influencer_playbook(promotion_status)]
        indicator_guidance["regulatory_analysis_enabled"] = (
            self.regulatory_analysis_enabled
        )
        indicator_guidance["generation_mode"] = (
            "issuance_guidance_no5_special"
            if self.regulatory_analysis_enabled
            else "standard_it_audit"
        )
        indicator_fields = [
            "target_basis",
            "analysis_objective",
            "definition",
            "analysis_method",
            "analysis_grain",
            "data_requirements",
            "client_request_guidance",
            "key_scope_questions",
            "potential_anomalies",
            "data_acquisition_difficulty",
            "priority",
        ]
        if self.regulatory_analysis_enabled:
            indicator_fields.extend(
                [
                    "regulatory_references",
                    "population_definition",
                    "coverage_period",
                    "exception_rules",
                    "follow_up_procedures",
                    "expected_evidence",
                ]
            )
        if promotion_status == "yes":
            indicator_fields.extend(
                ["metric_family_id", "playbook_id", "formula", "dimensions"]
            )
        return {
            "schema_version": REQUEST_SCHEMA_VERSION,
            "request_id": self.request_id,
            "submitted_at": self.submitted_at,
            "locale": "zh-CN",
            "company_information": company_information,
            "indicator_guidance": indicator_guidance,
            "reference_files": [
                attachment.metadata() for attachment in self.attachments
            ],
            "research_preferences": {
                "public_information_enabled": self.public_research_enabled,
                "company_data_role": (
                    "Use public company data only as supplementary identity and "
                    "business context. Do not treat registered business scope as "
                    "proof of the actual business model."
                ),
            },
            "regulatory_guidance": {
                "framework_id": REGULATORY_GUIDANCE_NO5_ID,
                "title": REGULATORY_GUIDANCE_NO5_TITLE,
                "role": "primary_it_audit_methodology",
                "baseline_applies": True,
                "special_analysis_enabled": (
                    self.regulatory_analysis_enabled
                ),
                "covered_sections": list(
                    REGULATORY_GUIDANCE_NO5_SECTIONS
                ),
                "section_catalog": [
                    {
                        "section": section,
                        "title": title,
                        "audit_focus": (
                            REGULATORY_GUIDANCE_NO5_SECTION_FOCUSES[section]
                        ),
                        "priority": (
                            section
                            in REGULATORY_GUIDANCE_NO5_PRIORITY_SECTIONS
                        ),
                    }
                    for section, title in (
                        REGULATORY_GUIDANCE_NO5_SECTION_TITLES.items()
                    )
                ],
                "priority_sections": list(
                    REGULATORY_GUIDANCE_NO5_PRIORITY_SECTIONS
                ),
                "priority_section_rules": {
                    "5-11": (
                        "Trace third-party repayments to contracts, payer "
                        "identity, fund flows, commercial substance, and "
                        "accounting treatment."
                    ),
                    "5-12": (
                        "For distributor models, test end-customer sales, "
                        "inventory, returns, pricing, rebates, logistics, and "
                        "business-finance-fund consistency."
                    ),
                    "5-13": (
                        "For internet-based business, test system reliability, "
                        "user and transaction authenticity, terminal-user "
                        "behavior, payments, logistics, and financial links."
                    ),
                    "5-14": (
                        "For system-dependent operations, cover IT general "
                        "controls, base-data quality, business-finance-fund "
                        "consistency, multi-indicator review, anti-fraud "
                        "scenarios, and follow-up of suspected exceptions."
                    ),
                },
                "interpretation_rules": [
                    "Assess applicability before designing indicators.",
                    "Keep unknown facts unknown; never infer not applicable from missing input.",
                    "Preserve objective commercial analysis while applying IT-audit evidence standards.",
                    "Separate data-analysis indicators from non-data audit procedures.",
                    "Do not produce an unqualified regulatory or audit opinion.",
                ],
            },
            "output_requirements": {
                "language": "zh-CN",
                "indicator_count": self.indicator_guidance.get(
                    "indicator_count"
                ),
                "minimum_indicator_count": 5,
                "maximum_indicator_count": 10,
                "data_based_only": True,
                "it_audit_oriented": True,
                "regulatory_special_analysis": (
                    self.regulatory_analysis_enabled
                ),
                "each_indicator_must_include": indicator_fields,
                "data_requirement_must_include": [
                    "dataset_name",
                    "business_purpose",
                    "grain",
                    "recommended_period",
                    "required_fields",
                    "join_keys",
                    "scope_and_completeness",
                ],
                "reject_generic_metrics_without_requestable_data": True,
                "merge_data_requests_across_indicators": True,
                "required_metric_families": (
                    list(INFLUENCER_REQUIRED_FAMILIES)
                    if promotion_status == "yes"
                    else []
                ),
                "forbidden_metric_families": (
                    list(INFLUENCER_SPECIFIC_FAMILIES)
                    if promotion_status == "no"
                    else []
                ),
                "regulatory_review_must_include": (
                    [
                        "applicability_assessment",
                        "non_data_procedures",
                        "scope_limitations",
                    ]
                    if self.regulatory_analysis_enabled
                    else []
                ),
            },
        }

    def influencer_promotion_status(self) -> str:
        ecommerce_marketing = self.company_information.get(
            "ecommerce_marketing"
        )
        if not isinstance(ecommerce_marketing, dict):
            return ""
        status = str(
            ecommerce_marketing.get("uses_influencer_promotion") or ""
        ).strip()
        return status if status in INFLUENCER_PROMOTION_STATUSES else ""

    def required_metric_families(self) -> tuple[str, ...]:
        if self.influencer_promotion_status() == "yes":
            return INFLUENCER_REQUIRED_FAMILIES
        return ()

    def forbidden_metric_families(self) -> tuple[str, ...]:
        if self.influencer_promotion_status() == "no":
            return INFLUENCER_SPECIFIC_FAMILIES
        return ()

    def to_json(self) -> str:
        return json.dumps(
            self.to_payload(),
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def with_selected_company(
        self,
        selected_company: dict[str, Any],
        *,
        original_query: str | None = None,
    ) -> "MetricDiscoveryRequest":
        """Return the same request anchored to a user-confirmed legal entity."""
        company_name = str(
            selected_company.get("company_name") or ""
        ).strip()
        if not company_name:
            raise MetricDiscoveryContractError(
                "The selected company has no registered name."
            )
        company_information = dict(self.company_information)
        source_query = str(
            original_query
            or company_information.get("company_query")
            or company_information.get("company_name")
            or ""
        ).strip()
        company_information["company_query"] = source_query
        company_information["company_name"] = company_name
        company_information["selected_company"] = {
            key: str(selected_company.get(key) or "").strip()
            for key in (
                "company_name",
                "company_id",
                "credit_code",
                "status",
                "legal_representative",
                "established_date",
            )
        }
        return replace(self, company_information=company_information)


@dataclass(frozen=True)
class MetricIndicator:
    indicator_id: str
    metric_family_id: str
    playbook_id: str
    title: str
    category: str
    priority: str
    target_basis: str
    analysis_objective: str
    definition: str
    formula: str
    analysis_grain: str
    dimensions: tuple[str, ...]
    analysis_method: tuple[str, ...]
    data_requirements: tuple[dict[str, Any], ...]
    client_request_guidance: str
    key_scope_questions: tuple[str, ...]
    potential_anomalies: tuple[str, ...]
    data_acquisition_difficulty: str
    evidence_basis: tuple[str, ...]
    assumptions: tuple[str, ...]
    regulatory_references: tuple[str, ...] = ()
    population_definition: str = ""
    coverage_period: str = ""
    exception_rules: tuple[str, ...] = ()
    follow_up_procedures: tuple[str, ...] = ()
    expected_evidence: tuple[str, ...] = ()
    scope_limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class MetricDiscoveryResult:
    """Validated result returned by the dedicated Dify workflow."""

    summary: str
    indicators: tuple[MetricIndicator, ...]
    consolidated_data_requests: tuple[dict[str, Any], ...]
    assumptions: tuple[str, ...]
    source_notes: tuple[str, ...]
    regulatory_review: dict[str, Any] = field(default_factory=dict)
    workflow_run_id: str = ""
    raw_outputs: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_workflow_response(
        cls,
        response: dict[str, Any],
        *,
        regulatory_analysis_required: bool = False,
        required_metric_families: tuple[str, ...] = (),
        forbidden_metric_families: tuple[str, ...] = (),
    ) -> "MetricDiscoveryResult":
        data = response.get("data") or {}
        if not isinstance(data, dict):
            raise MetricDiscoveryContractError(
                "The metric workflow response has no data object."
            )
        status = str(data.get("status") or "").strip().lower()
        if status and status != "succeeded":
            raise MetricDiscoveryContractError(
                str(data.get("error") or "The metric workflow failed.")
            )
        outputs = data.get("outputs") or {}
        if not isinstance(outputs, dict):
            raise MetricDiscoveryContractError(
                "The metric workflow outputs must be an object."
            )
        payload = _extract_result_payload(outputs)
        indicators_raw = payload.get("indicators") or []
        if not isinstance(indicators_raw, list):
            raise MetricDiscoveryContractError(
                "The metric workflow must return an indicators array."
            )
        if not 5 <= len(indicators_raw) <= 10:
            raise MetricDiscoveryContractError(
                "The metric workflow must return between 5 and 10 indicators; "
                f"received {len(indicators_raw)}."
            )

        indicators = tuple(
            _parse_indicator(item, index)
            for index, item in enumerate(indicators_raw, start=1)
        )
        regulatory_review = payload.get("regulatory_review") or {}
        if not isinstance(regulatory_review, dict):
            raise MetricDiscoveryContractError(
                "The regulatory_review output must be an object."
            )
        if regulatory_analysis_required:
            _validate_regulatory_review(
                regulatory_review,
                indicators,
            )
        if required_metric_families:
            _validate_metric_family_coverage(
                indicators,
                required_metric_families,
            )
        if forbidden_metric_families:
            _validate_forbidden_metric_families(
                indicators,
                forbidden_metric_families,
            )
        consolidated = payload.get("consolidated_data_requests") or []
        if not isinstance(consolidated, list):
            consolidated = []
        return cls(
            summary=_as_text(
                payload.get("summary")
                or payload.get("business_summary")
                or "已生成可用于数据核查的分析指标。"
            ),
            indicators=indicators,
            consolidated_data_requests=tuple(
                item for item in consolidated if isinstance(item, dict)
            ),
            assumptions=_string_tuple(payload.get("assumptions")),
            source_notes=_string_tuple(payload.get("source_notes")),
            regulatory_review=regulatory_review,
            workflow_run_id=_as_text(
                response.get("workflow_run_id") or data.get("id")
            ),
            raw_outputs=outputs,
        )


def _extract_result_payload(outputs: dict[str, Any]) -> dict[str, Any]:
    for key in ("metric_pack", "result", "structured_output", "answer"):
        candidate = outputs.get(key)
        if isinstance(candidate, dict):
            return candidate
        if isinstance(candidate, str) and candidate.strip():
            text = _strip_json_fence(candidate)
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    if isinstance(outputs.get("indicators"), list):
        return outputs
    raise MetricDiscoveryContractError(
        "The metric workflow did not return metric_pack JSON."
    )


def _parse_indicator(item: Any, index: int) -> MetricIndicator:
    if not isinstance(item, dict):
        raise MetricDiscoveryContractError(
            f"Indicator {index} must be an object."
        )
    title = _as_text(item.get("title") or item.get("indicator_name"))
    target_basis = _as_text(
        item.get("target_basis")
        or item.get("rationale")
        or item.get("applicability")
    )
    objective = _as_text(
        item.get("analysis_objective")
        or item.get("objective")
        or item.get("verification_question")
    )
    method = _string_tuple(
        item.get("analysis_method")
        or item.get("method_steps")
        or item.get("method")
    )
    requirements = item.get("data_requirements") or item.get("datasets") or []
    guidance = _as_text(
        item.get("client_request_guidance")
        or item.get("request_guidance")
        or item.get("recommended_request_wording")
    )
    missing = []
    if not title:
        missing.append("title")
    if not target_basis:
        missing.append("target_basis")
    if not objective:
        missing.append("analysis_objective")
    if not method:
        missing.append("analysis_method")
    if not isinstance(requirements, list) or not requirements:
        missing.append("data_requirements")
    if not guidance:
        missing.append("client_request_guidance")
    if missing:
        raise MetricDiscoveryContractError(
            f"Indicator {index} is not data-based; missing "
            + ", ".join(missing)
            + "."
        )

    normalized_requirements = tuple(
        _parse_data_requirement(requirement, index, req_index)
        for req_index, requirement in enumerate(requirements, start=1)
    )
    return MetricIndicator(
        indicator_id=_as_text(item.get("indicator_id") or f"M{index:02d}"),
        metric_family_id=_as_text(item.get("metric_family_id")),
        playbook_id=_as_text(item.get("playbook_id")),
        title=title,
        category=_as_text(item.get("category") or "综合分析"),
        priority=_as_text(item.get("priority") or "中"),
        target_basis=target_basis,
        analysis_objective=objective,
        definition=_as_text(item.get("definition")),
        formula=_as_text(item.get("formula") or item.get("calculation")),
        analysis_grain=_as_text(
            item.get("analysis_grain") or item.get("grain")
        ),
        dimensions=_string_tuple(item.get("dimensions")),
        analysis_method=method,
        data_requirements=normalized_requirements,
        client_request_guidance=guidance,
        key_scope_questions=_string_tuple(
            item.get("key_scope_questions")
            or item.get("scope_questions")
        ),
        potential_anomalies=_string_tuple(
            item.get("potential_anomalies")
            or item.get("anomalies")
        ),
        data_acquisition_difficulty=_as_text(
            item.get("data_acquisition_difficulty")
            or item.get("difficulty")
            or "待评估"
        ),
        evidence_basis=_string_tuple(
            item.get("evidence_basis") or item.get("sources")
        ),
        assumptions=_string_tuple(item.get("assumptions")),
        regulatory_references=_string_tuple(
            item.get("regulatory_references")
            or item.get("regulatory_refs")
        ),
        population_definition=_as_text(item.get("population_definition")),
        coverage_period=_as_text(item.get("coverage_period")),
        exception_rules=_string_tuple(item.get("exception_rules")),
        follow_up_procedures=_string_tuple(
            item.get("follow_up_procedures")
        ),
        expected_evidence=_string_tuple(item.get("expected_evidence")),
        scope_limitations=_string_tuple(item.get("scope_limitations")),
    )


def _build_influencer_playbook(status: str) -> dict[str, Any]:
    if status == "yes":
        coverage_policy = "mandatory"
        required_families = list(INFLUENCER_REQUIRED_FAMILIES)
        recommended_families = list(INFLUENCER_RECOMMENDED_FAMILIES)
        enabled = True
    elif status == "unknown":
        coverage_policy = "conditional"
        required_families = []
        recommended_families = [
            *INFLUENCER_REQUIRED_FAMILIES,
            *INFLUENCER_RECOMMENDED_FAMILIES,
        ]
        enabled = True
    else:
        coverage_policy = "excluded"
        required_families = []
        recommended_families = []
        enabled = False
    return {
        "playbook_id": INFLUENCER_PLAYBOOK_ID,
        "enabled": enabled,
        "user_answer": status,
        "coverage_policy": coverage_policy,
        "required_metric_families": required_families,
        "recommended_metric_families": recommended_families,
        "forbidden_metric_families": (
            list(INFLUENCER_SPECIFIC_FAMILIES) if status == "no" else []
        ),
        "metric_family_catalog": [
            dict(item) for item in INFLUENCER_METRIC_FAMILY_CATALOG
        ],
        "generation_rules": [
            "电商销售本身不能作为使用达人推广的证据；仅以用户明确选择为准。",
            "明确区分销售额、净销售额、GSV/GMV、佣金和推广消耗口径。",
            "相关性不得表述为因果关系。",
            "达人、内容、商品、订单、支付、退款、结算与财务记录应可追溯。",
            "unknown状态只能生成待确认的条件性指标，不得把达人推广写成已知事实。",
        ],
    }


def _validate_metric_family_coverage(
    indicators: tuple[MetricIndicator, ...],
    required_families: tuple[str, ...],
) -> None:
    covered = {
        indicator.metric_family_id
        for indicator in indicators
        if indicator.playbook_id == INFLUENCER_PLAYBOOK_ID
    }
    missing = [family for family in required_families if family not in covered]
    if missing:
        raise MetricDiscoveryContractError(
            "达人推广专项指标结果不完整；缺少指标族："
            + "、".join(missing)
            + "。请确认已按项目说明更新并发布 Dify 指标工作流。"
        )


def _validate_forbidden_metric_families(
    indicators: tuple[MetricIndicator, ...],
    forbidden_families: tuple[str, ...],
) -> None:
    forbidden = set(forbidden_families)
    returned = sorted(
        {
            indicator.metric_family_id
            for indicator in indicators
            if indicator.metric_family_id in forbidden
        }
    )
    if returned:
        raise MetricDiscoveryContractError(
            "用户已确认未使用达人推广，但结果仍包含达人专属指标族："
            + "、".join(returned)
            + "。请检查并重新发布 Dify 指标工作流。"
        )


def _validate_regulatory_review(
    review: dict[str, Any],
    indicators: tuple[MetricIndicator, ...],
) -> None:
    if not review:
        raise MetricDiscoveryContractError(
            "The published Dify workflow did not return the required "
            "regulatory_review for the Issuance Guidance No. 5 analysis."
        )

    applicability = review.get("applicability_assessment")
    if not isinstance(applicability, list):
        raise MetricDiscoveryContractError(
            "regulatory_review.applicability_assessment must be an array."
        )
    if len(applicability) != len(REGULATORY_GUIDANCE_NO5_SECTIONS):
        raise MetricDiscoveryContractError(
            "The regulatory applicability assessment must contain exactly "
            "one entry for each section from 5-1 through 5-19."
        )

    covered_sections = []
    allowed_statuses = {"适用", "不适用", "待确认"}
    for item in applicability:
        if not isinstance(item, dict):
            raise MetricDiscoveryContractError(
                "Every regulatory applicability entry must be an object."
            )
        section = _as_text(item.get("section"))
        status = _as_text(item.get("status"))
        basis = _as_text(item.get("basis"))
        if status not in allowed_statuses:
            raise MetricDiscoveryContractError(
                f"Regulatory section {section or 'unknown'} has an invalid "
                "status; use 适用, 不适用, or 待确认."
            )
        if not basis:
            raise MetricDiscoveryContractError(
                f"Regulatory section {section or 'unknown'} must explain its "
                "applicability basis."
            )
        covered_sections.append(section)

    duplicate_sections = {
        section
        for section in covered_sections
        if covered_sections.count(section) > 1
    }
    if duplicate_sections:
        raise MetricDiscoveryContractError(
            "The regulatory applicability assessment contains duplicate "
            "sections: "
            + ", ".join(sorted(duplicate_sections, key=_section_sort_key))
            + "."
        )
    covered_section_set = set(covered_sections)
    missing_sections = (
        set(REGULATORY_GUIDANCE_NO5_SECTIONS) - covered_section_set
    )
    if missing_sections:
        raise MetricDiscoveryContractError(
            "The regulatory applicability assessment is incomplete; missing "
            + ", ".join(sorted(missing_sections, key=_section_sort_key))
            + "."
        )

    procedures = review.get("non_data_procedures")
    limitations = review.get("scope_limitations")
    if (
        not isinstance(procedures, list)
        or not procedures
        or not all(_as_text(item) for item in procedures)
    ):
        raise MetricDiscoveryContractError(
            "regulatory_review.non_data_procedures must contain at least one "
            "IT-audit procedure."
        )
    if not isinstance(limitations, list) or not all(
        _as_text(item) for item in limitations
    ):
        raise MetricDiscoveryContractError(
            "regulatory_review.scope_limitations must be an array of text."
        )

    for index, indicator in enumerate(indicators, start=1):
        missing = []
        if not indicator.regulatory_references:
            missing.append("regulatory_references")
        if not indicator.population_definition:
            missing.append("population_definition")
        if not indicator.coverage_period:
            missing.append("coverage_period")
        if not indicator.exception_rules:
            missing.append("exception_rules")
        if not indicator.follow_up_procedures:
            missing.append("follow_up_procedures")
        if not indicator.expected_evidence:
            missing.append("expected_evidence")
        if missing:
            raise MetricDiscoveryContractError(
                f"Regulatory indicator {index} is incomplete; missing "
                + ", ".join(missing)
                + "."
            )
        invalid_references = [
            reference
            for reference in indicator.regulatory_references
            if _regulatory_section_root(reference)
            not in REGULATORY_GUIDANCE_NO5_SECTIONS
        ]
        if invalid_references:
            raise MetricDiscoveryContractError(
                f"Regulatory indicator {index} contains unsupported "
                "references: "
                + ", ".join(invalid_references)
                + "."
            )


def _regulatory_section_root(reference: str) -> str:
    match = re.match(r"^(5-(?:[1-9]|1[0-9]))(?:\D|$)", reference.strip())
    return match.group(1) if match else ""


def _section_sort_key(section: str) -> int:
    try:
        return int(section.split("-", 1)[1])
    except (IndexError, ValueError):
        return 999


def _parse_data_requirement(
    item: Any,
    indicator_index: int,
    requirement_index: int,
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise MetricDiscoveryContractError(
            f"Indicator {indicator_index} data requirement "
            f"{requirement_index} must be an object."
        )
    dataset_name = _as_text(
        item.get("dataset_name")
        or item.get("name")
        or item.get("table_name")
    )
    grain = _as_text(item.get("grain") or item.get("data_grain"))
    required_fields = _string_tuple(
        item.get("required_fields") or item.get("fields")
    )
    missing = []
    if not dataset_name:
        missing.append("dataset_name")
    if not grain:
        missing.append("grain")
    if not required_fields:
        missing.append("required_fields")
    if missing:
        raise MetricDiscoveryContractError(
            f"Indicator {indicator_index} data requirement "
            f"{requirement_index} is incomplete; missing "
            + ", ".join(missing)
            + "."
        )
    normalized = dict(item)
    normalized["dataset_name"] = dataset_name
    normalized["grain"] = grain
    normalized["required_fields"] = list(required_fields)
    normalized["join_keys"] = list(
        _string_tuple(item.get("join_keys") or item.get("keys"))
    )
    return normalized


def _contains_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_contains_meaningful_value(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_meaningful_value(item) for item in value)
    if isinstance(value, bool):
        return value
    return True


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ()
        parts = [
            re.sub(r"^\s*(?:[-*•]|\d+[.)、])\s*", "", line).strip()
            for line in stripped.splitlines()
        ]
        return tuple(part for part in parts if part)
    if isinstance(value, (list, tuple, set)):
        return tuple(
            text
            for item in value
            if (text := _as_text(item))
        )
    text = _as_text(value)
    return (text,) if text else ()


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _strip_json_fence(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and lines[0].lstrip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()
