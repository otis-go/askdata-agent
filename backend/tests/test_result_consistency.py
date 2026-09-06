"""Pure consistency checks and their two pre-coercion integration boundaries."""

from copy import deepcopy
from decimal import Decimal
import unittest
from unittest.mock import Mock, patch

from app.errors import PipelineStageError
from app.mcp_runtime import LocalMcpClient, create_local_mcp_server
from app.mcp_runtime.schemas import DatabaseQueryResult
from app.mcp_runtime.tools.database_tools import build_database_query_tool
from app.querying.models import SqlExecution
from app.querying.result_consistency import validate_execution_consistency
from app.querying.result_contract import ColumnMetadata, ExecutionData, ResultContract
from app.workflows.query_graph import QueryWorkflow


def execution_pair():
    """Known execution fixture; its database is supplied separately by the tests."""
    contract = ResultContract(
        result_id="same-execution",
        execution=ExecutionData(
            database="askdata_mock", sql="SELECT 7 AS value", success=False,
            error="observed execution error",
            columns=[ColumnMetadata(
                id="column_0", ordinal=0, name="value", dtype="INTEGER",
                value_encoding="native_json", representation_status="preserved",
            )],
            rows=[[7]], returned_rows=1, total_rows=1, truncated=False,
            completeness="complete_query_output",
        ),
    )
    legacy = SqlExecution(
        contract.execution.sql, contract.execution.success, ["value"],
        [{"value": 7}], contract.execution.error,
        result_contract=contract, result_id=contract.result_id,
    )
    return legacy, contract


def payload_from(legacy, contract):
    return {
        "database": "askdata_mock", "sql": legacy.sql,
        "success": legacy.success, "error": legacy.error,
        "columns": deepcopy(legacy.columns), "rows": deepcopy(legacy.rows),
        "row_count": len(legacy.rows), "result_id": legacy.result_id,
        "result_contract": contract.model_dump(mode="json") if contract else None,
    }


def decimal_pair(text):
    legacy, contract = execution_pair()
    contract.execution.columns[0].dtype = "DECIMAL(38, 2)"
    contract.execution.columns[0].value_encoding = "decimal_text"
    contract.execution.rows = [[text]]
    legacy.rows = [{"value": float(Decimal(text))}]
    return legacy, contract


def duplicate_pair():
    legacy, contract = execution_pair()
    contract.execution.columns.append(ColumnMetadata(
        id="column_1", ordinal=1, name="value", dtype="INTEGER",
        value_encoding="native_json", representation_status="preserved",
    ))
    contract.execution.rows = [[1, 2]]
    legacy.columns = ["value", "value"]
    legacy.rows = [{"value": 2}]
    return legacy, contract


class ResultConsistencyTest(unittest.TestCase):
    def assert_status(self, expected, legacy, contract, *, supply_fixture_database=True):
        before_legacy = deepcopy(legacy)
        # Some cases deliberately bypass Pydantic validation by assignment.
        before_contract = contract.model_dump(warnings=False) if contract is not None else None
        # SqlExecution deliberately has no database field. The fixture's trusted
        # context is explicit here, never inferred from the canonical contract.
        evidence = (
            {"database": "askdata_mock", **vars(legacy)}
            if isinstance(legacy, SqlExecution) and supply_fixture_database
            else legacy
        )
        report = validate_execution_consistency(evidence, contract)
        self.assertEqual(report.status, expected)
        self.assertIsInstance(report.conflicts, tuple)
        self.assertIsInstance(report.unknowns, tuple)
        if expected == "consistent":
            self.assertFalse(report.conflicts)
            self.assertFalse(report.unknowns)
        elif expected == "inconsistent":
            self.assertTrue(report.conflicts)
        else:
            self.assertFalse(report.conflicts)
            self.assertTrue(report.unknowns)
        self.assertEqual(legacy, before_legacy)
        if isinstance(legacy, SqlExecution):
            self.assertEqual(legacy.result_id, before_legacy.result_id)
        if contract is not None:
            self.assertEqual(contract.model_dump(warnings=False), before_contract)
        return report

    def test_complete_known_pair_is_consistent(self):
        self.assert_status("consistent", *execution_pair())

    def test_plain_mapping_is_supported(self):
        legacy, contract = execution_pair()
        self.assert_status("consistent", payload_from(legacy, contract), contract)

    def test_known_database_names_match_exactly(self):
        legacy, contract = execution_pair()
        payload = payload_from(legacy, contract)
        self.assert_status("consistent", payload, contract)
        self.assertEqual(payload["database"], "askdata_mock")

    def test_database_mismatch_is_rejected(self):
        legacy, contract = execution_pair()
        payload = payload_from(legacy, contract)
        contract.execution.database = "another_database"
        report = self.assert_status("inconsistent", payload, contract)
        self.assertIn("database", [issue.field for issue in report.conflicts])

    def test_database_comparison_does_not_normalize_case_or_whitespace(self):
        for value in ("ASKDATA_MOCK", "askdata_mock ", " askdata_mock"):
            with self.subTest(value=value):
                legacy, contract = execution_pair()
                payload = payload_from(legacy, contract)
                payload["database"] = value
                self.assert_status("inconsistent", payload, contract)

    def test_missing_or_null_database_is_insufficient_and_not_filled(self):
        for side in ("legacy", "contract", "both"):
            for omit in (True, False):
                with self.subTest(side=side, omit=omit):
                    legacy, contract = execution_pair()
                    payload = payload_from(legacy, contract)
                    if side in ("legacy", "both"):
                        if omit:
                            del payload["database"]
                        else:
                            payload["database"] = None
                    if side in ("contract", "both"):
                        if omit:
                            del contract.execution.database
                        else:
                            contract.execution.database = None
                    report = self.assert_status("insufficient_evidence", payload, contract)
                    self.assertTrue(any(issue.field.endswith(".database") for issue in report.unknowns))

    def test_sql_execution_without_database_remains_unknown(self):
        legacy, contract = execution_pair()
        report = self.assert_status(
            "insufficient_evidence", legacy, contract,
            supply_fixture_database=False,
        )
        self.assertIn("legacy.database", [issue.field for issue in report.unknowns])
        self.assertNotIn("database", vars(legacy))

    def test_database_must_be_a_string_without_coercion(self):
        for side in ("legacy", "contract"):
            for value in (False, 0, 1, 1.0, [], {}):
                with self.subTest(side=side, value=value):
                    legacy, contract = execution_pair()
                    payload = payload_from(legacy, contract)
                    if side == "legacy":
                        payload["database"] = value
                    else:
                        contract.execution.database = value
                    self.assert_status("inconsistent", payload, contract)

    def test_sql_must_match_exactly_not_semantically(self):
        for sql in ("SELECT 8 AS value", "select 7 as value", "SELECT 7 AS value "):
            with self.subTest(sql=sql):
                legacy, contract = execution_pair()
                legacy.sql = sql
                self.assert_status("inconsistent", legacy, contract)

    def test_unknown_sql_does_not_get_filled(self):
        legacy, contract = execution_pair()
        contract.execution.sql = None
        self.assert_status("insufficient_evidence", legacy, contract)
        self.assertIsNone(contract.execution.sql)

    def test_conflicting_success_is_rejected(self):
        legacy, contract = execution_pair()
        legacy.success = True
        self.assert_status("inconsistent", legacy, contract)

    def test_legacy_success_must_be_actual_bool_even_without_contract(self):
        for value in ("false", "true", 0, 1):
            for with_contract in (True, False):
                with self.subTest(value=value, with_contract=with_contract):
                    legacy, contract = execution_pair()
                    legacy.success = value
                    self.assert_status("inconsistent", legacy, contract if with_contract else None)

    def test_mutated_contract_success_must_be_actual_bool(self):
        for value in ("false", 0, 1):
            with self.subTest(value=value):
                legacy, contract = execution_pair()
                contract.execution.success = value
                self.assert_status("inconsistent", legacy, contract)

    def test_unknown_success_is_insufficient_not_false(self):
        legacy, contract = execution_pair()
        contract.execution.success = None
        self.assert_status("insufficient_evidence", legacy, contract)

    def test_known_error_conflict_is_rejected(self):
        legacy, contract = execution_pair()
        legacy.error = "different execution error"
        self.assert_status("inconsistent", legacy, contract)

    def test_error_none_is_unknown_not_known_absence(self):
        for missing_side in ("legacy", "contract", "both"):
            with self.subTest(missing_side=missing_side):
                legacy, contract = execution_pair()
                if missing_side in ("legacy", "both"):
                    legacy.error = None
                if missing_side in ("contract", "both"):
                    contract.execution.error = None
                self.assert_status("insufficient_evidence", legacy, contract)

    def test_result_id_conflict_is_rejected(self):
        legacy, contract = execution_pair()
        legacy.result_id = "different-execution"
        self.assert_status("inconsistent", legacy, contract)

    def test_result_ids_cannot_be_empty_or_whitespace(self):
        for side in ("legacy", "contract"):
            for value in ("", "   ", "\t\n"):
                with self.subTest(side=side, value=value):
                    legacy, contract = execution_pair()
                    setattr(legacy if side == "legacy" else contract, "result_id", value)
                    self.assert_status("inconsistent", legacy, contract)

    def test_missing_outer_result_id_is_not_synthesized(self):
        legacy, contract = execution_pair()
        legacy.result_id = None
        self.assert_status("insufficient_evidence", legacy, contract)
        self.assertIsNone(legacy.result_id)

    def test_result_id_is_not_required_to_be_uuid(self):
        legacy, contract = execution_pair()
        legacy.result_id = contract.result_id = "test-result"
        self.assert_status("consistent", legacy, contract)

    def test_column_name_mismatch_is_rejected(self):
        legacy, contract = execution_pair()
        legacy.columns = ["different_name"]
        legacy.rows = [{"different_name": 7}]
        self.assert_status("inconsistent", legacy, contract)

    def test_column_order_mismatch_is_rejected(self):
        legacy, contract = duplicate_pair()
        contract.execution.columns[1].name = "second"
        legacy.columns = ["second", "value"]
        legacy.rows = [{"value": 1, "second": 2}]
        self.assert_status("inconsistent", legacy, contract)

    def test_mutated_ordinal_and_duplicate_column_identity_are_rejected(self):
        for field, value in (("ordinal", 0), ("ordinal", 3), ("id", "column_0")):
            with self.subTest(field=field):
                legacy, contract = duplicate_pair()
                setattr(contract.execution.columns[1], field, value)
                self.assert_status("inconsistent", legacy, contract)

    def test_returned_rows_and_actual_rows_must_agree(self):
        for value in (0, 2, True):
            with self.subTest(value=value):
                legacy, contract = execution_pair()
                contract.execution.returned_rows = value
                self.assert_status("inconsistent", legacy, contract)

    def test_outer_row_count_must_be_exact_integer_and_match(self):
        for value in (2, True, "1", 1.0):
            with self.subTest(value=value):
                legacy, contract = execution_pair()
                payload = payload_from(legacy, contract)
                payload["row_count"] = value
                self.assert_status("inconsistent", payload, contract)

    def test_canonical_and_legacy_row_counts_must_agree(self):
        legacy, contract = execution_pair()
        legacy.rows = []
        self.assert_status("inconsistent", legacy, contract)

    def test_row_width_and_legacy_dictionary_keys_must_agree(self):
        for canonical_rows, legacy_rows in (([[7, 8]], [{"value": 7}]), ([[7]], [{}]), ([[7]], [{"value": 7, "extra": 8}])):
            with self.subTest(canonical_rows=canonical_rows, legacy_rows=legacy_rows):
                legacy, contract = execution_pair()
                contract.execution.rows = canonical_rows
                legacy.rows = legacy_rows
                self.assert_status("inconsistent", legacy, contract)

    def test_null_matches_null_without_becoming_string(self):
        legacy, contract = execution_pair()
        contract.execution.rows = [[None]]
        legacy.rows = [{"value": None}]
        self.assert_status("consistent", legacy, contract)
        legacy.rows = [{"value": "None"}]
        self.assert_status("inconsistent", legacy, contract)

    def test_native_values_are_type_sensitive(self):
        for canonical, old in ((1, True), (True, 1), (1, 1.0), (1.0, 1), (7, "7")):
            with self.subTest(canonical=canonical, old=old):
                legacy, contract = execution_pair()
                contract.execution.rows = [[canonical]]
                legacy.rows = [{"value": old}]
                self.assert_status("inconsistent", legacy, contract)

    def test_exact_decimal_projection_is_consistent(self):
        self.assert_status("consistent", *decimal_pair("12.50"))

    def test_non_exact_decimal_projection_is_insufficient(self):
        self.assert_status("insufficient_evidence", *decimal_pair("12.30"))

    def test_decimal_mismatch_is_rejected_without_epsilon(self):
        legacy, contract = decimal_pair("12.50")
        legacy.rows = [{"value": 12.500000000000002}]
        self.assert_status("inconsistent", legacy, contract)

    def test_decimal_float_collision_cannot_prove_source_identity(self):
        first = "123456789012345678.12"
        second = "123456789012345678.13"
        self.assertNotEqual(Decimal(first), Decimal(second))
        self.assertEqual(float(Decimal(first)), float(Decimal(second)))
        legacy, contract = decimal_pair(first)
        self.assert_status("insufficient_evidence", legacy, contract)
        contract.execution.rows = [[second]]
        self.assert_status("insufficient_evidence", legacy, contract)

    def test_duplicate_names_match_last_write_wins_but_are_insufficient(self):
        legacy, contract = duplicate_pair()
        self.assert_status("insufficient_evidence", legacy, contract)
        contract.execution.rows[0][0] = 999
        self.assert_status("insufficient_evidence", legacy, contract)

    def test_duplicate_name_visible_value_conflict_is_rejected(self):
        legacy, contract = duplicate_pair()
        legacy.rows = [{"value": 1}]
        self.assert_status("inconsistent", legacy, contract)

    def test_unknown_codec_does_not_guess_from_value_shape(self):
        legacy, contract = execution_pair()
        contract.execution.columns[0].value_encoding = None
        contract.execution.rows = [["7"]]
        self.assert_status("insufficient_evidence", legacy, contract)

    def test_missing_contract_is_insufficient_not_created(self):
        legacy, _ = execution_pair()
        legacy.result_contract = None
        self.assert_status("insufficient_evidence", legacy, None)
        self.assertIsNone(legacy.result_contract)

    def test_known_conflict_wins_over_missing_evidence(self):
        legacy, contract = execution_pair()
        legacy.result_id = None
        contract.execution.error = None
        legacy.sql = "SELECT 8 AS value"
        self.assert_status("inconsistent", legacy, contract)

    def test_damaged_execution_object_is_not_treated_as_unknown_metadata(self):
        for value in (None, 7, [], "broken"):
            with self.subTest(value=value):
                legacy, contract = execution_pair()
                contract.execution = value
                self.assert_status("inconsistent", legacy, contract)

    def test_required_column_name_cannot_be_null(self):
        legacy, contract = execution_pair()
        contract.execution.columns[0].name = None
        self.assert_status("inconsistent", legacy, contract)

    def test_invalid_codec_and_status_are_rejected_even_without_values(self):
        for attribute in ("value_encoding", "representation_status"):
            for value in ("broken", [], 1):
                for shape in ("empty", "null", "value"):
                    with self.subTest(attribute=attribute, value=value, shape=shape):
                        legacy, contract = execution_pair()
                        setattr(contract.execution.columns[0], attribute, value)
                        if shape == "empty":
                            contract.execution.rows = []
                            contract.execution.returned_rows = 0
                            legacy.rows = []
                        elif shape == "null":
                            contract.execution.rows = [[None]]
                            legacy.rows = [{"value": None}]
                        self.assert_status("inconsistent", legacy, contract)

    def test_temporal_codecs_match_representation_without_reinterpreting_types(self):
        for encoding, value in (
            ("iso_date", "2026-09-06"),
            ("iso_datetime", "2026-09-06T12:34:56.123456"),
            ("iso_datetime", "2026-09-06T12:34:56+00:00"),
        ):
            with self.subTest(encoding=encoding, value=value):
                legacy, contract = execution_pair()
                contract.execution.columns[0].value_encoding = encoding
                contract.execution.rows = [[value]]
                legacy.rows = [{"value": value}]
                self.assert_status("consistent", legacy, contract)
                legacy.rows = [{"value": value + "Z"}]
                self.assert_status("inconsistent", legacy, contract)

    def test_invalid_text_codec_payloads_are_not_stringified(self):
        for encoding, value in (
            ("decimal_text", "NaN"), ("decimal_text", "Infinity"),
            ("decimal_text", "not-a-number"), ("decimal_text", 12.5),
            ("integer_text", "1.5"), ("iso_date", "2026-02-30"),
            ("iso_datetime", "2026-09-06T12:34:56.123456789"),
        ):
            with self.subTest(encoding=encoding, value=value):
                legacy, contract = execution_pair()
                contract.execution.columns[0].value_encoding = encoding
                contract.execution.rows = [[value]]
                legacy.rows = [{"value": value}]
                self.assert_status("inconsistent", legacy, contract)

    def test_declared_integer_text_is_decoded_without_float(self):
        legacy, contract = execution_pair()
        contract.execution.columns[0].value_encoding = "integer_text"
        contract.execution.rows = [["9007199254740993"]]
        legacy.rows = [{"value": 9007199254740993}]
        self.assert_status("consistent", legacy, contract)
        legacy.rows = [{"value": float(9007199254740993)}]
        self.assert_status("inconsistent", legacy, contract)

    def test_overflow_projection_does_not_hide_known_finite_mismatches(self):
        legacy, contract = decimal_pair("1e400")
        self.assert_status("insufficient_evidence", legacy, contract)
        legacy.rows = [{"value": None}]
        self.assert_status("insufficient_evidence", legacy, contract)
        for value in (0.0, float("-inf"), "Infinity"):
            with self.subTest(value=value):
                legacy.rows = [{"value": value}]
                self.assert_status("inconsistent", legacy, contract)

    def test_diagnostics_do_not_contain_sql_id_names_or_row_values(self):
        legacy, contract = execution_pair()
        legacy.sql = "SECRET_SQL"
        legacy.result_id = "SECRET_ID"
        legacy.columns = ["SECRET_COLUMN"]
        legacy.rows = [{"SECRET_COLUMN": "SECRET_VALUE"}]
        report = self.assert_status("inconsistent", legacy, contract)
        for secret in ("SECRET_SQL", "SECRET_ID", "SECRET_COLUMN", "SECRET_VALUE"):
            self.assertNotIn(secret, repr(report))


class ConsistencyBoundaryIntegrationTest(unittest.TestCase):
    def test_handler_rejects_non_bool_before_pydantic_coercion(self):
        for value in ("false", 0, 1):
            for with_contract in (True, False):
                with self.subTest(value=value, with_contract=with_contract):
                    legacy, _ = execution_pair()
                    legacy.success = value
                    if not with_contract:
                        legacy.result_contract = None
                    handler = build_database_query_tool("askdata_mock", Mock(execute=Mock(return_value=legacy)), None)
                    with patch("app.mcp_runtime.tools.database_tools.DatabaseQueryResult") as model:
                        with self.assertRaises(ValueError):
                            handler(legacy.sql)
                        model.assert_not_called()

    def test_handler_rejects_known_conflicts_before_result_construction(self):
        for field, value in (("sql", "SELECT 8 AS value"), ("success", True), ("error", "different"), ("result_id", "another-result")):
            with self.subTest(field=field):
                legacy, _ = execution_pair()
                setattr(legacy, field, value)
                handler = build_database_query_tool("askdata_mock", Mock(execute=Mock(return_value=legacy)), None)
                with patch("app.mcp_runtime.tools.database_tools.DatabaseQueryResult") as model:
                    with self.assertRaises(ValueError):
                        handler(legacy.sql)
                    model.assert_not_called()

    def test_handler_rejects_database_conflict_with_bound_database(self):
        legacy, contract = execution_pair()
        contract.execution.database = "another_database"
        handler = build_database_query_tool(
            "askdata_mock", Mock(execute=Mock(return_value=legacy)), None,
        )
        with patch("app.mcp_runtime.tools.database_tools.DatabaseQueryResult") as model:
            with self.assertRaises(ValueError):
                handler(legacy.sql)
            model.assert_not_called()

    def test_handler_allows_insufficient_decimal_and_duplicate_evidence(self):
        for factory in (duplicate_pair, lambda: decimal_pair("12.30")):
            legacy, contract = factory()
            handler = build_database_query_tool("askdata_mock", Mock(execute=Mock(return_value=legacy)), None)
            result = handler(legacy.sql)
            self.assertEqual(result.result_contract.model_dump(), contract.model_dump())
            self.assertEqual(result.rows, legacy.rows)
            self.assertEqual(result.columns, legacy.columns)

    def test_workflow_rejects_success_before_bool_conversion(self):
        for value in ("false", 0, 1):
            for with_contract in (True, False):
                with self.subTest(value=value, with_contract=with_contract):
                    legacy, contract = execution_pair()
                    payload = payload_from(legacy, contract if with_contract else None)
                    payload["success"] = value
                    with self.assertRaises(PipelineStageError) as raised:
                        QueryWorkflow._restore_execution(payload)
                    self.assertEqual(raised.exception.stage, "result_contract_validation")

    def test_workflow_rejects_known_cross_contract_conflicts(self):
        for field, value in (("sql", "SELECT 8 AS value"), ("success", True), ("error", "different"), ("result_id", "another-result")):
            with self.subTest(field=field):
                legacy, contract = execution_pair()
                payload = payload_from(legacy, contract)
                payload[field] = value
                with self.assertRaises(PipelineStageError) as raised:
                    QueryWorkflow._restore_execution(payload)
                self.assertEqual(raised.exception.stage, "result_contract_validation")

    def test_workflow_rejects_database_conflict(self):
        legacy, contract = execution_pair()
        contract.execution.database = "another_database"
        payload = payload_from(legacy, contract)
        self.assertEqual(payload["database"], "askdata_mock")
        with self.assertRaises(PipelineStageError) as raised:
            QueryWorkflow._restore_execution(payload)
        self.assertEqual(raised.exception.stage, "result_contract_validation")
        self.assertIn("database", str(raised.exception))

    def test_workflow_allows_missing_database_without_filling_it(self):
        for side in ("legacy", "contract", "both"):
            for omit in (True, False):
                with self.subTest(side=side, omit=omit):
                    legacy, contract = execution_pair()
                    payload = payload_from(legacy, contract)
                    if side in ("legacy", "both"):
                        if omit:
                            del payload["database"]
                        else:
                            payload["database"] = None
                    if side in ("contract", "both"):
                        if omit:
                            del payload["result_contract"]["execution"]["database"]
                        else:
                            payload["result_contract"]["execution"]["database"] = None
                    before = deepcopy(payload)
                    restored = QueryWorkflow._restore_execution(payload)
                    if side in ("contract", "both"):
                        self.assertIsNone(restored.result_contract.execution.database)
                    self.assertEqual(payload, before)

    def test_workflow_restores_insufficient_but_nonconflicting_contracts(self):
        for factory in (duplicate_pair, lambda: decimal_pair("12.30")):
            legacy, contract = factory()
            payload = payload_from(legacy, contract)
            before = deepcopy(payload)
            restored = QueryWorkflow._restore_execution(payload)
            self.assertEqual(restored.result_contract.model_dump(mode="json"), payload["result_contract"])
            self.assertEqual(restored.rows, payload["rows"])
            self.assertEqual(restored.columns, payload["columns"])
            self.assertEqual(payload, before)

    def test_workflow_only_restores_explicit_outer_result_id(self):
        legacy, contract = execution_pair()
        payload = payload_from(legacy, contract)
        self.assertEqual(QueryWorkflow._restore_execution(payload).result_id, "same-execution")
        for omit in (True, False):
            with self.subTest(omit=omit):
                missing = deepcopy(payload)
                if omit:
                    del missing["result_id"]
                else:
                    missing["result_id"] = None
                restored = QueryWorkflow._restore_execution(missing)
                self.assertIsNone(restored.result_id)
                self.assertEqual(restored.result_contract.result_id, "same-execution")

    def test_mcp_output_contract_schema_only_adds_outer_result_identity(self):
        self.assertEqual(set(DatabaseQueryResult.model_fields), {
            "database", "sql", "success", "columns", "rows", "row_count",
            "error", "result_contract", "result_id",
        })

    def test_workflow_checks_sql_fallback_against_the_contract(self):
        legacy, contract = execution_pair()
        payload = payload_from(legacy, contract)
        del payload["sql"]
        with self.assertRaises(PipelineStageError):
            QueryWorkflow._restore_execution(payload, "SELECT 8 AS value")
        restored = QueryWorkflow._restore_execution(payload, contract.execution.sql)
        self.assertEqual(restored.sql, contract.execution.sql)

    def test_workflow_does_not_turn_unknown_success_into_false(self):
        legacy, contract = execution_pair()
        for omit in (True, False):
            with self.subTest(omit=omit):
                payload = payload_from(legacy, contract)
                if omit:
                    del payload["success"]
                else:
                    payload["success"] = None
                with self.assertRaises(PipelineStageError):
                    QueryWorkflow._restore_execution(payload)

    def test_workflow_conflict_stops_before_result_explanation(self):
        legacy, contract = execution_pair()
        payload = payload_from(legacy, contract)
        payload["sql"] = "SELECT 8 AS value"
        workflow = QueryWorkflow.__new__(QueryWorkflow)
        workflow.response_generator = Mock()
        update = workflow._execute_single_database({
            "task_id": "consistency-test", "mcp_execution": payload,
        })
        self.assertEqual(update["result"]["status"], "failed")
        self.assertEqual(update["execution_log"][-1]["stage"], "result_contract_validation")
        workflow.response_generator.finalize.assert_not_called()

    def test_real_local_mcp_surfaces_handler_consistency_rejection(self):
        legacy, _ = execution_pair()
        legacy.sql = "SELECT 8 AS value"
        engine = Mock(execute=Mock(return_value=legacy))
        client = LocalMcpClient(create_local_mcp_server(engine))
        with self.assertRaises(RuntimeError) as raised:
            client.call_tool("query_askdata_mock", {"sql": legacy.sql})
        self.assertIn("sql", str(raised.exception))
        self.assertNotIn(legacy.sql, str(raised.exception))
        engine.execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
