# AskData 项目与大模型交互方式调查

> 调查日期：2026-08-31  
> 调查依据：当前仓库源码与当前 Python `Settings` 的实际生效值。  
> 安全说明：本文不会记录或泄露 `LLM_API_KEY` 的具体内容，只说明它是否已配置。  
> 范围：Chat LLM、Embedding、Rerank、所有直接模型调用点，以及当前是否使用商用云模型/本地模型/vLLM。

## 0. 结论摘要

当前项目**不是使用本机加载的模型，也不是使用本地 vLLM 服务**。当前实际生效配置是通过 HTTPS 调用阿里云 DashScope 的远程模型 API：

| 职责 | 当前模型名 | 当前实际 endpoint | 判断 |
|---|---|---|---|
| Chat / Generation | `qwen3.7-plus` | `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` | 阿里云 DashScope 托管的商用云 API |
| Embedding | `text-embedding-v4` | `https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings` | 阿里云 DashScope 托管的云 Embedding API |
| Rerank | `qwen3-rerank` | `https://dashscope.aliyuncs.com/compatible-api/v1/reranks` | 阿里云 DashScope 托管的云 Rerank API |

当前 `LLM_API_KEY` 的实际状态是“已配置”。本文检查配置时没有向任何模型 endpoint 发起生成请求。

需要区分两个问题：

1. **项目当前正在使用什么？**——DashScope 远程云服务，答案明确，不是本地 vLLM。
2. **代码能否改配置连接本地服务？**——Chat 和 Embedding 的 URL 是可配置的 OpenAI-compatible 风格接口，因此具备改接兼容服务的结构基础；但 Rerank 使用独立的 `/reranks` 协议，不能仅改一个 Chat URL 就断言整套项目已经支持本地 vLLM。

另外，vLLM 不是一个具体“模型名称”，而是模型推理/服务框架。当前仓库既没有 `vllm` Python 依赖，也没有启动 vLLM server 的脚本或本地权重路径；它只是通过通用 HTTP 客户端访问外部模型服务。

---

## 1. 模型配置从哪里来

### 1.1 `.env` 的加载方式

位置：`backend/app/config.py:8-24`  
函数：`load_env()`

```python
BASE_DIR = Path(__file__).resolve().parent.parent

def load_env(path: Path | None = None) -> None:
    env_path = path or BASE_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

load_env()
```

默认读取的是：

```text
backend/.env
```

这里使用 `os.environ.setdefault(...)`，所以优先级是：

```text
操作系统/启动进程已有环境变量
    高于
backend/.env 中的同名配置
    高于
Settings 字段的源码默认值
```

因此判断“当前到底调用哪个模型”时，不能只读 `.env.example`，也不能只看源码默认值，必须读取 `Settings` 的实际结果。

### 1.2 三类模型配置字段

位置：`backend/app/config.py:27-43`  
类：`Settings`

```python
api_key: str = os.getenv("LLM_API_KEY", "")
llm_base_url: str = os.getenv(
    "LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
).rstrip("/")
llm_model: str = os.getenv("LLM_MODEL", "qwen-plus")

embedding_model: str = os.getenv("EMBEDDING_MODEL", "text-embedding-v4")
embedding_dimensions: int = int(os.getenv("EMBEDDING_DIMENSIONS", "1024"))
embedding_base_url: str = os.getenv("EMBEDDING_BASE_URL", "").rstrip("/")

rerank_model: str = os.getenv("RERANK_MODEL", "qwen3-rerank")
rerank_base_url: str = os.getenv(
    "RERANK_BASE_URL", "https://dashscope.aliyuncs.com/compatible-api/v1"
).rstrip("/")
```

源码不是只配置一个“万能大模型”，而是拆成：

- `LLM_MODEL`：对话、路由、Agent 决策、结果说明、摘要；
- `EMBEDDING_MODEL`：Schema document 和查询文本向量化；
- `RERANK_MODEL`：对 Schema candidates 重排序。

三者共用 `LLM_API_KEY`。Embedding 可以通过 `EMBEDDING_BASE_URL` 指向不同服务；未配置时回退到 `LLM_BASE_URL`。Rerank 始终使用独立的 `RERANK_BASE_URL`。

### 1.3 URL 如何拼接

位置：`backend/app/config.py:77-88`

```python
@property
def chat_url(self) -> str:
    return f"{self.llm_base_url}/chat/completions"

@property
def embeddings_url(self) -> str:
    base = self.embedding_base_url or self.llm_base_url
    return f"{base}/embeddings"

@property
def rerank_url(self) -> str:
    return f"{self.rerank_base_url}/reranks"
```

所以配置变量应该保存“base URL”，具体路径由项目代码追加。

### 1.4 当前实际生效值

本次通过当前仓库 `backend/.venv` 导入 `app.config.settings`，只打印非敏感字段，得到：

```json
{
  "api_key_configured": true,
  "llm_model": "qwen3.7-plus",
  "chat_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
  "embedding_model": "text-embedding-v4",
  "embedding_dimensions": 1024,
  "embeddings_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
  "rerank_model": "qwen3-rerank",
  "rerank_url": "https://dashscope.aliyuncs.com/compatible-api/v1/reranks",
  "timeout": 30,
  "temperature": 1.0,
  "max_retries": 0
}
```

这组“实际生效值”比 `.env.example` 更能代表当前运行状态。例如源码默认 Chat 模型是 `qwen-plus`，而当前实际值已经被配置覆盖为 `qwen3.7-plus`。

`backend/.env.example:1-10` 和 `README.md:35-43` 也明确把 DashScope 作为项目默认部署示例，但它们只是模板/文档；当前判断主要依据仍是实际 `Settings` 值。

---

## 2. `ModelClient`：项目唯一的模型 HTTP 客户端

位置：`backend/app/model_client.py:14-120`  
类：`ModelClient`

项目没有使用 `openai`、DashScope SDK 或 vLLM Python SDK。`backend/requirements.txt` 中也没有这些依赖。它使用 Python 标准库 `urllib.request` 自己构造 HTTP POST。

`AskDataService` 创建一个 `ModelClient(settings)`，再把同一实例交给 SchemaIndex、SessionContext 和 QueryWorkflow：

位置：`backend/app/services/askdata_service.py:23-35`

```python
self.model_client = model_client or ModelClient(settings)
self.schema_index = schema_index or SchemaIndex(self.model_client, settings)
self.context = SessionContext(self.model_client, self.config)
self.workflow = QueryWorkflow(self.model_client, self.schema_index, self.config)
```

这意味着 Chat、Embedding 和 Rerank 虽然是三个模型/接口，但统一经过同一个 Python client 和同一个 API Key。

### 2.1 Chat / Generation 请求

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

按当前生效配置，实际请求主体近似为：

```json
{
  "model": "qwen3.7-plus",
  "messages": [
    {"role": "system", "content": "具体调用方构造的系统指令"},
    {"role": "user", "content": "用户问题、上下文或结构化JSON"}
  ],
  "temperature": 1.0,
  "stream": false
}
```

返回协议按 OpenAI-compatible Chat Completions 结构读取：

```text
result["choices"][0]["message"]["content"]
```

`chat_json()` 位于 `model_client.py:41-53`。它不是另一个模型接口，而是先调用 `chat()`，再移除可选 Markdown JSON 围栏并执行 `json.loads()`；如果整段无法解析，会尝试提取第一个 `{...}`。

### 2.2 Embedding 请求

位置：`backend/app/model_client.py:55-71`  
函数：`ModelClient.embed()`

```python
for start in range(0, len(texts), 10):
    payload = {
        "model": self.config.embedding_model,
        "input": texts[start : start + 10],
        "dimensions": self.config.embedding_dimensions,
        "encoding_format": "float",
    }
    result = self._post(self.config.embeddings_url, payload)
```

当前请求使用：

```json
{
  "model": "text-embedding-v4",
  "input": ["最多10段文本"],
  "dimensions": 1024,
  "encoding_format": "float"
}
```

返回读取 `result["data"][*]["embedding"]`，按 `index` 排序后，再由 `_normalize()` 做 L2 归一化（`model_client.py:67-71,122-125`）。一次传入超过 10 个文本时，客户端会拆成多次 HTTP 请求。

### 2.3 Rerank 请求

位置：`backend/app/model_client.py:73-88`  
函数：`ModelClient.rerank()`

```python
payload = {
    "model": self.config.rerank_model,
    "query": query,
    "documents": documents,
    "top_n": min(top_n, len(documents)),
    "instruct": "Rank database schema fields by relevance to the user's analytics query.",
}
result = self._post(self.config.rerank_url, payload)
```

当前使用 `qwen3-rerank`。返回从：

```text
result["results"][*].index
result["results"][*].relevance_score（或 score）
```

转换成 `list[tuple[int, float]]`，再按 score 降序排序。

### 2.4 真正发送请求的位置

位置：`backend/app/model_client.py:90-120`  
函数：`ModelClient._post()`

```python
if not self.config.api_key:
    raise RuntimeError("LLM_API_KEY 尚未配置")

request = urllib.request.Request(
    url,
    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    headers={
        "Authorization": f"Bearer {self.config.api_key}",
        "Content-Type": "application/json",
    },
    method="POST",
)

with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
    return json.loads(response.read().decode("utf-8"))
```

严格说，真正发生网络 I/O 的是 `backend/app/model_client.py:107` 的 `urllib.request.urlopen(...)`。

共同协议特征：

- `POST` JSON；
- `Authorization: Bearer <LLM_API_KEY>`；
- Chat 不流式返回；
- Chat、Embedding、Rerank 全部复用 `_post()`；
- 当前有效 `max_retries=0`，所以本次运行配置不会自动重试；
- 请求失败后相同 URL 会进入 30 秒熔断窗口。

即使未来把 URL 改成本地服务，代码仍要求 `LLM_API_KEY` 非空并发送 Bearer Header；否则它在网络请求前就会报错。

---

## 3. 项目中所有 Chat LLM 调用点

对 `backend/app` 搜索 `model_client.chat(...)` 和 `model_client.chat_json(...)`，当前共有五类业务用途。它们都使用同一个 `LLM_MODEL`，即当前的 `qwen3.7-plus`，并不存在“路由模型”“SQL 模型”“总结模型”各配置一个不同 Chat 模型的代码。

### 3.1 请求预处理：路由、独立问题改写、Schema 检索词提取

位置：`backend/app/preprocessing.py:53-112`  
类/函数：`RequestPreprocessor.prepare()`

```python
system = """你是问数系统的请求预处理器，一次完成上下文聚合、意图判断和必要回复。
# ...要求输出 action、standalone_query、retrieval 等 JSON
"""
user = f"当前问题：{query}\n近期轻量上下文：{recent_context or '无'}"
payload = self.model_client.chat_json(system, user)
```

这次模型调用同时负责：

- 将请求分为 `database_query`、`data_qa`、`direct_response`；
- 需要查库时生成 `standalone_query`；
- 生成 `retrieval_terms`、metrics、dimensions、filters、time expressions 等；
- 普通交流时直接生成 `response`。

返回的 Python 类型是 `dict[str, Any]`，随后 `_parse()` 在 `preprocessing.py:114-157` 校验并转换成 `PreparedRequest`。

如果这一步模型不可用，代码不会继续查数据库，而是在 `preprocessing.py:95-107` 走保守的 `direct_response` fallback。

### 3.2 单数据库 Agent：决定 clarify 或 MCP tool，并生成 SQL

位置：`backend/app/querying/single_database_agent.py:28-133`  
类/函数：`SingleDatabaseAgent.prepare()`

```python
system = f"你是单数据库问数智能体。\n\n{self.skill.instructions}"
payload = {**base_payload, "tool_results": observations}
decision = self.model_client.chat_json(
    system,
    json.dumps(payload, ensure_ascii=False),
)
```

模型在 user JSON 中看到：

- `query`、`database`；
- `schema_graph`、裁剪后的 retrieval；
- 用户确认字段和参数；
- `schema_text`；
- 当前允许的 MCP Tool Schema；
- 已完成的非数据库工具结果。

模型返回普通 JSON：

```json
{"action":"clarify","clarification":{}}
```

或者：

```json
{
  "action":"call_tool",
  "tool_name":"query_askdata_mock",
  "arguments":{"sql":"SELECT ..."},
  "reason":"..."
}
```

所以数据库 SQL 是 Chat 模型生成的，位于 `decision["arguments"]["sql"]`。程序再通过 MCP/DuckDB 做只读、权限和表名校验。

该函数有最多 `mcp_max_tool_calls` 次模型决策循环。当前默认上限为 3：时间工具结果会进入下一轮 Chat；数据库工具返回后立即退出 Agent。

这里没有使用 Chat Completions 原生顶层 `tools` 字段。MCP tools 是普通 JSON，被放入 user message 的 `mcp_tools` 字段；模型按 system instruction 输出一个普通 JSON tool decision，然后 Python 代码执行它。

### 3.3 已有数据问答：基于历史/拖入表格生成自然语言回答

位置：`backend/app/querying/response_generator.py:25-32`  
函数：`ResponseGenerator.answer_qa()`

```python
system = self.qa_skill.instructions if self.qa_skill else (
    "基于已有数据上下文回答，不编造数值；依据不足时明确说明。"
)
return self.model_client.chat(
    system,
    f"问题：{query}\n可用上下文：{context or '无'}",
)
```

这条路径不查询新数据库。它把已有查询结果/分析上下文作为 `context` 交给 Chat 模型，返回普通字符串。

### 3.4 SQL 执行后的结果说明

位置：`backend/app/querying/response_generator.py:34-58`  
函数：`ResponseGenerator.finalize()`

```python
user = (
    f"问题：{query}\nSQL：{execution.sql}\n列：{execution.columns}\n"
    f"结果数据：{execution.rows[: self.table_row_limit]}\nSchema：{schema_context}\n"
    f"用户保存的分析表格：{analysis_context or '无'}"
)
payload = self.model_client.chat_json(system, user)
```

模型看到：原问题、实际 SQL、columns、限定行数的真实 rows、Schema context 和可选分析表格。输出要求为：

```json
{"valid":true,"reason":"...","title":"...","analysis":"..."}
```

这不是继续生成 SQL，而是对已执行结果生成标题和简短说明。

### 3.5 长会话的异步摘要

位置：`backend/app/services/short_term_memory.py:91-134,157-200`  
类/函数：`ShortTermMemory.maybe_schedule()` / `_summarize()`

当会话上下文达到 token 软阈值，并且旧轮次足够多时，代码用单 worker 的 `ThreadPoolExecutor` 异步执行：

```python
state.future = self._executor.submit(self._summarize, ...)
```

`_summarize()` 再调用：

```python
summary = self.model_client.chat(system, user).strip()
```

输入包含上一版摘要和一批较旧完整轮次，输出是新的摘要字符串。正常前台请求不会等待这个异步任务（`short_term_memory.py:136-142`）。

### 3.6 Chat 调用点汇总

| 调用方 | 函数 | 输入重点 | 输出 | 当前 Chat 模型 |
|---|---|---|---|---|
| RequestPreprocessor | `prepare()` | 当前问题、近期上下文、路由/提取指令 | JSON | `qwen3.7-plus` |
| SingleDatabaseAgent | `prepare()` | query、Schema、retrieval、MCP tools/results | clarify 或 call_tool JSON | `qwen3.7-plus` |
| ResponseGenerator | `answer_qa()` | 问题 + 已有数据上下文 | 文本 | `qwen3.7-plus` |
| ResponseGenerator | `finalize()` | 问题 + SQL + rows + Schema | 结果说明 JSON | `qwen3.7-plus` |
| ShortTermMemory | `_summarize()` | 上一摘要 + 旧会话轮次 | 文本摘要 | `qwen3.7-plus` |

---

## 4. Embedding 与 Rerank 的真实调用点

位置：`backend/app/retrieval/service.py`  
类：`SchemaIndex`

这两类请求不负责生成自然语言答案，但它们也是项目对外部模型服务的真实调用。

### 4.1 Schema document 建索引时的 Embedding

位置：`backend/app/retrieval/service.py:52-84`  
函数：`SchemaIndex.ensure_built()`

```python
if not force and self.store.load(signature):
    source = self.store.embedding_source
    if source == self.config.embedding_model and self.model_client.enabled:
        self.embedding_source = source
        return

raw_documents = self._build_raw_documents()
semantic_texts = [item["semantic_text"] for item in raw_documents]
vectors = self.model_client.embed(semantic_texts)
# ...将 vector 写入 FieldDocument，再 replace_all(...)
```

职责：把每个字段文档的 `semantic_text` 送给当前 `text-embedding-v4`，生成 1024 维 vector，并保存进本地 Schema Store。

它**不是每次 Query 都必然重算全部 document vectors**。当本地索引 signature 有效、记录的 embedding source 与当前模型名一致，且 API Key 已配置时，会直接加载并 return。以下情况会重新调用 Embedding：

- 强制 rebuild；
- Schema signature 改变；
- 索引缺失或无法加载；
- 索引记录的 embedding model 与当前配置不一致。

由于 `ModelClient.embed()` 每批最多 10 个文本，索引文档数量较多时会发生多次 `/embeddings` HTTP 请求。

### 4.2 每次 Schema Retrieval 的 query Embedding

位置：`backend/app/retrieval/service.py:87-162,391-395`

```python
terms = list(dict.fromkeys(retrieval_terms or []))
retrieval_text = " ".join(terms).strip()

dense = self.store.dense_search(
    self._query_vector(retrieval_text),
    self.config.dense_top_k,
    allowed_doc_ids,
)

def _query_vector(self, text: str) -> list[float]:
    return self.model_client.embed([text])[0]
```

职责：把预处理模型生成的 `retrieval_terms` 去重后用空格连接，再调用 `text-embedding-v4` 生成一个 query vector，交给本地 `dense_search()`。

只要 `retrieval_text` 非空，这一步每次 Schema Retrieval 都会调用一次远程 `/embeddings`。Embedding 输入不是完整 standalone query，而是 retrieval terms 拼出的文本。

### 4.3 Schema candidates 的 Rerank

位置：`backend/app/retrieval/service.py:149-179`

```python
rrf = sorted(fused.items(), key=lambda item: item[1], reverse=True)[
    : self.config.rrf_top_k
]
candidate_indexes = [index for index, _ in rrf]

texts = [self.documents[index].rerank_text for index in candidate_indexes]
result = self.model_client.rerank(query, texts, len(texts))
```

职责：BM25 与 Dense 的候选经过本地 RRF 融合后，把：

- `query`：完整 standalone query；
- `documents`：每个候选 FieldDocument 的 `rerank_text`；

发送给当前 `qwen3-rerank`。返回 relevance score，再由本地代码做阈值筛选与 top fields 截断。

### 4.4 哪些 Retrieval 步骤不调用外部模型

以下操作完全在本地执行：

- `LocalSchemaStore.bm25_search()`：本地 BM25；
- `LocalSchemaStore.dense_search()`：使用已经拿到的向量做本地相似度搜索；
- RRF 融合：`SchemaIndex.retrieve()` 中的 Python 排名融合；
- threshold、top-k 截断；
- `SchemaGraphBuilder` 构图；
- MCP tool discovery；
- DuckDB SQL 执行。

“Dense Search 存在”不等于数据库在远程向量服务中。当前只把文本向量化交给 DashScope；vectors 与 Dense Search 索引保存在项目本地 `schema_store.json`/内存 Store 中。

### 4.5 Retrieval 模型调用汇总

| 场景 | 模型调用 | 输入 | 是否每次 Query 都调用 |
|---|---|---|---|
| 建立/重建 Schema Index | `embed(semantic_texts)` | 所有 FieldDocument 的 `semantic_text` | 否，索引有效时跳过 |
| Query Dense Retrieval | `embed([retrieval_text])` | retrieval terms 拼接文本 | 是，只要检索文本非空 |
| Candidate Rerank | `rerank(query, rerank_texts, top_n)` | 完整 query + RRF candidates | 是，只要存在候选 |

Embedding 或 Rerank 失败时没有本地语义模型兜底：`SchemaIndex` 会将其包装为 `PipelineStageError`，停止下游数据库查询。`Settings.public_status()` 也明确声明 `semantic_fallbacks: False`（`backend/app/config.py:90-105`）。

---

## 5. 从前端 Query 到模型服务的完整边界

### 5.1 前端不直接访问大模型

位置：`frontend/src/api.ts:3-36,59-68`

```typescript
query: (query, workspace, sessionId) =>
  request<QueryResult>("/api/query", {
    method: "POST",
    body: JSON.stringify({ query, session_id: sessionId, workspace }),
  })
```

前端只访问 AskData 的 FastAPI `/api/query` 与 clarification endpoint。前端源码中没有 DashScope/OpenAI/vLLM client，也不会拿到 `LLM_API_KEY`。

FastAPI 路由位于 `backend/app/api/routes.py:124-140`：

```python
@router.post("/query", response_model=QueryResult)
def query(payload: QueryRequest, user: AuthUser = Depends(require_user)) -> QueryResult:
    workspace = payload.workspace.model_dump(exclude_none=True) if payload.workspace else None
    return service.submit(payload.query, payload.session_id, workspace, user.user_id)
```

之后由 `AskDataService.submit()` 启动 `QueryWorkflow`。所有模型凭证和请求都留在后端。

### 5.2 总体交互架构

```text
Vue Frontend
frontend/src/api.ts::api.query()
    │ POST /api/query
    ▼
FastAPI Route
backend/app/api/routes.py::query()
    ▼
AskDataService.submit()
backend/app/services/askdata_service.py
    │
    ├─ shared ModelClient
    │   ├─ chat()/chat_json()
    │   ├─ embed()
    │   └─ rerank()
    │
    └─ QueryWorkflow / SchemaIndex / SessionContext
        │
        ├─ RequestPreprocessor ─────── Chat: qwen3.7-plus
        ├─ SchemaIndex
        │   ├─ document/query vectors Embedding: text-embedding-v4
        │   └─ candidates Rerank: qwen3-rerank
        ├─ SingleDatabaseAgent ────── Chat: qwen3.7-plus
        ├─ ResponseGenerator ──────── Chat: qwen3.7-plus
        └─ ShortTermMemory ────────── Chat: qwen3.7-plus（按阈值异步）
            │
            ▼
ModelClient._post()
Authorization: Bearer <已配置但不在前端暴露的 Key>
            │ HTTPS
            ▼
阿里云 DashScope endpoints
```

### 5.3 `direct_response` 路径

```text
User Query
→ RequestPreprocessor.chat_json()       # 1 次 Chat
→ action = direct_response
→ 预处理模型返回的 response 直接成为结果
→ END
```

这一条正常只发生 1 次 Chat 调用，不调用 Embedding、Rerank、Agent 或 DuckDB。

### 5.4 `data_qa` 路径

```text
User Query
→ RequestPreprocessor.chat_json()       # Chat #1，判断为 data_qa
→ QueryWorkflow._answer_qa()
→ ResponseGenerator.answer_qa()
→ ModelClient.chat()                    # Chat #2，读取已有 context
→ Answer
```

正常发生 2 次 Chat。它使用已有表格/历史结果上下文，不做新 Schema Retrieval，也不执行 SQL。

### 5.5 `database_query` 路径

```text
User Query
→ RequestPreprocessor.chat_json()       # Chat #1
    输出 standalone_query + retrieval_terms
→ SchemaIndex.ensure_built()
    └─ 索引无效时 embed(all semantic_texts)  # 可选，多批 Embedding
→ embed([retrieval_text])               # 1 次 Query Embedding
→ local Dense Search + local BM25 + local RRF
→ rerank(standalone_query, candidates)  # 1 次 Rerank
→ SchemaGraphBuilder                    # 本地，不调模型
→ SingleDatabaseAgent.chat_json()       # Chat #2，或最多 #2～#4
    ├─ clarify → LangGraph interrupt
    ├─ time tool → observation → 再次 Agent Chat
    └─ query_<database>({sql})
→ MCP + DuckDB                          # 本地，不调模型
→ rows
→ ResponseGenerator.finalize()
→ ModelClient.chat_json()               # 最后 1 次 Chat
→ QueryResult
```

在没有 clarification、Agent 直接调用数据库工具的最短成功路径中：

| 类型 | 次数 |
|---|---:|
| Chat | 3（预处理 1 + Agent 1 + 结果说明 1） |
| Query Embedding | 1 |
| Rerank | 1 |
| Document Embedding | 0（本地索引有效时） |

如果 Agent 先调用时间工具，Chat 会增加，Agent 自身最多 3 次决策，因此正常数据库路径通常是 **3～5 次 Chat**。如果 Schema Index 需要重建，还会增加若干批 document Embedding 请求。

精确次数受模型 action、clarification、索引状态和配置影响，运行时才能从 trace 确认，不能仅凭固定 Query 静态断言。

### 5.6 clarify 恢复时的模型调用

Agent 返回 clarify 后，当次 Agent 已结束。用户回答会调用：

```python
self.workflow.invoke(Command(resume={"option_id": option_id}), task_id)
```

位置：`backend/app/services/askdata_service.py:122-161`。

恢复后从 human clarification node 继续，再经过 Schema Retrieval 和 Agent；不会重新执行最开始的 RequestPreprocessor，但会再次调用 query Embedding、Rerank 和 Agent Chat。

### 5.7 可选的后台摘要调用

`SessionContext.remember()` 保存结果后会触发 `ShortTermMemory.maybe_schedule()`。只有会话 token 达到阈值时才异步增加一次 Chat 摘要请求，因此不能把它固定计算在每次 Query 的同步调用次数中。

---

## 6. 商用云、本地模型与 vLLM 的严格判断

### 6.1 当前运行方式：商用云 API

当前生效的三个 URL 都是：

```text
https://dashscope.aliyuncs.com/...
```

并且当前配置有非空 API Key，HTTP Header 使用 Bearer token。因此当前运行形态是：

```text
AskData 本地后端
→ 互联网 HTTPS
→ 阿里云 DashScope 托管模型服务
```

这里的“商用”指**调用部署形态**：模型由云厂商托管，项目按 API 服务方式访问。即便某个 Qwen 系列存在可下载权重，也不能因此把当前 `qwen3.7-plus + dashscope.aliyuncs.com` 说成本地开源模型部署。

### 6.2 当前不是本地模型的源码证据

当前仓库没有发现：

- Hugging Face/ModelScope 权重下载或本地权重目录配置；
- `transformers`、`torch`、`llama.cpp`、`ollama`、`vllm` 等推理依赖；
- CUDA/GPU device、tensor parallel、quantization 等推理配置；
- 本地模型进程启动脚本；
- `localhost`/`127.0.0.1` 模型 endpoint 的当前配置；
- 在 AskData 进程中加载 tokenizer/model 权重的代码。

`backend/requirements.txt:1-8` 只有 FastAPI、LangGraph、DuckDB、MCP、SQLGlot 等应用依赖。模型交互完全由 `urllib.request` 发往配置 URL。

### 6.3 当前不是 vLLM 的源码证据

vLLM 是一个推理与模型服务框架，不是 `qwen3.7-plus`、`text-embedding-v4` 这样的模型 ID。

当前项目没有：

- `vllm` 包依赖或 `from vllm ...`；
- `vllm serve ...` / `python -m vllm...` 启动命令；
- 指向本机 vLLM server 的有效 `LLM_BASE_URL`；
- vLLM 特有的部署参数。

所以当前结论只能是：**没有使用 vLLM。** 不能因为 Chat URL 采用 OpenAI-compatible 路径，就认为服务端一定是 vLLM；当前 host 已明确是 DashScope。

### 6.4 代码是否允许换成本地 OpenAI-compatible Chat 服务

结构上可以配置，但前提是服务实现项目期待的协议。

Chat 最少要满足：

```text
POST <LLM_BASE_URL>/chat/completions
Authorization: Bearer <非空值>
Request:
  model
  messages[system,user]
  temperature
  stream=false
Response:
  choices[0].message.content
```

因此，如果某个本地 vLLM server 暴露上述兼容接口，可以把：

```text
LLM_BASE_URL
LLM_MODEL
LLM_API_KEY
```

改为该服务的 base URL、served model name 和非空鉴权值。这里是在说明代码的可配置边界，不代表当前已经这样部署，也不代表任意 vLLM 版本/模型都必然兼容。

### 6.5 仅替换 Chat 还不够

数据库 Query 的完整成功路径还硬依赖 Embedding 与 Rerank：

#### Embedding 服务必须满足

```text
POST <EMBEDDING_BASE_URL 或 LLM_BASE_URL>/embeddings
Request:
  model
  input: list[str]
  dimensions
  encoding_format="float"
Response:
  data[*].index
  data[*].embedding
```

如果本地 Chat server 不同时提供该协议，就必须设置独立 `EMBEDDING_BASE_URL` 和匹配的 `EMBEDDING_MODEL`/维度。

#### Rerank 服务必须满足

```text
POST <RERANK_BASE_URL>/reranks
Request:
  model
  query
  documents
  top_n
  instruct
Response:
  results[*].index
  results[*].relevance_score 或 score
```

当前 Rerank 协议是项目明确写死的 `/reranks` 形状。某个本地 vLLM 版本或其它 reranker server 是否原生支持完全相同的 endpoint/payload/response，**仅从本仓库无法确认，必须针对实际服务运行验证**。不能只把 `LLM_BASE_URL` 改成 vLLM，就认为 Hybrid Retrieval 已经全部本地化。

### 6.6 三种部署状态对比

| 状态 | Chat | Embedding | Rerank | 当前项目情况 |
|---|---|---|---|---|
| 当前有效配置 | DashScope `qwen3.7-plus` | DashScope `text-embedding-v4` | DashScope `qwen3-rerank` | **正在使用** |
| 源码默认配置 | DashScope `qwen-plus` | DashScope `text-embedding-v4` | DashScope `qwen3-rerank` | 没有环境覆盖时使用 |
| 全本地部署 | 本地兼容 Chat 服务 | 本地兼容 Embedding 服务 | 本地兼容 `/reranks` 服务 | **仓库未配置、未证明可直接运行** |

### 6.7 哪些数据会离开本机发送到 DashScope

按当前云配置，以下内容会经过后端发送给外部模型服务：

- 用户原问题、近期轻量会话上下文：RequestPreprocessor；
- FieldDocument 的 `semantic_text`：索引首次建立/重建时的 Embedding；
- retrieval terms 拼接文本：每次 query Embedding；
- 完整 standalone query 与 candidate `rerank_text`：Rerank；
- Schema graph、retrieval hits、用户确认字段/参数、MCP Tool Schema：SingleDatabaseAgent；
- SQL、columns、限定行数的数据库 rows、Schema context：ResponseGenerator.finalize；
- 需要摘要的旧会话轮次：ShortTermMemory。

DuckDB 和 CSV 查询本身在本地执行，但成功后的部分 rows 会为了生成文字说明而发送给 Chat 模型。当前 `CONTEXT_TABLE_ROW_LIMIT` 有效值为 50，所以 finalizer 最多取前 50 行进入 Prompt（`response_generator.py:44-47` 与 `config.py:69`）。

这也是判断云/本地部署时的重要边界：将 Chat 改成本地不仅改变回答生成位置，也会改变 Schema、查询结果和会话信息的数据出站范围。

---

## 7. 最终结论

### 调用的是什么大模型？

生成与 Agent 决策统一使用当前配置的 **`qwen3.7-plus`**。另外还有两个非生成模型：**`text-embedding-v4`** 和 **`qwen3-rerank`**。

### 是商用模型还是本地模型？

当前是 **阿里云 DashScope 托管的商用云 API 调用方式**。证据是实际有效的 `https://dashscope.aliyuncs.com/...` endpoints、Bearer API Key 和 raw HTTP 请求代码。

### 是自己配置的本地模型吗？

**不是。** 仓库当前没有本地权重加载、推理依赖、本地模型 endpoint 或模型 server 启动逻辑。

### 是 vLLM 模型吗？

**不是。** vLLM 是服务框架；当前仓库没有使用或启动 vLLM，当前远端服务是 DashScope。

### 能否以后接 vLLM？

Chat 层具有改接 OpenAI-compatible endpoint 的基础，但整条数据库问答链还要求兼容的 Embedding 和 `/reranks` 服务，并且当前客户端强制非空 API Key。是否能无代码改动接入某个具体 vLLM 部署，必须对该部署的三类 endpoint 和返回 JSON 做实测，当前源码不能直接保证。

用一句话总结：

> **AskData 当前是“本地 Agent/Workflow/Retrieval/DuckDB 编排 + 阿里云 DashScope 三类远程模型 API”，不是本地 vLLM 推理。**

