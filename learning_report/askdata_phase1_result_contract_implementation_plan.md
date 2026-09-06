# AskData Phase 1：ResultContract 最小改造调查与实施方案

> 日期：2026-09-06。
> 依据：[Business Signal Layer Design Document](D:/agent_study/askdata_studio/learning_report/askdata_business_signal_layer_design.md)，并重新核对当前源码。
> 本轮按“调查、设计最小改造、输出清单/数据流/兼容/风险”交付方案，分块写入本文件，**尚未实施业务代码修改**。
> 本阶段只建设执行事实契约，不实现Business Signal、SQL lineage解析、Repository、新LLM或新LangGraph节点。

## 1. 修改文件列表

### 1.1 建议最小范围：新增1个生产文件，修改5个生产文件

下表是**拟修改清单**，不是已修改清单。

| 操作 | 文件 | 最小职责 / 修改点 |
|---|---|---|
| 新增 | `D:/agent_study/askdata_studio/backend/app/querying/result_contract.py`（拟新增，目前不存在） | 定义Pydantic ResultContract、ExecutionData、ColumnMetadata、ExecutionProvenance；集中放版本/不变式校验、受支持值codec及旧展示投影。只依赖stdlib/Pydantic，不反向import SqlExecution或MCP，避免循环依赖。 |
| 修改 | [querying/models.py](D:/agent_study/askdata_studio/backend/app/querying/models.py:7) | 在SqlExecution末尾增加`result_contract: ResultContract \| None = None`；保留原5个字段顺序及默认值，避免破坏现有位置参数调用。 |
| 修改 | [querying/duckdb_engine.py](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:33) | execute在cursor存活且dict化之前采集dtype/ordinal/原值/截断证据；建立执行provenance；把新contract挂到SqlExecution。失败路径不伪造cursor事实。 |
| 修改 | [mcp_runtime/schemas.py](D:/agent_study/askdata_studio/backend/app/mcp_runtime/schemas.py:21) | DatabaseQueryResult增加可选`result_contract`嵌套字段，原7字段保留；success/error说明补充旧格式交付失败这一明确例外。 |
| 修改 | [mcp_runtime/tools/database_tools.py](D:/agent_study/askdata_studio/backend/app/mcp_runtime/tools/database_tools.py:32) | 构造DatabaseQueryResult时显式传递execution.result_contract；row_count仍表示返回行数，不改成总行数。 |
| 修改 | [workflows/query_graph.py](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:293) | 在既有_execute_single_database内读取/严格验证新增载荷，并关联到重建SqlExecution；保留canonical contract与旧展示投影，处理缺失/非法版本/兼容失败，不新增节点。 |

这6个生产文件即可完成“引擎捕获→MCP→Workflow重建”的最小贯通。**不把正式对外API新增contract字段悄悄并入本阶段。** QueryResult的类型和普通结果形状保持不变，新契约由SqlExecution及现有state.mcp_execution持有。

### 1.2 为什么这些文件暂时不需要改

| 文件 / 组件 | 不修改的依据 |
|---|---|
| [LocalMcpClient](D:/agent_study/askdata_studio/backend/app/mcp_runtime/client.py:41) | L54直接dict(structured_content)，没有字段白名单；透传本身不需要修改。版本验证集中在Workflow入口及新模型，避免两处实现不同规则。 |
| [MCP server注册](D:/agent_study/askdata_studio/backend/app/mcp_runtime/server.py) / 已安装SDK | 已按返回类型产生输出Schema并序列化Pydantic模型；不改第三方依赖。 |
| [SingleDatabaseAgent.prepare](D:/agent_study/askdata_studio/backend/app/querying/single_database_agent.py:109) | L119–125把整个tool_result作为execution返回，无字段裁剪；不修改SQL生成、工具选择、Prompt或循环。 |
| [QueryState](D:/agent_study/askdata_studio/backend/app/workflows/state.py:33) | 已有`mcp_execution: dict[str, Any]`，可在同一个key中容纳嵌套contract，不必增加state字段。 |
| [ResponseGenerator.finalize](D:/agent_study/askdata_studio/backend/app/querying/response_generator.py:34) | 继续消费兼容sql/columns/rows，本期不让它消费契约或新增LLM逻辑。 |
| [QueryResult定义](D:/agent_study/askdata_studio/backend/app/models.py:62)、[ResultBuilder](D:/agent_study/askdata_studio/backend/app/workflows/result_builder.py:84)、前端/API | 保持现有公开字段与普通结果展示。异常重复列的兼容处理在已有Workflow节点中明确返回诊断，不依靠改前端容纳重名dict键。 |
| retrieval、SCHEMA、权限策略、CSV | 本阶段不解释业务语义、不改数据与授权，不改变SQL安全校验范围。 |

### 1.3 必需测试范围

建议新增 `D:/agent_study/askdata_studio/backend/tests/test_result_contract.py`（拟新增）负责模型、codec、捕获及兼容边界；扩展 [test_mcp_runtime.py](D:/agent_study/askdata_studio/backend/tests/test_mcp_runtime.py:23) 验证MCP往返；扩展 [test_service.py](D:/agent_study/askdata_studio/backend/tests/test_service.py:356) 验证Workflow与原QueryResult回归。

即：**生产6文件 + 测试3文件**的建议实施范围；本轮仅新增本报告，没有建立这些代码文件或改测试。

## 2. 数据流变化

### 2.1 调查结果一：SqlExecution在哪里创建

本轮搜索backend/app中的`SqlExecution(`，生产代码共有4处：

| 文件 / 函数 | 当前行号 | 用途 | Phase 1处理 |
|---|---:|---|---|
| [DuckDbEngine.execute](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:49) | L49 | 成功执行结果 | 创建新contract并附加；保留前4个位置参数意义 |
| [DuckDbEngine.execute](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:51) | L51 | 校验/解析/连接/执行等异常结果 | 可创建失败的执行attempt contract；没有cursor时不伪造dtype/总行数/完整性 |
| [QueryWorkflow._execute_single_database](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:296) | L296–302 | MCP dict重建执行对象 | 必须恢复并验证result_contract，否则新字段再度丢失 |
| [QueryWorkflow._run_multi_database](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:359) | L359–363 | 尚未实现多库的合成失败 | 可选字段默认None即可兼容；它没有真实DuckDB执行，不能伪造执行provenance |

成功/失败的当前代码：[DuckDbEngine.execute L40–51](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:40)：

```python
safe_sql = self._validate_sql(database, sql, access_scope)
with self.connect(database) as connection:
    cursor = connection.execute(safe_sql)
    raw_rows = cursor.fetchmany(201)
    columns = [item[0] for item in cursor.description or []]
    rows = [
        {column: self._json_value(value) for column, value in zip(columns, row)}
        for row in raw_rows[:200]
    ]
return SqlExecution(safe_sql, True, columns, rows)
# except分支：
return SqlExecution(sql, False, error=str(exc))
```

真正采集点应放在L42–48，不能等到旧rows已经按重复列名覆盖后再补column_id。

### 2.2 调查结果二：DatabaseQueryResult在哪里创建

生产代码只有一处构造：[build_database_query_tool内部query_database，L32–43](D:/agent_study/askdata_studio/backend/app/mcp_runtime/tools/database_tools.py:32)：

```python
execution = engine.execute(database, sql, access_scope)
return DatabaseQueryResult(
    database=database,
    sql=execution.sql,
    success=execution.success,
    columns=execution.columns,
    rows=execution.rows,
    row_count=len(execution.rows),
    error=execution.error,
)
```

只给SqlExecution新增字段不会自动穿过这里；需要新增显式赋值。原`row_count`继续等于实际返回旧展示rows数，正常兼容路径与新returned_rows一致；任何兼容投影失败必须明确诊断，不能假装两种row_count自然一致。

### 2.3 调查结果三：MCP structured_content在哪里生成

不是AskData手工构造，而是当前已安装SDK的 [FuncMetadata.convert_result L140–144](D:/agent_study/askdata_studio/backend/.venv/Lib/site-packages/mcp/server/mcpserver/utilities/func_metadata.py:140)：

```python
validated = self.output_model.model_validate(result)
structured_content = validated.model_dump(mode="json", by_alias=True)
return CallToolResult(content=unstructured_content, structured_content=structured_content)
```

DatabaseQueryResult声明并携带合法嵌套contract后，SDK会一起序列化。dtype不能直接存DuckDB类型对象，必须显式转成受支持的字符串/参数数据；Decimal/date等值也必须先遵守选定codec，不能指望SDK自动决定语义政策。

本项目 [LocalMcpClient._call_tool L41–54](D:/agent_study/askdata_studio/backend/app/mcp_runtime/client.py:41) 检查is_error和structured_content存在后：

```python
return dict(result.structured_content)
```

dict转换不会丢掉新增字段，但Pydantic对象身份会消失，所以需要在下一可信消费边界显式验证还原。

### 2.4 调查结果四：Workflow在哪里重建execution

[QueryWorkflow._prepare_single_database L280–289](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:280) 先把Agent给出的整个execution存入`state['mcp_execution']`，没有裁剪。

真正压缩点是 [_execute_single_database L295–302](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:295)：

```python
raw_execution = state.get("mcp_execution") or {}
execution = SqlExecution(
    sql=str(raw_execution.get("sql") or state.get("direct_sql") or ""),
    success=bool(raw_execution.get("success")),
    columns=list(raw_execution.get("columns") or []),
    rows=list(raw_execution.get("rows") or []),
    error=raw_execution.get("error"),
)
```

这里没有重新执行SQL，只重建旧5字段。Phase 1应在这里验证嵌套新载荷，将同一contract附加到execution，并核对旧展示字段与canonical值的投影是否一致。不能只在MCP trace中保留contract、业务消费仍拿无contract对象。

### 2.5 新旧数据流

```text
当前：
cursor
 → SqlExecution(5字段)
 → DatabaseQueryResult(7字段)
 → MCP structured_content
 → dict → state.mcp_execution
 → SqlExecution(又只复制5字段)
 → ResponseGenerator / ResultBuilder → QueryResult

拟议：
cursor（有序列、dtype、原取值、fetch证据）
 → ResultContract.execution（canonical）
 → SqlExecution(原5字段 + result_contract)
 → DatabaseQueryResult(原7字段 + result_contract)
 → MCP structured_content（保留version、null、codec）
 → dict → 原有state.mcp_execution
 → Workflow验证/恢复同一ResultContract
 → SqlExecution(兼容字段 + result_contract)
       ├─ contract：留给后续确定性组件，本阶段不调用它们
       └─ 原字段：既有ResponseGenerator / ResultBuilder → 原QueryResult
```

`result_id`在引擎执行attempt处生成一次，MCP/Workflow不能重新生成；ordinal在往返中不重排。新contract不增加一次SQL执行、COUNT补查或一次LLM调用。

## 3. 新旧contract兼容方案

### 3.1 Phase 1只交付execution部分

拟议最小结构如下。它是待实施接口，不是当前已经存在的源码：

```text
ResultContract
├── version: "1"
├── result_id: 执行attempt UUID（本次身份，不是业务主键）
├── execution
│   ├── database: string
│   ├── sql: string（与当前字段一致，成功为执行SQL，失败可为尝试SQL）
│   ├── success: bool（执行/取值是否成功，不受LLM valid影响）
│   ├── error: string | null
│   ├── columns: ColumnMetadata[]
│   │   └── id, ordinal, name, dtype, value_encoding, representation_status
│   ├── rows: 按ordinal排列的二维值数组
│   ├── returned_rows: int
│   ├── total_rows: int | null
│   ├── truncated: bool | null
│   ├── completeness: complete_query_output | partial_query_output | unknown
│   └── provenance
│       └── engine, source_kind, captured_at,
│           sql_submitted, submitted_sql, access_scope_ref, snapshot_ref
└── understanding: null（Phase 1不计算业务语义）
```

`source lineage/role/unit/aggregation/row_grain`不在本期推断；“可信语义契约”在本期准确意味着**可信的执行数据、物理类型与来源身份基础**，不是已经能判断SUM是否合法或解释业务含义。不会读取Interpretation、LLM分析或retrieval分数来填空。

### 3.2 dtype、column identity与值表示

| 项目 | Phase 1决定 |
|---|---|
| dtype | 由cursor.description的type_code捕获并转换为稳定字符串，例如BIGINT、DOUBLE、DECIMAL(20,2)、DATE；不直接序列化DuckDB类型对象。无cursor时未知，不从SCHEMA或Python值猜。 |
| name | 保留cursor实际输出名；不把它当源字段名或业务alias绑定。 |
| id / ordinal | `c0/c1/...`与0-based位置；跨结果唯一身份是`(result_id, column_id)`，不是单独c0。 |
| canonical rows | 二维数组，与有序columns对应；重复name也不能覆盖值。 |
| value_encoding | 支持类型明确codec：native_json、decimal_text、integer_text、iso_date、iso_datetime；同列编码一致。 |
| representation_status | preserved/lossy/unsupported/unknown；记录DB→Python→JSON的表示边界，不虚称所有类型无损。 |

dtype保留但value已经偷偷改变，同样不可信，因此这一小块codec属于契约边界工作，不是Business Signal扩展：

- DECIMAL新契约以十进制字符串保存；旧QueryResult投影仍可沿用原float形式，但不能再把旧投影当canonical。
- 可能超过跨JSON消费者安全范围的整数列使用integer_text，同列非NULL小整数也统一此codec。
- 日期/受支持时间戳保存ISO文本并注明实际dtype；NS精度等driver已无法完整表示的类型不得标preserved。
- DOUBLE的原浮点值保留不等于精确货币；NULL仍是NULL，不补0。
- 未支持的类型/无法JSON编码的对象给显式unsupported或受控取值错误，不静默转str或NULL冒充原值。

现有转换位置见 [DuckDbEngine._json_value L144–150](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:144)。采集新contract应在旧转换/重名dict投影前；支持范围之外的driver损失仍需标记，不能仅靠调整代码顺序承诺通用无损。

### 3.3 截断、返回行数与未知总行数

仍保留200行上限，用一次fetchmany(201)获取边界证据：

| 场景 | returned_rows | total_rows | truncated | completeness |
|---|---:|---:|---|---|
| 成功，输出0行且确认耗尽 | 0 | 0 | false | complete_query_output |
| 成功，fetch得到1～200行且确认耗尽 | n | n | false | complete_query_output |
| 成功，fetch得到201行，保留前200 | 200 | null | true | partial_query_output |
| 失败/捕获证据不足 | 实际携带行数，通常0 | null | null | unknown |
| legacy载荷没有新contract | 旧len(rows)仍可读 | 未知 | 未知 | 无contract意味着unknown，不默认完整 |

`total_rows`只表示**实际SQL的输出总行数**。例如SQL自身LIMIT100，全返回时total_rows=100、truncated=false；这不证明没有LIMIT的业务总体只有100行。

禁止：把row_count=len(rows)改称total_rows；在捕获201行时把total_rows填201；默认补跑COUNT；用rows不足200判断业务期间数据完整。本期不计算business completeness，completeness名称明确限定query_output。

### 3.4 Execution provenance最小语义

| 信息 | 来源与约束 |
|---|---|
| result_id | 引擎进入本次execute时生成，成功/失败保持同一ID；MCP/state还原不重建ID，不等于workflow task_id。 |
| database | engine实参/Tool绑定的库；Workflow校验与本次预期库一致，不以LLM输出自报替代。 |
| engine / source_kind | 程序赋值duckdb / csv_views，依据当前[connect L54–73](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:54)。 |
| captured_at | 服务端UTC捕获时间；不是业务发生时间、数据新鲜度证明或一致性快照。 |
| sql_submitted / submitted_sql | 是否真正调用connection.execute，以及提交的safe_sql；验证/连接失败则false/null，不能将尝试SQL说成已经执行。 |
| access_scope_ref | 由实际服务端AccessScope计算的非敏感稳定引用/摘要；无scope时null/未提供。不是权限令牌，也不是新授权机制。 |
| snapshot_ref | 当前未建立快照能力时null；不使用时间戳或database名假装快照ID，不在Phase 1新增Repository/快照系统。 |

execution.sql保留原字段成功/尝试语义；provenance.submitted_sql补足失败分支中“实际提交过哪条cleaned SQL”的区别。`sql_submitted=true`只证明已经提交，不等于执行或取值成功；后者看execution.success/error。

对合成多库失败和旧结果，不为了凑对象而编造DuckDB执行ID、时间、dtype或捕获证明。

### 3.5 双轨兼容：canonical与旧展示投影

推荐明确两条轨道：

```text
新：ResultContract.execution → 未来机器计算可信入口
旧：SqlExecution原字段 / DatabaseQueryResult原字段 → 当前展示与说明
```

正常、列名唯一且受支持的结果：旧sql/columns/rows/row_count语义保持；旧字段由同一次原始捕获或canonical解码后按原显示codec投影，不能分别执行两次SQL得到两套数据。

SqlExecution追加可选字段，DatabaseQueryResult追加可选字段；QueryResult本期不增加顶层contract字段。当前 [ResultBuilder L126–138](D:/agent_study/askdata_studio/backend/app/workflows/result_builder.py:126) 可继续原有赋值。契约在state.mcp_execution中保留，且在重建execution上可直接访问，为下一期留好内部入口。

必须区分“QueryResult结构不破坏”与“任何历史错误行为原样保留”。重复输出名称是一项必须明确的例外：

- `SELECT 1 AS x,2 AS x`的新contract保持columns两个位置与rows=`[[1,2]]`。
- 旧`dict[str,Any]`不能同时保存两个同名键；无法同时做到保留同名、保留两值、完全不改变表示。
- 沿用上阶段设计的选择：**不偷偷重命名，也不继续静默覆盖；对旧展示投影给受控兼容失败。**
- canonical执行/取值成功仍为true；兼容载荷用明确`RESULT_COMPATIBILITY_ERROR`说明不能交付旧表格。旧rows不提供被覆盖的假成功表格；其row_count只表示旧投影行数，不能冒充canonical returned_rows。
- Workflow识别该兼容错误，在既有节点中返回清楚的QueryResult失败文案“SQL已执行，但旧结果格式无法无损展示重复列”，而不是谎称SQL没有执行。保留canonical结果与诊断，不调用LLM解释错误表格。

这意味着异常重复列用例的旧成功行为会被纠正，但普通唯一列结果与QueryResult字段结构不变。不能宣称新旧载荷在兼容失败时所有success/rows必然相等；应使用同一个投影规则验证该例外，明确SQL事实与旧交付状态不同。

对`SELECT 1 AS x,2 AS x`，建议把预期值写死为验收规范：

| 字段 | canonical contract | 旧兼容载荷 |
|---|---|---|
| success | true（SQL执行与取值成功） | false（不能交付旧格式） |
| columns | 两个独立column_id，name均为x | `["x", "x"]`保留诊断用名称，不作为成功表格输出 |
| rows | `[[1, 2]]` | `[]`，不返回覆盖后的假完整行 |
| 数量 | returned_rows=1,total_rows=1,truncated=false | row_count=0，仅说明旧交付rows数量 |
| error | null | `RESULT_COMPATIBILITY_ERROR: duplicate output names` |

因此原DatabaseQueryResult.success的“SQL是否执行成功”描述需要补充“兼容结果可交付；兼容错误时实际执行状态见result_contract”。这是对异常分支的明确语义调整，不宣称旧success永远是纯DB事实；不得未经说明改变其含义。

实现时需要两项防止自相矛盾的处理，都在已列入的文件范围内：

1. 当前engine的try/except会统一捕获ValueError（[L39–51](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:39)）。先固定成功canonical，再处理投影；重复列投影失败不能直接掉入旧异常处理，把canonical成功改写成SQL失败。
2. 当前Workflow的`execute_duckdb`日志取旧execution.success（[L312–317](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:312)）。新兼容异常分支应按canonical事实记录数据库成功，并另记结果兼容失败；其他宣称描述“SQL执行状态”的摘要也须使用同一事实依据，不能留下互相矛盾的日志。

### 3.6 旧载荷、非法载荷与版本处理

| 输入 | 处理 |
|---|---|
| 新contract合法、version受支持 | 恢复为Pydantic对象；核验有序列/行宽、returned_rows、完整性不变式、库与旧字段的确定性投影关系。 |
| result_contract缺失/null | 接受旧路径，SqlExecution.result_contract=None；不影响普通展示，但任何未来可信消费必须视为metadata/完整性未知。 |
| 非法新contract已抵达Workflow入口 | 不悄悄按legacy接收；记录明确RESULT_CONTRACT_ERROR，在既有Workflow节点受控处理。 |
| 新旧字段冲突 | 正常结果按投影规则校验，不任意挑一边或bool/str强转；受控失败并保留原证据。 |
| 合法新contract的旧展示投影不可表示 | 使用3.5的兼容失败路径，不修改canonical事实。 |

验证函数集中在拟新增模块，Workflow调用；MCP SDK仍负责其返回模型校验。未知总行数必须经过Pydantic→MCP JSON→dict→Pydantic往返仍为null，不能`or 0`或`bool(None)`变成虚假的已知值。

并非所有非法contract都会到达Workflow：生产者Pydantic构造或SDK输出校验可能更早失败，沿已有MCP is_error→LocalMcpClient RuntimeError→Agent PipelineStageError→服务失败路径返回。无需为统一错误码修改Agent/SDK；测试应分别覆盖“生产/SDK提前拒绝”与“伪造dict已经抵达Workflow”两个边界，不能把后者处理承诺泛化到所有情况。

### 3.7 保持既有Agent，但承认两项可见影响

第一，数据库Tool返回后，[SingleDatabaseAgent L119–125](D:/agent_study/askdata_studio/backend/app/querying/single_database_agent.py:119) 立即return；其结果不进入L127的observations，因此新增contract实际数据不会自动进入下一轮SQL Agent推理。ResponseGenerator也不因SqlExecution多字段就自动读取整个对象。

第二，输出**Schema定义**会进入已有Prompt：[LocalMcpClient._list_tools L22–35](D:/agent_study/askdata_studio/backend/app/mcp_runtime/client.py:22) 已返回output_schema；[SingleDatabaseAgent L60–81](D:/agent_study/askdata_studio/backend/app/querying/single_database_agent.py:60) 把整个mcp_tools加入模型输入。因此可以承诺“不改Agent代码/不增加LLM调用”，但不能承诺“Prompt字节/token完全不变”。新schema应保持紧凑，回归测试现有调用行为。

另外，新增载荷会随[tool trace L110–117](D:/agent_study/askdata_studio/backend/app/querying/single_database_agent.py:110)进入[execution_log L304–310](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:304)，可能嵌套出现在QueryResult诊断字段。它不是新增正式顶层API，也不能以日志作为新契约的唯一消费入口。

## 4. 实施风险

### 4.1 主要风险与对应措施

| 风险 | 发生位置 / 原因 | 最小控制 |
|---|---|---|
| 只新增类型却仍丢字段 | Tool和Workflow都显式复制旧字段 | 同时覆盖模型、构造点、MCP往返与Workflow还原；不能只测engine |
| 改坏位置参数 | engine L49用SqlExecution(safe_sql,True,columns,rows) | 新可选字段放末尾，原顺序不动；多库合成失败保持None |
| dtype不是JSON类型 | cursor返回DuckDB类型对象 | 捕获时规范化dtype，不把对象直接交给SDK序列化 |
| dtype保存了，值却失真 | 旧Decimal→float；driver时间精度；重名dict覆盖 | 新contract在旧投影之前建立；支持类型用codec；已损失或未知表示不标preserved |
| 新旧事实出现两套独立来源 | 分别构造旧rows和新rows而未共享捕获/投影规则 | 一次SQL、同一批原值/确定性codec；Workflow校验一致性与兼容失败例外 |
| 把total_rows变成返回数 | 把现有row_count复制/改名，或null被`or 0`处理 | 独立字段与校验；201哨兵只证明截断，不能证明总数 |
| 无截断被理解为业务全量 | SQL自身LIMIT/HAVING、WHERE及数据覆盖问题 | completeness明确只描述query_output；本期不认证业务总体 |
| 异常兼容状态被说成SQL错误 | 新contract成功但旧投影无法表示同名列 | 使用明确兼容错误码和Workflow文案；原SQL/取值事实在contract中不改写 |
| 失败分支捏造provenance | 验证/连接失败没提交SQL，多库路径没执行 | 用sql_submitted/submitted_sql区别；不生成虚假dtype/快照/总行数 |
| 新输出schema扩大Prompt | Agent现有mcp_tools包含output_schema | 保持模型字段紧凑，测试工具输入仍只sql、调用次数不增加；不改SQL Agent来掩盖影响 |
| 载荷/日志体积增长 | 旧rows、新canonical rows、MCP text/structured与trace可能重复 | 保持200行上限；测序列化与state体积；不把这次改造成日志/存储重构 |
| SDK/Pydantic往返改变null/数字 | 版本、JSON codec或模型宽松转换 | 严格测试类型、null、版本；非法新contract不静默降级legacy |
| provenance被当成权限/快照保证 | execution_id、时间戳、scope摘要不是授权令牌/原子数据快照 | 保留实际权限校验；snapshot_ref未知为null；不扩大查询范围 |

### 4.2 最小验收矩阵

以下是建议实施时必须加入的测试，不是本轮已经运行的新实现测试：

| 测试 | 期望 |
|---|---|
| 普通区域聚合查询 | 现有QueryResult.columns/rows/SQL及调用路径回归不变；内部已有新contract |
| 空结果但有投影列 | dtype仍可捕获；returned=0,total=0,truncated=false，不能丢columns |
| 199 / 200行SQL输出 | total=returned，确认未截断；不误报200必截断 |
| 201 / 500行SQL输出 | returned=200,total=null,truncated=true；数据库不额外COUNT/fetchall |
| SQL自身LIMIT100 | total=100且应用未截断；语义仅限该SQL输出 |
| 同名输出x、x | contract保留两个列身份和两个值；旧兼容路径受控失败，不静默只留后值 |
| alias叫sales_amount | name按cursor保留，dtype按实际类型保留；不生成paid_amount lineage或metric角色 |
| DECIMAL、BIGINT、DATE、NULL | 新codec往返保持声明语义；旧展示codec与canonical明确分开 |
| 无法保真/不支持类型 | 明确lossy/unsupported或受控错误，不填假值 |
| 校验失败 / 数据库执行失败 | 错误与sql_submitted状态正确；无cursor时不填total=0或truncated=false |
| 多库未实现合成失败 | 原路径仍可构造SqlExecution，result_contract=None，不伪造DuckDB执行 |
| MCP完整往返 | version/result_id/dtype/ordinal/null总数/codec均保持；旧字段仍存在 |
| Workflow重建 | SqlExecution.result_contract还原成功；同一result_id不变；不只留在trace |
| 缺少contract的旧MCP载荷 | 保持旧展示路径；新契约缺失就是unknown，不升级为可信新结果 |
| 非法contract / 不支持版本 | 到达Workflow的非法载荷受控RESULT_CONTRACT_ERROR；生产者/SDK提前拒绝另测既有错误通道，不吞成legacy |
| 新旧字段冲突 | 按确定性投影规则拒绝；只允许显式定义的兼容失败差异 |
| 工具发现与Agent | query工具input_schema仍只要求sql；不新增工具/节点/模型调用；output_schema新增部分可序列化 |

测试优先使用现有项目虚拟环境、内存DuckDB和临时fixture，不调用在线LLM。已有 [MCP测试L13–18](D:/agent_study/askdata_studio/backend/tests/test_mcp_runtime.py:13) 与 [Service测试L278–297](D:/agent_study/askdata_studio/backend/tests/test_service.py:278) 已使用临时数据库/FakeModel，可在其基础上扩展；不要为测试改写业务CSV。

### 4.3 建议实施顺序与本期完成定义

1. **模型与不变式先行**：建立新独立模块和测试，明确codec、列身份、数量与null语义；不先接入LLM/业务语义。
2. **engine捕获**：成功/失败分支都覆盖，保留原调用签名；先测dtype/重名/200边界与失败provenance。
3. **MCP贯通**：追加可选字段并显式传递，用现有SDK做往返测试，不修改SDK/工具注册/SQL Agent。
4. **Workflow还原**：在旧节点内校验contract、维持兼容投影、处理legacy与兼容错误；不新增LangGraph节点。
5. **旧行为回归**：验证正常QueryResult不变、模型调用数不增加、新载荷不会丢在重建处。

Phase 1完成的证据应是：**同一次执行的有序值、dtype、返回数量、截断/未知总数及来源身份，可以经过MCP到Workflow再还原，且现有普通QueryResult仍正常工作。**

不以“已能计算目标完成率”验收；本期不实现Business Signal，也不宣称已经拥有unit、aggregation、row_grain或输出lineage。

### 4.4 本轮交付边界

本轮完成了四个创建/转换边界的源码调查和上述实施方案，仅写本Markdown，没有新增ResultContract生产文件，没有修改SqlExecution、DatabaseQueryResult、Workflow、QueryResult或测试。

交付核验：方案包含要求的4个部分；核验范围内59个后端业务/测试Python及业务CSV文件的SHA-256前后相同。拟新增的生产result_contract.py仍不存在，未把设计误报为已实施。

**最小建议：新增1个契约模块，修改5个生产文件，新增/扩展3个测试文件；不改SQL Agent、不加LLM、不加节点、不引入Repository、不实现Signal。**
