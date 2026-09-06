# AskData Studio 数据端可行性调研报告

> 调研范围：**仅数据本身**（数据源、Schema、查询结果结构），不涉及 Agent 流程 / Skill / MCP 调用链设计，不给出改造方案。
> 调研时间：2026-08-25
> 所有探查脚本与原始输出位于 `./data_probe/`（未修改 backend / frontend 任何文件）。

---

## 目录

- [调研方法与可复现说明](#调研方法与可复现说明)
- [第一部分：数据源与 Schema 现状摸底](#第一部分数据源与-schema-现状摸底)
- [第二部分：查询结果的真实结构检查](#第二部分查询结果的真实结构检查)
- [第三部分：支撑 Repository + Derive 的差距分析](#第三部分支撑-repository--derive-的差距分析)
- [总结表](#总结表)

---

## 调研方法与可复现说明

本项目 `backend/.venv` 的 `pyvenv.cfg` 指向了失效的绝对路径
（`C:\Users\Administrator\Desktop\code\askdata_studio\...`），venv 的 `python.exe` 无法直接启动。
探查时改用内置解释器 + venv 的 site-packages，**未修改项目任何文件**：

```bash
cd D:/agent_study/askdata_studio
PYTHONPATH="D:/agent_study/askdata_studio/backend/.venv/Lib/site-packages" \
  ./backend/.python311/python.exe -X utf8 data_probe/probe_0X_xxx.py
```

| 脚本 | 作用 | 原始输出 |
| --- | --- | --- |
| `data_probe/probe_01_csv_profile.py` | CSV 体量、字段类型、取值分布、空值 | `out_01_csv_profile.json` |
| `data_probe/probe_02_execution_shape.py` | 走真实 `DuckDbEngine`，抓取 `SqlExecution` / `DatabaseQueryResult` 结构 | `out_02_execution_shape.json` |
| `data_probe/probe_03_signal_feasibility.py` | 排名/占比/合计/完成率/环比/同比 可算性验证 | `out_03_signal_feasibility.json` |
| `data_probe/probe_04_dtype_and_truncation.py` | 物理列类型 vs 静态 Schema 类型；截断行为精确验证 | `out_04_dtype_and_truncation.json` |
| `data_probe/probe_05_result_metadata_heuristics.py` | 端到端 `QueryResult` 结构；前后端两套列元信息启发式对照 | `out_05_result_metadata.json` |
| `data_probe/probe_06_verify_claims.py` | 核实 `cursor.description` 确实携带 `type_code`；样例数值二次核对 | `out_06_verify_claims.json` |

---

## 第一部分：数据源与 Schema 现状摸底

### 1.1 数据存储形式

**结论：100% Mock 数据，没有任何真实数据库连接。**

存储介质是 **CSV 文件**，运行时由 DuckDB 以 **内存视图** 方式挂载，全程只读。

`backend/app/querying/duckdb_engine.py:54-73`：

```python
@contextmanager
def connect(self, database: str) -> Iterator[duckdb.DuckDBPyConnection]:
    """创建内存连接并将 CSV 文件注册为只读视图。"""
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

要点：
- 每次请求新建一个 `:memory:` 连接，CSV 文件名即 SQL 表名，**无持久化数据库文件**。
- `sample_size=-1` 表示全量扫描推断类型，类型推断是可靠的（见 §1.2.4）。
- 数据由 `backend/app/demo_data.py` 用固定随机种子 `seed=20260815` 生成，**可复现**
  （`backend/seed_demo_data.py` 为入口脚本）。

#### 存放路径与格式

| 项 | 值 |
| --- | --- |
| 数据根目录 | `backend/data/databases/`（`duckdb_engine.py:21` `DATABASE_ROOT`） |
| 唯一数据库 | `askdata_mock`（目录名即数据库名） |
| 文件格式 | CSV，`utf-8-sig`（带 BOM），逗号分隔（`demo_data.py:76`） |
| 数据库数量 | **1 个**。多库路径 `_run_multi_database` 明确返回「尚未启用」（`query_graph.py:340-348`） |

#### 无效 / 孤儿数据文件（重要）

`backend/data/` 下存在若干**代码中完全没有引用**的历史遗留文件，调研时容易误判为数据源：

| 文件 | 大小 | 实际状态 |
| --- | --- | --- |
| `backend/data/askdata_mock.db` | 94 KB | **孤儿 SQLite 库**。含 `orders_current`(246行) / `orders_history`(489行) / `customers`(34行) / `products`(15行) / `sales_targets`(8行) / `saved_memories`(1行)。行数与当前 CSV **不一致**（CSV 为 240/480/30/12）。`grep` 全项目 `.py` 无任何引用，属于早期 SQLite 版本残留。 |
| `backend/data/schema_index.json` | 733 KB | **过期索引**。signature `29d3207b0722a982`，文档结构为旧版（**缺 `database_id` 字段**）。代码只读写 `schema_store.json`。 |
| `backend/data/schema_index_local_test.json` | 81 KB | 同上，旧版结构的本地测试残留。 |

**当前唯一生效的索引文件**是 `backend/data/schema_store.json`
（`backend/app/retrieval/service.py:42`：`self.index_path = index_path or BASE_DIR / "data" / "schema_store.json"`），
signature `749a2820ef726ef3`，30 个字段文档，embedding 来源 `text-embedding-v4`，向量维度 1024。

> 这三个孤儿文件对 Repository 的直接影响：**「哪份数据是权威的」当前没有任何机制声明**，
> 靠人工阅读代码才能判断。

### 1.2 表清单与用途

数据库 `askdata_mock`，共 **5 张表 / 30 个字段**，全部登记在
`backend/app/database.py` 的 `SCHEMA` 常量中（`database.py:42-108`）。

| 表名 (SQL) | 业务标签 | 域 | 行数 | 主键 | 用途 |
| --- | --- | --- | --- | --- | --- |
| `orders_current` | 当前订单明细 | 销售订单 | **240** | `order_id` | 2026-08 当月订单交易明细，支撑「本月/当前/近期」销售查询 |
| `orders_history` | 历史订单明细 | 销售订单 | **480** | `order_id` | 2026-06 ~ 2026-07 归档订单，支撑历史趋势与跨月对比 |
| `customers` | 客户信息 | 客户经营 | **30** | `customer_id` | 客户名称/等级/地区维度表 |
| `products` | 产品信息 | 产品经营 | **12** | `product_id` | 产品名称/类别维度表 |
| `sales_targets` | 地区销售目标 | 销售计划 | **8** | `target_id` | 按「月份 × 地区」的销售目标，用于完成率与目标对比 |

**关键结构特征**：`orders_current` 与 `orders_history` 是**同构分表**——
两者共用同一份字段定义常量 `ORDER_FIELDS`（`database.py:51` 与 `database.py:61` 都引用它），
差别仅在于时间范围。**这意味着任何跨月分析都必须 UNION 两张表**（详见 §3.C）。

#### 表间关系

`backend/app/database.py:111-156` 定义了 6 条关系，分两类：

```python
# 外键关系（默认 relation_type = foreign_key）
orders_current.customer_id  = customers.customer_id      # 当前订单所属客户
orders_history.customer_id  = customers.customer_id      # 历史订单所属客户
orders_current.product_id   = products.product_id        # 当前订单对应产品
orders_history.product_id   = products.product_id        # 历史订单对应产品

# 业务关系（relation_type = "business"）
orders_current.region = sales_targets.region   # description: "...月份需额外对齐"
orders_history.region = sales_targets.region   # description: "...月份需额外对齐"
```

**这里有一个对 Derive 极其关键的隐患**：
`orders_* → sales_targets` 的关联只声明了 `region` 一个键，月份对齐要求
**只以自然语言写在 `description` 里**（`database.py:145`：`"...月份需额外对齐"`），
而 `SchemaGraphBuilder._bfs`（`retrieval/graph.py:147-171`）在构图时只搬运
`left_field`/`right_field` 两个字段，**不解析 description**。
实测这条关系被误用时的后果见 §3.C「完成率」。

### 1.3 Schema 组织方式

三层 Schema 的存放位置完全不同：

| 层级 | 存放位置 | 形态 | 是否结构化 |
| --- | --- | --- | --- |
| **表级** | `backend/app/database.py` `SCHEMA` | 源码内 Python 字面量常量 | ✅ 结构化 dict |
| **字段级** | 同上，`_field()` 工厂函数 | 源码内 Python 字面量常量 | ✅ 结构化 dict |
| **数据级** | `backend/data/schema_store.json` | **构建索引时动态探查生成** | ❌ **压成自然语言字符串** |

#### 表级 / 字段级：静态源码常量

`backend/app/database.py:9-26` 定义了字段的固定 7 元组：

```python
def _field(name, label, field_type, description, aliases, role, aggregation="none") -> dict:
    return {
        "name": name, "label": label, "type": field_type,
        "description": description, "aliases": aliases,
        "role": role, "aggregation": aggregation,
    }
```

**注意**：Schema 是**硬编码在源码里的**，不是数据库元数据、也不是可编辑的配置文件。
新增表或字段必须改 Python 源码并重建索引
（`SchemaIndex._schema_signature()` 对 `SCHEMA + RELATIONS` 做 SHA256，签名变化即触发重建，`retrieval/service.py:430-441`）。

#### 数据级：索引构建时探查，但产物是字符串

`backend/app/retrieval/service.py:311-369` `_append_table_documents()` 在构建字段索引时，
**真的连上 DuckDB 跑了 SQL** 去取样例和分布：

```python
samples = [                                    # service.py:316-322
    DuckDbEngine._json_value(row[0])
    for row in connection.execute(
        f'SELECT DISTINCT "{field["name"]}" FROM "{table["id"]}" '
        f'WHERE "{field["name"]}" IS NOT NULL LIMIT 5'
    ).fetchall()
]
profile = self._field_profile(connection, table["id"], field)
```

`_field_profile()`（`service.py:371-385`）按类型分三支：

```python
if field["type"] in {"数值", "整数"}:
    row = connection.execute(f"SELECT MIN({column}), MAX({column}), AVG({column}) FROM {table}").fetchone()
    return f"最小值 {row[0]}，最大值 {row[1]}，平均值 {average}"      # <-- 返回 str
if field["type"] == "日期":
    row = connection.execute(f"SELECT MIN({column}), MAX({column}) FROM {table}").fetchone()
    return f"范围 {row[0]} 至 {row[1]}"                              # <-- 返回 str
count = connection.execute(f"SELECT COUNT(DISTINCT {column}) FROM {table}").fetchone()[0]
return f"约 {count} 个不同值"                                        # <-- 返回 str
```

> **这是数据级 Schema 的核心缺陷**：min/max/avg/distinct_count 这些数值**确实被算出来了**，
> 但立刻被 f-string 拼成一句中文，只为喂给 embedding / rerank / prompt。
> 落到 `schema_store.json` 里的 `profile` 是 `"最小值 0.0，最大值 314067.87，平均值 65244.28"`
> 这样一个**不可程序化消费的字符串**。Derive 想拿 max 值必须去正则解析中文句子。
>
> 同时缺失：**null 比例、行数、distinct 数（数值/日期字段没有）、精度、单位**。

#### 抽样检查：3 张核心表的完整 Schema

---

##### ① `orders_current` — 当前订单明细（240 行）

**表级描述**（`database.py:43-52`）

| 属性 | 值 |
| --- | --- |
| `id` | `orders_current` |
| `label` | 当前订单明细 |
| `database` | `askdata_mock` |
| `domain` | 销售订单 |
| `description` | 2026年8月当前订单交易明细，适合本月、当前和近期销售查询 |
| `business_terms` | `["本月订单", "当前销售", "实时成交"]` |
| `primary_key` | `["order_id"]` |
| 关联关系 | → `customers`（customer_id, 外键）<br>→ `products`（product_id, 外键）<br>→ `sales_targets`（region, **business 类型，月份需额外对齐**） |

**字段级描述**（`database.py:29-39`，共 9 字段）

| 字段名 | label | 静态类型 | **物理类型** | role | aggregation | 业务含义 | 主/外键 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `order_id` | 订单编号 | 整数 | `BIGINT` | identifier | count | 订单唯一编号，可用于订单计数 | **PK** |
| `region` | 销售地区 | 文本 | `VARCHAR` | dimension | group | 订单归属的销售大区 | — |
| `category` | 产品类别 | 文本 | `VARCHAR` | dimension | group | 订单中产品所属的业务品类 | 冗余自 products |
| `order_amount` | 订单金额 | 数值 | `DOUBLE` | **metric** | sum | 优惠和退款处理前的订单原始金额 | — |
| `paid_amount` | 实付金额 | 数值 | `DOUBLE` | **metric** | sum | 客户实际支付金额，可用于计算实际成交金额 | — |
| `status` | 订单状态 | 文本 | `VARCHAR` | filter | group | 订单当前支付或退款状态 | — |
| `order_date` | 下单日期 | 日期 | `DATE` | **time** | group | 订单创建日期，格式为 YYYY-MM-DD | — |
| `customer_id` | 客户编号 | 整数 | `BIGINT` | foreign_key | none | 关联客户信息表的客户标识 | **FK→customers** |
| `product_id` | 产品编号 | 整数 | `BIGINT` | foreign_key | none | 关联产品信息表的产品标识 | **FK→products** |

**数据级信息**（实测，`out_01` + `out_04`）

| 字段 | distinct | null | 取值范围 / 分布 | `schema_store.json` 里的 `profile`（原文） |
| --- | --- | --- | --- | --- |
| `order_id` | 240 | 0 | 10001 ~ 10240，连续无缺号 | `"最小值 10001，最大值 10240，平均值 10120.5"` |
| `region` | 4 | 0 | 华东70 / 华南65 / 华北54 / 西南51 | `"约 4 个不同值"` |
| `category` | 4 | 0 | 企业服务64 / 安全服务61 / 智能硬件59 / 数据产品56 | `"约 4 个不同值"` |
| `order_amount` | 240 | 0 | 8193.6 ~ 360180.18，SUM=19,644,867.74 | `"最小值 8193.6，最大值 360180.18，平均值 81853.62"` |
| `paid_amount` | 209 | 0 | 0.0 ~ 314067.87，SUM=15,658,626.69，**32 个 0 值** | `"最小值 0.0，最大值 314067.87，平均值 65244.28"` |
| `status` | 3 | 0 | 已支付208 / 已取消17 / 已退款15 | `"约 3 个不同值"` |
| `order_date` | 31 | 0 | 2026-08-01 ~ 2026-08-31（**满月**） | `"范围 2026-08-01 至 2026-08-31"` |
| `customer_id` | 30 | 0 | 101 ~ 130（全客户覆盖） | `"最小值 101，最大值 130，平均值 115.31"` |
| `product_id` | 12 | 0 | 101 ~ 112（全产品覆盖） | `"最小值 101，最大值 112，平均值 106.56"` |

样例值（`schema_store.json` `samples`，每字段 5 条 DISTINCT）：
`paid_amount` → `[0.0, 101799.64, 187867.43, 87730.57, 21008.48]`；
`order_date` → `["2026-08-18", "2026-08-26", "2026-08-29", "2026-08-30", "2026-08-22"]`。

> **`paid_amount` 的 32 个 0 值不是脏数据**，而是业务规则：
> `demo_data.py:136-138` 中，`status != '已支付'` 时 `paid_amount` 直接置 0。
> 这条规则**在 Schema 里没有任何地方声明**，只能从生成代码倒推。它直接造成一个口径陷阱，见 §1.4.5。

---

##### ② `sales_targets` — 地区销售目标（8 行）

**表级描述**（`database.py:92-107`）

| 属性 | 值 |
| --- | --- |
| `id` / `label` | `sales_targets` / 地区销售目标 |
| `domain` | 销售计划 |
| `description` | 按月份和地区制定的销售目标，用于目标完成率和实际销售对比 |
| `business_terms` | `["业绩目标", "销售预算", "目标完成率"]` |
| `primary_key` | `["target_id"]`（**实际业务主键应为 `(target_month, region)`，未声明**） |

**字段级描述**

| 字段名 | label | 静态类型 | **物理类型** | role | aggregation | 业务含义 |
| --- | --- | --- | --- | --- | --- | --- |
| `target_id` | 目标编号 | 整数 | `BIGINT` | identifier | none | 销售目标记录的唯一编号 |
| `target_month` | 目标月份 | **日期** | **`VARCHAR`** ⚠️ | **time** | group | 销售目标对应月份，格式为 YYYY-MM |
| `region` | 销售地区 | 文本 | `VARCHAR` | dimension | group | 目标所属销售大区 |
| `target_amount` | 销售目标 | 数值 | **`BIGINT`** ⚠️ | **metric** | sum | 该地区当月计划完成的销售金额 |
| `owner_name` | 区域负责人 | 文本 | `VARCHAR` | dimension | group | 负责该地区销售目标的人员 |

> ⚠️ **两处静态 Schema 与物理类型不一致**（`out_04_dtype_and_truncation.json`）：
> - `target_month`：静态声明 **`日期`**，物理是 **`VARCHAR`**（值形如 `"2026-07"`，DuckDB 无法推断为 DATE）。
>   → `_field_profile` 会走「日期」分支执行 `MIN/MAX`，字符串比较**恰好**对 `YYYY-MM` 有效，属于巧合正确。
>   → 但对 Derive 而言，**跨表时间对齐时一边是 `DATE` 一边是 `VARCHAR`，必须显式 `strftime` 转换**，
>     而 Schema 里两个字段的 `type` 都写着「日期」，看不出这个差异。
> - `target_amount`：静态声明 `数值`，物理是 `BIGINT`（整数）。与 `paid_amount` 的 `DOUBLE` 相除时需注意整数语义。

**数据级信息**（实测）

| 字段 | distinct | null | 全部取值 |
| --- | --- | --- | --- |
| `target_month` | **2** | 0 | `2026-07`(4行) / `2026-08`(4行) |
| `region` | 4 | 0 | 华东/华南/华北/西南，各 2 行 |
| `target_amount` | 8 | 0 | 1,100,000 ~ 2,200,000；月合计：2026-07=**5,900,000**，2026-08=**6,900,000** |
| `owner_name` | 4 | 0 | 林晓/周岚/宋言/陈川，各 2 行 |

> **目标覆盖缺口**：订单数据覆盖 **2026-06 / 07 / 08** 三个月，目标只覆盖 **07 / 08** 两个月。
> **2026-06 有实际值但没有目标值**，该月完成率不可计算。

---

##### ③ `customers` — 客户信息（30 行）

**表级描述**（`database.py:64-77`）

| 属性 | 值 |
| --- | --- |
| `id` / `label` | `customers` / 客户信息 |
| `domain` | 客户经营 |
| `description` | 客户名称、客户等级和所在地区，用于客户维度分析 |
| `business_terms` | `["客户画像", "客户分层", "企业客户"]` |
| `primary_key` | `["customer_id"]` |

**字段级 + 数据级**

| 字段名 | label | 静态类型 | 物理类型 | role | 业务含义 | distinct | null | 取值分布 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `customer_id` | 客户编号 | 整数 | `BIGINT` | identifier | 客户唯一标识，可与订单关联 | 30 | 0 | 101~130 |
| `customer_name` | 客户名称 | 文本 | `VARCHAR` | dimension | 企业客户的展示名称 | 30 | 0 | 如「远景科技」「云帆数据」 |
| `customer_level` | 客户等级 | 文本 | `VARCHAR` | dimension | 战略、重点或普通客户分层 | **3** | 0 | 普通客户14 / 战略客户9 / 重点客户7 |
| `region` | 客户地区 | 文本 | `VARCHAR` | dimension | 客户注册或主要经营所在大区 | 4 | 0 | 华东8 / 华南8 / 华北7 / 西南7 |

> **`customer_level` 是有序分类（战略 > 重点 > 普通），但 Schema 里没有任何顺序声明**，
> `role` 只是 `dimension`。Derive 做「客户分层排序」时无法确定顺序，只能靠 LLM 常识。

---

### 1.4 Schema 中是否包含「指标口径」/「业务计算规则」

**结论：没有。完全缺失，且现有的两个"疑似"字段都是死的。**

对全项目 `.py` / `.json` / `.md` 搜索
`口径 | 指标定义 | 计算规则 | business_rule | metric_definition | formula | 同比 | 环比 | 完成率` 的结果：

| 命中位置 | 内容 | 性质 |
| --- | --- | --- |
| `app/database.py:97` | `"description": "按月份和地区制定的销售目标，用于目标完成率和实际销售对比"` | **自由文本**，非结构化 |
| `app/database.py:98` | `"business_terms": ["业绩目标", "销售预算", "目标完成率"]` | **检索关键词**，用于 BM25/embedding，非计算定义 |
| `app/skills/database_query/SKILL.md:22` | 「不自行补充会改变业务口径的条件」 | **给 LLM 的自然语言约束** |
| `app/services/short_term_memory.py:164` | 「保留用户目标、已确认业务口径…」 | 会话摘要 prompt |

即：**不存在任何形式的指标注册表 / 计算公式 / 口径定义**。
「销售额 = SUM(paid_amount) WHERE status='已支付'」这类口径，
**每次都由 LLM 从字段 description 里现场推断并写进 SQL**，没有任何一处固化。

#### 两个「看起来像口径」但实际是死代码的字段

**① `aggregation`（字段级聚合方式）**

`database.py:16,25` 定义，`models.py:10,93` 声明为 `Literal["auto","group","sum","avg","count","max","min"]`。
`orders_current.paid_amount` 明确标了 `aggregation="sum"`。

但全项目 grep `aggregation` 的所有命中：

```
app/database.py:16,25        # 定义
app/models.py:10,93          # Pydantic 声明
frontend/src/App.vue:209     # aggregation: "auto" as const   <-- 前端恒定写死 "auto"
frontend/src/App.vue:387     # aggregation: "auto"
frontend/src/types.ts:8,175
```

> **没有任何一行业务逻辑读取 `aggregation` 的值**。它不参与 SQL 生成、不参与结果解释、
> 也不进入 embedding 文本（`_append_table_documents` 拼 `keyword_text`/`semantic_text`/`rerank_text` 时都没有它）。
> **这是一个已定义但完全未消费的字段。**

**② `role`（字段业务角色）**

`role` 取值有 `identifier / dimension / metric / filter / time / foreign_key`，语义质量不错。
它的消费路径是：

```
database.py  → retrieval/service.py:361 (field_role)
             → store.py:24 FieldDocument.field_role
             → rerank_text 字符串："...；角色：metric；..."   (service.py:347)
             → graph.py:52  schema_graph.fields[].role
             → graph.py:112-126 context_text() 拼成 prompt 文本
```

> `role` **只被拼进给大模型看的文本**，从未被任何确定性逻辑用于判断。
> 尤其关键的是：**它没有跟随查询结果传递到下游**（见 §2.3）。
> 结果层的 metric/dimension 判定是另起炉灶的中文正则（见 §2.2）。

---

### 1.5 数据内容质量与特征

#### 1.5.1 数据量级

| 表 | 行数 | 量级 |
| --- | --- | --- |
| `orders_history` | 480 | 百行级 |
| `orders_current` | 240 | 百行级 |
| `customers` | 30 | 十行级 |
| `products` | 12 | 十行级 |
| `sales_targets` | 8 | 个位数 |
| **合计** | **770** | **千行以内** |

> 全库不足千行。这意味着**在 Derive 阶段做全量聚合、重算校验、交叉验证的成本几乎为 0**，
> 是一个有利条件。但同时也意味着**200 行返回上限的截断问题在明细查询中会真实触发**
> （`orders_current` 240 行 > 200，见 §2.3）。

#### 1.5.2 数值型字段的业务含义

**结论：数值字段业务含义清晰，但存在「ID 混在数值里」的问题。**

| 字段 | 业务语义 | 是否真·指标 |
| --- | --- | --- |
| `order_amount` | 金额（元），优惠/退款前原始额 | ✅ 金额型指标 |
| `paid_amount` | 金额（元），实际支付额 | ✅ 金额型指标 |
| `target_amount` | 金额（元），计划目标额 | ✅ 金额型指标（**目标值**） |
| `order_id` | 订单编号 | ❌ **标识符**，但可 `COUNT` 派生「订单数」（`aggregation="count"` 已标注但未被消费） |
| `customer_id` / `product_id` / `target_id` | 外键/主键 | ❌ 标识符 |

> 3 个真指标全部是「金额」，**没有比率型、次数型、完成率型的原生字段**——
> 所有比率/占比/完成率都必须**在查询时现场计算**，数据里不存这类列（见 §1.5.4 实测）。
> 另外，**"元" 这个单位在 Schema 里从未声明**，只在 `description` 中隐含（"订单金额"/"支付金额"）。

#### 1.5.3 时间 / 维度 / 指标字段的区分度

**结论：区分清晰，`role` 字段已正确标注。**

| 类别 | 字段 | 说明 |
| --- | --- | --- |
| **时间** (`role=time`) | `orders_*.order_date`（DATE，日粒度）<br>`sales_targets.target_month`（VARCHAR，月粒度） | ⚠️ **两者粒度和物理类型都不同**，跨表对齐需 `strftime(order_date,'%Y-%m')` |
| **维度** (`role=dimension`) | `region`（4值）、`category`（4值）、`customer_level`（3值）、`customer_name`（30值）、`product_name`（12值）、`owner_name`（4值） | 基数都很低，适合分组 |
| **指标** (`role=metric`) | `order_amount`、`paid_amount`、`target_amount` | 全为金额型 |
| **筛选** (`role=filter`) | `status`（3值：已支付/已取消/已退款） | 独立标为 filter，语义正确 |
| **标识** (`role=identifier/foreign_key`) | `*_id` 系列 | — |

**维度冗余一致性实测（`out_03`）**：

```
订单表 region   与 customers.region  不一致的行数 = 0
订单表 category 与 products.category 不一致的行数 = 0
```

> `orders_*` 冗余存了 `region` 和 `category`。实测**完全一致，无冲突**。
> 这是好消息（可以不 JOIN 直接分组），但也是隐患：
> **同一个业务维度存在两条取数路径**（`orders.region` vs `customers.region`），
> Schema 没有声明哪条是权威路径，不同 SQL 可能走不同路径，Derive 结果不可比。

#### 1.5.4 是否存在「目标值 / 预算值 / 上期值」

实测（`probe_03`，直连 `information_schema` 全列扫描）：

| 需要的值 | 是否存在 | 位置 / 说明 |
| --- | --- | --- |
| **目标值** | ✅ **存在** | `sales_targets.target_amount`，粒度 = 月 × 地区，仅覆盖 2026-07 / 2026-08 |
| **预算值** | ⚠️ **等同目标值** | 无独立预算列。`business_terms` 把「销售预算」列为 `target_amount` 的同义词（`database.py:98,104`） |
| **上期值 (MoM)** | ❌ **不存在为列** | 无 `prev_*` / `last_*` 列。**必须用 `LAG()` 窗口函数 + 跨表 UNION 现算** |
| **同期值 (YoY)** | ❌ **不存在，且不可算** | 全库只有 **2026** 一年、**3 个月**数据（见 §3.C） |

**目标值的量级校准问题（重要）**：

| 月份 | 实际销售额（SUM paid_amount, 已支付） | 目标合计 | 完成率 |
| --- | --- | --- | --- |
| 2026-06 | 14,096,078.76 | **无目标** | **不可算** |
| 2026-07 | 16,145,060.58 | 5,900,000 | 273.6% |
| 2026-08 | 15,658,626.69 | 6,900,000 | 226.9% |

按地区看 2026-08（`out_03` 「完成率_正确对齐」）：

| 地区 | 实际销售额 | 销售目标 | 完成率 |
| --- | --- | --- | --- |
| 西南 | 4,474,287.06 | 1,300,000 | **344.18%** |
| 华北 | 3,379,043.36 | 1,600,000 | **211.19%** |
| 华南 | 3,513,112.52 | 1,800,000 | **195.17%** |
| 华东 | 4,292,183.75 | 2,200,000 | **195.10%** |

> **完成率在算术上算得出来，但业务上完全失真**——目标值比实际值低 2~3.4 倍。
> `demo_data.py:42-51` 中 `sales_targets` 是**手写的固定常量**，
> 而订单金额是 `randomizer.uniform(8000, 120000) * level_multiplier` 随机生成的，
> **两者从未做过量级校准**。
>
> 对 Derive 的含义：完成率这个信号**管道能跑通，但产出的业务结论是错的**。
> 任何基于「完成率 > 100% 即达标」的判断在这份数据上会 100% 命中「全部超额完成」，
> 无法验证 Derive 逻辑的正确性。

#### 1.5.5 口径歧义实证：同一张表能算出 4 个不同的「销售额」

`probe_03` 对 `orders_current` 同时计算 4 种口径：

| 口径 | SQL | 结果 |
| --- | --- | --- |
| A：订单金额全量 | `SUM(order_amount)` | **19,644,867.74** |
| B：实付金额全量 | `SUM(paid_amount)` | **15,658,626.69** |
| C：订单金额仅已支付 | `SUM(CASE WHEN status='已支付' THEN order_amount END)` | **16,803,729.82** |
| D：实付金额仅已支付 | `SUM(CASE WHEN status='已支付' THEN paid_amount END)` | **15,658,626.69** |

**最大差异 25.5%（A vs B/D）**。用户问「本月销售额」时，四个答案都"合理"。

> **一个特别隐蔽的陷阱**：**B ≡ D**（两者完全相等）。
> 原因是 `demo_data.py:136-138` 让非「已支付」订单的 `paid_amount = 0`。
> 这意味着 **写不写 `WHERE status='已支付'` 对 `paid_amount` 的求和没有影响**——
> 一个漏写筛选条件的 SQL 在这份数据上**恰好也能得到正确结果**，
> 但换成真实数据（退款订单 `paid_amount ≠ 0`）就会立刻出错。
> 这类「侥幸正确」会让 Derive 的正确性验证失去意义。

---

## 第二部分：查询结果的真实结构检查

### 2.1 完整代码路径

SQL 执行成功后，结果的封装与传递链路如下（全部实测走通）：

```
① LLM 决策  SingleDatabaseAgent.prepare()            querying/single_database_agent.py:109
       │     mcp_client.call_tool("query_askdata_mock", {"sql": ...})
       ▼
② MCP 工具  query_database(sql)                       mcp_runtime/tools/database_tools.py:32-43
       │     engine.execute(database, sql, access_scope)
       ▼
③ 执行引擎  DuckDbEngine.execute()                    querying/duckdb_engine.py:33-51
       │     ★ 结果在这里第一次被封装 → SqlExecution
       ▼
④ 工具返回  DatabaseQueryResult (Pydantic)            mcp_runtime/schemas.py:21-28
       │     多了 database / row_count 两个字段
       ▼
⑤ 存入状态  state["mcp_execution"] = tool_result      workflows/query_graph.py:266-274
       │     ★ 变成普通 dict，类型信息丢失
       ▼
⑥ 重建对象  SqlExecution(**raw_execution)             workflows/query_graph.py:279-285
       │     ★ database / row_count 在这里被丢弃
       ▼
⑦ 组装响应  ResultBuilder.completed()                 workflows/result_builder.py:83-139
       │     ★ 这里用中文正则重新猜 metric/dimension
       ▼
⑧ API 响应  QueryResult (Pydantic) → JSON             models.py:62-83 / api/routes.py:123-129
```

### 2.2 返回给上层的数据结构是什么？

**三个不同的容器，逐层丢信息。**

#### ③ 核心结构：`SqlExecution`（Python **dataclass**）

`backend/app/querying/models.py:7-14` —— **全文如下，没有省略**：

```python
@dataclass
class SqlExecution:
    sql: str
    success: bool
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
```

**5 个字段，仅此而已。** 实测确认（`out_02`）：`SqlExecution` 字段 = `['columns','error','rows','sql','success']`。

产生它的代码 `duckdb_engine.py:41-49`：

```python
with self.connect(database) as connection:
    cursor = connection.execute(safe_sql)
    raw_rows = cursor.fetchmany(201)
    columns = [item[0] for item in cursor.description or []]   # ← 只取 description[0]，即列名
    rows = [
        {column: self._json_value(value) for column, value in zip(columns, row)}
        for row in raw_rows[:200]
    ]
return SqlExecution(safe_sql, True, columns, rows)
```

> **决定性的一行是 `columns = [item[0] for item in cursor.description or []]`。**
> DBAPI 的 `cursor.description` 是一个 7 元组序列
> `(name, type_code, display_size, internal_size, precision, scale, null_ok)`，
> DuckDB 在此提供了 **`type_code`（列的物理类型）**。
> 代码**只取了下标 `[0]`（列名），把 `type_code` 及其余 5 项全部丢弃**。
>
> 即：**dtype 在这一行、这一刻，是可得的，然后被主动丢掉了。**

**实测验证**（`probe_06`，对 §2.4 那条真实 SQL 打印 `cursor.description` 全部元组）：

| `description[i][0]`（被保留） | `description[i][1]` = **`type_code`（被丢弃）** | 元组长度 |
| --- | --- | --- |
| `销售地区` | **`VARCHAR`** | 7 |
| `销售额` | **`DOUBLE`** | 7 |
| `订单数` | **`BIGINT`** | 7 |
| `客单价` | **`DOUBLE`** | 7 |
| `销售目标` | **`BIGINT`** | 7 |
| `目标完成率` | **`DOUBLE`** | 7 |

> **6 列的 `type_code` 全部非空且准确**。
> 也就是说，`SqlExecution` 想要的 dtype **在构造它的那一行代码里就在手边**，
> 且能精确区分 `DOUBLE`（销售额、客单价、目标完成率）与 `BIGINT`（订单数、销售目标）——
> 这恰好是 Derive 判断"能否安全求和/相除"所需要的信息。


`_json_value()`（`duckdb_engine.py:144-150`）进一步做了类型擦除：

```python
@staticmethod
def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()      # ← DATE → str "2026-08-05"
    if isinstance(value, Decimal):
        return float(value)           # ← Decimal → float，精度丢失
    return value
```

> 实测（`out_02` Q3）：`order_date` 物理类型是 `DATE`，
> 但返回给上层的 Python 类型是 **`str`**。
> 下游拿到 `"2026-08-05"` **无法区分它是日期还是一个文本编码**。

#### ④ MCP 工具层：`DatabaseQueryResult`（Pydantic）

`backend/app/mcp_runtime/schemas.py:21-28`：

```python
class DatabaseQueryResult(BaseModel):
    database: str
    sql: str
    success: bool
    columns: list[str] = Field(default_factory=list, description="结果字段")
    rows: list[dict[str, Any]] = Field(default_factory=list, description="查询结果，最多200行")
    row_count: int = Field(default=0, description="返回结果行数")
    error: str | None = None
```

比 `SqlExecution` 多了 `database` 和 `row_count`。

> **但 `row_count` 的赋值是 `row_count=len(execution.rows)`**（`database_tools.py:41`），
> 即**截断后**的行数，**恒 ≤ 200**。它表达的是"我返回了几行"，
> **不是"符合条件的总共有几行"**。见 §2.3 的截断分析。

#### ⑥ 状态回传：类型信息二次丢失

`workflows/query_graph.py:266-285`：

```python
execution = decision["execution"]        # 这是 dict（MCP 工具结果序列化后）
return {"mcp_execution": execution, ...}
...
raw_execution = state.get("mcp_execution") or {}
execution = SqlExecution(
    sql=str(raw_execution.get("sql") or state.get("direct_sql") or ""),
    success=bool(raw_execution.get("success")),
    columns=list(raw_execution.get("columns") or []),
    rows=list(raw_execution.get("rows") or []),
    error=raw_execution.get("error"),
)
```

> `database` 和 `row_count` 在重建时**被显式丢弃**——`SqlExecution` 里根本没有这两个字段。
> 从此刻起，结果**连"来自哪个数据库"都不知道了**。

#### ⑧ 最终 API 响应：`QueryResult`

`models.py:62-83`，实测顶层 21 个字段（`out_05`）：

```
['analysis', 'analysis_sources', 'clarification', 'columns', 'execution_log',
 'interpretation', 'message', 'result_title', 'retrieval', 'route', 'route_reason',
 'rows', 'saved', 'schema_graph', 'sql', 'standalone_query', 'status', 'steps',
 'task_id', 'tool_calls', 'workflow_mode']
```

与数据结果直接相关的只有两个：

```python
columns: list[str] = []                    # models.py:71
rows: list[dict[str, Any]] = []            # models.py:72
```

> **`QueryResult` 顶层没有 `row_count`，也没有 `truncated`。**
> 行数信息只能通过 `len(rows)` 或 `tool_calls[0].row_count`（同样是截断后的值）获得。

### 2.3 每一列携带了哪些信息？

**答：只有列名。值是裸标量。没有任何列级元信息。**

`columns` 是 `list[str]`，`rows` 是 `list[dict]`，`dict` 的键就是列名字符串。
实测一个真实的完整结果（`probe_05`，走真实 `DuckDbEngine` + 真实 `ResultBuilder`）：

```json
{
  "columns": ["销售地区", "销售额", "订单数", "客单价", "销售目标", "目标完成率"],
  "rows": [
    {"销售地区": "西南", "销售额": 4474287.06, "订单数": 47,
     "客单价": 95197.6, "销售目标": 1300000, "目标完成率": 344.18},
    {"销售地区": "华东", "销售额": 4292183.75, "订单数": 56,
     "客单价": 76646.14, "销售目标": 2200000, "目标完成率": 195.1}
  ]
}
```

#### 逐项核对清单

| 要求的信息 | 是否存在 | 证据 / 位置 |
| --- | --- | --- |
| **列的数据类型 (dtype)** | ❌ **缺失** | `duckdb_engine.py:44` 只取 `cursor.description[i][0]`，丢弃 `type_code`。下游只能靠 `type(value)` 反推 Python 类型，且 `DATE` 已被 `_json_value` 转成 `str`。 |
| **列的业务角色 (metric/dimension/id)** | ⚠️ **只有一个不可靠的中文正则近似** | `result_builder.py:95-99`，见下方详述。Schema 里的 `field_role` **没有传下来**。 |
| **对应的原始 Schema 字段** | ❌ **完全缺失** | 结果列名是 LLM 在 SQL 里自由写的中文别名（Skill 明确要求「输出字段使用简短中文别名」，`database_query/SKILL.md:24`）。**没有任何 `column → table.field` 的映射**。 |
| **是否被 LIMIT / 截断** | ❌ **缺失，且是主动丢弃** | 见下方详述。 |
| **单位、精度、格式** | ❌ **后端完全缺失**；前端有一套独立的中文正则 | `ResultTableCard.vue:39-49`，见下方详述。 |
| **基础统计 (sum/max/min/null 比例)** | ❌ **完全缺失** | `SqlExecution` 没有任何统计字段。字段级统计只存在于 `schema_store.json` 的 `profile` **字符串**里，且是**全表**统计，与**本次查询结果**无关。 |

---

#### 详述 ①：业务角色 —— 后端的中文正则

`backend/app/workflows/result_builder.py:95-99`：

```python
metric_columns = [
    column for column in combined.columns
    if any(term in column for term in ("额", "数", "率", "平均", "目标"))
]
dimension_columns = [column for column in combined.columns if column not in metric_columns]
```

**这是全系统唯一的结果列角色判定**，判定依据是**列名里有没有这 5 个汉字**。
它的产物只写进 `Interpretation.metric` / `Interpretation.dimension` 两个**展示用字符串**
（`result_builder.py:117-118`），**不写回 `columns`，也不写进 `rows`**。

实测该规则在上面那个真实结果上的表现（`out_05`）：

| 列名 | 正确角色 | 规则判定 | 是否正确 |
| --- | --- | --- | --- |
| 销售地区 | dimension | dimension | ✅ |
| 销售额 | metric | metric（含「额」） | ✅ |
| 订单数 | metric | metric（含「数」） | ✅ |
| **客单价** | **metric** | **dimension** | ❌ **错判** |
| 销售目标 | metric | metric（含「目标」） | ✅ |
| 目标完成率 | metric | metric（含「率」） | ✅ |

生成的 `Interpretation` 实测值：

```json
{
  "metric": "销售额、订单数、销售目标、目标完成率",
  "dimension": "销售地区、客单价",     ← 客单价（平均客单价）被当成了分组维度
  "time_range": "本月",
  "table": "当前订单明细、地区销售目标"
}
```

在更广的列名上继续测（`out_05` `heuristic_disagreements`）：

| 列名 | 规则判定 | 实际应为 | 结果 |
| --- | --- | --- | --- |
| `客单价` | dimension | metric | ❌ |
| `环比百分比` | dimension | metric | ❌ （含「比」不含「率」） |
| `占比百分比` | dimension | metric | ❌ |
| `毛利` | dimension | metric | ❌ |
| `订单编号` | dimension | **identifier** | ❌ 规则只有 metric/dimension 二分，**没有 id 类别** |

> **结论：这套规则既不完备（无 id/time 类别），也不准确（4/16 明显错判），
> 更关键的是它的产物根本没有回写到结果数据结构上。**

---

#### 详述 ②：单位 / 精度 —— 前端另一套独立正则，且与后端冲突

`frontend/src/components/ResultTableCard.vue:39-49`：

```ts
function formatCell(value: unknown, column: string) {
  if (value === null || value === undefined || value === "") return "—"
  if (typeof value !== "number") return String(value)
  if (/金额|销售额|客单价|收入/.test(column)) {
    return new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", maximumFractionDigits: 0 }).format(value)
  }
  if (/率|占比/.test(column)) return `${(value * 100).toFixed(1)}%`
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })
}
```

**这是全系统唯一的单位/精度来源**，同样是列名中文正则，且**与后端那套规则互相独立、互不知晓**。

实测冲突（`out_05`）：

| 列名 | 后端 `result_builder` 判定 | 前端 `formatCell` 判定 | 冲突 |
| --- | --- | --- | --- |
| `客单价` | **dimension** | **currency(CNY)** → 隐含 metric | ⚠️ **直接矛盾** |
| `占比百分比` | **dimension** | **percent(×100)** → 隐含 metric | ⚠️ **直接矛盾** |
| `销售目标` | metric | number(2位小数) → 无货币格式 | ⚠️ 金额未按货币渲染 |
| `订单数` | metric | number(2位小数) | 一致 |

**并且已经产生了一个可复现的实际渲染错误**（`out_05` `percent_unit_demo`）：

```
列「目标完成率」
  SQL 返回值        = 344.18          （SQL 里已经写了 100.0 * a / b，已是百分数）
  前端 formatCell   = "34418.0%"      （再乘一次 100）
  正确应显示         = "344.18%"
```

> 根因：**「这一列的值是比率(0.34) 还是百分数(34.18)」这件事没有任何契约**。
> SQL 由 LLM 自由生成，可能写 `a/b`（比率），也可能写 `100.0*a/b`（百分数）。
> 项目自带测试 `tests/test_service.py:93` 里 mock 的 SQL 用的是
> `ROUND(a.sales / NULLIF(t.target_amount, 0), 4)` —— **比率口径**；
> 而实际数据探查中 LLM 完全可能写成百分数口径。**前端只能盲猜，猜错就放大 100 倍。**

---

#### 详述 ③：截断 —— 信息在引擎里存在，被主动丢弃

`duckdb_engine.py:43-48`：

```python
raw_rows = cursor.fetchmany(201)        # ← 故意多取 1 行
columns = [item[0] for item in cursor.description or []]
rows = [
    {column: self._json_value(value) for column, value in zip(columns, row)}
    for row in raw_rows[:200]           # ← 只保留 200 行，第 201 行丢弃
]
```

`fetchmany(201)` 这个 `+1` 的写法，**唯一的用途就是判断"是否还有更多数据"**。
实测验证（`probe_04`）：

```
表内总行数            = 240
fetchmany(201) 实取   = 201          ← 引擎确实拿到了第 201 行
返回给上层            = 200          ← 被切掉
引擎是否知道被截断     = True         ← len(raw_rows) > 200
SqlExecution 截断字段  = 无           ← 这个 True 没有被记录到任何地方
```

`SqlExecution` 字段实测 = `['columns','error','rows','sql','success']`，**没有 `truncated` / `total_rows`**。

> **后果**：上层拿到 200 行 `orders_current` 明细，
> 无法知道真实是 240 行。
> - `row_count` = 200（`database_tools.py:41` 的 `len(execution.rows)`）
> - 若在此基础上 Derive 算「合计」「占比」「排名」，**结果基于 83% 的数据，且无人知情**。
>
> 这是**当前对 Derive 威胁最大的单点问题**：它不是"信息缺失"，而是"信息被算出来后丢弃"，
> 且**静默失败**——不报错、不告警、结果看起来完全正常。

**另有一处隐性约束**：`ResponseGenerator.finalize()`（`response_generator.py:46`）
只把 `execution.rows[:self.table_row_limit]` 喂给 LLM 做结果说明，
`table_row_limit` 默认 **50**（`config.py:69` `CONTEXT_TABLE_ROW_LIMIT`）。
即 LLM 生成的 `analysis` 文字**最多只看到 50 行**，
但 `analysis` 会被当成对**全部 200 行**的描述返回给用户。

---

#### 详述 ④：结果列名不稳定（同一问题两次不同列名）

`backend/data/saved_memories.json` 是**真实运行产生的持久化记录**，里面有两条同一问题的结果：

```json
[
  {
    "task_id": "23ad750ad514",
    "query": "查询本月各地区销售额",
    "columns": ["地区", "销售额"],                       ← 第一次
    "rows": [{"地区": "西南", "销售额": 4474287.0600000005}, ...],
    "created_at": "2026-08-22T16:54:47"
  },
  {
    "task_id": "9d4aef8a2c10",
    "query": "查询本月各地区销售额",
    "columns": ["销售地区", "销售额"],                    ← 第二次，同一个问题
    "rows": [{"销售地区": "西南", "销售额": 4474287.0600000005}, ...],
    "created_at": "2026-08-21T21:02:39"
  }
]
```

> **完全相同的自然语言问题，两次运行产生了不同的列名**（`地区` vs `销售地区`），
> 数值完全一致。项目测试 `tests/test_service.py:358` 硬编码断言
> `self.assertEqual(result.columns, ["销售地区", "销售额"])`，
> 说明这个列名**只是某一次 LLM 输出的快照**。
>
> 对 Derive 的含义：**任何按列名取值的确定性逻辑都是不可靠的**
> （`row["销售额"]` 可能 KeyError，`row["地区"]` 时有时无），
> **跨两次查询结果做对比（如环比、同期对比）时无法对齐列**。

另注意数值 `4474287.0600000005` —— **IEEE 双精度噪声被原样持久化**，
既无精度声明也无舍入契约。

### 2.4 一个真实的完整查询结果样例

以下是 `probe_05` 用**真实 `DuckDbEngine` 执行 + 真实 `ResultBuilder.completed()` 组装**
产出的完整 `QueryResult`（`out_05_result_metadata.json` 中 `queryresult_full_sample`，此处省略
`steps`/`execution_log`/`retrieval` 等与数据结构无关的字段）：

```json
{
  "task_id": "probe-task-0001",
  "status": "completed",
  "route": "database_query",
  "message": "查询完成",

  "sql": "SELECT o.region AS 销售地区, ROUND(SUM(o.paid_amount), 2) AS 销售额, COUNT(o.order_id) AS 订单数, ROUND(SUM(o.paid_amount) / COUNT(o.order_id), 2) AS 客单价, MAX(t.target_amount) AS 销售目标, ROUND(100.0 * SUM(o.paid_amount) / MAX(t.target_amount), 2) AS 目标完成率 FROM orders_current o JOIN sales_targets t ON o.region = t.region AND t.target_month = '2026-08' WHERE o.status = '已支付' GROUP BY o.region ORDER BY 销售额 DESC",

  "columns": ["销售地区", "销售额", "订单数", "客单价", "销售目标", "目标完成率"],

  "rows": [
    {"销售地区": "西南", "销售额": 4474287.06, "订单数": 47, "客单价": 95197.6,  "销售目标": 1300000, "目标完成率": 344.18},
    {"销售地区": "华东", "销售额": 4292183.75, "订单数": 56, "客单价": 76646.14, "销售目标": 2200000, "目标完成率": 195.1},
    {"销售地区": "华南", "销售额": 3513112.52, "订单数": 58, "客单价": 60570.91, "销售目标": 1800000, "目标完成率": 195.17},
    {"销售地区": "华北", "销售额": 3379043.36, "订单数": 47, "客单价": 71894.54, "销售目标": 1600000, "目标完成率": 211.19}
  ],

  "interpretation": {
    "metric": "销售额、订单数、销售目标、目标完成率",
    "dimension": "销售地区、客单价",
    "time_range": "本月",
    "table": "当前订单明细、地区销售目标",
    "assumptions": ["Schema字段经过Rerank阈值筛选", "用户拖入字段为确定性约束"]
  },

  "result_title": "本月各地区销售额与目标完成率",
  "analysis": "示例说明",
  "workflow_mode": "single_database_agent"
}
```

**对这个样例的逐列诊断**：

| 列 | 值类型(Python) | dtype 已知？ | 角色已知？ | 单位已知？ | 溯源到 Schema？ | 精度/量纲契约？ |
| --- | --- | --- | --- | --- | --- | --- |
| 销售地区 | `str` | ❌ | ⚠️ 正则猜 dimension ✅ | — | ❌ 无法知道来自 `orders_current.region` | — |
| 销售额 | `float` | ❌ | ⚠️ 正则猜 metric ✅ | ❌ 前端猜「元」 | ❌ 无法知道 = `SUM(paid_amount)` | ❌ |
| 订单数 | `int` | ❌ | ⚠️ 正则猜 metric ✅ | ❌ | ❌ 无法知道 = `COUNT(order_id)` | ❌ |
| 客单价 | `float` | ❌ | ❌ **正则错判 dimension** | ❌ 前后端矛盾 | ❌ | ❌ |
| 销售目标 | `int` | ❌ | ⚠️ 正则猜 metric ✅ | ❌ 无法知道来自 `sales_targets` | ❌ |
| 目标完成率 | `float` | ❌ | ⚠️ 正则猜 metric ✅ | ❌ | ❌ | ❌ **344.18 是%还是比率？前端猜错，渲染成 34418.0%** |

> **一个"看起来相当完整"的结果，实际上 6 列全部无 dtype、全部无法溯源、全部无单位契约，
> 1 列角色错判，1 列量纲错误。**

### 2.5 一个已存在但完全未实现的「输出契约」设计

`frontend/src/types.ts:82-88` 中存在这样一个类型定义：

```ts
export interface DatabaseHandoff {
  ...
  output_contract: {
    row_grain: string
    columns: { name: string; alias: string; type: string }[]
    max_rows: number
    empty_result_policy: string
  }
}
```

这个 `output_contract` 恰恰包含了 Derive 最需要的东西：
**行粒度、列名→别名→类型三元组、最大行数、空结果策略**。

但对 backend 全量 grep：

```bash
grep -rn "output_contract|row_grain|empty_result_policy|max_rows" \
     --include=*.py --include=*.json --include=*.md backend/
# (无任何结果)
```

> **后端从未产生过这个结构**。它属于「多库 Handoff」路径，而该路径
> `_run_multi_database()` 直接返回「当前仅支持单库直接查询；多库 Handoff 尚未启用。」
> （`query_graph.py:340-348`）。
>
> 即：**项目里已经有人设想过输出契约的样子，只是它停留在前端 TypeScript 类型里，是一段死代码。**
> 这对后续 Repository 设计是有价值的既有素材。

---

## 第三部分：支撑 Repository + Derive 的差距分析

### A. 现有静态 Schema + 数据级信息，是否足够支撑一个 Repository（数据契约层）？

**结论：具备约 50~60% 的地基，但缺三类关键信息，目前不足以支撑一个可靠的 Repository。**

#### ✅ 已具备的（质量不错，可直接复用）

| 能力 | 位置 | 评价 |
| --- | --- | --- |
| 表级元信息 | `database.py` `SCHEMA` | id / label / domain / description / business_terms / primary_key 齐全 |
| 字段级元信息 | `database.py` `_field()` | name / label / type / description / aliases / **role** 齐全，`role` 语义质量高（区分了 identifier/dimension/metric/filter/time/foreign_key） |
| 表间关系 | `database.py` `RELATIONS` | 6 条，且已区分 `foreign_key` / `business` 两类 |
| 关系可达性计算 | `retrieval/graph.py:147-171` `_bfs` | 已有 BFS 最短路径连通逻辑，能自动补 join key |
| 版本签名 | `retrieval/service.py:430-441` | 对 `SCHEMA+RELATIONS` 做 SHA256，Schema 变更可检测 |
| 字段级内容哈希 | `retrieval/service.py:73-75` | 每个字段文档有 `content_hash` |
| Schema 图版本 | `retrieval/graph.py:105` | `graph_version`，本次查询用了哪些表/字段可追溯 |
| 数据级探查能力 | `retrieval/service.py:311-385` | **已经在连库跑 SQL 取 samples 和 min/max/avg/distinct** |

> 特别值得强调：**数据级探查的"管道"已经存在且能跑通**，
> 缺的不是采集能力，而是**产物的形态**（见下）。

#### ❌ 缺失的关键信息（按对 Repository 的阻塞程度排序）

**缺口 1（最致命）：数据级统计是自然语言字符串，不可程序化消费**

```python
# retrieval/service.py:376-380 —— 数值已算出，随即被 f-string 吞掉
row = connection.execute(f"SELECT MIN({column}), MAX({column}), AVG({column}) FROM {table}").fetchone()
return f"最小值 {row[0]}，最大值 {row[1]}，平均值 {average}"
```

落盘形态：`"profile": "最小值 0.0，最大值 314067.87，平均值 65244.28"`

Repository 想拿 `max` 必须正则解析中文。且**完全缺失**：
`row_count`、`null_count` / `null_ratio`、`distinct_count`（数值和日期字段没有）、
`zero_count`（`paid_amount` 有 32 个 0，这是业务信号不是脏数据）、分位数。

**缺口 2（最致命）：没有指标口径注册表**

§1.4 已证实全项目零命中。直接后果（§1.5.5 实测）：
「本月销售额」在同一张表上有 **4 个都说得通的答案**，相差 25.5%，
且其中 B≡D 的巧合会掩盖 SQL 写错筛选条件的问题。
**Repository 无法回答「销售额到底是什么」这个最基本的契约问题。**

**缺口 3（高）：关系上的约束条件只有自然语言**

```python
# database.py:140-147
{
    "left_table": "orders_current", "left_field": "region",
    "right_table": "sales_targets", "right_field": "region",
    "description": "当前销售与月度目标按地区进行业务关联，月份需额外对齐",  # ← 唯一的月份对齐要求
    "relation_type": "business",
}
```

`_bfs`（`graph.py:147-171`）只读 `left_field`/`right_field`，**不解析 description**。
实测漏掉月份对齐的后果（`out_03`「完成率_只按region关联的错误结果」）：

| 地区 | 实际销售额（被放大） | 正确值 | 目标（被重复累加） | 正确值 | 关联后行数 |
| --- | --- | --- | --- | --- | --- |
| 华东 | 8,584,367.50 | 4,292,183.75 | **229,600,000** | 2,200,000 | 112（应为56） |
| 华南 | 7,026,225.04 | 3,513,112.52 | **194,300,000** | 1,800,000 | 116 |
| 华北 | 6,758,086.72 | 3,379,043.36 | **138,650,000** | 1,600,000 | 94 |
| 西南 | 8,948,574.12 | 4,474,287.06 | **112,800,000** | 1,300,000 | 94 |

> **销售额被放大整 2 倍（因为 sales_targets 有 2 个月份），目标被放大 100 倍以上。**
> 而这个 JOIN **完全合法**——它严格遵守了 `RELATIONS` 里声明的关联字段。
>
> Repository 缺的是：**关系基数（1:1 / 1:N / N:N）、必需的附加对齐条件、扇出风险等级**。

**缺口 4（高）：静态类型与物理类型不一致，且无声明式对应**

`sales_targets.target_month` 静态写「日期」，物理是 `VARCHAR`（§1.3 表②）。
Repository 若按静态类型生成日期运算会失败；按物理类型又丢了业务语义。

**缺口 5（中）：单位、量纲、精度、值域语义全部缺失**

- 3 个金额字段的单位「元」只隐含在 description 文字里，无 `unit` 属性；
- `customer_level`（战略>重点>普通）是**有序分类**，Schema 里只标 `dimension`，无顺序；
- `status` 的 3 个枚举值（已支付/已取消/已退款）**未在 Schema 中枚举**，
  只能从 `samples`（LIMIT 5）里碰运气看到；
- 无小数精度契约（`paid_amount` 实际 2 位小数，无声明）。

**缺口 6（中）：权威取数路径未声明**

`region` 同时存在于 `orders_current` / `orders_history` / `customers` / `sales_targets`；
`category` 同时存在于 `orders_*` / `products`。
实测冗余值**完全一致**（0 行冲突），但 Schema **没有声明哪条是权威路径**。
不同 SQL 走不同路径，两次结果无法保证可比。

**缺口 7（中）：数据资产权威性无声明**

`askdata_mock.db`（SQLite，行数与 CSV 不同）、`schema_index.json`、
`schema_index_local_test.json` 三个孤儿文件与生效文件并存，
**没有任何机制标注哪份是权威的**（§1.1）。

**缺口 8（低）：`aggregation` 已定义但零消费**

`aggregation` 已经为每个字段标好了 `sum`/`count`/`group`/`none`，
质量不错（`order_id` 标了 `count`，`paid_amount` 标了 `sum`），
但**没有任何一行逻辑读它**（§1.4）。这是一个**已有但未接线**的资产。

---

### B. 当前查询结果的返回格式，是否方便直接进行确定性业务信号计算？

**结论：不方便。当前格式只能支撑「LLM 看着表格说话」，不能支撑确定性计算。**

一个 Derive 模块拿到 `{"columns": [...], "rows": [...]}` 后，
要算排名/占比/合计/完成率/同比，必须先回答 5 个问题，而**当前格式一个都答不了**：

| Derive 必须先知道 | 当前能否得到 | 障碍 |
| --- | --- | --- |
| 哪些列是可加总的指标？ | ❌ | 只有 `result_builder.py:95-99` 的中文正则，实测 `客单价`/`环比百分比`/`占比百分比`/`毛利` 全部错判成 dimension，且产物不回写到结果里 |
| 哪些列是分组维度？ | ❌ | 同上，二分法无 id/time 类别，`订单编号` 会被当成维度参与分组 |
| 这一列的数值是比率还是百分数？ | ❌ | 无契约。实测 `目标完成率=344.18` 被前端渲染成 `34418.0%` |
| 拿到的行是全量还是被截断？ | ❌ | 引擎 `fetchmany(201)` **已经知道**被截断，但不写进 `SqlExecution`。240 行表静默只返回 200 行 |
| 这一列对应哪个 Schema 字段？ | ❌ | 列名是 LLM 自由写的中文别名，无映射；且同一问题两次列名不同（`地区` vs `销售地区`，见 `saved_memories.json`） |

#### 主要障碍（按严重程度排序）

**障碍 1：静默截断 —— 会产生"看起来正确的错误答案"**

这是唯一一个**不会报错、不会告警、结果看起来完全正常**的障碍。
在 240 行的 `orders_current` 上做明细查询后算「合计」，Derive 会基于 200 行给出一个数，
**没有任何信号提示这个数是错的**。信息本已在引擎手里（`len(raw_rows) == 201`），
只是没有出口。

**障碍 2：列名不稳定 —— 破坏所有按列名取值的逻辑**

`saved_memories.json` 已经记录了同一问题产生 `["地区","销售额"]` 与 `["销售地区","销售额"]` 两种列名。
Derive 若写 `row["销售额"]` 会时灵时不灵；
若要做**跨两次查询的对比**（环比、同期对比正是这类），**无法对齐列**。

**障碍 3：无 dtype —— 数值/日期/文本无法可靠区分**

`_json_value` 把 `DATE` 转成 `str`（`duckdb_engine.py:146-147`）。
Derive 拿到 `"2026-08-05"` 无法确定它是日期还是文本编码，
时间序列排序只能靠字符串字典序碰运气（对 `YYYY-MM-DD` 恰好有效，对其他格式即错）。
同时 `Decimal → float` 引入精度噪声（`4474287.0600000005` 已被持久化进 `saved_memories.json`）。

**障碍 4：两套互不知晓的元信息启发式**

后端 `result_builder.py:95-99`（角色）与前端 `ResultTableCard.vue:39-49`（单位）
是两套独立的中文正则，实测在 `客单价`、`占比百分比` 上**直接互相矛盾**。
这说明「列的语义」这件事在系统里**没有单一事实来源**。

**障碍 5：无行粒度声明**

结果是明细行还是聚合行？如果是聚合，按什么分组？
`interpretation.dimension` 是个展示用的中文顿号串（且会错判），不是结构化的 group-by 列表。
Derive 无法判断「这张表能不能再聚合」「占比的分母是什么」。

#### ✅ 少数有利条件

- `rows` 是 `list[dict]`，键值扁平、JSON 可序列化，**转 pandas / 直接迭代都很容易**——容器形态本身没问题；
- `sql` 原文完整保留在 `QueryResult.sql`，理论上**可以反解**出列 → 字段的映射
  （项目已依赖 `sqlglot`，见 `duckdb_engine.py:11-13`，`_validate_sql` 已在做 AST 遍历）；
- `schema_graph` 完整挂在 `QueryResult.schema_graph` 上（含 `graph_version`、
  参与的 tables / fields / joins，且 fields 里**带 `role`**），
  **本次查询用了哪些 Schema 字段是已知的**——只是没有和结果列建立对应关系。

> 换句话说：**拼图的两半都在（结果列在 `columns`，字段 role 在 `schema_graph.fields[].role`），
> 中间缺的是 `column → doc_id` 这一根连线。**

---

### C. 数据本身是否具备计算常见业务信号的条件？

**结论：具备「静态截面类」信号的条件，「时间对比类」信号条件不足，「目标类」信号数据失真。**

以下全部为 `probe_03` 实测结果（`out_03_signal_feasibility.json`）。

#### ✅ 现在就能算，且结果可靠

**① 合计 / 排名 / 占比**（单表内，`orders_current` 240 行 < 200？→ 聚合后 4 行，无截断风险）

```sql
SELECT region AS 地区, SUM(paid_amount) AS 销售额,
       ROUND(100.0 * SUM(paid_amount) / SUM(SUM(paid_amount)) OVER (), 2) AS 占比百分比,
       RANK() OVER (ORDER BY SUM(paid_amount) DESC) AS 排名
FROM orders_current WHERE status = '已支付' GROUP BY region
```

实测输出：

| 地区 | 销售额 | 占比% | 排名 |
| --- | --- | --- | --- |
| 西南 | 4,474,287.06 | 28.57 | 1 |
| 华东 | 4,292,183.75 | 27.41 | 2 |
| 华南 | 3,513,112.52 | 22.44 | 3 |
| 华北 | 3,379,043.36 | 21.58 | 4 |

**条件充分**：4 个低基数维度（region / category / customer_level / product_name）
× 3 个金额指标，全部无空值，聚合后行数远小于 200。

**② 多维交叉分析**：`region × category`（4×4=16 组）、`customer_level × region`（3×4=12 组）等，
维度基数低、外键完整（`customer_id` 覆盖全部 30 个客户，`product_id` 覆盖全部 12 个产品），
JOIN 无孤儿行。

**③ 结构占比 / 贡献度**：如「战略客户贡献了多少销售额占比」——
`customer_level` 3 个值分布均衡（14/9/7），可算。

#### ⚠️ 能算，但有严重前提或结果失真

**④ 环比（MoM）—— 能算，但必须跨两张表 UNION**

由于 `orders_current`(2026-08) 与 `orders_history`(2026-06~07) 是**同构分表**，
月度趋势必须 UNION：

```sql
WITH monthly AS (
    SELECT strftime(order_date,'%Y-%m') AS ym, SUM(paid_amount) AS amt
    FROM orders_history WHERE status='已支付' GROUP BY 1
    UNION ALL
    SELECT strftime(order_date,'%Y-%m'), SUM(paid_amount)
    FROM orders_current WHERE status='已支付' GROUP BY 1
)
SELECT ym, amt, amt - LAG(amt) OVER (ORDER BY ym) AS 环比增量,
       100.0*(amt/LAG(amt) OVER (ORDER BY ym) - 1) AS 环比百分比
FROM monthly ORDER BY ym
```

实测输出：

| 月份 | 销售额 | 环比增量 | 环比% |
| --- | --- | --- | --- |
| 2026-06 | 14,096,078.76 | — | — |
| 2026-07 | 16,145,060.58 | +2,048,981.82 | **+14.54%** |
| 2026-08 | 15,658,626.69 | −486,433.89 | **−3.01%** |

> **能算，结果合理。但前提是必须知道"要 UNION 两张表"。**
> `RELATIONS` 里**没有任何一条声明 `orders_current` 与 `orders_history` 是同构分表**——
> 它们只是碰巧共用了 `ORDER_FIELDS` 常量（`database.py:51,61`）。
> Schema 图 `_bfs` 也永远不会把这两张表连起来（它们之间没有 relation）。
> **"分表" 这个事实只存在于两张表的 `description` 文字里**
> （"2026年8月当前订单交易明细" / "2026年6月至7月历史归档订单"）。
>
> 另外只有 **3 个数据点**，环比序列极短，趋势判断意义有限。

**⑤ 目标完成率 —— 能算，但数据严重失真且有扇出陷阱**

正确写法必须**同时对齐 region 和月份**：

```sql
WITH actual AS (
    SELECT region, strftime(order_date,'%Y-%m') AS ym, SUM(paid_amount) AS amt
    FROM orders_current WHERE status='已支付' GROUP BY 1,2
)
SELECT a.region, a.ym, a.amt, t.target_amount,
       100.0*a.amt/t.target_amount AS 完成率
FROM actual a JOIN sales_targets t
  ON a.region = t.region AND a.ym = t.target_month     -- ← 月份对齐不可省
```

实测：完成率 **195% ~ 344%**（§1.5.4 表）。

**两个问题**：
1. **数据失真**：目标值（1.3M~2.2M）与实际值（3.4M~4.5M）量级不匹配，
   全部地区「超额完成 2~3.4 倍」。`demo_data.py:42-51` 的目标是手写常量，
   订单金额是随机生成，**两者从未校准**。信号能算，但**没有区分度，无法验证 Derive 逻辑正确性**。
2. **扇出陷阱**：漏掉 `a.ym = t.target_month` 会让销售额翻 2 倍、目标翻 100 倍（§3.A 缺口 3 实测表），
   而这个 SQL **完全符合 `RELATIONS` 的声明**。

**⑥ 2026-06 的完成率 —— 不可算**

| 月份 | 有实际值 | 有目标值 |
| --- | --- | --- |
| 2026-06 | ✅ 231 单 | ❌ **无** |
| 2026-07 | ✅ 249 单 | ✅ |
| 2026-08 | ✅ 240 单 | ✅ |

`sales_targets` 只有 `2026-07` / `2026-08` 两个月（实测 `target_month` distinct=2）。

#### ❌ 现在算不了

**⑦ 同比（YoY）—— 数据根本不存在**

实测：

```
全局最早月 = 2026-06
全局最晚月 = 2026-08
覆盖年份数 = 1
```

> 全库只有 **2026 年、3 个月**的数据。
> 「2026年8月 vs 2025年8月」**没有任何可比数据**。
> 这不是 Schema 或结果结构的问题，**是数据本身的绝对缺口**，
> 补齐只能靠扩充数据（例如让 `demo_data.py` 多生成 12~24 个月）。

**⑧ 累计值 / YTD**：数据从 2026-06 起，**没有 1~5 月**，「本年累计」不可算。

**⑨ 同期目标对比 / 目标达成趋势**：只有 2 个月目标，无法构成趋势。

**⑩ 客户留存 / 复购 / 生命周期**：`customers` 无注册日期、无首单日期、无状态字段，
只有 4 个属性（id/name/level/region）。无法计算新老客户、留存率。

**⑪ 退款率 / 取消率的金额口径**：`status` 有「已退款」，但**退款订单的 `paid_amount` 被置为 0**
（`demo_data.py:136-138`），**没有记录退款金额**。
只能算「按订单数的退款率」（15/240=6.25%），**算不了「按金额的退款率」**。

#### 信号可行性汇总

| 业务信号 | 可算性 | 关键约束 |
| --- | --- | --- |
| 合计 (SUM) | ✅ 可靠 | 需明确口径（4 选 1，见 §1.5.5） |
| 排名 (RANK) | ✅ 可靠 | 维度基数低（3~30），无风险 |
| 占比 (share) | ✅ 可靠 | 需注意分母是否被截断（明细查询时） |
| 多维交叉 | ✅ 可靠 | 外键完整，冗余维度实测一致 |
| 环比 (MoM) | ⚠️ 需跨表 UNION | 分表关系未在 Schema 声明；仅 3 个数据点 |
| 目标完成率 | ⚠️ 数据失真 + 扇出陷阱 | 目标量级未校准（195%~344%）；月份对齐仅存在于 description |
| 2026-06 完成率 | ❌ | 该月无目标值 |
| **同比 (YoY)** | ❌ **绝对不可算** | 全库仅 1 年 3 个月 |
| YTD 累计 | ❌ | 缺 2026 年 1~5 月 |
| 客户留存/复购 | ❌ | `customers` 无任何时间字段 |
| 金额口径退款率 | ❌ | 退款金额未记录（`paid_amount` 被置 0） |
| 订单数口径退款率 | ✅ | `status` 计数可算 |

---

### D. 只从数据端出发，要补齐哪些最小必要的信息 / 结构？

以下是**信息层面的缺口清单**（不含实现方案、不含代码设计），
按「不补就无法可靠 Derive」的优先级排序。

#### P0 —— 不补则 Derive 会产出静默错误的答案

| # | 需补齐的信息 | 当前状态 | 不补的具体后果 |
| --- | --- | --- | --- |
| **D1** | **结果集完整性标记**：本次结果是全量还是被截断、符合条件的总行数 | 引擎 `fetchmany(201)` **已算出**该信息（`duckdb_engine.py:43`），但 `SqlExecution` 无字段承载 | 240 行表静默返回 200 行，合计/占比/排名基于 83% 数据，**无任何错误信号** |
| **D2** | **结果列 → Schema 字段的映射**（`column → database.table.field` 或 `doc_id`） | 完全缺失。列名是 LLM 自由写的中文别名 | 无法确定 `销售额` 是 `SUM(paid_amount)` 还是 `SUM(order_amount)`；列名不稳定（`地区` vs `销售地区` 已实测）导致按列名取值失败、跨结果无法对齐 |
| **D3** | **结果列的数据类型**（dtype） | `cursor.description` 提供了 `type_code`，`duckdb_engine.py:44` 只取 `[0]` 丢弃；`_json_value` 进一步把 `DATE→str`、`Decimal→float` | 无法区分日期与文本；时间序列排序靠字符串字典序碰运气；精度噪声（`4474287.0600000005`）被持久化 |
| **D4** | **指标口径定义**（销售额/订单数等 = 什么表达式 + 什么筛选条件） | 全项目零命中（§1.4） | 同一问题 4 个答案相差 25.5%；且 B≡D 的巧合会掩盖 SQL 漏写筛选条件 |
| **D5** | **关系的基数与必需对齐条件**（1:1 / 1:N / N:N；`orders×targets` 必须对齐月份） | 月份对齐**只写在 `description` 自然语言里**（`database.py:145`），`_bfs` 不解析 | 合法 JOIN 导致销售额翻 2 倍、目标翻 100 倍（实测） |

#### P1 —— 不补则 Derive 结果会被误读或误渲染

| # | 需补齐的信息 | 当前状态 | 不补的具体后果 |
| --- | --- | --- | --- |
| **D6** | **结果列的业务角色**（metric / dimension / time / identifier） | 仅 `result_builder.py:95-99` 的 5 字中文正则，实测 4/16 错判，且产物不回写到 `columns`/`rows`。Schema 里的 `field_role` 质量很好但**未随结果传递** | `客单价`、`环比百分比`、`毛利` 被当成分组维度；`订单编号` 被当成维度参与分组 |
| **D7** | **量纲契约**（比率 vs 百分数）与**单位**（元/个/%）、精度 | 后端零；前端 `ResultTableCard.vue:39-49` 中文正则独立猜测，与后端矛盾 | 已实测：`目标完成率=344.18` 被渲染成 `34418.0%` |
| **D8** | **行粒度声明**（明细行 / 按哪些列聚合） | 仅 `interpretation.dimension` 中文顿号串，且会错判 | 无法判断结果能否再聚合、占比的分母是什么、能否安全求和 |
| **D9** | **物理类型与静态类型的对齐**（`target_month`：静态「日期」vs 物理 `VARCHAR`；`target_amount`：静态「数值」vs 物理 `BIGINT`） | 不一致，无声明 | 跨表时间对齐时一边 `DATE` 一边 `VARCHAR`，Schema 上看不出来 |

#### P2 —— 不补则 Derive 可用但结论质量受限

| # | 需补齐的信息 | 当前状态 | 不补的具体后果 |
| --- | --- | --- | --- |
| **D10** | **结构化的字段级统计**：`row_count` / `null_ratio` / `distinct_count` / `min` / `max` / `zero_count` / 精度 | 数值**已被算出**（`service.py:376-384`）随即压成中文字符串 `"最小值 0.0，最大值 314067.87，平均值 65244.28"` | Derive 无法做值域校验、异常检测、除零防护；`paid_amount` 的 32 个 0 值是业务规则却无法被识别 |
| **D11** | **枚举字段的完整值域**（`status` 3 值、`customer_level` 3 值**及其顺序**、`region` 4 值） | 只能从 `samples`（`LIMIT 5`）里碰运气看到，无完整枚举、无顺序 | 「战略>重点>普通」的分层排序只能靠 LLM 常识；筛选条件无法校验合法性 |
| **D12** | **同构分表关系**（`orders_current` ⊕ `orders_history` 是同一实体的时间分片） | **完全未声明**。二者只是碰巧共用 `ORDER_FIELDS` 常量；`RELATIONS` 无此条目；`_bfs` 永不连通 | 环比/趋势必须 UNION 才对，但这个事实只存在于 description 文字里 |
| **D13** | **权威取数路径**（`region` 用 `orders.region` 还是 `customers.region`） | 冗余存在且实测一致，但无声明 | 不同 SQL 走不同路径，两次结果无法保证可比 |
| **D14** | **数据资产权威性标注** | `askdata_mock.db`（行数与 CSV 不同）、`schema_index.json`、`schema_index_local_test.json` 三个孤儿文件与生效文件并存，无标注 | 无法程序化判断哪份是权威数据 |

#### P3 —— 数据本身的绝对缺口（补不了信息，只能补数据）

| # | 缺口 | 影响的信号 |
| --- | --- | --- |
| **D15** | **时间跨度不足**：仅 2026-06 ~ 2026-08，1 年 3 个月 | **同比(YoY) 完全不可算**；YTD 不可算；环比仅 3 点 |
| **D16** | **目标值覆盖不全**：`sales_targets` 缺 2026-06 | 2026-06 完成率不可算 |
| **D17** | **目标值量级未校准**：目标 1.3M~2.2M vs 实际 3.4M~4.5M | 完成率恒为 195%~344%，**无区分度，无法验证 Derive 逻辑正确性** |
| **D18** | **退款金额未记录**：非「已支付」订单 `paid_amount` 直接置 0（`demo_data.py:136-138`） | 金额口径的退款率/取消率不可算；且掩盖了 SQL 漏写筛选条件的错误 |
| **D19** | **客户维度无时间字段**：`customers` 仅 4 个属性 | 留存率、复购率、新老客户、生命周期全部不可算 |

#### 一个有利前提

以下能力**已经存在，只是产物形态或接线不对**，属于「改形态」而非「从零建设」：

| 已有能力 | 现状 | 缺的是 |
| --- | --- | --- |
| 数据级探查管道 | `service.py:311-385` 已连库跑 SQL 取 samples/min/max/avg/distinct | 产物是中文字符串，不是结构化字段（D10） |
| dtype 来源 | `cursor.description` 的 `type_code` 就在手边 | 只取了 `[0]`（D3） |
| 截断判定 | `fetchmany(201)` 的 `+1` 已经把答案算出来了 | 没有字段承载（D1） |
| 字段 `role` | Schema 里质量很好，且已进入 `schema_graph.fields[].role` | 没有和结果列建立对应（D2 + D6） |
| `aggregation` | 已为每个字段标好 `sum`/`count`/`group` | 零消费，无人读取（D4 的一部分） |
| SQL AST 解析 | 项目已依赖 `sqlglot`，`_validate_sql` 已在遍历 AST | 没用它反解 `SELECT ... AS 别名` 的溯源（D2） |
| 输出契约设计 | `frontend/src/types.ts:82-88` 的 `output_contract` 已含 `row_grain`/`columns[name,alias,type]`/`max_rows` | 后端从未产生，是死代码（D1+D2+D3+D8 的现成蓝本） |

---

## 总结表

| 检查项 | 现状 | 对 Repository/Derive 的支持程度 | 主要缺口 |
| --- | --- | --- | --- |
| **数据存储形式** | 纯 Mock CSV，DuckDB `:memory:` 挂载只读视图；1 个库 5 张表 770 行；无真实数据库 | 🟢 **充分** — 全量重算成本近 0，只读安全 | 3 个孤儿文件（`askdata_mock.db` / `schema_index*.json`）与生效数据并存，权威性无声明 |
| **表级 Schema** | `database.py` 源码常量，含 id/label/domain/description/business_terms/primary_key | 🟢 **充分** | `sales_targets` 主键声明为 `target_id`，实际业务主键是 `(target_month, region)` |
| **字段级 Schema** | 30 字段，含 name/label/type/description/aliases/**role**/aggregation | 🟡 **基本可用** | 无单位、无精度、无枚举值域、无有序分类顺序；`aggregation` **零消费**；`role` 仅进 prompt 文本 |
| **数据级 Schema** | 索引构建时**真的连库探查**了 samples(5条) + min/max/avg/distinct | 🔴 **形态不可用** | 数值被 f-string 压成中文串 `"最小值 0.0，最大值 314067.87，平均值 65244.28"`；缺 row_count / null_ratio / zero_count / 精度 |
| **表间关系** | 6 条，已区分 `foreign_key` / `business`；`_bfs` 可自动补 join key | 🔴 **有严重陷阱** | 无基数(1:N/N:N)；`orders×targets` 的月份对齐**只写在 description**，漏掉时销售额翻 2 倍、目标翻 100 倍（实测） |
| **指标口径 / 计算规则** | **全项目零命中** | 🔴 **完全缺失** | 「本月销售额」有 4 个都说得通的答案，相差 25.5%；且 B≡D 的巧合掩盖 SQL 漏写筛选 |
| **同构分表关系** | `orders_current`(08) 与 `orders_history`(06~07) 共用 `ORDER_FIELDS` | 🔴 **未声明** | `RELATIONS` 无此条目，`_bfs` 永不连通；「趋势要 UNION」只存在于 description 文字 |
| **静态类型 vs 物理类型** | `target_month` 静态「日期」/物理 `VARCHAR`；`target_amount` 静态「数值」/物理 `BIGINT` | 🟡 **不一致** | 跨表时间对齐一边 `DATE` 一边 `VARCHAR`，Schema 上看不出来 |
| **查询结果容器** | `SqlExecution` dataclass，**仅 5 字段**：`sql/success/columns/rows/error` | 🟡 **容器形态 OK，元信息为零** | `columns` 是 `list[str]`，`rows` 是 `list[dict]`，值是裸标量 |
| **列的 dtype** | `cursor.description` 的 `type_code` **就在手边**，`duckdb_engine.py:44` 只取 `[0]` 丢弃；`DATE→str`、`Decimal→float` | 🔴 **主动丢弃** | 日期与文本无法区分；精度噪声 `4474287.0600000005` 已被持久化 |
| **列的业务角色** | 仅 `result_builder.py:95-99` 的 5 字中文正则；产物只进展示字符串，不回写结果 | 🔴 **不可靠且未回写** | 实测 4/16 错判（`客单价`/`环比百分比`/`占比百分比`/`毛利`）；无 id/time 类别 |
| **列 → Schema 字段溯源** | **完全没有** | 🔴 **完全缺失** | 列名是 LLM 自由写的中文别名；**同一问题两次列名不同**（`地区` vs `销售地区`，`saved_memories.json` 实证） |
| **截断标记** | 引擎 `fetchmany(201)` **已算出**是否截断，`SqlExecution` 无字段承载 | 🔴 **信息被丢弃，静默失败** | 240 行表静默返回 200 行；`row_count` 恒 ≤200 表达的是"返回几行"不是"共几行" |
| **单位 / 精度 / 量纲** | 后端零；前端 `ResultTableCard.vue:39-49` 独立中文正则，与后端矛盾 | 🔴 **已产生实际错误** | `目标完成率=344.18` 被渲染成 `34418.0%`；`客单价`/`占比百分比` 前后端判定直接冲突 |
| **结果级统计** | 无任何 sum/max/min/null 字段 | 🔴 **完全缺失** | Derive 无法做值域校验、除零防护、异常检测 |
| **行粒度** | 仅 `interpretation.dimension` 中文顿号串，且会错判 | 🔴 **不可用** | 无法判断能否再聚合、占比分母是什么 |
| **合计 / 排名 / 占比** | 实测可算，结果正确（4 地区占比 28.57/27.41/22.44/21.58） | 🟢 **数据条件充分** | 需先确定口径（4 选 1）；明细查询时分母可能被截断 |
| **环比 (MoM)** | 实测可算：06→07 **+14.54%**，07→08 **−3.01%** | 🟡 **可算但有前提** | 必须 UNION 两张同构分表，而该关系未声明；仅 3 个数据点 |
| **目标完成率** | 实测可算：195%~344% | 🟡 **可算但数据失真** | 目标量级未校准（恒超额 2~3.4 倍，无区分度）；2026-06 无目标；JOIN 扇出陷阱 |
| **同比 (YoY)** | 全库仅 **2026 年 3 个月**（06/07/08），覆盖年份数=1 | 🔴 **绝对不可算** | 数据本身缺口，只能扩充数据 |
| **目标值 / 预算值** | ✅ `sales_targets.target_amount`（月×地区，仅 07/08） | 🟡 **存在但不全** | 缺 2026-06；无独立预算列（与目标同义）；量级未校准 |
| **上期值 / 同期值** | ❌ 无 `prev_*` / `last_*` 列（实测全列扫描确认） | 🟡 **需窗口函数现算** | `LAG()` + 跨表 UNION 可算 MoM；YoY 无数据 |
| **维度体系** | region(4) / category(4) / customer_level(3) / customer_name(30) / product_name(12)，基数低、零空值；冗余维度实测 **0 行冲突** | 🟢 **充分** | 权威取数路径未声明；`customer_level` 有序但无顺序声明 |
| **数据完整性** | 全部 30 字段 **零空值**；外键 100% 覆盖；`order_id` 连续无缺号 | 🟢 **优秀** | `paid_amount` 的 32 个 0 值是业务规则（非空值），但 Schema 未声明 |
| **既有输出契约设计** | `frontend/src/types.ts:82-88` `output_contract` 含 `row_grain`/`columns[name,alias,type]`/`max_rows`/`empty_result_policy` | 🟡 **死代码，但有参考价值** | 后端全量 grep 零命中；所属的多库路径 `_run_multi_database` 明确「尚未启用」 |

### 一句话结论

**Schema 的"骨架"（表/字段/关系/role）质量不错，数据的"内容"（零空值、外键完整、维度清晰）也很干净，
但三件事让当前状态还不足以支撑可靠的 Repository + Derive：**

1. **数据级信息被压成了自然语言字符串** —— 统计值算出来了，形态不可消费；
2. **查询结果只有"列名 + 裸值"** —— dtype 在手边被丢弃、截断标记算出来被丢弃、
   列无法溯源到 Schema 字段、角色/单位靠两套互相矛盾的中文正则猜；
3. **指标口径完全不存在** —— 同一个「销售额」有 4 个都说得通的答案。

**其中 D1（静默截断）和 D2（列名不可溯源且不稳定）是最危险的两项**，
因为它们**不报错**：Derive 会基于 200/240 行数据、按可能 KeyError 的列名，
给出一个看起来完全正常的错误答案。

---

*报告基于 2026-08-25 的代码与数据实测。探查脚本与原始 JSON 输出见 `./data_probe/`。*
