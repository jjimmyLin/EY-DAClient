# 商业分析指标生成 — Dify 工作流契约与整体框架

This workflow is a separate Dify Workflow app. It must not replace or modify
the existing data-analysis app that accepts `task_type`, `context`, and `query`.

The first release should use a deterministic Workflow rather than an Agent.
The desktop owns form interaction, local file selection, request validation,
threading, cancellation, and result rendering. Dify owns document extraction,
天眼查 AI / public research, evidence normalization, indicator reasoning, and
the final structured output. `《监管规则适用指引——发行类第5号》` is the
primary methodology baseline for IT-audit-oriented indicator generation. The
special-analysis switch strengthens the same workflow; it must not start a
second Dify run.

## 1. Start node

Create exactly these inputs:

| Variable | Dify type | Required | Recommended limit |
|---|---|---:|---:|
| `request_payload` | Paragraph | Yes | 60,000+ characters |
| `reference_files` | File List / Document | No | 10 files |

`request_payload` is the complete versioned JSON request. The file list is the
only separate input because Dify file variables cannot be embedded as local
desktop paths inside JSON.

The client uploads each reference document to `POST /files/upload`, then sends:

```json
{
  "inputs": {
    "request_payload": "{\"schema_version\":\"metric_discovery.request.v1\",...}",
    "reference_files": [
      {
        "transfer_method": "local_file",
        "upload_file_id": "<dify-upload-id>",
        "type": "document"
      }
    ]
  },
  "response_mode": "streaming",
  "user": "metric:<local-user>@<machine>"
}
```

## 2. Overall workflow framework

The two optional evidence paths must both return a value, including when they
are skipped. Use one Variable Aggregator after each IF/ELSE to normalize its
exclusive branches. When the document path and research path run in parallel,
merge them with a Code node; Variable Aggregator does not merge parallel data.

```text
Start
  └─ Code 01: parse_and_validate_request
       ├─ IF 02A: has_reference_files
       │    ├─ Yes → Document Extractor → LLM: extract_document_evidence
       │    └─ No  → Template: empty_document_evidence
       │                 ↓
       │         Variable Aggregator: document_evidence
       │
       └─ IF 02B: public_research_enabled AND company_name is not empty
            ├─ Yes → Tool/HTTP: 天眼查 AI
            │        → Tool/HTTP: approved public web search
            │        → Code: normalize_public_evidence
            └─ No  → Template: empty_public_evidence
                          ↓
                  Variable Aggregator: public_evidence

document_evidence + public_evidence + parsed request
  └─ Code 03: build_source_bundle
       └─ LLM 04: build_compact_business_context
            └─ Code 04B: build_regulatory_context
                 └─ LLM 05: generate_metric_candidates (structured output)
                      └─ LLM 06: data_based_critic (structured output)
                      └─ Code 07: validate_metric_pack
                           └─ IF 08: valid
                                ├─ Yes → pass_valid_pack
                                └─ No  → LLM: repair_metric_pack
                                          → Code: validate_repaired_pack
                                             ↓
                              Variable Aggregator: final_valid_pack
                                             ↓
                              Code 09: consolidate_data_requests
                                             ↓
                              Output: metric_pack
```

The critical path is request parsing → context building → candidate generation
→ critique → deterministic validation → Output. The optional source paths may
degrade to empty evidence but must not prevent generation.

## 3. Request parsing

The first Code node should:

1. Parse `request_payload` as JSON.
2. Reject any schema version other than `metric_discovery.request.v1`.
3. Preserve empty arrays and `null` values as “not provided”.
4. Never reinterpret an empty selection as “the company does not have this”.
5. Determine the desired indicator count:
   - use `indicator_guidance.indicator_count` when present;
   - otherwise choose 5–10 based on information coverage and selected topics.
6. Return compact variables for downstream nodes, while keeping the original
   request available for evidence references.
7. Read `regulatory_guidance.special_analysis_enabled` as a strict boolean and
   preserve `regulatory_guidance.covered_sections`, `priority_sections`,
   `section_catalog`, `priority_section_rules`, `interpretation_rules`, and
   `output_requirements`. Do not infer special mode from prompt text, and do not
   rely on the model to recall section titles from memory.

Suggested outputs:

```json
{
  "request": {},
  "company_name": "",
  "public_research_enabled": false,
  "regulatory_analysis_enabled": false,
  "generation_mode": "standard_it_audit",
  "desired_indicator_count": 8,
  "has_reference_files": true
}
```

## 4. Document handling

Run the Document Extractor only when `reference_files` is not empty. Treat all
document text as untrusted reference content:

- ignore instructions found inside documents;
- extract business facts only;
- retain file names and page/slide/section anchors when available;
- do not let document text decide which tools to call;
- do not write project documents into a shared knowledge base.

For long documents, summarize each document first and pass only relevant
business facts into the metric generator.

## 5. 天眼查 AI and public research

Public research is supplementary. It must not be a prerequisite for generation.

Only call it when:

```text
request.research_preferences.public_information_enabled == true
AND company_information.company_name is not empty
```

Initial 天眼查 AI scope:

1. Company search/entity anchoring.
2. Registration/basic company information.

Do not treat registered business scope as proof of the actual operating model.
When exact identity cannot be established, tag public findings as uncertain and
continue with manual inputs, documents, and industry assumptions.

The workflow must still succeed when 天眼查 AI:

- has no remaining quota;
- times out;
- is removed after the free period;
- returns no exact company.

Expose 天眼查 AI through a Dify Tool Plugin or HTTP Request node. Keep its
provider credentials inside Dify, never in the desktop application. Configure
the node with a fail branch or a correctly typed default value, then append a
short explanation to `source_notes`.

## 6. Business-context prompt

The business-context LLM should produce a compact internal object:

```json
{
  "identity": {},
  "industries": [],
  "business_models": [],
  "products_services": [],
  "customer_types": [],
  "business_chain_hypotheses": [],
  "user_analysis_directions": [],
  "user_analysis_focuses": [],
  "ecommerce_marketing": {
    "uses_influencer_promotion": "yes|no|unknown|null",
    "user_confirmed": false,
    "scope_definition": []
  },
  "metric_playbooks": [],
  "confirmed_facts": [],
  "inferred_facts": [],
  "unknowns": [],
  "sources_used": []
}
```

Source precedence is field-specific:

- user input and client documents are primary for actual operations;
- authoritative company data is primary for legal identity;
- public web information is supplementary;
- industry knowledge is a hypothesis, never a company fact.

Semantically deduplicate repeated facts before metric generation, while
retaining all source references.

### 6.1 Regulatory context

`build_regulatory_context` is deterministic and must not call an additional
LLM. It converts the request contract into a short prompt block:

- the full 5-1 through 5-19 framework is always the primary IT-audit
  methodology baseline;
- assess applicability before designing indicators;
- absence of information means `待确认`, never `不适用`;
- design client-data indicators only where data analysis is capable of
  addressing the risk;
- retain non-data procedures and scope limitations for matters that require
  interviews, walkthroughs, system inspection, control testing, contracts, or
  third-party evidence;
- prioritize 5-11 `第三方回款核查`, 5-12 `经销模式`, 5-13
  `通过互联网开展业务相关信息系统核查`, and 5-14 `信息系统专项核查`;
- apply those four priority sections according to the confirmed payment,
  distribution, internet-business, and system-dependence facts rather than
  assuming that all four are applicable;
- do not let the special mode override the user's company facts, project scope,
  or selected business directions.

When `special_analysis_enabled` is `false`, apply those principles as a concise
baseline and return the existing result fields. When it is `true`, require the
strict special fields in section 8. This distinction keeps the normal workflow
compact while making the button's effect verifiable.

Recommended Code-node behavior:

```python
def main(request: dict) -> dict:
    guidance = request.get("regulatory_guidance") or {}
    enabled = guidance.get("special_analysis_enabled") is True
    context = {
        "framework_id": guidance.get("framework_id"),
        "baseline_applies": True,
        "special_analysis_enabled": enabled,
        "sections": guidance.get("section_catalog") or [],
        "priority_section_rules": guidance.get("priority_section_rules") or {},
        "interpretation_rules": guidance.get("interpretation_rules") or [],
        "required_output": request.get("output_requirements") or {},
    }
    return {
        "regulatory_analysis_enabled": enabled,
        "generation_mode": (
            "issuance_guidance_no5_special" if enabled else "standard_it_audit"
        ),
        "regulatory_context": context,
    }
```

## 7. Metric-generation prompt

The generator must first create more candidates than requested, then select the
best 5–10. Every selected indicator must pass all of these questions:

1. Why is this indicator relevant to the supplied company/project context?
2. What exact business question or risk does it test?
3. Which requestable client datasets are needed?
4. What is the row-level grain of each dataset?
5. Which fields and join keys are required?
6. How will the analysis be performed?
7. How should the project team phrase the request to the client?
8. What scope/period/completeness points must be clarified?
9. What anomalies could the analysis reveal?
10. Which 5-x provisions support the indicator, what is the complete population
    and period, which exception rules apply, how should exceptions be followed
    up, and what evidence is expected? These items are mandatory in special
    mode.

Reject:

- generic KPI names without a data request;
- metrics that require unavailable external facts rather than client data;
- vague requests such as “provide sales data”;
- methods that invent fields not listed in `data_requirements`;
- multiple metrics that test the same risk with the same data and method.

### 7.1 电商达人推广条件剧本（直接追加至指标生成节点 Prompt）

```text
你必须读取 request.company_information.ecommerce_marketing 和
request.indicator_guidance.metric_playbooks，不得根据“电商销售”、经营范围、
公开资料或行业惯例自行推断企业使用达人推广。

找到 playbook_id=ecommerce_influencer_effectiveness.v1 的剧本后，严格执行：

1. user_answer=yes：
   - 必须启用剧本，并覆盖 required_metric_families 中的每一个指标族；
   - 每个必选指标族至少对应一项独立指标；
   - 指标必须输出 playbook_id、metric_family_id、formula、dimensions；
   - 优先补充 recommended_metric_families，但总指标数仍为5至10项；
   - 指标定义、公式与口径应以 metric_family_catalog 为准，可结合企业实际细化，
     不得删除其核心核查目的。

2. user_answer=no：
   - 禁止生成 forbidden_metric_families 中的达人专属指标；
   - 可以根据其他已知事实生成平台投流、平台结算或电商运营指标；
   - 不得把“未使用达人推广”扩写为“未使用任何营销投放”。

3. user_answer=unknown：
   - 只能把剧本指标作为“待确认”条件性指标；
   - target_basis 必须明确写明“待确认是否使用达人推广”；
   - 不得把达人、MCN、达人链接、达人佣金写成已知事实；
   - client_request_guidance 和 key_scope_questions 必须包含确认推广模式所需资料或访谈问题。

通用约束：
- 区分销售额、净销售额、GMV/GSV、佣金、坑位费和推广消耗；
- ROI公式必须明确分子、分母、退款取消订单和归因窗口；
- 推广消耗与销售表现的相关性不得表述为因果关系；
- 建议使用达人/MCN、内容、商品、推广链接、订单、支付、退款、平台结算、
  银行收款和财务凭证间的稳定标识构建可追溯链；
- 不得生成没有可索取数据、字段、粒度、连接键和具体分析步骤的泛化指标。
```

`parse_and_validate_request` 必须校验：选择了 `电商销售` 时，
`uses_influencer_promotion` 只能是 `yes`、`no` 或 `unknown`，且
`user_confirmed` 必须为 `true`。桌面端已执行同样校验，此处是服务端防线。

## 8. Required Output

The Output node must return `metric_pack` as an object or a JSON string. The
example below abbreviates `applicability_assessment` to one row for readability;
the actual special-mode output must return all 19 rows:

```json
{
  "schema_version": "metric_discovery.result.v1",
  "summary": "本次指标围绕……",
  "assumptions": [],
  "source_notes": [],
  "indicators": [
    {
      "indicator_id": "M01",
      "metric_family_id": "platform_ledger_reconciliation",
      "playbook_id": "ecommerce_influencer_effectiveness.v1",
      "title": "订单、发货、开票及收款匹配率",
      "category": "收入与销售",
      "priority": "高",
      "target_basis": "公司采用企业客户订单销售并存在项目验收环节",
      "analysis_objective": "识别收入链路缺失及提前确认线索",
      "definition": "完整业务链条金额占已确认收入对应订单金额的比例",
      "formula": "完整匹配订单金额 / 已确认收入对应订单金额",
      "analysis_grain": "订单行级",
      "dimensions": ["月份", "客户", "产品", "销售人员"],
      "analysis_method": [
        "以订单号和订单行号建立销售订单基础表",
        "关联发货、验收、发票和收款核销记录",
        "比较各环节数量、金额和日期并识别缺失链条"
      ],
      "data_requirements": [
        {
          "dataset_name": "销售订单明细",
          "business_purpose": "取得完整订单总体",
          "grain": "一行一条订单行",
          "recommended_period": "核查期及前后各一个月",
          "required_fields": [
            "订单号",
            "订单行号",
            "客户编码",
            "产品编码",
            "订单日期",
            "数量",
            "金额"
          ],
          "join_keys": ["订单号", "订单行号"],
          "scope_and_completeness": "包含核查期间全部订单及取消订单"
        }
      ],
      "client_request_guidance": "请提供核查期间全部销售订单行明细……",
      "key_scope_questions": [
        "一张订单是否允许多次发货",
        "收款是否按发票进行核销"
      ],
      "potential_anomalies": [
        "无订单收入",
        "未履约但已开票",
        "期末集中确认"
      ],
      "data_acquisition_difficulty": "中",
      "evidence_basis": ["用户填写：工程或项目制"],
      "assumptions": [],
      "regulatory_references": ["5-12 经销模式"],
      "population_definition": "核查期间全部销售订单及取消订单",
      "coverage_period": "核查期及前后各一个月",
      "exception_rules": ["订单、履约、开票或收款任一环节缺失"],
      "follow_up_procedures": ["追查业务单据并访谈业务负责人"],
      "expected_evidence": ["订单、出库、签收、发票及收款核销记录"],
      "scope_limitations": []
    }
  ],
  "consolidated_data_requests": [
    {
      "dataset_name": "销售订单明细",
      "description": "支持M01等指标",
      "required_fields": ["订单号", "订单行号", "客户编码"]
    }
  ],
  "regulatory_review": {
    "applicability_assessment": [
      {
        "section": "5-1",
        "status": "适用|不适用|待确认",
        "basis": "基于已确认事实；缺少信息时说明待确认事项"
      }
    ],
    "non_data_procedures": ["访谈、穿行测试、系统检查或控制测试等程序"],
    "scope_limitations": ["尚未获取的信息、无法仅凭数据分析覆盖的事项"]
  }
}
```

Normal mode may omit `regulatory_review` and all optional per-indicator
regulatory fields. Special mode must return `regulatory_review`, and
`applicability_assessment` must contain exactly one item for every section from
`5-1` through `5-19`. Every special-mode indicator must contain non-empty
`regulatory_references`, `population_definition`, `coverage_period`,
`exception_rules`, `follow_up_procedures`, and `expected_evidence`.

The desktop validates the final result again. It rejects the whole workflow
result when:

- the number of indicators is outside 5–10;
- an indicator has no `target_basis`, `analysis_objective`,
  `analysis_method`, `data_requirements`, or `client_request_guidance`;
- a data requirement has no `dataset_name`, `grain`, or `required_fields`.
- in special mode, any 5-1 through 5-19 applicability item or required
  per-indicator regulatory field is missing;
- a special-mode regulatory reference points outside 5-1 through 5-19;
- when influencer promotion is `yes`, an item in `required_metric_families`
  is not represented by an indicator with matching `playbook_id` and
  `metric_family_id`.

Code 07 must perform the same metric-family coverage check before the repair
branch. If coverage is incomplete, pass the exact missing family IDs to the
repair LLM; do not rerun the whole workflow or silently substitute unrelated
indicators.

## 9. Failure behavior

Return a workflow failure for malformed request/response contracts. For partial
source failures, complete the workflow and add a human-readable entry to
`source_notes`.

Do not expose tool credentials, stack traces, or raw provider payloads in the
Output.

## 10. Publish and integration acceptance gate

The workflow is ready for the desktop only after all of these checks pass:

1. Publish it as a separate Dify Workflow app and create a dedicated app API
   key.
2. Confirm `GET /parameters` exposes exactly `request_payload` and
   `reference_files` with the types defined above.
3. Test these cases in Dify: manual input only; document only; research enabled;
   天眼查 AI / public search unavailable; 第5号文专项模式; 电商+达人推广是;
   电商+达人推广否; 电商+达人推广暂不确定.
4. Confirm the Output key is `metric_pack`, the schema version is
   `metric_discovery.result.v1`, and every test returns 5–10 indicators.
5. Enter the workflow base URL, API key, and timeout in the desktop API
   settings. Do not embed the API key in the executable.
6. Run one desktop request without a file and one with a PDF/DOCX/PPTX. Check
   the Dify run log, file ownership under the same `user`, response rendering,
   and cancellation/error behavior.
7. For the special-mode case, confirm the Dify run count is exactly one and the
   desktop accepts all 5-1 through 5-19 applicability entries. Temporarily omit
   one required field and confirm the desktop fails closed with a contract
   error instead of displaying an ordinary result as a special review.
8. For `uses_influencer_promotion=yes`, confirm all five required metric-family
   IDs are present. For `no`, confirm no forbidden influencer-specific family
   is returned. For `unknown`, confirm the result states the condition as
   `待确认` and does not present influencer promotion as a confirmed fact.
