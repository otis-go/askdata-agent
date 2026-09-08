# Evidence Extraction Design

日期：2026-09-08；审计对象：Phase 3.2 的 `target_attainment.py` 与 `models.py`。

## 当前字段审计

现有 `SignalEvidence` 已包含以下通用事实；当前构造位于 `_TargetAttainment.evidence()`。

| 分组 | 当前字段 | 提取决策 |
| --- | --- | --- |
| 执行身份 | result_id、context_version、result_contract_version、context_digest、provenance | 通用 Builder 原样记录 |
| 列身份 | column_id、ordinal、source_fields、schema_metadata | 按显式列 ID 提取已捕获元数据；schema_metadata 对应需求中的 schema_binding |
| 行与键 | row_index、key_columns、key_values | 通用化，新增完整 side business_key 和 alignment_status；缺失侧不借用另一侧的键 |
| 指标 | metric_semantic、aggregation | 复制已有源语义与调用方已认可的 Compatibility 规范事实 |
| 查询语义 | grain、filters、time、normalized_period、normalized_filters | 原样记录；保留原字段 time，承载 time_constraints，避免重命名既有输出 |
| 数值 | observed_value、raw_value、dtype、value_encoding、representation_status | 只消费已有 NumericReadResult；value_encoding 对应 encoding |
| 数值质量 | 当前位于 observed_value.source_quality | 新增直接 numeric_quality 和 numeric_issues，保留原嵌套观察字段 |
| 单位/完整性 | eligibility、unit_declaration | 保留已接受的声明与已捕获完整性事实，不再判断资格 |
| 限制 | upstream_limitations | 汇集 Context/query bindings/grain/filter/time/selected semantic 的既有限制 |
| 公式 | 当前仅在 BusinessSignal.computed_value 中引用 | Evidence 新增 formula_refs，每项只含 formula_id 与 formula_version；支持一项操作数参与多个公式 |

`SignalEvidence` 不增加 computed_value，不携带或生成 signal_id，不计算任何公式。

## 通用事实与 S1 决策的边界

通用 Builder 负责记录、定位已有列元数据和分离复制。它不判断 Context 是否有业务资格，也不验证 receipt binding、不重新 Alignment、不调用 Numeric Reader。读取原 NumericReadResult.raw_value 不等同再次访问 execution.rows 单元格。

S1 继续负责 actual/target 到 left/right 的角色映射、已通过的输入与 receipt 门禁、单位声明选择、Numeric 调用、attainment_rate 公式、状态优先级、零目标与 missing 的计算决策，以及 `actual:metric`/`target:metric` 引用命名。

## Builder 契约

新增 `evidence.py` 与关键字参数纯函数 `build_signal_evidence(...) -> SignalEvidence`。

显式输入：BusinessContext、SignalSelection、context_role、evidence_id、context_digest、row_index、已有 numeric_result、alignment_pair、alignment_side、formula_refs，以及可选的已认可 Compatibility 规范事实和已选 unit_declaration。

`alignment_side` 只解释已有 pair 的左右位置；验证参数位置与 pair 一致属于局部结构校验，不生成或重做配对。传入 Compatibility 仅作为已认可事实的来源；S1 只有通过既有资格/来源门禁后才传入，否则传 None，并且拒绝路径不传旧 pair。

Builder 还拒绝明确的标签矛盾：Numeric 观察的 evidence_id/unit_id 与显式参数不符、单位声明的 result_id/context_digest/column_ids 不属于当前操作数，或 Compatibility 提供的 result_id/context_digest 与当前标签不符。它不重算摘要、不验证 Compatibility status/binding，也不比较指标、期间、单位尺度或其他资格规则。

Builder 按本侧 pair 状态记录 missing 或 not_read；已有 Numeric 观察的 present/sql_null/unknown_payload/unknown_metadata/rejected 保持原义。不重新取值、不补零；缺失行不产生 row_index、原始数值或本侧业务键。

公式引用使用列表，避免把未来“一组操作数、多个公式”的审计信息绑定在 S1 单公式形状上。本阶段只给 S1 填入 attainment_rate，不实现其他计算器。

## 兼容性与验证

原 Evidence 字段名称与含义保留；新增字段以默认值兼容旧模型载荷。保持 signal_id 当前策略。

重构前已运行 S1 66 项测试，并捕获其中 69 次计算调用的完整返回快照。重构后逐字段比较，除新增 Evidence 字段外，要求旧字段及计算结果完全相同。同时对 S1 公式、门禁、Numeric 调用、zero/missing 分支进行源码 AST 比较。

新增 `test_signal_evidence.py` 验证用户要求的 12 类情况，以及直接 Builder 深拷贝、绑定参数矛盾、missing/duplicate/undefined/incompatible 的无虚假观察。现有 S1 和 Business Signal 测试保持原样执行，最后运行 backend 全量回归。

## 明确边界

NumericReadResult 当前不带可独立验证的完整 row/column 来源绑定。其来源仍由已过门禁并按指定单元格读取的计算器保证；Builder 不声称额外认证。公式引用表示计算依据的关联，不表示公式已成功执行，实际状态和结果仍属于 BusinessSignal。

本阶段不涉及 S2、S3、SignalBatch、Engine、Workflow；不新增 SQL、数据库、LLM、clock 或随机身份依赖。
