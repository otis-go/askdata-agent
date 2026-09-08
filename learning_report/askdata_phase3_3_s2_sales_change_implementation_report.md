# Phase 3.3 S2 Sales Change Implementation Report

Phase 3.3 已完成：实现 Regional Sales Change，复用既有 Compatibility、Alignment、Numeric Reader 和 Signal Evidence。新增 S2 测试 **73/73**，Business Signal 合计 **538/538**，backend 全量 **988/988**；原有 915 项测试无回归。

本轮没有修改 Phase 2、ResultContract、Compatibility、Alignment、Numeric Reader、Evidence Builder、S1 或既有测试。没有实现 S3、SignalBatch、Engine、Workflow，也没有新增 Agent、SQL 或 LLM 调用。

## 1. 输入契约

入口位于 [sales_change.py](D:/agent_study/askdata_studio/backend/app/querying/business_signals/sales_change.py:247)：

```python
compute_sales_change(
    current: SignalInput,
    baseline: SignalInput,
    compatibility: ContextCompatibility,
    alignment: AlignmentResult,
    policy: SalesChangePolicy,
) -> list[BusinessSignal]
```

调用方提供已针对当前输入生成的 Compatibility 和 Alignment。计算器不会重新判断 Compatibility，不会重新提取或匹配业务键。返回值是单个 BusinessSignal 的列表；没有增加批次模型或编排入口。

门禁依次验证当前完整输入快照的 receipt binding、计算器支持的 Policy 定义范围、compatible 状态、compare 操作及 current/baseline 角色顺序、Alignment 与当前回执和自身内容的绑定。然后确认完整 Alignment 已通过且仅包含非广播的 matched pairs，才调用 Numeric Reader。

绑定沿用已有实现，覆盖实际 Policy 内容、Context、selection、declarations 和规范语义。只保留旧 definition_digest 字符串而改变规则，或修改 selection、声明、数值单元、期间、回执状态、Alignment 行号，都不能复用旧成功证明。缺失或旧版本 Alignment binding 同样拒绝。

| 条件 | S2 行为 |
| --- | --- |
| receipt 不属于当前输入 | incompatible_context / COMPATIBILITY_RECEIPT_MISMATCH |
| 新鲜有效回执，但 Policy 超出 S2 V1 范围 | unsupported / UNSUPPORTED_SALES_CHANGE_POLICY |
| 当前 receipt 配旧 Alignment，或 Alignment 内容变化 | incompatible_context / ALIGNMENT_RECEIPT_MISMATCH |
| missing region、duplicate region、未解析业务键等 Alignment 失败 | 保留失败状态；整个 Alignment 不进行 Numeric 读取 |
| 配对成功后的单个操作数 NULL 或 Numeric 拒绝 | 该配对两个输出都不计算；保留事实和原因，不影响其他已对齐且数值有效的配对 |

`supports_monthly_sales_change_v1()` 只比较 Policy 定义与固定计算器范围，不检查 Context 的 metric、time、filter 或 unit，不替代 Compatibility。这样泛型 SalesChangePolicy 即使显式授权了 order_amount、customer/category 或部分期间，也不能借新回执扩大本计算器的业务范围。

输入会重新验证并建立独立快照。参数类型或内部模型结构无效时抛 TypeError/ValueError；有效但不匹配或不合格的业务输入返回带原因的非 computed Signal。

## 2. Time Policy

新增 [sales_change_policy.py](D:/agent_study/askdata_studio/backend/app/querying/business_signals/sales_change_policy.py:25)，提供：

```python
monthly_sales_change_v1(
    *,
    database: str,
    accepted_issuer_kinds: list[IssuerKind],
    accepted_issuer_refs: list[str],
    numeric_rules: NumericRules | None = None,
) -> SalesChangePolicy
```

Policy ID 为 monthly_sales_change_v1，version 为 1。数据库身份和接受的声明 issuer 必须由调用方显式提供，不默认授予 demo fixture 或生产数据源权限。NumericRules 默认 decimal_exact_v1；DOUBLE 需要显式提供允许 binary float 的 reporting_approx_v1。

| 规则 | current | baseline |
| --- | --- | --- |
| Metric | orders_current.paid_amount / SUM | orders_history.paid_amount / SUM |
| 业务口径 | actual_paid_sales | actual_paid_sales |
| Grain / key | orders_current.region | orders_history.region |
| Time source | orders_current.order_date | orders_history.order_date |
| 时间形状 | date 精度，完整自然月，下界包含、上界不包含 | 同左 |
| 非时间过滤 | status = 已支付 | status = 已支付 |

V1 遵循既有 Phase 3.0 的环比约定：**current 是 baseline 的下一个完整自然月**。例如 current 为 [2026-08-01, 2026-09-01)，baseline 为 [2026-07-01, 2026-08-01)。跨年和闰年由既有日历规则处理；非相邻月、部分月、下界不包含或上界包含均拒绝。

实际期间及结构化时间过滤仍由既有 Compatibility 检查。计算器不根据 current/history 表名推断月份，不读取系统时间。

Policy 同时要求明确的同单位/scale、population、row_selection 和 snapshot_revision 声明，保持 same_revision 约束，不进行货币转换、自动汇总或隐含补数。接受的证据等级保持 trusted_declaration。

Factory 的 definition_digest 来自实际展开默认值后的 Policy 内容，排除摘要字段自身。Canonical JSON 固定对象键排序、列表顺序、标量类型和分隔符，再计算 SHA-256；相同内容可复现。回执继续绑定完整实际 Policy，不能仅相信调用方的摘要标签。这些摘要用于防止错误复用，不是安全签名或声明真实性认证。

## 3. Formula

两个操作数均按已绑定配对的行号和显式 metric_column_id 调用 Numeric Reader，各读取一次。计算器没有直接访问 execution.rows；输入快照与摘要中保留 rows 仅用于来源绑定。

```text
absolute_change = current_sales - baseline_sales
change_rate     = absolute_change / baseline_sales
```

使用独立 Decimal Context：precision 80、ROUND_HALF_EVEN，显式设置指数范围及 traps/flags。差额不预先量化，也不强制保留两位；变化率只在最后量化为 12 位小数。计算不受调用方 Decimal 精度、舍入方式、flags 或 traps 影响，也不修改调用方状态。

| current | baseline | absolute_change | change_rate | 顶层状态 |
| ---: | ---: | ---: | ---: | --- |
| 150.00 | 100.00 | 50.00 | 0.500000000000 | computed |
| 100.00 | 200.00 | -100.00 | -0.500000000000 | computed |
| 100.0001 | 100.0000 | 0.0001 | 0.000001000000 | computed |
| 0.00 | 100.00 | -100.00 | -1.000000000000 | computed |

下降导致负差额和负变化率是合法结果；输入本身的负销售额仍遵循 NumericRules 拒绝。DOUBLE 的来源质量在两个输出中都保持 approximate，Decimal 保持 exact；来源质量与公式的 arithmetic_rounding 分开记录。

复用 BusinessSignal，signal_type 为 regional_sales_change，computed_value 固定包含 absolute_change 和 change_rate。差额使用已被 Compatibility 消费的单位声明，变化率单位为 ratio。没有产生 alert、risk 或 recommendation。

## 4. baseline=0 处理

仅在两个 NumericReadResult 都 ready 后判断零基期，包括负零。保持 Phase 3.0 已定义的两个输出独立状态：

| 项目 | current=150.00、baseline=0.00 |
| --- | --- |
| absolute_change | computed，150.00，原销售单位 |
| change_rate | undefined，value=null，reason_code=ZERO_BASELINE |
| BusinessSignal.status | undefined |
| Evidence | 两个真实输入均为 present，保留实际零值 |

0/0 同样保留 computed 差额 0，比例与顶层 undefined。没有执行除零。NULL 或 missing baseline 不视作零；NULL current 即使遇到 baseline=0，也不会生成可计算差额。

消费者需要同时检查顶层与各 computed_value 的状态，不能把 undefined Signal 中的所有输出统一当作已计算，或丢掉仍有意义的绝对差额。

## 5. Evidence

完整复用既有 `build_signal_evidence()` 与 SignalEvidence，没有增加新的 Evidence 模型。每个配对保留 current:metric、baseline:metric 两个操作数 Evidence，两个计算输出都引用这两个 ID。

| 依据 | 来源 |
| --- | --- |
| result_id、contract/context version、context_digest | 当前输入快照及已有摘要规则 |
| column_id、ordinal、lineage、SUM、schema metadata | selection 和 BusinessContext 的列语义 |
| row_index、business_key、alignment_status | 已验证的 AlignmentPair 对应侧 |
| observed_value、raw_value、dtype/encoding、numeric_quality、numeric_issues | 当前对应单元的 Numeric Reader 结果及 Context 列元数据 |
| normalized metric、period、filters、declarations_used | 已确认属于当前输入的 Compatibility |
| unit declaration、上游 limitations | 已消费的当前输入声明及 Context |
| formula_refs | absolute_change / 1 和 change_rate / 1 |
| policy_id、policy_version、实际 policy_digest | BusinessSignal 保存的当前 Policy 身份 |

缺失侧 Evidence 不编造 row_index、raw_value、business_key 或数值；整体门禁失败时已知但未读的操作数记为 not_read。NULL 保存 sql_null，Numeric 拒绝保存原始捕获值和拒绝原因。Evidence 不含 computed_value，也不执行公式。

正常、undefined、NULL 和 rejected Signal 均通过 JSON roundtrip。调用前后 Context、SignalInput、Policy、Compatibility、Alignment 和实际取得的 NumericReadResult 深比较不变；修改返回结果中的 Evidence 或业务键也不会污染输入。

## 6. 测试

新增 [test_sales_change.py](D:/agent_study/askdata_studio/backend/tests/test_sales_change.py)，**73 项全部通过**。正例使用生产 Policy factory，以及真实 Compatibility 和 Alignment producer；S2 新测试使用捕获的 BusinessContext fixture，不增加 SQL 解析、执行或数据库查询。

| 用户要求 | 验证结果 |
| --- | --- |
| 150/100 | 差额 50，变化率 0.5 |
| 100/200 下降 | 差额 -100，变化率 -0.5 |
| 多个 region、不同 row 顺序 | 按业务键匹配并保留双方真实行号 |
| baseline=0 | 差额 computed、比率与顶层 undefined |
| missing region | 全局 Alignment 失败，无 Numeric 读取，不补零 |
| duplicate key / 未解析键 | 拒绝，不任取一行 |
| NULL | 不计算该配对，保留 sql_null |
| DOUBLE approximate | 需要显式许可，两个输出均保留 approximate |
| Decimal precision | 未量化差额与 12 位 HALF_EVEN 比率通过独立 Fraction oracle |
| receipt mismatch | Policy、selection、声明、值和回执语义变化均拒绝 |
| Alignment mismatch | 旧来源绑定、修改行号或提升状态均拒绝 |
| input mutation | 输入、NumericReadResult、全局 Decimal 状态均不变 |
| Evidence 完整 | 双操作数、双公式、来源、单位和质量均保留 |

额外覆盖固定 Policy 下的 order_amount、相似字段、相同 alias 不同 source、AVG、customer grain；新鲜有效回执下的越界 Policy；完整月开闭边界、跨年和闰年；显式授权参数、实际 Policy 摘要、零指数边界、A→A、A→B→A 及相同内容重构。

通过 mock 禁用上游 Compatibility/Alignment 重跑和网络、clock、UUID 路径，结合源码检查确认计算器没有 SQL、LLM、Workflow 或直接数值 rows 读取。

另作独立只读检查：32 组 Fraction 数值 oracle、6 组零值/巨大零指数、8 组 approximate/拒绝案例，以及 11 项 Policy/回执/Evidence 门禁探针，均符合预期。未发现阻断本次 S2 实现的新 P0/P1；这些临时探针不计入 73 项持久测试。

## 7. backend 回归及变更范围

在 backend 目录运行现有虚拟环境：

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_sales_change.py -q
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_signal_evidence.py -q
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_target_attainment.py -q
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_business_signal_*.py' -q
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
```

| 回归组 | 结果 |
| --- | ---: |
| S2 | 73/73 |
| Evidence | 47/47 |
| S1 | 66/66 |
| 其他 Business Signal：Alignment、Compatibility、Numeric、Models、Policies | 352/352 |
| Business Signal 合计 | **538/538** |
| backend 全量 | **988/988** |

backend 全量运行 22.876 秒，无失败、错误或跳过；基线 915 + 新增 73 = 988。

本轮仅新增以下文件：

- [sales_change.py](D:/agent_study/askdata_studio/backend/app/querying/business_signals/sales_change.py)：S2 计算与输入来源门禁。
- [sales_change_policy.py](D:/agent_study/askdata_studio/backend/app/querying/business_signals/sales_change_policy.py)：显式月度规则和支持范围。
- [test_sales_change.py](D:/agent_study/askdata_studio/backend/tests/test_sales_change.py)：73 项回归。
- 本实现报告。

与本轮开始的快照相比，128 个既有文件哈希一致。既有 Phase 3 文件本来即处于 untracked 状态，本轮保持该状态，未 stage 或 commit。`git diff --check` 通过；新增 Python 文件另行检查无尾随空白。

## 8. 剩余边界

- 当前仅支持上述 paid_amount/SUM、region、相邻完整自然月和明确已支付口径。不支持同比、任意期间、自动聚合、时间推断或隐式单位转换。
- Policy 及声明真实性仍由上游负责。摘要防止错误复用，不认证数据来源；本阶段没有增加信任服务或密钥机制。
- NumericReadResult 仍由计算器按已验证配对和选定列调用 Reader 并直接交给 Evidence Builder；没有重新设计其独立来源契约。
- signal_id 维持 None 与 SIGNAL_IDENTITY_NOT_FROZEN 提示。没有引入时间、随机数或 UUID 身份策略。
- S1 与冻结基础层保持原实现；本轮没有做通用计算器框架重构。
- **本阶段未实现 S3、SignalBatch、Engine、Workflow；没有新增 Agent、SQL 或 LLM 能力。**

本报告交付 S2 实现及回归证据，没有自动启动后续阶段。
