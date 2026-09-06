"""Representation evidence, without changing the SQL or bounded-fetch path."""

from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from math import isinf, isnan
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import UUID

import duckdb
from pydantic import ValidationError

from app.querying.duckdb_engine import DuckDbEngine
from app.querying.result_contract import ColumnMetadata, ExecutionData, ResultContract


class RepresentationStatusTest(unittest.TestCase):
    def setUp(self):
        self.engine = DuckDbEngine()

    def execute_recorded(self, sql):
        """Real driver values; the wrapper permits only the existing one fetch."""
        statements = []
        fetches = []
        observed_rows = []

        @contextmanager
        def recorded_connect(database):
            self.assertEqual(database, "askdata_mock")
            connection = duckdb.connect(":memory:")
            try:
                def execute(statement):
                    statements.append(statement)
                    cursor = connection.execute(statement)

                    def fetchmany(size):
                        raw_rows = cursor.fetchmany(size)
                        fetches.append((size, len(raw_rows)))
                        observed_rows.extend(raw_rows)
                        return raw_rows

                    return SimpleNamespace(
                        description=cursor.description, fetchmany=fetchmany,
                    )

                # There is intentionally no fetchall, second cursor, or query
                # helper available through the wrapper.
                yield SimpleNamespace(execute=execute)
            finally:
                connection.close()

        with patch.object(self.engine, "connect", recorded_connect):
            result = self.engine.execute("askdata_mock", sql)
        self.assertTrue(result.success, result.error)
        self.assertEqual(statements, [sql])
        self.assertEqual(fetches, [(201, len(observed_rows))])
        self.assertEqual(
            ResultContract.model_validate_json(result.result_contract.model_dump_json()),
            result.result_contract,
        )
        return result, observed_rows

    def test_approved_native_types_are_preserved(self):
        result, raw_rows = self.execute_recorded(
            "SELECT 7::INTEGER AS i, 8::BIGINT AS big, 1.25::FLOAT AS f, "
            "2.5::DOUBLE AS d, TRUE AS b, 'hello' AS text"
        )
        execution = result.result_contract.execution
        self.assertEqual(
            [column.dtype for column in execution.columns],
            ["INTEGER", "BIGINT", "FLOAT", "DOUBLE", "BOOLEAN", "VARCHAR"],
        )
        self.assertEqual(execution.rows, [list(raw_rows[0])])
        self.assertEqual(
            [column.representation_status for column in execution.columns],
            ["preserved"] * 6,
        )
        self.assertEqual(
            [column.value_encoding for column in execution.columns],
            ["native_json"] * 6,
        )
        self.assertEqual(result.rows, [{
            "i": 7, "big": 8, "f": 1.25, "d": 2.5, "b": True, "text": "hello",
        }])

    def test_finite_date_and_microsecond_timestamp_are_preserved(self):
        result, raw_rows = self.execute_recorded(
            "SELECT DATE '2026-09-06' AS day, "
            "TIMESTAMP '2026-09-06 12:34:56.123456' AS moment"
        )
        execution = result.result_contract.execution
        self.assertEqual(raw_rows, [(date(2026, 9, 6), datetime(2026, 9, 6, 12, 34, 56, 123456))])
        self.assertEqual(execution.rows, [["2026-09-06", "2026-09-06T12:34:56.123456"]])
        self.assertEqual(
            [column.representation_status for column in execution.columns],
            ["preserved", "preserved"],
        )
        self.assertEqual(
            [column.value_encoding for column in execution.columns],
            ["iso_date", "iso_datetime"],
        )

    def test_finite_decimal_text_is_preserved_without_legacy_float_claim(self):
        amount = "123456789012345678.12"
        result, raw_rows = self.execute_recorded(
            f"SELECT CAST('{amount}' AS DECIMAL(20,2)) AS amount"
        )
        column = result.result_contract.execution.columns[0]
        self.assertEqual(raw_rows, [(Decimal(amount),)])
        self.assertEqual(result.result_contract.execution.rows, [[amount]])
        self.assertEqual(column.value_encoding, "decimal_text")
        self.assertEqual(column.representation_status, "preserved")
        self.assertIs(type(result.rows[0]["amount"]), float)
        self.assertEqual(result.rows[0]["amount"], float(Decimal(amount)))
        self.assertNotEqual(Decimal.from_float(result.rows[0]["amount"]), Decimal(amount))

    def test_second_and_millisecond_timestamps_keep_finite_and_infinite_distinct_statuses(self):
        result, _ = self.execute_recorded(
            "SELECT '2026-09-06 12:34:56'::TIMESTAMP_S AS seconds, "
            "'2026-09-06 12:34:56.123'::TIMESTAMP_MS AS milliseconds, "
            "'infinity'::TIMESTAMP_S AS positive, '-infinity'::TIMESTAMP_MS AS negative"
        )
        self.assertEqual(
            [column.representation_status for column in result.result_contract.execution.columns],
            ["preserved", "preserved", None, None],
        )

    def test_timestamp_ns_aligned_and_unaligned_are_both_unknown(self):
        result, raw_rows = self.execute_recorded(
            "SELECT '2026-01-01 00:00:00.123456000'::TIMESTAMP_NS AS aligned, "
            "'2026-01-01 00:00:00.123456789'::TIMESTAMP_NS AS unaligned"
        )
        # The observer knows the literals, but the producer may use only dtype
        # and fetched values; the latter cannot distinguish these originals.
        self.assertEqual(raw_rows[0][0], raw_rows[0][1])
        execution = result.result_contract.execution
        self.assertEqual([column.dtype for column in execution.columns], ["TIMESTAMP_NS"] * 2)
        self.assertEqual([column.value_encoding for column in execution.columns], ["iso_datetime"] * 2)
        self.assertEqual([column.representation_status for column in execution.columns], [None, None])
        self.assertEqual(execution.rows, [["2026-01-01T00:00:00.123456"] * 2])

    def test_date_infinity_and_finite_extrema_are_ambiguous(self):
        result, raw_rows = self.execute_recorded(
            "SELECT DATE 'infinity' AS positive, DATE '9999-12-31' AS finite_max, "
            "DATE '-infinity' AS negative, DATE '0001-01-01' AS finite_min"
        )
        self.assertEqual(raw_rows, [(date.max, date.max, date.min, date.min)])
        execution = result.result_contract.execution
        self.assertEqual([column.representation_status for column in execution.columns], [None] * 4)
        self.assertEqual([column.value_encoding for column in execution.columns], ["iso_date"] * 4)
        self.assertEqual(execution.rows, [["9999-12-31", "9999-12-31", "0001-01-01", "0001-01-01"]])

    def test_timestamp_infinity_and_finite_extrema_are_ambiguous(self):
        result, raw_rows = self.execute_recorded(
            "SELECT TIMESTAMP 'infinity' AS positive, "
            "TIMESTAMP '9999-12-31 23:59:59.999999' AS finite_max, "
            "TIMESTAMP '-infinity' AS negative, "
            "TIMESTAMP '0001-01-01 00:00:00' AS finite_min"
        )
        self.assertEqual(raw_rows, [(datetime.max, datetime.max, datetime.min, datetime.min)])
        execution = result.result_contract.execution
        self.assertEqual([column.representation_status for column in execution.columns], [None] * 4)
        self.assertEqual([column.value_encoding for column in execution.columns], ["iso_datetime"] * 4)

    def test_empty_result_does_not_claim_preservation(self):
        result, raw_rows = self.execute_recorded("SELECT 1::INTEGER AS value WHERE FALSE")
        self.assertEqual(raw_rows, [])
        execution = result.result_contract.execution
        self.assertEqual(execution.rows, [])
        self.assertEqual(execution.columns[0].dtype, "INTEGER")
        self.assertIsNone(execution.columns[0].representation_status)
        self.assertIsNone(execution.columns[0].value_encoding)

    def test_all_null_columns_remain_unknown_even_for_special_dtypes(self):
        result, raw_rows = self.execute_recorded(
            "SELECT NULL::INTEGER AS number, NULL::DATE AS day, "
            "NULL::TIMESTAMP_NS AS moment, NULL::UUID AS identifier, "
            "NULL::BLOB AS payload, NULL::INTEGER[] AS items"
        )
        self.assertEqual(raw_rows, [(None,) * 6])
        execution = result.result_contract.execution
        self.assertEqual(execution.rows, [[None] * 6])
        self.assertEqual([column.representation_status for column in execution.columns], [None] * 6)
        self.assertEqual([column.value_encoding for column in execution.columns], [None] * 6)

    def test_null_does_not_override_preserved_non_null_observations(self):
        result, _ = self.execute_recorded(
            "SELECT NULL::INTEGER AS value UNION ALL SELECT 7::INTEGER AS value"
        )
        execution = result.result_contract.execution
        self.assertEqual(execution.rows, [[None], [7]])
        self.assertEqual(execution.columns[0].representation_status, "preserved")
        self.assertEqual(execution.columns[0].value_encoding, "native_json")

    def test_one_ambiguous_observation_prevents_column_preserved_claim(self):
        result, _ = self.execute_recorded(
            "SELECT DATE '2026-09-06' AS value UNION ALL SELECT DATE 'infinity' AS value"
        )
        execution = result.result_contract.execution
        self.assertEqual(execution.rows, [["2026-09-06"], ["9999-12-31"]])
        self.assertIsNone(execution.columns[0].representation_status)
        self.assertEqual(execution.columns[0].value_encoding, "iso_date")

    def assert_unsupported(self, expression):
        result, raw_rows = self.execute_recorded(f"SELECT {expression} AS value")
        execution = result.result_contract.execution
        self.assertTrue(execution.success)
        self.assertEqual(execution.columns[0].representation_status, "unsupported")
        self.assertIsNone(execution.columns[0].value_encoding)
        self.assertIsNone(execution.rows)
        self.assertIsNone(execution.completeness)
        self.assertEqual(execution.returned_rows, 1)
        self.assertEqual(execution.total_rows, 1)
        self.assertIs(execution.truncated, False)
        self.assertIsNotNone(result.rows[0]["value"])
        self.assertIs(type(result.rows[0]["value"]), type(raw_rows[0][0]))
        return result.rows[0]["value"], raw_rows[0][0]

    def test_list_has_no_approved_codec_and_legacy_list_is_unchanged(self):
        value, raw = self.assert_unsupported("[1, 2]")
        self.assertEqual(value, [1, 2])
        self.assertEqual(value, raw)

    def test_uuid_has_no_approved_codec_and_legacy_uuid_is_unchanged(self):
        value, raw = self.assert_unsupported("'00000000-0000-0000-0000-000000000001'::UUID")
        self.assertIsInstance(value, UUID)
        self.assertEqual(value, raw)

    def test_blob_has_no_approved_codec_and_legacy_bytes_are_unchanged(self):
        value, raw = self.assert_unsupported("'hello'::BLOB")
        self.assertEqual(value, b"hello")
        self.assertEqual(value, raw)

    def test_nan_has_no_approved_codec_and_is_not_fake_null(self):
        value, raw = self.assert_unsupported("'NaN'::DOUBLE")
        self.assertTrue(isnan(value))
        self.assertTrue(isnan(raw))

    def test_numeric_positive_and_negative_infinity_are_unsupported(self):
        for text, sign in (("Infinity", 1), ("-Infinity", -1)):
            with self.subTest(text=text):
                value, raw = self.assert_unsupported(f"'{text}'::DOUBLE")
                self.assertTrue(isinf(value))
                self.assertEqual(value, raw)
                self.assertGreater(value * sign, 0)

    def test_one_unsupported_value_withholds_rows_not_other_column_metadata(self):
        result, _ = self.execute_recorded("SELECT 7::INTEGER AS number, [1, 2] AS items")
        execution = result.result_contract.execution
        self.assertEqual(
            [column.representation_status for column in execution.columns],
            ["preserved", "unsupported"],
        )
        self.assertIsNone(execution.rows)
        self.assertEqual(result.rows, [{"number": 7, "items": [1, 2]}])

    def test_demonstrably_irreversible_codec_conversion_is_lossy(self):
        original = datetime(2026, 9, 6, 12, 34, 56, 123456)
        encoded = original.replace(microsecond=0).isoformat()
        # This is a controlled codec test, NOT a claim that fetchmany can
        # retrospectively reveal discarded TIMESTAMP_NS nanoseconds.
        self.assertEqual(
            self.engine._representation_status(original, encoded, "iso_datetime", "TIMESTAMP"),
            "lossy",
        )
        self.assertEqual(
            self.engine._representation_status(original, original.isoformat(), "iso_datetime", "TIMESTAMP"),
            "preserved",
        )

    def test_proven_loss_propagates_to_column_status_without_changing_raw_rows(self):
        first = datetime(2026, 9, 6, 12, 34, 56)
        second = datetime(2026, 9, 6, 12, 34, 56, 123456)
        raw_rows = [(None,), (first,), (second,)]
        column = ColumnMetadata(id="column_0", ordinal=0, name="moment", dtype="TIMESTAMP")

        def truncating_test_codec(value):
            return value.replace(microsecond=0).isoformat(), "iso_datetime"

        with patch.object(DuckDbEngine, "_contract_value", side_effect=truncating_test_codec):
            rows = DuckDbEngine._contract_rows([column], raw_rows)
        self.assertEqual(rows, [[None], [first.isoformat()], [first.isoformat()]])
        self.assertEqual(column.representation_status, "lossy")
        self.assertEqual(column.value_encoding, "iso_datetime")
        self.assertEqual(raw_rows, [(None,), (first,), (second,)])
        self.assertEqual(second.microsecond, 123456)

    def test_missing_physical_dtype_does_not_prove_preservation(self):
        column = ColumnMetadata(id="column_0", ordinal=0, name="value")
        rows = DuckDbEngine._contract_rows([column], [(7,)])
        self.assertEqual(rows, [[7]])
        self.assertEqual(column.value_encoding, "native_json")
        self.assertIsNone(column.representation_status)

    def test_reused_column_metadata_does_not_keep_stale_preservation_evidence(self):
        column = ColumnMetadata(id="column_0", ordinal=0, name="day", dtype="DATE")
        DuckDbEngine._contract_rows([column], [(date(2026, 9, 6),)])
        self.assertEqual(column.representation_status, "preserved")
        DuckDbEngine._contract_rows([column], [(date.max,)])
        self.assertIsNone(column.representation_status)
        self.assertEqual(column.value_encoding, "iso_date")
        self.assertEqual(DuckDbEngine._contract_rows([column], [(None,)]), [[None]])
        self.assertIsNone(column.representation_status)
        self.assertIsNone(column.value_encoding)

    def test_unapproved_physical_types_are_not_preserved_merely_as_strings(self):
        for expression in ("'101'::BIT", "'{\"answer\":42}'::JSON"):
            with self.subTest(expression=expression):
                value, raw = self.assert_unsupported(expression)
                self.assertIs(type(value), str)
                self.assertEqual(value, raw)

    def test_dtype_python_value_mismatch_has_no_approved_codec(self):
        for dtype, value in (("DATE", "2026-09-06"), ("INTEGER", True), ("VARCHAR", 7)):
            with self.subTest(dtype=dtype, value=value):
                column = ColumnMetadata(id="column_0", ordinal=0, name="value", dtype=dtype)
                self.assertIsNone(DuckDbEngine._contract_rows([column], [(value,)]))
                self.assertEqual(column.representation_status, "unsupported")
                self.assertIsNone(column.value_encoding)

    def test_representation_status_applies_only_to_returned_samples(self):
        values = ", ".join(
            f"({ordinal}, DATE '2026-09-06')" for ordinal in range(200)
        )
        result, raw_rows = self.execute_recorded(
            f"SELECT value FROM (VALUES {values}, (200, DATE 'infinity')) "
            "AS sample(ordinal, value) ORDER BY ordinal"
        )
        self.assertEqual(len(raw_rows), 201)
        self.assertEqual(raw_rows[-1], (date.max,))
        execution = result.result_contract.execution
        self.assertEqual(execution.returned_rows, 200)
        self.assertIs(execution.truncated, True)
        self.assertIsNone(execution.total_rows)
        self.assertEqual(execution.completeness, "partial_query_output")
        self.assertEqual(execution.rows, [["2026-09-06"]] * 200)
        self.assertEqual(execution.columns[0].representation_status, "preserved")

    def test_four_states_round_trip_and_unknown_string_is_rejected(self):
        for status in ("preserved", "lossy", "unsupported", None):
            with self.subTest(status=status):
                contract = ResultContract(
                    result_id="representation-test",
                    execution=ExecutionData(columns=[ColumnMetadata(
                        id="column_0", ordinal=0, name="value",
                        representation_status=status,
                    )]),
                )
                restored = ResultContract.model_validate_json(contract.model_dump_json())
                self.assertEqual(restored.execution.columns[0].representation_status, status)
        with self.assertRaises(ValidationError):
            ColumnMetadata(id="column_0", ordinal=0, name="value", representation_status="unknown")


if __name__ == "__main__":
    unittest.main()
