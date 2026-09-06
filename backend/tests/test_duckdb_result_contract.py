import csv
import tempfile
import unittest
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.querying.duckdb_engine import DuckDbEngine
from app.querying.models import SqlExecution
from app.querying.result_contract import ResultContract


class DuckDbResultContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        folder = root / "askdata_mock"
        folder.mkdir()
        with (folder / "orders_current.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["order_id", "region"])
            writer.writerows((index, "华北") for index in range(500))
        self.engine = DuckDbEngine(root)

    def execute_recorded(self, sql: str, database: str = "askdata_mock"):
        """Use real CSV/DuckDB execution while recording query and fetch calls."""
        statements = []
        fetches = []
        original_connect = self.engine.connect

        @contextmanager
        def recording_connect(name):
            with original_connect(name) as connection:
                def execute(statement):
                    statements.append(statement)
                    cursor = connection.execute(statement)

                    def fetchmany(size):
                        rows = cursor.fetchmany(size)
                        fetches.append((size, len(rows)))
                        return rows

                    # No fetchall/second-query helpers: the engine must use its
                    # one existing bounded fetch and the returned description.
                    return SimpleNamespace(description=cursor.description, fetchmany=fetchmany)

                yield SimpleNamespace(execute=execute)

        with patch.object(self.engine, "connect", recording_connect):
            result = self.engine.execute(database, sql)
        self.assertIsInstance(result, SqlExecution)
        self.assertIsInstance(result.result_contract, ResultContract)
        self.assertEqual(
            ResultContract.model_validate_json(result.result_contract.model_dump_json()),
            result.result_contract,
        )
        return result, statements, fetches

    def assert_unknown_result(self, result):
        execution = result.result_contract.execution
        self.assertFalse(result.success)
        self.assertFalse(execution.success)
        self.assertEqual(execution.error, result.error)
        self.assertTrue(execution.error)
        self.assertEqual(result.columns, [])
        self.assertEqual(result.rows, [])
        for name in (
            "columns", "rows", "returned_rows", "total_rows", "truncated", "completeness",
        ):
            self.assertIsNone(getattr(execution, name), name)

    def test_normal_select_preserves_legacy_fields_and_captures_dtype(self):
        sql = (
            "SELECT CAST(order_id AS INTEGER) AS identifier, region "
            "FROM orders_current WHERE order_id < 3 ORDER BY order_id"
        )
        result, statements, fetches = self.execute_recorded(f"```sql\n{sql};\n```")
        execution = result.result_contract.execution

        self.assertTrue(result.success)
        self.assertEqual(result.sql, sql)
        self.assertEqual(result.columns, ["identifier", "region"])
        self.assertEqual(result.rows, [{"identifier": i, "region": "华北"} for i in range(3)])
        self.assertEqual(execution.database, "askdata_mock")
        self.assertEqual(execution.sql, result.sql)
        self.assertTrue(execution.success)
        self.assertIsNone(execution.error)
        self.assertEqual([column.ordinal for column in execution.columns], [0, 1])
        self.assertEqual([column.name for column in execution.columns], result.columns)
        self.assertEqual([column.dtype for column in execution.columns], ["INTEGER", "VARCHAR"])
        self.assertEqual(len({column.id for column in execution.columns}), 2)
        self.assertEqual([column.value_encoding for column in execution.columns], ["native_json"] * 2)
        self.assertEqual([column.representation_status for column in execution.columns], ["preserved"] * 2)
        self.assertEqual(execution.rows, [[i, "华北"] for i in range(3)])
        self.assertEqual(execution.returned_rows, 3)
        self.assertEqual(execution.total_rows, 3)
        self.assertIs(execution.truncated, False)
        self.assertEqual(execution.completeness, "complete_query_output")
        self.assertEqual(execution.provenance.engine, "duckdb")
        self.assertEqual(execution.provenance.source_kind, "csv_views")
        self.assertIs(execution.provenance.sql_submitted, True)
        self.assertEqual(execution.provenance.submitted_sql, sql)
        self.assertIsNotNone(execution.provenance.captured_at)
        self.assertIsNone(execution.provenance.snapshot_ref)
        self.assertIsNone(execution.provenance.access_scope_ref)
        self.assertEqual(statements, [sql])
        self.assertEqual(fetches, [(201, 3)])

    def test_zero_and_200_rows_are_exhausted_not_unknown(self):
        for count in (0, 200):
            with self.subTest(count=count):
                sql = f"SELECT order_id FROM orders_current WHERE order_id < {count} ORDER BY order_id"
                result, statements, fetches = self.execute_recorded(sql)
                execution = result.result_contract.execution
                self.assertTrue(result.success)
                self.assertEqual(len(result.rows), count)
                self.assertEqual(execution.rows, [[i] for i in range(count)])
                self.assertEqual(execution.returned_rows, count)
                self.assertEqual(execution.total_rows, count)
                self.assertIs(execution.truncated, False)
                self.assertEqual(execution.completeness, "complete_query_output")
                self.assertEqual(execution.columns[0].dtype, "BIGINT")
                self.assertEqual(statements, [sql])
                self.assertEqual(fetches, [(201, count)])

    def test_201_and_larger_outputs_are_truncated_with_unknown_total(self):
        for count in (201, 500):
            with self.subTest(count=count):
                sql = f"SELECT order_id FROM orders_current WHERE order_id < {count} ORDER BY order_id"
                result, statements, fetches = self.execute_recorded(sql)
                execution = result.result_contract.execution
                self.assertTrue(result.success)
                self.assertEqual(len(result.rows), 200)
                self.assertEqual(execution.rows, [[i] for i in range(200)])
                self.assertEqual(execution.returned_rows, 200)
                self.assertIsNone(execution.total_rows)
                self.assertIs(execution.truncated, True)
                self.assertEqual(execution.completeness, "partial_query_output")
                self.assertEqual(statements, [sql])
                self.assertEqual(fetches, [(201, 201)])

    def test_sql_execution_failure_has_no_fabricated_cursor_metadata(self):
        sql = "SELECT missing_column FROM orders_current"
        result, statements, fetches = self.execute_recorded(sql)
        self.assert_unknown_result(result)
        execution = result.result_contract.execution
        self.assertEqual(execution.database, "askdata_mock")
        self.assertEqual(execution.sql, sql)
        self.assertIs(execution.provenance.sql_submitted, True)
        self.assertEqual(execution.provenance.submitted_sql, sql)
        self.assertEqual(statements, [sql])
        self.assertEqual(fetches, [])

    def test_validation_failure_was_not_submitted(self):
        sql = "DELETE FROM orders_current"
        result, statements, fetches = self.execute_recorded(sql)
        self.assert_unknown_result(result)
        execution = result.result_contract.execution
        self.assertEqual(execution.sql, sql)
        self.assertIs(execution.provenance.sql_submitted, False)
        self.assertIsNone(execution.provenance.submitted_sql)
        self.assertEqual(statements, [])
        self.assertEqual(fetches, [])

    def test_connection_failure_was_not_submitted(self):
        result, statements, fetches = self.execute_recorded("SELECT 1 AS value", database="missing")
        self.assert_unknown_result(result)
        execution = result.result_contract.execution
        self.assertEqual(execution.database, "missing")
        self.assertIs(execution.provenance.sql_submitted, False)
        self.assertIsNone(execution.provenance.submitted_sql)
        self.assertEqual(statements, [])
        self.assertEqual(fetches, [])

    def test_duplicate_names_do_not_overwrite_contract_values(self):
        result, _, _ = self.execute_recorded("SELECT 1 AS repeated, 2 AS repeated")
        execution = result.result_contract.execution
        self.assertEqual(result.columns, ["repeated", "repeated"])
        self.assertEqual(result.rows, [{"repeated": 2}])  # Deliberately unchanged legacy behavior.
        self.assertEqual(execution.rows, [[1, 2]])
        self.assertEqual([column.ordinal for column in execution.columns], [0, 1])
        self.assertNotEqual(execution.columns[0].id, execution.columns[1].id)

    def test_decimal_and_dates_use_explicit_lossless_contract_encodings(self):
        amount = "123456789012345678.12"
        result, _, _ = self.execute_recorded(
            f"SELECT CAST('{amount}' AS DECIMAL(20,2)) AS amount, "
            "DATE '2026-09-06' AS day, TIMESTAMP '2026-09-06 12:34:56.123456' AS moment"
        )
        execution = result.result_contract.execution
        self.assertEqual(result.rows[0]["amount"], float(Decimal(amount)))
        self.assertIs(type(result.rows[0]["amount"]), float)
        self.assertEqual(result.rows[0]["day"], "2026-09-06")
        self.assertEqual(execution.rows, [[amount, "2026-09-06", "2026-09-06T12:34:56.123456"]])
        self.assertEqual([column.dtype for column in execution.columns], ["DECIMAL(20,2)", "DATE", "TIMESTAMP"])
        self.assertEqual([column.value_encoding for column in execution.columns], ["decimal_text", "iso_date", "iso_datetime"])

    def test_unsupported_values_do_not_become_fake_nulls_or_sql_failures(self):
        for expression in ("[1, 2]", "CAST('NaN' AS DOUBLE)"):
            with self.subTest(expression=expression):
                result, _, _ = self.execute_recorded(f"SELECT {expression} AS value")
                execution = result.result_contract.execution
                self.assertTrue(result.success)
                self.assertTrue(execution.success)
                self.assertIsNotNone(result.rows[0]["value"])
                self.assertIsNone(execution.rows)
                self.assertEqual(execution.columns[0].representation_status, "unsupported")
                self.assertIsNone(execution.columns[0].value_encoding)
                self.assertEqual(execution.returned_rows, 1)
                self.assertEqual(execution.total_rows, 1)
                self.assertIs(execution.truncated, False)
                self.assertIsNone(execution.completeness)

    def test_total_rows_describes_sql_output_not_source_table_size(self):
        result, statements, fetches = self.execute_recorded(
            "SELECT order_id FROM orders_current ORDER BY order_id LIMIT 5"
        )
        execution = result.result_contract.execution
        self.assertEqual(execution.total_rows, 5)
        self.assertIs(execution.truncated, False)
        self.assertEqual(len(statements), 1)
        self.assertEqual(fetches, [(201, 5)])

    def test_result_identity_and_metadata_are_not_shared_between_calls(self):
        first, _, _ = self.execute_recorded("SELECT 1 AS value")
        second, _, _ = self.execute_recorded("SELECT 1 AS value")
        self.assertNotEqual(first.result_contract.result_id, second.result_contract.result_id)
        self.assertIsNot(first.result_contract.execution, second.result_contract.execution)
        self.assertIsNot(first.result_contract.execution.columns, second.result_contract.execution.columns)


if __name__ == "__main__":
    unittest.main()
