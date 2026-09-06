import unittest
from contextlib import contextmanager
from dataclasses import asdict, fields
from inspect import Parameter, signature
from types import SimpleNamespace
from typing import get_type_hints
from unittest.mock import Mock, patch

import duckdb

from app.mcp_runtime.tools.database_tools import build_database_query_tool
from app.querying.duckdb_engine import DuckDbEngine
from app.querying.models import SqlExecution
from app.querying.result_contract import ColumnMetadata, ExecutionData, ResultContract
from app.security import AccessController
from app.workflows.query_graph import QueryWorkflow
from app.workflows.result_builder import ResultBuilder


LEGACY_FIELDS = ("sql", "success", "columns", "rows", "error")
METADATA_FIELDS = ("result_contract", "result_id")
SQL = "SELECT 1 AS x"


def make_contract(result_id="test-result"):
    return ResultContract(
        result_id=result_id,
        execution=ExecutionData(
            sql=SQL, success=True,
            columns=[ColumnMetadata(id="column_0", ordinal=0, name="x", dtype="INTEGER")],
            rows=[[1]], returned_rows=1,
        ),
    )


class SqlExecutionInterfaceTest(unittest.TestCase):
    def test_legacy_two_through_five_positional_arguments(self):
        arguments = (SQL, True, ["x"], [{"x": 1}], "legacy error")
        for count in range(2, 6):
            with self.subTest(argument_count=count):
                execution = SqlExecution(*arguments[:count])
                expected = (SQL, True, [], [], None)
                expected = arguments[:count] + expected[count:]
                self.assertEqual(tuple(getattr(execution, name) for name in LEGACY_FIELDS), expected)
                self.assertIsNone(execution.result_contract)
                self.assertIsNone(execution.result_id)

    def test_new_metadata_can_be_supplied_by_keyword(self):
        contract = make_contract()
        execution = SqlExecution(
            SQL, True, ["x"], [{"x": 1}], None,
            result_contract=contract, result_id=contract.result_id,
        )
        self.assertIs(execution.result_contract, contract)
        self.assertEqual(execution.result_id, "test-result")

    def test_optional_metadata_is_not_synthesized(self):
        contract_only = SqlExecution(SQL, True, result_contract=make_contract())
        id_only = SqlExecution(SQL, True, result_id="envelope-id")
        self.assertIsNone(contract_only.result_id)
        self.assertIsNone(id_only.result_contract)

    def test_metadata_is_rejected_as_positional_arguments(self):
        for metadata in ((make_contract(),), (make_contract(), "test-result")):
            with self.subTest(metadata_count=len(metadata)):
                with self.assertRaises(TypeError):
                    SqlExecution(SQL, True, ["x"], [{"x": 1}], None, *metadata)

    def test_signature_and_positional_pattern_matching_are_compatible(self):
        parameters = signature(SqlExecution).parameters
        self.assertEqual(tuple(parameters), LEGACY_FIELDS + METADATA_FIELDS)
        for name in LEGACY_FIELDS:
            self.assertEqual(parameters[name].kind, Parameter.POSITIONAL_OR_KEYWORD)
        for name in METADATA_FIELDS:
            self.assertEqual(parameters[name].kind, Parameter.KEYWORD_ONLY)
            self.assertIsNone(parameters[name].default)
        self.assertEqual(SqlExecution.__match_args__, LEGACY_FIELDS)

    def test_fields_expose_metadata_with_requested_flags_and_types(self):
        descriptors = {item.name: item for item in fields(SqlExecution)}
        self.assertEqual(tuple(descriptors), LEGACY_FIELDS + METADATA_FIELDS)
        for name in LEGACY_FIELDS:
            self.assertFalse(descriptors[name].kw_only)
            self.assertTrue(descriptors[name].compare)
            self.assertTrue(descriptors[name].repr)
        for name in METADATA_FIELDS:
            self.assertTrue(descriptors[name].kw_only)
            self.assertFalse(descriptors[name].compare)
            self.assertFalse(descriptors[name].repr)
            self.assertIsNone(descriptors[name].default)
        hints = get_type_hints(SqlExecution)
        self.assertEqual(hints["result_contract"], ResultContract | None)
        self.assertEqual(hints["result_id"], str | None)

    def test_equality_ignores_metadata_even_when_contracts_differ(self):
        legacy = SqlExecution(SQL, True, ["x"], [{"x": 1}])
        first = SqlExecution(
            SQL, True, ["x"], [{"x": 1}],
            result_contract=make_contract("first"), result_id="first",
        )
        second_contract = make_contract("second")
        second_contract.execution.columns[0].dtype = "BIGINT"
        second = SqlExecution(
            SQL, True, ["x"], [{"x": 1}],
            result_contract=second_contract, result_id="second",
        )
        self.assertNotEqual(first.result_contract, second.result_contract)
        self.assertEqual(legacy, first)
        self.assertEqual(first, legacy)
        self.assertEqual(first, second)

    def test_equality_still_compares_every_legacy_field(self):
        original = dict(sql=SQL, success=True, columns=["x"], rows=[{"x": 1}], error=None)
        baseline = SqlExecution(**original)
        replacements = dict(sql="SELECT 2 AS x", success=False, columns=["y"], rows=[{"x": 2}], error="failure")
        for name, value in replacements.items():
            with self.subTest(field=name):
                changed = SqlExecution(**{**original, name: value})
                self.assertNotEqual(baseline, changed)
        with self.assertRaises(TypeError):
            hash(baseline)  # The mutable dataclass remains unhashable.

    def test_repr_keeps_only_the_legacy_fields(self):
        legacy = SqlExecution(SQL, True, ["x"], [{"x": 1}])
        enriched = SqlExecution(
            SQL, True, ["x"], [{"x": 1}],
            result_contract=make_contract(), result_id="hidden-id",
        )
        self.assertEqual(repr(legacy), repr(enriched))
        self.assertEqual(
            repr(enriched),
            "SqlExecution(sql='SELECT 1 AS x', success=True, columns=['x'], rows=[{'x': 1}], error=None)",
        )

    def test_asdict_includes_unknown_metadata(self):
        execution = SqlExecution(SQL, True)
        self.assertEqual(asdict(execution), {
            "sql": SQL, "success": True, "columns": [], "rows": [], "error": None,
            "result_contract": None, "result_id": None,
        })

    def test_asdict_deepcopies_pydantic_contract_but_does_not_json_encode_it(self):
        contract = make_contract()
        execution = SqlExecution(
            SQL, True, ["x"], [{"x": 1}], result_contract=contract, result_id="test-result",
        )
        payload = asdict(execution)
        self.assertEqual(tuple(payload), LEGACY_FIELDS + METADATA_FIELDS)
        self.assertIsInstance(payload["result_contract"], ResultContract)
        self.assertIsNot(payload["result_contract"], contract)
        self.assertEqual(payload["result_contract"].model_dump(), contract.model_dump())
        self.assertEqual(payload["result_id"], "test-result")
        payload["result_contract"].execution.rows[0][0] = 99
        payload["rows"][0]["x"] = 99
        payload["columns"].append("y")
        self.assertEqual(contract.execution.rows, [[1]])
        self.assertEqual(execution.rows, [{"x": 1}])
        self.assertEqual(execution.columns, ["x"])

    def test_legacy_mutable_defaults_remain_independent(self):
        first = SqlExecution(SQL, True)
        second = SqlExecution(SQL, True)
        first.columns.append("x")
        first.rows.append({"x": 1})
        self.assertEqual(second.columns, [])
        self.assertEqual(second.rows, [])


class SqlExecutionProducerCompatibilityTest(unittest.TestCase):
    def test_duckdb_success_and_failure_return_the_base_class(self):
        @contextmanager
        def memory_connection(database):
            connection = duckdb.connect(":memory:")
            try:
                yield connection
            finally:
                connection.close()

        engine = DuckDbEngine()
        for sql, success in ((SQL, True), ("SELECT missing_column", False), ("DELETE FROM orders_current", False)):
            with self.subTest(sql=sql), patch.object(engine, "connect", memory_connection):
                execution = engine.execute("askdata_mock", sql)
                self.assertIs(type(execution), SqlExecution)
                self.assertIs(execution.success, success)
                self.assertIsInstance(execution.result_contract, ResultContract)
                self.assertTrue(execution.result_id)
                self.assertEqual(execution.result_id, execution.result_contract.result_id)

    def test_workflow_restores_base_class_with_or_without_contract(self):
        for contract in (None, make_contract().model_dump(mode="json")):
            with self.subTest(has_contract=contract is not None):
                payload = {"sql": SQL, "success": True, "columns": ["x"], "rows": [{"x": 1}]}
                if contract is not None:
                    payload["result_contract"] = contract
                execution = QueryWorkflow._restore_execution(payload)
                self.assertIs(type(execution), SqlExecution)
                self.assertIsNone(execution.result_id)
                if contract is None:
                    self.assertIsNone(execution.result_contract)
                else:
                    self.assertEqual(execution.result_contract.model_dump(mode="json"), contract)

    def test_workflow_contract_failure_also_uses_base_class(self):
        workflow = QueryWorkflow.__new__(QueryWorkflow)
        workflow.response_generator = SimpleNamespace(finalize=Mock())
        state = {"task_id": "interface-test", "mcp_execution": {"sql": SQL, "success": True, "result_contract": {}}}
        with patch.object(ResultBuilder, "failed", wraps=ResultBuilder.failed) as failed:
            update = workflow._execute_single_database(state)
        execution = failed.call_args.args[1]
        self.assertIs(type(execution), SqlExecution)
        self.assertFalse(execution.success)
        self.assertIsNone(execution.result_contract)
        self.assertIsNone(execution.result_id)
        self.assertEqual(update["result"]["status"], "failed")
        workflow.response_generator.finalize.assert_not_called()

    def test_existing_database_handler_accepts_legacy_base_execution(self):
        engine = Mock(spec=DuckDbEngine)
        engine.execute.return_value = SqlExecution(SQL, True, ["x"], [{"x": 1}])
        scope = AccessController().resolve(None)
        handler = build_database_query_tool("askdata_mock", engine, scope)
        result = handler(SQL)
        engine.execute.assert_called_once_with("askdata_mock", SQL, scope)
        self.assertIsNone(result.result_contract)
        self.assertEqual(result.columns, ["x"])
        self.assertEqual(result.rows, [{"x": 1}])
        self.assertEqual(result.row_count, 1)


if __name__ == "__main__":
    unittest.main()
