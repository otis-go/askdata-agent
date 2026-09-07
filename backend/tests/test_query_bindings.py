"""Public query-binding preparation closes hidden predicate metadata inputs.

Positive integration cases intentionally never hand-build extra SchemaBinding
objects: all predicate bindings must come from prepare_query_bindings().
"""

import copy
import unittest
from unittest.mock import patch

import sqlglot

from app.database import SCHEMA
from app.querying.result_contract import ColumnMetadata, ExecutionData, ResultContract
from app.querying.result_understanding.filter import understand_filters
from app.querying.result_understanding.grain import understand_grain
from app.querying.result_understanding.lineage import understand_columns
from app.querying.result_understanding.schema_binding import bind_schema, prepare_query_bindings
from app.querying.result_understanding.sql_parser import ParsedSelect, parse_sql
from app.querying.result_understanding.time_constraint import understand_time_constraints


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


def contract_for(sql, parsed, database="askdata_mock"):
    return ResultContract(
        result_id="query-bindings-test-result",
        execution=ExecutionData(
            database=database, sql=sql, success=True,
            columns=[
                ColumnMetadata(id=f"column_{index}", ordinal=index, name=alias or f"output_{index}")
                for index, alias in enumerate(parsed.aliases)
            ],
        ),
    )


def pipeline(sql, schema=SCHEMA):
    """Exercise only public interfaces, with no hidden-field test adapters."""
    parsed = parse_sql(sql)
    contract = contract_for(sql, parsed)
    columns = understand_columns(contract)
    bound = [bind_schema(column, schema) for column in columns]
    prepared = prepare_query_bindings(parsed, contract.execution.database, schema)
    filters = understand_filters(parsed, bound, prepared.bindings)
    times = understand_time_constraints(filters, bound, prepared.bindings)
    return parsed, contract, columns, bound, prepared, filters, times


def identities(prepared):
    return [(binding.source.database, binding.source.table, binding.source.field) for binding in prepared.bindings]


class QueryBindingsTest(unittest.TestCase):
    def prepare(self, sql, *, database="askdata_mock", schema=SCHEMA):
        return prepare_query_bindings(parse_sql(sql), database, schema)

    def test_hidden_status_binding_closes_public_filter_input(self):
        _, _, columns, _, prepared, filters, _ = pipeline(
            "SELECT region FROM orders_current WHERE status='paid'",
        )
        self.assertEqual(prepared.status, "resolved")
        self.assertEqual(len(columns), 1)
        self.assertEqual(filters.status, "resolved")
        self.assertEqual(filters.filters[0].lineage[0].field, "status")
        binding = filters.filters[0].schema_bindings[0]
        self.assertEqual(binding.label, "订单状态")
        self.assertEqual(binding.role, "filter")

    def test_fixed_query_public_lifecycle_has_four_scoped_filters_and_time(self):
        parsed, _, _, bound, prepared, filters, times = pipeline(FULL_SQL)
        self.assertEqual(prepared.status, "resolved")
        self.assertEqual(filters.status, "resolved")
        self.assertEqual([item.scope for item in filters.filters], ["WHERE", "WHERE", "WHERE", "HAVING"])
        self.assertEqual(len(filters.filters), 4)
        self.assertEqual(filters.filters[-1].aggregation_expression, "SUM(o.paid_amount)")
        self.assertEqual(filters.excluded_scopes, [])
        self.assertEqual(len(times), 1)
        time = times[0]
        self.assertEqual(time.status, "resolved")
        self.assertEqual(time.source_field.table, "orders_current")
        self.assertEqual(time.source_field.field, "order_date")
        self.assertEqual((time.lower, time.upper), ("2026-08-01", "2026-09-01"))
        self.assertEqual((time.inclusive.lower, time.inclusive.upper), (True, False))
        self.assertEqual(time.scope, "WHERE")
        grain = understand_grain(parsed, bound)
        self.assertEqual(grain.query_grain, "grouped")
        self.assertEqual(grain.business_grain, ["销售地区"])

    def test_preparation_does_not_turn_hidden_fields_into_output_columns(self):
        _, contract, columns, bound, prepared, _, _ = pipeline(FULL_SQL)
        self.assertEqual([column.column_id for column in columns], ["column_0", "column_1"])
        self.assertEqual([column.lineage[0].field for column in columns], ["region", "paid_amount"])
        self.assertEqual(len(contract.execution.columns), 2)
        self.assertEqual(len(bound), 2)
        self.assertEqual([item.source.field for item in prepared.bindings], ["region", "paid_amount", "status", "order_date"])

    def test_same_named_fields_are_bound_to_the_actual_table(self):
        orders = self.prepare("SELECT region FROM orders_current")
        customers = self.prepare("SELECT region FROM customers")
        self.assertEqual(orders.status, "resolved")
        self.assertEqual(customers.status, "resolved")
        self.assertEqual(orders.bindings[0].source.table, "orders_current")
        self.assertEqual(customers.bindings[0].source.table, "customers")
        self.assertEqual(orders.bindings[0].label, "销售地区")
        self.assertEqual(customers.bindings[0].label, "客户地区")

    def test_table_alias_ascii_case_and_first_source_spelling_are_preserved(self):
        result = self.prepare(
            "SELECT O.REGION, SUM(O.PAID_AMOUNT) AS sales_amount "
            "FROM ORDERS_CURRENT O WHERE o.STATUS='paid' GROUP BY o.region",
        )
        self.assertEqual(result.status, "resolved")
        self.assertEqual(identities(result), [
            ("askdata_mock", "ORDERS_CURRENT", "REGION"),
            ("askdata_mock", "ORDERS_CURRENT", "PAID_AMOUNT"),
            ("askdata_mock", "ORDERS_CURRENT", "STATUS"),
        ])

    def test_nonexistent_field_is_unknown_and_returns_no_partial_bindings(self):
        result = self.prepare("SELECT region FROM orders_current WHERE missing_field=1")
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.bindings, [])
        self.assertTrue(result.limitations)

    def test_unsupported_syntax_is_not_bypassed_by_schema(self):
        statements = (
            "SELECT region FROM orders_current WHERE region='a' OR region='b'",
            "SELECT region FROM orders_current WHERE NOT region='a'",
            "SELECT region FROM orders_current WHERE LOWER(region)='a'",
            "SELECT LOWER(region) FROM orders_current",
            "SELECT region FROM orders_current WHERE paid_amount>(SELECT AVG(paid_amount) FROM orders_history)",
            "SELECT region FROM orders_current WHERE EXISTS (SELECT 1 FROM orders_history)",
            "SELECT o.region FROM orders_current o JOIN customers c ON o.customer_id=c.customer_id",
            "WITH source AS (SELECT region FROM orders_current) SELECT region FROM source",
            "SELECT region FROM orders_current UNION ALL SELECT region FROM customers",
            "SELECT region, SUM(paid_amount) OVER (PARTITION BY region) FROM orders_current",
            "SELECT region FROM orders_current QUALIFY region='a'",
            "SELECT region, SUM(paid_amount) FROM orders_current GROUP BY DATE_TRUNC('month',order_date),region",
            "SELECT region AS r, SUM(paid_amount) FROM orders_current GROUP BY r",
            "SELECT region,SUM(paid_amount) FROM orders_current GROUP BY 1",
            "SELECT SUM(paid_amount) FILTER (WHERE status='paid') FROM orders_current",
        )
        for sql in statements:
            with self.subTest(sql=sql):
                # Unsupported roots cannot always pass parse_sql; this is only
                # test setup, never an alternative implementation parser.
                statement = sqlglot.parse_one(sql, read="duckdb")
                result = prepare_query_bindings(statement, "askdata_mock", SCHEMA)
                self.assertEqual(result.status, "unsupported")
                self.assertEqual(result.bindings, [])
                self.assertTrue(result.limitations)

    def test_inputs_and_nested_schema_metadata_are_not_mutated(self):
        schema = copy.deepcopy(SCHEMA)
        parsed = parse_sql(FULL_SQL)
        contract = contract_for(FULL_SQL, parsed)
        columns = [bind_schema(column, schema) for column in understand_columns(contract)]
        before = copy.deepcopy((parsed.statement.dump(), schema, contract.model_dump(), [c.model_dump() for c in columns]))
        first = prepare_query_bindings(parsed, contract.execution.database, schema)
        second = prepare_query_bindings(parsed, contract.execution.database, schema)
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        first.bindings[0].aliases.clear()
        first.bindings.clear()
        first.limitations.append("test-owned mutation")
        self.assertTrue(second.bindings[0].aliases)
        after = (parsed.statement.dump(), schema, contract.model_dump(), [c.model_dump() for c in columns])
        self.assertEqual(after, before)

    def test_unprojected_having_aggregate_source_is_prepared(self):
        _, _, columns, _, prepared, filters, _ = pipeline(
            "SELECT region FROM orders_current GROUP BY region HAVING SUM(paid_amount)>100",
        )
        self.assertEqual(len(columns), 1)
        self.assertEqual(prepared.status, "resolved")
        self.assertEqual([binding.source.field for binding in prepared.bindings], ["region", "paid_amount"])
        self.assertEqual(filters.status, "resolved")
        self.assertEqual(filters.filters[0].scope, "HAVING")
        self.assertEqual(filters.filters[0].aggregation_expression, "SUM(paid_amount)")

    def test_unprojected_group_by_field_is_prepared_not_added_to_columns(self):
        _, _, columns, _, prepared, _, _ = pipeline(
            "SELECT SUM(paid_amount) FROM orders_current GROUP BY region",
        )
        self.assertEqual(len(columns), 1)
        self.assertEqual(prepared.status, "resolved")
        self.assertEqual([binding.source.field for binding in prepared.bindings], ["paid_amount", "region"])

    def test_actual_avg_is_not_overwritten_by_schema_default_sum(self):
        _, _, _, bound, prepared, filters, _ = pipeline(
            "SELECT AVG(paid_amount) AS average_amount FROM orders_current HAVING AVG(paid_amount)>100",
        )
        self.assertEqual(prepared.status, "resolved")
        self.assertEqual(bound[0].aggregation, "AVG")
        self.assertEqual(prepared.bindings[0].default_aggregation, "sum")
        self.assertEqual(filters.filters[0].aggregation_expression, "AVG(paid_amount)")

    def test_count_star_and_literals_do_not_invent_field_bindings(self):
        for sql in ("SELECT COUNT(*) FROM orders_current", "SELECT COUNT(1) FROM orders_current", "SELECT 1, 'text', NULL"):
            with self.subTest(sql=sql):
                result = self.prepare(sql)
                self.assertEqual(result.status, "resolved")
                self.assertEqual(result.bindings, [])

    def test_count_field_has_a_real_field_binding(self):
        result = self.prepare("SELECT COUNT(customer_id) FROM orders_current")
        self.assertEqual(result.status, "resolved")
        self.assertEqual([binding.source.field for binding in result.bindings], ["customer_id"])

    def test_source_order_is_select_where_having_group_and_deduplicated(self):
        result = self.prepare(
            "SELECT region FROM orders_current "
            "WHERE status='paid' AND order_date>='2026-08-01' AND REGION='a' "
            "GROUP BY category,region HAVING SUM(paid_amount)>0",
        )
        self.assertEqual(result.status, "resolved")
        self.assertEqual([binding.source.field for binding in result.bindings], [
            "region", "status", "order_date", "paid_amount", "category",
        ])

    def test_unknown_database_is_not_filled_from_schema(self):
        for database in (None, "", "   "):
            with self.subTest(database=database):
                result = self.prepare("SELECT region FROM orders_current", database=database)
                self.assertEqual(result.status, "unknown")
                self.assertEqual(result.bindings, [])
                self.assertTrue(result.limitations)

    def test_database_identity_remains_exact(self):
        for database in ("ASKDATA_MOCK", "another_database"):
            with self.subTest(database=database):
                result = self.prepare("SELECT region FROM orders_current", database=database)
                self.assertEqual(result.status, "unknown")
                self.assertEqual(result.bindings, [])

    def test_duplicate_table_identity_is_unknown_even_when_metadata_matches(self):
        schema = copy.deepcopy(SCHEMA)
        duplicate = copy.deepcopy(schema[0])
        duplicate["id"] = "ORDERS_CURRENT"
        schema.append(duplicate)
        result = self.prepare("SELECT region FROM orders_current", schema=schema)
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.bindings, [])
        self.assertTrue(result.limitations)

    def test_duplicate_field_identity_is_unknown_without_partial_success(self):
        schema = copy.deepcopy(SCHEMA)
        field = next(item for item in schema[0]["fields"] if item["name"] == "status")
        duplicate = copy.deepcopy(field)
        duplicate["name"] = "STATUS"
        duplicate["label"] = "conflicting metadata"
        schema[0]["fields"].append(duplicate)
        result = self.prepare("SELECT region FROM orders_current WHERE status='paid'", schema=schema)
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.bindings, [])

    def test_unknown_table_does_not_search_other_tables_by_field_name(self):
        result = self.prepare("SELECT region FROM missing_table")
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.bindings, [])

    def test_schema_aliases_are_not_source_identity(self):
        result = self.prepare('SELECT region FROM orders_current WHERE "销售额">100')
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.bindings, [])

    def test_select_alias_is_not_used_to_guess_predicate_source(self):
        result = self.prepare("SELECT region AS status FROM orders_current WHERE status='paid'")
        self.assertEqual(result.status, "unsupported")
        self.assertEqual(result.bindings, [])

    def test_display_alias_does_not_change_actual_source(self):
        result = self.prepare("SELECT paid_amount AS order_date FROM orders_current")
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.bindings[0].source.field, "paid_amount")
        self.assertEqual(result.bindings[0].role, "metric")

    def test_hidden_between_date_works_through_public_time_reader(self):
        _, _, _, _, prepared, filters, times = pipeline(
            "SELECT region FROM orders_current "
            "WHERE order_date BETWEEN DATE '2026-08-01' AND DATE '2026-08-31'",
        )
        self.assertEqual(prepared.status, "resolved")
        self.assertEqual(filters.status, "resolved")
        self.assertEqual(times[0].status, "resolved")
        self.assertEqual((times[0].lower, times[0].upper), ("2026-08-01", "2026-08-31"))
        self.assertEqual((times[0].inclusive.lower, times[0].inclusive.upper), (True, True))

    def test_hidden_target_month_uses_schema_role_without_calendar_expansion(self):
        _, _, _, _, prepared, _, times = pipeline(
            "SELECT region FROM sales_targets WHERE target_month='2026-08'",
        )
        self.assertEqual(prepared.status, "resolved")
        self.assertEqual(times[0].status, "resolved")
        self.assertEqual(times[0].precision, "month")
        self.assertEqual((times[0].lower, times[0].upper), ("2026-08", "2026-08"))

    def test_no_time_predicate_does_not_use_table_description(self):
        _, _, _, _, prepared, _, times = pipeline("SELECT region FROM orders_current")
        self.assertEqual(prepared.status, "resolved")
        self.assertEqual(times, [])
        self.assertEqual([binding.source.field for binding in prepared.bindings], ["region"])

    def test_ast_and_parsed_select_inputs_produce_same_result(self):
        parsed = parse_sql(FULL_SQL)
        from_parsed = prepare_query_bindings(parsed, "askdata_mock", tuple(SCHEMA))
        from_ast = prepare_query_bindings(parsed.statement, "askdata_mock", SCHEMA)
        self.assertEqual(from_parsed, from_ast)

    def test_missing_root_cannot_reconstruct_from_projection_sql(self):
        parsed = parse_sql("SELECT region FROM orders_current")
        missing_root = ParsedSelect(parsed.projections, parsed.aliases, parsed.table, parsed.qualifier)
        result = prepare_query_bindings(missing_root, "askdata_mock", SCHEMA)
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.bindings, [])
        self.assertTrue(result.limitations)

    def test_preparation_does_not_reparse_original_sql(self):
        parsed = parse_sql(FULL_SQL)
        original_parse_one = sqlglot.parse_one

        def guard_parse_one(sql, *args, **kwargs):
            # SQLGlot's DATE rendering may internally parse a type name such
            # as 'array'; only a query reparse would violate this boundary.
            self.assertNotEqual(sql, FULL_SQL)
            self.assertNotIn("SELECT", str(sql).upper())
            return original_parse_one(sql, *args, **kwargs)

        with patch("sqlglot.parse", side_effect=AssertionError("no query parsing")), \
             patch("sqlglot.parse_one", side_effect=guard_parse_one), \
             patch("app.querying.result_understanding.sql_parser.parse_sql", side_effect=AssertionError("no query parsing")):
            result = prepare_query_bindings(parsed, "askdata_mock", SCHEMA)
        self.assertEqual(result.status, "resolved")

    def test_repeat_queries_do_not_leak_bindings_across_tables(self):
        first = self.prepare("SELECT region FROM orders_current")
        self.prepare("SELECT region FROM customers")
        second = self.prepare("SELECT region FROM orders_current")
        self.assertEqual(first, second)
        self.assertEqual(second.bindings[0].label, "销售地区")


if __name__ == "__main__":
    unittest.main()
