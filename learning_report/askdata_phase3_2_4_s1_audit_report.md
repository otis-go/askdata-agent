# Phase 3.2.4 S1 Audit Report

日期：2026-09-08

**最终判断：A. Approve S2**

S1 的公式、指标口径、区域对齐、Numeric 安全、Evidence 完整性、失败保护和职责边界均通过本轮审计。未发现新的 P0/P1。现有 backend **915/915** 全部通过，无失败或跳过。

本轮只读：未修改生产代码、测试、Policy 或既有报告，仅新增本审计报告。审计开始保存的 127 个已有源文件/测试/报告的 SHA256 在结束时全部一致。未实现 S2 或其他后续能力。

验证方式包括源码逐层追踪、现有完整回归、真实阶段 producer 正反例、独立 Fraction 舍入对照、输入快照比较和运行时禁止越界调用。除单独说明的结构拒绝场景外，反例使用重新构造的 Context 和内容匹配的新声明，避免把所有拒绝误归因于旧 receipt。

## 1. S1 End-to-End Architecture Report

```mermaid
flowchart LR
  B[BusinessContext] --> I[SignalInput]
  I --> C[Compatibility Receipt]
  C --> A[AlignmentResult]
  A --> N[Numeric Reader]
  N --> T[Target Attainment Calculator]
  T --> S[BusinessSignal]
  S --> E[SignalEvidence]
```

| 层 | 实际职责 | 审计结果 |
| --- | --- | --- |
| BusinessContext | 保存执行快照及 Phase 2 解析/绑定的列、grain、filter、time 语义 | 不执行业务公式 |
| SignalInput | 显式列选择、Context 和补充声明 | 不猜 metric、不制造事实 |
| Compatibility | 依据显式 Policy 判断资格，输出完整输入绑定和规范语义 | 不配对业务行、不计算比率 |
| Alignment | 验证 receipt 属于当前输入，按业务键配对，并绑定完整输出来源 | 不重复指标/时间/单位资格判断，不读 metric 算术值 |
| Numeric Reader | 由 column_id + row_index 定位单元格，校验 codec/type/range，产出 Decimal 工作值 | 不重新判断业务资格，不计算业务公式 |
| S1 Calculator | 检查资格/来源/状态，调用 Reader，处理失败和零分母，计算固定公式 | 不重跑 Compatibility/Alignment，不做查询或解释生成 |
| BusinessSignal | 保存计算结果、状态、Policy 版本/内容摘要和限制 | 与 Evidence 的依据职责分离 |
| SignalEvidence | 复制已有元数据、配对位置、Numeric 快照和公式引用 | 不读取 execution.rows，不计算公式，不产生 computed_value |

真实闭环补充验证从两个捕获 ResultContract 出发，经实际 `build_business_context()` 生成 Context，而非手工填写列语义。提供明确 Schema、完整月份 SQL、8 个区域的捕获数值和匹配声明，链路结果为：

```text
actual Context resolved + target Context resolved
→ Compatibility compatible
→ Alignment aligned
→ 16 次 Numeric ready
→ 8 个 computed S1 Signal
→ 16 份完整 operand Evidence
```

该闭环探针不执行 SQL；SQL 语义解析发生在上游 Phase 2 Builder。调用 S1 期间将 Builder、Compatibility、Alignment、网络、clock 和随机身份入口替换为抛错函数，S1 仍完成计算。额外一组缺少 grain 标签的审计输入被安全判为 insufficient_evidence；补齐明确 Schema 标签后完整链路通过，未改代码或放宽门禁。

代码位置：`result_understanding/builder.py:65`、`models.py:278`、`compatibility.py:748`、`alignment.py:344`、`numeric.py:211`、`target_attainment.py:217`、`evidence.py:25`。

## 2. Formula Audit Report

**通过。** 固定公式为 `actual_sales / target_amount`：实际代码仅对两个 NumericReadResult 的 Decimal work_value 做除法。

| 角色 | 审计 Policy 指标来源 | 聚合 |
| --- | --- | --- |
| actual | askdata_mock.orders_current.paid_amount | SUM |
| target | askdata_mock.sales_targets.target_amount | SUM |

真实 Builder 闭环中的华北：actual 第 0 行为 `100.00`，target 第 2 行为 `200.00`，得到 `0.500000000000`，单位为 ratio。没有反向相除、整数截断、百分比字符串计算或 float 除法。

工作精度 80，输出 scale 12，ROUND_HALF_EVEN；不预先按货币显示精度量化输入，不将超过 1 的比率截断。源读数质量与公式舍入质量分别记录。

证据：`target_attainment.py:31` 的 `_ratio()`、`:184` 的 `compute_pair()`；另以 16 组独立 Fraction/整数 HALF_EVEN 对照验证 Decimal 结果，包括极值、最小非零分母和接近舍入中点的输入。

## 3. Metric Semantics Report

**通过。** 审计使用显式 S1 Policy 的完整 source 三元组、SUM、paid 状态条件及目标 metric-basis 声明。Policy 定义位于 `test_business_signal_compatibility.py:60`；实际判断位于 `compatibility.py:230`，其中 source/SUM 核心检查位于 `:264`。

| 新鲜输入反例 | 结果 |
| --- | --- |
| order_amount 替代 paid_amount | METRIC_SOURCE_MISMATCH，无 computed |
| 相似字段名、尾部空白、错误表来源 | METRIC_SOURCE_MISMATCH，无 computed |
| 错误来源但 alias 伪装成正确 metric | 拒绝，alias 不提供资格 |
| actual 或 target 改为 AVG、COUNT、无聚合 | AGGREGATION_MISMATCH，无 computed |
| MAX | 在 Phase 2 结构模型即拒绝 |
| 保持正确 source/SUM，仅修改展示 alias | 正常计算，证明不依赖 output_name |

口径规则来自显式 Policy 和已捕获 lineage；没有根据相似名称、展示名或表描述猜测指标。Metric/Time 联合 33 项探针中，31 项走完整新鲜输入管线，2 项在结构层拒绝。

## 4. Key Alignment Audit

**通过。** `alignment.py:282` 按规范业务键 token 配对，不按行位置 zip。duplicate 不任选行；missing 保持为空。

独立乱序探针：

| 区域 | actual 行 | target 行 | 比率 |
| --- | ---: | ---: | ---: |
| 华北 | 0 | 1 | 0.250000000000 |
| 华东 | 1 | 2 | 3.000000000000 |
| 华南 | 2 | 0 | 0.200000000000 |

这是独立于第 2 节 100/200 的三地区数据集。华北始终对应华北，而不是两个数组的同一序号。

双侧 missing、双侧 duplicate、跨区域 pair 索引修改、篡改状态提升、旧 Alignment 搭配新 receipt 均拒绝。Alignment 的 13 个提前失败探针均未进入 structure/extract，pairs 数量为 0。完整 Alignment 内容摘要绑定 pair/status/missing/duplicate 等事实，不能仅靠保留 aligned 标签复用旧结果。

## 5. Time Audit

**通过。** actual 由 Policy 指定 `closed_open_month`，使用 `[month-start, next-month-start)`；target 的 `target_month` 由 Policy 指定 `month_equality`，再映射到同一规范月份。

正例覆盖普通整月、2024 年闰年 2 月、12 月跨年上界，以及 orders_current 表中明确声明的 2023-01 数据。旧月份仍能正常通过，说明没有把表名中的 current 当作当前月份证据。

错月、部分月、跨两月、错误开闭边界返回 TIME_PERIOD_MISMATCH；缺失边界时，表名、alias 或 SQL 注释中的月份提示均不能补足证据。缺漏或新增未匹配的日期过滤条件返回 TIME_FILTER_MISMATCH；非法 2024-02-30 被判为 unsupported。

Metric/Time 的 6 个正例正常 computed，25 个完整管线反例全部非 computed，Numeric 调用均为 0。时间判断在 Compatibility；S1 只验证该回执仍属于当前输入。

证据：`compatibility.py:326`、target 月等式展开 `:354`、actual 半开月判断 `:373`、filter 对照 `:442`、跨 Context 月份关系 `:628`。

## 6. Numeric Audit

**通过。** 所有公式输入来自 `read_numeric_value(context, selection.metric_column_id, pair.row_index, rules)`。S1 和 Evidence 的 AST 中均没有直接 `.rows` 或 `['rows']` 单元格取数。

完整输入的复制和 canonical hashing 会访问快照用于身份比较，这不等于公式取数；算术仅使用 Reader 返回的 Decimal work_value。Evidence.raw_value 也只复制 NumericReadResult，不再读单元格。

验证内容：

- NULL 保留 sql_null；missing 保留 missing；不转零。
- negative、非法 decimal text、codec/type 不符、超出边界等拒绝。
- DOUBLE 默认 exact Policy 拒绝；显式 approximate Policy 才允许，并保留 approximate 来源质量；Decimal + DOUBLE 混合仍为 approximate。
- 16 组 Fraction 舍入对照、11 组零值/失败、3 组 DOUBLE Policy、4 组巨大零指数场景均符合预期。
- 另对 3 组真实 DuckDbEngine 输出进行 Numeric/Decimal 对照：DECIMAL 100/200、最大 DECIMAL38 与 1e-18 分母、DOUBLE 0.1/0.3。该补充只验证 producer 数值路径，不替代完整资格链路。

输入幅度 `<10^38`、允许 scale≤18，非零分母最小 `10^-18`；商和 12 位输出小数可容纳于 80 位工作精度。极端调用方 Context（precision=2、窄指数边界、traps/flags 开启）不影响 1/3 的正确计算，且调用前后的全局状态完全相同。

证据：`numeric.py:211`、`:345`；`policies.py:169`；`target_attainment.py:31`、`:184`。

## 7. Evidence Completeness Report

**通过。** 先核对真实 Builder 闭环全部 8 个 Signal 的 16 个操作数，再用固定种子 324 在审计程序中抽取 4 个 Signal，抽样可复现。随机抽样只发生在审计工具中，未进入业务实现。

以下每个 actual 均来自 `audit-s1-actual-2026-08`，每个 target 均来自 `audit-s1-target-2026-08`；两个操作数 column_id 均为各自结果内的 `col_m`，ordinal=1。

| 抽样区域 | actual row_index / value | target row_index / value | attainment_rate |
| --- | --- | --- | --- |
| 华中 | 6 / 1.00 | 6 / 3.00 | 0.333333333333 |
| 港澳 | 7 / 333.00 | 1 / 111.00 | 3.000000000000 |
| 西北 | 5 / 500.00 | 3 / 1000.00 | 0.500000000000 |
| 华北 | 0 / 100.00 | 2 / 200.00 | 0.500000000000 |

逐操作数核对结果：

- result_id、column_id、row_index、ordinal 能定位回原 Context 的捕获单元格。
- raw_value 与 observed_value.value 一致，NumericQuality 与 Reader 快照一致。
- 这些 Decimal 输入的 source_fidelity=exact、source_kind=decimal_text、input scale=2；华中 1/3 的公式 rounding=rounded，与输入 exact 不冲突。
- 两个 Evidence 都引用 `formula_id=attainment_rate`、`formula_version=1`。
- Signal 的 policy_version=1，policy_digest 等于 receipt.binding.policy_digest，确实由实际 Policy 内容产生。
- ComputationResult.input_evidence_ids 完整关联 actual:metric、target:metric；每个 computed Signal 恰有两侧输入依据。
- source_fields/SUM、完整 unit declaration、原时间粒度、规范期间和业务键均保留；JSON 往返不丢失。

模型职责符合要求：BusinessSignal.computed_value 保存比率；SignalEvidence 不含 computed_value，也不生成 signal_id。

## 8. Failure Safety Report

**通过。** 没有观察到以下失败条件产生错误 computed：

| 条件 | 结果/保护 |
| --- | --- |
| target=0，包括负零、0/0 | undefined，ZERO_DENOMINATOR，不执行除法 |
| missing target/actual | insufficient_evidence，整体 Alignment 门禁失败，数值不读取、不补零 |
| duplicate region | incompatible_context，保留冲突，不选择其中一行 |
| NULL actual | insufficient_evidence，保留 sql_null 和实际位置 |
| Numeric reject | unsupported/incompatible_context 等原失败状态，无比率 |
| Compatibility 未通过 | 沿用非 compatible 状态，无 Numeric 读取 |
| Compatibility 与当前输入/Policy/selection/declaration 不符 | COMPATIBILITY_RECEIPT_MISMATCH，无 Numeric 读取 |
| Alignment 与当前 receipt 或自身原输出不符 | ALIGNMENT_RECEIPT_MISMATCH，无 Numeric 读取 |
| 缺失/未知版本 receipt binding | 拒绝，不接受旧成功标签作为资格 |

输入读取必须双方 ready 后才处理零分母；NULL/negative/invalid 不会因另一侧目标为零而被改判成可计算数值。数值失败优先级保持 unsupported > incompatible_context > insufficient_evidence。

39 个 Alignment/gate 探针全部符合预期：3 正例、23 个 S1 拒绝例、13 个 Alignment 提前拒绝例。其中 23 个 S1 反例的 Numeric 调用数=0、公式调用数=0。未发现零填充、默认目标、未声明单位或名称猜测。

## 9. Determinism Report

**通过。** 对真实 Builder 的 8 区域输入验证 A→A；将 actual 华北从 100.00 改为 150.00，重新构造 Context/声明/receipt/Alignment 得到 B，再调用 A，结果与首次 A 完全相同。相同内容重建模型同样通过。

生产计算链没有 random、clock、uuid 身份生成。结果顺序由规范键排列；摘要使用稳定序列化。signal_id 保持当前明确未冻结策略：None，并带 SIGNAL_IDENTITY_NOT_FROZEN 提示；没有为本次审计临时制造 ID。

## 10. Purity Report

**通过。** 真实链路前后深比较以下对象，均保持不变：

- ResultContract、原 BusinessContext 和 Schema；
- SignalInput、Policy、Compatibility Receipt、AlignmentResult；
- S1 内部实际取得的 16 个 NumericReadResult，与各自返回时的深拷贝快照一致；
- 全局 Decimal context 的精度、rounding、指数范围、flags、traps。

修改返回 Signal 的 Evidence.source_fields 和 unit_declaration.column_ids，不影响任何上游对象或后续 A 计算。Evidence Builder 的独立深拷贝和禁用 execution.rows 访问也由现有 47 项专项测试验证。

## 11. Boundary Report

**通过。** S1 没有 Agent 规划、SQL 生成、SQL 执行、Workflow 或 LLM 解释逻辑。Evidence 只组装既有依据，不重跑任何上游业务阶段；Compatibility/Alignment/Numeric 的职责仍分离。

审计基于当前捕获事实契约、显式 S1 Policy 和对应授权声明。Policy 定义与声明真实性由上游提供；receipt 摘要用于防止错误复用，不是签名或外部真实性认证。

NumericReadResult 没有独立的完整 cell 来源绑定，通用 Builder 由调用方保证来源；本轮已验证 S1 自己按已绑定配对、明确列 ID 调用 Reader，并完整传递该结果，因此该已知边界未构成本次闭环阻断。

未实现 S2、S3、SignalBatch、Engine、Workflow，也未接入这些能力。本结论允许继续 S2 开发，不会自动启动实现。

## 12. Regression

在 backend 目录使用现有虚拟环境运行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_target_attainment.py -q
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_signal_evidence.py -q
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_business_signal_*.py' -q
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

| 回归组 | 结果 |
| --- | ---: |
| S1 | 66/66 |
| Evidence | 47/47 |
| 其他 Business Signal | 352/352 |
| Business Signal 总计 | 465/465 |
| backend 全量 | **915/915** |

backend 全量运行 22.057 秒，未跳过测试。额外审计探针以只读临时调用执行，没有写入或更改测试文件，也没有改变 915 项基线。`git diff --check` 通过。

本轮开始时 Phase 3 文件本已未跟踪；审计未 stage/commit。结束时全部 127 个既有文件哈希一致，源码和测试零修改；仓库仅新增本 Markdown 报告。

## 13. Final Decision

| Approve 条件 | 判断 |
| --- | --- |
| 公式正确 | 通过 |
| Metric 口径正确 | 通过 |
| Alignment 正确 | 通过 |
| Numeric 安全 | 通过 |
| Evidence 完整 | 通过 |
| 异常安全 | 通过 |
| 无业务越权 | 通过 |
| 全部测试通过 | 通过：915/915 |

**A. Approve S2**

本轮未发现新的 P0/P1，无需在进入 S2 前修复阻断项。S2 本轮未实现。
