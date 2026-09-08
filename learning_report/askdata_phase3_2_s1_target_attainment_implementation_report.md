# Phase 3.2 S1 Target Attainment Implementation Report

日期：2026-09-08

**结果：S1 Monthly Regional Target Attainment 已实现。新增 66 项测试全部通过，backend 全量 868/868 通过；本轮实现审阅未发现剩余 P0/P1。**

## 1. 修改文件

| 文件 | 本轮变化 |
| --- | --- |
| `backend/app/querying/business_signals/target_attainment.py` | 新增 S1 纯计算入口、前置门禁、Decimal 公式及 BusinessSignal/Evidence 构造 |
| `backend/app/querying/business_signals/alignment_binding.py` | 新增 Alignment producer 来源绑定及纯内容匹配函数 |
| `backend/app/querying/business_signals/alignment.py` | 仅新增绑定 helper 导入，并在既有 producer 返回处附加绑定 |
| `backend/app/querying/business_signals/models.py` | 增加 AlignmentReceiptBinding；扩展未读取/拒绝观察、单位证据和未生成 Signal 身份的表达 |
| `backend/tests/test_target_attainment.py` | 新增 66 项 S1 回归 |
| `backend/tests/test_business_signal_models.py` | 同步 Evidence 原样记录不支持的上游版本这一输出契约断言；保留严格类型和空值拒绝检查 |
| `learning_report/askdata_phase3_2_s1_target_attainment_implementation_report.md` | 本报告 |

原 AlignmentResult 没有来源字段，无法同时满足“验证属于当前 Compatibility receipt”和“不重跑 Alignment”。用户已明确批准：**“允许最小来源绑定扩展”**。本轮按此例外仅修改 producer 输出；键提取、missing、duplicate、广播逻辑没有改变。

与本轮开始保存的 110 个已有源文件/测试/报告摘要比较，只有表中 `alignment.py`、`models.py` 和 `test_business_signal_models.py` 三个已有文件发生改变。Compatibility、Compatibility receipt binding、Policies、Numeric Reader、BusinessContext、ResultContract、其他 Phase 2 文件保持原样。

## 2. 输入契约

```python
compute_target_attainment(
    actual: SignalInput,
    target: SignalInput,
    compatibility: ContextCompatibility,
    alignment: AlignmentResult,
    policy: TargetAttainmentPolicy,
) -> list[BusinessSignal]
```

返回逐业务键的 BusinessSignal 列表；无法安全使用行配对时返回一个 context scope 的拒绝 Signal。这只是函数返回容器，没有引入 SignalBatch。

参数必须是指定模型。入口重新验证模型结构并复制输入快照；结构错误抛出 TypeError/ValueError。结构合法但来源不符、资格不通过或数值不可计算，返回带原因的非 computed Signal。

Compatibility 必须绑定当前 Policy 实际内容、两个完整 SignalInput、列选择和声明。Alignment 还必须同时绑定当前完整 Compatibility receipt 和自身完整输出内容。

## 3. 计算流程

1. 比较 Compatibility 的完整输入绑定。
2. 要求 Compatibility 为 `compatible`，operation 为 `divide`，角色顺序为 actual、target。
3. 比较 Alignment 来源绑定，拒绝旧结果、缺失绑定、未知绑定版本和输出内容变化。
4. 从 receipt 的 `declarations_used` 精确解析已接受的单位声明。
5. 要求整体 Alignment 为 `aligned`，输出为 matched、非广播配对。
6. 按每个 pair 的左右 row_index 和各自 selection.metric_column_id 调用 Numeric Reader。
7. 双方读取均 `ready` 后，检查零目标，再执行 Decimal 除法，构造 BusinessSignal。

计算入口不调用 Compatibility 或 Alignment，也不解析 SQL、不执行 SQL。前置门禁失败时不调用 Numeric Reader；不根据 output_name 或展示别名查找数值。

Alignment 绑定使用版本化 canonical JSON：对象键排序、数组保留顺序、保留标量类型、固定分隔符、ASCII 转义、拒绝非有限数字，以 UTF-8 SHA256 生成摘要。完整 receipt 包含其原有 binding；Alignment 内容只排除自身 binding，避免递归。

摘要域分别为 `alignment-compatibility-v1` 和 `alignment-result-v1`。这用于发现旧结果错误复用，不是安全签名、PKI 或调用者认证。计算入口只验证绑定，不重新签发绑定。

## 4. Decimal 策略

- 使用 Policy 已冻结的 `decimal_precision=80`、`ratio_scale=12`、`ROUND_HALF_EVEN`。
- 使用显式新建 Context 的 localcontext，隔离调用方的精度、指数范围、traps 和 flags。
- 输入保持 Numeric Reader 给出的 Decimal 工作值，不按货币显示位数预先量化。
- 仅最终比率量化至 12 位小数；`100 / 200` 输出文本 `0.500000000000`，单位为 `ratio`。
- 使用 Inexact 标记实际数值舍入；不将仅补充/去除末尾零视作信息损失。
- 任一输入为获 Policy 许可的 DOUBLE/FLOAT，输出保留 approximate 来源质量；不会宣称恢复了原始精度。

覆盖 1/3、half-even 边界、1e-18 非零目标、38 位最大输入以及调用方设置低精度和舍入 traps 的情形。未调用 float()，没有二进制浮点除法，也不修改全局 Decimal context。

## 5. Zero denominator 策略

双方数值均 ready 后，若目标 Decimal 等于零，输出：

```text
status = undefined
computed_value.attainment_rate.value = None
reason_code = ZERO_DENOMINATOR
```

正零、负零和 0/0 均适用；不执行除零。若另一侧为 NULL、非法数值或负数，则先返回其不足/拒绝状态，不借零目标绕过 Numeric 门禁。

## 6. Missing 处理

整体 Alignment 未 aligned 时，全部配对均不读取数值、不执行公式，包括其中已经 matched 的配对。

| 情形 | 输出行为 |
| --- | --- |
| missing_left / missing_right | 缺失侧 presence=missing、row_index=None；另一侧 not_read；保留 Alignment issues |
| ambiguous / duplicate | 不选择重复桶中的任意一行；保留冲突 issues |
| unresolved | 不生成比率，保留不足/拒绝原因 |
| receipt / Alignment binding 不匹配 | context scope 拒绝，不引用旧 pairs 的业务键或行索引 |
| Numeric SQL NULL | presence=sql_null，保留真实行索引，数值为空 |
| 已读取但 Numeric 拒绝 | presence=rejected，保留原始单元格和拒绝原因 |

`not_read` 明确表示门禁阻止了读取，不冒充 missing 或 unknown_metadata。不存在 None、missing、unknown 到零的转换。Numeric 失败状态优先级沿用设计：unsupported > incompatible_context > insufficient_evidence；数学 undefined/computed 只在资格通过后确定。

## 7. BusinessSignal 输出

每个 Signal 包含固定 signal_type、scope/status、BusinessKey、Policy 实际内容摘要、calculator_version、current_value、reference_value、computed_value、evidence 和 limitations。

公式通过已有强类型字段表达：

```text
computed_value.attainment_rate.formula_id = attainment_rate
computed_value.attainment_rate.formula_version = 1
computed_value.attainment_rate.input_evidence_ids = [actual:metric, target:metric]
```

本轮未冻结全局 Signal identity 算法。Phase 3.0 给出的内容摘要组成是推荐，Phase 3.1A 也明确未冻结规范化身份算法。因此 `signal_id=None`，并输出 info Issue `SIGNAL_IDENTITY_NOT_FROZEN`；不随机生成，也不挪用 result_id。

观察模型新增 `not_read` 和 `rejected`，两者均不得携带数值文本。所有返回值通过 BusinessSignal 模型构造，并与输入容器隔离。

## 8. Evidence 设计

每个 Signal 保留 actual、target 两份 operand evidence：

- 原 result_id、Context/ResultContract 版本、Context digest。
- 显式 metric column_id、ordinal、Alignment row_index、各侧原始业务键和列选择。
- 原 raw_value、ObservedValue、dtype、encoding、representation_status 和 NumericQuality。
- metric/relationship ref、源字段、Schema metadata、aggregation、grain、原时间条件和规范期间、原 filters 和规范 filters。
- completeness、truncated、返回/总行数、understanding_status、已使用声明引用、producer provenance 及上游限制。
- 完整 `unit_declaration`，保留实际 unit_id、unit_scale、声明身份、内容和 scope。

单位仅从 Compatibility 已消费的声明中读取，不默认 CNY，不做单位转换。Compatibility 允许的重复同内容声明在解析时按完整内容去重，不会被误判为缺少单位。

Evidence 的 result_contract_version 可以原样记录非空上游版本，例如 `2`；真实 Compatibility 仍将其判为 unsupported，S1 不计算。这避免输出拒绝证据时丢失实际版本或发生模型异常。

`actual:metric` 与 `target:metric` 是单个 Signal 内的稳定操作数引用，不是全局 Signal 身份。row_index 是捕获结果的行位置，不是源数据主键。

## 9. 测试结果

`test_target_attainment.py` 新增 **66 项**，全部通过。附件要求的 12 类全部覆盖：

| 要求 | 结果 |
| --- | --- |
| 100 / 200 = 0.5 | 通过 |
| 多 region | 通过 |
| 行顺序不同 | 通过 |
| target=0 | 通过，包括负零和 0/0 |
| missing target | 通过，无零填充 |
| duplicate key | 通过，无任意行选择 |
| Numeric NULL | 通过，保留行位置 |
| DOUBLE approximate | 通过，要求显式 Policy 许可 |
| Decimal precision | 通过，包含极值、half-even 和全局 Context 隔离 |
| Alignment 未通过 | 通过，Numeric Reader 未调用 |
| Compatibility receipt 不匹配 | 通过，Numeric Reader 未调用 |
| 输入不修改 | 通过，含输出修改隔离与 A/B/A 调用 |

额外覆盖 Policy/selection/declaration/Context/period 变化、旧 Alignment 配新 receipt、pair/status 变化、缺失/未知 binding、同内容重构、单位声明和未知上游版本、禁止重跑上游阶段、JSON 往返等。

| 测试组 | 通过数 |
| --- | ---: |
| S1 Target Attainment | 66 |
| Alignment | 108 |
| Compatibility | 120 |
| Numeric | 67 |
| Models | 33 |
| Policies | 24 |
| Business Signal 合计（含 S1） | **418** |

独立审阅发现的重复同内容单位声明错误拒绝已修复并加入回归。本轮最终审阅未发现剩余 P0/P1。

## 10. Backend 回归

在 `backend` 目录使用现有 `.venv\Scripts\python.exe` 执行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_target_attainment.py -q
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_business_signal_*.py' -q
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

最终结果：S1 **66/66**，既有 Business Signal **352/352**，backend 全量 **868/868**，无失败或跳过；最终 backend 完整运行耗时 21.875 秒。基线 802 项，加本轮新增 66 项。零目标测试同时验证 100/0 与 0/0 均不进入除法函数。

现有 Models 测试的一处版本断言随输出契约扩展同步更新，仍保持 33 项；其余既有测试文件内容未改变。`git diff --check` 通过。Phase 3 文件在本轮开始时已处于未跟踪状态；本轮新增和修复文件仍在工作区待提交，未执行 stage 或 commit。

## 11. 未实现能力与剩余边界

本阶段未实现：**S2 Sales Change、S3 Product Contribution、SignalBatch、Engine、Workflow**。没有加入 LLM、SQL 执行或应用 Agent 集成。

Signal identity 生成仍待独立冻结；当前结果显式保留空 signal_id。旧的无来源绑定 AlignmentResult 可以被模型读取，但不能授权 S1；调用方需提供新 producer 生成的结果，S1 本身不会重跑上游阶段。内容摘要只针对错误复用，不能证明调用方真实性或防止主动重算摘要。

S1 仅接受已经获批的单位和 Numeric Policy，不自动转换货币、不猜缺失事实、不将比率钳制到 0–1，也不输出业务好坏判断。
