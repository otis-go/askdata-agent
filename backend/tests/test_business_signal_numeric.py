"""Numeric Reader checks using hand-written public Phase 2 contracts only.

No fixture executes/parses SQL or calls the BusinessContext builder. The reader
locates canonical cells, never business keys or semantic/alias interpretations.
"""

import ast
import builtins
import copy
import datetime
from dataclasses import FrozenInstanceError
from decimal import (
    Decimal, DefaultContext, FloatOperation, Inexact, InvalidOperation, ROUND_FLOOR,
    Rounded, getcontext, setcontext,
)
import io
from pathlib import Path
import socket
import time
import unittest
from unittest.mock import patch
import uuid

from app.querying.business_signals import numeric
from app.querying.business_signals.policies import NumericRules
from app.querying.result_contract import ColumnMetadata, ExecutionData
from app.querying.result_understanding.models import (
    BusinessContext, ColumnSemantic, FilterInfo, GrainInfo, QueryBindingsInfo,
)


def exact_rules(**changes):
    values = {
        "profile": "decimal_exact_v1",
        "accepted_encodings": ["native_json", "decimal_text"],
    }
    values.update(changes)
    return NumericRules(**values)


def approximate_rules(**changes):
    values = {
        "profile": "reporting_approx_v1",
        "accepted_encodings": ["native_json", "decimal_text"],
        "allow_binary_float": True,
    }
    values.update(changes)
    return NumericRules(**values)


def captured_context(
    value="123.4500", *, dtype="DECIMAL(18,4)", encoding="decimal_text",
    representation="preserved", rows="default", columns="default",
):
    """Construct captured facts directly; the SQL text is deliberately opaque."""
    if columns == "default":
        columns = [ColumnMetadata(
            id="amount-id", ordinal=0, name="untrusted_display_name",
            dtype=dtype, value_encoding=encoding,
            representation_status=representation,
        )]
    if rows == "default":
        rows = [[value]]
    return BusinessContext(
        result_id="captured-numeric-fixture",
        result_contract_version="1",
        execution=ExecutionData(
            database="fixture_database", sql="opaque fixture; never parse me",
            success=True, columns=columns, rows=rows,
        ),
        column_semantics=[ColumnSemantic(
            column_id="semantic-only-id", ordinal=0, output_name="1000000",
            status="unknown",
        )],
        query_bindings=QueryBindingsInfo(status="unknown"),
        grain=GrainInfo(status="unknown"),
        filters=FilterInfo(status="unknown"),
        time_constraints=[], understanding_status="unknown",
    )


def context_signature(context):
    """Include flags and traps, which a precision-only assertion would miss."""
    return (
        context.prec, context.rounding, context.Emin, context.Emax,
        context.capitals, context.clamp,
        tuple(sorted((signal.__name__, enabled) for signal, enabled in context.flags.items())),
        tuple(sorted((signal.__name__, enabled) for signal, enabled in context.traps.items())),
    )


class NumericReaderTests(unittest.TestCase):
    def read(self, context=None, rules=None, **kwargs):
        if context is None:
            context = captured_context()
        if rules is None:
            rules = exact_rules()
        return numeric.read_numeric_value(context, "amount-id", 0, rules, **kwargs)

    def assert_rejected(self, result, status, *, presence=None):
        self.assertEqual(result.status, status)
        self.assertIsNone(result.work_value)
        self.assertTrue(result.issues)
        self.assertIsInstance(result.issues, tuple)
        for issue in result.issues:
            self.assertEqual(issue.stage, "numeric")
            self.assertTrue(issue.code)
        if presence is None:
            self.assertIsNone(result.observed_value)
        else:
            self.assertEqual(result.observed_value.presence, presence)
            self.assertIsNone(result.observed_value.value)

    def test_decimal_preserves_source_text_and_exact_work_value(self):
        result = self.read()
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.raw_value, "123.4500")
        self.assertEqual(result.observed_value.presence, "present")
        self.assertEqual(result.observed_value.value, "123.4500")
        self.assertEqual(result.work_value.as_tuple(), Decimal("123.4500").as_tuple())
        self.assertEqual(result.numeric_quality.source_fidelity, "exact")
        self.assertEqual(result.numeric_quality.source_kind, "decimal_text")
        self.assertEqual(result.numeric_quality.scale, 4)
        self.assertEqual(result.observed_value.source_quality, result.numeric_quality)
        self.assertFalse(result.issues)

    def test_large_precision_decimal_does_not_pass_through_float(self):
        text = "12345678901234567890.123456789012345678"
        result = self.read(captured_context(text, dtype="DECIMAL(38,18)"))
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.work_value.as_tuple(), Decimal(text).as_tuple())
        self.assertEqual(result.observed_value.value, text)
        self.assertNotEqual(result.work_value, Decimal(str(float(text))))

    def test_decimal_text_scientific_notation_is_finite_and_preserved(self):
        for value, dtype in [("1E+3", "DECIMAL(6,0)"), ("1.2300E-2", "DECIMAL(8,6)")]:
            with self.subTest(value=value):
                result = self.read(captured_context(value, dtype=dtype))
                self.assertEqual(result.status, "ready")
                self.assertEqual(result.observed_value.value, value)
                self.assertEqual(result.work_value.as_tuple(), Decimal(value).as_tuple())

    def test_decimal_syntax_rejects_noncanonical_number_guesses(self):
        invalid = [
            "1_000", " 1.0", "1.0 ", "１２.００", "1,2", "NaN", "Infinity",
            "+Infinity", "-Infinity", "sNaN", "0x10", "", ".", "1e", "--1",
        ]
        for value in invalid:
            with self.subTest(value=value):
                result = self.read(captured_context(value))
                self.assert_rejected(result, "unsupported")

    def test_decimal_requires_text_runtime_value(self):
        for value in (123, 123.45, True):
            with self.subTest(value=value):
                self.assert_rejected(self.read(captured_context(value)), "unsupported")

    def test_decimal_physical_precision_and_scale_are_enforced(self):
        for value, dtype in [
            ("1000.00", "DECIMAL(5,2)"), ("1.001", "DECIMAL(5,2)"),
            ("1", "DECIMAL(0,0)"), ("1", "DECIMAL(39,0)"),
            ("1", "DECIMAL(2,3)"), ("1", "DECIMAL"),
        ]:
            with self.subTest(value=value, dtype=dtype):
                self.assert_rejected(self.read(captured_context(value, dtype=dtype)), "unsupported")

    def test_decimal_source_codec_mismatch_is_unsupported(self):
        for value, dtype, encoding in [
            (123, "DECIMAL(10,0)", "native_json"),
            ("123", "INTEGER", "decimal_text"),
            ("1.25", "DOUBLE", "decimal_text"),
        ]:
            with self.subTest(dtype=dtype, encoding=encoding):
                self.assert_rejected(self.read(captured_context(
                    value, dtype=dtype, encoding=encoding,
                ), approximate_rules()), "unsupported")

    def test_integer_native_json_is_exact(self):
        result = self.read(captured_context(100, dtype="INTEGER", encoding="native_json"))
        self.assertEqual(result.status, "ready")
        self.assertIs(type(result.raw_value), int)
        self.assertEqual(result.raw_value, 100)
        self.assertEqual(result.work_value, Decimal("100"))
        self.assertEqual(result.observed_value.value, "100")
        self.assertEqual(result.numeric_quality.source_fidelity, "exact")
        self.assertEqual(result.numeric_quality.source_kind, "integer")

    def test_producer_approved_integer_dtype_whitelist(self):
        for dtype in (
            "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
            "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT",
        ):
            with self.subTest(dtype=dtype):
                result = self.read(captured_context(100, dtype=dtype, encoding="native_json"))
                self.assertEqual(result.status, "ready")
                self.assertEqual(result.work_value, Decimal("100"))

    def test_integer_physical_range_is_checked(self):
        ranges = [
            ("TINYINT", 2**7), ("SMALLINT", 2**15), ("INTEGER", 2**31),
            ("BIGINT", 2**63), ("HUGEINT", 2**127),
            ("UTINYINT", 2**8), ("USMALLINT", 2**16), ("UINTEGER", 2**32),
            ("UBIGINT", 2**64), ("UHUGEINT", 2**128),
        ]
        for dtype, out_of_range in ranges:
            with self.subTest(dtype=dtype):
                self.assert_rejected(self.read(captured_context(
                    out_of_range, dtype=dtype, encoding="native_json",
                )), "unsupported")

    def test_negative_unsigned_integer_is_outside_its_physical_type(self):
        self.assert_rejected(self.read(captured_context(
            -1, dtype="UTINYINT", encoding="native_json",
        )), "unsupported")

    def test_bool_float_and_numeric_string_are_not_native_integer(self):
        for value in (True, False, "100", 100.0):
            with self.subTest(value=value):
                self.assert_rejected(self.read(captured_context(
                    value, dtype="INTEGER", encoding="native_json",
                )), "unsupported")

    def test_integer_text_is_not_a_v1_reader_capability(self):
        result = self.read(captured_context("100", dtype="BIGINT", encoding="integer_text"))
        self.assert_rejected(result, "unsupported")

    def test_binary_float_exact_profile_is_known_incompatibility(self):
        for dtype in ("FLOAT", "DOUBLE"):
            with self.subTest(dtype=dtype):
                self.assert_rejected(self.read(captured_context(
                    0.1, dtype=dtype, encoding="native_json",
                )), "incompatible_context")

    def test_explicit_approximate_profile_preserves_binary_float(self):
        for dtype in ("FLOAT", "DOUBLE"):
            with self.subTest(dtype=dtype):
                value = 0.1 + 0.2
                result = self.read(captured_context(value, dtype=dtype, encoding="native_json"), approximate_rules())
                self.assertEqual(result.status, "ready")
                self.assertIs(type(result.raw_value), float)
                self.assertEqual(result.raw_value, value)
                self.assertEqual(result.observed_value.value, repr(value))
                self.assertEqual(result.work_value.as_tuple(), Decimal(repr(value)).as_tuple())
                self.assertNotEqual(result.work_value, Decimal.from_float(value))
                self.assertEqual(result.numeric_quality.source_kind, "binary_float")
                self.assertEqual(result.numeric_quality.source_fidelity, "approximate")

    def test_approximate_profile_does_not_downgrade_exact_sources(self):
        result = self.read(captured_context(), approximate_rules())
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.numeric_quality.source_fidelity, "exact")

    def test_float_dtype_requires_actual_float(self):
        for value in (1, True, "1.0"):
            with self.subTest(value=value):
                self.assert_rejected(self.read(captured_context(
                    value, dtype="DOUBLE", encoding="native_json",
                ), approximate_rules()), "unsupported")

    def test_nonfinite_float_is_rejected_after_mutation_of_public_rows(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            for rules in (exact_rules(), approximate_rules()):
                with self.subTest(value=value, profile=rules.profile):
                    context = captured_context(1.0, dtype="DOUBLE", encoding="native_json")
                    context.execution.rows[0][0] = value
                    self.assert_rejected(self.read(context, rules), "unsupported")

    def test_varchar_looks_numeric_but_has_no_numeric_codec(self):
        result = self.read(captured_context("100.00", dtype="VARCHAR", encoding="native_json"))
        self.assert_rejected(result, "unsupported")

    def test_unapproved_dtypes_are_not_inferred_from_python_values(self):
        for dtype in ("BOOLEAN", "DATE", "TIMESTAMP", "BIGNUM", "INT", "REAL", "DOUBLE[]"):
            with self.subTest(dtype=dtype):
                self.assert_rejected(self.read(captured_context(
                    100, dtype=dtype, encoding="native_json",
                ), approximate_rules()), "unsupported")

    def test_null_is_sql_null_even_without_non_null_metadata(self):
        for dtype, encoding, representation in [
            ("DECIMAL(18,4)", "decimal_text", "preserved"),
            ("DECIMAL(18,4)", None, None),
            (None, None, None),
        ]:
            with self.subTest(dtype=dtype, encoding=encoding):
                result = self.read(captured_context(
                    None, dtype=dtype, encoding=encoding, representation=representation,
                ))
                self.assert_rejected(result, "insufficient_evidence", presence="sql_null")
                self.assertIsNone(result.raw_value)

    def test_unknown_payload_is_not_an_empty_result_or_null(self):
        for columns in ("default", None):
            with self.subTest(columns=columns):
                result = self.read(captured_context(rows=None, columns=columns))
                self.assert_rejected(result, "insufficient_evidence", presence="unknown_payload")

    def test_known_empty_rows_cannot_supply_an_observed_row(self):
        with self.assertRaises(ValueError):
            self.read(captured_context(rows=[]))

    def test_missing_columns_leave_metadata_unknown(self):
        result = self.read(captured_context(100, columns=None))
        self.assert_rejected(result, "insufficient_evidence", presence="unknown_metadata")

    def test_partial_or_missing_numeric_metadata_does_not_infer_type(self):
        for dtype, encoding, representation in [
            (None, "native_json", "preserved"),
            ("INTEGER", None, "preserved"),
            ("INTEGER", "native_json", None),
            (None, None, None),
        ]:
            with self.subTest(dtype=dtype, encoding=encoding, representation=representation):
                result = self.read(captured_context(
                    100, dtype=dtype, encoding=encoding, representation=representation,
                ))
                self.assert_rejected(result, "insufficient_evidence", presence="unknown_metadata")

    def test_known_lossy_representation_is_incompatible(self):
        self.assert_rejected(self.read(captured_context(representation="lossy")), "incompatible_context")

    def test_known_unsupported_representation_is_unsupported(self):
        self.assert_rejected(self.read(captured_context(representation="unsupported")), "unsupported")

    def test_magnitude_limit_is_strict_and_does_not_clamp(self):
        rules = exact_rules(max_abs_exponent=3)
        self.assertEqual(self.read(captured_context("999.9900"), rules).status, "ready")
        for value in ("1000.0000", "1001.0000"):
            with self.subTest(value=value):
                self.assert_rejected(self.read(captured_context(value), rules), "unsupported")
        self.assert_rejected(self.read(captured_context(
            10**38, dtype="HUGEINT", encoding="native_json",
        )), "unsupported")

    def test_input_scale_limit_is_enforced_without_rounding(self):
        rules = exact_rules(max_input_scale=2)
        result = self.read(captured_context("1.2300"), rules)
        self.assert_rejected(result, "unsupported")
        result = self.read(captured_context("0.000000000000000001", dtype="DECIMAL(38,18)"))
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.work_value, Decimal("0.000000000000000001"))
        self.assert_rejected(self.read(captured_context(
            "0.0000000000000000001", dtype="DECIMAL(38,19)",
        )), "unsupported")

    def test_float_scale_is_subject_to_numeric_rules_too(self):
        result = self.read(captured_context(1e-19, dtype="DOUBLE", encoding="native_json"), approximate_rules())
        self.assert_rejected(result, "unsupported")

    def test_negative_inputs_follow_explicit_policy(self):
        for value, dtype, encoding, rules in [
            ("-1.0000", "DECIMAL(18,4)", "decimal_text", exact_rules()),
            (-1, "INTEGER", "native_json", exact_rules()),
            (-1.0, "DOUBLE", "native_json", approximate_rules()),
        ]:
            with self.subTest(dtype=dtype):
                self.assert_rejected(self.read(captured_context(
                    value, dtype=dtype, encoding=encoding,
                ), rules), "incompatible_context")

    def test_negative_zero_is_zero_not_a_negative_input(self):
        for value, dtype, encoding, rules in [
            ("-0.0000", "DECIMAL(18,4)", "decimal_text", exact_rules()),
            (-0.0, "DOUBLE", "native_json", approximate_rules()),
        ]:
            with self.subTest(dtype=dtype):
                result = self.read(captured_context(value, dtype=dtype, encoding=encoding), rules)
                self.assertEqual(result.status, "ready")
                self.assertTrue(result.work_value.is_zero())
                self.assertTrue(result.work_value.is_signed())

    def test_policy_can_disable_otherwise_supported_encodings(self):
        for context, rules in [
            (captured_context(), exact_rules(accepted_encodings=["native_json"])),
            (captured_context(100, dtype="INTEGER", encoding="native_json"),
             exact_rules(accepted_encodings=["decimal_text"])),
            (captured_context(1.0, dtype="DOUBLE", encoding="native_json"),
             approximate_rules(accepted_encodings=["decimal_text"])),
        ]:
            with self.subTest(dtype=context.execution.columns[0].dtype):
                self.assert_rejected(self.read(context, rules), "incompatible_context")

    def test_input_is_not_quantized_to_future_ratio_or_money_scale(self):
        text = "1.123456789012345678"
        result = self.read(captured_context(text, dtype="DECIMAL(38,18)"))
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.work_value.as_tuple(), Decimal(text).as_tuple())
        self.assertEqual(result.observed_value.value, text)

    def test_explicit_unknown_column_id_is_an_input_error(self):
        with self.assertRaises(ValueError):
            numeric.read_numeric_value(captured_context(), "not-an-id", 0, exact_rules())

    def test_column_id_not_output_name_is_the_only_lookup_key(self):
        columns = [
            ColumnMetadata(id="one", ordinal=0, name="same", dtype="INTEGER",
                           value_encoding="native_json", representation_status="preserved"),
            ColumnMetadata(id="two", ordinal=1, name="same", dtype="DECIMAL(10,2)",
                           value_encoding="decimal_text", representation_status="preserved"),
        ]
        context = captured_context(columns=columns, rows=[[100, "200.50"]])
        first = numeric.read_numeric_value(context, "one", 0, exact_rules())
        second = numeric.read_numeric_value(context, "two", 0, exact_rules())
        self.assertEqual(first.work_value, Decimal("100"))
        self.assertEqual(second.work_value, Decimal("200.50"))
        with self.assertRaises(ValueError):
            numeric.read_numeric_value(context, "same", 0, exact_rules())

    def test_duplicate_ids_introduced_after_model_validation_are_rejected(self):
        context = captured_context()
        duplicate = context.execution.columns[0].model_copy(deep=True)
        duplicate.ordinal = 1
        context.execution.columns.append(duplicate)
        context.execution.rows[0].append("5.0000")
        with self.assertRaises(ValueError):
            self.read(context)

    def test_ordinal_structure_is_revalidated_without_repair(self):
        for ordinal in (-1, 1, 20):
            with self.subTest(ordinal=ordinal):
                context = captured_context()
                context.execution.columns[0].ordinal = ordinal
                before = copy.deepcopy(context)
                with self.assertRaises(ValueError):
                    self.read(context)
                self.assertEqual(context, before)

    def test_mutated_noninteger_ordinals_are_not_coerced(self):
        for ordinal in (False, "0", 0.0):
            with self.subTest(ordinal=ordinal):
                context = captured_context()
                context.execution.columns[0].ordinal = ordinal
                with self.assertRaises(ValueError):
                    self.read(context)

    def test_mutated_row_width_is_rejected(self):
        for row in ([], ["1.0000", "2.0000"]):
            with self.subTest(row=row):
                context = captured_context()
                context.execution.rows[0] = row
                with self.assertRaises(ValueError):
                    self.read(context)

    def test_mutated_noncanonical_scalar_is_a_structural_error(self):
        for value in (Decimal("1.00"), {"amount": "1.00"}, ["1.00"]):
            with self.subTest(value=value):
                context = captured_context()
                context.execution.rows[0][0] = value
                with self.assertRaises(ValueError):
                    self.read(context)

    def test_out_of_range_and_negative_row_index_are_input_errors(self):
        for row_index in (-1, 1, 500):
            with self.subTest(row_index=row_index):
                with self.assertRaises(ValueError):
                    numeric.read_numeric_value(captured_context(), "amount-id", row_index, exact_rules())

    def test_requested_row_index_selects_only_that_canonical_row(self):
        context = captured_context(rows=[["1.0000"], ["2.0000"]])
        result = numeric.read_numeric_value(context, "amount-id", 1, exact_rules())
        self.assertEqual(result.work_value, Decimal("2.0000"))
        self.assertEqual(result.raw_value, "2.0000")

    def test_wrong_public_argument_types_are_not_coerced(self):
        arguments = [
            ({}, "amount-id", 0, exact_rules()),
            (captured_context(), 1, 0, exact_rules()),
            (captured_context(), "amount-id", True, exact_rules()),
            (captured_context(), "amount-id", "0", exact_rules()),
            (captured_context(), "amount-id", 0.0, exact_rules()),
            (captured_context(), "amount-id", 0, {}),
            (captured_context(), "amount-id", 0, None),
        ]
        for values in arguments:
            with self.subTest(types=tuple(type(item).__name__ for item in values)):
                with self.assertRaises(TypeError):
                    numeric.read_numeric_value(*values)

    def test_empty_column_id_is_an_input_error(self):
        with self.assertRaises(ValueError):
            numeric.read_numeric_value(captured_context(), "", 0, exact_rules())

    def test_mutated_rules_are_revalidated_instead_of_silently_defaulted(self):
        rules = exact_rules()
        rules.accepted_encodings.append("integer_text")
        with self.assertRaises(ValueError):
            self.read(rules=rules)
        for changes in ({"decimal_precision": 8}, {"allow_binary_float": True}, {"profile": "unknown"}):
            with self.subTest(changes=changes):
                stale = exact_rules().model_copy(update=changes)
                with self.assertRaises(ValueError):
                    self.read(rules=stale)

    def test_unit_and_evidence_are_not_invented(self):
        result = self.read()
        self.assertIsNone(result.observed_value.unit_id)
        self.assertIsNone(result.observed_value.evidence_id)
        explicit = self.read(unit_id="caller-validated-unit", evidence_id="caller-stable-cell-evidence")
        self.assertEqual(explicit.observed_value.unit_id, "caller-validated-unit")
        self.assertEqual(explicit.observed_value.evidence_id, "caller-stable-cell-evidence")

    def test_optional_bindings_must_be_nonempty_strings_when_supplied(self):
        for name in ("unit_id", "evidence_id"):
            with self.subTest(name=name):
                with self.assertRaises(TypeError):
                    self.read(**{name: 1})
                with self.assertRaises(ValueError):
                    self.read(**{name: ""})

    def test_repeated_and_a_b_a_calls_leave_context_and_rules_unchanged(self):
        context_a = captured_context()
        context_b = captured_context(0.25, dtype="DOUBLE", encoding="native_json")
        rules_a, rules_b = exact_rules(), approximate_rules()
        inputs = (context_a, context_b, rules_a, rules_b)
        before = copy.deepcopy(inputs)
        first = self.read(context_a, rules_a)
        self.read(context_b, rules_b)
        second = self.read(context_a, rules_a)
        self.assertEqual(first, second)
        self.assertEqual(inputs, before)
        self.assertIsNot(first.observed_value, second.observed_value)
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            first.status = "unsupported"

    def test_rejected_reads_also_leave_input_unchanged(self):
        for context, rules in [
            (captured_context(None), exact_rules()),
            (captured_context(representation="lossy"), exact_rules()),
            (captured_context(0.1, dtype="DOUBLE", encoding="native_json"), exact_rules()),
            (captured_context("not numeric"), exact_rules()),
        ]:
            with self.subTest(value=context.execution.rows[0][0]):
                before = copy.deepcopy((context, rules))
                self.read(context, rules)
                self.assertEqual((context, rules), before)

    def test_global_decimal_context_attributes_flags_and_traps_are_unchanged(self):
        original = getcontext().copy()
        try:
            active = getcontext()
            active.prec = 6
            active.rounding = ROUND_FLOOR
            active.capitals = 0
            active.flags[Inexact] = True
            active.flags[Rounded] = True
            active.traps[FloatOperation] = True
            active.traps[InvalidOperation] = True
            before = context_signature(active)
            context = captured_context(
                "12345678901234567890.123456789012345678", dtype="DECIMAL(38,18)",
            )
            result = self.read(context)
            self.assertEqual(result.status, "ready")
            self.assertEqual(result.observed_value.value, "12345678901234567890.123456789012345678")
            self.read(captured_context("not numeric"))
            self.read(captured_context(0.1, dtype="DOUBLE", encoding="native_json"), approximate_rules())
            self.assertEqual(context_signature(getcontext()), before)
            self.assertIs(getcontext(), active)
        finally:
            setcontext(original)

    def test_decimal_work_value_does_not_depend_on_ambient_exponent_limits(self):
        context = captured_context(
            "12345678901234567890.123456789012345678", dtype="DECIMAL(38,18)",
        )
        expected = self.read(context)
        original = getcontext().copy()
        original_default = DefaultContext.copy()
        try:
            active = getcontext()
            active.prec = 2
            active.Emin = -1
            active.Emax = 1
            active.clamp = 1
            for signal in active.traps:
                active.traps[signal] = True
            DefaultContext.prec = 3
            DefaultContext.Emin = -2
            DefaultContext.Emax = 2
            DefaultContext.clamp = 1
            DefaultContext.rounding = ROUND_FLOOR
            DefaultContext.capitals = 0
            for signal in DefaultContext.traps:
                DefaultContext.traps[signal] = True
                DefaultContext.flags[signal] = True
            before = context_signature(active)
            before_default = context_signature(DefaultContext)
            self.assertEqual(self.read(context), expected)
            self.assertEqual(context_signature(getcontext()), before)
            self.assertEqual(context_signature(DefaultContext), before_default)
        finally:
            setcontext(original)
            for name in ("prec", "rounding", "Emin", "Emax", "capitals", "clamp"):
                setattr(DefaultContext, name, getattr(original_default, name))
            DefaultContext.flags = original_default.flags.copy()
            DefaultContext.traps = original_default.traps.copy()

    def test_numeric_module_has_no_forbidden_static_dependencies(self):
        tree = ast.parse(Path(numeric.__file__).read_text(encoding="utf-8"))
        forbidden = {
            "sqlglot", "duckdb", "duckdb_engine", "sql_parser", "builder",
            "agent", "agents", "workflow", "workflows", "retrieval", "llm",
            "openai", "langchain", "langgraph", "database", "dotenv", "time",
            "datetime", "random", "uuid", "os", "socket", "requests", "pathlib",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [alias.name for alias in node.names]
            else:
                continue
            for name in names:
                self.assertFalse(set(name.lower().split(".")) & forbidden, name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, {"eval", "exec", "open", "__import__"})

    def test_reader_path_does_not_touch_io_clock_identity_or_sql(self):
        rules = exact_rules()
        cases = [
            (captured_context(), "ready"),
            (captured_context(None), "insufficient_evidence"),
            (captured_context(representation="lossy"), "incompatible_context"),
            (captured_context("not numeric"), "unsupported"),
        ]
        original_import = builtins.__import__
        forbidden_prefixes = (
            "sqlglot", "duckdb", "app.querying.duckdb_engine",
            "app.querying.result_understanding.builder", "openai", "langchain", "langgraph",
        )

        def guarded_import(name, *args, **kwargs):
            if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_prefixes):
                raise AssertionError(f"forbidden dependency accessed: {name}")
            return original_import(name, *args, **kwargs)

        def forbidden(*args, **kwargs):
            raise AssertionError("Numeric Reader accessed acquisition, clock, or generated identity")

        class ClockForbidden(datetime.datetime):
            now = classmethod(forbidden)
            utcnow = classmethod(forbidden)
            today = classmethod(forbidden)

        with (
            patch.object(builtins, "__import__", guarded_import),
            patch.object(builtins, "open", forbidden),
            patch.object(io, "open", forbidden),
            patch.object(socket, "socket", forbidden),
            patch.object(time, "time", forbidden),
            patch.object(time, "time_ns", forbidden),
            patch.object(time, "monotonic", forbidden),
            patch.object(datetime, "datetime", ClockForbidden),
            patch.object(uuid, "uuid4", forbidden),
            patch.object(uuid, "uuid1", forbidden),
        ):
            for context, expected_status in cases:
                result = self.read(context, rules)
                self.assertEqual(result.status, expected_status)


class NumericColumnEligibilityTests(unittest.TestCase):
    def column(self, **changes):
        values = {
            "id": "selected-metric", "ordinal": 5, "name": "not-a-metric-guess",
            "dtype": "DECIMAL(18,4)", "value_encoding": "decimal_text",
            "representation_status": "preserved",
        }
        values.update(changes)
        return ColumnMetadata(**values)

    def test_public_helper_checks_decimal_and_integer_metadata(self):
        decimal_result = numeric.check_numeric_column(self.column(), exact_rules())
        self.assertEqual(decimal_result, numeric.NumericColumnEligibility(
            "ready", source_kind="decimal_text", decimal_shape=(18, 4),
        ))
        for dtype in (
            "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
            "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT",
        ):
            with self.subTest(dtype=dtype):
                result = numeric.check_numeric_column(self.column(
                    dtype=dtype, value_encoding="native_json",
                ), exact_rules())
                self.assertEqual(result, numeric.NumericColumnEligibility(
                    "ready", source_kind="integer",
                ))

    def test_binary_float_requires_explicit_approximate_profile(self):
        for dtype in ("FLOAT", "DOUBLE"):
            with self.subTest(dtype=dtype):
                column = self.column(dtype=dtype, value_encoding="native_json")
                rejected = numeric.check_numeric_column(column, exact_rules())
                self.assertEqual(rejected.status, "incompatible_context")
                self.assertEqual(rejected.code, "BINARY_FLOAT_NOT_ALLOWED")
                self.assertEqual(rejected.source_kind, "binary_float")
                accepted = numeric.check_numeric_column(column, approximate_rules())
                self.assertEqual(accepted.status, "ready")
                self.assertEqual(accepted.source_kind, "binary_float")

    def test_approximate_profile_accepts_exact_metadata_without_relabeling(self):
        result = numeric.check_numeric_column(self.column(), approximate_rules())
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.source_kind, "decimal_text")
        self.assertEqual(result.decimal_shape, (18, 4))

    def test_unknown_and_empty_result_metadata_are_insufficient(self):
        for changes in (
            {"dtype": None}, {"value_encoding": None}, {"representation_status": None},
            {"dtype": None, "value_encoding": None, "representation_status": None},
        ):
            with self.subTest(changes=changes):
                result = numeric.check_numeric_column(self.column(**changes), exact_rules())
                self.assertEqual(result.status, "insufficient_evidence")
                self.assertEqual(result.code, "UNKNOWN_NUMERIC_METADATA")
        # Phase 1 leaves representation unknown when it saw no non-NULL rows.
        context = captured_context(rows=[], representation=None)
        with patch.object(numeric, "read_numeric_value", side_effect=AssertionError("must not read row zero")):
            result = numeric.check_numeric_column(context.execution.columns[0], exact_rules())
        self.assertEqual(result.status, "insufficient_evidence")

    def test_known_representation_failures_precede_unknown_other_metadata(self):
        for representation, status, code in (
            ("unsupported", "unsupported", "UNSUPPORTED_REPRESENTATION"),
            ("lossy", "incompatible_context", "LOSSY_REPRESENTATION"),
        ):
            with self.subTest(representation=representation):
                result = numeric.check_numeric_column(self.column(
                    dtype=None, value_encoding=None, representation_status=representation,
                ), exact_rules())
                self.assertEqual((result.status, result.code), (status, code))

    def test_unsupported_codecs_and_dtype_codec_mismatches_are_not_policy_failures(self):
        cases = [
            ("BIGINT", "integer_text", "UNSUPPORTED_ENCODING"),
            ("DATE", "iso_date", "UNSUPPORTED_ENCODING"),
            ("TIMESTAMP", "iso_datetime", "UNSUPPORTED_ENCODING"),
            ("DECIMAL(18,4)", "native_json", "CODEC_VALUE_MISMATCH"),
            ("INTEGER", "decimal_text", "CODEC_VALUE_MISMATCH"),
            ("DOUBLE", "decimal_text", "CODEC_VALUE_MISMATCH"),
        ]
        for dtype, encoding, code in cases:
            for rules in (exact_rules(), approximate_rules()):
                with self.subTest(dtype=dtype, encoding=encoding, profile=rules.profile):
                    result = numeric.check_numeric_column(self.column(
                        dtype=dtype, value_encoding=encoding,
                    ), rules)
                    self.assertEqual((result.status, result.code), ("unsupported", code))

    def test_dtype_capability_is_shared_with_reader_without_name_guessing(self):
        for dtype in (
            "DECIMAL(0,0)", "DECIMAL(39,0)", "DECIMAL(2,3)", "DECIMAL",
            "VARCHAR", "BOOLEAN", "BIGNUM", "INT", "REAL", "DOUBLE[]",
        ):
            with self.subTest(dtype=dtype):
                result = numeric.check_numeric_column(self.column(
                    dtype=dtype, value_encoding="native_json", name="actual_paid_sales",
                ), approximate_rules())
                self.assertEqual(result.status, "unsupported")
                self.assertEqual(result.code, "UNSUPPORTED_DTYPE")

    def test_supported_encoding_excluded_by_policy_is_incompatible(self):
        for column, rules in (
            (self.column(), exact_rules(accepted_encodings=["native_json"])),
            (self.column(dtype="INTEGER", value_encoding="native_json"),
             exact_rules(accepted_encodings=["decimal_text"])),
            (self.column(dtype="DOUBLE", value_encoding="native_json"),
             approximate_rules(accepted_encodings=["decimal_text"])),
        ):
            with self.subTest(dtype=column.dtype):
                result = numeric.check_numeric_column(column, rules)
                self.assertEqual(result.status, "incompatible_context")
                self.assertEqual(result.code, "ENCODING_NOT_ALLOWED")

    def test_column_readiness_does_not_certify_cell_null_type_range_or_scale(self):
        cases = [
            (captured_context(None), exact_rules(), "SQL_NULL"),
            (captured_context(True), exact_rules(), "CODEC_VALUE_MISMATCH"),
            (captured_context("1000.00", dtype="DECIMAL(5,2)"), exact_rules(), "DECIMAL_DTYPE_RANGE"),
            (captured_context("1.2300"), exact_rules(max_input_scale=2), "SCALE_EXCEEDED"),
            (captured_context("-1.0000"), exact_rules(), "NEGATIVE_INPUT_NOT_ALLOWED"),
        ]
        for context, rules, code in cases:
            with self.subTest(code=code):
                column_result = numeric.check_numeric_column(context.execution.columns[0], rules)
                self.assertEqual(column_result.status, "ready")
                cell_result = numeric.read_numeric_value(context, "amount-id", 0, rules)
                self.assertNotEqual(cell_result.status, "ready")
                self.assertEqual(cell_result.issues[0].code, code)

    def test_reader_retains_runtime_failure_order_before_metadata_or_policy(self):
        cases = [
            (captured_context(None, representation="unsupported"), "SQL_NULL"),
            (captured_context(True, dtype="DOUBLE", encoding="native_json"), "CODEC_VALUE_MISMATCH"),
            (captured_context(123, encoding="decimal_text"), "CODEC_VALUE_MISMATCH"),
        ]
        nonfinite = captured_context(1.0, dtype="DOUBLE", encoding="native_json", representation="lossy")
        nonfinite.execution.rows[0][0] = float("nan")
        cases.append((nonfinite, "NONFINITE_VALUE"))
        for context, code in cases:
            with self.subTest(code=code):
                result = numeric.read_numeric_value(
                    context, "amount-id", 0, exact_rules(accepted_encodings=["native_json"]),
                )
                self.assertEqual(result.issues[0].code, code)

    def test_helper_revalidates_numeric_rules_snapshot(self):
        mutated = exact_rules()
        mutated.accepted_encodings.append("integer_text")
        with self.assertRaises(ValueError):
            numeric.check_numeric_column(self.column(), mutated)
        for changes in ({"allow_binary_float": True}, {"profile": "unknown"}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    numeric.check_numeric_column(self.column(), exact_rules().model_copy(update=changes))

    def test_helper_rejects_wrong_argument_types_and_invalid_metadata(self):
        with self.assertRaises(TypeError):
            numeric.check_numeric_column({}, exact_rules())
        with self.assertRaises(TypeError):
            numeric.check_numeric_column(self.column(), {})
        for changes in ({"dtype": 1}, {"value_encoding": 1}, {"representation_status": "unknown"}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    numeric.check_numeric_column(self.column().model_copy(update=changes), exact_rules())

    def test_helper_is_deterministic_pure_and_has_frozen_result(self):
        column_a, rules_a = self.column(), exact_rules()
        column_b = self.column(dtype="DOUBLE", value_encoding="native_json")
        rules_b = approximate_rules()
        inputs = (column_a, rules_a, column_b, rules_b)
        before = copy.deepcopy(inputs)
        decimal_before = context_signature(getcontext())
        with patch.object(numeric, "read_numeric_value", side_effect=AssertionError("must not read rows")):
            first = numeric.check_numeric_column(column_a, rules_a)
            numeric.check_numeric_column(column_b, rules_b)
            second = numeric.check_numeric_column(column_a, rules_a)
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertEqual(inputs, before)
        self.assertEqual(context_signature(getcontext()), decimal_before)
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            first.status = "unsupported"


if __name__ == "__main__":
    unittest.main()
