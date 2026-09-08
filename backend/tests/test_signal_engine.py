"""Batch existing real S1/S2/S3 outputs without repeating their producers.

Malformed references and status conflicts below are explicit structural negative
fixtures, not manufactured successful Compatibility or Alignment receipts.
"""

import ast
import copy
import inspect
import json
import socket
import time
import unittest
import uuid
from unittest.mock import patch

from app.querying.business_signals import (
    alignment, compatibility, evidence, numeric, product_contribution, sales_change, target_attainment,
)
from app.querying.business_signals import batch as batch_module, engine
from app.querying.business_signals.batch import SignalBatch
from app.querying.business_signals.models import BusinessSignal
import test_product_contribution as s3_tests
import test_sales_change as s2_tests
import test_target_attainment as s1_tests


STATUSES = {"computed", "undefined", "insufficient_evidence", "incompatible_context", "unsupported"}


def s1(inputs=None):
    return s1_tests.TargetAttainmentTests().compute(inputs)


def s2(inputs=None):
    return s2_tests.SalesChangeTests().compute(inputs)


def s3(inputs=None):
    return s3_tests.ProductContributionTests().compute(inputs)


def context_identity(value):
    return value.result_id, value.context_digest, value.context_version, value.result_contract_version


def mutated(signal, change):
    raw = signal.model_dump(mode="python")
    change(raw)
    return BusinessSignal.model_validate(raw)


class SignalEngineTests(unittest.TestCase):
    def build(self, signals):
        return engine.SignalEngine().build(signals)

    def assert_local_hidden(self, bad):
        good = s1()[0]
        supplied = [bad, good]
        before = copy.deepcopy(supplied)
        batch = self.build(supplied)
        bad_index = next(index for index, item in enumerate(batch.signals) if item is bad)
        good_index = next(index for index, item in enumerate(batch.signals) if item is good)
        self.assertNotIn(bad_index, batch.displayable_signal_indices)
        self.assertIn(good_index, batch.displayable_signal_indices)
        local = [item for item in batch.limitations if item.signal_index is not None]
        self.assertTrue(local)
        self.assertTrue(all(item.signal_index == bad_index for item in local))
        self.assertTrue(all(item.code and item.message for item in local))
        self.assertEqual(supplied, before)
        self.assertIs(batch.signals[bad_index], bad)
        self.assertIs(batch.signals[good_index], good)
        return batch

    def test_real_mixed_signals_sort_s1_s2_s3_without_replacing_objects(self):
        one, two, three = s1()[0], s2()[0], s3()
        supplied = [three[1], two, one, three[0]]
        batch = self.build(supplied)
        expected = [one, two, three[1], three[0]]
        self.assertEqual(batch.signals, expected)
        self.assertTrue(all(actual is original for actual, original in zip(batch.signals, expected)))
        self.assertEqual(batch.displayable_signal_indices, [0, 1, 2, 3])
        self.assertIsInstance(batch.displayable_signals, tuple)
        self.assertTrue(all(actual is original for actual, original in zip(batch.displayable_signals, expected)))
        self.assertEqual(supplied, [three[1], two, one, three[0]])
        self.assertEqual(batch.version, "1")
        self.assertIsNone(batch.batch_id)

    def test_all_five_statuses_are_retained_and_only_computed_undefined_display(self):
        computed = s1()[0]
        insufficient = s1(s1_tests.s1_inputs(actual=[["华东", None]]))[0]
        undefined = s2(s2_tests.s2_inputs(baseline=[["华东", "0"]]))[0]
        incompatible = s3(s3_tests.s3_inputs([["A", "-1.00"]]))[0]
        unsupported = s3(s3_tests.s3_inputs([["A", "bad-decimal"]]))[0]
        batch = self.build([unsupported, undefined, computed, incompatible, insufficient])
        self.assertEqual(batch.signals, [computed, insufficient, undefined, unsupported, incompatible])
        self.assertEqual(batch.displayable_signal_indices, [0, 2])
        self.assertEqual(batch.status_counts, {status: 1 for status in STATUSES})
        self.assertEqual(len(batch.signals), 5)

    def test_empty_batch_is_valid_with_every_zero_count_and_no_generated_identity(self):
        for supplied in ([], ()):
            with self.subTest(container=type(supplied).__name__):
                batch = self.build(supplied)
                self.assertEqual(batch.signals, [])
                self.assertEqual(batch.created_contexts, [])
                self.assertEqual(batch.displayable_signal_indices, [])
                self.assertEqual(batch.displayable_signals, ())
                self.assertEqual(batch.status_counts, {status: 0 for status in STATUSES})
                self.assertIsNone(batch.batch_id)

    def test_same_type_keeps_caller_order_without_value_or_status_ranking(self):
        small = s2(s2_tests.s2_inputs(current=[["华东", "101"]]))[0]
        large = s2(s2_tests.s2_inputs(current=[["华东", "900"]]))[0]
        failure = s2(s2_tests.s2_inputs(current=[["华东", None]]))[0]
        supplied = [small, failure, large]
        batch = self.build(tuple(supplied))
        self.assertTrue(all(actual is original for actual, original in zip(batch.signals, supplied)))
        self.assertEqual(batch.displayable_signal_indices, [0, 2])

    def test_duplicate_signal_objects_are_not_deduplicated(self):
        signal = s1()[0]
        batch = self.build([signal, signal])
        self.assertEqual(len(batch.signals), 2)
        self.assertIs(batch.signals[0], signal)
        self.assertIs(batch.signals[1], signal)
        self.assertEqual(batch.displayable_signal_indices, [0, 1])
        self.assertEqual(batch.status_counts["computed"], 2)
        self.assertEqual(len(batch.created_contexts), 2)

    def test_evidence_ids_are_local_and_same_ids_across_signals_remain_valid(self):
        signals = s3()
        self.assertEqual([item.evidence_id for item in signals[0].evidence],
                         [item.evidence_id for item in signals[1].evidence])
        batch = self.build(signals)
        self.assertEqual(batch.displayable_signal_indices, [0, 1])
        self.assertEqual(len(batch.created_contexts), 2)
        for output, original in zip(batch.signals, signals):
            self.assertIs(output.evidence, original.evidence)
            self.assertTrue(all(left is right for left, right in zip(output.evidence, original.evidence)))
            self.assertIs(output.operand_references, original.operand_references)
        self.assertNotIn("evidence", batch.model_dump())
        self.assertNotIn("evidence_registry", batch.model_dump())

    def test_context_references_deduplicate_full_identity_not_just_result_id(self):
        first = s1()[0]
        second = s1(s1_tests.s1_inputs(actual=[["华东", "120.00"]]))[0]
        self.assertEqual(first.evidence[0].result_id, second.evidence[0].result_id)
        self.assertNotEqual(first.evidence[0].context_digest, second.evidence[0].context_digest)
        batch = self.build([first, second])
        expected = {context_identity(item) for signal in (first, second) for item in signal.evidence}
        self.assertEqual({context_identity(item) for item in batch.created_contexts}, expected)
        self.assertEqual(len(batch.created_contexts), 3)
        self.assertTrue(all(set(item.model_dump()) == {"result_id", "context_digest", "context_version", "result_contract_version"}
                            for item in batch.created_contexts))

    def test_context_contract_version_is_part_of_identity(self):
        original = s1()[0]
        changed = mutated(original, lambda raw: raw["evidence"][0].update(result_contract_version="2"))
        batch = self.build([original, changed])
        self.assertEqual(len(batch.created_contexts), 3)
        actual = [item for item in batch.created_contexts if item.result_id == original.evidence[0].result_id]
        self.assertEqual({item.result_contract_version for item in actual}, {"1", "2"})
        # Batch assembly records versions without requalifying the BusinessContext.
        self.assertEqual(batch.displayable_signal_indices, [0, 1])

    def test_undefined_s2_retains_computed_absolute_change_and_none_rate(self):
        signal = s2(s2_tests.s2_inputs(current=[["华东", "150.00"]], baseline=[["华东", "0"]]))[0]
        before = signal.model_dump()
        batch = self.build([signal])
        output = batch.signals[0]
        self.assertEqual(output.status, "undefined")
        self.assertEqual(output.computed_value["absolute_change"].status, "computed")
        self.assertEqual(output.computed_value["absolute_change"].value, "150.00")
        self.assertEqual(output.computed_value["change_rate"].status, "undefined")
        self.assertIsNone(output.computed_value["change_rate"].value)
        self.assertEqual(output.computed_value["change_rate"].reason_code, "ZERO_BASELINE")
        self.assertEqual(batch.displayable_signal_indices, [0])
        self.assertEqual(output.model_dump(), before)

    def test_top_status_mismatch_is_local_and_does_not_change_original_status(self):
        original = s2(s2_tests.s2_inputs(baseline=[["华东", "0"]]))[0]
        for status in ("computed", "insufficient_evidence", "incompatible_context", "unsupported"):
            with self.subTest(status=status):
                bad = mutated(original, lambda raw: raw.update(status=status))
                self.assert_local_hidden(bad)
                self.assertEqual(bad.status, status)
                self.assertEqual(bad.computed_value["change_rate"].status, "undefined")

    def test_child_status_priority_uses_all_fixed_formula_outputs(self):
        original = s2()[0]
        order = ["computed", "undefined", "insufficient_evidence", "incompatible_context", "unsupported"]
        for left, right in zip(order, order[1:]):
            with self.subTest(left=left, right=right):
                raw = original.model_dump()
                raw["status"] = left
                for formula, status in (("absolute_change", left), ("change_rate", right)):
                    raw["computed_value"][formula]["status"] = status
                    if status != "computed":
                        raw["computed_value"][formula]["value"] = None
                self.assert_local_hidden(BusinessSignal.model_validate(raw))

    def test_formula_reference_ids_must_be_nonempty_unique_and_locally_closed(self):
        original = s1()[0]
        for ids in ([], ["absent:metric"], ["actual:metric"], ["actual:metric", "actual:metric"],
                    ["target:metric", "actual:metric"]):
            with self.subTest(ids=ids):
                self.assert_local_hidden(mutated(original, lambda raw: raw["computed_value"]["attainment_rate"].update(input_evidence_ids=ids)))
        raw = original.model_dump()
        decoy = copy.deepcopy(raw["evidence"][0])
        decoy["evidence_id"] = decoy["observed_value"]["evidence_id"] = "decoy:metric"
        raw["evidence"].append(decoy)
        raw["computed_value"]["attainment_rate"]["input_evidence_ids"] = ["decoy:metric", "target:metric"]
        self.assert_local_hidden(BusinessSignal.model_validate(raw))

    def test_duplicate_evidence_id_within_one_signal_is_hidden_without_deduplication(self):
        original = s1()[0]
        bad = mutated(original, lambda raw: raw["evidence"].append(copy.deepcopy(raw["evidence"][0])))
        self.assertEqual(len(bad.evidence), 3)
        self.assert_local_hidden(bad)
        self.assertEqual(len(bad.evidence), 3)

    def test_referenced_evidence_must_associate_the_same_formula(self):
        original = s2()[0]
        for refs in ([], [{"formula_id": "attainment_rate", "formula_version": "1"}]):
            with self.subTest(refs=refs):
                self.assert_local_hidden(mutated(original, lambda raw: raw["evidence"][0].update(formula_refs=refs)))

    def test_current_and_reference_ids_must_be_distinct_closed_and_observationally_equal(self):
        original = s1()[0]
        changes = [
            lambda raw: raw["current_value"].update(evidence_id=None),
            lambda raw: raw["current_value"].update(evidence_id="absent:metric"),
            lambda raw: raw["reference_value"].update(evidence_id=raw["current_value"]["evidence_id"]),
            lambda raw: raw["current_value"].update(value="101.00"),
            lambda raw: raw["reference_value"].update(unit_id="USD"),
            lambda raw: raw["evidence"][0].update(context_role="target"),
        ]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                self.assert_local_hidden(mutated(original, change))
        raw = original.model_dump()
        for observation in (raw["current_value"], raw["evidence"][0]["observed_value"]):
            observation.update(presence="sql_null", value=None)
        raw["evidence"][0]["raw_value"] = None
        self.assert_local_hidden(BusinessSignal.model_validate(raw))

    def test_empty_evidence_hides_only_the_affected_signal(self):
        bad = mutated(s1()[0], lambda raw: raw.update(evidence=[]))
        self.assert_local_hidden(bad)
        self.assertEqual(bad.evidence, [])

    def test_engine_preserves_opaque_computed_text_without_parsing_or_recalculation(self):
        signal = mutated(s1()[0], lambda raw: raw["computed_value"]["attainment_rate"].update(value="opaque-caller-result"))
        batch = self.build([signal])
        self.assertEqual(batch.displayable_signal_indices, [0])
        self.assertEqual(batch.signals[0].computed_value["attainment_rate"].value, "opaque-caller-result")

    def test_invalid_input_types_unknown_states_and_invalid_model_shapes_raise(self):
        valid = s1()[0]
        for supplied in (None, {}, "signals", 1, [valid, {}], [valid, None], iter([valid])):
            with self.subTest(supplied=type(supplied).__name__), self.assertRaises((TypeError, ValueError)):
                self.build(supplied)
        for changes in ({"status": "unknown"}, {"signal_type": "unknown"}, {"business_key": None},
                        {"computed_value": {"attainment_rate": {}}}):
            with self.subTest(changes=changes), self.assertRaises((TypeError, ValueError)):
                self.build([valid.model_copy(update=changes)])
        for version in ("", "2"):
            with self.subTest(formula_version=version):
                bad = valid.model_copy(deep=True)
                child = bad.computed_value["attainment_rate"]
                bad.computed_value["attainment_rate"] = child.model_copy(update={"formula_version": version})
                for item in bad.evidence:
                    item.formula_refs[:] = [ref.model_copy(update={"formula_version": version})
                                            for ref in item.formula_refs]
                with self.assertRaises(ValueError):
                    self.build([bad])
        for change in ({"value": None}, {"unit_id": 1}, {"unit_id": ""},
                       {"input_evidence_ids": None}, {"input_evidence_ids": [7, "target:metric"]}):
            with self.subTest(computed_output=change):
                bad = valid.model_copy(deep=True)
                bad.computed_value["attainment_rate"] = bad.computed_value["attainment_rate"].model_copy(update=change)
                with self.assertRaises((TypeError, ValueError)):
                    self.build([bad])
        for change in ({"evidence_id": ""}, {"context_role": "invalid"}):
            with self.subTest(evidence_shape=change):
                bad = valid.model_copy(deep=True)
                bad.evidence[0] = bad.evidence[0].model_copy(update=change)
                with self.assertRaises((TypeError, ValueError)):
                    self.build([bad])

    def test_batch_json_round_trip_preserves_undefined_and_has_no_displayable_signal_copy(self):
        signals = [*s3(), *s2(s2_tests.s2_inputs(baseline=[["华东", "0"]])), *s1()]
        batch = self.build(signals)
        raw = json.loads(batch.model_dump_json())
        self.assertNotIn("displayable_signals", raw)
        self.assertEqual(len(raw["signals"]), len(signals))
        rebuilt = SignalBatch.model_validate_json(batch.model_dump_json())
        self.assertEqual(rebuilt, batch)
        self.assertTrue(all(rebuilt.signals[index] is signal for index, signal in zip(rebuilt.displayable_signal_indices, rebuilt.displayable_signals)))
        undefined = next(item for item in rebuilt.signals if item.status == "undefined")
        self.assertIsNone(undefined.computed_value["change_rate"].value)

    def test_batch_model_rejects_invalid_display_indices_and_inconsistent_derived_fields(self):
        good, bad = s1()[0], s1(s1_tests.s1_inputs(actual=[["华东", None]]))[0]
        original = self.build([good, bad, good]).model_dump(mode="python")
        for indices in ([3], [0, 0], [2, 0], [1], [True]):
            with self.subTest(indices=indices), self.assertRaises((TypeError, ValueError)):
                SignalBatch.model_validate(original | {"displayable_signal_indices": indices})
        with self.assertRaises((TypeError, ValueError)):
            SignalBatch.model_validate(original | {"status_counts": {status: 0 for status in STATUSES}})
        with self.assertRaises((TypeError, ValueError)):
            SignalBatch.model_validate(original | {"created_contexts": []})

    def test_a_a_b_a_is_deterministic_and_input_containers_remain_unchanged(self):
        supplied = [*s3(), *s2(), *s1()]
        before = copy.deepcopy(supplied)
        builder = engine.SignalEngine()
        first, repeated = builder.build(supplied), builder.build(supplied)
        builder.build([*s2(s2_tests.s2_inputs(baseline=[["华东", "0"]]))])
        after = builder.build(supplied)
        self.assertEqual(first, repeated)
        self.assertEqual(first, after)
        self.assertEqual(supplied, before)
        self.assertIsNot(first.signals, supplied)
        self.assertIsNot(first.signals, after.signals)
        self.assertTrue(all(left is right for left, right in zip(first.signals, after.signals)))
        for signal in first.signals:
            self.assertTrue(any(signal is original for original in supplied))

    def test_engine_never_repeats_calculators_evidence_numeric_or_upstream_stages(self):
        supplied = [*s1(), *s2(), *s3()]
        with patch.object(target_attainment, "compute_target_attainment", side_effect=AssertionError("S1 rerun")), \
             patch.object(sales_change, "compute_sales_change", side_effect=AssertionError("S2 rerun")), \
             patch.object(product_contribution, "compute_product_contribution", side_effect=AssertionError("S3 rerun")), \
             patch.object(evidence, "build_signal_evidence", side_effect=AssertionError("Evidence rebuilt")), \
             patch.object(numeric, "read_numeric_value", side_effect=AssertionError("Numeric reread")), \
             patch.object(compatibility, "check_context_compatibility", side_effect=AssertionError("Compatibility rerun")), \
             patch.object(alignment, "align_context_keys", side_effect=AssertionError("Alignment rerun")), \
             patch("builtins.open", side_effect=AssertionError("file IO")), \
             patch.object(socket, "socket", side_effect=AssertionError("network")), \
             patch.object(time, "time", side_effect=AssertionError("clock")), \
             patch.object(uuid, "uuid4", side_effect=AssertionError("random")):
            batch = self.build(supplied)
        self.assertEqual(len(batch.displayable_signal_indices), 4)
        for module in (engine, batch_module):
            tree = ast.parse(inspect.getsource(module))
            names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
            attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
            self.assertFalse(names & {"Decimal", "float", "eval", "exec", "Workflow", "Agent", "BusinessContext"})
            self.assertFalse(attributes & {"rows", "execute", "parse_sql", "query", "connect", "invoke", "ainvoke", "completions"})


if __name__ == "__main__":
    unittest.main()
