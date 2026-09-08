"""Pure Evidence assembly from captured facts and completed stage results.

Approved inputs use real Compatibility, Alignment and Numeric producers. The
builder does not reread those stages; diagnostic-only snapshots are explicitly
assembled without approved Compatibility semantics.
"""

import ast
import copy
from dataclasses import replace
import inspect
import socket
import time
import unittest
import uuid
from unittest.mock import patch

from app.querying.business_signals import alignment, compatibility, evidence, numeric, target_attainment
from app.querying.business_signals.models import EvidenceFormulaRef, SignalEvidence
from app.querying.result_contract import ExecutionData
from app.querying.result_understanding.models import BusinessContext
from test_business_signal_compatibility import inputs_fixture, typed_policy
from test_target_attainment import qualify, s1_inputs


def operand_args(inputs=None, *, role="actual", pair_index=0, read=True, policy=None):
    inputs = s1_inputs() if inputs is None else inputs
    receipt, aligned, policy = qualify(inputs, policy)
    supplied = inputs[role]
    pair = aligned.pairs[pair_index]
    side = "left" if role == "actual" else "right"
    row_index = pair.left_row_index if side == "left" else pair.right_row_index
    unit = next(item for item in supplied.declarations if item.declaration_type == "unit")
    result = None
    if read and row_index is not None:
        result = numeric.read_numeric_value(supplied.context, supplied.selection.metric_column_id,
                                           row_index, policy.numeric_rules,
                                           unit_id=unit.claims.unit.unit_id, evidence_id=f"{role}:metric")
    return {
        "context": supplied.context, "selection": supplied.selection,
        "context_role": role, "evidence_id": f"{role}:metric",
        "context_digest": compatibility.context_digest(supplied.context),
        "row_index": row_index, "numeric_result": result,
        "alignment_pair": pair, "alignment_side": side,
        "formula_refs": [EvidenceFormulaRef(formula_id="attainment_rate")],
        "compatibility": receipt, "unit_declaration": unit,
    }


class SignalEvidenceTests(unittest.TestCase):
    def build(self, args=None, **updates):
        args = operand_args() if args is None else args
        return evidence.build_signal_evidence(**(args | updates))

    def test_normal_operand_preserves_result_column_and_row_identity(self):
        result = self.build()
        self.assertIsInstance(result, SignalEvidence)
        self.assertEqual((result.result_id, result.context_role, result.column_id, result.ordinal, result.row_index),
                         ("captured-s1-actual", "actual", "col_m", 1, 0))
        self.assertEqual(result.context_version, "1")
        self.assertEqual(result.result_contract_version, "1")
        inputs = s1_inputs()
        receipt, aligned, policy = qualify(inputs)
        with patch.object(target_attainment, "build_signal_evidence", wraps=evidence.build_signal_evidence) as builder:
            signal = target_attainment.compute_target_attainment(
                inputs["actual"], inputs["target"], receipt, aligned, policy,
            )[0]
        self.assertEqual(builder.call_count, 2)
        self.assertEqual(signal.status, "computed")
        self.assertEqual([item.context_role for item in signal.evidence], ["actual", "target"])
        self.assertEqual([item.result_id for item in signal.evidence],
                         [inputs["actual"].context.result_id, inputs["target"].context.result_id])
        for item in signal.evidence:
            self.assertEqual((item.column_id, item.row_index), ("col_m", 0))
            self.assertEqual(item.formula_refs, [EvidenceFormulaRef(formula_id="attainment_rate")])
        self.assertEqual(signal.computed_value["attainment_rate"].input_evidence_ids,
                         [item.evidence_id for item in signal.evidence])

    def test_decimal_text_raw_and_approved_observation_are_not_formatted(self):
        result = self.build(operand_args(s1_inputs(actual=[["华东", "000100.00"]])))
        self.assertEqual(result.raw_value, "000100.00")
        self.assertEqual(result.observed_value.value, "000100.00")
        self.assertEqual(result.observed_value.presence, "present")
        self.assertEqual(result.value_encoding, "decimal_text")
        self.assertEqual(result.representation_status, "preserved")

    def test_column_id_locates_metadata_despite_ordinal_and_display_names(self):
        result = self.build(operand_args(s1_inputs(metric_first=True)))
        self.assertEqual((result.column_id, result.ordinal), ("col_m", 0))
        self.assertEqual(result.raw_value, "100.00")

    def test_business_key_and_alignment_status_are_explicit(self):
        args = operand_args()
        result = self.build(args)
        self.assertEqual(result.business_key, args["alignment_pair"].left_key)
        self.assertEqual(result.key_values, result.business_key.components)
        self.assertEqual(result.key_columns, {"region": "col_k"})
        self.assertEqual(result.alignment_status, "matched")

    def test_raw_and_normalized_query_semantics_are_preserved(self):
        args = operand_args()
        result = self.build(args)
        semantic = args["context"].column_semantics[1]
        self.assertEqual(result.source_fields, semantic.lineage)
        self.assertEqual(result.schema_metadata, semantic.schema_bindings)
        self.assertEqual(result.aggregation, "SUM")
        self.assertEqual(result.grain, args["context"].grain)
        self.assertEqual(result.filters, args["context"].filters)
        self.assertEqual(result.time, args["context"].time_constraints)
        self.assertEqual(result.metric_semantic.context_role, "actual")
        self.assertEqual(result.normalized_period, args["compatibility"].periods[0].period)
        self.assertTrue(result.normalized_filters)

    def test_target_retains_original_month_precision_and_normalized_date_period(self):
        result = self.build(operand_args(role="target"))
        self.assertEqual(result.time[0].precision, "month")
        self.assertEqual(result.normalized_period.precision, "date")
        self.assertEqual(result.normalized_period.lower, "2026-08-01")

    def test_eligibility_and_full_unit_claim_are_copied(self):
        args = operand_args()
        result = self.build(args)
        self.assertEqual(result.eligibility.completeness, "complete_query_output")
        self.assertFalse(result.eligibility.truncated)
        self.assertEqual((result.eligibility.returned_rows, result.eligibility.total_rows), (1, 1))
        self.assertTrue(result.eligibility.declarations)
        self.assertEqual(result.unit_declaration, args["unit_declaration"])
        self.assertEqual(result.unit_declaration.claims.unit.unit_scale, "1")
        self.assertEqual(result.observed_value.unit_id, "CNY")

    def test_numeric_quality_and_issues_come_from_reader_snapshot(self):
        args = operand_args()
        result = self.build(args)
        self.assertEqual(result.numeric_quality, args["numeric_result"].numeric_quality)
        self.assertEqual(result.numeric_quality, result.observed_value.source_quality)
        self.assertEqual(result.numeric_issues, list(args["numeric_result"].issues))
        self.assertEqual(result.numeric_quality.source_fidelity, "exact")

    def test_formula_reference_is_recorded_without_a_formula_result(self):
        result = self.build()
        self.assertEqual(result.formula_refs, [EvidenceFormulaRef(formula_id="attainment_rate", formula_version="1")])
        self.assertFalse(hasattr(result, "computed_value"))
        self.assertFalse(hasattr(result, "signal_id"))

    def test_sql_null_keeps_its_real_row_and_never_becomes_zero(self):
        args = operand_args(s1_inputs(actual=[["华东", None]]))
        result = self.build(args)
        self.assertEqual(result.row_index, 0)
        self.assertEqual(result.observed_value.presence, "sql_null")
        self.assertIsNone(result.observed_value.value)
        self.assertIsNone(result.raw_value)
        self.assertTrue(any(issue.code == "SQL_NULL" for issue in result.numeric_issues))

    def test_missing_target_has_no_row_value_or_borrowed_business_key(self):
        inputs = s1_inputs([["华东", "100.00"], ["华北", "90.00"]], [["华东", "200.00"]])
        _, aligned, _ = qualify(inputs)
        index = next(index for index, pair in enumerate(aligned.pairs) if pair.status == "missing_right")
        result = self.build(operand_args(inputs, role="target", pair_index=index, read=False))
        self.assertEqual(result.alignment_status, "missing_right")
        self.assertEqual(result.observed_value.presence, "missing")
        self.assertIsNone(result.row_index)
        self.assertIsNone(result.raw_value)
        self.assertIsNone(result.business_key)
        self.assertEqual(result.key_values, [])

    def test_known_side_of_a_missing_pair_is_unread_not_missing(self):
        inputs = s1_inputs([["华东", "100.00"], ["华北", "90.00"]], [["华东", "200.00"]])
        _, aligned, _ = qualify(inputs)
        index = next(index for index, pair in enumerate(aligned.pairs) if pair.status == "missing_right")
        result = self.build(operand_args(inputs, pair_index=index, read=False))
        self.assertEqual(result.observed_value.presence, "not_read")
        self.assertEqual(result.row_index, 1)
        self.assertIsNone(result.raw_value)
        self.assertIsNotNone(result.business_key)

    def test_duplicate_side_does_not_claim_one_of_the_ambiguous_rows(self):
        inputs = s1_inputs(target=[["华东", "200.00"], ["华东", "300.00"]])
        result = self.build(operand_args(inputs, role="target", read=False))
        self.assertEqual(result.alignment_status, "ambiguous")
        self.assertEqual(result.observed_value.presence, "not_read")
        self.assertIsNone(result.row_index)
        self.assertIsNone(result.raw_value)
        self.assertIsNone(result.business_key)

    def test_unresolved_counterpart_is_not_falsely_labelled_missing(self):
        inputs = s1_inputs(actual=[[None, "100.00"]])
        result = self.build(operand_args(inputs, read=False))
        self.assertEqual(result.alignment_status, "unresolved")
        self.assertEqual(result.observed_value.presence, "not_read")
        self.assertIsNone(result.row_index)

    def test_negative_numeric_rejection_keeps_raw_cell_and_reader_issue(self):
        args = operand_args(s1_inputs(actual=[["华东", "-100.00"]]))
        result = self.build(args)
        self.assertEqual(result.observed_value.presence, "rejected")
        self.assertEqual(result.raw_value, "-100.00")
        self.assertEqual(result.row_index, 0)
        self.assertIsNone(result.observed_value.value)
        self.assertTrue(any(issue.code == "NEGATIVE_INPUT_NOT_ALLOWED" for issue in result.numeric_issues))

    def test_invalid_decimal_rejection_does_not_create_unknown_metadata(self):
        result = self.build(operand_args(s1_inputs(actual=[["华东", "not-decimal"]])))
        self.assertEqual(result.observed_value.presence, "rejected")
        self.assertEqual(result.raw_value, "not-decimal")
        self.assertEqual(result.dtype, "DECIMAL(18,2)")
        self.assertTrue(any(issue.code == "INVALID_DECIMAL_TEXT" for issue in result.numeric_issues))

    def test_unknown_numeric_metadata_keeps_known_raw_observation(self):
        args = operand_args()
        column = args["context"].execution.columns[1].model_copy(update={"dtype": None})
        execution = args["context"].execution.model_copy(update={"columns": [args["context"].execution.columns[0], column]}, deep=True)
        context = args["context"].model_copy(update={"execution": execution}, deep=True)
        reading = numeric.read_numeric_value(context, "col_m", 0, typed_policy("s1").numeric_rules,
                                             evidence_id="actual:metric")
        self.assertEqual(reading.status, "insufficient_evidence")
        result = self.build(args, context=context, numeric_result=reading, compatibility=None,
                            context_digest=compatibility.context_digest(context), unit_declaration=None)
        self.assertEqual(result.observed_value.presence, "unknown_metadata")
        self.assertIsNone(result.dtype)
        self.assertEqual(result.raw_value, "100.00")
        self.assertEqual(result.row_index, 0)
        self.assertIsNone(result.metric_semantic)

    def test_unknown_payload_cannot_claim_an_observed_row_or_raw_value(self):
        args = operand_args()
        execution = args["context"].execution.model_copy(update={"rows": None}, deep=True)
        context = args["context"].model_copy(update={"execution": execution}, deep=True)
        reading = numeric.read_numeric_value(context, "col_m", 0, typed_policy("s1").numeric_rules,
                                             evidence_id="actual:metric")
        self.assertEqual(reading.observed_value.presence, "unknown_payload")
        result = self.build(args, context=context, numeric_result=reading, compatibility=None,
                            context_digest=compatibility.context_digest(context), unit_declaration=None)
        self.assertEqual(result.observed_value.presence, "unknown_payload")
        self.assertIsNone(result.row_index)
        self.assertIsNone(result.raw_value)

    def test_unknown_columns_cannot_claim_column_ordinal_or_row(self):
        args = operand_args()
        execution = args["context"].execution.model_copy(update={"columns": None}, deep=True)
        context = args["context"].model_copy(update={"execution": execution}, deep=True)
        reading = numeric.read_numeric_value(context, "col_m", 0, typed_policy("s1").numeric_rules,
                                             evidence_id="actual:metric")
        result = self.build(args, context=context, numeric_result=reading, compatibility=None,
                            context_digest=compatibility.context_digest(context), unit_declaration=None)
        self.assertEqual(result.observed_value.presence, "unknown_metadata")
        self.assertIsNone(result.column_id)
        self.assertIsNone(result.ordinal)
        self.assertIsNone(result.row_index)

    def test_unqualified_context_rejection_has_no_old_pair_or_normalized_claims(self):
        args = operand_args()
        result = self.build(args, compatibility=None, alignment_pair=None, alignment_side=None,
                            row_index=None, numeric_result=None, unit_declaration=None)
        self.assertEqual(result.observed_value.presence, "not_read")
        self.assertIsNone(result.row_index)
        self.assertIsNone(result.business_key)
        self.assertIsNone(result.alignment_status)
        self.assertIsNone(result.metric_semantic)
        self.assertIsNone(result.normalized_period)
        self.assertEqual(result.normalized_filters, [])
        self.assertEqual(result.eligibility.declarations, [])
        self.assertIsNone(result.unit_declaration)

    def test_zero_denominator_evidence_remains_present_even_when_s1_undefined(self):
        inputs = s1_inputs(target=[["华东", "0.00"]])
        receipt, aligned, policy = qualify(inputs)
        signal = target_attainment.compute_target_attainment(inputs["actual"], inputs["target"], receipt, aligned, policy)[0]
        self.assertEqual(signal.status, "undefined")
        item = next(item for item in signal.evidence if item.context_role == "target")
        self.assertEqual(item.observed_value.presence, "present")
        self.assertEqual(item.raw_value, "0.00")
        self.assertEqual(item.formula_refs, [EvidenceFormulaRef(formula_id="attainment_rate")])

    def test_approximate_double_source_quality_is_not_promoted_to_exact(self):
        inputs = s1_inputs([["华东", 100.0]], [["华东", 200.0]], actual_dtype="DOUBLE", target_dtype="DOUBLE")
        policy = typed_policy("s1", numeric_rules={
            "profile": "reporting_approx_v1", "accepted_encodings": ["native_json", "decimal_text"],
            "allow_binary_float": True,
        })
        result = self.build(operand_args(inputs, policy=policy))
        self.assertIs(type(result.raw_value), float)
        self.assertEqual(result.numeric_quality.source_kind, "binary_float")
        self.assertEqual(result.numeric_quality.source_fidelity, "approximate")
        self.assertEqual(result.numeric_quality, result.observed_value.source_quality)

    def test_missing_side_rejects_a_numeric_snapshot(self):
        args = operand_args()
        inputs = s1_inputs([["华东", "100.00"], ["华北", "90.00"]], [["华东", "200.00"]])
        _, aligned, _ = qualify(inputs)
        index = next(index for index, pair in enumerate(aligned.pairs) if pair.status == "missing_right")
        missing = operand_args(inputs, role="target", pair_index=index, read=False)
        with self.assertRaises(ValueError):
            self.build(missing, numeric_result=args["numeric_result"])

    def test_row_index_must_match_the_explicit_alignment_side(self):
        with self.assertRaises(ValueError):
            self.build(row_index=1)

    def test_pair_cannot_be_supplied_without_an_alignment_side(self):
        with self.assertRaises(ValueError):
            self.build(alignment_side=None)

    def test_context_scope_cannot_claim_a_row(self):
        with self.assertRaises(ValueError):
            self.build(alignment_pair=None, alignment_side=None, row_index=0, numeric_result=None)

    def test_context_scope_cannot_claim_an_alignment_side(self):
        with self.assertRaises(ValueError):
            self.build(alignment_pair=None, alignment_side="left", row_index=None, numeric_result=None)

    def test_conflicting_numeric_evidence_label_is_rejected(self):
        args = operand_args()
        reading = args["numeric_result"]
        reading = replace(reading, observed_value=reading.observed_value.model_copy(update={"evidence_id": "different:metric"}))
        with self.assertRaises(ValueError):
            self.build(args, numeric_result=reading)

    def test_conflicting_numeric_unit_label_is_rejected(self):
        args = operand_args()
        reading = args["numeric_result"]
        reading = replace(reading, observed_value=reading.observed_value.model_copy(update={"unit_id": "USD"}))
        with self.assertRaises(ValueError):
            self.build(args, numeric_result=reading)

    def test_absent_numeric_labels_can_be_filled_from_explicit_facts(self):
        args = operand_args()
        reading = args["numeric_result"]
        reading = replace(reading, observed_value=reading.observed_value.model_copy(update={"unit_id": None, "evidence_id": None}))
        original = copy.deepcopy(reading)
        result = self.build(args, numeric_result=reading)
        self.assertEqual(result.observed_value.evidence_id, "actual:metric")
        self.assertEqual(result.observed_value.unit_id, "CNY")
        self.assertEqual(reading, original)

    def test_unit_declaration_result_must_match_the_operand(self):
        args = operand_args()
        other = operand_args(role="target")["unit_declaration"]
        self.assertEqual(other.claims.unit.unit_id, args["unit_declaration"].claims.unit.unit_id)
        with self.assertRaises(ValueError):
            self.build(args, unit_declaration=other)

    def test_unit_declaration_digest_must_match_the_explicit_context_digest(self):
        args = operand_args()
        changed = args["unit_declaration"].model_copy(update={"context_digest": "other-context-digest"})
        with self.assertRaises(ValueError):
            self.build(args, unit_declaration=changed)

    def test_unit_declaration_must_reference_the_selected_metric_column(self):
        args = operand_args()
        changed = args["unit_declaration"].model_copy(update={"column_ids": ["col_k"]})
        with self.assertRaises(ValueError):
            self.build(args, unit_declaration=changed)

    def test_compatibility_result_label_must_match_the_operand(self):
        args = operand_args()
        receipt = args["compatibility"]
        changed = receipt.model_copy(update={"result_ids": receipt.result_ids | {"actual": "other-result"}})
        with self.assertRaises(ValueError):
            self.build(args, compatibility=changed)

    def test_compatibility_digest_label_must_match_the_explicit_context_digest(self):
        args = operand_args()
        receipt = args["compatibility"]
        changed = receipt.model_copy(update={"input_digests": receipt.input_digests | {"actual": "other-digest"}})
        with self.assertRaises(ValueError):
            self.build(args, compatibility=changed)

    def test_builder_records_supplied_facts_without_deciding_compatibility_status(self):
        args = operand_args()
        receipt = args["compatibility"]
        changed = receipt.model_copy(update={"status": "incompatible_context"})
        result = self.build(args, compatibility=changed)
        self.assertEqual(result.metric_semantic, receipt.normalized_metric_refs[0])
        self.assertEqual(result.normalized_period, receipt.periods[0].period)
        self.assertEqual(result.observed_value.value, "100.00")
        self.assertFalse(hasattr(result, "computed_value"))

    def test_direct_builder_result_is_deeply_detached_from_all_input_containers(self):
        args = operand_args()
        before = copy.deepcopy(args)
        result = self.build(args)
        result.business_key.components.clear()
        result.key_columns.clear()
        result.source_fields.clear()
        result.schema_metadata.clear()
        result.time.clear()
        result.normalized_filters.clear()
        result.eligibility.declarations.clear()
        result.unit_declaration.column_ids.clear()
        result.formula_refs.clear()
        self.assertEqual(args, before)

    def test_repeated_equal_inputs_return_equal_evidence(self):
        args = operand_args()
        self.assertEqual(self.build(args), self.build(copy.deepcopy(args)))

    def test_new_evidence_fields_survive_json_round_trip(self):
        result = self.build()
        reconstructed = SignalEvidence.model_validate_json(result.model_dump_json())
        self.assertEqual(reconstructed, result)
        self.assertEqual(reconstructed.alignment_status, "matched")
        self.assertIsNotNone(reconstructed.business_key)
        self.assertTrue(reconstructed.formula_refs)

    def test_legacy_evidence_payload_loads_with_new_fields_absent(self):
        raw = self.build().model_dump(mode="python")
        for field in ("business_key", "alignment_status", "numeric_quality", "numeric_issues", "formula_refs"):
            raw.pop(field)
        result = SignalEvidence.model_validate(raw)
        self.assertIsNone(result.business_key)
        self.assertIsNone(result.alignment_status)
        self.assertEqual(result.numeric_issues, [])
        self.assertEqual(result.formula_refs, [])

    def test_builder_preserves_upstream_explanation_text_without_interpreting_it(self):
        args = operand_args()
        raw = args["context"].model_dump(mode="python")
        raw["limitations"] = ["opaque context note"]
        raw["column_semantics"][1]["reason"] = "opaque selected semantic note"
        raw["filters"]["filters"][0]["limitations"] = ["opaque predicate note"]
        context = BusinessContext.model_validate(raw)
        result = self.build(args, context=context, compatibility=None)
        self.assertIn("opaque context note", result.upstream_limitations)
        self.assertIn("opaque selected semantic note", result.upstream_limitations)
        self.assertIn("opaque predicate note", result.upstream_limitations)
        self.assertEqual(result.observed_value.value, "100.00")

    def test_no_compatibility_object_means_no_normalized_claims(self):
        result = self.build(compatibility=None)
        self.assertIsNone(result.metric_semantic)
        self.assertIsNone(result.normalized_period)
        self.assertEqual(result.normalized_filters, [])
        self.assertEqual(result.eligibility.declarations, [])

    def test_builder_does_not_reread_numeric_or_reassess_upstream_stages(self):
        args = operand_args()
        with patch.object(numeric, "read_numeric_value", side_effect=AssertionError("Numeric rerun")), \
             patch.object(alignment, "align_context_keys", side_effect=AssertionError("Alignment rerun")), \
             patch.object(compatibility, "check_context_compatibility", side_effect=AssertionError("Compatibility rerun")), \
             patch.object(compatibility, "context_digest", side_effect=AssertionError("Context digest recomputed")):
            result = self.build(args)
        self.assertEqual(result.raw_value, "100.00")

    def test_builder_does_not_access_execution_rows_or_serialize_the_whole_context(self):
        args = operand_args()

        class RowsMustNotBeRead(ExecutionData):
            def __getattribute__(self, name):
                if name == "rows":
                    raise AssertionError("Evidence may not access execution.rows")
                return super().__getattribute__(name)

        original_execution = args["context"].execution
        execution = RowsMustNotBeRead.model_construct(**original_execution.model_dump(mode="python"))
        # Keep the already captured metadata as models; no new Context is built.
        execution = execution.model_copy(update={"columns": original_execution.columns})
        context = args["context"].model_copy(update={"execution": execution})
        with patch.object(BusinessContext, "model_dump", side_effect=AssertionError("whole Context serialization")), \
             patch.object(ExecutionData, "model_dump", side_effect=AssertionError("whole execution serialization")):
            result = self.build(args, context=context)
        self.assertEqual(result.raw_value, "100.00")

    def test_builder_has_no_sql_llm_clock_random_or_formula_execution(self):
        args = operand_args()
        with patch("builtins.open", side_effect=AssertionError("file IO")), \
             patch.object(socket, "socket", side_effect=AssertionError("network IO")), \
             patch.object(time, "time", side_effect=AssertionError("clock")), \
             patch.object(uuid, "uuid4", side_effect=AssertionError("random identity")):
            result = self.build(args)
        self.assertEqual(result.context_digest, args["context_digest"])
        tree = ast.parse(inspect.getsource(evidence))
        names = {node.func.id if isinstance(node.func, ast.Name) else node.func.attr
                 for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, (ast.Name, ast.Attribute))}
        self.assertFalse(names & {"execute", "parse_sql", "read_numeric_value", "check_context_compatibility",
                                  "align_context_keys", "context_digest", "quantize", "uuid4", "float"})
        self.assertFalse(any(isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
                             for node in ast.walk(tree)))

    def test_s2_roles_and_multiple_formula_refs_do_not_require_an_s1_calculator(self):
        inputs, policy = inputs_fixture("s2"), typed_policy("s2")
        receipt = compatibility.check_context_compatibility(inputs, policy, operation="compare")
        aligned = alignment.align_context_keys(inputs, receipt, policy)
        self.assertEqual(aligned.status, "aligned")
        supplied = inputs["baseline"]
        unit = next(item for item in supplied.declarations if item.declaration_type == "unit")
        row_index = aligned.pairs[0].right_row_index
        reading = numeric.read_numeric_value(supplied.context, "col_m", row_index, policy.numeric_rules,
                                             evidence_id="baseline:metric", unit_id=unit.claims.unit.unit_id)
        refs = [EvidenceFormulaRef(formula_id="absolute_change"), EvidenceFormulaRef(formula_id="change_rate")]
        result = evidence.build_signal_evidence(
            context=supplied.context, selection=supplied.selection, context_role="baseline",
            evidence_id="baseline:metric", context_digest=compatibility.context_digest(supplied.context),
            row_index=row_index, numeric_result=reading, alignment_pair=aligned.pairs[0], alignment_side="right",
            formula_refs=refs, compatibility=receipt, unit_declaration=unit,
        )
        self.assertEqual(result.context_role, "baseline")
        self.assertEqual(result.business_key, aligned.pairs[0].right_key)
        self.assertEqual(result.normalized_period.lower, "2026-07-01")
        self.assertEqual(result.formula_refs, refs)

    def test_s3_broadcast_total_keeps_its_real_row_without_fabricating_a_side_key(self):
        inputs, policy = inputs_fixture("s3"), typed_policy("s3")
        receipt = compatibility.check_context_compatibility(inputs, policy, operation="divide")
        aligned = alignment.align_context_keys(inputs, receipt, policy)
        self.assertEqual(aligned.status, "aligned")
        supplied = inputs["total"]
        unit = next(item for item in supplied.declarations if item.declaration_type == "unit")
        reading = numeric.read_numeric_value(supplied.context, "col_m", 0, policy.numeric_rules,
                                             evidence_id="total:metric", unit_id=unit.claims.unit.unit_id)
        result = evidence.build_signal_evidence(
            context=supplied.context, selection=supplied.selection, context_role="total",
            evidence_id="total:metric", context_digest=compatibility.context_digest(supplied.context),
            row_index=0, numeric_result=reading, alignment_pair=aligned.pairs[0], alignment_side="right",
            formula_refs=[EvidenceFormulaRef(formula_id="contribution_rate")],
            compatibility=receipt, unit_declaration=unit,
        )
        self.assertEqual(result.alignment_status, "matched")
        self.assertEqual(result.row_index, 0)
        self.assertIsNone(result.business_key)
        self.assertEqual(result.key_values, [])
        self.assertEqual(result.raw_value, "90.00")


if __name__ == "__main__":
    unittest.main()
