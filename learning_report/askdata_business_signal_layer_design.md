# AskData Business Signal Layer Design Document

> 设计日期：2026-09-06。依据：[AskData Baseline Report](D:/agent_study/askdata_studio/learning_report/askdata_business_signal_baseline_report.md) 及本轮重新核对的源码。
> 本阶段只做设计，分块写入本独立 Markdown；不修改业务代码、测试、配置、数据，不实现新 Agent。
> 文中的 ResultContract、Result Understanding、SignalBatch 及相关字段均为**拟议设计**，不是当前源码已经存在的类型。标注“当前”的结论才是在描述现有实现。

## 1. Current Problem

### 1.1 当前不足不是缺一句分析文本，而是缺少可验证的计算输入

当前 [SqlExecution，L7–13](D:/agent_study/askdata_studio/backend/app/querying/models.py:7) 只有：

```python
@dataclass
class SqlExecution:
    sql: str
    success: bool
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
```

这些字段可以支撑结果展示，但不能单独回答：某列真正来自哪个表达式、是不是实付金额、可否再次 SUM、是什么期间与粒度、是否截断、分母是否完整、单位是否一致。

当前 [DuckDbEngine.execute，L42–49](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:42) 在捕获时已经发生信息压缩：

```python
cursor = connection.execute(safe_sql)
raw_rows = cursor.fetchmany(201)
columns = [item[0] for item in cursor.description or []]
rows = [
    {column: self._json_value(value) for column, value in zip(columns, row)}
    for row in raw_rows[:200]
]
return SqlExecution(safe_sql, True, columns, rows)
```

因此仅在最终 QueryResult 外面套一个类，不能恢复已经覆盖的同名列、丢掉的 dtype、Decimal 精度或截断信息。[数值转换 L144–150](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:144) 把日期转字符串、Decimal 转 float；新增契约必须在这些信息丢失之前取得证据。

### 1.2 三类内容必须独立保存

| 类别 | 例子 | 可以证明什么 | 不能证明什么 |
|---|---|---|---|
| A. Database Fact / DB-originated execution data | 实际执行 SQL、cursor 输出列与 dtype、返回单元格值、执行错误 | 数据库对这条 SQL 实际返回了什么；SQL 聚合值也属于 DB-originated 输出 | SQL 业务口径正确、时间数据完整、值一定是可加指标 |
| B. Schema / business metadata | 源字段定义、role、允许聚合提示、经确认的单位/指标政策 | 经精确源字段绑定后，辅助说明值的业务含义 | 仅凭 role=metric 就证明任意 join 后 SUM 合法 |
| C. Derived business meaning | 目标完成率、环比变化率、产品实付贡献率 | 在输入条件满足时，由确定性规则计算的结论 | 不是数据库直接原生返回的业务事实；不能超越输入精度和可信范围 |

另有一类必须明确：**program-derived metadata**，例如 `returned_rows=len(rows)`、SQL AST 解析出的 alias/SUM/GROUP BY。它们不是数据库原始值，也不是 LLM 推断；本设计把它们放入明确的执行统计或 Understanding 区域，并记录来源。

### 1.3 信任边界

允许的入口：实际执行 SQL、捕获时的列与值、完整的权限过滤后 SCHEMA；schema_graph 仅用于候选查找和解释，不取代 SQL 绑定。

禁止的事实入口：

- `interpretation.metric/dimension`：当前是列名包含“额/数/率/平均/目标”的 heuristic，见 [ResultBuilder.completed L95–99](D:/agent_study/askdata_studio/backend/app/workflows/result_builder.py:95)。
- `analysis/title/valid`：通常来自 LLM，见 [ResponseGenerator.finalize L41–55](D:/agent_study/askdata_studio/backend/app/querying/response_generator.py:41)。它们不赋予计算资格。
- retrieval score：语义相关性排名，不是业务数值置信度、数据质量或风险概率。
- `QueryResult.status`：当前还受 `final.valid` 影响，见 [ResultBuilder L113–115](D:/agent_study/askdata_studio/backend/app/workflows/result_builder.py:113)，不能当作单独的 SQL success。

### 1.4 总体设计决策

新增一个中间 **ResultContract**：承载执行数据及其可验证语义描述；保持 QueryResult 为面向用户的兼容展示对象。新增一个普通确定性 **Result Understanding** 组件填充语义证据，再由普通 **Business Signal Engine** 计算三个白名单信号。不新增 Agent，不增加自主工具调用循环。

```text
捕获执行事实 → ResultContract.execution
                       │
SQL + 授权SCHEMA → Result Understanding → ResultContract.understanding
                       │
                       ▼
                输入资格逐项检查
                       │
             Business Signal Engine
                       │
           SignalBatch（派生结果与证据）
                       │
             现有 ResponseGenerator 解释
                       │
          现有 ResultBuilder / QueryResult 展示
```

本设计不承诺从任意 SQL 自动理解全部业务语义。首批支持可验证的小范围 SQL 形状；遇到未知语义，普通查询可以成功，而相应 signal 返回不可计算及具体原因。

## 2. Result Contract Design

### 2.1 为什么需要中间契约

推荐新增，而不是把所有字段继续混进 Interpretation 或直接消费 QueryResult。

它有两个严格分区：

1. `execution`：数据库来源数据、表示方式、执行范围标识和结果数量。
2. `understanding`：通过 SQL 解析与受信 metadata 绑定得到的来源、粒度、口径及检查证据。

**不在 ResultContract 中放销售完成率等最终信号；不放 LLM 解释、retrieval score、工作流 steps。** 派生业务值另放 SignalBatch。这样 A/B/C 不会因为处在同一个用户结果页就混同。

### 2.2 最小结构：一份契约、两个分区

下面是接口草图，不是可运行实现。`null/unknown` 是合法状态；不能为了让对象完整而猜默认 metadata。

```text
ResultContract
├── version: "1"
├── result_id: 本次执行的稳定标识
├── execution
│   ├── database, sql, success, error
│   ├── snapshot_ref: string | null
│   ├── access_scope_ref: string
│   ├── columns: OutputColumn[]
│   │   └── id, ordinal, name, dtype, value_encoding, representation_status
│   ├── rows: JsonScalar[][]
│   ├── returned_rows: int
│   ├── total_rows: int | null
│   ├── truncated: bool | null
│   └── completeness: complete_query_output | partial_query_output | unknown
└── understanding
    ├── schema_ref: 绑定时使用的Schema版本/内容摘要
    ├── columns: ColumnUnderstanding[]
    │   └── column_id, alias, expression, resolution,
    │       lineage, role, unit, measure_ref, aggregation
    ├── row_grain: kind, key_column_ids, time_bucket, evidence_refs
    ├── scope: 实际期间/时间源字段/过滤/输出限制/总体覆盖证据
    └── checks: code, status, evidence_refs, detail
```

这是首批信号所需的最小**语义面**，不是要求每次填满所有内容。未知字段如 unit、measure_ref、scope 的覆盖证明保持未知；检查器只要求该 signal 实际依赖的证据。不建设通用 metadata catalog。

`snapshot_ref` 与 `access_scope_ref` 是执行/控制 provenance，不是 DB 单元格事实。前者未知时不能声称多次执行来自同一快照；后者引用服务端解析的授权范围，不复制令牌或允许模型自报权限。`result_id`/快照引用都不意味着本期需要实现 Repository。

### 2.3 Column Metadata 定义

| 字段 / 所在区 | 定义 | 生产者 / 证据 | 约束 |
|---|---|---|---|
| id / execution.columns | `c0/c1/...`，本结果内稳定列身份 | cursor ordinal 的确定性分配 | 不依赖名称唯一性 |
| ordinal | 输出列位置，从0开始 | cursor.description 顺序 | 与 rows 数组位置一致 |
| name | 数据库实际输出名称 | cursor.description item[0] | 可以是 alias 或表达式显示名，不当作源字段名 |
| dtype | DuckDB 输出物理类型描述，未知为null | cursor.description type_code；含类型本身携带的参数 | 不从 SCHEMA 的“数值”或 rows 样本猜 dtype；不填虚构 nullability |
| value_encoding | wire 值如何表示/解码 | 引擎显式 codec | `native_json/decimal_text/integer_text/iso_date/iso_datetime`；与 dtype 一起解释 |
| representation_status | preserved / lossy / unsupported / unknown | 经验证的driver取值路径与codec | 明确“DB→Python→wire”是否保持所声明表示；unsupported列不能进入相关signal |
| alias / understanding.columns | SQL 中显式 alias，未写AS/别名则null | 实际 SQL AST | 与 SCHEMA aliases（搜索同义词列表）完全不同 |
| expression | 已绑定的输出 SQL 表达式 | SQL AST | 保留 CAST、CASE、聚合与运算，不能只剩别名 |
| resolution | resolved / partial / unknown / unsupported | 确定性解析与校验 | 只证明已支持表达式的绑定状态，不是“业务正确率” |
| lineage | value_sources 与 dependencies | SQL scope、CTE、UNION分支、源字段绑定 | 使用 database/table/field；保留运算路径与分支，不只保存无序字段集合 |
| role | `value/status/evidence_refs`，例如metric/dimension/time/identifier/filter/unknown | 精确绑定的SCHEMA + 受限变换规则 | SUM(metric)需合法表达式；不能把任何numeric都叫metric |
| unit | `value/status/evidence_refs`；没有依据则value=null | 经批准的字段/指标政策；当前SCHEMA未提供 | 不默认CNY/元，不因两个字段都叫金额就判兼容 |
| measure_ref | 经确定性规则识别的度量政策引用或null | 源字段+表达式+过滤+时间口径匹配 | 不是LLM命名；销售额别名不自动得到此引用 |
| aggregation | 实际SQL操作及上游操作链、distinct/filter条件 | SQL AST | 区分SQL实际SUM与SCHEMA推荐sum；不默认允许二次求和 |

`lineage.value_sources` 描述贡献数值的字段，例如 paid_amount；`dependencies` 描述影响范围/分组/匹配的字段，例如 order_date、region、status、join key。只记录 paid_amount 而遗漏期间和状态，不足以复核信号。

role、unit 和 measure_ref 都是 **metadata binding**，不是 DB fact；aggregation 和 expression 是 **程序从实际 SQL 确定性提取的描述**，不是已算出的 Business Signal。

### 2.4 rows 的表示：避免在契约入口再次丢数据

建议新契约使用按 ordinal 排列的行数组，而不是以输出名称为 key 的 dict：

```json
{
  "columns": [
    {"id": "c0", "ordinal": 0, "name": "x", "dtype": "INTEGER", "value_encoding": "native_json", "representation_status": "preserved"},
    {"id": "c1", "ordinal": 1, "name": "x", "dtype": "INTEGER", "value_encoding": "native_json", "representation_status": "preserved"}
  ],
  "rows": [[1, 2]]
}
```

它能完整记录 `SELECT 1 AS x, 2 AS x`。首版兼容展示适配器要求输出名称唯一；不满足时应给受控诊断，不能在转回当前 QueryResult.rows 的 dict 时悄悄覆盖。Signal 绑定采用 column_id；遇到 SQL 内重复 alias 造成上游引用歧义，解析必须拒绝，不能靠 ordinal 猜语义。

旧结果已经变成 `{'x':2}` 时，不能通过 adapter 恢复丢掉的1；应标记 legacy/lossy，拒绝需要该值的计算。新捕获逻辑必须在当前 engine 的 L45–48 之前运行。

序列化政策：

- DECIMAL 用可无损解码的十进制字符串 + dtype/codec；可能超出跨JSON消费者安全整数范围的物理整数列用 integer_text，不能先转float再编码。codec按列一致应用，同列所有非NULL整数均用所声明编码，不能只有大值临时变字符串。
- DATE/经验证能完整表示的微秒级TIMESTAMP可以用ISO字符串，但明确codec及实际类型/时区信息；没有时区证据时不补造时区。
- DOUBLE 保持数据库的浮点语义并标识 approximate；把它格式化为两位小数或再转Decimal，不会获得原先不存在的精确货币保证。
- NULL 保持null；不自动转0。非有限浮点或当前未支持的嵌套/扩展类型，使用受控“不支持”状态，不能静默 stringify 后送进金额计算。
- Signal 运算结果的数值质量不能高于输入；`deterministic` 不等于 `exact`。

还必须承认driver取值本身的边界：本轮内存只读probe中 `TIMESTAMP_NS '2026-08-01 00:00:00.123456789'` 的type_code为TIMESTAMP_NS，DuckDB内的纳秒仍存在，但普通fetch得到Python datetime的小数部分只有123456。损失发生在 `_json_value` **之前**。首版把此类不能经已验证取值路径完整表示的类型标为unsupported/lossy，不为它设计新提取路线；相关signal不得使用。execution里的值也不能被描述为该原始值的无损副本。

当前 [Decimal→float L148–149](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:148) 与 [MCP模型 rows 定义 L25–26](D:/agent_study/askdata_studio/backend/app/mcp_runtime/schemas.py:25) 后续必须相应贯通契约；本轮不修改。

### 2.5 Result Metadata：完整性必须有两个层次

| 字段 | 精确定义 | 来源 / 未知处理 |
|---|---|---|
| row_grain | 一行表示什么；如 month×sales_region、period×product_id、global aggregate、unknown | SQL分组/投影/连接分析 + 受信键/粒度条件；不从样本名称猜 |
| returned_rows | 契约实际携带的行数 | 恒等于len(rows)，是程序派生值 |
| total_rows | **实际执行这条SQL的输出总行数**，包含它自身的LIMIT/HAVING效果 | 有耗尽证据才确认；应用截断时默认null；不是源订单数或自然语言问题的“应有总数” |
| truncated | 应用结果上限是否裁掉SQL输出 | true/false/null；null=缺少捕获证据，不等于false |
| completeness | complete_query_output / partial_query_output / unknown | 只描述SQL输出传递完整性 |
| scope.population_coverage | 完整覆盖声明的分析总体、部分、未知 | 业务窗口、授权范围、谓词、SQL限制、数据覆盖依据共同决定；独立于completeness |

保留当前最多200行的边界时，新捕获规则应明确为：

| 对同一执行fetchmany(201)得到的行数 | returned_rows | total_rows | truncated | completeness |
|---:|---:|---:|---|---|
| 0～200，确认该次读取已到输出末尾 | 实际数n | n | false | complete_query_output |
| 201 | 200 | null | true | partial_query_output |
| 旧contract、读取中断或捕获证据不可用 | 已知返回数 | null | null | unknown |
| SQL执行失败 | 通常0 | null | null | unknown；signal不得计算 |

不为凑齐total_rows默认再执行COUNT包装SQL、不自动fetch全量。重执行可能代价高、快照不同；首版没有“自动补查”这一行为。若将来确需精确总数，应作为独立、明确授权的数据获取决策，不偷偷混进Result Understanding。

具体区分：

- `SELECT ... LIMIT 100` 全返回：total_rows=100、truncated=false；但若分析要求全体订单，population_coverage仍不是complete。
- 对所有授权订单先SQL聚合成4个地区，全返回4行：total_rows=4；不表示只分析了4条订单。若时间/总体条件可证明，适合区域信号。
- SQL只返回HAVING后存活组：输出可能完整，但被过滤组已不在里面；不能把它们用于全产品份额分母。
- 空结果：可能是完整SQL的0行，也可能数据期缺失、权限/条件不匹配。空结果不是自动的零销售事实。

`scope` 至少记录：实际时间源字段、半开期间区间、规范化过滤条件、实体总体、SQL级LIMIT/OFFSET/HAVING、访问范围引用、覆盖状态与证据。两个不同月份可以有不同区间，但度量/状态/实体总体/权限口径必须一致才能比较。

数据覆盖不能仅由MIN/MAX日期证明。当前CSV覆盖固定6～8月，见 [生成器L23–51](D:/agent_study/askdata_studio/backend/app/demo_data.py:23)。生产“该月已收齐”需要受信来源/水位或业务确认；没有就unknown。首批demo可用人工批准的固定文件指纹与期间声明，但不得称它是已实现的生产水位系统。

### 2.6 最小业务政策：补充缺失定义，不补造数据

当前 [_field L9–26](D:/agent_study/askdata_studio/backend/app/database.py:9) 没有unit/currency；[paid_amount L34](D:/agent_study/askdata_studio/backend/app/database.py:34) 是实付，[order_date L36](D:/agent_study/askdata_studio/backend/app/database.py:36) 是订单创建日期；[target_amount L104](D:/agent_study/askdata_studio/backend/app/database.py:104) 没有明确“目标也以实付口径制定”。因此单靠当前SCHEMA不足以认证S1。

拟议最小办法：只为三个信号保存一份受信、版本化的**业务规则配置**，由项目/业务负责人确认，不由LLM生成；本阶段仅列出必须确认的内容：

- 实付度量的源字段、状态处理、按订单创建日归属月份；不能从“成交日期”alias改成付款日。
- 实际与目标的比较口径、单位或共同计量尺度；不默认“元”。S2/S3即便最终是比例，也需确认分子分母同量纲、同计量尺度。
- 明确期间、授权总体、current/history是否互斥、demo文件快照/数据覆盖声明。
- 目标月×地区唯一性、客户/产品主键唯一性如何取得本次可用的验证证据。
- 数值政策：接受exact还是显式approximate输入，比例舍入精度、零/负值政策。

规则配置只是有限白名单，不是全企业指标平台。规则可引用当前SCHEMA，但不能把未写明的币种、唯一性或收入确认政策伪称为SCHEMA事实。缺规则时返回 `UNIT_UNVERIFIED/MEASURE_POLICY_MISSING/...`，不生成冒充可信的数值信号。

当前demo若将来明确批准“两个金额字段使用同一演示计量尺度”，可以记录例如 `demo_amount_scale_v1` 的引用；这只是待批准政策示例，不是本报告已经获得的业务事实。未批准前，本文数值示例均是条件演示。

### 2.7 状态与不变式

首版应保证：

1. rows长度等于returned_rows；每行列数等于columns长度；column_id/ordinal唯一。
2. 截断为true时total_rows未知或有独立可靠计数，不允许随手填returned_rows；unknown字段往返不变成默认false/0。
3. 执行失败不计算signal；语义解析不支持不伪装成SQL执行失败。
4. 源字段绑定、Schema版本、规则引用均可回到本次执行SQL；metadata不可从LLM文本回填。
5. 各signal只依据自身必需的checks；某一列不支持，不必否定完全独立的可验证列，但不得绕过它实际依赖的检查。
6. 未知unit/覆盖/lineage不赋予任何“高置信度”分数；结果是明确资格状态与原因。
7. 所有证据引用可解析到本次契约或随批次携带的证据；本期不依赖尚未建设的Repository。

### 2.8 最小迁移边界（设计，不实施）

新契约必须经过整个现有通道，不能只在DuckDB出口添字段：

```text
引擎事实捕获
 → SqlExecution关联/携带execution contract
 → DatabaseQueryResult结构化携带同一versioned contract
 → MCP structured_content
 → LocalMcpClient校验/解码
 → state.mcp_execution
 → Workflow取回完整contract，禁止再次只复制原五字段
 → Understanding填入独立语义分区
```

首版推荐让当前数据库MCP结果**增加一个版本化execution contract载荷**，原字段保留作兼容展示投影；它们必须由同一份事实派生，不能成为两套互相矛盾的事实源。业务语义在Workflow中加入，不要求DuckDB Tool理解销售业务。

关键显式复制点是 [数据库Tool L35–43](D:/agent_study/askdata_studio/backend/app/mcp_runtime/tools/database_tools.py:35) 和 [Workflow L296–302](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:296)。如果不处理第二处，MCP里已有的新信息仍会再次丢掉。

旧MCP结果缺contract时可继续展示，但metadata/completeness未知；信号资格不足时跳过，不从日志、Interpretation或旧rows猜补成“可信新结果”。

## 3. Result Understanding Layer

### 3.1 输入与输出

输入：ResultContract.execution（**实际执行SQL**、有序输出列、原语义保真的值与元数据）、服务端权限范围内完整SCHEMA、可选schema_graph、已批准的有限规则配置。

输出：ResultContract.understanding，包括列来源/操作、粒度、实际分析范围、可审阅证据与未解决问题。

组件职责是确定性解析与匹配，不是让另一个LLM判断字段“看起来像什么”。当前已经使用sqlglot解析SQL，见 [DuckDbEngine._validate_sql L81–86](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:81)；设计可沿用该依赖，但权限校验的平面表名扫描不是完整lineage resolver，不能直接当成作用域解析器。

### 3.2 实际处理顺序

| 步骤 | 操作与证据 | 不满足时 |
|---|---|---|
| 1 锚定执行 | 校验contract版本、SQL成功、列顺序/值codec，取实际sql而非LLM原始decision文本 | 拒绝对应计算，保留可展示结果 |
| 2 建立SQL作用域 | 分别处理查询块、表别名、非递归CTE、显式子查询投影 | 循环/不支持作用域标unsupported |
| 3 对齐输出列 | 顶层投影ordinal与cursor列ordinal对应，识别显式alias | 列数不符或有无法展开输出时unknown；不用名称相似度修补 |
| 4 绑定源字段 | 限定表/列引用及表别名→授权SCHEMA；未限定列引用必须在当前scope唯一解析 | 多个region候选时ambiguous，不任挑graph命中字段 |
| 5 追溯表达式 | 记录SUM/CAST/CASE等操作，穿过CTE和UNION分支；区分值来源与过滤/分组依赖 | 只解析一部分时partial，不能声称全lineage |
| 6 绑定metadata | 根据精确字段引用与有限变换规则绑定role/unit/measure policy | 同义词只能辅助展示；无证据保持unknown |
| 7 确认grain/scope | 分析GROUP BY、时间bucket、WHERE、JOIN、LIMIT/HAVING与源覆盖 | 无法证明join粒度或总体范围时相关checks不通过 |
| 8 评估signal资格 | 按S1/S2/S3的必需证据做确定性匹配 | 输出明确缺失原因，不请LLM补语义 |

实际SQL可引用未被召回graph选中的合法字段，因此必须查完整**授权SCHEMA**。graph是缩小候选的帮助，不是源字段白名单之外的推断捷径，也不能覆盖SQL实际引用。

### 3.3 关键例子：SUM(paid_amount) AS sales_amount

实际SQL：

```sql
SELECT SUM(paid_amount) AS sales_amount
FROM orders_current;
```

本轮只读检查当前DuckDB输出：`('sales_amount', DOUBLE, None, None, None, None, None)`。因此本例不能根据“金额”擅自把输出dtype标成DECIMAL。

拟议元数据分开记录为：

```json
{
  "output_column": {
    "id": "c0",
    "ordinal": 0,
    "name": "sales_amount",
    "dtype": "DOUBLE",
    "value_encoding": "native_json",
    "representation_status": "preserved"
  },
  "column_understanding": {
    "column_id": "c0",
    "alias": "sales_amount",
    "expression": "SUM(orders_current.paid_amount)",
    "resolution": "resolved",
    "lineage": {
      "value_sources": [
        {"database": "askdata_mock", "table": "orders_current", "field": "paid_amount"}
      ],
      "dependencies": []
    },
    "role": {
      "value": "metric",
      "status": "resolved",
      "evidence_refs": ["SCHEMA:orders_current.paid_amount", "RULE:sum-of-bound-metric"]
    },
    "unit": {"value": null, "status": "unknown", "evidence_refs": []},
    "measure_ref": null,
    "aggregation": {
      "operations": [{"op": "SUM", "distinct": false, "filter": null}],
      "reaggregation": "not_assumed"
    }
  }
}
```

其中 `RULE:sum-of-bound-metric` 是拟议的有限推导规则引用，须与规则文本一起存在，不能只是一个伪造证据标签。`resolution=resolved` 仅表示本例的源表达式能解析；unit/measure_ref仍未知，所以不能仅凭这一状态运行任意signal。

逐步理解：

1. `sales_amount` 是输出名字/显式alias，不是源Schema字段。
2. 源字段唯一解析为 `askdata_mock.orders_current.paid_amount`，由实际FROM scope确定。
3. 聚合SUM来自SQL AST；SCHEMA的aggregation=sum仅作为兼容性提示，不替代实际SQL。
4. 输出dtype来自cursor；源列类型、聚合结果类型不能混用。
5. 没有GROUP BY，本例是global aggregate，key_column_ids为空，不是一行一个地区。
6. 本例没有时间谓词、region或product键，不能凭“当前订单”名称自动赋予月×地区/月×产品grain；不符合S1/S2/S3的完整输入形状。

因此“解决输出名≠来源”并不意味着“所有业务语义已解决”。它解决的是可检查的绑定第一步。

### 3.4 CTE、UNION、COUNT 和聚合的受限传播

**CTE必须回溯到真实源字段：**

```sql
WITH s AS (
    SELECT region, SUM(paid_amount) AS actual
    FROM orders_current
    GROUP BY region
)
SELECT region, actual FROM s;
```

外层`actual`的值来源不是永久业务表`s.actual`，而是内层SUM。应保留 `PROJECT(s.actual) ← SUM(orders_current.paid_amount)` 的操作路径与内层region粒度。不能因为外层只是SELECT就丢失上游聚合信息。

**UNION ALL必须保留两支：** 同一输出位置同时来源于current和history；输出名来自哪一支不能决定实际来源只剩那一支。支持显式同列序、同语义的UNION ALL；保留branch路径和每支过滤条件，再确认时间覆盖互斥/去重政策。当前CSV订单ID无重叠是快照事实，不是永久保证。

**COUNT不可粗暴当order_id：** COUNT(*)是经过FROM/JOIN/WHERE的行集合计数；COUNT(col)受NULL影响；COUNT(DISTINCT col)有去重口径。它们的lineage和聚合描述不能合并成同一“订单数”。

**聚合不能随意再次聚合：** 内层AVG外层AVG未必是总体平均；预聚合SUM只有在输入组互斥且覆盖完整时才可再次求和；ratio通常不可相加。即使role=metric，也保持reaggregation=not_assumed，除非某条白名单规则证明合法。

### 3.5 row_grain 与 join 安全是独立检查

SQL `GROUP BY month, region`说明“一行一组month/region”；要进一步认定“每组是正确月地区实付”，还需源字段语义、时间口径和连接不放大事实的证据。

首版可识别：

- 无join明细：以受信源主键为候选grain；若主键未投影，不能让后续误以为可按该键可靠对齐。
- 普通GROUP BY：记录分组表达式；首批signal要求其必要分组键都显式投影，能映射到column_id。
- 无GROUP BY的整体聚合：global aggregate；HAVING可使其返回零行。
- 预聚合结果等值连接：两边在连接键上已证明唯一，才传播合并grain。

当前 [RELATIONS L140–155](D:/agent_study/askdata_studio/backend/app/database.py:140) 只结构化定义订单region→目标region，月份放description。S1必须验证月+地区，不接受“图里有join路径”作为充分证明。

首版S1接受的形状是：订单先按月地区聚合；目标在同月地区唯一；最后一对一连接。**拒绝把原始订单与目标直接join后SUM(target_amount)当安全目标值**。最终行数看起来只有4行也不证明聚合前没有倍增。

唯一性证据必须来自这次执行对应的可信约束、受信固定数据集验证记录，或已有同快照核验结果。当前SCHEMA只给target_id，不保证month×region唯一；普通SELECT中 `MAX(target_amount)`、`SUM(target_amount)` 或目标值看起来一致，不能作为源目标没有重复的证明。首版不在Understanding中自动查询数据库补证明。

### 3.6 MVP 支持边界

| 输入形状 | 首版处理 |
|---|---|
| 显式列、单表、唯一可解析别名 | 支持绑定 |
| 普通GROUP BY、SUM、COUNT、AVG、MIN、MAX | 支持记录实际操作；只有符合signal政策的操作才取得该signal资格 |
| 简单CAST、批准的日期月分组表达式 | 支持记录变换；日期字符串的物理类型不因“按月分组”变成DATE |
| 非递归CTE、有限层显式投影子查询 | 在实现的scope解析范围内支持，限制深度/形状；不支持则明确降级 |
| 语义一致、显式列序的UNION ALL | 保留分支；额外要求覆盖/重复政策证据 |
| 已证明键与基数的受限等值JOIN | 支持；SCHEMA关系存在但基数未知不够 |
| 显式产品ID查询，产品名称需额外join | 名称仅展示；无产品表权限时可用ID，不能越权补名字 |
| 模糊源字段、复杂CASE/运算、未知UDF | 可记录部分依赖，但不自动给signal可信身份 |
| 递归/lateral、窗口、UNION DISTINCT、GROUPING SETS/ROLLUP、复杂OR/NATURAL/CROSS/M:N JOIN | 首版不自动认证业务grain与signal资格 |
| 已有LIMIT/Top-K/HAVING | 记录其作用位置；首版若影响所需总体且无完整独立依据，则不计算相关signal |

限制的是**自动语义认证**，不是扩大现有SQL执行禁止范围；允许执行的复杂查询仍可返回数据。无需为了首批三个信号实现通用SQL血缘平台。

### 3.7 “可信业务上下文”的定义

不是拼接一段更长的Schema提示词，而是这组结构化、可验证的判断：

```text
该列来自哪个已执行表达式？        → lineage + expression
该值按什么粒度产生？            → row_grain + join checks
度量含义/单位来自谁？            → schema绑定 + 批准规则引用
统计了谁、哪个期间、什么过滤？    → scope
全部所需数据都在吗？            → 输出完整性 + 总体覆盖证据
这条具体signal的前提是否满足？   → 每项资格检查结果
```

证据不足时输出unknown或不可计算，不输出一个看似精确的confidence分数。只有在支持范围内按规则通过所需检查，才称“该signal的输入已验证”；不宣称已证明任意SQL满足用户全部业务意图。

## 4. Business Signal Engine Design

### 4.1 首版只计算三个信号，不承担数据获取

本阶段编号固定为：**S1 月度区域目标完成率；S2 区域销售变化；S3 产品实付贡献**。S3不是baseline候选表中的客户线索编号。

Engine是普通确定性函数/组件：输入一份当前ResultContract和已批准的三条规则，输出SignalBatch；没有LLM、没有自主MCP调用、没有额外SQL重试，也不从历史QueryResult或用户拖入表格拼接“新事实”。

首版支持的输入形状：

| Signal | 一份ResultContract必须提供的形状 |
|---|---|
| S1 | 月×销售地区，一行包含已验证的实际值与目标值；来源为订单预聚合与唯一目标的安全匹配 |
| S2 | 期间×销售地区，一行一个期间地区实付；同一结果含明确基期与当前期 |
| S3 | 单一明确期间/范围内，完整的产品ID→实付汇总集合；名称/品类可选 |

例如用户只查询本月四个地区销售额：可以保留结果，但没有目标、基期和产品维度，不能自动产生全部三个信号；对应记录 `REQUIRED_INPUT_MISSING`。以后由已有查询路径在用户明确的问题/范围内取得所需数据，不要求新增复杂Agent。本期不设计自动改写SQL补数据的机制。

### 4.2 共用输入检查与数值规则

对每个信号依次检查：

1. execution.success为true；codec可解码，必要值没有名称覆盖/有损legacy问题。
2. 必需列有唯一column_id与完整源表达式绑定；measure/unit政策可匹配。
3. 实际grain、join基数、键唯一性满足该规则；不能只看最终行数。
4. SQL输出完整，且覆盖该规则声明的总体；期间覆盖与权限范围有证据。
5. 输入NULL、缺组、零/负分母符合明确政策；没有政策则不可计算。
6. 计算后用程序检查公式、有限数值、分母/范围一致性；证据随输出保留。

首版金额/比例规则采用非负实付与正分母；负金额、负基数不套用普通增长/贡献定义。NULL不自动当0。省略组只有在总体完整、实体域和“空组=0”政策都已确认时才可补0；首版无证明时直接跳过该实体。

建议比例内值为ratio，非百分数字符串：例如 `-0.282948`，展示时才变成`-28.29%`。计算保留足够精度，最终ratio示例统一6位小数、HALF_EVEN；展示百分比再格式化为2位。该舍入规则是设计决策，不是当前已有实现。达标与变化方向用未舍入的A与T、C−P判断，不能依据展示ratio；例如0.9999996会舍入显示为1.000000，却不能因此判定达标。

DECIMAL/整数可使用确定性十进制运算，但工作精度必须覆盖受支持输入dtype、聚合规模和操作；不能依赖Python Decimal默认28位精度处理所有DuckDB DECIMAL。若无法保证该范围，返回UNSUPPORTED_NUMERIC_POLICY。只在最后按既定规则量化。DOUBLE输入只能在规则明确允许approximate时计算，并保留numeric_quality=approximate。对现有已float化值调用Decimal不算精度修复。若未来标注精确输入，采用明确含义如exact_input_rounded_output，不把量化后的比率说成未舍入的数学精确商；规则版本必须能查到舍入政策。

### 4.3 共用输出与Evidence

```text
SignalBatch
├── version
├── result_id
├── signals: ComputedSignal[]
│   └── signal_id, signal_type, rule_version,
│       entity, period, scope_ref,
│       value, value_unit, numeric_quality,
│       inputs, supporting_values, evidence_refs
├── skipped: SignalNotComputed[]
│   └── signal_type, entity/period（若可确定）,
│       reason_codes, missing_requirements
└── evidence: EvidenceRecord[]
    └── evidence_id, result_id, snapshot_ref, access_scope_ref,
        column_ids, row_keys, source_fields, expression,
        scope_ref, schema_ref, policy_refs, check_refs
```

`signals`只放已满足输入条件并算出的数值；`skipped`不是0值信号。某实体不可计算不影响其他已通过实体，但总体统计不能忽略缺失实体后冒充全量。首版三个比率型signal在分母不合法时跳过该信号，原可信金额仍保留在ResultContract，不返回虚假的0%、100%或Infinity。

Evidence至少能回答：用了哪次执行、哪些行/列、什么表达式和源字段、什么期间与过滤范围、哪些业务政策、哪些验证结果。**仅列 `orders_current.paid_amount` 与 `orders_history.paid_amount` 不够**，它不能定位实际输入值和比较期间。

证据可在批次中内嵌，或引用同次ResultContract内可解析的对象；首次不需要建设Repository。单独导出SignalBatch时，应一并带出解引用所需的契约/证据快照，不能保留无从打开的result_id。数据快照指纹用于识别数据，不自动证明多文件读取原子一致或业务上已收齐；相关保证未知时照实标未知。

### 4.4 S1：MONTHLY_REGIONAL_TARGET_ATTAINMENT

**输入与粒度。**

- 订单：覆盖目标月份的 `paid_amount/order_date/region`。
- 目标：`sales_targets.target_month/region/target_amount`；可选 `owner_name`。
- 每行grain=`自然月 × 订单销售地区`；实际与目标同月同地区，同度量口径与计量尺度。
- 源码定义依据：[订单字段 L31–36](D:/agent_study/askdata_studio/backend/app/database.py:31)、[目标表 L92–105](D:/agent_study/askdata_studio/backend/app/database.py:92)、[目标关系 L140–155](D:/agent_study/askdata_studio/backend/app/database.py:140)。

**计算。** 订单先聚合得到A，目标唯一得到T，进行一对一匹配；T>0时：完成率=A/T，差额=A−T。使用未舍入输入比较A≥T，才可表述“按该口径达到目标”；A<T只能说“尚未达到”，不自动判进度落后或经营异常。近似输入的判断也只针对已声明近似口径，不获得严格财务保证。

**边界条件。** 缺目标/重复目标无合并政策、未按月对齐、源目标被订单join重复、单位/目标实付口径不明、期间覆盖未知、应用截断或必要NULL → 跳过；T≤0 → 不生成普通完成率。首版只认证有完整覆盖依据的已结束月，不用固定8月CSV自动回答9月“本月目标”。

**条件示例输出。** 下列数值来自baseline的华北8月样例，假设已批准相关demo口径并取得新contract的全部证据；不是当前系统已经产出的signal。此处approximate是保守质量标注，不宣称原始货币精确性：

```json
{
  "signal_id": "demo-s1-huabei-202608",
  "signal_type": "MONTHLY_REGIONAL_TARGET_ATTAINMENT",
  "rule_version": "1",
  "entity": {"type": "sales_region", "key": "华北"},
  "period": {"start": "2026-08-01", "end_exclusive": "2026-09-01"},
  "scope_ref": "demo-scope-aug-sales",
  "value": "2.111902",
  "value_unit": "ratio",
  "numeric_quality": "approximate",
  "inputs": {"actual": "3379043.36", "target": "1600000.00"},
  "supporting_values": {"amount_delta": "1779043.36", "amount_unit_ref": "approved-demo-amount-scale"},
  "evidence_refs": ["E-S1-ACTUAL", "E-S1-TARGET", "E-S1-COMPARABILITY"]
}
```

上述Evidence在真实批次中必须实际保存：

| Evidence ID | 必须能解析到的内容 |
|---|---|
| E-S1-ACTUAL | 输入契约对应实际列/华北8月行；SUM(orders_current.paid_amount)及实际CAST/状态过滤；order_date时间边界、订单region分组、源快照 |
| E-S1-TARGET | 同一输入契约目标列/匹配行；sales_targets.target_amount、target_month、region；月地区唯一性证据与连接条件 |
| E-S1-COMPARABILITY | 相同单位/计量尺度、实付与目标口径批准引用；输入完整、月份覆盖、权限与无fanout检查 |

这里的英文Evidence ID只是设计示例名称；真实系统不允许只输出ID而缺少记录。LLM可将2.111902解释为约211.19%，但不能据此制造“区域负责人优秀”等评价。

### 4.5 S2：SALES_CHANGE

**输入与粒度。** 同一份结果中两期的订单销售region与实付聚合，grain=`period × sales_region`。来源是覆盖各期间的current/history之明确同列合并，通常使用 order_date/region/paid_amount；不能把客户region替代订单region。[表时间说明 L43–61](D:/agent_study/askdata_studio/backend/app/database.py:43)。

**计算。** 对同地区当前值C、基期P：absolute_change=C−P；P>0时change_ratio=(C−P)/P。方向由正/零/负确定，不需要LLM。月环比表示相邻自然月的总量比较，并非日均调整或同比。

**边界条件。** 两期必须同度量/状态/单位/实体总体/权限政策；月份覆盖完整且可比；current/history没有未经处理的重叠。P≤0或缺期/NULL/语义不同 → 跳过比率，不输出无限增长。缺历史权限不补0；[demo_current_sales L66–71](D:/agent_study/askdata_studio/backend/app/security/access_control.py:66) 不可读history，因此7→8月比较可能不具备输入。

首版若缺某地区某月行，不自动判销售为0；需要完整授权总体与明确空组政策才可补齐。两张事实表不能按客户/产品join后求和代替UNION。不同月份全部结果即使各自完整，也不能不核对期间/总体直接相除。

**条件示例输出。**

```json
{
  "signal_id": "demo-s2-huabei-202607-202608",
  "signal_type": "SALES_CHANGE",
  "rule_version": "1",
  "entity": {"type": "sales_region", "key": "华北"},
  "period": {
    "current": {"start": "2026-08-01", "end_exclusive": "2026-09-01"},
    "previous": {"start": "2026-07-01", "end_exclusive": "2026-08-01"}
  },
  "scope_ref": "demo-scope-jul-aug-sales",
  "value": "-0.282948",
  "value_unit": "ratio",
  "numeric_quality": "approximate",
  "inputs": {"current": "3379043.36", "previous": "4712413.08"},
  "supporting_values": {"absolute_change": "-1333369.72", "amount_unit_ref": "approved-demo-amount-scale"},
  "evidence_refs": ["E-S2-CURRENT", "E-S2-PREVIOUS", "E-S2-COMPARABLE-SCOPE"]
}
```

- E-S2-CURRENT：当前期输入行/列、订单当前表paid_amount表达式、order_date范围与region绑定。
- E-S2-PREVIOUS：历史表相应字段、基期输入行/列、相同状态与金额政策。
- E-S2-COMPARABLE-SCOPE：UNION分支、数据覆盖互斥证据、同权限/总体/单位/度量、输入完整和缺组政策。

LLM允许的解释：“按已确认的订单创建月份实付口径，华北8月较7月下降约28.29%。”不允许把信号写成“华北销售异常下降”“客户流失导致下降”；首版没有异常阈值或根因证据。

### 4.6 S3：PRODUCT_CONTRIBUTION

**输入与粒度。** 一个明确期间/授权总体中完整的 `product_id → SUM(paid_amount)` 集合；grain=`period × product_id`。可选从products精确关联product_name/category，仅用于展示。来源依据：[paid_amount/product_id L34–38](D:/agent_study/askdata_studio/backend/app/database.py:34)、[products L78–91](D:/agent_study/askdata_studio/backend/app/database.py:78)、[产品关系 L126–139](D:/agent_study/askdata_studio/backend/app/database.py:126)。

**计算。** A_i为产品实付，T=完整合格产品集合的ΣA_i；T>0时contribution_ratio=A_i/T。全部份额计算完成后，展示层才可按金额降序选择Top N；相同金额以product_id作为稳定展示排序键，不暗示业务高低差别。

**边界条件。** 首版要求全产品汇总集合在同一contract中完整返回；现有12产品适用，但不是永久12产品上限保证。输入已有Top-K/LIMIT/HAVING过滤、截断、未知遗漏组或未知产品join倍增 → 跳过全总体贡献。T≤0、必要NULL、存在未定义的负金额 → 跳过普通非负份额。不能把Top-K金额之和充作全公司分母。

先只支持完整集合方案；“任意Top-K输入 + 另一次查询的分母”涉及范围/快照对齐，不纳入首版。即便将来支持独立分母，也必须证明同指标/期间/权限/过滤母集。

身份使用product_id，不用可能重名的product_name。产品名称/品类来自当前目录，不伪称历史维度快照；无products权限时可计算已授权订单中的产品ID级贡献，但不能偷偷读取名称。措辞是“所声明授权范围内的实付金额贡献”，不是“件数/利润贡献”或未证明的公司整体份额。

**条件示例输出。**

```json
{
  "signal_id": "demo-s3-product102-202608",
  "signal_type": "PRODUCT_CONTRIBUTION",
  "rule_version": "1",
  "entity": {"type": "product", "key": "102"},
  "period": {"start": "2026-08-01", "end_exclusive": "2026-09-01"},
  "scope_ref": "demo-scope-aug-all-authorized-products",
  "value": "0.110199",
  "value_unit": "ratio",
  "numeric_quality": "approximate",
  "inputs": {"product_amount": "1725561.53", "population_amount": "15658626.69"},
  "supporting_values": {"amount_unit_ref": "approved-demo-amount-scale"},
  "evidence_refs": ["E-S3-PRODUCT-AMOUNT", "E-S3-FULL-POPULATION"]
}
```

- E-S3-PRODUCT-AMOUNT：产品102的契约行/值列、orders_current.product_id与paid_amount、实际SUM表达式、日期/状态过滤。
- E-S3-FULL-POPULATION：**所有产品分组行**或其完整可解析引用、ΣA_i表达式、同范围/单位、未截断且无提前Top-K/HAVING、覆盖与合法join证据。

LLM可解释“产品102在该范围8月实付金额中贡献约11.02%”，不能把该比例解释为销量占比。

### 4.7 不计算也是结构化结果

示例：只有本月区域销售，既没有历史期，也没有可信目标口径：

```json
{
  "version": "1",
  "result_id": "example-result",
  "signals": [],
  "skipped": [
    {
      "signal_type": "MONTHLY_REGIONAL_TARGET_ATTAINMENT",
      "reason_codes": ["REQUIRED_INPUT_MISSING", "MEASURE_POLICY_MISSING"],
      "missing_requirements": ["同月地区目标值", "实际与目标可比口径"]
    },
    {
      "signal_type": "SALES_CHANGE",
      "reason_codes": ["REQUIRED_INPUT_MISSING"],
      "missing_requirements": ["同口径基期地区实付"]
    }
  ],
  "evidence": []
}
```

其他稳定原因码可限于：`LINEAGE_UNRESOLVED`、`GRAIN_UNVERIFIED`、`INPUT_TRUNCATED`、`POPULATION_INCOMPLETE`、`COVERAGE_UNKNOWN`、`UNIT_UNVERIFIED`、`PERIOD_NOT_COMPARABLE`、`INVALID_DENOMINATOR`、`UNSUPPORTED_NUMERIC_POLICY`、`ACCESS_SCOPE_INSUFFICIENT`。它们是可读诊断，不是新的Agent决策标签。

所有金额示例引用baseline中同一固定文件快照的数值，舍入比率本轮已只读复算。示例中“批准的计量尺度/完整性/规则”是**未来完成验证后的前提**，并不代表当前SCHEMA已经提供这些保证，也没有在本轮运行真正的Business Signal Engine。

## 5. Integration Point

### 5.1 Option A / B / C 比较

| 位置 | 在AskData中的对应点 | 优点 | 主要问题 | 设计结论 |
|---|---|---|---|---|
| A. DuckDB后 | [DuckDbEngine.execute L42–49](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:42)，cursor仍在时 | 能取得真正dtype、ordinal、原值、fetch/截断证据 | 如果这里计算销售信号，会把业务规则耦合进通用执行器；还缺Workflow声明的业务上下文 | **必需的事实捕获点**，只捕获，不放Signal规则 |
| B1. SqlExecution后、QueryResult前 | [Workflow重建 L296–302](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:296) 附近 | 可形成统一中间contract，脱离MCP具体实现 | 只消费现有五字段仍太晚，无法恢复上游丢失信息 | 作为完整contract接收/校验位置，必须配合A |
| B2. QueryResult后 | [ResultBuilder输出 L111–138](D:/agent_study/askdata_studio/backend/app/workflows/result_builder.py:111) 之后 | 接口容易拿到，现成有rows | 已混入heuristic/LLM/control且字段损失；诱使从interpretation/log补语义 | **不作为Engine输入位置** |
| C. ResponseGenerator前 | [Workflow执行成功分支 L337之后、L341之前](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:337) | 已有真实执行、Schema及访问范围；信号先确定性计算，LLM只解释 | 要保证从MCP一直贯通新contract；不能继续只重建五字段 | **推荐Understanding与Engine的逻辑集成点** |

最终选择不是把A与C互斥二选一，而是 **A捕获不可重建事实，C完成语义验证与确定性信号计算**。B是契约的传输/适配边界；QueryResult仍为展示出口，不反向成为事实源。

### 5.2 与真实执行顺序的对应

当前真实代码：[QueryWorkflow._execute_single_database L337–355](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:337)：

```python
if not execution.success:
    result = ResultBuilder.failed(state, execution, log)
    return {"execution_log": log, "tool_calls": [call], "result": result.model_dump(mode="json")}
try:
    final = self.response_generator.finalize(
        state["standalone_query"], execution, state["schema_context"],
        state.get("analysis_context", ""),
    )
...
result = ResultBuilder.completed(state, [execution], execution, final, [call], log)
```

拟议逻辑顺序（不是已存在的函数名或本次patch）：

```text
MCP回传新执行契约
  → Workflow严格验证/解码，保留execution事实
  → if SQL失败：既有失败结果；不计算signal
  → Result Understanding（SQL + 授权SCHEMA + 受信规则）
  → Business Signal Engine（一次确定性调用）
  → 得到SignalBatch：已计算signals + skipped原因 + evidence
  → ResponseGenerator：接收已核验信号与执行范围，负责自然语言
  → ResultBuilder：将执行展示投影、SignalBatch、解释分开封装
  → QueryResult/API/UI
```

首版可以作为已有节点内的普通组件调用，不必新增LangGraph节点，更不需要新增“理解Agent/信号Agent/审核Agent”三重循环。

### 5.3 各组件责任边界

| 组件 | 未来所需变化范围（只设计） | 明确不做 |
|---|---|---|
| DuckDbEngine / SqlExecution承载 | 捕获物理元数据、完整性、稳定列身份与codec | 不判断客户风险，不从中文列名识别指标 |
| 数据库Tool / DatabaseQueryResult | 传递版本化execution payload；旧字段由同源兼容投影产生 | 不把row_count改名后冒充total_rows |
| MCP Client / Workflow state | 校验载荷版本、保持未知/数值codec/元数据贯通 | 不只在diagnostic trace里留完整数据，再用残缺对象计算 |
| Result Understanding | SQL来源解析、Schema/政策绑定、grain/scope资格证明 | 不访问LLM，不自动查库补证据，不负责SQL是否回答用户全部意图 |
| Business Signal Engine | 三条规则、边界处理、派生值和证据 | 不生成SQL、不扩权限、不从analysis提取事实、不做根因 |
| ResponseGenerator | 基于已计算值和证据组织说明，未知时说明限制 | 不生成/修正canonical signal数值、单位、阈值或confidence |
| ResultBuilder / QueryResult | 显示所需投影；可新增独立的可选business_signals: SignalBatch作为输出扩展 | 不把Signal塞入interpretation后再让下游当事实；QueryResult不是Engine输入 |

最后一项是拟议的兼容API扩展，不是当前 [QueryResult L62–83](D:/agent_study/askdata_studio/backend/app/models.py:62) 已有字段。ResultContract保留独立来源身份，SignalBatch是确定性派生结果；API即使同时携带两类数据与文本，也不能让下游把它们混成同一种事实。

### 5.4 LLM 接入必须满足的约束

当前 [ResponseGenerator L45–47](D:/agent_study/askdata_studio/backend/app/querying/response_generator.py:45) 看SQL、columns、前N rows与上下文；[初始化 L22](D:/agent_study/askdata_studio/backend/app/querying/response_generator.py:22) 取配置行数，baseline实测为50。未来不能让Engine从这个50行文本样本计算信号。

LLM应额外收到：已计算signals、比率表示/展示规则、精确范围、关键证据、不可计算原因。可以压缩解释上下文，但**Signal计算所用的完整输入和证据不能跟着Prompt采样丢掉**。

生成文本依然是LLM产物；即使Prompt要求“不改数字、不猜异常”，也不是硬保证。因此canonical值直接来自SignalBatch，LLM返回文本不得覆盖它。UI/API可直接展示canonical指标，说明文本单独标识。首版不声称已实现对每一句自然语言的完备事实证明。

对于 `valid`：

- SQL执行是否成功由execution.success决定。
- 某信号是否可计算由确定性checks决定。
- `final.valid`最多是模型对“本次结果能否回答问题”的意见，不能修改前两者，也不是业务置信度。

若模型认为SQL没回答用户问题，可保留这个提示；已计算的信号只声称“关于实际执行范围的事实”，不能因此自动声称用户意图已全部满足。任何可信语义/数据检查失败仍应使对应信号不可计算，不能用LLM同意来豁免。

### 5.5 降级与错误行为

| 情况 | 数据查询结果 | SignalBatch | LLM说明 |
|---|---|---|---|
| SQL执行失败 | 返回执行错误 | 不计算 | 不能把失败当空业务总体 |
| SQL成功，legacy/metadata未知 | 保留可安全展示数据 | 相应规则skipped | 解释缺少哪类证据，不填造值 |
| SQL成功，SQL形状不支持Understanding | 保留数据 | UNSUPPORTED/LINEAGE_UNRESOLVED等 | 可以描述表格，不升级为确定性信号 |
| 语义通过，但零分母/缺必要组 | 保留输入金额 | 对应比率skipped | 明确不可计算，不输出0%替代 |
| 信号成功，说明器异常 | 保留execution与signals | 不丢弃已验证signal | 返回受控说明失败文案 |
| 用户无所需历史/目标权限 | 不额外获取数据 | ACCESS_SCOPE_INSUFFICIENT或缺输入 | 不能说明“该地区上期为0” |

当前对PipelineStageError已有保留成功SQL数据的fallback，见 [Workflow L345–353](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:345)；但合法JSON非object和`bool("false")`问题仍在 [chat_json L41–53](D:/agent_study/askdata_studio/backend/app/model_client.py:41)、[ResponseGenerator L52–58](D:/agent_study/askdata_studio/backend/app/querying/response_generator.py:52)。下一阶段接入必须把这些边界纳入受控处理，不能假设原fallback覆盖所有LLM失败；本轮不修复。

## 6. Scope Boundary

### 6.1 当前数据不足以直接输出的结论

| 禁止直接输出 | 当前缺少什么 | 现有字段为什么不能替代 |
|---|---|---|
| 客户流失 | 客户生命周期、活跃/终止定义、足够观察期、经批准的流失规则/标签 | 两期实付下降、一个月没订单只能形成线索；customer_level是分层，不是风险事实 |
| 信用风险 / 违约 / 逾期 | 应收余额、到期日、账期、合同、偿付记录与风险定义 | order_amount不是应收账款余额；取消/退款状态不等于信用事件 |
| 利润 / 毛利分析 | 成本、采购价、费用、结算口径等 | paid_amount−order_amount不是利润；quantity也不存在 |
| 根因分析 | 支持因果的活动、定价、渠道、外部因素等证据与检验设计 | 金额下降或贡献变化是描述性比较，不证明下降原因 |
| 退款金额趋势 | refund_amount、refund_date、退款事件历史/净额规则 | status只有订单快照；order_date是创建日期，不能代替退款日期 |
| 销量件数 / 件单价 | quantity、计量单位、订单行模型 | order_id计数是订单数，不是销售件数 |

依据：[完整订单字段 L29–39](D:/agent_study/askdata_studio/backend/app/database.py:29)、[客户/产品/目标字段 L63–107](D:/agent_study/askdata_studio/backend/app/database.py:63)。[demo _orders L133–150](D:/agent_study/askdata_studio/backend/app/demo_data.py:133) 在非已支付状态把paid_amount设为0，仍未提供退款时间/金额事件。缺原始数据时，新增unit/role等metadata或让LLM解释不能补齐计算能力。

同样不在首版生成“异常”“预警”“高风险”“优秀区域”等业务评级。首版三个信号只有可复算值、明确范围和证据；任何未来评级需要独立、明确的业务阈值与用途。

### 6.2 明确不建设的东西

- 不建设通用BI/OLAP平台、全指标目录、企业级语义建模语言或通用SQL血缘平台。
- 不新增复杂Agent、自动补查/SQL自修循环、多数据库联邦计算。
- 不实现Repository、历史结果任意Derive、跨会话/跨权限自动合并数据。
- 不重写现有Schema Retrieval、MCP协议或整个Workflow；只设计必要的契约贯通与已有节点内的确定性组件。
- 不把所有查询都强迫变成三个信号；输入不适用时只保留普通查询结果和清晰的skipped原因。
- 不通过“Schema有该字段”宣称输出已经有lineage，不通过“LLM valid=True”宣称数据资格已经通过。

### 6.3 下一阶段的最小实施顺序与停点

这是后续获得实施授权后的建议顺序，本轮不执行：

| 小阶段 | 产出 | 达到什么才进入下一步 |
|---|---|---|
| 1 事实契约 | 捕获点、codec、dtype、行身份、完整性与执行来源，贯通MCP/state | 往返不丢值/元数据；未知保持未知；旧结果不自动升级 |
| 2 受限Understanding | 少量SQL形状的列绑定、grain/scope、unit/measure政策引用与checks | 支持用例能证明来源；歧义/不支持输入可控拒绝，不猜补 |
| 3 三条Signal规则 | S1/S2/S3，统一证据与skipped结构 | 固定fixture与边界用例可复算；缺单位/覆盖/权限不计算 |
| 4 既有Agent集成 | 在finalize前调用组件，解释与canonical信号分离 | LLM失败/误判不能覆盖计算结果；缺输入无自动补查 |

不需要同时实现所有复杂SQL、所有类型和所有业务指标。先用现有固定demo、经批准的明确口径覆盖三类输入形状；在未批准metadata/未贯通新contract之前，当前系统产生“不具备信号计算资格”是正确行为，不应为了演示成功而伪造来源。

### 6.4 最小验收用例（规范，不是本轮已新增测试）

| 用例 | 期望行为 |
|---|---|
| SUM(paid_amount) AS sales_amount | alias/name与源字段分离；实际SUM记录；dtype取cursor；无region/period时不伪造grain |
| 英文alias revenue/中文alias 销售额 | 绑定依赖SQL，不随显示名称改变；禁止借Interpretation确定role |
| SELECT 1 AS x,2 AS x | 捕获按ordinal保留两个值；兼容dict展示不静默覆盖，歧义有诊断 |
| 返回0/199/200/201/500行 | 输出完整性、total_rows与truncated符合2.5定义；500不报total=200 |
| SQL含LIMIT100但全fetch | complete_query_output可成立；全量分析population_coverage不得因此通过 |
| SQL聚合全量订单后返回4地区 | 允许证明完整聚合；不误认为只处理4订单 |
| legacy缺dtype/truncated | unknown贯通MCP/state，不能默认false/数值类型 |
| DECIMAL高精度、大整数、NULL | codec往返遵守声明；不先float化；NULL不补0；工作精度不足可控拒绝 |
| driver不能完整表示的TIMESTAMP_NS | 明确unsupported/lossy，不谎称无损时间类型 |
| 两层CTE的SUM | 追溯基表与上游操作；不把CTE名当永久业务源 |
| current/history UNION ALL | 两分支lineage保留；无互斥/去重政策时不宣布安全全集 |
| orders与targets只按region join | S1拒绝；补月但重复累计目标仍拒绝 |
| 目标重复、缺目标、T=0、unit未知 | S1跳过完成率并给具体原因，不以MAX目标隐藏重复 |
| S1 ratio舍入后恰为1 | 达标比较使用未舍入A与T，不按展示值判定 |
| S2缺历史权限或基期行 | 不补0、不额外查库；缺乏资格 |
| S2 P=0/负基数/不同状态口径 | 普通增长率不计算，可信原金额仍可展示 |
| S3先Top3再取其和作分母 | 拒绝总体份额；完整输入算份额后再展示Top3才允许 |
| 某产品名称重复/目录join不唯一 | ID身份不混淆；无法证明不放大金额则不算贡献 |
| LLM返回[]、"false"、异常或新编造数字 | 受控说明失败/意见处理；不得覆盖execution与SignalBatch |
| LLM与signal对“能否回答用户问题”意见不同 | 保留意图层提示；signal仅声明实际执行范围，不伪装全部问题已解决 |

这些验收点只覆盖设计承诺的MVP范围，不构成对当前完整项目的已通过测试声明。

### 6.5 设计证据索引

| 当前源码 | 类 / 函数与行号 | 支持的设计决定 |
|---|---|---|
| [querying/models.py](D:/agent_study/askdata_studio/backend/app/querying/models.py:7) | SqlExecution L7–13 | 现有五字段不足，需独立中间contract |
| [duckdb_engine.py](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:33) | execute L33–51；connect L54–73；_validate_sql L75–127；_json_value L144–150 | 捕获点、CSV内存数据库、SQL parser与权限、数值/类型损失 |
| [mcp_runtime/schemas.py](D:/agent_study/askdata_studio/backend/app/mcp_runtime/schemas.py:21) | DatabaseQueryResult L21–28 | 结构化执行结果契约需要贯通 |
| [database_tools.py](D:/agent_study/askdata_studio/backend/app/mcp_runtime/tools/database_tools.py:32) | query_database L32–43 | 显式字段装配与row_count=len(rows) |
| [mcp_runtime/client.py](D:/agent_study/askdata_studio/backend/app/mcp_runtime/client.py:38) | LocalMcpClient.call_tool/_call_tool L38–54 | MCP structured_content到dict的校验边界 |
| [query_graph.py](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:215) | _retrieve_schema L215–229；_prepare_single_database L280–289；_execute_single_database L293–355 | graph是执行前context；state重建压缩；C集成点 |
| [result_builder.py](D:/agent_study/askdata_studio/backend/app/workflows/result_builder.py:84) | completed L84–139；failed L142–156 | 禁止以Interpretation/最终status作为事实输入 |
| [response_generator.py](D:/agent_study/askdata_studio/backend/app/querying/response_generator.py:34) | finalize L34–58；__init__ L22 | LLM看样本与生成valid/title/analysis；只负责说明 |
| [model_client.py](D:/agent_study/askdata_studio/backend/app/model_client.py:41) | chat_json L41–53 | JSON解析不保证object，需要受控说明边界 |
| [models.py](D:/agent_study/askdata_studio/backend/app/models.py:54) | Interpretation L54–59；QueryResult L62–83 | 混合展示contract，不作为Engine入口 |
| [database.py](D:/agent_study/askdata_studio/backend/app/database.py:9) | _field L9–26；ORDER_FIELDS L29–39；SCHEMA L42–108；RELATIONS L111–156 | 源业务语义、缺unit/口径、三信号字段与粒度约束 |
| [demo_data.py](D:/agent_study/askdata_studio/backend/app/demo_data.py:23) | seed_demo_data L23–51；_orders L115–153 | 固定月份/状态快照，不得声称线上实时覆盖 |
| [access_control.py](D:/agent_study/askdata_studio/backend/app/security/access_control.py:22) | allows_database/allows_table L22–26；demo_current_sales L66–71 | 总体受实际授权限制，不越权补历史/名称 |
| [Baseline Report](D:/agent_study/askdata_studio/learning_report/askdata_business_signal_baseline_report.md) | 第2–4节、5.4数据指纹 | 已确认的信息损失、固定数值样例与数据能力边界 |

### 6.6 最终决策摘要

交付自检：六个要求章节完整；文档中的绝对路径源码链接与行号范围检查通过；六个JSON示例可解析。设计前后核验的59个后端业务/测试Python文件及业务CSV的SHA-256均未变化。本轮新增文件仅为本设计文档；未实施契约、Signal或集成代码，验收用例尚是设计规范。

**新增最小中间ResultContract；在DuckDB出口保留事实，在ResponseGenerator之前完成受限SQL语义绑定和三条确定性信号计算。**

QueryResult继续展示，LLM继续解释，但两者不成为事实来源。无法确认来源、完整性、粒度、单位或比较政策时，系统明确“不计算该信号”，保留普通查询结果。

这一步要建立的是“每个业务数值都能说明输入、口径、运算和证据”的可靠边界，而不是让系统在证据不足时多说几句经营分析。
