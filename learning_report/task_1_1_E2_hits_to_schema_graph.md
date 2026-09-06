# Task 1.1-E2：从 `retrieval["hits"]` 追到 `schema_graph`

> 固定 Query：`查询本月各地区销售额`  
> 分析依据：当前工作区真实源码  
> 本文只追踪 `retrieval["hits"] → schema_graph`，不继续分析检索算法，也不进入后续 Agent、MCP 或 SQL 生成。

## Step 1：从 `QueryWorkflow._retrieve_schema()` 继续往下

### 1.1 真实位置

- 文件：`backend/app/workflows/query_graph.py`
- 类：`QueryWorkflow`
- 函数：`_retrieve_schema()`
- 当前关键行：`193-233`

### 1.2 关键源码

```python
def _retrieve_schema(self, state: QueryState) -> dict[str, Any]:
    standalone_query = state["standalone_query"]
    extraction = state.get("extraction") or {}  #想找什么
    # 用完整问题和检索提示，在用户权限允许的 Schema 中寻找最相关字段。
    # 调用 BM25 等召回策略查找对应数据。
    retrieval = self.schema_index.retrieve(  #找到了什么
        standalone_query,
        retrieval_terms=list(extraction.get("retrieval_terms") or []),
        access_scope=state.get("access_scope"),
    )
    workspace = state.get("workspace") or {}
    query_workspace = {
        "schema_fields": list(workspace.get("schema_fields") or []),
        "confirmed_schema_tables": list(workspace.get("confirmed_schema_tables") or []),
        "confirmed_parameters": dict(workspace.get("confirmed_parameters") or {}),
    }
    retrieval = self.schema_index.include_workspace(
        retrieval,
        query_workspace,
        state.get("access_scope"),
    )
    retrieval["extraction"] = extraction
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

源码位置：`backend/app/workflows/query_graph.py:193-233`。

### 1.3 按真实执行顺序逐行理解

#### 第一步：取得完整 Query 和上游抽取信息

```python
standalone_query = state["standalone_query"]
extraction = state.get("extraction") or {}
```

位置：`backend/app/workflows/query_graph.py:194-195`。

- 输入对象：`state: QueryState`。
- `standalone_query`：本题固定为 `查询本月各地区销售额`，前提是上游 State 中确实写入这个值。
- `extraction`：普通 `dict`，里面可能有 `retrieval_terms`、metrics、dimensions、filters、time expressions 等上游抽取信息。
- 这里没有新建新的 extraction 内容；若 State 中已有一个非空 extraction dict，本地变量引用的就是那个 dict。
- 固定 Query 对应的具体 `retrieval_terms` 是上游模型运行结果，当前无法静态确认。

`QueryState` 中这两个字段的类型入口见 `backend/app/workflows/state.py:22-26`。

#### 第二步：得到原始 retrieval

```python
retrieval = self.schema_index.retrieve(
    standalone_query,
    retrieval_terms=list(extraction.get("retrieval_terms") or []),
    access_scope=state.get("access_scope"),
)
```

位置：`backend/app/workflows/query_graph.py:198-202`。

- 输入：完整 Query、检索词列表、权限范围。
- 返回变量：`retrieval: dict[str, Any]`。
- 对象性质：`SchemaIndex.retrieve()` 返回一个新的 retrieval 字典。
- 此时主要装有：`hits`、`table_candidates`、候选数量、阈值和各阶段诊断信息。
- 本轮从已经产生的 `retrieval["hits"]` 往下研究，不再展开它是怎样召回出来的。

#### 第三步：从 State 的 workspace 构造检索专用 workspace

```python
workspace = state.get("workspace") or {}
query_workspace = {
    "schema_fields": list(workspace.get("schema_fields") or []),
    "confirmed_schema_tables": list(workspace.get("confirmed_schema_tables") or []),
    "confirmed_parameters": dict(workspace.get("confirmed_parameters") or {}),
}
```

位置：`backend/app/workflows/query_graph.py:203-208`。

- `workspace`：读取 State 中现有 workspace；没有时使用新空字典。
- `query_workspace`：一定是这里新建的字典。
- `schema_fields` 和 `confirmed_schema_tables` 被复制成新 list。
- `confirmed_parameters` 被复制成新 dict。
- 本轮真正会影响 `include_workspace()` 的是前两个字段；`confirmed_parameters` 虽然被传进去，但当前函数不读取它。

#### 第四步：把用户确认的 Schema 信息并入 retrieval

```python
retrieval = self.schema_index.include_workspace(
    retrieval,
    query_workspace,
    state.get("access_scope"),
)
```

位置：`backend/app/workflows/query_graph.py:209-213`。

- 输入：当前 `retrieval` 字典、刚构造的 `query_workspace`、权限范围。
- 返回：仍命名为 `retrieval`。
- 重要对象语义：`include_workspace()` 会修改传入的 retrieval 字典并返回它，而不是创建一个全新的外层 retrieval。
- 主要变化：可能增加或提升 `retrieval["hits"]`，然后重算 `selected_count` 和 `table_candidates`。

其内部细节见本文 Step 2。

#### 第五步：把上游 extraction 附加到 retrieval

```python
retrieval["extraction"] = extraction
```

位置：`backend/app/workflows/query_graph.py:214`。

- 修改对象：同一个 `retrieval` 字典。
- 新增/覆盖键：`retrieval["extraction"]`。
- 值：本函数开头读取到的 `extraction` 对象。
- 这一步不改变 hits。

#### 第六步：把 enriched hits 交给 GraphBuilder

```python
schema_graph = self.graph_builder.build(
    retrieval["hits"],
    state.get("access_scope"),
)
```

位置：`backend/app/workflows/query_graph.py:215-218`。

- 输入 1：`retrieval["hits"]`，类型大致为 `list[dict[str, Any]]`。
- 输入 2：当前用户的 `access_scope`。
- 返回变量：`schema_graph: dict[str, Any]`。
- 对象性质：`SchemaGraphBuilder.build()` 新建并返回一个 graph 字典。
- GraphBuilder 不把原来的 hit dict 直接改造成 graph；它读取 hits，再新建 tables、fields、joins 等结构。

#### 第七步：把 graph 嵌回 retrieval

```python
retrieval["schema_graph"] = schema_graph
```

位置：`backend/app/workflows/query_graph.py:219`。

- 修改对象：原来的 `retrieval` 字典。
- 新增/覆盖键：`schema_graph`。
- 值：刚刚由 `build()` 返回的 graph 字典。
- 此时 Python 内存中，局部变量 `schema_graph` 与 `retrieval["schema_graph"]` 指向同一个 graph 对象。

#### 第八步：从 graph tables 推导数据库名称

```python
databases = sorted({
    str(table.get("database") or schema_graph.get("database") or "askdata_mock")
    for table in schema_graph.get("tables", [])
})
```

位置：`backend/app/workflows/query_graph.py:220-223`。

- 输入：`schema_graph["tables"]`。
- 输出：去重、排序后的 `list[str]`。
- 若 `tables` 为空，集合推导结果为空，因此 `databases == []`；源码不会因为默认字符串存在就自动产生一个数据库名。
- 固定 Query 最终得到哪些 tables 和 databases，依赖运行时 hits，当前无法静态确认。

#### 第九步：返回 LangGraph Node 的 State 更新

```python
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

位置：`backend/app/workflows/query_graph.py:224-233`。

这里返回的是一个新的“State 更新字典”。`_retrieve_schema()` 没有直接写：

```python
state["retrieval"] = ...
state["schema_graph"] = ...
```

而是通过 Node 的 return 让 LangGraph 把返回字段合入工作流 State。该函数注册为 `retrieve_schema` Node 的位置是 `backend/app/workflows/query_graph.py:63-69`。

更新后，核心 State 字段是：

```text
State["retrieval"]
  └─ enriched retrieval dict
       ├─ hits
       ├─ table_candidates
       ├─ extraction
       └─ schema_graph

State["schema_graph"]
  └─ 同一次 build() 产生的 graph dict
```

`QueryState` 对 `retrieval`、`schema_graph` 的字段声明见 `backend/app/workflows/state.py:24-27`。

### 1.4 Step 1 的最小对象流

```text
SchemaIndex.retrieve(...)
→ retrieval（新 dict）

retrieval + query_workspace
→ include_workspace(...)
→ retrieval（同一个外层 dict，被原地更新）

retrieval["hits"] + access_scope
→ SchemaGraphBuilder.build(...)
→ schema_graph（新 dict）

schema_graph
→ retrieval["schema_graph"]
→ Node return["schema_graph"]
→ State["schema_graph"]
```

---

## Step 2：解释 `SchemaIndex.include_workspace()`

### 2.1 真实位置

- 文件：`backend/app/retrieval/service.py`
- 类：`SchemaIndex`
- 函数：`include_workspace()`
- 当前行：`212-271`

### 2.2 关键源码：准备输入和去重集合

```python
def include_workspace(
    self,
    retrieval: dict[str, Any],
    workspace: dict[str, Any],
    access_scope: AccessScope | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """将用户确认的字段加入检索结果。"""
    scope = (
        access_scope
        if isinstance(access_scope, AccessScope)
        else AccessScope.from_dict(access_scope)
        if access_scope is not None
        else None
    )
    confirmed_tables = set(workspace.get("confirmed_schema_tables") or [])
    confirmed_fields = {
        (item.get("tableId"), item.get("name"))
        for item in workspace.get("schema_fields", [])
        if item.get("name")
    }
    hits = list(retrieval.get("hits", []))
    known = {hit["doc_id"] for hit in hits}
```

位置：`backend/app/retrieval/service.py:212-233`。

逐行解释：

1. `retrieval`
   - 输入的原始检索结果字典。
   - 重点字段是 `retrieval["hits"]`。

2. `workspace`
   - 是 `_retrieve_schema()` 刚构造的 `query_workspace`。
   - 这里实际读取 `confirmed_schema_tables` 和 `schema_fields`。

3. `scope`
   - 如果传入的已经是 `AccessScope`，直接使用。
   - 如果是 dict，调用 `AccessScope.from_dict()` 新建权限对象。
   - 如果没有传权限，则为 `None`。

4. `confirmed_tables: set`
   - 来自 `workspace["confirmed_schema_tables"]`。
   - 元素是 table id，例如 `"orders_current"`。
   - 语义是：用户已经明确确认整张表。

5. `confirmed_fields: set[tuple]`
   - 来自 `workspace["schema_fields"]`。
   - 每项转成 `(tableId, name)`。
   - 例如：`("orders_current", "paid_amount")`。
   - 如果旧版 workspace 没有 `tableId`，可能形成 `(None, "paid_amount")`。

6. `hits = list(...)`
   - 新建一个 list，是原 hits 列表的浅拷贝。
   - list 容器是新的，但已有 hit dict 仍是原来的 dict 对象引用。

7. `known`
   - 把已有 hits 的 `doc_id` 收集为 set。
   - 用于后面判断“已存在则更新，不存在才 append”。

### 2.3 关键源码：遍历 FieldDocument 并匹配 workspace

```python
for document in self.documents:
    explicit_field = (document.table_id, document.field_name) in confirmed_fields
    legacy_field = (None, document.field_name) in confirmed_fields
    if document.table_id not in confirmed_tables and not explicit_field and not legacy_field:
        continue
```

位置：`backend/app/retrieval/service.py:234-238`。

`self.documents` 属性定义为：

```python
@property
def documents(self) -> list[FieldDocument]:
    return self.store.active_documents()
```

位置：`backend/app/retrieval/service.py:48-50`。

所以“怎样找到对应 FieldDocument”的真实答案是：

1. 取得 Store 中全部 active `FieldDocument`。
2. 逐个遍历，不是通过额外搜索接口查找。
3. 检查三种命中条件：
   - 文档所属表在 `confirmed_tables`；
   - `(table_id, field_name)` 精确出现在 `confirmed_fields`；
   - `(None, field_name)` 以旧版无 table id 形式出现。
4. 三种条件都不满足就 `continue`。

特别注意：

- 确认一个具体 `schema_field`，会加入对应字段文档。
- 确认一个 `confirmed_schema_table`，会让该表的所有 active 字段文档都满足条件，而不是只加入表名。
- `confirmed_parameters` 当前没有在 `include_workspace()` 中使用。

`FieldDocument` 的字段定义见 `backend/app/retrieval/store.py:12-35`，其中用于匹配的核心字段是 `doc_id`、`database_id`、`table_id` 和 `field_name`。

### 2.4 关键源码：权限检查

```python
if scope and not scope.allows_table(document.database_id, document.table_id):
    if document.table_id in confirmed_tables or explicit_field:
        raise PipelineStageError(
            "schema_access_control",
            "用户确认内容包含无权访问的Schema字段",
        )
    continue
```

位置：`backend/app/retrieval/service.py:239-245`。

- 已确认内容不能绕过权限。
- 若用户明确确认了一个无权表，或明确用 `(tableId, field_name)` 确认了无权字段，直接抛出 `PipelineStageError`。
- 如果只是旧版 `(None, field_name)` 恰好匹配到一个无权表中的同名字段，该文档会被跳过，不抛明确确认错误。

这一步只决定 workspace 文档能否并入 hits，不分析 workspace 的其他业务用途。

### 2.5 关键源码：已有 hit 不重复 append，而是提升

```python
if document.doc_id in known:
    hit = next(hit for hit in hits if hit["doc_id"] == document.doc_id)
    hit.update({
        "source": "user_confirmed",
        "selection_reason": "user_confirmed",
        "score": 1.0,
        "rerank_score": 1.0,
    })
    continue
```

位置：`backend/app/retrieval/service.py:246-254`。

去重键是 `document.doc_id`。

如果文档已经在原始 hits 中：

- 不 append 第二份。
- 从浅拷贝后的 `hits` 中找到原 hit dict。
- 原地更新这个 hit dict：
  - `source = "user_confirmed"`
  - `selection_reason = "user_confirmed"`
  - `score = 1.0`
  - `rerank_score = 1.0`

因为 hits 是浅拷贝，已有 hit dict 本身与调用前列表中的 dict 是同一对象。也就是说，已有 hit 的 `update()` 是对该 dict 的原地修改。

### 2.6 关键源码：原 hits 中没有时，新建 hit

```python
hits.append({
    **document.public(),
    "score": 1.0,
    "bm25_rank": None,
    "dense_rank": None,
    "rrf_score": 0.0,
    "rerank_score": 1.0,
    "keyword_score": 0.0,
    "vector_score": 0.0,
    "selection_reason": "user_confirmed",
    "source": "user_confirmed",
})
known.add(document.doc_id)
```

位置：`backend/app/retrieval/service.py:255-267`。

如果该 `doc_id` 不在 `known`：

1. `document.public()` 新建 FieldDocument 的公开 dict。
2. 加入一组与普通 retrieval hit 兼容的 score/rank 字段。
3. 因为它不是本轮检索算法召回的，所以：
   - `bm25_rank = None`
   - `dense_rank = None`
   - `rrf_score = 0.0`
   - `keyword_score = 0.0`
   - `vector_score = 0.0`
4. 因为它是用户明确确认的，所以：
   - `score = 1.0`
   - `rerank_score = 1.0`
   - `source = "user_confirmed"`
   - `selection_reason = "user_confirmed"`
5. 新 doc id 加进 `known`，避免后续再次加入。

`FieldDocument.public()` 会去掉 `dense_vector`，并把内部 `semantic_text` 改名为公开的 `vector_text`，见 `backend/app/retrieval/store.py:37-42`。

### 2.7 关键源码：写回同一个 retrieval

```python
retrieval["hits"] = hits
retrieval["selected_count"] = len(hits)
retrieval["table_candidates"] = self._table_candidates(hits)
return retrieval
```

位置：`backend/app/retrieval/service.py:268-271`。

真实对象变化是：

- `hits`：是新建的 list 容器。
- `retrieval`：仍是调用方传入的同一个外层 dict。
- `retrieval["hits"]`：被替换成 enriched hits 新列表。
- `selected_count`：按 enriched hits 数量重算。
- `table_candidates`：按 enriched hits 重新分组计算。
- return：返回同一个被修改过的 retrieval 字典。

`_table_candidates()` 会按 `table_id` 分组，记录每张表的最高字段 score 和字段数量，并按 score 降序，见 `backend/app/retrieval/service.py:420-432`。

### 2.8 Step 2 的最小数据流

```text
原始 retrieval["hits"]
        +
workspace["schema_fields"]
workspace["confirmed_schema_tables"]
        │
        ▼
遍历 self.documents（active FieldDocument）
        │
        ├─ doc_id 已存在 → 更新原 hit 为 user_confirmed
        └─ doc_id 不存在 → append 新的 user_confirmed hit
        │
        ▼
retrieval["hits"] = enriched hits
retrieval["selected_count"] = len(enriched hits)
retrieval["table_candidates"] = 重新按表聚合
```

一句话回答“新建还是修改”：

> `include_workspace()` 新建 hits 列表，但原地修改并返回同一个 retrieval 外层字典。

---

## Step 3：进入 `SchemaGraphBuilder.build()`

### 3.1 真实位置和初始化

- 文件：`backend/app/retrieval/graph.py`
- 类：`SchemaGraphBuilder`
- 函数：`build()`
- 当前行：`18-109`

构造器先把静态 `SCHEMA` 建成 table id 到 table definition 的映射：

```python
class SchemaGraphBuilder:
    """根据字段检索结果构建最小连通 Schema 图。"""

    def __init__(self) -> None:
        self.tables = {table["id"]: table for table in SCHEMA}
```

位置：`backend/app/retrieval/graph.py:12-16`。

`self.tables` 大致是：

```python
{
    "orders_current": {...完整 table definition...},
    "orders_history": {...},
    "customers": {...},
    "products": {...},
    "sales_targets": {...},
}
```

来源是 `backend/app/database.py:42-108` 的真实 `SCHEMA`。

### 3.2 第一段：输入和权限过滤

```python
def build(
    self,
    hits: list[dict[str, Any]],
    access_scope: AccessScope | dict[str, Any] | None = None,
) -> dict[str, Any]:
    scope = (
        access_scope
        if isinstance(access_scope, AccessScope)
        else AccessScope.from_dict(access_scope)
        if access_scope is not None
        else None
    )
    if scope:
        hits = [
            hit
            for hit in hits
            if scope.allows_table(str(hit.get("database_id") or ""), hit["table_id"])
        ]
```

位置：`backend/app/retrieval/graph.py:18-35`。

变量解释：

- 输入 `hits`：来自 `_retrieve_schema()` 传入的 `retrieval["hits"]`，已经经过 `include_workspace()`。
- 输入 `access_scope`：来自 `State["access_scope"]`。
- `scope`：规范化后的 `AccessScope | None`。
- 如果有 scope，本地变量 `hits` 会重新绑定到一个新建的过滤后 list。
- 这个过滤 list 只保留用户有权访问其 database/table 的 hit。
- GraphBuilder 没有写回 `retrieval["hits"]`；权限过滤只改变 `build()` 内部的局部 `hits` 变量。
- hit dict 没有在这里被修改。

因此对象关系是：

```text
retrieval["hits"]
→ build(hits, scope)
→ local filtered hits（有 scope 时是新 list）
```

### 3.3 第二段：先确定 selected tables，再求关系

```python
allowed_tables = set(scope.allowed_tables) if scope else set(self.tables)
selected_tables = set(hit["table_id"] for hit in hits)
relations = self._shortest_path_relations(selected_tables, allowed_tables)
graph_tables = set(selected_tables)
for relation in relations:
    graph_tables.update((relation["left_table"], relation["right_table"]))
```

位置：`backend/app/retrieval/graph.py:36-41`。

真实执行顺序非常重要：源码不是先构造完整 fields，再构造 tables。它先做：

#### 1. `allowed_tables`

- 类型：`set[str]`。
- 有 scope：复制 `scope.allowed_tables`。
- 无 scope：使用 `self.tables` 的所有 key。
- 输出给 Join path 搜索，限制关系路径不能穿过无权表。

#### 2. `selected_tables`

- 类型：`set[str]`。
- 来源：过滤后每个 hit 的 `hit["table_id"]`。
- 语义：用户相关字段直接命中的表。
- 去重是 set 自动完成的。

固定 Query 最终会产生哪些 `selected_tables`，取决于实际 `retrieval["hits"]`，当前无法静态确认。

#### 3. `relations`

- 类型：`list[dict[str, Any]]`。
- 由 `_shortest_path_relations(selected_tables, allowed_tables)` 返回。
- 每项来自静态 `RELATIONS`。
- 它代表把 selected tables 连接起来需要用到的关系边。

#### 4. `graph_tables`

- 初始是 `selected_tables` 的新 set 副本。
- 遍历每条 relation，把它的 `left_table`、`right_table` 都加入。
- 如果关系路径经过一个没有直接命中字段的中间表，该表会在这里被补进 graph。

输出给下一步的是：

```text
hits            → 构造直接命中的 fields
relations       → 补 relation key fields + 构造 joins
graph_tables    → 构造 tables
```

### 3.4 第三段：从 hits 构造 selected fields

```python
fields: dict[str, dict[str, Any]] = {}
for hit in hits:
    fields[hit["doc_id"]] = {
        "id": hit["doc_id"],
        "table_id": hit["table_id"],
        "name": hit["field_name"],
        "label": hit["field_label"],
        "type": hit["field_type"],
        "description": hit.get("field_description", ""),
        "role": hit.get("field_role", ""),
        "source": hit.get("source", "retrieval"),
        "score": hit.get("score", 0),
    }
```

位置：`backend/app/retrieval/graph.py:43-55`。

源码没有名为 `selected_fields` 的变量。这里的 `fields` dict 就是字段集合的内部构建结构。

变量结构：

```python
fields: dict[doc_id, graph_field_dict]
```

例如：

```python
{
    "orders_current.paid_amount": {
        "id": "orders_current.paid_amount",
        "table_id": "orders_current",
        "name": "paid_amount",
        "label": "实付金额",
        "type": "数值",
        "description": "...",
        "role": "metric",
        "source": "retrieval",
        "score": 0.91,
    }
}
```

示例中的 score 仅为结构展示，不代表固定 Query 的真实运行分数；真实值当前无法静态确认。

这一转换会丢弃 hit 中很多只属于 Retrieval 的内容，例如：

- `keyword_text`
- `vector_text`
- `rerank_text`
- `bm25_rank`
- `dense_rank`
- `rrf_score`
- `keyword_score`
- `vector_score`

Graph 字段只保留后续描述 Schema 结构需要的标识、类型、说明、角色、来源和最终 score。

### 3.5 第四段：补充 Join path 所需的关联字段

```python
# 补充最短连接路径所需的关联字段。
for relation in relations:
    for side in ("left", "right"):
        table_id = relation[f"{side}_table"]
        field_name = relation[f"{side}_field"]
        doc_id = f"{table_id}.{field_name}"
        if doc_id in fields:
            continue
        definition = self._field_definition(table_id, field_name)
        fields[doc_id] = {
            "id": doc_id,
            "table_id": table_id,
            "name": field_name,
            "label": definition.get("label", field_name),
            "type": definition.get("type", "未知"),
            "description": definition.get("description", "关联键"),
            "role": definition.get("role", "join_key"),
            "source": "relation_key",
            "score": 1.0,
        }
```

位置：`backend/app/retrieval/graph.py:57-76`。

执行过程：

1. 遍历 `relations` 中每条表关系。
2. 分别读取关系左端和右端：
   - `left_table` + `left_field`
   - `right_table` + `right_field`
3. 拼成标准字段 id：`table_id.field_name`。
4. 如果这个 Join key 已经由 retrieval hit 加进 `fields`，跳过，避免重复。
5. 否则调用 `_field_definition(table_id, field_name)` 从静态 `SCHEMA` 找字段定义。
6. 新建 graph field，并标记：
   - `source = "relation_key"`
   - `score = 1.0`

`_field_definition()` 的真实实现是：

```python
def _field_definition(self, table_id: str, field_name: str) -> dict[str, Any]:
    table = self.tables.get(table_id, {})
    return next((field for field in table.get("fields", []) if field["name"] == field_name), {})
```

位置：`backend/app/retrieval/graph.py:173-175`。

所以 Join key 的 label、type、description、role 不是从 Retrieval hit 猜出来的，而是回到 `database.py` 的真实 Schema definition 查找。

### 3.6 第五段：构造 tables

```python
tables = [
    {
        "id": table_id,
        "label": self.tables[table_id]["label"],
        "description": self.tables[table_id]["description"],
        "domain": self.tables[table_id].get("domain", ""),
        "database": self.tables[table_id].get("database", "askdata_mock"),
    }
    for table_id in sorted(graph_tables)
    if table_id in self.tables
]
```

位置：`backend/app/retrieval/graph.py:78-88`。

- 输入：`graph_tables: set[str]`。
- 顺序：按 table id 排序。
- 只保留存在于静态 `self.tables` 定义中的 table id。
- 每项从 `SCHEMA` 中抽取：id、label、description、domain、database。
- 输出：`tables: list[dict[str, Any]]`。

这个列表既包含：

- hits 直接命中的 selected tables；
- 关系路径为了连接它们而补入的中间 tables。

### 3.7 第六段：构造 joins

```python
joins = [
    {
        **relation,
        "relation_type": relation.get("relation_type", "foreign_key"),
    }
    for relation in relations
]
```

位置：`backend/app/retrieval/graph.py:89-95`。

- 输入：`relations`。
- 输出：`joins: list[dict[str, Any]]`。
- 每条 relation 的原字段都被保留。
- 如果原始 relation 没有 `relation_type`，GraphBuilder 补默认值 `"foreign_key"`。
- `database.py` 中按地区连接销售目标的关系已明确标记 `relation_type="business"`，会保留原值，见 `backend/app/database.py:140-155`。

典型 join 结构是：

```python
{
    "left_table": "orders_current",
    "left_field": "customer_id",
    "right_table": "customers",
    "right_field": "customer_id",
    "description": "当前订单所属客户",
    "relation_type": "foreign_key",
}
```

### 3.8 第七段：计算版本和 databases，返回 schema_graph

```python
version_source = json.dumps(
    {"tables": tables, "fields": list(fields.values()), "joins": joins},
    ensure_ascii=False,
    sort_keys=True,
)
databases = sorted({table["database"] for table in tables})
return {
    "database": databases[0] if len(databases) == 1 else None,
    "databases": databases,
    "graph_version": hashlib.sha256(version_source.encode("utf-8")).hexdigest()[:12],
    "tables": tables,
    "fields": list(fields.values()),
    "joins": joins,
}
```

位置：`backend/app/retrieval/graph.py:96-109`。

执行过程：

1. 将 tables、fields、joins 序列化成稳定 JSON 字符串 `version_source`。
2. 从 tables 中收集 database，去重、排序得到 `databases`。
3. 对 `version_source` 求 SHA-256，并取前 12 位，得到 `graph_version`。
4. 新建并返回最终 `schema_graph` dict。

### 3.9 `build()` 的真实执行顺序

按代码校正后的顺序是：

```text
retrieval["hits"]
→ 权限过滤后的 local hits
→ allowed_tables
→ selected_tables
→ relations（Join path）
→ graph_tables（selected + path intermediate tables）
→ fields（先放直接命中的字段）
→ fields（再补 relation key 字段）
→ tables
→ joins
→ graph_version / databases
→ schema_graph
```

这与“先确定 selected fields 再求 tables”的概念描述略有不同：概念上 hits 就是 selected fields；实现上，源码先从 hits 提取 table ids 并求 Join path，之后才把 hits 转成 graph 的 `fields` dict。

---

## Step 4：重点理解 Join path

### 4.1 `_shortest_path_relations()` 真实源码

```python
def _shortest_path_relations(
    self,
    selected_tables: set[str],
    allowed_tables: set[str],
) -> list[dict[str, Any]]:
    if len(selected_tables) < 2:
        return []
    ordered = sorted(selected_tables)
    chosen: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    anchor = ordered[0]
    for target in ordered[1:]:
        for relation in self._bfs(anchor, target, allowed_tables):
            key = (
                relation["left_table"], relation["left_field"],
                relation["right_table"], relation["right_field"],
            )
            chosen[key] = relation
    return list(chosen.values())
```

位置：`backend/app/retrieval/graph.py:128-145`。

按顺序解释：

1. 如果 selected tables 少于 2 张，不需要 Join，立即返回 `[]`。
2. `ordered = sorted(selected_tables)`：将 table ids 排序，保证选择 anchor 的顺序稳定。
3. `anchor = ordered[0]`：第一张表作为固定起点。
4. 对其余每个 `target`，调用 `_bfs(anchor, target, allowed_tables)`。
5. BFS 返回从 anchor 到 target 所需的 relation 列表。
6. 每条 relation 用四元组作为 key：
   - left table
   - left field
   - right table
   - right field
7. `chosen` 用这个 key 去重。
8. 最终返回所有被选择的 relation dict。

如果有三张以上 selected tables，当前代码不是逐对连接所有组合，而是：

```text
同一个 anchor
→ target 1 的路径
→ target 2 的路径
→ ...
→ 把所有路径中的 relation 去重合并
```

### 4.2 `_bfs()` 真实源码

```python
@staticmethod
def _bfs(
    start: str,
    target: str,
    allowed_tables: set[str],
) -> list[dict[str, Any]]:
    queue: deque[tuple[str, list[dict[str, Any]]]] = deque([(start, [])])
    visited = {start}
    while queue:
        table, path = queue.popleft()
        if table == target:
            return path
        for relation in RELATIONS:
            if relation["left_table"] == table:
                neighbor = relation["right_table"]
            elif relation["right_table"] == table:
                neighbor = relation["left_table"]
            else:
                continue
            if neighbor not in allowed_tables:
                continue
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, [*path, relation]))
    return []
```

位置：`backend/app/retrieval/graph.py:147-171`。

不用图论公式，可以把它理解成“按一层一层的邻接表关系找路”：

1. `queue` 初始只有 `(start, [])`。
   - 第一个元素：当前走到哪张表。
   - 第二个元素：走到这里已经经过哪些 relations。
2. 每轮从队列左边取一个 `(table, path)`。
3. 如果 `table == target`，当前 `path` 就是找到的连接路径。
4. 遍历项目的静态 `RELATIONS`：
   - 当前表在 relation 左边，则邻居是右表。
   - 当前表在 relation 右边，则邻居是左表。
   - 与当前表无关的 relation 跳过。
5. 邻居不在 `allowed_tables` 时跳过，不能穿过用户无权访问的表。
6. 邻居没访问过时，把它和扩展后的 path 放进队列。
7. 队列耗尽仍没有 target，则返回 `[]`。

因为队列按先加入先取出处理，所以它会先找到经过 relation 数较少的路径。若存在多个同样短的路径，选中哪一条还会受到 `RELATIONS` 在 `database.py` 中声明顺序的影响。

### 4.3 使用当前项目真实字段做直接 Join 示例

题目给出的抽象例子是：

```text
orders.amount
customers.region
```

当前源码中没有名为 `orders` 的表，也没有字段 `amount`。对应的真实项目例子可以写成：

```text
orders_current.paid_amount
customers.region
```

真实字段定义见：

- `orders_current.paid_amount`：`backend/app/database.py:29-38`、`42-52`
- `customers.region`：`backend/app/database.py:63-76`

假设 enriched retrieval hits 里有这两个字段：

```python
hits = [
    {
        "doc_id": "orders_current.paid_amount",
        "table_id": "orders_current",
        "field_name": "paid_amount",
        ...
    },
    {
        "doc_id": "customers.region",
        "table_id": "customers",
        "field_name": "region",
        ...
    },
]
```

这只是帮助理解的假设输入，不代表固定 Query 的真实 hits；固定 Query 的实际 hits 当前无法静态确认。

#### 第一步：selected tables

```python
selected_tables = {
    "orders_current",
    "customers",
}
```

它来自：

```python
set(hit["table_id"] for hit in hits)
```

位置：`backend/app/retrieval/graph.py:37`。

#### 第二步：为什么两个业务字段还不足以描述 Join

直接命中的字段只有：

```text
orders_current.paid_amount
customers.region
```

这两个字段分别是指标和维度，但它们本身不是当前 Schema 定义的表关联键。真实关系是：

```python
{
    "left_table": "orders_current",
    "left_field": "customer_id",
    "right_table": "customers",
    "right_field": "customer_id",
    "description": "当前订单所属客户",
}
```

位置：`backend/app/database.py:111-118`。

所以只有两个 retrieval hits 时，只知道“想用哪些业务字段”，还不知道连接条件需要：

```text
orders_current.customer_id
=
customers.customer_id
```

#### 第三步：怎样找到 relation

`selected_tables` 排序后是：

```python
["customers", "orders_current"]
```

所以：

```text
anchor = customers
target = orders_current
```

`_bfs()` 从 `customers` 出发遍历 `RELATIONS`。它会看到 `orders_current ↔ customers` 的关系，将 `orders_current` 放进 queue；下一次取出时命中 target，返回包含这条 relation 的 path。

因此：

```python
relations = [
    {
        "left_table": "orders_current",
        "left_field": "customer_id",
        "right_table": "customers",
        "right_field": "customer_id",
        "description": "当前订单所属客户",
    }
]
```

#### 第四步：GraphBuilder 怎样补 Join key

GraphBuilder 先保留两个命中字段：

```text
orders_current.paid_amount
customers.region
```

然后根据 relation 两端补入：

```text
orders_current.customer_id
customers.customer_id
```

补入字段的 `source` 是 `relation_key`，逻辑见 `backend/app/retrieval/graph.py:57-76`。

最终 fields 表达的是：

```text
用户问题相关字段：
  orders_current.paid_amount
  customers.region

为了连接表而补的字段：
  orders_current.customer_id
  customers.customer_id
```

#### 第五步：Join 信息怎样进入 graph

relation 被转换为：

```python
{
    "left_table": "orders_current",
    "left_field": "customer_id",
    "right_table": "customers",
    "right_field": "customer_id",
    "description": "当前订单所属客户",
    "relation_type": "foreign_key",
}
```

然后成为：

```python
schema_graph["joins"][0]
```

构造位置：`backend/app/retrieval/graph.py:89-95`。

### 4.4 中间需要第三张表时怎样加入

使用当前项目实际存在的例子：假设 hits 命中了：

```text
customers.region
products.product_name
```

当前 `RELATIONS` 中没有 `customers` 到 `products` 的直接关系，但存在：

```text
customers.customer_id
↔ orders_current.customer_id

orders_current.product_id
↔ products.product_id
```

关系定义见 `backend/app/database.py:111-131`。

于是 BFS 可以找到：

```text
customers
→ orders_current
→ products
```

返回的 `relations` 有两条：

```text
orders_current.customer_id = customers.customer_id
orders_current.product_id = products.product_id
```

然后 `build()` 执行：

```python
graph_tables = set(selected_tables)
for relation in relations:
    graph_tables.update((relation["left_table"], relation["right_table"]))
```

位置：`backend/app/retrieval/graph.py:39-41`。

所以：

```python
selected_tables = {"customers", "products"}

graph_tables = {
    "customers",
    "products",
    "orders_current",  # 关系路径补进来的中间表
}
```

`orders_current` 虽然没有直接命中用户字段，仍会进入：

```python
schema_graph["tables"]
```

同时关系两端的 key 会补进 `schema_graph["fields"]`：

```text
customers.customer_id
orders_current.customer_id
orders_current.product_id
products.product_id
```

两条关系进入：

```python
schema_graph["joins"]
```

### 4.5 找不到路径时发生什么

`_bfs()` 最后直接：

```python
return []
```

位置：`backend/app/retrieval/graph.py:171`。

因此当前实现中：

- 找不到允许访问的连接路径时，不会在 GraphBuilder 内抛错。
- `relations` 对该 target 为空。
- selected tables 仍可能都在 `schema_graph["tables"]`。
- 但没有对应 join 被加入 `schema_graph["joins"]`。

这意味着 graph 可能包含无法由当前 `RELATIONS` 连通的多张 selected tables。是否出现这种情况取决于实际 hits、静态关系和权限，固定 Query 下当前无法静态确认。

### 4.6 固定 Query 下能静态确认到什么程度

对 `查询本月各地区销售额`：

- 可以静态确认：GraphBuilder 会完全按照上述逻辑处理 enriched hits。
- 不能静态确认：本轮最终 hits 是否只来自 `orders_current`，是否还包含其他表。
- 如果所有 hits 都属于同一张表：
  - `len(selected_tables) < 2`
  - `_shortest_path_relations()` 返回 `[]`
  - `schema_graph["joins"] == []`
- 如果 hits 跨表：会按 `RELATIONS` 和权限尝试补 path、intermediate tables 和 relation keys。

---

## Step 5：`schema_graph` 的真实结构

### 5.1 真实 return 源码

```python
version_source = json.dumps(
    {"tables": tables, "fields": list(fields.values()), "joins": joins},
    ensure_ascii=False,
    sort_keys=True,
)
databases = sorted({table["database"] for table in tables})
return {
    "database": databases[0] if len(databases) == 1 else None,
    "databases": databases,
    "graph_version": hashlib.sha256(version_source.encode("utf-8")).hexdigest()[:12],
    "tables": tables,
    "fields": list(fields.values()),
    "joins": joins,
}
```

位置：`backend/app/retrieval/graph.py:96-109`。

当前真实顶层结构只有以下六项：

```text
schema_graph
├── database
├── databases
├── graph_version
├── tables
├── fields
└── joins
```

没有其他隐藏的顶层字段。

### 5.2 `database`

真实值生成方式：

```python
databases[0] if len(databases) == 1 else None
```

类型：

```text
str | None
```

含义：

- graph 中所有 tables 恰好属于一个 database 时，给出该 database id。
- 没有 database 或出现多个 database 时，值为 `None`。

来源：从最终 `tables` 每项的 `database` 字段收集。

后续价值：快速判断 graph 是否能归属于单一数据库。这里仅说明数据职责，不进入后续执行逻辑。

### 5.3 `databases`

真实值生成方式：

```python
databases = sorted({table["database"] for table in tables})
```

类型：

```python
list[str]
```

含义：graph 所涉及的全部数据库 id，去重并排序。

来源：最终 `tables`。

后续价值：明确 Schema 结构跨越哪些数据库；即使 `database` 因多库而为 `None`，仍保留完整列表。

### 5.4 `graph_version`

真实值生成方式：

```python
hashlib.sha256(version_source.encode("utf-8")).hexdigest()[:12]
```

类型：

```text
str，12 个十六进制字符
```

输入 `version_source` 只包含：

```text
tables + fields + joins
```

含义：当前 graph 内容的稳定摘要标识。

来源：对排序键后的 JSON 表示做 SHA-256。

后续价值：标识“这一次使用的是哪一版 Schema graph”，便于携带和记录结构版本；它不是字段相关性 score。

### 5.5 `tables`

类型：

```python
list[dict[str, Any]]
```

每项真实结构：

```python
{
    "id": table_id,
    "label": self.tables[table_id]["label"],
    "description": self.tables[table_id]["description"],
    "domain": self.tables[table_id].get("domain", ""),
    "database": self.tables[table_id].get("database", "askdata_mock"),
}
```

构造位置：`backend/app/retrieval/graph.py:78-88`。

来源：

```text
selected_tables
+ Join path 中所有 relation endpoints
→ graph_tables
→ 静态 SCHEMA table definitions
```

它回答：

- 字段属于哪张表；
- 表叫什么、做什么；
- 表属于哪个业务 domain 和 database；
- 是否有为 Join path 补入的中间表。

后续需要它，是因为单独给出字段名并不能说明字段所在表和表的业务用途。

### 5.6 `fields`

类型：

```python
list[dict[str, Any]]
```

每项真实结构：

```python
{
    "id": str,
    "table_id": str,
    "name": str,
    "label": str,
    "type": str,
    "description": str,
    "role": str,
    "source": str,
    "score": float,
}
```

构造位置：

- 直接命中字段：`backend/app/retrieval/graph.py:43-55`
- Join relation key：`backend/app/retrieval/graph.py:57-76`

来源分为两类：

1. `source="retrieval"` 或 `source="user_confirmed"`
   - 来自 enriched `retrieval["hits"]`。
2. `source="relation_key"`
   - 原 hits 中没有，但为了 Join path 从静态 SCHEMA 补入。

它回答：

- 哪些字段与问题相关；
- 字段属于哪个 table；
- 字段的类型、说明和角色；
- 字段是检索命中、用户确认，还是关系路径补充。

后续需要它，是因为结构化查询必须知道可用字段名、所在表和数据类型；Join key 还保证跨表关系具备必要字段。

### 5.7 `joins`

类型：

```python
list[dict[str, Any]]
```

每项通常包含：

```python
{
    "left_table": str,
    "left_field": str,
    "right_table": str,
    "right_field": str,
    "description": str,
    "relation_type": str,
}
```

构造位置：`backend/app/retrieval/graph.py:89-95`。

来源：

- `_shortest_path_relations()` 返回的 relations；
- relations 本身来自 `backend/app/database.py:111-156` 的静态 `RELATIONS`；
- 未声明 `relation_type` 时补成 `foreign_key`。

它回答：

- 哪两张表相连；
- 左右各用哪个字段连接；
- 这条关系的业务说明；
- 是普通 foreign key 关系还是显式 business relation。

后续需要它，是因为只有 tables 和 fields 仍不能表达跨表连接条件；joins 才明确描述连接方式。

### 5.8 一个简化的 schema_graph 形状

下面只展示结构，不代表固定 Query 的真实运行结果：

```python
schema_graph = {
    "database": "askdata_mock",
    "databases": ["askdata_mock"],
    "graph_version": "12位摘要",
    "tables": [
        {
            "id": "orders_current",
            "label": "当前订单明细",
            "description": "...",
            "domain": "销售订单",
            "database": "askdata_mock",
        },
        {
            "id": "customers",
            "label": "客户信息",
            "description": "...",
            "domain": "客户经营",
            "database": "askdata_mock",
        },
    ],
    "fields": [
        {
            "id": "orders_current.paid_amount",
            "table_id": "orders_current",
            "name": "paid_amount",
            "label": "实付金额",
            "type": "数值",
            "description": "...",
            "role": "metric",
            "source": "retrieval",
            "score": "运行时分数",
        },
        {
            "id": "orders_current.customer_id",
            "table_id": "orders_current",
            "name": "customer_id",
            "label": "客户编号",
            "type": "整数",
            "description": "...",
            "role": "foreign_key",
            "source": "relation_key",
            "score": 1.0,
        },
    ],
    "joins": [
        {
            "left_table": "orders_current",
            "left_field": "customer_id",
            "right_table": "customers",
            "right_field": "customer_id",
            "description": "当前订单所属客户",
            "relation_type": "foreign_key",
        }
    ],
}
```

再次强调：这个例子用于展示字段形状。固定 Query 的具体 tables、fields、joins、score 和 graph_version 当前无法静态确认。

---

## 最后只总结两个核心对象

### retrieval

`retrieval` 主要回答：

> **哪些字段与用户问题相关？**

#### `hits`

- 是字段级相关结果列表。
- 每项仍保留较完整的 FieldDocument 公开信息和检索诊断字段。
- 经过 `include_workspace()` 后，还可能包含用户明确确认的字段或确认表中的字段。
- `source` 可以区分普通 retrieval 与 `user_confirmed`。
- 生成位置是 `SchemaIndex.retrieve()`，workspace enrich 位置是 `backend/app/retrieval/service.py:212-271`。

#### score / ranking

- hit 中保留最终 `score` 及若干排名/分数诊断字段。
- 本轮不重新分析这些分数怎样计算。
- `include_workspace()` 对用户确认字段把 `score` 和 `rerank_score` 提升为 `1.0`，见 `backend/app/retrieval/service.py:246-266`。

#### `table_candidates`

由 `_table_candidates(hits)` 生成，真实代码位于 `backend/app/retrieval/service.py:420-432`。

每张表包含：

```text
table_id
table_label
score       # 该表 hits 中的最高 score
field_count # 该表命中的字段数量
```

它是对 hits 的“按表聚合摘要”，仍然属于相关性视角，不包含表间 Join path。

### schema_graph

`schema_graph` 主要回答：

> **这些相关字段属于哪些表，这些表之间如何连接？**

#### `fields`

- 包含 retrieval/user-confirmed 的相关字段。
- 还包含 Join path 必要但没有直接命中的 relation key 字段。
- 每个字段明确记录 `table_id`、类型、角色、来源和 score。

#### `tables`

- 包含相关字段所在表。
- 还可能包含连接路径经过的中间表。
- 表 metadata 来自静态 `SCHEMA`。

#### `joins`

- 包含连接 graph tables 所需的关系。
- 明确左右表、左右字段、关系说明和关系类型。
- 来源是静态 `RELATIONS` 经路径选择后的子集。

### 最简化对比

```text
retrieval["hits"]
↓
相关字段候选
（重点是字段相关性、score、ranking、按表候选摘要）

schema_graph
↓
相关字段
+ 字段所属表
+ 为连通这些表需要的中间表
+ 必要 Join key
+ Join 关系
```

可以用一句话记忆：

> `retrieval` 解决“找哪些字段”，`schema_graph` 解决“这些字段放回数据库结构后怎样组成可连接的 Schema 子图”。

