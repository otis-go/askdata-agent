"""P2-AUD-01: reject contradictory execution facts before understanding SQL."""

import copy
import csv
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from app.database import SCHEMA
from app.querying.duckdb_engine import DuckDbEngine
from app.querying.result_consistency import validate_execution_provenance
from app.querying.result_contract import (
    ColumnMetadata,
    ExecutionData,
    ExecutionProvenance,
    ResultContract,
)
from app.querying.result_understanding import builder


SQL = "SELECT SUM(paid_amount) AS sales_amount FROM orders_current"
CONFLICTING_SQL = "SELECT SUM(order_amount) AS sales_amount FROM orders_current"
SQL_FIELD = "execution.provenance.submitted_sql"
SQL_REASON = "execution/provenance SQL mismatch"
SUBMITTED_FIELD = "execution.provenance.sql_submitted"
SUBMITTED_REASON = "success/sql_submitted conflict"


def captured_contract():
    return ResultContract(
        result_id="audit-conflict",
        execution=ExecutionData(
            database="askdata_mock", sql=SQL, success=True,
            columns=[ColumnMetadata(
                id="column_0", ordinal=0, name="sales_amount", dtype="BIGINT",
                value_encoding="native_json", representation_status="preserved",
            )],
            rows=[[230]], returned_rows=1, total_rows=1, truncated=False,
            completeness="complete_query_output",
            provenance=ExecutionProvenance(
                engine="duckdb", source_kind="csv_views",
                sql_submitted=True, submitted_sql=SQL,
            ),
        ),
    )


class ProvenanceConsistencyTest(unittest.TestCase):
    def assert_validation(self, contract, status):
        before = copy.deepcopy(contract.model_dump())
        report = validate_execution_provenance(contract.execution)
        self.assertEqual(report.status, status)
        self.assertEqual(report, validate_execution_provenance(contract.execution))
        self.assertEqual(contract.model_dump(), before)
        if status == "consistent":
            self.assertEqual(report.conflicts, ())
            self.assertEqual(report.unknowns, ())
        elif status == "insufficient_evidence":
            self.assertEqual(report.conflicts, ())
            self.assertTrue(report.unknowns)
        else:
            self.assertTrue(report.conflicts)
        return report

    def assert_builds(self, contract):
        before = copy.deepcopy(contract.model_dump())
        context = builder.build_business_context(contract, SCHEMA)
        self.assertEqual(context.result_id, contract.result_id)
        self.assertEqual(context.understanding_status, "resolved")
        self.assertEqual(context.limitations, [])
        self.assertEqual(context.column_semantics[0].lineage[0].field, "paid_amount")
        self.assertEqual(context.execution.model_dump(), before["execution"])
        self.assertEqual(contract.model_dump(), before)
        return context

    def assert_rejected(self, contract, field, reason):
        before = copy.deepcopy(contract.model_dump())
        with self.assertRaises(ValueError) as raised:
            builder.build_business_context(contract, SCHEMA)
        message = str(raised.exception)
        self.assertIn(field, message)
        self.assertIn(reason, message)
        self.assertNotIn(SQL, message)
        self.assertNotIn(CONFLICTING_SQL, message)
        self.assertEqual(contract.model_dump(), before)

    def test_matching_execution_and_provenance_build_resolved_context(self):
        contract = captured_contract()
        self.assert_validation(contract, "consistent")
        self.assert_builds(contract)

    def test_original_p2_aud_01_reproduction_is_rejected(self):
        contract = captured_contract()
        contract.execution.provenance.submitted_sql = CONFLICTING_SQL
        report = self.assert_validation(contract, "inconsistent")
        self.assertEqual(
            [(issue.field, issue.reason) for issue in report.conflicts],
            [(SQL_FIELD, SQL_REASON)],
        )
        self.assert_rejected(contract, SQL_FIELD, SQL_REASON)

    def test_success_when_sql_was_not_submitted_is_rejected(self):
        contract = captured_contract()
        contract.execution.provenance.sql_submitted = False
        report = self.assert_validation(contract, "inconsistent")
        self.assertEqual(
            [(issue.field, issue.reason) for issue in report.conflicts],
            [(SUBMITTED_FIELD, SUBMITTED_REASON)],
        )
        self.assert_rejected(contract, SUBMITTED_FIELD, SUBMITTED_REASON)

    def test_absent_optional_provenance_remains_compatible(self):
        contract = captured_contract()
        contract.execution.provenance = None
        self.assert_validation(contract, "insufficient_evidence")
        context = self.assert_builds(contract)
        self.assertIsNone(context.execution.provenance)

    def test_unknown_submitted_sql_remains_compatible(self):
        contract = captured_contract()
        contract.execution.provenance.submitted_sql = None
        self.assert_validation(contract, "insufficient_evidence")
        context = self.assert_builds(contract)
        self.assertIsNone(context.execution.provenance.submitted_sql)

    def test_unknown_sql_submitted_is_not_false(self):
        contract = captured_contract()
        contract.execution.provenance.sql_submitted = None
        self.assert_validation(contract, "insufficient_evidence")
        context = self.assert_builds(contract)
        self.assertIsNone(context.execution.provenance.sql_submitted)

    def test_empty_optional_provenance_remains_compatible(self):
        contract = captured_contract()
        contract.execution.provenance = ExecutionProvenance()
        self.assert_validation(contract, "insufficient_evidence")
        self.assert_builds(contract)

    def test_sql_comparison_is_strict_without_equivalence_normalization(self):
        for submitted_sql in (SQL.lower(), " " + SQL, SQL + ";", SQL + " -- same query"):
            with self.subTest(submitted_sql=submitted_sql):
                contract = captured_contract()
                contract.execution.provenance.submitted_sql = submitted_sql
                self.assert_validation(contract, "inconsistent")
                self.assert_rejected(contract, SQL_FIELD, SQL_REASON)

    def test_known_conflicts_take_precedence_over_missing_optional_evidence(self):
        cases = (
            (CONFLICTING_SQL, None, SQL_FIELD, SQL_REASON),
            (None, False, SUBMITTED_FIELD, SUBMITTED_REASON),
        )
        for submitted_sql, sql_submitted, field, reason in cases:
            with self.subTest(field=field):
                contract = captured_contract()
                contract.execution.provenance.submitted_sql = submitted_sql
                contract.execution.provenance.sql_submitted = sql_submitted
                report = self.assert_validation(contract, "inconsistent")
                self.assertTrue(report.unknowns)
                self.assertIn((field, reason), [(x.field, x.reason) for x in report.conflicts])
                self.assert_rejected(contract, field, reason)

    def test_both_known_conflicts_are_reported_without_sql_values(self):
        contract = captured_contract()
        contract.execution.provenance.submitted_sql = CONFLICTING_SQL
        contract.execution.provenance.sql_submitted = False
        report = self.assert_validation(contract, "inconsistent")
        self.assertEqual(
            {(issue.field, issue.reason) for issue in report.conflicts},
            {(SQL_FIELD, SQL_REASON), (SUBMITTED_FIELD, SUBMITTED_REASON)},
        )
        self.assertNotIn(SQL, repr(report))
        self.assertNotIn(CONFLICTING_SQL, repr(report))
        self.assert_rejected(contract, SQL_FIELD, SQL_REASON)
        self.assert_rejected(contract, SUBMITTED_FIELD, SUBMITTED_REASON)

    def test_unknown_execution_scalars_are_not_coerced_by_helper(self):
        for field in ("sql", "success"):
            with self.subTest(field=field):
                contract = captured_contract()
                setattr(contract.execution, field, None)
                self.assert_validation(contract, "insufficient_evidence")
                self.assertIsNone(getattr(contract.execution, field))

    def test_failed_unsubmitted_execution_does_not_trigger_success_conflict(self):
        contract = captured_contract()
        contract.execution.success = False
        contract.execution.provenance.sql_submitted = False
        contract.execution.provenance.submitted_sql = None
        self.assert_validation(contract, "insufficient_evidence")

    def test_two_conflict_types_fail_before_every_semantic_entry(self):
        stages = (
            "parse_sql", "understand_columns", "bind_schema", "prepare_query_bindings",
            "understand_grain", "understand_filters", "understand_time_constraints",
        )
        for conflict in ("sql", "submitted"):
            with self.subTest(conflict=conflict):
                contract = captured_contract()
                if conflict == "sql":
                    contract.execution.provenance.submitted_sql = CONFLICTING_SQL
                    field, reason = SQL_FIELD, SQL_REASON
                else:
                    contract.execution.provenance.sql_submitted = False
                    field, reason = SUBMITTED_FIELD, SUBMITTED_REASON
                with ExitStack() as stack:
                    spies = {
                        stage: stack.enter_context(patch.object(
                            builder, stage,
                            side_effect=AssertionError(f"{stage} must not run for conflicting facts"),
                        ))
                        for stage in stages
                    }
                    self.assert_rejected(contract, field, reason)
                    for stage, spy in spies.items():
                        with self.subTest(stage=stage):
                            spy.assert_not_called()

    def test_helper_and_builder_preserve_nested_input_values_and_objects(self):
        for conflict in (False, True):
            with self.subTest(conflict=conflict):
                contract = captured_contract()
                if conflict:
                    contract.execution.provenance.submitted_sql = CONFLICTING_SQL
                execution = contract.execution
                provenance = execution.provenance
                columns, column = execution.columns, execution.columns[0]
                rows, row = execution.rows, execution.rows[0]
                before = copy.deepcopy(contract.model_dump())
                schema = copy.deepcopy(SCHEMA)
                schema_before = copy.deepcopy(schema)
                self.assert_validation(contract, "inconsistent" if conflict else "consistent")
                if conflict:
                    with self.assertRaisesRegex(ValueError, SQL_REASON):
                        builder.build_business_context(contract, schema)
                else:
                    context = builder.build_business_context(contract, schema)
                    self.assertEqual(context.execution.model_dump(), before["execution"])
                    self.assertIsNot(context.execution, execution)
                    self.assertIsNot(context.execution.provenance, provenance)
                    self.assertIsNot(context.execution.rows[0], row)
                self.assertEqual(contract.model_dump(), before)
                self.assertEqual(schema, schema_before)
                self.assertIs(contract.execution, execution)
                self.assertIs(execution.provenance, provenance)
                self.assertIs(execution.columns, columns)
                self.assertIs(execution.columns[0], column)
                self.assertIs(execution.rows, rows)
                self.assertIs(execution.rows[0], row)

    def test_real_duckdb_producer_builds_without_further_execution(self):
        sql = (
            "SELECT region, SUM(paid_amount) AS sales_amount "
            "FROM orders_current GROUP BY region"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            folder = root / "askdata_mock"
            folder.mkdir()
            with (folder / "orders_current.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["region", "paid_amount"])
                writer.writerows([("华北", 100), ("华北", 50), ("华南", 80)])
            engine = DuckDbEngine(root)
            # Only fixture capture executes SQL; the public consumer below may not.
            produced = engine.execute("askdata_mock", f"```sql\n{sql};\n```")
            self.assertTrue(produced.success, produced.error)
            contract = produced.result_contract
            self.assertIsInstance(contract, ResultContract)
            self.assertEqual(contract.execution.sql, sql)
            self.assertEqual(contract.execution.provenance.submitted_sql, sql)
            self.assertIs(contract.execution.provenance.sql_submitted, True)
            self.assertEqual(
                sorted(contract.execution.rows), sorted([["华北", 150], ["华南", 80]]),
            )
            before = copy.deepcopy(contract.model_dump())
            with (
                patch.object(DuckDbEngine, "execute", side_effect=AssertionError("must not re-execute")) as execute,
                patch.object(DuckDbEngine, "connect", side_effect=AssertionError("must not reconnect")) as connect,
                patch("app.querying.duckdb_engine.duckdb.connect", side_effect=AssertionError("must not connect")) as native_connect,
            ):
                self.assert_validation(contract, "consistent")
                context = builder.build_business_context(contract, SCHEMA)
                execute.assert_not_called()
                connect.assert_not_called()
                native_connect.assert_not_called()
            self.assertEqual(context.understanding_status, "resolved")
            self.assertEqual(context.limitations, [])
            self.assertEqual(context.grain.query_grain, "grouped")
            self.assertEqual(context.column_semantics[1].lineage[0].field, "paid_amount")
            self.assertEqual(context.result_id, contract.result_id)
            self.assertEqual(context.execution.model_dump(), before["execution"])
            self.assertEqual(contract.model_dump(), before)


if __name__ == "__main__":
    unittest.main()
