# AskData 源码调查：从 SchemaGraph 到 SingleDatabaseAgent、clarify 与 MCP 执行

> 调查日期：2026-08-30  
> 固定示例问题：`查询本月各地区销售额`  
> 调查方式：以当前仓库的可执行 Python 源码为最高依据；不依据 PDF、README、类名或注释替代控制流证据。  
> 本文只调查 SchemaGraph 之后的数据库 Agent 阶段，以及它直接调用的 Skill、模型、MCP、DuckDB 与澄清恢复路径；不重新分析 Retrieval/Rerank，也不提出重构方案。

## 0. 先给严格结论

### 0.1 一句话结论

AskData 这一阶段实际上是：**LangGraph 先确定一个目标数据库，再让 `SingleDatabaseAgent.prepare()` 在最多 3 次“模型决策 → MCP 工具执行”之间循环；时间工具结果会作为 observation 进入下一次模型调用，但数据库工具结果一旦返回就立即退出 Agent，交给 Workflow 整理和生成最终说明。**

### 0.2 对附件核心问题的直接回答

1. `SingleDatabaseAgent` 收到的 `query` 不是未经处理的 HTTP 原始字符串，而是 `State["standalone_query"]`。
2. `database` 在进入 Agent 前已经由 Workflow 从 `schema_graph["tables"]` 汇总出的 `database_names` 中选定；Agent 不负责数据库路由。
3. `schema_graph`、`schema_text`、裁剪后的 `retrieval`、`confirmed_fields`、`confirmed_parameters` 和过滤后的 `mcp_tools` 都会进入本轮 LLM 的 **user message JSON**。
4. `SKILL.md` 会在进程初始化时由 `SkillRegistry` 从磁盘读取，成为 `SkillDefinition.instructions`，之后拼入 Agent 的 **system message**。
5. Agent 调用 `ModelClient.chat_json()` 取得一个普通 JSON 对象。这里没有向 Chat API 的顶层 `tools` 字段传工具；MCP Tool Schema 是 `user` 消息中 `mcp_tools` 字段的普通 JSON 数据。
6. 如果模型返回 `clarify`，`prepare()` 当次立即返回；LangGraph 在 `human_clarification` 节点通过 `interrupt()` 暂停。用户回答后，Service 用同一个 `task_id` 调用一次新的 `workflow.invoke(Command(resume=...))`，恢复原 checkpoint，然后重新经过 Schema Retrieval 和 Agent。Agent 自己没有停在循环里等待用户。
7. 如果模型调用时间工具，工具结果会追加到 `observations`，下一轮 LLM 会在 `tool_results` 中看到它。
8. 如果模型调用当前数据库的 `query_<database>` 工具，SQL 位于模型 JSON 的 `arguments.sql`；执行结果一返回，Agent 立刻 `return`，数据库 `rows` **不会**再喂给同一个 Agent LLM。
9. 因而它不是典型的完整 ReAct 闭环。更精确的分类是 **C：有界的混合式 Tool Loop**：非数据库工具支持 `LLM → Tool → Observation → LLM`，终止性的数据库工具只支持 `LLM → Tool → return`。若 A/B 二选一，它在数据库查询的主路径上更接近 **B：LLM decision node**。
10. Workflow 外层存在“澄清 → 人类回答 → 重新检索 → 再进 Agent”的状态环，但不存在“数据库执行 → 将 rows 更新进状态 → 回到 Agent 决策”的外层循环。
11. `SingleDatabase` 修饰的是**本次 Agent 所能查询的数据库范围**，不是单 Agent、单次采样或单条用户 Query。当前多数据库分支明确返回“尚未启用”。

以上第 1～11 项均有下文逐段源码证据。固定 Query 的真实检索命中、模型会先选哪个时间工具、模型生成的精确 SQL 和行数据属于运行时结果，静态源码不能预先保证；本文不会把测试 Fake Model 的固定输出冒充生产模型结果。

---

## 1. 从 SchemaGraphBuilder 进入 SingleDatabaseAgent 的真实入口

### 1.1 Agent 在 Workflow 初始化时被创建

位置：`backend/app/workflows/query_graph.py:27-55`  
类/函数：`QueryWorkflow.__init__()`

```python
self.skills = SkillRegistry()
self.graph_builder = SchemaGraphBuilder()
self.database_engine = DuckDbEngine()
self.single_database_agent = SingleDatabaseAgent(
    model_client,
    self.mcp_client,
    self.skills.get("database_query"),
    self.config.mcp_max_tool_calls,
)
```

这里注入四样东西：

- 同一个 `ModelClient`；
- `QueryWorkflow.mcp_client` 这个工厂方法；
- Registry 中名为 `database_query` 的 `SkillDefinition`；
- 配置的 MCP 最大工具调用次数。

`SingleDatabaseAgent.__init__()` 又取配置值和 Skill 值的较小者：

位置：`backend/app/querying/single_database_agent.py:16-26`

```python
self.max_tool_calls = min(max_tool_calls, skill.max_tool_calls)
```

当前 `backend/app/skills/database_query/config.json:9` 的 `max_tool_calls` 是 `3`，当前 `backend/app/config.py:50` 的环境变量默认值也是 `3`，所以默认上限是 3；如果部署环境覆盖配置，则要在运行时才能确认最终值。

### 1.2 SchemaGraphBuilder 的产物如何写入 State

位置：`backend/app/workflows/query_graph.py:193-230`  
函数：`QueryWorkflow._retrieve_schema()`

```python
retrieval = self.schema_index.retrieve(
    standalone_query,
    retrieval_terms=list(extraction.get("retrieval_terms") or []),
    access_scope=state.get("access_scope"),
)
# ... include_workspace(...)
schema_graph = self.graph_builder.build(
    retrieval["hits"],
    state.get("access_scope"),
)
retrieval["schema_graph"] = schema_graph
databases = sorted({
    str(table.get("database") or schema_graph.get("database") or "askdata_mock")
    for table in schema_graph.get("tables", [])
})
return {
    "standalone_query": standalone_query,
    "extraction": extraction,
    "retrieval": retrieval,
    "schema_graph": schema_graph,
    "schema_context": self.graph_builder.context_text(schema_graph),
    "database_names": databases,
    "clarification": None,
    "direct_sql": "",
}
```

这段代码产生并写回 LangGraph `QueryState` 的四个直接相关字段：

- `retrieval: dict[str, Any]`：Schema 检索结果，并额外挂入 `schema_graph`；
- `schema_graph: dict[str, Any]`：字段、表、Join 关系等结构化图；
- `schema_context: str`：`SchemaGraphBuilder.context_text()` 把图渲染成模型容易阅读的文本；
- `database_names: list[str]`：从图中的每个 table 的 `database` 聚合、去重并排序。

`SchemaGraphBuilder.context_text()` 位于 `backend/app/retrieval/graph.py:111-126`。它将数据库、表、字段和关联逐行拼成字符串。这就是后面 payload 中名为 `schema_text` 的值；项目没有另一个独立的 `schema_text` 生成器。

### 1.3 Workflow 先分单库/多库，再选择 database

位置：`backend/app/workflows/query_graph.py:235-239`  
函数：`QueryWorkflow._after_retrieval()`

```python
return (
    "prepare_single_database"
    if len(state.get("database_names") or []) <= 1
    else "run_multi_database"
)
```

位置：`backend/app/workflows/query_graph.py:261-272`  
函数：`QueryWorkflow._prepare_single_database()`

```python
workspace = dict(state.get("workspace") or {})
database = (state.get("database_names") or ["askdata_mock"])[0]
decision = self.single_database_agent.prepare(
    state["standalone_query"],
    database,
    state["schema_graph"],
    state["schema_context"],
    state["retrieval"],
    workspace,
    state.get("access_scope") or {},
)
```

按位置参数逐项对应：

```text
State["standalone_query"]  -> query
database                   -> database
State["schema_graph"]     -> schema_graph
State["schema_context"]   -> schema_context
State["retrieval"]        -> retrieval
workspace                  -> workspace
State["access_scope"]     -> access_scope
```

关键事实：`database` 在调用 `SingleDatabaseAgent.prepare()` **之前**已经得到。若 `database_names` 为空，代码回退到字符串 `"askdata_mock"`；若多于一个数据库，正常分支不会进入该函数，而会走 `run_multi_database`。

---

## 2. `SingleDatabaseAgent` 真正收到并交给模型的八类数据

### 2.1 `prepare()` 的直接 Python 入参

位置：`backend/app/querying/single_database_agent.py:28-37`

```python
def prepare(
    self,
    query: str,
    database: str,
    schema_graph: dict[str, Any],
    schema_context: str,
    retrieval: dict[str, Any],
    workspace: dict[str, Any],
    access_scope: dict[str, Any],
) -> dict[str, Any]:
```

附件列出的 `confirmed_fields`、`confirmed_parameters`、`schema_text`、`mcp_tools` 并不是四个直接形参。它们在 `prepare()` 内从 `workspace`、`schema_context` 和 MCP catalog 派生，然后进入 `base_payload`。

### 2.2 八项逐项调查表

| LLM payload 字段 | 产生位置与传入位置 | 传入/生成时 Python 类型 | 大致内容 | 是否进入 Agent LLM | 若不是完整进入，实际用途 |
|---|---|---|---|---|---|
| `query` | `RequestPreprocessor._parse()` 生成 `PreparedRequest.standalone_query`（`backend/app/preprocessing.py:140-156`）；`QueryWorkflow._preprocess()` 写 `State["standalone_query"]`（`query_graph.py:146-158`）；`_prepare_single_database()` 第 1 个位置参数传入（`query_graph.py:264-272`） | `str` | 可独立理解的问题；固定示例通常是 `查询本月各地区销售额`，但是否改写由预处理模型运行时决定 | **是**，完整进入 `base_payload["query"]` | 不适用 |
| `database` | `_retrieve_schema()` 从 `schema_graph["tables"]` 聚合为 `database_names`（`query_graph.py:220-230`）；`_prepare_single_database()` 取第一个或回退 `askdata_mock`（`query_graph.py:263`） | `str` | 当前唯一目标数据库 ID，例如当前静态 Schema 中的 `askdata_mock` | **是**，完整进入 payload | 在进入 LLM 前还用于构造终止性工具名 `query_<database>`，并过滤其它数据库工具 |
| `schema_graph` | `SchemaGraphBuilder.build()`（`backend/app/retrieval/graph.py:18-109`）；写入 State 后由 `_prepare_single_database()` 传入 | `dict[str, Any]` | `database/databases/graph_version/tables/fields/joins` | **是**，完整进入 payload | 同一对象还被 Workflow 用于确定数据库名；Agent 内不修改它 |
| `retrieval` | `SchemaIndex.retrieve()`，再由 `include_workspace()` 扩充；`_retrieve_schema()` 写入 State（`query_graph.py:198-228`） | `dict[str, Any]` | 完整检索对象含 hits、阈值、低置信候选等 | **只进入子集** | Agent 只复制 `threshold`、把 `hits` 改名为 `selected_fields`、复制 `low_confidence_candidates`；完整 retrieval 的其它顶层字段不会进入这轮 LLM |
| `confirmed_fields` | 外部 workspace 经 `SessionContext.normalize_workspace()`/`query_workspace()` 规范化（`backend/app/services/session_context.py:262-278`）；Agent 取 `workspace.get("schema_fields", [])` | 运行时代码得到 `list`；按 API 模型意图是 `list[ConfirmedField]`，进入 State 后通常是 `list[dict]` | 每项主要为 `name`、`aggregation`、可选 `tableId`；模型定义见 `backend/app/models.py:8-11` | **是**，进入 payload | 它不是独立 `prepare()` 参数。此前 Retrieval 的 `include_workspace()` 也用它强制补入已确认字段（`retrieval/service.py:227-267`） |
| `confirmed_parameters` | `SessionContext` 规范化为空或已有 `dict`（`session_context.py:263-278`）；用户澄清恢复时 `_human_clarification()` 追加 `{parameter: option_id}`（`query_graph.py:241-256`）；Agent 从 workspace 读取 | `dict`，静态注解粒度为 `dict[str, Any]` | 已确认的参数名到选项 ID/值的映射，例如可能为 `{"time_range": "orders_current"}` | **是**，进入 payload | 不是独立形参；同时保存在 Workflow workspace，供重新检索与再次 Agent 决策使用 |
| `schema_text` | `SchemaGraphBuilder.context_text(schema_graph)` 产生 `State["schema_context"]`（`query_graph.py:229`；实现见 `retrieval/graph.py:111-126`）；Agent 将它换名 | `str` | 数据库、表、字段、Join 的逐行自然语言/半结构化文本 | **是**，进入 payload | `prepare()` 形参叫 `schema_context`，payload 字段才叫 `schema_text`；没有生成新内容，只是同一字符串换键名 |
| `mcp_tools` | `QueryWorkflow.mcp_client()` 创建本地 MCP client/server（`query_graph.py:57-59`）；`LocalMcpClient.list_tools()` 发现 catalog；Agent 根据 Skill allowlist 和当前 database 过滤（`single_database_agent.py:38-48`） | `list[dict[str, Any]]` | 每项含 name、title、description、input_schema、output_schema、annotations | **是**，完整过滤结果进入 payload | 它也用于程序侧验证 `tool_name` 是否真的可用。它不是 Python callable 本身，也不是 MCP server 对象 |

补充两个容易误判的对象：

- `workspace` 整体没有直接放入 LLM payload；只有 `schema_fields` 与 `confirmed_parameters` 以新键名进入。`confirmed_schema_tables` 不作为独立 payload 字段进入，但它已经参与了 `include_workspace()`，并可能通过 enriched hits/schema graph 间接反映出来。
- `access_scope` 没有进入 LLM payload。它用于创建受权限约束的 MCP server、隐藏无权数据库工具，并在 DuckDB 执行前再次校验数据库/表权限。

### 2.3 `base_payload` 是最终上下文的主体

位置：`backend/app/querying/single_database_agent.py:56-73`

```python
system = f"你是单数据库问数智能体。\n\n{self.skill.instructions}"

observations: list[dict[str, Any]] = []
tool_trace: list[dict[str, Any]] = []
base_payload = {
    "query": query,
    "database": database,
    "schema_graph": schema_graph,
    "retrieval": {
        "threshold": retrieval.get("threshold"),
        "selected_fields": retrieval.get("hits", []),
        "low_confidence_candidates": retrieval.get("low_confidence_candidates", []),
    },
    "confirmed_fields": workspace.get("schema_fields", []),
    "confirmed_parameters": workspace.get("confirmed_parameters", {}),
    "schema_text": schema_context,
    "mcp_tools": tools,
}
```

这里有两个独立的模型输入面：

- `system`：固定角色前缀 + 运行时加载的 Skill instructions；
- `base_payload`：本次任务的数据与工具 Schema，稍后 JSON 序列化为 user message。

---

## 3. “构造 Prompt”与“真正发生 LLM sampling”必须分开

### 3.1 构造本轮 user payload

位置：`backend/app/querying/single_database_agent.py:75-81`

```python
for call_index in range(1, self.max_tool_calls + 1):
    payload = {**base_payload, "tool_results": observations}
    decision = self.model_client.chat_json(
        system,
        json.dumps(payload, ensure_ascii=False),
    )
```

`payload = ...` 和 `json.dumps(...)` 只是构造/序列化 Prompt 内容，不是网络调用。Agent 层真正发起一次模型决策的语句是 `self.model_client.chat_json(...)`，即 `single_database_agent.py:78-81`。

### 3.2 ModelClient 如何构造真正的 Chat 请求

位置：`backend/app/model_client.py:25-39`  
函数：`ModelClient.chat()`

```python
payload = {
    "model": self.config.llm_model,
    "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ],
    "temperature": self.config.temperature if temperature is None else temperature,
    "stream": False,
}
result = self._post(self.config.chat_url, payload)
return str(result["choices"][0]["message"]["content"]).strip()
```

因此发送给模型的数据可以还原为：

```python
{
    "model": settings.llm_model,
    "messages": [
        {
            "role": "system",
            "content": "你是单数据库问数智能体。\n\n" + SKILL_MD全文,
        },
        {
            "role": "user",
            "content": json.dumps({
                "query": ...,
                "database": ...,
                "schema_graph": ...,
                "retrieval": {...},
                "confirmed_fields": ...,
                "confirmed_parameters": ...,
                "schema_text": ...,
                "mcp_tools": [...],
                "tool_results": [...],
            }, ensure_ascii=False),
        },
    ],
    "temperature": settings.temperature,
    "stream": False,
}
```

重要事实：这里没有顶层 `"tools": [...]`，也没有 API 原生的 `tool_calls` 消息协议。模型是阅读 user JSON 里的 `mcp_tools`，再按 Skill 约定在普通 `message.content` 中输出 JSON。

### 3.3 哪一行真的把 HTTP 请求发出去

位置：`backend/app/model_client.py:90-108`  
函数：`ModelClient._post()`

```python
request = urllib.request.Request(..., method="POST")
# ...
with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
    return json.loads(response.read().decode("utf-8"))
```

严格说，**实际向模型服务发送 HTTP 请求并等待响应的是 `backend/app/model_client.py:107` 的 `urllib.request.urlopen(...)`**。调用层级是：

```text
SingleDatabaseAgent.prepare():78
→ ModelClient.chat_json():41-53
→ ModelClient.chat():25-39
→ ModelClient._post():90-120
→ urllib.request.urlopen():107   # 真正网络 I/O
```

`_post()` 在 `model_client.py:105-117` 还有网络重试循环。本文所说的“一次 LLM sampling”按一次 `chat_json()` 的逻辑决策调用计数；网络错误导致的同请求重试是 HTTP attempt，不应误算成 Agent 新一轮 observation/decision。

### 3.4 模型原始结果如何解析

位置：`backend/app/model_client.py:41-53`  
函数：`ModelClient.chat_json()`

```python
raw = self.chat(system, user)
cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
try:
    return json.loads(cleaned)
except json.JSONDecodeError:
    match = re.search(r"\{[\s\S]*\}", cleaned)
    # ...再尝试 json.loads(match.group(0))
```

所以层次是：

```text
API JSON response
→ choices[0].message.content（str）
→ 去除可选 ```json 围栏
→ json.loads(...)
→ decision（dict[str, Any]）
```

源码允许的业务动作最终只剩 `call_tool` 和 `clarify`，因为：

- `database_query/config.json:10-13` 声明 `output_actions`；
- `single_database_agent.py:83-85` 校验 `decision["action"]` 是否在允许集合；
- `single_database_agent.py:87-100` 只实现 `clarify` 与 `call_tool` 两个分支。

---

## 4. `SKILL.md` 如何从磁盘进入 system prompt

### 4.1 Registry 的默认搜索根目录

位置：`backend/app/skills/registry.py:26-31`  
类/函数：`SkillRegistry.__init__()`

```python
def __init__(self, root: Path | None = None) -> None:
    self.root = root or Path(__file__).resolve().parent
    self._skills = self._load()
```

默认 `root` 就是 `backend/app/skills`。这是运行时文件系统路径，不是通过 Python import 导入 Markdown。

### 4.2 如何发现并读取 Skill

位置：`backend/app/skills/registry.py:41-59`  
函数：`SkillRegistry._load()`

```python
for config_path in sorted(self.root.glob("*/config.json")):
    directory = config_path.parent
    instruction_path = directory / "SKILL.md"
    if not instruction_path.exists():
        raise ValueError(...)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    name = str(payload.get("name") or directory.name).strip()
    output[name] = SkillDefinition(
        name=name,
        description=str(payload.get("description") or "").strip(),
        instructions=instruction_path.read_text(encoding="utf-8").strip(),
        allowed_tools=tuple(str(item) for item in payload.get("allowed_tools") or []),
        max_tool_calls=max(0, int(payload.get("max_tool_calls", 0))),
        output_actions=tuple(str(item) for item in payload.get("output_actions") or []),
    )
```

对当前 Skill，真实路径对应为：

```text
backend/app/skills/database_query/config.json
backend/app/skills/database_query/SKILL.md
```

`SkillDefinition` 的真实字段位于 `registry.py:9-16`：

```python
@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    instructions: str
    allowed_tools: tuple[str, ...]
    max_tool_calls: int
    output_actions: tuple[str, ...]
```

### 4.3 如何注入 Agent 与模型

真实调用关系：

```text
QueryWorkflow.__init__()                         query_graph.py:40
→ SkillRegistry()
→ SkillRegistry._load()                         registry.py:41-59
→ 读取 database_query/SKILL.md 全文             registry.py:55
→ SkillRegistry.get("database_query")           query_graph.py:46
→ SingleDatabaseAgent.__init__(..., skill, ...) query_graph.py:43-48
→ self.skill = skill                            single_database_agent.py:25
→ system = 固定前缀 + self.skill.instructions   single_database_agent.py:56
→ ModelClient.chat_json(system, user)           single_database_agent.py:78-81
→ messages[0].content = system                  model_client.py:28-31
```

因此 `SKILL.md` 的性质是：**存放在普通 Markdown 文件中的、由 Registry 在运行时动态加载的 Agent instruction；在本实现中它最终充当 system prompt 的主体。**

它不是：

- **Python Tool**：没有可被直接调用的 Python callable；
- **MCP Tool**：不会出现在 MCP `tools/list` 中，也没有 MCP input/output schema；
- **只供人阅读的文档**：因为源码明确读取全文并送入 LLM。

### 4.4 Markdown 里的要求是否被程序强制执行

`backend/app/skills/database_query/SKILL.md:18-23` 要求相对时间必要时先调用时间工具、生成一条只读 `SELECT/WITH`、不使用 `SELECT *` 等。运行时的强制程度不同：

- **硬校验**：允许的 action、允许的 tool、arguments 必须是 dict、clarify 至少两个选项、最多调用次数；见 `single_database_agent.py:83-129`。
- **硬校验**：SQL 只能有一条、只能是只读 Query、禁止 `SELECT *`、只能引用已知且有权限的表；见 `duckdb_engine.py:75-127`。
- **主要依赖模型遵循 instruction**：何时信息“实质缺失”、reason 如何写、中文别名等，没有在 Agent 里逐项验证。

所以不能只因 `SKILL.md` 写了某项要求，就宣称模型运行时一定会照做；需要看有没有对应程序校验。以上已分别指出。

---

## 5. `mcp_tools` 到底是什么：注册、发现、过滤、送入模型

### 5.1 每次 `prepare()` 都创建当前权限下的本地 MCP Client

位置：`backend/app/workflows/query_graph.py:57-59`

```python
def mcp_client(self, access_scope: dict[str, Any]) -> LocalMcpClient:
    scope = AccessScope.from_dict(access_scope)
    return LocalMcpClient(create_local_mcp_server(self.database_engine, scope))
```

Agent 调用位置：`backend/app/querying/single_database_agent.py:38-42`

```python
database_tool = f"query_{database}"
mcp_client = self.mcp_client_factory(access_scope)
catalog = mcp_client.list_tools()
```

这里是同进程 MCP transport，不是启动另一个远程数据库服务；`LocalMcpClient` 持有本地 `MCPServer`。

### 5.2 Server 如何注册时间工具和每库查询工具

位置：`backend/app/mcp_runtime/server.py:20-66`  
函数：`create_local_mcp_server()`

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

databases = sorted({str(table.get("database") or "askdata_mock") for table in SCHEMA})
for database in databases:
    if not scope.allows_database(database):
        continue
    # ...只列出有表权限的 tables
    handler = build_database_query_tool(database, database_engine, scope)
    server.tool(
        name=f"query_{database}",
        title=f"查询数据库 {database}",
        description=(...),
        annotations=READ_ONLY,
    )(handler)
```

源码事实：

- 时间工具始终注册；
- `SCHEMA` 中每个当前用户允许访问的 database 注册一个独立 `query_<database>` 工具；
- database tool 的 description 列出当前权限允许的表；
- input/output schema 由 MCP 库依据 handler 的 Python 类型注解与 Pydantic 返回模型生成。

### 5.3 Client 的 `tools/list` 被转换成什么 Python 数据

位置：`backend/app/mcp_runtime/client.py:16-36`  
类/函数：`LocalMcpClient.list_tools()` / `_list_tools()`

```python
result = await client.list_tools()
return [
    {
        "name": tool.name,
        "title": tool.title,
        "description": tool.description,
        "input_schema": tool.input_schema,
        "output_schema": tool.output_schema,
        "annotations": (
            tool.annotations.model_dump(by_alias=True, exclude_none=True)
            if tool.annotations else {}
        ),
    }
    for tool in result.tools
]
```

所以 `mcp_tools` 是 `list[dict[str, Any]]`。列表元素是工具**说明与 JSON Schema**，不是函数对象，也不是已经发生的 tool call。

### 5.4 Agent 如何过滤工具

位置：`backend/app/querying/single_database_agent.py:43-54`

```python
tools = [
    tool
    for tool in catalog
    if any(fnmatch(tool["name"], pattern) for pattern in self.skill.allowed_tools)
    and (not tool["name"].startswith("query_") or tool["name"] == database_tool)
]
tool_names = {tool["name"] for tool in tools}
if database_tool not in tool_names:
    raise PipelineStageError("mcp_tool_discovery", ...)
```

当前 Skill allowlist 是 `current_datetime`、`resolve_date_range`、`query_*`（`database_query/config.json:4-8`）。第二个条件又把所有 `query_*` 收窄到**当前 database 对应的一个工具**。这正是 `SingleDatabase` 的运行时约束之一。

### 5.5 当前环境实际 `tools/list` 的结果

本次调查使用仓库当前 `.venv`，对 `LocalMcpClient(create_local_mcp_server()).list_tools()` 做了只读调用。默认访问范围返回 3 个工具。以下不是猜测，而是 2026-08-30 当前源码与当前依赖生成的结构；不同 `access_scope` 可能隐藏 database tool，因此生产请求的精确列表仍由运行时权限决定。

三个工具共同 annotations 为：

```json
{
  "readOnlyHint": true,
  "destructiveHint": false,
  "idempotentHint": true,
  "openWorldHint": false
}
```

annotations 的构造位置是 `backend/app/mcp_runtime/server.py:12-17`。

#### 工具 1：`current_datetime`

```json
{
  "name": "current_datetime",
  "title": "获取当前日期时间",
  "description": "获取Asia/Shanghai或UTC时区的当前日期与时间。",
  "input_schema": {
    "type": "object",
    "properties": {
      "timezone_name": {
        "default": "Asia/Shanghai",
        "enum": ["Asia/Shanghai", "UTC"],
        "title": "Timezone Name",
        "type": "string"
      }
    },
    "title": "current_datetimeArguments"
  },
  "output_schema": {
    "properties": {
      "date": {"description": "当前日期，格式为YYYY-MM-DD", "title": "Date", "type": "string"},
      "datetime": {"description": "包含时区的当前时间", "title": "Datetime", "type": "string"},
      "timezone": {"description": "返回结果使用的时区", "title": "Timezone", "type": "string"}
    },
    "required": ["date", "datetime", "timezone"],
    "title": "DateTimeResult",
    "type": "object"
  }
}
```

实现函数：`backend/app/mcp_runtime/tools/time_tools.py:20-27`。输入类型 `TimezoneName` 在该文件 `:10` 定义，输出类型 `DateTimeResult` 在 `backend/app/mcp_runtime/schemas.py:8-11` 定义。

#### 工具 2：`resolve_date_range`

```json
{
  "name": "resolve_date_range",
  "title": "解析相对日期范围",
  "description": "将今天、昨天、本周、上周、本月、上月或今年转换为明确起止日期。",
  "input_schema": {
    "type": "object",
    "properties": {
      "expression": {
        "enum": ["今天", "昨天", "本周", "上周", "本月", "上月", "今年"],
        "title": "Expression",
        "type": "string"
      },
      "timezone_name": {
        "default": "Asia/Shanghai",
        "enum": ["Asia/Shanghai", "UTC"],
        "title": "Timezone Name",
        "type": "string"
      }
    },
    "required": ["expression"],
    "title": "resolve_date_rangeArguments"
  },
  "output_schema": {
    "properties": {
      "expression": {"description": "输入的相对时间表达式", "title": "Expression", "type": "string"},
      "start_date": {"description": "起始日期，格式为YYYY-MM-DD", "title": "Start Date", "type": "string"},
      "end_date": {"description": "结束日期，格式为YYYY-MM-DD，包含当天", "title": "End Date", "type": "string"},
      "timezone": {"description": "计算日期范围时使用的时区", "title": "Timezone", "type": "string"}
    },
    "required": ["expression", "start_date", "end_date", "timezone"],
    "title": "DateRangeResult",
    "type": "object"
  }
}
```

实现函数：`backend/app/mcp_runtime/tools/time_tools.py:30-42`。枚举输入在 `:11`，日期解析职责在 `:45-63`，输出 Pydantic 模型在 `backend/app/mcp_runtime/schemas.py:14-18`。

#### 工具 3：`query_askdata_mock`

```json
{
  "name": "query_askdata_mock",
  "title": "查询数据库 askdata_mock",
  "description": "在数据库askdata_mock中执行一条只读DuckDB SQL。可用表：orders_current, orders_history, customers, products, sales_targets。每次调用最多返回200行。",
  "input_schema": {
    "type": "object",
    "properties": {
      "sql": {
        "description": "需要执行的一条DuckDB SELECT或WITH只读SQL。只能引用当前工具对应数据库中的表，最多返回200行。",
        "maxLength": 12000,
        "minLength": 8,
        "title": "Sql",
        "type": "string"
      }
    },
    "required": ["sql"],
    "title": "query_askdata_mockArguments"
  },
  "output_schema": {
    "properties": {
      "database": {"description": "执行查询的数据库名称", "title": "Database", "type": "string"},
      "sql": {"description": "实际执行或尝试执行的SQL", "title": "Sql", "type": "string"},
      "success": {"description": "SQL是否执行成功", "title": "Success", "type": "boolean"},
      "columns": {"description": "结果字段", "items": {"type": "string"}, "title": "Columns", "type": "array"},
      "rows": {"description": "查询结果，最多200行", "items": {"additionalProperties": true, "type": "object"}, "title": "Rows", "type": "array"},
      "row_count": {"default": 0, "description": "返回结果行数", "title": "Row Count", "type": "integer"},
      "error": {
        "anyOf": [{"type": "string"}, {"type": "null"}],
        "default": null,
        "description": "执行失败时的错误信息",
        "title": "Error"
      }
    },
    "required": ["database", "sql", "success"],
    "title": "DatabaseQueryResult",
    "type": "object"
  }
}
```

SQL 入参的 `Annotated[str, Field(...)]` 定义在 `backend/app/mcp_runtime/tools/database_tools.py:12-22`；返回类型 `DatabaseQueryResult` 定义在 `backend/app/mcp_runtime/schemas.py:21-28`。

### 5.6 模型如何“知道”可调用什么

模型看到每个工具的：

```text
name + title + description + input_schema + output_schema + annotations
```

这些字典位于 user message JSON 的 `mcp_tools`。Skill system message又要求模型输出：

```json
{"action":"call_tool","tool_name":"...","arguments":{},"reason":"..."}
```

模型据此选择 `tool_name` 并按 `input_schema` 生成 `arguments`。随后程序再次做两个层次的检查：

1. Agent 检查选择的 `tool_name` 必须在过滤后的 `tool_names` 中，并要求 `arguments` 为 dict（`single_database_agent.py:102-107`）；
2. MCP/Pydantic 根据工具 Schema 校验具体参数，数据库执行器再验证 SQL 与权限。

这是一种“把 MCP schemas 作为 Prompt 数据交给模型，再由应用代码调用 MCP”的实现，不是 Chat API 原生 tools 参数自动执行。

---

## 6. `clarify` 分支：模型输出、状态保存、暂停与恢复

### 6.1 模型应返回的结构

Skill 给出的目标结构位于 `backend/app/skills/database_query/SKILL.md:33-47`：

```json
{
  "action": "clarify",
  "reason": "...",
  "clarification": {
    "parameter": "...",
    "question": "...",
    "reason": "...",
    "options": [
      {
        "id": "...",
        "label": "...",
        "description": "...",
        "recommended": true
      }
    ]
  }
}
```

这里是 Prompt 约定；真正让它成为运行时分支的是下面的 Python 代码。

### 6.2 Agent 如何识别并校验 `clarify`

位置：`backend/app/querying/single_database_agent.py:83-97`

```python
action = str(decision.get("action") or "")
if action not in self.skill.output_actions:
    raise ValueError(f"Skill不允许输出动作：{action}")

if action == "clarify":
    clarification = decision.get("clarification")
    if not isinstance(clarification, dict) or len(
        clarification.get("options") or []
    ) < 2:
        raise ValueError("智能体返回的澄清信息不完整")
    return {
        "action": "clarify",
        "clarification": clarification,
        "tool_trace": tool_trace,
    }
```

Agent 此处硬性确认：

- action 是 Skill 允许的 `clarify`；
- `clarification` 是 dict；
- `options` 至少两个。

它没有在这里逐字段验证每个 option。后面 `ResultBuilder.waiting()` 会构造 Pydantic `Clarification`/`ClarificationOption`，其模型定义在 `backend/app/models.py:40-51`，从而进一步验证输出形状。

**当前 `SingleDatabaseAgent.prepare()` 在 `return` 处立即结束。** 它没有等待用户输入，也不会在其 `for` 循环里挂起。

### 6.3 clarify 内容先保存到 LangGraph State

位置：`backend/app/workflows/query_graph.py:261-279`  
函数：`QueryWorkflow._prepare_single_database()`

```python
if decision["action"] == "clarify":
    return {
        "workflow_mode": "single_database_agent",
        "clarification": decision["clarification"],
        "mcp_tool_trace": decision.get("tool_trace", []),
        "direct_sql": "",
    }
```

Node 返回的是一个 **State update**；LangGraph 将 `clarification` dict 写入 `QueryState["clarification"]`。Graph 的条件边判断该字段：

位置：`backend/app/workflows/query_graph.py:102-109`

```python
builder.add_conditional_edges(
    "prepare_single_database",
    lambda state: "human_clarification" if state.get("clarification") else "execute_single_database",
    {
        "human_clarification": "human_clarification",
        "execute_single_database": "execute_single_database",
    },
)
```

因此它进入 `human_clarification` node，而不是数据库执行 node。

### 6.4 Workflow 在哪里暂停

位置：`backend/app/workflows/query_graph.py:241-256`  
函数：`QueryWorkflow._human_clarification()`

```python
response = interrupt(state.get("clarification") or {})
option_id = str(response.get("option_id") if isinstance(response, dict) else response)
workspace = dict(state.get("workspace") or {})
payload = state.get("clarification") or {}
parameter = str(payload.get("parameter") or "other")
tables = list(workspace.get("confirmed_schema_tables") or [])
if any(table["id"] == option_id for table in SCHEMA):
    tables = list(dict.fromkeys([*tables, option_id]))
workspace["confirmed_schema_tables"] = tables
workspace["confirmed_parameters"] = {
    **dict(workspace.get("confirmed_parameters") or {}),
    parameter: option_id,
}
return {"workspace": workspace, "clarification": None, "direct_sql": "", "result": {}}
```

第一次执行到 `interrupt(...)` 时，LangGraph 用该 payload 暂停。`QueryWorkflow` 使用 `InMemorySaver`（`query_graph.py:54`），编译时把它作为 checkpointer（`query_graph.py:116`），并以 `task_id` 作为 `thread_id`（`query_graph.py:118-124`）。所以暂停状态与同一个 task/thread 绑定。

### 6.5 暂停结果如何变成 API 可见的 waiting result

`QueryWorkflow.invoke()` 在暂停后没有 `state["result"]`，于是调用 `ResultBuilder.waiting()`：

位置：`backend/app/workflows/query_graph.py:122-130`

```python
state = self.graph.invoke(payload, config=self.run_config(task_id))
return self._state_result(state, task_id)
```

位置：`backend/app/workflows/result_builder.py:59-81`

```python
payload = state.get("clarification") or {}
clarification = Clarification(
    parameter=str(payload.get("parameter") or "other"),
    question=str(payload.get("question") or "请补充本次查询所需信息"),
    reason=str(payload.get("reason") or "该信息会改变查询结果"),
    options=payload.get("options") or [],
)
return QueryResult(
    task_id=state["task_id"],
    status="waiting_clarification",
    # ...
    clarification=clarification,
    retrieval=ResultBuilder.public_retrieval(state.get("retrieval") or {}),
    standalone_query=state.get("standalone_query"),
    schema_graph=state.get("schema_graph"),
)
```

Service 随后调用 `SessionContext.remember()`（`backend/app/services/askdata_service.py:106-112`）。`remember()` 把 `QueryResult` 与 query/workspace/user 写入内存 `tasks`，并写 session archive（`backend/app/services/session_context.py:40-64`）。因此 clarify 信息同时存在于：

1. LangGraph checkpoint 的 `QueryState["clarification"]`；
2. 对外 `QueryResult.clarification`；
3. Service 的 task/session 记录（以及启用时的 session archive）。

### 6.6 用户回复后，是“恢复原 Agent”还是“一次新调用”

显式澄清 API：`backend/app/api/routes.py:133-146` 调 `AskDataService.clarify()`。

核心恢复代码：`backend/app/services/askdata_service.py:122-161`

```python
task = self.tasks.get(task_id)
# ...校验用户和 option_id...
result = self.workflow.invoke(
    Command(resume={"option_id": option_id}),
    task_id,
)
```

自然语言回复也可以在下一次 `submit()` 被识别：`askdata_service.py:62-71` 用 `latest_pending()` 和 `match_clarification()` 匹配后，转调同一个 `self.clarify(...)`，不会创建新 `task_id`。

严格判断：

- **不是** `SingleDatabaseAgent` 自己一直停在循环里等用户；它早已返回。
- **是**一次新的 Python `workflow.invoke(...)` 调用。
- **不是**创建一个新 `QueryWorkflow` 对象或新任务；Service 复用 `self.workflow`，并复用原 `task_id` 作为 LangGraph `thread_id`。
- `Command(resume=...)` 令原 checkpoint 中的 `interrupt()` 返回用户选择，`_human_clarification()` 才继续更新 workspace。
- Graph 有 `human_clarification → retrieve_schema` 的边（`query_graph.py:101`），所以恢复后会重新 Retrieval、重建 SchemaGraph，再调用 `SingleDatabaseAgent.prepare()`。这是**一次新的 Agent prepare/LLM 决策阶段**。

简化状态流：

```text
Agent sampling
→ decision.action = clarify
→ SingleDatabaseAgent.prepare() return
→ State["clarification"] = clarification
→ human_clarification node
→ interrupt(payload)
→ 本次 workflow.invoke 返回 waiting QueryResult
→ Service 保存 pending task

用户提交 option_id
→ 新的一次 AskDataService.clarify()
→ 新的一次 workflow.invoke(Command(resume=...), 同一 task_id)
→ 原 interrupt 返回 option_id
→ 更新 State["workspace"].confirmed_*
→ human_clarification → retrieve_schema
→ prepare_single_database
→ 新的一次 SingleDatabaseAgent.prepare()/LLM 决策
```

---

## 7. `call_tool` 分支：从模型 JSON 到 SQL、DuckDB 和 rows

### 7.1 模型输出与 Agent 解析

Skill 约定的输出位于 `backend/app/skills/database_query/SKILL.md:27-31`：

```json
{
  "action": "call_tool",
  "tool_name": "query_askdata_mock",
  "arguments": {
    "sql": "SELECT ..."
  },
  "reason": "..."
}
```

真实解析代码：`backend/app/querying/single_database_agent.py:99-109`

```python
if action != "call_tool":
    raise ValueError("智能体必须返回call_tool或clarify")

tool_name = str(decision.get("tool_name") or "")
arguments = decision.get("arguments")
if tool_name not in tool_names:
    raise ValueError(f"智能体选择了未提供的MCP工具：{tool_name}")
if not isinstance(arguments, dict):
    raise ValueError("MCP工具参数必须是JSON对象")

tool_result = mcp_client.call_tool(tool_name, arguments)
```

**SQL 是 LLM 直接生成的吗？**

对 database tool 而言，是。模型从普通 Chat response 的 JSON 中直接给出 SQL，字段路径是：

```text
choices[0].message.content
→ json.loads(...)
→ decision["arguments"]["sql"]
```

Agent 本身没有生成 SQL 的模板，也没有把其它字段变成 SQL。它只校验 `tool_name`/`arguments` 的基本形状，再把整个 arguments 交给 MCP。SQL 还会被 MCP/Pydantic 和 `DuckDbEngine` 校验，因此“LLM 生成”不等于“无校验直接执行”。固定 Query 会生成的精确 SQL 必须看运行时模型返回，不能由静态源码确认。

### 7.2 MCP Client 真正发起工具调用

位置：`backend/app/mcp_runtime/client.py:38-54`  
类/函数：`LocalMcpClient.call_tool()` / `_call_tool()`

```python
def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(self._call_tool(name, arguments))

async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async with Client(self.server) as client:
        result = await client.call_tool(name, arguments)
    if result.is_error:
        # ...转成 RuntimeError
    if result.structured_content is None:
        raise RuntimeError(...)
    return dict(result.structured_content)
```

调用链跨过 `await client.call_tool(...)` 进入前面通过 `server.tool(...)(handler)` 注册的 callable。当前 database 为 `askdata_mock` 时，名字为 `query_askdata_mock`，对应 handler 是 `build_database_query_tool(...)` 创建的闭包。

### 7.3 具体 database tool 如何调用执行引擎

位置：`backend/app/mcp_runtime/tools/database_tools.py:25-46`  
函数：`build_database_query_tool()` / 内部 `query_database()`

```python
def build_database_query_tool(database, engine, access_scope):
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

此 closure 在创建时已经绑定：

- `database`：当前工具对应数据库；
- `DuckDbEngine`：Workflow 持有的数据库引擎；
- `access_scope`：本次用户权限。

模型不能通过 arguments 改写这三个绑定值，只能提交 Schema 允许的 `sql` 参数。

### 7.4 DuckDB 实际执行与 rows 构造

位置：`backend/app/querying/duckdb_engine.py:33-51`  
类/函数：`DuckDbEngine.execute()`

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

`_validate_sql()` 在 `duckdb_engine.py:75-127` 做只读、单语句、禁止 `SELECT *`、已知表与访问权限检查。`connect()` 在 `:53-73` 建立内存 DuckDB 连接，把 `backend/data/databases/<database>/*.csv` 注册为只读 view。查询成功返回 `SqlExecution` dataclass：

位置：`backend/app/querying/models.py:7-13`

```python
@dataclass
class SqlExecution:
    sql: str
    success: bool
    columns: list[str]
    rows: list[dict[str, Any]]
    error: str | None
```

database tool 再把它包装成 `DatabaseQueryResult`，MCP 将 Pydantic 输出放入 `structured_content`，Client 最终转回一个普通 dict。成功时形状为：

```python
{
    "database": str,
    "sql": str,
    "success": bool,
    "columns": list[str],
    "rows": list[dict[str, Any]],
    "row_count": int,
    "error": str | None,
}
```

### 7.5 tool result 返回给谁

返回方向逐层是：

```text
DuckDbEngine.execute()
→ SqlExecution
→ query_database()
→ DatabaseQueryResult
→ MCP CallToolResult.structured_content
→ LocalMcpClient._call_tool()
→ dict(result.structured_content)
→ SingleDatabaseAgent.prepare() 内的 tool_result
```

Agent 先将它记入 trace：`single_database_agent.py:110-117`

```python
trace = {
    "call_index": call_index,
    "tool": tool_name,
    "arguments": arguments,
    "result": tool_result,
    "reason": str(decision.get("reason") or ""),
}
tool_trace.append(trace)
```

然后关键终止判断位于 `single_database_agent.py:119-127`：

```python
if tool_name == database_tool:
    return {
        "action": "executed",
        "execution": tool_result,
        "tool_trace": tool_trace,
        "source": "model_mcp",
    }

observations.append({"tool": tool_name, "result": tool_result})
```

Python 控制流先判断 database tool 并 `return`，只有非数据库工具才执行下一行 `observations.append(...)`。所以：

- 时间工具结果 → 加入 observations → 下一轮 payload 的 `tool_results` → 同一个 Agent 再采样；
- 数据库工具结果（含 rows）→ 直接作为 `execution` 返回 Workflow → **不会**加入 observations → **不会**再送入同一个 Agent LLM。

这条先后顺序是判断是否为完整 ReAct loop 的最关键源码证据。

### 7.6 Workflow 接收 database result 后做什么

位置：`backend/app/workflows/query_graph.py:280-290`

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

这是 `_prepare_single_database` node 的 State update。Graph 的条件边会走 `execute_single_database`，而不是回到 `prepare_single_database`（`query_graph.py:102-110`）。

`QueryWorkflow._execute_single_database()` 在 `query_graph.py:293-302` 把 `mcp_execution` dict 重新构造成 `SqlExecution`，并在 `:303-336` 整理 execution log/tool call。SQL 失败就直接构建失败结果（`:337-339`）；成功则进入：

```python
final = self.response_generator.finalize(
    state["standalone_query"],
    execution,
    state["schema_context"],
    state.get("analysis_context", ""),
)
```

位置：`backend/app/workflows/query_graph.py:340-344`。

`ResponseGenerator.finalize()` 位于 `backend/app/querying/response_generator.py:34-58`。它确实把 SQL、columns、截断后的 rows、Schema context 等交给 `ModelClient.chat_json()`，生成标题和简短说明。

因此要精确区分：

- **NO**：database rows 不会返回 `SingleDatabaseAgent` 的 decision LLM，也不会让它再决定一个工具；
- **YES**：database rows 成功后会进入一个**不同职责、不同 system prompt 的 `ResponseGenerator.finalize()` LLM 调用**，用于结果说明；这不是 Agent tool loop 的下一轮。

最终 `ResultBuilder.completed()` 在 `backend/app/workflows/result_builder.py:84-139` 把 SQL、columns、rows、analysis、retrieval、schema_graph、tool_calls 等装进 `QueryResult`。Graph 对 `execute_single_database` 的边是直接到 `END`（`query_graph.py:110`）。

---

## 8. 循环调查：它究竟是不是 ReAct Agent

### 8.1 Agent 内确实存在一个 `for` 循环

完整控制骨架位于 `backend/app/querying/single_database_agent.py:75-129`：

```python
for call_index in range(1, self.max_tool_calls + 1):
    payload = {**base_payload, "tool_results": observations}
    decision = self.model_client.chat_json(...)

    if action == "clarify":
        return {...}

    tool_result = mcp_client.call_tool(tool_name, arguments)
    tool_trace.append(trace)

    if tool_name == database_tool:
        return {
            "action": "executed",
            "execution": tool_result,
            ...
        }

    observations.append({"tool": tool_name, "result": tool_result})

raise ValueError(f"MCP工具调用超过上限：{self.max_tool_calls}")
```

因此不能把这个类说成“永远只调用一次模型”。它可以出现：

```text
LLM sampling #1
→ call_tool(current_datetime / resolve_date_range)
→ time tool result
→ observations
→ LLM sampling #2（user JSON 的 tool_results 已包含 observation）
→ ...
```

但是 database tool 是终止性工具：

```text
LLM sampling #N
→ call_tool(query_<database>, {sql: ...})
→ database rows
→ return execution
```

没有后续：

```text
database rows
→ observations
→ Agent LLM sampling #N+1
```

### 8.2 一次正常 `prepare()` 到底发生几次 LLM sampling

源码能给出的严格答案是：**0～`max_tool_calls` 次；在当前默认可用配置、且确实进入循环的正常请求中，通常是 1～3 次。**

- 配置或 Skill 把上限设为 0 时，`range(1, 1)` 不迭代，直接报超限，所以理论下限为 0；当前默认不是这种配置。
- 第一次模型直接选择 database tool：1 次 Agent sampling。
- 先调用一个时间工具，再选择 database tool：2 次。
- 先调用两个非数据库工具，再选择 database tool：3 次。
- 三次都没有选择 database tool/clarify：完成 3 次 sampling 后抛出工具调用超限错误。
- 模型在任意一轮选择 clarify：该轮后结束本次 `prepare()`。

对固定 Query `查询本月各地区销售额`，Skill 文本要求“相对时间会影响 SQL 时，先调用时间工具”，但程序没有硬编码“看到本月必须调用哪个时间工具”。模型可能直接生成含日期逻辑的 SQL，也可能先调用 `current_datetime` 或 `resolve_date_range`。所以**生产模型实际发生 1、2 还是 3 次，只能在运行时根据 `mcp_tool_trace` 确认**。

此外，一次成功数据库查询之后通常还有 `ResponseGenerator.finalize()` 的 1 次模型调用，但那是结果整理 sampling，不计入 `SingleDatabaseAgent.prepare()` 自身次数。

### 8.3 A/B/C 分类

附件给出的选项是：

```text
A. 一个完整 Agent Loop
B. 一次 LLM decision node
C. 其他结构
```

严格分类：**C，受上限约束的混合式 Tool Loop。**

理由：

- 它不是纯 B，因为非数据库工具的 result 会进入下一轮 LLM，代码确实有多轮 decision/tool/observation。
- 它也不是“对所有工具都闭环”的 A，因为最关键的 database rows 不进入下一轮 Agent decision；数据库调用被设计成终止动作。
- 若只观察最常见的“模型直接生成 SQL 并调用数据库”主路径，它的作用更接近 B：一次 LLM decision node + 一次确定性 tool execution。

从严格 Agent Engineering 术语看，建议称它为：

> **带非终止辅助工具 observation 的、数据库工具终止型 LLM Tool Controller。**

不建议不加限定地称为“完整 ReAct Loop”。

### 8.4 Agent 内循环由谁控制

控制者唯一明确为：

```text
backend/app/querying/single_database_agent.py
→ SingleDatabaseAgent.prepare()
→ for call_index in range(...)
```

循环继续条件不是一个显式 `while` 布尔表达式，而是：当前 action 为 `call_tool`、tool 是允许的非数据库工具、调用成功，并且尚未达到 `max_tool_calls`。`clarify`、database tool、异常或超限都会终止。

### 8.5 Workflow 外层有没有更大的 tool loop

Graph 定义位于 `backend/app/workflows/query_graph.py:63-116`。与本阶段直接相关的边是：

```text
retrieve_schema
├─→ human_clarification ─→ retrieve_schema
├─→ prepare_single_database
│   ├─→ human_clarification ─→ retrieve_schema
│   └─→ execute_single_database ─→ END
└─→ run_multi_database ─→ END / human_clarification
```

源码证明两个不同结论：

1. **存在外层 HITL 状态环**：`human_clarification → retrieve_schema`（`query_graph.py:101`）。用户补充后重新检索、重新进 Agent。
2. **不存在外层数据库 observation 决策环**：`execute_single_database → END`（`query_graph.py:110`），没有返回 `prepare_single_database` 的 edge。数据库 rows 不会通过 State 更新后再进入 Agent。

所以整个 Workflow 也没有形成下面这种数据库 ReAct 循环：

```text
Agent decision
→ database tool
→ State rows
→ Agent decision again
```

`ResponseGenerator.finalize()` 是终点前的结果说明模型，不是回到 tool selection node。

---

## 9. `SingleDatabase` 的真实含义与多数据库逻辑

### 9.1 不是根据类名猜，而是看约束发生在哪里

有四组直接证据说明它修饰“数据库范围”：

1. `_after_retrieval()` 先以 `len(database_names)` 区分 single/multi（`query_graph.py:235-239`）。
2. `_prepare_single_database()` 在 Agent 前选定一个 `database` 字符串（`query_graph.py:261-264`）。
3. Agent 计算唯一终止工具名 `database_tool = f"query_{database}"`（`single_database_agent.py:38`）。
4. Agent 过滤掉所有其它 `query_*` 工具，只留下当前 `database_tool`（`single_database_agent.py:43-48`）。

另外，`build_database_query_tool()` 的注释和 closure 都是一库一工具（`database_tools.py:25-46`），MCP server 也按 database 循环注册工具（`server.py:47-66`）。

因此：

- **Single 不是单 Agent**：整个系统本来就有多个模型职责/组件，例如 Preprocessor、SingleDatabaseAgent、ResponseGenerator。
- **Single 不是单次 sampling**：Agent 的 `for` 允许最多多轮 sampling。
- **Single 不是单次用户 Query**：clarify 恢复会在同一 task 内再次进 Agent。
- **Single 是一次只面向一个已经选定的 database**。

Skill 还要求同一 database 的数据在一条 SQL 中查完，DuckDB 又强制一次只执行一条 SQL；这是该实现的额外限制，但不是“SingleDatabase”唯一或主要含义。

### 9.2 database 是否在进入 Agent 前确定

**是。** 确定链路是：

```text
SchemaGraphBuilder.build()
→ schema_graph["tables"][*]["database"]
→ QueryWorkflow._retrieve_schema()
→ database_names = sorted(unique database IDs)
→ QueryWorkflow._after_retrieval() 判断数量
→ QueryWorkflow._prepare_single_database()
→ database = database_names[0]（空则 askdata_mock）
→ SingleDatabaseAgent.prepare(..., database, ...)
```

Agent 不在多个数据库之间打分、路由或选择。它只用传入值收窄可见数据库工具。

### 9.3 当前多数据库路径实际做什么

位置：`backend/app/workflows/query_graph.py:357-365`  
函数：`QueryWorkflow._run_multi_database()`

```python
failure = SqlExecution(
    sql="",
    success=False,
    error="当前仅支持单库直接查询；多库 Handoff 尚未启用。",
)
result = ResultBuilder.failed(state, failure, [])
return {
    "workflow_mode": "multi_database_pending",
    "result": result.model_dump(mode="json"),
}
```

这不是多数据库 Agent、并行查询或 merge；它是一个明确失败分支。Graph 的 `run_multi_database` 条件边虽然允许有 clarification 字段时去 human node（`query_graph.py:111-115`），但当前 `_run_multi_database()` 自身不会创建 clarification，而是直接返回 `result`，所以当前实现会走 `end`。

当前 `backend/app/database.py:42-108` 的所有表都属于 `askdata_mock`，因此以当前静态 Schema 正常构建的图通常只有一个 database。若未来 Schema 出现多个 database 且一个图包含它们，代码会进入上述 pending/failed 分支。

---

## 10. 完整真实调用链（从上一阶段产物到最终返回）

```text
上一阶段 SchemaGraphBuilder.build(...)
backend/app/retrieval/graph.py:18-109
    ↓ 返回 schema_graph: dict

QueryWorkflow._retrieve_schema()
backend/app/workflows/query_graph.py:193-233
    ├─ State["retrieval"] = enriched retrieval
    ├─ State["schema_graph"] = schema_graph
    ├─ State["schema_context"] = SchemaGraphBuilder.context_text(schema_graph)
    └─ State["database_names"] = graph tables 中 database 去重排序
    ↓

QueryWorkflow._after_retrieval()
backend/app/workflows/query_graph.py:235-239
    ├─ database_names <= 1 → prepare_single_database
    └─ database_names > 1  → run_multi_database（当前明确失败：Handoff 未启用）
    ↓

QueryWorkflow._prepare_single_database()
backend/app/workflows/query_graph.py:261-290
    ├─ database = database_names[0]；空则 askdata_mock
    └─ SingleDatabaseAgent.prepare(
           query=State["standalone_query"],
           database=database,
           schema_graph=State["schema_graph"],
           schema_context=State["schema_context"],
           retrieval=State["retrieval"],
           workspace=State["workspace"],
           access_scope=State["access_scope"],
       )
       ↓

SingleDatabaseAgent.prepare()
backend/app/querying/single_database_agent.py:28-133
    ├─ QueryWorkflow.mcp_client(access_scope)
    │  backend/app/workflows/query_graph.py:57-59
    │  ↓
    │  create_local_mcp_server(DuckDbEngine, AccessScope)
    │  backend/app/mcp_runtime/server.py:20-67
    │  ↓
    │  LocalMcpClient.list_tools()
    │  backend/app/mcp_runtime/client.py:16-36
    │  ↓
    │  按 Skill allowlist + 当前 query_<database> 过滤
    │
    ├─ system = "你是单数据库问数智能体" + SkillDefinition.instructions
    ├─ user JSON = query/database/schema_graph/retrieval/
    │              confirmed_fields/confirmed_parameters/schema_text/
    │              mcp_tools/tool_results
    │
    └─ for call_index = 1..max_tool_calls
       ↓
       ModelClient.chat_json(system, user_json)
       backend/app/model_client.py:41-53
       ↓
       ModelClient.chat()
       backend/app/model_client.py:25-39
       ↓
       urllib.request.urlopen(...)
       backend/app/model_client.py:107     # 真正发送模型 HTTP 请求
       ↓
       message.content → JSON dict decision
       │
       ├── action = clarify
       │   ↓
       │   SingleDatabaseAgent.prepare() return clarification
       │   ↓
       │   QueryWorkflow._prepare_single_database()
       │   → State["clarification"]
       │   ↓
       │   QueryWorkflow._human_clarification()
       │   backend/app/workflows/query_graph.py:241-256
       │   → interrupt(clarification)
       │   ↓
       │   ResultBuilder.waiting()
       │   → waiting_clarification QueryResult
       │   ↓
       │   用户回答
       │   ↓
       │   AskDataService.clarify()
       │   backend/app/services/askdata_service.py:122-161
       │   → workflow.invoke(Command(resume={option_id}), 同一 task_id)
       │   ↓
       │   更新 workspace.confirmed_schema_tables / confirmed_parameters
       │   ↓
       │   retrieve_schema → 重新构图 → 再次进入 Agent
       │
       └── action = call_tool
           ↓ tool_name + arguments
           LocalMcpClient.call_tool(tool_name, arguments)
           backend/app/mcp_runtime/client.py:38-54
           │
           ├── current_datetime / resolve_date_range
           │   backend/app/mcp_runtime/tools/time_tools.py:20-42
           │   ↓ structured result
           │   observations.append({tool, result})
           │   ↓
           │   回到 Agent for 下一轮，作为 payload["tool_results"]
           │
           └── query_<database>, arguments = {"sql": LLM生成的SQL}
               ↓
               build_database_query_tool() 创建的 query_database(sql)
               backend/app/mcp_runtime/tools/database_tools.py:25-46
               ↓
               DuckDbEngine.execute(database, sql, access_scope)
               backend/app/querying/duckdb_engine.py:33-51
               ↓
               SQL校验 → 内存 DuckDB/CSV views → columns + rows（最多200）
               ↓
               DatabaseQueryResult → MCP structured_content → dict tool_result
               ↓
               SingleDatabaseAgent 立即 return execution
               ↓ 是否再次进入 Agent LLM：NO

QueryWorkflow._prepare_single_database()
→ State["mcp_execution"] = tool_result
→ State["mcp_tool_trace"] = trace
    ↓

QueryWorkflow._execute_single_database()
backend/app/workflows/query_graph.py:293-355
→ dict 重建为 SqlExecution
→ 失败：ResultBuilder.failed() → END
→ 成功：ResponseGenerator.finalize()
          backend/app/querying/response_generator.py:34-58
          ↓ 另一次、非 Agent 决策的 LLM sampling
          SQL + columns + rows + schema_context → 标题/说明 JSON
          ↓
          ResultBuilder.completed()
          backend/app/workflows/result_builder.py:84-139
          ↓
          QueryResult(sql, columns, rows, analysis, retrieval, schema_graph, traces...)
          ↓
          END
```

---

## 11. 固定 Query 的可确认数据流与不可静态确认项

固定 Query：`查询本月各地区销售额`

### 11.1 源码明确证明

- 若预处理路由为 `database_query`，Agent 的 `query` 来自预处理后的 `standalone_query`，不是另行从 HTTP 读取。
- 当前静态 `SCHEMA` 只有 `askdata_mock` 一个数据库；所有表定义见 `backend/app/database.py:42-108`。
- 图只含该库时，Workflow 在 Agent 前选择 `database = "askdata_mock"`。
- Agent 可见的 database tool 名是 `query_askdata_mock`，其它 `query_*` 会被过滤。
- 该工具的 arguments 必须包含 `sql`；SQL 字符串由模型放在 `decision["arguments"]["sql"]`。
- database rows 不会再次进入 `SingleDatabaseAgent`；成功后它们进入 `ResponseGenerator.finalize()` 和最终 `QueryResult`。
- 任何时间工具结果都会进入下一轮 `tool_results`。

### 11.2 运行时才能确认

- 预处理模型是否原样保留 `standalone_query`；
- 本次 Schema hits 和最终 schema_graph 的确切字段集合；
- 模型是否先调用 `current_datetime`、`resolve_date_range`，还是直接调用 database tool；
- SingleDatabaseAgent 此次到底采样 1、2 还是 3 次；
- 模型生成的精确 SQL 文本；
- DuckDB 返回的精确 rows；
- 最终结果说明模型生成的 title/analysis；
- 部署时环境变量覆盖后的 `max_tool_calls` 和模型 endpoint 行为。

### 11.3 根据结构可以合理推断、但不能冒充运行结果

由于问题包含“本月”，Skill instruction 倾向模型先解析明确日期；但 Agent 代码没有对该词做确定性分支，所以只能说“模型被要求这样做”，不能说固定 Query 必然先调用某一个时间工具。

当前测试 Fake Model 在 `backend/tests/test_service.py:62-104` 演示了真实协议：它读取 `tool_results`，对“今天”先返回 `current_datetime`，之后在 `arguments.sql` 中返回 SQL。测试 `test_relative_date_calls_datetime_tool_before_sql`（`test_service.py:345-354`）验证了多轮辅助工具路径；`test_single_database_agent_executes_one_query`（`:356-360`）验证了固定 Query 在 Fake Model 下的一次 database call。它们证明控制流可工作，但 Fake Model 的决策不能等同于生产 LLM 的必然决策。

---

## 12. 最终问题清单：逐条结论

### 12.1 `SingleDatabaseAgent` 一次正常调用实际发生几次 LLM sampling？

当前默认上限内是 **1～3 次 Agent decision sampling，精确次数运行时才能确认**。直接调用数据库是 1 次；每个先行的非数据库工具会再导致下一轮。成功后 `ResponseGenerator.finalize()` 另有一次结果整理 sampling，不属于 Agent 本身。

### 12.2 第一次返回 `call_tool` 后，tool result 会不会重新喂回这个 LLM？

- 第一次调用的是时间/其它非数据库工具：**会**，以 `tool_results` 中 `{tool, result}` 的形式进入下一轮。
- 第一次调用的是当前 `query_<database>`：**不会**，结果立即作为 `execution` return。

### 12.3 Agent 内有没有 `LLM → Tool → Observation → LLM`？

**对非数据库工具有；对 database tool 没有。** 因此是部分/混合 loop，不是对最终查询结果闭环的完整 ReAct loop。

### 12.4 真正控制循环的是谁？

Agent 内循环由 `backend/app/querying/single_database_agent.py::SingleDatabaseAgent.prepare()` 的 `for call_index in range(...)` 控制。外层只另有 `backend/app/workflows/query_graph.py::_compile()` 定义的 human clarification 状态环。

### 12.5 更接近完整 Agent，还是 LLM decision node？

严格三选一是 **C：数据库终止型的有界 Tool Controller**。在主数据库路径上更接近 LLM decision node，因为 rows 不返回决策模型；辅助时间工具路径又比纯单次 decision node 多一层 observation loop。

### 12.6 为什么叫 `SingleDatabaseAgent`？

因为 Workflow 先选定一个 database，Agent 只暴露这个库对应的一个 `query_<database>` 工具。它不代表单模型组件、单次采样、单条用户 Query，也不代表系统已支持多库协作。

### 12.7 AskData 在这一阶段真正的控制流是什么？

**确定性 LangGraph 编排 + Skill 驱动的 JSON 模型决策 + 进程内 MCP 工具执行；辅助时间工具可以回到同一决策循环，数据库工具是终止动作，执行结果交给独立的结果说明模型与 ResultBuilder。**

---

## 13. 源码状态与本次核验说明

本次只读核验结果：

- 对下列关键文件执行 Python AST parse，全部通过：`single_database_agent.py`、`query_graph.py`、`registry.py`、`model_client.py`、`mcp_runtime/client.py`、`mcp_runtime/server.py`、`database_tools.py`、`mcp_runtime/schemas.py`、`duckdb_engine.py`。
- 使用当前 `backend/.venv` 成功执行本地 MCP `tools/list`，得到本文第 5.5 节记录的三个工具。
- 运行 `tests.test_mcp_runtime` 全组以及四个直接相关 Service 测试（同 task 澄清恢复、自然语言澄清恢复、时间工具先于 SQL、单库查询），共 10 个测试，全部通过。

因此当前调查范围内没有发现“源码语法错误导致只能猜测”的情况。不过上述测试使用 Fake Model，不能证明外部生产 LLM 对固定 Query 的具体输出；精确 sampling 次数、SQL 和 rows 仍须看一次真实运行 trace。

本文没有修改任何业务代码。
