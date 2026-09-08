"""S3 contracts and complete partitions through real qualification producers.

All facts and declarations are synthetic and explicit. No SQL is parsed or
executed. Successful Compatibility and Alignment receipts are never invented.
Evidence integration preserves the established calculator and failure checks.
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

from app.querying.business_signals import alignment, compatibility, evidence, product_contribution
from app.querying.business_signals.models import (
    AlignmentResult, BusinessSignal, ContextCompatibility, ProductContributionInput, SignalInput,
)
from app.querying.business_signals.policies import NumericRules, ProductContributionPolicy
from app.querying.business_signals.product_contribution_policy import (
    category_sales_contribution_v1, product_sales_contribution_v1,
)
from test_business_signal_compatibility import captured_context, replace_declaration, supplied_input


_DEFAULT = object()


def s3_policy(*, product=False, allow_global_total=True, numeric_rules=None):
    if isinstance(numeric_rules, dict):
        numeric_rules = NumericRules.model_validate(numeric_rules)
    factory = product_sales_contribution_v1 if product else category_sales_contribution_v1
    return factory(database="askdata_mock", accepted_issuer_kinds=["fixture_catalog"],
                   accepted_issuer_refs=["demo_v1"], allow_global_total=allow_global_total,
                   numeric_rules=numeric_rules)


def rename_field(value, old, new):
    if isinstance(value, dict):
        if value.get("field") == old:
            value["field"] = new
        for child in value.values():
            rename_field(child, old, new)
    elif isinstance(value, list):
        for child in value:
            rename_field(child, old, new)


def reissue_input(role, raw, *, product=False):
    supplied = supplied_input("s3", role, raw)
    domain = "product-id" if product else "product-category"
    declarations = []
    for declaration in supplied.declarations:
        payload = declaration.model_dump()
        payload["scope"]["key_domains"] = [domain]
        if role == "parts" and declaration.declaration_type == "population":
            payload["claims"]["population"]["partition_key_domains"] = [domain]
        declarations.append(type(declaration).model_validate(payload))
    selection = supplied.selection.model_copy(update={
        "key_column_ids": {} if role == "total" else {"product_id" if product else "category": "col_k"},
    }, deep=True)
    return supplied.model_copy(update={"selection": selection, "declarations": declarations}, deep=True)


def s3_input(role, rows, *, product=False, dtype="DECIMAL(18,2)", metric_first=False,
             lower=None, upper=None):
    raw = captured_context("s3", role, lower=lower, upper=upper)
    if product:
        rename_field(raw, "category", "product_id")
        if role == "parts":
            raw["execution"]["columns"][0]["dtype"] = "INTEGER"
    raw["execution"].update(rows=copy.deepcopy(rows), returned_rows=None if rows is None else len(rows),
                            total_rows=None if rows is None else len(rows))
    metric_index = 1 if role == "parts" else 0
    raw["execution"]["columns"][metric_index].update(
        dtype=dtype, value_encoding="decimal_text" if dtype.startswith("DECIMAL(") else "native_json",
    )
    if metric_first and role == "parts":
        raw["execution"]["columns"].reverse()
        raw["column_semantics"].reverse()
        for index, column in enumerate(raw["execution"]["columns"]):
            column.update(ordinal=index, name="same_alias")
        for index, semantic in enumerate(raw["column_semantics"]):
            semantic.update(ordinal=index, output_name="same_alias")
        if rows is not None:
            raw["execution"]["rows"] = [[row[1], row[0]] for row in rows]
    return reissue_input(role, raw, product=product)


def s3_inputs(parts=_DEFAULT, total=_DEFAULT, *, product=False, dtype="DECIMAL(18,2)",
              total_dtype=None, metric_first=False):
    keys = (1, 2) if product else ("A", "B")
    parts = [[keys[0], "40.00"], [keys[1], "60.00"]] if parts is _DEFAULT else parts
    total = [["100.00"]] if total is _DEFAULT else total
    return ProductContributionInput(
        parts=s3_input("parts", parts, product=product, dtype=dtype, metric_first=metric_first),
        total=s3_input("total", total, product=product, dtype=total_dtype or dtype),
    )


def roles(inputs):
    return {"parts": inputs.parts, "total": inputs.total}


def change_declaration(inputs, role, name, mutate):
    updated = roles(inputs)
    replace_declaration(updated, role, name, mutate)
    return ProductContributionInput(**updated)


def qualify(inputs, policy=None, *, operation="divide"):
    policy = policy or s3_policy()
    receipt = compatibility.check_context_compatibility(roles(inputs), policy, operation=operation)
    aligned = alignment.align_context_keys(roles(inputs), receipt, policy)
    return receipt, aligned, policy


def rehash_policy(raw):
    """Bind a deliberately changed definition before testing profile rejection."""
    policy = ProductContributionPolicy.model_validate(raw)
    payload = policy.model_dump(mode="python", exclude={"definition_digest"})
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    digest = "policy-definition-v1:sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return policy.model_copy(update={"definition_digest": digest}, deep=True)


def rational_ratio(part, total):
    """Independent HALF_EVEN oracle using only integer arithmetic after parsing."""
    exact = Fraction(Decimal(part)) / Fraction(Decimal(total))
    scaled = exact * 10**12
    whole, remainder = divmod(scaled.numerator, scaled.denominator)
    if remainder * 2 > scaled.denominator or (remainder * 2 == scaled.denominator and whole % 2):
        whole += 1
    return f"{whole // 10**12}.{whole % 10**12:012d}", exact


def decimal_state():
    context = getcontext()
    return (context.prec, context.rounding, context.Emin, context.Emax, context.capitals,
            context.clamp, dict(context.flags), dict(context.traps))


class ProductContributionTests(unittest.TestCase):
    def compute(self, inputs=None, policy=None, receipt=None, aligned=None):
        inputs = s3_inputs() if inputs is None else inputs
        if receipt is None or aligned is None:
            receipt, aligned, policy = qualify(inputs, policy)
        return product_contribution.compute_product_contribution(inputs, receipt, aligned, policy)

    def approved(self, inputs=None, policy=None):
        inputs = s3_inputs() if inputs is None else inputs
        receipt, aligned, policy = qualify(inputs, policy)
        self.assertEqual(receipt.status, "compatible", receipt.model_dump())
        self.assertEqual(aligned.status, "aligned", aligned.model_dump())
        self.assertTrue(aligned.broadcastable)
        self.assertEqual(aligned.broadcast_role, "total")
        self.assertTrue(all(pair.broadcast and pair.right_row_index == 0 and pair.right_key is None
                            for pair in aligned.pairs))
        return inputs, receipt, aligned, policy

    def assert_operand_evidence(self, signals):
        for signal in signals:
            self.assertEqual([item.evidence_id for item in signal.evidence], ["parts:metric", "total:metric"])
            self.assertEqual(signal.current_value, signal.evidence[0].observed_value)
            self.assertEqual(signal.reference_value, signal.evidence[1].observed_value)
            self.assertEqual(signal.current_value.evidence_id, "parts:metric")
            self.assertEqual(signal.reference_value.evidence_id, "total:metric")
            self.assertEqual(signal.computed_value["contribution_rate"].input_evidence_ids,
                             ["parts:metric", "total:metric"])
            self.assertEqual([ref.context_role for ref in signal.operand_references], ["parts", "total"])
            for ref in signal.operand_references:
                self.assertTrue(ref.result_id)
                self.assertTrue(ref.context_digest)
                self.assertFalse({"value", "raw_value", "quality", "evidence_id", "computed_value"}
                                 & set(ref.model_dump()))

    def assert_noncomputed(self, signals, status=None):
        self.assertTrue(signals)
        self.assert_operand_evidence(signals)
        for signal in signals:
            if status is not None:
                self.assertEqual(signal.status, status)
            self.assertNotEqual(signal.status, "computed")
            self.assertEqual(set(signal.computed_value), {"contribution_rate"})
            self.assertIsNone(signal.computed_value["contribution_rate"].value)
            self.assertNotEqual(signal.computed_value["contribution_rate"].status, "computed")

    def assert_gate(self, inputs, receipt, aligned, policy, status=None):
        with patch.object(product_contribution, "read_numeric_value", side_effect=AssertionError("numeric before gate")):
            signals = self.compute(inputs, policy, receipt, aligned)
        self.assert_noncomputed(signals, status)
        return signals

    def test_category_100_of_400_is_one_quarter(self):
        signals = self.compute(s3_inputs([["A", "100.00"], ["B", "300.00"]], [["400.00"]]))
        by_key = {signal.business_key.components[0].normalized_value: signal for signal in signals}
        self.assertEqual(by_key["A"].status, "computed")
        self.assertEqual(by_key["A"].computed_value["contribution_rate"].value, "0.250000000000")
        self.assertEqual(by_key["B"].computed_value["contribution_rate"].value, "0.750000000000")
        self.assert_operand_evidence(signals)

    def test_multiple_parts_and_reordering_preserve_business_keys(self):
        signals = self.compute(s3_inputs([["C", "50.00"], ["A", "20.00"], ["B", "30.00"]]))
        self.assertEqual([signal.business_key.components[0].normalized_value for signal in signals], ["A", "B", "C"])
        self.assertEqual([signal.computed_value["contribution_rate"].value for signal in signals],
                         ["0.200000000000", "0.300000000000", "0.500000000000"])
        self.assertEqual([signal.operand_references[0].row_index for signal in signals], [1, 2, 0])

    def test_product_profile_uses_integer_product_id_keys(self):
        inputs = s3_inputs(product=True)
        inputs, receipt, aligned, policy = self.approved(inputs, s3_policy(product=True))
        signals = self.compute(inputs, policy, receipt, aligned)
        self.assertEqual([signal.business_key.components[0].normalized_value for signal in signals], [1, 2])
        self.assertTrue(all(type(signal.business_key.components[0].normalized_value) is int for signal in signals))
        self.assertTrue(all(signal.business_key.components[0].component_id == "product_id" for signal in signals))
        self.assertTrue(all(signal.status == "computed" for signal in signals))

    def test_product_id_string_and_boolean_values_cannot_be_coerced(self):
        for key in ("1", True):
            with self.subTest(key=key):
                inputs = s3_inputs([[key, "100.00"]], product=True)
                receipt, aligned, policy = qualify(inputs, s3_policy(product=True))
                self.assert_gate(inputs, receipt, aligned, policy, "incompatible_context")

    def test_product_profile_rejects_varchar_key_metadata(self):
        inputs = s3_inputs([["1", "100.00"]], product=True)
        raw = inputs.parts.context.model_dump()
        raw["execution"]["columns"][0]["dtype"] = "VARCHAR"
        inputs = inputs.model_copy(update={"parts": reissue_input("parts", raw, product=True)}, deep=True)
        receipt, aligned, policy = qualify(inputs, s3_policy(product=True))
        self.assert_gate(inputs, receipt, aligned, policy)

    def test_category_identity_does_not_trim_distinct_keys(self):
        signals = self.compute(s3_inputs([["A", "40.00"], ["A ", "60.00"]]))
        self.assertEqual({signal.business_key.components[0].raw_value for signal in signals}, {"A", "A "})
        self.assertTrue(all(signal.status == "computed" for signal in signals))

    def test_metric_selection_uses_id_and_ordinal_not_alias(self):
        signals = self.compute(s3_inputs(metric_first=True))
        self.assertTrue(all(signal.status == "computed" for signal in signals))
        self.assertTrue(all((signal.operand_references[0].column_id, signal.operand_references[0].ordinal)
                            == ("col_m", 0) for signal in signals))

    def test_total_broadcast_preserves_real_identity_with_evidence(self):
        inputs, receipt, aligned, policy = self.approved()
        signals = self.compute(inputs, policy, receipt, aligned)
        self.assert_operand_evidence(signals)
        for signal in signals:
            part, total = signal.operand_references
            self.assertEqual((part.result_id, total.result_id), (inputs.parts.context.result_id, inputs.total.context.result_id))
            self.assertEqual((total.column_id, total.ordinal, total.row_index), ("col_m", 0, 0))
            self.assertTrue(part.alignment_broadcast)
            self.assertTrue(total.alignment_broadcast)
            self.assertEqual(signal.reference_value.value, "100.00")
            self.assertEqual(total.context_digest, receipt.input_digests["total"])

    def test_legal_input_bundle_is_required_and_missing_roles_are_not_synthesized(self):
        inputs = s3_inputs()
        for payload in ({"parts": inputs.parts}, {"total": inputs.total}, {"parts": inputs.parts, "total": None}):
            with self.subTest(payload=payload), self.assertRaises((TypeError, ValueError)):
                ProductContributionInput.model_validate(payload)

    def test_empty_parts_do_not_invent_a_product(self):
        inputs = s3_inputs([], [["0.00"]])
        receipt, aligned, policy = qualify(inputs)
        signals = self.assert_gate(inputs, receipt, aligned, policy, "insufficient_evidence")
        self.assertTrue(all(signal.scope == "context" and signal.business_key is None for signal in signals))

    def test_empty_total_is_missing_evidence_not_zero(self):
        inputs = s3_inputs(total=[])
        receipt, aligned, policy = qualify(inputs)
        signals = self.assert_gate(inputs, receipt, aligned, policy, "insufficient_evidence")
        self.assertTrue(all(signal.reference_value.value is None for signal in signals))

    def test_unknown_total_payload_does_not_claim_a_row(self):
        inputs = s3_inputs(total=None)
        receipt, aligned, policy = qualify(inputs)
        signals = self.assert_gate(inputs, receipt, aligned, policy, "insufficient_evidence")
        self.assertTrue(all(signal.operand_references[1].row_index is None for signal in signals))

    def test_multiple_total_rows_are_not_reduced_to_the_first(self):
        inputs = s3_inputs(total=[["100.00"], ["999.00"]])
        receipt, aligned, policy = qualify(inputs)
        self.assert_gate(inputs, receipt, aligned, policy, "incompatible_context")

    def test_grouped_total_is_not_global_total(self):
        inputs = s3_inputs()
        raw = inputs.parts.context.model_dump()
        raw["result_id"] = inputs.total.context.result_id
        raw["execution"].update(rows=[["all", "100.00"]], returned_rows=1, total_rows=1)
        inputs = inputs.model_copy(update={"total": reissue_input("total", raw)}, deep=True)
        receipt, aligned, policy = qualify(inputs)
        self.assert_gate(inputs, receipt, aligned, policy, "incompatible_context")

    def test_total_cannot_have_a_key_selection(self):
        inputs = s3_inputs()
        selection = inputs.total.selection.model_copy(update={"key_column_ids": {"category": "col_m"}})
        inputs = inputs.model_copy(update={"total": inputs.total.model_copy(update={"selection": selection}, deep=True)})
        receipt, aligned, policy = qualify(inputs)
        self.assert_gate(inputs, receipt, aligned, policy, "incompatible_context")

    def test_broadcast_requires_explicit_policy_permission(self):
        inputs = s3_inputs()
        receipt, aligned, policy = qualify(inputs, s3_policy(allow_global_total=False))
        self.assert_gate(inputs, receipt, aligned, policy)

    def test_shape_helper_accepts_only_one_ordinary_nonbroadcast_match(self):
        # The current producer always broadcasts its global total. Exercise
        # the defensive shape contract only; do not rebind this changed result
        # or present it to the public calculator as a successful producer.
        _, receipt, aligned, _ = self.approved(s3_inputs([["A", "100.00"]]))
        ordinary = aligned.model_copy(update={
            "broadcastable": False, "broadcast_role": None,
            "pairs": [aligned.pairs[0].model_copy(update={"broadcast": False})],
        }, deep=True)
        self.assertTrue(product_contribution._alignment_shape_matches(ordinary, receipt, 1))
        self.assertFalse(product_contribution._alignment_shape_matches(ordinary, receipt, 2))
        self.assertFalse(product_contribution._alignment_shape_matches(
            ordinary.model_copy(update={"broadcastable": True, "broadcast_role": "total"}), receipt, 1))

    def test_shape_helper_rejects_mixed_broadcast_and_unobserved_total_locations(self):
        _, receipt, aligned, _ = self.approved()
        for change in ({"broadcast": False}, {"right_row_index": 1}, {"right_key": aligned.pairs[0].left_key}):
            with self.subTest(change=change):
                changed = aligned.model_copy(deep=True)
                changed.pairs[0] = changed.pairs[0].model_copy(update=change)
                self.assertFalse(product_contribution._alignment_shape_matches(changed, receipt, 2))

    def test_duplicate_parts_are_not_aggregated(self):
        inputs = s3_inputs([["A", "40.00"], ["A", "60.00"]])
        receipt, aligned, policy = qualify(inputs)
        signals = self.assert_gate(inputs, receipt, aligned, policy, "incompatible_context")
        self.assertTrue(any(issue.code == "DUPLICATE_KEY" for signal in signals for issue in signal.limitations))

    def test_null_part_key_does_not_become_a_missing_product(self):
        inputs = s3_inputs([[None, "40.00"], ["B", "60.00"]])
        receipt, aligned, policy = qualify(inputs)
        signals = self.assert_gate(inputs, receipt, aligned, policy, "insufficient_evidence")
        self.assertTrue(any(issue.code == "NULL_KEY" for signal in signals for issue in signal.limitations))

    def test_explicit_normalization_collision_blocks_partition(self):
        raw = s3_policy().model_dump()
        raw["key_rules"][0].update(normalization="explicit_mapping", mapping_id="approved-category-map",
                                   mapping_version="1", value_mappings=[
                                       {"raw_value": "A", "normalized_value": "A"},
                                       {"raw_value": "A ", "normalized_value": "A"},
                                   ])
        inputs = s3_inputs([["A", "40.00"], ["A ", "60.00"]])
        receipt, aligned, policy = qualify(inputs, rehash_policy(raw))
        self.assertEqual(receipt.status, "compatible")
        self.assertTrue(any(item.normalization_collision for item in aligned.duplicate_keys))
        self.assert_gate(inputs, receipt, aligned, policy, "incompatible_context")

    def test_missing_partition_proof_is_not_replaced_by_matching_sum(self):
        inputs = change_declaration(s3_inputs(), "parts", "population",
                                    lambda raw: raw["claims"]["population"].update(partition_key_domains=[]))
        receipt, aligned, policy = qualify(inputs)
        self.assert_gate(inputs, receipt, aligned, policy, "insufficient_evidence")

    def test_unknown_and_incomplete_population_have_distinct_failures(self):
        for coverage, expected in (("unknown", "insufficient_evidence"), ("incomplete", "incompatible_context")):
            with self.subTest(coverage=coverage):
                inputs = change_declaration(s3_inputs(), "total", "population",
                                            lambda raw: raw["claims"]["population"].update(coverage=coverage))
                receipt, aligned, policy = qualify(inputs)
                self.assert_gate(inputs, receipt, aligned, policy, expected)

    def test_total_limit_one_and_parts_or_total_top_n_are_rejected(self):
        for role, mode in (("total", "limit"), ("parts", "top_n"), ("total", "top_n")):
            with self.subTest(role=role, mode=mode):
                inputs = change_declaration(s3_inputs(), role, "row_selection",
                                            lambda raw: raw["claims"]["row_selection"].update(mode=mode, limit=1))
                receipt, aligned, policy = qualify(inputs)
                self.assert_gate(inputs, receipt, aligned, policy, "incompatible_context")

    def test_missing_row_selection_attestation_does_not_trigger_sql_inspection(self):
        inputs = s3_inputs()
        supplied = inputs.total.model_copy(update={"declarations": [
            item for item in inputs.total.declarations if item.declaration_type != "row_selection"
        ]}, deep=True)
        inputs = inputs.model_copy(update={"total": supplied}, deep=True)
        receipt, aligned, policy = qualify(inputs)
        self.assert_gate(inputs, receipt, aligned, policy, "insufficient_evidence")

    def test_truncated_output_cannot_be_a_complete_denominator(self):
        inputs = s3_inputs()
        raw = inputs.total.context.model_dump()
        raw["execution"].update(truncated=True, completeness="partial_query_output", total_rows=2)
        inputs = inputs.model_copy(update={"total": reissue_input("total", raw)}, deep=True)
        receipt, aligned, policy = qualify(inputs)
        self.assert_gate(inputs, receipt, aligned, policy, "incompatible_context")

    def test_different_periods_are_rejected(self):
        inputs = s3_inputs()
        inputs = inputs.model_copy(update={"total": s3_input("total", [["100.00"]],
                                                           lower="2026-07-01", upper="2026-08-01")}, deep=True)
        receipt, aligned, policy = qualify(inputs)
        self.assert_gate(inputs, receipt, aligned, policy, "incompatible_context")

    def test_same_explicit_nonmonthly_window_is_supported(self):
        inputs = ProductContributionInput(
            parts=s3_input("parts", [["A", "40.00"], ["B", "60.00"]], lower="2026-08-05", upper="2026-08-21"),
            total=s3_input("total", [["100.00"]], lower="2026-08-05", upper="2026-08-21"),
        )
        self.assertTrue(all(signal.status == "computed" for signal in self.compute(inputs)))

    def test_paid_filter_conflict_is_rejected(self):
        inputs = s3_inputs()
        raw = inputs.total.context.model_dump()
        raw["filters"]["filters"][2]["value"] = "unpaid"
        inputs = inputs.model_copy(update={"total": reissue_input("total", raw)}, deep=True)
        receipt, aligned, policy = qualify(inputs)
        self.assert_gate(inputs, receipt, aligned, policy, "incompatible_context")

    def test_unit_and_scale_conflicts_are_not_converted(self):
        for change in ({"unit_id": "USD"}, {"unit_scale": "1000"}):
            with self.subTest(change=change):
                inputs = change_declaration(s3_inputs(), "total", "unit", lambda raw: raw["claims"]["unit"].update(change))
                receipt, aligned, policy = qualify(inputs)
                self.assert_gate(inputs, receipt, aligned, policy, "incompatible_context")

    def test_revision_conflict_is_not_ignored_when_numbers_match(self):
        inputs = change_declaration(s3_inputs(), "total", "snapshot_revision",
                                    lambda raw: raw["claims"]["snapshot_revision"].update(revision_ref="other-revision"))
        receipt, aligned, policy = qualify(inputs)
        self.assert_gate(inputs, receipt, aligned, policy, "incompatible_context")

    def test_fixed_profile_rejects_order_amount_and_same_alias_wrong_table(self):
        for mismatch in ("field", "table"):
            with self.subTest(mismatch=mismatch):
                inputs = s3_inputs()
                raw = inputs.parts.context.model_dump()
                if mismatch == "field":
                    rename_field(raw, "paid_amount", "order_amount")
                else:
                    metric = raw["column_semantics"][1]
                    metric["lineage"][0]["table"] = "orders_history"
                    metric["schema_bindings"][0]["source"]["table"] = "orders_history"
                    for item in raw["query_bindings"]["bindings"]:
                        if item["source"]["field"] == "paid_amount":
                            item["source"]["table"] = "orders_history"
                inputs = inputs.model_copy(update={"parts": reissue_input("parts", raw)}, deep=True)
                receipt, aligned, policy = qualify(inputs)
                self.assert_gate(inputs, receipt, aligned, policy, "incompatible_context")

    def test_avg_count_and_unknown_aggregation_are_not_sales_sum(self):
        for aggregation in ("AVG", "COUNT", None):
            with self.subTest(aggregation=aggregation):
                inputs = s3_inputs()
                raw = inputs.parts.context.model_dump()
                raw["column_semantics"][1]["aggregation"] = aggregation
                inputs = inputs.model_copy(update={"parts": reissue_input("parts", raw)}, deep=True)
                receipt, aligned, policy = qualify(inputs)
                self.assert_gate(inputs, receipt, aligned, policy)

    def test_fresh_correctly_hashed_profit_and_margin_policies_cannot_expand_profile(self):
        for field in ("profit_amount", "margin_amount"):
            with self.subTest(field=field):
                inputs = s3_inputs()
                raw_policy = s3_policy().model_dump()
                rename_field(raw_policy, "paid_amount", field)
                for role in ("parts", "total"):
                    raw = getattr(inputs, role).context.model_dump()
                    rename_field(raw, "paid_amount", field)
                    inputs = inputs.model_copy(update={role: reissue_input(role, raw)}, deep=True)
                receipt, aligned, policy = qualify(inputs, rehash_policy(raw_policy))
                self.assertEqual((receipt.status, aligned.status), ("compatible", "aligned"))
                self.assert_gate(inputs, receipt, aligned, policy, "unsupported")

    def test_fresh_correctly_hashed_customer_and_region_policies_cannot_expand_profile(self):
        for field in ("customer_id", "region"):
            with self.subTest(field=field):
                inputs = s3_inputs()
                raw_policy = s3_policy().model_dump()
                rename_field(raw_policy, "category", field)
                raw = inputs.parts.context.model_dump()
                rename_field(raw, "category", field)
                inputs = inputs.model_copy(update={"parts": reissue_input("parts", raw)}, deep=True)
                receipt, aligned, policy = qualify(inputs, rehash_policy(raw_policy))
                self.assertEqual((receipt.status, aligned.status), ("compatible", "aligned"))
                self.assert_gate(inputs, receipt, aligned, policy, "unsupported")

    def test_total_zero_with_all_zero_parts_is_undefined(self):
        signals = self.compute(s3_inputs([["A", "0.00"], ["B", "-0.00"]], [["0.00"]]))
        self.assert_noncomputed(signals, "undefined")
        self.assertEqual(len(signals), 2)
        self.assertTrue(all(signal.computed_value["contribution_rate"].reason_code == "ZERO_TOTAL" for signal in signals))

    def test_zero_total_with_any_positive_part_is_incompatible(self):
        signals = self.compute(s3_inputs([["A", "0.00"], ["B", "0.01"]], [["0.00"]]))
        self.assert_noncomputed(signals, "incompatible_context")
        self.assertTrue(all(signal.computed_value["contribution_rate"].reason_code != "ZERO_TOTAL" for signal in signals))

    def test_zero_part_with_positive_total_has_zero_contribution(self):
        signals = self.compute(s3_inputs([["A", "0.00"], ["B", "100.00"]]))
        self.assertEqual([signal.computed_value["contribution_rate"].value for signal in signals],
                         ["0.000000000000", "1.000000000000"])

    def test_part_above_total_is_not_clamped(self):
        self.assert_noncomputed(self.compute(s3_inputs([["A", "101.00"], ["B", "0.00"]])), "incompatible_context")

    def test_partition_sum_mismatch_is_rejected_in_both_directions(self):
        for second in ("59.99", "60.01"):
            with self.subTest(second=second):
                self.assert_noncomputed(self.compute(s3_inputs([["A", "40.00"], ["B", second]])), "incompatible_context")

    def test_one_null_part_blocks_every_contribution_in_the_partition(self):
        inputs, receipt, aligned, policy = self.approved(s3_inputs([["A", "40.00"], ["B", None]]))
        signals = self.compute(inputs, policy, receipt, aligned)
        self.assert_noncomputed(signals, "insufficient_evidence")
        null = next(signal for signal in signals if signal.business_key.components[0].normalized_value == "B")
        self.assertEqual(null.current_value.presence, "sql_null")
        self.assertEqual(null.operand_references[0].row_index, 1)

    def test_null_total_has_a_real_row_but_no_contribution(self):
        signals = self.compute(s3_inputs(total=[[None]]))
        self.assert_noncomputed(signals, "insufficient_evidence")
        self.assertTrue(all(signal.reference_value.presence == "sql_null" for signal in signals))
        self.assertTrue(all(signal.operand_references[1].row_index == 0 for signal in signals))

    def test_negative_part_or_total_blocks_all_outputs(self):
        for inputs in (s3_inputs([["A", "-1.00"], ["B", "101.00"]]), s3_inputs(total=[["-100.00"]])):
            with self.subTest(inputs=inputs):
                self.assert_noncomputed(self.compute(inputs), "incompatible_context")

    def test_one_numeric_rejection_blocks_other_readable_parts(self):
        signals = self.compute(s3_inputs([["A", "bad-decimal"], ["B", "60.00"]]))
        self.assert_noncomputed(signals, "unsupported")
        self.assertTrue(any(issue.code == "INVALID_DECIMAL_TEXT" for signal in signals for issue in signal.limitations))

    def test_unreadable_partition_never_enters_reconciliation_or_ratio(self):
        for value in (None, "bad-decimal"):
            with self.subTest(value=value):
                inputs, receipt, aligned, policy = self.approved(s3_inputs([["A", value], ["B", "60.00"]]))
                with patch.object(product_contribution, "_reconcile", side_effect=AssertionError("unreadable partition")), \
                     patch.object(product_contribution, "_ratio", side_effect=AssertionError("unreadable operand")):
                    signals = self.compute(inputs, policy, receipt, aligned)
                self.assert_noncomputed(signals)

    def test_zero_and_inconsistent_partition_never_enter_ratio_evaluation(self):
        for parts, total in (([["A", "0"]], [["0"]]), ([["A", "1"]], [["0"]]),
                             ([["A", "40"], ["B", "59"]], [["100"]])):
            with self.subTest(parts=parts, total=total):
                inputs, receipt, aligned, policy = self.approved(s3_inputs(parts, total))
                with patch.object(product_contribution, "_ratio", side_effect=AssertionError("partition not ready")):
                    signals = self.compute(inputs, policy, receipt, aligned)
                self.assert_noncomputed(signals)

    def test_double_is_rejected_without_explicit_numeric_permission(self):
        inputs = s3_inputs([["A", 40.0], ["B", 60.0]], [[100.0]], dtype="DOUBLE")
        receipt, aligned, policy = qualify(inputs)
        self.assert_gate(inputs, receipt, aligned, policy, "incompatible_context")

    def test_authorized_double_preserves_approximate_quality(self):
        policy = s3_policy(numeric_rules={"profile": "reporting_approx_v1", "allow_binary_float": True,
                                         "accepted_encodings": ["native_json", "decimal_text"]})
        signals = self.compute(s3_inputs([["A", 40.0], ["B", 60.0]], [[100.0]], dtype="DOUBLE"), policy)
        self.assertTrue(all(signal.status == "computed" for signal in signals))
        self.assertTrue(all(signal.computed_value["contribution_rate"].numeric_quality.source_fidelity == "approximate"
                            for signal in signals))

    def test_allowing_float_does_not_implicitly_enable_tolerance(self):
        policy = s3_policy(numeric_rules={"profile": "reporting_approx_v1", "allow_binary_float": True,
                                         "accepted_encodings": ["native_json", "decimal_text"]})
        inputs = s3_inputs([["A", 0.1], ["B", 0.2]], [[0.1 + 0.2]], dtype="DOUBLE")
        self.assert_noncomputed(self.compute(inputs, policy), "incompatible_context")

    def test_exact_reconciliation_rejects_even_a_tiny_nonzero_residual(self):
        inputs = s3_inputs([["A", "500"], ["B", "500.000000000000000001"]], [["1000"]], dtype="DECIMAL(38,18)")
        self.assert_noncomputed(self.compute(inputs), "incompatible_context")

    def test_relative_partition_tolerance_includes_boundary_but_not_beyond(self):
        policy = s3_policy(numeric_rules={"profile": "reporting_approx_v1", "allow_binary_float": True,
                                         "accepted_encodings": ["native_json", "decimal_text"],
                                         "reconciliation": "relative_tolerance", "relative_tolerance": "1e-12"})
        for second, accepted in (("500.000000000999", True), ("500.000000001", True),
                                 ("500.000000001001", False), ("499.999999999", True),
                                 ("499.999999998999", False)):
            with self.subTest(second=second):
                signals = self.compute(s3_inputs([["A", "500"], ["B", second]], [["1000"]], dtype="DECIMAL(38,18)"), policy)
                if accepted:
                    self.assertTrue(all(signal.status == "computed" for signal in signals))
                    self.assertTrue(all(signal.computed_value["contribution_rate"].numeric_quality.source_fidelity == "exact"
                                        for signal in signals))
                else:
                    self.assert_noncomputed(signals, "incompatible_context")

    def test_relative_single_part_excess_is_not_clamped(self):
        policy = s3_policy(numeric_rules={"profile": "reporting_approx_v1", "allow_binary_float": True,
                                         "accepted_encodings": ["native_json", "decimal_text"],
                                         "reconciliation": "relative_tolerance", "relative_tolerance": "1e-12"})
        inputs = s3_inputs([["A", "1000.000000001"]], [["1000"]], dtype="DECIMAL(38,18)")
        signal = self.compute(inputs, policy)[0]
        self.assertEqual(signal.status, "computed")
        self.assertEqual(signal.computed_value["contribution_rate"].value, "1.000000000001")
        outside = s3_inputs([["A", "1000.000000001001"]], [["1000"]], dtype="DECIMAL(38,18)")
        self.assert_noncomputed(self.compute(outside, policy), "incompatible_context")

    def test_tolerance_cannot_erase_a_positive_part_against_zero_total(self):
        policy = s3_policy(numeric_rules={"profile": "reporting_approx_v1", "allow_binary_float": True,
                                         "accepted_encodings": ["native_json", "decimal_text"],
                                         "reconciliation": "relative_tolerance", "relative_tolerance": "1e-12"})
        inputs = s3_inputs([["A", "0.000000000000000001"]], [["0"]], dtype="DECIMAL(38,18)")
        self.assert_noncomputed(self.compute(inputs, policy), "incompatible_context")

    def test_ratio_rounding_does_not_adjust_the_last_part_to_force_sum_one(self):
        signals = self.compute(s3_inputs([["A", "1"], ["B", "1"], ["C", "1"]], [["3"]]))
        values = [signal.computed_value["contribution_rate"].value for signal in signals]
        self.assertEqual(values, ["0.333333333333"] * 3)
        self.assertEqual(sum(Decimal(value) for value in values), Decimal("0.999999999999"))

    def test_extreme_precision_matches_independent_fraction_oracle(self):
        amounts = ["0.000000000000000001", "99999999999999999999.999999999999999998"]
        total = "99999999999999999999.999999999999999999"
        signals = self.compute(s3_inputs([["A", amounts[0]], ["B", amounts[1]]], [[total]], dtype="DECIMAL(38,18)"))
        for signal, amount in zip(signals, amounts):
            expected, exact = rational_ratio(amount, total)
            result = signal.computed_value["contribution_rate"]
            self.assertEqual(result.value, expected)
            self.assertEqual(result.numeric_quality.arithmetic_rounding,
                             "exact" if Fraction(Decimal(result.value)) == exact else "rounded")

    def test_small_nonzero_total_is_not_a_zero_denominator(self):
        inputs = s3_inputs([["A", "0.000000000000000001"]], [["0.000000000000000001"]], dtype="DECIMAL(38,18)")
        signal = self.compute(inputs)[0]
        self.assertEqual(signal.status, "computed")
        self.assertEqual(signal.computed_value["contribution_rate"].value, "1.000000000000")

    def test_max_parts_boundary_is_global_and_never_truncates(self):
        policy = s3_policy(numeric_rules={"profile": "decimal_exact_v1", "accepted_encodings": ["native_json", "decimal_text"],
                                         "max_parts": 2})
        self.assertTrue(all(signal.status == "computed" for signal in self.compute(s3_inputs(), policy)))
        inputs = s3_inputs([["A", "20"], ["B", "30"], ["C", "50"]])
        receipt, aligned, policy = qualify(inputs, policy)
        self.assert_gate(inputs, receipt, aligned, policy, "unsupported")

    def test_global_decimal_settings_flags_and_traps_are_not_inherited_or_mutated(self):
        inputs, receipt, aligned, policy = self.approved(s3_inputs([["A", "1"], ["B", "2"]], [["3"]]))
        outer = decimal_state()
        with localcontext() as ambient:
            ambient.prec = 3
            ambient.Emin, ambient.Emax = -2, 2
            for trap in ambient.traps:
                ambient.traps[trap] = True
            ambient.flags[Inexact] = ambient.flags[Rounded] = True
            before = decimal_state()
            signals = self.compute(inputs, policy, receipt, aligned)
            self.assertEqual([signal.computed_value["contribution_rate"].value for signal in signals],
                             ["0.333333333333", "0.666666666667"])
            self.assertEqual(decimal_state(), before)
        self.assertEqual(decimal_state(), outer)

    def test_stale_policy_selection_claim_and_rows_are_rejected_before_numeric(self):
        for mutation in ("policy", "metric", "key", "aux", "claim", "rows"):
            with self.subTest(mutation=mutation):
                inputs, receipt, aligned, policy = self.approved()
                if mutation == "policy":
                    raw = policy.model_dump()
                    raw["metric_rules"][0]["allowed_sources"][0]["field"] = "other_amount"
                    policy = ProductContributionPolicy.model_validate(raw)
                elif mutation in ("metric", "key", "aux"):
                    change = {"metric": {"metric_column_id": "col_k"}, "key": {"key_column_ids": {"category": "col_m"}},
                              "aux": {"auxiliary_column_ids": {"audit": "col_m"}}}[mutation]
                    inputs = inputs.model_copy(update={"parts": inputs.parts.model_copy(update={
                        "selection": inputs.parts.selection.model_copy(update=change),
                    }, deep=True)}, deep=True)
                elif mutation == "claim":
                    inputs = change_declaration(inputs, "parts", "unit", lambda raw: raw["claims"]["unit"].update(unit_id="USD"))
                else:
                    inputs = inputs.model_copy(update={"parts": s3_input("parts", [["A", "41.00"], ["B", "59.00"]])})
                self.assert_gate(inputs, receipt, aligned, policy, "incompatible_context")

    def test_receipt_semantic_changes_are_rejected_before_numeric(self):
        for field in ("period", "relationship", "filter", "domain", "declarations"):
            with self.subTest(field=field):
                inputs, receipt, aligned, policy = self.approved()
                raw = receipt.model_dump()
                if field == "period":
                    raw["periods"][0]["period"]["upper"] = "2026-10-01"
                elif field == "relationship":
                    raw["normalized_metric_refs"][0]["relationship_id"] = "different-relationship"
                elif field == "filter":
                    raw["non_time_filters"][0]["value"]["value"] = "unpaid"
                elif field == "domain":
                    raw["key_domains"] = ["other-domain"]
                else:
                    raw["declarations_used"] = raw["declarations_used"][1:]
                self.assert_gate(inputs, ContextCompatibility.model_validate(raw), aligned, policy, "incompatible_context")

    def test_unbound_or_unknown_receipt_and_alignment_versions_are_rejected(self):
        for stage in ("receipt", "alignment"):
            for version in (None, "2"):
                with self.subTest(stage=stage, version=version):
                    inputs, receipt, aligned, policy = self.approved()
                    original = receipt if stage == "receipt" else aligned
                    changed = original.model_copy(update={"binding": None if version is None else original.binding.model_copy(update={"version": version})})
                    self.assert_gate(inputs, changed if stage == "receipt" else receipt,
                                     changed if stage == "alignment" else aligned, policy, "incompatible_context")

    def test_old_alignment_does_not_authorize_new_receipt(self):
        _, _, old_alignment, policy = self.approved()
        inputs = s3_inputs([["A", "41.00"], ["B", "59.00"]])
        receipt, _, _ = qualify(inputs, policy)
        signals = self.assert_gate(inputs, receipt, old_alignment, policy, "incompatible_context")
        self.assertTrue(all(signal.scope == "context" for signal in signals))

    def test_tampered_pair_broadcast_or_row_is_rejected(self):
        for change in ({"broadcast": False}, {"right_row_index": 1}, {"left_row_index": 1}):
            with self.subTest(change=change):
                inputs, receipt, aligned, policy = self.approved()
                changed = aligned.model_copy(deep=True)
                changed.pairs[0] = changed.pairs[0].model_copy(update=change)
                self.assert_gate(inputs, receipt, changed, policy, "incompatible_context")

    def test_align_operation_is_not_division_permission(self):
        inputs = s3_inputs()
        receipt, aligned, policy = qualify(inputs, operation="align")
        self.assert_gate(inputs, receipt, aligned, policy, "incompatible_context")

    def test_total_is_read_once_and_all_numeric_results_are_preserved(self):
        inputs, receipt, aligned, policy = self.approved()
        original = product_contribution.read_numeric_value
        captured = []

        def capture(*args, **kwargs):
            self.assertIsNone(kwargs.get("evidence_id"))
            result = original(*args, **kwargs)
            captured.append((args[0].result_id, args[1], args[2], result, copy.deepcopy(result)))
            return result

        with patch.object(product_contribution, "read_numeric_value", side_effect=capture):
            signals = self.compute(inputs, policy, receipt, aligned)
        self.assertTrue(all(signal.status == "computed" for signal in signals))
        self.assertEqual(len(captured), 3)
        self.assertEqual([(column, row) for identity, column, row, _, _ in captured if identity == inputs.total.context.result_id], [("col_m", 0)])
        self.assertEqual(sorted(row for identity, _, row, _, _ in captured if identity == inputs.parts.context.result_id), [0, 1])
        self.assertTrue(all(reading == before for _, _, _, reading, before in captured))

    def test_input_bundle_policy_and_receipts_are_not_modified(self):
        inputs, receipt, aligned, policy = self.approved()
        before = copy.deepcopy((inputs, receipt, aligned, policy))
        self.compute(inputs, policy, receipt, aligned)
        self.assertEqual((inputs, receipt, aligned, policy), before)

    def test_output_keys_and_operand_references_are_detached(self):
        inputs, receipt, aligned, policy = self.approved()
        before = copy.deepcopy((inputs, receipt, aligned, policy))
        signal = self.compute(inputs, policy, receipt, aligned)[0]
        signal.business_key.components.clear()
        signal.operand_references.clear()
        self.assertEqual((inputs, receipt, aligned, policy), before)

    def test_a_a_and_a_b_a_are_deterministic(self):
        inputs, receipt, aligned, policy = self.approved()
        first = self.compute(inputs, policy, receipt, aligned)
        self.assertEqual(self.compute(inputs, policy, receipt, aligned), first)
        self.compute(s3_inputs([["A", "0.00"], ["B", "0.00"]], [["0.00"]]))
        self.assertEqual(self.compute(inputs, policy, receipt, aligned), first)

    def test_equal_content_reconstruction_accepts_existing_receipts(self):
        inputs, receipt, aligned, policy = self.approved()
        first = self.compute(inputs, policy, receipt, aligned)
        second = self.compute(ProductContributionInput.model_validate(inputs.model_dump()),
                              ProductContributionPolicy.model_validate(policy.model_dump()),
                              ContextCompatibility.model_validate(receipt.model_dump()),
                              AlignmentResult.model_validate(aligned.model_dump()))
        self.assertEqual(first, second)

    def test_evidence_builder_without_upstream_rerun_network_clock_or_randomness(self):
        inputs, receipt, aligned, policy = self.approved()
        with patch.object(product_contribution, "build_signal_evidence", wraps=evidence.build_signal_evidence) as builder, \
             patch.object(compatibility, "check_context_compatibility", side_effect=AssertionError("Compatibility rerun")), \
             patch.object(alignment, "align_context_keys", side_effect=AssertionError("Alignment rerun")), \
             patch.object(socket, "socket", side_effect=AssertionError("network")), \
             patch.object(time, "time", side_effect=AssertionError("clock")), \
             patch.object(uuid, "uuid4", side_effect=AssertionError("random identity")):
            signals = self.compute(inputs, policy, receipt, aligned)
        self.assertTrue(all(signal.status == "computed" for signal in signals))
        self.assertEqual(builder.call_count, 2 * len(signals))
        self.assert_operand_evidence(signals)
        self.assertTrue(all(signal.signal_id is None for signal in signals))

    def test_calculator_neither_indexes_raw_rows_nor_calls_sql_or_llm(self):
        tree = ast.parse(inspect.getsource(product_contribution))
        calls = {node.func.id if isinstance(node.func, ast.Name) else node.func.attr
                 for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, (ast.Name, ast.Attribute))}
        self.assertFalse(calls & {"float", "check_context_compatibility", "align_context_keys",
                                 "execute", "execute_sql", "parse_sql", "generate_sql", "invoke", "ainvoke", "uuid4"})
        self.assertFalse([node for node in ast.walk(tree) if isinstance(node, ast.Subscript)
                          and any(isinstance(child, ast.Attribute) and child.attr == "rows"
                                  for child in ast.walk(node.value))])

    def test_computed_undefined_null_and_rejected_signals_round_trip(self):
        cases = [s3_inputs(), s3_inputs([["A", "0"]], [["0"]]),
                 s3_inputs([["A", None], ["B", "60"]]), s3_inputs([["A", "invalid"], ["B", "60"]])]
        for inputs in cases:
            for signal in self.compute(inputs):
                with self.subTest(status=signal.status):
                    self.assertEqual(BusinessSignal.model_validate_json(signal.model_dump_json()), signal)
                    self.assert_operand_evidence([signal])


if __name__ == "__main__":
    unittest.main()
