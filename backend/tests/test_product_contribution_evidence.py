"""S3 Evidence integration using real Compatibility, Alignment and Numeric reads.

Synthetic captured inputs supply all declarations. No SQL is parsed/executed,
and successful receipts are produced by the existing qualification stages.
"""

import ast
import copy
import hashlib
import inspect
import json
import socket
import time
import unittest
import uuid
from unittest.mock import patch

from app.querying.business_signals import alignment, compatibility, evidence, numeric, product_contribution
from app.querying.business_signals.models import BusinessSignal, EvidenceFormulaRef, SignalEvidence
from app.querying.result_contract import ExecutionData
from app.querying.result_understanding.models import BusinessContext
from test_product_contribution import qualify, s3_inputs, s3_policy
import test_sales_change as s2_tests
import test_signal_evidence as builder_tests
import test_target_attainment as s1_tests


def operand_args(inputs=None, *, role="parts", pair_index=0):
    inputs = s3_inputs() if inputs is None else inputs
    receipt, aligned, policy = qualify(inputs)
    supplied = getattr(inputs, role)
    pair = aligned.pairs[pair_index]
    side = "left" if role == "parts" else "right"
    row = getattr(pair, f"{side}_row_index")
    unit = next(item for item in supplied.declarations if item.declaration_type == "unit")
    reading = numeric.read_numeric_value(supplied.context, supplied.selection.metric_column_id,
                                         row, policy.numeric_rules, unit_id=unit.claims.unit.unit_id)
    return dict(context=supplied.context, selection=supplied.selection, context_role=role,
                evidence_id=f"{role}:metric", context_digest=receipt.input_digests[role],
                row_index=row, numeric_result=reading, alignment_pair=pair, alignment_side=side,
                alignment_broadcast=pair.broadcast,
                formula_refs=[EvidenceFormulaRef(formula_id="contribution_rate", formula_version="1")],
                compatibility=receipt, unit_declaration=unit)


class ProductContributionEvidenceTests(unittest.TestCase):
    def compute(self, inputs=None, policy=None, receipt=None, aligned=None):
        inputs = s3_inputs() if inputs is None else inputs
        if receipt is None or aligned is None:
            receipt, aligned, policy = qualify(inputs, policy)
        return product_contribution.compute_product_contribution(inputs, receipt, aligned, policy)

    def assert_links(self, signal):
        self.assertEqual([item.evidence_id for item in signal.evidence], ["parts:metric", "total:metric"])
        self.assertEqual([item.context_role for item in signal.evidence], ["parts", "total"])
        self.assertEqual(signal.computed_value["contribution_rate"].input_evidence_ids,
                         ["parts:metric", "total:metric"])
        for item in signal.evidence:
            self.assertEqual(item.formula_refs,
                             [EvidenceFormulaRef(formula_id="contribution_rate", formula_version="1")])
            self.assertEqual(item.observed_value.evidence_id, item.evidence_id)
            self.assertEqual(item.numeric_quality, item.observed_value.source_quality)
            self.assertFalse(hasattr(item, "computed_value"))
        self.assertEqual(signal.current_value, signal.evidence[0].observed_value)
        self.assertEqual(signal.reference_value, signal.evidence[1].observed_value)
        self.assertEqual(len(signal.operand_references), 2)
        self.assertNotIn("EVIDENCE_INTEGRATION_PENDING", [issue.code for issue in signal.limitations])

    def test_each_computed_signal_has_two_linked_evidence_records(self):
        signals = self.compute()
        self.assertEqual(len(signals), 2)
        self.assertTrue(all(signal.status == "computed" for signal in signals))
        for signal in signals:
            self.assert_links(signal)
            self.assertIsNone(signal.signal_id)

    def test_broadcast_keeps_total_row_zero_without_borrowing_part_key(self):
        inputs = s3_inputs([["B", "60.00"], ["A", "40.00"]])
        receipt, aligned, policy = qualify(inputs)
        self.assertEqual((receipt.status, aligned.status), ("compatible", "aligned"))
        signals = self.compute(inputs, policy, receipt, aligned)
        self.assertEqual([item.evidence[0].row_index for item in signals], [1, 0])
        for signal, pair in zip(signals, aligned.pairs):
            part, total = signal.evidence
            self.assertEqual(part.business_key, pair.left_key)
            self.assertEqual(part.key_values, pair.left_key.components)
            self.assertEqual(part.key_columns, {"category": "col_k"})
            self.assertEqual((total.result_id, total.column_id, total.ordinal, total.row_index),
                             (inputs.total.context.result_id, "col_m", 0, 0))
            self.assertEqual(total.key_columns, {})
            self.assertEqual(total.key_values, [])
            self.assertIsNone(total.business_key)
            self.assertEqual((part.alignment_status, total.alignment_status), ("matched", "matched"))
            self.assertTrue(part.alignment_broadcast)
            self.assertTrue(total.alignment_broadcast)
            self.assertEqual(total.raw_value, "100.00")
            self.assertEqual(total.context_digest, receipt.input_digests["total"])

    def test_shared_total_evidence_is_equal_but_deeply_detached(self):
        signals = self.compute()
        first, second = (signal.evidence[1] for signal in signals)
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        before = copy.deepcopy(second)
        first.formula_refs.clear()
        first.source_fields.clear()
        first.unit_declaration.column_ids.clear()
        first.eligibility.declarations.clear()
        self.assertIsNot(first.observed_value, second.observed_value)
        self.assertIsNot(first.observed_value.source_quality, second.observed_value.source_quality)
        self.assertEqual(second, before)

    def test_integer_product_ids_are_preserved_in_parts_evidence_only(self):
        inputs = s3_inputs(product=True)
        signals = self.compute(inputs, s3_policy(product=True))
        self.assertEqual([signal.evidence[0].key_values[0].raw_value for signal in signals], [1, 2])
        for signal in signals:
            component = signal.evidence[0].key_values[0]
            self.assertIs(type(component.normalized_value), int)
            self.assertEqual((component.component_id, component.domain_id), ("product_id", "product-id"))
            self.assertEqual(signal.evidence[1].key_values, [])
            self.assert_links(signal)

    def test_metric_column_id_and_ordinal_survive_duplicate_display_aliases(self):
        signals = self.compute(s3_inputs(metric_first=True))
        self.assertEqual([signal.evidence[0].raw_value for signal in signals], ["40.00", "60.00"])
        for signal in signals:
            self.assertEqual((signal.evidence[0].column_id, signal.evidence[0].ordinal), ("col_m", 0))

    def test_complete_captured_semantics_and_eligibility_are_preserved(self):
        inputs = s3_inputs()
        receipt, aligned, policy = qualify(inputs)
        signal = self.compute(inputs, policy, receipt, aligned)[0]
        for item in signal.evidence:
            supplied = getattr(inputs, item.context_role)
            context = supplied.context
            column = next(column for column in context.execution.columns if column.id == "col_m")
            semantic = next(semantic for semantic in context.column_semantics if semantic.column_id == "col_m")
            self.assertEqual((item.context_version, item.result_contract_version), (context.version, context.result_contract_version))
            self.assertEqual(item.source_fields, semantic.lineage)
            self.assertEqual(item.schema_metadata, semantic.schema_bindings)
            self.assertEqual(item.aggregation, "SUM")
            self.assertEqual(item.grain, context.grain)
            self.assertEqual(item.time, context.time_constraints)
            self.assertEqual(item.filters, context.filters)
            self.assertEqual(item.metric_semantic, next(ref for ref in receipt.normalized_metric_refs
                                                       if ref.context_role == item.context_role))
            self.assertEqual(item.normalized_period, next(ref.period for ref in receipt.periods
                                                         if ref.context_role == item.context_role))
            self.assertEqual(item.normalized_filters, [ref for ref in receipt.non_time_filters
                                                       if ref.context_role == item.context_role])
            self.assertEqual((item.dtype, item.value_encoding, item.representation_status),
                             (column.dtype, column.value_encoding, column.representation_status))
            self.assertEqual(item.eligibility.completeness, context.execution.completeness)
            self.assertEqual(item.eligibility.truncated, context.execution.truncated)
            self.assertEqual(item.eligibility.returned_rows, context.execution.returned_rows)
            self.assertEqual(item.eligibility.total_rows, context.execution.total_rows)
            self.assertEqual(item.eligibility.understanding_status, context.understanding_status)
            self.assertEqual(item.eligibility.declarations, [ref for ref in receipt.declarations_used
                                                           if ref.result_id == context.result_id])
            self.assertEqual(item.unit_declaration, next(ref for ref in supplied.declarations
                                                        if ref.declaration_type == "unit"))
            self.assertEqual(item.provenance, context.execution.provenance)

    def test_observations_link_to_evidence_with_original_decimal_text(self):
        signal = self.compute(s3_inputs([["A", "000100.00"]]))[0]
        self.assertEqual(signal.current_value.value, "000100.00")
        self.assertEqual(signal.evidence[0].raw_value, "000100.00")
        self.assert_links(signal)
        self.assertEqual(signal.evidence[0].numeric_quality.scale, 2)
        self.assertEqual(signal.evidence[1].numeric_quality.scale, 2)

    def test_zero_total_retains_observed_zero_and_undefined_formula_links(self):
        for signal in self.compute(s3_inputs([["A", "0.00"], ["B", "-0.00"]], [["0.00"]])):
            self.assertEqual(signal.status, "undefined")
            self.assertEqual(signal.computed_value["contribution_rate"].reason_code, "ZERO_TOTAL")
            self.assertIsNone(signal.computed_value["contribution_rate"].value)
            self.assertEqual(signal.reference_value.presence, "present")
            self.assertEqual(signal.reference_value.value, "0.00")
            self.assertEqual(signal.evidence[1].raw_value, "0.00")
            self.assert_links(signal)

    def test_sql_null_on_either_side_keeps_its_real_row_without_becoming_zero(self):
        for role in ("parts", "total"):
            with self.subTest(role=role):
                inputs = s3_inputs([["A", None], ["B", "60.00"]]) if role == "parts" else s3_inputs(total=[[None]])
                signals = self.compute(inputs)
                self.assertTrue(all(signal.status != "computed" for signal in signals))
                item = next(item for item in signals[0].evidence if item.context_role == role)
                self.assertEqual(item.row_index, 0)
                self.assertEqual(item.observed_value.presence, "sql_null")
                self.assertIsNone(item.observed_value.value)
                self.assertIsNone(item.raw_value)
                self.assertIn("SQL_NULL", [issue.code for issue in item.numeric_issues])
                self.assertTrue(item.alignment_broadcast)
                for signal in signals:
                    self.assert_links(signal)

    def test_rejected_numeric_preserves_raw_value_quality_and_reader_issue(self):
        for value, code in (("-1.00", "NEGATIVE_INPUT_NOT_ALLOWED"), ("bad-decimal", "INVALID_DECIMAL_TEXT")):
            with self.subTest(value=value):
                signals = self.compute(s3_inputs([["A", value], ["B", "60.00"]]))
                self.assertTrue(all(signal.status != "computed" for signal in signals))
                item = signals[0].evidence[0]
                self.assertEqual(item.observed_value.presence, "rejected")
                self.assertEqual(item.raw_value, value)
                self.assertEqual(item.row_index, 0)
                self.assertIsNone(item.observed_value.value)
                self.assertIn(code, [issue.code for issue in item.numeric_issues])
                self.assert_links(signals[0])

    def test_absent_total_rows_never_invent_row_zero_or_missing_business_key(self):
        for total in ([], None):
            with self.subTest(total=total):
                inputs = s3_inputs(total=total)
                receipt, aligned, policy = qualify(inputs)
                with patch.object(product_contribution, "read_numeric_value", side_effect=AssertionError("unqualified read")):
                    signals = self.compute(inputs, policy, receipt, aligned)
                for signal in signals:
                    self.assertNotEqual(signal.status, "computed")
                    self.assert_links(signal)
                    for item in signal.evidence:
                        self.assertIsNone(item.row_index)
                        self.assertIsNone(item.business_key)
                        self.assertEqual(item.key_values, [])
                        self.assertIsNone(item.raw_value)
                        self.assertIsNone(item.alignment_broadcast)
                        self.assertEqual(item.observed_value.presence, "not_read")

    def test_receipt_mismatches_expose_only_current_context_metadata_and_not_read(self):
        original = s3_inputs()
        receipt, aligned, policy = qualify(original)
        changed = s3_inputs([["A", "20.00"], ["B", "80.00"]])
        for inputs, receipt_arg, alignment_arg in (
            (changed, receipt, aligned),
            (original, receipt.model_copy(update={"binding": None}), aligned),
            (original, receipt, aligned.model_copy(update={"binding": None})),
        ):
            with self.subTest(inputs=inputs.parts.context.execution.rows, bound=alignment_arg.binding is not None):
                with patch.object(product_contribution, "read_numeric_value", side_effect=AssertionError("stale read")), \
                     patch.object(product_contribution, "_ratio", side_effect=AssertionError("stale formula")):
                    signals = self.compute(inputs, policy, receipt_arg, alignment_arg)
                for signal in signals:
                    self.assertEqual(signal.status, "incompatible_context")
                    self.assert_links(signal)
                    for item in signal.evidence:
                        self.assertEqual(item.result_id, getattr(inputs, item.context_role).context.result_id)
                        self.assertEqual(item.context_digest, compatibility.context_digest(getattr(inputs, item.context_role).context))
                        self.assertEqual(item.observed_value.presence, "not_read")
                        self.assertIsNone(item.row_index)
                        self.assertIsNone(item.raw_value)
                        self.assertIsNone(item.business_key)
                        self.assertIsNone(item.alignment_status)
                        self.assertIsNone(item.alignment_broadcast)
                        self.assertIsNone(item.metric_semantic)
                        self.assertIsNone(item.normalized_period)
                        self.assertEqual(item.eligibility.declarations, [])

    def test_failed_alignment_does_not_label_unmatched_operands_as_broadcast(self):
        for rows in ([["A", "40.00"], ["A", "60.00"]], [[None, "100.00"]]):
            with self.subTest(rows=rows):
                inputs = s3_inputs(rows)
                receipt, aligned, policy = qualify(inputs)
                self.assertNotEqual(aligned.status, "aligned")
                with patch.object(product_contribution, "read_numeric_value", side_effect=AssertionError("failed alignment read")):
                    signals = self.compute(inputs, policy, receipt, aligned)
                for signal in signals:
                    self.assertNotEqual(signal.status, "computed")
                    self.assert_links(signal)
                    for item in signal.evidence:
                        self.assertIsNone(item.raw_value)
                        self.assertIsNone(item.alignment_broadcast)
                        self.assertNotEqual(item.observed_value.presence, "present")
                    self.assertIsNone(signal.evidence[0].row_index)
                    self.assertEqual(signal.evidence[0].key_values, [])

    def test_approximate_float_evidence_keeps_raw_source_quality_separate_from_ratio_rounding(self):
        inputs = s3_inputs([["A", 1.0], ["B", 2.0]], [[3.0]], dtype="DOUBLE")
        policy = s3_policy(numeric_rules={"profile": "reporting_approx_v1", "allow_binary_float": True,
                                          "accepted_encodings": ["native_json", "decimal_text"]})
        signal = self.compute(inputs, policy)[0]
        self.assertEqual(signal.status, "computed")
        self.assertEqual(signal.computed_value["contribution_rate"].value, "0.333333333333")
        self.assertEqual(signal.computed_value["contribution_rate"].numeric_quality.arithmetic_rounding, "rounded")
        for item, raw in zip(signal.evidence, (1.0, 3.0)):
            self.assertIs(type(item.raw_value), float)
            self.assertEqual(item.raw_value, raw)
            self.assertEqual(item.numeric_quality.source_fidelity, "approximate")
            self.assertEqual(item.numeric_quality.source_kind, "binary_float")
            self.assertEqual(item.numeric_quality.arithmetic_rounding, "exact")
        self.assert_links(signal)

    def test_numeric_is_read_n_plus_one_times_and_reader_objects_are_not_mutated(self):
        inputs = s3_inputs()
        receipt, aligned, policy = qualify(inputs)
        records = []
        real_read = product_contribution.read_numeric_value

        def capture(*args, **kwargs):
            self.assertNotIn("evidence_id", kwargs)
            reading = real_read(*args, **kwargs)
            records.append((reading, copy.deepcopy(reading), args[0].result_id, args[2]))
            return reading

        with patch.object(product_contribution, "read_numeric_value", side_effect=capture) as reader, \
             patch.object(product_contribution, "build_signal_evidence", wraps=evidence.build_signal_evidence) as builder:
            signals = self.compute(inputs, policy, receipt, aligned)
        self.assertEqual(reader.call_count, 3)
        self.assertEqual(builder.call_count, 4)
        self.assertEqual([(result_id, row) for _, _, result_id, row in records].count((inputs.total.context.result_id, 0)), 1)
        for reading, before, _, _ in records:
            self.assertEqual(reading, before)
            self.assertIsNone(reading.observed_value.evidence_id)
        for signal in signals:
            self.assert_links(signal)

    def test_builder_consumes_captured_readings_without_rows_qualification_digest_or_formula(self):
        args = operand_args(role="total")

        class RowsMustNotBeRead(ExecutionData):
            def __getattribute__(self, name):
                if name == "rows":
                    raise AssertionError("Evidence must not reread execution.rows")
                return super().__getattribute__(name)

        original = args["context"].execution
        guarded = RowsMustNotBeRead.model_construct(**original.model_dump(mode="python"))
        guarded = guarded.model_copy(update={"columns": original.columns})
        args["context"] = args["context"].model_copy(update={"execution": guarded})
        with patch.object(numeric, "read_numeric_value", side_effect=AssertionError("read")), \
             patch.object(alignment, "align_context_keys", side_effect=AssertionError("align")), \
             patch.object(compatibility, "check_context_compatibility", side_effect=AssertionError("qualify")), \
             patch.object(compatibility, "context_digest", side_effect=AssertionError("digest")), \
             patch.object(product_contribution, "_ratio", side_effect=AssertionError("formula")), \
             patch.object(BusinessContext, "model_dump", side_effect=AssertionError("serialize context")), \
             patch.object(ExecutionData, "model_dump", side_effect=AssertionError("serialize rows")):
            result = evidence.build_signal_evidence(**args)
        self.assertEqual(result.raw_value, "100.00")
        self.assertEqual(result.row_index, 0)
        self.assertTrue(result.alignment_broadcast)
        self.assertIsNone(result.business_key)

    def test_builder_rejects_contradictory_or_untyped_broadcast_arguments(self):
        args = operand_args()
        for value in (1, "true"):
            with self.subTest(value=value), self.assertRaises(TypeError):
                evidence.build_signal_evidence(**(args | {"alignment_broadcast": value}))
        with self.assertRaises(ValueError):
            evidence.build_signal_evidence(**(args | {"alignment_broadcast": False}))
        with self.assertRaises(ValueError):
            evidence.build_signal_evidence(**(args | {"alignment_pair": None, "alignment_side": None,
                                                      "row_index": None, "numeric_result": None}))
        legacy = builder_tests.operand_args()
        with self.assertRaises(ValueError):
            evidence.build_signal_evidence(**(legacy | {"alignment_broadcast": False}))
        missing_inputs = s1_tests.s1_inputs([["华东", "100.00"], ["华北", "100.00"]], [["华东", "200.00"]])
        _, aligned, _ = s1_tests.qualify(missing_inputs)
        index = next(index for index, pair in enumerate(aligned.pairs) if pair.status == "missing_right")
        missing = builder_tests.operand_args(missing_inputs, role="target", pair_index=index, read=False)
        with self.assertRaises(ValueError):
            evidence.build_signal_evidence(**(missing | {"alignment_broadcast": True}))

    def test_optional_broadcast_field_omits_only_none_and_round_trips_explicit_flags(self):
        legacy = evidence.build_signal_evidence(**builder_tests.operand_args())
        self.assertIsNone(legacy.alignment_broadcast)
        self.assertNotIn("alignment_broadcast", legacy.model_dump())
        self.assertNotIn("alignment_broadcast", json.loads(legacy.model_dump_json()))
        self.assertIn("provenance", legacy.model_dump())
        self.assertIsNone(legacy.model_dump()["provenance"])
        current = self.compute()[0].evidence[0]
        for flag in (True, False):
            with self.subTest(flag=flag):
                # Model wire shape only; no successful producer receipt is forged.
                raw = current.model_dump() | {"alignment_broadcast": flag}
                item = SignalEvidence.model_validate(raw)
                self.assertIs(item.model_dump()["alignment_broadcast"], flag)
                self.assertEqual(SignalEvidence.model_validate_json(item.model_dump_json()), item)

    def test_input_purity_determinism_and_detached_nested_evidence(self):
        inputs = s3_inputs()
        receipt, aligned, policy = qualify(inputs)
        arguments = (inputs, receipt, aligned, policy)
        before = copy.deepcopy(arguments)
        first = self.compute(inputs, policy, receipt, aligned)
        repeated = self.compute(inputs, policy, receipt, aligned)
        self.compute(s3_inputs([["C", "100.00"]]))
        rebuilt = self.compute(copy.deepcopy(inputs), copy.deepcopy(policy), copy.deepcopy(receipt), copy.deepcopy(aligned))
        self.assertEqual(first, repeated)
        self.assertEqual(first, rebuilt)
        self.assertEqual(arguments, before)
        item = first[0].evidence[0]
        item.key_columns.clear()
        item.key_values.clear()
        item.business_key.components.clear()
        item.source_fields.clear()
        item.schema_metadata.clear()
        item.time.clear()
        item.normalized_filters.clear()
        item.unit_declaration.column_ids.clear()
        item.eligibility.declarations.clear()
        self.assertEqual(arguments, before)
        self.assertEqual(repeated, rebuilt)

    def test_integration_has_no_io_clock_random_upstream_rerun_or_direct_row_value_read(self):
        inputs = s3_inputs()
        receipt, aligned, policy = qualify(inputs)
        with patch("builtins.open", side_effect=AssertionError("file IO")), \
             patch.object(socket, "socket", side_effect=AssertionError("network")), \
             patch.object(time, "time", side_effect=AssertionError("clock")), \
             patch.object(uuid, "uuid4", side_effect=AssertionError("random")), \
             patch.object(compatibility, "check_context_compatibility", side_effect=AssertionError("qualification rerun")), \
             patch.object(alignment, "align_context_keys", side_effect=AssertionError("alignment rerun")):
            signals = self.compute(inputs, policy, receipt, aligned)
        self.assertTrue(all(signal.status == "computed" for signal in signals))
        for module in (evidence, product_contribution):
            tree = ast.parse(inspect.getsource(module))
            attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
            self.assertNotIn("rows", attrs)
            self.assertFalse(attrs & {"execute", "execute_sql", "parse_sql", "invoke", "ainvoke", "chat", "completions"})

    def test_json_round_trip_preserves_all_evidence_states(self):
        inputs_list = (s3_inputs(), s3_inputs([["A", "0.00"]], [["0.00"]]),
                       s3_inputs([["A", None]]), s3_inputs([["A", "bad"]]), s3_inputs(total=[]))
        for inputs in inputs_list:
            with self.subTest(rows=inputs.parts.context.execution.rows):
                for signal in self.compute(inputs):
                    self.assert_links(signal)
                    self.assertEqual(BusinessSignal.model_validate_json(signal.model_dump_json()), signal)

    def test_s1_and_s2_wire_snapshots_match_preintegration_canonical_hashes(self):
        # Captured before Phase 3.4.4. No local external baseline file is needed.
        cases = {
            "s1_normal": (lambda: s1_tests.TargetAttainmentTests().compute(), "8e5ad454ed0755d19cbcd4334e53e39cf63f11793216e8988aa5ac11d6ac2a89"),
            "s1_zero": (lambda: s1_tests.TargetAttainmentTests().compute(s1_tests.s1_inputs(target=[["华东", "0"]])), "60eb7aaa6dc070243821d119396ad28ce926032cfe4b4fdac1d517ca71c27a3d"),
            "s1_null": (lambda: s1_tests.TargetAttainmentTests().compute(s1_tests.s1_inputs(actual=[["华东", None]])), "5fd9ec9f599186be984d5a94a84b005bb6f190f9988cbbbbdae8cf8dd315916b"),
            "s2_normal": (lambda: s2_tests.SalesChangeTests().compute(), "2be3da4a974a714b8e31ae8488c2544b9d6e52ed1b9fc5683f25e7635e586866"),
            "s2_zero": (lambda: s2_tests.SalesChangeTests().compute(s2_tests.s2_inputs(baseline=[["华东", "0"]])), "769955454365d9ba6640ee538194607804dd2eab4b14db680e68cfc4d59e6237"),
            "s2_null": (lambda: s2_tests.SalesChangeTests().compute(s2_tests.s2_inputs(current=[["华东", None]])), "090f8b9044e46f13ad62adde8ef0094c44fadfd360ca2dfd590204db0ce35935"),
        }
        for name, (produce, expected) in cases.items():
            with self.subTest(name=name):
                payload = [signal.model_dump(mode="json") for signal in produce()]
                canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
                self.assertEqual(hashlib.sha256(canonical.encode("utf-8")).hexdigest(), expected)


if __name__ == "__main__":
    unittest.main()
