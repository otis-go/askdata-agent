# Phase 3.1C Context Compatibility Implementation Report

日期：2026-09-08。Phase 3.1C 已实现；S1、S2、S3 的完整合成输入均可达到 `compatible`。专项测试及 backend 全量 **694/694** 通过，原有 **561** 项无回归。`compatible` 表示具备进入下一阶段的 Context 资格，不表示已经完成行对齐或业务计算。

## 1. 修改文件

| 文件 | 本轮变更 |
| --- | --- |
| [compatibility.py](D:/agent_study/askdata_studio/backend/app/querying/business_signals/compatibility.py) | 新增资格检查、跨 Context 检查、声明绑定及确定性输出 |
| [test_business_signal_compatibility.py](D:/agent_study/askdata_studio/backend/tests/test_business_signal_compatibility.py) | 新增 120 项测试，含 S1/S2/S3 显式 fixture |
| [numeric.py](D:/agent_study/askdata_studio/backend/app/querying/business_signals/numeric.py) | 抽取共享 metadata helper，保持 Reader 原有值检查顺序 |
| [test_business_signal_numeric.py](D:/agent_study/askdata_studio/backend/tests/test_business_signal_numeric.py) | 保留原 54 项，新增 13 项 helper 测试 |
| [policies.py](D:/agent_study/askdata_studio/backend/app/querying/business_signals/policies.py) | 新增 `AuthorizedRevisionPair`，向 `SnapshotRules` 添加默认空列表 `authorized_revision_pairs` |
| [本报告](D:/agent_study/askdata_studio/learning_report/askdata_phase3_1c_context_compatibility_implementation_report.md) | 新增实施与验证记录 |

未修改 Phase 1、Phase 2、前端、`business_signals/models.py` 或已有 Phase 3 报告。与工作开始前保存的 101 个文件哈希比较，原有文件仅上述 `numeric.py`、Numeric 测试和 `policies.py` 三个文件变化，其余 98 个未变。

当前 HEAD 为 `77c1aba97c2a99571a290bd018f6dcfcd5c35d3c`。已有 Phase 3.0/3.1A/3.1B 文件原本就在未跟踪工作区中，本轮予以保留；本轮文件同样尚未暂存、未提交。没有执行 `git add` 或 commit。

## 2. 公共 API

```python
check_context_compatibility(
    inputs: dict[ContextRole, SignalInput],
    policy: TargetAttainmentPolicy | SalesChangePolicy | ProductContributionPolicy,
    *,
    operation: Operation,
) -> ContextCompatibility

context_digest(context: BusinessContext) -> str
filter_scope_digest(context: BusinessContext) -> str
```

API 位于 `app.querying.business_signals.compatibility`，返回现有 `ContextCompatibility`。仅接受具体 Typed Policy、明确的角色字典和 `align` / `compare` / `divide`；不从参数顺序、表名或显示名称猜角色。缺角色、多角色、非法 selection、结构冲突均抛出 `TypeError` / `ValueError`。

额外公开的 Numeric API 位于 `app.querying.business_signals.numeric`：

```python
check_numeric_column(
    column: ColumnMetadata,
    numeric_rules: NumericRules,
) -> NumericColumnEligibility
```

## 3. 单 Context eligibility

检查 Context / ResultContract 版本、非空 `result_id`、执行成功、rows / columns 是否已知、执行 counts 自洽、输出完整性，以及整体和必需语义范围的 status / limitations。可安全确认的问题会累计收集。

按现有 ExecutionData 模型验证输入结构；不将结构异常包装成业务状态。显式选择只通过 column ID 定位。列语义 ID 重复、未知 ID、ordinal 与元数据冲突均拒绝。

`success=False`、已知 provenance 冲突、部分或截断结果不兼容。缺必要执行事实、未知语义、无观测行属于证据不足。`execution.sql` 与 `submitted_sql` 仅作捕获事实的一致性比较，不作 SQL 语义等价判断；optional provenance 缺失本身不构成冲突。

## 4. Cross-context compatibility

按 Policy 固定角色顺序验证 metric relationship、key domain、period、non-time filters、unit、population 和 revision。输入字典插入顺序不影响角色与输出顺序。

同一 `result_id` 携带不同 Context 内容会产生 `RESULT_ID_CONFLICT`；同一 declaration ID 携带不同内容会产生 `DECLARATION_ID_CONFLICT`。不同 execution identity 保留各自 ID，不自动合并。

## 5. Metric mapping

使用选定列的真实 lineage、完整 source identity、SchemaBinding 和实际 aggregation，逐项匹配 `Policy.metric_rules`。数据库标识按原值比较，table / field 仅做 ASCII 大小写归一；不根据 alias、标签或 Schema 默认聚合推断业务指标。

指标必须有一个明确且获准的字段来源。要求 SchemaBinding 时，必须有且仅有一个对应来源的 binding。`SUM(order_amount) AS sales_amount` 不会因 alias 与 `paid_amount` 相同而获准；实际 `AVG` 也不会继承 Schema 默认 `SUM`。缺 binding 或未知来源保持证据不足。

## 6. Relationship rules

`compare` / `divide` 必须存在恰好一条对应 operation 的显式 relationship。`compare` 要求 `equivalent` 且两侧 metric ID 相同。S2/S3 要求 equivalent 关系，不能把 baseline / total 改成无关 target metric 后借 `divide` 放行。

S1 要求 `actual_to_target`，允许实际值与目标值采用不同 metric ID；target 的 metric-basis 声明还必须绑定 Policy relationship ID 以及正确的双方 metric ID。

`align` 检查显式 key domain 资格，不要求两个 metric ID 相等，也不执行行对齐。一般 Context 资格要求仍适用。

## 7. Grain checks

已知 query grain 和 grouping source 集合必须与 Policy 一致。`region` 与 `region + category` 不兼容；不自动 roll up 或 regroup。未知 grouping evidence 不通过。

S3 的 total 必须满足 global aggregate、恰好一行及明确的 `allow_global_total` 广播授权。读取行数只用于输出结构资格，不读取该行的业务值。

## 8. Key eligibility

selection 的 key 字典按 Policy `component_id` 绑定 column ID；要求完整且无歧义的组件选择、正确的原始来源、非聚合 grouping 列，以及受支持的 dtype / encoding / representation。

支持明确声明的 string / integer key 类型；已知 VARCHAR 与 integer 规则冲突属于不兼容，未知 metadata 属于证据不足，不支持的 codec / dtype 属于 unsupported。指标列不能同时作为 grouping key。

此处不访问 key 值、不建立索引、不执行值映射、不判断缺哪个地区，也不检测结果行重复。Policy 的行级 normalization / collision / missing-key 规则留给 Alignment。

## 9. Filter compatibility

只消费 FilterInfo 的结构化 resolved 条件与 typed literals；不解析 expression / SQL。V1 支持纯 AND 的明示谓词，按精确相同条件去重并忽略 AND 顺序。

先按 **物理 source identity + typed predicate** 比对每个角色的必需条件，再按 Policy domain 映射用于跨 Context 比较。不同物理来源即使复用同一个 domain，也不能掩盖缺失条件。字符串 `"1"` 与整数 `1` 不等价。

S2/S3 要求非时间签名相等。S1 可通过受信 metric basis 桥接恰好一个 actual-only 的字符串等值状态条件，其他 population 条件仍必须一致；如果 Policy 明确选 `mapped_equal`，则不能借该桥接绕过完整相等要求。S2/S3 的 metric-basis filter 模式返回 `UNSUPPORTED_FILTER_POLICY`。

HAVING 不兼容；OR 或上游 unsupported 按 unsupported 处理。excluded scopes，以及即使未列入 excluded_scopes、却混入 filters 的 JOIN ON / QUALIFY，均不放行。未知 FilterInfo / 单条件不会被当作已知空集合，进而制造假的跨 Context 冲突。

时间谓词仅在已授权 time source 下单独消费，并核对所有结构化时间谓词的交集与 TimeConstraintInfo 一致。不能隐藏额外的时间限制。

## 10. Time compatibility

完全基于捕获的 time_constraints 和显式 TimeRules；不读 current/history 表名，不读时钟。使用纯 Gregorian 字面值校验，包括闰年、跨年和有限年份范围。

| Signal | V1 规则 |
| --- | --- |
| S1 | actual 是完整自然月 date 半开区间，target 是同月 `YYYY-MM` 等值；必须有 `same_calendar_month` 授权 |
| S2 | 两侧完整自然月，baseline 恰为 current 的前一自然月，时间域一致 |
| S3 | 时间域、calendar、precision、lower / upper、开闭完全一致，且原始约束为 WHERE |

target 月字面值经明确月规则转换成规范 date 半开区间，写入现有 NormalizedPeriod；原始 Context 不变。不将 BETWEEN 月底自动解释成 V1 半开整月。

缺时间不等于 all history；部分月、范围冲突、错误开闭或不获准来源均不能通过。time-domain 声明必须证明对应 source、domain、calendar、precision 和受支持的比较域；不执行时区转换。

## 11. Declaration binding / trust

检查 version、type、issuer_kind / issuer_ref、evidence_grade、result_id、context_digest、column IDs、scope 和对应 claim。未知声明版本先返回 unsupported，不因当前 Pydantic 版本字段限制而被错误归类。构造成功不代表受信。

Policy 每个角色的 required_types 作为所接受声明类型集合；issuer、issuer_ref、grade 也必须显式获准。仅自称 `fixture_catalog` 不够。声明必须覆盖选定列，并绑定存在的 source、approved period、filter scope、population scope 和 Policy key domains；claim 不能超出声明 source scope。

S1 target 的 metric basis 与 source uniqueness 均须有已知 target version，且版本相同。源唯一性必须覆盖恰好的 key + time 字段与对应 domain，不能用包含额外字段的更弱唯一性替代。

全空白 digest、单位、scale、issuer reference、basis reference、population reference、dataset / revision reference 或 target version 不算已知证据。有效引用保持原值比较，不执行 trim 后等价合并。无效声明不会进入 `declarations_used`；同域受信声明的 claims / scope 冲突不会取第一条掩盖问题。

`context_digest` 使用版本化 `context-v1:sha256:` 前缀，对 BusinessContext 的 Python-mode dump 做固定 JSON 编码：排序对象键、ASCII 转义、固定分隔符、拒绝 nonfinite JSON；保留数组顺序及 JSON 中 int / float 的表示区别。SQL 作为不透明字符串进入内容绑定。

`filter_scope_digest` 使用 `filter-v1:sha256:`，绑定结构化 WHERE 来源、operator、typed literals、bounds 和 status；精确 AND 去重排序，忽略渲染 expression / value_sql。这两个 helper 可供声明 producer 显式生成绑定引用，Compatibility 不自行签发声明。

这些 digest 是本版本的内容绑定约定，不是 SQL 等价证明、PKI、外部真实性验证或 Signal ID。fixture 的 `demo_v1` 信任完全来自测试 Policy 白名单。

## 12. Unit compatibility

必须有绑定选定 metric source 的受信 unit 声明。只接受已知且相同的 `unit_id` 与 `unit_scale`；已知不同即不兼容，不做单位或汇率转换。display scale 不参与业务单位换算。

测试显式声明 CNY / scale 1；不是从 `paid_amount`、Schema 或列名推断。S1 即使未来输出 ratio，输入单位证明仍不能省略。V1 必需证据门槛保持严格，关闭 Policy 中的可放宽布尔选项不会使缺证据输入获准。

## 13. Numeric column eligibility

`NumericColumnEligibility` 是 frozen dataclass，包含 `status`、可选 `code` / `message`、`source_kind` 和 `decimal_shape`。成功状态为 `ready`，失败使用 Numeric Reader 已有的证据不足 / 不兼容 / unsupported 类别。

helper 只读取 ColumnMetadata 与 NumericRules，核对 dtype、codec、representation、numeric profile 和 decimal shape。与 Reader 共享 metadata / source 和 Policy 核心规则。

exact profile 拒绝 DOUBLE；明确允许 binary float 的 reporting profile 可以通过列级资格。lossy 不兼容，unsupported codec 不支持，未知 dtype / representation 证据不足。原 Reader 的 NULL、nonfinite 和 runtime-type 检查顺序保持，原 54 项测试全部通过。

Compatibility 不调用 `read_numeric_value(row_index=0)`。列级通过不证明每个单元格的值有效；NULL、负值、零分母及具体数值读取仍由后续 Reader / 计算流程处理。

## 14. Completeness / coverage

分别检查 query output 完整性与 business population 证明。V1 要求 complete_query_output、未截断以及已知且自洽的 counts。partial / truncated 不兼容；未知必要字段证据不足。

row-selection 需有受信 `absent` 声明；明确 limit / offset / top_n / other 不兼容。不会扫描 SQL 找 LIMIT。population 必须明确 complete，unknown 证据不足，incomplete 不兼容。

S3 parts 还要证明 Policy key domains 的完整 partition；两侧 population scope 必须一致。不会因返回四个地区就推断覆盖完整。源 target 唯一性来自声明，不来自 GROUP BY 或结果行数量。

## 15. Snapshot / revision

使用 provenance.snapshot_ref 或受信 snapshot_revision 声明；captured_at 相近无证明作用，全空白 snapshot 视为缺证据。已知 snapshot 与声明 revision 不一致会产生冲突；空白 snapshot 不会覆盖有效声明。

受信声明使用 `(dataset_ref, revision_ref)` 身份；仅有 snapshot_ref 时使用 `(execution.database, snapshot_ref)`。same_revision 要求两侧身份完全相同。若一侧走声明、一侧走 snapshot，命名空间也必须按该约定一致，不推断两个不同标识等价。

`authorized_revision_pair` 必须命中 Policy 明确的有序四元组，分别列出左右 dataset / revision。新增的 `authorized_revision_pairs=[]` 保持旧 Policy 构造兼容；空列表不授权任何配对。双方自报相同 comparison_group_ref 不能代替 Policy 授权。不查询数据库确认 revision。

## 16. Status priority

固定优先级：`unsupported > incompatible_context > insufficient_evidence > compatible`。

收集所有可安全确认的 Issue。对于未知 columns / filters / time，不把未知事实当成确定的缺失或冲突；不受支持版本阻止对该版本结构的继续推断。结构性非法输入仍抛出异常。测试同时覆盖多类问题时的优先级。

## 17. Issue codes

Issue 使用稳定 code、`stage="compatibility"`、role / result_id、evidence_paths、severity 和解释消息；断言以状态、code、path 为主，不解析 message。

| 范围 | 代表性 codes |
| --- | --- |
| 版本 / 上游 | `UNSUPPORTED_CONTEXT_VERSION`, `UNKNOWN_UNDERSTANDING`, `UPSTREAM_LIMITATIONS` |
| 执行 / 完整性 | `FAILED_EXECUTION`, `EXECUTION_PROVENANCE_CONFLICT`, `PARTIAL_QUERY_OUTPUT`, `UNKNOWN_COMPLETENESS` |
| 身份 | `RESULT_ID_CONFLICT`, `DECLARATION_ID_CONFLICT` |
| 指标 | `METRIC_SOURCE_MISMATCH`, `METRIC_BINDING_UNKNOWN`, `AGGREGATION_MISMATCH`, `METRIC_RELATIONSHIP_MISMATCH` |
| 粒度 / key | `GRAIN_MISMATCH`, `UNKNOWN_GRAIN`, `KEY_SELECTION_MISMATCH`, `KEY_TYPE_MISMATCH`, `KEY_BROADCAST_NOT_AUTHORIZED` |
| 时间 / 过滤 | `TIME_PERIOD_MISMATCH`, `TIME_FILTER_MISMATCH`, `FILTER_MISMATCH`, `HAVING_NOT_ALLOWED`, `UNSUPPORTED_FILTER_SCOPE`, `UNSUPPORTED_FILTER_POLICY` |
| 声明绑定 | `DECLARATION_RESULT_MISMATCH`, `DECLARATION_DIGEST_MISMATCH`, `DECLARATION_SCOPE_UNKNOWN`, `UNTRUSTED_DECLARATION` |
| 缺少证明 | `DECLARATION_REFERENCE_UNKNOWN`, `DECLARATION_CLAIM_UNKNOWN`, `MISSING_UNIT_DECLARATION`, `ROW_SELECTION_UNKNOWN`, `TARGET_VERSION_UNKNOWN` |
| coverage / revision | `POPULATION_UNKNOWN`, `POPULATION_INCOMPLETE`, `SOURCE_KEY_DUPLICATE`, `REVISION_UNKNOWN`, `REVISION_CONFLICT` |

Numeric metadata 失败保留共享 helper 的 code。Issue 按固定 role 顺序、code、path 和 message 排序并精确去重，重复调用顺序稳定。

## 18. normalized outputs

兼容输出稳定包含 operation、context_roles、result_ids、normalized_metric_refs、key_domains、periods、non_time_filters、declarations_used 和 input_digests。

metric refs 保留映射 ID、匹配状态及已证明的来源；compare / divide 同时附对应 relationship ID。periods 来自捕获的有界时间；filters 来自已验证的结构化条件与显式 domain；declarations_used 只列通过验证的声明引用。

不补造单位、source、period 或新业务事实。输出与输入深拷贝隔离，后续修改输入不会改变已返回结果。

## 19. Purity

Compatibility 无 SQL parser、DuckDbEngine、数据库 client、Agent / Workflow、retrieval、LLM 或时钟模块依赖，不打开 CSV / .env，不读取 Schema 补 Policy。SQL 和 expression 是不透明捕获内容。

测试验证 A→A、A→B→A、深层输入不变、输出隔离、角色字典顺序与 Issue 顺序稳定；同时覆盖 AST 禁止依赖检查及 parser / file / network / clock 访问阻断。所有新 Compatibility fixture 均显式构造 BusinessContext 和声明，没有解析或执行 SQL。

结构验证及内容 digest 可能遍历已捕获行数据进行验证或序列化；这不建立 key index、不选择业务计算行、不做行值相等判断，也不产生 Alignment 结果。

## 20. 专项测试

在 `D:\agent_study\askdata_studio\backend` 使用项目 `.venv\Scripts\python.exe`，按附件顺序执行：

| 命令（`python` 为上述解释器） | 结果 |
| --- | --- |
| `python -m unittest discover -s tests -p test_business_signal_compatibility.py` | **120/120**，0.436s，OK |
| `python -m unittest discover -s tests -p test_business_signal_numeric.py` | **67/67**，0.014s，OK |
| `python -m unittest discover -s tests -p test_business_signal_models.py` | **33/33**，0.011s，OK |
| `python -m unittest discover -s tests -p test_business_signal_policies.py` | **24/24**，0.009s，OK |

覆盖附件基础、Filter、Time、Unit / Declaration、Numeric 的 39 个必测场景及额外边界。S1/S2/S3 happy path 均明确提供单位、时间域、row selection、population、revision，以及 S1 target 的 basis / source uniqueness。

补充回归包含不相关指标除法、混入 JOIN / QUALIFY、未知 facts 不制造冲突、声明空白引用、相同 filter domain 掩盖缺失物理条件、明确 revision pair、同 ID 异内容、source 唯一性范围及输入纯函数性质。缺 counterpart key、重复结果 key、零分母仍不在此阶段求解。

## 21. backend 全量回归

专项之后执行：`python -m unittest discover -s tests`。

结果：**Ran 694 tests in 18.736s — OK**，进程退出码 0，无失败或错误。

计数核对：原基线 **561** + Compatibility 新增 **120** + Numeric helper 新增 **13** = **694**。原有 561 项全部包含在本次回归中。

完整本地日志：[backend-tests.log](<C:/Users/Wang Hongbo/.codex/visualizations/2026/09/07/01a07c06-45b4-7451-854d-0a060836bcda/phase31c/backend-tests.log>)。日志位于仓库外，不作为代码变更。

## 22. 当前尚未实现的 3.1 内容

以下内容仍未实现：

- row-level Business Key Alignment。
- missing key 判断。
- duplicate key 行检测及 normalization collision 处理。
- S1 attainment_rate、S2 absolute_change / change_rate、S3 contribution_rate 公式。
- SignalEvidence 自动装配。
- Signal ID。
- SignalBatch / Engine。

本阶段没有生成 BusinessSignal，也没有推进上述后续功能。Phase 2 保持冻结。
