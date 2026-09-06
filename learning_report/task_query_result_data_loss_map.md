# AskData 第八步源码调查：Query Result Data Loss Map

> 调查日期：2026-09-03  
> 源码范围：当前工作区 `D:\agent_study\askdata_studio`  
> 主链：`DuckDbEngine.execute()` → `SqlExecution` → `DatabaseQueryResult` → MCP `structured_content` → Workflow state → rebuilt `SqlExecution` → `ResultBuilder` → `QueryResult`  
> 方法：重新阅读当前源码，并使用当前项目虚拟环境执行最小只读 probe；没有沿用旧报告的结论。  
> 运行时版本：DuckDB 1.5.5、MCP 2.0.0、mcp-types 2.0.0、Pydantic 2.13.4。  
> 变更边界：本次只新增这份学习报告，没有修改业务代码、Contract、Repository、Derive 或 MCP 实现。

---

## 1. Executive Summary

1. SQL 真正执行于 `backend/app/querying/duckdb_engine.py:L42`：`cursor = connection.execute(safe_sql)`。当前 DuckDB 1.5.5 中，返回的 `cursor` 实际就是同一个 `DuckDBPyConnection` 对象，但已经承载本次 result set 的 description 和 fetch 状态。
2. `cursor.description` 当前是 `list[tuple]`，每个 tuple 有 DB-API 风格的 7 个位置。只读 probe 确认 `item[0]` 是列名、`item[1]` 是有效的 DuckDB `type_code`；`display_size/internal_size/precision/scale/null_ok` 五个位置在本次各类型 probe 中均为 `None`。
3. AskData 在 `duckdb_engine.py:L44` 只读取 `item[0]`。有效的 `type_code`——包括 `INTEGER`、`BIGINT`、`FLOAT`、`DOUBLE`、`DATE`、`TIMESTAMP` 和 `DECIMAL(10,2)`——在构造 `SqlExecution` 前已经被丢弃。这是最早、最重要的 Contract 压缩。
4. `fetchmany(201)` 最多读取 201 行，`raw_rows[:200]` 最多保留 200 行。第 201 行本来足以作为“结果超过 200 行”的哨兵，但当前代码没有生成 `truncated`，也没有保存 `len(raw_rows)`；上层无法区分 201 行与 500 行。
5. `raw_rows` 的每行是 positional tuple，`rows` 的每行变为以列名为 key 的 dict。这个转换提高了可读性，但丢失位置结构；若 SQL 返回重复列名，后一个值会覆盖前一个值。只读 probe 已验证 `columns=['duplicate_name','duplicate_name']` 时 row 只剩 `{'duplicate_name': 2}`。
6. `_json_value()` 将 `date/datetime` 变为 ISO 字符串，将 `Decimal` 变为 `float`；其他常见 Python 值原样保留。因此日期的 Python/物理类型身份丢失，Decimal 的精确十进制语义、精度和 scale 也不能由下游可靠恢复。
7. `DatabaseQueryResult` 不删减 `SqlExecution` 的五个字段，而是新增 closure 中的 `database`，并增加派生字段 `row_count=len(execution.rows)`。这个 `row_count` 是“最终返回 rows 数”，不是 SQL 总命中数，也不是 cursor 首次 fetch 的 201 行数。
8. MCP SDK 把 Pydantic `DatabaseQueryResult` 验证并 `model_dump(mode="json")` 为 `CallToolResult.structured_content`；项目随后执行 `dict(result.structured_content)`。字段值仍在，但 `DatabaseQueryResult` 的 Python/Pydantic 类型身份在这里消失，成为普通 dict。
9. Workflow 在 `query_graph.py:L296-L302` 从 `state["mcp_execution"]` 重建 `SqlExecution`，只复制 `sql/success/columns/rows/error`；`database` 和显式 `row_count` 不进入重建对象。不过原始 MCP dict 还通过 `mcp_tool_trace → execution_log[*].result` 形成旁路，最终 QueryResult 的嵌套日志中通常仍保留这两个字段。
10. `ResultBuilder.completed()` 将 `sql/columns/rows` 原样放入 QueryResult；同时用返回列名中的中文子串猜测 metric/dimension，用 schema graph 的候选表生成 table interpretation。后者是后处理推断，不是 DuckDB cursor 提供的列 lineage、physical dtype 或业务语义。

核心判断：

> 当前结果主 Contract 对“展示 SQL、列名和前 200 行 JSON 值”基本足够；对 physical dtype、Decimal 精度/scale、列 nullability、输出列 lineage、总命中数和 truncation 状态不足；对 metric/dimension/unit 等业务语义只能依赖旁路 schema 和后处理推断，不能从 `rows` 本身可靠恢复。

---

## 2. End-to-End Result Path

### 2.1 真实单数据库成功路径

```text
DuckDbEngine.execute(database, sql, access_scope)
backend/app/querying/duckdb_engine.py:L33-L51
        │
        ├─ _validate_sql(...) → safe_sql
        ├─ connect(database) → DuckDBPyConnection
        └─ cursor = connection.execute(safe_sql)                 L42
                ↓
          cursor.description + cursor.fetchmany(201)
                ↓
          columns = [item[0] ...]                                L44
          raw tuple values → _json_value() → row dict            L45-L48
                ↓
SqlExecution
backend/app/querying/models.py:L7-L13
{sql, success, columns, rows, error}
                ↓
query_database(sql)
build_database_query_tool() 创建的 closure
backend/app/mcp_runtime/tools/database_tools.py:L25-L46
                ↓
DatabaseQueryResult
backend/app/mcp_runtime/schemas.py:L21-L28
{database, sql, success, columns, rows, row_count, error}
                ↓
MCP SDK output model validation + model_dump(mode="json")
backend/.venv/Lib/site-packages/mcp/server/mcpserver/
utilities/func_metadata.py:L110-L144
                ↓
CallToolResult
{content, structured_content, is_error}
                ↓
LocalMcpClient._call_tool()
backend/app/mcp_runtime/client.py:L41-L54
dict(result.structured_content)
                ↓
tool_result: dict[str, Any]
                ↓
SingleDatabaseAgent.prepare()
backend/app/querying/single_database_agent.py:L109-L123
decision["execution"] = tool_result
tool_trace[*]["result"] = tool_result
                ↓
QueryWorkflow._prepare_single_database()
backend/app/workflows/query_graph.py:L261-L290
state["mcp_execution"] = execution dict
state["mcp_tool_trace"] = tool trace
                ↓
QueryWorkflow._execute_single_database()
backend/app/workflows/query_graph.py:L293-L355
raw_execution = state["mcp_execution"]
                ↓
SqlExecution(...) 重新构造                               L296-L302
                ↓
ResponseGenerator.finalize(...)
backend/app/querying/response_generator.py:L34-L58
生成 final = {valid, reason, title, analysis}
                ↓
ResultBuilder.completed(...)
backend/app/workflows/result_builder.py:L84-L139
                ↓
QueryResult Pydantic object
backend/app/models.py:L62-L83
                ↓ model_dump(mode="json")
state["result"]: dict
query_graph.py:L354-L355
                ↓ QueryResult.model_validate(...)
QueryWorkflow._state_result()
query_graph.py:L126-L130
                ↓
最终 QueryResult Pydantic object
```

### 2.2 两条并行的数据通道

MCP dict 进入 Workflow 后并非只有一份：

```text
tool_result dict
├── decision["execution"]
│      ↓
│   state["mcp_execution"]
│      ↓
│   rebuilt SqlExecution
│      ↓
│   QueryResult.sql / columns / rows
│
└── tool_trace[*]["result"]
       ↓
    state["mcp_tool_trace"]
       ↓
    execution_log[*]["result"]
       ↓
    QueryResult.execution_log（嵌套保留原 MCP 字段）
```

结论：`database` 和 `row_count` **从 rebuilt `SqlExecution` 的主路径中被丢弃**，但通常仍能在最终 `QueryResult.execution_log[*].result` 的诊断旁路里找到。不能把“未进入主 Contract”误写成“整个 QueryResult 对象中绝对不存在”。

### 2.3 最终对象还经历一次 QueryResult → dict → QueryResult

结论：`ResultBuilder.completed()` 首先返回 `QueryResult`，LangGraph state 保存的是 JSON-mode dict，Workflow 对外返回前又用该 dict 构造 `QueryResult`。

证据：

`backend/app/workflows/query_graph.py:L122-L130, L354-L355`

```python
def invoke(self, payload: QueryState | Command, task_id: str) -> QueryResult:
    state = self.graph.invoke(payload, config=self.run_config(task_id))
    return self._state_result(state, task_id)

def _state_result(self, state: dict[str, Any], task_id: str) -> QueryResult:
    if state.get("result"):
        return QueryResult.model_validate(state["result"])

result = ResultBuilder.completed(...)
return {"execution_log": log, "tool_calls": [call], "result": result.model_dump(mode="json")}
```

解释：这一步按同一个 `QueryResult` schema dump/validate，当前字段没有再次有意删减；发生的是容器/类型身份转换。最终返回的是新的 QueryResult Pydantic 实例，而不是 ResultBuilder 刚创建的同一个 Python 对象。

---

## 3. DuckDbEngine Deep Dive

### 3.1 完整关键源码

结论：当前结果第一次被物化和压缩的代码全部集中在 `DuckDbEngine.execute()` 的 L40-L49。

证据：

`backend/app/querying/duckdb_engine.py:L33-L51`

```python
def execute(
    self,
    database: str,
    sql: str,
    access_scope: AccessScope | None = None,
) -> SqlExecution:
    try:
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
    except (ValueError, ParseError, duckdb.Error, OSError) as exc:
        return SqlExecution(sql, False, error=str(exc))
```

### 3.2 `safe_sql`

结论：传给 DuckDB 的不是未经检查的原始 `sql`，而是 `_validate_sql()` 返回的 `safe_sql`。在成功路径中，`SqlExecution.sql` 保存 `safe_sql`；失败路径保存传入的原始 `sql`。

证据：

- `backend/app/querying/duckdb_engine.py:L40`：`safe_sql = self._validate_sql(...)`；
- 同文件 `L42`：执行 `safe_sql`；
- 同文件 `L49`：成功对象保存 `safe_sql`；
- 同文件 `L50-L51`：失败对象保存原始 `sql`。

解释：`_validate_sql()` 会剥掉代码围栏和末尾分号（同文件 `L81, L138-L142`）。因此成功与失败的 `SqlExecution.sql` 在格式语义上并不完全对称。

### 3.3 `cursor`：SQL 真正执行的位置

结论：SQL 在 L42 真正执行。

证据：

`backend/app/querying/duckdb_engine.py:L41-L43`

```python
with self.connect(database) as connection:
    cursor = connection.execute(safe_sql)
    raw_rows = cursor.fetchmany(201)
```

解释：当前 DuckDB 1.5.5 只读 probe 确认：

```text
type(cursor) == _duckdb.DuckDBPyConnection
cursor is connection == True
```

也就是说，变量名叫 `cursor`，但 `connection.execute()` 返回的是同一个 `DuckDBPyConnection` 实例；该实例此时保存当前查询的 result set 状态，并提供：

- `description`：列级 DB-API 风格元组；
- `fetchone/fetchmany/fetchall`：消费当前结果行；
- `rowcount`：本版本查询前后都为 `-1`，不能用作总命中行数。

它还具有连接本身的能力，但 AskData 在本函数中只使用 `fetchmany()` 和 `description`。

### 3.4 `cursor.description`

结论：当前代码只保留列名。

证据：

`backend/app/querying/duckdb_engine.py:L44`

```python
columns = [item[0] for item in cursor.description or []]
```

解释：

- `cursor.description` 在 probe 中是 list；
- 每个 `item` 是长度 7 的 tuple；
- AskData 只读取第 0 位；
- 第 1 位有效 `type_code` 和后五位 DB-API metadata slot 都没有进入任何变量；
- `or []` 允许 description 为 `None` 时生成空列名列表，但正常 SELECT 有 description。

详细审计见第 4 节。

### 3.5 `raw_rows`

结论：`raw_rows` 是最多 201 个 positional row tuple 组成的 list。

证据：

`backend/app/querying/duckdb_engine.py:L43`

```python
raw_rows = cursor.fetchmany(201)
```

当前 runtime probe：

```text
500 行查询：
len(raw_rows) = 201
此时 cursor 中尚有 299 行未 fetch
cursor.rowcount = -1
```

解释：第 201 行显然是为检测“超过 200”预留的哨兵式读取，但当前后续代码没有使用这个信号。`raw_rows` 本身也没有离开 `execute()`。

### 3.6 `columns`

结论：`columns` 是保留顺序的 `list[str]`，来源仅是 description 的列名。

证据：

`backend/app/querying/duckdb_engine.py:L44`

```python
columns = [item[0] for item in cursor.description or []]
```

解释：列顺序和重复列名都保留在 list 中，但没有每列的 dtype、nullability、precision、scale 或来源表。

### 3.7 `rows`：tuple → dict + value normalization

结论：只处理 `raw_rows` 前 200 个 tuple；每个位置按 `zip(columns, row)` 与列名配对，并在进入 dict 前调用 `_json_value()`。

证据：

`backend/app/querying/duckdb_engine.py:L45-L48`

```python
rows = [
    {column: self._json_value(value) for column, value in zip(columns, row)}
    for row in raw_rows[:200]
]
```

逐步变化：

```text
row tuple
(10001, 64841.17, date(2026, 8, 5), "已支付")
        ↓ zip(columns, row)
("order_id", 10001), ("order_amount", 64841.17), ...
        ↓ _json_value(value)
date → "2026-08-05"
        ↓ dict comprehension
{
  "order_id": 10001,
  "order_amount": 64841.17,
  "order_date": "2026-08-05",
  "status": "已支付"
}
```

### 3.8 tuple → dict 的额外信息损失：重复列名覆盖

结论：如果两个输出列同名，`columns` 仍含两个名称，但 row dict 只能保留最后一个同名 key 对应的值。

证据：

同样来自 `backend/app/querying/duckdb_engine.py:L46` 的 dict comprehension；只读 probe 使用：

```sql
SELECT 1 AS duplicate_name, 2 AS duplicate_name
```

实际结果：

```python
columns == ["duplicate_name", "duplicate_name"]
rows == [{"duplicate_name": 2}]
```

解释：raw tuple `(1, 2)` 中第一个位置的值 `1` 被同名 dict key 覆盖。这不是 DuckDB 丢失，而是 AskData row representation 从 positional tuple 转成 mapping 时发生。

### 3.9 `SqlExecution` 的构造

结论：成功路径只把 `safe_sql`、成功标志、列名列表和最多 200 个 normalized row dict 交给 `SqlExecution`；error 使用默认 `None`。

证据：

`backend/app/querying/duckdb_engine.py:L49`

```python
return SqlExecution(safe_sql, True, columns, rows)
```

失败路径：

`backend/app/querying/duckdb_engine.py:L50-L51`

```python
except (ValueError, ParseError, duckdb.Error, OSError) as exc:
    return SqlExecution(sql, False, error=str(exc))
```

解释：此时以下信息没有参数位置，无法进入 `SqlExecution`：logical database、type_code、precision/scale/nullability、raw tuple、raw fetched count、总命中数、truncated 标志、列 lineage。第一次主 Contract 压缩发生在 `L44-L49`。

---

## 4. cursor.description Metadata Audit

### 4.1 标准位置、当前 DuckDB 实际值和 AskData 读取行为

本节必须区分三件事：DB-API 风格 tuple 有这个位置、当前 DuckDB 1.5.5 是否提供有效值、AskData 是否读取。

只读 probe 的每个 description item 都是：

```text
(name, type_code, display_size, internal_size, precision, scale, null_ok)
```

审计表：

| Metadata | tuple 标准位置 | 当前 DuckDB 1.5.5 probe | AskData 当前是否读取 | 是否进入 `SqlExecution` | 证据 |
|---|---:|---|---:|---:|---|
| column name | `item[0]` | ✅ 有效字符串，如 `order_id` | ✅ | ✅ `columns` | `duckdb_engine.py:L44, L49` |
| type_code | `item[1]` | ✅ 有效 `DuckDBPyType`，如 `BIGINT/DOUBLE/DATE/DECIMAL(10,2)` | ❌ | ❌ | runtime probe；源码只取 `item[0]` |
| display_size | `item[2]` | ⚠️ slot 存在，但 probe 均为 `None` | ❌ | ❌ | runtime probe；`duckdb_engine.py:L44` |
| internal_size | `item[3]` | ⚠️ slot 存在，但 probe 均为 `None` | ❌ | ❌ | runtime probe；`duckdb_engine.py:L44` |
| precision | `item[4]` | ⚠️ slot 存在，但 `DECIMAL(10,2)` probe 也为 `None` | ❌ | ❌ | runtime probe；`duckdb_engine.py:L44` |
| scale | `item[5]` | ⚠️ slot 存在，但 `DECIMAL(10,2)` probe 也为 `None` | ❌ | ❌ | runtime probe；`duckdb_engine.py:L44` |
| null_ok | `item[6]` | ⚠️ slot 存在，但 probe 均为 `None` | ❌ | ❌ | runtime probe；`duckdb_engine.py:L44` |

重要细节：虽然独立 `precision`/`scale` slot 是 `None`，Decimal 的 DuckDB type object 自身显示为 `DECIMAL(10,2)`。所以当前 runtime 的 type_code 中仍承载可用的物理类型细节；AskData 因完全丢弃 `item[1]` 而一起丢掉了它。

### 4.2 最小只读 probe

本次没有修改业务代码，直接使用项目虚拟环境中的 DuckDB 1.5.5 内存连接执行：

```sql
SELECT
  CAST(42 AS INTEGER) AS int_col,
  CAST(42000000000 AS BIGINT) AS bigint_col,
  CAST(1.25 AS DOUBLE) AS double_col,
  CAST(1.25 AS FLOAT) AS float_col,
  CAST(123.45 AS DECIMAL(10,2)) AS decimal_col,
  DATE '2026-09-03' AS date_col,
  TIMESTAMP '2026-09-03 12:34:56.123456' AS timestamp_col,
  TRUE AS bool_col,
  CAST('abc' AS VARCHAR) AS varchar_col,
  CAST(NULL AS INTEGER) AS null_col
```

关键运行结果：

```python
('int_col',       INTEGER,       None, None, None, None, None)
('bigint_col',    BIGINT,        None, None, None, None, None)
('double_col',    DOUBLE,        None, None, None, None, None)
('float_col',     FLOAT,         None, None, None, None, None)
('decimal_col',   DECIMAL(10,2), None, None, None, None, None)
('date_col',      DATE,          None, None, None, None, None)
('timestamp_col', TIMESTAMP,     None, None, None, None, None)
('bool_col',      BOOLEAN,       None, None, None, None, None)
('varchar_col',   VARCHAR,       None, None, None, None, None)
('null_col',      INTEGER,       None, None, None, None, None)
```

此处 runtime 证据只说明**当前安装版本和这些实际 probe 表达式**。不能把五个 `None` 扩大解释成 DuckDB 在所有类型、所有版本、所有驱动路径都永远不提供这些值。

### 4.3 当前真实 CSV 查询再次验证

对 `askdata_mock.orders_current` 执行只读查询：

```sql
SELECT order_id, order_amount, order_date, status
FROM orders_current
ORDER BY order_id
LIMIT 1
```

实际 description：

```python
[
  ('order_id',     BIGINT,  None, None, None, None, None),
  ('order_amount', DOUBLE,  None, None, None, None, None),
  ('order_date',   DATE,    None, None, None, None, None),
  ('status',       VARCHAR, None, None, None, None, None),
]
```

这验证了历史 investigation lead“cursor.description 可能包含 type_code”为真，并进一步确认 type_code 在当前项目真实 CSV view 查询中确实有值；历史 lead“当前 columns 可能只读取 item[0]”也由 `duckdb_engine.py:L44` 确认。

### 4.4 `cursor.description` 没有提供什么

在当前 probe 中，description 没有提供可用的：

- display/internal size；
- 独立 precision/scale slot；
- nullability；
- source database/source table；
- schema field role、aggregation、unit 等业务 metadata。

因此这些项目要区分：

- `type_code`：DuckDB 已提供，但 AskData 丢失；
- precision/scale 独立 slot：本次 DuckDB 没提供有效值，不能简单称为 AskData 丢失；不过 Decimal type_code 中的 `(10,2)` 确实被丢失；
- source table/business role/unit：不是当前 description 天然拥有的信息，属于 N/A，而不是在 `item[0]` 选择时全部“丢掉”。

---

## 5. Value Type Conversion Audit

### 5.1 唯一显式转换函数

结论：当前只显式转换 `date/datetime` 和 `Decimal`。

证据：

`backend/app/querying/duckdb_engine.py:L144-L150`

```python
@staticmethod
def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value
```

调用点：

`backend/app/querying/duckdb_engine.py:L45-L47`

```python
{column: self._json_value(value) for column, value in zip(columns, row)}
```

### 5.2 当前 runtime 的类型变化表

| DuckDB physical type（probe） | raw row 中 Python 类型 | 转换前示例 | `SqlExecution.rows` 中类型 | MCP/JSON 类型 | 信息变化 |
|---|---|---|---|---|---|
| `INTEGER` | `int` | `42` | `int` | JSON number | 值保留；因 type_code 丢失，不能再证明是 INTEGER |
| `BIGINT` | `int` | `42000000000` | `int` | JSON number | 值保留；与 INTEGER 的物理区别丢失 |
| `DOUBLE` | `float` | `1.25` | `float` | JSON number | 值保留；与 FLOAT 的物理区别丢失 |
| `FLOAT` | `float` | `1.25` | `float` | JSON number | 值保留；与 DOUBLE 的物理区别丢失 |
| `DECIMAL(10,2)` | `Decimal` | `Decimal('123.45')` | `float` | JSON number | 🔄 转换；exact decimal 类型、声明精度/scale、尾随零语义不可恢复，并可能发生二进制浮点精度损失 |
| `DATE` | `date` | `date(2026,9,3)` | `str` | JSON string | 🔄 ISO 文本值保留；date 类型身份丢失 |
| `TIMESTAMP` | `datetime` | `datetime(...,123456)` | `str` | JSON string | 🔄 ISO 文本值保留；datetime 类型身份丢失 |
| `BOOLEAN` | `bool` | `True` | `bool` | JSON boolean | 值和 Python 类别保留；physical type 证据仍因 type_code 丢失 |
| `VARCHAR` | `str` | `'abc'` | `str` | JSON string | 文本值保留；不能仅凭 str 排除其原来是被序列化的 DATE/TIMESTAMP |
| typed `NULL`（probe 为 INTEGER） | `NoneType` | `None` | `None` | JSON null | null 值保留；原列 physical dtype 无法从 null 恢复 |

### 5.3 DATE / DATETIME 的具体损失

`isoformat()` 保留规范化文本内容。例如：

```text
date(2026, 9, 3)
→ "2026-09-03"

datetime(2026, 9, 3, 12, 34, 56, 123456)
→ "2026-09-03T12:34:56.123456"
```

但是下游只看到 str。它不能仅靠 Python/JSON 类型区分：

- 原始 `VARCHAR` 恰好内容是 `"2026-09-03"`；
- 原始 `DATE` 经 `_json_value()` 得到同样字符串。

因此文本内容可能足够展示，却不足以作为可靠 physical dtype contract。

### 5.4 Decimal 的具体损失

结论：Decimal 在最早的 row normalization 中就被转成 float，而不是到 MCP JSON 序列化阶段才转换。

证据：

`backend/app/querying/duckdb_engine.py:L148-L149`

```python
if isinstance(value, Decimal):
    return float(value)
```

解释：下游只能看到 Python float/JSON number，不能可靠恢复：

- 原来是 `DECIMAL` 还是 `DOUBLE`；
- `DECIMAL(p,s)` 的 p/s；
- 精确十进制表示和尾随零；
- 某些大数或高精度小数在 float 中是否已发生舍入。

### 5.5 MCP 后续是否再次改变这些值

当前 database handler 的 rows 注解是 `list[dict[str, Any]]`。MCP SDK 对 `DatabaseQueryResult` 做 output model validation 后使用 JSON mode dump。

证据：

`backend/.venv/Lib/site-packages/mcp/server/mcpserver/utilities/func_metadata.py:L140-L144`

```python
validated = self.output_model.model_validate(result)
structured_content = validated.model_dump(mode="json", by_alias=True)
return CallToolResult(content=unstructured_content, structured_content=structured_content)
```

只读 MCP probe 确认：`int/float/str` 在 `structured_content['rows']` 中仍分别是 `int/float/str`。主要不可逆转换已经发生在 `_json_value()`，而不是 `dict(result.structured_content)`。

---

## 6. Row Count & Truncation Audit

### 6.1 当前代码的三个行数

| 概念 | 当前是否得到 | 当前存在哪里 | 是否传到上层 |
|---|---:|---|---:|
| SQL result 的真实总行数 | ❌ 未计算 | cursor 可继续迭代，但 `rowcount == -1`，没有总数 | ❌ |
| 首次实际 fetch 行数 | ✅ `len(raw_rows)` 可得，范围 0～201 | 只存在于 `execute()` 局部 list | ❌ 未保存 |
| 最终返回行数 | ✅ `len(rows)`，范围 0～200 | rows 本身可派生；MCP `row_count` 显式保存 | ✅，但主 rebuilt SqlExecution 无字段 |

### 6.2 关键源码

证据：

`backend/app/querying/duckdb_engine.py:L42-L49`

```python
cursor = connection.execute(safe_sql)
raw_rows = cursor.fetchmany(201)
columns = [item[0] for item in cursor.description or []]
rows = [
    {...}
    for row in raw_rows[:200]
]
return SqlExecution(safe_sql, True, columns, rows)
```

解释：

- `fetchmany(201)` 读取上限是 201；
- `raw_rows[:200]` 丢弃第 201 个已读取 row；
- connection 离开 `with` 后关闭，未读取的剩余结果也不再可用；
- 没有 `total_count`；
- 没有 `fetched_count`；
- 没有 `truncated = len(raw_rows) > 200`。

### 6.3 不同总行数下的实际行为

假设 SQL 本身不带更小 LIMIT：

| SQL 实际结果行数 | `fetchmany(201)` 得到 | `rows` 返回 | 可否知道 truncated |
|---:|---:|---:|---|
| 0 | 0 | 0 | 当前 contract 无 flag；从 rows 可知空结果 |
| 50 | 50 | 50 | contract 无 flag；根据 fetch 逻辑静态可知未截断，但上层只见 50 |
| 200 | 200 | 200 | contract 无 flag；上层无法凭 `row_count=200` 区分是否正好 200 |
| 201 | 201 | 200 | 已截断 1 行，但信号被丢弃 |
| 500 | 201 | 200 | 第 201 行被丢弃，另 299 行未 fetch；上层只见 200 |

只读 probe 对 500 行 in-memory query 实测：

```text
first fetch = 201
returned slice = 200
remaining cursor rows = 299
cursor.rowcount = -1
```

对当前真实 CSV 两表自连接产生的 57,600 行结果，`DuckDbEngine.execute()` 实测仍只返回 200 行，`SqlExecution` 中没有截断标志。

### 6.4 `row_count` 的真实语义

结论：MCP 中的 `row_count` 是 `len(execution.rows)`，即返回行数；不是 SQL 总命中数，也不是 `len(raw_rows)`。

证据：

`backend/app/mcp_runtime/tools/database_tools.py:L35-L42`

```python
return DatabaseQueryResult(
    ...
    rows=execution.rows,
    row_count=len(execution.rows),
    error=execution.error,
)
```

所以当 SQL 实际产生 500 行：

```text
总结果：500（当前主查询没有保存）
fetch：201（局部变量，没有保存）
返回：200
DatabaseQueryResult.row_count：200
truncated：事实上 true，但 contract 中不存在
```

### 6.5 ResponseGenerator 还会看到更小子集

这不会删减最终 `QueryResult.rows`，但会限制用于 LLM 结果说明的数据上下文。

证据：

`backend/app/querying/response_generator.py:L22, L44-L47`

```python
self.table_row_limit = max(1, (config or settings).context_table_row_limit)

f"结果数据：{execution.rows[: self.table_row_limit]}\nSchema：{schema_context}\n"
```

默认值证据：`backend/app/config.py:L69`

```python
context_table_row_limit: int = int(os.getenv("CONTEXT_TABLE_ROW_LIMIT", "50"))
```

因此默认情况下：DuckDB 最多 200 rows 进入结果 Contract，但生成 `analysis/title/valid` 的 LLM 最多只看到前 50 rows。`analysis` 是基于子集和其他 context 的后处理文本，不是数据库原始事实字段。

---

## 7. SqlExecution Contract

### 7.1 完整定义

结论：`SqlExecution` 只有五个字段。

证据：

`backend/app/querying/models.py:L7-L13`

```python
@dataclass
class SqlExecution:
    sql: str
    success: bool
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
```

| 字段 | 来源 | 语义 |
|---|---|---|
| `sql` | 成功用 `safe_sql`；失败用原始 `sql` | 实际执行或尝试执行的 SQL 文本 |
| `success` | `execute()` 控制流 | 是否通过校验并成功执行/fetch/转换 |
| `columns` | `description[*][0]` | 有序输出列名；可重复 |
| `rows` | 前 200 个 raw tuple 经 dict + `_json_value` | JSON-oriented row values |
| `error` | caught exception 的 `str(exc)` | 失败原因；成功默认 `None` |

### 7.2 第一次 Contract 压缩发生在哪里

结论：主要压缩不是 dataclass 定义单独造成，而是 `execute()` 在构造 dataclass 前只抽取列名、截取行和转换值，再以五个参数创建对象。

证据：

`backend/app/querying/duckdb_engine.py:L43-L49`

```python
raw_rows = cursor.fetchmany(201)
columns = [item[0] for item in cursor.description or []]
rows = [
    {column: self._json_value(value) for column, value in zip(columns, row)}
    for row in raw_rows[:200]
]
return SqlExecution(safe_sql, True, columns, rows)
```

### 7.3 cursor/engine context 到 `SqlExecution` 的保留与损失

| 信息 | 进入 `SqlExecution` 吗 | 状态 |
|---|---:|---|
| SQL | 是 | ✅ 成功保存 cleaned `safe_sql`；失败保存原始 SQL |
| success | 是 | ➕ 由控制流新增 |
| error | 是 | ➕ 从异常字符串化；异常对象类型/traceback 不保留 |
| column name/order | 是 | ✅ 保存为 `columns` |
| duplicate column names | columns 中是 | ⚠️ columns 保存，但 row dict 的同名值覆盖 |
| rows | 是，最多 200 | 🔄 tuple→dict，values normalization |
| logical database | 否 | ❌ `execute()` 参数存在，但 dataclass 无字段 |
| physical `type_code` | 否 | ❌ DuckDB 有效提供，L44 未读取 |
| precision/scale | 否 | ⚠️ 独立 slots 当前为 None；Decimal type_code 中的 p/s 随 type_code 丢失 |
| nullability | 否 | N/A：当前 runtime slot 为 None，Contract 也无字段 |
| raw Python value type | 不显式保存 | 🔄 部分可从对象观察；DATE/Decimal 已转换 |
| raw tuple positional form | 否 | 🔄 变成 dict；重复名称时发生实际值丢失 |
| raw fetched count | 否 | ❌ `len(raw_rows)` 未保存 |
| returned count | 无字段 | ⚠️ 可由 `len(rows)` 派生 |
| total matching count | 否 | N/A：当前查询未计算；cursor.rowcount 为 -1 |
| truncated | 否 | ❌ `len(raw_rows)>200` 信号未保存 |
| source table/column lineage | 否 | N/A：description 未提供，Contract 也未建立映射 |
| schema/business role/unit | 否 | N/A：不是 cursor result metadata；来自其他系统上下文才可能存在 |

### 7.4 到了这里已经无法可靠恢复什么

仅凭 `SqlExecution`，无法可靠恢复：

- INTEGER vs BIGINT；
- FLOAT vs DOUBLE；
- DECIMAL vs DOUBLE，以及 DECIMAL precision/scale；
- DATE/TIMESTAMP vs 内容恰好像日期的 VARCHAR；
- null 所属列的 physical dtype；
- SQL 原始总行数和是否截断；
- 每个 output column 对应哪个源表/源字段；
- metric/dimension/time/identifier 等业务 role；
- unit。

即使后续根据值或名称“猜”出来，也属于 derive/inference，不是恢复原始 cursor contract。

---

## 8. MCP Result Contract

### 8.1 `SqlExecution → DatabaseQueryResult`

结论：database MCP handler 返回的是 Pydantic `DatabaseQueryResult`，不是 dict，也不是 `SqlExecution`。

证据：

`backend/app/mcp_runtime/tools/database_tools.py:L25-L43`

```python
def build_database_query_tool(
    database: str,
    engine: DuckDbEngine,
    access_scope: AccessScope,
) -> Callable[[SqlStatement], DatabaseQueryResult]:

    def query_database(sql: SqlStatement) -> DatabaseQueryResult:
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

完整模型定义：

`backend/app/mcp_runtime/schemas.py:L21-L28`

```python
class DatabaseQueryResult(BaseModel):
    database: str
    sql: str
    success: bool
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = Field(default=0)
    error: str | None = Field(default=None)
```

逐项比较：

| 分类 | 字段 | 变化 |
|---|---|---|
| preserved information | `sql/success/columns/rows/error` | 从 `SqlExecution` 复制到 Pydantic model |
| new metadata | `database` | ➕ 从 builder closure 的 `database` 加入，不是从 cursor 恢复 |
| derived information | `row_count` | ➕ `len(execution.rows)`，代表返回 rows 数 |
| lost information | 无新的字段损失 | `DatabaseQueryResult` 对 `SqlExecution` 是字段超集；早先已丢的 dtype/truncation 不会复原 |
| Contract identity | dataclass → Pydantic model | 🔄 类型和验证边界变化 |

### 8.2 `row_count` 不是 SQL 总数

结论：即使 SQL 实际产生 57,600 行，当前 database handler 的 `row_count` 仍是 200。

证据：

`backend/app/mcp_runtime/tools/database_tools.py:L39-L42`

```python
rows=execution.rows,
row_count=len(execution.rows),
```

解释：`execution.rows` 已在 DuckDbEngine 中被截成最多 200。MCP 层没有 cursor，也没有执行额外 `COUNT(*)`，因此这里不能知道 total matching row count。

### 8.3 `DatabaseQueryResult → CallToolResult.structured_content`

结论：MCP Server 调用 Tool 时要求 SDK 转换 handler result；SDK 用注册时生成的 output model 验证结果，再以 JSON mode dump 到 `structured_content`。

证据：

`backend/.venv/Lib/site-packages/mcp/server/mcpserver/server.py:L498-L504`

```python
async def call_tool(...):
    ...
    return await self._tool_manager.call_tool(
        name, arguments, context, convert_result=True
    )
```

`backend/.venv/Lib/site-packages/mcp/server/mcpserver/utilities/func_metadata.py:L126-L144`

```python
if isinstance(result, CallToolResult):
    if self.output_schema is not None:
        self.output_model.model_validate(result.structured_content)
    return result

unstructured_content = _convert_to_content(result)
...
validated = self.output_model.model_validate(result)
structured_content = validated.model_dump(mode="json", by_alias=True)
return CallToolResult(
    content=unstructured_content,
    structured_content=structured_content,
)
```

解释：当前 handler 返回 `DatabaseQueryResult`，不是预建 `CallToolResult`，所以走后半分支。结果同时有：

- `content`：非结构化 ContentBlock 列表；
- `structured_content`：JSON-compatible dict；
- `is_error`：MCP tool execution 层是否报错。

### 8.4 上层读取 content 还是 structured_content

结论：成功路径只把 `structured_content` 转成 dict；`content` 不进入 Workflow。

证据：

`backend/app/mcp_runtime/client.py:L41-L54`

```python
async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async with Client(self.server) as client:
        result = await client.call_tool(name, arguments)
    if result.is_error:
        messages = [
            str(getattr(block, "text", ""))
            for block in result.content
            if getattr(block, "text", "")
        ]
        raise RuntimeError(...)
    if result.structured_content is None:
        raise RuntimeError(...)
    return dict(result.structured_content)
```

说明：

- `content` 仅在 `is_error=True` 时被读取，用于拼错误文本；
- 成功时要求 `structured_content` 非空；
- L54 的 `dict(...)` 产生普通 Python dict；
- 这是浅层容器转换，不会重新推导 rows。

### 8.5 字段值没有丢失，但类型/Contract 身份丢失

只读 end-to-end MCP probe 确认：

```text
MCP 返回类型：mcp_types._types.CallToolResult
structured_content 类型：dict
structured_content keys：
database, sql, success, columns, rows, row_count, error
LocalMcpClient 返回类型：dict
```

因此必须分开写：

| 问题 | 结论 |
|---|---|
| `DatabaseQueryResult` 的 7 个字段值是否因 MCP 丢失 | 没有，当前 structured_content 全部保留 |
| Pydantic `DatabaseQueryResult` 实例身份是否保留 | 没有，SDK dump 后是 dict |
| output schema 是否完全消失 | 协议/Tool definition 仍有 schema；但 `tool_result` 这个运行时值本身只是 dict，不携带 model class |
| `CallToolResult` 身份是否传到 Agent | 没有，LocalMcpClient 只返回其 structured dict |
| `content` 是否传到 Agent | 成功路径没有；但其信息与 structured result 在当前 tool 中基本是冗余表示 |

### 8.6 MCP 没有恢复 DuckDB 已丢信息

MCP schema 只描述现有 `DatabaseQueryResult` 字段。由于模型没有 column metadata、total count、truncated、lineage 字段，MCP 不可能通过序列化自动恢复这些信息。`structured_content` 只会把已有 Contract JSON 化。

---

## 9. Workflow Contract

### 9.1 MCP dict 如何进入 QueryState

结论：Agent 把同一个 `tool_result` 同时放入 `execution` 返回值和 tool trace。

证据：

`backend/app/querying/single_database_agent.py:L109-L123`

```python
tool_result = mcp_client.call_tool(tool_name, arguments)
trace = {
    "call_index": call_index,
    "tool": tool_name,
    "arguments": arguments,
    "result": tool_result,
    "reason": str(decision.get("reason") or ""),
}
tool_trace.append(trace)

if tool_name == database_tool:
    return {
        "action": "executed",
        "execution": tool_result,
        "tool_trace": tool_trace,
        "source": "model_mcp",
    }
```

Workflow 接收后写入 state：

`backend/app/workflows/query_graph.py:L280-L289`

```python
execution = decision["execution"]
return {
    "workflow_mode": "single_database_agent",
    "clarification": None,
    "mcp_execution": execution,
    "mcp_tool_trace": decision.get("tool_trace", []),
    "direct_sql": str(execution.get("sql") or ""),
    "sql_source": decision.get("source", "model"),
}
```

State 类型声明：

`backend/app/workflows/state.py:L30-L36`

```python
direct_sql: str
sql_source: str
tool_facts: dict[str, Any]
mcp_execution: dict[str, Any]
mcp_tool_trace: list[dict[str, Any]]
execution_log: list[dict[str, Any]]
tool_calls: list[dict[str, Any]]
```

解释：在这一层，`mcp_execution` 只是 `dict[str, Any]`。Pydantic `DatabaseQueryResult` 类型身份已经在 MCP SDK/LocalMcpClient 边界消失。

### 9.2 第二次 Contract 压缩：重新构造 `SqlExecution`

结论：Workflow 从 `mcp_execution` 的 7 字段 dict 中只选择 5 个字段构造 `SqlExecution`。

证据：

`backend/app/workflows/query_graph.py:L293-L302`

```python
def _execute_single_database(self, state: QueryState) -> dict[str, Any]:
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

具体丢弃位置：

- `database`：存在于 `raw_execution`，但 L296-L302 的 constructor 没有对应参数；
- `row_count`：存在于 `raw_execution`，但 L296-L302 没有读取；
- 其他 5 字段被读取并发生基础类型规范化：`str/bool/list/list`。

### 9.3 为什么又构造 `SqlExecution`

这是当前源码的接口适配事实：

- MCP/QueryState 边界使用 JSON-compatible dict；
- `ResponseGenerator.finalize()` 的第二个参数类型是 `SqlExecution`（`response_generator.py:L34-L39`）；
- `ResultBuilder.completed()` 的 `executions` 和 `combined` 参数类型是 `list[SqlExecution]` / `SqlExecution`（`result_builder.py:L84-L90`）；
- `ResultBuilder.failed()` 也要求 `SqlExecution`（`result_builder.py:L142`）。

因此 `_execute_single_database()` 先把 transport/state dict 恢复为 querying 层的 dataclass，再调用这些下游接口。本报告只描述这个适配，不评价设计。

### 9.4 逐字段比较

| 字段 | `DatabaseQueryResult` | `state["mcp_execution"]` dict | rebuilt `SqlExecution` | 主路径状态 |
|---|---:|---:|---:|---|
| `database` | ✅ | ✅ | ❌ | 在 `query_graph.py:L296-L302` 未复制 |
| `sql` | ✅ | ✅ | ✅ `str(...)` | preserved/normalized |
| `success` | ✅ | ✅ | ✅ `bool(...)` | preserved/normalized；若 key 缺失会默认为 False |
| `columns` | ✅ | ✅ | ✅ `list(...)` | preserved，外层 list 重建 |
| `rows` | ✅ | ✅ | ✅ `list(...)` | preserved，外层 list 重建；row dict 未重新验证 dtype |
| `row_count` | ✅ derived | ✅ | ❌ | 显式字段在 L296-L302 未复制；仍可由 `len(rows)` 再派生 |
| `error` | ✅ | ✅ | ✅ | preserved |

### 9.5 `row_count` 随后被重新计算

结论：Workflow 的 tool call summary 再次以 `len(execution.rows)` 计算 row count，而不是使用 MCP dict 的 `row_count`。

证据：

`backend/app/workflows/query_graph.py:L322-L335`

```python
call = {
    "call_index": int(database_call.get("call_index") or 1),
    "database": database,
    ...
    "sql": execution.sql,
    "success": execution.success,
    "row_count": len(execution.rows),
    "error": execution.error,
}
```

这里的 `database` 也不是从 `raw_execution["database"]` 复制，而是 L294 从 `state["database_names"]` 重新选取。因此两个值可能数值相同，但 provenance 不同。

### 9.6 旁路：原始 MCP dict 并未完全从最终对象消失

结论：`database` 和 `row_count` 虽然不在 rebuilt `SqlExecution`，原 `tool_result` 仍随 trace 进入 execution log。

证据：

`backend/app/workflows/query_graph.py:L303-L311`

```python
trace = list(state.get("mcp_tool_trace") or [])
log = [
    {
        "stage": "mcp_tool_call",
        "success": not bool(item.get("result", {}).get("error")),
        **item,
    }
    for item in trace
]
```

`item` 来自 Agent trace，其中 `item["result"]` 就是完整 tool_result dict。`ResultBuilder.completed()` 又把 `execution_log` 写入 QueryResult（`result_builder.py:L132`）；失败路径也写入（`L151-L152`）。

因此应分两种观察口径：

- **canonical execution contract**：rebuilt SqlExecution 不含 database/row_count；
- **diagnostic nested data**：QueryResult.execution_log 的 MCP trace 仍可能含完整原 dict。

### 9.7 对象身份

静态源码可以确认这些类型边界：

```text
DatabaseQueryResult (Pydantic)
→ structured_content (dict)
→ LocalMcpClient return (dict)
→ QueryState.mcp_execution (dict)
→ rebuilt SqlExecution (dataclass)
```

`columns=list(...)` 和 `rows=list(...)` 会创建新的外层 list；内部 row dict 是否在 LangGraph checkpoint/serialization 中仍保持同一对象 identity，不是业务 contract，也无法仅靠这段静态源码保证。字段值语义是可确认的，对象 identity 不应依赖。

---

## 10. ResultBuilder / QueryResult

### 10.1 `ResultBuilder.completed()` 从 `SqlExecution` 读取什么

结论：它直接从 `combined` 读取 `columns` 三次、`sql` 一次、`rows` 一次；不读取 dtype（对象中没有），也不读取 `success/error` 填入 QueryResult 顶层。

证据：

`backend/app/workflows/result_builder.py:L84-L139`

关键代码：

```python
metric_columns = [
    column for column in combined.columns
    if any(term in column for term in ("额", "数", "率", "平均", "目标"))
]
dimension_columns = [
    column for column in combined.columns if column not in metric_columns
]

return QueryResult(
    ...
    interpretation=Interpretation(...),
    sql=combined.sql,
    columns=combined.columns,
    rows=combined.rows,
    analysis=final.get("analysis"),
    execution_log=execution_log,
    tool_calls=tool_calls,
    ...
)
```

`executions: list[SqlExecution]` 参数在当前 `completed()` 函数主体中没有被使用；单库路径传入 `[execution]`，但 QueryResult 没有保留一个 executions 列表。

### 10.2 ResultBuilder 重新推断的业务语义

结论：metric/dimension 不是来自 DuckDB physical type，也不是从 schema field role 精确映射，而是基于**返回列名中文子串**的启发式分类。

证据：

`backend/app/workflows/result_builder.py:L95-L99`

```python
metric_columns = [
    column for column in combined.columns
    if any(term in column for term in ("额", "数", "率", "平均", "目标"))
]
dimension_columns = [column for column in combined.columns if column not in metric_columns]
```

解释：

- 名称包含“额/数/率/平均/目标” → metric；
- 其他列 → dimension；
- 这不是 regex，只是 substring test；
- 不读取 `rows` 值类型来分类；
- 不读取 DuckDB `type_code`；
- 不读取 `schema_graph.fields[*].role` 进行 output-column mapping。

因此 `Interpretation.metric/dimension` 是 ResultBuilder 后处理推断，可能与数据库 physical dtype 和 schema business role 不一致。

### 10.3 table/time/analysis 分别来自哪里

证据：

`backend/app/workflows/result_builder.py:L92-L123`

```python
graph = state.get("schema_graph") or {}
table_ids = [item["id"] for item in graph.get("tables", [])]
table_labels = [item["label"] for item in SCHEMA if item["id"] in table_ids]
...
time_range="、".join(
    (state.get("extraction") or {}).get("time_expressions") or []
) or "未指定",
table="、".join(table_labels) or "Schema召回数据表",
```

来源分类：

| QueryResult 信息 | 来源 | 性质 |
|---|---|---|
| `interpretation.table` | schema graph 选中 table ids，再到静态 SCHEMA 找 label | schema/retrieval context，不是 cursor column lineage |
| `interpretation.time_range` | request extraction 的 time expressions | 用户语义提取，不是 DB result metadata |
| `interpretation.metric/dimension` | output column name substring heuristic | ResultBuilder 推断 |
| `analysis/result_title/status(valid)` | `ResponseGenerator.finalize()` 返回的 LLM JSON | 生成式后处理，不是 DB 原始事实 |
| `sql/columns/rows` | rebuilt `SqlExecution` | 数据库结果主路径 |

ResponseGenerator 的证据：`backend/app/querying/response_generator.py:L41-L56`。它把 query、SQL、columns、前 N rows、schema context 和用户保存表 context 发给模型，再取回 `valid/reason/title/analysis`。

### 10.4 `QueryResult` 的完整结构

结论：最终 API domain model 定义如下。

证据：

`backend/app/models.py:L62-L83`

```python
class QueryResult(BaseModel):
    task_id: str
    status: Literal["waiting_clarification", "completed", "failed"]
    route: Literal["database_query", "data_qa", "direct_response"]
    message: str
    interpretation: Interpretation | None = None
    clarification: Clarification | None = None
    steps: list[str] = []
    sql: str | None = None
    columns: list[str] = []
    rows: list[dict[str, Any]] = []
    analysis: str | None = None
    saved: bool = False
    route_reason: str | None = None
    retrieval: dict[str, Any] | None = None
    execution_log: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    result_title: str | None = None
    analysis_sources: list[dict[str, Any]] = Field(default_factory=list)
    standalone_query: str | None = None
    schema_graph: dict[str, Any] | None = None
    workflow_mode: str | None = None
```

与数据库结果**直接对应**的顶层字段主要只有：

- `sql`；
- `columns`；
- `rows`。

与执行间接有关：

- `status/message`：执行状态与 LLM `final.valid` 的综合结果；
- `execution_log/tool_calls`：诊断和调用摘要；
- `analysis/result_title`：LLM 结果说明；
- `interpretation`：schema/extraction/列名启发式形成的语义摘要；
- `schema_graph/retrieval`：上游检索 context，与 result rows 并行保存。

### 10.5 成功路径保留与丢失

成功时 `ResultBuilder.completed()`：

- ✅ 顶层保留 `combined.sql/columns/rows`；
- ✅ 嵌套保留 execution log 和 tool calls；
- ➕ 增加 interpretation、steps、title、analysis 等后处理信息；
- ❌ 没有顶层 database、success、error、row_count、truncated；
- ❌ 没有 column metadata/type contract；
- ❌ 没有 output column → source table/field 的 lineage mapping；
- ⚠️ database/row_count/success/error 可在 nested `execution_log` 或 `tool_calls` 找到，但不是稳定的顶层 result data contract。

### 10.6 失败路径的差异

证据：

`backend/app/workflows/result_builder.py:L142-L156`

```python
return QueryResult(
    task_id=state["task_id"],
    status="failed",
    route="database_query",
    message="SQL生成或执行失败",
    analysis=execution.error,
    sql=execution.sql or None,
    ...
    execution_log=log,
    ...
)
```

失败 QueryResult 顶层：

- `sql` 保留；
- `error` 被转换成 `analysis`；
- `columns/rows` 使用 QueryResult 默认空列表；
- `execution_log` 保留，里面可含 MCP trace result；
- 没有把 `_execute_single_database()` 生成的 `call` 传入 `ResultBuilder.failed()`，因此 `result.tool_calls` 使用默认空列表。尽管 LangGraph state update 同时含 `tool_calls:[call]`（`query_graph.py:L337-L339`），`_state_result()` 最终只验证 `state["result"]`，不会把 state 外层 tool_calls 补回 QueryResult。

### 10.7 最终无法从 canonical QueryResult 恢复的信息

不依赖诊断日志、只看 `QueryResult.sql/columns/rows` 的 canonical data 时，无法恢复：

- column physical type/type_code；
- Decimal precision/scale；
- column nullability；
- DATE/TIMESTAMP 与同形 VARCHAR 的确定区别；
- INTEGER/BIGINT、FLOAT/DOUBLE 的确定区别；
- raw positional tuple 和重复列名被覆盖的值；
- raw fetched count；
- total matching row count；
- truncated 状态；
- output column 的 source table/source field lineage；
- unit；
-可靠的 metric/dimension/time semantic mapping。

`QueryResult.schema_graph` 可能保存候选字段和业务 role，但没有建立“这个具体 output alias 对应那个 schema field”的确定映射，所以不能把 schema graph 的存在等同于结果列 lineage 已保留。

---

## 11. Full Data Loss Table

### 11.1 状态图例

```text
✅ preserved              原信息以相同语义保留
🔄 transformed            值/结构/语义发生转换
➕ derived/added           本层新加或从已有数据推导
❌ lost                   上一层已有的有效信息未进入本层
⚠️ ambiguous              仍可观察或旁路存在，但语义/Contract 不稳定或已改变
N/A not available         上一层本来就没有直接提供，不能称为本层丢失
```

### 11.2 完整横向表

> “Workflow dict”主列指 `state["mcp_execution"]`；另有 `mcp_tool_trace` 诊断旁路，会在单元格中单独注明。  
> “QueryResult”同时说明 canonical 顶层字段与 nested `execution_log/tool_calls/schema_graph`，避免把两者混为一谈。

| Information | DuckDB / cursor | `SqlExecution` | `DatabaseQueryResult` | MCP `structured_content` | Workflow dict | rebuilt `SqlExecution` | `QueryResult` | 首次变化/丢失位置 |
|---|---|---|---|---|---|---|---|---|
| SQL | ✅ `safe_sql` 是 execute 输入，不属于 description | ✅ 成功保存 safe SQL；失败保存原输入 | ✅ | ✅ | ✅ | ✅，经 `str/fallback` | ✅ 顶层 `sql` | 🔄 `_validate_sql()` 清理；`duckdb_engine.py:L40,L49-L51` |
| logical database | ⚠️ engine 参数中有；cursor metadata 无此字段 | ❌ 无字段 | ➕ closure 加入 | ✅ | ✅ `mcp_execution` | ❌ 未复制 | ⚠️ 无顶层字段；completed 时可在 tool_calls/log/schema context 中出现 | 第一次未进入 `SqlExecution`：`duckdb_engine.py:L49`；再次丢弃：`query_graph.py:L296-L302` |
| success | N/A cursor 无 bool；成功由控制流体现 | ➕ `True/False` | ✅ | ✅ | ✅ | ✅ `bool(...)` | 🔄 顶层变成 `status/message`，nested log/call 有 bool | `duckdb_engine.py:L49-L51` 新增 |
| error | N/A cursor；失败表现为 exception | 🔄 exception → `str` | ✅ | ✅ | ✅ | ✅ | 🔄 失败时进入 `analysis`，并在 log 中保留 | `duckdb_engine.py:L50-L51` 丢失 exception 类型/traceback |
| column name | ✅ `description[*][0]` | ✅ `columns` | ✅ | ✅ | ✅ | ✅ | ✅ 顶层 `columns` | 保留链：`duckdb_engine.py:L44,L49` |
| column order | ✅ description/tuple 顺序 | ✅ columns 顺序；row 改成 mapping | ✅ | ✅ | ✅ | ✅ | ✅ columns 顺序 | row positional form 在 `duckdb_engine.py:L45-L47` 转换 |
| duplicate column values | ✅ raw tuple 分开保存每个位置 | ❌ row dict 同名 key 后值覆盖前值 | ❌ | ❌ | ❌ | ❌ | ❌ | `duckdb_engine.py:L46` dict comprehension |
| physical type / type_code | ✅ `description[*][1]`，当前有效 | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | `duckdb_engine.py:L44` 只取 item[0] |
| INTEGER vs BIGINT | ✅ type_code 可区分 | ❌ rows 中都只是 int | ❌ | ❌ JSON number | ❌ | ❌ | ❌ | `duckdb_engine.py:L44` |
| FLOAT vs DOUBLE | ✅ type_code 可区分 | ❌ rows 中都只是 float | ❌ | ❌ JSON number | ❌ | ❌ | ❌ | `duckdb_engine.py:L44` |
| DB-API precision slot | ⚠️ 位置存在，当前 probe 为 None | N/A 无有效输入 | N/A | N/A | N/A | N/A | N/A | 当前 DuckDB runtime 未提供，不是 AskData 单独丢失 |
| DB-API scale slot | ⚠️ 位置存在，当前 probe 为 None | N/A 无有效输入 | N/A | N/A | N/A | N/A | N/A | 当前 DuckDB runtime 未提供 |
| Decimal declared `(p,s)` | ✅ 当前 type_code 如 `DECIMAL(10,2)` | ❌，且 value 转 float | ❌ | ❌ | ❌ | ❌ | ❌ | type_code 丢在 L44；Decimal 转换在 `L148-L149` |
| nullability | ⚠️ `null_ok` slot 存在但当前为 None | N/A | N/A | N/A | N/A | N/A | N/A | 当前 cursor 未提供可用值；Contract 也无字段 |
| raw Python value type | ✅ tuple value object | 🔄 DATE/TS→str，Decimal→float；其他对象类别仍可观察 | ✅ transformed values | 🔄 JSON-compatible dump | ✅ | ✅ | ✅ transformed values | `_json_value()`：`duckdb_engine.py:L145-L150` |
| serialized value type | N/A 尚未 normalization | ➕ JSON-oriented Python values | ✅ | ✅ JSON-compatible | ✅ | ✅ | ✅ rows | `duckdb_engine.py:L45-L47` 首次形成 |
| raw positional row tuple | ✅ | 🔄 tuple→dict | ❌ | ❌ | ❌ | ❌ | ❌ | `duckdb_engine.py:L45-L47` |
| row data | ✅ cursor 可流式读取；局部只 fetch 前 201 | 🔄 最多前 200、normalized dict | ✅ | ✅ | ✅ | ✅ | ✅ 顶层 rows | 截断在 `duckdb_engine.py:L43,L47` |
| raw fetched row count | ✅ 可由 `len(raw_rows)` 得到 | ❌ 无字段 | ❌ | ❌ | ❌ | ❌ | ❌ | 构造 `SqlExecution` 的 `L49` 未保存 |
| returned row count | ➕ `len(raw_rows[:200])` 可得 | ⚠️ 无字段，但 `len(rows)` 可派生 | ➕ 显式 `row_count=len(rows)` | ✅ | ✅ | ⚠️ 显式字段丢失，但仍可由 rows 派生 | ⚠️ tool_calls/log 中有；无顶层字段 | 添加：`database_tools.py:L41`；主路径丢弃：`query_graph.py:L296-L302` |
| total matching row count | N/A 当前未计算；cursor.rowcount=-1 | N/A | N/A | N/A | N/A | N/A | N/A | 从未进入这条 Contract；除非 SQL 自己查询 COUNT |
| truncated flag | ✅/➕ `len(raw_rows)>200` 可在局部可靠判断 | ❌ 未创建字段 | ❌ | ❌ | ❌ | ❌ | ❌ | `duckdb_engine.py:L43-L49` 放弃第 201 行信号 |
| remaining cursor rows | ✅ 在 cursor 中尚可 fetch | ❌ connection 随 with 关闭 | ❌ | ❌ | ❌ | ❌ | ❌ | `duckdb_engine.py:L49` 离开 with，`connect():L71-L73` close |
| source table | N/A description 不给 output lineage；SQL 文本中仅有可解析引用 | ⚠️ SQL 保留，但无列级 mapping | ⚠️ 同左 | ⚠️ 同左 | ⚠️ state 另有 schema_graph | ⚠️ SQL 仍在 | ⚠️ schema_graph/table interpretation 是候选上下文，不是 column lineage | 未建立确定映射；不能简单标 lost |
| Schema field mapping | N/A cursor 不拥有 | N/A | N/A | N/A | ➕ state 另有 schema_graph，但不在 mcp_execution | N/A execution object | ⚠️ `schema_graph` 保留候选字段；没有 output alias→field mapping | 作为旁路 context 加入，不是 DB result 传递 |
| business role: metric/dimension | N/A cursor 不拥有 | N/A | N/A | N/A | ⚠️ schema graph 可含 field role，未映射输出列 | N/A | ➕ ResultBuilder 按列名子串推断；schema_graph 另存 | `result_builder.py:L95-L123` 后处理推断 |
| business time role | N/A | N/A | N/A | N/A | ⚠️ extraction/schema context 旁路 | N/A | ➕ interpretation.time_range 来自 extraction | `result_builder.py:L119-L121`，非 DB metadata |
| unit | N/A cursor 不拥有 | N/A | N/A | N/A | N/A：当前 schema field contract 无显式 unit | N/A | N/A：无显式 unit 字段 | `database.py:L9-L26` 的 field keys 不含 unit |
| `DatabaseQueryResult` Pydantic identity | N/A | N/A | ➕ 有 | ❌ dump 后为 dict | ❌ | ❌ 变成另一 dataclass | ❌，最终是 QueryResult model | MCP SDK `func_metadata.py:L140-L144` |
| MCP `content` | N/A | N/A | N/A | ⚠️ CallToolResult 另有 content，不在 structured dict | ❌ 成功路径忽略 | N/A | N/A | `mcp_runtime/client.py:L45-L54` 仅 error 时读 content |
| MCP `is_error` | N/A | N/A | N/A | ➕ CallToolResult transport/tool 状态 | ❌ client 检查后不保存 | N/A | N/A | `mcp_runtime/client.py:L45-L54` |

### 11.3 主表最重要的读法

1. `❌ lost` 只用于“上游确有有效信息、下游没有”。例如 type_code 和第 201 行截断信号。
2. `N/A` 用于“这一层天然没有/当前 runtime 未提供”。例如 cursor 没有业务 unit、当前 null_ok slot 是 None。
3. `⚠️` 表示值可能还在 SQL、schema_graph 或 diagnostic log 中，但没有形成可靠的 canonical mapping/field。
4. `➕` 不代表数据库事实被恢复。例如 ResultBuilder 的 metric/dimension 是新推断，不是 cursor metadata。

---

## 12. ASCII Data Loss Map

```text
DuckDB 1.5.5 / DuckDBPyConnection result cursor
│
├── safe SQL（execute 的外部输入）                         ✅
├── description[*][0] column name                        ✅
├── description[*][1] type_code                          ✅ 有效
│     ├── BIGINT / INTEGER / DOUBLE / FLOAT / DATE ...
│     └── DECIMAL(10,2) 中含 p/s
├── description[*][2..6]                                 ⚠️ slot 存在，本次均 None
├── raw row                                               ✅ positional tuple
├── raw Python types                                      ✅ int/float/Decimal/date/...
├── raw_rows count                                        ✅ 最多 201，局部可知
├── total matching count                                  N/A：rowcount=-1，未计算
└── source/business metadata                              N/A：description 不提供
│
│  backend/app/querying/duckdb_engine.py:L43-L49
│  ├── 只取 item[0]                                      ❌ type_code 丢失
│  ├── raw_rows[:200]                                    ❌ 第 201 行/截断信号丢失
│  ├── tuple → dict                                      🔄 positional form 消失
│  │      └── duplicate key                              ❌ 前值被覆盖
│  ├── date/datetime → ISO str                           🔄 type identity 丢失
│  └── Decimal → float                                   🔄 exact decimal 语义丢失
▼
SqlExecution dataclass
│
├── sql                                                  ✅
├── success                                              ➕
├── columns                                              ✅ names only
├── rows                                                 ✅/🔄 最多 200 JSON-oriented dicts
├── error                                                ➕ exception text
├── database                                             ❌ 无字段
├── column metadata                                      ❌ 无字段
├── fetched/total/truncated                              ❌/N/A/❌
└── lineage/business role/unit                           N/A
│
│  backend/app/mcp_runtime/tools/database_tools.py:L35-L42
│  ├── database from closure                             ➕
│  └── row_count = len(rows)                             ➕ returned count only
▼
DatabaseQueryResult (Pydantic)
│
├── database/sql/success/columns/rows/row_count/error    ✅
└── dtype/truncated/total/lineage                         ❌ 仍不存在
│
│  MCP SDK func_metadata.py:L140-L144
│  └── output validation + model_dump(mode="json")       🔄
▼
MCP CallToolResult
│
├── structured_content: dict                             ✅ 7 个字段值
├── content: ContentBlock list                           ➕ transport representation
└── is_error: bool                                       ➕ MCP execution metadata
│
│  backend/app/mcp_runtime/client.py:L41-L54
│  ├── success: 只取 structured_content
│  └── dict(structured_content)                          🔄 Pydantic/MCP identity 消失
▼
普通 tool_result / Workflow state
│
├── state["mcp_execution"]: 7-field dict                 ✅
└── state["mcp_tool_trace"][*].result                    ✅ 诊断旁路副本/引用
│
│  backend/app/workflows/query_graph.py:L293-L302
│  ├── copy sql/success/columns/rows/error                ✅
│  ├── database                                           ❌ 主路径不复制
│  └── row_count                                          ❌ 主路径不复制
▼
rebuilt SqlExecution
│
├── sql/success/columns/rows/error                        ✅
├── returned count                                        ⚠️ len(rows) 可再派生
└── database                                              ❌
│
├── ResponseGenerator.finalize()
│     ├── 默认只看前 50 rows                              ⚠️ analysis 基于子集
│     └── valid/title/analysis                            ➕ LLM 后处理
│
└── ResultBuilder.completed()
      ├── metric/dimension by column-name substring       ➕ 启发式，不是 DB 事实
      ├── table labels from schema_graph + SCHEMA         ➕ schema context
      ├── time range from extraction                      ➕ query semantics
      └── sql/columns/rows                                ✅
▼
QueryResult
│
├── sql / columns / rows                                  ✅ canonical result data
├── status / message                                      🔄 execution + LLM valid
├── interpretation                                        ➕ inferred/context-derived
├── analysis / title                                      ➕ LLM-generated
├── execution_log                                         ✅ 原 MCP dict 可嵌套保留
├── tool_calls                                            ➕ database/row_count 摘要（成功路径）
├── schema_graph / retrieval                              ✅ 上游 context，非 column lineage
├── physical dtype / p/s / nullability                    ❌
├── total count / truncated                               ❌
└── explicit output-column semantic mapping / unit        ❌ / N/A
```

---

## 13. Three Contract Boundaries

### Boundary A：DuckDB cursor → SqlExecution

#### 输入拥有的信息

- 当前 query result 的 ordered column descriptions；
- 有效 column names 和 type_codes；
- DECIMAL type_code 中的 precision/scale 表示；
- positional raw tuple values 及其 Python runtime types；
- 可继续 fetch 的 cursor state；
- `raw_rows` 局部最多 201 行，因此可判断是否超过 200。

#### 输出拥有的信息

- safe/original SQL 文本；
- success；
- column names；
- 最多 200 个 normalized row dict；
- error string。

#### 新增信息

- `success`；
- error 时的异常文本。

#### 转换信息

- tuple → dict；
- date/datetime → ISO str；
- Decimal → float；
- 全结果流 → 前 200 rows。

#### 丢失信息

- type_code；
- Decimal physical `(p,s)`；
- raw positional representation；
- duplicate-column 被覆盖的值；
- 第 201 行和 truncation signal；
- fetched count 和 remaining cursor state；
- exception object 类型/traceback。

#### 未来 Derive 是否可能需要

高度可能需要：numeric/date 判断依赖 physical type；安全 SUM/AVG/division 依赖 numeric/decimal contract；结果完整性判断依赖 truncated。Boundary A 是最不可逆、对 Derive 影响最大的边界。

### Boundary B：SqlExecution → DatabaseQueryResult → MCP structured_content

#### 输入拥有的信息

`SqlExecution` 的五字段和已 normalized rows。

#### 输出拥有的信息

结构化 7 字段 dict：`database/sql/success/columns/rows/row_count/error`。

#### 新增信息

- database：来自 Tool closure；
- row_count：`len(rows)` 派生的返回行数；
- MCP `content/is_error` transport metadata。

#### 转换信息

- dataclass → Pydantic output model；
- Pydantic model → JSON-compatible structured dict；
- structured dict → LocalMcpClient 普通 dict。

#### 丢失信息

- 当前 7 个业务字段值没有在此边界丢失；
- `DatabaseQueryResult` Pydantic identity 消失；
- `CallToolResult` 和成功 content representation 不传给 Workflow。

#### 未来 Derive 是否可能需要

database provenance 和 returned row count 可能有用，并且本边界已经提供；但 Boundary A 丢失的 physical dtype/total/truncated 没有在这里恢复。MCP JSON 化本身不是主要数据损失点，Contract 字段集合才是限制。

### Boundary C：MCP result / Workflow state → rebuilt SqlExecution → ResultBuilder / QueryResult

#### 输入拥有的信息

- `mcp_execution` 7 字段 dict；
- `mcp_tool_trace` 中的原 MCP result；
- Workflow 的 schema_graph、extraction、query context；
- database_names。

#### 输出拥有的信息

- rebuilt SqlExecution 的五字段；
- QueryResult canonical `sql/columns/rows`；
- execution log/tool call summaries；
- schema/retrieval context；
- interpretation、analysis、title、status。

#### 新增信息

- call summary 中重新选择的 database、重新计算的 `len(rows)`；
- metric/dimension 列名启发式；
- table/time interpretation；
- LLM `valid/title/analysis`；
- Workflow steps/status/message。

#### 转换信息

- dict → SqlExecution dataclass；
- success/error → status/message/log；
- error → failed QueryResult.analysis；
- SqlExecution + contexts → QueryResult；
- QueryResult → JSON dict → 新 QueryResult instance。

#### 丢失信息

- database/显式 row_count 不进入 rebuilt SqlExecution；
- `executions` list 当前不进入 QueryResult；
- canonical QueryResult 没有 success/error/row_count/truncated/type metadata 字段；
- 但 database/row_count 等通常仍在 diagnostic log/tool_calls 旁路，不能说整个对象彻底丢失。

#### 未来 Derive 是否可能需要

Derive 若只接 rebuilt SqlExecution 或 canonical QueryResult，将看不到 database 的稳定字段、显式 returned count 和所有 physical metadata。若读取 nested logs/schema_graph，只能得到旁路信息，且仍缺 output-column 精确 mapping 与 truncation。

---

## 14. Implications for Future Derive

本节只评估当前 Contract 是否足够，不设计或建议实现。

### 14.1 三类“类型”必须分开

#### A. Physical Type

数据库执行层的真实类型，例如：

```text
INTEGER / BIGINT / FLOAT / DOUBLE / DECIMAL(10,2)
DATE / TIMESTAMP / VARCHAR / BOOLEAN
```

当前 DuckDB `cursor.description[*][1]` 能提供 type_code，但 AskData 不保留。

#### B. Serialization Type

`SqlExecution.rows` / JSON 中实际看到的容器值类型：

```text
int / float / str / bool / None
JSON number / string / boolean / null
```

这是 `_json_value()` 和 JSON serialization 后的表示，不等价于 physical type。

#### C. Schema / Business Semantic Type

业务含义，例如：

```text
销售额 = metric，可 SUM，可能有货币单位
销售地区 = dimension
order_date = time dimension
order_id = identifier，可用于 COUNT
```

当前静态 SCHEMA 的 `_field()` 包含 `type/role/aggregation`（`backend/app/database.py:L9-L26`），但没有显式 `unit`。QueryResult 保存 schema_graph，却没有确定的 output column alias → schema field mapping。

### 14.2 为什么看 rows 的 Python 类型不等于知道 dtype

当前真实转换已经制造多对一映射：

```text
INTEGER ─┐
         ├→ Python int → JSON number
BIGINT  ─┘

FLOAT  ──┐
DOUBLE ──┼→ Python float → JSON number
DECIMAL ─┘   （Decimal 先被显式转 float）

DATE      ─┐
TIMESTAMP ─┼→ Python str → JSON string
VARCHAR   ─┘
```

而且：

- 全列都是 NULL 时，rows 只显示 `None`；
- 空结果没有任何 value sample；
- 聚合表达式的 output dtype 可能不同于源字段 dtype；
- SQL alias 可能改掉原字段名；
- 同一个 numeric physical type 不自动说明业务上可加总；identifier 虽是整数也不应被当金额 SUM；
- 两个 numeric 列能做除法也不代表业务上有意义，仍涉及零值、NULL、量纲和单位。

### 14.3 Derive 能力评估

| 未来判断 | 当前 Contract 评价 | 原因 |
|---|---|---|
| 某列是不是 numeric | **不足** | rows sample 只能猜；INTEGER/BIGINT 与 FLOAT/DOUBLE/DECIMAL 已合并，空/全 NULL 无法判断，type_code 丢失 |
| 能不能 `SUM` | **部分足够** | schema_graph 可能带源字段 aggregation/role，但输出列没有确定映射；仅看 int/float 不知道 identifier、已聚合指标或业务可加性 |
| 能不能 `AVG` | **部分足够** | 数值 sample 不证明 physical dtype/业务含义；schema metadata 有帮助但无法稳健映射到 output alias |
| 两列能不能安全相除 | **不足** | 缺可靠 dtype、nullability、零值约束、unit/量纲和业务语义；sample 不足以证明全列安全 |
| 某列是不是 date | **不足** | DATE/TIMESTAMP 已变 str，与同形 VARCHAR 无法可靠区分；schema context 只提供候选且缺 output mapping |
| 某列是不是 dimension | **部分足够** | ResultBuilder 已按名称猜，schema role 也可能存在；但不是 DB/lineage 支持的可靠结论 |
| 某列是不是 metric | **部分足够** | 同上；“名称含额/数/率”等只是启发式，numeric 也不等于 metric |
| 是否发生结果截断 | **不足** | engine 读了第 201 行却未保存 flag；`row_count=200` 同时可能表示恰好 200 或至少 201 |
| 返回了多少行 | **足够** | 可由 `len(rows)` 得到；MCP 和 tool call summary 也派生 row_count |
| SQL 总共命中多少行 | **不足** | cursor.rowcount 为 -1，当前执行未做 total count，returned row_count 语义不同 |
| 精确 Decimal 计算是否仍安全 | **不足** | Decimal 已转 float，p/s 和 exact representation 丢失 |
| column source lineage | **不足** | SQL/schema context 尚在，但没有 output alias→source field 的确定 Contract；表达式/聚合更无法靠名称恢复 |
| unit 是否一致 | **不足** | 当前 schema field contract 没有显式 unit；rows 和 cursor description 也不提供业务单位 |

### 14.4 对未来 Derive 最重要的事实判断

1. 当前 Contract 的强项是展示：SQL、列名、前 200 行 JSON-friendly 数据。
2. Serialization type 只能说明“当前值如何编码”，不能替代 physical type。
3. Physical type 只能说明数据库表示，也不能单独决定 metric/dimension 或合法聚合。
4. Schema role/aggregation 是业务 metadata，但当前没有把每个 output column 稳定映射回 schema field。
5. ResultBuilder 现有 interpretation 是后处理推断；它不能被当作 DuckDB 原始事实。
6. `row_count` 足以描述 returned rows，不足以描述 total rows 或 truncation。

---

## 15. Source Evidence Index

### 15.1 项目源码索引

| 文件 | 类 / 函数 | 当前行号 | 本报告中的作用 |
|---|---|---:|---|
| `backend/app/querying/duckdb_engine.py` | `DuckDbEngine.execute()` | L33-L51 | 真正执行 SQL；description 抽取；fetch 201；返回 200；构造 SqlExecution |
| `backend/app/querying/duckdb_engine.py` | `DuckDbEngine.connect()` | L53-L73 | 创建内存 DuckDB、注册 CSV views、关闭 connection |
| `backend/app/querying/duckdb_engine.py` | `DuckDbEngine._validate_sql()` | L75-L127 | 生成执行用 `safe_sql`；本报告仅用于区分成功保存的 SQL |
| `backend/app/querying/duckdb_engine.py` | `clean_sql()` | L138-L142 | 去除 fence/空白的 SQL 文本转换 |
| `backend/app/querying/duckdb_engine.py` | `_json_value()` | L144-L150 | date/datetime→ISO str，Decimal→float |
| `backend/app/querying/models.py` | `SqlExecution` | L7-L13 | querying 层五字段结果 Contract |
| `backend/app/mcp_runtime/tools/database_tools.py` | `build_database_query_tool()` / `query_database()` | L25-L46 | SqlExecution→DatabaseQueryResult；添加 database，派生 row_count |
| `backend/app/mcp_runtime/schemas.py` | `DatabaseQueryResult` | L21-L28 | MCP database tool 七字段 Pydantic output Contract |
| `backend/app/mcp_runtime/client.py` | `LocalMcpClient._call_tool()` | L41-L54 | 读取 CallToolResult、成功路径选择 structured_content、转普通 dict |
| `backend/app/querying/single_database_agent.py` | `SingleDatabaseAgent.prepare()` | L102-L123 | tool_result 同时进入 execution 与 tool_trace |
| `backend/app/workflows/state.py` | `QueryState` | L6-L38 | 声明 mcp_execution/mcp_tool_trace/execution_log/tool_calls/result 均为 state 字段 |
| `backend/app/workflows/query_graph.py` | `QueryWorkflow.invoke()` / `_state_result()` | L122-L130 | LangGraph state 中的 result dict 最终重建为 QueryResult |
| `backend/app/workflows/query_graph.py` | `_prepare_single_database()` | L261-L290 | DatabaseQueryResult dict 写入 mcp_execution 与 trace state |
| `backend/app/workflows/query_graph.py` | `_execute_single_database()` | L293-L355 | dict→SqlExecution 第二次压缩；日志/call summary；ResultBuilder 调用 |
| `backend/app/querying/response_generator.py` | `ResponseGenerator.__init__()` | L15-L23 | 设置用于 LLM 说明的 table row limit |
| `backend/app/querying/response_generator.py` | `ResponseGenerator.finalize()` | L34-L58 | 用 SQL/columns/前 N rows/schema context 生成 valid/title/analysis |
| `backend/app/workflows/result_builder.py` | `ResultBuilder.completed()` | L84-L139 | 列名启发式、schema/extraction context、构造成功 QueryResult |
| `backend/app/workflows/result_builder.py` | `ResultBuilder.failed()` | L142-L156 | error→analysis、构造失败 QueryResult |
| `backend/app/models.py` | `Interpretation` | L54-L59 | metric/dimension/time/table 后处理表示 |
| `backend/app/models.py` | `QueryResult` | L62-L83 | 最终 API/domain result 完整字段 |
| `backend/app/database.py` | `_field()` | L9-L26 | 当前 schema business metadata keys：type/role/aggregation；无 explicit unit |
| `backend/app/config.py` | `Settings.context_table_row_limit` | L69 | ResponseGenerator 默认只看前 50 rows |

### 15.2 当前安装 MCP SDK 源码索引

| 文件 | 类 / 函数 | 当前行号 | 本报告中的作用 |
|---|---|---:|---|
| `backend/.venv/Lib/site-packages/mcp/server/mcpserver/server.py` | `MCPServer.call_tool()` | L498-L504 | 调 ToolManager，并指定 `convert_result=True` |
| `backend/.venv/Lib/site-packages/mcp/server/mcpserver/tools/tool_manager.py` | `ToolManager.call_tool()` | L75-L87 | 由 tool name 找到并运行 handler |
| `backend/.venv/Lib/site-packages/mcp/server/mcpserver/utilities/func_metadata.py` | `FuncMetadata.convert_result()` | L110-L144 | output model validation、JSON dump、构造 CallToolResult |
| `backend/.venv/Lib/site-packages/mcp_types/_types.py` | `CallToolResult` | L1463-L1483 | `content/structured_content/is_error` 字段定义 |

### 15.3 只读 runtime probe 索引

| Probe | 当前环境 | 已确认事实 |
|---|---|---|
| 多类型内存 SELECT | DuckDB 1.5.5 | description 是 7 元组；type_code 有效；后五位均为 None；raw Python 类型映射 |
| `range(500)` fetch | DuckDB 1.5.5 | fetchmany(201)=201、剩余 299、cursor.rowcount=-1 |
| 真实 `orders_current` 查询 | 项目 CSV-backed DuckDB | BIGINT/DOUBLE/DATE/VARCHAR description；date→str |
| 真实 CSV 57,600 行 cross join | `DuckDbEngine.execute()` | 最终 `SqlExecution.rows` 只有 200，无 truncated |
| 重复列名 SELECT | `DuckDbEngine.execute()` | columns 保留两个同名；row dict 仅保留后值 |
| 进程内 MCP call | MCP 2.0.0 | handler result→CallToolResult；structured_content=dict；LocalMcpClient 返回普通 dict |

### 15.4 对历史 investigation leads 的重新验证

| 历史待验证假设 | 当前结论 |
|---|---|
| cursor.description 可能包含 type_code | **成立**；当前 DuckDB 1.5.5 item[1] 有有效 DuckDBPyType |
| columns 可能只读取 item[0] | **成立**；`duckdb_engine.py:L44` |
| 可能为截断多 fetch 一行 | **部分成立**；确实 fetch 201/return 200，但没有真正生成或传递 truncated |
| 最终 rows 可能限制 200 | **成立**；`raw_rows[:200]` |
| date/datetime 可能字符串化 | **成立**；`_json_value().isoformat()` |
| Decimal 可能类型转换 | **成立**；显式 `float(value)` |
| DatabaseQueryResult 可能多 database/row_count | **成立**；二者分别为 closure metadata 和 returned-row derived value |
| Workflow 可能重建 SqlExecution | **成立**；`query_graph.py:L296-L302`，且未复制 database/row_count |

---

### 我现在作为项目作者必须真正理解的知识点

1. `cursor.description` 的 column name 和 physical type 是两种不同信息。
2. 当前代码只取 `item[0]`，type_code 在第一道 Contract 边界消失。
3. `fetchmany(201)` 的第 201 行只是一条未被保存的截断信号。
4. `row_count=len(rows)` 是返回行数，不是 SQL 总命中数。
5. tuple→dict 会改变行结构，重复列名会造成真实值覆盖。
6. DATE→str、Decimal→float 是业务代码主动转换，不是 MCP 才做的转换。
7. Python `int/float/str` 不能可靠反推 INTEGER/BIGINT/DECIMAL/DATE/VARCHAR。
8. DatabaseQueryResult 比 SqlExecution 多 database 和派生 row_count，没有恢复 dtype。
9. MCP structured_content 保留字段值，但丢失 Pydantic Contract 实例身份。
10. Workflow 重建 SqlExecution 时主路径不复制 database/row_count。
11. execution_log 是原 MCP result 的诊断旁路，不能等同于 canonical result contract。
12. ResultBuilder 的 metric/dimension 是列名启发式，不是数据库或 schema lineage 事实。
13. QueryResult.schema_graph 是相关 schema context，不是 output column→source field 映射。
14. 当前 Derive 最大缺口是 physical dtype、lineage、total count、truncated 和 unit。
15. 展示友好的 JSON rows 与可供可靠 Derive 使用的 typed result contract 不是同一件事。

