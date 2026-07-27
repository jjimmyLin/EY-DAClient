# 分析经验学习功能

## 目标与边界

该功能只学习可复用的分析方法、字段语义、业务规则、适用条件和常见风险。它不上传原始数据、样本行、完整 Python 代码、标准输出、错误输出、本地路径、图表内容或任何 API Key。

一次完整分析在本地执行成功并通过语义审计后，界面会显示非模态反馈卡片。用户点击“有用”后，客户端立即显示“谢谢！”，随后在后台把脱敏后的 `session_payload` 提交给独立的 Dify 经验工作流。

知识库写入必须由 Dify 工作流完成。经验工作流的 App API Key 和 Base URL 作为内部部署配置固化在客户端中，不向用户提供配置入口。桌面客户端不能保存 Dify Knowledge API Key。

## 本地配置

经验学习默认启用。工作流 App API Key 和 Base URL 不从 `.env` 读取；以下 `.env` 配置只用于运维控制和非敏感运行参数：

```dotenv
EXPERIENCE_LEARNING_ENABLED=true
DIFY_EXPERIENCE_TIMEOUT=120
EXPERIENCE_MAX_PAYLOAD_CHARS=40000
EXPERIENCE_TENANT_ID=<tenant-id>
EXPERIENCE_PROJECT_ID=<project-id>
APP_VERSION=<client-version>
ANALYSIS_WORKFLOW_VERSION=<analysis-workflow-version>
```

客户端使用与正常分析流一致的 `POST /v1/workflows/run` 端点调用“分析经验提取器”。`EXPERIENCE_LEARNING_ENABLED=false` 可作为部署级紧急停用开关。不要在本地配置 Knowledge API Key。

## Dify 工作流改造

现有工作流在“规范化并生成候选知识文档”之后仍需增加知识库写入链路：

```text
规范化候选
  -> 候选数组准备
  -> Iteration（每条候选）
       -> 计算 experience_hash
       -> 查询同名/同 hash 文档
       -> 不存在：create-by-text
       -> 更新文档 metadata
  -> 汇总写入结果
  -> End
```

Dify 工作流环境变量：

```text
KNOWLEDGE_API_BASE=https://<dify-host>/v1
KNOWLEDGE_API_KEY=<Knowledge API Key，Secret 类型>
KNOWLEDGE_DATASET_ID=<目标知识库 ID>
```

创建文档请求：

```http
POST /datasets/{KNOWLEDGE_DATASET_ID}/document/create-by-text
Authorization: Bearer {KNOWLEDGE_API_KEY}
Content-Type: application/json
```

建议请求体：

```json
{
  "name": "experience_<experience_hash>",
  "text": "<candidate.document_markdown>",
  "indexing_technique": "high_quality",
  "doc_form": "text_model",
  "process_rule": {
    "mode": "automatic"
  }
}
```

`experience_hash` 应使用以下规范化内容生成 SHA-256：

```text
schema_family_id
+ knowledge_type
+ normalized_question
+ required_fields（排序）
+ method_steps（排序）
```

写入前按 `experience_<experience_hash>` 查询文档列表；已存在时返回 `duplicate`，避免同一经验被多次加入知识库。

创建成功后，使用返回的 `document.id` 写入至少以下 metadata：

```text
experience_hash
tenant_id
project_id
schema_family_id
knowledge_type
scope
confidence
app_version
workflow_version
analysis_session_id
analysis_run_id
```

## 工作流输出契约

最终 End 节点必须返回：

```json
{
  "knowledge_write_status": "uploaded",
  "candidate_count": 2,
  "uploaded_count": 2,
  "failed_count": 0
}
```

`knowledge_write_status` 支持：

- `uploaded`：所有新候选已提交知识库。
- `duplicate`：候选均已存在，无需重复写入。
- `partial`：部分成功；同时返回准确的 `failed_count`。
- `no_candidate`：审查后没有可复用候选。

客户端会拒绝缺少 `knowledge_write_status` 的响应。这样可以防止把“生成候选成功”误认为“知识库写入成功”。

## 运行规则

- 反馈卡片每个分析 Session 最多出现一次。
- 样本预检、失败执行、未通过语义审计的任务不触发反馈。
- 用户点击“暂不”或离开当前 Session 后不再提示。
- 后台学习失败只写应用日志和任务内部状态，不弹窗、不覆盖分析结果。
- Dify HTTP Request 节点若受 SSRF 策略限制，改为调用公司内网 ingestion proxy，由代理持有 Knowledge API Key 并转发 Knowledge API。
