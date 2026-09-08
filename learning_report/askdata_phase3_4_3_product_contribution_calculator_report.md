# Phase 3.4.3 Product Contribution Calculator Report

已实现 S3 Product Contribution Calculator。输出为 `BusinessSignal(signal_type="product_contribution")`，计算字段仅有 `contribution_rate`。本轮新增 72 项 S3 测试，backend 从 988 项增至 1060 项，全部通过。

本阶段未实现 **Evidence Integration、SignalBatch、Engine、Workflow**。S3 没有 SQL、数据库访问、LLM、Agent 或风险/告警/建议功能；不重跑 Compatibility、Alignment，也不直接读取 rows。

## 1. Input contract

公开入口：

```python
compute_product_contribution(
    inputs: ProductContributionInput,
    compatibility: ContextCompatibility,
    alignment: AlignmentResult,
    policy: ProductContributionPolicy,
) -> list[BusinessSignal]
```

`ProductContributionInput` 仅包含必填的 `parts: SignalInput` 和 `total: SignalInput`。不推断角色，不制造 Context、selection、声明或分母。入口重新验证并分离嵌套模型快照，避免结果与调用方共享可变容器。

进入数值读取前依次确认：当前完整输入与 Policy 对应当前 Compatibility receipt；实际 Policy 定义在支持范围；Compatibility 为 compatible；operation 为 divide，角色顺序为 parts/total；Alignment 内容绑定同一 receipt；Alignment 为 aligned，且已确认的配对完整覆盖 parts。

结构不合法的参数抛出 TypeError/ValueError；合法模型中的业务失败返回明确状态，不产生计算值。绑定指纹用于拒绝旧结果误用，不是安全签名或身份认证。

## 2. Policy gate

新增两个显式 factory，数据库和获准声明 issuer 必须由调用方传入，广播默认禁止，需显式 `allow_global_total=True`。

| 固定定义 | parts key | parts / total metric | total grain |
| --- | --- | --- | --- |
| category_sales_contribution_v1 | orders_current.category，string | 同一 database 的 SUM(orders_current.paid_amount) | global_aggregate |
| product_sales_contribution_v1 | orders_current.product_id，integer | 同一 database 的 SUM(orders_current.paid_amount) | global_aggregate |

两个 profile 均要求 `actual_paid_sales`、等价销售口径、相同显式有界日期期间、`status='已支付'`、相同单位及比例、完整分区与总体、同一 revision。期间采用 `same_bounded_period`，没有额外限制为整月，也不从表名或系统时间推断。

门禁同时核对 policy_id、version、完整实际定义和内容 digest。泛型 ProductContributionPolicy 即使重新生成 digest 并取得新的成功 receipt，也不能扩展到 customer、region、profit、margin 或放宽 completeness。output_name 不参与口径选择。

允许配置的范围限于已受类型约束的 NumericRules、声明 issuer allowlist、显式 key mapping；数据库必须在各来源间一致。其余业务规则保持固定。

`definition_digest` 对展开默认值后的实际 Policy 内容生成 SHA-256，只排除 digest 本身；JSON 对象键排序、数组保留顺序、保留标量类型、固定分隔符和 ASCII 转义。没有 UUID、时间或随机输入。

## 3. Broadcast handling

读取配对前验证 Alignment binding。全局总额复用必须同时具备：所有 pair 为 matched、`broadcast=True`、`right_row_index=0`，Alignment 明确声明 total 可广播，parts 行索引恰好完整覆盖一次。拒绝混合广播标记、多行 total、total key selection、缺失或重复业务键；不取第一条、不自动聚合、不补零。

当前上游对两个获准 global-total profile 实际产生的正常配对均为 `matched + broadcast=True`，包括单个 part。Calculator 另接受单次消费、无分母复用的普通 matched 形状；该非广播分支仅有形状 helper 单测，**没有声称它已有真实 producer 端到端成功样本**。本轮没有为测试伪造并重签成功 Alignment。

每个输出只增加有序 `operand_references=[parts,total]`，保留 result_id、context_digest、column_id、ordinal、row_index 和 pair 的 broadcast 标记。绑定失败时保留可确认的输入身份，row_index/broadcast 为 None，不引用不可信的行位置。

这些定位信息不是 SignalEvidence。S3 的 `evidence=[]`、`input_evidence_ids=[]`，ObservedValue 的 evidence_id 未生成；输出保留 `EVIDENCE_INTEGRATION_PENDING` 提示。未调用或修改 Evidence Builder。

## 4. Completeness check

完整性资格由既有 Compatibility 判断。Calculator 通过固定 Policy 定义门禁和当前 receipt binding 确认以下资格仍属于当前输入，不重新实现相同检查：

- complete_query_output，未截断。
- parts 为完整分区，total 为完整总体，声明 coverage 为 complete。
- row_selection 声明存在且内容为 absent；拒绝 LIMIT、TopN。
- snapshot revision 一致。
- 同期间、同过滤口径、同单位，parts grouped 与 total global_aggregate。

数值恰好相等不能代替 population/row_selection 声明。Calculator 不查询预期产品全集；没有观测到的产品不会被制造为零销售产品。空 parts 不生成虚构业务键。

## 5. Partition reconciliation

Numeric Reader 成功读取全部输入后，先核对完整分区，再计算任何单项贡献率。total 只读取一次，每个 part 读取一次。

默认 exact：`sum(parts) == total`，不使用隐藏 epsilon。显式 relative_tolerance 时，阈值为 `abs(total) * Decimal(relative_tolerance)`，当前受支持 NumericRules 的容差是 `1e-12`。同时检查完整分区残差和单项超过 total 的部分；等于阈值允许，超过阈值拒绝。

实际使用非零容差时记录 `PARTITION_WITHIN_RELATIVE_TOLERANCE`。允许浮点来源并不自动启用容差。容差内略大于 1 的计算结果保持原值，不截断为 1，也不修改最后一个比例来强制和为 1。

累计和不套用单个输入的大小上限。按现有最多 10000 项、最大数量级和 18 位小数的限制，累计所需有效数字不超过 60 位；局部精度为 80。另防御检查中间运算 Inexact，发生时返回 PARTITION_PRECISION_LOSS，避免用已经失真的累加值批准分区。

## 6. Decimal formula

`part_sales / total_sales` 的两个数值均来自 `read_numeric_value(context, selection.metric_column_id, row_index, rules, unit_id=...)`。单位仅从当前成功 receipt 已使用的声明解析，不重做单位 Compatibility。

比例计算使用独立 `decimal.Context` 和 `localcontext`，精度 80，按 Policy 的 12 位小数及 ROUND_HALF_EVEN 输出十进制字符串。没有 float 公式，没有 global context 修改；调用方的精度、指数范围、flags 和 traps 不影响结果。

来源精确性与运算舍入分开记录。Decimal 保留 exact；显式允许的 DOUBLE 保留 approximate；非终止比例记录 rounded。失败或 undefined 没有伪造计算品质，已读取 current/reference 的原始品质仍保留。

## 7. Zero total

| 已读取完整分区 | 输出 |
| --- | --- |
| total=0，全部 parts=0 | 全部 undefined，reason=ZERO_TOTAL，value=None |
| total=0，任一 part>0 | 全部分区 incompatible_context，ZERO_TOTAL_WITH_POSITIVE_PART |
| total>0，某个 part=0，且分区核对通过 | 该项 contribution_rate=0.000000000000 |
| 很小但非零的 total | 按真实 Decimal 值核对和计算，不视作零 |

零分母路径不调用比例公式。零与负零按真实数值处理；没有 Infinity、NaN 或默认比例。负 part/total 由 NumericRules 拒绝，不自动取绝对值。

## 8. Failure handling

回执不匹配、Policy 越界、Compatibility 不通过、Alignment 不匹配或不通过，均在 Numeric 读取前结束。绑定失败不把旧配对转换成新输入的定位信息。

数值阶段采用完整分区门禁：任意一个 part 或 total 为 NULL、负值、拒绝的编码/类型/数量级，所有贡献率均不计算。混合 Numeric 失败按 unsupported、incompatible_context、insufficient_evidence 的顺序保留阻断状态和原始问题。可读取的操作数仍保存真实 ObservedValue，不补零。

part 超过 total 或累计和不符同样阻止全部输出。max_parts 超限返回 unsupported，不能截取前 N 项计算。没有输出 profit、risk、alert、recommendation。

## 9. Tests

新增 `backend/tests/test_product_contribution.py`，72 项通过。公开 Calculator 正例使用真实 Compatibility → Alignment producer 链；数值精度使用独立 Fraction 舍入 oracle 对照。

| 要求案例 | 覆盖 |
| --- | --- |
| 1–3：category/product_id/global broadcast | 100/400=0.25、多项重排、integer product_id、显式广播与定位信息 |
| 4–7：total 多行/key、LIMIT/TopN、truncated | 全部分区拒绝；缺完整性声明不能由数值补证 |
| 8–10：time/filter/metric mismatch | 不同期间、支付过滤、order_amount、同 alias 异来源、AVG/COUNT 拒绝 |
| 11–13：zero、part>total、NULL | 零和正值矛盾、分区和不符、单项 NULL 阻断全部比例 |
| 14–15：DOUBLE/Decimal | approximate 保留、默认 exact 核对、容差边界、极值、12 位舍入、global Context 隔离 |
| 16–18：receipt/Alignment mismatch、mutation | Policy/selection/声明/rows/语义变更，旧 Alignment 和广播篡改；输入及 Reader 结果不变 |

另覆盖 A→A、A→B→A、相同内容重新构造、JSON roundtrip、输出容器隔离、Negative、重复键和 mapping 冲突、Numeric 调用次数、无上游重跑、无 Evidence Builder、无 SQL/网络/LLM/clock/random。

独立只读复核另外执行 7 项入口/失败链探针、52 次真实数值链探针，以及生产 Reader 结果驱动的 10000 项累加检查；未发现新的 P0/P1。这些探针不计入 unittest 数量。

## 10. Backend regression

使用 backend 现有 `.venv/Scripts/python.exe` 和 unittest 执行：

| 测试组 | 结果 |
| --- | --- |
| S3 test_product_contribution | 72/72 |
| S1 test_target_attainment | 66/66 |
| S2 test_sales_change | 73/73 |
| Evidence test_signal_evidence | 47/47 |
| Business Signal 基础 models/policies/numeric/compatibility/alignment | 352/352 |
| Business Signal 合计 | 610/610 |
| backend full | **1060/1060** |

执行方式为 `python -m unittest discover -s tests -p "<对应测试文件模式>"`；全量使用 `python -m unittest discover -s tests`。上述 610 项是完整 Business Signal 范围合计，不与 backend 数量相加。

对执行前 134 个既有源码文件进行哈希比对，仅 `models.py` 改动；Compatibility、Alignment、binding helpers、Numeric Reader、Evidence Builder、S1/S2、Phase 2、ResultContract 和 Workflow 文件均未改变。S1/S2 各一份正常输出的 JSON 与修改前快照逐字段一致，新字段只在 S3 提供，旧字段的 null 序列化保持不变。

本轮文件：

- 新增 `backend/app/querying/business_signals/product_contribution.py`：Calculator。
- 新增 `backend/app/querying/business_signals/product_contribution_policy.py`：两个固定 Policy factory 和实际内容门禁。
- 扩展 `backend/app/querying/business_signals/models.py`：输入容器、最小操作数定位模型和可选输出字段；不改 S1/S2 公式或状态。
- 新增 `backend/tests/test_product_contribution.py`：72 项专项测试。
- 新增本报告。

没有提交或暂存文件。工作区原有 Phase 3 文件仍为 untracked，本轮保留了该状态；交付文件尚需随项目统一纳入版本管理。

Calculator 实现与本轮回归已完成。**Evidence Integration 留待 Phase 3.4.4；SignalBatch、Engine、Workflow 未实现或接入。** 完整业务审计仍需在后续 Evidence 集成后进行，不能把当前最小定位信息等同于完整 Evidence。
