# Phase 3.1E Compatibility Receipt Hardening Report

最终结论：**A. Ready for Phase 3.2**。

`P31E-AUD-01` 已修复并完成复审。Compatibility 现在对实际 Policy、完整 SignalInput 和完整回执语义生成确定性绑定；Alignment 在 key extraction 前核对绑定，错误复用旧回执返回 `incompatible_context`，不产生 pairs。backend 全量 **802/802** 通过。

本报告更新此前 Integration Audit 的阻断结论；旧审计报告作为修复前记录保留。本轮没有实现 S1/S2/S3、BusinessSignal、SignalBatch、Engine 或 Workflow。

## 1. Root Cause

修复前的回执只绑定 BusinessContext 内容、部分 metric identity 和 declaration references，没有绑定检查当时的完整 Policy、selection、声明 claim / scope，以及回执所有关键语义。

因此，即使旧 receipt.status=compatible，调用方仍可能换入另一份 Policy、交换 region / channel selection、修改同 ID unit claim，或者修改回执 operation / period，随后错误获得 aligned。该缺口此前依赖“调用方始终传同一快照”的约定，未在 API 边界执行。

修复没有把 metric、time、filter 或 unit 判断复制到 Alignment；它补齐的是“这个资格结果属于哪一份输入”的内容绑定。

## 2. Receipt binding design

[ContextCompatibility](D:/agent_study/askdata_studio/backend/app/querying/business_signals/models.py:372) 新增 `binding: CompatibilityReceiptBinding | None`。生产 Compatibility 完成现有判断后，使用**本次实际检查的深拷贝 inputs 和已验证 Policy**填充 binding；通过和未通过的结果都带绑定。

绑定结构：

| 层 | 字段 / 覆盖内容 |
| --- | --- |
| CompatibilityReceiptBinding | version、policy_id、policy_version、definition_digest、policy_digest、input_bindings、semantics_digest |
| SignalInputBinding，每个明确 role 一份 | result_id、context_digest、selection_digest、declarations、input_digest |
| DeclarationContentBinding，每条声明一份 | declaration_id、declaration_type、result_id、声明所指 context_digest、content_digest |

`policy_digest` 对**完整实际 Policy 内容**计算，包括身份、source 授权、relationship、numeric、time、filter、unit、declaration 信任规则、key mapping 等所有字段。

原 `definition_digest` 保留为 Policy 身份字段，不被误当成程序已核实的内容 hash，也不被覆盖。即使调用方保持 policy_id / version / definition_digest 全部不变，修改实际来源授权或其他规则，也会改变新计算的 policy_digest 并被拒绝。

`input_digest` 对完整 SignalInput 计算，覆盖 Context、全部 selection 字段及全部声明内容；selection_digest 明确包含 metric_column_id、key_column_ids、auxiliary_column_ids。声明 manifest 不只记录已使用的声明，也记录未使用声明及其内容、顺序和数量。

`semantics_digest` 对整个 ContextCompatibility dump 计算，唯一排除的是递归的 binding 本身。它覆盖 operation、status、issues、roles、result_ids、input_digests、完整 metric / relationship refs、periods、non_time_filters、key_domains 和 declarations_used。

Alignment 重算当前输入及当前回执对应的 binding，并与原绑定逐字段比较。没有数据库读取或再次进行业务资格判断。

## 3. Modified files

| 文件 | 修改范围 |
| --- | --- |
| [receipt_binding.py](D:/agent_study/askdata_studio/backend/app/querying/business_signals/receipt_binding.py) | 新增纯内容摘要与绑定 helper：`bind_receipt`、`receipt_binding_matches` |
| [models.py](D:/agent_study/askdata_studio/backend/app/querying/business_signals/models.py:337) | 新增三个 binding 合同，ContextCompatibility 添加可选 binding |
| [compatibility.py](D:/agent_study/askdata_studio/backend/app/querying/business_signals/compatibility.py:821) | 现有检查结束后，对实际输入快照和结果调用 bind_receipt |
| [alignment.py](D:/agent_study/askdata_studio/backend/app/querying/business_signals/alignment.py:83) | 加强 receipt_matches 门禁并更新相关说明；业务对齐逻辑保持不变 |
| [test_business_signal_alignment.py](D:/agent_study/askdata_studio/backend/tests/test_business_signal_alignment.py:743) | 保留原 73 项，新增 35 项；同步旧 synthetic fixture 的绑定及更严格拒绝状态 |
| [本报告](D:/agent_study/askdata_studio/learning_report/askdata_phase3_1e_compatibility_receipt_hardening_report.md) | 新增修复、回归及复审记录 |

未修改 Phase 2 BusinessContext、ResultContract、Numeric Reader、Policy 定义、前端或旧报告。对原 108 个源码 / 测试 / 前端及 Phase 3 报告文件核对，原有文件仅上表中的四个发生变化。

额外保存并比较了 `_Alignment` 的九个非门禁方法语法树：初始化、Issue 添加、structure、key_column、extract、find_duplicates、broadcast、outer_pairs、run 全部一致。键提取、索引、missing、duplicate / collision、广播及输出组装没有业务逻辑修改。

工作区原有 Phase 3 文件此前尚未跟踪；本轮继续保留，未暂存、未提交。

## 4. Alignment gate behavior

门禁发生在 `run()` 进入 structure、extract、broadcast 或 outer_pairs 之前。

| 输入情况 | 行为 |
| --- | --- |
| receipt.status 非 compatible | 保留原拒绝状态，添加 COMPATIBILITY_NOT_APPROVED，不提取 key |
| compatible 但 binding=None | incompatible_context / COMPATIBILITY_BINDING_MISSING |
| 旧回执对应另一份 Policy / SignalInput | incompatible_context / COMPATIBILITY_BINDING_MISMATCH |
| operation 或任何已绑定 normalized semantics 改动 | incompatible_context / COMPATIBILITY_BINDING_MISMATCH |
| 不支持的 binding version 或 binding 内字段被替换 | incompatible_context / COMPATIBILITY_BINDING_MISMATCH |
| 内容相同、对象重新构造或字典插入顺序变化 | 正常通过，进入原 Alignment 业务逻辑 |

所有新增负例都把 structure / extract / broadcast / outer_pairs 替换为一旦执行即抛错的探针，确认绑定拒绝发生在这些阶段之前。结果没有 pairs、missing lists、duplicate lists 或广播。

原有细粒度身份诊断保留。缺失或空白的 receipt.input_digests 现在还会造成完整语义绑定失败，整体状态从原来的 insufficient_evidence 收紧为 incompatible_context；对应两项原测试同步更新，保留原诊断代码断言。

旧版序列化回执仍可加载为 binding=None，但不能再作为进入 Alignment 的依据。需要重新运行 Compatibility 获取新回执；Alignment 不自动给旧结果补绑或重新判断资格。

## 5. Digest design

[receipt_binding.py:25](D:/agent_study/askdata_studio/backend/app/querying/business_signals/receipt_binding.py:25) 使用版本化域前缀、固定 JSON 编码及 SHA-256：

- `sort_keys=True`：对象键顺序稳定。
- `ensure_ascii=True`、固定分隔符 `(',', ':')`、UTF-8 编码。
- `allow_nan=False`：不接受非有限 JSON 数值。
- 保留数组顺序、数量及原始标量类型，不做 trim、casefold 或业务等价归并。
- 对 Pydantic 的 `model_dump(mode="python")` 内容计算，模型默认字段也纳入绑定。

域前缀分别为 context-v1、compat-selection-v1、compat-declaration-v1、compat-input-v1、compat-policy-v1、compat-semantics-v1，后接 `:sha256:` 和十六进制摘要。context 的编码结果与已有 context_digest 一致，不修改旧 Context digest 约定。

独立复审核对了 Policy 全内容 hash 与实现结果一致；并验证字典顺序不影响摘要，而列表顺序、int / float、False / 0、-0.0 / 0.0 保持可区分。

没有 uuid、time、random、SQL、LLM、外部获取或环境相关配置。重复调用、A→B→A 和 JSON 序列化重建均稳定，输入及原 receipt 不被修改。

这些摘要只检测错误复用旧回执，**不是安全签名、PKI 或防恶意篡改机制**。掌握输入并刻意重新计算全部绑定的一方仍可构造一致摘要；bind_receipt 自身不判断业务资格，生产路径只在真实 Compatibility 检查完成后调用它。

## 6. Regression cases

用户要求的十个场景均已覆盖：

| Case | 回归 | 实测 |
| --- | --- | --- |
| 1 | 正常 Compatibility → Alignment | aligned，S1/S2/S3 均通过 |
| 2 | Policy source 修改，旧回执；身份与声明 digest 字符串保持不变 | incompatible_context，提取前拒绝 |
| 3 | metric_column_id 修改 | incompatible_context，提取前拒绝 |
| 4 | key_column_ids 修改 | incompatible_context，提取前拒绝 |
| 5 | 同 declaration ID 下 claim 修改 | incompatible_context，提取前拒绝 |
| 6 | operation compare → divide | incompatible_context，提取前拒绝 |
| 7 | period 修改 | incompatible_context，提取前拒绝 |
| 8 | Policy 或 normalized metric relationship 修改 | incompatible_context，提取前拒绝 |
| 9 | 相同内容重新构造 | aligned；JSON round trip 与字典顺序变化均通过 |
| 10 | inputs / Policy / receipt 不修改 | 深层快照相同，A→A / A→B→A 通过 |

新增 35 项还覆盖 auxiliary selection、Policy identity、声明 attribution / scope / result binding、声明增删 / 重排、operation 改成 align、metric source refs、filters、key domains、declarations_used、拒绝状态被提升为 compatible、legacy receipt、未知 binding version，以及 binding 内子摘要被替换。

旧 synthetic_receipt fixture 现在显式调用内容绑定 helper，仅用于原有低层防御测试；它仍明确不代表生产业务资格证明，没有 mock 门禁来绕过本次修复。

独立复审完成 20 个只读反例探针。此前的 Policy source / trust / numeric 变化、同 ID unit claim、复合键 region / channel selection 互换、operation / period / relationship 修改全部被拒绝。复审未发现新的 P0/P1，确认 P31E-AUD-01 已关闭。

## 7. Existing S1/S2/S3 readiness impact

使用真实已捕获 fixture 和生产 API 重新串联：

| 输入对 | Compatibility | Alignment | 按 pair row_index + selection.metric_column_id 读取 |
| --- | --- | --- | --- |
| S1 actual / target | compatible，binding version 1 | aligned | 双侧 Numeric ready |
| S2 current / baseline | compatible，binding version 1 | aligned | 双侧 Numeric ready |
| S3 parts / total | compatible，binding version 1 | aligned，授权广播保持 | parts / total Numeric ready |

每组还将 SignalInput、Policy 和 receipt 经 JSON 序列化重新构造，并反转角色字典插入顺序：Alignment 输出和重新生成的 Compatibility 回执均与原结果一致。调用前后输入不变。

既有 missing / duplicate / unknown / normalization collision / broadcast 边界由保留的 Alignment 测试继续覆盖，没有为了取得 aligned 而补零、选择重复首行或推断未知值。Numeric Reader 代码未修改。

证据：[readiness-recheck.json](<C:/Users/Wang Hongbo/.codex/visualizations/2026/09/07/01a07c06-45b4-7451-854d-0a060836bcda/phase31e-hardening/readiness-recheck.json>)。本次仅安全读取输入 cell，没有业务公式或 Evidence 自动装配。

## 8. Full tests

在 backend 目录，按用户指定顺序执行 `.\.venv\Scripts\python.exe -B -m unittest discover ...`：

| 顺序 | 测试参数 | 结果 |
| --- | --- | --- |
| 1 | `-s tests -p test_business_signal_alignment.py` | **108/108**，1.059s，OK |
| 2 | `-s tests -p test_business_signal_compatibility.py` | **120/120**，0.572s，OK |
| 3 | `-s tests -p test_business_signal_numeric.py` | **67/67**，0.017s，OK |
| 4 | `-s tests -p test_business_signal_models.py` | **33/33**，0.013s，OK |
| 5 | `-s tests -p test_business_signal_policies.py` | **24/24**，0.012s，OK |
| 6 | `-s tests` | **802/802**，16.700s，OK |

所有进程退出码为 0。计数为原 **767** + 新增 **35** = **802**；没有删除原测试，两项缺失 / 空白 digest 测试按本轮明确要求改为更严格拒绝状态。其余既有行为回归通过。

完整日志：[backend-tests.log](<C:/Users/Wang Hongbo/.codex/visualizations/2026/09/07/01a07c06-45b4-7451-854d-0a060836bcda/phase31e-hardening/backend-tests.log>)，保存在仓库外。

## 9. Remaining limitations

- 绑定用于防错误复用，不验证声明在真实业务世界中的真实性，也不提供签名或恶意重算防护。
- 旧无绑定回执必须重新经过 Compatibility；不在 Alignment 内自动迁移或重新认可。
- 列表顺序和声明数量属于严格快照，改变顺序也需新回执；字典键顺序不属于差异。
- 输入模型或 canonical 编码的后续演进需要版本化处理；本轮只接受 binding version 1。
- 全 Context 内容需要参与摘要计算；这会序列化捕获数据，但不执行 SQL、不解码或计算 metric 业务值。
- 结构性非法 API 输入继续遵循原 TypeError / ValueError 合同；有效形状的绑定不一致返回 incompatible_context。
- S1/S2/S3 公式、BusinessSignal、SignalEvidence 自动装配、SignalBatch、Engine 和 Workflow 仍未实现。

**最终结论：A. Ready for Phase 3.2。** 这是完成 Receipt Hardening 并复审后的准入结论，本轮没有开始实现 S1。
