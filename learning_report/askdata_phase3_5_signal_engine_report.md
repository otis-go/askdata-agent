# Phase 3.5 Signal Engine Report

已实现 SignalBatch 与 SignalEngine，将既有 S1/S2/S3 BusinessSignal 组织为有序批次，并提供经过状态和 Evidence 引用检查的展示子集。Engine 不重新计算，也不调用计算器或基础层。

新增 Engine 测试 **22/22**；全部 Business Signal **654/654**；backend **1104/1104**，相对 1082 项基线无回归。

本阶段未实现 **ResponseGenerator、Workflow、LLM 或 Prompt 设计**。没有改动 S1/S2/S3 Calculator、Evidence Builder、Compatibility、Alignment 或 Numeric Reader。

## 1. SignalBatch Contract

新增独立 [batch.py](D:/agent_study/askdata_studio/backend/app/querying/business_signals/batch.py)，不改变既有 Signal 模型。

| 字段 | 含义 |
| --- | --- |
| version | Batch 契约版本，当前为 1 |
| batch_id | Engine 返回 None；身份算法未冻结，不生成随机或时间 ID |
| signals | 全部原始 BusinessSignal，包括成功、undefined、失败以及不可展示的记录 |
| created_contexts | 本批次引用的已有 Context 身份，不创建 BusinessContext |
| displayable_signal_indices | 可展示记录在 signals 中的有序索引 |
| status_counts | 原始 Signal 的五种顶层状态计数，包含值为 0 的状态 |
| limitations | 批次级筛选或一致性问题，附排序后 signal_index |

`BatchContextRef` 仅保存 result_id、context_digest、context_version、result_contract_version。按最终批次顺序第一次出现去重；同一 result_id 的不同 digest 或 version 保留为不同快照，不擅自合并。

`BatchLimitation` 保存 code、signal_index 和 message。上游 limitation 继续保存在各自 Signal 内，不搬运或重解释。

Batch 没有单一顶层成功/失败状态，避免一个失败 Signal 覆盖其他结果。status_counts 统计的是原始状态；实际展示数量应读取 displayable_signal_indices，不能把 computed 计数等同于通过引用检查的数量。

## 2. SignalEngine 入口与顺序

新增 [SignalEngine](D:/agent_study/askdata_studio/backend/app/querying/business_signals/engine.py:31)：

```python
from app.querying.business_signals.engine import SignalEngine

# 三组变量均为上游已经产出的 BusinessSignal 列表。
batch = SignalEngine().build([*s1_signals, *s2_signals, *s3_signals])

eligible_signals = batch.displayable_signals
payload = batch.model_dump_json()
```

入口接受有序 list 或 tuple。V1 固定按 S1 → S2 → S3 分组，同类型保持调用方的输入顺序。排序只操作新建的外层集合，不排序原输入，不按数值、严重性、置信度或 LLM 评分排序。

重复传入的 Signal 保留，不进行自动去重、数值合并、再求和或平均。没有计算 job、计算器分发 registry 或自动选择业务信号的逻辑。

## 3. 状态与展示规则

“进入响应”在本阶段只定义数据资格；没有实现响应生成器。

| Signal.status | 展示资格 | Batch 中的处理 |
| --- | --- | --- |
| computed | 状态及 Evidence 引用一致时允许 | 保留原始计算值与 Evidence |
| undefined | 状态及 Evidence 引用一致时允许 | 保留 None、reason 与已计算的其他子输出，不替换成 0 |
| insufficient_evidence | 不进入展示子集 | 完整保留，附 SIGNAL_NOT_DISPLAYABLE |
| incompatible_context | 不进入展示子集 | 完整保留，附 SIGNAL_NOT_DISPLAYABLE |
| unsupported | 不进入展示子集 | 完整保留，附 SIGNAL_NOT_DISPLAYABLE |

状态一致性以子公式输出的最高优先级与顶层状态比较：

```text
unsupported > incompatible_context > insufficient_evidence > undefined > computed
```

这只用于校验已有状态，不重新赋值，也不作为 Signal 排名。S2 baseline=0 时，absolute_change 仍是 computed，change_rate 和顶层状态仍是 undefined，整个 Signal 可以展示；不存在 undefined 自动补零。

合法模型中的顶层/子状态冲突返回 SIGNAL_STATUS_MISMATCH，仅隐藏该 Signal。合法但断裂或错配的 Evidence 引用返回 SIGNAL_EVIDENCE_LINK_INVALID，同样保留原记录，不影响其他合格 Signal。

无序集合、错误元素类型、未知状态/公式版本，以及消费字段的结构非法情况明确抛出 TypeError/ValueError。这类调用契约错误与正常业务失败状态分开处理，不把无法按现有模型 JSON 回读的非法字段当作普通展示过滤。

## 4. Evidence 关联

Batch 直接保留各 BusinessSignal 及其现有嵌套 Evidence，不创建 batch.evidence、不建立全局 Evidence 池，也不重建 SignalEvidence。

展示检查只验证本 Signal 内的身份关联：

- Evidence ID 非空且在该 Signal 内唯一；其他 Signal 中同名 ID 不能补足缺失引用。
- current/reference 的 Evidence ID 不同，并各自指向观察内容一致的 Evidence。
- 操作数角色按 S1 actual/target、S2 current/baseline、S3 parts/total 对应。
- 可展示的两个操作数保留 present 观察，不能是 missing/NULL 却声称已得到可展示计算结果。
- 每个公式的 input_evidence_ids 是有序的 current/reference 两个 ID；不能借用第三个无关 Evidence。
- 每个被引用 Evidence 都有对应 formula_id / formula_version 的关联。

不重新判断 source、aggregation、grain、period、filter、unit 兼容性或 Policy；不重新验证 Compatibility/Alignment receipt，不读取 Numeric。计算值文本原样保留，不再次解析或计算。

S3 total 的 business_key=None、row_index=0、alignment_broadcast=True 等既有事实随原 Evidence 保留；Engine 不重新生成广播 Evidence。

## 5. 引用、纯度与 JSON

`batch.signals` 使用新的外层列表，但其中 Signal 与 Evidence 对象仍是原对象。`batch.displayable_signals` 是返回这些对象引用的 tuple 属性，不作为第二份 Signal/Evidence 集合序列化。JSON 只在 signals 中承载原有记录，通过索引表达展示子集。

Engine 不修改输入列表、Signal、Evidence 或其嵌套字段。契约沿用现有模型的浅冻结行为：由于明确共享引用，调用方也必须将这些嵌套容器视为只读；不能宣称调用方后续主动修改原对象时 Batch 仍具备深隔离。

SignalBatch 模型自身校验全部 Signal 的已消费字段、状态计数、Context 引用和展示索引。索引必须唯一、递增、在范围内，且只能指向一致的 computed/undefined Signal；limitation 的索引也必须有效。JSON 中把失败 Signal 指成可展示、篡改计数或丢失 Context 引用会被拒绝。

普通 JSON roundtrip 会按模型重新解析对象，这是序列化边界行为，不是 Engine 组装时复制 Evidence。A→A 与 A→B→A 输出一致；无随机、时钟或可变 Engine 会话状态。

## 6. 测试与独立复核

新增 `backend/tests/test_signal_engine.py`，22 项全部通过，覆盖：

- 真实 S1/S2/S3 组合、五种状态、空 Batch、S2 部分 undefined。
- 固定类型顺序、同类型原序、重复 Signal 保留。
- 原 Signal/Evidence 对象身份不变，输入集合不修改。
- 同名 Evidence ID 的局部作用域、断裂/重复/错角色/错公式引用、观察不一致、缺 Evidence。
- Context 按完整身份去重，同 result_id 不同 digest/version 保留。
- 非法输入结构、未知版本的明确拒绝；合法缺引用或状态冲突只隐藏。
- JSON roundtrip、展示索引/计数/Context 篡改防御。
- 确定性；所有计算器、Evidence Builder、Numeric Reader、Compatibility、Alignment 及 IO/clock 入口禁止调用时仍能组装。

独立复核发现并关闭了两类本轮新增层的边界问题：消费字段的结构错误原被误作展示过滤，及同步篡改的非法公式版本原可通过关联比较。最终针对 10 类非法消费字段在 Engine 和直接 Batch 构造入口进行 20 次拒绝验证；合法状态/引用失配、跨 Signal 同名 ID 隔离、JSON 防御仍通过。修复仅涉及本轮新模块，没有调整旧计算行为。

## 7. Regression 与文件范围

最终执行结果：

| 测试组 | 通过 |
| --- | --- |
| Signal Engine 新增 | 22/22 |
| 原有 Business Signal | 632/632 |
| 全部 Business Signal | **654/654** |
| backend full | **1104/1104** |

全量命令为 `python -m unittest discover -s tests -q`，工作目录 backend，使用现有 `.venv/Scripts/python.exe`。最终全量运行用时 25.632 秒；相对 1082 项基线新增 22 项，零失败。

本轮仅新增：

- `backend/app/querying/business_signals/batch.py`
- `backend/app/querying/business_signals/engine.py`
- `backend/tests/test_signal_engine.py`
- 本报告。

修改前保存的 110 个既有源码文件哈希全部保持不变，包括 models.py、S1/S2/S3 Calculator、Evidence Builder、Compatibility、Alignment、Numeric Reader、Phase 2、ResultContract 和 Workflow。没有暂存或提交文件。

## 8. 剩余边界

此 Engine 是已有 Signal 的验证与组织层，信任上游受支持计算器产出的计算事实；它不认证 Policy/receipt、不重算数值、不对不同 Signal 再做业务资格判断。

当前只定义固定类型分组、局部展示资格和引用契约。未来响应消费者应使用 displayable_signal_indices / displayable_signals，不把 signals 全量审计记录直接当作展示列表。

**Phase 3.5 SignalBatch / SignalEngine 已完成。本阶段未实现 ResponseGenerator、Workflow、LLM 或 Prompt 设计。**
