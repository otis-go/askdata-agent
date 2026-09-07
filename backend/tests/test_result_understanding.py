import ast
import unittest
from pathlib import Path

from app.querying.result_contract import ColumnMetadata, ExecutionData, ResultContract
from app.querying.result_understanding.lineage import understand_columns


def contract_for(sql, names, database="askdata_mock", success=True):
    return ResultContract(
        result_id="semantic-test-result",
        execution=ExecutionData(
            database=database, sql=sql, success=success,
            columns=None if names is None else [
                ColumnMetadata(id=f"column_{index}", ordinal=index, name=name)
                for index, name in enumerate(names)
            ],
        ),
    )


class ColumnLineageTest(unittest.TestCase):
    def test_requested_query(self):
        contract = contract_for(
            "SELECT o.region, SUM(o.paid_amount) AS sales_amount "
            "FROM orders_current o GROUP BY o.region",
            ["region", "sales_amount"],
        )
        region, sales = understand_columns(contract)
        self.assertEqual(region.status, "resolved")
        self.assertEqual(region.lineage[0].field, "region")
        self.assertIsNone(region.aggregation)
        self.assertEqual(sales.model_dump(), {
            "column_id": "column_1", "ordinal": 1, "output_name": "sales_amount",
            "expression": "SUM(o.paid_amount)",
            "lineage": [{"database": "askdata_mock", "table": "orders_current", "field": "paid_amount"}],
            "aggregation": "SUM", "status": "resolved", "reason": None,
            "schema_bindings": [],
        })

    def test_sum_avg_and_count_columns(self):
        for function in ("SUM", "AVG", "COUNT"):
            with self.subTest(function=function):
                result = understand_columns(contract_for(
                    f"SELECT {function}(paid_amount) AS result FROM orders_current", ["result"],
                ))[0]
                self.assertEqual(result.status, "resolved")
                self.assertEqual(result.aggregation, function)
                self.assertEqual(result.lineage[0].field, "paid_amount")

    def test_count_star_and_literal_have_relation_not_fake_field_lineage(self):
        for argument in ("*", "1", "NULL", "'literal'", "TRUE"):
            with self.subTest(argument=argument):
                result = understand_columns(contract_for(
                    f"SELECT COUNT({argument}) AS n FROM orders_current", ["n"],
                ))[0]
                self.assertEqual(result.status, "resolved")
                self.assertEqual(result.aggregation, "COUNT")
                self.assertEqual(result.lineage[0].table, "orders_current")
                self.assertIsNone(result.lineage[0].field)

    def test_output_alias_never_selects_source(self):
        result = understand_columns(contract_for(
            "SELECT SUM(order_amount) AS sales_amount FROM orders_current", ["sales_amount"],
        ))[0]
        self.assertEqual(result.lineage[0].field, "order_amount")

    def test_output_names_are_display_only_and_ordinal_controls_binding(self):
        first, second = understand_columns(contract_for(
            "SELECT region, paid_amount FROM orders_current", ["paid_amount", "region"],
        ))
        self.assertEqual((first.output_name, first.lineage[0].field), ("paid_amount", "region"))
        self.assertEqual((second.output_name, second.lineage[0].field), ("region", "paid_amount"))

    def test_duplicate_names_preserve_both_columns(self):
        results = understand_columns(contract_for(
            "SELECT region AS x, paid_amount AS x FROM orders_current", ["x", "x"],
        ))
        self.assertEqual([item.column_id for item in results], ["column_0", "column_1"])
        self.assertEqual([item.ordinal for item in results], [0, 1])
        self.assertEqual([item.lineage[0].field for item in results], ["region", "paid_amount"])

    def test_duplicate_constant_names_have_known_empty_lineage(self):
        results = understand_columns(contract_for("SELECT 1 AS x, 2 AS x", ["x", "x"]))
        self.assertEqual([item.expression for item in results], ["1", "2"])
        self.assertTrue(all(item.status == "resolved" and item.lineage == [] for item in results))

    def test_constants_do_not_need_database_or_rows(self):
        for value in ("1", "'region'", "NULL", "TRUE"):
            with self.subTest(value=value):
                result = understand_columns(contract_for(f"SELECT {value} AS x", ["x"], database=None))[0]
                self.assertEqual(result.status, "resolved")
                self.assertEqual(result.lineage, [])
                self.assertIsNone(result.aggregation)

    def test_quoted_and_ascii_case_insensitive_aliases(self):
        result = understand_columns(contract_for(
            'SELECT "o"."地区" AS "销售区域" FROM "Orders_Current" AS "O"', ["销售区域"],
        ))[0]
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.lineage[0].table, "Orders_Current")
        self.assertEqual(result.lineage[0].field, "地区")

    def test_unicode_aliases_are_not_casefolded(self):
        result = understand_columns(contract_for(
            'SELECT "ä".region FROM orders_current AS "Ä"', ["region"],
        ))[0]
        self.assertEqual(result.status, "unsupported")

    def test_table_qualified_column_without_alias(self):
        result = understand_columns(contract_for(
            "SELECT orders_current.region FROM orders_current", ["region"],
        ))[0]
        self.assertEqual(result.status, "resolved")

    def test_where_and_group_by_columns_are_not_projection_lineage(self):
        result = understand_columns(contract_for(
            "SELECT SUM(paid_amount) FROM orders_current "
            "WHERE status = 'paid' GROUP BY region HAVING COUNT(order_id) > 0", ["total"],
        ))[0]
        self.assertEqual([source.field for source in result.lineage], ["paid_amount"])

    def test_no_catalog_lookup_or_business_binding_is_claimed(self):
        result = understand_columns(contract_for(
            "SELECT field_from_sql FROM table_from_sql", ["unrelated_output_label"],
        ))[0]
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.lineage[0].table, "table_from_sql")
        self.assertEqual(result.lineage[0].field, "field_from_sql")
        self.assertNotIn("role", result.model_dump())

    def test_input_is_not_mutated_or_given_a_new_id(self):
        contract = contract_for("SELECT region FROM orders_current", ["region"])
        before = contract.model_dump()
        first = understand_columns(contract)
        second = understand_columns(contract)
        self.assertEqual(first, second)
        self.assertEqual(contract.model_dump(), before)
        self.assertEqual(contract.result_id, "semantic-test-result")
        self.assertIsNone(contract.execution.rows)
        self.assertIsNone(contract.execution.columns[0].dtype)


class UnsupportedLineageTest(unittest.TestCase):
    def assert_unsupported(self, sql, names):
        results = understand_columns(contract_for(sql, names))
        self.assertEqual(len(results), len(names))
        for item in results:
            self.assertEqual(item.status, "unsupported")
            self.assertIsNone(item.lineage)
            self.assertIsNone(item.aggregation)
            self.assertTrue(item.reason)
        return results

    def test_cte(self):
        self.assert_unsupported(
            "WITH t AS (SELECT region FROM orders_current) SELECT region FROM t", ["region"],
        )

    def test_union_and_other_set_operations(self):
        for operation in ("UNION", "UNION ALL", "INTERSECT", "EXCEPT"):
            with self.subTest(operation=operation):
                self.assert_unsupported(f"SELECT 1 AS x {operation} SELECT 2 AS x", ["x"])

    def test_window_in_projection_order_by_or_qualify(self):
        for sql in (
            "SELECT region, SUM(paid_amount) OVER (PARTITION BY region) FROM orders_current",
            "SELECT region, paid_amount FROM orders_current ORDER BY ROW_NUMBER() OVER ()",
            "SELECT region, paid_amount FROM orders_current QUALIFY ROW_NUMBER() OVER () = 1",
        ):
            with self.subTest(sql=sql):
                self.assert_unsupported(sql, ["region", "amount"])

    def test_joins_and_comma_sources(self):
        for sources in (
            "orders_current o JOIN customers c ON o.customer_id = c.customer_id",
            "orders_current o, customers c",
        ):
            with self.subTest(sources=sources):
                self.assert_unsupported(f"SELECT o.region FROM {sources}", ["region"])

    def test_nested_queries_in_any_scope(self):
        for sql in (
            "SELECT x.region FROM (SELECT region FROM orders_current) x",
            "SELECT (SELECT MAX(region) FROM orders_current) AS x",
            "SELECT region FROM orders_current WHERE EXISTS (SELECT 1 FROM customers)",
        ):
            with self.subTest(sql=sql):
                self.assert_unsupported(sql, ["x"])

    def test_star_and_columns_expansion(self):
        for projection in ("*", "o.*", "* EXCLUDE(region)", "COLUMNS('region')"):
            with self.subTest(projection=projection):
                self.assert_unsupported(f"SELECT {projection} FROM orders_current o", ["x"])

    def test_qualified_or_modified_table_sources(self):
        for source in (
            "main.orders_current",
            "catalog.main.orders_current",
            "orders_current AS o(region)",
            "orders_current TABLESAMPLE(10 PERCENT)",
            "orders_current PIVOT (SUM(paid_amount) FOR region IN ('x'))",
            "read_csv_auto('file.csv')",
        ):
            with self.subTest(source=source):
                self.assert_unsupported(f"SELECT region FROM {source}", ["region"])

    def test_bad_or_schema_qualified_column_does_not_fall_back(self):
        for column in ("other.region", "orders_current.region", "main.orders_current.region"):
            with self.subTest(column=column):
                self.assert_unsupported(f"SELECT {column} FROM orders_current o", ["region"])

    def test_field_without_source_is_not_invented(self):
        self.assert_unsupported("SELECT region", ["region"])

    def test_whole_row_alias_is_not_invented_as_a_field(self):
        for expression in ("o", "COUNT(o)"):
            with self.subTest(expression=expression):
                self.assert_unsupported(f"SELECT {expression} FROM orders_current o", ["x"])

    def test_forward_select_alias_reference_is_not_a_base_field(self):
        for reference in ("p", "P", "SUM(p)"):
            with self.subTest(reference=reference):
                first, second = understand_columns(contract_for(
                    f"SELECT paid_amount AS p, {reference} AS x FROM orders_current", ["p", "x"],
                ))
                self.assertEqual(first.status, "resolved")
                self.assertEqual(second.status, "unsupported")
                self.assertIsNone(second.lineage)

    def test_explicit_table_qualifier_disambiguates_select_alias_name(self):
        first, second = understand_columns(contract_for(
            "SELECT paid_amount AS region, o.region FROM orders_current o", ["region", "region"],
        ))
        self.assertEqual([first.status, second.status], ["resolved", "resolved"])
        self.assertEqual(second.lineage[0].field, "region")

    def test_complex_expressions_are_per_column_unsupported(self):
        for expression in (
            "ROUND(SUM(paid_amount), 2)", "paid_amount * 2", "MAX(paid_amount)",
            "SUM(DISTINCT paid_amount)", "COUNT(DISTINCT region)",
            "SUM(paid_amount ORDER BY region)", "COUNT(region, category)",
            "SUM(paid_amount) FILTER(WHERE region='x')", "SUM(paid_amount + 1)",
            "CAST(paid_amount AS DOUBLE)", "CASE WHEN region='x' THEN paid_amount ELSE 0 END",
        ):
            with self.subTest(expression=expression):
                region, other = understand_columns(contract_for(
                    f"SELECT region, {expression} AS x FROM orders_current", ["region", "x"],
                ))
                self.assertEqual(region.status, "resolved")
                self.assertEqual(other.status, "unsupported")
                self.assertIsNone(other.lineage)
                self.assertIsNone(other.aggregation)
                self.assertIsNotNone(other.expression)

    def test_projection_count_mismatch_is_not_silently_zipped(self):
        for names in (["x"], ["x", "y", "z"]):
            with self.subTest(names=names):
                self.assert_unsupported("SELECT region, paid_amount FROM orders_current", names)

    def test_invalid_nonselect_and_multistatement_sql(self):
        for sql in ("SELECT (", "DELETE FROM orders_current", "SELECT 1; SELECT 2"):
            with self.subTest(sql=sql):
                self.assert_unsupported(sql, ["x"])


class UnknownLineageTest(unittest.TestCase):
    def test_missing_sql_is_unknown(self):
        for sql in (None, "", "  "):
            with self.subTest(sql=sql):
                item = understand_columns(contract_for(sql, ["x"]))[0]
                self.assertEqual(item.status, "unknown")
                self.assertIsNone(item.expression)
                self.assertIsNone(item.lineage)

    def test_unsuccessful_or_unknown_execution_is_unknown(self):
        for success in (False, None):
            with self.subTest(success=success):
                item = understand_columns(contract_for("SELECT region FROM orders_current", ["region"], success=success))[0]
                self.assertEqual(item.status, "unknown")
                self.assertIsNone(item.lineage)

    def test_missing_database_is_not_defaulted(self):
        contract = contract_for("SELECT region FROM orders_current", ["region"], database=None)
        item = understand_columns(contract)[0]
        self.assertEqual(item.status, "unknown")
        self.assertIsNone(item.lineage[0].database)
        self.assertEqual(item.lineage[0].table, "orders_current")
        self.assertEqual(item.lineage[0].field, "region")
        self.assertIsNone(contract.execution.database)

    def test_missing_columns_is_not_a_known_empty_result(self):
        with self.assertRaisesRegex(ValueError, "columns is unknown"):
            understand_columns(contract_for("SELECT 1", None))

    def test_explicit_empty_columns_returns_empty_list(self):
        self.assertEqual(understand_columns(contract_for(None, [])), [])

    def test_postconstruction_ordinal_corruption_is_rejected(self):
        contract = contract_for("SELECT 1, 2", ["x", "y"])
        contract.execution.columns[1].ordinal = 0
        with self.assertRaises(ValueError):
            understand_columns(contract)

    def test_postconstruction_duplicate_ids_are_rejected(self):
        contract = contract_for("SELECT 1, 2", ["x", "y"])
        contract.execution.columns[1].id = "column_0"
        with self.assertRaises(ValueError):
            understand_columns(contract)

    def test_requires_contract_not_unvalidated_dict(self):
        with self.assertRaises(TypeError):
            understand_columns({})

    def test_new_modules_have_no_execution_or_application_dependencies(self):
        root = Path(__file__).resolve().parents[1] / "app" / "querying" / "result_understanding"
        allowed = {"__future__", "typing", "dataclasses", "datetime", "pydantic", "sqlglot", "result_contract", "models", "sql_parser", "lineage", "filter"}
        for path in root.glob("*.py"):
            with self.subTest(module=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            self.assertIn(alias.name.split(".")[0], allowed)
                    elif isinstance(node, ast.ImportFrom):
                        self.assertIn((node.module or "").split(".")[0], allowed)


if __name__ == "__main__":
    unittest.main()
