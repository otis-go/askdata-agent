# Phase 3.4.4 S3 Evidence Integration Report

S3 Product Contribution 已接入统一 SignalEvidence。每个 Signal 都包含 `parts:metric`、`total:metric` 两份操作数证据，并通过 contribution_rate 的 input_evidence_ids 与 current/reference observation 关联。Evidence 记录已有事实，不重新计算。

新增 S3 Evidence 测试 22/22；原 S3 Calculator 测试 72/72；Business Signal 合计 632/632；backend 全量 **1082/1082**，相对 1060 项基线无回归。

本阶段未实现 **S3 Audit、SignalBatch、Engine、Workflow**，没有新增 SQL、DB、LLM 或 Agent 功能。

## 1. Evidence 模型变化

继续复用 `SignalEvidence`，没有创建 ProductContributionEvidence。只增加一个可选字段：

```python
alignment_broadcast: bool | None = Field(
    default=None, exclude_if=lambda value: value is None,
)
```

| 值 | 含义 |
| --- | --- |
| True | 此 Evidence 所在的 matched pair 使用 global total broadcast；parts 保留自身 key，total 没有 key |
| False | 显式普通 matched pair，不声明广播 |
| None | 未提供该语义；包括旧 S1/S2 路径，以及没有可信 matched pair 的失败路径 |

只有新字段为 None 时被省略，未启用全局 exclude_none，也没有改变旧字段的 null/list 序列化。显式广播事实仅支持 parts/total matched 操作数；广播 total 必须保留 row 0、business_key=None、key_values=[]，不能贴上 part 的业务键。

保留 Phase 3.4.3 已有的 operand_references 定位信息，与统一 Evidence 共存。没有新增 Signal ID 策略，也不生成 UUID、timestamp 或随机身份。

## 2. Builder 变化

`build_signal_evidence()` 增加可选参数 `alignment_broadcast=None`。S1/S2 调用无需修改。S3 对已验证的 matched pair 显式传入 pair.broadcast；其他路径传 None。

新增检查只验证调用方提供的位置标签是否一致：参数为严格 bool、角色与 left/right side 对应、pair 为 matched、标记与 pair.broadcast 相同；广播配对的 total 必须为 right row 0 且 right_key=None。Builder 不重新判断 grain、Compatibility 或 Alignment，不计算 context digest，不读取 rows，也不调用 Numeric Reader 或公式。

Evidence 字段来源如下：

| 字段 | 已有来源 |
| --- | --- |
| result_id、context_version、result_contract_version | 当前 BusinessContext |
| context_digest | Calculator 对当前输入生成的既有身份摘要 |
| column_id、ordinal、dtype、encoding、representation_status | selection.metric_column_id 对应的 execution column 元信息 |
| row_index、business_key、key_values、alignment_status、alignment_broadcast | 已绑定 Alignment 的该操作数一侧 |
| source_fields、schema_metadata、aggregation | 当前选中列的 ColumnSemantic |
| metric_semantic、normalized_period、normalized_filters、eligibility.declarations | 已由 Calculator 验证的当前 Compatibility receipt |
| grain、time、filters、upstream_limitations | 当前 BusinessContext 捕获事实 |
| observed_value.value、raw_value、numeric_quality、numeric_issues | 本次计算已获得的 NumericReadResult |
| unit_declaration、observed_value.unit_id | receipt 已消费、Calculator 已解析的单位声明 |
| formula_refs | contribution_rate / 1 的关联信息 |

未知或未读取的事实保持未知；formula_refs 表示关联，不能把失败路径中的公式引用解释为公式已执行。Evidence 不包含 computed_value。

## 3. S3 接入方式

Calculator 在统一的 Signal 装配点调用 Builder，分别传入 parts、total 的 Context、selection、已读取 NumericResult、可信配对位置和单位。当前输入无法通过门禁时，也生成两份记录真实失败状态的 Evidence，不借用未经验证的 pair 或 normalized semantics。

输出关联为：

```text
BusinessSignal
  current_value.evidence_id   = parts:metric
  reference_value.evidence_id = total:metric
  computed_value.contribution_rate.input_evidence_ids
                             = [parts:metric, total:metric]
  evidence                   = [parts Evidence, total Evidence]
```

这两个 Evidence ID 在单个 Signal 内标识操作数；不是跨 Signal 的全局唯一身份。current/reference observation 由 Evidence 中保留的原始 Numeric 观察提供，读取结果本身不会被改写。移除已经完成阶段的 EVIDENCE_INTEGRATION_PENDING 提示。

Calculator 继续负责 qualification gate、Numeric 读取、完整分区核对、贡献率公式与状态。`_arithmetic`、`_reconcile`、`_ratio`、`_alignment_shape_matches`、`run`、`compute_partition`、`accepted_units`、`reference`、`reject` 九个函数的 AST 与本轮修改前完全相同。

另将修改前 Calculator 与当前版本对照运行 12 个成功/失败场景；除新增 Evidence 关联及移除 pending 提示外，计算值、状态、reason、品质、定位信息与其他问题记录一致。没有再次求和、求比例或读取数值。

## 4. Broadcast Evidence

真实 category/global-total 链路的示例：

| 输出 | parts Evidence | total Evidence |
| --- | --- | --- |
| A，contribution_rate=0.400000000000 | parts result，col_m，ordinal 1，row 0，value=40.00，key=A | total result，col_m，ordinal 0，row 0，value=100.00，key=None |
| B，contribution_rate=0.600000000000 | parts result，col_m，ordinal 1，row 1，value=60.00，key=B | 同一个 total result/column/row/value，key=None |

两侧 alignment_broadcast=True 表示该 pair 使用 total 广播；没有把 parts 本身描述成 global aggregate。total 的 key_columns={}、key_values=[]、business_key=None，grain 仍来自 total Context。

多个 part 对应的 total Evidence 内容相同，使用同一次 total Numeric 读取结果；每个 Signal 持有独立深拷贝，修改一个输出不会污染其他输出或输入。整数 product_id 同样保留原始类型，不转换为类别名称。

当前两个支持的 S3 profile 的真实 producer 仍产生 matched+broadcast 配对。False 的模型往返和局部位置语义不等于已经获得真实 producer 的普通非广播 S3 端到端样本；本轮未伪造或重签这样的成功回执。

失败处理：

| 场景 | Evidence 行为 |
| --- | --- |
| missing/空结果在资格阶段被拒绝 | 记录当前 result/column、捕获的 completeness/row count；observed_value 为 not_read，无虚构 row/value/key |
| 已确认的 missing side | missing，无该侧 row/raw/key，不把另一侧 key 复制过来 |
| NULL | sql_null，保留真实 row，raw/value 为 None，不能成为零 |
| Numeric reject | rejected，保留真实 row、Reader raw_value、品质和拒绝问题，不产生计算值 |
| 合法但未 aligned 的重复/歧义配对 | 保留已确认的状态与可定位事实；不选第一行，不声称是 matched broadcast |
| receipt mismatch / Alignment mismatch | 不消费旧 pair，row/key/alignment_broadcast 为空、not_read；不引用未验证的 normalized metric、period 或声明 |
| total=0 | 保留真实零操作数和既有 undefined/incompatible 状态，不在 Evidence 中补算比例 |

## 5. S1/S2 兼容性

S1、S2 源文件未修改。新参数默认 None，S1/S2 Evidence 对象中该值仍为 None，JSON 不出现新增字段，也不无条件写 False。

修改前保存 S1/S2 各自正常、零分母、NULL 共六组完整 JSON。修改后重新计算并逐字段比较，完全一致；新回归测试同时保存这些输出的 canonical SHA-256 期望值，不依赖开发机的外部快照文件。另验证旧 JSON 反序列化再序列化仍完全相同，包括旧 null 和空列表。

共享 Evidence 原有 47 项、S1 66 项、S2 73 项测试均通过。

## 6. 测试结果

新增 `backend/tests/test_product_contribution_evidence.py`，22 项通过，覆盖全部 15 类要求：

- category 与 integer product_id 的两份 Evidence、formula links 和字段完整性。
- 显式广播、total business_key=None、多个 part 共享同一总额事实且相互隔离。
- 缺失、NULL、Numeric reject、receipt mismatch、Alignment mismatch，不伪造输入依据。
- Decimal 原文、DOUBLE approximate、零总额、来源品质与比例舍入分离。
- Numeric 恰好 N+1 次，总额一次；Builder 消费已有结果，Reader 对象不变。
- Builder 参数矛盾防御；禁止其读取 rows、重新资格判断、重算 digest 或公式。
- JSON roundtrip、S1/S2 历史输出、输入/输出深拷贝、A→A 与 A→B→A。
- 无 SQL、LLM、文件/网络 IO、clock 或随机身份依赖。

原 `test_product_contribution.py` 的 72 项保留全部公式和失败断言，仅将上一阶段“没有 Evidence、不得调用 Builder”的阶段断言更新为“两份关联 Evidence、复用 Builder”；仍检查无上游重跑和无 SQL/LLM 等边界。

独立接线复核另外执行 12 个真实 S3 公共链探针，确认失败真实性、总额读取次数和 Evidence 隔离；这是本轮实现验证，没有扩大为完整 S3 业务 Audit。

## 7. Backend regression

使用现有 backend `.venv/Scripts/python.exe` 与 unittest：

| 测试组 | 通过 |
| --- | --- |
| S3 Calculator | 72/72 |
| S3 Evidence | 22/22 |
| S1 | 66/66 |
| S2 | 73/73 |
| 通用 Evidence | 47/47 |
| Business Signal 基础模型、Policy、Numeric、Compatibility、Alignment | 352/352 |
| Business Signal 合计 | **632/632** |
| backend full | **1082/1082** |

全量命令：`python -m unittest discover -s tests -q`，工作目录为 backend；1082 项用时 26.391 秒。总数为基线 1060 加新增 22 项，无失败。Business Signal 合计包含上述子组，不与 backend 数量重复累加。

本轮文件变更：

- `backend/app/querying/business_signals/models.py`：SignalEvidence 可选广播字段与局部形状校验。
- `backend/app/querying/business_signals/evidence.py`：显式广播参数及既有事实装配。
- `backend/app/querying/business_signals/product_contribution.py`：S3 Evidence 接线及引用。
- `backend/tests/test_product_contribution.py`：迁移上一阶段禁止 Evidence 的断言。
- `backend/tests/test_product_contribution_evidence.py`：新增 22 项。
- 本报告。

对本轮前保存的 109 个既有源码文件进行哈希比较，变化仅有前四项。Compatibility、Alignment、Numeric Reader、S1/S2、Policy、Phase 2、ResultContract、Workflow 均未修改。没有暂存或提交工作区文件。

## 8. 剩余边界

Evidence 依赖调用方已确认的 Compatibility/Alignment 和实际 Numeric 读取结果，不独立认证这些事实，也不重新查询数据。绑定用于避免旧输入结果的错误复用，不是安全签名。

本轮没有变更受支持的 category/product_id 销售范围、分区完整性、广播资格、相对容差或零总额策略。Evidence 只记录依据，不产生额外计算值或业务判断。

**Phase 3.4.4 S3 Evidence Integration 已完成。S3 Audit、SignalBatch、Engine、Workflow 本阶段未实现。**
