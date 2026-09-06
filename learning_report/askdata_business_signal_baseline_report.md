# AskData Baseline Report

> Business Signal Layer 改造前基线；调查日期：2026-09-06。
> 本报告分块写入 `learning_report`，仅新增本 Markdown。未修改业务代码、测试、配置或 CSV，未实现 Result Contract、Repository、Derive 或 Business Signal Engine。
> 依据是本次读取的当前源码，以及内存 DuckDB / mock LLM 的只读 probe，不沿用旧报告行号。本文中的候选计算逻辑不是已经实现的 Signal API。

## 1. Current Architecture

### 1.1 核心判断

当前已经具备“受权限约束的单库 Text-to-SQL → 查询执行 → 结果说明 → API/UI”链路，但 **QueryResult 是执行数据、Schema 上下文、规则推断、LLM 文本和工作流记录的混合对象，不是已经可直接用于确定性业务信号计算的完整事实契约**。

本次最重要的发现：

1. `rows` 最接近数据库结果，但经过类型转换、最多 200 行裁剪；它不是原始 cursor 数据，也不天然代表全量。
2. `columns` 是输出列名；`sql` 是执行记录。它们不能单独证明业务口径、单位、输出列语义或来源表。
3. `schema_graph`、`retrieval` 是执行前选择的 Schema context，不是执行后输出列 lineage。
4. `interpretation.metric/dimension` 来自中文列名关键词，不是数据库或 Schema 对输出列的确定标注。
5. `analysis/result_title` 通常来自 LLM；`status` 还受到 LLM `valid` 影响，不能等同于数据库执行成功。
6. 实际顺序是 **重建 SqlExecution → ResponseGenerator.finalize → ResultBuilder.completed → QueryResult**，不是 QueryResult 再进入 ResponseGenerator。
7. 当前数据是 `askdata_mock` 的五张 CSV：订单覆盖 2026-06 至 2026-08，目标覆盖 7、8 月。本报告不把当前系统日期 9 月的空数据解释成业务下滑。
8. 已复现同名输出列覆盖、Decimal 精度损失条件及 LLM 输出类型处理缺陷；dtype、lineage、信号业务规则缺口应与这些实际 bug 分开。
9. 第一批适合的确定性信号是月度区域目标完成、区域销售变化、产品贡献；客户相关先称“变化/活动线索”，不能直接称已确认客户风险。

证据入口：[DuckDbEngine.execute，L33–51](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:33)、[ResultBuilder.completed，L84–139](D:/agent_study/askdata_studio/backend/app/workflows/result_builder.py:84)、[实际生成顺序，L337–355](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:337)、[SCHEMA，L42–108](D:/agent_study/askdata_studio/backend/app/database.py:42)。后文逐项展开。

### 1.2 实际端到端链路

下图中的简称均在随后表格给出绝对路径、函数及当前行号；仅展开本次结果边界，不重复 SQL 决策和检索算法。

```text
POST /api/query
  → AskDataService.submit()
  → QueryWorkflow.invoke()
  → preprocess / retrieve_schema / prepare_single_database
  → SingleDatabaseAgent.prepare(): mcp_client.call_tool(...)
  → LocalMcpClient.call_tool() / _call_tool()
  → 本进程 MCP Server 中注册的 query_<database>
  → build_database_query_tool() 创建的 query_database(sql)
  → DuckDbEngine.execute(database, sql, access_scope)
       validate SQL → CSV-backed 内存 DuckDB → cursor
       → SqlExecution(sql, success, columns, rows, error)
  → DatabaseQueryResult（增加 database、返回行数 row_count）
  → MCP structured_content → Python dict
  → Agent 返回 execution → state["mcp_execution"]
  → QueryWorkflow._execute_single_database()
       重建 SqlExecution（此处不是再执行一次 SQL）
       ├─ 执行失败 → ResultBuilder.failed()
       └─ 执行成功 → ResponseGenerator.finalize()
                       ↑ query / SQL / columns / 前 N rows
                       ↑ schema_context / analysis_context
                     → ResultBuilder.completed()
  → QueryResult → state["result"] → QueryResult.model_validate()
  → AskDataService → API → UI
```

| 实际组件 | 输入 → 输出 / 职责 | 当前证据 |
|---|---|---|
| API `query` | Request / user → `service.submit` → QueryResult | [routes，L124–130](D:/agent_study/askdata_studio/backend/app/api/routes.py:124) |
| `AskDataService.submit` | 建立请求状态、调用 Workflow、返回结果 | [submit，L84–120](D:/agent_study/askdata_studio/backend/app/services/askdata_service.py:84) |
| `QueryWorkflow.invoke/_state_result` | 调用图；把 state.result 还原为 QueryResult | [L122–130](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:122) |
| `SingleDatabaseAgent.prepare` | MCP dict 同时进入 trace.result 和 decision.execution | [L109–125](D:/agent_study/askdata_studio/backend/app/querying/single_database_agent.py:109) |
| `LocalMcpClient.call_tool/_call_tool` | 同步桥接异步工具调用；读取 structured_content | [L38–54](D:/agent_study/askdata_studio/backend/app/mcp_runtime/client.py:38) |
| 数据库 Tool `query_database` | 执行 engine；包装 DatabaseQueryResult | [L25–46](D:/agent_study/askdata_studio/backend/app/mcp_runtime/tools/database_tools.py:25) |
| `DuckDbEngine.execute/connect` | 验证、执行、裁剪和序列化 | [L33–73](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:33) |
| `_prepare_single_database` | decision.execution → state.mcp_execution | [L280–289](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:280) |
| `_execute_single_database` | 重建执行对象、调用说明器与结果构建器 | [L293–355](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:293) |
| `ResponseGenerator.finalize` | 执行结果样本与上下文 → LLM final dict | [L34–58](D:/agent_study/askdata_studio/backend/app/querying/response_generator.py:34) |
| `ResultBuilder.completed/failed` | 执行数据、上下文、说明、日志 → API contract | [L84–156](D:/agent_study/askdata_studio/backend/app/workflows/result_builder.py:84) |

命名容易误导的一点：`_execute_single_database()` 主要是在整理**已经由 MCP Tool 执行过的结果**。L295 从 `mcp_execution` 取值，L296–302 重建对象，没有再次调用 `engine.execute()`。

### 1.3 数据源与权限边界

结论：当前业务查询查的是本地 CSV-backed 内存 DuckDB，不是线上数据库连接。

证据：[DuckDbEngine.connect，L54–73](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:54)。关键代码：

```python
folder = self._database_folder(database)
connection = duckdb.connect(":memory:")
...
for csv_path in csv_files:
    table = csv_path.stem
    ...
    connection.execute(
        f'CREATE VIEW "{table}" AS '
        f"SELECT * FROM read_csv_auto('{path}', header=true, sample_size=-1)"
    )
```

CSV 路径：[askdata_mock 数据目录](D:/agent_study/askdata_studio/backend/data/databases/askdata_mock)。运行时 CSV 类型由 `read_csv_auto` 推断；静态 SCHEMA 的“数值/日期”等描述不是实际 DuckDB dtype。内存注册 View 不修改 CSV。

可用信号还受访问范围限制：[AccessScope.allows_database/allows_table，L22–26](D:/agent_study/askdata_studio/backend/app/security/access_control.py:22)、[DuckDbEngine._validate_sql，L107–127](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:107)。例如 [demo_current_sales 策略，L66–71](D:/agent_study/askdata_studio/backend/app/security/access_control.py:66) 不含历史订单表，不能因为全仓库存在历史数据，就为该用户提供跨月历史比较。

当前只支持单数据库路径；[QueryWorkflow._run_multi_database，L357–365](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:357) 明确返回尚未启用的多库错误。五张表均在一个 `askdata_mock` 中，本报告信号不需要多数据库扩展。

### 1.4 本次基线核验方法

- 静态调查：当前业务源码、直接调用者、Schema、CSV 生成器及必要 UI 消费点；历史报告仅作调查线索。
- 动态调查：现有 [Python 虚拟环境](D:/agent_study/askdata_studio/backend/.venv/Scripts/python.exe)，Python 3.11.9、DuckDB 1.5.5；使用 `-B`，不写字节码。
- 只读数据核验：读取五张 CSV；通过 `DuckDbEngine.connect()` 的内存连接执行聚合查询，不启动 Service、不重建索引、不重新生成 demo 数据、不调用在线 LLM。
- LLM 边界核验使用假返回值，不消耗模型额度。动态数字来自本地文件快照，不是运行真实用户 Query 得到的模型答案。
- 表内金额沿用 CSV 数值尺度；没有从源码确认币种/单位，因此不擅自写“元”。
- 本报告记录的是已检查文件和已测用例，不宣称完整测试套件全部通过、所有潜在 SQL 均安全或所有 LLM 决策均业务正确。

## 2. Result Provenance Map

### 2.1 第一层：数据库来源不等于原始数据库表示

结论：`SqlExecution` 的第一次压缩发生在 cursor 读取、列名投影、行数裁剪和 value 转换处。

证据：[DuckDbEngine.execute，L40–51](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:40)：

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
```

解释：

1. `connection.execute` 才是真实 SQL 执行点；`safe_sql` 是经过安全校验/清理的 SQL，不代表业务正确性已经证明。
2. `fetchmany(201)` 只拿有限行，不计算 SQL 结果总行数；然后只保留前 200。
3. `description` 只读取第 0 项列名，不把类型对象传上去。
4. tuple 按列名变成 dict；如果列名重复，后一个值覆盖前一个值。
5. `rows` 里的计算列也可能由 SQL 中的 SUM、CASE、常量等表达式产生。它是该 SQL 的结果，不必然是源表原始单元格。
6. [异常路径 L50–51](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:50) 记录尝试 SQL、`success=False` 和错误；错误可能来自 Python 校验、解析、文件系统或 DuckDB，不全是 DB 引擎错误。

转换证据：[DuckDbEngine._json_value，L144–150](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:144)：

```python
if isinstance(value, (date, datetime)):
    return value.isoformat()
if isinstance(value, Decimal):
    return float(value)
return value
```

| 信息 | 上游实际来源 | 当前向上保留情况 |
|---|---|---|
| SQL | 模型/调用方生成，经 Python 清理验证后执行 | 成功时保留实际 safe_sql；属于执行记录，不是天然业务事实 |
| columns | cursor.description 的列名，包含 SQL alias | 保留名称，不保留 dtype、输出表达式映射 |
| rows | DuckDB 返回的 tuple/value | 最多 200 行；dict 化；日期字符串化；Decimal 浮点化 |
| success/error | 引擎执行或本地验证的结果 | SqlExecution 保留；最终 QueryResult 不含独立顶层 success/error |
| physical type | cursor.description 的 type_code | engine 未读取；不是从 JSON 类型即可恢复 |
| precision/scale/nullability | DuckDB description 对应位置 | probe 中为 None，不能把“标准有槽位”写成“数据库提供了有效值后被丢掉” |
| 结果是否完整 | fetch 后在局部可以知道是否取得第 201 行 | 没有导出 truncated；总结果行数也未计算 |
| 业务角色、单位、source lineage | 不由当前 cursor.description 天然提供 | 不是此处“丢了数据库已经提供的完整业务 metadata”，而是没有建立对应契约 |

完整执行对象只有五个字段，证据：[SqlExecution，L7–13](D:/agent_study/askdata_studio/backend/app/querying/models.py:7)：

```python
@dataclass
class SqlExecution:
    sql: str
    success: bool
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
```

### 2.2 MCP 与 Workflow：值保留、对象身份变化、字段再次压缩

证据：[query_database，L32–43](D:/agent_study/askdata_studio/backend/app/mcp_runtime/tools/database_tools.py:32)：

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

- 原五字段全部复制；`database` 是 Tool 闭包绑定的执行环境 metadata；`row_count` 是程序计算的**返回 rows 数量**，不是 SQL 的 COUNT(*)、不是 fetch201 数量。
- [DatabaseQueryResult，L21–28](D:/agent_study/askdata_studio/backend/app/mcp_runtime/schemas.py:21) 是 Pydantic 模型。当前安装 SDK 在 [FuncMetadata.convert_result，L140–144](D:/agent_study/askdata_studio/backend/.venv/Lib/site-packages/mcp/server/mcpserver/utilities/func_metadata.py:140) 对返回模型校验后 `model_dump(mode="json", by_alias=True)`，构造 CallToolResult。这里不能补回之前已丢失的 dtype/行数信息。
- [LocalMcpClient._call_tool，L43–54](D:/agent_study/askdata_studio/backend/app/mcp_runtime/client.py:43) 正常读 `result.structured_content`，最终 `return dict(result.structured_content)`。字段值继续存在，但返回对象不再具有 `DatabaseQueryResult` 的 Pydantic 类型身份。
- MCP `is_error` 与数据库 `success=False` 是不同层次：工具协议正常完成，也可能携带数据库执行失败的结构化结果。

Workflow 重建证据：[QueryWorkflow._execute_single_database，L293–302](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:293)：

```python
database = (state.get("database_names") or ["askdata_mock"])[0]
raw_execution = state.get("mcp_execution") or {}
execution = SqlExecution(
    sql=str(raw_execution.get("sql") or state.get("direct_sql") or ""),
    success=bool(raw_execution.get("success")),
    columns=list(raw_execution.get("columns") or []),
    rows=list(raw_execution.get("rows") or []),
    error=raw_execution.get("error"),
)
```

事实描述：下游 ResponseGenerator 和 ResultBuilder 接受 SqlExecution，因此这一层按它的五字段接口重新装配。`database/row_count` 没有复制进重建对象；database 从 state 另取，row_count 在 [L334](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:334) 再次用 len 计算。不能说它们“从整个系统彻底消失”：MCP trace.result 仍嵌套保存在日志中，但那不是顶层规范化业务结果字段。

### 2.3 Schema context、heuristic、LLM 分别从哪里进入

**Schema context。** [QueryWorkflow._retrieve_schema，L215–229](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:215) 在执行前由 hits 建 graph，并生成 schema_context。[SchemaGraphBuilder.build，L43–76](D:/agent_study/askdata_studio/backend/app/retrieval/graph.py:43) 收集 Schema 字段/关联键；[L102–109](D:/agent_study/askdata_studio/backend/app/retrieval/graph.py:102) 返回图。没有“输出 alias/表达式 → 一个或多个源字段”的确定映射。graph 中出现 paid_amount 或 role=metric，不等价于本次每个输出列都有可信业务标注。

**Heuristic。** [ResultBuilder.completed，L92–99、L116–123](D:/agent_study/askdata_studio/backend/app/workflows/result_builder.py:92)：

```python
table_ids = [item["id"] for item in graph.get("tables", [])]
table_labels = [item["label"] for item in SCHEMA if item["id"] in table_ids]
metric_columns = [
    column for column in combined.columns
    if any(term in column for term in ("额", "数", "率", "平均", "目标"))
]
dimension_columns = [column for column in combined.columns if column not in metric_columns]
```

`metric/dimension` 是命名规则的推断；例如英文 alias `sales` 不含这些中文词，会落入 dimension；`目标月份` 含“目标”，可能被当成 metric。`interpretation.table` 是候选 graph 表名的 Schema label 查找，不是 SQL AST 的实际用表列表；`time_range` 是 extraction.time_expressions 拼接，不是执行 SQL 的时间条件校验；assumptions 是固定文案。

**LLM。** [ResponseGenerator.finalize，L41–55](D:/agent_study/askdata_studio/backend/app/querying/response_generator.py:41)：

```python
user = (
    f"问题：{query}\nSQL：{execution.sql}\n列：{execution.columns}\n"
    f"结果数据：{execution.rows[: self.table_row_limit]}\nSchema：{schema_context}\n"
    f"用户保存的分析表格：{analysis_context or '无'}"
)
payload = self.model_client.chat_json(system, user)
return {
    "valid": bool(payload.get("valid", True)),
    "reason": str(payload.get("reason") or "结果检查通过"),
    "title": str(payload.get("title") or "查询结果"),
    "analysis": str(payload.get("analysis") or f"查询返回{len(execution.rows)}行。"),
}
```

System prompt 要求“只能使用真实数值”，属于软约束；这里没有通过确定性程序重新验证每句说明的数值、因果或业务口径。实际配置 `context_table_row_limit=50`（本次运行读取）；[初始化 L22](D:/agent_study/askdata_studio/backend/app/querying/response_generator.py:22) 至少取 1。因此 LLM 可能只看 50 行，而 QueryResult 返回 200 行；两者都可能少于 SQL 总结果行数。

`final.valid` 决定 [ResultBuilder L113–115](D:/agent_study/askdata_studio/backend/app/workflows/result_builder.py:113) 的 status/message；`final.reason` 并没有作为独立 QueryResult 字段复制。SQL 成功不等于模型认为能回答问题，模型认为 valid 也不等于业务口径被验证。

**失败路径不是同一种 provenance。** [ResultBuilder.failed，L142–155](D:/agent_study/askdata_studio/backend/app/workflows/result_builder.py:142) 的 analysis 是 execution.error；结果说明 RuntimeError 经包装后由 [Workflow L345–353](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:345) 生成固定 fallback，仍保留成功 SQL 数据。所以不能笼统地说“所有 analysis 都是 LLM 生成”。

### 2.4 完整 QueryResult 字段来源表

当前 contract 共 **21 个顶层字段**，完整定义见 [QueryResult，L62–83](D:/agent_study/askdata_studio/backend/app/models.py:62)。下表以成功数据库路径为主，明确标注例外；赋值主入口是 [ResultBuilder.completed，L111–138](D:/agent_study/askdata_studio/backend/app/workflows/result_builder.py:111)。

| 字段 | 直接/原始来源与分类 | 未来 Business Signal Engine 使用边界 |
|---|---|---|
| task_id | state；workflow metadata | 请求关联，不是业务事实 |
| status | 执行分支 + final.valid；Mixed control/LLM-influenced | 不能代替纯 SQL success 或结果完整性 |
| route | ResultBuilder 固定路由；workflow metadata | 区分 database_query/data_qa/direct_response，不是指标 |
| message | 程序分支文案，成功路径受 valid 影响；display/control | 不作为计算依据 |
| interpretation | 列名 heuristic、Schema lookup、请求提取、固定文案；Mixed | 只能参考，不能直接作为指标/维度 contract |
| clarification | 暂停路径输入与选项；workflow/LLM-influenced | 不是本次执行结果 |
| steps | Python 固定文本、graph 计数和 state；deterministic/display | 描述流程，不证明每个业务结论正确 |
| sql | combined.sql；执行记录，SQL 内容由模型/调用方产生 | 可审查表达式与口径；安全通过不等于业务正确 |
| columns | cursor 输出名；DB-originated labels | 可定位返回列，不能据名字认定 dtype、unit 或 role |
| rows | cursor 值经转换裁剪；DB-originated data | 最有价值的数据基础，但必须确认完整性、粒度、类型与列唯一性 |
| analysis | final.analysis 通常 LLM；错误/fallback 路径为程序诊断 | 说明文本，不作确定性业务事实 |
| saved | 默认 False；保存动作后置 True；workflow/UI | 与销售等业务事实无关 |
| route_reason | intent.reason 或默认文案；LLM-influenced workflow | 是路由解释，不是业务原因证明 |
| retrieval | public_retrieval 白名单；Schema candidates + scores + diagnostics | 不把相关性分数解释为业务置信度/风险概率 |
| execution_log | MCP trace、执行/异常记录；diagnostic | 可审计，不作为隐式稳定事实表 |
| tool_calls | Workflow 组装的执行摘要；diagnostic/control | 可核验执行数据库、SQL、返回数；row_count 不是全量 |
| result_title | final.title 或默认标题；LLM/display | 不能从标题反推指标语义 |
| analysis_sources | state 中历史分析上下文来源；context/diagnostic | 不是本次 SQL 输出 lineage，不能当新鲜 DB 事实 |
| standalone_query | 请求改写/预处理经 state 传递；user/LLM-influenced | 是意图描述，不是实际过滤条件的确定证明 |
| schema_graph | 执行前 Schema 图；Schema context/diagnostic | 可辅助理解候选源字段，不是输出列确定映射 |
| workflow_mode | state 或默认值；workflow metadata | 路径标签，不是业务结论 |

补充来源：[ResultBuilder.waiting，L58–80](D:/agent_study/askdata_studio/backend/app/workflows/result_builder.py:58)、[AskDataService._payload，L286–297](D:/agent_study/askdata_studio/backend/app/services/askdata_service.py:286)、[AskDataService.save_memory，L203–213](D:/agent_study/askdata_studio/backend/app/services/askdata_service.py:203)、[public_retrieval，L159–166](D:/agent_study/askdata_studio/backend/app/workflows/result_builder.py:159)。

UI 消费已核实：[App.vue L580–612](D:/agent_study/askdata_studio/frontend/src/App.vue:580) 展示 interpretation、数据表和 analysis；其中表格要求 status=completed。故即使 SQL 成功且 rows 仍在，LLM valid=False 仍会导致页面不展示该结果表。这是混合的控制/展示语义，不能把顶层 status 当数据库成功事实。

### 2.5 来源地图与输入结论

```text
CSV → DuckDB cursor
        │ 列名 + 最多200行 + value normalization
        ▼
  SqlExecution(5字段)
        │ + Tool绑定database + len(rows)
        ▼
  DatabaseQueryResult(7字段)
        │ MCP JSON-compatible structured_content
        ▼
  dict → state.mcp_execution → 重建SqlExecution(5字段)
        │                       │
        │                       ├── SQL / columns / rows ─────────────┐
        │                       └── 前N行 → ResponseGenerator         │
        │                                     │ title/analysis/valid │
SCHEMA / hits → schema_graph / retrieval ──────┤                     │
request extraction → time_expressions ────────┤                     │
columns → 列名关键词 → metric/dimension ──────┤                     │
state / tool trace → 日志与流程字段 ──────────┤                     │
                                              ▼                     ▼
                                         ResultBuilder → QueryResult
                                            混合来源结果，不是单一事实表
```

可以作为未来输入基础的是：**经核验的 SQL 结果 columns/rows + 明确的执行范围与业务口径，以及绑定到实际输出的源 Schema 语义**。当前已有前两项的一部分，但尚未提供完整性与输出语义绑定的可靠保证。

不能作为业务事实的是：`interpretation.metric/dimension` 的猜测、LLM analysis/title/valid、retrieval score、候选 Schema 表集合、工作流文案。`schema_graph` 的源字段语义是有价值的 metadata，但不能跨过“是否真的对应本次输出”这一验证边界。

补充历史上下文的信任边界：[SessionContext.analysis_context，L215–260](D:/agent_study/askdata_studio/backend/app/services/session_context.py:215) 既可读取当前 session 的旧 QueryResult，也优先接受 workspace 提供的分析表数据；最多选择五张，行内容再按 table_row_limit 采样。`analysis_sources` 描述这些来源，并不验证它们等于当前数据库的最新事实。

## 3. Current Defects

### 3.1 分类原则

- **A — Correctness bug / 已复现的正确性或可靠性缺陷**：当前代码在明确输入下覆盖数据、改变值精度、错误解释字段或抛出未处理异常。
- **B — Engineering improvement**：整理对象转换、日志与测试结构等可维护性工作；不能只因层数多就称 bug。
- **C — Feature / input capability gap**：当前没有提供的输出语义、完整性证明、业务口径或业务信号能力。它可能阻断下一阶段，但不等于当前所有表格结果已经错误。
- 对条件尚未满足的情况标记“风险”，不把“可能产生错误 SQL”写成“已经观测到真实模型输出错误 SQL”。

### 3.2 A：已确认、可复现的缺陷

| ID | 触发条件与实测结果 | 首次发生位置 | 对业务信号的影响 |
|---|---|---|---|
| A1 同名列覆盖 | `SELECT 1 AS x, 2 AS x` → columns=`['x','x']`，rows=`[{'x':2}]`，success=True | [engine L44–48](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:44)，dict 键重复 | 第一列值不可恢复；计算可能读取错误值，名称列表与行 dict 不一致 |
| A2 Decimal 有损转换 | `CAST(123456789012345678.12 AS DECIMAL(20,2))` → Python float `1.2345678901234568e+17` | [_json_value L148–149](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:148) | 精确 decimal 结果可能发生不可逆精度丢失；这是类型条件触发，不代表当前 CSV 每个金额都已错误 |
| A3 布尔字段未严格解释 | mock `{'valid':'false'}` → bool 非空字符串为 True；最终 completed | [ResponseGenerator L52](D:/agent_study/askdata_studio/backend/app/querying/response_generator.py:52) | LLM 结构偏差导致相反控制语义；不能将 final.valid 当验证证书 |
| A4 合法 JSON 非对象未处理 | mock `[]` → `.get` 触发 AttributeError | [ModelClient L45](D:/agent_study/askdata_studio/backend/app/model_client.py:45)、[ResponseGenerator L52、57–58](D:/agent_study/askdata_studio/backend/app/querying/response_generator.py:52) | SQL 已执行成功，也可能无法完成最终结果封装；没有走已实现的说明失败 fallback |

A3/A4 的定位必须区分：`chat_json()` 有 `dict` 返回类型注解，但 [L41–53](D:/agent_study/askdata_studio/backend/app/model_client.py:41) 直接 `json.loads()`，没有验证 JSON 根节点一定是 object；类型注解不执行运行时校验。`bool/str` 强制转换也不等于业务字段校验。

异常边界证据：[ResponseGenerator L57–58](D:/agent_study/askdata_studio/backend/app/querying/response_generator.py:57) 只捕获 RuntimeError；[Workflow L345](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:345) 和 [AskDataService.submit L94](D:/agent_study/askdata_studio/backend/app/services/askdata_service.py:94) 捕获 PipelineStageError。不能据此保证 AttributeError 也会转成正常 QueryResult。

### 3.3 截断与元数据：确认损失，但准确界定问题

**200 行上限本身是明确设计**：[数据库 Tool 的参数说明 L15–18](D:/agent_study/askdata_studio/backend/app/mcp_runtime/tools/database_tools.py:15) 已写“最多返回200行”。问题是执行 contract 没有告诉上层这批 rows 是否完整。

只读 500 行 probe 观察：

```text
SQL 结果总行数（probe 构造已知）       500
cursor.fetchmany(201) 实际读取        201
此时 cursor 还可读取                 299
engine 最终返回 rows                200
DatabaseQueryResult.row_count       200 = len(rows)
truncated / total_result_count      没有该字段
```

证据：[engine L43–49](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:43)、[DatabaseQueryResult L21–28](D:/agent_study/askdata_studio/backend/app/mcp_runtime/schemas.py:21)。第 201 行只是局部数据，没有产生向上传输的布尔信号；200 行结果既可能“恰好 200”，也可能“500 中的前 200”。当前 contract 区分不了。

这对 Business Signal Engine 是 **结果完整性阻断项**。不过不能把 SQL 聚合本身也说成“只对 200 条订单求和”：数据库先执行 SQL，再 fetch 输出行。`SELECT SUM(paid_amount)` 可以计算整张授权源表；风险在于**对已裁剪的明细 rows 再计算总和/份额/排名**，或者 SQL 分组结果超过 200 行。本文的只读基线在数据库中先聚合，输出少于 200 行。

Metadata probe：

```text
('amount', DECIMAL(8,2), None, None, None, None, None)
('d',      DATE,         None, None, None, None, None)
```

当前 API 实测提供 name 和 type_code；display_size/internal_size/precision/scale/null_ok 的独立槽位为 None。DECIMAL 的类型对象自身包含精度/小数位信息，但 engine 只取 item[0]。所以应写“type_code 未保留”，而不是编造“DuckDB 提供了有效 nullability 后被丢弃”。

当前真实 CSV probe 也确认：`order_id` 为 BIGINT、`paid_amount` 为 DOUBLE、`order_date` 为 DATE；`sales_targets.target_month` 为 VARCHAR。静态 Schema 对 target_month 标“日期”，并不让 YYYY-MM 自动成为数据库 DATE。

### 3.4 B / C 与条件性风险清单

| ID / 分类 | 已确认事实 | 为什么不是直接认定所有当前结果都错 |
|---|---|---|
| C1 完整性信息不足 | 200 行上限、无 truncated/总结果行数，见 3.3 | 小结果与数据库先聚合的结果可能完整；任意结果作为全量统计输入则不安全 |
| C2 physical metadata 不贯通 | SqlExecution/QueryResult 没有 dtype；engine 只保留名称 | 展示普通表格未必需要 dtype，可靠数值/日期运算则需要明确类型依据 |
| C3 输出 lineage/语义绑定未建立 | graph 是执行前候选 Schema；没有 output alias/expression→source mapping | 不应称“cursor 原本提供了完整 lineage 后丢了”；这是尚未建立的能力 |
| C4 metric/dimension 只有 heuristic | 列名包含额/数/率/平均/目标即 metric | 用于展示解释是既有行为；未来把它当确定规则输入才会跨越可信边界 |
| C5 目标 join 粒度只部分表达 | 关系结构只写 region，月份对齐放 description；详见 4.3 | 数据可复现 fanout 条件，但本次未调用模型，不能断言某条真实模型 SQL 一定漏了月份 |
| C6 信号计算与规则缺失 | 当前执行节点是 finalize→ResultBuilder，没有 Business Signal Engine 或 typed signal 输出 | 是下一阶段功能目标，不是 Text-to-SQL 必然应有的已实现功能 |
| C7 业务源数据/metadata 不足 | 无成本、件数、账期；无单位币种/风险阈值等显式字段 | 数据能力和规则定义不能靠解释文本自动补齐 |
| B1 多次对象装配 | 五字段对象→七字段→dict→五字段→QueryResult | 这是当前分层接口；结构整理属工程工作，具体字段遗漏另行看影响 |
| B2 执行与展示状态混合 | SQL success 与 LLM valid 共用最终 status；前端按该 status 显示表格 | 是实际产品控制语义；先界定来源，不能未经产品约定就把所有 valid=False 判 bug |
| B3 日志与核心字段分散 | database/row_count/success 等可在嵌套 trace 中存在，顶层没有独立字段 | 审计可读但不是稳定分析接口；日志整理由下一阶段评估，不能以此构造隐式业务事实依赖 |

C6 的依据不仅是名称搜索：本次核对了 [实际执行出口 L337–365](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:337)、[结果构造 L84–156](D:/agent_study/askdata_studio/backend/app/workflows/result_builder.py:84) 和 [完整返回模型 L62–83](D:/agent_study/askdata_studio/backend/app/models.py:62)；没有独立业务信号计算/结果阶段。对业务源码和测试中的 BusinessSignal / business_signal / SignalEngine 搜索亦无命中。仓库之外是否有扩展，当前无法静态确认。

### 3.5 可重复的最小只读核验入口

以下是报告中的复现说明，不是新增到业务目录的测试或修复代码。可在 backend 工作目录通过现有 Python 虚拟环境运行，`-B` 禁止写字节码；它只读 CSV、创建临时内存 View，不创建数据文件，不调用 LLM。

```python
from app.querying.duckdb_engine import DuckDbEngine

engine = DuckDbEngine()
print(engine.execute("askdata_mock", "SELECT 1 AS x, 2 AS x"))
print(engine.execute(
    "askdata_mock",
    "SELECT CAST(123456789012345678.12 AS DECIMAL(20,2)) AS amount",
))

many = """WITH RECURSIVE nums(n) AS (
    SELECT 1 UNION ALL SELECT n + 1 FROM nums WHERE n < 500
) SELECT n FROM nums ORDER BY n"""
with engine.connect("askdata_mock") as connection:
    cursor = connection.execute(many)
    fetched = cursor.fetchmany(201)
    print(len(fetched), len(cursor.fetchall()))  # 201, 299
print(len(engine.execute("askdata_mock", many).rows))  # 200
```

这类 probe 证明的是处理规则及触发条件；它没有证明真实业务数据曾被用户以相同 SQL 查询，也没有验证真实 LLM 在某个问题上的输出。

A3/A4 的 mock 复现如下。FakeModel 不创建真实 ModelClient、不发网络请求；最后一行单独用真实 `chat_json` 方法配假 `chat`，验证 JSON 根节点未限制为对象：

```python
from types import SimpleNamespace
from app.querying.models import SqlExecution
from app.querying.response_generator import ResponseGenerator
from app.workflows.result_builder import ResultBuilder
from app.model_client import ModelClient

execution = SqlExecution("SELECT 1 AS x", True, ["x"], [{"x": 1}])
for payload in ({"valid": "false"}, {"valid": False}, []):
    fake = SimpleNamespace(chat_json=lambda system, user: payload)
    try:
        final = ResponseGenerator(fake).finalize("test", execution, "", "")
        result = ResultBuilder.completed(
            {"task_id": "readonly-probe"}, [execution], execution, final, [], []
        )
        print(repr(payload), final["valid"], result.status, result.rows)
    except Exception as exc:
        print(repr(payload), type(exc).__name__)

parsed = ModelClient.chat_json(
    SimpleNamespace(chat=lambda system, user: "[]"), "", ""
)
print(type(parsed).__name__)
```

实测依次为：`'false' → True/completed`、`False → False/failed`（两者 rows 都在）、`[] → AttributeError`，最后 `list`。这些例子证明的是解析/控制边界，不是模型真实输出概率。

## 4. Available Business Signals

### 4.1 Database Business Capability：实体、粒度、时间覆盖

只有一个业务数据库 `askdata_mock`。两张订单表是同一业务实体在不同时间范围的存储；客户、产品和地区月度目标是其他业务对象，地区/品类/负责人不是独立的主数据表。

| Table | 业务对象 / 主键 | 当前 CSV 行数 | 实测时间覆盖 / 粒度 | 源码证据 |
|---|---|---:|---|---|
| orders_current | 当前订单明细；order_id | 240 | 2026-08-01～08-31；一行一个订单，含一个 customer_id、product_id | [SCHEMA L43–52](D:/agent_study/askdata_studio/backend/app/database.py:43) |
| orders_history | 历史归档订单；order_id | 480 | 2026-06-01～07-31；相同订单结构 | [L53–62](D:/agent_study/askdata_studio/backend/app/database.py:53) |
| customers | 客户主数据；customer_id | 30 | 客户名称、等级、地区；没有历史版本列 | [L63–77](D:/agent_study/askdata_studio/backend/app/database.py:63) |
| products | 产品主数据；product_id | 12 | 产品名称、品类；没有数量/成本列 | [L78–91](D:/agent_study/askdata_studio/backend/app/database.py:78) |
| sales_targets | 月地区销售计划；target_id | 8 | 2026-07/08 × 华东/华南/华北/西南 | [L92–107](D:/agent_study/askdata_studio/backend/app/database.py:92) |

这些行数和覆盖期由本次读取当前 CSV 验证，不只是读取生成器参数。对应生成依据：[seed_demo_data，L16–65](D:/agent_study/askdata_studio/backend/app/demo_data.py:16)：current 固定生成 8 月 240 行，history 生成 6、7 月 480 行，targets 固定两个目标月份。不能认为该数据按系统时间自动更新。

本次快照一致性核验还发现：

- 合计 720 个 order_id 无重复；客户、产品主键无重复；目标 `(target_month, region)` 当前无重复。
- 订单 customer/product 外键均能找到主表记录。
- 当前订单 region 与客户 region 全部相等；订单 category 与产品 category 全部相等。
- 720 条订单中：已支付 634、已取消 49、已退款 37；非已支付的 paid_amount 非零记录为 0。

这是**当前样本事实**，不是运行时数据库强制约束。SCHEMA 中主键只是 metadata，CSV View 不自动建立这些约束；尤其目标只声明 target_id，不声明 `(month,region)` 唯一。当前一致也不证明客户地区与订单销售地区永远同义，或系统存在历史维度快照机制。

### 4.2 完整字段语义矩阵

字段实际结构由 [_field，L9–26](D:/agent_study/askdata_studio/backend/app/database.py:9) 创建：name、label、type、description、aliases、role、aggregation；不传 aggregation 时是 `none`。role/aggregation 是源 Schema 的业务提示，不是任意 SQL 输出列可以安全 SUM/AVG 的证明。

**两张订单表共享同一 ORDER_FIELDS：以下 9 行分别适用于 orders_current 和 orders_history，共 18 个表字段。** 证据：[ORDER_FIELDS，L29–39](D:/agent_study/askdata_studio/backend/app/database.py:29)，表定义分别在 L51/L61 引用。

| table | field | role | aggregation | aliases（完整） | 稳定定义 / 可支持信号 |
|---|---|---|---|---|---|
| 两张订单表 | order_id | identifier | count | 订单号、订单数、笔数 | 订单唯一编号；订单数、每订单平均实付，不能叫商品件数 |
| 两张订单表 | region | dimension | group | 地区、区域、大区 | 订单归属销售大区；区域变化、区域目标完成 |
| 两张订单表 | category | dimension | group | 品类、类别、产品类型 | 订单产品业务品类；品类实付贡献 |
| 两张订单表 | order_amount | metric | sum | 应收金额、原价金额 | 优惠/退款处理前订单原始金额；不是实际收入或应收账款余额 |
| 两张订单表 | paid_amount | metric | sum | 销售额、成交额、收入、实收 | 实际支付金额；目标完成、客户/产品/地区贡献的候选度量 |
| 两张订单表 | status | filter | group | 支付状态、退款状态、取消状态 | 当前订单状态；状态订单数/占比，不是状态变化事件 |
| 两张订单表 | order_date | time | group | 时间、日期、成交日期 | description 明确订单创建日期；月度下单口径，不是支付/退款发生时间 |
| 两张订单表 | customer_id | foreign_key | none | 客户ID、企业编号 | 客户关联键；按客户聚合 |
| 两张订单表 | product_id | foreign_key | none | 产品ID、商品编号 | 产品关联键；按产品聚合 |

逐字段证据与上表顺序一致：[L30–38](D:/agent_study/askdata_studio/backend/app/database.py:30)。alias 用于表达匹配，并不覆盖 description 的具体定义；“成交日期”alias 不能把订单创建日期变成付款日期。

| table | field | role | aggregation | aliases（完整） | 稳定定义 / 可支持信号 |
|---|---|---|---|---|---|
| customers | customer_id | identifier | none | 客户ID、企业编号 | 客户主键、客户级信号身份 |
| customers | customer_name | dimension | group | 客户、企业名称、公司名称 | 展示名称，不用名称替代 ID 关联 |
| customers | customer_level | dimension | group | 客户层级、客户级别 | 战略/重点/普通分层；分层贡献和变化，不是风险等级 |
| customers | region | dimension | group | 客户区域、所在地区 | 注册/主要经营区域；与订单销售归属区域定义不同 |
| products | product_id | identifier | none | 产品ID、商品编号 | 产品主键 |
| products | product_name | dimension | group | 产品、商品、服务名称 | 产品贡献展示名称 |
| products | category | dimension | group | 产品线、品类、产品类型 | 产品目录品类；可做品类汇总 |
| sales_targets | target_id | identifier | none | 计划编号 | 目标记录标识 |
| sales_targets | target_month | time | group | 月份、考核月份 | 月度目标期间，格式 YYYY-MM；本次 DuckDB 实际推断 VARCHAR |
| sales_targets | region | dimension | group | 地区、区域、大区 | 目标归属地区 |
| sales_targets | target_amount | metric | sum | 目标额、业绩目标、销售预算 | 目标金额；必须在合法月地区粒度使用 |
| sales_targets | owner_name | dimension | group | 负责人、区域经理 | 目标负责人展示/汇总维度，不证明其负责每条历史订单 |

逐字段证据：[customers L72–75](D:/agent_study/askdata_studio/backend/app/database.py:72)、[products L87–89](D:/agent_study/askdata_studio/backend/app/database.py:87)、[sales_targets L101–105](D:/agent_study/askdata_studio/backend/app/database.py:101)。两张订单表 18 + 客户 4 + 产品 3 + 目标 5 = **30 个表字段实例**。

当前没有显式 unit/currency、指标口径版本、目标复合键约束、关系基数、期间是否结算完成、风险阈值等 metadata。没有这些并不使 paid_amount 失去基本定义，但会限制跨指标比较、自动异常标签和通用计算规则。

### 4.3 关系、粒度与金额口径边界

普通关联来自 [RELATIONS，L111–139](D:/agent_study/askdata_studio/backend/app/database.py:111)：

```text
orders_current.customer_id → customers.customer_id
orders_history.customer_id → customers.customer_id
orders_current.product_id  → products.product_id
orders_history.product_id  → products.product_id
```

目标关系来自 [L140–155](D:/agent_study/askdata_studio/backend/app/database.py:140)，其中当前订单部分的真实定义为：

```python
{
    "left_table": "orders_current",
    "left_field": "region",
    "right_table": "sales_targets",
    "right_field": "region",
    "description": "当前销售与月度目标按地区进行业务关联，月份需额外对齐",
    "relation_type": "business",
}
```

关键判断：

1. 结构化 join key 只有 region，月份对齐仅在文字里；源码并非完全没有提醒，但也没有把复合条件/基数编码完整。
2. 本次数据中每地区有两个月目标；仅 region 关联会把 current 的 240 行扩为 480 行。这个可复现条件不等于本次调用了模型并观察到错误 SQL。
3. 即使补上月份，若把同一目标金额贴到每条订单后 SUM，目标仍会按订单数重复。目标完成信号的必要口径是：**销售先聚合到月×销售区域，再与同粒度唯一目标对齐**。
4. 跨月订单来自 current/history 两个同构集合；当前无重叠可用明确字段 UNION ALL。不能把两张事实表按相同客户或产品直接 join 后汇总金额。将来归档有重叠时，当前样本的“无重复”不能继续当无条件前提。

金额/状态生成规则见 [_orders，L127–150](D:/agent_study/askdata_studio/backend/app/demo_data.py:127)：

```python
status = randomizer.choices(
    ["已支付", "已取消", "已退款"], weights=[84, 9, 7], k=1
)[0]
paid_amount = (
    order_amount * randomizer.uniform(0.86, 1.0) if status == "已支付" else 0
)
```

因此 demo 中已取消/已退款订单实付为 0；只有状态快照，没有退款金额与退款日期。按 order_date 求和得到的是“订单创建期间所归属订单的当前实付金额”，不能自动当成会计收入确认或当期现金流。原始订单金额减实付金额混有折扣、取消与退款状态因素，不能直接命名为退款额、欠款或利润。

### 4.4 数据可计算性与业务判断是两件事

第一批信号统一以下边界：期间用明确的 2026-07/08，不用容易漂移的“现在/本月”；金额用 paid_amount 定义；区域用订单 region；比较保持相同状态与范围；分母为零/缺失时不输出普通增长率；缺期不当作真实零业务；权限不允许的数据不参与计算。

下节中的“需要 metadata”区分两类：已有数据可以算数值，但业务政策尚需明确；或根本缺原始数据，新增几个名称/标签不能使其可计算。这里不设计新字段或接口。

### 4.5 Business Signal Candidate Analysis

**以下是有源码数据依据的候选，不是项目当前已存在的 Signal implementation。** “适合 Agent 输出”指先确定性计算、再让 Agent 表达事实；不是让模型从 50 行样本中猜数值。所需原始字段均在 4.2 的完整 Schema 矩阵中，表关系依据见 4.3。

| Signal Name | Business Meaning | Required Tables | Required Fields | Computation Logic | 是否需要新增/明确 metadata | 是否适合 Agent 输出 |
|---|---|---|---|---|---|---|
| S1 月度地区目标完成 | 同月同销售区域的实付相对目标 | 期间对应的订单表；sales_targets | 订单 paid_amount/order_date/region；目标 target_month/region/target_amount；可选 owner_name | 月地区实际 A；唯一目标 T；完成率 A/T，差额 A−T；先聚合再对齐，T=0/缺目标不生成普通比率 | 无需新增原始交易数据；需确认实付与目标同口径同单位、期间、目标粒度唯一性、零分母政策；“进度落后”另需政策 | 高；可输出实际/目标/差额/比例及期间；未确认口径前只作 demo 比较 |
| S2 区域销售环比变化 | 连续可比月份的地区实付变化 | orders_current + orders_history | region/paid_amount/order_date；可选 status | 同区域聚合 A_t、A_prev；delta=A_t−A_prev，rate=delta/A_prev；prev=0单列处理 | 不缺原始数据；需固定可比期间、覆盖范围、状态口径；异常阈值尚不存在 | 高；适合事实增减，不支持未经证据的下降原因 |
| S3 客户实付下降线索 | 哪些客户本期贡献低于前期 | 两张订单表 + customers | 订单 customer_id/paid_amount/order_date；客户 customer_id/customer_name/customer_level | 客户级两期聚合；保留前期有实付但本期为0客户；delta/rate，前期0另行处理 | 数值可算；风险标签需观察窗、最小基数和阈值；客户等级不是风险等级 | 有条件；称“下降线索”，不能宣称流失/信用风险 |
| S4 客户近期未成交线索 | 截至固定分析日的已支付订单间隔 | 两张订单表 + customers | 订单 customer_id/order_date/status；客户 customer_id/customer_name/customer_level | 只看 as_of 之前且当前快照标记已支付的订单，按客户 MAX(order_date)，计算距 as_of 天数；无历史记录单列 | 需 as_of、窗口/阈值和历史覆盖说明；只有3个月历史，不能恢复历史时点订单状态 | 有条件；可以说明观测期内未成交，不可以断言客户已流失 |
| S5 客户取消/退款状态占比 | 订单创建窗口内的当前状态构成 | 期间订单表；可加 customers | order_id/customer_id/status/order_date；客户展示字段 | 客户窗口内特定状态订单数/窗口总订单数；明确计数与最小样本 | 不缺计数数据；需窗口、样本门槛；没有 refund_date/refund_amount | 有条件；只能是状态占比，不能写“当月退款金额率” |
| S6 产品实付贡献/排名 | 产品贡献多少实付、占完整范围多少 | 期间订单表 + products | 订单 product_id/paid_amount/order_date；产品 product_id/product_name/category | 按产品聚合 A_p；份额=A_p/所有授权范围产品实付；先完整聚合/算分母，再选 Top N | 不缺原始数据；需明确期间、分母范围、金额口径与单位 | 高；最适合首批。不能对裁剪后的 Top N 分母算全市场份额 |
| S7 产品实付变化 | 产品在可比月份的实付增减 | 两张订单表 + products | 订单 product_id/paid_amount/order_date；产品 product_id/product_name/category | 产品×月份聚合，对齐产品ID，再求 delta/rate；零基期/无本期分开 | 不缺基本数据；需可比窗口和零基数政策；异常判断需阈值 | 高；描述增减，不做因果归因 |
| S8 产品每已支付订单平均实付 | 某产品对应已支付订单的平均金额 | 期间订单表 + products | 订单 product_id/order_id/paid_amount/status/order_date；产品 product_id/product_name | 已支付实付合计 / 已支付 distinct order_id 数；保持每订单一产品前提 | 当前数据模型可算；需确定状态、窗口、计数语义；没有 quantity | 高，但必须叫“每订单平均实付”，不能叫件单价或平均商品售价 |

上表中的展示字段采用真实 `customer_name/product_name`；关联身份采用 `customer_id/product_id`，不以展示名称替代主键。

证据聚合：[ORDER_FIELDS](D:/agent_study/askdata_studio/backend/app/database.py:29)、[customers](D:/agent_study/askdata_studio/backend/app/database.py:63)、[products](D:/agent_study/askdata_studio/backend/app/database.py:78)、[sales_targets](D:/agent_study/askdata_studio/backend/app/database.py:92)、[demo 状态/金额口径](D:/agent_study/askdata_studio/backend/app/demo_data.py:127)。

### 4.6 当前明确不支持的业务判断

| 想输出的结论 | 当前缺什么 | 判断 |
|---|---|---|
| 产品利润、毛利率 | 成本、费用、采购/结算等原始数据 | 不是只加 metadata 就能算 |
| 商品销量（件）、单位售价 | quantity、计量单位、订单商品行 | order_id count 只能代表订单数 |
| 客户违约/逾期/信用风险 | 应收余额、到期日、账期、合同/偿付信息 | 已有订单取消/退款不等于信用违约 |
| 已确认客户流失 | 客户生命周期、业务定义/标签、足够观察期 | 本数据只能产出交易减少或未成交线索 |
| 当期真实退款金额/退款时间趋势 | refund_amount/refund_date/事件历史 | 当前 status 与原始 order_amount 不能替代 |
| 产品库存/缺货/周转 | 库存、入出库事件 | 现有 Schema 无此实体 |
| 销售下滑的确定原因 | 因果所需证据，例如活动、价格政策、渠道或外部因素 | 现有相关增减不能证明原因 |

依据是 4.2 已完整列出的当前 30 个表字段及 [_orders 的生成范围 L115–153](D:/agent_study/askdata_studio/backend/app/demo_data.py:115)，不是根据文件名推测。这里不否认未来可接新数据，只说明当前 baseline 的边界。

### 4.7 固定数据快照上的只读数值 baseline

这是为后续对照建立的**人工明确口径 + 数据库聚合结果**，不经过 LLM。选择 2026 年 7 月与 8 月，避免系统已到 9 月的“本月”歧义。它是合成演示数据中的描述性结果，不是现实经营结论。

核验口径：

- `orders_current UNION ALL orders_history` 按相同显式字段合并；本次已核对无重复 order_id。
- 按 `order_date` 所在自然月计算 `SUM(paid_amount)`。当前非已支付 paid_amount=0，因此在当前文件快照上与仅已支付求和一致；不是对所有未来数据的无条件保证。
- 为使本次 CSV 两位小数金额的基线可重复，探针在聚合前 `CAST(paid_amount AS DECIMAL(18,2))`。这只是探针口径；没有修改生产 SQL、CSV 推断类型或 engine 的 Decimal→float 行为。
- 金额表不标币种/单位，因为当前 metadata 未给出。目标比例按 demo 中二者可比较的候选口径演示；真实业务仍需确认相同单位与收入口径。
- 所有全量汇总在数据库完成后再 fetch。客户/产品 Top 3 是排序后的展示子集，不用于推导完整总体分母。

**订单月份全量汇总：**

| 月份 | 订单行数 | 实付合计（CSV 数值尺度） |
|---|---:|---:|
| 2026-06 | 231 | 14,096,078.76 |
| 2026-07 | 249 | 16,145,060.58 |
| 2026-08 | 240 | 15,658,626.69 |

**S1/S2：2026-08 区域目标比较与 7→8 月变化，比例四舍五入到两位小数：**

| 订单销售区域 | 7月实付 | 8月实付 | 8月目标 | 8月完成率 | 7→8月变化率 |
|---|---:|---:|---:|---:|---:|
| 华东 | 3,767,803.15 | 4,292,183.75 | 2,200,000.00 | 195.10% | +13.92% |
| 华北 | 4,712,413.08 | 3,379,043.36 | 1,600,000.00 | 211.19% | −28.29% |
| 华南 | 3,623,635.97 | 3,513,112.52 | 1,800,000.00 | 195.17% | −3.05% |
| 西南 | 4,041,208.38 | 4,474,287.06 | 1,300,000.00 | 344.18% | +10.72% |

学习重点：华北同时出现“按候选口径超过目标”和“实付环比下降”。这是两个不同问题的确定性比较，不是矛盾；但“下降异常”“负责人有问题”等判断没有现成规则/证据。完成率偏高也不能直接宣布生产业务超额优秀，这是固定 demo 数值。

**S3：7 月基期实付 > 0，按变化率升序的前三个客户样例：**

| customer_id | 7月实付 | 8月实付 | 变化率 | 允许的陈述 |
|---|---:|---:|---:|---|
| 117 | 870,395.35 | 94,085.77 | −89.19% | 该客户在已选两个月的实付下降 |
| 114 | 624,806.76 | 206,423.27 | −66.96% | 同上，不构成违约/流失认定 |
| 111 | 999,445.32 | 359,474.91 | −64.03% | 同上，风险阈值未定义 |

**S6：8 月按产品实付合计降序的前三个产品：**

| product_id | 8月实付合计 |
|---|---:|
| 102 | 1,725,561.53 |
| 106 | 1,723,739.46 |
| 104 | 1,655,275.45 |

这些数字仅证明既有数据可以支持候选信号计算。当前生产 QueryResult 没有因此多出 signal 列表，也没有验证模型会为任意自然语言问题选择同样的 SQL。

### 4.8 数值 baseline 的复算逻辑

下面为本次区域 probe 的等价完整只读 SQL，保留实际字段名。可通过 `DuckDbEngine.connect("askdata_mock")` 的连接执行；它不写任何表或文件：

```sql
WITH all_orders AS (
    SELECT region, paid_amount, order_date FROM orders_current
    UNION ALL
    SELECT region, paid_amount, order_date FROM orders_history
), sales AS (
    SELECT strftime(order_date, '%Y-%m') AS month,
           region,
           SUM(CAST(paid_amount AS DECIMAL(18,2))) AS actual
    FROM all_orders
    GROUP BY month, region
)
SELECT t.target_month,
       t.region,
       p.actual AS july,
       s.actual AS august,
       CAST(t.target_amount AS DECIMAL(18,2)) AS target,
       ROUND(s.actual / NULLIF(t.target_amount, 0) * 100, 4) AS attainment_pct,
       ROUND((s.actual - p.actual) / NULLIF(p.actual, 0) * 100, 4) AS mom_pct
FROM sales_targets t
LEFT JOIN sales s
  ON s.month = t.target_month AND s.region = t.region
LEFT JOIN sales p
  ON p.month = '2026-07' AND p.region = t.region
WHERE t.target_month = '2026-08'
ORDER BY t.region;
```

客户 probe：合并订单后按 customer_id 分组，使用两个半开日期窗 `[2026-07-01,2026-08-01)`、`[2026-08-01,2026-09-01)` 的条件 SUM，保留 july>0，按 `(august−july)/july` 排序取前三。产品 probe：current 按 product_id 分组 SUM，同样 CAST 后排序取前三。月份 probe：合并订单后按 `strftime(order_date,'%Y-%m')` 分组 COUNT(*) / SUM。这里没有创建 signal 模块，只有调查计算。

## 5. Recommended Minimal Improvement Scope

### 5.1 建议下一阶段收敛为三组工作，而非大型 BI 改造

以下是范围建议与验收目标，不是本轮实施承诺、接口设计或代码 patch。

| 顺序 / 范围 | 最小目的 | 为什么必须在此处处理 | 可观察的验收问题 |
|---|---|---|---|
| P0：执行结果与说明边界的已确认缺陷 | 处理 A1 同名列覆盖、A2 精确值损失条件、A3/A4 LLM 返回类型处理 | 信号层不能建立在悄悄覆盖/改变的值上，说明失败也不应未经处理地中断已成功结果 | 重复列输入是否显式处理且不静默丢值？精确数值是否满足声明精度？非对象/错误布尔是否有受控行为？ |
| P0：结果完整性与输入资格 | 明确结果是完整聚合、完整明细、受限子集还是未知；不能把展示限额等同全量 | 200 行上限 + 无完整性信息会使后续总和/份额错误 | 199、200、201、500 输出行能否正确区分？SQL 内全量聚合与返回明细后聚合能否区分？ |
| P1：首批信号的口径与实际输出对应关系 | 为选定信号核实时间、源字段、单位/币种、状态、粒度和分母；区分 Schema context 与已确认映射 | 只保存 role 或 alias，不能证明一列实际是可求和的销售额 | 是否能解释每个输出值的来源表达式、所属月份、销售区域、目标对齐条件？ |
| P1：先覆盖少量确定性描述性信号 | 优先 S1 月地区目标完成、S2 区域变化、S6 产品贡献 | 三者既有数据支持且比“客户风险”更少依赖未定义业务判断 | 固定 7/8 月数据下结果能否与本报告只读基线一致？缺目标/零基数/受限权限时是否明确不作普通比较？ |
| P2：有条件加入客户线索 | S3/S4/S5 需要观察窗、最小样本/基数、风险定义 | 当前只有交易快照和有限历史，不能从下降直接推出流失 | Agent 是否只表达证据支持的“线索”，并明确期间和样本边界？ |
| 按需 B：有限工程整理 | 仅整理上述范围真正涉及的对象转换、错误路径、验证用例 | 结构好看不等于事实可靠；不应为了层数多先重写整个 Workflow/MCP | 是否能降低字段语义漂移且不扩大改造到无关链路？ |

建议第一批关注“发生了什么、算出来多少”，不把“异常严重度、根因、客户确定风险”提前并入同一目标。尤其 S1 的完成率和 S2 的变化率是两个不同口径，不能混成一个笼统的经营健康评分。

### 5.2 Business Signal Engine 的当前输入充分性

| 未来要判断的问题 | 当前基础是否足够 | 原因 / 可靠性边界 |
|---|---|---|
| 某个返回值是不是 Python int/float/str | 基本足够识别当前表示 | rows 可观察序列化表示，但这不等于数据库类型 |
| 某列真正是不是数据库 numeric/date | 部分足够，通用判断不足 | 已知源 Schema/审阅 SQL 可辅助；输出 dtype 未贯通，DATE 和 VARCHAR 都可能变 str |
| 能否对某列 SUM | 不足以对任意 QueryResult 自动判断 | ID 可是 int；比率、均值、累计量也可为 float；是否可加取决于语义和粒度 |
| 能否 AVG | 部分足够 | 明确原始订单度量可按口径算；已有分组平均值再平均不一定正确，当前无普适语义保证 |
| 两列能否安全相除 | 不足以通用判断 | 数值类型兼容之外，还要同期间、同范围、合适单位/业务含义及零分母政策 |
| 是否为 metric / dimension | 候选源语义部分足够，输出绑定不足 | SCHEMA role 是源字段 metadata；Interpretation 是名称 heuristic |
| 是否截断、是否完整 | 不足 | 没有完整性字段；len(rows)=200 不可区分恰好200与被裁剪 |
| 构造固定月区域实付聚合 | 有条件足够 | 当前 CSV、显式 SQL 和粒度可核验；不能因此放宽任意返回结果的输入资格 |
| 输出“某客户确定流失/违约” | 不足 | 原始业务证据与风险定义都不够；分析文本不能补齐 |

必须区分三层信息：

| 层次 | 本项目中的真实例子 | 不能混同的地方 |
|---|---|---|
| Physical type | 当前 CSV 推断 paid_amount=DOUBLE、order_date=DATE；probe 可返回 DECIMAL(20,2) | SCHEMA 写“数值”不等于物理 DOUBLE；SQL 表达式可改变输出 dtype |
| Serialization type | DATE→ISO str、Decimal→float；整数通常仍是 int，NULL 是 None/JSON null | str 不等于 VARCHAR，float 不等于原始 DOUBLE；全 NULL/空结果更不能靠样本恢复 dtype |
| Schema/business semantic type | paid_amount 为 metric/sum；region 为 dimension/group；order_date 为 time/group | numeric 不等于 metric；源字段 role 不等于任意输出 alias 的可靠角色；SUM 提示不能消除 join 重复 |

对于用户重点字段，最小可靠性边界可归纳为：

```text
rows / columns / sql  → 候选执行数据基础，先核验口径与完整性
schema_graph          → Schema context，可辅助但不是输出 lineage
retrieval             → 相关性候选与检索诊断，不是业务事实
interpretation        → 混合解释信息，metric/dimension 为 heuristic
analysis              → 通常为 LLM 文本，失败时也可能为诊断文案
```

### 5.3 明确不纳入本轮与建议首批范围的内容

本轮只完成 Read → Trace → Compare → Record，没有修复上述缺陷。

建议首批不扩展到：多库联邦计算、完整语义层/OLAP 系统、全指标目录、自动根因归因、CRM 风险模型、库存利润体系，也不因为需要 Signal 就重写 MCP、检索算法或 SQL Agent。本次也没有设计新 Repository、Result Contract v2 或 Derive API。

需要业务方确认、当前源码不能替代的决定是：实际/目标是否同单位与同口径、何时算已完成期间、客户风险的观察窗和阈值、缺期/零基数如何表达。**没有确认就只能输出限定条件下的计算事实或线索，不能自动升级成已验证业务结论。**

### 5.4 基线数据指纹与复核范围

以下为本次读取的 CSV SHA-256，用于判断未来数据是否还是本报告的同一快照。它不是代码版本号，也不是对真实业务数据完整性的认证。

| 文件 | SHA-256 |
|---|---|
| [orders_current.csv](D:/agent_study/askdata_studio/backend/data/databases/askdata_mock/orders_current.csv) | `59454FA149ECAEF21E348C7550566FB9AE2B3C824355455A650DC26DB6AD2D52` |
| [orders_history.csv](D:/agent_study/askdata_studio/backend/data/databases/askdata_mock/orders_history.csv) | `3958154A376B70350ADE9194B87D6B2E3A66519511FB4F9086E6B3E0E197E920` |
| [customers.csv](D:/agent_study/askdata_studio/backend/data/databases/askdata_mock/customers.csv) | `6ACA5F425DFB6A7D1313091912242D1B6D90EADA4A7D53457B8CA11A00323A37` |
| [products.csv](D:/agent_study/askdata_studio/backend/data/databases/askdata_mock/products.csv) | `7B1B19AEA42257CE48B83B58598E9043FDA0FC0129F65D0D5EDADEF8ED321AF4` |
| [sales_targets.csv](D:/agent_study/askdata_studio/backend/data/databases/askdata_mock/sales_targets.csv) | `B68EB556FC58A0B17EE2095F8E2B4AA293AE4B84834DC10F055C24B175A3086D` |

实际核验覆盖：CSV 行数/期间/键关系、日期与数值类型、同名列、Decimal、500行裁剪、LLM mock 的 boolean/JSON 根节点形状，以及候选信号只读聚合。没有真实线上数据库/模型调用，没有跑需要写库或外部服务的端到端全测试；因此不报告模型准确率或生产覆盖率。

写作前后 SHA-256 对照：本次纳入核验的 59 个后端业务/测试 Python 文件及业务 CSV 文件均无变化、无缺失。实际新增交付物仅为本报告，未执行修复。

### 5.5 Source Evidence Index

下列行号均依据本次当前源码。主文各关键段已链接到具体位置；本索引用于回 IDE 学习。

| 文件 | 类 / 函数、当前行号 | 在本报告中的证据作用 |
|---|---|---|
| [duckdb_engine.py](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:33) | DuckDbEngine.execute L33–51；connect L54–73；_validate_sql L75–127；_json_value L144–150 | 执行、CSV数据源、类型转换、裁剪、权限、数据损失 |
| [querying/models.py](D:/agent_study/askdata_studio/backend/app/querying/models.py:7) | SqlExecution L7–13 | 五字段执行 contract |
| [database_tools.py](D:/agent_study/askdata_studio/backend/app/mcp_runtime/tools/database_tools.py:12) | SqlStatement L12–21；build_database_query_tool/query_database L25–46 | 200行说明、执行包装、database/row_count 来源 |
| [mcp_runtime/schemas.py](D:/agent_study/askdata_studio/backend/app/mcp_runtime/schemas.py:21) | DatabaseQueryResult L21–28 | 七字段 MCP 工具结果 |
| [mcp_runtime/client.py](D:/agent_study/askdata_studio/backend/app/mcp_runtime/client.py:38) | LocalMcpClient.call_tool/_call_tool L38–54 | structured_content → dict |
| [SDK func_metadata.py](D:/agent_study/askdata_studio/backend/.venv/Lib/site-packages/mcp/server/mcpserver/utilities/func_metadata.py:110) | FuncMetadata.convert_result L110–144，核心 L140–144 | 当前安装 SDK 的模型验证与 JSON-compatible 输出 |
| [single_database_agent.py](D:/agent_study/askdata_studio/backend/app/querying/single_database_agent.py:109) | SingleDatabaseAgent.prepare L109–125 | Tool 返回值 → execution 与 trace |
| [query_graph.py](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:122) | invoke/_state_result L122–130；_retrieve_schema L198–229；_prepare_single_database L280–289；_execute_single_database L293–355；_run_multi_database L357–365 | 真实顺序、上下文生成、执行重建、说明失败分支及当前单库范围 |
| [result_builder.py](D:/agent_study/askdata_studio/backend/app/workflows/result_builder.py:84) | completed L84–139；failed L142–156；public_retrieval L159–166；waiting L58–80 | QueryResult 混合来源、heuristic、错误与展示字段 |
| [models.py](D:/agent_study/askdata_studio/backend/app/models.py:54) | Interpretation L54–59；QueryResult L62–83 | 当前完整结果模型 |
| [response_generator.py](D:/agent_study/askdata_studio/backend/app/querying/response_generator.py:15) | __init__ L15–23；finalize L34–58 | 模型输入、前N行、valid/title/analysis、异常包装 |
| [model_client.py](D:/agent_study/askdata_studio/backend/app/model_client.py:41) | ModelClient.chat_json L41–53 | JSON解析不保证根节点object |
| [config.py](D:/agent_study/askdata_studio/backend/app/config.py:69) | Settings.context_table_row_limit L69 | 说明器默认50行；本次实测有效值也为50 |
| [database.py](D:/agent_study/askdata_studio/backend/app/database.py:9) | _field L9–26；ORDER_FIELDS L29–39；SCHEMA L42–108；RELATIONS L111–156 | 业务实体、全部字段语义、关系与目标粒度 |
| [demo_data.py](D:/agent_study/askdata_studio/backend/app/demo_data.py:16) | seed_demo_data L16–71；_customers L82–94；_products L97–112；_orders L115–153 | 固定数据期间、业务样本生成与状态金额口径；本轮没有调用写入函数 |
| [retrieval/graph.py](D:/agent_study/askdata_studio/backend/app/retrieval/graph.py:43) | SchemaGraphBuilder.build L43–109；context_text L112起 | 执行前 Schema 字段/关系 context，不是输出 lineage |
| [access_control.py](D:/agent_study/askdata_studio/backend/app/security/access_control.py:22) | AccessScope.allows_database/allows_table L22–26；demo_current_sales L66–71 | 能否使用所需数据库/历史表 |
| [askdata_service.py](D:/agent_study/askdata_studio/backend/app/services/askdata_service.py:84) | submit L84–120；save_memory L203–213；_payload L286–297 | Workflow结果返回、saved状态、分析上下文输入 |
| [session_context.py](D:/agent_study/askdata_studio/backend/app/services/session_context.py:215) | SessionContext.analysis_context L215–260 | 历史/用户提供表格与 analysis_sources 的真实来源 |
| [api/routes.py](D:/agent_study/askdata_studio/backend/app/api/routes.py:124) | query L124–130 | QueryResult 到 API 的出口 |
| [App.vue](D:/agent_study/askdata_studio/frontend/src/App.vue:580) | 结果展示模板 L580–612，表格条件 L593–596 | interpretation/analysis 展示；status 与显示关系 |

### 5.6 作为项目作者必须真正理解的 10 个点

1. [DuckDbEngine.execute](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:33)：SQL 完成执行与只 fetch 前 201 行是不同阶段；聚合结果行数不是源订单数。
2. [DuckDbEngine._json_value](D:/agent_study/askdata_studio/backend/app/querying/duckdb_engine.py:144)：DB 来源、物理类型与 JSON 表示不能混为一谈。
3. [query_database](D:/agent_study/askdata_studio/backend/app/mcp_runtime/tools/database_tools.py:32)：row_count=len(rows)，不等于 SQL 总结果行数。
4. [QueryWorkflow._execute_single_database](D:/agent_study/askdata_studio/backend/app/workflows/query_graph.py:293)：这是重建/整理已执行结果；说明器在 QueryResult 构造前调用。
5. [ResultBuilder.completed](D:/agent_study/askdata_studio/backend/app/workflows/result_builder.py:95)：metric/dimension 是列名 heuristic，不能当确定业务事实。
6. [ResponseGenerator.finalize](D:/agent_study/askdata_studio/backend/app/querying/response_generator.py:34)：LLM 看样本，valid 是模型判断；JSON解析不等于业务校验。
7. [SCHEMA / RELATIONS](D:/agent_study/askdata_studio/backend/app/database.py:92)：月地区目标与订单是不同粒度；region join 不足以保证金额正确。
8. [SchemaGraphBuilder.build](D:/agent_study/askdata_studio/backend/app/retrieval/graph.py:43)：源 Schema 候选和最终输出 lineage 是两回事。
9. [demo_data._orders](D:/agent_study/askdata_studio/backend/app/demo_data.py:127)：状态快照、订单日期、实付口径限制了退款、收入与客户风险的解释。
10. [QueryResult](D:/agent_study/askdata_studio/backend/app/models.py:62)：当前是混合来源接口；业务信号只能建立在来源、口径和完整性都可说明的数据上。

---

**Baseline 结论：已有交易、客户、产品与月地区目标足以支撑一小组描述性业务信号；首要基础工作是明确执行结果的完整性、数值表示、真实输出语义和比较口径，不能把现有 LLM 说明或 heuristic 包装当成已经可靠的业务事实。**
