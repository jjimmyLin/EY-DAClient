# 商业分析指标生成 — Dify 工作流契约与整体框架

This workflow is a separate Dify Workflow app. It must not replace or modify
the existing data-analysis app that accepts `task_type`, `context`, and `query`.

The first release should use a deterministic Workflow rather than an Agent.
The desktop owns form interaction, local file selection, request validation,
threading, cancellation, and result rendering. Dify owns document extraction,
天眼查 AI / public research, evidence normalization, indicator reasoning, and
the final structured output.

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
  "response_mode": "blocking",
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

Suggested outputs:

```json
{
  "request": {},
  "company_name": "",
  "public_research_enabled": false,
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
  "request_scope": null,
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

Reject:

- generic KPI names without a data request;
- metrics that require unavailable external facts rather than client data;
- vague requests such as “provide sales data”;
- methods that invent fields not listed in `data_requirements`;
- multiple metrics that test the same risk with the same data and method.

The selected `request_scope` controls complexity:

- `精简范围`: prefer one or a few common detail tables;
- `常规范围`: allow several linkable business tables;
- `完整范围`: allow cross-department/system chains and mapping tables;
- `其他`: follow `request_scope_custom`;
- `null`: infer an appropriate scope and disclose that assumption.

## 8. Required Output

The Output node must return `metric_pack` as an object or a JSON string:

```json
{
  "schema_version": "metric_discovery.result.v1",
  "summary": "本次指标围绕……",
  "assumptions": [],
  "source_notes": [],
  "indicators": [
    {
      "indicator_id": "M01",
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
      "assumptions": []
    }
  ],
  "consolidated_data_requests": [
    {
      "dataset_name": "销售订单明细",
      "description": "支持M01等指标",
      "required_fields": ["订单号", "订单行号", "客户编码"]
    }
  ]
}
```

The desktop validates the final result again. It rejects the whole workflow
result when:

- the number of indicators is outside 5–10;
- an indicator has no `target_basis`, `analysis_objective`,
  `analysis_method`, `data_requirements`, or `client_request_guidance`;
- a data requirement has no `dataset_name`, `grain`, or `required_fields`.

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
3. Test four cases in Dify: manual input only; document only; research enabled;
   and 天眼查 AI / public search unavailable.
4. Confirm the Output key is `metric_pack`, the schema version is
   `metric_discovery.result.v1`, and every test returns 5–10 indicators.
5. Enter the workflow base URL, API key, and timeout in the desktop API
   settings. Do not embed the API key in the executable.
6. Run one desktop request without a file and one with a PDF/DOCX/PPTX. Check
   the Dify run log, file ownership under the same `user`, response rendering,
   and cancellation/error behavior.
