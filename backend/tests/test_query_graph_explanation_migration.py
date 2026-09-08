"""Formal Graph wiring with real Signal, Engine, Prompt and response contracts.

Business calculators finish in fixture setup. The injected backend source only
delivers their existing outputs; the Graph never derives facts from table rows.
SQL acquisition and model language choices are mocked at their outer boundaries.
"""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from pydantic import ValidationError

from app.config import Settings
from app.models import QueryResult
from app.querying.business_signals.batch import SignalBatch
from app.querying.business_signals.engine import SignalEngine
from app.querying.business_signals.models import BusinessSignal
from app.querying.explanation.context_builder import build_explanation_context
from app.querying.explanation.prompt_builder import PromptPackage, build_prompt_package
from app.querying.explanation.response_models import ExplanationResponse
from app.querying.result_contract import ResultContract
from app.retrieval import SchemaIndex
from app.service import AskDataService
from app.workflows import query_graph
from app.workflows.query_graph import QueryWorkflow
from app.workflows.signal_delivery import SignalDelivery, SignalRequest, execution_digest
from test_explanation_context import all_keys, no_upstream_calls
from test_response_generator_migration import package_for
from test_service import FakeModelClient
from test_signal_engine import s1, s2, s3
from test_target_attainment import s1_inputs


FORBIDDEN_PROMPT_KEYS = {
    "sql", "rows", "columns", "execution", "execution_result", "business_context",
    "result_contract", "analysis_context", "raw_value", "provenance", "source_fields",
    "description", "schema_context",
}


def choose_blocks(system, user):
    data = json.loads(user)
    return json.dumps({"blocks": [
        {"signal_index": block["ref"]["signal_index"],
         "expression_variant": block["expression_variant"], "wording": "summary"}
        for block in data["fact_blocks"]
    ]})


class PromptClient(FakeModelClient):
    """Existing service router/SQL fake plus the strict explanation choice API."""

    def __init__(self):
        super().__init__()
        self.chat = Mock(side_effect=choose_blocks)


class QueryGraphExplanationMigrationTests(unittest.TestCase):
    @staticmethod
    def execution_for(signals=None):
        signals = s1() if signals is None else signals
        return {
            "success": True, "sql": "SELECT 100 AS amount /* SECRET_SQL_432 */",
            "columns": ["amount", "table_note"],
            "rows": [{"amount": 100, "table_note": "SECRET_TABLE_ROW_432"}],
            "error": None, "result_id": signals[0].evidence[0].result_id,
        }

    @staticmethod
    def state(task="phase432-test", route="database_query"):
        return {
            "task_id": task, "query": "解释已授权业务信号", "session_id": "user:session",
            "access_scope": {"user_id": "user"}, "workspace": {},
            "intent": {"action": route, "reason": "captured signals"},
            "analysis_context": "SECRET_OLD_ANALYSIS_432",
            "recent_result_context": "SECRET_OLD_ROWS_432",
            "short_term_context": "SECRET_OLD_HISTORY_432",
            "analysis_sources": [{"task_id": "old-table", "title": "existing table"}],
        }

    def workflow(self, source=None, *, route="database_query", execution=None, client=None):
        client = client or PromptClient()
        workflow = QueryWorkflow(client, SimpleNamespace(), Settings(api_key=""),
                                 signal_source=source)
        workflow.preprocessor = SimpleNamespace(prepare=Mock(return_value=SimpleNamespace(
            source="model", action=route, confidence=1.0, reason="captured signals",
            response_type="answer", response="", standalone_query="captured query",
            rewritten=False, retrieval=SimpleNamespace(public=lambda: {}),
        )))
        # The existing execution preparation is an acquisition boundary. New
        # explanation nodes and the actual SignalEngine remain unmocked.
        workflow._retrieve_schema = Mock(return_value={
            "standalone_query": "captured query", "retrieval": {}, "schema_graph": {},
            "schema_context": "SECRET_SCHEMA_432", "database_names": ["askdata_mock"],
            "clarification": None,
        })
        supplied = self.execution_for() if execution is None else execution
        workflow._prepare_single_database = Mock(return_value={
            "workflow_mode": "single_database_agent", "clarification": None,
            "mcp_execution": supplied, "mcp_tool_trace": [],
        })
        workflow.graph = workflow._compile()
        return workflow, client

    @staticmethod
    def source_for(signals):
        return Mock(side_effect=lambda request: SignalDelivery(request=request, signals=tuple(signals)))

    def invoke(self, workflow, state=None):
        state = self.state() if state is None else state
        return workflow.invoke(state, state["task_id"])

    def checkpoint(self, workflow, task="phase432-test"):
        return workflow.graph.get_state(workflow.run_config(task)).values

    def assert_unavailable(self, result, code, *, table=True):
        self.assertIn(result.explanation.generation_status, ("unavailable", "failed", "not_requested", "validation_failed"))
        self.assertIn(code, result.explanation.diagnostic_codes)
        self.assertEqual(result.explanation.blocks, ())
        self.assertEqual(result.explanation.citations, ())
        self.assertNotIn("SECRET_", result.analysis)
        if table:
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.rows, [{"amount": 100, "table_note": "SECRET_TABLE_ROW_432"}])

    def test_compiled_query_runs_real_engine_batch_prompt_and_response(self):
        signals = s1()
        source = self.source_for(signals)
        workflow, client = self.workflow(source)
        with patch.object(SignalEngine, "build", autospec=True, side_effect=SignalEngine.build) as engine:
            result = self.invoke(workflow)
        self.assertEqual(engine.call_count, 1)
        self.assertEqual(engine.call_args.args[1], list(signals))
        request = source.call_args.args[0]
        self.assertIsInstance(request, SignalRequest)
        self.assertEqual(request.route, "database_query")
        saved = self.checkpoint(workflow)
        batch = SignalBatch.model_validate(saved["signal_batch"])
        package = PromptPackage.model_validate_json(json.dumps(saved["prompt_package"]))
        self.assertEqual(batch.signals, signals)
        self.assertEqual(package, build_prompt_package(build_explanation_context(batch),
                                                      question=self.state()["query"]))
        self.assertEqual(request.execution_digest, execution_digest(saved["execution_result"]))
        self.assertEqual(request.execution_result_id, signals[0].evidence[0].result_id)
        self.assertEqual(result.explanation.generation_status, "generated")
        self.assertEqual(result.explanation.citations, package.reference_blocks)
        self.assertEqual(tuple(item.fact for item in result.explanation.blocks), package.fact_blocks)
        self.assertEqual(saved["explanation_response"], result.explanation.model_dump(mode="json"))
        self.assertEqual(client.chat.call_count, 1)

    def test_s1_s2_s3_database_delivery_uses_each_current_result(self):
        for factory in (s1, s2, s3):
            with self.subTest(signal=factory.__name__):
                signals = factory()
                workflow, _ = self.workflow(self.source_for(signals), execution=self.execution_for(signals))
                result = self.invoke(workflow)
                self.assertEqual(result.explanation.generation_status, "generated")
                self.assertEqual(len(result.explanation.blocks), len(signals))

    def test_contract_only_result_identity_reaches_formal_signal_delivery(self):
        inputs = s1_inputs()
        signals = s1(inputs)
        context = inputs["actual"].context
        contract = ResultContract(result_id=context.result_id,
                                  version=context.result_contract_version,
                                  execution=deepcopy(context.execution))
        columns = [column.name for column in contract.execution.columns]
        rows = [dict(zip(columns, row)) for row in contract.execution.rows]
        # Match DuckDB's existing legacy display codec. Canonical exact decimal
        # text remains in ResultContract and in already-calculated Evidence.
        for row in rows:
            row[columns[1]] = float(row[columns[1]])
        execution = {
            "success": contract.execution.success, "sql": contract.execution.sql,
            "columns": columns, "rows": rows, "error": contract.execution.error,
            "result_contract": contract.model_dump(mode="json"),
        }
        self.assertNotIn("result_id", execution)
        before = deepcopy(execution)
        source = self.source_for(signals)
        workflow, client = self.workflow(source, execution=execution)
        result = self.invoke(workflow)
        self.assertEqual(result.explanation.generation_status, "generated")
        request = source.call_args.args[0]
        self.assertEqual(request.execution_result_id, contract.result_id)
        saved = self.checkpoint(workflow)["execution_result"]
        self.assertEqual(saved["result_id"], contract.result_id)
        self.assertEqual(saved["result_contract"], contract.model_dump(mode="json"))
        self.assertEqual(request.execution_digest, execution_digest(saved))
        changed_metadata = deepcopy(saved)
        changed_metadata["result_contract"]["execution"]["columns"][1]["dtype"] = "DECIMAL(19,2)"
        self.assertNotEqual(execution_digest(changed_metadata), request.execution_digest)
        self.assertEqual(result.columns, columns)
        self.assertEqual(result.rows, rows)
        self.assertEqual(result.sql, contract.execution.sql)
        self.assertEqual(execution, before)
        self.assertFalse(all_keys(json.loads(client.chat.call_args.args[1])) & FORBIDDEN_PROMPT_KEYS)

    def test_qa_batches_multiple_existing_signals_without_execution_or_history(self):
        signals = [*s1(), *s2(), *s3()]
        source = self.source_for(signals)
        workflow, client = self.workflow(source, route="data_qa")
        result = self.invoke(workflow, self.state(route="data_qa"))
        request = source.call_args.args[0]
        self.assertEqual(request.route, "data_qa")
        self.assertIsNone(request.execution_result_id)
        self.assertIsNone(request.execution_digest)
        self.assertEqual(result.explanation.generation_status, "generated")
        self.assertEqual(len(result.explanation.blocks), 4)
        self.assertEqual(result.rows, [])
        self.assertIsNone(result.sql)
        self.assertEqual(result.analysis_sources, self.state()["analysis_sources"])
        self.assertNotIn("SECRET_", client.chat.call_args.args[1])
        workflow._prepare_single_database.assert_not_called()

    def test_no_source_and_source_none_cannot_reuse_old_package_or_rows(self):
        package = package_for(s1())
        for source in (None, Mock(return_value=None)):
            with self.subTest(source=source):
                workflow, client = self.workflow(source)
                state = self.state()
                state.update({"explanation_prompt_package": package.model_dump(mode="json"),
                              "explanation_task_id": state["task_id"],
                              "explanation_for_query": state["query"]})
                result = self.invoke(workflow, state)
                self.assert_unavailable(result, "NO_SIGNAL_BATCH")
                client.chat.assert_not_called()

    def test_qa_without_batch_has_explicit_failure_and_no_history_fallback(self):
        workflow, client = self.workflow(route="data_qa")
        result = self.invoke(workflow, self.state(route="data_qa"))
        self.assert_unavailable(result, "NO_SIGNAL_BATCH", table=False)
        self.assertEqual(result.status, "failed")
        client.chat.assert_not_called()

    def test_source_exception_does_not_echo_exception_or_fallback(self):
        workflow, client = self.workflow(Mock(side_effect=RuntimeError("SECRET_SOURCE rows=[900]")))
        self.assert_unavailable(self.invoke(workflow), "SIGNAL_DELIVERY_FAILED")
        client.chat.assert_not_called()

    def test_delivery_must_be_typed_signals_not_batch_prompt_or_arbitrary_dict(self):
        signals = s1()
        for supplied in (SignalEngine().build(signals), package_for(signals),
                         {"signals": [item.model_dump(mode="json") for item in signals]}, "old analysis"):
            with self.subTest(supplied=type(supplied).__name__):
                workflow, client = self.workflow(Mock(return_value=supplied))
                self.assert_unavailable(self.invoke(workflow), "INVALID_SIGNAL_DELIVERY")
                client.chat.assert_not_called()

    def test_malformed_typed_delivery_preserves_table_instead_of_raising(self):
        for signal in (BusinessSignal.model_construct(),
                       s1()[0].model_copy(update={"evidence": None})):
            with self.subTest(signal_type=type(signal).__name__):
                source = Mock(side_effect=lambda request: SignalDelivery.model_construct(
                    request=request, signals=(signal,)))
                workflow, client = self.workflow(source)
                self.assert_unavailable(self.invoke(workflow), "INVALID_SIGNAL_DELIVERY")
                client.chat.assert_not_called()

    def test_wrong_task_query_session_user_and_route_bindings_are_rejected(self):
        signals = s1()
        changes = ({"task_id": "other-task"}, {"query": "other query"},
                   {"session_id": "other-session"}, {"user_id": "other-user"},
                   {"route": "data_qa", "execution_result_id": None, "execution_digest": None})
        for change in changes:
            with self.subTest(change=change):
                source = Mock(side_effect=lambda request: SignalDelivery(
                    request=request.model_copy(update=change), signals=tuple(signals)))
                workflow, client = self.workflow(source)
                self.assert_unavailable(self.invoke(workflow), "INVALID_SIGNAL_DELIVERY")
                client.chat.assert_not_called()

    def test_old_execution_digest_is_rejected_even_when_result_id_matches(self):
        signals = s1()
        deliveries = []

        def source(request):
            if not deliveries:
                deliveries.append(SignalDelivery(request=request, signals=tuple(signals)))
            return deliveries[0]

        first, _ = self.workflow(source)
        self.assertEqual(self.invoke(first).explanation.generation_status, "generated")
        for change in ({"rows": [{"amount": 200, "table_note": "changed"}]},
                       {"sql": "SELECT 200 AS amount"}):
            with self.subTest(change=change):
                execution = self.execution_for(signals)
                execution.update(change)
                next_workflow, client = self.workflow(source, execution=execution)
                result = self.invoke(next_workflow)
                self.assert_unavailable(result, "INVALID_SIGNAL_DELIVERY", table=False)
                self.assertEqual(result.rows, execution["rows"])
                self.assertEqual(result.status, "completed")
                client.chat.assert_not_called()

    def test_every_computed_signal_requires_current_execution_reference(self):
        mixed = [*s1(), *s2()]
        workflow, client = self.workflow(self.source_for(mixed))
        self.assert_unavailable(self.invoke(workflow), "INVALID_SIGNAL_DELIVERY")
        client.chat.assert_not_called()

    def test_execution_without_identity_keeps_table_but_cannot_deliver_signals(self):
        source = self.source_for(s1())
        execution = self.execution_for()
        execution.pop("result_id")
        workflow, client = self.workflow(source, execution=execution)
        result = self.invoke(workflow)
        self.assertEqual(result.explanation.generation_status, "unavailable")
        self.assertEqual(result.rows, execution["rows"])
        source.assert_not_called()
        client.chat.assert_not_called()

    def test_empty_and_failed_only_batches_keep_audit_notice_without_llm(self):
        for signals in ([], s1(s1_inputs(actual=[["华东", None]]))):
            with self.subTest(signals=signals):
                workflow, client = self.workflow(self.source_for(signals))
                result = self.invoke(workflow)
                self.assert_unavailable(result, "NO_DISPLAYABLE_FACTS")
                self.assertEqual(result.explanation.generation_status, "not_requested")
                batch = SignalBatch.model_validate(self.checkpoint(workflow)["signal_batch"])
                self.assertEqual(len(batch.signals), len(signals))
                self.assertEqual(batch.displayable_signal_indices, [])
                if signals:
                    self.assertTrue(result.explanation.notice_blocks)
                client.chat.assert_not_called()

    def test_engine_error_returns_unavailable_without_mutating_signals(self):
        signals = s1()
        before = deepcopy(signals)
        workflow, client = self.workflow(self.source_for(signals))
        with patch.object(SignalEngine, "build", side_effect=ValueError("SECRET_ENGINE")):
            self.assert_unavailable(self.invoke(workflow), "INVALID_SIGNAL_BATCH")
        self.assertEqual(signals, before)
        client.chat.assert_not_called()

    def test_prompt_build_failure_keeps_batch_and_table_without_fallback(self):
        for function in ("build_explanation_context", "build_prompt_package"):
            with self.subTest(function=function):
                workflow, client = self.workflow(self.source_for(s1()))
                with patch.object(query_graph, function, side_effect=ValueError("SECRET_PROMPT rows=[900]")):
                    result = self.invoke(workflow)
                self.assert_unavailable(result, "PROMPT_BUILD_FAILED")
                self.assertIsNotNone(self.checkpoint(workflow)["signal_batch"])
                self.assertIsNone(self.checkpoint(workflow)["prompt_package"])
                client.chat.assert_not_called()

    def test_llm_failure_keeps_table_and_current_package_without_fallback(self):
        workflow, client = self.workflow(self.source_for(s1()))
        client.chat.side_effect = RuntimeError("SECRET_LLM rows=[900]")
        self.assert_unavailable(self.invoke(workflow), "LLM_CALL_FAILED")
        self.assertIsNotNone(self.checkpoint(workflow)["prompt_package"])
        self.assertEqual(client.chat.call_count, 1)

    def test_invalid_llm_response_cannot_publish_numbers_or_arbitrary_prose(self):
        workflow, client = self.workflow(self.source_for(s1()))
        client.chat.side_effect = None
        client.chat.return_value = json.dumps({"text": "SECRET_INVENTED 999", "valid": True})
        result = self.invoke(workflow)
        self.assert_unavailable(result, "RESPONSE_VALIDATION_FAILED")
        self.assertEqual(result.explanation.generation_status, "validation_failed")
        self.assertEqual(client.chat.call_count, 1)

    def test_response_from_another_package_is_rejected_at_final_binding_gate(self):
        from app.querying.response_generator import ResponseGenerator
        other = package_for(s1(s1_inputs(actual=[["华东", "120"]])), question=self.state()["query"])
        response = ResponseGenerator(PromptClient()).generate_from_prompt_package(other)
        workflow, client = self.workflow(self.source_for(s1()))
        workflow.response_generator = SimpleNamespace(
            finalize=Mock(return_value=response), answer_qa=Mock(return_value=response),
            generate_from_prompt_package=Mock(return_value=response),
        )
        result = self.invoke(workflow)
        self.assert_unavailable(result, "RESPONSE_VALIDATION_FAILED")
        self.assertEqual(result.explanation.generation_status, "validation_failed")
        client.chat.assert_not_called()

    def test_prompt_contains_whitelisted_facts_and_no_sql_rows_or_context(self):
        source = self.source_for(s1())
        workflow, client = self.workflow(source)
        result = self.invoke(workflow)
        system, user = client.chat.call_args.args
        self.assertFalse(all_keys(json.loads(user)) & FORBIDDEN_PROMPT_KEYS)
        self.assertNotIn("SECRET_", system + user)
        self.assertNotIn("table_note", system + user)
        self.assertFalse(set(source.call_args.args[0].model_dump()) & FORBIDDEN_PROMPT_KEYS)
        self.assertEqual(result.columns, ["amount", "table_note"])
        self.assertEqual(result.rows, self.execution_for()["rows"])
        self.assertIn("SECRET_SQL_432", result.sql)
        self.assertNotIn("SECRET_", result.analysis)

    def test_signal_delivery_and_graph_do_not_mutate_caller_inputs(self):
        signals = s1()
        deliveries = []

        def deliver(request):
            delivery = SignalDelivery(request=request, signals=tuple(signals))
            deliveries.append((delivery, delivery.model_dump_json()))
            return delivery

        execution, state = self.execution_for(signals), self.state()
        before = deepcopy((signals, execution, state))
        workflow, _ = self.workflow(deliver, execution=execution)
        self.invoke(workflow, state)
        self.assertEqual((signals, execution, state), before)
        self.assertEqual(deliveries[0][0].model_dump_json(), deliveries[0][1])

    def test_state_batch_package_response_and_result_json_roundtrip(self):
        workflow, _ = self.workflow(self.source_for(s3()), execution=self.execution_for(s3()))
        result = self.invoke(workflow)
        saved = self.checkpoint(workflow)
        wire = json.loads(json.dumps({key: saved[key] for key in (
            "execution_result", "signal_batch", "prompt_package", "explanation_response", "result")}))
        self.assertEqual(wire["execution_result"], saved["execution_result"])
        batch = SignalBatch.model_validate(wire["signal_batch"])
        self.assertEqual(SignalBatch.model_validate_json(batch.model_dump_json()), batch)
        package = PromptPackage.model_validate_json(json.dumps(wire["prompt_package"]))
        self.assertEqual(PromptPackage.model_validate_json(package.model_dump_json()), package)
        response = ExplanationResponse.model_validate_json(json.dumps(wire["explanation_response"]))
        self.assertEqual(response, result.explanation)
        self.assertEqual(QueryResult.model_validate(wire["result"]), result)
        self.assertEqual(QueryResult.model_validate_json(result.model_dump_json()), result)

    def test_old_state_outputs_are_cleared_before_missing_delivery(self):
        source = self.source_for(s1())
        workflow, client = self.workflow(source)
        first = self.invoke(workflow)
        self.assertEqual(first.explanation.generation_status, "generated")
        state = self.state()
        saved = self.checkpoint(workflow)
        for key in ("signal_batch", "prompt_package", "explanation_response", "execution_result"):
            state[key] = deepcopy(saved[key])
        source.side_effect = None
        source.return_value = None
        client.chat.reset_mock()
        self.assert_unavailable(self.invoke(workflow, state), "NO_SIGNAL_BATCH")
        self.assertIsNone(self.checkpoint(workflow)["signal_batch"])
        self.assertIsNone(self.checkpoint(workflow)["prompt_package"])
        client.chat.assert_not_called()

    def test_fixed_source_and_model_choices_are_deterministic_a_b_a(self):
        workflow, _ = self.workflow(self.source_for(s1()))
        a = self.state()
        first = self.invoke(workflow, a).explanation.model_dump_json()
        self.assertEqual(self.invoke(workflow, a).explanation.model_dump_json(), first)
        b = self.state(task="phase432-other")
        b["query"] = "另一种表达请求"
        self.invoke(workflow, b)
        self.assertEqual(self.invoke(workflow, a).explanation.model_dump_json(), first)

    def test_explanation_nodes_never_rerun_calculators_or_read_semantic_inputs(self):
        signals = s1()
        workflow, _ = self.workflow(self.source_for(signals))
        state = self.state()
        state.update({"mcp_execution": self.execution_for(signals), "schema_graph": {},
                      "database_names": ["askdata_mock"]})
        state.update(workflow._execute_single_database(state))
        # LangGraph's scheduler legitimately reads time for retries. Guard only
        # the deterministic explanation nodes, after acquisition has finished.
        with no_upstream_calls():
            for node in (workflow._build_signal_batch, workflow._build_explanation_prompt,
                         workflow._generate_explanation):
                state.update(node(state))
        result = QueryResult.model_validate(state["result"])
        self.assertEqual(result.explanation.generation_status, "generated")

    def test_failed_execution_terminates_before_signal_source_or_prompt(self):
        source = self.source_for(s1())
        execution = {"success": False, "sql": "SELECT broken", "error": "execution failed"}
        workflow, client = self.workflow(source, execution=execution)
        result = self.invoke(workflow)
        self.assertEqual(result.status, "failed")
        source.assert_not_called()
        client.chat.assert_not_called()

    def test_invalid_contract_terminates_before_signal_source(self):
        source = self.source_for(s1())
        execution = self.execution_for()
        execution["result_contract"] = {"version": "unsupported"}
        workflow, client = self.workflow(source, execution=execution)
        result = self.invoke(workflow)
        self.assertEqual(result.status, "failed")
        self.assertIn("契约校验失败", result.message)
        source.assert_not_called()
        client.chat.assert_not_called()

    def test_delivery_json_roundtrip_and_unknown_fields_are_strict(self):
        request = SignalRequest(task_id="task", query="query", session_id="session",
                                user_id="user", route="data_qa")
        delivery = SignalDelivery(request=request, signals=tuple(s1()))
        self.assertEqual(SignalDelivery.model_validate_json(delivery.model_dump_json()), delivery)
        for extras in ({"rows": []}, {"sql": "SELECT hidden"}, {"signal_batch": {}}):
            raw = json.loads(delivery.model_dump_json())
            raw.update(extras)
            with self.subTest(extras=extras), self.assertRaises(ValidationError):
                SignalDelivery.model_validate_json(json.dumps(raw))

    def test_service_constructor_delivery_reaches_formal_query_graph(self):
        signals = s1()
        source = self.source_for(signals)
        client = PromptClient()
        with tempfile.TemporaryDirectory() as temporary:
            config = Settings(api_key="", embedding_dimensions=32,
                              schema_recall_threshold=0.55, session_archive_enabled=False)
            index = SchemaIndex(client, config, Path(temporary) / "schema_index.json")
            service = AskDataService(client, index, signal_source=source)
            execution = self.execution_for(signals)
            service.workflow.single_database_agent.prepare = Mock(return_value={
                "action": "execute", "execution": execution, "tool_trace": [], "source": "fixture",
            })
            result = service.submit("查询本月各地区销售额", "production-session", user_id="demo_analyst")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.explanation.generation_status, "generated")
        self.assertEqual(result.rows, execution["rows"])
        request = source.call_args.args[0]
        self.assertEqual(request.task_id, result.task_id)
        self.assertEqual(request.query, "查询本月各地区销售额")
        self.assertEqual(request.user_id, "demo_analyst")
        self.assertEqual(request.session_id, "demo_analyst:production-session")
        self.assertNotIn("SECRET_", client.chat.call_args.args[1])

    def test_service_qa_delivery_is_bound_to_current_user_and_session(self):
        signals = [*s1(), *s2()]
        source = self.source_for(signals)
        client = PromptClient()
        with tempfile.TemporaryDirectory() as temporary:
            config = Settings(api_key="", embedding_dimensions=32, session_archive_enabled=False)
            index = SchemaIndex(client, config, Path(temporary) / "schema_index.json")
            service = AskDataService(client, index, signal_source=source)
            for user in ("demo_analyst", "demo_current_sales"):
                result = service.submit("分析刚才的结果", "shared-session", user_id=user)
                request = source.call_args.args[0]
                self.assertEqual(request.user_id, user)
                self.assertEqual(request.session_id, f"{user}:shared-session")
                self.assertEqual(request.task_id, result.task_id)
                self.assertEqual(request.route, "data_qa")
                self.assertEqual(result.explanation.generation_status, "generated")
        self.assertEqual(source.call_count, 2)


if __name__ == "__main__":
    unittest.main()
