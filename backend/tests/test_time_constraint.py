"""Time constraints use supplied filter/source evidence, never SQL or rows."""

import copy
import inspect
import unittest
from unittest.mock import patch

import sqlglot
from sqlglot import exp

from app.database import SCHEMA
from app.querying.result_contract import ColumnMetadata, ExecutionData, ResultContract
from app.querying.result_understanding.filter import understand_filters
from app.querying.result_understanding.lineage import understand_columns
from app.querying.result_understanding.models import FilterInfo, LineageSource, SchemaBinding
from app.querying.result_understanding.schema_binding import bind_schema
from app.querying.result_understanding.time_constraint import understand_time_constraints


def inputs(sql, *, bound=True):
    """SQL parsing is test setup; the time reader receives only semantics."""
    statement = sqlglot.parse_one(sql, read="duckdb")
    projections = statement.expressions if isinstance(statement, exp.Select) else [None]
    contract = ResultContract(
        result_id="time-test-result",
        execution=ExecutionData(
            database="askdata_mock", sql=sql, success=True,
            columns=[
                ColumnMetadata(id=f"column_{index}", ordinal=index, name=f"display_{index}")
                for index, _ in enumerate(projections)
            ],
        ),
    )
    columns = understand_columns(contract)
    if bound:
        columns = [bind_schema(column, SCHEMA) for column in columns]
    return understand_filters(statement, columns), columns


def source(field="order_date", table="orders_current", database="askdata_mock"):
    return LineageSource(database=database, table=table, field=field)


class TimeConstraintTest(unittest.TestCase):
    def read(self, predicate, *, field="order_date", table="orders_current"):
        return understand_time_constraints(*inputs(
            f"SELECT {field} FROM {table} WHERE {predicate}",
        ))

    def test_lower_inclusive_upper_exclusive_form_one_range(self):
        result = self.read("order_date >= '2026-08-01' AND order_date < '2026-09-01'")
        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertEqual(item.status, "resolved")
        self.assertEqual(item.source_field, source())
        self.assertEqual(item.operator, "AND")
        self.assertEqual((item.lower, item.upper), ("2026-08-01", "2026-09-01"))
        self.assertEqual((item.inclusive.lower, item.inclusive.upper), (True, False))
        self.assertEqual(item.precision, "date")
        self.assertEqual(item.scope, "WHERE")
        self.assertFalse(item.is_empty)
        self.assertIn("AND", item.expression)
        self.assertEqual(item.schema_bindings[0].label, "下单日期")
        self.assertEqual(item.schema_bindings[0].role, "time")

    def test_between_preserves_both_closed_bounds(self):
        result = self.read("order_date BETWEEN '2026-08-01' AND '2026-08-31'")
        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertEqual(item.status, "resolved")
        self.assertEqual(item.operator, "BETWEEN")
        self.assertEqual((item.lower, item.upper), ("2026-08-01", "2026-08-31"))
        self.assertEqual((item.inclusive.lower, item.inclusive.upper), (True, True))
        self.assertIn("BETWEEN", item.expression)

    def test_between_typed_date_literals(self):
        item = self.read("order_date BETWEEN DATE '2026-08-01' AND DATE '2026-08-31'")[0]
        self.assertEqual(item.status, "resolved")
        self.assertEqual((item.lower, item.upper), ("2026-08-01", "2026-08-31"))

    def test_target_month_remains_month_not_expanded_dates(self):
        item = self.read("target_month='2026-08'", field="target_month", table="sales_targets")[0]
        self.assertEqual(item.status, "resolved")
        self.assertEqual(item.source_field, source("target_month", "sales_targets"))
        self.assertEqual(item.operator, "=")
        self.assertEqual(item.precision, "month")
        self.assertEqual((item.lower, item.upper), ("2026-08", "2026-08"))
        self.assertEqual((item.inclusive.lower, item.inclusive.upper), (True, True))

    def test_no_conditions_produce_known_empty_list(self):
        self.assertEqual(understand_time_constraints(*inputs("SELECT order_date FROM orders_current")), [])

    def test_non_time_conditions_do_not_invent_time(self):
        self.assertEqual(self.read("region='华北'", field="region"), [])

    def test_date_shaped_string_on_dimension_is_not_time(self):
        self.assertEqual(self.read("region='2026-08-01'", field="region"), [])

    def test_current_date_is_unsupported(self):
        result = self.read("order_date>=CURRENT_DATE")
        self.assertTrue(result)
        self.assertTrue(any(item.status == "unsupported" for item in result))

    def test_other_dynamic_or_complex_time_is_unsupported(self):
        for predicate in (
            "order_date>=CURRENT_DATE-INTERVAL '1 month'",
            "order_date>=DATE '2026-08-01'+INTERVAL '1 day'",
            "order_date AT TIME ZONE 'UTC'>=TIMESTAMP '2026-08-01 00:00:00'",
            "DATE_TRUNC('month',order_date)=DATE '2026-08-01'",
            "order_date='2026-08-01' OR order_date='2026-08-02'",
            "order_date>(SELECT MAX(order_date) FROM orders_history)",
        ):
            with self.subTest(predicate=predicate):
                result = self.read(predicate)
                self.assertTrue(result)
                self.assertTrue(any(item.status == "unsupported" for item in result))
                self.assertTrue(any(item.limitations for item in result))

    def test_rows_and_user_query_are_not_accepted_as_evidence(self):
        semantics, columns = inputs("SELECT order_date FROM orders_current")
        for keyword, value in (
            ("rows", [{"order_date": "2026-08-01"}, {"order_date": "2026-08-31"}]),
            ("query", "本月订单"),
        ):
            with self.subTest(keyword=keyword), self.assertRaises(TypeError):
                understand_time_constraints(semantics, columns, **{keyword: value})
        self.assertNotIn("rows", inspect.signature(understand_time_constraints).parameters)
        self.assertEqual(understand_time_constraints(semantics, columns), [])

    def test_input_and_nested_metadata_unchanged(self):
        semantics, columns = inputs("SELECT order_date FROM orders_current WHERE order_date>='2026-08-01'")
        bindings = [columns[0].schema_bindings[0].model_copy(deep=True)]
        before = copy.deepcopy((semantics.model_dump(), [c.model_dump() for c in columns], [b.model_dump() for b in bindings]))
        result = understand_time_constraints(semantics, columns, bindings)
        self.assertEqual(result[0].status, "resolved")
        result[0].schema_bindings[0].aliases.clear()
        result[0].schema_bindings.clear()
        result.clear()
        after = (semantics.model_dump(), [c.model_dump() for c in columns], [b.model_dump() for b in bindings])
        self.assertEqual(after, before)

    def test_time_reader_does_not_reparse_sql(self):
        semantics, columns = inputs("SELECT order_date FROM orders_current WHERE order_date>='2026-08-01'")
        with patch("sqlglot.parse", side_effect=AssertionError("no SQL parsing")), \
             patch("sqlglot.parse_one", side_effect=AssertionError("no SQL parsing")), \
             patch("app.querying.result_understanding.sql_parser.parse_sql", side_effect=AssertionError("no SQL parsing")):
            self.assertEqual(understand_time_constraints(semantics, columns)[0].status, "resolved")

    def test_all_single_comparisons_retain_endpoint_inclusivity(self):
        for operator, lower, upper, lower_inclusive, upper_inclusive in (
            (">", "2026-08-01", None, False, None),
            (">=", "2026-08-01", None, True, None),
            ("<", None, "2026-08-01", None, False),
            ("<=", None, "2026-08-01", None, True),
            ("=", "2026-08-01", "2026-08-01", True, True),
        ):
            with self.subTest(operator=operator):
                item = self.read(f"order_date{operator}'2026-08-01'")[0]
                self.assertEqual(item.status, "resolved")
                self.assertEqual(item.operator, operator)
                self.assertEqual((item.lower, item.upper), (lower, upper))
                self.assertEqual((item.inclusive.lower, item.inclusive.upper), (lower_inclusive, upper_inclusive))

    def test_stricter_lower_and_upper_win(self):
        item = self.read(
            "order_date>='2026-08-01' AND order_date>'2026-08-05' "
            "AND order_date<='2026-08-31' AND order_date<'2026-08-25'",
        )[0]
        self.assertEqual((item.lower, item.upper), ("2026-08-05", "2026-08-25"))
        self.assertEqual((item.inclusive.lower, item.inclusive.upper), (False, False))

    def test_equal_boundary_exclusive_wins_in_both_orders(self):
        for predicates in (
            "order_date>='2026-08-01' AND order_date>'2026-08-01'",
            "order_date>'2026-08-01' AND order_date>='2026-08-01'",
        ):
            with self.subTest(predicates=predicates):
                item = self.read(predicates)[0]
                self.assertEqual(item.lower, "2026-08-01")
                self.assertFalse(item.inclusive.lower)

    def test_contradictory_bounds_describe_empty_domain_not_row_count(self):
        for predicates in (
            "order_date>='2026-09-01' AND order_date<'2026-08-01'",
            "order_date>'2026-08-01' AND order_date<='2026-08-01'",
            "order_date='2026-08-01' AND order_date='2026-08-02'",
        ):
            with self.subTest(predicates=predicates):
                item = self.read(predicates)[0]
                self.assertEqual(item.status, "resolved")
                self.assertTrue(item.is_empty)
                self.assertNotIn("row_count", item.model_dump())

    def test_valid_leap_day(self):
        item = self.read("order_date='2024-02-29'")[0]
        self.assertEqual(item.status, "resolved")
        self.assertEqual(item.lower, "2024-02-29")

    def test_invalid_calendar_and_non_iso_values_not_resolved(self):
        for literal in ("2026-02-29", "2026-13-01", "2026-08-32", "2026-8-1", "2026/08/01", "infinity"):
            with self.subTest(literal=literal):
                item = self.read(f"order_date='{literal}'")[0]
                self.assertNotEqual(item.status, "resolved")
                self.assertTrue(item.limitations)

    def test_invalid_month_not_resolved(self):
        for literal in ("2026-00", "2026-13"):
            with self.subTest(literal=literal):
                item = self.read(f"target_month='{literal}'", field="target_month", table="sales_targets")[0]
                self.assertNotEqual(item.status, "resolved")

    def test_month_inequality_is_explicitly_unsupported(self):
        item = self.read("target_month>='2026-08'", field="target_month", table="sales_targets")[0]
        self.assertEqual(item.status, "unsupported")

    def test_timestamp_not_silently_narrowed_to_date(self):
        item = self.read("order_date>=TIMESTAMP '2026-08-01 12:34:56'")[0]
        self.assertEqual(item.status, "unsupported")
        self.assertTrue(item.limitations)

    def test_missing_time_role_returns_unknown_not_name_guess(self):
        semantics, columns = inputs("SELECT order_date FROM orders_current WHERE order_date='2026-08-01'", bound=False)
        result = understand_time_constraints(semantics, columns)
        self.assertTrue(result)
        self.assertEqual(result[0].status, "unknown")

    def test_exact_source_binding_can_supply_missing_time_role(self):
        semantics, columns = inputs("SELECT order_date FROM orders_current WHERE order_date='2026-08-01'", bound=False)
        bindings = [SchemaBinding(source=source(), role="time", label="下单日期", description="日期")]
        item = understand_time_constraints(semantics, columns, bindings)[0]
        self.assertEqual(item.status, "resolved")
        self.assertEqual(item.schema_bindings[0].source, source())

    def test_foreign_table_or_database_binding_cannot_supply_role(self):
        semantics, columns = inputs("SELECT order_date FROM orders_current WHERE order_date='2026-08-01'", bound=False)
        for wrong in (source(table="orders_history"), source(database="another_database")):
            with self.subTest(wrong=wrong):
                item = understand_time_constraints(semantics, columns, [SchemaBinding(source=wrong, role="time")])[0]
                self.assertEqual(item.status, "unknown")

    def test_conflicting_time_roles_return_unknown(self):
        semantics, columns = inputs("SELECT order_date FROM orders_current WHERE order_date='2026-08-01'")
        conflicting = SchemaBinding(source=source(), role="dimension")
        result = understand_time_constraints(semantics, columns, [conflicting])
        self.assertEqual(result[0].status, "unknown")

    def test_unknown_lineage_is_not_bound_from_field_name(self):
        semantics, columns = inputs("SELECT order_date FROM orders_current WHERE unknown_date='2026-08-01'")
        result = understand_time_constraints(semantics, columns)
        self.assertTrue(result)
        self.assertEqual(result[0].status, "unknown")
        self.assertIsNone(result[0].source_field)

    def test_unknown_and_unsupported_empty_filter_info_not_known_empty(self):
        for status in ("unknown", "unsupported"):
            with self.subTest(status=status):
                result = understand_time_constraints(FilterInfo(status=status, limitations=["upstream unavailable"]), [])
                self.assertTrue(result)
                self.assertEqual(result[0].status, status)
                self.assertTrue(result[0].limitations)

    def test_two_sources_are_not_merged(self):
        current, current_columns = inputs("SELECT order_date FROM orders_current WHERE order_date>='2026-08-01'")
        history, history_columns = inputs("SELECT order_date FROM orders_history WHERE order_date<'2026-07-01'")
        combined = FilterInfo(status="resolved", filters=[*current.filters, *history.filters])
        result = understand_time_constraints(combined, [*current_columns, *history_columns])
        self.assertEqual(len(result), 2)
        keyed = {item.source_field.table: item for item in result}
        self.assertEqual(keyed["orders_current"].lower, "2026-08-01")
        self.assertIsNone(keyed["orders_current"].upper)
        self.assertEqual(keyed["orders_history"].upper, "2026-07-01")
        self.assertIsNone(keyed["orders_history"].lower)

    def test_having_aggregate_does_not_become_input_date_range(self):
        semantics, columns = inputs("SELECT COUNT(order_date) FROM orders_current HAVING COUNT(order_date)>100")
        result = understand_time_constraints(semantics, columns)
        self.assertTrue(result)
        self.assertTrue(any(item.status == "unsupported" and item.scope == "HAVING" for item in result))
        self.assertFalse(any(item.status == "resolved" and item.scope == "WHERE" for item in result))

    def test_not_equal_is_not_one_contiguous_date_range(self):
        item = self.read("order_date!='2026-08-01'")[0]
        self.assertEqual(item.status, "unsupported")

    def test_null_date_does_not_get_fabricated_endpoint(self):
        item = self.read("order_date=NULL")[0]
        self.assertNotEqual(item.status, "resolved")
        self.assertIsNone(item.lower)
        self.assertIsNone(item.upper)

    def test_alias_display_name_does_not_select_temporal_source(self):
        semantics, columns = inputs("SELECT region AS order_date FROM orders_current WHERE region='2026-08-01'")
        self.assertEqual(understand_time_constraints(semantics, columns), [])

    def test_upstream_binding_conflict_cannot_be_healed_from_remaining_columns(self):
        sql = "SELECT order_date FROM orders_current WHERE order_date='2026-08-01'"
        _, columns = inputs(sql)
        ast = sqlglot.parse_one(sql, read="duckdb")
        bad = SchemaBinding(source=source(), role="dimension")
        semantics = understand_filters(ast, columns, [bad])
        self.assertEqual(semantics.status, "resolved")
        self.assertTrue(semantics.filters[0].limitations)
        self.assertEqual(semantics.filters[0].schema_bindings, [])
        result = understand_time_constraints(semantics, columns)
        self.assertTrue(result)
        self.assertTrue(any(item.status == "unknown" for item in result))
        self.assertFalse(any(item.status == "resolved" for item in result))

    def test_retained_where_without_conditions_is_incomplete_not_no_time(self):
        semantics = FilterInfo(
            status="resolved", filters=[],
            where_expression="order_date > '2026-08-01'",
        )
        with patch("sqlglot.parse", side_effect=AssertionError("do not recover from expression text")), \
             patch("sqlglot.parse_one", side_effect=AssertionError("do not recover from expression text")):
            result = understand_time_constraints(semantics, [])
        self.assertTrue(result)
        self.assertEqual(result[0].status, "unknown")
        self.assertIsNone(result[0].lower)
        self.assertIsNone(result[0].upper)

    def test_same_source_conflicting_predicate_roles_cannot_partially_resolve(self):
        semantics, _ = inputs(
            "SELECT order_date FROM orders_current "
            "WHERE order_date>='2026-08-01' AND order_date<'2026-09-01'",
        )
        wrong = semantics.filters[1].schema_bindings[0].model_copy(update={"role": "dimension"})
        changed = semantics.filters[1].model_copy(update={"schema_bindings": [wrong]})
        conflicting = semantics.model_copy(update={"filters": [semantics.filters[0], changed]})
        result = understand_time_constraints(conflicting, [])
        self.assertTrue(result)
        self.assertTrue(any(item.status == "unknown" for item in result))
        self.assertFalse(any(item.status == "resolved" for item in result))

    def test_between_missing_structured_bound_is_unknown_without_reparsing(self):
        semantics, columns = inputs(
            "SELECT order_date FROM orders_current "
            "WHERE order_date BETWEEN '2026-08-01' AND '2026-08-31'",
        )
        for field in ("lower_bound", "upper_bound"):
            with self.subTest(field=field):
                broken = semantics.filters[0].model_copy(update={field: None})
                incomplete = semantics.model_copy(update={"filters": [broken]})
                with patch("sqlglot.parse", side_effect=AssertionError("do not reparse BETWEEN")), \
                     patch("sqlglot.parse_one", side_effect=AssertionError("do not reparse BETWEEN")):
                    result = understand_time_constraints(incomplete, columns)
                self.assertTrue(result)
                self.assertEqual(result[0].status, "unknown")
                self.assertIsNone(result[0].lower)
                self.assertIsNone(result[0].upper)


if __name__ == "__main__":
    unittest.main()
