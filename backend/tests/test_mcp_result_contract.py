import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp import Client

from app.mcp_runtime import LocalMcpClient, create_local_mcp_server
from app.mcp_runtime.schemas import DatabaseQueryResult
from app.mcp_runtime.tools.database_tools import build_database_query_tool
from app.querying.duckdb_engine import DuckDbEngine
from app.querying.result_contract import ResultContract
from app.security import AccessController


class McpResultContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        folder = root / "askdata_mock"
        folder.mkdir()
        with (folder / "orders_current.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["order_id", "region"])
            writer.writerows((index, "华北") for index in range(201))
        self.engine = DuckDbEngine(root)
        self.scope = AccessController().resolve(None)
        self.server = create_local_mcp_server(self.engine, self.scope)
        self.client = LocalMcpClient(self.server)

    def round_trip(self, sql):
        """Observe all stages of the same real local MCP/DuckDB invocation."""
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
        ):
            payload = self.client.call_tool("query_askdata_mock", {"sql": sql})

        self.assertEqual(len(executions), 1)
        self.assertEqual(len(sdk_results), 1)
        execution = executions[0]
        sdk_result = sdk_results[0]
        self.assertFalse(sdk_result.is_error)
        self.assertIs(type(sdk_result.structured_content), dict)
        self.assertIs(type(payload), dict)
        self.assertIsNot(payload, sdk_result.structured_content)

        expected = {
            "database": "askdata_mock",
            "sql": execution.sql,
            "success": execution.success,
            "columns": execution.columns,
            "rows": execution.rows,
            "row_count": len(execution.rows),
            "error": execution.error,
            "result_contract": execution.result_contract.model_dump(mode="json"),
            "result_id": execution.result_id,
        }
        self.assertEqual(sdk_result.structured_content, expected)
        self.assertEqual(payload, expected)
        # Transport retains values, not the original Pydantic object identity.
        self.assertIs(type(payload["result_contract"]), dict)
        self.assertEqual(
            ResultContract.model_validate(payload["result_contract"]),
            execution.result_contract,
        )
        self.assertEqual(
            DatabaseQueryResult.model_validate(payload).result_contract,
            execution.result_contract,
        )
        self.assertEqual(payload["result_contract"]["version"], "1")
        self.assertEqual(payload["result_contract"]["result_id"], execution.result_contract.result_id)
        self.assertEqual(payload["result_id"], execution.result_contract.result_id)
        return payload

    def test_database_query_result_accepts_legacy_fields_without_contract(self):
        legacy = {
            "database": "askdata_mock", "sql": "SELECT 1 AS value", "success": True,
            "columns": ["value"], "rows": [{"value": 1}], "row_count": 1, "error": None,
        }
        result = DatabaseQueryResult(**legacy)
        self.assertIsNone(result.result_contract)
        self.assertIsNone(result.result_id)
        self.assertEqual(result.model_dump(exclude={"result_contract", "result_id"}), legacy)
        self.assertIn("result_contract", result.model_dump())
        self.assertIsNone(result.model_dump()["result_contract"])

    def test_handler_explicitly_passes_the_execution_contract(self):
        sql = "SELECT 1 AS value"
        execution = self.engine.execute("askdata_mock", sql, self.scope)
        handler = build_database_query_tool("askdata_mock", self.engine, self.scope)
        with patch.object(self.engine, "execute", return_value=execution) as execute:
            result = handler(sql)
        execute.assert_called_once_with("askdata_mock", sql, self.scope)
        self.assertEqual(handler.__name__, "query_askdata_mock")
        self.assertIsInstance(result, DatabaseQueryResult)
        self.assertIs(result.result_contract, execution.result_contract)
        self.assertEqual(result.result_id, execution.result_id)
        self.assertEqual(result.sql, execution.sql)
        self.assertEqual(result.columns, execution.columns)
        self.assertEqual(result.rows, execution.rows)
        self.assertEqual(result.row_count, len(execution.rows))

    def test_tool_name_and_input_schema_are_unchanged(self):
        by_name = {tool["name"]: tool for tool in self.client.list_tools()}
        tool = by_name["query_askdata_mock"]
        self.assertEqual(tool["input_schema"]["required"], ["sql"])
        self.assertEqual(set(tool["input_schema"]["properties"]), {"sql"})
        sql_schema = tool["input_schema"]["properties"]["sql"]
        self.assertEqual(sql_schema["type"], "string")
        self.assertEqual(sql_schema["minLength"], 8)
        self.assertEqual(sql_schema["maxLength"], 12000)
        self.assertTrue(tool["annotations"]["readOnlyHint"])
        output_schema = tool["output_schema"]
        self.assertEqual(
            set(output_schema["properties"]),
            {"database", "sql", "success", "columns", "rows", "row_count", "error", "result_contract", "result_id"},
        )
        self.assertNotIn("result_contract", output_schema.get("required", []))
        self.assertIn({"type": "null"}, output_schema["properties"]["result_contract"]["anyOf"])
        self.assertNotIn("result_id", output_schema.get("required", []))
        self.assertIn({"type": "null"}, output_schema["properties"]["result_id"]["anyOf"])

    def test_scalar_dtype_ordinal_and_null_survive_round_trip(self):
        payload = self.round_trip(
            "SELECT CAST('123456789012345678.12' AS DECIMAL(20,2)) AS amount, "
            "CAST(NULL AS VARCHAR) AS missing, DATE '2026-09-06' AS day"
        )
        execution = payload["result_contract"]["execution"]
        self.assertTrue(payload["success"])
        self.assertEqual([column["dtype"] for column in execution["columns"]], ["DECIMAL(20,2)", "VARCHAR", "DATE"])
        self.assertEqual([column["ordinal"] for column in execution["columns"]], [0, 1, 2])
        self.assertTrue(all(type(column["ordinal"]) is int for column in execution["columns"]))
        self.assertEqual(execution["rows"], [["123456789012345678.12", None, "2026-09-06"]])
        self.assertIsNone(payload["rows"][0]["missing"])
        self.assertIsNone(execution["error"])
        self.assertIsNone(execution["columns"][1]["value_encoding"])
        self.assertIsNone(execution["provenance"]["snapshot_ref"])
        self.assertEqual(execution["returned_rows"], 1)
        self.assertEqual(execution["total_rows"], 1)
        self.assertIs(execution["truncated"], False)

    def test_duplicate_column_names_keep_distinct_identity_and_position(self):
        payload = self.round_trip("SELECT 1 AS repeated, 2 AS repeated")
        execution = payload["result_contract"]["execution"]
        self.assertEqual(payload["rows"], [{"repeated": 2}])  # Legacy behavior is unchanged.
        self.assertEqual(execution["rows"], [[1, 2]])
        self.assertEqual([column["name"] for column in execution["columns"]], ["repeated", "repeated"])
        self.assertEqual([column["ordinal"] for column in execution["columns"]], [0, 1])
        self.assertNotEqual(execution["columns"][0]["id"], execution["columns"][1]["id"])

    def test_truncated_result_keeps_true_and_unknown_total(self):
        payload = self.round_trip("SELECT order_id FROM orders_current ORDER BY order_id")
        execution = payload["result_contract"]["execution"]
        self.assertTrue(payload["success"])
        self.assertEqual(payload["row_count"], 200)
        self.assertEqual(execution["returned_rows"], 200)
        self.assertEqual(execution["rows"], [[i] for i in range(200)])
        self.assertEqual(execution["columns"][0]["dtype"], "BIGINT")
        self.assertEqual(execution["columns"][0]["ordinal"], 0)
        self.assertIs(execution["truncated"], True)
        self.assertIsNone(execution["total_rows"])
        self.assertEqual(execution["completeness"], "partial_query_output")

    def test_sql_failures_keep_unknown_metadata_as_null(self):
        for sql, submitted in (
            ("SELECT missing_column FROM orders_current", True),
            ("DELETE FROM orders_current", False),
        ):
            with self.subTest(sql=sql):
                payload = self.round_trip(sql)
                execution = payload["result_contract"]["execution"]
                self.assertFalse(payload["success"])
                self.assertFalse(execution["success"])
                self.assertEqual(payload["row_count"], 0)  # Legacy count, not an observed SQL total.
                self.assertEqual(execution["error"], payload["error"])
                for field in ("columns", "rows", "returned_rows", "total_rows", "truncated", "completeness"):
                    self.assertIsNone(execution[field], field)  # Indexing also verifies key presence.
                self.assertIs(execution["provenance"]["sql_submitted"], submitted)

    def test_empty_result_keeps_known_zero_distinct_from_null(self):
        payload = self.round_trip("SELECT order_id FROM orders_current WHERE order_id < 0")
        execution = payload["result_contract"]["execution"]
        self.assertTrue(payload["success"])
        self.assertEqual(execution["rows"], [])
        self.assertIs(type(execution["returned_rows"]), int)
        self.assertIs(type(execution["total_rows"]), int)
        self.assertEqual(execution["returned_rows"], 0)
        self.assertEqual(execution["total_rows"], 0)
        self.assertIs(execution["truncated"], False)
        self.assertEqual(execution["columns"][0]["dtype"], "BIGINT")
        self.assertIsNone(execution["columns"][0]["value_encoding"])
        self.assertIsNone(execution["columns"][0]["representation_status"])


if __name__ == "__main__":
    unittest.main()
