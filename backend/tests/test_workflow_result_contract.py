import csv
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from langgraph.checkpoint.memory import InMemorySaver

from app.errors import PipelineStageError
from app.mcp_runtime import LocalMcpClient, create_local_mcp_server
from app.querying.duckdb_engine import DuckDbEngine
from app.querying.models import SqlExecution
from app.querying.result_contract import ColumnMetadata, ExecutionData, ResultContract
from app.workflows.query_graph import QueryWorkflow
from app.workflows.result_builder import ResultBuilder


class WorkflowResultContractTest(unittest.TestCase):
    def setUp(self):
        # Exercise the actual node/helper without constructing any model client.
        self.workflow = QueryWorkflow.__new__(QueryWorkflow)
        self.workflow.response_generator = SimpleNamespace(finalize=Mock(return_value={
            "valid": True, "title": "Test result", "analysis": "Test explanation",
        }))

    @staticmethod
    def payload():
        sql = "SELECT CAST('12.30' AS DECIMAL(8,2)) AS amount, '华北' AS region"
        contract = ResultContract(
            result_id="test-result",
            execution=ExecutionData(
                database="askdata_mock", sql=sql, success=True,
                columns=[
                    ColumnMetadata(id="column_0", ordinal=0, name="amount", dtype="DECIMAL(8,2)", value_encoding="decimal_text", representation_status="preserved"),
                    ColumnMetadata(id="column_1", ordinal=1, name="region", dtype="VARCHAR", value_encoding="native_json", representation_status="preserved"),
                ],
                rows=[["12.30", "华北"]], returned_rows=1, total_rows=1,
                truncated=False, completeness="complete_query_output",
            ),
        )
        return {
            "database": "askdata_mock", "sql": sql, "success": True,
            "columns": ["amount", "region"], "rows": [{"amount": 12.3, "region": "华北"}],
            "row_count": 1, "error": None, "result_contract": contract.model_dump(mode="json"),
        }

    @staticmethod
    def state(payload):
        return {
            "task_id": "workflow-contract-test", "standalone_query": "查询本月各地区销售额",
            "schema_context": "", "schema_graph": {}, "database_names": ["askdata_mock"],
            "mcp_execution": payload,
            "mcp_tool_trace": [{"tool": "query_askdata_mock", "call_index": 1, "result": payload}],
        }

    @staticmethod
    def mcp_payload(sql):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "askdata_mock"
            folder.mkdir()
            with (folder / "orders_current.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["order_id", "region"])
                writer.writerows((index, "华北") for index in range(201))
            client = LocalMcpClient(create_local_mcp_server(DuckDbEngine(root)))
            return client.call_tool("query_askdata_mock", {"sql": sql})

    def assert_rejected(self, payload):
        before = deepcopy(payload)
        with self.assertRaises(PipelineStageError) as raised:
            self.workflow._restore_execution(payload)
        self.assertEqual(raised.exception.stage, "result_contract_validation")
        self.workflow.response_generator.finalize.reset_mock()
        state = self.state(payload)
        before_state = deepcopy(state)
        update = self.workflow._execute_single_database(state)
        self.assertEqual(update["result"]["status"], "failed")
        self.assertEqual(update["result"]["message"], "查询结果契约校验失败")
        self.assertEqual(update["execution_log"][-1]["stage"], "result_contract_validation")
        self.workflow.response_generator.finalize.assert_not_called()
        self.assertEqual(payload, before)
        self.assertEqual(state, before_state)

    def test_typed_contract_restored_without_changing_legacy_fields(self):
        payload = self.payload()
        before = deepcopy(payload)
        execution = self.workflow._restore_execution(payload)
        self.assertIsInstance(execution, SqlExecution)
        self.assertIsInstance(execution.result_contract, ResultContract)
        self.assertEqual(execution.result_contract.model_dump(mode="json"), payload["result_contract"])
        for name in ("sql", "success", "columns", "rows", "error"):
            self.assertEqual(getattr(execution, name), payload[name])
        self.assertEqual(execution.result_contract.execution.rows[0][0], "12.30")
        self.assertEqual(execution.rows[0]["amount"], 12.3)
        self.assertEqual(payload, before)
        self.workflow.response_generator.finalize.assert_not_called()

    def test_missing_or_null_contract_continues_as_unknown(self):
        for missing in (True, False):
            with self.subTest(missing=missing):
                payload = self.payload()
                if missing:
                    del payload["result_contract"]
                else:
                    payload["result_contract"] = None
                before = deepcopy(payload)
                with patch.object(ResultBuilder, "completed", wraps=ResultBuilder.completed) as completed:
                    update = self.workflow._execute_single_database(self.state(payload))
                execution = completed.call_args.args[2]
                self.assertIsNone(execution.result_contract)
                self.assertEqual(execution.rows, payload["rows"])
                self.assertEqual(update["result"]["status"], "completed")
                self.assertEqual(payload, before)

    def test_legacy_direct_sql_fallback_is_unchanged(self):
        execution = self.workflow._restore_execution({"success": True}, "SELECT 1 AS value")
        self.assertEqual(execution.sql, "SELECT 1 AS value")
        self.assertEqual(execution.columns, [])
        self.assertEqual(execution.rows, [])
        self.assertIsNone(execution.result_contract)

    def test_unknown_metadata_is_not_filled_from_legacy_payload(self):
        payload = self.payload()
        data = payload["result_contract"]["execution"]
        for name in ("returned_rows", "total_rows", "truncated", "completeness", "provenance"):
            data[name] = None
        for column in data["columns"]:
            for name in ("dtype", "value_encoding", "representation_status"):
                column[name] = None
        execution = self.workflow._restore_execution(payload)
        self.assertEqual(execution.result_contract.model_dump(mode="json"), payload["result_contract"])
        self.assertIsNone(execution.result_contract.execution.returned_rows)
        self.assertIsNone(execution.result_contract.execution.columns[0].dtype)

    def test_absent_metadata_remains_unknown_without_mutating_state(self):
        payload = self.payload()
        payload["result_contract"]["execution"] = {}
        before = deepcopy(payload)
        execution = self.workflow._restore_execution(payload)
        self.assertTrue(all(value is None for value in execution.result_contract.execution.model_dump().values()))
        self.assertEqual(payload, before)

    def test_invalid_or_missing_version_is_rejected(self):
        for version in ("2", 1, None, False):
            with self.subTest(version=version):
                payload = self.payload()
                payload["result_contract"]["version"] = version
                self.assert_rejected(payload)
        payload = self.payload()
        del payload["result_contract"]["version"]
        self.assert_rejected(payload)

    def test_present_invalid_contract_is_not_treated_as_legacy(self):
        for contract in ({}, [], "", False, 0):
            with self.subTest(contract=contract):
                payload = self.payload()
                payload["result_contract"] = contract
                self.assert_rejected(payload)

    def test_contract_row_width_and_returned_count_must_match(self):
        for field, value in (("rows", [["12.30"]]), ("returned_rows", 2), ("returned_rows", True)):
            with self.subTest(field=field, value=value):
                payload = self.payload()
                payload["result_contract"]["execution"][field] = value
                self.assert_rejected(payload)

    def test_column_ordinal_and_identity_are_validated(self):
        for field, value in (("ordinal", 0), ("ordinal", 3), ("id", "column_0")):
            with self.subTest(field=field, value=value):
                payload = self.payload()
                payload["result_contract"]["execution"]["columns"][1][field] = value
                self.assert_rejected(payload)

    def test_legacy_column_order_and_row_shape_must_match(self):
        cases = [
            ("columns", ["region", "amount"]),
            ("columns", "amount"),
            ("columns", 1),
            ("rows", [[12.3, "华北"]]),
            ("rows", [{"amount": 12.3}]),
            ("rows", [{"amount": 12.3, "region": "华北", "extra": 1}]),
            ("rows", {"amount": 12.3, "region": "华北"}),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                payload = self.payload()
                payload[field] = value
                self.assert_rejected(payload)

    def test_legacy_row_counts_cannot_disagree_with_contract(self):
        for field, value in (("rows", []), ("row_count", 2), ("row_count", True)):
            with self.subTest(field=field, value=value):
                payload = self.payload()
                payload[field] = value
                self.assert_rejected(payload)
        payload = self.payload()
        payload["result_contract"]["execution"]["rows"] = None
        payload["rows"] = []
        payload["row_count"] = 0
        self.assert_rejected(payload)  # Known returned_rows still must match the outer rows.

    def test_unknown_column_metadata_does_not_skip_known_row_width_check(self):
        payload = self.payload()
        payload["result_contract"]["execution"]["columns"] = None
        execution = self.workflow._restore_execution(payload)
        self.assertIsNone(execution.result_contract.execution.columns)
        payload["columns"] = ["amount"]
        payload["rows"] = [{"amount": 12.3}]
        self.assert_rejected(payload)

    def test_real_mcp_contract_reaches_existing_result_builder(self):
        queries = [
            "SELECT CAST('12.30' AS DECIMAL(8,2)) AS amount, CAST(NULL AS VARCHAR) AS region",
            "SELECT 1 AS repeated, 2 AS repeated",
            "SELECT order_id FROM orders_current ORDER BY order_id",
            "SELECT order_id FROM orders_current WHERE order_id < 0",
            "SELECT [1, 2] AS items",
        ]
        for sql in queries:
            with self.subTest(sql=sql):
                payload = self.mcp_payload(sql)
                state = self.state(payload)
                before = deepcopy(state)
                with patch.object(ResultBuilder, "completed", wraps=ResultBuilder.completed) as completed:
                    update = self.workflow._execute_single_database(state)
                execution = completed.call_args.args[2]
                self.assertEqual(execution.result_contract.model_dump(mode="json"), payload["result_contract"])
                self.assertIs(completed.call_args.args[1][0], execution)
                self.workflow.response_generator.finalize.assert_not_called()
                self.assertEqual(update["result"]["explanation"]["generation_status"], "unavailable")
                self.assertEqual(update["result"]["explanation"]["diagnostic_codes"], ["NO_SIGNAL_BATCH"])
                self.assertEqual(update["result"]["status"], "completed")
                self.assertEqual(state, before)

    def test_sql_failure_keeps_contract_and_skips_finalization(self):
        payload = self.mcp_payload("SELECT missing_column FROM orders_current")
        with patch.object(ResultBuilder, "failed", wraps=ResultBuilder.failed) as failed:
            update = self.workflow._execute_single_database(self.state(payload))
        execution = failed.call_args.args[1]
        self.assertEqual(execution.result_contract.model_dump(mode="json"), payload["result_contract"])
        self.assertIsNone(execution.result_contract.execution.truncated)
        self.assertIsNone(execution.result_contract.execution.returned_rows)
        self.assertEqual(update["result"]["status"], "failed")
        self.assertEqual(update["execution_log"][-1]["stage"], "execute_duckdb")
        self.workflow.response_generator.finalize.assert_not_called()

    def test_compiled_graph_retains_existing_nodes_and_terminal_edge(self):
        self.workflow.checkpointer = InMemorySaver()
        graph = self.workflow._compile().get_graph()
        self.assertEqual(set(graph.nodes), {
            "__start__", "__end__", "preprocess", "respond_directly", "answer_qa",
            "retrieve_schema", "human_clarification", "prepare_single_database",
            "execute_single_database", "run_multi_database",
            "build_signal_batch", "build_explanation_prompt", "generate_explanation",
        })
        self.assertTrue(any(
            edge.source == "execute_single_database" and edge.target == "__end__"
            for edge in graph.edges
        ))
        self.assertTrue(any(
            edge.source == "execute_single_database" and edge.target == "build_signal_batch"
            for edge in graph.edges
        ))


if __name__ == "__main__":
    unittest.main()
