# Phase 3.3.5 S2 Audit Report

**最终结论：A. Approve S3。**

本轮只读审计 Regional Sales Change 的业务闭环，未发现新的 P0/P1。Metric、期间比较、零基期、Alignment、Numeric、Evidence、失败处理及职责边界均通过。全部指定回归重新运行：S2 73/73、S1 66/66、Evidence 47/47、Business Signal 538/538、backend **988/988**。

没有修改生产代码或测试，没有实现 S3、SignalBatch、Engine、Workflow。仓库仅新增本报告。以下结论来自本轮源码检查、重新执行的测试及额外只读探针，并非沿用上一阶段结论。

## 1. S2 Architecture Report

**通过。** 已追踪：

```text
BusinessContext → SignalInput → Compatibility(compare) → Alignment
                → NumericReader → SalesChangeCalculator
                → BusinessSignal → SignalEvidence
```

| 层 | 本轮确认的职责 |
| --- | --- |
| BusinessContext | 保留执行身份、列来源、聚合、grain、过滤与时间事实；不计算业务变化 |
| SignalInput | 显式提供 Context、metric/key selection 和绑定当前 Context 的声明 |
| Compatibility(compare) | 按 Policy 判断来源、SUM、地区粒度、完整相邻月、过滤、单位、声明及快照资格，并绑定完整输入 |
| Alignment | 验证 receipt 身份，按地区规范键配对；记录 missing、duplicate、collision；输出来源绑定 |
| NumericReader | 按 column_id、ordinal 和已对齐行号取得安全 Decimal 工作值及来源质量 |
| SalesChangeCalculator | 验证当前 receipt、Alignment 和支持的 Policy 范围，计算两个固定公式 |
| BusinessSignal | 保存计算结果、各输出状态、Policy 身份和 Evidence 引用 |
| SignalEvidence | 组装已有操作数事实、来源、质量和公式引用，不重新计算或取得数据 |

[S2 门禁](D:/agent_study/askdata_studio/backend/app/querying/business_signals/sales_change.py:178)只验证输入绑定、Policy 支持范围和既有阶段的结果；不重新执行 Compatibility 或 Alignment。Policy profile 比较只针对规则定义，不对 Context 重复检查 metric、time、filter 或 unit。

另外使用固定捕获的 ResultContract、现有 SCHEMA 和真实 BusinessContext Builder，串起真实 Compatibility(compare)、Alignment、S2 及共享 Evidence，验证 8 个地区。该链路调用 Numeric Reader 16 次、公式 8 次、Evidence Builder 16 次；计算阶段禁用 SQL parser、Compatibility/Alignment 重跑及网络调用，仍然通过。

这些审计数据为明确构造的捕获事实和显式授权的 fixture 声明，没有执行数据库 SQL。审计验证的是这些事实进入当前实现后的行为，不把 fixture 当作生产数据库真实性证明。

## 2. S2 Metric Report

**通过。** [Policy](D:/agent_study/askdata_studio/backend/app/querying/business_signals/sales_change_policy.py:83)明确 current 为 orders_current.paid_amount / SUM，baseline 为 orders_history.paid_amount / SUM，业务语义均为 actual_paid_sales，grain 为 region。

[Compatibility](D:/agent_study/askdata_studio/backend/app/querying/business_signals/compatibility.py:268)按数据库、表、字段的完整来源授权，并检查实际 aggregation；没有利用 output_name 猜测 metric。

| 本轮反例 | 结果 |
| --- | --- |
| current/baseline 的 order_amount、相似 paid 字段 | METRIC_SOURCE_MISMATCH |
| 相同 output_name，但来源不同 | METRIC_SOURCE_MISMATCH |
| current/baseline 的 AVG、COUNT、缺失聚合 | AGGREGATION_MISMATCH |
| 只更换合法 paid_amount 输出 alias | 仍可 computed |
| 泛型 Policy 显式授权 order_amount 并取得新 compatible/aligned | S2 返回 unsupported / UNSUPPORTED_SALES_CHANGE_POLICY |

上述业务反例重新签发当前声明、Compatibility 和 Alignment，均在 Numeric 读取前被拒绝，不依赖旧回执不匹配来间接通过测试。category/customer 粒度也不能通过泛型 Policy 扩大本 S2 的支持范围。

## 3. Period Policy Report

**通过。** monthly_sales_change_v1 要求 date 精度、Gregorian calendar、同一时间域的两个完整自然月，且 **current 月份 = baseline 月份 + 1**。

合格示例为 current [2026-08-01, 2026-09-01)，baseline [2026-07-01, 2026-08-01)。两个下界都包含、上界都不包含，比较源是各自的 order_date。检查位于 [自然月边界](D:/agent_study/askdata_studio/backend/app/querying/business_signals/compatibility.py:373)与[相邻期间关系](D:/agent_study/askdata_studio/backend/app/querying/business_signals/compatibility.py:632)。

| 情况 | 本轮结果 |
| --- | --- |
| 2026-08 完整月与 2026-07 完整月 | computed |
| 合法跨年、闰年二月及较早年份的相邻月 | computed |
| current 或 baseline 为部分月 | TIME_PERIOD_MISMATCH |
| 非相邻月、同月、期间倒序 | TIME_PERIOD_MISMATCH |
| 任一侧下界不包含、上界包含 | TIME_PERIOD_MISMATCH |
| 保留 orders_current/history 表名，但删除时间事实 | TIME_UNKNOWN 等不足状态，无 computed |
| 缺失 time_domain 声明 | MISSING_TIME_DOMAIN_DECLARATION，无 computed |
| 新鲜有效回执授权 ship_date、bounded_range 或放宽完整/有界要求 | S2 Policy profile 拒绝，无 Numeric 读取 |

实际资格来自结构化时间约束、与其一致的捕获过滤条件、授权时间域声明和 Policy。表名、当前系统时间和相同输出 alias 都不能补足期间资格。

Metric、Period 和 Policy 组合审计共 37 个实际公共链路案例：7 个正常计算、30 个业务拒绝；另有 2 个不受支持证据等级的结构拒绝，合计 **39 项均符合预期**。30 个业务拒绝的 Numeric 调用数均为 0。

## 4. Formula Report

**通过。** [公式实现](D:/agent_study/askdata_studio/backend/app/querying/business_signals/sales_change.py:44)使用 Numeric Reader 返回的 Decimal：

```text
absolute_change = current_sales - baseline_sales
change_rate = (current_sales - baseline_sales) / baseline_sales
```

差额保持精确，不强制量化两位；比率使用未量化差额，最后按 Policy 的 12 位小数、ROUND_HALF_EVEN 量化。没有 float 公式计算。独立 Decimal Context 固定精度 80，并隔离调用方的指数范围、flags 和 traps。

| current | baseline | 差额 | 变化率 |
| ---: | ---: | ---: | ---: |
| 150.00 | 100.00 | 50.00 | 0.500000000000 |
| 100.00 | 200.00 | -100.00 | -0.500000000000 |
| 0.00 | 100.00 | -100.00 | -1.000000000000 |
| 200.0001 | 200.0000 | 0.0001 | 0.000000500000 |

下降产生负差额和负变化率合法；输入负销售额仍按 NumericRules 拒绝。本轮重新执行 45 组独立 Fraction 整数舍入 oracle，覆盖增长、下降、Decimal/HUGEINT 极值、18 位尺度、正负中点及近中点，全部一致。

## 5. Zero Baseline Report

**通过。** 在两个 NumericReadResult 都 ready 后，才判断 baseline 是否为零。不会执行除零。

| 输入 | absolute_change | change_rate | 顶层状态 |
| --- | --- | --- | --- |
| current=300.00，baseline=0.00 | computed / 300.00 | undefined / null / ZERO_BASELINE | undefined |
| current=0.00，baseline=0.00 | computed / 0.00 | undefined / null / ZERO_BASELINE | undefined |
| baseline 为负零 | 正常计算差额 | undefined | undefined |
| current=NULL，baseline=0 | 不计算 | 不计算；不改判为零基期公式成功 | insufficient_evidence |

9 组零、负零、0/0 和巨大零指数探针符合预期。没有 Infinity、NaN 或用默认 0 伪造变化率。两项 ComputationResult 独立保留状态，消费者仍需检查顶层和各输出状态。

## 6. Alignment Report

**通过。** [Alignment](D:/agent_study/askdata_studio/backend/app/querying/business_signals/alignment.py:231)按规范业务键建索引；[配对](D:/agent_study/askdata_studio/backend/app/querying/business_signals/alignment.py:282)依据 key，不依据 row position。

8 地区实际 Builder 链路中，华北 current 第 0 行匹配 baseline 第 2 行；华南 current 第 1 行匹配 baseline 第 7 行，均得到正确结果。行号为从 0 开始的索引。

左右 missing、duplicate、NULL key 和 normalization collision 均经过独立反例检查。不补 0，不取重复行的第一条，不通过 inner join 隐藏缺失键。全局 Alignment 失败会阻止所有配对进入 Numeric 和公式阶段。

Alignment 与当前 Compatibility receipt 的完整绑定在 [S2 入口](D:/agent_study/askdata_studio/backend/app/querying/business_signals/sales_change.py:194)验证；旧回执来源、缺失/未知版本绑定、篡改行位置或提升状态均无法继续计算。

## 7. Numeric Report

**通过。** [S2 数值入口](D:/agent_study/askdata_studio/backend/app/querying/business_signals/sales_change.py:219)只调用 Numeric Reader，参数是明确的 metric_column_id 和已绑定的 AlignmentPair 行号。没有直接从 rows 读取公式操作数。

本轮独立 Numeric 审计重新执行 77 次公共链路，包含上述 45 组公式、9 组零值，以及 6 组 approximate/混合输入、3 组 exact Policy 下的 DOUBLE 拒绝、11 组 NULL/负值/非法文本/范围/codec 拒绝、3 组极端全局 Decimal 配置。

148 次 Reader 调用、62 次实际公式调用逐一核对：公式参数确为对应 Reader 返回的 ready 对象，工作值为 Decimal。DOUBLE 经显式 reporting_approx_v1 许可后，两个输出的 source_fidelity 都保持 approximate；混合 Decimal/DOUBLE 也不升级为 exact。Decimal 来源保持 exact，公式舍入质量单独记录。

NULL 保留 sql_null 及实际观察位置；Numeric 拒绝阻止所属配对的两个公式。所有 NumericReadResult 和调用方 Decimal 状态保持不变。

## 8. Evidence Report

**通过。** 8 个实际 Builder 链路 Signal 的 16 个操作数全部核查，并使用审计器的固定局部种子 335 随机抽取 4 个 Signal 展示。抽样发生在计算完成后；随机行为不在生产计算路径中。

以下 current 的 result_id 均为 audit335-current，baseline 均为 audit335-baseline；两个执行中的列 ID 均为 col_m、ordinal=1。列 ID 由 result_id 限定所属执行。

| 地区 | current row_index / value | baseline row_index / value | absolute_change | change_rate |
| --- | --- | --- | --- | --- |
| 华中 | 3 / 200.0001 | 4 / 200.0000 | 0.0001 | 0.000000500000 |
| 东北 | 6 / 300.00 | 0 / 0.00 | 300.00 | null，undefined |
| 华北 | 0 / 150.00 | 2 / 100.00 | 50.00 | 0.500000000000 |
| 华南 | 1 / 100.00 | 7 / 200.00 | -100.00 | -0.500000000000 |

每个操作数均核查 result_id、column_id、row_index、真实值、exact/decimal_text 质量、context_digest、contract/context version、source_fields、SUM、schema metadata、grain、原始/规范期间、filters、授权声明及单位。每份 Evidence 都含 absolute_change / 1 和 change_rate / 1 两个公式引用，两个输出都引用 current:metric、baseline:metric。

BusinessSignal 保存 monthly_sales_change_v1、policy_version=1 及与当前 receipt 一致的实际 policy_digest。没有发现结果存在但对应输入 Evidence 缺失。JSON roundtrip 后事实和状态保持一致。

[共享 Evidence Builder](D:/agent_study/askdata_studio/backend/app/querying/business_signals/evidence.py:25)不包含 computed_value，不计算公式或重读 rows。missing 侧不编造行号、业务键或数值；门禁失败时未读取的已知侧为 not_read；NULL 和 rejected 与零严格区分。

## 9. Failure Safety Report

**通过。** 下列失败均阻止不合格配对产生 computed：

| 失败 | 观察到的保护 |
| --- | --- |
| Compatibility 未通过 | 保留非 compatible 状态，无 Numeric/公式 |
| Policy、selection、declaration、Context/rows 或回执语义变化 | receipt mismatch，无 Numeric/公式 |
| 当前 receipt 配旧 Alignment，或 Alignment 内容变化 | Alignment mismatch，无 Numeric/公式 |
| Missing、duplicate、NULL key、normalization collision | 全局失败，无 Numeric/公式 |
| NULL sales、Numeric reject | 该配对两项输出均无 computed，保留原因和输入事实 |

独立 Alignment/Failure/Determinism 审计共 **48 项通过**：34 个全局拒绝均 Numeric=0、公式=0；7 个单配对 Numeric 拒绝均读取两次、公式=0；其余覆盖正常/重构/重放、零基期及混合配对。

故障范围已区分：全局 Alignment 失败阻止全部计算；若 Alignment 已通过，仅某地区 Numeric 为 NULL，则该地区不能 computed，其他已合法对齐且数值有效的地区仍可计算。baseline=0 则遵循明确的独立输出规则，不属于把失败输入补零的情况。

## 10. Determinism Report

**通过。** 同输入 A→A、A→B→A、相同内容重新构造均得到完全一致结果。实际 Builder 链路中将 current 华北从 150.00 改为 151.00，重新构造声明、Compatibility 和 Alignment 后得到 B，再计算 A，结果与首次 A 完全相同。

生产 S2、Policy factory 和 Evidence Builder 未发现 random、uuid、clock 调用。signal_id 保持当前策略：None，并附 SIGNAL_IDENTITY_NOT_FROZEN 信息；没有生成临时身份。

同时检查了纯函数边界：ResultContract、SCHEMA、BusinessContext、SignalInput、Policy、Compatibility、Alignment、实际 NumericReadResult 及全局 Decimal 状态均未被计算修改。改变返回 Signal 的 Evidence/source_fields 或 business_key 容器不影响输入或后续结果。

## 11. Boundary Report

**通过。** S2 只输出 regional_sales_change 的 absolute_change 和 change_rate。模型与实现没有新增 Alert、Risk、Recommendation、LLM 解释或 Agent 规划，没有 SQL 生成/执行、Workflow、Engine 或批次编排。

源码及调用探针确认计算阶段不重新检查 Compatibility、重新 Alignment 或读取数据源。完整输入序列化与摘要会携带 rows 以防止错误复用，这不是直接读取数值执行公式。

当前边界保持明确：仅支持固定授权的 paid_amount/SUM、region、相邻完整自然月、同单位/scale 和所需声明。声明真实性仍由上游负责；receipt 摘要防止错误复用，不是签名或外部真实性认证。NumericReadResult 的来源由 S2 自己按验证后的配对调用 Reader 并直接传递，本轮已验证该闭环。

本轮没有实现 S3、SignalBatch、Engine、Workflow。Approve 允许后续进入 S3 开发，不会在本轮启动实现。

## 12. Regression

本轮在 backend 目录重新运行：

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_sales_change.py -q
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_target_attainment.py -q
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_signal_evidence.py -q
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_business_signal_*.py' -q
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
```

| 回归组 | 结果 |
| --- | ---: |
| S2 | 73/73 |
| S1 | 66/66 |
| Evidence | 47/47 |
| 其他 Business Signal：Alignment、Compatibility、Numeric、Models、Policies | 352/352 |
| Business Signal 合计 | **538/538** |
| backend 全量 | **988/988** |

backend 全量耗时 23.260 秒，0 failure、0 error、0 skipped。额外只读探针没有写入测试文件，不改变 988 项基线。

与本轮开始快照相比，132 个既有文件 SHA-256 全部一致。源码、测试及既有报告均未修改；仓库仅新增本 Markdown 报告。既有 Phase 3 文件保持原来的 untracked 状态，本轮未 stage/commit；git diff --check 通过。

详细抽样及期间探针记录保存在仓库外的 [E2E Evidence 审计记录](<C:/Users/Wang Hongbo/.codex/visualizations/2026/09/07/01a07c06-45b4-7451-854d-0a060836bcda/phase335/e2e-evidence-audit.json>)、[Metric/Period 审计记录](<C:/Users/Wang Hongbo/.codex/visualizations/2026/09/07/01a07c06-45b4-7451-854d-0a060836bcda/phase335/s2_metric_period_policy_audit.json>)及[回归记录](<C:/Users/Wang Hongbo/.codex/visualizations/2026/09/07/01a07c06-45b4-7451-854d-0a060836bcda/phase335/regression-results.json>)。

## 13. Final Decision

| Approve 条件 | 判断 |
| --- | --- |
| Metric 正确 | 通过 |
| Period 比较正确 | 通过 |
| Baseline 处理正确 | 通过 |
| Alignment 正确 | 通过 |
| Numeric 安全 | 通过 |
| Evidence 完整 | 通过 |
| Failure 安全 | 通过 |
| 无业务越权 | 通过 |
| 全部测试通过 | 通过：988/988 |

**A. Approve S3**

未发现新的 P0/P1 或进入 S3 前必须修复的阻断项。本轮代码零修改，S3 未实现。
