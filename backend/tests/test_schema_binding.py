"""Pure Schema binding tests: no SQL execution, workflow, or model calls."""

import copy
import unittest

from app.database import SCHEMA
from app.querying.result_contract import ColumnMetadata, ExecutionData, ResultContract
from app.querying.result_understanding.lineage import understand_columns
from app.querying.result_understanding.models import (
    ColumnSemantic,
    LineageSource,
    SchemaBinding,
)
from app.querying.result_understanding.schema_binding import bind_schema


def source(table="orders_current", field="paid_amount", database="askdata_mock"):
    return LineageSource(database=database, table=table, field=field)


def column(sources=None, **overrides):
    values = {
        "column_id": "column_0",
        "ordinal": 0,
        "output_name": "sales_amount",
        "expression": "SUM(o.paid_amount)",
        "lineage": [source()] if sources is None else sources,
        "aggregation": "SUM",
        "status": "resolved",
    }
    values.update(overrides)
    return ColumnSemantic(**values)


def parsed_column(function):
    contract = ResultContract(
        result_id="schema-binding-test-result",
        execution=ExecutionData(
            database="askdata_mock",
            sql=f"SELECT {function}(o.paid_amount) AS sales_amount FROM orders_current o",
            success=True,
            columns=[ColumnMetadata(id="column_0", ordinal=0, name="sales_amount")],
        ),
    )
    return understand_columns(contract)[0]


class SchemaBindingTest(unittest.TestCase):
    def test_sum_binds_actual_parsed_source_to_real_schema(self):
        result = bind_schema(parsed_column("SUM"), SCHEMA)
        self.assertEqual(result.aggregation, "SUM")
        self.assertEqual(len(result.schema_bindings), 1)
        binding = result.schema_bindings[0]
        self.assertEqual(binding.source, source())
        self.assertEqual(binding.label, "实付金额")
        self.assertEqual(binding.aliases, ["销售额", "成交额", "收入", "实收"])
        self.assertEqual(binding.description, "客户实际支付金额，可用于计算实际成交金额")
        self.assertEqual(binding.role, "metric")
        self.assertEqual(binding.default_aggregation, "sum")

    def test_avg_does_not_get_overwritten_by_schema_default_sum(self):
        result = bind_schema(parsed_column("AVG"), SCHEMA)
        self.assertEqual(result.aggregation, "AVG")
        self.assertEqual(result.schema_bindings[0].default_aggregation, "sum")

    def test_same_field_name_binds_by_qualified_identity(self):
        orders = bind_schema(column([source(field="region")]), SCHEMA)
        customers = bind_schema(column([source("customers", "region")]), SCHEMA)
        self.assertEqual(orders.schema_bindings[0].label, "销售地区")
        self.assertEqual(customers.schema_bindings[0].label, "客户地区")
        self.assertNotEqual(
            orders.schema_bindings[0].description,
            customers.schema_bindings[0].description,
        )

    def test_output_name_does_not_override_lineage(self):
        result = bind_schema(
            column([source(field="order_amount")], output_name="销售额"), SCHEMA,
        )
        self.assertEqual(result.schema_bindings[0].source.field, "order_amount")
        self.assertEqual(result.schema_bindings[0].label, "订单金额")

    def test_schema_alias_is_not_an_alternative_field_identity(self):
        result = bind_schema(column([source(field="销售额")]), SCHEMA)
        self.assertEqual(result.schema_bindings, [])

    def test_schema_table_label_is_not_an_alternative_table_identity(self):
        result = bind_schema(column([source(table="当前订单明细")]), SCHEMA)
        self.assertEqual(result.schema_bindings, [])

    def test_unknown_status_is_not_bound_even_with_matching_source(self):
        original = column(status="unknown", reason="missing execution evidence")
        result = bind_schema(original, SCHEMA)
        self.assertEqual(result.schema_bindings, [])
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.reason, original.reason)

    def test_unsupported_status_is_not_bound_even_with_matching_source(self):
        original = column(status="unsupported", reason="not supported")
        result = bind_schema(original, SCHEMA)
        self.assertEqual(result.schema_bindings, [])
        self.assertEqual(result.status, "unsupported")
        self.assertEqual(result.reason, original.reason)

    def test_multiple_sources_are_all_bound_in_original_order(self):
        sources = [source("customers", "region"), source(field="region"), source()]
        result = bind_schema(column(sources), SCHEMA)
        self.assertEqual(result.lineage, sources)
        self.assertEqual([binding.source for binding in result.schema_bindings], sources)
        self.assertEqual(
            [binding.label for binding in result.schema_bindings],
            ["客户地区", "销售地区", "实付金额"],
        )

    def test_missing_source_does_not_remove_other_sources_or_lineage(self):
        sources = [source(), source(field="missing"), source("customers", "region")]
        result = bind_schema(column(sources), SCHEMA)
        self.assertEqual(result.lineage, sources)
        self.assertEqual(
            [binding.source for binding in result.schema_bindings],
            [sources[0], sources[2]],
        )
        self.assertEqual(result.status, "resolved")

    def test_database_identity_is_required_and_case_sensitive(self):
        for database in (None, "", "another_database", "ASKDATA_MOCK"):
            with self.subTest(database=database):
                result = bind_schema(column([source(database=database)]), SCHEMA)
                self.assertEqual(result.schema_bindings, [])

    def test_cross_database_uses_only_exact_database_match(self):
        schema = [
            {"database": "other", "id": "orders_current", "fields": [
                {"name": "paid_amount", "label": "Other database amount"},
            ]},
            {"database": "askdata_mock", "id": "orders_current", "fields": [
                {"name": "paid_amount", "label": "Expected amount"},
            ]},
        ]
        result = bind_schema(column(), schema)
        self.assertEqual(result.schema_bindings[0].label, "Expected amount")

    def test_table_and_field_ascii_case_match_without_rewriting_source(self):
        original_source = source("Orders_Current", "PAID_Amount")
        result = bind_schema(column([original_source]), SCHEMA)
        self.assertEqual(result.schema_bindings[0].label, "实付金额")
        self.assertEqual(result.schema_bindings[0].source, original_source)
        self.assertEqual(result.lineage, [original_source])

    def test_non_ascii_identifier_case_is_not_folded(self):
        schema = [{"database": "askdata_mock", "id": "Ä", "fields": [
            {"name": "Ö", "label": "Exact Unicode identifier"},
        ]}]
        exact = bind_schema(column([source("Ä", "Ö")]), schema)
        self.assertEqual(exact.schema_bindings[0].label, "Exact Unicode identifier")
        for table, field in (("ä", "Ö"), ("Ä", "ö")):
            with self.subTest(table=table, field=field):
                self.assertEqual(bind_schema(column([source(table, field)]), schema).schema_bindings, [])

    def test_missing_table_or_field_is_not_bound(self):
        for table, field in (("missing", "paid_amount"), ("", "paid_amount"),
                             ("orders_current", "missing"), ("orders_current", "")):
            with self.subTest(table=table, field=field):
                result = bind_schema(column([source(table, field)]), SCHEMA)
                self.assertEqual(result.schema_bindings, [])

    def test_relation_level_count_has_no_invented_field_binding(self):
        original = column([source(field=None)], aggregation="COUNT", expression="COUNT(*)")
        result = bind_schema(original, SCHEMA)
        self.assertEqual(result.schema_bindings, [])
        self.assertEqual(result.lineage, original.lineage)

    def test_constants_and_absent_lineage_have_no_binding(self):
        for lineage in ([], None):
            with self.subTest(lineage=lineage):
                original = column(lineage=lineage)
                result = bind_schema(original, SCHEMA)
                self.assertEqual(result.schema_bindings, [])
                self.assertEqual(result.lineage, lineage)

    def test_duplicate_table_identity_is_ambiguous(self):
        schema = copy.deepcopy(SCHEMA)
        duplicate = copy.deepcopy(schema[0])
        duplicate["id"] = "ORDERS_CURRENT"
        duplicate["fields"] = []
        schema.append(duplicate)
        self.assertEqual(bind_schema(column(), schema).schema_bindings, [])

    def test_duplicate_field_identity_is_ambiguous(self):
        schema = copy.deepcopy(SCHEMA)
        schema[0]["fields"].append({"name": "PAID_AMOUNT", "label": "Ambiguous"})
        self.assertEqual(bind_schema(column(), schema).schema_bindings, [])

    def test_absent_metadata_remains_unknown_not_fabricated(self):
        schema = [{"database": "askdata_mock", "id": "orders_current", "fields": [
            {"name": "paid_amount"},
        ]}]
        binding = bind_schema(column(), schema).schema_bindings[0]
        self.assertIsNone(binding.label)
        self.assertIsNone(binding.aliases)
        self.assertIsNone(binding.description)
        self.assertIsNone(binding.role)
        self.assertIsNone(binding.default_aggregation)

    def test_explicit_empty_aliases_are_not_unknown(self):
        schema = [{"database": "askdata_mock", "id": "orders_current", "fields": [
            {"name": "paid_amount", "aliases": []},
        ]}]
        self.assertEqual(bind_schema(column(), schema).schema_bindings[0].aliases, [])

    def test_input_column_and_schema_are_not_modified(self):
        original = parsed_column("AVG")
        original_before = original.model_dump()
        schema = copy.deepcopy(SCHEMA)
        schema_before = copy.deepcopy(schema)
        result = bind_schema(original, schema)
        self.assertIsNot(result, original)
        self.assertEqual(original.model_dump(), original_before)
        self.assertEqual(schema, schema_before)
        self.assertEqual(
            result.model_dump(exclude={"schema_bindings"}),
            original.model_dump(exclude={"schema_bindings"}),
        )

    def test_lineage_lists_are_isolated_in_both_directions(self):
        original = column()
        result = bind_schema(original, SCHEMA)
        self.assertIsNot(result.lineage, original.lineage)
        self.assertIsNot(result.lineage[0], original.lineage[0])
        original.lineage.append(source("customers", "region"))
        self.assertEqual(len(result.lineage), 1)
        result.lineage.clear()
        self.assertEqual(len(original.lineage), 2)

    def test_binding_aliases_are_isolated_from_schema_in_both_directions(self):
        schema = copy.deepcopy(SCHEMA)
        aliases = next(item for item in schema[0]["fields"] if item["name"] == "paid_amount")["aliases"]
        result = bind_schema(column(), schema)
        bound_aliases = result.schema_bindings[0].aliases
        self.assertIsNot(aliases, bound_aliases)
        aliases.append("schema only")
        self.assertNotIn("schema only", bound_aliases)
        bound_aliases.append("output only")
        self.assertNotIn("output only", aliases)

    def test_rebinding_replaces_stale_bindings_and_is_idempotent(self):
        old_binding = SchemaBinding(source=source(), label="Stale label", aliases=["old"])
        original = column(schema_bindings=[old_binding])
        first = bind_schema(original, SCHEMA)
        second = bind_schema(first, SCHEMA)
        self.assertEqual(len(first.schema_bindings), 1)
        self.assertEqual(first.schema_bindings[0].label, "实付金额")
        self.assertEqual(first.model_dump(), second.model_dump())
        self.assertEqual(original.schema_bindings[0].label, "Stale label")
        second.schema_bindings[0].aliases.append("second only")
        self.assertNotIn("second only", first.schema_bindings[0].aliases)
        self.assertEqual(original.schema_bindings[0].aliases, ["old"])

    def test_unresolved_or_missing_sources_clear_stale_bindings(self):
        stale = SchemaBinding(source=source(), label="Stale label")
        for status, lineage in (("unknown", [source()]), ("unsupported", [source()]),
                                ("resolved", [source(field="missing")])):
            with self.subTest(status=status, lineage=lineage):
                original = column(status=status, lineage=lineage, schema_bindings=[stale])
                result = bind_schema(original, SCHEMA)
                self.assertEqual(result.schema_bindings, [])
                self.assertEqual(len(original.schema_bindings), 1)

    def test_old_column_constructor_gets_independent_empty_bindings(self):
        first = column()
        second = column()
        self.assertEqual(first.schema_bindings, [])
        self.assertEqual(second.schema_bindings, [])
        first.schema_bindings.append(SchemaBinding(source=source()))
        self.assertEqual(second.schema_bindings, [])

    def test_schema_binding_serializes_source_and_default_aggregation(self):
        result = bind_schema(parsed_column("AVG"), SCHEMA)
        encoded = result.model_dump_json()
        restored = ColumnSemantic.model_validate_json(encoded)
        self.assertEqual(restored, result)
        self.assertEqual(restored.aggregation, "AVG")
        self.assertEqual(restored.schema_bindings[0].default_aggregation, "sum")
        self.assertEqual(restored.schema_bindings[0].source.field, "paid_amount")


if __name__ == "__main__":
    unittest.main()
