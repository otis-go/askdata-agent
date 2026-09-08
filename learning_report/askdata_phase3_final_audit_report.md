# Phase 3 Business Signal Layer Final Audit Report

**最终结论：A. Freeze Phase 3。**

本轮只读审计当前工作区的 Calculation Readiness、S1/S2/S3、SignalEvidence、SignalBatch 和 SignalEngine，未发现新的 P0/P1 或冻结前必须修复的问题。全部 Business Signal **654/654**、backend **1104/1104** 重新运行通过。

冻结范围是既有可信 producer 与只读消费者之间的确定性业务信号契约。SignalBatch 可作为未来解释层的业务事实入口；此结论不表示已经替换现有 ResponseGenerator 或接入 Workflow，也不表示能认证任意外部构造数据的真实性。

没有修改生产代码或测试；仓库仅新增本报告。没有实现 ResponseGenerator、Prompt Builder、LLM 调用或 Workflow 接入，没有创建提交或 tag。

## 1. Architecture Boundary Report

**通过。** 已追踪当前模块职责与依赖：

```text
Execution Layer
  DuckDbEngine → ResultContract：执行身份、列、位置行、编码与执行完整性
        ↓
Semantic Layer
  BusinessContext：lineage、schema binding、grain、filter、time
        ↓
Business Signal Layer
  SignalInput + 显式 Policy / declarations
    → Compatibility：业务计算资格
    → receipt binding：完整输入快照身份
    → Alignment：业务键配对 / 已授权 total broadcast
    → alignment binding：配对结果属于当前 receipt
    → NumericReader：按 column_id / row_index 读取已有数值
    → S1 / S2 / S3：确定性业务计算
    → BusinessSignal + SignalEvidence：结果与依据
    → SignalEngine → SignalBatch：组织、引用检查、展示资格
        ↓
未来 Explanation Layer：仅解释与表达，当前尚未接入
```

ResultContract 的 complete_query_output 明确只是查询输出完整，不等于业务总体完整。[Execution 契约](D:/agent_study/askdata_studio/backend/app/querying/result_contract.py:76)与 [BusinessContext Builder](D:/agent_study/askdata_studio/backend/app/querying/result_understanding/builder.py:61)保留这一区别。

Compatibility 判断 metric、grain、period、filter、unit、coverage 等资格；Alignment 在绑定门禁之后提取键。计算器检查当前 receipt / Alignment 所属快照，然后消费 NumericReader，不重新运行 Compatibility 或 Alignment。Evidence 只记录传入事实，Engine 只组织已有结果。

业务层没有自然语言解释职责。Issue 中的固定诊断文字用于说明状态，不是 LLM 生成的业务判断、建议、告警或风险评分。

## 2. Signal Contract Report

**通过。** 三个 Calculator 均产出统一 [BusinessSignal](D:/agent_study/askdata_studio/backend/app/querying/business_signals/models.py:630)，没有绕过 Contract 的平行结果模型。

| Signal | signal_type | computed_value 固定输出 |
| --- | --- | --- |
| S1 | monthly_regional_target_attainment | attainment_rate |
| S2 | regional_sales_change | absolute_change、change_rate |
| S3 | product_contribution | contribution_rate |

共同保存 status、current_value、reference_value、computed_value、evidence、limitations，以及 Policy ID / version / digest、calculator_version、business_key。S3 的 operand_references 是额外位置引用，没有取代统一 Evidence。

[ComputationResult](D:/agent_study/askdata_studio/backend/app/querying/business_signals/models.py:608)要求 computed 有 value / unit，非 computed 不得携带计算值。模型固定公式名称及对应关系；Engine 再检查顶层状态与各公式状态一致性。S2 的顶层 undefined 可以同时保留已计算的 absolute_change，这是显式的多输出语义。

signal_id、batch_id 保持 None，没有随机身份或时间身份。当前冻结的是 V1 计算与输出契约，不包含新的全局 ID 算法。

## 3. Evidence Completeness Report

**通过。** 本轮补充构造 S1/S2/S3 各 12 个业务键，改变两侧行顺序及 metric ordinal，通过真实 Compatibility / Alignment producer 生成 **36 个 computed Signal、72 份操作数 Evidence**。

每份 Evidence 均核对：

- result_id、context_digest、Context / ResultContract version。
- column_id、ordinal、row_index 与原始单元格、observed value、numeric quality。
- source_fields、SUM、schema binding、metric semantic、grain、time、filter、unit。
- 两侧 Evidence ID、formula_refs、计算输出 input_evidence_ids，以及 Signal 的 Policy 版本和 digest。

使用独立 Fraction 运算与整数 HALF_EVEN 舍入对照 **48 个公式输出**，全部一致。36 个 Signal 进入 Engine 后均通过展示检查。

审计工具使用固定局部种子 351 / 352 / 353，从每类 12 项中随机抽取 3 项；随机性只用于审计抽样，不在生产代码内。以下为各类代表，位置均为零基索引：

| Signal / key | 第一个操作数 result / column / row / value | 第二个操作数 result / column / row / value | 输出 |
| --- | --- | --- | --- |
| S1 / R09 | captured-s1-actual / col_m / 9 / 430.01 | captured-s1-target / col_m / 2 / 610.02 | attainment_rate=0.704911314383 |
| S2 / R04 | captured-s2-current / col_m / 2 / 215.01 | captured-s2-baseline / col_m / 7 / 305.02 | absolute_change=-90.01；change_rate=-0.295095403580 |
| S3 / R01 | captured-s3-parts / col_m / 10 / 38.00 | captured-s3-total / col_m / 0 / 2130.00 | contribution_rate=0.017840375587 |

S3 total Evidence 保留 business_key=None、alignment_broadcast=True，未复制 part 的业务键。旧 S1/S2 路径不强加广播字段。

[Evidence Builder](D:/agent_study/askdata_studio/backend/app/querying/business_signals/evidence.py:25)仅装配既有 Context、selection、AlignmentPair、NumericReadResult、Compatibility 与 formula refs；没有读取 rows、SQL、数据库或计算公式。Evidence 不包含 computed_value；计算结果属于 BusinessSignal。缺失、未读取、NULL 和 rejected 保留真实状态。

## 4. Deterministic Report

**通过。** 对全部 16 个 Phase 3 模块执行 import / AST 审阅，未发现 LLM、SQL parser / executor、数据库、网络、clock、random、uuid 或 datetime 依赖。外部项目依赖限于已有数据契约和语义模型，其余为确定性标准库与模型验证。

SQL / database 字段可能作为已有身份数据被保留或纳入内容摘要；这不是 SQL 解析、执行或数据库访问。NumericReader 读取已有行单元格，Alignment 读取已有业务键，不重新获取数据。

三类公式均使用显式 Decimal Context 与 localcontext，不用 float 公式，也不修改环境 Decimal 状态。Binary float 来源即使转为 Decimal 工作值，仍保留 approximate quality。

本轮补充通过：

- 三个 Calculator 的 A→A、A→B→A 与输入快照不变检查。
- Engine 的 A→A、A→B→A、JSON roundtrip、顺序与引用保留检查。
- 三个独立 Python 进程，PYTHONHASHSEED 分别为 0、1、333，混合 S1/S2/S3 Batch 的 JSON 输出 SHA-256 完全一致：`529639db0a586bf1a511e5ea3d332c15113ee930968b3961d421244543f63ea7`。

[receipt binding](D:/agent_study/askdata_studio/backend/app/querying/business_signals/receipt_binding.py:25)与 [alignment binding](D:/agent_study/askdata_studio/backend/app/querying/business_signals/alignment_binding.py:17)使用稳定 JSON、显式顺序与 SHA-256，不生成身份或重新授予资格。

## 5. Failure Safety Report

**通过。** 回归测试及本轮 **21 个独立失败探针**覆盖 S1/S2/S3 的 zero、NULL、非法 Decimal、missing、duplicate、旧 receipt、当前 receipt 配旧 Alignment。

| 情况 | 审计结果 |
| --- | --- |
| missing / NULL | 明确证据不足，不将缺失值转换成 0 |
| duplicate / ambiguous key | 不取第一条，不按行位置配对，不产生该失败配对的 computed |
| unsupported numeric / codec / profile | 保留 unsupported 或相应拒绝状态，不转换猜测 |
| Compatibility / receipt mismatch | Numeric 读取前拒绝 |
| Alignment failure / binding mismatch | Numeric 读取前拒绝 |
| S1 target=0 | attainment_rate undefined，value=None |
| S2 baseline=0 | absolute_change 正常计算，change_rate undefined / None |
| S3 total=0 | 按分区核对与零分母规则保留 undefined 或拒绝，不产生无穷、NaN 或替代分母 |

既有 Numeric 测试同时覆盖 Decimal、DOUBLE approximate、NULL、未知元数据、错误编码与非有限数值。S3 对全分区数值失败采取整体拒绝，不能跳过坏 part 后继续声称完整分区。

Engine 不修补状态或数值：computed / undefined 只有在引用与状态一致时进入展示子集；insufficient_evidence、incompatible_context、unsupported 保留在 Batch 审计记录中。失败记录的缺失引用不会借用其他 Signal 的 Evidence。

## 6. Coverage Report

**通过，依赖已定义的受信声明边界。** S3 denominator 资格不是由“只有一行”或“parts 加总恰好相等”推断。

| 要求 | 当前检查 |
| --- | --- |
| 已执行且完整的查询输出 | complete_query_output、truncated=False、已知且相等的输出计数；partial / unknown 拒绝 |
| 无行选择 | 两侧当前有效声明 row_selection=absent；LIMIT、OFFSET、TopN、other 拒绝 |
| 完整业务总体 | population=complete，双方相同 population_scope_ref |
| 完整 parts 分区 | partition_key_domains 必须完整匹配获准 category 或 product_id domain |
| 同一快照 | Policy 要求同一 dataset / revision；缺失或不一致拒绝 |
| 独立 global total | global_aggregate、无 total key、恰一行、Policy 显式授权广播 |
| 当前输入身份 | receipt 绑定 Policy、selection、Context、声明全部内容和 normalized semantics；Alignment 绑定当前 receipt / pairs |
| 数值一致性 | 资格通过且所有 Numeric ready 后，再核对 sum(parts) 与独立 total |

依据：[声明与覆盖资格](D:/agent_study/askdata_studio/backend/app/querying/business_signals/compatibility.py:487)、[row selection / population 检查](D:/agent_study/askdata_studio/backend/app/querying/business_signals/compatibility.py:571)、[global total 广播](D:/agent_study/askdata_studio/backend/app/querying/business_signals/alignment.py:253)、[Calculator 门禁](D:/agent_study/askdata_studio/backend/app/querying/business_signals/product_contribution.py:218)、[分区核对](D:/agent_study/askdata_studio/backend/app/querying/business_signals/product_contribution.py:48)。

本轮 **23 个独立覆盖反例全部通过**：parts / total 各自的 LIMIT、OFFSET、TopN、other，incomplete / unknown population，缺 row_selection / population / revision、截断，以及缺失或错误 partition domain、coverage 改动后复用旧 receipt。全部使用真实 Compatibility → Alignment；NumericReader 被异常哨兵替换，证明拒绝发生在数值读取前，contribution value 均为 None。

必须保留的限定：Phase 2 没有结构化 LIMIT / TopN 字段，Phase 3 不扫描 SQL，覆盖资格依赖 Policy 授权且绑定当前输入的真实声明。摘要检测错误复用，不认证 issuer、不证明故意错误声明的真实性。不得将本结论描述成“任意 SQL 或任意调用方都无法伪造完整总体”。这是既有信任边界，不是本轮新发现的冻结缺陷。

## 7. Engine Boundary Report

**通过。** [SignalEngine.build](D:/agent_study/askdata_studio/backend/app/querying/business_signals/engine.py:40)只接收已产出的 BusinessSignal，不进行 job 分发、重算或业务资格重判。

- 固定 S1 → S2 → S3 分组，同类型维持输入顺序，重复 Signal 原样保留。
- [局部引用检查](D:/agent_study/askdata_studio/backend/app/querying/business_signals/batch.py:83)核对状态、操作数角色、Evidence ID 与 formula refs，不读取业务 Context 重新判定 metric、period、filter、unit。
- 保留全部 Signal；displayable_signal_indices / displayable_signals 给出展示子集，不把失败记录丢失或转换。
- 新建外层集合，保留原 BusinessSignal / Evidence 对象引用，不复制 Evidence、不修改输入。
- created_contexts 按 result_id、context_digest、context_version、result_contract_version 去重，不合并同 result_id 的不同快照。
- JSON 回读校验展示索引、状态计数和 Context 引用。非法消费字段明确拒绝；合法业务失败或局部引用失配保留并隐藏。

Engine 22 项回归及独立混合批次探针全部通过。浅冻结意味着共享嵌套容器应保持只读；当前契约不提供调用方后续主动修改对象时的深隔离。

## 8. Explanation Layer Boundary Report

**Phase 3 边界通过；未来接入约束尚未实施。**

未来 ResponseGenerator 的业务事实输入应为 SignalBatch，通过 displayable_signal_indices / displayable_signals 消费可展示结果；可以引用 Evidence 与 limitations 解释依据和不确定性。不能将 signals 中的全量失败审计记录直接当作 computed 展示。

未来 LLM 只负责解释、表达，不从 SQL rows 或 BusinessContext 再做计算、推断指标、补值或判定业务事实；不重新对齐，不绕过 coverage / receipt / Numeric 资格。这个边界是后续解释层的验收约束，本轮没有实现 Prompt 或调用 LLM。

当前仓库已有旧 [ResponseGenerator.finalize](D:/agent_study/askdata_studio/backend/app/querying/response_generator.py:34)，仍接收 SqlExecution / rows 并调用 chat_json，[query_graph](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:403)仍调用旧路径。业务层之外尚无 business_signals 导入。这说明 Phase 3 作为独立层已就绪，不说明全应用已经切换成 SignalBatch-only；按本轮禁止 Workflow 接入的要求，没有修改该旧路径。

## 9. Regression Report

全部重新运行，无新增或修改测试文件：

| 测试组 | 通过 |
| --- | --- |
| Models | 33/33 |
| Policies | 24/24 |
| Numeric Reader | 67/67 |
| Compatibility | 120/120 |
| Alignment | 108/108 |
| S1 | 66/66 |
| S2 | 73/73 |
| S3 Calculator | 72/72 |
| Signal Evidence | 47/47 |
| S3 Evidence | 22/22 |
| Signal Engine | 22/22 |
| **全部 Business Signal** | **654/654** |
| **backend full** | **1104/1104** |

使用 backend 现有 `.venv/Scripts/python.exe` 与 unittest。Business Signal 套件用 5.468 秒；backend full 命令为 `python -m unittest discover -s tests -q`，用 26.910 秒，零失败、零跳过。额外只读探针不计入 1104 项基线。

审计开始保存的 **113 个既有源码文件 SHA-256 全部一致**。报告写入前 git status 与开始时完全一致；本轮仓库新增仅为本报告。既有 Phase 3 生产文件、测试及报告仍是未跟踪工作区文件，没有自动暂存或提交。

## 10. Final Decision

| Freeze 条件 | 判断 |
| --- | --- |
| S1/S2/S3 全部 Audit 通过 | 既有 Audit Approved，本轮统一合同、公式、Evidence、失败路径复核通过 |
| SignalEngine 稳定 | 顺序、引用、状态、JSON、确定性与纯度通过 |
| Evidence 完整 | 36 个成功结果 / 72 份操作数依据逐项核对通过 |
| 无 LLM 依赖 | Phase 3 import / AST 与调用边界通过 |
| 无业务越权 | 不解释、不规划、不获取数据、不重新授予上游资格 |
| 全部测试通过 | Business Signal 654/654；backend 1104/1104 |

**A. Freeze Phase 3。**

建议将已审计的 Phase 3 工作区文件与报告纳入一个可追溯提交后，再执行 `git tag phase3-business-signal-v1`。当前 HEAD 为 `77c1aba97c2a99571a290bd018f6dcfcd5c35d3c`，直接给当前 HEAD 打 tag 不会包含尚未跟踪的 Phase 3 文件；本轮没有创建 tag。

冻结仍保留以下既定边界：受信 producer / declaration 的真实性由上游负责；内容 digest 不是安全签名；Signal / Batch ID 算法尚未定义；共享对象按只读方式消费；旧 ResponseGenerator / Workflow 迁移留待后续阶段。本轮不实现该后续阶段。
