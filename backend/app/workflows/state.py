from __future__ import annotations

from typing import Any, TypedDict


class QueryState(TypedDict, total=False):
    """LangGraph 工作流状态。"""

    task_id: str
    query: str
    session_id: str
    workspace: dict[str, Any]
    access_scope: dict[str, Any]
    route_context: str
    short_term_context: str
    recent_result_context: str
    analysis_context: str
    analysis_sources: list[dict[str, Any]]
    # Separate Table snapshot and Graph-owned explanation artifacts. All are
    # JSON-compatible and rebuilt per invocation, never supplied as facts by UI.
    execution_result: dict[str, Any] | None
    signal_batch: dict[str, Any] | None
    prompt_package: dict[str, Any] | None
    explanation_response: dict[str, Any] | None
    # Retired 4.3.1 handoff fields are cleared, never consumed by this Graph.
    explanation_prompt_package: dict[str, Any] | None
    explanation_task_id: str | None
    explanation_for_query: str | None
    intent: dict[str, Any]
    direct_response: str
    response_type: str
    standalone_query: str
    rewritten: bool
    extraction: dict[str, Any]
    retrieval: dict[str, Any]
    schema_graph: dict[str, Any]
    schema_context: str
    database_names: list[str]
    clarification: dict[str, Any] | None
    direct_sql: str
    sql_source: str
    tool_facts: dict[str, Any]
    mcp_execution: dict[str, Any]
    mcp_tool_trace: list[dict[str, Any]]
    execution_log: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    workflow_mode: str
    result: dict[str, Any]
