"""Row-key alignment from captured facts and explicit, approved Policy rules.

Normal cases use the real Compatibility checker and its scoped fixture
declarations. ``synthetic_receipt`` is used only to exercise the narrow
Alignment boundary defensively; its binding is only a test fixture, never a
production qualification proof. It does not mock or bypass the receipt gate.
No fixture parses or executes SQL or reads a metric value.
"""

import ast
import copy
import inspect
import socket
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from app.querying.business_signals import alignment, compatibility, numeric
from app.querying.business_signals.models import ContextCompatibility, SignalInput
from app.querying.business_signals.receipt_binding import bind_receipt
from app.querying.result_understanding.models import BusinessContext
from test_business_signal_compatibility import (
    KINDS, binding, captured_context, inputs_fixture, source, supplied_input,
    replace_declaration, typed_policy,
)


def with_rows(inputs, role, keys, *, kind="s2", dtype="VARCHAR"):
    """Reissue the fixture declarations against these explicit captured rows."""
    raw = captured_context(kind, role)
    if role == "total":
        raw["execution"]["rows"] = [[value] for value in keys]
    else:
        raw["execution"]["columns"][0]["dtype"] = dtype
        raw["execution"]["rows"] = [[value, "90.00"] for value in keys]
    raw["execution"]["returned_rows"] = len(keys)
    raw["execution"]["total_rows"] = len(keys)
    inputs[role] = supplied_input(kind, role, raw)


def fixture(left=("华北", "华东"), right=("华北", "华东"), *, kind="s2", dtype="VARCHAR"):
    inputs = inputs_fixture(kind)
    left_role, right_role = KINDS[kind][1]
    with_rows(inputs, left_role, left, kind=kind, dtype=dtype)
    with_rows(inputs, right_role, right, kind=kind, dtype=dtype)
    return inputs


def changed_context(inputs, role, mutate):
    """Update a captured Context for a synthetic-receipt boundary case."""
    raw = inputs[role].context.model_dump(mode="python")
    mutate(raw)
    inputs[role] = inputs[role].model_copy(update={
        "context": BusinessContext.model_validate(raw),
    }, deep=True)


def changed_receipt(receipt, mutate):
    """Reconstruct a changed, structurally valid receipt without rebinding it."""
    raw = receipt.model_dump(mode="python")
    mutate(raw)
    return ContextCompatibility.model_validate(raw)


def synthetic_receipt(inputs, policy, *, operation="compare", status="compatible"):
    receipt = ContextCompatibility(
        operation=operation,
        context_roles=list(policy.required_roles),
        result_ids={role: value.context.result_id for role, value in inputs.items()},
        status=status,
        key_domains=list(dict.fromkeys(rule.domain_id for rule in policy.key_rules)),
        input_digests={role: compatibility.context_digest(value.context) for role, value in inputs.items()},
        normalized_metric_refs=[{
            "context_role": rule.context_role, "metric_id": rule.metric_id,
            "mapping_id": rule.mapping_id, "match_status": "matched",
        } for rule in policy.metric_rules],
    )
    return bind_receipt(receipt, inputs, policy)


def integer_policy():
    raw = typed_policy().model_dump(mode="python")
    raw["key_rules"][0]["value_type"] = "integer"
    return type(typed_policy()).model_validate(raw)


def mapping_policy(entries):
    raw = typed_policy().model_dump(mode="python")
    raw["key_rules"][0].update({
        "normalization": "explicit_mapping", "mapping_id": "approved-region-map",
        "mapping_version": "1",
        "value_mappings": [{"raw_value": old, "normalized_value": new} for old, new in entries],
    })
    return type(typed_policy()).model_validate(raw)


def composite_fixture():
    inputs = inputs_fixture()
    raw_policy = typed_policy().model_dump(mode="python")
    raw_policy["key_rules"].append({
        "domain_id": "sales-channel", "component_id": "channel", "value_type": "string",
        "sources": [{"context_role": role, "source": source(role, "channel")}
                    for role in ("current", "baseline")],
    })
    for grain in raw_policy["grain_rules"]:
        grain["grouping_sources"].append(source(grain["context_role"], "channel"))
    policy = type(typed_policy()).model_validate(raw_policy)
    for role in ("current", "baseline"):
        raw = captured_context("s2", role)
        key_source = source(role, "channel")
        raw["execution"]["columns"].append({
            "id": "col_channel", "ordinal": 2, "name": "display_key", "dtype": "VARCHAR",
            "value_encoding": "native_json", "representation_status": "preserved",
        })
        raw["column_semantics"].append({
            "column_id": "col_channel", "ordinal": 2, "output_name": "display_key",
            "expression": "opaque channel key", "lineage": [key_source], "status": "resolved",
            "schema_bindings": [binding(key_source)],
        })
        raw["query_bindings"]["bindings"].append(binding(key_source))
        raw["grain"]["grouping_columns"] = raw["grain"]["grouping_columns"] + [key_source]
        raw["grain"]["grouping_expressions"].append("opaque channel key")
        raw["grain"]["business_grain"].append("display only")
        rows = [["华北", "90.00", "web"], ["华北", "80.00", "store"]]
        raw["execution"]["rows"] = rows if role == "current" else list(reversed(rows))
        raw["execution"]["returned_rows"] = raw["execution"]["total_rows"] = 2
        supplied = supplied_input("s2", role, raw)
        declarations = []
        for declaration in supplied.declarations:
            scope = declaration.scope.model_copy(update={
                "key_domains": ["sales-region", "sales-channel"],
            }, deep=True)
            declarations.append(declaration.model_copy(update={
                "scope": scope, "column_ids": ["col_m", "col_k", "col_channel"],
            }, deep=True))
        inputs[role] = supplied.model_copy(update={
            "selection": supplied.selection.model_copy(update={
                "key_column_ids": {"region": "col_k", "channel": "col_channel"},
            }, deep=True), "declarations": declarations,
        }, deep=True)
    return inputs, policy


def values(key, *, raw=False):
    return tuple(component.raw_value if raw else component.normalized_value for component in key.components)


class BusinessSignalAlignmentTests(unittest.TestCase):
    def approved(self, inputs, policy=None, *, operation="compare"):
        policy = policy or typed_policy()
        receipt = compatibility.check_context_compatibility(inputs, policy, operation=operation)
        self.assertEqual(receipt.status, "compatible", receipt.model_dump())
        return receipt

    def align(self, inputs=None, policy=None, receipt=None, *, operation="compare"):
        inputs = inputs if inputs is not None else fixture()
        policy = policy or typed_policy()
        receipt = receipt if receipt is not None else self.approved(inputs, policy, operation=operation)
        return alignment.align_context_keys(inputs, receipt, policy)

    def assert_state(self, result, expected):
        self.assertEqual(result.status, expected, result.model_dump())
        if expected != "aligned":
            self.assertTrue(result.issues, result.model_dump())
            self.assertTrue(all(item.code and item.evidence_paths for item in result.issues))
        return result

    def pair_map(self, result):
        return {values(pair.key): pair for pair in result.pairs}

    def test_complete_region_match_is_aligned(self):
        result = self.assert_state(self.align(), "aligned")
        self.assertEqual(result.operation, "compare")
        self.assertEqual((result.left_role, result.right_role), ("current", "baseline"))
        self.assertEqual(result.key_domain, ["sales-region"])
        self.assertEqual(len(result.pairs), 2)
        self.assertTrue(all(pair.status == "matched" for pair in result.pairs))
        self.assertFalse(result.missing_left_keys or result.missing_right_keys or result.duplicate_keys)

    def test_extra_left_key_is_missing_right(self):
        result = self.assert_state(self.align(fixture(right=("华北",))), "insufficient_evidence")
        self.assertEqual([values(key) for key in result.missing_right_keys], [("华东",)])
        pair = self.pair_map(result)[("华东",)]
        self.assertEqual((pair.status, pair.left_row_index, pair.right_row_index), ("missing_right", 1, None))
        self.assertIsNotNone(pair.left_key)
        self.assertIsNone(pair.right_key)

    def test_extra_right_key_is_missing_left(self):
        result = self.assert_state(self.align(fixture(left=("华北",))), "insufficient_evidence")
        self.assertEqual([values(key) for key in result.missing_left_keys], [("华东",)])
        pair = self.pair_map(result)[("华东",)]
        self.assertEqual((pair.status, pair.left_row_index, pair.right_row_index), ("missing_left", None, 1))

    def test_outer_union_keeps_both_unmatched_sides(self):
        result = self.align(fixture(left=("华北", "华东"), right=("华北", "华南")))
        self.assertEqual(set(self.pair_map(result)), {("华北",), ("华东",), ("华南",)})
        self.assertEqual({pair.status for pair in result.pairs}, {"matched", "missing_left", "missing_right"})

    def test_duplicate_key_never_chooses_first_row(self):
        result = self.assert_state(self.align(fixture(left=("华北", "华北"), right=("华北",))), "incompatible_context")
        self.assertEqual(len(result.duplicate_keys), 1)
        duplicate = result.duplicate_keys[0]
        self.assertEqual((duplicate.context_role, duplicate.row_indexes), ("current", [0, 1]))
        self.assertEqual([values(key, raw=True) for key in duplicate.raw_keys], [("华北",), ("华北",)])
        self.assertFalse(duplicate.normalization_collision)
        pair = self.pair_map(result)[("华北",)]
        self.assertEqual(pair.status, "ambiguous")
        self.assertIsNone(pair.left_row_index)
        self.assertIsNone(pair.left_key)
        self.assertEqual(pair.right_row_index, 0)

    def test_both_sides_duplicate_preserve_all_rows(self):
        result = self.align(fixture(left=("华北", "华北"), right=("华北", "华北", "华北")))
        self.assertEqual(result.status, "incompatible_context")
        self.assertEqual({item.context_role: item.row_indexes for item in result.duplicate_keys},
                         {"current": [0, 1], "baseline": [0, 1, 2]})
        self.assertEqual((result.pairs[0].left_row_index, result.pairs[0].right_row_index), (None, None))

    def test_different_row_order_retains_actual_row_indexes(self):
        result = self.assert_state(self.align(fixture(right=("华东", "华北"))), "aligned")
        pairs = self.pair_map(result)
        self.assertEqual((pairs[("华北",)].left_row_index, pairs[("华北",)].right_row_index), (0, 1))
        self.assertEqual((pairs[("华东",)].left_row_index, pairs[("华东",)].right_row_index), (1, 0))

    def test_duplicate_display_names_do_not_choose_metric_column(self):
        inputs = fixture()
        for role in inputs:
            raw = inputs[role].context.model_dump(mode="python")
            for column in raw["execution"]["columns"]:
                column["name"] = "same display"
            for semantic in raw["column_semantics"]:
                semantic["output_name"] = "same display"
            inputs[role] = supplied_input("s2", role, raw)
        result = self.assert_state(self.align(inputs), "aligned")
        self.assertEqual(set(self.pair_map(result)), {("华北",), ("华东",)})

    def test_column_id_selects_nonzero_ordinal(self):
        inputs = fixture()
        for role in inputs:
            raw = inputs[role].context.model_dump(mode="python")
            raw["execution"]["columns"].reverse()
            raw["column_semantics"].reverse()
            for ordinal, column in enumerate(raw["execution"]["columns"]):
                column["ordinal"] = ordinal
            for ordinal, semantic in enumerate(raw["column_semantics"]):
                semantic["ordinal"] = ordinal
            raw["execution"]["rows"] = [list(reversed(row)) for row in raw["execution"]["rows"]]
            inputs[role] = supplied_input("s2", role, raw)
        result = self.assert_state(self.align(inputs), "aligned")
        self.assertEqual(set(self.pair_map(result)), {("华北",), ("华东",)})

    def test_integer_keys_stay_integers(self):
        result = self.assert_state(self.align(fixture(left=(1, 2), right=(2, 1), dtype="INTEGER"), integer_policy()), "aligned")
        self.assertTrue(all(type(component.raw_value) is int and type(component.normalized_value) is int
                            for pair in result.pairs for component in pair.key.components))
        self.assertEqual(set(self.pair_map(result)), {(1,), (2,)})

    def test_integer_key_rejects_text_cell_without_coercion(self):
        result = self.align(fixture(left=(1,), right=("1",), dtype="INTEGER"), integer_policy())
        self.assert_state(result, "incompatible_context")
        self.assertFalse(any(pair.status == "matched" for pair in result.pairs))

    def test_integer_key_rejects_boolean_cell(self):
        result = self.align(fixture(left=(1,), right=(True,), dtype="INTEGER"), integer_policy())
        self.assert_state(result, "incompatible_context")

    def test_integer_key_rejects_integral_float_cell(self):
        result = self.align(fixture(left=(1,), right=(1.0,), dtype="INTEGER"), integer_policy())
        self.assert_state(result, "incompatible_context")

    def test_string_key_rejects_integer_cell(self):
        result = self.align(fixture(left=("1",), right=(1,)))
        self.assert_state(result, "incompatible_context")
        self.assertFalse(any(pair.status == "matched" for pair in result.pairs))

    def test_integer_declared_range_is_enforced(self):
        for dtype, value in (("TINYINT", 128), ("UTINYINT", -1), ("INTEGER", 2 ** 31), ("BIGINT", 2 ** 63)):
            with self.subTest(dtype=dtype):
                inputs = fixture(left=(value,), right=(value,), dtype=dtype)
                self.assert_state(self.align(inputs, integer_policy()), "incompatible_context")

    def test_integer_boundary_values_remain_exact(self):
        for dtype, boundaries in (("TINYINT", (-128, 127)), ("UTINYINT", (0, 255)),
                                  ("BIGINT", (-2 ** 63, 2 ** 63 - 1))):
            with self.subTest(dtype=dtype):
                result = self.align(fixture(left=boundaries, right=boundaries, dtype=dtype), integer_policy())
                self.assert_state(result, "aligned")
                self.assertEqual(set(self.pair_map(result)), {(value,) for value in boundaries})

    def test_no_unauthorized_region_mapping(self):
        result = self.assert_state(self.align(fixture(left=("华北地区",), right=("华北",))), "insufficient_evidence")
        self.assertEqual(len(result.pairs), 2)
        self.assertFalse(any(pair.status == "matched" for pair in result.pairs))

    def test_identity_does_not_trim_or_casefold(self):
        inputs = fixture(left=(" North ", "STRASSE"), right=("North", "straße"))
        result = self.assert_state(self.align(inputs), "insufficient_evidence")
        self.assertEqual(len(result.pairs), 4)
        self.assertEqual({component.raw_value for pair in result.pairs for component in pair.key.components},
                         {" North ", "North", "STRASSE", "straße"})

    def test_identity_preserves_empty_string_exactly(self):
        result = self.assert_state(self.align(fixture(left=("",), right=("",))), "aligned")
        self.assertEqual(values(result.pairs[0].key, raw=True), ("",))

    def test_explicit_mapping_preserves_both_raw_role_keys(self):
        policy = mapping_policy([("华北地区", "north"), ("华北", "north")])
        result = self.assert_state(self.align(fixture(left=("华北地区",), right=("华北",)), policy), "aligned")
        pair = result.pairs[0]
        self.assertEqual(values(pair.key), ("north",))
        self.assertEqual(values(pair.left_key, raw=True), ("华北地区",))
        self.assertEqual(values(pair.right_key, raw=True), ("华北",))
        self.assertEqual(values(pair.left_key), values(pair.right_key))

    def test_mapping_collision_is_duplicate_not_overwrite(self):
        policy = mapping_policy([("华北地区", "north"), ("华北", "north")])
        result = self.assert_state(self.align(fixture(left=("华北地区", "华北"), right=("华北",)), policy), "incompatible_context")
        duplicate = result.duplicate_keys[0]
        self.assertTrue(duplicate.normalization_collision)
        self.assertEqual(duplicate.row_indexes, [0, 1])
        self.assertEqual([values(key, raw=True) for key in duplicate.raw_keys], [("华北地区",), ("华北",)])
        self.assertIsNone(result.pairs[0].left_row_index)

    def test_unmapped_value_does_not_fall_back_to_identity(self):
        policy = mapping_policy([("华北地区", "north")])
        result = self.assert_state(self.align(fixture(left=("north",), right=("north",)), policy), "insufficient_evidence")
        self.assertFalse(result.pairs)
        self.assertFalse(result.missing_left_keys or result.missing_right_keys)

    def test_mapping_partial_side_does_not_assert_counterpart_missing(self):
        policy = mapping_policy([("华北", "north"), ("华南", "south")])
        result = self.align(fixture(left=("unmapped",), right=("华南",)), policy)
        self.assert_state(result, "insufficient_evidence")
        self.assertEqual(result.pairs[0].status, "unresolved")
        self.assertFalse(result.missing_left_keys)

    def test_null_key_is_insufficient_without_coercion(self):
        result = self.assert_state(self.align(fixture(left=(None,), right=("华北",))), "insufficient_evidence")
        self.assertEqual(len(result.pairs), 1)
        self.assertEqual(result.pairs[0].status, "unresolved")
        self.assertFalse(result.missing_left_keys)
        self.assertIsNone(result.pairs[0].left_row_index)

    def test_null_key_does_not_hide_other_matched_rows(self):
        result = self.align(fixture(left=("华北", None), right=("华北", "华南")))
        self.assert_state(result, "insufficient_evidence")
        pairs = self.pair_map(result)
        self.assertEqual(pairs[("华北",)].status, "matched")
        self.assertEqual(pairs[("华南",)].status, "unresolved")

    def test_duplicate_has_priority_over_missing_or_null(self):
        result = self.align(fixture(left=("华北", "华北", None), right=("华南",)))
        self.assert_state(result, "incompatible_context")
        self.assertTrue(result.duplicate_keys)
        self.assertGreaterEqual(len(result.issues), 2)

    def test_composite_key_uses_every_ordered_component(self):
        inputs, policy = composite_fixture()
        result = self.assert_state(self.align(inputs, policy), "aligned")
        self.assertEqual(result.key_domain, ["sales-region", "sales-channel"])
        self.assertEqual(set(self.pair_map(result)), {("华北", "web"), ("华北", "store")})
        self.assertTrue(all([component.component_id for component in pair.key.components] == ["region", "channel"]
                            for pair in result.pairs))
        self.assertFalse(result.duplicate_keys)

    def test_selection_dict_order_does_not_change_component_order(self):
        inputs, policy = composite_fixture()
        expected = self.align(inputs, policy).model_dump(mode="json")
        for role, supplied in list(inputs.items()):
            selection = supplied.selection.model_copy(update={
                "key_column_ids": dict(reversed(list(supplied.selection.key_column_ids.items()))),
            }, deep=True)
            inputs[role] = supplied.model_copy(update={"selection": selection}, deep=True)
        self.assertEqual(self.align(inputs, policy).model_dump(mode="json"), expected)

    def test_global_total_broadcast_when_explicitly_allowed(self):
        inputs = fixture(left=("food", "books"), right=("900.00",), kind="s3")
        result = self.assert_state(self.align(inputs, typed_policy("s3"), operation="divide"), "aligned")
        self.assertTrue(result.broadcastable)
        self.assertEqual(result.broadcast_role, "total")
        self.assertEqual((result.left_role, result.right_role), ("parts", "total"))
        self.assertEqual(len(result.pairs), 2)
        self.assertTrue(all(pair.broadcast and pair.right_row_index == 0 and pair.right_key is None for pair in result.pairs))

    def test_global_total_broadcast_denied_by_policy(self):
        inputs = fixture(left=("food",), right=("900.00",), kind="s3")
        raw = typed_policy("s3").model_dump(mode="python")
        raw["grain_rules"][1]["total_broadcast"] = "forbid"
        policy = type(typed_policy("s3")).model_validate(raw)
        result = self.align(inputs, policy, synthetic_receipt(inputs, policy, operation="divide"))
        self.assert_state(result, "incompatible_context")
        self.assertFalse(result.broadcastable)

    def test_broadcast_requires_one_total_row(self):
        inputs = fixture(left=("food",), right=("900.00", "800.00"), kind="s3")
        policy = typed_policy("s3")
        result = self.align(inputs, policy, synthetic_receipt(inputs, policy, operation="divide"))
        self.assert_state(result, "incompatible_context")
        self.assertFalse(result.broadcastable)

    def test_broadcast_requires_actual_global_grain(self):
        inputs = fixture(left=("food",), right=("900.00",), kind="s3")
        changed_context(inputs, "total", lambda raw: raw["grain"].update({"query_grain": "grouped"}))
        policy = typed_policy("s3")
        result = self.align(inputs, policy, synthetic_receipt(inputs, policy, operation="divide"))
        self.assert_state(result, "incompatible_context")
        self.assertFalse(result.broadcastable)

    def test_broadcast_requires_empty_key_selection(self):
        inputs = fixture(left=("food",), right=("900.00",), kind="s3")
        total = inputs["total"]
        inputs["total"] = total.model_copy(update={"selection": total.selection.model_copy(update={
            "key_column_ids": {"category": "col_m"},
        }, deep=True)}, deep=True)
        policy = typed_policy("s3")
        result = self.align(inputs, policy, synthetic_receipt(inputs, policy, operation="divide"))
        self.assert_state(result, "incompatible_context")
        self.assertFalse(result.broadcastable)

    def test_grouped_pair_does_not_claim_broadcast(self):
        result = self.align()
        self.assertFalse(result.broadcastable)
        self.assertIsNone(result.broadcast_role)
        self.assertTrue(all(not pair.broadcast for pair in result.pairs))

    def test_empty_rows_produce_explicit_insufficient_gate(self):
        inputs = fixture(left=())
        policy = typed_policy()
        receipt = compatibility.check_context_compatibility(inputs, policy, operation="compare")
        self.assertEqual(receipt.status, "insufficient_evidence")
        result = self.assert_state(self.align(inputs, policy, receipt), "insufficient_evidence")
        self.assertFalse(result.pairs)

    def test_none_rows_produce_explicit_insufficient_gate(self):
        inputs = fixture()
        raw = inputs["current"].context.model_dump(mode="python")
        raw["execution"].update({"rows": None, "returned_rows": None, "total_rows": None})
        inputs["current"] = supplied_input("s2", "current", raw)
        policy = typed_policy()
        receipt = compatibility.check_context_compatibility(inputs, policy, operation="compare")
        result = self.assert_state(self.align(inputs, policy, receipt), "insufficient_evidence")
        self.assertFalse(result.pairs)

    def test_empty_rows_defensive_receipt_retains_known_union(self):
        inputs = fixture(left=())
        policy = typed_policy()
        result = self.assert_state(self.align(inputs, policy, synthetic_receipt(inputs, policy)), "insufficient_evidence")
        self.assertEqual(set(self.pair_map(result)), {("华北",), ("华东",)})
        self.assertTrue(all(pair.status == "missing_left" for pair in result.pairs))

    def test_none_rows_defensive_receipt_does_not_assert_missing(self):
        inputs = fixture()
        changed_context(inputs, "current", lambda raw: raw["execution"].update({
            "rows": None, "returned_rows": None, "total_rows": None,
        }))
        policy = typed_policy()
        result = self.assert_state(self.align(inputs, policy, synthetic_receipt(inputs, policy)), "insufficient_evidence")
        self.assertTrue(all(pair.status == "unresolved" for pair in result.pairs))
        self.assertFalse(result.missing_left_keys)

    def test_noncompatible_receipts_gate_before_key_extraction(self):
        inputs = fixture(left=("华北", "华北"), right=("华北",))
        policy = typed_policy()
        for status in ("insufficient_evidence", "incompatible_context", "unsupported"):
            with self.subTest(status=status):
                receipt = synthetic_receipt(inputs, policy, status=status)
                result = self.assert_state(self.align(inputs, policy, receipt), status)
                self.assertFalse(result.pairs or result.duplicate_keys)

    def test_stale_context_digest_rejects_changed_rows(self):
        inputs = fixture()
        receipt = self.approved(inputs)
        with_rows(inputs, "current", ("西南",))
        result = self.assert_state(self.align(inputs, receipt=receipt), "incompatible_context")
        self.assertFalse(result.pairs)

    def test_stale_result_identity_is_rejected(self):
        inputs = fixture()
        receipt = self.approved(inputs)
        receipt = receipt.model_copy(update={"result_ids": {"current": "wrong-result", "baseline": inputs["baseline"].context.result_id}}, deep=True)
        result = self.assert_state(self.align(inputs, receipt=receipt), "incompatible_context")
        self.assertFalse(result.pairs)

    def test_missing_receipt_digest_is_incompatible(self):
        inputs = fixture()
        receipt = self.approved(inputs).model_copy(update={"input_digests": {}}, deep=True)
        result = self.assert_state(self.align(inputs, receipt=receipt), "incompatible_context")
        self.assertFalse(result.pairs)

    def test_receipt_key_domain_mismatch_rejected(self):
        inputs = fixture()
        receipt = self.approved(inputs).model_copy(update={"key_domains": ["different-domain"]}, deep=True)
        result = self.assert_state(self.align(inputs, receipt=receipt), "incompatible_context")
        self.assertFalse(result.pairs)

    def test_receipt_roles_mismatch_rejected(self):
        inputs = fixture()
        receipt = self.approved(inputs).model_copy(update={"context_roles": ["actual", "target"]}, deep=True)
        result = self.assert_state(self.align(inputs, receipt=receipt), "incompatible_context")
        self.assertFalse(result.pairs)

    def test_receipt_metric_mapping_identity_mismatch_rejected(self):
        inputs = fixture()
        receipt = self.approved(inputs)
        references = list(receipt.normalized_metric_refs)
        references[0] = references[0].model_copy(update={"mapping_id": "other-explicit-mapping"}, deep=True)
        receipt = receipt.model_copy(update={"normalized_metric_refs": references}, deep=True)
        result = self.assert_state(self.align(inputs, receipt=receipt), "incompatible_context")
        self.assertTrue(any(issue.code == "COMPATIBILITY_POLICY_REFERENCE_MISMATCH" for issue in result.issues))
        self.assertFalse(result.pairs)

    def test_receipt_used_declaration_must_still_exist(self):
        inputs = fixture()
        receipt = self.approved(inputs)
        inputs["current"] = inputs["current"].model_copy(update={"declarations": []}, deep=True)
        result = self.assert_state(self.align(inputs, receipt=receipt), "incompatible_context")
        self.assertTrue(any(issue.code == "COMPATIBILITY_DECLARATION_REFERENCE_MISMATCH" for issue in result.issues))
        self.assertFalse(result.pairs)

    def test_receipt_blank_digest_is_incompatible(self):
        inputs = fixture()
        receipt = self.approved(inputs)
        digests = dict(receipt.input_digests)
        digests["current"] = "   "
        receipt = receipt.model_copy(update={"input_digests": digests}, deep=True)
        result = self.assert_state(self.align(inputs, receipt=receipt), "incompatible_context")
        self.assertTrue(any(issue.code == "COMPATIBILITY_DIGEST_UNKNOWN" for issue in result.issues))
        self.assertFalse(result.pairs)

    def test_missing_selected_id_does_not_fall_back_to_display_name(self):
        inputs = fixture()
        selection = inputs["current"].selection.model_copy(update={"key_column_ids": {"region": "display_key"}}, deep=True)
        inputs["current"] = inputs["current"].model_copy(update={"selection": selection}, deep=True)
        policy = typed_policy()
        with self.assertRaises(ValueError):
            self.align(inputs, policy, synthetic_receipt(inputs, policy))

    def test_missing_key_component_is_explicitly_rejected(self):
        inputs = fixture()
        selection = inputs["current"].selection.model_copy(update={"key_column_ids": {}}, deep=True)
        inputs["current"] = inputs["current"].model_copy(update={"selection": selection}, deep=True)
        policy = typed_policy()
        result = self.assert_state(self.align(inputs, policy, synthetic_receipt(inputs, policy)), "incompatible_context")
        self.assertTrue(any(issue.code == "KEY_SELECTION_MISMATCH" for issue in result.issues))

    def test_missing_column_metadata_is_unknown(self):
        inputs = fixture()
        changed_context(inputs, "current", lambda raw: raw["execution"].update({"columns": None}))
        policy = typed_policy()
        result = self.assert_state(self.align(inputs, policy, synthetic_receipt(inputs, policy)), "insufficient_evidence")
        self.assertTrue(any(issue.code == "KEY_METADATA_UNKNOWN" for issue in result.issues))
        self.assertTrue(all(pair.status == "unresolved" for pair in result.pairs))
        self.assertFalse(result.missing_left_keys)

    def test_unknown_dtype_encoding_and_fidelity_are_insufficient(self):
        for field in ("dtype", "value_encoding", "representation_status"):
            with self.subTest(field=field):
                inputs = fixture()
                changed_context(inputs, "current", lambda raw: raw["execution"]["columns"][0].update({field: None}))
                policy = typed_policy()
                result = self.assert_state(self.align(inputs, policy, synthetic_receipt(inputs, policy)), "insufficient_evidence")
                self.assertTrue(any(issue.code == "KEY_METADATA_UNKNOWN" for issue in result.issues))
                self.assertFalse(result.missing_left_keys)

    def test_key_lossy_representation_is_incompatible(self):
        inputs = fixture()
        changed_context(inputs, "current", lambda raw: raw["execution"]["columns"][0].update({"representation_status": "lossy"}))
        policy = typed_policy()
        result = self.assert_state(self.align(inputs, policy, synthetic_receipt(inputs, policy)), "incompatible_context")
        self.assertTrue(any(issue.code == "KEY_REPRESENTATION_LOSSY" for issue in result.issues))

    def test_unsupported_key_representation_has_highest_priority(self):
        inputs = fixture(left=("华北",), right=("华北", "华北", None))
        changed_context(inputs, "current", lambda raw: raw["execution"]["columns"][0].update({"representation_status": "unsupported"}))
        policy = typed_policy()
        result = self.assert_state(self.align(inputs, policy, synthetic_receipt(inputs, policy)), "unsupported")
        self.assertTrue(result.duplicate_keys)
        self.assertTrue(any(issue.code == "NULL_KEY" for issue in result.issues))
        self.assertTrue(any(issue.code == "KEY_REPRESENTATION_UNSUPPORTED" for issue in result.issues))

    def test_key_codec_does_not_use_metric_decimal_decoder(self):
        inputs = fixture()
        changed_context(inputs, "current", lambda raw: raw["execution"]["columns"][0].update({
            "dtype": "DECIMAL(18,2)", "value_encoding": "decimal_text",
        }))
        policy = typed_policy()
        result = self.assert_state(self.align(inputs, policy, synthetic_receipt(inputs, policy)), "unsupported")
        self.assertTrue(any(issue.code == "KEY_CODEC_UNSUPPORTED" for issue in result.issues))

    def test_supported_dtype_conflicting_with_policy_is_incompatible(self):
        inputs = fixture(left=(1,), right=(1,), dtype="INTEGER")
        policy = typed_policy()
        result = self.assert_state(self.align(inputs, policy, synthetic_receipt(inputs, policy)), "incompatible_context")
        self.assertTrue(any(issue.code == "KEY_TYPE_MISMATCH" for issue in result.issues))

    def test_ambiguous_bucket_is_not_marked_missing_on_other_side(self):
        inputs = fixture(left=("华北", "华北"), right=())
        policy = typed_policy()
        result = self.assert_state(self.align(inputs, policy, synthetic_receipt(inputs, policy)), "incompatible_context")
        self.assertEqual(result.pairs[0].status, "ambiguous")
        self.assertFalse(result.missing_right_keys)
        self.assertIsNone(result.pairs[0].left_row_index)

    def test_broadcast_preserves_duplicate_parts_as_ambiguous(self):
        inputs = fixture(left=("food", "food"), right=("900.00",), kind="s3")
        result = self.assert_state(self.align(inputs, typed_policy("s3"), operation="divide"), "incompatible_context")
        self.assertTrue(result.duplicate_keys)
        pair = result.pairs[0]
        self.assertEqual((pair.status, pair.left_row_index, pair.right_row_index), ("ambiguous", None, 0))
        self.assertTrue(pair.broadcast)

    def test_total_unknown_rows_never_broadcast_zero(self):
        inputs = fixture(left=("food",), right=("900.00",), kind="s3")
        changed_context(inputs, "total", lambda raw: raw["execution"].update({"rows": None, "returned_rows": None, "total_rows": None}))
        policy = typed_policy("s3")
        result = self.assert_state(self.align(inputs, policy, synthetic_receipt(inputs, policy, operation="divide")), "insufficient_evidence")
        self.assertFalse(result.broadcastable)
        self.assertFalse(result.pairs)

    def test_policy_and_inputs_must_be_typed(self):
        inputs = fixture()
        policy = typed_policy()
        receipt = self.approved(inputs, policy)
        with self.assertRaises(TypeError):
            alignment.align_context_keys(inputs, receipt, policy.model_dump())
        with self.assertRaises(TypeError):
            alignment.align_context_keys(list(inputs.values()), receipt, policy)
        with self.assertRaises(TypeError):
            alignment.align_context_keys(inputs, receipt.model_dump(), policy)

    def test_role_keys_must_match_policy_exactly(self):
        inputs = fixture()
        policy = typed_policy()
        receipt = self.approved(inputs, policy)
        with self.assertRaises(ValueError):
            alignment.align_context_keys({"current": inputs["current"]}, receipt, policy)

    def test_receipt_periods_preserved_without_time_inference(self):
        inputs = fixture()
        receipt = self.approved(inputs)
        result = self.assert_state(self.align(inputs, receipt=receipt), "aligned")
        self.assertTrue(all(pair.key.periods == receipt.periods for pair in result.pairs))
        self.assertEqual([period.context_role for period in result.pairs[0].key.periods], ["current", "baseline"])

    def test_operation_align_is_retained(self):
        result = self.assert_state(self.align(operation="align"), "aligned")
        self.assertEqual(result.operation, "align")

    def test_s1_actual_target_rows_align_without_formula(self):
        inputs = fixture(kind="s1")
        result = self.assert_state(self.align(inputs, typed_policy("s1"), operation="divide"), "aligned")
        self.assertEqual((result.left_role, result.right_role), ("actual", "target"))
        self.assertEqual(result.operation, "divide")
        self.assertNotIn("computed", result.model_dump_json())

    def test_input_and_policy_are_unchanged(self):
        inputs = fixture(left=("华北", "华北"), right=("华南",))
        policy = typed_policy()
        receipt = self.approved(inputs, policy)
        before = copy.deepcopy((inputs, policy, receipt))
        self.align(inputs, policy, receipt)
        self.assertEqual((inputs, policy, receipt), before)

    def test_repeated_a_then_b_then_a_is_deterministic(self):
        inputs_a = fixture()
        inputs_b = fixture(left=("华北", "华北"), right=("西南",))
        first = self.align(inputs_a).model_dump(mode="json")
        self.align(inputs_b)
        self.assertEqual(self.align(inputs_a).model_dump(mode="json"), first)

    def test_input_role_insertion_order_is_irrelevant(self):
        inputs = fixture()
        receipt = self.approved(inputs)
        expected = self.align(inputs, receipt=receipt).model_dump(mode="json")
        reverse = dict(reversed(list(inputs.items())))
        self.assertEqual(self.align(reverse, receipt=receipt).model_dump(mode="json"), expected)

    def test_output_order_is_stable_when_row_order_changes(self):
        first = self.align(fixture(left=("华北", "华东"), right=("华南", "华北")))
        second = self.align(fixture(left=("华东", "华北"), right=("华北", "华南")))
        self.assertEqual([values(pair.key) for pair in first.pairs], [values(pair.key) for pair in second.pairs])
        self.assertEqual([(values(pair.key), pair.status) for pair in first.pairs],
                         [(values(pair.key), pair.status) for pair in second.pairs])

    def test_output_nested_keys_are_detached_from_other_calls(self):
        inputs = fixture()
        first = self.align(inputs)
        expected = self.align(inputs).model_dump(mode="json")
        first.pairs[0].key.components.clear()
        self.assertEqual(self.align(inputs).model_dump(mode="json"), expected)

    def test_metric_cells_are_not_decoded(self):
        inputs = fixture()
        for role in inputs:
            raw = inputs[role].context.model_dump(mode="python")
            for row in raw["execution"]["rows"]:
                row[1] = "invalid decimal; no numeric observation requested"
            inputs[role] = supplied_input("s2", role, raw)
        result = self.assert_state(self.align(inputs), "aligned")
        self.assertEqual(len(result.pairs), 2)

    def test_alignment_does_not_call_compatibility_or_numeric_reader(self):
        inputs = fixture()
        policy = typed_policy()
        receipt = self.approved(inputs, policy)
        with ExitStack() as stack:
            stack.enter_context(patch.object(compatibility, "check_context_compatibility", side_effect=AssertionError("no compatibility rerun")))
            stack.enter_context(patch.object(numeric, "read_numeric_value", side_effect=AssertionError("no metric read")))
            stack.enter_context(patch.object(numeric, "check_numeric_column", side_effect=AssertionError("no numeric column read")))
            result = self.align(inputs, policy, receipt)
        self.assert_state(result, "aligned")

    def test_alignment_performs_no_sql_or_network(self):
        inputs = fixture()
        policy = typed_policy()
        receipt = self.approved(inputs, policy)
        import duckdb
        from app.querying.result_understanding import sql_parser
        with ExitStack() as stack:
            stack.enter_context(patch.object(sql_parser, "parse_sql", side_effect=AssertionError("no SQL parsing")))
            stack.enter_context(patch.object(duckdb, "connect", side_effect=AssertionError("no SQL execution")))
            stack.enter_context(patch.object(socket, "create_connection", side_effect=AssertionError("no network")))
            result = self.align(inputs, policy, receipt)
        self.assert_state(result, "aligned")

    def test_alignment_module_has_no_acquisition_or_computation_imports(self):
        tree = ast.parse(inspect.getsource(alignment))
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
        forbidden = {"duckdb", "sqlglot", "sql_parser", "lineage", "requests", "socket", "httpx",
                     "openai", "datetime", "time", "numeric", "engine", "formulas"}
        self.assertFalse([(module, part) for module in modules for part in module.split(".") if part in forbidden])

    def test_alignment_issue_paths_point_to_captured_key_evidence(self):
        result = self.align(fixture(left=(None, "华北", "华北"), right=("华北",)))
        alignment_issues = [item for item in result.issues if item.stage == "alignment"]
        self.assertTrue(alignment_issues)
        self.assertTrue(any("rows" in path for item in alignment_issues for path in item.evidence_paths))
        self.assertTrue(all(item.code and item.context_role for item in alignment_issues))

    def assert_receipt_rejected_before_keys(self, inputs, receipt, policy=None, *, missing=False):
        """A binding failure must not inspect columns or produce row pairs."""
        with ExitStack() as stack:
            for method in ("structure", "extract", "broadcast", "outer_pairs"):
                stack.enter_context(patch.object(
                    alignment._Alignment, method,
                    side_effect=AssertionError(f"receipt mismatch reached {method}"),
                ))
            result = self.align(inputs, policy, receipt)
        self.assert_state(result, "incompatible_context")
        code = "COMPATIBILITY_BINDING_MISSING" if missing else "COMPATIBILITY_BINDING_MISMATCH"
        self.assertTrue(any(issue.code == code for issue in result.issues), result.model_dump())
        self.assertFalse(result.pairs or result.missing_left_keys or result.missing_right_keys or result.duplicate_keys)
        self.assertFalse(result.broadcastable)
        return result

    def test_bound_real_pipeline_keeps_all_three_readiness_fixtures_aligned(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                inputs = (fixture(kind=kind) if kind != "s3" else
                          fixture(left=("food", "tools"), right=("900.00",), kind=kind))
                policy = typed_policy(kind)
                receipt = self.approved(inputs, policy, operation="compare" if kind == "s2" else "divide")
                self.assertIsNotNone(receipt.binding)
                self.assert_state(self.align(inputs, policy, receipt), "aligned")

    def test_receipt_binds_actual_policy_source_even_with_same_declared_digest(self):
        inputs, policy = fixture(), typed_policy()
        receipt = self.approved(inputs, policy)
        raw = policy.model_dump(mode="python")
        raw["metric_rules"][0]["allowed_sources"][0]["field"] = "refund_amount"
        changed = type(policy).model_validate(raw)
        self.assertEqual((changed.policy_id, changed.version, changed.definition_digest),
                         (policy.policy_id, policy.version, policy.definition_digest))
        self.assert_receipt_rejected_before_keys(inputs, receipt, changed)

    def test_receipt_binds_policy_identity_fields(self):
        inputs, policy = fixture(), typed_policy()
        receipt = self.approved(inputs, policy)
        self.assertEqual(receipt.binding.policy_version, policy.version)
        for field, changed_value in (("policy_id", "different-policy"),
                                     ("definition_digest", "different-declared-digest")):
            with self.subTest(field=field):
                changed = policy.model_copy(update={field: changed_value}, deep=True)
                self.assert_receipt_rejected_before_keys(inputs, receipt, changed)

    def test_receipt_binds_metric_selection(self):
        inputs = fixture()
        receipt = self.approved(inputs)
        original = inputs["current"]
        inputs["current"] = original.model_copy(update={"selection": original.selection.model_copy(
            update={"metric_column_id": "col_k"}, deep=True)}, deep=True)
        self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_binds_key_selection_before_missing_id_validation(self):
        inputs = fixture()
        receipt = self.approved(inputs)
        original = inputs["current"]
        inputs["current"] = original.model_copy(update={"selection": original.selection.model_copy(
            update={"key_column_ids": {"region": "different-key-column"}}, deep=True)}, deep=True)
        self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_binds_auxiliary_selection(self):
        inputs = fixture()
        receipt = self.approved(inputs)
        original = inputs["current"]
        inputs["current"] = original.model_copy(update={"selection": original.selection.model_copy(
            update={"auxiliary_column_ids": {"caption": "col_k"}}, deep=True)}, deep=True)
        self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_binds_unit_claim_content_with_unchanged_declaration_id(self):
        inputs = fixture()
        receipt = self.approved(inputs)
        old_ids = [item.declaration_id for item in inputs["current"].declarations]
        replace_declaration(inputs, "current", "unit", lambda raw: raw["claims"]["unit"].update({"unit_id": "USD"}))
        self.assertEqual([item.declaration_id for item in inputs["current"].declarations], old_ids)
        self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_binds_complete_declaration_attribution_and_scope(self):
        changes = {
            "issuer_ref": lambda raw: raw.update({"issuer_ref": "other-catalog"}),
            "basis_ref": lambda raw: raw.update({"basis_ref": "other-basis"}),
            "columns": lambda raw: raw.update({"column_ids": ["col_m"]}),
            "scope": lambda raw: raw["scope"].update({"population_scope_ref": "another-population"}),
        }
        for name, mutate in changes.items():
            with self.subTest(field=name):
                inputs = fixture()
                receipt = self.approved(inputs)
                replace_declaration(inputs, "current", "unit", mutate)
                self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_binds_declaration_result_and_context_identity(self):
        for field in ("result_id", "context_digest"):
            with self.subTest(field=field):
                inputs = fixture()
                receipt = self.approved(inputs)
                replace_declaration(inputs, "current", "unit", lambda raw: raw.update({field: "different-identity"}))
                self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_rejects_added_declaration(self):
        inputs = fixture()
        receipt = self.approved(inputs)
        original = inputs["current"]
        extra = original.declarations[0].model_copy(update={"declaration_id": "additional-unit-claim"}, deep=True)
        inputs["current"] = original.model_copy(update={"declarations": original.declarations + [extra]}, deep=True)
        self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_rejects_removed_declaration(self):
        inputs = fixture()
        receipt = self.approved(inputs)
        original = inputs["current"]
        inputs["current"] = original.model_copy(update={"declarations": original.declarations[1:]}, deep=True)
        self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_rejects_reordered_declaration_snapshot(self):
        inputs = fixture()
        receipt = self.approved(inputs)
        original = inputs["current"]
        inputs["current"] = original.model_copy(update={"declarations": list(reversed(original.declarations))}, deep=True)
        self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_rejects_operation_compare_to_divide(self):
        inputs = fixture()
        receipt = self.approved(inputs).model_copy(update={"operation": "divide"}, deep=True)
        self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_rejects_operation_compare_to_align(self):
        inputs = fixture()
        receipt = self.approved(inputs).model_copy(update={"operation": "align"}, deep=True)
        self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_rejects_changed_normalized_period(self):
        inputs = fixture()
        receipt = changed_receipt(self.approved(inputs), lambda raw:
                                  raw["periods"][0]["period"].update({"lower": "2026-08-02"}))
        self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_rejects_changed_normalized_period_domain(self):
        inputs = fixture()
        receipt = changed_receipt(self.approved(inputs), lambda raw:
                                  raw["periods"][0]["period"].update({"domain_id": "another-calendar-domain"}))
        self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_binds_policy_metric_relationship(self):
        inputs, policy = fixture(), typed_policy()
        receipt = self.approved(inputs, policy)
        raw = policy.model_dump(mode="python")
        raw["relationship_rules"][0]["relationship_id"] = "replacement-relationship"
        self.assert_receipt_rejected_before_keys(inputs, receipt, type(policy).model_validate(raw))

    def test_receipt_binds_normalized_metric_relationship(self):
        inputs = fixture()
        receipt = changed_receipt(self.approved(inputs), lambda raw:
                                  raw["normalized_metric_refs"][0].update({"relationship_id": "replacement-relationship"}))
        self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_binds_normalized_metric_source_content(self):
        inputs = fixture()
        receipt = self.approved(inputs)
        self.assertTrue(receipt.normalized_metric_refs[0].source_fields)
        receipt = changed_receipt(receipt, lambda raw:
                                  raw["normalized_metric_refs"][0]["source_fields"][0].update({"field": "refund_amount"}))
        self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_binds_normalized_filters(self):
        inputs = fixture()
        receipt = changed_receipt(self.approved(inputs), lambda raw:
                                  raw["non_time_filters"][0]["value"].update({"value": "unpaid"}))
        self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_binds_normalized_key_domains(self):
        inputs = fixture()
        receipt = self.approved(inputs).model_copy(update={"key_domains": ["another-domain"]}, deep=True)
        self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_binds_declarations_used_content(self):
        inputs = fixture()
        receipt = changed_receipt(self.approved(inputs), lambda raw:
                                  raw["declarations_used"][0].update({"context_digest": "different-context-digest"}))
        self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_binds_declarations_used_membership(self):
        inputs = fixture()
        receipt = self.approved(inputs)
        receipt = receipt.model_copy(update={"declarations_used": receipt.declarations_used[1:]}, deep=True)
        self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_cannot_promote_noncompatible_status(self):
        inputs = fixture(left=())
        policy = typed_policy()
        receipt = compatibility.check_context_compatibility(inputs, policy, operation="compare")
        self.assertEqual(receipt.status, "insufficient_evidence")
        receipt = receipt.model_copy(update={"status": "compatible", "issues": []}, deep=True)
        self.assert_receipt_rejected_before_keys(inputs, receipt, policy)

    def test_legacy_receipt_without_binding_is_rejected(self):
        inputs = fixture()
        raw = self.approved(inputs).model_dump(mode="python")
        raw.pop("binding")
        legacy = ContextCompatibility.model_validate(raw)
        self.assertIsNone(legacy.binding)
        self.assert_receipt_rejected_before_keys(inputs, legacy, missing=True)

    def test_unknown_binding_version_is_rejected_before_keys(self):
        inputs = fixture()
        receipt = self.approved(inputs)
        receipt = receipt.model_copy(update={"binding": receipt.binding.model_copy(update={"version": "2"}, deep=True)}, deep=True)
        self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_binding_policy_version_cannot_be_replaced(self):
        inputs = fixture()
        receipt = changed_receipt(self.approved(inputs), lambda raw:
                                  raw["binding"].update({"policy_version": "2"}))
        self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_binding_embedded_input_digest_cannot_be_replaced(self):
        inputs = fixture()
        receipt = changed_receipt(self.approved(inputs), lambda raw:
                                  raw["binding"]["input_bindings"]["current"].update({"input_digest": "stale-input"}))
        self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_binding_embedded_declaration_digest_cannot_be_replaced(self):
        inputs = fixture()
        receipt = changed_receipt(self.approved(inputs), lambda raw:
                                  raw["binding"]["input_bindings"]["current"]["declarations"][0].update({"content_digest": "stale-claim"}))
        self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_receipt_binding_semantics_digest_cannot_be_replaced(self):
        inputs = fixture()
        receipt = changed_receipt(self.approved(inputs), lambda raw:
                                  raw["binding"].update({"semantics_digest": "stale-semantics"}))
        self.assert_receipt_rejected_before_keys(inputs, receipt)

    def test_binding_digest_cannot_be_replaced_by_declared_policy_string(self):
        inputs, policy = fixture(), typed_policy()
        receipt = self.approved(inputs, policy)
        self.assertNotEqual(receipt.binding.policy_digest, policy.definition_digest)
        receipt = changed_receipt(receipt, lambda raw:
                                  raw["binding"].update({"policy_digest": policy.definition_digest}))
        self.assert_receipt_rejected_before_keys(inputs, receipt, policy)

    def test_reconstructed_equal_content_can_reuse_receipt(self):
        inputs, policy = fixture(), typed_policy()
        receipt = self.approved(inputs, policy)
        reconstructed_inputs = {role: SignalInput.model_validate(value.model_dump(mode="python"))
                                for role, value in inputs.items()}
        reconstructed_policy = type(policy).model_validate(policy.model_dump(mode="python"))
        reconstructed_receipt = ContextCompatibility.model_validate(receipt.model_dump(mode="python"))
        self.assert_state(self.align(reconstructed_inputs, reconstructed_policy, reconstructed_receipt), "aligned")
        fresh = self.approved(reconstructed_inputs, reconstructed_policy)
        self.assertEqual(fresh.binding, receipt.binding)

    def test_binding_canonicalizes_nested_dict_insertion_order(self):
        def reverse_dicts(value):
            if isinstance(value, dict):
                return {key: reverse_dicts(item) for key, item in reversed(list(value.items()))}
            if isinstance(value, list):
                return [reverse_dicts(item) for item in value]
            return value

        inputs, policy = fixture(), typed_policy()
        receipt = self.approved(inputs, policy)
        reconstructed_inputs = {role: SignalInput.model_validate(reverse_dicts(value.model_dump(mode="python")))
                                for role, value in reversed(list(inputs.items()))}
        reconstructed_policy = type(policy).model_validate(reverse_dicts(policy.model_dump(mode="python")))
        fresh = self.approved(reconstructed_inputs, reconstructed_policy)
        self.assertEqual(fresh.binding, receipt.binding)
        self.assert_state(self.align(reconstructed_inputs, reconstructed_policy, receipt), "aligned")

    def test_receipt_generation_and_gate_do_not_mutate_inputs(self):
        inputs, policy = fixture(), typed_policy()
        before = copy.deepcopy((inputs, policy))
        receipt = self.approved(inputs, policy)
        receipt_before = receipt.model_copy(deep=True)
        self.assert_state(self.align(inputs, policy, receipt), "aligned")
        self.assertEqual((inputs, policy), before)
        self.assertEqual(receipt, receipt_before)

    def test_binding_is_deterministic_after_a_b_a(self):
        inputs_a, policy = fixture(), typed_policy()
        first = self.approved(inputs_a, policy)
        inputs_b = fixture(left=("other",), right=("other",))
        second = self.approved(inputs_b, policy)
        self.assertNotEqual(first.binding, second.binding)
        self.assertEqual(self.approved(inputs_a, policy).binding, first.binding)
        self.assert_state(self.align(inputs_a, policy, first), "aligned")


if __name__ == "__main__":
    unittest.main()
