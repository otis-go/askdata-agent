# AskData Studio

AskData Studio 是一个本地运行的自然语言问数项目。前端使用 Vue 3，后端使用 FastAPI 和 LangGraph；系统能够检索字段级 Schema、生成并执行 SQL，并以表格和文字形式返回结果。

## 环境要求

- Python 3.11
- Node.js 20.19 或更高版本
- 可用的大模型、Embedding 和 Rerank API Key

以下命令均从项目根目录开始执行，不依赖固定的本机路径。

## 安装环境

### 后端

Windows PowerShell：

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

macOS 或 Linux：

```bash
cd backend
python3.11 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

编辑 `backend/.env`，至少填写 API Key。默认配置使用 `text-embedding-v4` 和 `qwen3-rerank`：

```env
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen3.7-plus
EMBEDDING_MODEL=text-embedding-v4
RERANK_MODEL=qwen3-rerank
```

### 前端

```powershell
cd frontend
npm install
```

## 启动服务

分别打开两个终端。

后端（Windows）：

```powershell
cd backend
.\.venv\Scripts\python.exe run.py
```

后端（macOS 或 Linux）：

```bash
cd backend
./.venv/bin/python run.py
```

前端：

```powershell
cd frontend
npm run dev
```

启动后访问：

- 前端页面：`http://127.0.0.1:5173`
- API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/api/health`

## 使用方法

### Phase 5 固定 Demo

在后端目录运行 ` .\.venv\Scripts\python.exe run_demo.py --llm live`（替代 `run.py`），前端启动方式不变。
页面提供三个固定问题：`8月各区域目标完成率？`、`哪个区域销售下降？`、`哪个产品贡献最高？`。
使用管理员演示账号，以便读取 S2 所需的历史订单。固定期间为 2026 年 8 月，S2 对比 7 月，销售口径为已支付订单。

Demo 使用已有 CSV、DuckDB、Semantic Layer、S1/S2/S3、SignalEngine 和解释流程，固定 SQL 与显式业务声明仅在此入口装配。
原 `run.py` 保持通用问数流程；它尚未配置生产 `SignalSource`，不会自动生成这些业务信号。

无有效模型配置时，可用 ` .\.venv\Scripts\python.exe run_demo.py --llm fixture` 验证展示链路。
fixture 只替代模型的展示选项响应，页面会明确标注“未调用真实 LLM”；计算与解释校验仍使用原实现。
故障演示可追加 `--failure no-signal`、`--failure llm` 或 `--failure validator`，重启后端后重新查询。
这些开关仅存在于独立 Demo 启动进程，不能通过普通 API 请求启用。

详细验收与截图见 [Phase 5.0 Demo Integration Report](learning_report/askdata_phase5_0_demo_integration_report.md)。

使用内置账号登录：

- 管理员：`admin` / `admin123`
- 销售用户：`sales` / `sales123`

登录后可直接输入问题，例如：

- 查询本月各地区销售额
- 按客户等级统计本月销售额
- 对比本月各地区销售额和销售目标

右侧的“查询字段”用于明确本次 SQL 必须使用的字段；保存的结果表用于后续问答和综合分析。查询完成后可以查看 SQL、翻页、导出 Excel，并按需保存字段或结果。
