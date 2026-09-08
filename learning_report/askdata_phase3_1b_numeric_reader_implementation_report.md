# Phase 3.1B — Numeric Reader Implementation Report

已完成确定性数值读取层。Numeric 专项 **54/54**、models **33/33**、policies **24/24** 通过；backend 全量 **561/561** 通过，原有 507 项无回归。

本轮没有修改 Phase 3.1A 模型或 Policy。实施前后对 98 个已有文件（96 个源码/测试文件、2 份 Phase 3 文档）进行 SHA-256 核对，全部未变。Phase 1、Phase 2、Agent、Workflow、MCP、DuckDbEngine 与 SQL execution 保持原样。

## 1. 修改文件

| 新增文件 | 内容 |
|---|---|
| [numeric.py](D:/agent_study/askdata_studio/backend/app/querying/business_signals/numeric.py) | 单个 canonical cell 的定位、数值资格与读取；小型内存返回对象 |
| [test_business_signal_numeric.py](D:/agent_study/askdata_studio/backend/tests/test_business_signal_numeric.py) | 54 项专项测试，全部使用手工构造的公开模型 fixture |
| 本报告 | API、行为边界、测试与回归结果 |

已有 models.py、policies.py 不需要扩展。Git 中 Phase 3.0/3.1A 的未跟踪文件在本轮开始时已经存在；本轮未暂存或提交文件。

## 2. Numeric Reader 公共 API

[read_numeric_value](D:/agent_study/askdata_studio/backend/app/querying/business_signals/numeric.py:107) 使用窄接口：

```python
read_numeric_value(
    context: BusinessContext,
    column_id: str,
    row_index: int,
    numeric_rules: NumericRules,
    *,
    unit_id: str | None = None,
    evidence_id: str | None = None,
) -> NumericReadResult
```

unit_id、evidence_id 只复制调用者显式提供的标签，不验证其业务含义，不生成默认单位或身份。

[NumericReadResult](D:/agent_study/askdata_studio/backend/app/querying/business_signals/numeric.py:28) 是 numeric.py 中的小型 frozen dataclass：

| 字段 | 含义 |
|---|---|
| status | ready / insufficient_evidence / incompatible_context / unsupported |
| observed_value | 复用 ObservedValue；已知拒绝时为 None |
| work_value | 安全读取后的 Decimal，失败时为 None |
| raw_value | 原 canonical scalar；未定位到 cell 时为 None |
| numeric_quality | 复用 NumericQuality |
| issues | Issue 的 tuple；程序依据 code 和路径判断 |

这是内存读取结果，**不是新的 JSON wire contract，也不是 BusinessSignal**。Decimal 留在内存中，公开 ObservedValue 保存文本。被拒绝的 NaN/Inf 可作为 raw_value 留作内部诊断，绝不成为正常的 ObservedValue.value；调用方不能把整个返回对象直接当作可发布的 JSON 证据。

现有 ObservedValue 不允许 present 同时 value=None，而 known unsupported 不等于 unknown_metadata。因此已知拒绝采用 observed_value=None、work_value=None，另保留 raw_value 与 Issue，无需重新设计 Phase 3.1A 契约。

ready 只表示该单元格在 NumericRules 下可读取，不代表 Context 业务兼容、单位已验证或业务公式已计算。

## 3. Column / row 定位规则

唯一取值路径：

```text
BusinessContext.execution.columns
  → 唯一 column_id
  → ColumnMetadata.ordinal
  → execution.rows[row_index][ordinal]
```

不读取 output_name、Schema label/alias、column_semantics 来猜列，也不使用 legacy dict。重复 display name 不影响按 ID 定位。

由于已有公开模型的嵌套列表可变，Reader 重新检查当前位置结构：

- ColumnMetadata.id 非空且在整个结果中唯一。
- ordinal 是真实 int，且等于该列在 columns 中的零基位置；不接受 bool、不修正 ordinal。
- rows/每行保持 positional list，行宽与已知 columns 数量一致。
- row_index 是真实非负 int；已知 rows 中越界明确拒绝。

**异常边界：** 错误参数类型抛 TypeError；不存在的 column_id、重复 ID、ordinal 矛盾、非法行宽、负/越界 row_index 等结构错误抛 ValueError。非法 NumericRules 定义由 Pydantic ValidationError（ValueError 子类）拒绝。不会将结构错误转成 zero、SQL NULL 或业务 key missing。

columns=None 表示无法定位列元数据，返回不足；columns=[] 则是已知不存在请求列，抛 ValueError。rows=None 表示未知 payload，rows=[] 则无法提供请求的观察行，抛 ValueError。

## 4. DECIMAL 路径

只接受实际 DECIMAL(p,s) + decimal_text + preserved，且值的 Python 类型严格为 str。

按当前 producer 范围检查 1≤p≤38、0≤s≤p。文本只接受有限 ASCII 十进制语法，允许 Decimal 原生字符串可能出现的科学计数形式；拒绝空白、下划线、Unicode 数字、逗号、NaN/Infinity 或任意显示字符串。

在明确的 localcontext 内直接使用 `Decimal(text)`，不经过 float。原 text 完整保存在 raw_value 和 ObservedValue.value 中，例如 "123.4500" 的尾零与 scale 不被清除。

同时检查物理 DECIMAL precision/scale 与 NumericRules 工作范围。超限返回 unsupported，不量化、截断或修补。科学计数文本原样保留，不展开为定点格式；本阶段不提供格式化能力。

## 5. Integer 路径

允许当前 producer 的十个整数 dtype：

```text
TINYINT / SMALLINT / INTEGER / BIGINT / HUGEINT
UTINYINT / USMALLINT / UINTEGER / UBIGINT / UHUGEINT
```

必须是 native_json + preserved，且 `type(raw) is int`。bool、float 和看起来像整数的 str 均拒绝。额外核对 signed/unsigned 物理范围，再执行 NumericRules 范围检查，避免 TINYINT=256 等矛盾观察被接受。

整数转为精确工作 Decimal，source_fidelity=exact、source_kind=integer。integer_text 虽存在于 Phase 1 codec 枚举中，但没有 V1 读取能力，始终 unsupported。

## 6. FLOAT / DOUBLE approximate 路径

必须满足 FLOAT / DOUBLE + native_json + preserved、真实 Python float、有限值，并显式使用 reporting_approx_v1 且 allow_binary_float=True。

decimal_exact_v1 遇到该来源返回 incompatible_context，不自动切换 profile。被批准的浮点使用：

```text
原 canonical float
  → repr(raw)：已接收 float 的最短 round-trip 文本
  → Decimal(text)
```

未调用 Decimal(float)。raw_value 保留原浮点；ObservedValue.value 保存工作文本。NumericQuality 明确标记 approximate / binary_float，不声称恢复数据库原始十进制金额精度。

NaN / ±Infinity 一律 unsupported，没有正常数值观察或工作 Decimal。浮点也受 magnitude / scale 限制；极小残差不会被自动视为零。

## 7. NULL / missing / unknown 处理

| 情形 | 返回 |
|---|---|
| 真实 cell=None | insufficient_evidence；presence=sql_null；value/work_value=None |
| rows=None | insufficient_evidence；presence=unknown_payload |
| columns=None，rows 已知 | insufficient_evidence；presence=unknown_metadata；不猜列位置 |
| dtype/encoding/representation 缺失 | insufficient_evidence；presence=unknown_metadata；保留已定位 raw_value |
| 已知空 rows 或请求行越界 | ValueError，不返回 missing/NULL/0 |

SQL NULL 优先保留真实观察状态，不要求全 NULL 列具备尚未建立的 codec/保真元数据。NULL 永远不转成 "0" 或 Decimal(0)。

本阶段从不产生业务 key missing：哪个 key 对应哪行、缺哪一侧，属于后续 Alignment。

## 8. representation_status 规则

| representation_status | 非 NULL cell 的处理 |
|---|---|
| preserved | 继续检查 dtype、codec、值类型和 Policy |
| lossy | incompatible_context |
| unsupported | unsupported |
| None | insufficient_evidence，不自动视为 preserved |

已知 lossy / unsupported 不被另一个缺失的元数据字段覆盖。模型被外部变异为非法 representation 字符串时，抛 ValueError；它不是新增合法枚举。

未知元数据不会通过 Python runtime 值反推数据库类型。VARCHAR "100.00"、BOOLEAN、未批准的 dtype 或 codec 不因“看起来能转成数值”被接受。

## 9. NumericRules 实际执行方式

读取入口对 NumericRules 定义做独立 dump + 严格重新验证，防止冻结模型中的 accepted_encodings 列表被事后修改后绕过规则。

| 字段/要求 | 实际作用 |
|---|---|
| profile / allow_binary_float | 控制浮点路径；exact 不降级 |
| accepted_encodings | 被 Policy 排除的已支持 codec 返回 incompatible_context |
| required_representation | V1 必须 preserved |
| decimal_precision | 设置局部工作精度并限制有效位数 |
| max_abs_exponent | 严格执行 abs(value) < 10^n，边界值也拒绝 |
| max_input_scale | 执行工作文本的实际 scale 上限，不预先舍入 |
| negative_inputs | 当前 reject；负数 incompatible_context；signed zero 保留 |
| rounding | 显式固定局部 Context 的舍入模式，但 Reader 不执行量化 |

物理 dtype 范围与 Policy 范围分别检查。超出任一批准范围均不 clamp/truncate/round。

ratio_scale、max_parts、zero_denominator、reconciliation/relative_tolerance 属于后续公式或集合核对，本次不用于输入舍入、行集合计算或除零判断。数值 0 在读取阶段是正常数值。

## 10. Decimal local context

全部 Decimal 构造与范围检查都处于独立 localcontext。显式指定 precision、rounding、Emin/Emax、capitals、clamp、flags、traps，避免继承调用方或 DefaultContext 的环境设置。

precision 来自严格验证后的 NumericRules（当前固定 80）。Decimal(text) 精确构造；通过 tuple、scale 和 adjusted magnitude 检查资格，不使用 unary plus、normalize 或 quantize 偷偷舍入。

实现不修改 getcontext() 或 DefaultContext。测试同时改变两者的精度、指数范围、flags 和 traps，比较正常环境下的结果，并核对调用前后全部上下文属性完全相同。

## 11. NumericQuality

| 成功来源 | source_fidelity | source_kind |
|---|---|---|
| DECIMAL text | exact | decimal_text |
| 原生整数 | exact | integer |
| 显式获准的 FLOAT/DOUBLE | approximate | binary_float |

读取没有新增算术舍入，arithmetic_rounding=exact；该字段不抵消 binary_float 的 approximate 来源属性。scale 来自原精确工作文本的 Decimal exponent，不默认金额两位小数或比率十二位。

失败不产生可计算工作值，NumericQuality 保持 unknown。单位和 evidence_id 缺省为 None；ready 不以虚构 CNY 或随机 ID 为前提。

## 12. 失败状态分类

| 分类 | 典型情形 |
|---|---|
| insufficient_evidence | unknown payload、SQL NULL、缺 columns/dtype/encoding/representation |
| incompatible_context | lossy、exact profile + binary float、已支持 codec 被 Policy 禁用、负输入被拒绝 |
| unsupported | 未支持 dtype/codec、integer_text、runtime 类型与 codec 不符、非有限值、非法 decimal text、magnitude/scale/物理 dtype 范围超限 |
| TypeError / ValueError | 参数、身份与 positional structure 非法；不包装为业务数值失败 |

每个结构化失败带 stage=numeric 的 Issue，含 code、result_id、evidence_paths、severity、message。message 只解释；控制流程不解析它。

检查顺序为：合法参数与已知位置结构 → payload/列元数据是否存在 → 真实 NULL → 非有限值 → 已知表示质量 → 缺失元数据 → 类型/codec 能力 → Policy 许可 → 数值范围。若存在明确结构错误，先抛异常，不用 unknown 状态掩盖。

## 13. 输入纯度

函数没有修改 Context、ExecutionData、rows、ColumnMetadata 或 NumericRules。没有缓存、当前时间、随机身份或全局 Decimal 状态依赖。同输入重复读取及 A → B → A 的结果一致。

静态检查确认 numeric.py 不导入 sqlglot、DuckDbEngine、Agent、Workflow、retrieval、LLM、数据库、环境或时钟模块。运行期封锁 I/O、socket、clock、uuid 和禁止的模块导入，验证成功、NULL、已知拒绝及非法文本路径。

只读执行数据不等于验证执行成功、SQL 合法、业务覆盖或语义 resolved；这些明确留给 Compatibility。Reader 也不会读取 SCHEMA 补单位或查询数据库补证。

## 14. 专项测试结果

Numeric 专项 **54/54 passed**，覆盖附件全部 22 类必测 Case，并补充：

- 十种整数物理类型、unsigned 负值与物理边界。
- 科学计数 DECIMAL、严格 ASCII 文本、原文/scale 保留。
- codec 被 Policy 主动禁用、变异 NumericRules 重新校验。
- duplicate output name、变异 duplicate ID、bool/string ordinal、行宽与非 scalar cell。
- 浮点近似、负零、极小非零值、非有限值拒绝。
- Context/rules 深比较、A → B → A、Decimal 全局与 DefaultContext 隔离。

所有新 fixture 直接构造公开 BusinessContext/ResultContract 模型，不调用 builder、SQL parser 或执行器。NaN/Inf 等无法通过正式契约构造的数据，通过合法模型构建后的嵌套列表变异注入，以验证 Reader 的防御检查。

独立只读审查与 16 项数值/环境探针通过，未发现必须修复的问题。

## 15. backend 全量回归

按要求依次完成：

| 顺序 | 测试 | 结果 |
|---|---|---|
| 1 | test_business_signal_numeric | 54 passed |
| 2 | test_business_signal_models | 33 passed |
| 3 | test_business_signal_policies | 24 passed |
| 4 | backend 全量 | **561 passed** |

使用 backend/.venv 中的 Python 运行 unittest。全量命令在 backend 目录执行：

```text
.venv/Scripts/python.exe -B -m unittest discover -s tests -v
```

结果：**Ran 561 tests in 15.423s — OK**，即原有 507 项 + 新增 54 项，无失败或跳过。

全量回归照常运行原有解析器/执行器测试；本轮未新增业务数据 SQL 查询或应用 LLM 调用。Numeric Reader 及其专项 fixture 不触发 SQL/LLM。

文件核对确认旧文件全部未变，新增代码与测试仅 numeric.py 和 test_business_signal_numeric.py。

## 16. 当前仍未实现的 3.1 能力

本阶段没有实现：

- Context Compatibility logic，包括 metric/grain/time/filter、单位、覆盖、声明信任与绑定判定。
- Key Alignment、key normalization、跨 Context 行匹配或 missing key 判断。
- S1/S2/S3 公式、比率量化、Signal 状态决策或 BusinessSignal 计算。
- SignalEvidence 自动装配、Signal ID 或 canonical digest 生成。
- SignalBatch / Engine、查询 acquisition 或 Agent/Workflow 接入。

本次结果只解决一个明确 canonical cell 能否安全形成工作数值。后续消费者仍需独立完成业务资格检查，再调用固定公式；不能把 ready 当作这些检查已经通过。
