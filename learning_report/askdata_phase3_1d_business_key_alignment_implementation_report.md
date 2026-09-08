# Phase 3.1D Business Key Alignment Implementation Report

日期：2026-09-08。Phase 3.1D 已完成：对已通过 Compatibility 的显式角色输入，确定性提取业务键、建立索引并生成 outer alignment。Alignment 专项 **73/73**、backend 全量 **767/767** 通过，原有 **694** 项无回归。

本阶段只产生键与行号的对应关系。`aligned` 不表示已计算 BusinessSignal。

## 1. 修改文件

| 文件 | 本轮变更 |
| --- | --- |
| [alignment.py](D:/agent_study/askdata_studio/backend/app/querying/business_signals/alignment.py) | 新增 `align_context_keys`、回执门禁、安全键提取、索引、outer pairs、重复 / 碰撞和广播处理 |
| [models.py](D:/agent_study/askdata_studio/backend/app/querying/business_signals/models.py) | 仅新增 `AlignmentPair`、`DuplicateKey`、`AlignmentResult` 三个输出合同及其结构校验 |
| [test_business_signal_alignment.py](D:/agent_study/askdata_studio/backend/tests/test_business_signal_alignment.py) | 新增 73 项测试，复用现有 Compatibility fixture |
| [本报告](D:/agent_study/askdata_studio/learning_report/askdata_phase3_1d_business_key_alignment_implementation_report.md) | 新增实施及验证记录 |

未修改 Compatibility、Numeric Reader、Policy、Phase 1、Phase 2、前端或旧测试。对工作开始前保存的 104 个文件进行 SHA-256 比较，只有获准最小扩展的 `models.py` 变化，其余 103 个保持一致；源码新增仅 Alignment 与对应测试。

当前 HEAD：`77c1aba97c2a99571a290bd018f6dcfcd5c35d3c`。原有 Phase 3 文件仍保留在未跟踪工作区，本轮未暂存、未提交。

## 2. Alignment API

```python
from app.querying.business_signals.alignment import align_context_keys

align_context_keys(
    inputs: dict[ContextRole, SignalInput],
    compatibility: ContextCompatibility,
    policy: TargetAttainmentPolicy | SalesChangePolicy | ProductContributionPolicy,
) -> AlignmentResult
```

输入角色必须与具体 Typed Policy 的固定角色对一致，不能传 Context 列表让函数猜角色。返回的 `operation` 保留 Compatibility 回执中的 `align` / `compare` / `divide`，不据此执行公式。

非 `compatible` 回执直接阻止键提取，保留上游 Issue 并添加 `COMPATIBILITY_NOT_APPROVED`。通过门禁时核对现有回执可提供的绑定：

- 固定角色顺序、result IDs 和完整 Context 内容 digest。
- 有序 key domains。
- metric refs 的 role / metric_id / mapping_id / matched 身份摘要。
- 回执引用的声明 ID / type / result ID / digest 是否仍存在。

这些是回执绑定核对，不重新判断 metric source、aggregation、time 或 filter。Alignment 只复用 `context_digest`，不会调用 `check_context_compatibility`。

**调用前提：必须传入 Compatibility 检查当时的同一份 Policy、selection 和 declarations 快照。** 现有回执没有完整的 Policy / selection / declaration 内容摘要；本阶段又禁止修改 Compatibility，因此这里不能识别所有同 ID 下的 Policy 改动、selection 改绑或声明内容替换，也不能认证人为构造的回执。不能将当前检查描述为完整的回执真实性或快照一致性证明。

缺 Context digest 为证据不足；已知 Context 内容或现有引用不符为不兼容，均不进入键提取。非法 API 类型、缺失角色、歧义 column ID / ordinal 或行宽结构错误抛出 `TypeError` / `ValueError`。

## 3. BusinessKey 生成

复用已有 `BusinessKey`、`BusinessKeyComponent`，组件顺序严格沿用 `Policy.key_rules`，不依赖 selection 字典插入顺序。

每个组件保留 domain_id、component_id、value_type、原始 cell 的 raw_value 以及 Policy 决定的 normalized_value。现有合同要求 normalized_value 必填；identity 模式直接复制原值，不实施任何字符串变换。

BusinessKey.periods 深拷贝自已通过的 Compatibility periods。跨期对齐按业务键组件匹配，不把双方不同月份当成不同地区；这里不重新解释时间。

若左右原始值经显式映射后相等，pair 的 left_key 和 right_key 分别保留两侧原始值。例如 `华北地区 → north` 与 `华北 → north` 匹配后，两个 raw_value 仍可分别审阅。

## 4. Key extraction

唯一取值路径为：`SignalSelection.key_column_ids[component_id] → ColumnMetadata.id → ordinal → execution.rows[row_index][ordinal]`。

不使用 output_name、label、alias 或猜测的 ordinal。选定 ID 不存在时拒绝，不回退到同名列；重复 display name 不影响定位。验证 column IDs 唯一、ordinals 对应零起始位置以及行宽一致，然后只读取 key cell。

| Key 类型 | 安全读取规则 |
| --- | --- |
| string | native_json、preserved、VARCHAR，且 cell 满足 `type(value) is str`；保留空串、空格和大小写 |
| integer | native_json、preserved、受支持整数 dtype，且 `type(value) is int`；拒绝 bool、float 和数字字符串，并校验有符号 / 无符号位宽范围 |
| NULL | `NULL_KEY`，insufficient_evidence；不转换成字符串或默认 key |
| 未知 metadata | insufficient_evidence，不猜测类型 |
| lossy / 已知类型冲突 | incompatible_context |
| 不支持的 codec / representation / dtype | unsupported |

不调用 Numeric Reader，不解码、比较或计算 metric cell。Context 内容 digest 会序列化整个捕获 Context，包括 metric 原始值；这是绑定校验，不是 metric 读取或业务计算。

## 5. Normalization 策略

仅支持现有 KeyRule 明确规定的 `identity` 与 `explicit_mapping`。

identity 保持原值：`华北地区` 不自动等于 `华北`，`A` 不自动等于 `a`，` 华北 ` 不自动等于 `华北`。没有 trim、lower、casefold、地区推断或模糊匹配。

explicit_mapping 使用明确 mapping_id、mapping_version 和类型保持的 value_mappings，按精确 raw 值查表。未命中时返回 `KEY_MAPPING_UNKNOWN` / insufficient_evidence；由于现有 Policy 未定义回退授权，不自动采用 identity fallback。

任何数值到字符串的隐式转换均被禁止。内部 token 包含 domain、component、value_type 和 normalized value，避免 Python 中 bool 与 int 等值带来的错误匹配。

## 6. Index 策略

每个角色独立建立 `typed composite key → 所有原始 row indexes / BusinessKeys` 的索引；不同角色相同业务键表示候选对应，不表示同一个捕获结果。

按完整 typed token 排序输出 union key domain，不依赖原始行出现顺序。原始 row_index 始终指向该输入的真实位置，行顺序变化后行号应相应变化；不能宣称行重排前后整个结果字节相同。

bucket 的代表 key 使用固定规则选择一个实际观察到的 raw key 来标识 bucket，不据此选择重复行进行计算。每个重复 bucket 的完整 raw_keys 和 row_indexes 单独保留。

## 7. Missing key 处理

采用 outer alignment，保留双方已知键的并集，不做静默 inner join：

| 左侧已知键 | 右侧已知键 | Pair 状态 |
| --- | --- | --- |
| 华北 | 华北 | matched |
| 华东 | 无 | missing_right |
| 无 | 华南 | missing_left |

missing 项分别进入 missing_left_keys / missing_right_keys，未匹配侧 row_index 为 None；整体状态按 MissingRules 上升为 insufficient_evidence。没有补零，也没有产生默认 metric 值。

只有对侧的键提取完整，才能证明键在该侧的观测索引中缺失。若对侧 rows=None，或包含 NULL、未映射或不可读取的 key，对应未匹配项为 `unresolved`，不进入确定 missing lists。其他能够证明的唯一匹配仍可保留。

正常路径中，空 rows / rows=None 会先被真实 Compatibility 回执门禁阻止。额外防御测试也验证：人为构造 approved 回执时，已知空 grouped rows 给出明确证据不足并保留可证明的 outer 信息；未知 rows 不被当成已知空集合。

## 8. Duplicate 处理

同一 Context 的某个完整业务键对应多行时，生成 `DUPLICATE_KEY`，默认 incompatible_context；保留全部 row_indexes 与逐行 raw_keys，不覆盖、不取第一条、不求和。

若多个不同完整 raw keys 归一化到同一 key，额外生成 `NORMALIZATION_COLLISION`，并设置 duplicate.normalization_collision=True。仅仅在不同角色间将不同 raw 值映射到相同 normalized 值，不属于同侧碰撞。

涉及重复 bucket 的 pair 为 `ambiguous`；重复侧 row_index 和 side key 均为 None。对侧若恰有唯一行，可保留其行号；两侧重复时两侧均不选择。即使另一侧已知为空，也不会把重复 bucket 伪装成一个可计算的 missing pair。

状态优先级固定为 `unsupported > incompatible_context > insufficient_evidence > aligned`。收集可安全确认的多项问题，Issue 使用稳定 code、alignment stage、role、result_id、key 和 evidence_paths，按固定角色、code、key、path 排序。

## 9. Broadcast 策略

广播只处理获准的 global total 行结构，需同时满足：

- 右侧是 total role，Policy 明确 `global_aggregate` + `allow_global_total`，左侧为 grouped。
- 实际 total grain 已知为 global_aggregate，grouping_columns 为空。
- total 没有选择业务键；全部 KeyRule 的 source roles 恰好属于左侧 grouped role。
- total rows 已知且恰好一行。

通过后，每个已知 parts key 可以引用 total 的原始 row_index 0，pair.broadcast=True；right_key 保持 None，不构造假的空 BusinessKey，不读取 total metric 值。

`broadcastable=True` 表示 total 的结构已获授权和验证，不表示整个 AlignmentResult 必然 aligned；parts 仍可能存在重复、NULL 或未映射 key。parts 重复时，广播 pair 保留唯一 total 行号，但不会选择某一条重复 parts 行。

禁止广播、错误 grain、带 key 的 total 或已知非单行 total 不兼容；未知 total 行或必要 grain 证据不足。没有默认让所有 global aggregate 广播。

## 10. AlignmentResult 结构

| 模型 | 字段及含义 |
| --- | --- |
| AlignmentResult | status、operation、left_role、right_role、key_domain、pairs、missing_left_keys、missing_right_keys、duplicate_keys、issues、broadcastable、broadcast_role |
| AlignmentPair | key、left_row_index、right_row_index、left_key、right_key、status、broadcast |
| DuplicateKey | context_role、key、row_indexes、raw_keys、normalization_collision |

key_domain 是保留 Policy 顺序的 domain ID 列表，以支持复合键；每个 BusinessKey 仍保留完整有序组件。Pair 状态为 matched / missing_left / missing_right / ambiguous / unresolved。

AlignmentResult.status 仅允许 aligned / insufficient_evidence / incompatible_context / unsupported；不存在 computed。新增合同校验非负行号、matched / missing 的索引形态，以及 duplicate row_indexes 与 raw_keys 一一对应。输出没有 metric value、change_rate 或其他业务计算字段。

代表性 Issue codes 包括 `COMPATIBILITY_NOT_APPROVED`、`COMPATIBILITY_DIGEST_MISMATCH`、`KEY_VALUE_TYPE_MISMATCH`、`KEY_INTEGER_OUT_OF_RANGE`、`KEY_MAPPING_UNKNOWN`、`NULL_KEY`、`DUPLICATE_KEY`、`NORMALIZATION_COLLISION`、`MISSING_LEFT_KEY`、`MISSING_RIGHT_KEY` 和 `BROADCAST_NOT_AUTHORIZED`。

## 11. Purity

函数对 SignalInput、BusinessContext、rows、Policy、Compatibility 和嵌套声明不做修改；输入与输出使用独立深拷贝快照。相同输入重复调用和 A→B→A 结果一致，角色字典顺序不会改变角色分配，selection 字典顺序不会改变 Policy 组件顺序。

没有 SQL parsing / execution、数据库查询、LLM、网络、系统时间、Schema / CSV / .env 获取，也没有调用 Compatibility 或 Numeric Reader。测试通过禁用 parser、DuckDB connect、网络与已有检查器调用验证边界，并检查模块依赖。

新测试的正常场景使用真实 Compatibility checker 生成回执，但整个 fixture 构造过程不解析或执行 SQL。少量 synthetic approved 回执仅用于防御性边界测试，明确不代表业务语义证明。

只读独立复核额外运行了 100 组键组合，覆盖空 rows、NULL、重复、顺序反转、大小写、空格和空字符串；union、row_index、raw 值保留及未知侧缺失判定均通过。审阅未发现尚未修复的 P0/P1。

## 12. 专项测试

在 `D:\agent_study\askdata_studio\backend` 使用 `.venv\Scripts\python.exe`，严格按附件顺序执行：

| unittest 命令中的测试文件 | 结果 |
| --- | --- |
| `test_business_signal_alignment.py` | **73/73**，0.552s，OK |
| `test_business_signal_numeric.py` | **67/67**，0.017s，OK |
| `test_business_signal_compatibility.py` | **120/120**，0.506s，OK |
| `test_business_signal_models.py` | **33/33**，0.015s，OK |
| `test_business_signal_policies.py` | **24/24**，0.010s，OK |

每项命令格式：`.\.venv\Scripts\python.exe -m unittest discover -s tests -p <测试文件>`。

Alignment 覆盖附件全部 15 项必测场景，并补充复合键、非零 ordinal、严格整数范围与 bool 拒绝、两侧 raw 值、未映射时不回退、未知键的 unresolved、两侧重复、回执内容 / 引用变化、metadata 优先级、广播结构、确定性、输入不变和禁止调用边界。

S1 actual/target、S2 current/baseline 的唯一 key 匹配，以及 S3 parts/global-total 的结构广播，都由真实 Compatibility 回执进入 Alignment 并达到 aligned；未执行任何 Signal 公式。

## 13. backend 回归

上述专项之后执行：`.\.venv\Scripts\python.exe -m unittest discover -s tests`。

结果：**Ran 767 tests in 17.575s — OK**，退出码 0，无失败或错误。

计数：原有 **694** + Alignment 新增 **73** = **767**。原基线全部包含在本次全量回归中。

完整日志：[backend-tests.log](<C:/Users/Wang Hongbo/.codex/visualizations/2026/09/07/01a07c06-45b4-7451-854d-0a060836bcda/phase31d/backend-tests.log>)，存放于仓库外。

## 14. 尚未实现能力

本阶段仍未实现：

- S1 Target Attainment 公式。
- S2 Sales Change 公式。
- S3 Product Contribution 公式。
- SignalEvidence 自动装配。
- BusinessSignal 生成及 Signal ID。
- SignalBatch / Engine。

没有执行 metric 计算，也没有修改 BusinessContext 或 Phase 2。后续流程必须检查 AlignmentResult.status，不能仅凭存在 pairs 或 broadcastable=True 就执行公式。
