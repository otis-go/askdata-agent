import csv
import tempfile
import unittest
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from mcp import Client

from app.errors import PipelineStageError
from app.mcp_runtime import LocalMcpClient, create_local_mcp_server
from app.mcp_runtime.schemas import DatabaseQueryResult
from app.mcp_runtime.tools.database_tools import build_database_query_tool
from app.querying.duckdb_engine import DuckDbEngine
from app.querying.models import SqlExecution
from app.querying.result_consistency import validate_execution_consistency
from app.security import AccessController
from app.workflows.query_graph import QueryWorkflow
from app.workflows.result_builder import ResultBuilder


class ReleaseP2Test(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        folder = root / "askdata_mock"
        folder.mkdir()
        with (folder / "orders_current.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["order_id", "region", "paid_amount"])
            writer.writerows((index, "华北", index + 1) for index in range(201))
        self.engine = DuckDbEngine(root)
        self.scope = AccessController().resolve(None)
        self.client = LocalMcpClient(create_local_mcp_server(self.engine, self.scope))
        self.workflow = QueryWorkflow.__new__(QueryWorkflow)
        self.workflow.response_generator = SimpleNamespace(finalize=Mock(return_value={
            "valid": True, "title": "Test result", "analysis": "Test explanation",
        }))

    @contextmanager
    def recorded_execution(self):
        statements = []
        fetches = []
        original_connect = self.engine.connect

        @contextmanager
        def recording_connect(database):
            with original_connect(database) as connection:
                def execute(sql):
                    statements.append(sql)
                    cursor = connection.execute(sql)

                    def fetchmany(size):
                        rows = cursor.fetchmany(size)
                        fetches.append((size, len(rows)))
                        return rows

                    # No fetchall or second-query API is supplied by this proxy.
                    return SimpleNamespace(description=cursor.description, fetchmany=fetchmany)

                yield SimpleNamespace(execute=execute)

        with patch.object(self.engine, "connect", recording_connect):
            yield statements, fetches

    @staticmethod
    def payload(execution):
        return {
            "database": "askdata_mock", "sql": execution.sql,
            "success": execution.success, "columns": execution.columns,
            "rows": execution.rows, "row_count": len(execution.rows),
            "error": execution.error, "result_id": execution.result_id,
            "result_contract": execution.result_contract.model_dump(mode="json"),
        }

    def round_trip(self, sql):
        executions = []
        sdk_results = []
        original_execute = self.engine.execute

        def capture_execution(*args, **kwargs):
            execution = original_execute(*args, **kwargs)
            executions.append(execution)
            return execution

        class CapturingClient(Client):
            async def call_tool(self, *args, **kwargs):
                result = await super().call_tool(*args, **kwargs)
                sdk_results.append(result)
                return result

        with (
            patch.object(self.engine, "execute", side_effect=capture_execution),
            patch("app.mcp_runtime.client.Client", CapturingClient),
            patch("app.querying.duckdb_engine.uuid4", wraps=uuid4) as generate_id,
            self.recorded_execution() as (statements, fetches),
        ):
            payload = self.client.call_tool("query_askdata_mock", {"sql": sql})
        generate_id.assert_called_once_with()
        self.assertEqual(len(executions), 1)
        self.assertEqual(len(sdk_results), 1)
        execution = executions[0]
        expected = self.payload(execution)
        self.assertIs(type(execution), SqlExecution)
        self.assertIs(type(execution.result_id), str)
        self.assertTrue(execution.result_id.strip())
        self.assertEqual(execution.result_id, execution.result_contract.result_id)
        self.assertFalse(sdk_results[0].is_error)
        self.assertEqual(sdk_results[0].structured_content, expected)
        self.assertEqual(payload, expected)
        self.assertIsNot(payload, sdk_results[0].structured_content)
        self.assertEqual(DatabaseQueryResult.model_validate(payload).result_id, execution.result_id)

        before = deepcopy(payload)
        restored = self.workflow._restore_execution(payload)
        self.assertEqual(restored.result_id, execution.result_id)
        self.assertEqual(restored.result_contract.model_dump(mode="json"), expected["result_contract"])
        self.assertEqual(payload, before)
        state = {
            "task_id": "release-p2-test", "standalone_query": "查询本月各地区销售额",
            "database_names": ["askdata_mock"], "schema_graph": {}, "schema_context": "",
            "mcp_execution": payload,
            "mcp_tool_trace": [{"tool": "query_askdata_mock", "call_index": 1, "result": payload}],
        }
        before_state = deepcopy(state)
        method = "completed" if execution.success else "failed"
        with patch.object(ResultBuilder, method, wraps=getattr(ResultBuilder, method)) as build_result:
            update = self.workflow._execute_single_database(state)
        rebuilt = build_result.call_args.args[2 if execution.success else 1]
        self.assertEqual(rebuilt.result_id, execution.result_id)
        self.assertEqual(rebuilt.result_contract.model_dump(mode="json"), expected["result_contract"])
        self.assertEqual(state, before_state)
        self.assertEqual(update["result"]["status"], "completed" if execution.success else "failed")
        if not execution.success:
            self.workflow.response_generator.finalize.assert_not_called()
        return payload, statements, fetches

    def test_same_sql_twice_has_distinct_ids_and_one_execution_each(self):
        sql = "SELECT 1 AS value"
        results = []
        for _ in range(2):
            with (
                patch("app.querying.duckdb_engine.uuid4", wraps=uuid4) as generate_id,
                self.recorded_execution() as (statements, fetches),
            ):
                execution = self.engine.execute("askdata_mock", sql, self.scope)
            generate_id.assert_called_once_with()
            self.assertEqual(execution.result_id, execution.result_contract.result_id)
            self.assertIs(type(execution.result_id), str)
            self.assertTrue(execution.result_id.strip())
            self.assertEqual(statements, [sql])
            self.assertEqual(fetches, [(201, 1)])
            results.append(execution)
        self.assertNotEqual(results[0].result_id, results[1].result_id)

    def test_aggregate_id_and_contract_survive_real_mcp_and_workflow(self):
        sql = "SELECT region, SUM(paid_amount) AS sales_amount FROM orders_current GROUP BY region"
        payload, statements, fetches = self.round_trip(sql)
        self.assertEqual(statements, [sql])
        self.assertEqual(fetches, [(201, 1)])
        self.assertEqual(payload["rows"], [{"region": "华北", "sales_amount": 20301}])
        self.assertEqual(payload["result_contract"]["execution"]["database"], "askdata_mock")

    def test_truncated_id_and_unknown_total_survive_round_trip(self):
        sql = "SELECT order_id FROM orders_current ORDER BY order_id"
        payload, statements, fetches = self.round_trip(sql)
        self.assertEqual(statements, [sql])
        self.assertEqual(fetches, [(201, 201)])
        data = payload["result_contract"]["execution"]
        self.assertEqual(data["returned_rows"], 200)
        self.assertIsNone(data["total_rows"])
        self.assertIs(data["truncated"], True)

    def test_sql_failure_id_survives_real_mcp_and_workflow(self):
        sql = "SELECT missing_column FROM orders_current"
        payload, statements, fetches = self.round_trip(sql)
        self.assertEqual(statements, [sql])
        self.assertEqual(fetches, [])
        self.assertFalse(payload["success"])
        self.assertIsNone(payload["result_contract"]["execution"]["truncated"])

    def test_validation_failure_still_generates_only_one_id(self):
        payload, statements, fetches = self.round_trip("DELETE FROM orders_current")
        self.assertFalse(payload["success"])
        self.assertEqual(statements, [])
        self.assertEqual(fetches, [])
        self.assertIs(payload["result_contract"]["execution"]["provenance"]["sql_submitted"], False)

    def test_handler_rejects_conflicting_database_from_engine(self):
        sql = "SELECT 1 AS value"
        execution = self.engine.execute("askdata_mock", sql, self.scope)
        execution.result_contract.execution.database = "another_database"
        before = execution.result_contract.model_dump(mode="json")
        handler = build_database_query_tool("askdata_mock", self.engine, self.scope)
        with patch.object(self.engine, "execute", return_value=execution) as execute:
            with self.assertRaisesRegex(ValueError, "database"):
                handler(sql)
        execute.assert_called_once_with("askdata_mock", sql, self.scope)
        self.assertEqual(execution.result_contract.model_dump(mode="json"), before)

    def test_workflow_rejects_database_mismatch_before_restoring(self):
        execution = self.engine.execute("askdata_mock", "SELECT 1 AS value", self.scope)
        payload = self.payload(execution)
        payload["result_contract"]["execution"]["database"] = "another_database"
        before = deepcopy(payload)
        with self.assertRaises(PipelineStageError) as raised:
            self.workflow._restore_execution(payload)
        self.assertEqual(raised.exception.stage, "result_contract_validation")
        self.assertIn("database", str(raised.exception))
        self.assertEqual(payload, before)

    def test_unknown_contract_database_is_not_filled_by_handler(self):
        sql = "SELECT 1 AS value"
        execution = self.engine.execute("askdata_mock", sql, self.scope)
        execution.result_contract.execution.database = None
        handler = build_database_query_tool("askdata_mock", self.engine, self.scope)
        with patch.object(self.engine, "execute", return_value=execution):
            result = handler(sql)
        self.assertEqual(result.database, "askdata_mock")
        self.assertIsNone(result.result_contract.execution.database)
        report = validate_execution_consistency(result.model_dump(), result.result_contract)
        self.assertEqual(report.status, "insufficient_evidence")
        self.assertIn("execution.database", [issue.field for issue in report.unknowns])

    def test_workflow_rejects_different_outer_and_inner_ids(self):
        execution = self.engine.execute("askdata_mock", "SELECT 1 AS value", self.scope)
        payload = self.payload(execution)
        payload["result_id"] = "different-execution-id"
        before = deepcopy(payload)
        with self.assertRaises(PipelineStageError) as raised:
            self.workflow._restore_execution(payload)
        self.assertEqual(raised.exception.stage, "result_contract_validation")
        self.assertIn("result_id", str(raised.exception))
        self.assertEqual(payload, before)

    def test_handler_rejects_different_outer_and_inner_ids(self):
        sql = "SELECT 1 AS value"
        execution = self.engine.execute("askdata_mock", sql, self.scope)
        execution.result_id = "different-execution-id"
        handler = build_database_query_tool("askdata_mock", self.engine, self.scope)
        with patch.object(self.engine, "execute", return_value=execution):
            with self.assertRaisesRegex(ValueError, "result_id"):
                handler(sql)

    def test_missing_outer_id_is_legacy_compatible_and_not_copied(self):
        execution = self.engine.execute("askdata_mock", "SELECT 1 AS value", self.scope)
        for missing in (True, False):
            with self.subTest(missing=missing):
                payload = self.payload(execution)
                if missing:
                    del payload["result_id"]
                else:
                    payload["result_id"] = None
                before = deepcopy(payload)
                restored = self.workflow._restore_execution(payload)
                self.assertIsNone(restored.result_id)
                self.assertEqual(restored.result_contract.result_id, execution.result_id)
                self.assertEqual(payload, before)

    def test_missing_contract_and_id_are_not_synthesized_by_transport(self):
        sql = "SELECT 1 AS value"
        execution = SqlExecution(sql, True, ["value"], [{"value": 1}])
        with patch.object(self.engine, "execute", return_value=execution):
            payload = self.client.call_tool("query_askdata_mock", {"sql": sql})
        self.assertIn("result_id", payload)
        self.assertIn("result_contract", payload)
        self.assertIsNone(payload["result_id"])
        self.assertIsNone(payload["result_contract"])
        restored = self.workflow._restore_execution(payload)
        self.assertIsNone(restored.result_id)
        self.assertIsNone(restored.result_contract)

    def test_existing_outer_id_without_contract_is_preserved_not_replaced(self):
        sql = "SELECT 1 AS value"
        execution = SqlExecution(sql, True, ["value"], [{"value": 1}], result_id="legacy-id")
        with patch.object(self.engine, "execute", return_value=execution):
            payload = self.client.call_tool("query_askdata_mock", {"sql": sql})
        self.assertEqual(payload["result_id"], "legacy-id")
        self.assertIsNone(payload["result_contract"])
        restored = self.workflow._restore_execution(payload)
        self.assertEqual(restored.result_id, "legacy-id")
        self.assertIsNone(restored.result_contract)


if __name__ == "__main__":
    unittest.main()
