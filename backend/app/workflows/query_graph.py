from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import ValidationError

from ..config import Settings, settings
from ..database import SCHEMA
from ..errors import PipelineStageError
from ..mcp_runtime import LocalMcpClient, create_local_mcp_server
from ..model_client import ModelClient
from ..models import QueryResult
from ..preprocessing import RequestPreprocessor
from ..querying.duckdb_engine import DuckDbEngine
from ..querying.business_signals.batch import SignalBatch
from ..querying.business_signals.engine import SignalEngine
from ..querying.explanation.context_builder import build_explanation_context
from ..querying.explanation.prompt_builder import PromptPackage, build_prompt_package
from ..querying.explanation.response_adapter import unavailable_explanation
from ..querying.explanation.response_models import ExplanationResponse
from ..querying.explanation.validator import validate_response
from ..querying.models import SqlExecution
from ..querying.response_generator import ResponseGenerator
from ..querying.result_consistency import validate_execution_consistency
from ..querying.result_contract import ResultContract
from ..querying.single_database_agent import SingleDatabaseAgent
from ..retrieval import SchemaGraphBuilder, SchemaIndex
from ..security import AccessScope
from ..skills import SkillRegistry
from .result_builder import ResultBuilder
from .signal_delivery import SignalRequest, SignalSource, execution_digest, resolve_signals
from .state import QueryState


class QueryWorkflow:
    """基于 LangGraph 的问答和数据库查询工作流。"""

    def __init__(
        self,
        model_client: ModelClient,
        schema_index: SchemaIndex,
        config: Settings | None = None,
        *,
        signal_source: SignalSource | None = None,
    ) -> None:
        self.model_client = model_client
        self.schema_index = schema_index
        self.config = config or settings
        self.preprocessor = RequestPreprocessor(model_client)
        self.skills = SkillRegistry()
        self.graph_builder = SchemaGraphBuilder()
        self.database_engine = DuckDbEngine()
        self.single_database_agent = SingleDatabaseAgent(
            model_client,
            self.mcp_client,
            self.skills.get("database_query"),
            self.config.mcp_max_tool_calls,
        )
        self.response_generator = ResponseGenerator(model_client)
        self.signal_source = signal_source
        self.signal_engine = SignalEngine()
        self.checkpointer = InMemorySaver()
        self.graph = self._compile()

    def mcp_client(self, access_scope: dict[str, Any]) -> LocalMcpClient:
        scope = AccessScope.from_dict(access_scope)
        return LocalMcpClient(create_local_mcp_server(self.database_engine, scope))

    # Service 负责启动 Workflow；Workflow/LangGraph 根据 Graph 定义，
    # 决定第一个 Node 是 preprocess（8.27）。
    def _compile(self):
        builder = StateGraph(QueryState)
        builder.add_node("preprocess", self._preprocess)
        builder.add_node("respond_directly", self._respond_directly)
        builder.add_node("answer_qa", self._answer_qa)
        builder.add_node("retrieve_schema", self._retrieve_schema)
        builder.add_node("human_clarification", self._human_clarification)
        builder.add_node("prepare_single_database", self._prepare_single_database)
        builder.add_node("execute_single_database", self._execute_single_database)
        builder.add_node("run_multi_database", self._run_multi_database)
        builder.add_node("build_signal_batch", self._build_signal_batch)
        builder.add_node("build_explanation_prompt", self._build_explanation_prompt)
        builder.add_node("generate_explanation", self._generate_explanation)
        builder.add_edge(START, "preprocess")
        #8.27 LLM 决定的是“语义动作标签”；程序决定的是“这个标签对应哪条 execution path”。
        # LLM decision + deterministic orchestration：
        # LLM 生成 action="database_query"，确定性代码把它映射到 retrieve_schema Node。
        builder.add_conditional_edges(
            "preprocess",
            lambda state: {
                "direct_response": "respond_directly",
                "data_qa": "answer_qa",
                "database_query": "retrieve_schema",
            }[state["intent"]["action"]],
            {
                "respond_directly": "respond_directly",
                "answer_qa": "answer_qa",
                "retrieve_schema": "retrieve_schema",
            },
        )
        builder.add_edge("respond_directly", END)
        builder.add_edge("answer_qa", "build_signal_batch")
        builder.add_conditional_edges(
            "retrieve_schema",
            self._after_retrieval,
            {
                "human_clarification": "human_clarification",
                "prepare_single_database": "prepare_single_database",
                "run_multi_database": "run_multi_database",
            },
        )
        builder.add_edge("human_clarification", "retrieve_schema")
        builder.add_conditional_edges(
            "prepare_single_database",
            lambda state: "human_clarification" if state.get("clarification") else "execute_single_database",
            {
                "human_clarification": "human_clarification",
                "execute_single_database": "execute_single_database",
            },
        )
        builder.add_conditional_edges(
            "execute_single_database",
            lambda state: "build_signal_batch" if (state.get("execution_result") or {}).get("success") is True else "end",
            {"build_signal_batch": "build_signal_batch", "end": END},
        )
        builder.add_edge("build_signal_batch", "build_explanation_prompt")
        builder.add_edge("build_explanation_prompt", "generate_explanation")
        builder.add_edge("generate_explanation", END)
        builder.add_conditional_edges(
            "run_multi_database",
            lambda state: "human_clarification" if state.get("clarification") else "end",
            {"human_clarification": "human_clarification", "end": END},
        )
        return builder.compile(checkpointer=self.checkpointer)

    @staticmethod
    def run_config(task_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": task_id}}

    def invoke(self, payload: QueryState | Command, task_id: str) -> QueryResult:
        state = self.graph.invoke(payload, config=self.run_config(task_id))
        return self._state_result(state, task_id)

    def _state_result(self, state: dict[str, Any], task_id: str) -> QueryResult:
        if state.get("result"):
            return QueryResult.model_validate(state["result"])
        state = {**state, "task_id": state.get("task_id") or task_id}
        return ResultBuilder.waiting(state)
    # 节点更新逻辑（8.27）：旧 QueryState + 当前 Node 返回的 update -> 新 QueryState。
    def _preprocess(self, state: QueryState) -> dict[str, Any]:
        """生成路由、独立查询和 Schema 检索参数。"""
        # _preprocess() 只读取 state["query"]、route_context 和 execution_log，
        # 即 Shared State + node-local consumption（8.27）。
        decision = self.preprocessor.prepare(state["query"], state.get("route_context", ""))
        execution_log = list(state.get("execution_log") or [])
        if decision.source == "model_unavailable_fallback":
            execution_log.append({
                "stage": "route_fallback",
                "success": True,
                "source": decision.source,
                "action": decision.action,
                "reason": decision.reason,
            })
        return {
            **self._clear_explanation(),
            "execution_result": None,
            "result": {},
            "intent": {
                "action": decision.action,
                "confidence": decision.confidence,
                "reason": decision.reason,
                "response_type": decision.response_type,
                "source": decision.source,
            },
            "direct_response": decision.response,
            "standalone_query": decision.standalone_query,
            "rewritten": decision.rewritten,
            "extraction": decision.retrieval.public(),
            "execution_log": execution_log,
        }

    def _respond_directly(self, state: QueryState) -> dict[str, Any]:
        """返回预处理模型生成的普通回答或自然语言澄清。"""
        result = ResultBuilder.direct_response(
            state["task_id"],
            state.get("direct_response", ""),
            state["intent"],
            list(state.get("execution_log") or []),
        )
        return {
            "workflow_mode": result.workflow_mode,
            "result": result.model_dump(mode="json"),
        }

    def _answer_qa(self, state: QueryState) -> dict[str, Any]:
        answer = unavailable_explanation("NO_SIGNAL_BATCH")
        result = ResultBuilder.qa(
            state["task_id"], answer, state["intent"], state.get("analysis_sources") or []
        )
        return {
            **self._clear_explanation(),
            "execution_result": None,
            "workflow_mode": "qa",
            "result": result.model_dump(mode="json"),
        }

    @staticmethod
    def _clear_explanation() -> dict[str, Any]:
        # Derived artifacts are always rebuilt. A caller/checkpoint package
        # cannot bypass SignalEngine in the official Graph path.
        return {"signal_batch": None, "prompt_package": None, "explanation_response": None,
                "explanation_prompt_package": None, "explanation_task_id": None,
                "explanation_for_query": None}

    @staticmethod
    def _explanation_failure(code: str) -> dict[str, Any]:
        return {"prompt_package": None,
                "explanation_response": unavailable_explanation(code).model_dump(mode="json")}

    @staticmethod
    def _execution_payload(execution: SqlExecution) -> dict[str, Any]:
        """Detach the verified execution for Table/state, never for the prompt."""
        contract = execution.result_contract
        return {
            "sql": execution.sql, "success": execution.success,
            "columns": list(execution.columns), "rows": deepcopy(execution.rows),
            "error": execution.error,
            "result_contract": contract.model_dump(mode="json") if contract is not None else None,
            "result_id": execution.result_id or (contract.result_id if contract is not None else None),
        }

    def _build_signal_batch(self, state: QueryState) -> dict[str, Any]:
        """Obtain already computed Signals from a configured trusted source.

        The source receives only invocation identity, including an execution
        fingerprint. Selection, declarations and all business calculations
        belong to its upstream producer, not to this Graph or SignalEngine.
        """
        update = self._clear_explanation()
        source = getattr(self, "signal_source", None)
        if source is None:
            return {**update, **self._explanation_failure("NO_SIGNAL_BATCH")}
        try:
            route = (state.get("result") or {}).get("route")
            execution = state.get("execution_result") if route == "database_query" else None
            if route == "database_query" and (not execution or execution.get("success") is not True):
                return {**update, **self._explanation_failure("EXECUTION_UNAVAILABLE")}
            request = SignalRequest(
                task_id=state["task_id"], query=state["query"], session_id=state.get("session_id", ""),
                user_id=(state.get("access_scope") or {}).get("user_id"), route=route,
                execution_result_id=execution.get("result_id") if execution is not None else None,
                execution_digest=execution_digest(execution) if execution is not None else None,
            )
        except Exception:
            return {**update, **self._explanation_failure("INVALID_SIGNAL_DELIVERY")}
        try:
            delivery = source(request)
        except Exception:
            # The externally configured delivery boundary must not discard a
            # successful table or expose exception text as business evidence.
            return {**update, **self._explanation_failure("SIGNAL_DELIVERY_FAILED")}
        if delivery is None:
            return {**update, **self._explanation_failure("NO_SIGNAL_BATCH")}
        try:
            signals = resolve_signals(delivery, request)
        except Exception:
            return {**update, **self._explanation_failure("INVALID_SIGNAL_DELIVERY")}
        try:
            batch = getattr(self, "signal_engine", SignalEngine()).build(signals)
            # Revalidation also catches a malformed custom Engine dependency.
            batch = SignalBatch.model_validate_json(batch.model_dump_json())
        except Exception:
            return {**update, **self._explanation_failure("INVALID_SIGNAL_BATCH")}
        return {**update, "signal_batch": batch.model_dump(mode="json")}

    def _build_explanation_prompt(self, state: QueryState) -> dict[str, Any]:
        raw_batch = state.get("signal_batch")
        if raw_batch is None:
            return {"prompt_package": None}
        try:
            batch = SignalBatch.model_validate_json(json.dumps(raw_batch, allow_nan=False))
            context = build_explanation_context(batch)
            package = build_prompt_package(context, question=state["query"])
        except Exception:
            return self._explanation_failure("PROMPT_BUILD_FAILED")
        return {"prompt_package": package.model_dump(mode="json"), "explanation_response": None}

    def _generate_explanation(self, state: QueryState) -> dict[str, Any]:
        """Explain only this run's projected package, then attach to Table UI."""
        raw_package = state.get("prompt_package")
        if raw_package is None:
            raw_response = state.get("explanation_response")
            try:
                response = (ExplanationResponse.model_validate_json(json.dumps(raw_response, allow_nan=False))
                            if raw_response is not None else unavailable_explanation("NO_SIGNAL_BATCH"))
                if response.generation_status != "unavailable":
                    response = unavailable_explanation("NO_SIGNAL_BATCH")
            except (ValueError, TypeError):
                response = unavailable_explanation("NO_SIGNAL_BATCH")
        else:
            try:
                package = PromptPackage.model_validate_json(json.dumps(raw_package, allow_nan=False))
            except (ValueError, TypeError):
                response = unavailable_explanation("INVALID_PROMPT_PACKAGE")
            else:
                try:
                    response = (self.response_generator.answer_qa(package)
                                if (state.get("result") or {}).get("route") == "data_qa"
                                else self.response_generator.finalize(package))
                except Exception:
                    response = unavailable_explanation("LLM_CALL_FAILED", generation_status="failed", package=package)
                validation = validate_response(response, package)
                response = (validation.validated_response if validation.status == "validated"
                            else unavailable_explanation("RESPONSE_VALIDATION_FAILED",
                                                         generation_status="validation_failed", package=package))
        log = list(state.get("execution_log") or [])
        log.append({"stage": "result_explanation", "success": response.generation_status == "generated",
                    "codes": list(response.diagnostic_codes)})
        result = ResultBuilder.with_explanation(state["result"], response, log)
        return {"explanation_response": response.model_dump(mode="json"),
                "execution_log": log, "result": result.model_dump(mode="json")}

    # preprocess 写入 State["standalone_query"]，retrieve_schema 再读取它（8.27）。
    # _retrieve_schema()：把“用户想找什么”变成“数据库里真正相关的 Schema 结构”。
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

    @staticmethod
    def _after_retrieval(state: QueryState) -> str:
        if state.get("clarification"):
            return "human_clarification"
        return "prepare_single_database" if len(state.get("database_names") or []) <= 1 else "run_multi_database"

    def _human_clarification(self, state: QueryState) -> dict[str, Any]:
        # LangGraph 将 Command(resume=...) 的值作为 interrupt 返回值。
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

    # 向数据库 Agent 提供 standalone_query、database、schema_graph、schema_context、
    # retrieval、workspace 和 access_scope；前一个 Node 已准备好数据库环境，
    # 接下来由单数据库 Agent 决定如何查询（8.27）。
    def _prepare_single_database(self, state: QueryState) -> dict[str, Any]:
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
        if decision["action"] == "clarify":
            return {
                "workflow_mode": "single_database_agent",
                "clarification": decision["clarification"],
                "mcp_tool_trace": decision.get("tool_trace", []),
                "direct_sql": "",
            }
        execution = decision["execution"]
        # 类似 tool calling：SingleDatabaseAgent 将 query、schema 和 available tools
        # 提供给 LLM，由 LLM 判断需要澄清还是调用数据库 Tool（8.27）。
        return {
            "workflow_mode": "single_database_agent",
            "clarification": None,
            "mcp_execution": execution,
            "mcp_tool_trace": decision.get("tool_trace", []),
            "direct_sql": str(execution.get("sql") or ""),
            "sql_source": decision.get("source", "model"),
        }

    @staticmethod
    def _restore_execution(
        raw_execution: dict[str, Any], direct_sql: str = "",
    ) -> SqlExecution:
        raw_contract = raw_execution.get("result_contract")
        try:
            contract = None
            if raw_contract is not None:
                if not isinstance(raw_contract, dict) or "version" not in raw_contract:
                    raise ValueError("result_contract 必须是显式包含 version 的对象")
                contract = ResultContract.model_validate(raw_contract)
            # Validate the uncoerced envelope first: bool("false") and str(...) must
            # never hide an inconsistent or incorrectly typed supplied fact.
            consistency = validate_execution_consistency(raw_execution, contract)
            if consistency.status == "inconsistent":
                fields = ", ".join(issue.field for issue in consistency.conflicts)
                raise ValueError(f"一致性冲突字段：{fields}")
            success = raw_execution.get("success")
            if type(success) is not bool:
                raise ValueError("MCP success 必须是明确的 bool")
            sql = raw_execution.get("sql")
            execution = SqlExecution(
                sql=sql if sql is not None else direct_sql,
                success=success,
                columns=list(raw_execution.get("columns") or []),
                rows=list(raw_execution.get("rows") or []),
                error=raw_execution.get("error"),
                result_contract=contract,
                result_id=raw_execution.get("result_id"),
            )
            # Check the actual consumer object as well (including a legacy SQL
            # fallback). Unknown metadata stays unknown, not synthesized evidence.
            consistency = validate_execution_consistency(execution, contract)
            if consistency.status == "inconsistent":
                fields = ", ".join(issue.field for issue in consistency.conflicts)
                raise ValueError(f"重建 execution 一致性冲突字段：{fields}")
            # Legacy/insufficient_evidence results may continue for compatibility;
            # proceeding does not certify complete result identity or fidelity.
        except ValidationError as exc:
            # Do not copy row values or the whole payload into a validation log.
            error = exc.errors(include_input=False, include_url=False)[0]
            location = ".".join(str(item) for item in error["loc"])
            raise PipelineStageError(
                "result_contract_validation",
                f"ResultContract 校验失败：{location}: {error['msg']}",
            ) from exc
        except (ValueError, TypeError) as exc:
            raise PipelineStageError(
                "result_contract_validation", f"ResultContract 校验失败：{exc}",
            ) from exc
        return execution

#把已经执行好的数据库结果整理成 Workflow 最终结果
    def _execute_single_database(self, state: QueryState) -> dict[str, Any]:
        database = (state.get("database_names") or ["askdata_mock"])[0]
        raw_execution = state.get("mcp_execution") or {}
        contract_error = None
        try:
            execution = self._restore_execution(raw_execution, state.get("direct_sql") or "")
        except PipelineStageError as exc:
            # Stop in this existing node, including on a resumed HITL run.
            # An invalid supplied contract must not silently become legacy data.
            contract_error = exc
            execution = SqlExecution(
                sql=str(raw_execution.get("sql") or state.get("direct_sql") or ""),
                success=False,
                error=exc.message,
            )
        trace = list(state.get("mcp_tool_trace") or [])
        log = [
            {
                "stage": "mcp_tool_call",
                "success": not bool(item.get("result", {}).get("error")),
                **item,
            }
            for item in trace
        ]
        log.append({
            "stage": contract_error.stage if contract_error else "execute_duckdb",
            "success": execution.success,
            "error": execution.error,
            "via": "mcp",
        })
        database_call = next(
            (item for item in reversed(trace) if item.get("tool") == f"query_{database}"),
            {},
        )
        call = {
            "call_index": int(database_call.get("call_index") or 1),
            "database": database,
            "arguments": {
                "mode": "single_database_agent",
                "transport": "mcp_in_process",
                "tool_name": database_call.get("tool"),
                "schema_graph_version": state.get("schema_graph", {}).get("graph_version"),
                "sql_source": state.get("sql_source", "model"),
            },
            "sql": execution.sql,
            "success": execution.success,
            "row_count": len(execution.rows),
            "error": execution.error,
        }
        if not execution.success:
            result = ResultBuilder.failed(state, execution, log)
            response = unavailable_explanation("EXECUTION_UNAVAILABLE")
            result = result.model_copy(update={"explanation": response})
            if contract_error:
                result.message = "查询结果契约校验失败"
            return {**self._clear_explanation(), "execution_result": self._execution_payload(execution),
                    "explanation_response": response.model_dump(mode="json"),
                    "execution_log": log, "tool_calls": [call], "result": result.model_dump(mode="json")}
        final = unavailable_explanation("NO_SIGNAL_BATCH")
        result = ResultBuilder.completed(state, [execution], execution, final, [call], log)
        return {**self._clear_explanation(), "execution_result": self._execution_payload(execution),
                "execution_log": log, "tool_calls": [call], "result": result.model_dump(mode="json")}

    def _run_multi_database(self, state: QueryState) -> dict[str, Any]:
        """返回尚未实现的多数据库查询结果。"""
        failure = SqlExecution(
            sql="",
            success=False,
            error="当前仅支持单库直接查询；多库 Handoff 尚未启用。",
        )
        result = ResultBuilder.failed(state, failure, [])
        response = unavailable_explanation("EXECUTION_UNAVAILABLE")
        result = result.model_copy(update={"explanation": response})
        return {**self._clear_explanation(), "execution_result": self._execution_payload(failure),
                "explanation_response": response.model_dump(mode="json"),
                "workflow_mode": "multi_database_pending", "result": result.model_dump(mode="json")}
