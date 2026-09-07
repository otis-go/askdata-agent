"""Public BusinessContext assembly: execution identity, evidence and boundaries.

Fixtures contain captured facts only. Positive integration tests do not prepare
hidden bindings themselves and never execute SQL or call an LLM.
"""

import ast
import copy
import inspect
import unittest
from unittest.mock import patch

import sqlglot
from pydantic import ValidationError

from app.database import SCHEMA
from app.querying.result_contract import (
    ColumnMetadata,
    ExecutionData,
    ExecutionProvenance,
    ResultContract,
)
from app.querying.result_understanding.builder import build_business_context
from app.querying.result_understanding import builder
from app.querying.result_understanding.lineage import understand_columns
from app.querying.result_understanding.models import BusinessContext
from app.querying.result_understanding.sql_parser import parse_sql


FULL_SQL = """
SELECT o.region, SUM(o.paid_amount) AS sales_amount
FROM orders_current AS o
WHERE o.status = '已支付'
  AND o.order_date >= DATE '2026-08-01'
  AND o.order_date < DATE '2026-09-01'
GROUP BY o.region
HAVING SUM(o.paid_amount) > 0
ORDER BY o.region
LIMIT 10
"""


def contract_for(sql, names, *, database="askdata_mock", rows=None):
    """Known column names/ordinals are captured input, not parsed test evidence."""
    return ResultContract(
        result_id="business-context-captured-result",
        execution=ExecutionData(
            database=database,
            sql=sql,
            success=True,
            columns=[
                ColumnMetadata(id=f"column_{ordinal}", ordinal=ordinal, name=name)
                for ordinal, name in enumerate(names)
            ],
            rows=rows,
        ),
    )


def fixed_contract():
    return ResultContract(
        result_id="fixed-query-result-identity",
        execution=ExecutionData(
            database="askdata_mock", sql=FULL_SQL, success=True,
            columns=[
                ColumnMetadata(
                    id="column_0", ordinal=0, name="region", dtype="VARCHAR",
                    value_encoding="native_json", representation_status="preserved",
                ),
                ColumnMetadata(
                    id="column_1", ordinal=1, name="sales_amount", dtype="DECIMAL(38,2)",
                    value_encoding="decimal_text", representation_status="preserved",
                ),
            ],
            rows=[["华北", "100.10"], ["华南", "200.20"]],
            returned_rows=2, total_rows=2, truncated=False,
            completeness="complete_query_output",
            provenance=ExecutionProvenance(
                engine="duckdb", source_kind="csv_views",
                captured_at="2026-09-07T00:00:00+00:00", sql_submitted=True,
                submitted_sql=FULL_SQL, access_scope_ref="captured-scope", snapshot_ref=None,
            ),
        ),
    )


class BusinessContextTest(unittest.TestCase):
    def build(self, sql, names, **kwargs):
        return build_business_context(contract_for(sql, names, **kwargs), SCHEMA)

    def test_fixed_sql_uses_one_public_entry_for_all_semantic_evidence(self):
        contract = fixed_contract()
        context = build_business_context(contract, SCHEMA)
        self.assertIsInstance(context, BusinessContext)
        self.assertEqual(context.version, "1")
        self.assertEqual(context.result_id, contract.result_id)
        self.assertEqual(context.result_contract_version, contract.version)
        self.assertEqual(context.execution.model_dump(), contract.execution.model_dump())
        self.assertEqual(context.understanding_status, "resolved")
        self.assertEqual(context.limitations, [])

        self.assertEqual(len(context.column_semantics), 2)
        region, sales = context.column_semantics
        self.assertEqual((region.column_id, region.ordinal, region.output_name), ("column_0", 0, "region"))
        self.assertEqual((sales.column_id, sales.ordinal, sales.output_name), ("column_1", 1, "sales_amount"))
        self.assertEqual(region.lineage[0].field, "region")
        self.assertEqual(region.lineage[0].table, "orders_current")
        self.assertEqual(region.schema_bindings[0].label, "销售地区")
        self.assertEqual(sales.lineage[0].field, "paid_amount")
        self.assertEqual(sales.aggregation, "SUM")
        self.assertEqual(sales.schema_bindings[0].label, "实付金额")

        self.assertEqual(context.query_bindings.status, "resolved")
        self.assertEqual(
            [binding.source.field for binding in context.query_bindings.bindings],
            ["region", "paid_amount", "status", "order_date"],
        )
        self.assertEqual(context.grain.query_grain, "grouped")
        self.assertEqual(context.grain.business_grain, ["销售地区"])
        self.assertEqual(context.grain.status, "resolved")
        self.assertEqual(context.filters.status, "resolved")
        self.assertEqual([condition.scope for condition in context.filters.filters], ["WHERE", "WHERE", "WHERE", "HAVING"])
        self.assertTrue(all(condition.status == "resolved" for condition in context.filters.filters))
        self.assertEqual(context.filters.filters[-1].aggregation_expression, "SUM(o.paid_amount)")
        self.assertEqual(context.filters.excluded_scopes, [])
        self.assertEqual(len(context.time_constraints), 1)
        time = context.time_constraints[0]
        self.assertEqual(time.source_field.field, "order_date")
        self.assertEqual(time.source_field.table, "orders_current")
        self.assertEqual((time.lower, time.upper), ("2026-08-01", "2026-09-01"))
        self.assertEqual((time.inclusive.lower, time.inclusive.upper), (True, False))
        self.assertEqual(time.status, "resolved")
        self.assertNotIn("LIMIT", " ".join(condition.expression for condition in context.filters.filters))
        self.assertEqual(context.execution.completeness, "complete_query_output")

    def test_global_aggregate_without_time_is_resolved_not_inferred_current_month(self):
        context = self.build("SELECT SUM(paid_amount) FROM orders_current", ["sum(paid_amount)"])
        self.assertEqual(context.understanding_status, "resolved")
        self.assertEqual(context.grain.query_grain, "global_aggregate")
        self.assertIsNone(context.grain.business_grain)
        self.assertEqual(context.filters.status, "resolved")
        self.assertEqual(context.filters.filters, [])
        self.assertEqual(context.time_constraints, [])

    def test_detail_query_does_not_infer_grain_from_dimension_role(self):
        context = self.build("SELECT region, customer_id FROM orders_current", ["region", "customer_id"])
        self.assertEqual(context.column_semantics[0].schema_bindings[0].role, "dimension")
        self.assertEqual(context.grain.status, "unknown")
        self.assertIsNone(context.grain.query_grain)
        self.assertIsNone(context.grain.business_grain)
        self.assertEqual(context.understanding_status, "unknown")
        self.assertTrue(any(message.startswith("grain:") for message in context.limitations))

    def test_unsupported_projection_dominates_resolved_grain(self):
        sql = "SELECT region, ROUND(SUM(paid_amount),2) FROM orders_current GROUP BY region"
        contract = contract_for(sql, ["region", "rounded"])
        contract.execution.completeness = "complete_query_output"
        context = build_business_context(contract, SCHEMA)
        self.assertEqual(context.column_semantics[1].status, "unsupported")
        self.assertEqual(context.grain.status, "resolved")
        self.assertEqual(context.understanding_status, "unsupported")
        self.assertEqual(context.execution.completeness, "complete_query_output")
        self.assertTrue(any(message.startswith("lineage:") for message in context.limitations))

    def test_or_filter_remains_unsupported_despite_resolved_grain(self):
        context = self.build(
            "SELECT region,SUM(paid_amount) FROM orders_current "
            "WHERE region='华北' OR region='华南' GROUP BY region",
            ["region", "sales"],
        )
        self.assertEqual(context.grain.status, "resolved")
        self.assertEqual(context.filters.status, "unsupported")
        self.assertEqual(context.understanding_status, "unsupported")
        self.assertEqual(len(context.filters.filters), 1)
        self.assertIn(" OR ", context.filters.filters[0].expression)

    def test_missing_schema_binding_does_not_upgrade_resolved_lineage(self):
        schema = copy.deepcopy(SCHEMA)
        table = next(table for table in schema if table["id"] == "orders_current")
        table["fields"] = [field for field in table["fields"] if field["name"] != "paid_amount"]
        context = build_business_context(
            contract_for("SELECT SUM(paid_amount) FROM orders_current", ["sales_amount"]), schema,
        )
        self.assertEqual(context.column_semantics[0].status, "resolved")
        self.assertEqual(context.column_semantics[0].schema_bindings, [])
        self.assertEqual(context.query_bindings.status, "unknown")
        self.assertEqual(context.understanding_status, "unknown")
        self.assertTrue(context.limitations)

    def test_hidden_only_missing_schema_identity_keeps_overall_unknown(self):
        schema = copy.deepcopy(SCHEMA)
        table = next(table for table in schema if table["id"] == "orders_current")
        table["fields"] = [field for field in table["fields"] if field["name"] != "order_date"]
        context = build_business_context(
            contract_for(
                "SELECT SUM(paid_amount) FROM orders_current WHERE order_date >= DATE '2026-08-01'",
                ["sales_amount"],
            ),
            schema,
        )
        self.assertEqual(context.column_semantics[0].status, "resolved")
        self.assertEqual(context.column_semantics[0].schema_bindings[0].source.field, "paid_amount")
        self.assertEqual(len(context.column_semantics), 1)
        self.assertEqual(context.query_bindings.status, "unknown")
        self.assertEqual(context.query_bindings.bindings, [])
        self.assertEqual(context.understanding_status, "unknown")
        self.assertTrue(any(message.startswith("query_bindings:") for message in context.limitations))

    def test_schema_identity_conflict_is_unknown_without_picking_a_candidate(self):
        schema = copy.deepcopy(SCHEMA)
        table = next(table for table in schema if table["id"] == "orders_current")
        duplicate = copy.deepcopy(next(field for field in table["fields"] if field["name"] == "paid_amount"))
        duplicate["name"] = "PAID_AMOUNT"
        duplicate["label"] = "conflicting label"
        table["fields"].append(duplicate)
        context = build_business_context(
            contract_for("SELECT SUM(paid_amount) FROM orders_current", ["sales_amount"]), schema,
        )
        self.assertEqual(context.understanding_status, "unknown")
        self.assertEqual(context.column_semantics[0].schema_bindings, [])
        self.assertEqual(context.query_bindings.bindings, [])

    def test_count_star_preserves_table_source_without_fake_field_binding(self):
        context = self.build("SELECT COUNT(*) FROM orders_current", ["count_star()"])
        column = context.column_semantics[0]
        self.assertEqual(context.understanding_status, "resolved")
        self.assertEqual(column.aggregation, "COUNT")
        self.assertEqual(column.lineage[0].table, "orders_current")
        self.assertIsNone(column.lineage[0].field)
        self.assertEqual(column.schema_bindings, [])
        self.assertEqual(context.query_bindings.bindings, [])

    def test_existing_having_count_time_limitation_is_retained_not_silently_upgraded(self):
        context = self.build("SELECT COUNT(*) FROM orders_current HAVING COUNT(*)>0", ["count_star()"])
        self.assertEqual(context.filters.status, "resolved")
        self.assertEqual(context.filters.filters[0].aggregation_expression, "COUNT(*)")
        self.assertIsNone(context.filters.filters[0].lineage[0].field)
        # Existing V1 Time reader requires a physical field per predicate. The
        # assembler records its conservative limitation, not a new algorithm.
        self.assertEqual(context.time_constraints[0].status, "unknown")
        self.assertEqual(context.understanding_status, "unknown")
        self.assertTrue(any(item.startswith("time:") for item in context.limitations))

    def test_source_free_constant_does_not_need_invented_grain_or_binding(self):
        context = self.build("SELECT 1 AS x", ["x"])
        self.assertEqual(context.understanding_status, "resolved")
        self.assertEqual(context.column_semantics[0].lineage, [])
        self.assertEqual(context.column_semantics[0].schema_bindings, [])
        self.assertEqual(context.query_bindings.bindings, [])
        self.assertEqual(context.grain.status, "unknown")
        self.assertIsNone(context.grain.query_grain)
        self.assertEqual(context.time_constraints, [])

    def test_source_free_constant_does_not_need_database_identity(self):
        context = self.build("SELECT 1 AS x", ["x"], database=None)
        self.assertIsNone(context.execution.database)
        self.assertEqual(context.understanding_status, "resolved")
        self.assertEqual(context.query_bindings.status, "unknown")
        self.assertEqual(context.query_bindings.bindings, [])
        self.assertEqual(context.column_semantics[0].lineage, [])

    def test_constant_from_table_does_not_claim_source_free_query_grain(self):
        context = self.build("SELECT 1 AS x FROM orders_current", ["x"])
        self.assertEqual(context.grain.status, "unknown")
        self.assertEqual(context.understanding_status, "unknown")

    def test_unprojected_time_stays_query_evidence_not_extra_output(self):
        context = self.build(
            "SELECT SUM(paid_amount) FROM orders_current "
            "WHERE order_date >= DATE '2026-08-01' AND order_date < DATE '2026-09-01'",
            ["sales_amount"],
        )
        self.assertEqual(context.understanding_status, "resolved")
        self.assertEqual(len(context.column_semantics), 1)
        self.assertEqual(context.column_semantics[0].lineage[0].field, "paid_amount")
        self.assertEqual([item.source.field for item in context.query_bindings.bindings], ["paid_amount", "order_date"])
        self.assertEqual(context.time_constraints[0].status, "resolved")
        self.assertEqual(context.time_constraints[0].source_field.field, "order_date")

    def test_build_is_deterministic_and_deeply_isolated_from_inputs_and_each_other(self):
        contract = fixed_contract()
        schema = copy.deepcopy(SCHEMA)
        contract_before, schema_before = contract.model_dump(), copy.deepcopy(schema)
        first = build_business_context(contract, schema)
        second = build_business_context(contract, schema)
        self.assertEqual(first, second)
        self.assertIsNot(first.execution, contract.execution)
        self.assertIsNot(first.execution.columns, contract.execution.columns)
        self.assertIsNot(first.execution.rows, contract.execution.rows)
        self.assertIsNot(first.execution.provenance, contract.execution.provenance)
        second_before = second.model_dump()
        first.execution.rows[0][0] = "test-owned change"
        first.execution.columns[0].name = "test-owned name"
        first.execution.provenance.engine = "test-owned engine"
        first.column_semantics[0].schema_bindings[0].aliases.clear()
        first.query_bindings.bindings.clear()
        first.filters.filters.clear()
        first.grain.business_grain.clear()
        first.time_constraints[0].schema_bindings.clear()
        first.limitations.append("test-owned diagnostic")
        self.assertEqual(contract.model_dump(), contract_before)
        self.assertEqual(schema, schema_before)
        self.assertEqual(second.model_dump(), second_before)

    def test_existing_parsed_ast_and_column_semantics_are_not_mutated(self):
        contract = fixed_contract()
        parsed = parse_sql(FULL_SQL)
        columns = understand_columns(contract)
        before_ast = copy.deepcopy(parsed.statement.dump())
        before_columns = [column.model_dump() for column in columns]
        with patch("app.querying.result_understanding.builder.parse_sql", return_value=parsed), \
             patch("app.querying.result_understanding.builder.understand_columns", return_value=columns):
            context = build_business_context(contract, SCHEMA)
        self.assertEqual(context.understanding_status, "resolved")
        self.assertEqual(parsed.statement.dump(), before_ast)
        self.assertEqual([column.model_dump() for column in columns], before_columns)
        context.column_semantics[0].lineage.clear()
        self.assertEqual([column.model_dump() for column in columns], before_columns)

    def test_failed_or_unknown_execution_is_explicitly_rejected_before_parsing(self):
        for success in (False, None):
            with self.subTest(success=success):
                contract = ResultContract(
                    result_id="unsuccessful-capture",
                    execution=ExecutionData(sql="SELECT 1", success=success, error="captured failure"),
                )
                before = contract.model_dump()
                with patch("sqlglot.parse", side_effect=AssertionError("failed execution must not be parsed")):
                    with self.assertRaises(ValueError):
                        build_business_context(contract, SCHEMA)
                self.assertEqual(contract.model_dump(), before)

    def test_missing_required_sql_or_output_columns_is_explicitly_rejected(self):
        cases = [
            ExecutionData(success=True, sql="SELECT 1", columns=None),
            ExecutionData(success=True, sql="SELECT 1", columns=[]),
            ExecutionData(success=True, sql=None, columns=[ColumnMetadata(id="column_0", ordinal=0, name="x")]),
            ExecutionData(success=True, sql=" ", columns=[ColumnMetadata(id="column_0", ordinal=0, name="x")]),
        ]
        for execution in cases:
            with self.subTest(execution=execution):
                with self.assertRaises(ValueError):
                    build_business_context(ResultContract(result_id="missing-evidence", execution=execution), SCHEMA)

    def test_invalid_schema_input_types_raise_instead_of_silent_fallback(self):
        contract = fixed_contract()
        for schema in (None, "SCHEMA", {}, ["not a table mapping"]):
            with self.subTest(schema=schema):
                with self.assertRaises(TypeError):
                    build_business_context(contract, schema)

    def test_execution_unknowns_are_not_recomputed_from_rows_or_semantics(self):
        contract = contract_for("SELECT SUM(paid_amount) FROM orders_current", ["sales"], rows=[["100.00"]])
        context = build_business_context(contract, SCHEMA)
        self.assertEqual(context.execution.model_dump(), contract.execution.model_dump())
        self.assertIsNone(context.execution.returned_rows)
        self.assertIsNone(context.execution.total_rows)
        self.assertIsNone(context.execution.truncated)
        self.assertIsNone(context.execution.completeness)
        self.assertIsNone(context.execution.columns[0].dtype)
        self.assertIsNone(context.execution.columns[0].representation_status)
        self.assertIsNone(context.execution.provenance)

    def test_partial_execution_can_have_resolved_understanding_without_changing_capture_facts(self):
        contract = contract_for(
            "SELECT region,SUM(paid_amount) FROM orders_current GROUP BY region LIMIT 10",
            ["region", "sales"], rows=[["华北", "100.00"]],
        )
        contract.execution.returned_rows = 1
        contract.execution.truncated = True
        contract.execution.completeness = "partial_query_output"
        context = build_business_context(contract, SCHEMA)
        self.assertEqual(context.understanding_status, "resolved")
        self.assertEqual(context.execution.model_dump(), contract.execution.model_dump())
        self.assertTrue(context.execution.truncated)
        self.assertIsNone(context.execution.total_rows)

    def test_duplicate_output_names_preserve_ordinal_identity_and_canonical_rows(self):
        context = self.build("SELECT 1 AS x, 2 AS x", ["x", "x"], rows=[[1, 2]])
        self.assertEqual([item.column_id for item in context.column_semantics], ["column_0", "column_1"])
        self.assertEqual([item.ordinal for item in context.column_semantics], [0, 1])
        self.assertEqual([item.output_name for item in context.column_semantics], ["x", "x"])
        self.assertEqual([item.expression for item in context.column_semantics], ["1", "2"])
        self.assertEqual(context.execution.rows, [[1, 2]])

    def test_actual_avg_and_schema_default_sum_remain_separate(self):
        context = self.build("SELECT AVG(paid_amount) AS average_amount FROM orders_current", ["average_amount"])
        self.assertEqual(context.understanding_status, "resolved")
        self.assertEqual(context.column_semantics[0].aggregation, "AVG")
        self.assertEqual(context.column_semantics[0].schema_bindings[0].default_aggregation, "sum")

    def test_rows_and_table_names_do_not_establish_query_time(self):
        context = self.build("SELECT order_date FROM orders_current", ["order_date"], rows=[["2026-08-01"], ["2026-08-31"]])
        self.assertEqual(context.column_semantics[0].schema_bindings[0].role, "time")
        self.assertEqual(context.time_constraints, [])

    def test_previous_unsupported_features_are_not_enabled_by_assembly(self):
        cases = [
            ("WITH source AS (SELECT region FROM orders_current) SELECT region FROM source", ["region"]),
            ("SELECT region FROM orders_current UNION ALL SELECT region FROM customers", ["region"]),
            ("SELECT SUM(paid_amount) OVER (PARTITION BY region) FROM orders_current", ["sales"]),
            ("SELECT SUM(paid_amount) FROM orders_current GROUP BY DATE_TRUNC('month', order_date)", ["sales"]),
            ("SELECT SUM(paid_amount) FROM orders_current WHERE order_date>=CURRENT_DATE", ["sales"]),
        ]
        for sql, names in cases:
            with self.subTest(sql=sql):
                context = self.build(sql, names)
                self.assertEqual(context.understanding_status, "unsupported")
                self.assertTrue(context.limitations)

    def test_join_on_and_qualify_remain_excluded_not_where(self):
        cases = [
            (
                "SELECT o.region FROM orders_current o JOIN customers c ON o.customer_id=c.customer_id WHERE o.region='华北'",
                "JOIN ON",
            ),
            ("SELECT region FROM orders_current QUALIFY region='华北'", "QUALIFY"),
        ]
        for sql, expected_scope in cases:
            with self.subTest(sql=sql):
                context = self.build(sql, ["region"])
                self.assertEqual(context.understanding_status, "unsupported")
                self.assertEqual([condition.scope for condition in context.filters.excluded_scopes], [expected_scope])
                self.assertTrue(all(condition.scope in {"WHERE", "HAVING"} for condition in context.filters.filters))

    def test_malformed_or_multi_statement_sql_is_not_reduced_to_a_successful_first_query(self):
        for sql in ("SELECT (", "SELECT 1; SELECT 2"):
            with self.subTest(sql=sql):
                context = self.build(sql, ["x"])
                self.assertEqual(context.understanding_status, "unsupported")
                self.assertEqual(context.column_semantics[0].status, "unsupported")
                self.assertEqual(context.execution.sql, sql)
                self.assertTrue(context.limitations)

    def test_limitations_are_stable_deduplicated_and_stage_attributed(self):
        contract = contract_for(
            "SELECT region, ROUND(SUM(paid_amount),2) FROM orders_current "
            "WHERE region='华北' OR region='华南' GROUP BY region",
            ["region", "rounded"],
        )
        first = build_business_context(contract, SCHEMA)
        second = build_business_context(contract, SCHEMA)
        self.assertEqual(first.limitations, second.limitations)
        self.assertEqual(first.limitations, list(dict.fromkeys(first.limitations)))
        self.assertTrue(any(item.startswith("lineage:") for item in first.limitations))
        self.assertTrue(any(item.startswith("filter:") for item in first.limitations))
        self.assertTrue(all(":" in item for item in first.limitations))

    def test_p2_02_original_query_still_parses_twice_and_is_not_claimed_single_parse(self):
        original_parse = sqlglot.parse
        with patch("sqlglot.parse", wraps=original_parse) as parser:
            context = build_business_context(fixed_contract(), SCHEMA)
        original_query_calls = [call for call in parser.call_args_list if call.args and call.args[0] == FULL_SQL]
        self.assertEqual(len(original_query_calls), 2)
        self.assertEqual(context.understanding_status, "resolved")

    def test_business_context_version_is_validated_and_round_trip_preserves_execution(self):
        context = build_business_context(fixed_contract(), SCHEMA)
        restored = BusinessContext.model_validate_json(context.model_dump_json())
        self.assertEqual(restored, context)
        invalid = context.model_dump()
        invalid["version"] = "2"
        with self.assertRaises(ValidationError):
            BusinessContext.model_validate(invalid)

    def test_builder_static_boundary_remains_semantic_assembly_only(self):
        tree = ast.parse(inspect.getsource(builder))
        allowed_imports = {
            "__future__", "typing", "result_contract", "result_consistency", "filter", "grain", "lineage",
            "models", "schema_binding", "sql_parser", "time_constraint",
        }
        forbidden_calls = {
            "execute", "connect", "call_tool", "chat", "generate", "rerank", "embed",
            "now", "today", "utcnow", "min", "max", "eval", "exec",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertTrue(all(alias.name in allowed_imports for alias in node.names))
            elif isinstance(node, ast.ImportFrom):
                self.assertIn(node.module, allowed_imports)
            elif isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else (
                    node.func.attr if isinstance(node.func, ast.Attribute) else None
                )
                self.assertNotIn(name, forbidden_calls)
            elif isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, {"rows", "retrieval", "schema_graph"})
            elif isinstance(node, ast.ExceptHandler):
                self.assertIsNotNone(node.type)
                self.assertIsInstance(node.type, ast.Name)
                self.assertEqual(node.type.id, "UnsupportedSQL")


if __name__ == "__main__":
    unittest.main()
