# AskData 第九步源码调查：ResultBuilder / QueryResult Provenance Audit

> 调查日期：2026-09-04  
> 目标：建立最终 `QueryResult` 的 Result Provenance Map。  
> 主边界：`SqlExecution → ResultBuilder → QueryResult`。  
> 依据：当前工作区源码；本报告重新核对当前行号，不直接复制历史结论。  
> 限制：只读、追踪、分类；不修改 ResultBuilder、QueryResult、Interpretation、ResponseGenerator、SqlExecution，不设计 Repository/Derive/Result Contract v2。

---

## 1. Executive Summary

1. 数据库成功路径由 `QueryWorkflow._execute_single_database()` 调用 `ResultBuilder.completed(state, [execution], execution, final, [call], log)`；失败路径调用 `ResultBuilder.failed(state, execution, log)`。ResultBuilder 本身不执行 SQL，也不调用 LLM。
2. 最终 QueryResult 中最接近数据库事实的是 `sql/columns/rows`：它们从 rebuilt `SqlExecution` 直接复制。但 `rows` 已是 DuckDbEngine normalization 后、最多 200 行的 dict，不是 raw cursor tuple；DATE 已可能变 str、Decimal 已可能变 float。
3. `Interpretation.metric/dimension` 不是 schema role，也不是数据库 dtype。当前 ResultBuilder 仅检查输出列名是否包含“额/数/率/平均/目标”；命中者为 metric，其余全部为 dimension。这是明确的 heuristic inference。
4. `Interpretation.table` 来自 `schema_graph.tables[*].id → SCHEMA label` 的确定性 lookup。它描述召回/连通图中的候选表，不是 SQL output-column lineage。`time_range` 来自预处理 LLM 生成的 `extraction.time_expressions` 再由程序 join。
5. `ResponseGenerator.finalize()` 把 query、SQL、columns、前 N 行 rows、schema context、analysis context 发给 LLM。N 默认是 50，而 QueryResult 最多可保留 200 行，所以 LLM 说明不一定看过最终表中的全部 rows。
6. LLM 返回 `valid/reason/title/analysis`。程序做 JSON 解析、`bool/str` 转换和缺省值处理，但没有独立的业务正确性验证。ResultBuilder 使用 `valid/title/analysis`；`final.reason` 当前被丢弃。
7. 成功查询的 `status/message` 是 Mixed provenance：先由 DB `execution.success` 决定能否进入 completed path，再由 LLM `final.valid` 决定 `completed/failed` 和“查询完成/结果校验未通过”。它们不是纯 DB fact。
8. `retrieval/schema_graph` 是 schema/business context；`execution_log/tool_calls` 是 diagnostic/audit information；`task_id/route/workflow_mode/standalone_query/steps/route_reason` 主要是 workflow/control provenance。它们不能与 current rows 的数据库事实混为一类。
9. `analysis/result_title/interpretation/message` 以可读展示为主要构造目的。`analysis/title` 通常来自 LLM；Interpretation 混合 heuristic、schema metadata、LLM extraction 和固定文本。
10. QueryResult 中没有 output column → schema field 的确定映射。即使 `schema_graph.fields` 带 `role/type`，也只能说明相关 schema context，不能证明某个 SQL alias 已被可靠标注为 metric/dimension。

一句话总览：

> `QueryResult` 是一个混合响应对象：其中同时装有 normalized DB-originated data、schema context、确定性 Workflow 派生值、列名 heuristic、LLM 说明文本、控制状态和诊断记录；只有沿字段 provenance 拆开后，才能判断哪些适合未来确定性 Derive 使用。

---

## 2. SqlExecution → ResultBuilder → QueryResult Call Path

### 2.1 成功路径

结论：`ResultBuilder.completed()` 的唯一当前 database success caller 是 `QueryWorkflow._execute_single_database()`。

证据：

`backend/app/workflows/query_graph.py:L293-L355`

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
    # ...生成 log 和 call...
    if not execution.success:
        result = ResultBuilder.failed(state, execution, log)
        return {...}
    try:
        final = self.response_generator.finalize(
            state["standalone_query"], execution, state["schema_context"],
            state.get("analysis_context", ""),
        )
    except PipelineStageError as exc:
        final = {...}
    result = ResultBuilder.completed(state, [execution], execution, final, [call], log)
    return {"execution_log": log, "tool_calls": [call], "result": result.model_dump(mode="json")}
```

实际链：

```text
state["mcp_execution"]: dict
        ↓ query_graph.py:L296-L302
rebuilt SqlExecution
        ↓ execution.success == True
ResponseGenerator.finalize(...)
        ↓
final: {valid, reason, title, analysis}
        ↓
ResultBuilder.completed(
    state,
    [execution],
    execution,
    final,
    [call],
    log,
)
        ↓
QueryResult
        ↓ model_dump(mode="json")
state["result"]: dict
        ↓ QueryResult.model_validate(...)
最终 QueryResult
```

### 2.2 `completed()` 六个参数分别来自哪里

| 参数 | 当前调用值 | 直接来源 | Provenance |
|---|---|---|---|
| `state` | 当前完整 QueryState | LangGraph 累积状态 | Workflow/context container |
| `executions` | `[execution]` | rebuilt SqlExecution 包成单元素 list | deterministic packaging；当前函数体未使用 |
| `combined` | `execution` | `mcp_execution` dict 重建的 SqlExecution | normalized DB execution result |
| `final` | ResponseGenerator 返回或 exception fallback dict | LLM JSON + program normalization，或 deterministic fallback | LLM-generated / Mixed |
| `tool_calls` | `[call]` | `_execute_single_database()` 确定性构造 | diagnostic/audit metadata |
| `execution_log` | `log` | MCP trace + execute log + 可选 result-analysis error | diagnostic metadata |

### 2.3 进入 ResultBuilder 前的 `SqlExecution`

结论：只有五个字段。

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

在当前 single-database path 中，ResultBuilder 接到的不是 DuckDbEngine 最初返回的同一个对象，而是 Workflow 从 MCP dict 重建的 `SqlExecution`（`query_graph.py:L295-L302`）。字段值来自 MCP result，但 database/row_count 不属于该 dataclass。

### 2.4 失败路径

结论：单库执行失败时不调用 ResponseGenerator，也不调用 `completed()`；直接调用 `failed()`。

证据：

`backend/app/workflows/query_graph.py:L337-L339`

```python
if not execution.success:
    result = ResultBuilder.failed(state, execution, log)
    return {
        "execution_log": log,
        "tool_calls": [call],
        "result": result.model_dump(mode="json"),
    }
```

另一个失败 caller 是未实现的 multi-database path：

`backend/app/workflows/query_graph.py:L357-L365`

```python
failure = SqlExecution(
    sql="",
    success=False,
    error="当前仅支持单库直接查询；多库 Handoff 尚未启用。",
)
result = ResultBuilder.failed(state, failure, [])
```

这个 failure 是程序构造的 workflow failure，不是 DuckDB failure。

### 2.5 ResultBuilder 还读取哪些 Workflow State

`completed()` 当前读取：

```text
state["task_id"]
state["schema_graph"]
state["workflow_mode"]
state["rewritten"]
state["standalone_query"]
state["analysis_sources"]
state["extraction"]["time_expressions"]
state["intent"]["reason"]
state["retrieval"]
```

`failed()` 当前读取：

```text
state["task_id"]
state["intent"]["reason"]
state["retrieval"]
state["standalone_query"]
state["schema_graph"]
state["workflow_mode"]
```

证据：`backend/app/workflows/result_builder.py:L84-L155`。

### 2.6 ResultBuilder 是否调用其他组件

结论：不调用 LLM、数据库、Retriever 或 SchemaGraphBuilder。

`completed()` 只执行 Python list comprehension、`join`、`len`、state lookup、`public_retrieval()` 和 Pydantic model construction。LLM 调用发生在 caller 中：

```python
final = self.response_generator.finalize(...)
result = ResultBuilder.completed(..., final, ...)
```

证据：`backend/app/workflows/query_graph.py:L340-L354`。

### 2.7 最终谁返回 QueryResult

Workflow 内部：

`backend/app/workflows/query_graph.py:L122-L130`

```python
def invoke(self, payload: QueryState | Command, task_id: str) -> QueryResult:
    state = self.graph.invoke(payload, config=self.run_config(task_id))
    return self._state_result(state, task_id)

def _state_result(self, state: dict[str, Any], task_id: str) -> QueryResult:
    if state.get("result"):
        return QueryResult.model_validate(state["result"])
    ...
    return ResultBuilder.waiting(state)
```

Service/API 边界：

- `backend/app/services/askdata_service.py:L83-L120`：`AskDataService.submit()` 调用 Workflow、保存上下文后 `return result`；
- `backend/app/api/routes.py:L122-L130`：`POST /api/query` 声明 `response_model=QueryResult`，直接返回 `service.submit(...)`。

所以最终 API 得到的是 QueryResult Pydantic 对象；FastAPI 再按 response model 序列化。到此停止，不追前端消费。

---

## 3. QueryResult Full Contract

### 3.1 当前真实定义

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

完整字段数是 21。`interpretation` 自身还有 5 个子字段；`clarification` 自身还有 parameter/question/reason/options。

### 3.2 类型与主要赋值点概览

| QueryResult field | 类型 | 主要赋值位置 | 直接来源 | 主分类 |
|---|---|---|---|---|
| `task_id` | `str` | 各 ResultBuilder；Service exception | Service 生成的 task id | Workflow metadata |
| `status` | 三值 Literal | 各 builder | path、execution success、LLM valid | Mixed |
| `route` | 三值 Literal | 各 builder | 已选 Workflow branch 的固定值 | Workflow metadata / Mixed influence |
| `message` | `str` | 各 builder | 固定文案或 LLM-valid 分支 | Display-oriented / Mixed |
| `interpretation` | `Interpretation?` | `completed()` | heuristic + schema + extraction + literal | Mixed / Display-oriented |
| `clarification` | `Clarification?` | `waiting()` | state clarification | LLM-generated + control |
| `steps` | `list[str]` | 各 builder | 固定模板 + state count/value | Deterministic workflow/display |
| `sql` | `str?` | `completed()/failed()` | SqlExecution.sql | DB execution provenance |
| `columns` | `list[str]` | `completed()` | SqlExecution.columns | DB-originated metadata |
| `rows` | `list[dict]` | `completed()` | normalized SqlExecution.rows | DB-originated, transformed |
| `analysis` | `str?` | all paths | LLM text、DB error 或 deterministic waiting/fallback | Mixed / Display-oriented |
| `saved` | `bool` | model default；Service save | False default，save_memory 后 True | Workflow/storage metadata |
| `route_reason` | `str?` | builders | preprocessor intent.reason 或 fallback | LLM-generated/influenced workflow metadata |
| `retrieval` | `dict?` | waiting/completed/failed | state retrieval 的公开投影 | Schema metadata + Diagnostic |
| `execution_log` | `list[dict]` | direct/completed/failed | Workflow/MCP stage log | Diagnostic |
| `tool_calls` | `list[dict]` | completed | Workflow 构造的 call summary | Diagnostic/audit |
| `result_title` | `str?` | completed/qa | LLM title 或固定/fallback | Display-oriented / LLM-generated |
| `analysis_sources` | `list[dict]` | qa/completed | SessionContext 生成的历史表来源摘要 | Context provenance |
| `standalone_query` | `str?` | waiting/completed/failed | preprocessor LLM output/原 query fallback | LLM-influenced workflow metadata |
| `schema_graph` | `dict?` | waiting/completed/failed | SchemaGraphBuilder output in state | Schema/business metadata |
| `workflow_mode` | `str?` | all paths | branch/program fixed mode | Workflow/control metadata |

后面的第 9 节会按所有 route 和子字段给出完整 provenance，而不是只看 success path。

### 3.3 QueryResult 不只有 database-query 生产路径

除 `completed()/failed()`，当前 `ResultBuilder` 还有：

- `qa()`：`result_builder.py:L13-L33`；
- `direct_response()`：`L35-L56`；
- `waiting()`：`L58-L81`。

此外，`AskDataService.submit()` 捕获 `PipelineStageError` 时会绕过 ResultBuilder，直接构造失败 QueryResult：`backend/app/services/askdata_service.py:L94-L105`。

因此同一个字段可能按 route 具有不同 provenance；例如 `analysis` 在 database success 是 LLM result explanation，在 database failure 是 execution.error，在 data_qa 是 LLM answer，在 waiting 是确定性拼接的澄清文案。

---

## 4. ResultBuilder.completed() Deep Dive

### 4.1 函数签名和输入角色

证据：

`backend/app/workflows/result_builder.py:L84-L91`

```python
def completed(
    state: dict[str, Any],
    executions: list[SqlExecution],
    combined: SqlExecution,
    final: dict[str, Any],
    tool_calls: list[dict[str, Any]],
    execution_log: list[dict[str, Any]],
) -> QueryResult:
```

`executions` 当前未被函数体读取；真正用于结果数据的是 `combined`。single-database caller 将同一 execution 同时传成 `[execution]` 和 `execution`。

### 4.2 从 SchemaGraph / SCHEMA 计算 table labels

结论：table interpretation 是 schema context 的确定性 lookup，不是 DB cursor fact。

证据：

`backend/app/workflows/result_builder.py:L92-L94`

```python
graph = state.get("schema_graph") or {}
table_ids = [item["id"] for item in graph.get("tables", [])]
table_labels = [item["label"] for item in SCHEMA if item["id"] in table_ids]
```

数据流：

```text
state.schema_graph.tables[*].id
        ↓
table_ids
        ↓ 在静态 SCHEMA 中匹配 id
table_labels
```

这段代码没有解析 `combined.sql` 来确认实际 `FROM/JOIN`，也没有为每个 `combined.columns` 建立 source field mapping。因此 table labels 表示 schema graph 涉及的表，不是严格 query-result lineage。

### 4.3 metric heuristic

结论：metric 仅由输出列名 substring 决定。

证据：

`backend/app/workflows/result_builder.py:L95-L98`

```python
metric_columns = [
    column for column in combined.columns
    if any(term in column for term in ("额", "数", "率", "平均", "目标"))
]
```

输入：`combined.columns: list[str]`。  
规则：列名包含五个中文 term 中任意一个。  
输出：`metric_columns`。

它不读取：row values、DuckDB dtype、SCHEMA field role/aggregation、SQL aggregate expression。

可能误判：

- `订单编号` 含“号”但不含当前 term，会归为 dimension；
- `用户数` 命中“数”，即使是已分组 label 或并非可加指标也归为 metric；
- 英文 alias `revenue`/`count` 不命中，会归为 dimension；
- `利率说明` 含“率”，即使是文本说明也归为 metric；
- 一个实际 numeric metric 若列名只是 `value`，会归为 dimension。

这些是规则可能性分析；某次具体是否误判，运行时才能确认。

### 4.4 dimension heuristic

结论：dimension 是 metric 集合的补集，不是独立识别。

证据：

`backend/app/workflows/result_builder.py:L99`

```python
dimension_columns = [column for column in combined.columns if column not in metric_columns]
```

因此任何未命中 metric 关键词的列都会被当 dimension，包括可能的 identifier、时间、自由文本、英文 metric 或未知表达式。这是 heuristic output，不能当作 schema business fact。

### 4.5 workflow mode 和 steps

结论：`mode/steps` 是确定性的 workflow/display metadata。

证据：

`backend/app/workflows/result_builder.py:L100-L110`

```python
mode = str(state.get("workflow_mode") or "single_database_agent")
steps = [
    "一次预处理：上下文聚合、问答/问数路由、检索词提取",
    *([f"独立查询改写：{state.get('standalone_query')}"] if state.get("rewritten") else []),
    "BM25与Dense召回，经RRF融合和Rerank阈值筛选",
    f"构建Schema图：{len(graph.get('tables', []))}张表 / {len(graph.get('fields', []))}个字段",
    "单库智能体选择MCP工具并生成SQL" if mode == "single_database_agent" else "多库路径：按数据库生成Handoff",
    "通过MCP数据库工具调用DuckDB并整理结果",
]
if state.get("analysis_sources"):
    steps.append(f"综合分析{len(state['analysis_sources'])}张用户指定历史表")
```

固定文案、条件分支、`len()` 和格式化均是 deterministic program-derived。虽然其中插入的 standalone query、graph count、analysis source count 源自其他层，steps 本身是“系统如何执行”的说明，不是业务 answer。

### 4.6 构造 Interpretation

证据：

`backend/app/workflows/result_builder.py:L111-L124`

```python
interpretation=Interpretation(
    metric="、".join(metric_columns) or "查询结果指标",
    dimension="、".join(dimension_columns) or "无分组维度",
    time_range="、".join(
        (state.get("extraction") or {}).get("time_expressions") or []
    ) or "未指定",
    table="、".join(table_labels) or "Schema召回数据表",
    assumptions=["Schema字段经过Rerank阈值筛选", "用户拖入字段为确定性约束"],
)
```

这里混合了四种来源：

- metric/dimension：column-name heuristic；
- time_range：LLM preprocessor extraction，经 deterministic join；
- table：schema graph + static SCHEMA，经 deterministic lookup/join；
- assumptions：固定 literal display text。

### 4.7 构造 QueryResult 的逐字段来源

证据：

`backend/app/workflows/result_builder.py:L111-L139`

```python
return QueryResult(
    task_id=state["task_id"],
    status="completed" if final.get("valid", True) else "failed",
    route="database_query",
    message="查询完成" if final.get("valid", True) else "结果校验未通过",
    interpretation=Interpretation(...),
    steps=steps,
    sql=combined.sql,
    columns=combined.columns,
    rows=combined.rows,
    analysis=final.get("analysis"),
    route_reason=str(state.get("intent", {}).get("reason") or "问数"),
    retrieval=ResultBuilder.public_retrieval(state.get("retrieval") or {}),
    execution_log=execution_log,
    tool_calls=tool_calls,
    result_title=final.get("title") or "查询结果",
    analysis_sources=state.get("analysis_sources") or [],
    standalone_query=state.get("standalone_query"),
    schema_graph=graph,
    workflow_mode=mode,
)
```

分类：

- DB-originated/execution：`sql/columns/rows`；
- LLM-influenced mixed：`status/message` 读取 `final.valid`；
- LLM-generated display：`analysis/result_title`；
- LLM-generated workflow explanation：`route_reason` 通常来自 preprocessor reason；
- schema context：`retrieval/schema_graph`；
- diagnostic：`execution_log/tool_calls`；
- workflow context：`task_id/standalone_query/workflow_mode`；
- deterministic display/inference：`steps/interpretation` 的程序部分。

### 4.8 `public_retrieval()` 是确定性投影

结论：QueryResult.retrieval 不是 state retrieval 的无条件完整复制，而是固定 key allowlist 的公开投影。

证据：

`backend/app/workflows/result_builder.py:L158-L166`

```python
visible = {
    "query", "retrieval_terms", "extraction", "embedding_source",
    "rerank_source", "threshold", "bm25_count", "dense_count", "rrf_count",
    "candidate_count", "selected_count", "hits", "table_candidates",
    "low_confidence_candidates", "schema_graph",
}
return {key: value for key, value in retrieval.items() if key in visible}
```

这属于 deterministic projection + schema/retrieval metadata。它不是 DB query result，也不是 ResultBuilder 新推断的业务事实。

### 4.9 `final.reason` 当前没有进入 QueryResult

ResponseGenerator 返回 `reason`，exception fallback 也构造 `reason`，但 `ResultBuilder.completed()` 没有读取它。搜索 completed body 可见只读取：

```text
final.valid
final.analysis
final.title
```

所以 `reason` 的 provenance 到 `final` 为止；当前 QueryResult contract 中没有 result-validation reason 字段，也没有把它放进 log。

---

## 5. ResultBuilder.failed() Deep Dive

### 5.1 完整函数

证据：

`backend/app/workflows/result_builder.py:L141-L156`

```python
@staticmethod
def failed(
    state: dict[str, Any],
    execution: SqlExecution,
    log: list[dict[str, Any]],
) -> QueryResult:
    return QueryResult(
        task_id=state["task_id"],
        status="failed",
        route="database_query",
        message="SQL生成或执行失败",
        analysis=execution.error,
        sql=execution.sql or None,
        route_reason=str(state.get("intent", {}).get("reason") or "问数"),
        retrieval=ResultBuilder.public_retrieval(state.get("retrieval") or {}),
        execution_log=log,
        standalone_query=state.get("standalone_query"),
        schema_graph=state.get("schema_graph"),
        workflow_mode=str(state.get("workflow_mode") or "single_database_agent"),
    )
```

### 5.2 直接保留与语义转换

| QueryResult field | 来源 | 分类 |
|---|---|---|
| `sql` | `execution.sql or None` | DB execution provenance / attempted SQL |
| `analysis` | `execution.error` | DB/program execution error 被放入 display-oriented analysis |
| `status` | 固定 `failed` | deterministic control state |
| `route` | 固定 `database_query` | workflow metadata |
| `message` | 固定中文文案 | display-oriented deterministic |
| `route_reason` | state intent reason | LLM-influenced workflow metadata |
| `retrieval/schema_graph` | state context | schema metadata/diagnostic |
| `execution_log` | caller log | diagnostic |
| `standalone_query/workflow_mode/task_id` | state | workflow/control metadata |

### 5.3 没有进入失败 QueryResult 的 execution 字段

`failed()` 不赋值：

- `columns`；
- `rows`；
- `tool_calls`；
- `interpretation`；
- `result_title`；
- `analysis_sources`。

它们使用 QueryResult 默认值。当前 DuckDbEngine 失败结果本来也通常是 empty columns/rows；但从函数 Contract 看，即便传入一个 `success=False` 且带 rows 的 SqlExecution，failed() 也不会复制这些 rows。

单库 caller 虽在 LangGraph node update 外层返回 `tool_calls:[call]`，`ResultBuilder.failed()` 创建的 `result` dict 内没有 tool_calls。最终 `_state_result()` 只以 `state["result"]` 构造 QueryResult，因此 failed QueryResult.tool_calls 仍为空；较详细的 MCP result 仍可能嵌套在 `execution_log`。

### 5.4 两类 failure provenance

1. single-database failure：`execution.error` 可来自 SQL validation/DuckDB execution，接近执行事实；
2. multi-database pending：`query_graph.py:L359-L363` 由程序直接构造错误文本，是 workflow capability limitation，不是 DB error。

因此即使同样进入 `QueryResult.analysis`，错误文本来源也可能是 DB execution 或 deterministic workflow failure。

---

## 6. Interpretation Provenance Audit

### 6.1 Contract

证据：

`backend/app/models.py:L54-L59`

```python
class Interpretation(BaseModel):
    metric: str
    dimension: str
    time_range: str
    table: str
    assumptions: list[str] = []
```

Interpretation 不是 DuckDbEngine 或 MCP 返回对象；只有 `ResultBuilder.completed()` 为成功 database-query path 构造它。

### 6.2 逐字段 provenance

| Interpretation field | Immediate source | Original source | DB fact? | Heuristic? | LLM? | 可靠性边界 |
|---|---|---|---:|---:|---:|---|
| `metric` | `"、".join(metric_columns)` | `combined.columns` | 否 | **是**：列名包含“额/数/率/平均/目标” | 否 | 只能当输出列名 heuristic，不是 dtype/schema role |
| `dimension` | metric 补集 join | `combined.columns` | 否 | **是**：未命中 metric 的全部列 | 否 | 会把英文 metric、identifier、time 等都可能归为 dimension |
| `time_range` | join `extraction.time_expressions` | RequestPreprocessor 的 LLM JSON，经 `_parse()` 清洗 | 否 | ResultBuilder 内不是 heuristic | **是，间接** | 表示 query semantic extraction，不证明 SQL 实际时间 predicate |
| `table` | join `table_labels` | schema_graph table ids + static SCHEMA labels | 否 | ResultBuilder 内不是 heuristic | 否（但 graph 上游受 retrieval 影响） | 表示相关/连接 schema tables，不是 output lineage |
| `assumptions` | 固定 literal list | ResultBuilder 源码 | 否 | 否 | 否 | deterministic display claim；不是逐请求验证所得事实 |

证据：`backend/app/workflows/result_builder.py:L92-L123`。

### 6.3 `metric` 和 `dimension` 能否作为未来 Derive 的可靠业务事实

结论：**不能作为可靠业务事实；只能作为当前 UI/解释层的启发式标签。**

原因有源码证据：

1. 输入只有 `combined.columns`，没有 physical dtype；
2. 没有读取 `state.schema_graph.fields[*].role`；
3. 没有解析 SQL expression/aggregation；
4. dimension 只是“不属于 metric_columns”的剩余集合；
5. 输出为一个用“、”拼接的 display string，不是 column-id keyed mapping。

即使结果恰好是：

```text
metric="销售额"
dimension="销售地区"
```

也只能说明当前 alias 命中了名称规则，不能证明该列已与 schema 中 `paid_amount(role=metric)`、`region(role=dimension)` 建立确定映射。

### 6.4 `time_range` 不等于执行事实

RequestPreprocessor 要求 LLM 输出 `retrieval.time_expressions`：

`backend/app/preprocessing.py:L73-L86`

```json
{
  "retrieval": {
    "time_expressions": []
  }
}
```

其 `_parse()` 将该 list 规范化：

`backend/app/preprocessing.py:L140-L156`

```python
retrieval = RetrievalIntent(
    ...
    time_expressions=self._strings(raw.get("time_expressions")),
    ...
)
```

ResultBuilder 只 join 该值，不将它与 `combined.sql` 的 WHERE predicate 或返回数据核对。因此它是 query interpretation，不是数据库对实际过滤范围的证明。

### 6.5 `table` 不等于 output lineage

`SchemaGraphBuilder.build()` 的 fields/tables 来自 retrieval hits 和 join path：

`backend/app/retrieval/graph.py:L37-L55, L78-L87`

```python
selected_tables = set(hit["table_id"] for hit in hits)
...
fields[hit["doc_id"]] = {
    "table_id": hit["table_id"],
    "name": hit["field_name"],
    "role": hit.get("field_role", ""),
    ...
}

tables = [
    {
        "id": table_id,
        "label": self.tables[table_id]["label"],
        ...
    }
    for table_id in sorted(graph_tables)
]
```

ResultBuilder 的 `table` 只把这些 table ids 映射成 label。它不验证 SQL 最终实际引用了 graph 中全部表，也不记录每个 output alias 源自哪个 field。

### 6.6 `assumptions` 的实际性质

当前固定值是：

```python
assumptions=[
    "Schema字段经过Rerank阈值筛选",
    "用户拖入字段为确定性约束",
]
```

两条对所有 completed result 都写入，没有按本次是否真的存在 dragged fields 做条件判断。因此它属于 deterministic presentation text，而不是本次数据库结果或逐请求核验事实。

---

## 7. ResponseGenerator / LLM Boundary

### 7.1 谁调用、传入什么

结论：ResultBuilder 不调用 ResponseGenerator；`QueryWorkflow._execute_single_database()` 在确认 `execution.success` 后先调用它。

证据：

`backend/app/workflows/query_graph.py:L337-L344`

```python
if not execution.success:
    result = ResultBuilder.failed(state, execution, log)
    ...
try:
    final = self.response_generator.finalize(
        state["standalone_query"],
        execution,
        state["schema_context"],
        state.get("analysis_context", ""),
    )
```

四个输入：

| 参数 | 来源 | 分类 |
|---|---|---|
| `query` | state.standalone_query | LLM-influenced query context |
| `execution` | rebuilt SqlExecution | DB-originated result + execution provenance |
| `schema_context` | SchemaGraphBuilder.context_text output in state | schema/business context |
| `analysis_context` | SessionContext 聚合的用户指定历史表 | historical/user-selected context |

### 7.2 LLM 实际看到的 system/user 内容

证据：

`backend/app/querying/response_generator.py:L34-L50`

```python
system = """你是查询结果整理器。检查结果能否回答问题，并生成简短标题和一到两句说明。
只能使用结果中真实存在的数值。只返回JSON：
{"valid":true,"reason":"...","title":"...","analysis":"..."}。"""
user = (
    f"问题：{query}\nSQL：{execution.sql}\n列：{execution.columns}\n"
    f"结果数据：{execution.rows[: self.table_row_limit]}\nSchema：{schema_context}\n"
    f"用户保存的分析表格：{analysis_context or '无'}"
)
payload = self.model_client.chat_json(system, user)
```

因此答案逐项是：

- 看到 standalone query：是；
- 看到 SQL：是；
- 看到 columns：是；
- 看到 rows：是，但只看 slice；
- 看到 schema_context：是；
- 看到用户指定历史 analysis context：是；
- 看到全部最终 rows：不一定。

### 7.3 LLM 看多少 rows

证据：

`backend/app/querying/response_generator.py:L21-L23, L45-L47`

```python
self.table_row_limit = max(1, (config or settings).context_table_row_limit)
...
execution.rows[: self.table_row_limit]
```

默认值：

`backend/app/config.py:L69`

```python
context_table_row_limit: int = int(os.getenv("CONTEXT_TABLE_ROW_LIMIT", "50"))
```

DuckDbEngine 最多返回 200 rows，而默认 LLM 只看前 50。`ResultBuilder.completed()` 最终仍把完整 `combined.rows` 放进 QueryResult，所以：

```text
QueryResult.rows 可有 200 行
LLM final analysis 默认只基于前 50 行
```

### 7.4 LLM 输出 schema 与程序 normalization

Prompt 要求输出：

```json
{
  "valid": true,
  "reason": "...",
  "title": "...",
  "analysis": "..."
}
```

`ModelClient.chat_json()` 只负责将模型文本清理 fence 并解析 JSON：

`backend/app/model_client.py:L41-L53`

```python
raw = self.chat(system, user)
cleaned = re.sub(...)
try:
    return json.loads(cleaned)
except json.JSONDecodeError:
    match = re.search(r"\{[\s\S]*\}", cleaned)
    ...
```

ResponseGenerator 再做字段转换/default：

`backend/app/querying/response_generator.py:L49-L56`

```python
payload = self.model_client.chat_json(system, user)
return {
    "valid": bool(payload.get("valid", True)),
    "reason": str(payload.get("reason") or "结果检查通过"),
    "title": str(payload.get("title") or "查询结果"),
    "analysis": str(payload.get("analysis") or f"查询返回{len(execution.rows)}行。"),
}
```

这不是 Pydantic output model，也没有独立验证 analysis 中的数值是否真的出现在 rows。现有 program validation/normalization 只有：

- 响应必须可解析为 JSON object，失败会 RuntimeError；
- `valid` 用 `bool(...)` 转换；
- 其余三项用 `str(...)`；
- missing/empty 使用默认值。

所以准确表述是：**LLM-generated but JSON-parsed and program-normalized/defaulted**，不是“由程序独立验证为业务正确”。

### 7.5 `valid`、`analysis`、`title`、`reason` 分别如何进入 QueryResult

| final field | 生产方式 | ResultBuilder 使用方式 | QueryResult 影响 |
|---|---|---|---|
| `valid` | LLM 输出，`bool()` normalization，缺失默认 True | completed 中读取两次 | 决定 `status` 和 `message` |
| `analysis` | LLM 文本；缺失时程序生成“查询返回N行” | `final.get("analysis")` | 直接进入 `QueryResult.analysis` |
| `title` | LLM 文本；缺失默认“查询结果” | `final.get("title") or "查询结果"` | 进入 `result_title` |
| `reason` | LLM 文本；缺失默认“结果检查通过” | **没有读取** | 不进入 QueryResult |

### 7.6 LLM 是否看到并验证全部事实

不是。源码只能确认 Prompt 指示“只能使用结果中真实存在的数值”，但：

- 默认只给前 50 rows；
- 不给 column dtype；
- 不给 truncated/total count；
- `valid` 是模型判断；
- 没有第二段 Python 代码逐项核对 analysis 数值；
- ResultBuilder 直接接受 normalized `analysis/title/valid`。

因此 `analysis/title/valid` 不应被分类为 DB fact。

### 7.7 LLM 调用失败时的 fallback

ResponseGenerator 将 RuntimeError 包成 PipelineStageError：

`backend/app/querying/response_generator.py:L57-L58`

```python
except RuntimeError as exc:
    raise PipelineStageError("result_analysis", str(exc)) from exc
```

Workflow 捕获后：

`backend/app/workflows/query_graph.py:L345-L353`

```python
log.append({"stage": exc.stage, "success": False, "error": exc.message})
final = {
    "valid": True,
    "reason": f"{exc.stage}失败",
    "title": "查询结果（文字说明生成失败）",
    "analysis": f"SQL已成功执行，但{exc.stage}失败：{exc.message}",
}
```

这时：

- DB rows 仍保留；
- final.valid 被程序固定 True；
- title/analysis 是 deterministic fallback text，不是 LLM 输出；
- result-analysis failure 记录进 execution_log。

### 7.8 其他 route 中的 LLM content

- `data_qa`：`QueryWorkflow._answer_qa()` 调 `ResponseGenerator.answer_qa()`，其 LLM answer 传给 `ResultBuilder.qa()`，进入 `QueryResult.analysis`（`query_graph.py:L174-L188`；`result_builder.py:L13-L33`）。
- `direct_response`：RequestPreprocessor 的 LLM `response` 进入 `state.direct_response`，再由 `ResultBuilder.direct_response()` 放入 `analysis`（`preprocessing.py:L125-L138`；`query_graph.py:L161-L171`；`result_builder.py:L35-L56`）。
- 模型不可用 direct fallback：preprocessor 程序生成固定 unavailable response，仍进入 analysis（`preprocessing.py:L95-L107`）。

所以 QueryResult.analysis 的 provenance 必须按 route 判断，不能统一写成“查询结果分析”。

---

## 8. Schema / Workflow Context Sources

### 8.1 `SCHEMA` 提供什么

结论：静态 Schema field metadata 包括 name、label、type、description、aliases、role、aggregation；它不是当前 SQL cursor metadata。

证据：

`backend/app/database.py:L9-L26`

```python
def _field(..., role: str, aggregation: str = "none") -> dict:
    return {
        "name": name,
        "label": label,
        "type": field_type,
        "description": description,
        "aliases": aliases,
        "role": role,
        "aggregation": aggregation,
    }
```

QueryResult 中直接从 `SCHEMA` lookup 的 completed-field 是 `interpretation.table` 使用的 table label。QueryResult.schema_graph 里也有从 SCHEMA/relations 补充的字段与表 metadata。

### 8.2 `schema_graph` 来源

结论：schema_graph 来自 retrieval hits 经 `SchemaGraphBuilder.build()` 构建，包含相关字段、表和 join relation context。

证据：

`backend/app/workflows/query_graph.py:L193-L230`

```python
retrieval = self.schema_index.retrieve(...)
retrieval = self.schema_index.include_workspace(...)
retrieval["extraction"] = extraction
schema_graph = self.graph_builder.build(
    retrieval["hits"],
    state.get("access_scope"),
)
retrieval["schema_graph"] = schema_graph
return {
    "retrieval": retrieval,
    "schema_graph": schema_graph,
    "schema_context": self.graph_builder.context_text(schema_graph),
    ...
}
```

它是 Schema/business metadata + retrieval-derived context，不是 SQL result cursor 的 provenance。当前没有代码将 `combined.columns` 逐个映射到 `schema_graph.fields`。

### 8.3 `retrieval` 来源与公开过滤

`state.retrieval` 来自 SchemaIndex retrieve/include workspace，并附加 extraction/schema_graph。ResultBuilder 的 `public_retrieval()` 仅输出 allowlist keys（`result_builder.py:L158-L166`）。

所以 QueryResult.retrieval 是：

```text
schema retrieval outcome
+ scores/counts/hits/table candidates
+ extraction/schema graph context
→ deterministic public-key projection
```

它不是 DB row data，也不是当前 SQL output provenance mapping。

### 8.4 intent、route_reason、standalone_query、extraction

结论：它们通常源自 RequestPreprocessor 的一次 LLM JSON，然后经确定性 parse/normalization 写入 state。

证据：

`backend/app/preprocessing.py:L59-L110`

```python
payload = self.model_client.chat_json(system, user)
return self._parse(payload, query)
```

`backend/app/workflows/query_graph.py:L132-L159`

```python
decision = self.preprocessor.prepare(state["query"], state.get("route_context", ""))
return {
    "intent": {
        "action": decision.action,
        "confidence": decision.confidence,
        "reason": decision.reason,
        ...
    },
    "standalone_query": decision.standalone_query,
    "rewritten": decision.rewritten,
    "extraction": decision.retrieval.public(),
    ...
}
```

异常时 preprocessor 使用 deterministic conservative fallback，因此这些字段应标 LLM-generated/influenced or fallback，而不是 DB fact。

### 8.5 task_id

结论：由 Service 程序生成，是 workflow correlation metadata。

证据：

`backend/app/services/askdata_service.py:L72-L92`

```python
task_id = uuid.uuid4().hex[:12]
...
result = self.workflow.invoke(self._payload(task_id, ...), task_id)
```

它标识一次 task，不描述业务数据。

### 8.6 analysis_sources

结论：来自用户 workspace 选定的历史分析表或本 session 已完成 QueryResult 的来源摘要；它不是当前 query 的 DB rows。

证据：

`backend/app/services/session_context.py:L215-L260`

`source` 结构包含：

```python
{
    "task_id": task_id,
    "title": ...,
    "query": ...,
    "row_count": ...,
    "columns": ...,
}
```

传入初始 state 的位置：

`backend/app/services/askdata_service.py:L278-L301`

```python
analysis_context, analysis_sources = self.context.analysis_context(session_id, workspace)
return {
    ...
    "analysis_context": analysis_context,
    "analysis_sources": analysis_sources,
    ...
}
```

`analysis_context` 可包含历史 rows 的有限 slice，给 LLM 使用；`analysis_sources` 保存的是来源摘要。其分类是 historical context provenance，不是 current SQL DB fact。

### 8.7 execution_log 与 tool_calls

结论：由 Workflow 确定性构造，主要用于诊断/审计执行过程。

证据：

`backend/app/workflows/query_graph.py:L303-L335`

- `execution_log`：把 Agent/MCP trace 展开为 `stage="mcp_tool_call"` entries，再追加 `execute_duckdb` entry；
- `tool_calls`：构造 database、tool_name、transport、schema graph version、SQL source、SQL、success、returned row count、error 的摘要。

这些 nested dict 可能比顶层 QueryResult 保存更多执行细节，例如 database、success、error、row_count 和原 MCP result。它们仍是 diagnostic contract，而不是 canonical business rows。

### 8.8 route / workflow_mode / steps

- `route`：builder 按已走到的分支写固定 literal；最初分支受 preprocessor LLM action 影响，所以是 program-assigned but LLM-influenced control metadata。
- `workflow_mode`：各路径写 `single_database_agent/qa/direct_response/route_fallback/multi_database_pending/...`，描述执行模式。
- `steps`：ResultBuilder 根据固定模板和 state 条件组装，描述处理过程。

三者都是 Workflow/control 或 display metadata，不是用户业务数据事实。

### 8.9 `saved`

结论：ResultBuilder 不显式赋值，QueryResult 默认 False；保存记忆成功后 Service 原地改为 True。

证据：

- `backend/app/models.py:L74`：`saved: bool = False`；
- `backend/app/services/askdata_service.py:L196-L213`：保存 result 后 `result.saved = True`。

它表示应用存储状态，不是 SQL execution fact。

### 8.10 Display-oriented 字段的消费边界

从构造看，`message/result_title/analysis/interpretation/steps` 都面向可读响应。已检查的后端代码还确认：

- `AskDataService` 归档 assistant message 时使用 `result.analysis or result.message`（`askdata_service.py:L106-L119`）；
- `save_memory()` 使用 analysis/message、result_title、columns、rows（`L196-L213`）。

这说明 display 文本会参与归档/记忆描述，但仍不因此变成 DB fact。本报告按要求停在 QueryResult/API 边界，没有检查前端组件，因此其准确表述是：

> presentation-oriented by construction; frontend usage not confirmed from inspected files.

---

## 9. QueryResult Field Provenance Table

### 9.1 阅读说明

- `DB Fact? = yes(normalized)` 表示值源于数据库，但已发生明确表示转换，不是 raw cursor representation。
- `LLM? = influenced` 表示该字段由程序赋值，但其分支或源值受模型输出影响。
- `Canonical / Diagnostic` 一列描述当前对象中的角色，不是在提出未来 Contract 设计。
- 同一字段跨 route 来源不同的，Category 标 `Mixed` 并在 Original Source 中展开。

### 9.2 21 个顶层字段

| Field | Immediate Producer | Original Source | Category | DB Fact? | LLM? | Heuristic? | Canonical or Diagnostic |
|---|---|---|---|---:|---:|---:|---|
| `task_id` | ResultBuilder 各方法；Service exception path | `AskDataService.submit()` 的 `uuid.uuid4().hex[:12]` | Workflow metadata | No | No | No | Control/correlation identity |
| `status` | ResultBuilder / Service | DB success gate、LLM `final.valid`、route 固定状态、exception path | **Mixed** | Influenced, not a DB field | **Yes on completed path** | No | Canonical API control status |
| `route` | ResultBuilder / Service | 走到的 Workflow branch；branch 最初受 preprocessor LLM action 影响 | Workflow metadata / Mixed | No | Influenced | No | Canonical routing/control metadata |
| `message` | ResultBuilder / Service | 固定文案；completed 时由 `final.valid` 选择 | Display-oriented / Mixed | No | Influenced on completed/direct | No | Presentation/control text |
| `interpretation` | `ResultBuilder.completed()` | columns heuristic + extraction + schema graph/SCHEMA + literals | **Mixed** | No | Partly (`time_range`) | **Yes** | Presentation-oriented semantic summary |
| `clarification` | `ResultBuilder.waiting()` | `state.clarification`，当前可由 SingleDatabaseAgent LLM decision 产生 | LLM-generated + Workflow control | No | **Yes** | No | Control + presentation; Pydantic structured |
| `steps` | ResultBuilder | 固定模板、state 条件、`len()`、可能嵌入 standalone query | Deterministic derived / Workflow metadata | No | Value may embed LLM query | No | Presentation + execution narrative |
| `sql` | `completed()/failed()` | rebuilt `SqlExecution.sql`；原 SQL 通常由 Agent LLM 生成并经 validator/DB 执行 | Execution provenance / Mixed | Execution fact, not DB-returned data | **Origin often LLM** | No | Canonical query provenance |
| `columns` | `completed()` | DuckDB cursor description names，经 SqlExecution/MCP/Workflow | DB-originated metadata | **Yes** | SQL alias may be model-authored | No | Canonical result data |
| `rows` | `completed()` | DuckDB rows 经最多 200 行截取、tuple→dict、date/Decimal normalization | DB-originated, transformed | **Yes (normalized)** | No | No | Canonical result data |
| `analysis` | ResultBuilder / Service | DB success: LLM final；failure: execution.error；QA/direct: LLM；waiting/fallback: program text | **Mixed / Display-oriented** | Not as a field; may quote facts/errors | **Usually** | No | Presentation text; not canonical DB fact |
| `saved` | QueryResult default；`AskDataService.save_memory()` | default False，保存成功后程序设 True | Workflow/storage metadata | No | No | No | Control/UI state |
| `route_reason` | ResultBuilder / Service | `state.intent.reason`，通常是 preprocessor LLM 文本；fallback 时程序文本 | LLM-generated/influenced Workflow metadata | No | **Usually** | No | Explanatory/diagnostic routing metadata |
| `retrieval` | `waiting()/completed()/failed()` | state retrieval 经 `public_retrieval()` allowlist 投影 | Schema metadata + Diagnostic | No | Indirect via extraction/model services | No ResultBuilder heuristic | Context/diagnostic, not current DB data |
| `execution_log` | ResultBuilder 接收 caller log | Workflow stage entries、MCP trace、errors | Diagnostic | Contains nested execution facts | May contain LLM reason/output traces | No | Diagnostic/audit; untyped nested dicts |
| `tool_calls` | `completed()` | `_execute_single_database()` 构造的 call summary | Diagnostic / Deterministic derived | Contains execution facts | Contains model-selected tool/SQL source | No | Diagnostic/audit; failure result defaults empty |
| `result_title` | `completed()/qa()` | DB completed 通常为 LLM final.title；fallback/QA 为程序默认 | LLM-generated / Display-oriented | No | **Usually on DB completed** | No | Presentation label |
| `analysis_sources` | `qa()/completed()` | SessionContext 从 workspace/历史 task 生成来源摘要 | Workflow context provenance | Not current DB fact | Indirect prior titles possible | No | Context provenance / diagnostic |
| `standalone_query` | `waiting()/completed()/failed()` | RequestPreprocessor LLM output；missing 时可用原 query | LLM-generated/influenced Workflow metadata | No | **Usually** | No | Query context / trace |
| `schema_graph` | `waiting()/completed()/failed()` | retrieval hits 经 SchemaGraphBuilder + static SCHEMA/RELATIONS | Schema/business metadata | No | Indirect retrieval terms | No ResultBuilder heuristic | Context; not output-column lineage |
| `workflow_mode` | ResultBuilder/Workflow | 当前 branch/mode 的程序 literal 或 state 值 | Workflow/control metadata | No | Indirect route influence | No | Diagnostic/control |

### 9.3 Interpretation 子字段

| Field | Immediate Producer | Original Source | Category | DB Fact? | LLM? | Heuristic? | Contract role |
|---|---|---|---|---:|---:|---:|---|
| `interpretation.metric` | ResultBuilder | `combined.columns` 中包含指定中文 term 的名称 | **Heuristic** | No | No | **Yes** | Presentation inference |
| `interpretation.dimension` | ResultBuilder | `combined.columns - metric_columns` | **Heuristic** | No | No | **Yes** | Presentation inference |
| `interpretation.time_range` | ResultBuilder | preprocessor LLM `extraction.time_expressions` + join/default | **Mixed: LLM-generated + deterministic formatting** | No | **Yes** | No in ResultBuilder | Presentation/query interpretation |
| `interpretation.table` | ResultBuilder | schema_graph table ids → static SCHEMA labels + join/default | **Schema metadata + deterministic derived** | No | No direct | No in ResultBuilder | Presentation/schema context |
| `interpretation.assumptions` | ResultBuilder | 两个固定 literal | Deterministic display text | No | No | No | Presentation claim, not validated fact |

### 9.4 Clarification 子结构

Contract 证据：`backend/app/models.py:L40-L51`。

| Field | Immediate Producer | Original Source | Category | Validation |
|---|---|---|---|---|
| `clarification.parameter` | `ResultBuilder.waiting()` → Pydantic | Agent LLM decision payload；缺失默认 `other` | LLM-generated + deterministic default | `str(...)` + Pydantic field type |
| `clarification.question` | 同上 | Agent LLM | LLM-generated presentation/control | required by Pydantic；builder 有默认文本 |
| `clarification.reason` | 同上 | Agent LLM | LLM-generated explanation | required by Pydantic；builder 有默认文本 |
| `clarification.options` | 同上 | Agent LLM list | LLM-generated structured control | Agent 要求至少 2 项；Pydantic 校验 option model |

Agent validation 证据：`backend/app/querying/single_database_agent.py:L87-L97`。

```python
if action == "clarify":
    clarification = decision.get("clarification")
    if not isinstance(clarification, dict) or len(
        clarification.get("options") or []
    ) < 2:
        raise ValueError("智能体返回的澄清信息不完整")
```

这是“LLM-generated but program shape-validated”；它仍不是 DB fact。

### 9.5 各 route 下 `analysis` 的 provenance

| Route/path | `analysis` 来源 | 分类 |
|---|---|---|
| database query success | `final.analysis` | 通常 LLM-generated；missing 时 deterministic row-count text |
| result-analysis LLM failure | Workflow fallback text | Deterministic display/error text |
| database execution failure | `execution.error` | Execution diagnostic 被重用为 display analysis |
| multi-database pending | 程序构造的 capability error | Workflow diagnostic/display |
| data_qa | `ResponseGenerator.answer_qa()` | LLM-generated answer |
| direct_response | RequestPreprocessor `response` | LLM-generated；model unavailable 时 deterministic fallback |
| waiting clarification | question + option labels 拼接 | Deterministic formatting of LLM structured clarification |
| Service catches PipelineStageError | `exc.message` | Pipeline diagnostic/display |

所以只看字段名 `analysis` 无法判断其可靠性；必须同时读取 route/status/workflow_mode 和生产路径。

---

## 10. DB Fact vs Derived vs Heuristic vs LLM Table

### 10.1 分类总表

| Provenance class | 当前 QueryResult 中的代表 | 产生机制 | 能否当 current DB fact |
|---|---|---|---:|
| DB-originated | `columns`, `rows` | cursor result 经 execution/MCP/Workflow 传递 | columns 是结果 metadata；rows 是 normalized DB-originated data |
| DB execution provenance | `sql`；log/call 中 `success/error/row_count` | 执行输入、控制流和 `len(rows)` | 是执行事实/派生，不是 raw DB row fact |
| Schema metadata | `schema_graph`, `retrieval`, `interpretation.table` | SchemaIndex/GraphBuilder/SCHEMA lookup | 否；是相关 schema context |
| Deterministic derived | `steps`, fixed route/mode/message；tool call row_count；table label join | Python branch/list/join/len/default | 否，除非明确说是从 DB fact 派生 |
| Heuristic | `interpretation.metric`, `interpretation.dimension` | column-name substring + complement | **否，只能当推断** |
| LLM-generated | `analysis`, `result_title`, `route_reason`, `standalone_query`, clarification；final.valid | ModelClient JSON/text output | **否** |
| Workflow metadata | `task_id`, `route`, `status`, `workflow_mode`, `steps`, `saved` | service/workflow control flow | 否 |
| Display-oriented | `message`, `result_title`, `analysis`, `interpretation`, steps | 固定文案、LLM 文本或格式化 | 否 |
| Diagnostic | `execution_log`, `tool_calls`, `retrieval` | stage trace/call summary/检索明细 | 内部可嵌套事实，但字段整体不是业务事实 |
| Mixed | `status`, `message`, `analysis`, `interpretation`, `route` | 多个 provenance 组合 | 必须拆分后判断 |

### 10.2 最接近 DB fact 的三项也有边界

| Field | 为什么接近 DB fact | 仍需保留的限定 |
|---|---|---|
| `columns` | 来自 cursor.description 的 column names | alias 可由 LLM SQL 指定；没有 dtype/lineage |
| `rows` | 来自 DuckDB result values | 最多 200；tuple→dict；date→str；Decimal→float；不是 raw representation |
| `sql` | 成功路径保存实际执行的 safe SQL | SQL 通常由 LLM 生成；它是 execution provenance，不是 DB 返回的业务数据 |

### 10.3 LLM-generated but program-processed 的精确含义

| Value | Program processing | 是否独立业务验证 |
|---|---|---:|
| preprocessor route/reason/query/extraction | action allowlist、float clamp、str/list cleanup、fallback | 否 |
| Agent clarification | action allowlist、dict + 至少 2 options、Pydantic QueryResult models | 否 |
| Response final.valid | JSON parse、`bool()`、default True | 否 |
| Response final.title/analysis/reason | JSON parse、`str()`、default | 否 |
| data_qa/direct response text | 基础非空/route checks 或 exception handling | 否 |

程序 validation 能保证结构/枚举/基本形态，不等价于“内容已与数据库逐项核实”。

### 10.4 heuristic 与 deterministic derived 的区别

```text
len(execution.rows)
→ 同一输入永远同一输出，语义明确为 returned row count
→ deterministic derived

列名包含“额/数/率/平均/目标”
→ 同一输入也确定，但规则是在猜业务角色
→ heuristic inference
```

“代码执行是确定性的”不代表输出就是 deterministic fact。Heuristic 也可由确定性代码实现，区别在于它是否用近似规则推断未知业务语义。

---

## 11. Canonical vs Diagnostic vs Presentation Fields

### 11.1 当前对象中的职责分区

| 角色 | 字段 | 当前含义 |
|---|---|---|
| Canonical result data | `sql`, `columns`, `rows` | 当前查询执行与返回表格；rows 已 normalized/limited |
| Canonical API control | `task_id`, `status`, `route`, `clarification`, `saved` | task 生命周期、路由、交互和保存状态 |
| Schema/context payload | `retrieval`, `schema_graph`, `analysis_sources`, `standalone_query` | 查询如何被理解、用了哪些 schema/历史 context |
| Diagnostic/audit | `execution_log`, `tool_calls`, `route_reason`, `workflow_mode` | Agent/Workflow/MCP 如何运行、为何路由、调用摘要 |
| Presentation | `message`, `result_title`, `analysis`, `interpretation`, `steps` | 人类可读标题、说明、语义摘要和过程说明 |

这些角色并非物理上分成不同对象，而是当前同一个 QueryResult 中的逻辑分区；某些字段具有双重用途，例如 steps 既是 presentation 也是 execution narrative。

### 11.2 哪些 nested fields 比顶层保存更多

`QueryResult` 顶层没有：

```text
database
success bool
error field
returned row_count
tool name / transport
```

但成功 database path 的 `tool_calls[*]` 可包含：

```python
{
    "database": database,
    "arguments": {
        "mode": "single_database_agent",
        "transport": "mcp_in_process",
        "tool_name": ...,
        "schema_graph_version": ...,
        "sql_source": ...,
    },
    "sql": execution.sql,
    "success": execution.success,
    "row_count": len(execution.rows),
    "error": execution.error,
}
```

证据：`backend/app/workflows/query_graph.py:L322-L335`。

`execution_log[*]` 的 MCP call entry 还通过 `**item` 保留 Agent trace 的：

```text
tool
arguments
result（完整 MCP structured result dict）
reason
```

证据：`query_graph.py:L303-L311`，原 trace 来自 `single_database_agent.py:L109-L117`。

### 11.3 diagnostic nested data 的 Contract 边界

`execution_log` 和 `tool_calls` 的 QueryResult 类型都是：

```python
list[dict[str, Any]]
```

不像 SqlExecution、Interpretation、Clarification 那样有专门的 nested Pydantic model。当前源码确实把更丰富信息放在其中，但如果未来 Derive 读取它，就是在依赖 diagnostic dict shape，而不是一个专门的 canonical fact type。

这里只描述当前边界：

- 其中某些 value 是可靠执行事实，如某次 call 的 SQL/success/error；
- 某些是派生摘要，如 `row_count=len(rows)`；
- 某些是 LLM content，如 call reason；
- 字段整体用途是诊断/审计，不应整体视为业务结果表。

### 11.4 Presentation 字段是否参与后续逻辑

在 ResultBuilder 之后已检查的后端边界中：

- `analysis or message` 用于归档 assistant message；
- `analysis/message/result_title/columns/rows` 可用于保存 memory；
- `status/clarification` 控制是否可继续澄清/保存。

这说明 presentation/control fields 不是完全“无人消费”。但它们的消费用途仍是交互、归档和记忆，不改变其 provenance：LLM analysis 仍不是 DB fact，heuristic interpretation 仍不是 schema-grounded output lineage。

前端实际渲染和交互没有在本调查范围内检查：

> presentation-oriented by construction; frontend usage not confirmed from inspected files.

---

## 12. ASCII Result Provenance Map

```text
                              DuckDB execution
                                    │
                     backend/app/querying/duckdb_engine.py
                                    │
                  ┌─────────────────┼─────────────────┐
                  │                 │                 │
              safe SQL       column names       normalized rows
          execution provenance  DB metadata     DB-originated data
                  │                 │          (≤200, tuple→dict,
                  │                 │           date→str, Decimal→float)
                  └─────────────────┴─────────────────┘
                                    │
                             SqlExecution
                     {sql,success,columns,rows,error}
                                    │
                       MCP dict → rebuilt SqlExecution
                                    │
             ┌──────────────────────┴──────────────────────┐
             │                                             │
             │                              ResponseGenerator.finalize()
             │                                             │
             │                    ┌────────────────────────┼───────────────┐
             │                    │                        │               │
             │              standalone query         SQL/columns      rows[:N]
             │               LLM-influenced       execution/result   N默认50
             │                    │                        │               │
             │                    ├──── schema_context ────┤               │
             │                    └── analysis_context ────┴───────────────┘
             │                                             │
             │                                             ▼
             │                                       LLM final JSON
             │                           {valid, reason, title, analysis}
             │                            │       │       │       │
             │                            │       └───────┼───────┘
             │                            │ reason丢弃     │
             │                            │                │
             │                            ▼                ▼
             │                     status/message     title/analysis
             │                     LLM-influenced      LLM display
             │
             │
             │        Workflow / Schema context
             │
             │   ┌── state.schema_graph ── static SCHEMA
             │   │       │
             │   │       └→ table ids → labels          deterministic schema lookup
             │   │
             │   ├── state.extraction.time_expressions  preprocessor LLM output
             │   │       └→ join/default                deterministic formatting
             │   │
             │   ├── state.intent.reason                preprocessor LLM/fallback
             │   ├── state.retrieval                    schema retrieval context
             │   ├── state.analysis_sources             historical source summaries
             │   ├── task_id/workflow_mode              workflow control
             │   └── execution_log/tool_calls           diagnostic/audit
             │
             │
             │        ResultBuilder.completed()
             │
             ├── combined.sql/columns/rows ────────────────────────────────┐
             │                                                             │
             ├── column-name substring rule                                │
             │       ├→ contains 额/数/率/平均/目标 → metric               │
             │       └→ all remaining columns          → dimension          │
             │                            heuristic                         │
             │                                                             │
             ├── graph tables + SCHEMA labels → interpretation.table       │
             ├── extracted times → interpretation.time_range               │
             ├── fixed assumptions / steps / route / mode                   │
             └── LLM final valid/title/analysis                             │
                                                                           │
                                    ┌──────────────────────────────────────┘
                                    ▼
                              QueryResult
        ┌───────────────────────────┼──────────────────────────────┐
        │                           │                              │
  Canonical result data       Presentation / inference      Control / diagnostic
  sql / columns / rows        message / title / analysis    task_id / status / route
                              interpretation / steps        mode / route_reason
                                                           retrieval / schema_graph
                                                           logs / calls / sources
```

失败分支不经过 ResponseGenerator：

```text
SqlExecution.success == False
        ↓
ResultBuilder.failed()
        ├── sql → QueryResult.sql
        ├── error → QueryResult.analysis
        ├── fixed status/route/message
        └── state retrieval/schema/log/query/mode
```

---

## 13. Four Core Questions

### Q1. 最终 QueryResult 中哪部分最接近数据库真实事实？

结论：**`columns` 和 `rows` 最接近当前 SQL result；`sql` 最接近真实执行 provenance。**

证据：

`backend/app/workflows/result_builder.py:L125-L129`

```python
sql=combined.sql,
columns=combined.columns,
rows=combined.rows,
```

限定：

- columns 只保留名称，没有 dtype/lineage；
- rows 是 DB-originated，但已经最多 200 行、tuple→dict、date/datetime→str、Decimal→float；
- SQL 是成功执行的语句文本，但通常由 Agent LLM 生成，因此它是 execution fact，不是 DB 返回的业务值。

### Q2. 哪些字段是大模型生成的，不能被当作数据库事实？

主要包括：

- database completed 的 `analysis`、`result_title`；
- `final.valid`，它进一步影响 `status/message`；
- `route_reason`；
- `standalone_query`；
- extraction.time_expressions，进一步进入 `interpretation.time_range`；
- structured `clarification`；
- data_qa 的 `analysis`；
- direct_response 的 `analysis`。

证据链：

- preprocessor LLM：`backend/app/preprocessing.py:L59-L110`；
- Agent clarification LLM：`backend/app/querying/single_database_agent.py:L75-L97`；
- final LLM：`backend/app/querying/response_generator.py:L34-L56`；
- ResultBuilder consumption：`backend/app/workflows/result_builder.py:L111-L138`。

这些值有 JSON parsing、类型转换、枚举/shape checks 或 fallback，但没有被程序逐项证明为 DB fact。

### Q3. 哪些字段由 heuristic 产生，只能当作推断？

结论：当前 ResultBuilder 中明确的业务 heuristic 是：

- `interpretation.metric`；
- `interpretation.dimension`。

证据：

`backend/app/workflows/result_builder.py:L95-L99`

```python
metric_columns = [
    column for column in combined.columns
    if any(term in column for term in ("额", "数", "率", "平均", "目标"))
]
dimension_columns = [column for column in combined.columns if column not in metric_columns]
```

它们只能说明列名规则的分类结果，不能替代 physical dtype、schema role、SQL expression analysis 或 output lineage。

### Q4. 哪些主要是 Workflow / diagnostic / presentation metadata？

Workflow/control：

```text
task_id, status, route, clarification, saved,
route_reason, standalone_query, workflow_mode
```

Diagnostic/context：

```text
execution_log, tool_calls, retrieval,
schema_graph, analysis_sources
```

Presentation：

```text
message, result_title, analysis,
interpretation, steps
```

其中 `retrieval/schema_graph` 还具有真实 schema/business context 价值，execution logs 也可能嵌套 SQL/success/error 等执行事实；分类指的是它们在 QueryResult 中的主要职责，不代表内部所有值都不真实。

---

## 14. Implications for Future Derive

本节只说明未来 Derive 如果读取现有字段，实际读到哪一种 provenance；不提出新字段或实现。

### 14.1 逐输入可靠性边界

| Derive 读取对象 | 实际读取的 provenance | 可当作什么 | 不能当作什么 |
|---|---|---|---|
| `QueryResult.rows` | normalized DB-originated data | 已返回单元格值；当前最多 200 行 | raw cursor values、全量结果、physical dtype、业务 role |
| `Interpretation.metric` | column-name heuristic | 可参考的 display inference | 可靠 metric fact、numeric proof、aggregation permission |
| `Interpretation.dimension` | metric 补集 heuristic | 可参考的 display inference | 可靠 dimension fact、groupability proof |
| `analysis` | 多数 route 为 LLM text；失败/等待可为程序文本 | 人类可读解释、错误描述 | 确定性规则输入、DB verified fact set |
| `schema_graph` | schema/retrieval context | 相关 table/field/role/type 候选 context | 当前 output alias→source field 的确定映射 |
| `execution_log` | diagnostic mixed payload | 审计某次调用、查找 nested SQL/success/error/result | 稳定 typed canonical result；整体作为业务事实 |

### 14.2 可靠性层级

```text
事实层（带表示限制）
└── QueryResult.columns / rows / executed sql provenance

确定性派生层
└── len(rows)、fixed route/mode/status branches、steps、table label join

Schema context 层
└── schema_graph / retrieval
    真实描述候选 schema，但未与 output columns 确定映射

可参考推断层
└── Interpretation.metric / dimension
    仅列名 heuristic

生成式说明层
└── analysis / result_title / valid / route_reason / standalone_query
    LLM-generated or influenced

诊断层
└── execution_log / tool_calls
    混合 execution facts、派生摘要、LLM reason 与控制 metadata
```

### 14.3 对指定字段的最终判断

#### `QueryResult.rows`

最可靠的 current-result 数据来源，但仅代表已经 normalization 和行数限制后的返回值。Derive 可以观察值，不能由值的 Python/JSON 类型自动断言数据库 dtype 或业务语义。

#### `Interpretation.metric / dimension`

当前明确是 heuristic。未来读取它们，就是读取 ResultBuilder 的名称规则输出，而不是 schema-grounded fact。

#### `analysis`

通常是 LLM text，并且默认可能只基于前 50 rows。它适合解释，不是确定性计算输入。即使包含正确数值，也应理解为模型复述，而不是数据库 result cell 本身。

#### `schema_graph`

是有来源的 schema/business context，field 中可包含 role/type，table 中有 id/label；但没有 output column mapping。未来读取它是在读取相关 schema 候选，不是在读取每个结果列的已证实 lineage。

#### `execution_log`

是 diagnostic metadata，其中可能嵌套比顶层更丰富的 MCP result。未来读取它是在依赖 untyped trace structure；必须逐个 nested value 判断是 execution fact、派生值还是 LLM content，不能把整份 log 当 canonical fact。

### 14.4 最终边界

> 当前 QueryResult 同时容纳事实、上下文、推断、生成文本和诊断记录。未来 Derive 若不先识别 provenance，就可能把“列名 heuristic”误当业务 role、把“LLM analysis”误当数据库事实、把“schema candidate”误当 output lineage，或把“diagnostic row_count”误当 canonical total count。

---

## 15. Source Evidence Index

### 15.1 核心文件

| 文件 | 类 / 函数 | 当前行号 | Provenance 作用 |
|---|---|---:|---|
| `backend/app/querying/models.py` | `SqlExecution` | L7-L13 | ResultBuilder 的 DB execution input contract |
| `backend/app/workflows/result_builder.py` | `ResultBuilder.qa()` | L13-L33 | data_qa QueryResult provenance |
| `backend/app/workflows/result_builder.py` | `ResultBuilder.direct_response()` | L35-L56 | direct response/fallback provenance |
| `backend/app/workflows/result_builder.py` | `ResultBuilder.waiting()` | L58-L81 | clarification QueryResult provenance |
| `backend/app/workflows/result_builder.py` | `ResultBuilder.completed()` | L84-L139 | success result、heuristic、schema lookup、LLM final consumption |
| `backend/app/workflows/result_builder.py` | `ResultBuilder.failed()` | L141-L156 | failure result、error→analysis |
| `backend/app/workflows/result_builder.py` | `public_retrieval()` | L158-L166 | retrieval 公开字段的 deterministic projection |
| `backend/app/models.py` | `Clarification` | L47-L51 | structured clarification contract |
| `backend/app/models.py` | `Interpretation` | L54-L59 | metric/dimension/time/table/assumptions contract |
| `backend/app/models.py` | `QueryResult` | L62-L83 | 最终 21 字段完整 Contract |

### 15.2 直接调用者和 LLM 边界

| 文件 | 类 / 函数 | 当前行号 | Provenance 作用 |
|---|---|---:|---|
| `backend/app/workflows/query_graph.py` | `invoke()` / `_state_result()` | L122-L130 | state result dict → 最终 QueryResult |
| `backend/app/workflows/query_graph.py` | `_preprocess()` | L132-L159 | intent/query/extraction 写入 state |
| `backend/app/workflows/query_graph.py` | `_respond_directly()` | L161-L172 | direct ResultBuilder caller |
| `backend/app/workflows/query_graph.py` | `_answer_qa()` | L174-L189 | QA LLM + ResultBuilder caller |
| `backend/app/workflows/query_graph.py` | `_retrieve_schema()` | L193-L233 | retrieval/schema_graph/schema_context state 来源 |
| `backend/app/workflows/query_graph.py` | `_prepare_single_database()` | L261-L290 | Agent execution/clarification state 来源 |
| `backend/app/workflows/query_graph.py` | `_execute_single_database()` | L293-L355 | completed/failed caller、final、log、tool call |
| `backend/app/workflows/query_graph.py` | `_run_multi_database()` | L357-L365 | program-generated failure provenance |
| `backend/app/querying/response_generator.py` | `answer_qa()` | L25-L32 | QA analysis 的 LLM source |
| `backend/app/querying/response_generator.py` | `finalize()` | L34-L58 | valid/reason/title/analysis LLM boundary |
| `backend/app/model_client.py` | `chat_json()` | L41-L53 | LLM text → parsed JSON；非业务 semantic validator |
| `backend/app/preprocessing.py` | `RequestPreprocessor.prepare()` | L59-L112 | route/reason/query/extraction/direct response 的 LLM source/fallback |
| `backend/app/preprocessing.py` | `_parse()` | L114-L157 | LLM preprocessor JSON 的确定性校验/规范化 |
| `backend/app/querying/single_database_agent.py` | `prepare()` clarify branch | L75-L97 | structured clarification 的 LLM source 和 shape check |

### 15.3 Schema、state、service/API 来源

| 文件 | 类 / 函数 | 当前行号 | Provenance 作用 |
|---|---|---:|---|
| `backend/app/database.py` | `_field()` / `SCHEMA` | L9-L38 起 | field type/role/aggregation 等静态业务 metadata |
| `backend/app/retrieval/graph.py` | `SchemaGraphBuilder.build()` | L18-L95 起 | retrieval hits → fields/tables/joins context |
| `backend/app/workflows/state.py` | `QueryState` | L6-L38 | Workflow context/control/diagnostic fields 容器 |
| `backend/app/services/session_context.py` | `analysis_context()` | L215-L260 | analysis_sources 和历史 analysis payload 来源 |
| `backend/app/services/askdata_service.py` | `submit()` | L48-L120 | task_id 生成、Workflow 调用、exception QueryResult、返回 Service |
| `backend/app/services/askdata_service.py` | `save_memory()` | L196-L213 | `saved=False → True` 的唯一明确变更 |
| `backend/app/services/askdata_service.py` | `_payload()` | L278-L302 | analysis sources 和初始 state 来源 |
| `backend/app/api/routes.py` | `query()` | L122-L130 | QueryResult response model 的 API 返回边界 |
| `backend/app/querying/duckdb_engine.py` | `execute()` / `_json_value()` | L33-L51, L144-L150 | rows 的 DB origin、200 行限制和 normalization 背景 |
| `backend/app/config.py` | `context_table_row_limit` | L69 | LLM 默认只看前 50 rows |

---

### 作为项目作者，我必须自己真正看懂的源码点

1. `querying/models.py::SqlExecution`：ResultBuilder 真正接收的五字段是什么。
2. `query_graph.py::_execute_single_database`：completed/failed 分支和六个参数怎样产生。
3. `result_builder.py::completed`：sql/columns/rows 哪些是直接复制。
4. `result_builder.py::completed`：metric/dimension 的 substring heuristic 原文。
5. `result_builder.py::completed`：table/time/assumptions 分别来自 graph、extraction、literal。
6. `response_generator.py::finalize`：LLM 看见 SQL、schema 和多少行 rows。
7. `response_generator.py::finalize`：valid/title/analysis/reason 如何 normalize，reason 为何没进入结果。
8. `result_builder.py::failed`：error 为什么进入 analysis，哪些字段使用默认值。
9. `result_builder.py::public_retrieval`：QueryResult.retrieval 是公开投影，不是 DB data。
10. `models.py::QueryResult/Interpretation`：21 个顶层字段和 5 个解释子字段的角色。
11. `query_graph.py` 的 log/call 构造：为什么 nested diagnostic 比顶层保存更多执行信息。
12. `preprocessing.py::prepare/_parse`：route_reason、standalone_query、time extraction 为什么是 LLM-influenced。
