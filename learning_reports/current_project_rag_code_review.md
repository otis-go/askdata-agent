# AskData 当前项目 RAG 实现：面向学习的代码审查

> 审查日期：2026-08-28  
> 审查对象：当前工作区中的真实源码  
> 审查方式：只读静态追踪；未修改任何业务代码

## 0. 先说结论

从架构设计看，当前项目应归类为：

> **D. Hybrid RAG（面向数据库 Schema 与 Text-to-SQL 的混合 RAG）**

它不是通用的“PDF/网页知识库问答”。它检索的是数据库字段级 Schema 文档：同一组检索词分别进入 BM25 和 Dense Vector Search，经 Reciprocal Rank Fusion（RRF）融合，再由独立 Rerank 模型打分和 threshold 筛选。筛选后的字段被转换成 Schema 图和 Schema context，用来增强数据库 Agent 的 SQL/工具决策；SQL 执行结果又与 Schema context 一起进入最终回答模型。

因此，它同时满足：

- 有真实 Retrieval：BM25 + Embedding/Dense + RRF + Rerank。
- Retrieved documents 被转换成 LLM context。
- context 与用户 Query、系统 Prompt 一起进入生成模型。
- 最终生成不仅包括自然语言回答，还包括被 Schema context 增强的 SQL/工具调用决策。

更准确的工程描述是：

> **字段级 Schema Hybrid RAG + LLM Text-to-SQL Agent + 数据库结果增强生成。**

### 当前工作树的可运行状态

必须把“架构设计”与“当前文件能否执行”分开看。只读编译检查发现当前工作树存在学习注释造成的 Python 缩进错误：

- `backend/app/retrieval/store.py:97-102`：类方法之间的三引号字符串被放在类级缩进之外，随后 `bm25_search()` 又缩进回类内，触发 `IndentationError`。
- `backend/app/workflows/query_graph.py:61-68`：同类问题导致 `QueryWorkflow._compile()` 之前发生 `IndentationError`。
- `backend/app/services/askdata_service.py:38-72`：同类问题导致 `AskDataService.submit()` 之前发生 `IndentationError`。

所以：

- **静态可确认的架构类型：D. Hybrid RAG。**
- **当前工作树的实际运行状态：入口模块暂时无法被 Python 导入。**
- 下文分析的是这些文件中明确写出的真实设计和调用关系，不假装当前版本已经成功运行。

---

## 0.1 阅读地图：先预览一条真实 Query 的完整调用链

选择项目测试中明确支持的问题：

> **“查询本月各地区销售额”**

`backend/tests/test_service.py:356-360` 用这个问题验证单库 Agent 能返回“销售地区、销售额”和非空 rows。不过生产路径的路由、检索词、SQL 和最终文案由模型在运行时决定；以下追踪的是 `database_query` 成功路径。当前源码的缩进错误修复前，该测试本身无法运行。

### 0.1.1 最小全链路

```text
HTTP POST /query
↓
api/routes.py::query()
↓
AskDataService.submit()
↓
QueryWorkflow.invoke()
↓
LangGraph preprocess node
↓
RequestPreprocessor.prepare()
↓
ModelClient.chat_json()
  输出 action=database_query、standalone_query、retrieval_terms
↓
QueryWorkflow._retrieve_schema()
↓
SchemaIndex.retrieve()
├─ ensure_built()
├─ BM25: bm25_search() → tokenize()
├─ Dense: embed() → dense_search()
├─ RRF
├─ rerank()
└─ threshold → hits
↓
SchemaIndex.include_workspace()
↓
SchemaGraphBuilder.build(hits)
↓
SchemaGraphBuilder.context_text()
↓
QueryWorkflow._prepare_single_database()
↓
SingleDatabaseAgent.prepare()
↓
ModelClient.chat_json(system skill, user JSON context)
↓
LLM 返回 call_tool / clarify
↓ call_tool
LocalMcpClient.call_tool()
↓
query_askdata_mock(sql)
↓
DuckDbEngine.execute()
↓
SqlExecution(sql, columns, rows)
↓
QueryWorkflow._execute_single_database()
↓
ResponseGenerator.finalize()
↓
ModelClient.chat_json(final system, query+SQL+rows+schema context)
↓
ResultBuilder.completed()
↓
QueryResult → FastAPI response
```

### 0.1.2 每一层的输入、输出和 RAG 角色

| 顺序 | 文件 / 类 / 函数 | 输入 | 输出 | 为什么需要 | RAG 阶段 |
| --- | --- | --- | --- | --- | --- |
| 1 | `backend/app/api/routes.py:123-129` `query()` | `QueryRequest`、当前用户 | 调用 `service.submit(...)` | HTTP/Pydantic 边界 | Query ingestion |
| 2 | `backend/app/services/askdata_service.py:72-163` `AskDataService.submit()` | 原始 Query、session、workspace、user id | 初始工作流 State；最终 `QueryResult` | 统一会话、权限和任务生命周期 | Orchestration |
| 3 | `backend/app/workflows/query_graph.py:144-152` `invoke()` | `QueryState`、task id | LangGraph 最终 State | 执行确定性的节点路由 | Orchestration |
| 4 | `backend/app/workflows/query_graph.py:162-202` `_preprocess()` | `state["query"]`、route context | intent、standalone query、extraction | 把自然语言问题变成检索参数 | Query transformation |
| 5 | `backend/app/preprocessing.py:52-105` `prepare()` | Query、近期轻量上下文 | `PreparedRequest` | 用 LLM 完成路由、改写、检索词提取 | Query understanding |
| 6 | `backend/app/workflows/query_graph.py:244-252` `_retrieve_schema()` | standalone query、retrieval terms、access scope | `retrieval` dict | 从 State 进入 Retriever | Retrieval entry |
| 7 | `backend/app/retrieval/service.py:87-207` `SchemaIndex.retrieve()` | Query、terms、threshold、scope | hits、候选和各阶段计数 | 编排混合检索 | Retrieval |
| 8 | `backend/app/retrieval/store.py:102-145` `bm25_search()` | retrieval text、top-k、allowed ids | `(document index, score)` 列表 | 字面关键词召回 | Sparse retrieval |
| 9 | `backend/app/retrieval/service.py:388-392` `_query_vector()`；`store.py:147-162` `dense_search()` | retrieval text / vector | Dense candidates | 语义召回 | Dense retrieval |
| 10 | `backend/app/retrieval/service.py:141-176` 内联 RRF/Rerank/threshold | 两路 candidates、完整 Query | selected document indexes | 融合、精排和质量门槛 | Fusion/ranking |
| 11 | `backend/app/retrieval/service.py:178-207` `_hit()`/return | selected indexes | `hits: list[dict]` | 把内部索引还原为公开文档 | Retrieval output |
| 12 | `backend/app/retrieval/service.py:209-268` `include_workspace()` | hits、用户确认字段/表、权限 | 补充或提升后的 hits | 将显式用户约束并入候选 | Deterministic augmentation |
| 13 | `backend/app/retrieval/graph.py:18-109` `build()` | hits、access scope | `schema_graph` | 组织表、字段和必要关联 | Context preparation |
| 14 | `backend/app/retrieval/graph.py:112-126` `context_text()` | schema graph | `schema_context: str` | 生成 LLM 可读的 Schema 文本 | Context building |
| 15 | `backend/app/querying/single_database_agent.py:28-81` `prepare()` | Query、graph、hits、schema text、tools | LLM JSON decision | 用检索 context 约束 SQL/工具决策 | Augmented generation |
| 16 | `backend/app/querying/single_database_agent.py:102-127` | tool name + arguments | tool result / execution | 将 LLM 决策落到真实工具 | Agent action |
| 17 | `backend/app/mcp_runtime/tools/database_tools.py:25-43` | SQL、database、scope | `DatabaseQueryResult` | 权限内执行只读查询 | External grounding |
| 18 | `backend/app/querying/duckdb_engine.py:33-51` | SQL | `SqlExecution` | 返回真实数据库 rows | Evidence acquisition |
| 19 | `backend/app/querying/response_generator.py:34-58` `finalize()` | Query、SQL、columns、rows、Schema context | title/analysis JSON | 用真实结果生成最终说明 | Final generation |
| 20 | `backend/app/workflows/result_builder.py:84-139` `completed()` | State、execution、final JSON | `QueryResult` | API 输出组装 | Response assembly |

### 0.1.3 运行时分支说明

这一条 Query 并不是由硬编码规则直接路由：

- `RequestPreprocessor.prepare()` 首先调用 LLM。
- 只有模型返回 `action="database_query"`，LangGraph 才进入 `retrieve_schema`。
- `standalone_query` 和 `retrieval_terms` 也来自模型 JSON，经 `_parse()` 校验、去重和截断。
- “本月”是否先触发时间工具、是否需要澄清、生成哪条 SQL，均由 Agent 在 Skill 约束下运行时决定。

因此，最终 SQL、hits、rows 和回答文案必须运行时才能确认。源码能够静态确认的是数据结构、调用顺序和每层约束。

---

## 1. 项目中的 RAG 边界

### 1.1 RAG 涉及的核心代码

| 环节 | 当前项目中的真实位置 | 结论 |
| --- | --- | --- |
| HTTP Query 入口 | `backend/app/api/routes.py:123-129`，`query()` | `QueryRequest.query` 进入 `AskDataService.submit()` |
| Service 入口 | `backend/app/services/askdata_service.py:72-163`，`AskDataService.submit()` | 规范化 Query、解析权限、构造初始 State、启动工作流 |
| 工作流编排 | `backend/app/workflows/query_graph.py:68-146`，`QueryWorkflow._compile()` / `invoke()` | LangGraph 根据预处理结果选择 database query、data QA 或 direct response |
| Query 预处理 | `backend/app/preprocessing.py:46-156`，`RequestPreprocessor` | LLM 生成路由、`standalone_query` 和 `retrieval_terms` |
| Schema 文档定义 | `backend/app/retrieval/store.py:12-42`，`FieldDocument` | 一个 Document 对应一个数据库字段 |
| 文档构建 | `backend/app/retrieval/service.py:302-386`，`_build_raw_documents()` / `_append_table_documents()` | 从静态 Schema、Relations 和 CSV 字段样例/分布构造字段文档 |
| 文档 Embedding/持久化 | `backend/app/retrieval/service.py:52-84`，`ensure_built()`；`backend/app/retrieval/store.py:54-81` | 生成 `dense_vector`，保存到本地 JSON Store |
| BM25 | `backend/app/retrieval/store.py:102-145`，`bm25_search()` | 在 `keyword_text` 上即时计算 BM25 |
| Dense Search | `backend/app/retrieval/store.py:147-162`，`dense_search()` | 对所有允许访问的 active documents 做向量点积排序 |
| Hybrid orchestration | `backend/app/retrieval/service.py:87-207`，`SchemaIndex.retrieve()` | BM25 + Dense → RRF → Rerank → threshold → hits |
| 权限过滤 | `backend/app/security/access_control.py:13-45`；`backend/app/retrieval/service.py:103-120` | 将用户可访问的表映射为 `allowed_doc_ids` |
| hits → Schema 图 | `backend/app/retrieval/graph.py:12-109`，`SchemaGraphBuilder.build()` | 把字段 hits 变成表、字段、关联组成的最小 Schema 图 |
| Schema 图 → context | `backend/app/retrieval/graph.py:111-126`，`context_text()` | 生成供 LLM 阅读的 Schema 文本 |
| context → SQL Agent Prompt | `backend/app/querying/single_database_agent.py:28-81`，`prepare()` | Query、retrieval hits、Schema 图、Schema 文本和工具定义进入 LLM |
| SQL 工具执行 | `backend/app/mcp_runtime/tools/database_tools.py:25-46`；`backend/app/querying/duckdb_engine.py:33-51` | LLM 选择数据库工具，DuckDB 执行只读 SQL |
| Rows → 最终回答 Prompt | `backend/app/querying/response_generator.py:34-58`，`finalize()` | Query、SQL、列、Rows、Schema context 进入最终回答模型 |
| 通用 LLM API 封装 | `backend/app/model_client.py:25-88`，`chat()` / `chat_json()` / `embed()` / `rerank()` | 统一调用 Chat Completions、Embedding 和 Rerank 服务 |
| API 最终结果 | `backend/app/workflows/result_builder.py:84-139`，`completed()` | 组装 `QueryResult`，包括 SQL、rows、analysis、retrieval 等 |

### 1.2 knowledge/document 数据从哪里来

该项目没有通用知识库 ingestion。Schema RAG 的知识源有三部分：

1. **静态 Schema 定义**
   - 文件：`backend/app/database.py`
   - `_field()` 在 `9-26` 行定义字段原始结构。
   - `SCHEMA` 在 `42-108` 行定义数据库、表、业务说明、业务词和字段。
   - `RELATIONS` 在 `111-156` 行定义表间关系。

2. **项目内置同义词**
   - 文件：`backend/app/retrieval/service.py:17-28`
   - `SYNONYMS` 给 `paid_amount`、`region`、`order_date` 等字段补充“销售额”“地区”“时间”等业务表达。

3. **真实 CSV 数据特征**
   - CSV 位于 `backend/data/databases/askdata_mock/`。
   - `SchemaIndex._append_table_documents()` 对每个字段读取最多 5 个不同样例，并计算数值范围/平均值、日期范围或不同值数量，见 `backend/app/retrieval/service.py:312-386`。

因此，Schema Document 不是简单复制字段名，而是把静态元数据、业务同义词、真实样例和字段 profile 合成检索材料。

### 1.3 Document 数据结构

`FieldDocument` 定义在 `backend/app/retrieval/store.py:12-35`：

```text
标识与位置：
  doc_id, database_id, table_id, table_label,
  field_name, field_label

字段语义与 metadata：
  field_type, field_description, field_role,
  aliases, samples, profile, relation_ids

三种检索文本：
  keyword_text, semantic_text, rerank_text

索引状态：
  dense_vector, schema_version, content_hash, active
```

`FieldDocument.public()` 会删除不应直接输出的 `dense_vector`，并把内部字段 `semantic_text` 重命名为公开字段 `vector_text`，见 `backend/app/retrieval/store.py:37-42`。

注意：

- 内部真正的 dataclass 字段名是 `semantic_text`。
- `vector_text` 只存在于公开输出中。
- Retrieval 的最小文档单位是一个 Schema field，而不是一张表或一段任意文本。

### 1.4 文档清洗、预处理与 chunking

当前 Schema 文档预处理主要是结构化拼接，不是通用 NLP 清洗：

- 字段 aliases 与项目同义词去重。
- 最多取 5 个非空 distinct samples。
- 将样例转换为 JSON 可输出值。
- 计算字段 profile。
- 分别合成 `keyword_text`、`semantic_text`、`rerank_text`。
- 用 Schema 和 Relations 的 hash 判断索引版本是否变化。

实现位置：`backend/app/retrieval/service.py:302-386`、`432-442`。

当前 Schema Retrieval **没有 chunking**：

- `_append_table_documents()` 的循环是 `for field in table["fields"]`。
- 每次循环只 append 一个字段级 raw document。
- 没有 chunk size、overlap、page offset、parent document/chunk id 等结构。

所以在本项目中：

> Document = 字段级 Schema 文档；Chunk 概念没有单独实现。

另外，`RequestPreprocessor` 是对用户 Query 做预处理，不是对 Document 做清洗。二者不要混淆。

### 1.5 keyword_text 的真实含义

`keyword_text` 在 `SchemaIndex._append_table_documents()` 中生成，见 `backend/app/retrieval/service.py:335-340`。它由以下内容用空格拼接：

```text
database id
+ table domain
+ table id
+ table label
+ table business_terms
+ field name
+ field label
+ field description
+ aliases / synonyms
+ sample values
```

它的职责很明确：给 BM25 提供尽可能丰富的字面匹配入口。

它不等于：

- 用户 Query；
- Embedding 文本；
- 最终 LLM context；
- 一段数据库实际记录。

### 1.6 是否真的存在 index

存在本地持久化 Store，但需要准确区分：

- `LocalSchemaStore` 将完整 `FieldDocument` 列表、Schema signature 和 embedding source 保存为 JSON，见 `backend/app/retrieval/store.py:45-81`、`174-181`。
- 默认文件是 `backend/data/schema_store.json`，路径来自 `SchemaIndex.__init__()`，见 `backend/app/retrieval/service.py:34-44`。
- `ensure_built()` 可以加载已有向量，也可以重新构建文档和 Embedding，见 `backend/app/retrieval/service.py:52-84`。

但当前没有独立的 BM25 倒排索引：

- token、document frequency、average document length 都是在每次 `bm25_search()` 时重新计算。
- 所以 `LocalSchemaStore` 更准确地说是“字段文档与向量的本地持久化 Store”，不是 Lucene/Elasticsearch 类型的 BM25 index。

同样，`status()` 返回的 `milvus_compatible: True` 只是状态标记；真实 `dense_search()` 是 Python 列表全量扫描，不是 Milvus 或其他 ANN 向量数据库，见 `backend/app/retrieval/store.py:147-171`。

### 1.7 三条业务路径与 RAG 的关系

LangGraph 在 `QueryWorkflow._compile()` 中定义三条一级路径，见 `backend/app/workflows/query_graph.py:68-138`：

1. `database_query`
   - 进入 Schema Hybrid Retrieval。
   - 检索 context 增强 SQL Agent。
   - SQL rows 再增强最终回答。
   - 这是本报告所说的完整 Hybrid RAG 主路径。

2. `data_qa`
   - 不重新查询 Schema 或数据库。
   - 使用短期记忆、最近查询结果和用户指定分析表格作为 context。
   - 由 `QueryWorkflow._answer_qa()` 和 `ResponseGenerator.answer_qa()` 生成回答，见 `backend/app/workflows/query_graph.py:217-232`、`backend/app/querying/response_generator.py:25-32`。
   - 这是 context-augmented generation，但不是 BM25/Dense Schema RAG。

3. `direct_response`
   - 预处理模型直接生成回复。
   - 不进行 Retrieval。
   - 见 `backend/app/preprocessing.py:52-105`、`backend/app/workflows/query_graph.py:204-215`。

---

## 2. 真实 Query 调用链的阅读结论

前面的 `0.1` 先给出了“查询本月各地区销售额”的完整逐层追踪表，是为了在阅读模块细节前先建立全局地图。结合第 1 节的边界判断，这条成功路径可以压缩为：

```text
User Query
→ Preprocessing LLM：route + standalone_query + retrieval_terms
→ Schema Hybrid Retrieval：BM25 + Dense + RRF + Rerank
→ hits
→ Schema graph / schema context
→ Database Agent LLM：tool decision + SQL
→ DuckDB rows
→ Result Generator LLM
→ QueryResult.analysis / rows / SQL
```

必须保留的三个运行时不确定性是：

1. 预处理模型是否选择 `database_query`。
2. Agent 是否先调用时间工具、是否澄清、最终生成什么 SQL。
3. Embedding/Rerank 分数、hits、rows 和最终文案的具体值。

代码可以静态确认的是调用顺序、输入输出结构和约束；上述具体结果运行时才能确认。

---

## 3. Retrieval 重点详解：BM25

### 3.1 BM25 实际接收的 Query

`SchemaIndex.retrieve()` 先执行：

```python
terms = list(dict.fromkeys(retrieval_terms or []))
retrieval_text = " ".join(terms).strip()
```

位置：`backend/app/retrieval/service.py:95-100`。

因此 BM25 使用的是上游 LLM 抽取的 `retrieval_terms` 拼接文本，不是完整 `standalone_query`。例如运行时若抽取得到：

```python
["销售额", "地区", "本月"]
```

则 BM25 Query 是：

```text
销售额 地区 本月
```

具体词项和顺序是模型输出，运行时才能确认。若 `retrieval_text` 为空，BM25 与 Dense 两路都会被跳过，不会回退使用完整 Query，见 `backend/app/retrieval/service.py:122-140`。

### 3.2 query 如何 tokenize

`LocalSchemaStore.tokenize()` 位于 `backend/app/retrieval/store.py:186-194`：

```python
words = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", text.lower())
tokens = []
for word in words:
    tokens.append(word)
    if re.fullmatch(r"[\u4e00-\u9fff]+", word):
        tokens.extend(word[index:index + 2] for index in range(len(word) - 1))
```

行为是：

- 英文、数字、下划线组成的连续串作为一个 token，并先转小写。
- 连续中文先作为一个完整 token。
- 中文串再生成重叠的相邻二元字符 token。

示意：

```text
"销售额"
→ ["销售额", "销售", "售额"]
```

一个值得注意的当前实现细节：两字中文词会先 append 完整词，再生成同样的二元 token。例如：

```text
"地区"
→ ["地区", "地区"]
```

这会让两字中文 Query token 和 Document token 都出现重复。它不是通用分词理论，而是当前代码的真实行为。

### 3.3 document 如何 tokenize

`bm25_search()` 对候选文档执行：

```python
tokenized = [self.tokenize(item.keyword_text) for _, item in candidates]
```

位置：`backend/app/retrieval/store.py:109-122`。

所以 Query 与 Document 使用同一个 `tokenize()`，但 Document 的原始输入是每个字段的 `keyword_text`。

### 3.4 BM25 理论概念到当前代码的逐项映射

| BM25 概念 | 当前代码 | 含义 |
| --- | --- | --- |
| Corpus | `candidates` | 经过 `active` 和 `allowed_doc_ids` 过滤后的字段文档集合 |
| Query tokens | `query_tokens = self.tokenize(query)` | 对 `retrieval_text` 分词 |
| Document tokens | `self.tokenize(item.keyword_text)` | 对字段文档的关键词文本分词 |
| TF | `frequencies = Counter(tokens)`，随后 `frequency = frequencies.get(token, 0)` | 当前 token 在当前字段文档中出现次数 |
| DF | `document_frequency[token]` | 有多少候选字段文档包含该 token |
| N | `len(candidates)` | 当前用户权限范围内的候选文档数 |
| IDF | `log(1 + (N - df + 0.5) / (df + 0.5))` | token 越少见，权重越高 |
| document length | `len(tokens)` | 当前 keyword document 的 token 数 |
| avgdl | `average_length` | 所有候选 document token 长度的平均值 |
| k1 | `1.5` | TF 饱和相关参数 |
| b | `0.75` | 文档长度归一化强度 |
| 单 token 得分 | `idf * frequency * (k1 + 1) / denominator` | 当前 token 对当前文档的贡献 |
| 文档总分 | `score += ...` | 对 Query 中每个 token 的贡献求和 |
| 排序 | `sorted(scores, key=lambda item: item[1], reverse=True)` | 原始 BM25 score 降序 |
| top-k | `[:top_k]` | 截断为 `bm25_top_k` |
| 输出归一化 | `score / maximum` | 将最高候选分数缩放为 1.0 |

对应代码集中在 `backend/app/retrieval/store.py:115-145`。

### 3.5 TF、IDF、长度归一化如何共同形成 score

对每个候选字段文档，代码做以下事情：

1. `Counter(tokens)` 计算该文档的 TF。
2. `document_frequency` 提供每个 token 的 DF。
3. `len(candidates)` 是当前检索 corpus 大小 N。
4. `len(tokens)` 是当前文档长度 dl。
5. `average_length` 是 avgdl。
6. `k1=1.5`、`b=0.75` 进入 denominator。
7. Query 每个 token 的贡献累加为当前文档 raw score。
8. 所有文档按 raw score 降序。
9. 先取 `top_k`，丢弃 `score <= 0` 的结果。
10. 返回 `(document_index, raw_score / global_max_score)`。

返回类型是：

```python
list[tuple[int, float]]
```

其中：

- tuple 第一个值是该文档在完整 active document 列表中的 index。
- tuple 第二个值是归一化后的 BM25 score。

### 3.6 与标准 BM25/BM25Okapi 的关系和差异

当前 TF、IDF 和长度归一化主体与常见 BM25 公式一致，但它是手写、即时计算的本地实现，具有以下项目特征：

1. **不是预构建倒排索引**：每次搜索重新 tokenize 全部允许访问的文档，并重新计算 DF/avgdl。
2. **IDF 使用始终为正的变体**：`log(1 + ratio)`；一些 BM25Okapi 库使用另一种 IDF 并对负 IDF 做下限处理。
3. **自定义中文分词**：完整中文串 + overlapping bigrams，不是 Jieba、语言模型 tokenizer 或搜索引擎 analyzer。
4. **没有 stop words、stemming 或字段权重**。
5. **Query 中重复 token 会重复累加贡献**。
6. **返回前执行 max normalization**：常见 BM25 库通常直接保留 raw score。
7. **Corpus 受权限影响**：先过滤文档，再计算 N、DF、avgdl；因此不同用户可能对同一 Query 得到不同 BM25 分数。

这不是“错误的 BM25”，而是一个适合小型本地 Schema 集合的直接实现；但学习时不要把它误认为生产搜索引擎的持久化 BM25 index。

---

## 4. 多路检索：Dense、Hybrid、RRF、Rerank 与过滤

### 4.1 真实结构

```text
retrieval_terms
      │
      ▼
retrieval_text
      │
      ├──────────────────────────────┐
      ▼                              ▼
BM25 Search                    Query Embedding
keyword_text                   ModelClient.embed()
      │                              │
      ▼                              ▼
bm25: [(doc_index, score)]     query_vector
                                     │
                                     ▼
                                Dense Search
                                     │
                                     ▼
                              dense: [(doc_index, score)]
      │                              │
      └──────────────┬───────────────┘
                     ▼
              rank maps + RRF
                     ▼
             candidate_indexes
                     ▼
      rerank(full standalone_query,
             candidate.rerank_text)
                     ▼
               rerank_scores
                     ▼
        threshold + max_schema_fields
                     ▼
                    hits
```

实现位置：`backend/app/retrieval/service.py:87-207`。

### 4.2 Embedding 与 Dense Search

文档向量构建：

```text
FieldDocument.semantic_text
→ ModelClient.embed(semantic_texts)
→ normalized dense_vector
→ LocalSchemaStore.replace_all()
```

见 `backend/app/retrieval/service.py:52-84`、`backend/app/model_client.py:55-71`。

Query 向量构建：

```text
retrieval_text
→ SchemaIndex._query_vector()
→ ModelClient.embed([retrieval_text])[0]
→ query_vector
```

见 `backend/app/retrieval/service.py:132-139`、`388-392`。

`ModelClient.embed()` 对返回向量执行 L2 normalization，见 `backend/app/model_client.py:122-125`。`dense_search()` 对每个允许访问的文档计算 query vector 与 `document.dense_vector` 的点积，然后降序取 top-k，见 `backend/app/retrieval/store.py:147-162`。

因此当前 Dense Search 是：

- 真实存在的向量检索；
- 使用外部 Embedding 模型生成向量；
- 本地 Python brute-force 全量扫描；
- 不是 ANN index，也不是向量数据库查询。

BM25 和 Dense 的候选表示兼容，二者都返回：

```python
(active_document_index, branch_score)
```

### 4.3 RRF：融合的是 rank，不是原始 score

`SchemaIndex.retrieve()` 先根据两路结果顺序建立排名：

```python
bm25_rank = {index: rank for rank, (index, _) in enumerate(bm25, 1)}
dense_rank = {index: rank for rank, (index, _) in enumerate(dense, 1)}
```

然后在 `fused` 中按排名累加：

```python
fused[index] += 1 / (60 + rank)
```

位置：`backend/app/retrieval/service.py:141-151`。

所以当前项目使用：

- 不是 BM25 only；
- 不是 Vector only；
- 不是原始 score 的 weighted fusion；
- 不是简单 union/merge；
- **是 Reciprocal Rank Fusion。**

原始 `bm25_scores` 和 `dense_scores` 被保留下来，但只用于最终 hit 的 `keyword_score`、`vector_score` 诊断字段；它们不参与 RRF 计算。

RRF 中间结构：

```text
bm25_rank: dict[document_index, rank]
dense_rank: dict[document_index, rank]
fused: dict[document_index, rrf_score]
rrf: list[(document_index, rrf_score)]
candidate_indexes: list[document_index]
```

### 4.4 Rerank

RRF 候选被映射为：

```python
texts = [self.documents[index].rerank_text for index in candidate_indexes]
result = self.model_client.rerank(query, texts, len(texts))
```

位置：`backend/app/retrieval/service.py:156-168`。

关键区别：

- BM25/Dense Query：`retrieval_terms` 拼出的 `retrieval_text`。
- Rerank Query：完整的 `standalone_query`。
- Rerank Document：字段文档的 `rerank_text`。

`ModelClient.rerank()` 向 Rerank API 发送：

```python
{
    "model": config.rerank_model,
    "query": query,
    "documents": documents,
    "top_n": min(top_n, len(documents)),
    "instruct": "Rank database schema fields by relevance to the user's analytics query."
}
```

并返回按相关性降序的 `(documents 中的局部 index, relevance score)`，见 `backend/app/model_client.py:73-88`。`SchemaIndex` 再把局部 index 映射回 active document index，并将 score 限制在 `[0, 1]`。

### 4.5 Threshold、top-k 和最终 hits

配置定义在 `backend/app/config.py:44-48`：

| 层 | 配置 | 环境变量 | 源码默认值 |
| --- | --- | --- | --- |
| BM25 recall | `bm25_top_k` | `BM25_TOP_K` | 30 |
| Dense recall | `dense_top_k` | `DENSE_TOP_K` | 30 |
| RRF candidates | `rrf_top_k` | `RRF_TOP_K` | 40 |
| Rerank threshold | `schema_recall_threshold` | `SCHEMA_RECALL_THRESHOLD` | 0.55 |
| Final field cap | `max_schema_fields` | `MAX_SCHEMA_FIELDS` | 20 |

真实筛选顺序：

```text
RRF top rrf_top_k
→ Rerank 所有 RRF candidates
→ 按 rerank score 降序
→ score >= recall_threshold
→ 最多 max_schema_fields
→ hits
```

见 `backend/app/retrieval/service.py:170-180`。

最终 `hits` 中的 `score` 就是 Rerank score，而不是 BM25 score 或 RRF score；三类分数分别保留在 `rerank_score`、`keyword_score`、`vector_score`、`rrf_score` 中，见 `backend/app/retrieval/service.py:394-415`。

### 4.6 allowed_doc_ids 与 metadata filter

用户权限由 `AccessController.resolve(user_id)` 解析为：

```text
user_id
roles
allowed_databases
allowed_tables
```

见 `backend/app/security/access_control.py:13-89`。

`SchemaIndex.retrieve()` 将可访问表映射为允许检索的字段文档 ID：

```python
allowed_doc_ids = {
    document.doc_id
    for document in self.documents
    if scope.allows_table(document.database_id, document.table_id)
}
```

见 `backend/app/retrieval/service.py:103-120`。

Store 的两路搜索都会先按以下条件选择 candidates：

```text
document.active is True
AND
(allowed_doc_ids is None OR document.doc_id in allowed_doc_ids)
```

BM25 的 N、DF、avgdl 都是在过滤后的 corpus 上计算。Dense 也只计算允许访问的文档。之后 `SchemaGraphBuilder.build()` 再做一次表权限过滤，数据库工具执行 SQL 时还会再次验证 database/table 权限，见：

- `backend/app/retrieval/store.py:93-118`、`147-162`
- `backend/app/retrieval/graph.py:18-38`
- `backend/app/querying/duckdb_engine.py:104-126`

这是检索、context 构建和真实数据库执行三层防护。

当前 metadata filter 主要是 `active`、database/table 权限以及 workspace 明确确认的字段/表；没有通用的任意 metadata filter DSL。

### 4.7 Retrieval 返回结构

`SchemaIndex.retrieve()` 返回：

```text
{
  query,
  retrieval_terms,
  embedding_source,
  rerank_source,
  threshold,
  bm25_count,
  dense_count,
  rrf_count,
  candidate_count,
  selected_count,
  hits,
  table_candidates,
  low_confidence_candidates
}
```

见 `backend/app/retrieval/service.py:193-207`。

每个 hit 是 `FieldDocument.public()` 加下列检索字段：

```text
score, rerank_score,
bm25_rank, dense_rank,
rrf_score, keyword_score, vector_score,
selection_reason, source
```

`low_confidence_candidates` 这个名字容易误导。代码没有筛选 `score < threshold`，而是直接取 `ranked[:8]`，见 `backend/app/retrieval/service.py:182-192`。所以它：

- 可能包含低分结果；
- 也可能包含已经进入 hits 的高分结果；
- 与 hits 可以重叠；
- 本质上更接近“Rerank 前 8 个候选摘要”。

---

## 5. Retrieval 如何连接 Generation

这是当前项目最关键的 RAG 接缝：

```text
FieldDocument candidates
→ hits
→ SchemaGraphBuilder.build(hits)
→ schema_graph
→ SchemaGraphBuilder.context_text(schema_graph)
→ schema_context
→ SingleDatabaseAgent Prompt
→ LLM 生成工具决策/SQL
→ DuckDB rows
→ ResponseGenerator Prompt
→ LLM 生成最终回答
```

### 5.1 hits 如何变成 Schema graph

`QueryWorkflow._retrieve_schema()` 在拿到 `SchemaIndex.retrieve()` 的结果后执行：

```python
schema_graph = self.graph_builder.build(
    retrieval["hits"],
    state.get("access_scope"),
)
```

位置：`backend/app/workflows/query_graph.py:244-283`。

`SchemaGraphBuilder.build()` 会：

1. 再次按权限过滤 hits。
2. 收集命中字段所在表。
3. 在需要多表时查找连接表的最短关系路径。
4. 将关联所需 key 字段补进 graph。
5. 生成 `tables`、`fields`、`joins` 和 `graph_version`。

位置：`backend/app/retrieval/graph.py:18-109`。

命中的完整 FieldDocument 在 graph 中被缩减为：

```text
id, table_id, name, label, type,
description, role, source, score
```

因此 graph 不再保留 BM25 token、dense vector 等检索内部表示。

### 5.2 Schema graph 如何变成 LLM context

`SchemaGraphBuilder.context_text()` 将 graph 格式化为类似：

```text
数据库: askdata_mock (DuckDB/CSV)
表 orders_current（当前订单明细）：...
  - orders_current.region | 销售地区 | 文本 | ...
  - orders_current.paid_amount | 实付金额 | 数值 | ...
  - orders_current.order_date | 下单日期 | 日期 | ...
关联: table_a.field = table_b.field | ...
```

位置：`backend/app/retrieval/graph.py:111-126`。

这一步的输出是 `schema_context: str`，写回 Query State：

```python
"schema_context": self.graph_builder.context_text(schema_graph)
```

见 `backend/app/workflows/query_graph.py:274-280`。

注意两个并行的 context 表示：

- `schema_context`：精简、人类可读的 Schema 文本。
- `retrieval["hits"]`：仍然包含完整公开 FieldDocument 和各检索 score。

二者都会进入数据库 Agent，只是字段不同。

### 5.3 第一次 Augmented Generation：Schema context → SQL/工具决策

`QueryWorkflow._prepare_single_database()` 调用：

```python
self.single_database_agent.prepare(
    state["standalone_query"],
    database,
    state["schema_graph"],
    state["schema_context"],
    state["retrieval"],
    workspace,
    state.get("access_scope") or {},
)
```

位置：`backend/app/workflows/query_graph.py:334-376`。

`SingleDatabaseAgent.prepare()` 构造 system prompt：

```python
system = f"你是单数据库问数智能体。\n\n{self.skill.instructions}"
```

`self.skill.instructions` 来自：

- `backend/app/skills/database_query/SKILL.md`
- 由 `backend/app/skills/registry.py:41-59` 加载。

这个系统 Prompt 规定：

- 只能使用 Schema 图中的表、字段和关联。
- 只能调用允许的 MCP 工具。
- 生成只读 DuckDB `SELECT`/`WITH`。
- 不使用 `SELECT *`。
- 信息不足时返回结构化 clarification。

Agent 的 user 内容不是普通字符串模板，而是下面这个对象的 JSON：

```python
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

每轮再加入：

```python
payload = {
    **base_payload,
    "tool_results": observations,
}
```

随后调用：

```python
decision = self.model_client.chat_json(
    system,
    json.dumps(payload, ensure_ascii=False),
)
```

真实位置：`backend/app/querying/single_database_agent.py:38-81`。

最终通过 `ModelClient.chat()` 发出的 Chat Completions 结构是：

```python
{
    "model": config.llm_model,
    "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ],
    "temperature": config.temperature,
    "stream": False,
}
```

见 `backend/app/model_client.py:25-39`。

来源拆分：

| Prompt 内容 | 来源 |
| --- | --- |
| `query` | 用户问题经预处理后的 `standalone_query` |
| `selected_fields` | Hybrid Retrieval 的 hits |
| `low_confidence_candidates` | Rerank 排名前 8 候选摘要 |
| `schema_graph` | hits + 关系补全后的结构化图 |
| `schema_text` | graph 转成的可读 context |
| `confirmed_fields/parameters` | 用户 workspace 中的明确约束 |
| `mcp_tools` | 当前权限下动态发现的工具定义 |
| system content | database query Skill instructions |
| `tool_results` | 前面时间工具等调用的 observation |

LLM 返回的不是最终自然语言答案，而是：

```json
{"action":"call_tool","tool_name":"...","arguments":{},"reason":"..."}
```

或者 clarification。见 `backend/app/skills/database_query/SKILL.md:25-47`、`backend/app/querying/single_database_agent.py:83-129`。

这已经属于 Augmented Generation：LLM 生成 SQL/工具决策时，输入被检索到的 Schema 证据增强，而不是仅靠模型记忆猜表名和字段名。

### 5.4 工具执行产生新的 grounding evidence

若模型选择数据库工具：

```text
decision.tool_name + decision.arguments
→ LocalMcpClient.call_tool()
→ query_askdata_mock(sql)
→ DuckDbEngine.execute()
→ SqlExecution / DatabaseQueryResult
```

关键位置：

- `backend/app/querying/single_database_agent.py:102-127`
- `backend/app/mcp_runtime/client.py:38-54`
- `backend/app/mcp_runtime/tools/database_tools.py:25-43`
- `backend/app/querying/duckdb_engine.py:33-51`

数据库层会再次验证：单条语句、只读 Query、禁止 `SELECT *`、已知表和用户表权限，见 `backend/app/querying/duckdb_engine.py:75-127`。

SQL 执行结果大致为：

```text
SqlExecution {
  sql: str,
  success: bool,
  columns: list[str],
  rows: list[dict],
  error: str | None
}
```

这里的 rows 是最终回答的第二类外部证据：它不是检索到的 Schema 文档，而是 Agent 根据 Schema context 查询得到的真实业务数据。

### 5.5 第二次 Augmented Generation：Rows → 最终自然语言回答

`QueryWorkflow._execute_single_database()` 在 SQL 成功后调用：

```python
final = self.response_generator.finalize(
    state["standalone_query"],
    execution,
    state["schema_context"],
    state.get("analysis_context", ""),
)
```

位置：`backend/app/workflows/query_graph.py:379-441`。

`ResponseGenerator.finalize()` 的 system prompt 是：

```text
你是查询结果整理器。检查结果能否回答问题，并生成简短标题和一到两句说明。
只能使用结果中真实存在的数值。只返回JSON：
{"valid":true,"reason":"...","title":"...","analysis":"..."}。
```

user prompt 是：

```text
问题：{standalone_query}
SQL：{execution.sql}
列：{execution.columns}
结果数据：{execution.rows[:context_table_row_limit]}
Schema：{schema_context}
用户保存的分析表格：{analysis_context or '无'}
```

见 `backend/app/querying/response_generator.py:34-50`。

它同样经过 `ModelClient.chat_json()` → `ModelClient.chat()`，最终发送：

```python
messages = [
    {"role": "system", "content": result_organizer_prompt},
    {"role": "user", "content": query_sql_rows_schema_and_analysis_context},
]
```

其中：

- 来自用户：standalone Query、用户保存的分析表格。
- 来自第一阶段 RAG：Schema context。
- 来自工具执行：SQL、columns、rows。
- 来自系统：只使用真实数值、返回固定 JSON 的约束。

这一步之所以叫 Augmented Generation，是因为最终回答不是仅依据用户问题生成，而是依据动态检索的 Schema 和刚刚执行得到的真实 rows 生成。

最终模型 JSON 被规范化为：

```text
valid, reason, title, analysis
```

再由 `ResultBuilder.completed()` 放进 `QueryResult` 的 `result_title`、`analysis` 等字段，见 `backend/app/workflows/result_builder.py:84-139`。

---

## 6. 容易混淆的概念：按本项目解释

| 概念 | 当前项目中的真实含义 | 与下一步的关系 |
| --- | --- | --- |
| Document | 一个 `FieldDocument`，代表一个 database table column | 被 BM25、Dense、Rerank 检索 |
| Chunk | Schema 路径没有单独 Chunk；一个字段文档就是最小检索单元 | 不存在 chunk split/overlap |
| `keyword_text` | 表/字段/业务词/别名/样例的关键词拼接文本 | 输入 BM25 tokenizer |
| `semantic_text` | 字段含义、表用途、aliases、profile、samples 的语义描述 | 建索引时输入 Embedding；公开输出名为 `vector_text` |
| `rerank_text` | 更完整的字段、表、角色、样例、profile、relations 描述 | RRF 候选送入 Rerank |
| token | `tokenize()` 产生的英文串、中文整串和中文 bigram | 用于 BM25 TF/DF/长度计算 |
| query | `SchemaIndex.retrieve()` 的 `query` 是完整 standalone Query | 主要供 Rerank；BM25/Dense 使用 retrieval text |
| retrieval terms | 预处理 LLM 抽取的短 Schema 检索词 | 去重、空格拼接成 `retrieval_text` |
| retriever | `SchemaIndex` 是 orchestration 层；`LocalSchemaStore` 执行两路搜索 | 返回 hits 和候选诊断信息 |
| index | JSON 持久化的 FieldDocuments + dense vectors + signature | 不是独立倒排索引或 ANN index |
| BM25 | `LocalSchemaStore.bm25_search()` 的手写在线评分 | 返回 sparse candidates |
| embedding | `ModelClient.embed()` 返回的归一化浮点向量 | 文档保存为 `dense_vector`，Query 临时生成 query vector |
| vector | `list[float]` | `dense_search()` 做点积排序 |
| Dense Search | 对允许访问的 active documents 全量扫描 | 返回 dense candidates |
| Hybrid Search | BM25 与 Dense 同时召回 | 进入 RRF |
| top-k | BM25/Dense/RRF/final fields 各自独立的截断参数 | 控制候选规模而不是一个统一数字 |
| score | BM25、Dense、RRF、Rerank 各有不同 score | hit 的最终 `score` 是 Rerank score |
| metadata | database/table/field ids、label、role、aliases、active、版本等 | 用于权限、展示、graph 构建和诊断 |
| context | 主要是 `schema_context`；也包括 raw hits、tool results、rows、analysis context | 被序列化进 LLM user message |
| prompt | system instructions + user content/JSON | 由 `ModelClient.chat()` 转成 messages |
| LLM generation | 预处理 JSON、Agent 工具决策、最终结果说明 | 项目里不止一次 LLM 调用 |

核心数据流可以记成：

```text
SCHEMA + CSV samples/profile
→ FieldDocument
→ keyword_text / semantic_text / rerank_text
→ BM25 + Dense
→ RRF
→ Rerank
→ hits
→ schema_graph
→ schema_context
→ Agent prompt
→ SQL/tool execution
→ rows
→ final prompt
→ answer
```

---

## 7. 当前项目真实 RAG 架构图

```text
User Query
  │
  ▼
FastAPI query()
backend/app/api/routes.py
  │
  ▼
AskDataService.submit()
backend/app/services/askdata_service.py
  │
  ▼
QueryWorkflow / LangGraph
backend/app/workflows/query_graph.py
  │
  ▼
RequestPreprocessor.prepare()
backend/app/preprocessing.py
  │  LLM 输出 route + standalone_query + retrieval_terms
  ▼
SchemaIndex.retrieve()
backend/app/retrieval/service.py
  │
  ├────────────────────────┐
  ▼                        ▼
BM25 Search             Embedding + Dense Search
store.bm25_search()      ModelClient.embed()
store.tokenize()         store.dense_search()
  │                        │
  └────────────┬───────────┘
               ▼
          RRF（按 rank 融合）
               │
               ▼
       ModelClient.rerank()
               │
               ▼
      threshold + field cap
               │
               ▼
             hits
               │
               ▼
SchemaGraphBuilder.build()
backend/app/retrieval/graph.py
               │
               ▼
SchemaGraphBuilder.context_text()
               │
               ▼
schema_graph + schema_context + raw hits
               │
               ▼
SingleDatabaseAgent.prepare()
backend/app/querying/single_database_agent.py
               │
               ▼
LLM：生成 call_tool / clarify
               │ call_tool
               ▼
Local MCP database tool
backend/app/mcp_runtime/
               │
               ▼
DuckDbEngine.execute()
backend/app/querying/duckdb_engine.py
               │
               ▼
SQL + columns + rows
               │
               ▼
ResponseGenerator.finalize()
backend/app/querying/response_generator.py
               │
               ▼
LLM：结果校验 + title + analysis
               │
               ▼
ResultBuilder.completed()
backend/app/workflows/result_builder.py
               │
               ▼
QueryResult / Final API Answer
```

图中没有补入项目不存在的 chunker、向量数据库或多库 Handoff。`_run_multi_database()` 当前明确返回“尚未实现”，见 `backend/app/workflows/query_graph.py:443-451`。

---

## 8. 哪些代码值得重点手动阅读

目标是先能独立讲清：

```text
Query → Retrieval → Top K → Context → Prompt → LLM
```

### P0：必须逐行看懂

#### 1. `backend/app/preprocessing.py`

重点函数：

- `RequestPreprocessor.prepare()`：`52-105`
- `RequestPreprocessor._parse()`：`107-150`
- `RequestPreprocessor._strings()`：`152-156`

要看懂：

- 原始 Query 如何变成 standalone Query。
- retrieval terms 是谁生成的。
- 为什么 database/data QA/direct response 会走不同路径。

#### 2. `backend/app/retrieval/service.py`

重点函数：

- `SchemaIndex.ensure_built()`：`52-84`
- `SchemaIndex.retrieve()`：`87-207`
- `SchemaIndex.include_workspace()`：`209-268`
- `_build_raw_documents()` / `_append_table_documents()`：`302-370`
- `_query_vector()`：`388-392`
- `_hit()`：`394-415`

这是整个 RAG Retriever 的 orchestration 核心。要逐行跟踪每一个变量：

```text
terms
retrieval_text
bm25 / dense
bm25_rank / dense_rank
fused / rrf
candidate_indexes
texts / result / rerank_scores
ranked / selected / hits
```

#### 3. `backend/app/retrieval/store.py`

重点：

- `FieldDocument`：`12-42`
- `LocalSchemaStore.bm25_search()`：`102-145`
- `LocalSchemaStore.dense_search()`：`147-162`
- `LocalSchemaStore.tokenize()`：`186-194`

这里要亲手把 BM25 里的每个理论名词映射到变量。

#### 4. `backend/app/workflows/query_graph.py`

重点：

- `_compile()`：`68-138`
- `_preprocess()`：`162-202`
- `_retrieve_schema()`：`244-283`
- `_prepare_single_database()`：`334-376`
- `_execute_single_database()`：`379-441`

它负责把独立模块串成一条执行链。先忽略 LangGraph 框架细节，专注每个 Node 读什么 State、写什么 State。

#### 5. `backend/app/retrieval/graph.py`

重点：

- `SchemaGraphBuilder.build()`：`18-109`
- `SchemaGraphBuilder.context_text()`：`112-126`

要回答：hits 到底在哪一行变成了 LLM context？

#### 6. `backend/app/querying/single_database_agent.py`

重点：`SingleDatabaseAgent.prepare()`：`28-133`。

要看懂：

- system prompt 从哪里来。
- user JSON 中哪些字段来自 Retrieval。
- `chat_json()` 返回什么。
- tool result 如何回到下一轮 prompt。

#### 7. `backend/app/querying/response_generator.py`

重点：`ResponseGenerator.finalize()`：`34-58`。

这是最终自然语言回答的 prompt 边界。要区分 Schema context 和数据库 rows 各自起什么作用。

### P1：理解接口和职责即可

| 文件 | 目前掌握到什么程度即可 |
| --- | --- |
| `backend/app/api/routes.py` | 知道 `/query` 如何调用 Service |
| `backend/app/services/askdata_service.py` | 知道权限、session、workspace、workflow payload 如何组装 |
| `backend/app/model_client.py` | 知道 `chat/chat_json/embed/rerank` 的请求与返回结构 |
| `backend/app/config.py` | 知道各 top-k、threshold、模型和 row limit 的来源 |
| `backend/app/security/access_control.py` | 知道 role 如何变成允许的 databases/tables |
| `backend/app/skills/database_query/SKILL.md` | 理解数据库 Agent 的系统规则 |
| `backend/app/skills/registry.py` | 知道 Skill instructions 如何载入 |
| `backend/app/mcp_runtime/client.py` | 知道 `list_tools/call_tool` 的接口 |
| `backend/app/mcp_runtime/tools/database_tools.py` | 知道 SQL 最终如何交给 DuckDB |
| `backend/app/querying/duckdb_engine.py` | 理解只读与权限校验职责，不必先深挖 SQL AST |
| `backend/app/workflows/result_builder.py` | 知道最终 State 如何变成 `QueryResult` |
| `backend/app/models.py` / `workflows/state.py` | 理解 API 与 State 的字段契约 |

### P2：目前可以先跳过

- MCP SDK 的异步传输内部细节。
- LangGraph checkpointer 的实现原理。
- `SessionArchive` 的 SQLite 持久化细节。
- `ShortTermMemory` 的异步摘要调度。
- DuckDB/sqlglot 的所有安全规则边角。
- Demo data seed 细节。
- 前端展示逻辑。
- `_run_multi_database()`，因为当前明确未实现。
- BM25、Embedding、Rerank 模型的数学推导和训练方式。

推荐手读顺序：

```text
preprocessing.py
→ query_graph.py::_retrieve_schema
→ retrieval/service.py::retrieve
→ retrieval/store.py::bm25_search / dense_search / tokenize
→ retrieval/graph.py::build / context_text
→ single_database_agent.py::prepare
→ response_generator.py::finalize
→ model_client.py::chat
```

---

## 9. 由浅入深的学习任务

以下问题不附答案。请尝试只靠源码逐题回答，并为每题写出“变量名 + 文件 + 行号”。

### 任务 1：找到 Query 第一次进入系统的位置

问题：

1. HTTP JSON 中的 Query 被哪个 Pydantic model 接收？
2. FastAPI route 把它传给哪个 Service 函数？
3. Service 写入 LangGraph State 的字段名是什么？

### 任务 2：追踪 retrieval_terms 的诞生

问题：

1. 哪一次 LLM 调用负责产生 `retrieval_terms`？
2. system prompt 对 retrieval terms 有什么格式要求？
3. `_parse()` 和 `_strings()` 对模型输出做了哪些规范化？
4. `SchemaIndex.retrieve()` 是否会在 terms 为空时使用完整 Query 兜底？

### 任务 3：手工执行一次 tokenize

任选以下文本：

```text
销售额 地区 本月
orders_current paid_amount
```

问题：

1. 正则先得到哪些 `words`？
2. 最终 `tokens` 是什么？
3. 哪些中文 token 会重复？
4. Query 和 Document 是否使用同一套 tokenizer？

### 任务 4：手工映射一个 BM25 文档得分

不要求算出具体小数，只回答：

1. `frequency` 从哪里来？
2. `document_frequency[token]` 如何构建？
3. `len(candidates)`、`len(tokens)`、`average_length` 分别对应什么？
4. `k1`、`b` 的实际值是多少？
5. top-k 是在排序前还是排序后应用？
6. 返回 tuple 的两个字段分别是什么？

### 任务 5：证明项目是 Hybrid Retrieval

请从 `SchemaIndex.retrieve()` 中找到并连线：

```text
retrieval_text
→ bm25
→ query_vector
→ dense
→ bm25_rank / dense_rank
→ fused
→ rrf
→ candidate_indexes
```

然后回答：RRF 使用原始 score 还是 rank？

### 任务 6：区分四层 top-k / threshold

分别修改以下配置时，写出最先受到影响的变量和后续层：

```text
BM25_TOP_K
DENSE_TOP_K
RRF_TOP_K
MAX_SCHEMA_FIELDS
SCHEMA_RECALL_THRESHOLD
```

再回答：如果把 BM25 top-k 从 5 改为 20，是否会直接保证最终 hits 增加？为什么？

### 任务 7：从 hit 追到最终 messages

从一个 `hit` 出发，逐行找到：

```text
hit
→ schema_graph field
→ schema_context 的一行文本
→ SingleDatabaseAgent.base_payload
→ json.dumps(payload)
→ ModelClient.chat() 的 user message
```

然后区分：哪些内容来自用户、Retrieval、系统 Skill、工具定义和 workspace。

### 任务 8：做一次架构删减推演

假设删除 BM25，只保留 Dense Search，不真正改代码，只回答：

1. `SchemaIndex.retrieve()` 哪些变量和循环需要调整？
2. `LocalSchemaStore` 哪个方法可以保留不用动？
3. RRF 只剩一路 rank 时是否还有实际融合意义？
4. 最终 `_hit()` 中哪些诊断字段会失去来源？
5. `SchemaGraphBuilder`、Agent prompt 和 `ResponseGenerator` 是否必须修改？为什么？

完成这些问题后，你应该能脱离代码智能体，自己完整讲出：

> 用户 Query 先由预处理 LLM 产生 standalone Query 和 Schema retrieval terms；terms 同时进入 BM25 与 Dense Search，两路候选按 rank 进行 RRF，再用完整 Query 对 `rerank_text` 精排并按 threshold 得到字段 hits。hits 被转换成 Schema graph 和 Schema context，和原始 Query 一起增强数据库 Agent 的 SQL/工具决策。SQL 执行返回真实 rows 后，Query、SQL、rows 和 Schema context 再次进入 LLM，最终生成 API 返回的结果标题和分析文本。

---

## 10. 代码审查中的关键提醒

1. 不要看到 `schema_store` 就认为存在生产级搜索索引；BM25 是在线全量计算，Dense 是本地全量扫描。
2. 不要看到 `milvus_compatible` 就认为项目实际连接了 Milvus；当前搜索代码没有 Milvus 调用。
3. 不要把 `semantic_text` 和公开输出中的 `vector_text` 当成两个字段。
4. 不要把 `low_confidence_candidates` 理解为严格低于 threshold 的集合。
5. 不要把所有 LLM 调用当成最终 answer：预处理、Agent 决策、最终结果整理是三种不同职责。
6. 不要把 SQL rows 当成最初 Retrieval documents；它们是 Agent 执行后获得的第二阶段 evidence。
7. 不要忽略权限对 BM25 corpus 的影响；过滤发生在 DF 和 avgdl 计算之前。
8. 当前源码存在缩进语法错误；在修复前只能进行静态学习，不能声称端到端已经成功运行。
