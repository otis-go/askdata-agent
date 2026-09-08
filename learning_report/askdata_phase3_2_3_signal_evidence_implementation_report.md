# Phase 3.2.3 Signal Evidence Implementation Report

日期：2026-09-08

**Signal Evidence 已从 S1 提取为通用纯函数层。Evidence 专项 47/47、S1 66/66、既有 Business Signal 352/352 全部通过；backend 全量 915/915 通过。**

实施前已审计现有字段，输出 [Evidence Extraction Design](askdata_phase3_2_3_evidence_extraction_design.md)。本轮独立审阅未发现剩余 P0/P1。

## 1. Evidence 模型

沿用 `models.SignalEvidence`，保留全部原字段及其含义，新增以下通用字段：

| 新增字段 | 含义 |
| --- | --- |
| business_key | 当前操作数的完整本侧业务键，来自 AlignmentPair.left_key/right_key |
| alignment_status | 已有 pair 的状态，不是 Builder 新作的对齐判断 |
| numeric_quality | NumericReadResult 的质量快照，与 observed_value.source_quality 一致 |
| numeric_issues | 原 Numeric Reader issues，不重新解码或判断数值 |
| formula_refs | EvidenceFormulaRef 列表，每项只含 formula_id、formula_version |

`formula_refs` 支持同一操作数关联多个公式；本轮 S1 填入 `attainment_rate / 1`。公式引用不证明公式执行成功，undefined 或拒绝结果仍可说明所关联的公式。

旧载荷未提供新增字段时仍可读入模型：默认键/状态/质量为空、issues/公式引用为空列表。Builder 新产生的 Evidence 始终提供数值质量或明确 unknown 质量。

关系保持：`BusinessSignal.evidence[] -> SignalEvidence`。**BusinessSignal 保存计算结果、状态和计算限制；SignalEvidence 保存操作数依据。** Evidence 模型没有 computed_value、signal_id 或计算逻辑。

## 2. Evidence Builder

新增 `backend/app/querying/business_signals/evidence.py`：

```python
build_signal_evidence(
    *, context, selection, context_role, evidence_id, context_digest,
    row_index, numeric_result, alignment_pair, alignment_side,
    formula_refs, compatibility=None, unit_declaration=None,
) -> SignalEvidence
```

所有输入均为已有事实。context/selection 提供已捕获元数据；row_index 与 alignment_side 显式标识已有配对的一侧；numeric_result 是已经完成的读取快照。可选 Compatibility 只提供由调用方认可的规范事实，单位声明由调用方完成选择。

Builder：

- 按显式 column_id 定位元数据，不按显示名查找，不访问 execution.rows。
- 仅从 NumericReadResult 取得 observed_value、raw_value、numeric_quality 和 issues；不使用 work_value 执行算术。
- 不重新计算 Context digest；只记录显式传入的摘要。
- 不运行 Compatibility、Alignment、Numeric Reader、公式、SQL、数据库查询、LLM 或 clock。
- 每次直接返回深拷贝后的 SignalEvidence，不依赖外层 BusinessSignal 再复制才获得隔离。

局部一致性检查拒绝相互矛盾的事实：row_index 与 pair 侧不符；missing 侧携带数值读取；Numeric 观察的 evidence_id/unit_id 冲突；单位声明的 result_id/context_digest/column_ids 不属于当前操作数；Compatibility 已提供的结果/摘要标签与当前操作数不符。

这些检查不验证 Compatibility status/binding，不重算摘要、不比较 metric/time/filter/unit 资格。测试确认仅改变 Compatibility status 不会让 Builder 自行重新判断资格；资格门禁仍由计算器承担。

## 3. S1 改造

`_TargetAttainment.evidence()` 现在只负责 actual/target 到 left/right 的映射、传递已认可事实和 Policy 公式引用，然后调用 `build_signal_evidence()`。全部 Evidence 元数据与观察构造已移到通用层。

以下九个函数与重构前 AST **完全一致**：`_issue`、`_ratio`、`__init__`、`accepted_units`、`signal`、`reject`、`run`、`compute_pair`、`compute_target_attainment`。

因此 S1 的公式、Decimal 策略、资格/来源门禁、Numeric 调用、状态优先级、zero denominator、missing 处理及 signal_id 策略均保持原实现。

重构前后还对 S1 66 项测试中的 **69 次计算调用、150 个 Evidence 记录**进行完整快照比较。仅剔除五个新增 Evidence 字段后，所有旧字段和计算结果逐字段完全相同。

本轮文件范围：

| 文件 | 变化 |
| --- | --- |
| `backend/app/querying/business_signals/evidence.py` | 新增通用 Builder |
| `backend/app/querying/business_signals/models.py` | 新增 EvidenceFormulaRef 及五个 Evidence 字段/结构约束 |
| `backend/app/querying/business_signals/target_attainment.py` | import 与 Evidence 适配方法改造 |
| `backend/tests/test_signal_evidence.py` | 新增 47 项回归 |
| `learning_report/askdata_phase3_2_3_evidence_extraction_design.md` | 提取设计 |
| `learning_report/askdata_phase3_2_3_signal_evidence_implementation_report.md` | 本报告 |

本轮开始记录了 123 个既有源文件/测试/报告的 SHA256。只有 models.py 和 target_attainment.py 两个已有文件发生变化；既有测试、Compatibility、Alignment、receipt binding、Numeric、Policies、BusinessContext 和 ResultContract 均未修改。

## 4. 字段来源

| Evidence 字段 | 来源与约束 |
| --- | --- |
| result_id、context_version、result_contract_version | 当前 BusinessContext，保留不支持的原始上游版本供审计 |
| context_digest | 调用方已有输入摘要，不由 Builder 计算 |
| column_id、ordinal | selection.metric_column_id 对应的捕获列元数据 |
| source_fields、schema_metadata、aggregation | 当前列 ColumnSemantic；schema_metadata 承载需求中的 schema_binding |
| row_index、business_key、key_values、alignment_status | 显式位置与已有 AlignmentPair 本侧；缺失侧不借用另一侧的业务键 |
| key_columns | 已有 SignalSelection.key_column_ids |
| metric_semantic、normalized_period、normalized_filters | 调用方已认可的 Compatibility 中对应角色事实 |
| grain、filters、time | BusinessContext 原始查询语义；time 保留现有名称，承载 time_constraints |
| observed_value、raw_value | 已有 NumericReadResult；未读取时没有 raw_value |
| dtype、value_encoding、representation_status | 捕获列元数据；value_encoding 对应需求中的 encoding |
| numeric_quality、numeric_issues | Numeric Reader 原快照，保留 approximate/exact 区别 |
| formula_refs | 计算器提供的固定公式 ID/版本，不携带计算结果 |
| eligibility、unit_declaration、provenance | 已捕获完整性、已选完整单位声明及原执行 provenance |
| upstream_limitations | Context、query bindings、grain、filter 及其条件、时间条件、所选列语义的原说明 |

Evidence.numeric_quality 描述输入读数质量；公式的除法/输出舍入质量仍在 BusinessSignal.computed_value 中，两者不混用。

不支持或不完整情况保持真实：

| 情况 | 记录方式 |
| --- | --- |
| missing | presence=missing；本侧 row_index/business_key/raw_value/value 均为空，不填零 |
| duplicate / ambiguous | 不挑选重复行；该侧无确定行时不声称行位置或业务键 |
| unresolved | 保留已有 pair 状态，不冒充 missing |
| 未读取 | presence=not_read；可保留可信配对位置，但 raw_value 为空 |
| SQL NULL | presence=sql_null，保留真实 row_index，包括 0 |
| Numeric 拒绝 | presence=rejected，保留已读取原值、位置及 Numeric issues |
| undefined | 原操作数仍是 present，例如目标确实为 0；计算状态留在 BusinessSignal |
| incompatible receipt / 未过来源门禁 | S1 传入无旧 pair、无认可 Compatibility 事实的 context 级依据 |

## 5. 测试

新增 `test_signal_evidence.py` **47/47 通过**，覆盖全部要求：

| 要求 | 验证 |
| --- | --- |
| S1 normal evidence | 正常 S1 确实调用 Builder 两次；actual/target 的 result_id、column_id、row_index 和公式引用完整 |
| multiple operands | 两个操作数与 ComputationResult.input_evidence_ids 对应，左右角色显式 |
| missing operand | 不生成值、零、行位置或借来的本侧键 |
| numeric approximate | DOUBLE 的 approximate 来源质量不被提升为 exact |
| Decimal evidence | 原 decimal text/编码/精度保留，不重新格式化 |
| NULL | 保留 SQL NULL 和真实行位置 |
| input mutation | Builder 不改 Context、selection、pair、NumericResult、声明等；修改输出容器不污染输入 |
| JSON roundtrip | 新字段往返一致，旧载荷缺省字段可读入 |
| deterministic | 相同输入及相同内容重构返回相同 Evidence |
| no SQL | 运行时禁止 IO，静态禁止 SQL/数据库执行调用 |
| no LLM | 无网络/LLM 调用或依赖 |
| no clock | clock/random 调用被拦截，Builder 仍可完成 |

另外覆盖元数据名称与 ordinal 变化、Numeric 拒绝/未知元数据/未知 payload、重复/未解配对、undefined、标签矛盾、上游说明、禁止访问 execution.rows 或序列化整个 Context。

通用性测试使用既有 S2 角色及多公式引用、既有 S3 广播 Alignment 事实，仅构造 Evidence；没有实现 S2/S3 计算器。全局总计的真实行可记录，Builder 不为其虚构业务键。

独立审阅发现的跨输入单位声明关联问题已修复，并新增五类标识矛盾回归及“不重判 Compatibility status”的正向测试。

## 6. Backend 回归

| 测试组 | 通过数 |
| --- | ---: |
| Evidence 专项 | 47 |
| S1 Target Attainment | 66 |
| 既有 Business Signal（Alignment/Compatibility/Numeric/Models/Policies） | 352 |
| Business Signal 合计（包含 S1/Evidence） | **465** |
| backend 全量 | **915** |

baseline 868，加本轮新增 47 项，最终 **915/915，无失败或跳过**。没有修改、删减或跳过既有测试。

在 backend 目录可使用现有 `.venv\Scripts\python.exe` 复现：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_signal_evidence.py -q
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_target_attainment.py -q
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_business_signal_*.py' -q
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

S1 另经外部快照捕获程序运行全部 66 项测试并比较 69 次调用结果；快照不加入业务代码或测试目录。`git diff --check` 通过。Phase 3 原有文件在本轮开始时已未跟踪；本轮修改与新增文件保留在工作区，未执行 stage/commit。

## 7. 剩余边界

Builder 记录事实，不负责证明事实已获业务资格。调用方必须先完成当前输入对应的 Compatibility/Alignment 门禁，再传入认可的规范语义；它仍必须正确调用 Numeric Reader。

NumericReadResult 当前没有独立可验证的完整 row/column 来源绑定。Builder 只校验已有标签与配对位置是否矛盾，不声称能够独立认证 Numeric 快照来源，不重新读取单元格验证数值。非规范或相互矛盾的结构参数以异常拒绝，不制造占位数值。

signal_id 继续沿用 Phase 3.2 策略：未冻结身份生成规范时保持 None；没有 UUID、timestamp 或随机 identity。

**本阶段未实现 S2、S3、SignalBatch、Engine、Workflow。** 未接 SQL、数据库、LLM 或应用 Agent 流程。
