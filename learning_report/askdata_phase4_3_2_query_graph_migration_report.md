# Phase 4.3.2 QueryGraph Migration Report

本阶段完成已确认的接线范围：正式 QueryWorkflow 从受信后端来源接收已经计算好的 BusinessSignal，调用已有 SignalEngine，生成 SignalBatch、ExplanationContext、PromptPackage 和 ExplanationResponse。Graph 不计算 Signal，也不选择 metric、Policy、期间或声明。

**最终回归：新 Graph 测试 30/30，Explanation 112/112，Business Signal 654/654，Workflow/Service 70/70，backend 1216/1216。** 相对 1186 基线新增 30 项测试。

用户已确认：新增受信 BusinessSignal 交付入口；普通查询没有已计算 Signal 时明确不可解释。该来源通过服务端依赖注入配置，不是 HTTP 用户上传事实的入口。

## 1. Graph before / after

### 调查结果

4.3.1 的 `_execute_single_database` 在恢复、校验 SqlExecution 后保留表格，尝试消费外部绑定的 `explanation_prompt_package`；`_answer_qa` 使用同一包入口。缺包时不再回退旧分析。

当时 state 没有正式 `signal_batch`、`prompt_package`、`explanation_response`；生产代码也没有 BusinessContext Builder 或三个 Calculator 的调用方。SignalEngine 的实际契约是 `build(already_computed_signals)`，没有从 SQL 自动选择业务计算的能力。

### 新正式路径

```text
Query → 原有路由 / 检索 / SQL 执行与契约校验
                           │
                           ├─ execution_result → 原 Table 结果
                           │
                           └─ build_signal_batch
                                 受信 SignalSource(request)
                                     → 已计算 BusinessSignal[]
                                     → SignalEngine.build()
                                     → signal_batch
                                           ↓
                                build_explanation_prompt
                                     → build_explanation_context(batch)
                                     → build_prompt_package(context)
                                     → prompt_package
                                           ↓
                                generate_explanation
                                     → ResponseGenerator
                                     → 当前包引用校验
                                     → explanation_response
                                           ↓
                                附加解释状态，保留 Table
```

新增三个局部节点：`build_signal_batch`、`build_explanation_prompt`、`generate_explanation`。数据库执行成功后进入该链路；失败执行直接结束，不调用交付来源或模型。QA 经 `answer_qa` 初始化后使用同一链路，不读取历史 rows 或 analysis 作为事实。

原有路由、SQL Agent、检索、澄清和多库未实现分支均保留。本阶段仅调整解释分支，没有全面重构 Workflow。

## 2. State 变化

[state.py](D:/agent_study/askdata_studio/backend/app/workflows/state.py) 增加独立、可 JSON 序列化的产物：

| 字段 | 生产位置 | 使用方 |
| --- | --- | --- |
| `execution_result` | 执行结果恢复与一致性校验之后 | Table、交付请求的执行身份绑定 |
| `signal_batch` | SignalEngine | 白名单 ExplanationContext Builder、审计 |
| `prompt_package` | 既有 Prompt Builder | ResponseGenerator |
| `explanation_response` | ResponseGenerator 及受控失败分支 | ResultBuilder / API |

`execution_result` 保存独立的执行快照，包括原 SQL、列、行及已有 ResultContract。这些内容不作为 Prompt 构建输入。解释链只对快照生成技术摘要，用于识别当前执行。

`signal_batch` 保留完整 Signal/Evidence 审计内容；Prompt 仅消费既有白名单投影。ExplanationContext 是节点内局部变量，不把 BusinessContext 放入新解释状态。

每次请求开始及解释链开始时覆盖或清空派生产物。旧 `explanation_prompt_package`、`explanation_task_id`、`explanation_for_query` 仅作为废弃字段清空，不再消费；外部传入的旧包不能绕过 SignalEngine。

## 3. SignalBatch 接线与受信交付合同

新增 [signal_delivery.py](D:/agent_study/askdata_studio/backend/app/workflows/signal_delivery.py)：

```python
class SignalSource(Protocol):
    def __call__(self, request: SignalRequest) -> SignalDelivery | None: ...
```

`SignalRequest` 包含 task_id、query、session_id、user_id、route、execution_result_id、execution_digest；不包含 rows、SQL、BusinessContext、ResultContract 或历史上下文。

`SignalDelivery` 包含原 request 和有序 `tuple[BusinessSignal, ...]`。请求与交付采用严格、冻结、拒绝未知字段的模型。

正式配置入口：

```python
service = AskDataService(signal_source=trusted_signal_source)
# 或直接配置 QueryWorkflow(..., signal_source=trusted_signal_source)
```

已有 HTTP `submit` 流程自动经过新的 Graph 节点；服务端来源必须返回当前请求对应的已计算结果。来源可以返回 None，表示没有当前可交付的业务 Signal。默认未配置来源时明确 unavailable。

交付校验包括：

1. task、query、session、user、route 以及执行身份与当前请求完全相同。
2. 数据库路径要求非空 execution_result_id 和 execution_digest；QA 没有当前执行快照，两项必须为 None。
3. 逐个检查带 Evidence 的 computed/undefined Signal 必须引用当前 execution_result_id，避免一条命中掩盖其他陈旧 Signal。
4. 在序列化前检查原始结构，拒绝非法 model_copy、隐藏扩展字段和错误类型；随后 JSON 严格重验并返回独立对象。
5. 状态一致性、展示资格和引用完整性仍由现有 SignalEngine 负责；失败或缺 Evidence 的记录不会被交付层补造成 computed。

`execution_digest` 使用 SHA-256 对完整已验证执行 JSON 快照作规范序列化摘要：UTF-8、稳定键顺序、紧凑分隔、拒绝 NaN 和非 JSON 值。同一个 result_id 对应的 SQL、行或元数据变化，也会改变请求快照绑定。它不读取 clock、生成随机 ID 或计算业务值。

这是防止错误复用的调用关联，不是签名或业务真实性证明。受信 SignalSource 仍负责上游事实来源、完整输入选择和访问授权，不能把旧 Signal 重新包装成当前交付。本阶段未自动创建 selection、Policy、声明、Compatibility 或 Alignment。

## 4. Prompt 与 Response 路径

[build_signal_batch](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:236) 调用未修改的 SignalEngine；[build_explanation_prompt](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:280) 恢复本轮 Batch 并调用既有两个 Builder。

Prompt 的 question 使用当前 query，作为既有协议下的不可信问题文本。模型输入没有新增原始执行字段、自由文本业务上下文或完整 Evidence。

[generate_explanation](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:292) 仅将本轮 PromptPackage 交给 finalize / answer_qa，并调用 `validate_response_for_package`，保证生成事实和引用属于该包。不得将其他有效包的响应重新绑定到当前结果。

没有 PromptPackage 时只允许已有的受控 unavailable 状态通过；旧 generated 响应及畸形响应均不能回灌。ResponseGenerator、Prompt Builder、Evidence Builder 和受控表达策略沿用既有实现。

## 5. 失败处理

| 情况 | 结果 | 模型行为 |
| --- | --- | --- |
| 未配置来源 / 来源返回 None | unavailable / NO_SIGNAL_BATCH | 不调用 |
| 来源抛异常 | unavailable / SIGNAL_DELIVERY_FAILED | 不调用 |
| 交付类型、结构或请求绑定错误 | unavailable / INVALID_SIGNAL_DELIVERY | 不调用 |
| Engine 或 Batch 合同异常 | unavailable / INVALID_SIGNAL_BATCH | 不调用 |
| 空 Batch / 仅失败 Signal | not_requested / NO_DISPLAYABLE_FACTS，保留审计 notice | 不调用 |
| Context 投影或 Prompt 构建失败 | unavailable / PROMPT_BUILD_FAILED | 不调用 |
| PromptPackage 校验失败 | unavailable / INVALID_PROMPT_PACKAGE | 不调用 |
| LLM 调用失败 | failed / LLM_CALL_FAILED | 不回退 |
| 非法 LLM 响应 / 响应串包 | failed / INVALID_LLM_RESPONSE | 不发布候选事实 |
| SQL 失败或执行契约冲突 | unavailable / EXECUTION_UNAVAILABLE，执行仍为 failed | 不调用来源或模型 |

所有解释不可用分支都使用受控状态和固定文本，不回显来源或模型 exception 原文，不尝试从 SQL rows、旧 analysis_context、recent_result_context 或 short_term_context 补答案。

独立审查发现并修复：缺字段的 typed SignalDelivery 可在结构检查时抛 AttributeError，导致成功表格无法返回。交付验证边界现统一捕获异常并返回 INVALID_SIGNAL_DELIVERY；永久负向测试覆盖该场景。

## 6. Table / Explanation 分离

[ResultBuilder.with_explanation](D:/agent_study/askdata_studio/backend/app/workflows/result_builder.py:38) 只把已验证的响应附加到已有 QueryResult，不从表格生成业务事实。

- SQL 成功：原 status、sql、columns、rows、检索信息和工具记录保留。解释成功与否由 `explanation` 单独反映。
- 解释失败：表格查询仍为 completed；`analysis` 为固定的解释不可生成说明。
- QA 没有解释：返回 failed，并保留结构化解释状态，不再声称复用历史分析。
- SQL 失败：保留原执行错误，`QueryResult.explanation` 与 state.explanation_response 同步记录 EXECUTION_UNAVAILABLE。

现有 Table UI 未修改；它继续读取 QueryResult.rows/columns。旧 analysis 字段只用于兼容显示当前经验证的 ExplanationResponse.text。原 Interpretation/analysis_sources 展示元数据未送入新 Prompt。

## 7. 测试与回归

新增 [test_query_graph_explanation_migration.py](D:/agent_study/askdata_studio/backend/tests/test_query_graph_explanation_migration.py)，覆盖：

- 完整 compiled Graph 以及 AskDataService 正式入口的来源注入。
- 真实 S1/S2/S3 Calculator 预先产生的结果，真实 SignalEngine、Context/Prompt Builder、ResponseGenerator 和响应校验。
- 缺来源、None、空 Batch、仅失败 Signal、来源异常、畸形 typed delivery、Engine 错误。
- Prompt 投影与构建失败、LLM 失败、非法输出、其他包响应误用。
- task/query/session/user/route 绑定变化、逐 Signal 执行引用、同 result_id 的执行内容变化。
- 真实 ResultContract 模型的正向输入：顶层没有 result_id 时从合同取得身份，完整列元数据参与执行摘要，Decimal canonical 与原 Table 展示均保留。
- 旧包和旧 checkpoint 解释清空，Signal/输入 state/执行数据不修改。
- SQL/rows/Schema/历史分析哨兵不进入实际模型 Prompt，表格正常返回。
- State、Delivery、SignalBatch、PromptPackage、ExplanationResponse、QueryResult 的 JSON roundtrip。
- 固定来源与固定模型候选的 A→A、A→B→A；解释节点不重复上游计算。

上一阶段 `test_response_generator_migration.py` 的 33 个测试保留；涉及 Graph 的场景迁移到新的受信交付链，纯 ResponseGenerator 契约断言继续运行。旧执行契约与 Service 测试仅更新节点拓扑和 NO_SIGNAL_BATCH 预期，未删除原表格、路由或合同验证断言。

| 测试集合 | 结果 |
| --- | --- |
| 新 QueryGraph migration | 30/30 |
| 既有 ResponseGenerator migration | 33/33 |
| Explanation（原 82 + 新 Graph 30） | 112/112 |
| Business Signal | 654/654 |
| Workflow/Service（执行契约 15 + Graph 30 + Service 25） | 70/70 |
| backend full | 1216/1216 |

各分组存在重叠，不相加计算 backend 总数。Business Signal、Explanation、Workflow/Service 均做了分组验证；最终新增合同身份场景后再运行完整 backend。最终全量命令为在 `backend` 目录运行 `.\.venv\Scripts\python.exe -m unittest discover -s tests -q`，1216 个测试于 29.348 秒内全部通过。

测试中的业务 Signals 来自既有 Calculator fixture；SQL 获取和 LLM 输出在外部边界使用替身。新节点及 Engine/Builder/响应校验运行真实实现。本阶段不声称远端模型输出逐字确定，也未新增自动 SQL→业务计算选择器。

## 8. 修改范围与剩余边界

新增 `signal_delivery.py`、新 Graph 迁移测试和本报告。修改 query_graph.py、state.py、result_builder.py、AskDataService 构造器、ExplanationResponse 诊断 code，以及三个涉及旧接线预期的测试文件。

与本轮开始时 122 个既有源码/测试文件的 SHA-256 快照比较，仅上述 8 个既有文件变化。Phase 3 Calculator、SignalEngine、Compatibility、Alignment、Numeric Reader、Evidence Builder、既有 Context/Prompt Builder、ResponseGenerator 以及前端均未修改。

`git diff --check` 通过；未执行 git add、commit 或 tag，原暂存状态保留。新增交付模块、测试和报告目前为未跟踪文件，尚未加入暂存区。

剩余边界：

1. 正式 Graph 消费链与服务器来源注入已完成。默认部署没有自动业务生产来源时，仍明确不可解释；不会自动从任意查询选择 S1/S2/S3 或补足比较结果。
2. 来源必须交付已经完成语义、资格和计算步骤的 Signal，并负责与请求对应及访问权限。本轮未实现其业务查询、选择、Policy/声明管理或跨任务 Signal 仓库。
3. 数据库路径只接受关联当前执行的可展示 Signal；只涉及历史结果的受信业务解释使用 QA 路径。QA 也必须重新获得当前请求的受信交付，不能读取旧 analysis 当作业务事实。
4. 完整 Batch/Evidence 和执行快照保存在内部 Graph state；长期审计归档与新的引用 UI 不在本轮范围。

**本阶段未实现：Workflow 全面重构、多轮 Agent 解释、Prompt 优化。** 仅完成用户确认的局部 Graph 接线范围，未改动冻结的业务计算逻辑。
