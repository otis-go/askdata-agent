"""S2 over captured facts and real Compatibility/Alignment producer receipts.

The fixtures declare their sources and authority explicitly. They do not parse
or execute SQL, manufacture successful receipts, or infer metrics from aliases.
"""

import ast
import copy
from decimal import Decimal, Inexact, Rounded, getcontext, localcontext
from fractions import Fraction
import hashlib
import inspect
import json
import socket
import time
import unittest
import uuid
from unittest.mock import patch

from app.querying.business_signals import alignment, compatibility, sales_change
from app.querying.business_signals.models import AlignmentResult, BusinessSignal, ContextCompatibility, SignalInput
from app.querying.business_signals.policies import NumericRules, SalesChangePolicy
from app.querying.business_signals.sales_change_policy import monthly_sales_change_v1
from test_business_signal_compatibility import (
    captured_context, remove_declaration, replace_declaration, supplied_input,
)


def s2_policy(**changes):
    numeric = changes.pop("numeric_rules", None)
    if isinstance(numeric, dict):
        numeric = NumericRules.model_validate(numeric)
    policy = monthly_sales_change_v1(
        database="askdata_mock", accepted_issuer_kinds=["fixture_catalog"],
        accepted_issuer_refs=["demo_v1"], numeric_rules=numeric,
    )
    return SalesChangePolicy.model_validate({**policy.model_dump(), **changes})


def s2_input(role, rows, *, dtype="DECIMAL(18,2)", metric_first=False,
             lower=None, upper=None):
    raw = captured_context("s2", role, lower=lower, upper=upper)
    raw["execution"].update(rows=copy.deepcopy(rows), returned_rows=len(rows), total_rows=len(rows))
    raw["execution"]["columns"][1].update(
        dtype=dtype, value_encoding="decimal_text" if dtype.startswith("DECIMAL(") else "native_json",
    )
    if metric_first:
        raw["execution"]["columns"].reverse()
        raw["column_semantics"].reverse()
        for index, column in enumerate(raw["execution"]["columns"]):
            column.update(ordinal=index, name="same_display_alias")
        for index, semantic in enumerate(raw["column_semantics"]):
            semantic.update(ordinal=index, output_name="same_display_alias")
        raw["execution"]["rows"] = [[row[1], row[0]] for row in rows]
    return supplied_input("s2", role, raw)


def s2_inputs(current=None, baseline=None, *, current_dtype="DECIMAL(18,2)",
              baseline_dtype="DECIMAL(18,2)", metric_first=False):
    return {
        "current": s2_input("current", current if current is not None else [["华东", "150.00"]],
                            dtype=current_dtype, metric_first=metric_first),
        "baseline": s2_input("baseline", baseline if baseline is not None else [["华东", "100.00"]],
                             dtype=baseline_dtype, metric_first=metric_first),
    }


def qualify(inputs, policy=None, *, operation="compare"):
    policy = policy or s2_policy()
    receipt = compatibility.check_context_compatibility(inputs, policy, operation=operation)
    aligned = alignment.align_context_keys(inputs, receipt, policy)
    return receipt, aligned, policy


def fraction_rate_oracle(current, baseline):
    """Independent integer HALF_EVEN rounding; no Decimal division or quantize."""
    ratio = (Fraction(Decimal(current)) - Fraction(Decimal(baseline))) / Fraction(Decimal(baseline))
    scaled = abs(ratio) * 10**12
    whole, remainder = divmod(scaled.numerator, scaled.denominator)
    if remainder * 2 > scaled.denominator or (remainder * 2 == scaled.denominator and whole % 2):
        whole += 1
    sign = "-" if ratio < 0 else ""
    return f"{sign}{whole // 10**12}.{whole % 10**12:012d}", ratio


def decimal_state():
    context = getcontext()
    return (context.prec, context.rounding, context.Emin, context.Emax, context.capitals,
            context.clamp, dict(context.flags), dict(context.traps))


def rename_source_field(value, old, new):
    if isinstance(value, dict):
        if value.get("field") == old:
            value["field"] = new
        for nested in value.values():
            rename_source_field(nested, old, new)
    elif isinstance(value, list):
        for nested in value:
            rename_source_field(nested, old, new)


class SalesChangeTests(unittest.TestCase):
    def compute(self, inputs=None, policy=None, receipt=None, aligned=None):
        inputs = s2_inputs() if inputs is None else inputs
        if receipt is None or aligned is None:
            receipt, aligned, policy = qualify(inputs, policy)
        return sales_change.compute_sales_change(inputs["current"], inputs["baseline"], receipt, aligned, policy)

    def approved(self, inputs=None, policy=None, *, operation="compare"):
        inputs = s2_inputs() if inputs is None else inputs
        receipt, aligned, policy = qualify(inputs, policy, operation=operation)
        self.assertEqual(receipt.status, "compatible", receipt.model_dump())
        self.assertEqual(aligned.status, "aligned", aligned.model_dump())
        return inputs, receipt, aligned, policy

    def one(self, current="150.00", baseline="100.00", *, dtype="DECIMAL(18,2)", policy=None):
        inputs = s2_inputs([["华东", current]], [["华东", baseline]], current_dtype=dtype, baseline_dtype=dtype)
        inputs, receipt, aligned, policy = self.approved(inputs, policy)
        result = self.compute(inputs, policy, receipt, aligned)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], BusinessSignal)
        return result[0]

    def assert_gate_rejects(self, inputs, receipt, aligned, policy, *, status="incompatible_context"):
        with patch.object(sales_change, "read_numeric_value", side_effect=AssertionError("numeric gate bypass")):
            signals = self.compute(inputs, policy, receipt, aligned)
        self.assertTrue(signals)
        self.assertTrue(all(signal.status == status for signal in signals), signals)
        for signal in signals:
            self.assertEqual(set(signal.computed_value), {"absolute_change", "change_rate"})
            self.assertTrue(all(value.status != "computed" and value.value is None
                                for value in signal.computed_value.values()))
        return signals

    def test_growth_has_absolute_and_relative_change(self):
        signal = self.one()
        self.assertEqual(signal.status, "computed")
        self.assertEqual(signal.computed_value["absolute_change"].value, "50.00")
        self.assertEqual(signal.computed_value["change_rate"].value, "0.500000000000")

    def test_decline_is_a_valid_negative_change(self):
        signal = self.one("80.00", "100.00")
        self.assertEqual(signal.status, "computed")
        self.assertEqual(signal.computed_value["absolute_change"].value, "-20.00")
        self.assertEqual(signal.computed_value["change_rate"].value, "-0.200000000000")

    def test_requested_100_vs_200_decline_is_minus_100_and_minus_half(self):
        signal = self.one("100.00", "200.00")
        self.assertEqual(signal.status, "computed")
        self.assertEqual(signal.computed_value["absolute_change"].value, "-100.00")
        self.assertEqual(signal.computed_value["change_rate"].value, "-0.500000000000")

    def test_equal_sales_produce_zero_change(self):
        signal = self.one("100.00", "100.00")
        self.assertEqual(signal.status, "computed")
        self.assertEqual(Decimal(signal.computed_value["absolute_change"].value), Decimal(0))
        self.assertEqual(Decimal(signal.computed_value["change_rate"].value), Decimal(0))

    def test_zero_current_is_a_full_decline(self):
        signal = self.one("0.00", "100.00")
        self.assertEqual(signal.status, "computed")
        self.assertEqual(signal.computed_value["absolute_change"].value, "-100.00")
        self.assertEqual(signal.computed_value["change_rate"].value, "-1.000000000000")

    def test_positive_current_with_zero_baseline_keeps_absolute_change(self):
        signal = self.one("150.00", "0.00")
        self.assertEqual(signal.status, "undefined")
        absolute, rate = (signal.computed_value[name] for name in ("absolute_change", "change_rate"))
        self.assertEqual((absolute.status, absolute.value), ("computed", "150.00"))
        self.assertEqual((rate.status, rate.value, rate.reason_code), ("undefined", None, "ZERO_BASELINE"))

    def test_zero_over_zero_is_undefined_only_for_the_rate(self):
        signal = self.one("0.00", "0.00")
        self.assertEqual(signal.status, "undefined")
        self.assertEqual(signal.computed_value["absolute_change"].status, "computed")
        self.assertEqual(Decimal(signal.computed_value["absolute_change"].value), Decimal(0))
        self.assertEqual(signal.computed_value["change_rate"].reason_code, "ZERO_BASELINE")

    def test_negative_zero_baseline_is_zero(self):
        signal = self.one("10.00", "-0.00")
        self.assertEqual(signal.status, "undefined")
        self.assertEqual(signal.computed_value["absolute_change"].value, "10.00")
        self.assertEqual(signal.computed_value["change_rate"].reason_code, "ZERO_BASELINE")

    def test_multiple_regions_use_business_keys_after_row_reorder(self):
        inputs = s2_inputs([["华北", "100.00"], ["华东", "90.00"], ["华南", "50.00"]],
                           [["华南", "250.00"], ["华北", "400.00"], ["华东", "30.00"]])
        signals = self.compute(inputs)
        expected = {"华北": ("-300.00", "-0.750000000000", 0, 1),
                    "华东": ("60.00", "2.000000000000", 1, 2),
                    "华南": ("-200.00", "-0.800000000000", 2, 0)}
        self.assertEqual(len(signals), 3)
        for signal in signals:
            key = signal.business_key.components[0].normalized_value
            absolute, rate, current_index, baseline_index = expected[key]
            self.assertEqual(signal.computed_value["absolute_change"].value, absolute)
            self.assertEqual(signal.computed_value["change_rate"].value, rate)
            self.assertEqual([item.row_index for item in signal.evidence], [current_index, baseline_index])
            self.assertTrue(all(item.business_key.components[0].normalized_value == key for item in signal.evidence))

    def test_metric_is_selected_by_column_id_and_ordinal_not_duplicate_alias(self):
        signal = self.compute(s2_inputs(metric_first=True))[0]
        self.assertEqual(signal.computed_value["absolute_change"].value, "50.00")
        self.assertTrue(all((item.column_id, item.ordinal, item.row_index) == ("col_m", 0, 0)
                            for item in signal.evidence))

    def test_missing_baseline_blocks_all_pairs_and_preserves_missing(self):
        inputs = s2_inputs([["华东", "150.00"], ["华北", "200.00"]], [["华东", "100.00"]])
        receipt, aligned, policy = qualify(inputs)
        self.assertEqual(aligned.status, "insufficient_evidence")
        signals = self.assert_gate_rejects(inputs, receipt, aligned, policy, status="insufficient_evidence")
        missing = next(item for item in signals if item.business_key.components[0].normalized_value == "华北")
        self.assertEqual(missing.reference_value.presence, "missing")
        evidence = missing.evidence[1]
        self.assertIsNone(evidence.row_index)
        self.assertIsNone(evidence.raw_value)
        self.assertIsNone(evidence.business_key)
        self.assertTrue(any(issue.code == "MISSING_RIGHT_KEY" for issue in missing.limitations))

    def test_missing_current_is_not_zero(self):
        inputs = s2_inputs([["华东", "150.00"]], [["华东", "100.00"], ["华北", "200.00"]])
        receipt, aligned, policy = qualify(inputs)
        signals = self.assert_gate_rejects(inputs, receipt, aligned, policy, status="insufficient_evidence")
        missing = next(item for item in signals if item.business_key.components[0].normalized_value == "华北")
        self.assertEqual(missing.current_value.presence, "missing")
        self.assertIsNone(missing.current_value.value)

    def test_duplicate_baseline_keys_block_numeric_reads(self):
        inputs = s2_inputs(baseline=[["华东", "100.00"], ["华东", "200.00"]])
        receipt, aligned, policy = qualify(inputs)
        signals = self.assert_gate_rejects(inputs, receipt, aligned, policy)
        self.assertTrue(any(issue.code == "DUPLICATE_KEY" for signal in signals for issue in signal.limitations))

    def test_duplicate_current_keys_block_numeric_reads(self):
        inputs = s2_inputs(current=[["华东", "150.00"], ["华东", "160.00"]])
        receipt, aligned, policy = qualify(inputs)
        self.assert_gate_rejects(inputs, receipt, aligned, policy)

    def test_unresolved_null_key_blocks_numeric_reads(self):
        inputs = s2_inputs(current=[[None, "150.00"]])
        receipt, aligned, policy = qualify(inputs)
        signals = self.assert_gate_rejects(inputs, receipt, aligned, policy, status="insufficient_evidence")
        self.assertTrue(any(issue.code == "NULL_KEY" for signal in signals for issue in signal.limitations))

    def test_current_numeric_null_has_observation_location_but_no_formula(self):
        signal = self.one(None, "100.00")
        self.assertEqual(signal.status, "insufficient_evidence")
        self.assertTrue(all(item.value is None for item in signal.computed_value.values()))
        self.assertEqual(signal.current_value.presence, "sql_null")
        self.assertEqual(signal.evidence[0].row_index, 0)
        self.assertIsNone(signal.evidence[0].raw_value)

    def test_baseline_numeric_null_is_not_zero_baseline(self):
        signal = self.one("150.00", None)
        self.assertEqual(signal.status, "insufficient_evidence")
        self.assertTrue(all(item.value is None for item in signal.computed_value.values()))
        self.assertNotEqual(signal.computed_value["change_rate"].reason_code, "ZERO_BASELINE")

    def test_null_current_with_zero_baseline_does_not_compute_absolute(self):
        signal = self.one(None, "0.00")
        self.assertEqual(signal.status, "insufficient_evidence")
        self.assertTrue(all(item.status != "computed" for item in signal.computed_value.values()))

    def test_numeric_failure_only_blocks_its_own_aligned_pair(self):
        signals = self.compute(s2_inputs([["华东", "150.00"], ["华北", None]],
                                         [["华东", "100.00"], ["华北", "200.00"]]))
        by_key = {item.business_key.components[0].normalized_value: item for item in signals}
        self.assertEqual(by_key["华东"].status, "computed")
        self.assertEqual(by_key["华北"].status, "insufficient_evidence")

    def test_negative_sales_inputs_remain_rejected(self):
        for current, baseline in (("-1.00", "100.00"), ("150.00", "-1.00")):
            with self.subTest(current=current, baseline=baseline):
                signal = self.one(current, baseline)
                self.assertEqual(signal.status, "incompatible_context")
                self.assertTrue(all(item.value is None for item in signal.computed_value.values()))
                self.assertTrue(any(issue.code == "NEGATIVE_INPUT_NOT_ALLOWED" for issue in signal.limitations))

    def test_invalid_decimal_text_preserves_rejected_evidence(self):
        signal = self.one("invalid-decimal", "100.00")
        self.assertEqual(signal.status, "unsupported")
        self.assertEqual(signal.current_value.presence, "rejected")
        self.assertEqual(signal.evidence[0].raw_value, "invalid-decimal")

    def test_both_numeric_failures_preserve_issues_and_priority(self):
        signal = self.one("-1.00", "invalid-decimal")
        self.assertEqual(signal.status, "unsupported")
        self.assertTrue({"NEGATIVE_INPUT_NOT_ALLOWED", "INVALID_DECIMAL_TEXT"}
                        <= {issue.code for issue in signal.limitations})

    def test_double_requires_explicit_approximate_profile(self):
        inputs = s2_inputs([["华东", 150.0]], [["华东", 100.0]], current_dtype="DOUBLE", baseline_dtype="DOUBLE")
        receipt, aligned, policy = qualify(inputs)
        self.assert_gate_rejects(inputs, receipt, aligned, policy)

    def test_approved_double_retains_approximate_quality_for_both_outputs(self):
        policy = s2_policy(numeric_rules={"profile": "reporting_approx_v1", "allow_binary_float": True,
                                         "accepted_encodings": ["native_json", "decimal_text"]})
        signal = self.one(0.1 + 0.2, 0.3, dtype="DOUBLE", policy=policy)
        self.assertEqual(signal.status, "computed")
        for result in signal.computed_value.values():
            self.assertEqual(result.numeric_quality.source_fidelity, "approximate")
        self.assertEqual(Decimal(signal.computed_value["absolute_change"].value), Decimal("0.00000000000000004"))
        self.assertEqual(signal.computed_value["change_rate"].numeric_quality.arithmetic_rounding, "rounded")

    def test_absolute_change_does_not_force_two_decimal_places(self):
        signal = self.one("100.0001", "100.0000", dtype="DECIMAL(38,18)")
        self.assertEqual(signal.computed_value["absolute_change"].value, "0.0001")
        self.assertEqual(signal.computed_value["absolute_change"].numeric_quality.arithmetic_rounding, "exact")

    def test_exact_subtraction_and_rate_match_independent_fraction_oracle(self):
        cases = [
            ("2", "3"), ("4", "3"),
            ("100.000000000000000001", "100.000000000000000000"),
            ("99.999999999999999999", "100.000000000000000000"),
            ("99999999999999999999.999999999999999999", "0.000000000000000001"),
            ("0.000000000000000001", "99999999999999999999.999999999999999999"),
        ]
        for current, baseline in cases:
            with self.subTest(current=current, baseline=baseline):
                signal = self.one(current, baseline, dtype="DECIMAL(38,18)")
                absolute, rate = (signal.computed_value[name] for name in ("absolute_change", "change_rate"))
                expected, exact = fraction_rate_oracle(current, baseline)
                self.assertEqual(Fraction(Decimal(absolute.value)), Fraction(Decimal(current)) - Fraction(Decimal(baseline)))
                self.assertEqual(Decimal(rate.value), Decimal(expected))
                self.assertEqual(rate.numeric_quality.arithmetic_rounding,
                                 "exact" if Fraction(Decimal(rate.value)) == exact else "rounded")

    def test_half_even_ties_on_both_sides_of_zero(self):
        for current in ("2000000000001", "2000000000003", "1999999999999", "1999999999997"):
            with self.subTest(current=current):
                signal = self.one(current, "2000000000000", dtype="DECIMAL(38,18)")
                expected, _ = fraction_rate_oracle(current, "2000000000000")
                self.assertEqual(Decimal(signal.computed_value["change_rate"].value), Decimal(expected))

    def test_tiny_baseline_is_not_treated_as_zero(self):
        signal = self.one("0.000000000000000002", "0.000000000000000001", dtype="DECIMAL(38,18)")
        self.assertEqual(signal.status, "computed")
        self.assertEqual(signal.computed_value["change_rate"].value, "1.000000000000")

    def test_extreme_zero_exponents_do_not_expand_output_or_change_zero_semantics(self):
        for zero in ("0E+999999999999999999", "-0E+999999999999999999"):
            with self.subTest(zero=zero):
                signal = self.one("1.000000000000000001", zero, dtype="DECIMAL(38,18)")
                self.assertEqual(signal.status, "undefined")
                self.assertEqual(signal.computed_value["absolute_change"].value, "1.000000000000000001")
                self.assertEqual(signal.computed_value["change_rate"].reason_code, "ZERO_BASELINE")

    def test_global_decimal_precision_traps_flags_and_exponents_are_unchanged(self):
        inputs, receipt, aligned, policy = self.approved(s2_inputs([["华东", "2.00"]], [["华东", "3.00"]]))
        outer = decimal_state()
        with localcontext() as ambient:
            ambient.prec = 3
            ambient.Emin, ambient.Emax = -2, 2
            for trap in ambient.traps:
                ambient.traps[trap] = True
            ambient.flags[Inexact] = True
            ambient.flags[Rounded] = True
            before = decimal_state()
            signal = self.compute(inputs, policy, receipt, aligned)[0]
            self.assertEqual(signal.computed_value["change_rate"].value, "-0.333333333333")
            self.assertEqual(decimal_state(), before)
        self.assertEqual(decimal_state(), outer)

    def test_stale_policy_content_is_rejected_before_numeric(self):
        inputs, receipt, aligned, policy = self.approved()
        raw = policy.model_dump()
        raw["metric_rules"][0]["allowed_sources"][0]["field"] = "other_amount"
        self.assert_gate_rejects(inputs, receipt, aligned, SalesChangePolicy.model_validate(raw))

    def test_all_selection_changes_invalidate_old_receipts(self):
        for change in ({"metric_column_id": "col_k"}, {"key_column_ids": {"region": "col_m"}},
                       {"auxiliary_column_ids": {"audit": "col_m"}}):
            with self.subTest(change=change):
                inputs, receipt, aligned, policy = self.approved()
                inputs["current"] = inputs["current"].model_copy(update={
                    "selection": inputs["current"].selection.model_copy(update=change),
                }, deep=True)
                self.assert_gate_rejects(inputs, receipt, aligned, policy)

    def test_changed_declaration_invalidates_old_receipt(self):
        inputs, receipt, aligned, policy = self.approved()
        replace_declaration(inputs, "current", "unit", lambda raw: raw["claims"]["unit"].update(unit_id="USD"))
        self.assert_gate_rejects(inputs, receipt, aligned, policy)

    def test_changed_numeric_cell_invalidates_old_receipt(self):
        inputs, receipt, aligned, policy = self.approved()
        inputs["current"] = s2_input("current", [["华东", "999.00"]])
        self.assert_gate_rejects(inputs, receipt, aligned, policy)

    def test_old_alignment_cannot_use_a_new_current_receipt(self):
        inputs, receipt, aligned, policy = self.approved()
        inputs["current"] = s2_input("current", [["华东", "151.00"]])
        fresh, _, _ = qualify(inputs, policy)
        signals = self.assert_gate_rejects(inputs, fresh, aligned, policy)
        self.assertTrue(all(signal.scope == "context" and signal.business_key is None for signal in signals))

    def test_alignment_pair_mutation_cannot_cross_regions(self):
        inputs, receipt, aligned, policy = self.approved(s2_inputs(
            [["华东", "150.00"], ["华北", "90.00"]], [["华北", "30.00"], ["华东", "100.00"]]))
        changed = aligned.model_copy(deep=True)
        pair = changed.pairs[0]
        changed.pairs[0] = pair.model_copy(update={"right_row_index": 1 - pair.right_row_index})
        self.assert_gate_rejects(inputs, receipt, changed, policy)

    def test_unbound_and_unknown_version_alignment_are_rejected(self):
        inputs, receipt, aligned, policy = self.approved()
        for binding in (None, aligned.binding.model_copy(update={"version": "2"})):
            with self.subTest(binding=binding):
                self.assert_gate_rejects(inputs, receipt, aligned.model_copy(update={"binding": binding}), policy)

    def test_alignment_status_cannot_be_promoted(self):
        inputs = s2_inputs(baseline=[["华东", "100.00"], ["华东", "200.00"]])
        receipt, aligned, policy = qualify(inputs)
        self.assert_gate_rejects(inputs, receipt, aligned.model_copy(update={"status": "aligned"}), policy)

    def test_receipt_status_and_period_mutations_are_rejected(self):
        inputs, receipt, aligned, policy = self.approved()
        changed = receipt.model_copy(deep=True)
        first = changed.periods[0]
        changed.periods[0] = first.model_copy(update={"period": first.period.model_copy(update={"upper": "2026-10-01"})})
        self.assert_gate_rejects(inputs, changed, aligned, policy)
        self.assert_gate_rejects(inputs, receipt.model_copy(update={"status": "incompatible_context"}), aligned, policy)

    def test_align_operation_does_not_authorize_sales_comparison(self):
        inputs, receipt, aligned, policy = self.approved(operation="align")
        self.assert_gate_rejects(inputs, receipt, aligned, policy)

    def test_missing_unit_declaration_is_a_global_failure(self):
        inputs = s2_inputs()
        remove_declaration(inputs, "current", "unit")
        receipt, aligned, policy = qualify(inputs)
        self.assert_gate_rejects(inputs, receipt, aligned, policy, status="insufficient_evidence")

    def test_mismatched_units_are_not_converted(self):
        inputs = s2_inputs()
        replace_declaration(inputs, "baseline", "unit", lambda raw: raw["claims"]["unit"].update(unit_id="USD"))
        receipt, aligned, policy = qualify(inputs)
        self.assert_gate_rejects(inputs, receipt, aligned, policy)

    def test_nonadjacent_months_are_rejected(self):
        inputs = s2_inputs()
        inputs["baseline"] = s2_input("baseline", [["华东", "100.00"]], lower="2026-06-01", upper="2026-07-01")
        receipt, aligned, policy = qualify(inputs)
        self.assert_gate_rejects(inputs, receipt, aligned, policy)

    def test_partial_month_is_rejected(self):
        inputs = s2_inputs()
        inputs["current"] = s2_input("current", [["华东", "150.00"]], lower="2026-08-02", upper="2026-09-01")
        receipt, aligned, policy = qualify(inputs)
        self.assert_gate_rejects(inputs, receipt, aligned, policy)

    def test_exclusive_lower_month_boundary_is_rejected(self):
        inputs = s2_inputs()
        raw = inputs["current"].context.model_dump()
        raw["time_constraints"][0]["inclusive"]["lower"] = False
        raw["filters"]["filters"][0]["operator"] = ">"
        inputs["current"] = supplied_input("s2", "current", raw)
        for name in ("unit", "time_domain", "row_selection", "population", "snapshot_revision"):
            replace_declaration(inputs, "current", name,
                                lambda item: item["scope"]["period"].update(lower_inclusive=False))
        receipt, aligned, policy = qualify(inputs)
        self.assertNotEqual(receipt.status, "compatible")
        self.assert_gate_rejects(inputs, receipt, aligned, policy, status=receipt.status)

    def test_inclusive_upper_month_boundary_is_rejected(self):
        inputs = s2_inputs()
        raw = inputs["current"].context.model_dump()
        raw["time_constraints"][0]["inclusive"]["upper"] = True
        raw["filters"]["filters"][1]["operator"] = "<="
        inputs["current"] = supplied_input("s2", "current", raw)
        for name in ("unit", "time_domain", "row_selection", "population", "snapshot_revision"):
            replace_declaration(inputs, "current", name,
                                lambda item: item["scope"]["period"].update(upper_inclusive=True))
        receipt, aligned, policy = qualify(inputs)
        self.assertNotEqual(receipt.status, "compatible")
        self.assert_gate_rejects(inputs, receipt, aligned, policy, status=receipt.status)

    def test_adjacent_months_across_year_boundary_are_accepted(self):
        inputs = {
            "current": s2_input("current", [["华东", "150.00"]], lower="2027-01-01", upper="2027-02-01"),
            "baseline": s2_input("baseline", [["华东", "100.00"]], lower="2026-12-01", upper="2027-01-01"),
        }
        inputs, receipt, aligned, policy = self.approved(inputs)
        signal = self.compute(inputs, policy, receipt, aligned)[0]
        self.assertEqual(signal.status, "computed")
        self.assertEqual(signal.computed_value["change_rate"].value, "0.500000000000")
        self.assertEqual(signal.evidence[1].normalized_period.upper, signal.evidence[0].normalized_period.lower)

    def test_adjacent_months_across_leap_february_are_accepted(self):
        inputs = {
            "current": s2_input("current", [["华东", "150.00"]], lower="2024-03-01", upper="2024-04-01"),
            "baseline": s2_input("baseline", [["华东", "100.00"]], lower="2024-02-01", upper="2024-03-01"),
        }
        inputs, receipt, aligned, policy = self.approved(inputs)
        signal = self.compute(inputs, policy, receipt, aligned)[0]
        self.assertEqual(signal.status, "computed")
        self.assertEqual(signal.computed_value["absolute_change"].value, "50.00")
        self.assertEqual(signal.evidence[1].normalized_period.lower, "2024-02-01")
        self.assertEqual(signal.evidence[1].normalized_period.upper, "2024-03-01")

    def test_fixed_policy_rejects_wrong_and_similarly_named_metric_fields(self):
        for field in ("order_amount", "paid_amount_total"):
            with self.subTest(field=field):
                inputs = s2_inputs()
                raw = inputs["current"].context.model_dump()
                original_alias = raw["column_semantics"][1]["output_name"]
                rename_source_field(raw, "paid_amount", field)
                inputs["current"] = supplied_input("s2", "current", raw)
                self.assertEqual(inputs["current"].context.column_semantics[1].output_name, original_alias)
                receipt, aligned, policy = qualify(inputs)
                self.assert_gate_rejects(inputs, receipt, aligned, policy)

    def test_fixed_policy_rejects_wrong_metric_table_despite_same_alias(self):
        inputs = s2_inputs()
        raw = inputs["current"].context.model_dump()
        metric = raw["column_semantics"][1]
        metric["lineage"][0]["table"] = "orders_history"
        metric["schema_bindings"][0]["source"]["table"] = "orders_history"
        for item in raw["query_bindings"]["bindings"]:
            if item["source"]["field"] == "paid_amount":
                item["source"]["table"] = "orders_history"
        inputs["current"] = supplied_input("s2", "current", raw)
        self.assertEqual(inputs["current"].context.column_semantics[1].output_name, "sales_amount")
        receipt, aligned, policy = qualify(inputs)
        self.assert_gate_rejects(inputs, receipt, aligned, policy)

    def test_fixed_policy_rejects_avg_despite_same_metric_source_and_alias(self):
        inputs = s2_inputs()
        raw = inputs["current"].context.model_dump()
        raw["column_semantics"][1]["aggregation"] = "AVG"
        inputs["current"] = supplied_input("s2", "current", raw)
        receipt, aligned, policy = qualify(inputs)
        self.assert_gate_rejects(inputs, receipt, aligned, policy)

    def test_fixed_policy_rejects_customer_grain(self):
        inputs = s2_inputs()
        raw = inputs["current"].context.model_dump()
        rename_source_field(raw, "region", "customer_id")
        inputs["current"] = supplied_input("s2", "current", raw)
        receipt, aligned, policy = qualify(inputs)
        self.assert_gate_rejects(inputs, receipt, aligned, policy)

    def test_fresh_alternate_metric_policy_cannot_expand_this_calculator(self):
        inputs, policy = s2_inputs(), s2_policy()
        raw_policy = policy.model_dump()
        rename_source_field(raw_policy, "paid_amount", "order_amount")
        for role in inputs:
            raw = inputs[role].context.model_dump()
            rename_source_field(raw, "paid_amount", "order_amount")
            inputs[role] = supplied_input("s2", role, raw)
        receipt, aligned, policy = qualify(inputs, SalesChangePolicy.model_validate(raw_policy))
        self.assertEqual(receipt.status, "compatible")
        self.assertEqual(aligned.status, "aligned")
        self.assert_gate_rejects(inputs, receipt, aligned, policy, status="unsupported")

    def test_fresh_category_policy_cannot_expand_regional_s2(self):
        inputs, policy = s2_inputs(), s2_policy()
        raw_policy = policy.model_dump()
        rename_source_field(raw_policy, "region", "category")
        for role in inputs:
            raw = inputs[role].context.model_dump()
            rename_source_field(raw, "region", "category")
            inputs[role] = supplied_input("s2", role, raw)
        receipt, aligned, policy = qualify(inputs, SalesChangePolicy.model_validate(raw_policy))
        self.assertEqual(receipt.status, "compatible")
        self.assertEqual(aligned.status, "aligned")
        self.assert_gate_rejects(inputs, receipt, aligned, policy, status="unsupported")

    def test_missing_paid_filter_is_rejected(self):
        inputs = s2_inputs()
        raw = inputs["current"].context.model_dump()
        raw["filters"]["filters"] = raw["filters"]["filters"][:2]
        inputs["current"] = supplied_input("s2", "current", raw)
        receipt, aligned, policy = qualify(inputs)
        self.assert_gate_rejects(inputs, receipt, aligned, policy)

    def test_unknown_contract_version_is_preserved_in_rejected_evidence(self):
        inputs = s2_inputs()
        raw = inputs["current"].context.model_dump()
        raw["result_contract_version"] = "2"
        inputs["current"] = supplied_input("s2", "current", raw)
        receipt, aligned, policy = qualify(inputs)
        signals = self.assert_gate_rejects(inputs, receipt, aligned, policy, status="unsupported")
        self.assertEqual(signals[0].evidence[0].result_contract_version, "2")

    def test_units_come_from_consumed_declarations_and_absolute_preserves_scale(self):
        inputs = s2_inputs()
        for role in inputs:
            replace_declaration(inputs, role, "unit", lambda raw: raw["claims"]["unit"].update(
                unit_id="fixture_unit", unit_scale="1000", display_scale=0))
        signal = self.compute(inputs)[0]
        self.assertEqual(signal.status, "computed")
        self.assertEqual(signal.computed_value["absolute_change"].unit_id, "fixture_unit")
        self.assertEqual(signal.computed_value["change_rate"].unit_id, "ratio")
        for evidence in signal.evidence:
            self.assertEqual(evidence.unit_declaration.claims.unit.unit_scale, "1000")
            self.assertEqual(evidence.observed_value.unit_id, "fixture_unit")

    def test_evidence_has_both_formula_refs_and_original_operand_identity(self):
        signal = self.one()
        self.assertEqual(signal.signal_type, "regional_sales_change")
        self.assertEqual([item.context_role for item in signal.evidence], ["current", "baseline"])
        for role, evidence in zip(("current", "baseline"), signal.evidence):
            self.assertEqual(evidence.result_id, f"captured-s2-{role}")
            self.assertEqual((evidence.column_id, evidence.ordinal, evidence.row_index), ("col_m", 1, 0))
            self.assertEqual({ref.formula_id for ref in evidence.formula_refs}, {"absolute_change", "change_rate"})
            self.assertTrue(all(ref.formula_version == "1" for ref in evidence.formula_refs))
            self.assertEqual(evidence.numeric_quality, evidence.observed_value.source_quality)
            self.assertTrue(evidence.schema_metadata)
            self.assertTrue(evidence.eligibility.declarations)
            self.assertIsNotNone(evidence.unit_declaration)
        for result in signal.computed_value.values():
            self.assertEqual(set(result.input_evidence_ids), {item.evidence_id for item in signal.evidence})

    def test_evidence_keeps_current_and_baseline_periods_distinct(self):
        evidence = self.one().evidence
        self.assertEqual(evidence[0].normalized_period.lower, "2026-08-01")
        self.assertEqual(evidence[1].normalized_period.lower, "2026-07-01")
        self.assertTrue(all(item.aggregation == "SUM" and item.grain.query_grain == "grouped" for item in evidence))
        self.assertTrue(all(item.time[0].precision == "date" for item in evidence))

    def test_signal_identity_is_not_invented(self):
        signal = self.one()
        self.assertIsNone(signal.signal_id)
        self.assertTrue(any(issue.code == "SIGNAL_IDENTITY_NOT_FROZEN" for issue in signal.limitations))

    def test_actual_policy_digest_is_retained(self):
        inputs, receipt, aligned, policy = self.approved()
        signal = self.compute(inputs, policy, receipt, aligned)[0]
        self.assertEqual(signal.policy_digest, receipt.binding.policy_digest)

    def test_factory_definition_digest_matches_independent_canonical_hash(self):
        policy = s2_policy()
        payload = policy.model_dump(mode="python")
        supplied_digest = payload.pop("definition_digest")
        serialized = json.dumps(payload, ensure_ascii=True, allow_nan=False,
                                sort_keys=True, separators=(",", ":")).encode("utf-8")
        expected = "policy-definition-v1:sha256:" + hashlib.sha256(serialized).hexdigest()
        self.assertEqual(supplied_digest, expected)
        self.assertEqual(s2_policy().definition_digest, expected)
        changed = monthly_sales_change_v1(database="another_database", accepted_issuer_kinds=["fixture_catalog"],
                                          accepted_issuer_refs=["demo_v1"])
        self.assertNotEqual(changed.definition_digest, supplied_digest)

    def test_factory_requires_explicit_database_and_issuer_authority(self):
        arguments = {"database": "askdata_mock", "accepted_issuer_kinds": ["fixture_catalog"],
                     "accepted_issuer_refs": ["demo_v1"]}
        for omitted in arguments:
            with self.subTest(omitted=omitted), self.assertRaises(TypeError):
                monthly_sales_change_v1(**{key: value for key, value in arguments.items() if key != omitted})
        for change in ({"database": " "}, {"accepted_issuer_kinds": []}, {"accepted_issuer_refs": []},
                       {"accepted_issuer_refs": [" "]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                monthly_sales_change_v1(**{**arguments, **change})

    def test_factory_does_not_mutate_or_share_caller_containers(self):
        kinds, references = ["fixture_catalog"], ["caller-chosen-authority"]
        numeric = NumericRules(profile="decimal_exact_v1", accepted_encodings=["native_json", "decimal_text"])
        before = copy.deepcopy((kinds, references, numeric))
        policy = monthly_sales_change_v1(database="askdata_mock", accepted_issuer_kinds=kinds,
                                          accepted_issuer_refs=references, numeric_rules=numeric)
        self.assertEqual((kinds, references, numeric), before)
        self.assertTrue(all(rule.accepted_issuer_refs == references for rule in policy.declaration_rules))
        policy.declaration_rules[0].accepted_issuer_refs.append("output-only-change")
        policy.numeric_rules.accepted_encodings.clear()
        self.assertEqual((kinds, references, numeric), before)
        self.assertEqual(policy.declaration_rules[1].accepted_issuer_refs, references)

    def test_reconstructing_equal_content_is_deterministic(self):
        inputs, receipt, aligned, policy = self.approved()
        first = self.compute(inputs, policy, receipt, aligned)
        second = self.compute({role: SignalInput.model_validate(value.model_dump()) for role, value in inputs.items()},
                              SalesChangePolicy.model_validate(policy.model_dump()),
                              ContextCompatibility.model_validate(receipt.model_dump()),
                              AlignmentResult.model_validate(aligned.model_dump()))
        self.assertEqual(first, second)

    def test_all_input_snapshots_remain_unchanged(self):
        inputs, receipt, aligned, policy = self.approved()
        before = copy.deepcopy((inputs, receipt, aligned, policy))
        self.compute(inputs, policy, receipt, aligned)
        self.assertEqual((inputs, receipt, aligned, policy), before)

    def test_returned_evidence_and_keys_are_detached(self):
        inputs, receipt, aligned, policy = self.approved()
        before = copy.deepcopy((inputs, receipt, aligned, policy))
        signal = self.compute(inputs, policy, receipt, aligned)[0]
        signal.business_key.components.clear()
        signal.evidence[0].source_fields.clear()
        signal.evidence[0].unit_declaration.column_ids.clear()
        signal.evidence[0].formula_refs.clear()
        self.assertEqual((inputs, receipt, aligned, policy), before)

    def test_aba_invocations_do_not_leak_state(self):
        inputs, receipt, aligned, policy = self.approved()
        first = self.compute(inputs, policy, receipt, aligned)
        self.one("250.00", "0.00")
        self.assertEqual(self.compute(inputs, policy, receipt, aligned), first)

    def test_each_operand_is_read_once_and_evidence_builder_is_reused(self):
        inputs, receipt, aligned, policy = self.approved()
        with patch.object(sales_change, "read_numeric_value", wraps=sales_change.read_numeric_value) as reader, \
             patch.object(sales_change, "build_signal_evidence", wraps=sales_change.build_signal_evidence) as builder:
            signal = self.compute(inputs, policy, receipt, aligned)[0]
        self.assertEqual(signal.status, "computed")
        self.assertEqual(reader.call_count, 2)
        self.assertEqual(builder.call_count, 2)
        self.assertEqual([call.args[1:3] for call in reader.call_args_list], [("col_m", 0), ("col_m", 0)])

    def test_returned_numeric_read_results_are_not_modified_by_calculation_or_evidence(self):
        inputs, receipt, aligned, policy = self.approved(s2_inputs(
            [["华东", "150.00"], ["华北", None]], [["华东", "100.00"], ["华北", "200.00"]]))
        original_reader = sales_change.read_numeric_value
        captured = []

        def capture(*args, **kwargs):
            result = original_reader(*args, **kwargs)
            captured.append((result, copy.deepcopy(result)))
            return result

        with patch.object(sales_change, "read_numeric_value", side_effect=capture):
            signals = self.compute(inputs, policy, receipt, aligned)
        self.assertEqual({signal.status for signal in signals}, {"computed", "insufficient_evidence"})
        self.assertEqual(len(captured), 4)
        for reading, before in captured:
            self.assertEqual(reading, before)

    def test_no_upstream_rerun_network_clock_or_random_identity(self):
        inputs, receipt, aligned, policy = self.approved()
        with patch.object(compatibility, "check_context_compatibility", side_effect=AssertionError("compatibility rerun")), \
             patch.object(alignment, "align_context_keys", side_effect=AssertionError("alignment rerun")), \
             patch.object(socket, "socket", side_effect=AssertionError("network")), \
             patch.object(time, "time", side_effect=AssertionError("clock")), \
             patch.object(uuid, "uuid4", side_effect=AssertionError("random identity")):
            signal = self.compute(inputs, policy, receipt, aligned)[0]
        self.assertEqual(signal.status, "computed")

    def test_no_direct_row_reads_float_division_sql_llm_or_workflow_calls(self):
        tree = ast.parse(inspect.getsource(sales_change))
        calls = {node.func.id if isinstance(node.func, ast.Name) else node.func.attr
                 for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, (ast.Name, ast.Attribute))}
        self.assertFalse(calls & {"float", "check_context_compatibility", "align_context_keys", "execute",
                                 "execute_sql", "parse_sql", "generate_sql", "invoke", "ainvoke", "uuid4"})
        self.assertFalse([node for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr == "rows"])

    def test_computed_undefined_null_and_rejected_signals_survive_json_round_trip(self):
        for signal in (self.one(), self.one("150.00", "0.00"), self.one(None, "100.00"),
                       self.one("invalid-decimal", "100.00")):
            with self.subTest(status=signal.status):
                self.assertEqual(BusinessSignal.model_validate_json(signal.model_dump_json()), signal)


if __name__ == "__main__":
    unittest.main()
