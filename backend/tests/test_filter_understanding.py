"""Deterministic filter semantics from caller-owned AST and source evidence."""

import copy
import unittest
from unittest.mock import patch

import sqlglot
from sqlglot import exp

from app.database import SCHEMA
from app.querying.result_contract import ColumnMetadata, ExecutionData, ResultContract
from app.querying.result_understanding.filter import understand_filters
from app.querying.result_understanding.lineage import understand_columns
from app.querying.result_understanding.models import LineageSource, SchemaBinding
from app.querying.result_understanding.schema_binding import bind_schema
from app.querying.result_understanding.sql_parser import ParsedSelect, parse_sql


def inputs(sql, *, bound=True, database="askdata_mock"):
    """Parsing is allowed in setup, never inside understand_filters()."""
    statement = sqlglot.parse_one(sql, read="duckdb")
    projections = statement.expressions if isinstance(statement, exp.Select) else [None]
    contract = ResultContract(
        result_id="filter-test-result",
        execution=ExecutionData(
            database=database, sql=sql, success=True,
            columns=[
                ColumnMetadata(id=f"column_{index}", ordinal=index, name=f"display_{index}")
                for index, _ in enumerate(projections)
            ],
        ),
    )
    columns = understand_columns(contract)
    if bound:
        columns = [bind_schema(column, SCHEMA) for column in columns]
    return statement, columns


def source(field="region", table="orders_current", database="askdata_mock"):
    return LineageSource(database=database, table=table, field=field)


def binding(field="region", table="orders_current", database="askdata_mock", **metadata):
    return SchemaBinding(source=source(field, table, database), **metadata)


class FilterUnderstandingTest(unittest.TestCase):
    def test_where_region_uses_lineage_then_schema_metadata(self):
        result = understand_filters(*inputs(
            "SELECT o.region FROM orders_current o WHERE o.region='华北'",
        ))
        self.assertEqual(result.status, "resolved")
        self.assertEqual(len(result.filters), 1)
        condition = result.filters[0]
        self.assertEqual(condition.scope, "WHERE")
        self.assertEqual(condition.operator, "=")
        self.assertEqual(condition.lineage, [source()])
        self.assertEqual(condition.value, "华北")
        self.assertEqual(condition.value_type, "string")
        self.assertEqual(condition.value_sql, "'华北'")
        self.assertEqual(condition.schema_bindings[0].label, "销售地区")
        self.assertIsNone(condition.aggregation_expression)
        self.assertTrue(result.where_expression)
        self.assertIsNone(result.having_expression)

    def test_and_conditions_preserve_order_and_scope(self):
        statement, columns = inputs(
            "SELECT region FROM orders_current WHERE status='paid' AND region='华北'",
        )
        status_binding = binding("status", label="订单状态", role="dimension")
        result = understand_filters(statement, columns, [status_binding])
        self.assertEqual(result.status, "resolved")
        self.assertEqual([item.value for item in result.filters], ["paid", "华北"])
        self.assertEqual([item.scope for item in result.filters], ["WHERE", "WHERE"])
        self.assertEqual(result.filters[0].lineage, [source("status")])
        self.assertEqual(result.filters[0].schema_bindings[0].label, "订单状态")

    def test_having_sum_records_actual_aggregate_expression(self):
        result = understand_filters(*inputs(
            "SELECT SUM(paid_amount) AS sales_amount FROM orders_current "
            "HAVING SUM(paid_amount)>100",
        ))
        condition = result.filters[0]
        self.assertEqual(result.status, "resolved")
        self.assertEqual(condition.scope, "HAVING")
        self.assertEqual(condition.aggregation_expression, "SUM(paid_amount)")
        self.assertEqual(condition.lineage, [source("paid_amount")])
        self.assertEqual(condition.operator, ">")
        self.assertEqual(condition.value, 100)
        self.assertIs(type(condition.value), int)
        self.assertEqual(condition.value_type, "integer")

    def test_having_avg_not_schema_default_sum(self):
        result = understand_filters(*inputs(
            "SELECT AVG(paid_amount) FROM orders_current HAVING AVG(paid_amount)>100",
        ))
        condition = result.filters[0]
        self.assertEqual(condition.aggregation_expression, "AVG(paid_amount)")
        self.assertEqual(condition.schema_bindings[0].default_aggregation, "sum")

    def test_having_count_star_preserves_table_level_source(self):
        result = understand_filters(*inputs(
            "SELECT COUNT(*) FROM orders_current HAVING COUNT(*)>=2",
        ))
        condition = result.filters[0]
        self.assertEqual(result.status, "resolved")
        self.assertEqual(condition.aggregation_expression, "COUNT(*)")
        self.assertEqual(condition.lineage, [source(None)])
        self.assertEqual(condition.schema_bindings, [])

    def test_where_and_having_remain_distinct(self):
        result = understand_filters(*inputs(
            "SELECT region, SUM(paid_amount) FROM orders_current "
            "WHERE region='华北' GROUP BY region HAVING SUM(paid_amount)>100",
        ))
        self.assertEqual(result.status, "resolved")
        self.assertEqual([item.scope for item in result.filters], ["WHERE", "HAVING"])
        self.assertTrue(result.where_expression)
        self.assertTrue(result.having_expression)
        self.assertEqual(result.excluded_scopes, [])

    def test_date_literal_is_recorded_without_time_understanding(self):
        result = understand_filters(*inputs(
            "SELECT order_date FROM orders_current WHERE order_date>=DATE '2026-09-01'",
        ))
        condition = result.filters[0]
        self.assertEqual(condition.status, "resolved")
        self.assertEqual(condition.value, "2026-09-01")
        self.assertEqual(condition.value_type, "date_literal")
        self.assertEqual(condition.lineage, [source("order_date")])
        self.assertNotIn("time_range", result.model_dump())

    def test_timestamp_literal_is_not_evaluated(self):
        result = understand_filters(*inputs(
            "SELECT order_date FROM orders_current "
            "WHERE order_date<TIMESTAMP '2026-09-02 12:34:56.123456'",
        ))
        condition = result.filters[0]
        self.assertEqual(condition.value_type, "timestamp_literal")
        self.assertEqual(condition.value, "2026-09-02 12:34:56.123456")

    def test_string_date_stays_string(self):
        result = understand_filters(*inputs(
            "SELECT order_date FROM orders_current WHERE order_date>='2026-09-01'",
        ))
        self.assertEqual(result.filters[0].value_type, "string")

    def test_comparison_operators_are_supported(self):
        for operator in ("=", "!=", ">", ">=", "<", "<="):
            with self.subTest(operator=operator):
                result = understand_filters(*inputs(
                    f"SELECT paid_amount FROM orders_current WHERE paid_amount{operator}100",
                ))
                self.assertEqual(result.status, "resolved")
                self.assertEqual(result.filters[0].operator, operator)

    def test_nested_and_parentheses_do_not_change_conjunction(self):
        result = understand_filters(*inputs(
            "SELECT region, paid_amount FROM orders_current "
            "WHERE (region='华北' AND (paid_amount>100 AND paid_amount<200))",
        ))
        self.assertEqual(result.status, "resolved")
        self.assertEqual([item.value for item in result.filters], ["华北", 100, 200])

    def test_or_entire_scope_is_unsupported_not_flattened(self):
        result = understand_filters(*inputs(
            "SELECT region, paid_amount FROM orders_current "
            "WHERE paid_amount>100 AND (region='华北' OR region='华东')",
        ))
        self.assertEqual(result.status, "unsupported")
        self.assertEqual(len(result.filters), 1)
        self.assertEqual(result.filters[0].status, "unsupported")
        self.assertIn("OR", result.filters[0].expression)
        self.assertTrue(result.filters[0].limitations)

    def test_not_entire_scope_is_unsupported(self):
        result = understand_filters(*inputs(
            "SELECT region FROM orders_current WHERE NOT region='华北'",
        ))
        self.assertEqual(result.status, "unsupported")
        self.assertEqual(result.filters[0].status, "unsupported")

    def test_subquery_and_exists_are_unsupported(self):
        predicates = [
            "paid_amount>(SELECT AVG(paid_amount) FROM orders_history)",
            "EXISTS(SELECT 1 FROM orders_history)",
            "region IN (SELECT region FROM orders_history)",
        ]
        for predicate in predicates:
            with self.subTest(predicate=predicate):
                result = understand_filters(*inputs(
                    "SELECT region, paid_amount FROM orders_current WHERE " + predicate,
                ))
                self.assertEqual(result.status, "unsupported")
                self.assertTrue(result.limitations)

    def test_window_and_qualify_are_not_where_filters(self):
        result = understand_filters(*inputs(
            "SELECT region FROM orders_current "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY region)=1",
        ))
        self.assertEqual(result.status, "unsupported")
        self.assertEqual(result.filters, [])
        self.assertEqual([item.scope for item in result.excluded_scopes], ["QUALIFY"])
        self.assertEqual(result.excluded_scopes[0].status, "unsupported")

    def test_join_on_is_retained_separately_never_where(self):
        result = understand_filters(*inputs(
            "SELECT o.region FROM orders_current o LEFT JOIN customers c "
            "ON o.customer_id=c.customer_id WHERE o.region='华北'",
        ))
        self.assertEqual(result.status, "unsupported")
        self.assertEqual([item.scope for item in result.excluded_scopes], ["JOIN ON"])
        self.assertIn("customer_id", result.excluded_scopes[0].expression)
        self.assertTrue(all(item.scope == "WHERE" for item in result.filters))

    def test_complex_function_and_other_predicates_are_unsupported(self):
        for predicate in (
            "LOWER(region)='华北'", "paid_amount>order_amount", "100<paid_amount",
            "region IN ('华北','华东')",
            "region IS NULL", "order_date>=CURRENT_DATE", "paid_amount+1>100",
        ):
            with self.subTest(predicate=predicate):
                result = understand_filters(*inputs(
                    "SELECT region, paid_amount, order_date FROM orders_current WHERE " + predicate,
                ))
                self.assertEqual(result.status, "unsupported")

    def test_between_retains_both_literals_without_evaluating_them(self):
        result = understand_filters(*inputs(
            "SELECT paid_amount FROM orders_current WHERE paid_amount BETWEEN 1.20 AND 2.30",
        ))
        condition = result.filters[0]
        self.assertEqual(result.status, "resolved")
        self.assertEqual(condition.operator, "BETWEEN")
        self.assertEqual(condition.lineage, [source("paid_amount")])
        self.assertEqual(condition.lower_bound.value, "1.20")
        self.assertEqual(condition.upper_bound.value, "2.30")
        self.assertEqual(condition.lower_bound.value_type, "numeric_text")
        self.assertIsNone(condition.value)

    def test_aggregate_modifiers_and_wrappers_are_unsupported(self):
        for condition in (
            "SUM(DISTINCT paid_amount)>100", "ROUND(SUM(paid_amount),2)>100",
            "SUM(paid_amount+1)>100",
        ):
            with self.subTest(condition=condition):
                result = understand_filters(*inputs(
                    "SELECT SUM(paid_amount) FROM orders_current HAVING " + condition,
                ))
                self.assertEqual(result.status, "unsupported")

    def test_aggregate_local_filter_without_root_where_is_unsupported(self):
        result = understand_filters(*inputs(
            "SELECT SUM(paid_amount) FILTER (WHERE status='paid') FROM orders_current",
        ))
        self.assertEqual(result.status, "unsupported")
        self.assertIsNone(result.where_expression)
        self.assertEqual(result.filters, [])
        self.assertTrue(any("status" in message and "paid" in message for message in result.limitations))

    def test_aggregate_local_filter_is_not_promoted_to_root_where(self):
        result = understand_filters(*inputs(
            "SELECT region, SUM(paid_amount) FILTER (WHERE status='paid') "
            "FROM orders_current WHERE region='华北' GROUP BY region",
        ))
        self.assertEqual(result.status, "unsupported")
        self.assertEqual(result.where_expression, "region = '华北'")
        self.assertEqual(len(result.filters), 1)
        self.assertEqual(result.filters[0].scope, "WHERE")
        self.assertEqual(result.filters[0].expression, "region = '华北'")
        self.assertNotIn("status", result.filters[0].expression)
        self.assertTrue(any("status" in message and "paid" in message for message in result.limitations))

    def test_cte_and_union_are_unsupported(self):
        for sql in (
            "WITH x AS (SELECT region FROM orders_current) SELECT region FROM x WHERE region='华北'",
            "SELECT region FROM orders_current WHERE region='华北' UNION SELECT region FROM orders_history",
        ):
            with self.subTest(sql=sql):
                self.assertEqual(understand_filters(*inputs(sql)).status, "unsupported")

    def test_unknown_predicate_only_field_does_not_invent_binding(self):
        result = understand_filters(*inputs(
            "SELECT region FROM orders_current WHERE mystery_field='paid'",
        ))
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.filters[0].status, "unknown")
        self.assertEqual(result.filters[0].schema_bindings, [])
        self.assertTrue(result.filters[0].limitations)

    def test_binding_for_other_source_does_not_establish_unknown_field(self):
        statement, columns = inputs("SELECT region FROM orders_current WHERE status='paid'")
        for other in (binding("status", table="customers"), binding("status", database="another_database")):
            with self.subTest(other=other):
                result = understand_filters(statement, columns, [other])
                self.assertEqual(result.status, "unknown")
                self.assertEqual(result.filters[0].schema_bindings, [])

    def test_same_field_name_binding_respects_source_table(self):
        orders = understand_filters(*inputs("SELECT region FROM orders_current WHERE region='华北'"))
        customers = understand_filters(*inputs("SELECT region FROM customers WHERE region='华北'"))
        self.assertEqual(orders.filters[0].schema_bindings[0].label, "销售地区")
        self.assertEqual(customers.filters[0].schema_bindings[0].label, "客户地区")

    def test_output_name_is_not_used_to_find_source(self):
        statement, columns = inputs("SELECT region AS r FROM orders_current WHERE region='华北'")
        columns[0] = columns[0].model_copy(update={"output_name": "paid_amount"})
        result = understand_filters(statement, columns)
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.filters[0].lineage, [source()])

    def test_select_alias_is_not_guessed_as_base_field(self):
        for sql in (
            "SELECT region AS r FROM orders_current WHERE r='华北'",
            "SELECT SUM(paid_amount) AS sales_amount FROM orders_current HAVING sales_amount>100",
        ):
            with self.subTest(sql=sql):
                self.assertEqual(understand_filters(*inputs(sql)).status, "unsupported")

    def test_schema_alias_does_not_establish_source(self):
        statement, columns = inputs("SELECT region FROM orders_current WHERE sales_amount>100")
        result = understand_filters(statement, columns, [
            binding("paid_amount", label="销售额", aliases=["sales_amount"]),
        ])
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.filters[0].schema_bindings, [])

    def test_missing_database_is_not_inferred_from_binding(self):
        statement, columns = inputs("SELECT region FROM orders_current WHERE region='华北'", database=None)
        result = understand_filters(statement, columns, [binding(label="销售地区")])
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.filters[0].schema_bindings, [])

    def test_projection_expression_or_count_mismatch_is_unknown(self):
        statement, columns = inputs("SELECT region FROM orders_current WHERE region='华北'")
        for changed in ([], [columns[0].model_copy(update={"expression": "customer_id"})]):
            with self.subTest(changed=changed):
                self.assertEqual(understand_filters(statement, changed).status, "unknown")

    def test_lineage_wrong_table_or_field_cannot_bind(self):
        statement, columns = inputs("SELECT region FROM orders_current WHERE region='华北'")
        for wrong in (source(table="customers"), source("customer_id")):
            with self.subTest(wrong=wrong):
                changed = [columns[0].model_copy(update={"lineage": [wrong]})]
                result = understand_filters(statement, changed)
                self.assertEqual(result.status, "unknown")
                self.assertEqual(result.filters[0].schema_bindings, [])

    def test_unresolved_projection_evidence_is_not_promoted(self):
        statement, columns = inputs("SELECT region FROM orders_current WHERE region='华北'")
        for status in ("unknown", "unsupported"):
            with self.subTest(status=status):
                changed = [columns[0].model_copy(update={"status": status})]
                self.assertNotEqual(understand_filters(statement, changed).status, "resolved")

    def test_conflicting_binding_metadata_is_not_selected(self):
        statement, columns = inputs("SELECT region FROM orders_current WHERE region='华北'", bound=False)
        result = understand_filters(statement, columns, [binding(label="first"), binding(label="second")])
        self.assertEqual(result.filters[0].status, "resolved")
        self.assertEqual(result.filters[0].schema_bindings, [])
        self.assertTrue(result.filters[0].limitations)

    def test_numeric_literals_do_not_use_float_codec(self):
        for sql_value in ("123456789012345678.12", "1.234567890123456789e-20", "-123.4500"):
            with self.subTest(sql_value=sql_value):
                statement, columns = inputs(
                    "SELECT paid_amount FROM orders_current WHERE paid_amount>" + sql_value,
                )
                result = understand_filters(statement, columns)
                condition = result.filters[0]
                self.assertEqual(condition.status, "resolved")
                self.assertEqual(condition.value_type, "numeric_text")
                self.assertIs(type(condition.value), str)
                self.assertEqual(condition.value, statement.args["where"].this.expression.sql(dialect="duckdb"))

    def test_negative_integer_and_boolean_keep_distinct_types(self):
        for literal, value, value_type in (("-2", -2, "integer"), ("TRUE", True, "boolean"), ("FALSE", False, "boolean")):
            with self.subTest(literal=literal):
                result = understand_filters(*inputs(
                    "SELECT paid_amount FROM orders_current WHERE paid_amount=" + literal,
                ))
                self.assertEqual(result.filters[0].value, value)
                self.assertIs(type(result.filters[0].value), type(value))
                self.assertEqual(result.filters[0].value_type, value_type)

    def test_null_literal_is_not_rewritten_as_is_null(self):
        result = understand_filters(*inputs("SELECT region FROM orders_current WHERE region=NULL"))
        condition = result.filters[0]
        self.assertEqual(condition.operator, "=")
        self.assertIsNone(condition.value)
        self.assertEqual(condition.value_type, "null")
        self.assertEqual(condition.value_sql, "NULL")

    def test_no_filter_is_known_empty_not_unknown(self):
        result = understand_filters(*inputs("SELECT region FROM orders_current"))
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.filters, [])
        self.assertEqual(result.excluded_scopes, [])
        self.assertIsNone(result.where_expression)
        self.assertIsNone(result.having_expression)

    def test_already_parsed_input_does_not_reparse(self):
        sql = "SELECT region FROM orders_current WHERE region='华北'"
        parsed = parse_sql(sql)
        _, columns = inputs(sql)
        with patch("sqlglot.parse", side_effect=AssertionError("must not parse")), \
             patch("sqlglot.parse_one", side_effect=AssertionError("must not parse")), \
             patch("app.querying.result_understanding.sql_parser.parse_sql", side_effect=AssertionError("must not parse")):
            result = understand_filters(parsed, columns)
        self.assertEqual(result.status, "resolved")

    def test_raw_ast_does_not_reparse(self):
        statement, columns = inputs("SELECT region FROM orders_current WHERE region='华北'")
        with patch("sqlglot.parse", side_effect=AssertionError("must not parse")), \
             patch("sqlglot.parse_one", side_effect=AssertionError("must not parse")), \
             patch("app.querying.result_understanding.sql_parser.parse_sql", side_effect=AssertionError("must not parse")):
            result = understand_filters(statement, columns)
        self.assertEqual(result.status, "resolved")

    def test_legacy_parsed_select_without_root_has_unknown_filters(self):
        sql = "SELECT region FROM orders_current WHERE region='华北'"
        parsed = parse_sql(sql)
        old = ParsedSelect(parsed.projections, parsed.aliases, parsed.table, parsed.qualifier)
        _, columns = inputs(sql)
        self.assertEqual(understand_filters(old, columns).status, "unknown")

    def test_inputs_and_nested_metadata_are_not_modified(self):
        statement, columns = inputs("SELECT region FROM orders_current WHERE region='华北' AND status='paid'")
        supplied = [binding("status", label="订单状态", aliases=["状态"], description="状态说明")]
        before_ast = copy.deepcopy(statement.dump())
        before_columns = [item.model_dump() for item in columns]
        before_bindings = [item.model_dump() for item in supplied]
        result = understand_filters(statement, columns, supplied)
        self.assertEqual(result.status, "resolved")
        result.filters[0].lineage.clear()
        result.filters[0].schema_bindings.clear()
        result.filters[1].schema_bindings[0].aliases.clear()
        result.filters.clear()
        self.assertEqual(statement.dump(), before_ast)
        self.assertEqual([item.model_dump() for item in columns], before_columns)
        self.assertEqual([item.model_dump() for item in supplied], before_bindings)

    def test_ascii_case_matching_does_not_change_source_identity(self):
        result = understand_filters(*inputs("SELECT O.Region FROM Orders_Current o WHERE o.region='华北'"))
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.filters[0].schema_bindings[0].label, "销售地区")


if __name__ == "__main__":
    unittest.main()
