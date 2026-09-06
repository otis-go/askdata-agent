# AskData 源码调查：拆开 `mcp_client.call_tool()` 到 DuckDB 的黑盒

> 调查日期：2026-09-01  
> 起点：`SingleDatabaseAgent.prepare()` 中的 `tool_result = mcp_client.call_tool(tool_name, arguments)`  
> 终点：DuckDB 查询结果经 MCP `structured_content` 返回为普通 Python `dict`  
> 依据：当前仓库源码、当前虚拟环境内实际安装的 MCP SDK 源码，以及一次只读本地运行探针。  
> 限制：不重复分析 Prompt、Schema Retrieval、BM25/Dense/RRF/Rerank；不修改业务代码，不讨论重构。

## 0. 先给结论

AskData 中这段 MCP 链的本质是：

> **Workflow 为当前用户创建一个进程内 MCP Server，按 `SCHEMA` 和 `AccessScope` 动态注册受限的 `query_<database>` 工具；MCP SDK 用工具名找到 handler、依据函数类型注解校验参数并调用闭包；闭包把预先绑定的 database/engine/access scope 交给 DuckDB 硬校验和执行；Pydantic 结果再经 MCP `CallToolResult.structured_content` 返回成 Agent 使用的普通 dict。**

最重要的边界：

- LLM 只给 `tool_name` 和 JSON `arguments`，database tool 的 arguments 只有 `sql`。
- MCP 负责工具注册、发现、按名分派、输入/输出 Schema 和结构化传输。
- MCP `READ_ONLY` annotations 是 metadata，不会自动拦截 `DELETE`。
- 真正阻止危险 SQL 的是 `DuckDbEngine._validate_sql()`。
- 当前 MCP Server 与 FastAPI/Workflow 在同一个 Python 进程；不是网络远端 server，也不是子进程。
- 当前 DuckDB 查的是 `backend/data/databases/askdata_mock/*.csv` 创建的内存 views，不是真实线上数据库连接。
- `SingleDatabaseAgent` 最终得到的 `tool_result` 是 `dict[str, Any]`。

一次安全运行探针确认了当前实际类型：

```json
{
  "server_type": "mcp.server.mcpserver.server.MCPServer",
  "result_type": "mcp_types._types.CallToolResult",
  "is_error": false,
  "structured_content_type": "dict",
  "structured_keys": [
    "database", "sql", "success", "columns",
    "rows", "row_count", "error"
  ]
}
```

---

## 1. 起点与第一段真实调用链

位置：`backend/app/querying/single_database_agent.py:102-117`  
类/函数：`SingleDatabaseAgent.prepare()`

```python
tool_name = str(decision.get("tool_name") or "")
arguments = decision.get("arguments")
if tool_name not in tool_names:
    raise ValueError(f"智能体选择了未提供的MCP工具：{tool_name}")
if not isinstance(arguments, dict):
    raise ValueError("MCP工具参数必须是JSON对象")

tool_result = mcp_client.call_tool(tool_name, arguments)
```

本报告从最后一行开始。进入 `LocalMcpClient` 前已有两个应用层前置条件：

1. `tool_name: str` 必须出现在此前 `tools/list` 后过滤得到的 `tool_names`；
2. `arguments` 必须是 Python `dict`。

以数据库工具为例，运行时数据大致是：

```python
tool_name = "query_askdata_mock"
arguments = {
    "sql": "SELECT region, SUM(paid_amount) ..."
}
```

此时并没有直接调用 `query_database()` 或 `DuckDbEngine.execute()`；先进入统一的 MCP client 调用层。

---

## 2. `LocalMcpClient.call_tool()` 本身

位置：`backend/app/mcp_runtime/client.py:10-54`  
类：`LocalMcpClient`

### 2.1 `call_tool()` 是同步函数

```python
def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(self._call_tool(name, arguments))
```

它使用普通 `def`，所以是同步 API。其公开返回注解已经明确写为：

```python
dict[str, Any]
```

这与 `SingleDatabaseAgent.prepare()` 当前同步控制流相匹配：Agent 不需要写 `await`。

### 2.2 为什么还有 `_call_tool()`

```python
async def _call_tool(
    self,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    async with Client(self.server) as client:
        result = await client.call_tool(name, arguments)
    # ...检查并转换 result
```

底层 MCP SDK 的 `Client` 是异步客户端：建立/关闭 session 使用 async context manager，`client.call_tool()` 也必须 `await`。因此项目拆成：

```text
同步业务入口 call_tool()
→ asyncio.run(...)
→ 异步实现 _call_tool()
→ await MCP Client.call_tool()
```

这不是重试，也不是启动另一个 Agent；只是同步/异步接口适配。

### 2.3 `asyncio.run()` 具体做什么

`asyncio.run(self._call_tool(...))` 为这次协程调用创建并管理事件循环，执行到协程完成，最后关闭该事件循环，把协程返回的 dict 交回同步调用方。

当前 `QueryWorkflow`/Agent 是同步调用路径，所以这种桥接能够工作。按 Python 规则，如果在同一线程已经有正在运行的 event loop，直接再次 `asyncio.run()` 会报错；当前 AskData 这条源码路径没有这样嵌套。

### 2.4 `self.server` 是什么对象

构造函数：

```python
def __init__(self, server: MCPServer) -> None:
    self.server = server
```

真实类型是当前 MCP SDK 的：

```text
mcp.server.mcpserver.server.MCPServer
```

它由 `create_local_mcp_server(...)` 在本次请求中创建，里面已经注册时间工具和当前权限允许的数据库工具。它不是 URL 字符串，也不是进程句柄。

### 2.5 这是网络、子进程还是进程内调用

结论：**同一个 Python 进程中的本地 MCP Server。**

AskData 直接执行：

```python
Client(self.server)
```

传给 SDK 的是 `MCPServer` 对象，而不是 `"http://..."` URL。当前安装的 MCP SDK 在：

```text
backend/.venv/Lib/site-packages/mcp/client/client.py:261-292
```

明确说明：传 `Server`/`MCPServer` instance 时使用 in-process 连接；传 URL string 才使用 Streamable HTTP。

SDK 的实际选择代码在同文件 `:390-398`：

```python
srv = self.server
if isinstance(srv, MCPServer):
    srv = srv._lowlevel_server
if isinstance(srv, Server):
    self._connect = _connect_inproc(srv)
elif isinstance(srv, str):
    self._connect = _connect_transport(streamable_http_client(srv))
```

AskData 没有传 `mode="legacy"`，所以使用默认 `mode="auto"`。当前 SDK 的 `_connect_inproc()` 在 `mcp/client/client.py:102-120` 用 direct dispatcher pair 驱动请求；没有网络 socket、没有子进程，也没有 stdio transport，现代默认路径甚至不做 JSON-RPC 字节 framing。

因此“使用 MCP 协议抽象”和“发生远程网络调用”是两件不同的事；当前项目只有前者。

### 2.6 `await client.call_tool()` 返回什么

项目代码：

```python
result = await client.call_tool(name, arguments)
```

当前 MCP SDK 的签名是：

```python
async def call_tool(...) -> CallToolResult
```

实际 Python 类型：

```text
mcp_types._types.CallToolResult
```

其直接字段定义位于当前环境：

```text
backend/.venv/Lib/site-packages/mcp_types/_types.py:1463-1483
```

核心字段是：

```python
content: list[ContentBlock]
structured_content: Any = None
is_error: bool = False
```

### 2.7 `result.is_error` 是什么

`is_error` 表示 MCP tool call 是否以工具错误结束。AskData 检测它：

```python
if result.is_error:
    messages = [
        str(getattr(block, "text", ""))
        for block in result.content
        if getattr(block, "text", "")
    ]
    raise RuntimeError("; ".join(messages) or f"MCP工具调用失败：{name}")
```

它主要覆盖 unknown tool、参数 Schema 验证异常、handler 抛异常等 MCP/tool execution failure。

要注意 AskData 的一个细节：`DuckDbEngine.execute()` 会捕获 SQL validation/DuckDB 错误，并返回 `SqlExecution(success=False, error=...)`，而不是继续抛异常。因此“SQL 被拒绝”通常仍是一个正常返回的 `DatabaseQueryResult`：

```text
CallToolResult.is_error == False
structured_content["success"] == False
structured_content["error"] == "具体 SQL 错误"
```

所以 MCP 层错误状态和业务查询成功状态不能混为一谈。

### 2.8 `result.structured_content` 是什么

`structured_content` 是 tool handler 结构化返回值经过 MCP SDK 输出模型验证并 JSON 化后的内容。

当前 database handler 的返回注解是 `DatabaseQueryResult`。MCP SDK 根据该 Pydantic 模型生成 output schema，并在执行后得到：

```python
{
    "database": ...,
    "sql": ...,
    "success": ...,
    "columns": ...,
    "rows": ...,
    "row_count": ...,
    "error": ...,
}
```

当前运行探针确认其 Python 类型为 `dict`。

### 2.9 为什么还要 `dict(result.structured_content)`

```python
if result.structured_content is None:
    raise RuntimeError(f"MCP工具未返回结构化结果：{name}")
return dict(result.structured_content)
```

这两行建立了 AskData 自己的 client boundary：

1. 强制所有被本项目使用的 MCP tool 必须给结构化输出；只有 `content` 文本不够；
2. 将 MCP result 内部字段规范为一个普通 Python dict；
3. 隐藏 `CallToolResult`、ContentBlock 等 MCP SDK 类型，让上层 Agent 只依赖 `dict[str, Any]`；
4. 返回一个浅层 dict 副本/转换结果，而不是把 SDK 对象继续向上传播。

最终答案：

> `SingleDatabaseAgent` 中的 `tool_result` 是普通的 **`dict[str, Any]`**。database tool 成功或 SQL 业务失败时，dict 都具有固定的 database/sql/success/columns/rows/row_count/error 字段。

---

## 3. MCP Server 在什么时候创建，怎样注册 Tool

### 3.1 从 `QueryWorkflow` 到当前请求使用的本地 Server

**源码位置**：`backend/app/workflows/query_graph.py:35-59`  
**类 / 函数**：`QueryWorkflow.__init__()`、`QueryWorkflow.mcp_client()`

```python
self.database_engine = DuckDbEngine()
self.single_database_agent = SingleDatabaseAgent(
    model_client,
    self.mcp_client,
    self.skills.get("database_query"),
    self.config.mcp_max_tool_calls,
)

def mcp_client(self, access_scope: dict[str, Any]) -> LocalMcpClient:
    scope = AccessScope.from_dict(access_scope)
    return LocalMcpClient(create_local_mcp_server(self.database_engine, scope))
```

实际顺序是：

```text
QueryWorkflow 创建并保存一个 DuckDbEngine
        ↓
把 bound method：self.mcp_client
传给 SingleDatabaseAgent
        ↓
Agent 在一次 prepare() 中以当前 access_scope 调用这个 factory
        ↓
AccessScope.from_dict(access_scope)
        ↓
create_local_mcp_server(self.database_engine, scope)
        ↓
得到本次权限范围对应的 MCPServer
        ↓
LocalMcpClient(server)
```

这里要分清两个生命周期：

- `DuckDbEngine` 在 `QueryWorkflow.__init__()` 时创建并保存在 Workflow 上；
- `MCPServer` 是调用 `QueryWorkflow.mcp_client(access_scope)` 时根据这次的权限范围创建的。

因此，Tool 暴露范围可以随本次请求的 `access_scope` 改变，而不是应用启动后对所有用户永远使用同一份 Tool 注册表。

### 3.2 `create_local_mcp_server()` 创建的是什么

**源码位置**：`backend/app/mcp_runtime/server.py:20-32`  
**函数**：`create_local_mcp_server()`

```python
def create_local_mcp_server(
    engine: DuckDbEngine | None = None,
    access_scope: AccessScope | None = None,
) -> MCPServer:
    """创建与FastAPI运行在同一进程中的MCP服务。"""
    database_engine = engine or DuckDbEngine()
    scope = access_scope or AccessController().resolve(None)
    server = MCPServer(
        name="askdata-local-tools",
        title="AskData本地工具服务",
        description="提供本地数据库只读查询和基础时间计算工具。",
        instructions="调用数据库工具前先根据Schema图生成一条只读DuckDB SQL。",
    )
```

输入与输出：

- `engine`：通常就是 `QueryWorkflow` 保存的 `DuckDbEngine`；没有传入才新建。
- `access_scope`：当前用户的 `AccessScope`；没有传入时才解析默认用户。
- `server`：`mcp.server.MCPServer` 实例。它内部拥有 Tool manager/注册表，负责工具列举、按名称分派和 schema 驱动的参数/返回值处理。

源码 docstring 已直接限定它是“与 FastAPI 运行在同一进程中的 MCP 服务”。这与上一节从 SDK 分支得出的结论一致：本链不是 HTTP 远端 MCP，也不是 stdio 子进程 MCP。

### 3.3 `server.tool(...)(current_datetime)` 到底执行了什么

**源码位置**：`backend/app/mcp_runtime/server.py:34-45`

```python
server.tool(
    name="current_datetime",
    title="获取当前日期时间",
    description="获取Asia/Shanghai或UTC时区的当前日期与时间。",
    annotations=READ_ONLY,
)(current_datetime)

server.tool(
    name="resolve_date_range",
    title="解析相对日期范围",
    description="将今天、昨天、本周、上周、本月、上月或今年转换为明确起止日期。",
    annotations=READ_ONLY,
)(resolve_date_range)
```

这是一种“立即使用 decorator”的写法，可以拆成等价的两步来读：

```python
decorator = server.tool(
    name="current_datetime",
    title="获取当前日期时间",
    description="...",
    annotations=READ_ONLY,
)
decorator(current_datetime)
```

结合当前安装的 MCP SDK，真实动作是：

1. `server.tool(...)` 返回一个 decorator 函数；
2. 第二对括号把 `current_datetime` 作为 `fn` 交给这个 decorator；
3. decorator 调用 `MCPServer.add_tool(fn, name=..., ...)`；
4. SDK 从函数签名和类型注解构造 input/output JSON Schema；
5. SDK 将 Tool 对象保存到按 tool name 索引的内部注册表；
6. decorator 原样返回该 Python 函数。

用于确认该机制的 SDK 位置：

- `backend/.venv/Lib/site-packages/mcp/server/mcpserver/server.py:570-608`：`MCPServer.add_tool()`；
- 同文件 `:621-689`：`MCPServer.tool()` 返回 decorator；
- `backend/.venv/Lib/site-packages/mcp/server/mcpserver/tools/tool_manager.py:39-67`：构造 Tool 并以名称保存；
- `backend/.venv/Lib/site-packages/mcp/server/mcpserver/tools/base.py:58-121`：依据函数签名创建 Tool schema。

它与普通调用的区别是：

```python
handler(...)
```

会**立刻执行**函数体；而：

```python
server.tool(...)(handler)
```

只会把 `handler` 连同 name、description、输入/输出 schema 和 annotations **登记为可发现、可按名调用的 MCP Tool**，此时不会执行数据库 SQL。真正执行要等以后 `client.call_tool(tool_name, arguments)` 通过注册表找到它。

### 3.4 动态生成并注册 `query_<database>`

**源码位置**：`backend/app/mcp_runtime/server.py:47-67`  
**函数**：`create_local_mcp_server()`

```python
databases = sorted({str(table.get("database") or "askdata_mock") for table in SCHEMA})
for database in databases:
    if not scope.allows_database(database):
        continue
    tables = [
        table["id"]
        for table in SCHEMA
        if table.get("database") == database
        and scope.allows_table(database, table["id"])
    ]
    handler = build_database_query_tool(database, database_engine, scope)
    server.tool(
        name=f"query_{database}",
        title=f"查询数据库 {database}",
        description=(
            f"在数据库{database}中执行一条只读DuckDB SQL。"
            f"可用表：{', '.join(tables)}。每次调用最多返回200行。"
        ),
        annotations=READ_ONLY,
    )(handler)
return server
```

按执行顺序逐行还原：

1. `SCHEMA` 中每个 table document 都带 `database`；集合推导提取数据库名并去重、排序，得到 `databases: list[str]`。
2. `for database in databases` 逐库处理。
3. `scope.allows_database(database)` 不通过就 `continue`，该库不会创建 query tool。
4. `tables` 从 `SCHEMA` 中选择“属于当前 database 且 `scope.allows_table(...)` 为真”的 table id。
5. `build_database_query_tool(...)` 创建一个已经绑定 `database`、`database_engine`、`scope` 的 Python handler。
6. `server.tool(name=f"query_{database}", ...)(handler)` 把这个 handler 注册到 Server 的 tool registry。
7. Server 返回给 `LocalMcpClient`。

当前 `backend/app/database.py:42-108` 的 `SCHEMA` 中，五张表的 database 都是 `askdata_mock`，所以有该库权限时，真实产生的 Tool 名是：

```text
query_askdata_mock
```

它**不是**源码里手写的顶层函数 `def query_askdata_mock(...):`。真实函数是 `build_database_query_tool()` 每次调用所创建的内部函数 `query_database`；该 builder 还在 `backend/app/mcp_runtime/tools/database_tools.py:45` 设置：

```python
query_database.__name__ = f"query_{database}"
```

对外暴露的 MCP Tool name 则由注册时的这一行明确决定：

```python
name=f"query_{database}"
```

### 3.5 为什么不硬编码 `query_askdata_mock()`

当前源码体现的直接原因是 Tool 集合由 `SCHEMA + access_scope` 驱动：

```text
SCHEMA 中出现的 database
        ↓
当前 scope 是否允许该 database
        ↓
为每个允许 database 绑定 engine 与 scope
        ↓
注册 query_<database>
```

因此数据库名不是让 Agent 或 LLM 随意传入的普通参数，而是在 Server 创建阶段成为独立 Tool 的身份和闭包状态。当前仓库只有 `askdata_mock` 一个 schema database；“将来若 SCHEMA 增加其他 database，同一段循环可继续注册相应 Tool”是这段通用代码直接支持的能力，但**当前仓库没有可据此声称已经连接了多个生产数据库**。

### 3.6 六个容易混淆的阶段

| 阶段 | 当前代码中的实际责任方 | 当前链中的含义 |
|---|---|---|
| Tool definition | `current_datetime`、`resolve_date_range`、builder 创建的 `query_database` | Python handler 及其类型注解 |
| Tool registration | `create_local_mcp_server()` 调用 `server.tool(...)(handler)` | 将 handler/schema/metadata 放进当前 Server 注册表 |
| Tool discovery | `LocalMcpClient.list_tools()` → `Client.list_tools()` | Agent 获得当前 scope 下可见 Tool 的 name/schema/description |
| Tool selection | LLM decision，随后由 `SingleDatabaseAgent` 校验 | 选择 tool name 和 arguments；不是 MCP Server 替模型选择 |
| Tool execution | `LocalMcpClient.call_tool()` → MCP registry dispatcher → handler | 按 name 找到已注册 handler，并校验/调用 |
| SQL execution | `query_database()` → `DuckDbEngine.execute()` | Python 校验 SQL、加载 CSV view、执行 DuckDB 查询 |

---

## 4. `access_scope` 在哪几层真正生效

### 4.1 `AccessScope` 的真实结构和判定方法

**源码位置**：`backend/app/security/access_control.py:13-26`  
**类**：`AccessScope`

```python
@dataclass(frozen=True)
class AccessScope:
    user_id: str
    roles: tuple[str, ...]
    allowed_databases: frozenset[str]
    allowed_tables: frozenset[str]

    def allows_database(self, database: str) -> bool:
        return database in self.allowed_databases

    def allows_table(self, database: str, table_id: str) -> bool:
        return self.allows_database(database) and table_id in self.allowed_tables
```

它是后端生成的冻结 dataclass。database 权限和 table 权限均是显式白名单；`allows_table()` 还先要求 database 本身被允许。

`QueryWorkflow.mcp_client()` 在 `backend/app/workflows/query_graph.py:57-59` 把 State 中的公开 dict 恢复为 `AccessScope`：

```python
scope = AccessScope.from_dict(access_scope)
return LocalMcpClient(create_local_mcp_server(self.database_engine, scope))
```

因此传入 Tool builder 和 DuckDB engine 的不是 LLM 自己生成的权限参数，而是 Workflow 从后端状态恢复的对象。

### 4.2 当前仓库的示例角色策略

**源码位置**：`backend/app/security/access_control.py:48-89`  
**类 / 函数**：`AccessController.ROLE_POLICIES`、`AccessController.resolve()`

源码中的三种示例身份是：

- `demo_admin`：全部 schema database 和 table；
- `demo_analyst`：`askdata_mock` 和全部表；
- `demo_current_sales`：允许 `askdata_mock`，但表只有 `orders_current`、`customers`、`products`、`sales_targets`，不含 `orders_history`；
- 未识别用户没有 role，解析结果的 database/table 集合为空。

这说明本报告讨论的是项目当前 demo 权限系统，而不是外部 IAM 或生产数据库自身的授权机制。

### 4.3 多层权限链

真实链如下：

```text
后端生成的 access_scope dict
        ↓  AccessScope.from_dict(...)
AccessScope
        ↓  create_local_mcp_server(...)
allows_database(database)
        ├─ false：continue，根本不注册 query_<database>
        └─ true：继续
                ↓
        allows_table(database, table_id)
                ↓
Tool description 的“可用表”只列允许 table
                ↓
build_database_query_tool(database, engine, scope)
                ↓
scope 被闭包固定在 handler 内
                ↓
DuckDbEngine.execute(database, sql, scope)
                ↓
_validate_sql(...)
        ├─ 再查 allows_database(database)
        └─ 对 SQL 中每个引用表再查 allows_table(...)
                ↓
只有通过硬校验才 connection.execute(safe_sql)
```

这不是只依赖 LLM“自觉不访问”。它同时控制：

1. **Tool 是否存在/可发现**；
2. **Tool description 暴露的表名**；
3. **实际执行前能否通过 Python validation**。

### 4.4 Q1：没有 database 权限时，`query_<database>` 会怎样

**源码证据**：`backend/app/mcp_runtime/server.py:48-50`

```python
for database in databases:
    if not scope.allows_database(database):
        continue
```

答案：**根本不会注册**。因此 `tools/list` 中不会出现该 Tool。若绕过 Agent 的 tool list，直接以这个未知名称调用，MCP ToolManager 也找不到对应 handler，SDK 返回 error result；`LocalMcpClient._call_tool()` 随后因 `result.is_error` 抛出 `RuntimeError`。

仓库测试也锁定了这一行为：`backend/tests/test_mcp_runtime.py:62-75` 对无权限用户断言 query tool 不可见，直接调用会报错。

### 4.5 Q2：有 database 权限，但只允许部分 table 时，模型看到什么

在本次关注的 MCP 边界中，模型通过 Tool discovery 得到的 database tool description 由以下代码形成。

**源码位置**：`backend/app/mcp_runtime/server.py:51-64`

```python
tables = [
    table["id"]
    for table in SCHEMA
    if table.get("database") == database
    and scope.allows_table(database, table["id"])
]

description=(
    f"在数据库{database}中执行一条只读DuckDB SQL。"
    f"可用表：{', '.join(tables)}。每次调用最多返回200行。"
)
```

所以：

- database tool 仍会被注册；
- Tool 名仍是 `query_askdata_mock`；
- description 中的“可用表”只列白名单内的表；
- Tool 的 input schema 只有 `sql`，不会向模型暴露一个可修改的 `access_scope` 参数。

以 `demo_current_sales` 为例，它能看到这个 database tool，但其可用表列表不含 `orders_history`。

补充边界：Workflow 上游还会用权限过滤 schema，但这不属于本次 MCP 黑盒的展开范围；即使上游信息隐藏失误，下面的 `_validate_sql()` 仍是执行前的最终硬校验之一。

### 4.6 Q3：SQL 引用未授权表时还有硬校验吗

有。

**源码位置**：`backend/app/querying/duckdb_engine.py:104-126`  
**函数**：`DuckDbEngine._validate_sql()`

```python
if not access_scope.allows_database(database):
    raise ValueError(f"无权访问数据库：{database}")

allowed_table_ids = {
    str(item["id"]) for item in SCHEMA if item.get("database") == database
}
cte_names = {cte.alias_or_name for cte in expression.find_all(exp.CTE)}
referenced_tables = {
    table.name
    for table in expression.find_all(exp.Table)
    if table.name not in cte_names
}
unknown_tables = sorted(referenced_tables - allowed_table_ids)
if unknown_tables:
    raise ValueError(...)
for table_id in sorted(referenced_tables):
    if not access_scope.allows_table(database, table_id):
        raise ValueError(f"无权访问表：{database}.{table_id}")
```

校验的是 SQL parser 解析后的真实 table reference，而不是简单搜索字符串。CTE 名称先被排除，CTE 内真实引用的底表仍会由 AST 中的 `exp.Table` 找到。仓库测试 `backend/tests/test_mcp_runtime.py:103-123` 专门验证了把未授权 `orders_history` 藏在 CTE 中仍会失败。

---

## 5. `READ_ONLY` annotation 与真正只读安全校验

### 5.1 定义和使用位置

**源码位置**：`backend/app/mcp_runtime/server.py:12-17`

```python
READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
```

它在同文件这些注册位置传给 MCP Tool：

- `:34-39`：`current_datetime`；
- `:40-45`：`resolve_date_range`；
- `:58-66`：所有动态 `query_<database>`。

四个字段在 AskData 当前注册意图中表达：

| annotation | 当前 Tool 声明的意图 |
|---|---|
| `readOnlyHint=True` | 调用意图是读取，不修改数据或环境 |
| `destructiveHint=False` | 不宣称存在破坏性修改效果 |
| `idempotentHint=True` | 用同一参数重复调用，不应产生累积副作用 |
| `openWorldHint=False` | Tool 面向当前本地封闭数据/时间能力，而不是任意开放外部世界实体 |

这些值会进入 `tools/list` 返回的 Tool metadata，Agent/client 可以据此理解和展示工具性质。`backend/tests/test_mcp_runtime.py:23-35` 也断言 database tool 的 `readOnlyHint` 为真。

### 5.2 annotations 本身不是 SQL 安全边界

最重要的结论：

> `READ_ONLY` 是**描述性 MCP metadata**，不会因为 `readOnlyHint=True` 就自动解析 SQL 或阻止 `DELETE`、`UPDATE`、`DROP`。

证据来自两侧：

1. `server.tool(..., annotations=READ_ONLY)` 只把该对象交给 Tool registration；
2. 当前 MCP SDK 的 Tool dispatch/argument validation 没有根据这些 hints 改写或拒绝 SQL；
3. 真正检查 SQL AST 的代码位于 `DuckDbEngine._validate_sql()`，而且 `execute()` 在连接和执行前显式调用它。

三种约束必须分开：

| 层次 | 示例 | 强制力 |
|---|---|---|
| LLM 软约束 | Server instructions 和 `SqlStatement` description 要求生成只读 SQL | 模型可能不遵守 |
| MCP metadata | `READ_ONLY` 的四个 hints | 描述/提示 Tool 性质，不自动阻止危险 SQL |
| Python 硬校验 | `_validate_sql()` 校验语句类型、禁用 AST 节点、表白名单和权限 | 不通过就不会进入 `connection.execute()` |

所以 AskData 的工程安全思路是：让模型和 Tool metadata 都表达“只读”，但最终不信任生成 SQL，仍在执行边界用 Python parser 和权限白名单强制验证。

---

## 6. `build_database_query_tool()`：动态 handler 与 Python 闭包

### 6.1 完整关键代码

**源码位置**：`backend/app/mcp_runtime/tools/database_tools.py:12-46`  
**函数**：`build_database_query_tool()`

```python
SqlStatement = Annotated[
    str,
    Field(
        description=(
            "需要执行的一条DuckDB SELECT或WITH只读SQL。"
            "只能引用当前工具对应数据库中的表，最多返回200行。"
        ),
        min_length=8,
        max_length=12000,
    ),
]

def build_database_query_tool(
    database: str,
    engine: DuckDbEngine,
    access_scope: AccessScope,
) -> Callable[[SqlStatement], DatabaseQueryResult]:
    """为一个数据库创建一个独立的MCP查询工具。"""

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

    query_database.__name__ = f"query_{database}"
    return query_database
```

### 6.2 Q1：为什么动态创建，而不是直接定义 `query_askdata_mock()`

builder 的每次调用都能为一个不同 database 生成一个独立 handler：

```text
build_database_query_tool("askdata_mock", engine, scope)
        ↓
一个只代表 askdata_mock 的 query_database
```

Server 不必为每个 database 复制一份几乎相同的函数；它只需遍历 `SCHEMA` 中的 database，并为允许的 database 调用同一个 builder。变化的配置留在闭包里，Tool 对外保留统一的单参数接口。

### 6.3 Q2：它是不是 closure，为什么能记住三个对象

是，这是标准 Python **closure（闭包）**。

外层 `build_database_query_tool()` 的局部变量：

```text
database
engine
access_scope
```

都被内部 `query_database()` 的函数体引用：

```python
execution = engine.execute(database, sql, access_scope)
```

因此外层函数返回以后，这三个自由变量仍保存在返回函数的 closure cells 中；之后 MCP registry 调用该 handler 时，它仍能访问创建时绑定的值。这里返回的是一个新的函数对象，不是执行结果。

可以这样理解每个 handler 的状态：

```text
query_askdata_mock handler
├── 对外参数：sql
└── 闭包内固定：database="askdata_mock"
                engine=<DuckDbEngine>
                access_scope=<当前用户 AccessScope>
```

### 6.4 Q3：为什么 LLM arguments 只需 `sql`

内部 handler 的可调用签名只有：

```python
def query_database(sql: SqlStatement) -> DatabaseQueryResult:
```

MCP SDK 从这个签名生成 input schema，因此模型看到并需要提交的业务 arguments 是：

```json
{
  "sql": "SELECT ..."
}
```

`database`、`engine` 和 `access_scope` 不在 handler 参数列表中，而在 closure 内；所以它们不会成为 Tool input schema 的可填写字段。MCP SDK 还会根据 `SqlStatement` 上的 Pydantic `Field` 对 `sql` 做字符串、最短 8、最长 12000 的输入结构验证，然后才调用 handler。

### 6.5 Q4：闭包对安全边界的意义

模型不能通过以下伪造 arguments 改库或改权限：

```json
{
  "sql": "SELECT ...",
  "database": "another_database",
  "access_scope": {"allowed_tables": ["*"]}
}
```

原因不是 Prompt，而是公开的 handler schema 没有这些参数；真正传给 `engine.execute()` 的 `database` 和 `access_scope` 来自后端创建 closure 时绑定的对象。

所以数据库选择分成两步：

1. 模型最多选择一个已经被当前权限注册并暴露的 `query_<database>` tool name；
2. 一旦选中，该 Tool 内实际 database 和 scope 已由后端固定，模型只能提供 `sql`。

这能阻止模型通过普通 Tool arguments 把 `askdata_mock` 改成另一个库。但仍不能仅靠闭包保证 SQL 安全；SQL 内引用了什么表，仍必须由 `_validate_sql()` 检查。

---

## 7. SQL 进入 DuckDB 的主控制流

### 7.1 从 handler 到 `DuckDbEngine.execute()`

`query_database()` 接到经过 MCP input schema 验证的 `sql` 后，执行：

```python
execution = engine.execute(database, sql, access_scope)
```

此时三项输入来源是：

| 参数 | 来源 | 是否由 LLM 直接提供 |
|---|---|---|
| `database` | Tool builder 创建 handler 时固定 | 否 |
| `sql` | `decision["arguments"]["sql"]` 经 MCP 参数校验后传入 | 是 |
| `access_scope` | Tool builder 创建 handler 时固定 | 否 |

### 7.2 `execute()` 的真实执行顺序

**源码位置**：`backend/app/querying/duckdb_engine.py:33-51`  
**类 / 函数**：`DuckDbEngine.execute()`

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

逐行数据流：

1. `_validate_sql(database, sql, access_scope)` 清理、解析并检查 SQL；成功返回 `safe_sql: str`，失败抛异常。
2. `self.connect(database)` 创建上下文管理的 DuckDB 内存连接，并注册该库目录中的 CSV views。
3. `connection.execute(safe_sql)` 真正把已验证 SQL 交给 DuckDB。
4. `cursor.fetchmany(201)` 最多取 201 行原始 tuple；但当前代码没有单独用第 201 行产生“已截断”标记。
5. `cursor.description` 的每项第一个元素转成 `columns: list[str]`。
6. `raw_rows[:200]` 确保返回不超过 200 行。
7. 每一行 tuple 与 columns 配对，得到 `rows: list[dict[str, Any]]`。
8. `_json_value()` 将 `date/datetime` 转 ISO 字符串，将 `Decimal` 转 float，其他值不变（同文件 `:144-150`）。
9. 成功返回 `SqlExecution(safe_sql, True, columns, rows)`。
10. validation、SQL parsing、DuckDB、CSV 文件等受控错误被捕获，返回 `SqlExecution(sql, False, error=str(exc))`，而不是让这类查询失败直接成为 MCP protocol error。

最后一点尤其重要：

- SQL 不合法/无权限/执行错误 → handler 正常返回 `DatabaseQueryResult(success=False, error=...)`；
- Tool 名不存在、MCP handler 自身抛出未处理异常等 → `CallToolResult.is_error=True`，`LocalMcpClient` 抛 `RuntimeError`。

它们是两条不同的错误通道。

---

## 8. `_validate_sql()` 真正保证了什么

**源码位置**：`backend/app/querying/duckdb_engine.py:75-127`  
**类 / 函数**：`DuckDbEngine._validate_sql()`

### 8.1 清理代码围栏和尾部分号

```python
cleaned = self.clean_sql(sql).rstrip(";").strip()
```

`clean_sql()` 位于同文件 `:138-142`：

```python
cleaned = text.strip()
cleaned = re.sub(r"^```(?:sql)?\s*|\s*```$", "", cleaned, flags=re.I)
return cleaned.strip()
```

职责只是兼容模型偶尔返回的 Markdown SQL fence，并移除首尾空白。它不是安全检查本身。

### 8.2 必须能按 DuckDB dialect 解析，且只能有一个 statement

```python
statements = [item for item in sqlglot.parse(cleaned, read="duckdb") if item]
if len(statements) != 1:
    raise ValueError("一次只允许执行一条SQL")
```

映射：

```text
LLM SQL string
    ↓ sqlglot.parse(..., read="duckdb")
SQL AST statements
    ↓ len == 1
唯一 statement
```

因此 `SELECT ...; DELETE ...` 这种多语句输入会在 DuckDB 执行前失败。

### 8.3 根节点必须属于 query expression

```python
statement = statements[0]
if not isinstance(statement, exp.Query):
    raise ValueError("只允许执行SELECT/WITH只读查询")
```

源码错误文本称“只允许 SELECT/WITH”，实际程序判定条件是 sqlglot AST 根节点必须是 `exp.Query`。普通 `SELECT`、带 CTE 的查询等属于该类型；`UPDATE`、`DELETE`、`CREATE` 等不是允许的查询根节点。

### 8.4 AST 中显式禁止写入和管理节点

```python
forbidden_nodes = {
    "insert", "update", "delete", "merge", "create", "drop", "alter",
    "copy", "attach", "detach", "command", "transaction", "grant", "revoke",
}
if any(node.key in forbidden_nodes for node in statement.walk()):
    raise ValueError("SQL包含禁止的写入或管理操作")
```

这里不是对原 SQL 做大小写字符串匹配，而是遍历解析后的 AST。禁止集合包括：

```text
INSERT / UPDATE / DELETE / MERGE
CREATE / DROP / ALTER
COPY / ATTACH / DETACH
COMMAND / TRANSACTION / GRANT / REVOKE
```

这是对上一层 `exp.Query` 限制的防御性补充：即使一个危险节点被嵌进更大语法树，也会因节点 key 命中集合被拒绝。

### 8.5 每个 SELECT 都禁止 `*`

```python
for select in statement.find_all(exp.Select):
    if any(
        isinstance(projection, exp.Star)
        or isinstance(projection, exp.Column) and projection.is_star
        for projection in select.expressions
    ):
        raise ValueError("不允许使用SELECT *，必须明确列出查询字段")
```

它遍历全部 `exp.Select`，因此不仅检查最外层 SELECT，也检查 CTE/子查询中的 SELECT。拒绝裸 `*` 和 `table.*` 两种投影表示；查询必须明确列出返回字段。

### 8.6 database 权限校验

```python
if access_scope and not access_scope.allows_database(database):
    raise ValueError("当前用户无权访问该数据库")
```

生产调用链中 closure 总会把当前 `AccessScope` 传进来，因此会执行此项。方法签名允许 `access_scope=None`，直接以 `None` 调用 engine 时这项权限检查会跳过；但 `build_database_query_tool()` 的参数要求 `AccessScope`，当前 Agent→MCP 路径并不传 `None`。

### 8.7 table 必须属于当前 database 的已知 schema

```python
allowed = {
    table["id"] for table in SCHEMA if table.get("database", "askdata_mock") == database
}
cte_names = {cte.alias_or_name for cte in statement.find_all(exp.CTE)}
referenced = {
    table.name
    for table in statement.find_all(exp.Table)
    if table.name not in cte_names
}
unknown = {name for name in referenced if name not in allowed}
if unknown:
    raise ValueError(f"SQL引用了未知数据表：{', '.join(sorted(unknown))}")
```

数据流是：

```text
SCHEMA 中 database == 当前 database 的 table id
        ↓
allowed

SQL AST 中的 CTE alias
        ↓
cte_names（不把 CTE 临时名误当物理表）

SQL AST 中的物理 table name - CTE alias
        ↓
referenced
        ↓
referenced - allowed
        ↓
unknown；非空立即失败
```

因此 SQL 不能引用当前 database 的 SCHEMA 白名单之外的表。当前连接中也只创建当前 database 文件夹的 CSV views，并禁止 `ATTACH`，这共同构成“当前 database”边界。

精确边界：代码比较的是 `exp.Table.name`，没有另写一条针对 catalog/schema qualifier 的白名单；不要把它描述成一个完整的跨所有 DuckDB 功能的数据库沙箱。

### 8.8 每个真实底表再次检查当前用户权限

```python
if access_scope:
    denied = {
        table
        for table in referenced
        if not access_scope.allows_table(database, table)
    }
    if denied:
        raise ValueError("SQL引用了当前用户无权访问的数据表")
return cleaned
```

通过已知表检查仍不够：`orders_history` 对 `askdata_mock` 是已知表，但对 `demo_current_sales` 不是授权表，所以还要逐表调用 `allows_table()`。

只有全部通过后才返回 `cleaned`，上层才会把它作为 `safe_sql` 交给 `connection.execute()`。

### 8.9 实现规则总表

| 规则 | 是否实现 | 实际代码证据 |
|---|---:|---|
| SQL 必须能解析 | 是 | `sqlglot.parse(..., read="duckdb")`，`:82` |
| 一次只执行一条 SQL | 是 | `len(statements) != 1`，`:83-84` |
| 限定为 query AST | 是 | `isinstance(statement, exp.Query)`，`:85-87` |
| 禁止常见写入/DDL/管理 AST | 是 | `forbidden_nodes` + `statement.walk()`，`:88-93` |
| 禁止 `SELECT *` / `table.*` | 是 | 遍历每个 `exp.Select` 的 projections，`:95-102` |
| database 权限 | 是，传入 scope 时 | `allows_database()`，`:104-105` |
| 只能引用当前 database 在 `SCHEMA` 中的表名 | 是 | `allowed` 与 `unknown`，`:107-118` |
| table 权限 | 是，传入 scope 时 | `allows_table()`，`:119-126` |
| CTE 可绕过 table 权限 | 否 | 只排除 CTE alias，CTE 内底表仍在 `referenced`；测试 `test_mcp_runtime.py:103-123` |
| 强制 SQL 自带 `LIMIT 200` | 否 | 没有改写 SQL；执行后 `fetchmany(201)` 并只返回前 200 |
| 验证 SQL 的业务语义一定正确 | 否 | parser/权限只能验证结构与边界，不知道指标定义是否符合用户问题 |
| 对所有 DuckDB 可读函数做显式 allowlist | 否 | 当前函数内没有通用函数白名单，不应把现有校验夸大成完整 SQL sandbox |

### 8.10 软约束与硬校验的最终区分

```text
Server instructions / Tool description
“请生成只读 SQL”
        ↓
帮助 LLM 生成正确内容，但可能不遵守

READ_ONLY annotations
        ↓
告诉 client/Agent 工具性质，但不执行 SQL 检查

DuckDbEngine._validate_sql()
        ↓
解析 AST + 单语句 + query 类型 + 禁止节点
+ 明确字段 + schema table 白名单 + AccessScope
        ↓
失败：不会调用 connection.execute()
```

---

## 9. DuckDB 当前实际查询的数据源

### 9.1 不是线上数据库连接

**源码位置**：`backend/app/querying/duckdb_engine.py:21-31`

```python
DATABASE_ROOT = BASE_DIR / "data" / "databases"

class DuckDbEngine:
    """将 CSV 目录映射为只读 DuckDB 数据库。

    CSV 文件名作为 SQL 表名使用。
    """

    def __init__(self, database_root: Path | None = None) -> None:
        self.database_root = database_root or DATABASE_ROOT
```

`backend/app/database.py:1-4` 也明确声明：

```python
"""静态 Schema 定义。

业务数据位于 ``data/databases/<database>/*.csv``；本模块仅定义表、字段和表间关系。
"""
```

所以当前实现不是通过网络驱动连接 MySQL/PostgreSQL/线上 DuckDB 服务；它使用仓库内 `backend/data/databases/<database>/*.csv` 作为 demo/mock 业务数据。

当前工作区实际存在的 database 文件夹是：

```text
backend/data/databases/askdata_mock/
├── customers.csv
├── orders_current.csv
├── orders_history.csv
├── products.csv
└── sales_targets.csv
```

### 9.2 `connect(database)` 如何把 CSV 变成可查表

**源码位置**：`backend/app/querying/duckdb_engine.py:53-73`  
**函数**：`DuckDbEngine.connect()`

```python
@contextmanager
def connect(self, database: str) -> Iterator[duckdb.DuckDBPyConnection]:
    folder = self._database_folder(database)
    connection = duckdb.connect(":memory:")
    try:
        csv_files = sorted(folder.glob("*.csv"))
        if not csv_files:
            raise ValueError(f"数据库文件夹没有CSV表：{folder}")
        for csv_path in csv_files:
            table = csv_path.stem
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
                raise ValueError(f"CSV文件名不能作为安全表名：{csv_path.name}")
            path = csv_path.resolve().as_posix().replace("'", "''")
            connection.execute(
                f'CREATE VIEW "{table}" AS '
                f"SELECT * FROM read_csv_auto('{path}', header=true, sample_size=-1)"
            )
        yield connection
    finally:
        connection.close()
```

真实数据链：

```text
database = "askdata_mock"
        ↓
_database_folder(database)
        ↓
backend/data/databases/askdata_mock
        ↓
duckdb.connect(":memory:")
        ↓
逐个找到 *.csv
        ↓
CSV stem 作为 view 名
例如 orders_current.csv → view "orders_current"
        ↓
CREATE VIEW ... AS SELECT * FROM read_csv_auto(...)
        ↓
yield 当前内存 DuckDB connection
        ↓
connection.execute(safe_sql)
        ↓
退出 with 后 connection.close()
```

`_database_folder()`（同文件 `:129-136`）还要求 database 名符合安全 identifier，并校验解析后的目录确实位于 `database_root` 下且存在，防止用普通 database 参数进行目录穿越。不过在 MCP 路径中 database 本来就已由 closure 固定。

每次 `execute()` 都会建立一个新的 `:memory:` connection、重新为 CSV 创建 view，然后查询并关闭。它没有把 CSV 导入持久化 DuckDB 文件，也没有在此处维护长期连接池。

### 9.3 一句话判断当前数据环境

> 当前 AskData 的 database query Tool 查询的是仓库内 `backend/data/databases/askdata_mock/*.csv` 映射出的临时内存 DuckDB views；这是本地 Mock/Demo 数据查询实现，不是生产线上数据库连接实现。

---

## 10. 查询结果如何穿过 MCP 返回 Agent

### 10.1 第一层：`SqlExecution`

**源码位置**：`backend/app/querying/models.py:7-13`  
**类型**：dataclass `SqlExecution`

```python
@dataclass
class SqlExecution:
    sql: str
    success: bool
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
```

创建者是 `DuckDbEngine.execute()`：

- 成功：`SqlExecution(safe_sql, True, columns, rows)`；
- 失败：`SqlExecution(original_sql, False, error=str(exc))`。

它是 querying 层的内部执行结果，保存数据库执行关心的信息，不承担 MCP output schema。

### 10.2 第二层：`DatabaseQueryResult`

**源码位置**：`backend/app/mcp_runtime/schemas.py:21-28`  
**类型**：Pydantic `BaseModel`

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

创建者是 `build_database_query_tool()` 产生的 handler。

**源码位置**：`backend/app/mcp_runtime/tools/database_tools.py:32-43`

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

它在 `SqlExecution` 基础上：

- 增加由 closure 确定的 `database`；
- 明确计算 `row_count`；
- 用 Pydantic 模型提供稳定的 Tool output schema 和运行时输出验证。

### 10.3 第三层：MCP SDK 按名称分派和参数验证

当前安装 SDK 的真实分派链：

```text
MCPServer.call_tool(name, arguments)
backend/.venv/Lib/site-packages/mcp/server/mcpserver/server.py:498-504
        ↓
ToolManager.call_tool(name, arguments, ..., convert_result=True)
.../tools/tool_manager.py:75-87
        ↓
self.get_tool(name)
        ↓
tool.run(arguments, context, convert_result=True)
.../tools/base.py:123-181
        ↓
fn_metadata.validate_arguments(arguments)
.../utilities/func_metadata.py:72-80
        ↓
arg_model.model_validate(...)
        ↓
调用 sync handler（SDK 用 anyio worker thread 执行）
        ↓
DatabaseQueryResult
```

这证明“Tool name → handler”不是 AskData 里的一串 `if tool_name == ...`。SDK ToolManager 从注册表按 name 取 Tool；未知名称抛 `ToolError`。参数则按注册时从 Python 签名生成的 Pydantic model 验证。

### 10.4 第四层：`MCP CallToolResult`

SDK 得到 `DatabaseQueryResult` 后，因为 Server 调用了 `convert_result=True`，继续执行 output conversion。

**SDK 位置**：`backend/.venv/Lib/site-packages/mcp/server/mcpserver/utilities/func_metadata.py:110-144`

关键逻辑：

```python
validated = self.output_model.model_validate(result)
structured_content = validated.model_dump(mode="json", by_alias=True)
return CallToolResult(
    content=unstructured_content,
    structured_content=structured_content,
)
```

因此：

- `DatabaseQueryResult` 按 output model 再验证；
- `model_dump(mode="json")` 生成 JSON-compatible dict；
- SDK 用它构造 `mcp.types.CallToolResult`；
- 同时也保留 `content` 这种非结构化 content blocks 兼容表示。

`CallToolResult` 的真实字段定义位于 `backend/.venv/Lib/site-packages/mcp_types/_types.py:1463-1483`，关键字段是：

```python
content: list[ContentBlock]
structured_content: Any = None
is_error: bool = False
```

### 10.5 第五层：`structured_content` 变为 `tool_result`

回到项目代码：`backend/app/mcp_runtime/client.py:41-54`。

```python
result = await client.call_tool(name, arguments)
...
if result.structured_content is None:
    raise RuntimeError(...)
return dict(result.structured_content)
```

所以最终对象转换链是：

```text
DuckDbEngine.execute()
        ↓ 创建
SqlExecution dataclass
        ↓ handler 映射
DatabaseQueryResult Pydantic model
        ↓ MCP SDK output validation + model_dump(mode="json")
CallToolResult
├── content: list[ContentBlock]
├── structured_content: dict
└── is_error: bool
        ↓ LocalMcpClient 取 structured_content 并 dict(...)
普通 Python dict
        ↓
SingleDatabaseAgent 中的 tool_result
```

### 10.6 成功查询时 `tool_result` 的真实大致结构

```python
{
    "database": "askdata_mock",
    "sql": "SELECT region, SUM(amount) AS sales_amount ...",
    "success": True,
    "columns": ["region", "sales_amount"],
    "rows": [
        {"region": "华东", "sales_amount": 12345.0},
        # 最多 200 个 row dict
    ],
    "row_count": 1,
    "error": None,
}
```

上面具体 SQL、地区值和数值只是结构示意；固定问题在一次真实运行中会生成哪条 SQL、返回哪些业务值，取决于 LLM 决策、当前日期和 CSV 内容，**运行时才能确认**。字段集合和 Python 容器类型则由源码可以静态确认。

SQL 校验/执行失败但 handler 正常返回时结构仍相同，只会是：

```python
{
    "database": "askdata_mock",
    "sql": "原始失败 SQL",
    "success": False,
    "columns": [],
    "rows": [],
    "row_count": 0,
    "error": "具体错误文本",
}
```

### 10.7 返回 Agent 后发生什么（只标终点，不展开 Agent）

**源码位置**：`backend/app/querying/single_database_agent.py:109-124`  
**函数**：`SingleDatabaseAgent.prepare()`

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

到此，MCP 后半链返回完成：`tool_result` 同时进入 trace，并作为 `execution` 返回。按本任务限制，不再向下展开结果解释或后续生成。

---

## 11. MCP 在 AskData 当前源码中真正解决了什么

从技术上，项目当然可以不使用 MCP，直接写：

```python
if tool_name == "query_askdata_mock":
    execution = duckdb_engine.execute(...)
```

但当前源码引入 MCP 后，已经实际获得以下统一边界。

### 11.1 当前源码已经实现的能力

| 能力 | 当前实现证据 | 实际价值 |
|---|---|---|
| Tool discovery / `tools/list` | `LocalMcpClient.list_tools()`；`MCPServer.list_tools()` | Agent 不靠手写列表猜 Tool，可取得当前 Server、当前权限下真实可见工具 |
| 统一 Tool Schema | SDK 从 handler 签名、`Annotated/Field`、返回模型生成 input/output schema | 时间工具和 database 工具用同一描述格式提供给 Agent |
| name → handler 统一分派 | ToolManager 内部按 `_tools` 名称查找并 `tool.run()` | Agent 不必 import 或识别具体 Python handler |
| 输入参数 Pydantic 校验 | SDK `arg_model.model_validate()` | database tool 的 `sql` 必须满足字符串和长度 schema，再调用 handler |
| 输出结构和验证 | `DatabaseQueryResult` + SDK output model validation | 上层得到字段稳定的 structured content，而非解析任意文本 |
| 按 database 动态注册 | `for database in databases` + `name=f"query_{database}"` | Tool identity 跟随当前 SCHEMA database，而非每库复制函数 |
| 按权限缩小 Tool 暴露面 | database 不允许就不注册；table 列表过滤后写入 description | 模型只发现当前 scope 允许的 database tools 和允许表提示 |
| Tool metadata | 所有工具注册 `READ_ONLY` annotations | client/Agent 能获知工具的声明性质；但这不是硬安全验证 |
| Agent 与实现函数解耦 | Agent 只使用 list/call 和 JSON schema | Agent 不需要知道 closure、DuckDbEngine、CSV view 的具体调用方式 |
| 多种 Tool 使用同一协议边界 | 当前已经有两个时间工具和动态 database tool | 不是只为一个 SQL 函数包装；不同 handler 共享 discovery/call/result 机制 |

### 11.2 属于接口扩展潜力，但当前没有实现或使用的内容

| 架构潜力 | 当前状态 |
|---|---|
| 将同一 Agent 接到远程 HTTP MCP Server | SDK `Client` 支持，但 AskData 当前显式传本地 `MCPServer`，未使用网络 transport |
| 通过 stdio 启动独立 MCP 子进程 | 当前调用链没有，Server 与 FastAPI 同进程 |
| 查询真实生产数据库 | 当前 database handler 只查仓库 CSV 映射的内存 DuckDB views |
| 外部插件式自动发现任意工具 | 当前工具集合在 `create_local_mcp_server()` 中显式注册；没有扫描第三方 Tool 插件 |
| 多个真实 database 的现成运行实例 | 循环机制支持 SCHEMA 中多个 database，但当前 SCHEMA/数据目录只有 `askdata_mock` |

### 11.3 最准确的源码结论

> MCP 在 AskData 中承担的是一个**受当前权限裁剪、具有统一 schema 的本地 Tool 注册/发现/按名调用与结构化结果边界**；它把 Agent 的 `{tool_name, arguments}` 映射到已注册 Python handler，但 SQL 安全和数据权限的最终硬校验仍由 AskData 自己的 `AccessScope` 与 `DuckDbEngine._validate_sql()` 承担。

---

## 12. MCP 没有替 AskData 解决什么

| 问题 | MCP 是否负责 | 当前真正负责者 / 说明 |
|---|---:|---|
| 理解用户 Query | NO | 请求预处理与 LLM/Workflow；MCP 接到的已是 Tool 调用 |
| Schema Retrieval | NO | `SchemaIndex` 等上游组件；本任务不展开 |
| 选择 Tool | NO | LLM 输出 decision，`SingleDatabaseAgent` 检查 name 是否在已提供集合；MCP 只按 name 分派 |
| 生成 SQL | NO | LLM/Agent 根据 prompt、schema 信息产生 arguments.sql |
| 判断 SQL 是否满足业务问题 | NO | 当前 parser 不理解业务指标含义；模型可能生成语法安全但业务错误的 SQL |
| SQL 安全硬校验 | NO（不是 MCP metadata） | AskData 的 `DuckDbEngine._validate_sql()`；MCP 只负责 schema 参数校验和调用边界 |
| database/table 最终权限校验 | NO（MCP 协议本身不做） | Server registration 读取 `AccessScope` 缩小暴露面，DuckDB validator 再强制检查 |
| 查询底层数据 | NO | `DuckDbEngine.connect()/execute()` 和 DuckDB 执行 CSV views |
| 解释查询结果 | NO | MCP 只返回结构化结果；后续响应组件负责解释，本任务不展开 |
| Agent loop | NO | `SingleDatabaseAgent.prepare()` 管理调用次数、tool trace、继续/返回；MCP 执行一次指定 Tool call |

所以不要把 MCP 当成“会理解问题、会写 SQL、会验证业务正确性、会自主循环”的 Agent 框架。它在这里是 Agent 与具体工具实现之间的协议化执行边界。

---

## 13. 真实端到端源码调用链

下面只写当前源码真实存在的函数和对象；SDK 内部分派也展开到 handler。

```text
SingleDatabaseAgent.prepare()
backend/app/querying/single_database_agent.py:102-124

decision["tool_name"]  → tool_name: str
decision["arguments"]  → arguments: dict
        ↓
校验 tool_name in tool_names
校验 isinstance(arguments, dict)
        ↓
tool_result = mcp_client.call_tool(tool_name, arguments)
        ↓
LocalMcpClient.call_tool(name, arguments)
backend/app/mcp_runtime/client.py:38-39
        ↓
asyncio.run(self._call_tool(name, arguments))
        ↓
LocalMcpClient._call_tool(name, arguments)
backend/app/mcp_runtime/client.py:41-54
        ↓
async with Client(self.server) as client
        ↓
self.server 是本次 access_scope 下创建的本地 MCPServer 对象
不是 URL，不是子进程
        ↓
await client.call_tool(name, arguments)
当前 MCP SDK：backend/.venv/Lib/site-packages/mcp/client/client.py:751-824
        ↓
SDK in-process direct dispatcher
同一 Python 进程内把 call request 交给当前 Server
        ↓
MCPServer._handle_call_tool(...)
SDK：.../mcp/server/mcpserver/server.py:415-424
        ↓
MCPServer.call_tool(name, arguments, context)
SDK：同文件 :498-504
        ↓
ToolManager.call_tool(name, arguments, ..., convert_result=True)
SDK：.../tools/tool_manager.py:75-87
        ↓
从内部 Tool registry 查找 name
未知 name → ToolError
        ↓
Tool.run(arguments, context, convert_result=True)
SDK：.../tools/base.py:123-181
        ↓
Pydantic input model 校验 arguments
database tool 的公开参数只有 sql: SqlStatement
        ↓
找到 name="query_askdata_mock" 对应的 handler
        ↓
handler 实际是 build_database_query_tool(...) 创建的
query_database(sql)
backend/app/mcp_runtime/tools/database_tools.py:25-46
        ↓
closure 取出创建时绑定的：
database="askdata_mock"
engine=<DuckDbEngine>
access_scope=<当前用户 AccessScope>
        ↓
DuckDbEngine.execute(database, sql, access_scope)
backend/app/querying/duckdb_engine.py:33-51
        ↓
DuckDbEngine._validate_sql(...)
同文件 :75-127
        ↓
清理 SQL → sqlglot 解析 → 单 statement
→ exp.Query → 禁止危险 AST → 禁止 SELECT *
→ 当前 database 的已知表 → database/table 权限
        ↓
验证成功返回 safe_sql
        ↓
DuckDbEngine.connect(database)
同文件 :53-73
        ↓
duckdb.connect(":memory:")
        ↓
backend/data/databases/askdata_mock/*.csv
逐一注册为同名 DuckDB VIEW
        ↓
connection.execute(safe_sql)
        ↓
cursor.fetchmany(201)
        ↓
columns: list[str]
rows: list[dict[str, Any]]（最多前 200 行）
        ↓
SqlExecution
backend/app/querying/models.py:7-13
        ↓
query_database() 将其映射为 DatabaseQueryResult
backend/app/mcp_runtime/schemas.py:21-28
        ↓
MCP SDK output model 验证与 JSON mode dump
        ↓
CallToolResult
├── content
├── structured_content: dict
└── is_error: bool
        ↓
LocalMcpClient._call_tool()
检查 result.is_error
检查 structured_content 非 None
        ↓
dict(result.structured_content)
        ↓
tool_result: dict[str, Any]
        ↓
SingleDatabaseAgent.prepare()
backend/app/querying/single_database_agent.py:109-124
        ↓
trace["result"] = tool_result
execution = tool_result
```

### 13.1 Server 注册链与执行链如何汇合

调用发生前，Server 已由另一条构造链准备好：

```text
QueryWorkflow.mcp_client(access_scope dict)
backend/app/workflows/query_graph.py:57-59
        ↓
AccessScope.from_dict(...)
        ↓
create_local_mcp_server(self.database_engine, scope)
backend/app/mcp_runtime/server.py:20-67
        ↓
从 SCHEMA 提取 databases
        ↓
allows_database(database)
        ↓
build_database_query_tool(database, engine, scope)
        ↓
query_database closure
        ↓
server.tool(name=f"query_{database}", ...)(handler)
        ↓
Tool registry："query_askdata_mock" → handler
        ↓
LocalMcpClient(server)
```

执行时的 `ToolManager.call_tool("query_askdata_mock", arguments)` 正是在这张 registry 中找到先前注册的 closure。注册阶段不会查数据库；调用阶段才执行 handler 和 SQL。

---

## 14. 最后 8 个问题的直接答案

### Q1. `mcp_client.call_tool(tool_name, arguments)` 之后，真实 Python 调用链是什么？

```text
LocalMcpClient.call_tool()
→ asyncio.run(LocalMcpClient._call_tool())
→ async with MCP Client(self.server)
→ await Client.call_tool()
→ 进程内 direct dispatcher
→ MCPServer._handle_call_tool()
→ MCPServer.call_tool()
→ ToolManager.call_tool()
→ Tool.run()
→ Pydantic arguments validation
→ 已注册 handler
→ query_database(sql)
→ DuckDbEngine.execute()
→ _validate_sql()
→ connect()
→ connection.execute()
→ DatabaseQueryResult
→ CallToolResult.structured_content
→ dict(...)
→ tool_result
```

项目入口证据是 `backend/app/mcp_runtime/client.py:38-54`；Server/registry 内部证据分别在当前 SDK 的 `mcp/server/mcpserver/server.py:415-424, 498-504` 和 `tools/tool_manager.py:75-87`。

### Q2. `query_askdata_mock` 到底在哪里产生？它是不是源码中手写的固定函数？

不是手写固定函数。

`backend/app/mcp_runtime/server.py:47-66` 从 `SCHEMA` 得到 database，循环中用：

```python
handler = build_database_query_tool(database, database_engine, scope)
server.tool(name=f"query_{database}", ...)(handler)
```

当前 database 值是 `askdata_mock`，因此运行时注册名变为 `query_askdata_mock`。handler 是 `backend/app/mcp_runtime/tools/database_tools.py:32` 的内部 `query_database()` 新函数对象，其 `__name__` 也在 `:45` 动态设置。

### Q3. `build_database_query_tool()` 为什么使用 closure？

为了让每个动态 database Tool 对外只接收 `sql`，同时长期记住并固定后端选定的 `database`、共享 `engine` 和当前用户 `access_scope`。这样一份 builder 可以生成不同 database/权限上下文的独立 handler，不必复制 `query_xxx()` 函数。

### Q4. `access_scope` 如何影响 Tool 注册、Tool 暴露和 SQL 最终执行？

```text
注册：allows_database=False → 不注册 query_<database>
暴露：allows_table=True 的表才写入 Tool description 的“可用表”
绑定：完整 AccessScope 被固定进 handler closure，不给 LLM 修改
执行：_validate_sql() 再检查 database 和 SQL 引用的每张真实底表
```

真实位置：`backend/app/mcp_runtime/server.py:47-66`、`backend/app/mcp_runtime/tools/database_tools.py:25-46`、`backend/app/querying/duckdb_engine.py:104-126`。

### Q5. `READ_ONLY` annotation 和真正只读 SQL 安全校验有什么区别？

`READ_ONLY`（`backend/app/mcp_runtime/server.py:12-17`）是 Tool metadata，表达只读、非破坏、幂等、封闭世界提示；它本身不解析或拒绝 SQL。

真正的硬校验是 `DuckDbEngine._validate_sql()`（`backend/app/querying/duckdb_engine.py:75-127`）：它解析 AST、限制单条 query、拒绝写入/管理节点和 `SELECT *`，并强制 schema/table/权限白名单。前者是描述性约束，后者决定能否执行。

### Q6. `DuckDbEngine.execute()` 最终查询的是怎样的数据源？

它查询本地 Mock/Demo CSV。`connect(database)` 为每次调用创建 `duckdb.connect(":memory:")`，读取 `backend/data/databases/<database>/*.csv`，以 CSV 文件 stem 创建同名 view，再执行 SQL。当前真实 database 是 `askdata_mock`，不是线上数据库连接。证据：`backend/app/querying/duckdb_engine.py:21-31, 53-73`。

### Q7. 查询结果如何从 DuckDB 一层层返回成 Agent 中的 `tool_result`？

```text
DuckDB cursor
→ columns + rows
→ SqlExecution dataclass
→ DatabaseQueryResult Pydantic model
→ MCP output model validation
→ CallToolResult(structured_content=dict)
→ LocalMcpClient 检查 is_error/structured_content
→ dict(result.structured_content)
→ SingleDatabaseAgent 的 tool_result: dict[str, Any]
```

业务 SQL 失败通常表现为 `tool_result["success"] == False` 和非空 `error`；这与 MCP 调用本身的 `CallToolResult.is_error=True` 不同。

### Q8. 用一句最准确的话回答：MCP 在 AskData 中真正承担的架构职责是什么？

> **MCP 是 AskData 中受 `AccessScope` 裁剪的本地工具协议边界：它统一完成 Tool 注册、发现、schema 校验、按名分派和结构化回传，把 Agent 的 JSON Tool 决策映射到具体 Python handler；SQL 安全、底层查询和最终权限硬校验仍由 AskData 自己的组件承担。**

---

## 15. 回源码时建议沿这条最短阅读顺序

1. `backend/app/querying/single_database_agent.py:102-124`：只看调用起点与返回终点。
2. `backend/app/mcp_runtime/client.py:10-54`：同步/异步桥接、MCP result 转 dict。
3. `backend/app/workflows/query_graph.py:42-59`：engine 和 MCP client factory 从哪里来。
4. `backend/app/mcp_runtime/server.py:12-67`：metadata、按权限动态注册。
5. `backend/app/security/access_control.py:13-26, 48-89`：scope 结构和 demo 策略。
6. `backend/app/mcp_runtime/tools/database_tools.py:12-46`：公开输入 schema、closure、结果映射。
7. `backend/app/querying/duckdb_engine.py:33-73`：执行主流程和 CSV views。
8. `backend/app/querying/duckdb_engine.py:75-150`：SQL 硬校验、目录约束、JSON 值转换。
9. `backend/app/querying/models.py:7-13` 与 `backend/app/mcp_runtime/schemas.py:21-28`：两种结果对象。
10. 最后再看本地 SDK 的 `MCPServer.call_tool()`、ToolManager 和 result conversion，以理解框架替项目完成的中间分派。

读完后，应能把整个黑盒压缩为：

```text
LLM 给 name + {sql}
→ 当前权限下已注册的本地 MCP Tool
→ 闭包补齐 database/engine/scope
→ Python 硬校验
→ CSV-backed 内存 DuckDB
→ 结构化 MCP result
→ Agent 普通 dict
```

