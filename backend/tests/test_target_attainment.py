"""S1 calculation through real Compatibility and Alignment producer receipts.

The captured facts and unit declarations are explicit synthetic fixtures. These
tests neither parse nor execute SQL, and no successful receipt is manufactured.
"""

import ast
import copy
from decimal import Inexact, Rounded, getcontext, localcontext
import inspect
import unittest
from unittest.mock import patch

from app.querying.business_signals import alignment, compatibility, target_attainment
from app.querying.business_signals.models import (
    AlignmentResult, BusinessSignal, ContextCompatibility, SignalInput,
)
from app.querying.business_signals.policies import TargetAttainmentPolicy
from test_business_signal_compatibility import (
    captured_context, remove_declaration, replace_declaration, supplied_input,
    typed_policy,
)


def s1_input(role, rows, *, dtype="DECIMAL(18,2)", metric_first=False):
    raw = captured_context("s1", role)
    raw["execution"].update(rows=copy.deepcopy(rows), returned_rows=len(rows), total_rows=len(rows))
    raw["execution"]["columns"][1]["dtype"] = dtype
    raw["execution"]["columns"][1]["value_encoding"] = (
        "decimal_text" if dtype.startswith("DECIMAL(") else "native_json"
    )
    if metric_first:
        raw["execution"]["columns"].reverse()
        raw["column_semantics"].reverse()
        for index, column in enumerate(raw["execution"]["columns"]):
            column["ordinal"] = index
            column["name"] = "not_a_metric_identity"
        for index, semantic in enumerate(raw["column_semantics"]):
            semantic["ordinal"] = index
            semantic["output_name"] = "not_a_metric_identity"
        raw["execution"]["rows"] = [[row[1], row[0]] for row in rows]
    return supplied_input("s1", role, raw)


def s1_inputs(actual=None, target=None, *, actual_dtype="DECIMAL(18,2)",
              target_dtype="DECIMAL(18,2)", metric_first=False):
    return {
        "actual": s1_input("actual", actual if actual is not None else [["华东", "100.00"]],
                           dtype=actual_dtype, metric_first=metric_first),
        "target": s1_input("target", target if target is not None else [["华东", "200.00"]],
                           dtype=target_dtype, metric_first=metric_first),
    }


def qualify(inputs, policy=None, *, operation="divide"):
    policy = policy or typed_policy("s1")
    receipt = compatibility.check_context_compatibility(inputs, policy, operation=operation)
    aligned = alignment.align_context_keys(inputs, receipt, policy)
    return receipt, aligned, policy


def decimal_state():
    current = getcontext()
    return (current.prec, current.rounding, current.Emin, current.Emax,
            current.capitals, current.clamp, dict(current.flags), dict(current.traps))


class TargetAttainmentTests(unittest.TestCase):
    def compute(self, inputs=None, policy=None, receipt=None, aligned=None):
        inputs = s1_inputs() if inputs is None else inputs
        if receipt is None or aligned is None:
            receipt, aligned, policy = qualify(inputs, policy)
        return target_attainment.compute_target_attainment(
            inputs["actual"], inputs["target"], receipt, aligned, policy,
        )

    def approved(self, inputs=None, policy=None, *, operation="divide"):
        inputs = s1_inputs() if inputs is None else inputs
        receipt, aligned, policy = qualify(inputs, policy, operation=operation)
        self.assertEqual(receipt.status, "compatible", receipt.model_dump())
        self.assertEqual(aligned.status, "aligned", aligned.model_dump())
        return inputs, receipt, aligned, policy

    def assert_gate_rejects(self, inputs, receipt, aligned, policy, *, status="incompatible_context"):
        with patch.object(target_attainment, "read_numeric_value", side_effect=AssertionError("numeric gate bypass")):
            signals = self.compute(inputs, policy, receipt, aligned)
        self.assertTrue(signals)
        self.assertTrue(all(signal.status == status for signal in signals), signals)
        self.assertTrue(all(signal.computed_value["attainment_rate"].value is None for signal in signals))
        return signals

    def one_computed(self, inputs=None, policy=None):
        inputs, receipt, aligned, policy = self.approved(inputs, policy)
        signals = self.compute(inputs, policy, receipt, aligned)
        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertIsInstance(signal, BusinessSignal)
        self.assertEqual(signal.status, "computed", signal.model_dump())
        return signal

    def test_100_divided_by_200_is_half(self):
        signal = self.one_computed()
        self.assertEqual(signal.computed_value["attainment_rate"].value, "0.500000000000")
        self.assertEqual(signal.current_value.value, "100.00")
        self.assertEqual(signal.reference_value.value, "200.00")

    def test_multiple_regions_have_separate_signals(self):
        inputs = s1_inputs([["华东", "100.00"], ["华北", "90.00"]],
                           [["华东", "200.00"], ["华北", "30.00"]])
        signals = self.compute(inputs)
        self.assertEqual(len(signals), 2)
        values = {signal.business_key.components[0].normalized_value:
                  signal.computed_value["attainment_rate"].value for signal in signals}
        self.assertEqual(values, {"华东": "0.500000000000", "华北": "3.000000000000"})

    def test_different_row_order_uses_alignment_indexes(self):
        inputs = s1_inputs([["华东", "100.00"], ["华北", "90.00"]],
                           [["华北", "30.00"], ["华东", "200.00"]])
        signals = self.compute(inputs)
        east = next(signal for signal in signals if signal.business_key.components[0].normalized_value == "华东")
        evidence = {item.context_role: item for item in east.evidence}
        self.assertEqual((evidence["actual"].row_index, evidence["target"].row_index), (0, 1))
        self.assertEqual(east.computed_value["attainment_rate"].value, "0.500000000000")

    def test_metric_column_ordinal_is_used_despite_duplicate_display_names(self):
        signal = self.one_computed(s1_inputs(metric_first=True))
        self.assertEqual(signal.computed_value["attainment_rate"].value, "0.500000000000")
        self.assertTrue(all(item.column_id == "col_m" and item.ordinal == 0 for item in signal.evidence))

    def test_row_index_zero_is_a_real_observation(self):
        signal = self.one_computed()
        self.assertTrue(all(item.row_index == 0 for item in signal.evidence))
        self.assertTrue(all(item.observed_value.presence == "present" for item in signal.evidence))

    def test_zero_target_is_undefined_without_a_quotient(self):
        for actual in ("100.00", "0.00"):
            with self.subTest(actual=actual):
                with patch.object(target_attainment, "_ratio", side_effect=AssertionError("division by zero")):
                    signals = self.compute(s1_inputs([["华东", actual]], [["华东", "0.00"]]))
                self.assertEqual(signals[0].status, "undefined")
                result = signals[0].computed_value["attainment_rate"]
                self.assertIsNone(result.value)
                self.assertEqual(result.reason_code, "ZERO_DENOMINATOR")
                self.assertEqual(signals[0].reference_value.value, "0.00")

    def test_negative_zero_target_is_also_undefined(self):
        signal = self.compute(s1_inputs(target=[["华东", "-0.00"]]))[0]
        self.assertEqual(signal.status, "undefined")
        self.assertEqual(signal.reference_value.value, "-0.00")

    def test_zero_actual_with_positive_target_is_computed(self):
        signal = self.one_computed(s1_inputs(actual=[["华东", "0.00"]]))
        self.assertEqual(signal.computed_value["attainment_rate"].value, "0.000000000000")

    def test_missing_target_is_preserved_and_never_zero_filled(self):
        inputs = s1_inputs([["华东", "100.00"], ["华北", "90.00"]], [["华东", "200.00"]])
        receipt, aligned, policy = qualify(inputs)
        self.assertEqual(aligned.status, "insufficient_evidence")
        signals = self.assert_gate_rejects(inputs, receipt, aligned, policy, status="insufficient_evidence")
        north = next(signal for signal in signals if signal.business_key.components[0].normalized_value == "华北")
        self.assertEqual(north.current_value.presence, "not_read")
        self.assertEqual(north.reference_value.presence, "missing")
        missing = next(item for item in north.evidence if item.context_role == "target")
        self.assertIsNone(missing.row_index)
        self.assertIsNone(missing.raw_value)
        self.assertTrue(north.limitations)

    def test_missing_actual_is_preserved(self):
        inputs = s1_inputs([["华东", "100.00"]], [["华东", "200.00"], ["华北", "90.00"]])
        signal = next(item for item in self.compute(inputs) if item.business_key.components[0].normalized_value == "华北")
        self.assertEqual(signal.status, "insufficient_evidence")
        self.assertEqual(signal.current_value.presence, "missing")
        self.assertEqual(signal.reference_value.presence, "not_read")

    def test_missing_one_region_blocks_calculation_of_other_matched_pairs(self):
        inputs = s1_inputs([["华东", "100.00"], ["华北", "90.00"]], [["华东", "200.00"]])
        receipt, aligned, policy = qualify(inputs)
        signals = self.assert_gate_rejects(inputs, receipt, aligned, policy, status="insufficient_evidence")
        east = next(item for item in signals if item.business_key.components[0].normalized_value == "华东")
        self.assertEqual(east.current_value.presence, "not_read")
        self.assertEqual(east.reference_value.presence, "not_read")

    def test_duplicate_target_key_is_not_arbitrarily_selected(self):
        inputs = s1_inputs(target=[["华东", "200.00"], ["华东", "300.00"]])
        receipt, aligned, policy = qualify(inputs)
        self.assertEqual(receipt.status, "compatible")
        self.assertEqual(aligned.status, "incompatible_context")
        signals = self.assert_gate_rejects(inputs, receipt, aligned, policy)
        target_evidence = [item for signal in signals for item in signal.evidence if item.context_role == "target"]
        self.assertTrue(all(item.row_index is None for item in target_evidence))
        self.assertTrue(any("DUPLICATE" in issue.code for signal in signals for issue in signal.limitations))

    def test_duplicate_actual_key_is_rejected(self):
        inputs = s1_inputs(actual=[["华东", "100.00"], ["华东", "200.00"]])
        receipt, aligned, policy = qualify(inputs)
        self.assert_gate_rejects(inputs, receipt, aligned, policy)

    def test_actual_numeric_null_keeps_the_real_observation_location(self):
        signal = self.compute(s1_inputs(actual=[["华东", None]]))[0]
        self.assertEqual(signal.status, "insufficient_evidence")
        self.assertEqual(signal.current_value.presence, "sql_null")
        actual = next(item for item in signal.evidence if item.context_role == "actual")
        self.assertEqual(actual.row_index, 0)
        self.assertIsNone(actual.raw_value)
        self.assertIsNone(signal.computed_value["attainment_rate"].value)

    def test_target_numeric_null_is_not_a_zero_denominator(self):
        signal = self.compute(s1_inputs(target=[["华东", None]]))[0]
        self.assertEqual(signal.status, "insufficient_evidence")
        self.assertEqual(signal.reference_value.presence, "sql_null")

    def test_null_actual_takes_precedence_over_zero_target(self):
        signal = self.compute(s1_inputs([["华东", None]], [["华东", "0.00"]]))[0]
        self.assertEqual(signal.status, "insufficient_evidence")
        self.assertNotEqual(signal.computed_value["attainment_rate"].reason_code, "ZERO_DENOMINATOR")

    def test_negative_actual_is_rejected_with_raw_evidence(self):
        signal = self.compute(s1_inputs(actual=[["华东", "-100.00"]]))[0]
        self.assertEqual(signal.status, "incompatible_context")
        self.assertEqual(signal.current_value.presence, "rejected")
        actual = next(item for item in signal.evidence if item.context_role == "actual")
        self.assertEqual(actual.raw_value, "-100.00")
        self.assertEqual(actual.row_index, 0)

    def test_negative_target_is_rejected(self):
        signal = self.compute(s1_inputs(target=[["华东", "-200.00"]]))[0]
        self.assertEqual(signal.status, "incompatible_context")
        self.assertEqual(signal.reference_value.presence, "rejected")

    def test_invalid_decimal_text_is_rejected_not_relabelled_unknown(self):
        signal = self.compute(s1_inputs(actual=[["华东", "bad-decimal"]]))[0]
        self.assertEqual(signal.status, "unsupported")
        self.assertEqual(signal.current_value.presence, "rejected")
        self.assertTrue(any(issue.code == "INVALID_DECIMAL_TEXT" for issue in signal.limitations))

    def test_unsupported_numeric_input_takes_precedence_over_zero_target(self):
        signal = self.compute(s1_inputs([["华东", "bad-decimal"]], [["华东", "0.00"]]))[0]
        self.assertEqual(signal.status, "unsupported")
        self.assertIsNone(signal.computed_value["attainment_rate"].value)

    def test_native_scalar_codec_mismatch_preserves_rejected_scalar(self):
        signal = self.compute(s1_inputs(actual=[["华东", 1.25]]))[0]
        self.assertEqual(signal.status, "unsupported")
        actual = next(item for item in signal.evidence if item.context_role == "actual")
        self.assertEqual(actual.raw_value, 1.25)
        self.assertEqual(actual.observed_value.presence, "rejected")

    def test_double_requires_explicit_approximate_profile(self):
        inputs = s1_inputs([["华东", 100.0]], [["华东", 200.0]], actual_dtype="DOUBLE", target_dtype="DOUBLE")
        receipt, aligned, policy = qualify(inputs)
        self.assertEqual(receipt.status, "incompatible_context")
        self.assert_gate_rejects(inputs, receipt, aligned, policy)

    def test_approved_double_retains_approximate_source_quality(self):
        inputs = s1_inputs([["华东", 100.0]], [["华东", 200.0]], actual_dtype="DOUBLE", target_dtype="DOUBLE")
        policy = typed_policy("s1", numeric_rules={
            "profile": "reporting_approx_v1", "accepted_encodings": ["native_json", "decimal_text"],
            "allow_binary_float": True,
        })
        signal = self.one_computed(inputs, policy)
        result = signal.computed_value["attainment_rate"]
        self.assertEqual(result.value, "0.500000000000")
        self.assertEqual(result.numeric_quality.source_fidelity, "approximate")
        self.assertEqual(result.numeric_quality.source_kind, "binary_float")
        self.assertEqual(result.numeric_quality.arithmetic_rounding, "exact")
        self.assertIs(type(signal.evidence[0].raw_value), float)

    def test_mixed_decimal_and_double_is_still_approximate(self):
        inputs = s1_inputs(target=[["华东", 200.0]], target_dtype="DOUBLE")
        policy = typed_policy("s1", numeric_rules={
            "profile": "reporting_approx_v1", "accepted_encodings": ["native_json", "decimal_text"],
            "allow_binary_float": True,
        })
        result = self.one_computed(inputs, policy).computed_value["attainment_rate"]
        self.assertEqual(result.numeric_quality.source_fidelity, "approximate")

    def test_exact_integer_operands_can_produce_fractional_ratio(self):
        signal = self.one_computed(s1_inputs([["华东", 100]], [["华东", 200]],
                                             actual_dtype="BIGINT", target_dtype="BIGINT"))
        result = signal.computed_value["attainment_rate"]
        self.assertEqual(result.value, "0.500000000000")
        self.assertEqual(result.numeric_quality.source_fidelity, "exact")

    def test_recurring_decimal_records_arithmetic_rounding(self):
        signal = self.one_computed(s1_inputs([["华东", "1.00"]], [["华东", "3.00"]]))
        result = signal.computed_value["attainment_rate"]
        self.assertEqual(result.value, "0.333333333333")
        self.assertEqual(result.numeric_quality.source_fidelity, "exact")
        self.assertEqual(result.numeric_quality.arithmetic_rounding, "rounded")
        self.assertEqual(result.numeric_quality.scale, 12)

    def test_half_even_tie_rounds_down_to_even_zero(self):
        signal = self.one_computed(s1_inputs([["华东", "1.00"]], [["华东", "2000000000000.00"]]))
        self.assertEqual(signal.computed_value["attainment_rate"].value, "0.000000000000")

    def test_half_even_tie_rounds_up_to_even_two(self):
        signal = self.one_computed(s1_inputs([["华东", "3.00"]], [["华东", "2000000000000.00"]]))
        self.assertEqual(signal.computed_value["attainment_rate"].value, "0.000000000002")

    def test_half_even_tie_keeps_even_two(self):
        signal = self.one_computed(s1_inputs([["华东", "5.00"]], [["华东", "2000000000000.00"]]))
        self.assertEqual(signal.computed_value["attainment_rate"].value, "0.000000000002")

    def test_small_nonzero_target_is_not_treated_as_zero(self):
        inputs = s1_inputs(target=[["华东", "0.000000000000000001"]], target_dtype="DECIMAL(38,18)")
        signal = self.one_computed(inputs)
        self.assertEqual(signal.computed_value["attainment_rate"].value, "100000000000000000000.000000000000")

    def test_largest_approved_magnitude_and_scale_fit_precision(self):
        inputs = s1_inputs([["华东", "9" * 38]], [["华东", "0.000000000000000001"]],
                           actual_dtype="DECIMAL(38,0)", target_dtype="DECIMAL(38,18)")
        signal = self.one_computed(inputs)
        self.assertEqual(signal.computed_value["attainment_rate"].value, "9" * 38 + "0" * 18 + ".000000000000")

    def test_inputs_are_not_prequantized_to_two_currency_decimals(self):
        inputs = s1_inputs([["华东", "0.001"]], [["华东", "0.002"]],
                           actual_dtype="DECIMAL(38,18)", target_dtype="DECIMAL(38,18)")
        signal = self.one_computed(inputs)
        self.assertEqual(signal.current_value.value, "0.001")
        self.assertEqual(signal.computed_value["attainment_rate"].value, "0.500000000000")

    def test_global_decimal_settings_flags_and_traps_are_not_inherited_or_modified(self):
        inputs, receipt, aligned, policy = self.approved(s1_inputs([["华东", "1.00"]], [["华东", "3.00"]]))
        outer_state = decimal_state()
        with localcontext() as ambient:
            ambient.prec, ambient.Emax, ambient.Emin = 3, 2, -2
            ambient.traps[Inexact] = True
            ambient.traps[Rounded] = True
            ambient.flags[Inexact] = True
            expected = decimal_state()
            signal = self.compute(inputs, policy, receipt, aligned)[0]
            self.assertEqual(signal.computed_value["attainment_rate"].value, "0.333333333333")
            self.assertEqual(decimal_state(), expected)
        self.assertEqual(decimal_state(), outer_state)

    def test_stale_policy_receipt_is_rejected_before_numeric_reads(self):
        inputs, receipt, aligned, policy = self.approved()
        raw = policy.model_dump()
        raw["metric_rules"][0]["allowed_sources"][0]["field"] = "other_amount"
        self.assert_gate_rejects(inputs, receipt, aligned, TargetAttainmentPolicy.model_validate(raw))

    def test_stale_metric_selection_is_rejected_before_numeric_reads(self):
        inputs, receipt, aligned, policy = self.approved()
        selection = inputs["actual"].selection.model_copy(update={"metric_column_id": "col_k"})
        inputs["actual"] = inputs["actual"].model_copy(update={"selection": selection}, deep=True)
        self.assert_gate_rejects(inputs, receipt, aligned, policy)

    def test_stale_key_selection_is_rejected_before_numeric_reads(self):
        inputs, receipt, aligned, policy = self.approved()
        selection = inputs["actual"].selection.model_copy(update={"key_column_ids": {"region": "col_m"}})
        inputs["actual"] = inputs["actual"].model_copy(update={"selection": selection}, deep=True)
        self.assert_gate_rejects(inputs, receipt, aligned, policy)

    def test_stale_auxiliary_selection_is_rejected_before_numeric_reads(self):
        inputs, receipt, aligned, policy = self.approved()
        selection = inputs["actual"].selection.model_copy(update={"auxiliary_column_ids": {"audit": "col_m"}})
        inputs["actual"] = inputs["actual"].model_copy(update={"selection": selection}, deep=True)
        self.assert_gate_rejects(inputs, receipt, aligned, policy)

    def test_changed_declaration_claim_is_rejected_before_numeric_reads(self):
        inputs, receipt, aligned, policy = self.approved()
        replace_declaration(inputs, "actual", "unit", lambda raw: raw["claims"]["unit"].update(unit_id="USD"))
        self.assert_gate_rejects(inputs, receipt, aligned, policy)

    def test_changed_context_values_invalidate_the_old_receipt(self):
        inputs, receipt, aligned, policy = self.approved()
        inputs["actual"] = s1_input("actual", [["华东", "900.00"]])
        self.assert_gate_rejects(inputs, receipt, aligned, policy)

    def test_alignment_from_another_current_receipt_is_rejected(self):
        inputs, receipt, aligned, policy = self.approved()
        new_inputs = s1_inputs(actual=[["华东", "110.00"]])
        new_receipt, _, _ = qualify(new_inputs, policy)
        signals = self.assert_gate_rejects(new_inputs, new_receipt, aligned, policy)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].scope, "context")
        self.assertIsNone(signals[0].business_key)

    def test_alignment_pairs_cannot_be_changed_after_production(self):
        inputs, receipt, aligned, policy = self.approved(s1_inputs(
            [["华东", "100.00"], ["华北", "90.00"]], [["华东", "200.00"], ["华北", "30.00"]]))
        changed = aligned.model_copy(update={"pairs": [
            aligned.pairs[0].model_copy(update={"right_row_index": 1}), *aligned.pairs[1:],
        ]}, deep=True)
        self.assert_gate_rejects(inputs, receipt, changed, policy)

    def test_alignment_result_without_source_binding_is_rejected(self):
        inputs, receipt, aligned, policy = self.approved()
        self.assert_gate_rejects(inputs, receipt, aligned.model_copy(update={"binding": None}), policy)

    def test_unknown_alignment_binding_version_is_rejected(self):
        inputs, receipt, aligned, policy = self.approved()
        changed = aligned.model_copy(update={"binding": aligned.binding.model_copy(update={"version": "2"})})
        self.assert_gate_rejects(inputs, receipt, changed, policy)

    def test_alignment_status_cannot_be_promoted_after_production(self):
        inputs = s1_inputs(target=[["华东", "200.00"], ["华东", "300.00"]])
        receipt, aligned, policy = qualify(inputs)
        changed = aligned.model_copy(update={"status": "aligned"}, deep=True)
        self.assert_gate_rejects(inputs, receipt, changed, policy)

    def test_mutated_receipt_period_is_rejected_before_numeric_reads(self):
        inputs, receipt, aligned, policy = self.approved()
        period = receipt.periods[0].period.model_copy(update={"upper": "2026-10-01"})
        changed = receipt.model_copy(update={"periods": [receipt.periods[0].model_copy(update={"period": period}),
                                                         *receipt.periods[1:]]}, deep=True)
        self.assert_gate_rejects(inputs, changed, aligned, policy)

    def test_align_operation_receipt_does_not_authorize_division(self):
        inputs, receipt, aligned, policy = self.approved(operation="align")
        self.assert_gate_rejects(inputs, receipt, aligned, policy)

    def test_missing_unit_declaration_cannot_pass_the_calculation_gate(self):
        inputs = s1_inputs()
        remove_declaration(inputs, "actual", "unit")
        receipt, aligned, policy = qualify(inputs)
        self.assertEqual(receipt.status, "insufficient_evidence")
        self.assert_gate_rejects(inputs, receipt, aligned, policy, status="insufficient_evidence")

    def test_unknown_result_contract_version_is_preserved_in_rejected_evidence(self):
        inputs = s1_inputs()
        raw = inputs["actual"].context.model_dump(mode="python")
        raw["result_contract_version"] = "2"
        inputs["actual"] = supplied_input("s1", "actual", raw)
        receipt, aligned, policy = qualify(inputs)
        self.assertEqual(receipt.status, "unsupported")
        signals = self.assert_gate_rejects(inputs, receipt, aligned, policy, status="unsupported")
        evidence = next(item for item in signals[0].evidence if item.context_role == "actual")
        self.assertEqual(evidence.result_contract_version, "2")
        self.assertEqual(evidence.observed_value.presence, "not_read")

    def test_repeated_identical_accepted_unit_declaration_does_not_revoke_qualification(self):
        inputs = s1_inputs()
        declaration = next(item for item in inputs["actual"].declarations if item.declaration_type == "unit")
        inputs["actual"] = inputs["actual"].model_copy(update={
            "declarations": [*inputs["actual"].declarations, declaration.model_copy(deep=True)],
        }, deep=True)
        signal = self.one_computed(inputs)
        self.assertEqual(signal.computed_value["attainment_rate"].value, "0.500000000000")

    def test_selected_semantic_reason_survives_in_noncomputed_evidence(self):
        inputs = s1_inputs()
        raw = inputs["actual"].context.model_dump(mode="python")
        raw["column_semantics"][1].update(status="unknown", reason="captured opaque metric limitation")
        inputs["actual"] = supplied_input("s1", "actual", raw)
        receipt, aligned, policy = qualify(inputs)
        self.assertNotEqual(receipt.status, "compatible")
        signals = self.assert_gate_rejects(inputs, receipt, aligned, policy, status=receipt.status)
        actual = next(item for item in signals[0].evidence if item.context_role == "actual")
        self.assertIn("captured opaque metric limitation", actual.upstream_limitations)

    def test_unresolved_null_key_blocks_numeric_reading_and_retains_the_issue(self):
        inputs = s1_inputs(actual=[[None, "100.00"]])
        receipt, aligned, policy = qualify(inputs)
        self.assertEqual(receipt.status, "compatible")
        self.assertEqual(aligned.status, "insufficient_evidence")
        signals = self.assert_gate_rejects(inputs, receipt, aligned, policy, status="insufficient_evidence")
        self.assertTrue(any(issue.code == "NULL_KEY" for signal in signals for issue in signal.limitations))
        self.assertTrue(all(signal.current_value.presence != "missing" for signal in signals))

    def test_both_numeric_failures_retain_issues_and_use_priority(self):
        signal = self.compute(s1_inputs([["华东", "-100.00"]], [["华东", "bad-decimal"]]))[0]
        self.assertEqual(signal.status, "unsupported")
        codes = {item.code for item in signal.limitations}
        self.assertIn("NEGATIVE_INPUT_NOT_ALLOWED", codes)
        self.assertIn("INVALID_DECIMAL_TEXT", codes)
        self.assertEqual(signal.current_value.presence, "rejected")
        self.assertEqual(signal.reference_value.presence, "rejected")

    def test_numeric_incompatible_takes_priority_over_sql_null(self):
        signal = self.compute(s1_inputs([["华东", None]], [["华东", "-200.00"]]))[0]
        self.assertEqual(signal.status, "incompatible_context")
        self.assertEqual(signal.current_value.presence, "sql_null")
        self.assertEqual(signal.reference_value.presence, "rejected")

    def test_one_numeric_failure_does_not_remove_other_region_results(self):
        inputs = s1_inputs([["华东", "100.00"], ["华北", None]],
                           [["华东", "200.00"], ["华北", "30.00"]])
        signals = self.compute(inputs)
        by_key = {item.business_key.components[0].normalized_value: item for item in signals}
        self.assertEqual(by_key["华东"].status, "computed")
        self.assertEqual(by_key["华北"].status, "insufficient_evidence")
        self.assertEqual(by_key["华东"].computed_value["attainment_rate"].value, "0.500000000000")

    def test_unit_is_taken_from_the_approved_declaration(self):
        inputs = s1_inputs()
        for role in ("actual", "target"):
            replace_declaration(inputs, role, "unit", lambda raw: raw["claims"]["unit"].update(
                unit_id="fixture_custom_unit", unit_scale="1000"))
        signal = self.one_computed(inputs)
        self.assertEqual(signal.current_value.unit_id, "fixture_custom_unit")
        self.assertEqual(signal.reference_value.unit_id, "fixture_custom_unit")
        self.assertEqual(signal.computed_value["attainment_rate"].unit_id, "ratio")
        for evidence in signal.evidence:
            self.assertEqual(evidence.unit_declaration.claims.unit.unit_id, "fixture_custom_unit")
            self.assertEqual(evidence.unit_declaration.claims.unit.unit_scale, "1000")

    def test_evidence_links_both_result_ids_columns_rows_and_formula(self):
        signal = self.one_computed()
        self.assertEqual(signal.signal_type, "monthly_regional_target_attainment")
        self.assertEqual(signal.scope, "business_key")
        evidence = {item.context_role: item for item in signal.evidence}
        self.assertEqual(set(evidence), {"actual", "target"})
        self.assertEqual(evidence["actual"].result_id, "captured-s1-actual")
        self.assertEqual(evidence["target"].result_id, "captured-s1-target")
        for item in evidence.values():
            self.assertEqual(item.column_id, "col_m")
            self.assertEqual(item.ordinal, 1)
            self.assertEqual(item.row_index, 0)
            self.assertTrue(item.context_digest)
            self.assertTrue(item.eligibility.declarations)
            self.assertIsNotNone(item.unit_declaration)
        result = signal.computed_value["attainment_rate"]
        self.assertEqual(result.formula_id, "attainment_rate")
        self.assertEqual(result.formula_version, "1")
        self.assertEqual(set(result.input_evidence_ids), {item.evidence_id for item in signal.evidence})

    def test_source_semantics_and_original_date_month_precision_are_retained(self):
        signal = self.one_computed()
        evidence = {item.context_role: item for item in signal.evidence}
        self.assertEqual(evidence["actual"].time[0].precision, "date")
        self.assertEqual(evidence["target"].time[0].precision, "month")
        self.assertEqual(evidence["actual"].normalized_period, evidence["target"].normalized_period)
        for item in evidence.values():
            self.assertEqual(item.aggregation, "SUM")
            self.assertTrue(item.source_fields)
            self.assertTrue(item.schema_metadata)
            self.assertEqual(item.grain.query_grain, "grouped")
            self.assertIsNotNone(item.filters)

    def test_signal_identity_is_explicitly_unavailable_not_manufactured(self):
        signal = self.one_computed()
        self.assertIsNone(signal.signal_id)
        self.assertTrue(any(issue.code == "SIGNAL_IDENTITY_NOT_FROZEN" and issue.severity == "info"
                            for issue in signal.limitations))
        self.assertNotEqual(signal.signal_id, signal.evidence[0].result_id)

    def test_business_signal_uses_actual_policy_content_digest(self):
        inputs, receipt, aligned, policy = self.approved()
        signal = self.compute(inputs, policy, receipt, aligned)[0]
        self.assertEqual(signal.policy_digest, receipt.binding.policy_digest)
        self.assertNotEqual(signal.policy_digest, policy.definition_digest)

    def test_equal_content_reconstruction_produces_equal_signals(self):
        inputs, receipt, aligned, policy = self.approved()
        expected = self.compute(inputs, policy, receipt, aligned)
        reconstructed = {role: SignalInput.model_validate(value.model_dump()) for role, value in inputs.items()}
        got = self.compute(reconstructed, TargetAttainmentPolicy.model_validate(policy.model_dump()),
                           ContextCompatibility.model_validate(receipt.model_dump()),
                           AlignmentResult.model_validate(aligned.model_dump()))
        self.assertEqual(got, expected)

    def test_computation_does_not_modify_any_input_snapshot(self):
        inputs, receipt, aligned, policy = self.approved()
        before = copy.deepcopy((inputs, receipt, aligned, policy))
        self.compute(inputs, policy, receipt, aligned)
        self.assertEqual((inputs, receipt, aligned, policy), before)

    def test_evidence_and_business_key_are_detached_from_input_containers(self):
        inputs, receipt, aligned, policy = self.approved()
        before = copy.deepcopy((inputs, receipt, aligned, policy))
        signal = self.compute(inputs, policy, receipt, aligned)[0]
        signal.business_key.components.clear()
        signal.evidence[0].source_fields.clear()
        signal.evidence[0].unit_declaration.column_ids.clear()
        self.assertEqual((inputs, receipt, aligned, policy), before)

    def test_aba_invocations_have_no_state_leakage(self):
        inputs, receipt, aligned, policy = self.approved()
        first = self.compute(inputs, policy, receipt, aligned)
        self.compute(s1_inputs(actual=[["华东", "300.00"]]))
        self.assertEqual(self.compute(inputs, policy, receipt, aligned), first)

    def test_calculation_does_not_rerun_compatibility_or_alignment(self):
        inputs, receipt, aligned, policy = self.approved()
        with patch.object(compatibility, "check_context_compatibility", side_effect=AssertionError("reran qualification")), \
             patch.object(alignment, "align_context_keys", side_effect=AssertionError("reran alignment")):
            signal = self.compute(inputs, policy, receipt, aligned)[0]
        self.assertEqual(signal.status, "computed")

    def test_calculator_has_no_float_conversion_or_upstream_stage_call(self):
        tree = ast.parse(inspect.getsource(target_attainment))
        called = {node.func.id if isinstance(node.func, ast.Name) else node.func.attr
                  for node in ast.walk(tree) if isinstance(node, ast.Call)
                  and isinstance(node.func, (ast.Name, ast.Attribute))}
        self.assertFalse(called & {"float", "check_context_compatibility", "align_context_keys", "execute", "parse_sql", "uuid4"})

    def test_successful_signal_survives_model_json_round_trip(self):
        signal = self.one_computed()
        self.assertEqual(BusinessSignal.model_validate_json(signal.model_dump_json()), signal)


if __name__ == "__main__":
    unittest.main()
