"""Grain understanding uses caller-owned AST/lineage, never SQL execution."""

import copy
import unittest
from unittest.mock import patch

import sqlglot
from sqlglot import exp

from app.database import SCHEMA
from app.querying.result_contract import ColumnMetadata, ExecutionData, ResultContract
from app.querying.result_understanding.grain import understand_grain
from app.querying.result_understanding.lineage import understand_columns
from app.querying.result_understanding.models import LineageSource, SchemaBinding
from app.querying.result_understanding.schema_binding import bind_schema
from app.querying.result_understanding.sql_parser import ParsedSelect, parse_sql


def inputs(sql, *, bound=True, database="askdata_mock"):
    """Prepare the input before calling the non-parsing grain API."""
    statement = sqlglot.parse_one(sql, read="duckdb")
    projections = statement.expressions if isinstance(statement, exp.Select) else [None]
    contract = ResultContract(
        result_id="grain-test-result",
        execution=ExecutionData(
            database=database, sql=sql, success=True,
            columns=[
                ColumnMetadata(id=f"column_{index}", ordinal=index, name=f"display_{index}")
                for index, _ in enumerate(projections)
            ],
        ),
    )
    semantics = understand_columns(contract)
    if bound:
        semantics = [bind_schema(column, SCHEMA) for column in semantics]
    return statement, semantics


def source(field="region", table="orders_current", database="askdata_mock"):
    return LineageSource(database=database, table=table, field=field)


class GrainUnderstandingTest(unittest.TestCase):
    def test_group_by_field_uses_actual_lineage_and_schema_label(self):
        statement, semantics = inputs(
            "SELECT o.region, SUM(o.paid_amount) AS sales_amount "
            "FROM orders_current o GROUP BY o.region",
        )
        result = understand_grain(statement, semantics)
        self.assertEqual(result.query_grain, "grouped")
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.grouping_expressions, ["o.region"])
        self.assertEqual(result.grouping_columns, [source()])
        self.assertEqual(result.business_grain, ["销售地区"])

    def test_multiple_grouping_fields_keep_group_by_order(self):
        statement, semantics = inputs(
            "SELECT o.region, o.category, SUM(o.paid_amount) "
            "FROM orders_current o GROUP BY o.category, o.region",
        )
        result = understand_grain(statement, semantics)
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.grouping_expressions, ["o.category", "o.region"])
        self.assertEqual(result.grouping_columns, [source("category"), source()])
        self.assertEqual(result.business_grain, ["产品类别", "销售地区"])

    def test_global_sum_avg_and_count(self):
        for expression in ("SUM(paid_amount)", "AVG(paid_amount)", "COUNT(*)", "COUNT(order_id)"):
            with self.subTest(expression=expression):
                result = understand_grain(*inputs(f"SELECT {expression} FROM orders_current"))
                self.assertEqual(result.query_grain, "global_aggregate")
                self.assertEqual(result.status, "resolved")
                self.assertEqual(result.grouping_expressions, [])
                self.assertEqual(result.grouping_columns, [])
                self.assertIsNone(result.business_grain)

    def test_global_aggregate_may_have_a_constant_projection(self):
        result = understand_grain(*inputs("SELECT SUM(paid_amount), 'all' AS bucket FROM orders_current"))
        self.assertEqual(result.query_grain, "global_aggregate")
        self.assertEqual(result.status, "resolved")

    def test_date_trunc_group_is_unsupported(self):
        result = understand_grain(*inputs(
            "SELECT DATE_TRUNC('month', order_date), SUM(paid_amount) "
            "FROM orders_current GROUP BY DATE_TRUNC('month', order_date)",
        ))
        self.assertEqual(result.status, "unsupported")
        self.assertTrue(result.limitations)

    def test_window_partition_is_unsupported(self):
        result = understand_grain(*inputs(
            "SELECT region, SUM(paid_amount) OVER (PARTITION BY region) FROM orders_current",
        ))
        self.assertEqual(result.status, "unsupported")
        self.assertNotEqual(result.query_grain, "global_aggregate")

    def test_window_outside_projection_is_still_unsupported(self):
        result = understand_grain(*inputs(
            "SELECT region FROM orders_current QUALIFY ROW_NUMBER() OVER (PARTITION BY region) = 1",
        ))
        self.assertEqual(result.status, "unsupported")

    def test_cube_rollup_grouping_sets_and_all_are_unsupported(self):
        for grouping in ("CUBE(region)", "ROLLUP(region)", "GROUPING SETS ((region), ())", "ALL"):
            with self.subTest(grouping=grouping):
                result = understand_grain(*inputs(
                    "SELECT region, SUM(paid_amount) FROM orders_current GROUP BY " + grouping,
                ))
                self.assertEqual(result.status, "unsupported")

    def test_arithmetic_grouping_expression_is_unsupported(self):
        result = understand_grain(*inputs(
            "SELECT SUM(paid_amount) FROM orders_current GROUP BY paid_amount + 1",
        ))
        self.assertEqual(result.status, "unsupported")

    def test_union_is_unsupported(self):
        result = understand_grain(*inputs(
            "SELECT region FROM orders_current UNION SELECT region FROM orders_history",
        ))
        self.assertEqual(result.status, "unsupported")

    def test_cte_join_and_subquery_are_unsupported(self):
        cases = [
            "WITH x AS (SELECT region FROM orders_current) SELECT region FROM x GROUP BY region",
            "SELECT o.region FROM orders_current o JOIN customers c ON o.customer_id=c.customer_id GROUP BY o.region",
            "SELECT region FROM (SELECT region FROM orders_current) x GROUP BY region",
        ]
        for sql in cases:
            with self.subTest(sql=sql):
                self.assertEqual(understand_grain(*inputs(sql)).status, "unsupported")

    def test_grouping_ordinals_and_select_aliases_are_not_guessed(self):
        for group in ("1", "r"):
            with self.subTest(group=group):
                result = understand_grain(*inputs(
                    "SELECT region AS r, SUM(paid_amount) FROM orders_current GROUP BY " + group,
                ))
                self.assertEqual(result.status, "unsupported")

    def test_hidden_grouping_key_is_unknown_not_global(self):
        result = understand_grain(*inputs("SELECT SUM(paid_amount) FROM orders_current GROUP BY region"))
        self.assertEqual(result.query_grain, "grouped")
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.grouping_expressions, ["region"])
        self.assertIsNone(result.grouping_columns)
        self.assertTrue(result.limitations)

    def test_schema_dimension_role_cannot_create_a_grain(self):
        statement, semantics = inputs("SELECT region FROM orders_current")
        self.assertEqual(semantics[0].schema_bindings[0].role, "dimension")
        result = understand_grain(statement, semantics)
        self.assertEqual(result.status, "unknown")
        self.assertIsNone(result.query_grain)
        self.assertIsNone(result.business_grain)

    def test_output_name_is_not_a_source_or_grouping_key(self):
        statement, semantics = inputs("SELECT region, SUM(paid_amount) FROM orders_current GROUP BY region")
        semantics[0] = semantics[0].model_copy(update={"output_name": "customer_id"})
        result = understand_grain(statement, semantics)
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.grouping_columns, [source()])

    def test_missing_schema_binding_does_not_erase_query_grain(self):
        result = understand_grain(*inputs("SELECT region FROM orders_current GROUP BY region", bound=False))
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.grouping_columns, [source()])
        self.assertIsNone(result.business_grain)

    def test_schema_role_is_not_a_replacement_for_label(self):
        statement, semantics = inputs("SELECT region FROM orders_current GROUP BY region")
        semantics[0] = semantics[0].model_copy(update={"schema_bindings": [SchemaBinding(source=source(), role="dimension")]})
        result = understand_grain(statement, semantics)
        self.assertEqual(result.status, "resolved")
        self.assertIsNone(result.business_grain)

    def test_schema_binding_must_match_exact_source(self):
        for mismatched in (source(table="customers"), source(database="another_database"), source("customer_id")):
            with self.subTest(mismatched=mismatched):
                statement, semantics = inputs("SELECT region FROM orders_current GROUP BY region")
                semantics[0] = semantics[0].model_copy(update={
                    "schema_bindings": [SchemaBinding(source=mismatched, label="wrong label")],
                })
                result = understand_grain(statement, semantics)
                self.assertEqual(result.status, "resolved")
                self.assertIsNone(result.business_grain)

    def test_conflicting_schema_labels_are_not_selected(self):
        statement, semantics = inputs("SELECT region FROM orders_current GROUP BY region")
        semantics[0] = semantics[0].model_copy(update={"schema_bindings": [
            SchemaBinding(source=source(), label="first"),
            SchemaBinding(source=source(), label="second"),
        ]})
        result = understand_grain(statement, semantics)
        self.assertEqual(result.status, "resolved")
        self.assertIsNone(result.business_grain)

    def test_grouping_field_names_respect_table_identity(self):
        orders = understand_grain(*inputs("SELECT region FROM orders_current GROUP BY region"))
        customers = understand_grain(*inputs("SELECT region FROM customers GROUP BY region"))
        self.assertEqual(orders.business_grain, ["销售地区"])
        self.assertEqual(customers.business_grain, ["客户地区"])

    def test_projection_count_mismatch_returns_unknown(self):
        statement, semantics = inputs("SELECT region, SUM(paid_amount) FROM orders_current GROUP BY region")
        result = understand_grain(statement, semantics[:1])
        self.assertEqual(result.status, "unknown")

    def test_column_ordinal_and_identity_mismatch_return_unknown(self):
        for replacement in ({"ordinal": 1}, {"column_id": "column_1"}):
            with self.subTest(replacement=replacement):
                statement, semantics = inputs("SELECT region, SUM(paid_amount) FROM orders_current GROUP BY region")
                semantics[0] = semantics[0].model_copy(update=replacement)
                self.assertEqual(understand_grain(statement, semantics).status, "unknown")

    def test_projection_expression_mismatch_returns_unknown(self):
        statement, semantics = inputs("SELECT region FROM orders_current GROUP BY region")
        semantics[0] = semantics[0].model_copy(update={"expression": "customer_id"})
        self.assertEqual(understand_grain(statement, semantics).status, "unknown")

    def test_lineage_table_or_field_mismatch_returns_unknown(self):
        for wrong in (source("customer_id"), source(table="customers")):
            with self.subTest(wrong=wrong):
                statement, semantics = inputs("SELECT region FROM orders_current GROUP BY region")
                semantics[0] = semantics[0].model_copy(update={"lineage": [wrong]})
                self.assertEqual(understand_grain(statement, semantics).status, "unknown")

    def test_unknown_lineage_is_not_promoted(self):
        statement, semantics = inputs("SELECT region FROM orders_current GROUP BY region", database=None)
        result = understand_grain(statement, semantics)
        self.assertEqual(result.status, "unknown")
        self.assertIsNone(result.business_grain)

    def test_unsupported_column_semantics_are_not_promoted(self):
        statement, semantics = inputs("SELECT region FROM orders_current GROUP BY region")
        semantics[0] = semantics[0].model_copy(update={"status": "unsupported", "reason": "prior stage unsupported"})
        self.assertNotEqual(understand_grain(statement, semantics).status, "resolved")

    def test_complex_global_aggregate_is_unsupported(self):
        for expression in ("ROUND(SUM(paid_amount), 2)", "SUM(DISTINCT paid_amount)", "SUM(paid_amount + 1)"):
            with self.subTest(expression=expression):
                self.assertEqual(understand_grain(*inputs(f"SELECT {expression} FROM orders_current")).status, "unsupported")

    def test_non_grouped_field_with_aggregate_is_not_validated_as_global(self):
        result = understand_grain(*inputs("SELECT region, SUM(paid_amount) FROM orders_current"))
        self.assertNotEqual(result.status, "resolved")

    def test_already_parsed_select_is_accepted_without_reparsing(self):
        sql = "SELECT region, SUM(paid_amount) FROM orders_current GROUP BY region"
        parsed = parse_sql(sql)
        _, semantics = inputs(sql)
        with patch("sqlglot.parse", side_effect=AssertionError("must not parse")), \
             patch("sqlglot.parse_one", side_effect=AssertionError("must not parse")), \
             patch("app.querying.result_understanding.sql_parser.parse_sql", side_effect=AssertionError("must not parse")):
            result = understand_grain(parsed, semantics)
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.grouping_columns, [source()])

    def test_raw_ast_does_not_trigger_any_parser_call(self):
        statement, semantics = inputs("SELECT COUNT(*) FROM orders_current")
        with patch("sqlglot.parse", side_effect=AssertionError("must not parse")), \
             patch("sqlglot.parse_one", side_effect=AssertionError("must not parse")), \
             patch("app.querying.result_understanding.sql_parser.parse_sql", side_effect=AssertionError("must not parse")):
            result = understand_grain(statement, semantics)
        self.assertEqual(result.status, "resolved")

    def test_old_four_argument_parsed_select_cannot_invent_absent_grouping(self):
        sql = "SELECT region FROM orders_current GROUP BY region"
        parsed = parse_sql(sql)
        old = ParsedSelect(parsed.projections, parsed.aliases, parsed.table, parsed.qualifier)
        _, semantics = inputs(sql)
        result = understand_grain(old, semantics)
        self.assertEqual(result.status, "unknown")
        self.assertIsNone(result.query_grain)

    def test_ast_semantics_and_bindings_are_not_modified(self):
        statement, semantics = inputs("SELECT region, SUM(paid_amount) FROM orders_current GROUP BY region")
        before_statement = copy.deepcopy(statement.dump())
        before_semantics = [item.model_dump() for item in semantics]
        result = understand_grain(statement, semantics)
        self.assertEqual(statement.dump(), before_statement)
        self.assertEqual([item.model_dump() for item in semantics], before_semantics)
        self.assertIsNot(result.grouping_columns, semantics[0].lineage)
        result.grouping_columns.clear()
        result.grouping_expressions.clear()
        result.business_grain.clear()
        self.assertEqual(statement.dump(), before_statement)
        self.assertEqual([item.model_dump() for item in semantics], before_semantics)

    def test_ascii_case_insensitive_table_alias_and_field(self):
        statement, semantics = inputs(
            "SELECT O.Region FROM Orders_Current o GROUP BY o.region",
        )
        result = understand_grain(statement, semantics)
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.business_grain, ["销售地区"])


if __name__ == "__main__":
    unittest.main()
