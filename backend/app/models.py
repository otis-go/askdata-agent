from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ConfirmedField(BaseModel):
    name: str
    aggregation: Literal["auto", "group", "sum", "avg", "count", "max", "min"] = "auto"
    tableId: str | None = None


class AnalysisTableInput(BaseModel):
    task_id: str
    title: str
    query: str = ""
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)


class WorkspaceConfig(BaseModel):
    schema_fields: list[ConfirmedField] = Field(default_factory=list)
    analysis_table_ids: list[str] = Field(default_factory=list)
    analysis_tables: list[AnalysisTableInput] = Field(default_factory=list)
    # 兼容旧版前端的 fields 属性。
    fields: list[ConfirmedField] = Field(default_factory=list)

# HTTP JSON -> FastAPI/Pydantic 解析 -> QueryRequest Python 对象，变量名为 payload。
class QueryRequest(BaseModel):      #8.26 HTTP JSON 怎么变成 Python 对象
    query: str = Field(min_length=1, max_length=500)      #payload.query 就是 "查询本月各地区销售额"
    session_id: str = "demo-session"
    workspace: WorkspaceConfig | None = None


class ClarificationRequest(BaseModel):
    option_id: str


class ClarificationOption(BaseModel):
    id: str
    label: str
    description: str
    recommended: bool = False


class Clarification(BaseModel):
    parameter: str = "other"
    question: str
    reason: str
    options: list[ClarificationOption]


class Interpretation(BaseModel):
    metric: str
    dimension: str
    time_range: str
    table: str
    assumptions: list[str] = []


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


class SchemaField(BaseModel):
    name: str
    label: str
    type: str
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    role: str = ""
    aggregation: str = "none"


class SchemaTable(BaseModel):
    id: str
    label: str
    description: str
    fields: list[SchemaField]
    database: str = "askdata_mock"
    domain: str = ""
    business_terms: list[str] = Field(default_factory=list)
    primary_key: list[str] = Field(default_factory=list)


class SaveMemoryRequest(BaseModel):
    task_id: str


class SaveFieldMemoryRequest(BaseModel):
    table_id: str
    name: str
    label: str
    field_type: str


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
