# Phase 4.3 ResponseGenerator Migration Report

本阶段完成 ResponseGenerator 的输入、输出和现有调用点迁移。新解释入口只接受经过验证的 `PromptPackage`，不接受旧 execution/context 参数；模型选择受控表达，程序保留当前包中的事实、状态和引用。

**回归结果：Explanation 82/82，Business Signal 654/654，backend 1186/1186。** 相对 1153 基线新增 33 项迁移测试。

**运行边界：现有 HTTP/Service 路径尚未接入 SignalBatch 生产与 PromptPackage 传递。** 因此普通查询仍返回 SQL 结果表，但没有当前有效包时解释明确不可生成；历史结果 QA 也不再凭 rows 或旧 analysis 生成回答。当前已验证完整 Graph 消费显式绑定包的路径，不代表已完成自动 Signal 生产接线。

## 1. 旧路径分析与迁移方案

调查对象为 `response_generator.py`、`query_graph.py` 和 `result_builder.py`。

| 位置 | 迁移前行为 | 本阶段处理 |
| --- | --- | --- |
| `ResponseGenerator.finalize` | 接收 query、SqlExecution、schema_context、analysis_context；拼接 SQL、columns、截取 rows、Schema 和历史分析表 | 改为只接收 PromptPackage |
| `ResponseGenerator.answer_qa` | 接收 query 与自由文本 context，返回自由文本 | 使用同一 PromptPackage 契约，返回 ExplanationResponse |
| `QueryWorkflow._answer_qa` | 拼接 short_term_context、recent_result_context、analysis_context | 删除旧上下文读取，只检查当前包的调用绑定 |
| `QueryWorkflow._execute_single_database` | 把 SqlExecution 交给解释器；解释异常时构造 `valid=True` 的旧 fallback | 保留执行与表格处理；单独生成结构化解释状态 |
| `ResultBuilder` | 用模型 `valid` 决定查询成败，直接使用模型 analysis/title | 执行成功与解释成功分离；使用验证后的 response.text |

旧模型输出的 `valid` 既混合了业务判断与解释，又存在缺失默认成功、宽松 bool/str 转换和默认说明。旧 `chat_json` 还会修补代码围栏或前后文字。这些行为均不进入新解释入口。

迁移采用局部替换：新增 Adapter 与响应模型；更换两个解释入口及其结果包装。没有新增 Graph 节点、调整边或接入 Signal 生产流程。

## 2. 新输入契约

```text
已有 SignalEngine 产出的 SignalBatch
    → build_explanation_context(batch)
    → build_prompt_package(context, request_options, question=...)
    → PromptPackage
    → ResponseGenerator.generate_from_prompt_package(package)
    → ExplanationResponse
```

ResponseGenerator 的三个公开入口具有相同边界：

```python
generate_from_prompt_package(package: PromptPackage) -> ExplanationResponse
finalize(package: PromptPackage) -> ExplanationResponse
answer_qa(package: PromptPackage) -> ExplanationResponse
```

旧多参数调用、SqlExecution、自由文本及 rows 字典不再是可接受输入。直接 API 对错误输入抛出类型或模型校验错误；Graph 对缺失或非法传输返回明确的 unavailable 状态，且不调用模型。

复用 Phase 4.2 的严格模型校验：未知字段拒绝、嵌套对象重验、固定 system/user 消息与结构化事实一致性检查。新生成器及 Adapter 不读取 SignalBatch、BusinessContext、ResultContract、SQL、rows、columns 或完整 Evidence。

## 3. Migration Adapter 设计

[response_adapter.py](D:/agent_study/askdata_studio/backend/app/querying/explanation/response_adapter.py) 提供四个函数：

| 函数 | 职责 |
| --- | --- |
| `adapt_response_input` | 重验 PromptPackage；原样传递 user_message；在固定 system_message 后追加模型输出契约 |
| `render_explanation_response` | 严格解析表达候选，按当前包生成响应及引用 |
| `unavailable_explanation` | 生成固定解释不可用文本、状态和诊断 code |
| `validate_response_for_package` | 将已存响应与当前包的事实、引用、索引、locale、notice、omission 作一致性检查 |

Adapter 不执行模型调用，也不计算业务数值。既有 Phase 4.2 Prompt Builder 未修改。

模型仅返回如下结构：

```json
{
  "blocks": [
    {
      "signal_index": 0,
      "expression_variant": "target_attainment_summary_v1",
      "wording": "summary"
    }
  ]
}
```

`expression_variant` 必须与对应 Signal 原值一致；`wording` 只允许 `summary` 或 `operands`。模型必须保留当前包全部 fact blocks 的原始顺序，不能遗漏、重复、重排或引用其他 Signal。

模型不能返回任意文本模板、value、status、reason、citations、valid 或额外字段。最后展示的文本由受控中英词典与原始事实确定性生成，避免仅靠“请勿修改数字”的提示来保证事实正确。

## 4. ResponseGenerator 与输出契约

[response_generator.py](D:/agent_study/askdata_studio/backend/app/querying/response_generator.py:23) 调用原始 `ModelClient.chat`，随后交由 Adapter 解析，不调用具有修补行为的 `chat_json`。

拒绝非 JSON、代码围栏、前后附带文字、重复 JSON key、类型强转和非法输出结构；任何候选校验失败都不发布候选事实或候选文字。模型调用异常不回显 exception 原文，不用旧上下文补回答。

[ExplanationResponse](D:/agent_study/askdata_studio/backend/app/querying/explanation/response_models.py:205) 采用严格、冻结、拒绝未知字段的模型：

| 字段 | 含义 |
| --- | --- |
| `generation_status` | generated / not_requested / unavailable / failed，仅表示解释生成状态 |
| `presentation_coverage` | complete / partial / none，针对本包的可展示事实 |
| `blocks` | 原 SignalRef、固定 variant、受控 wording、原 FactBlock、EvidenceRef 和经验证文本 |
| `citations` | 当前包的 EvidenceSummary，保留结果、列、行、操作数及公式引用 |
| `text` | 按顺序渲染的事实及安全限制说明 |
| `notice_blocks` / `omissions` | 完整保留安全限制和本次未展示记录 |
| `source_signal_count` / 展示索引 | 保留来源位置，不重编号、不创建随机 ID |
| `diagnostic_codes` | 解释失败或无需调用模型的受控原因 |

coverage 的 complete 表示所有可展示事实都已包含，不宣称全部 Signal 都计算成功。仅有 `not_displayable` 记录时仍可 complete，同时明确保留隐藏记录 notice；存在分页或预算省略时为 partial。

S2 的顶层 undefined 不等于解释失败：absolute_change 仍保留 computed 原值，change_rate 保留 undefined / None / ZERO_BASELINE；解释可以 generated。禁止把 undefined 改为 0。

所有生成结果均保留双操作数引用，S3 broadcast total 不借用分项业务键。summary 可以只呈现结果，但完整双操作数仍在 citations；operands 额外展示原始 observation 文本。单位、倍率、期间边界、筛选范围、source fidelity、运算精度和安全限制均来自当前投影。

数字仅作为已有字符串呈现：不使用 Decimal/float 重新运算，不转换百分比、换单位或重新舍入。对字符串作字面量引用与标记字符转义，不把 business key、filter 或用户问题变成输出模板。

响应模型重验 blocks、citations、公式引用和渲染文本；`validate_response_for_package` 进一步拒绝生成响应被误用于另一份事实快照。它是当前输入间的一致性检查，不是签名或 producer 身份认证。

## 5. QueryGraph 与 ResultBuilder 的局部变化

[QueryWorkflow._generate_explanation](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:187) 是新的调用点门禁：

1. 从专用 `explanation_prompt_package` 读取包。
2. 要求 `explanation_task_id == task_id` 且 `explanation_for_query == query`，两者必须非空。
3. 重验 typed 包，或通过严格 JSON 校验恢复序列化包。
4. 包内 question 若存在，必须等于当前 query。
5. 数据库路径含 fact blocks 时，包内 Evidence 引用必须包含当前 execution 的 result_id。
6. 通过后仅将 PromptPackage 交给 finalize / answer_qa。

这个门禁检查传输关联，不重做 Compatibility、Alignment、Numeric 或业务语义判断。绑定字段由可信调用方提供，不是公开 HTTP 请求新增的事实入口。

ResultBuilder 将 `ExplanationResponse` 放入 `QueryResult.explanation`，并将已验证的 text 放入旧 UI 使用的 `analysis` 字段。新解释输出不再包含 `valid`；表格标题使用固定“查询结果”。

`QueryResult.explanation` 增加专用 JSON 恢复校验，解决 Workflow 的 `model_dump(mode="json")` 把严格 tuple 序列化为数组后无法回读的问题。嵌套模型仍拒绝未知字段、错误索引类型和伪造文本。完整 compiled Graph → `_state_result` 正向测试已通过。

## 6. 失败处理与独立表格路径

| 情况 | 解释状态 | 行为 |
| --- | --- | --- |
| 缺少当前包 | unavailable / NO_PROMPT_PACKAGE | 不调用模型 |
| 包非法、任务/问题/结果关联不匹配 | unavailable / INVALID_PROMPT_PACKAGE | 不调用模型 |
| 空包或没有 fact blocks | not_requested / NO_DISPLAYABLE_FACTS | 保留 notice/omission，不调用模型 |
| 模型调用失败 | failed / LLM_CALL_FAILED | 固定不可生成说明，无 facts/citations |
| 模型返回非法候选 | failed / INVALID_LLM_RESPONSE | 整体拒绝，不修补、不发布候选文本 |

以上均不回退到 SQL rows、历史 analysis_context、recent_result_context 或 short_term_context。

SQL 执行成功时，QueryResult 仍为 completed，原 SQL、columns、rows 保留；解释失败通过独立 explanation 字段和提示反映。仅请求解释的 data_qa 路径无法生成解释时，返回 failed，并明确 explanation unavailable/failed。

[现有 Table UI](D:/agent_study/askdata_studio/frontend/src/App.vue:590) 的表格与 analysis 展示原本分离，本阶段未修改前端。`analysis_sources` 继续作为附表展示信息，未送入解释器。ResultBuilder 原有 Interpretation 列名启发式仍属于旧展示元数据，未作为 Signal 事实或新 Prompt 输入。

## 7. 测试与 backend 回归

新增 [test_response_generator_migration.py](D:/agent_study/askdata_studio/backend/tests/test_response_generator_migration.py)，33 个测试方法覆盖：

- 真实 S1/S2/S3 → Batch → Context → Prompt → mocked model → ExplanationResponse。
- PromptPackage 单一入口；SQL/rows/BusinessContext/完整 Evidence 字段不进入模型输入。
- 禁止 acquisition 或上游计算调用；旧 context 读取 guard。
- LLM 异常、结构错误、额外业务值、错误 variant、遗漏/重复/重排/跨 Signal 引用拒绝。
- 代码围栏、前后自由文本、重复 JSON key、布尔/字符串索引和非字符串传输拒绝。
- undefined、失败 Signal、空包、分页、展示覆盖及安全 notice 保留。
- S3 broadcast Evidence、完整双操作数、原始数字和状态保留。
- 用户问题与语言不能改变事实；输入不修改；JSON roundtrip；A→A 与 A→B→A。
- 响应与当前包绑定；Graph 的任务/问题/result identity 校验。
- 完整 compiled Graph 消费序列化包并恢复 QueryResult；严格响应嵌套字段校验。
- 表格在缺包、引用不匹配和模型失败时正常保留。

旧测试未删除。两个旧测试文件调整了本次必须变化的接口预期：ResultContract 不再被传给 finalize；无 Signal 包的历史表 QA 不再声称成功复用旧分析。原执行契约、表格、路由和附表定位断言继续保留。

| 测试集合 | 结果 |
| --- | --- |
| ResponseGenerator migration | 33/33 |
| Explanation（49 既有 + 33 新增） | 82/82 |
| Business Signal | 654/654 |
| Workflow ResultContract | 15/15 |
| backend full | 1186/1186 |

backend 全量命令：在 `backend` 下运行 `.\.venv\Scripts\python.exe -m unittest discover -s tests -q`，29.649 秒通过。Explanation 与 Business Signal 还分别独立运行通过。未进行真实远端 LLM 调用；网络和模型输出使用测试替身。

确定性结论限于固定 PromptPackage 和固定模型表达候选的投影、校验及渲染。真实 LLM 可能选择不同 wording，本阶段不声称远端生成逐字确定。

## 8. 修改文件与范围核验

新增：

- `backend/app/querying/explanation/response_adapter.py`
- `backend/app/querying/explanation/response_models.py`
- `backend/tests/test_response_generator_migration.py`
- 本报告。

修改既有文件：

- `backend/app/querying/response_generator.py`：新输入契约与模型调用。
- `backend/app/workflows/query_graph.py`：两个解释调用点、传输门禁、失败状态。
- `backend/app/workflows/result_builder.py`：解释与表格结果分离。
- `backend/app/workflows/state.py`：专用包与调用绑定字段。
- `backend/app/models.py`：QueryResult 的结构化解释字段与 JSON 恢复。
- `backend/tests/test_workflow_result_contract.py`、`backend/tests/test_service.py`：迁移所需旧预期更新。

与本轮开始时的 120 个源码/测试文件 SHA-256 快照比较，仅以上 7 个既有文件变化。Phase 3 源码及测试、既有 Phase 4.2 实现、frontend 均未修改。`git diff --check` 通过；未执行 git add、commit 或 tag，原暂存状态保留。

## 9. 剩余边界

1. 已提供 ResponseGenerator 消费和现有 Graph 调用点迁移；尚无自动 SignalBatch producer 接线，也未为普通 HTTP 查询构造业务 Signal。没有包时不可解释是当前明确行为。
2. 当前只支持三类 Signal 的受控 summary/operands 表达，不支持任意业务问答、因果推断、自由多轮回答或新增业务事实。
3. 审计引用仍依赖当前任务/输入快照，未实现跨任务归档关联或全局 identity；复用持久化响应应携带原包并调用当前包校验函数。
4. 本阶段未建设新的 citation UI；结构化引用已在 API 输出中保留，旧 UI 使用受控 text。
5. 旧执行、路由与表格展示仍有各自上下文；本报告的无 raw-data Prompt 保证针对新的解释入口，不声称全系统 SQL Agent、路由或记忆功能均不读取这些数据。

**本阶段未实现：Workflow 重构、Prompt 优化、多轮 Agent 解释。** 未修改 Phase 3 Calculator、Evidence Builder、SignalEngine、Compatibility、Alignment 或 Numeric Reader。
