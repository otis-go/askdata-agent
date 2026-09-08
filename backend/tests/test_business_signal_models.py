"""Signal foundation contracts, using hand-written captured facts only.

These tests do not build a BusinessContext, parse or execute SQL, read Schema,
or calculate a signal. Values in output fixtures are supplied observations.
"""

import ast
import builtins
import copy
import datetime
import json
import time
import unittest
import uuid
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from pydantic import TypeAdapter, ValidationError

from app.querying.business_signals import models
from app.querying.result_contract import ColumnMetadata, ExecutionData
from app.querying.result_understanding.models import (
    BusinessContext,
    ColumnSemantic,
    FilterInfo,
    GrainInfo,
    LineageSource,
    QueryBindingsInfo,
)


def captured_context():
    """Construct the public Phase 2 model without invoking its builder."""
    region = LineageSource(
        database="fixture_db", table="captured_orders", field="region"
    )
    amount = LineageSource(
        database="fixture_db", table="captured_orders", field="paid_amount"
    )
    return BusinessContext(
        result_id="captured-current",
        result_contract_version="1",
        execution=ExecutionData(
            database="fixture_db",
            sql="opaque captured SQL; must never be parsed",
            success=True,
            columns=[
                ColumnMetadata(
                    id="column_0", ordinal=0, name="duplicate_display_name",
                    dtype="VARCHAR", value_encoding="native_json",
                    representation_status="preserved",
                ),
                ColumnMetadata(
                    id="column_1", ordinal=1, name="duplicate_display_name",
                    dtype="DECIMAL(18,2)", value_encoding="decimal_text",
                    representation_status="preserved",
                ),
            ],
            rows=[[" 华北 ", "72.00"]],
            returned_rows=1,
            total_rows=1,
            truncated=False,
            completeness="complete_query_output",
        ),
        column_semantics=[
            ColumnSemantic(
                column_id="column_0", ordinal=0,
                output_name="duplicate_display_name", lineage=[region],
                status="resolved",
            ),
            ColumnSemantic(
                column_id="column_1", ordinal=1,
                output_name="duplicate_display_name", lineage=[amount],
                aggregation="SUM", status="resolved",
            ),
        ],
        query_bindings=QueryBindingsInfo(status="resolved"),
        grain=GrainInfo(
            query_grain="grouped", business_grain=["captured sales region"],
            grouping_expressions=["region"], grouping_columns=[region],
            status="resolved",
        ),
        filters=FilterInfo(status="resolved"),
        time_constraints=[],
        understanding_status="resolved",
    )


def key_component(**changes):
    data = {
        "domain_id": "sales_region", "component_id": "region", "value_type": "string",
        "raw_value": " 华北 ", "normalized_value": "华北",
    }
    data.update(changes)
    return models.BusinessKeyComponent(**data)


def declaration_payload():
    return {
        "version": "1",
        "declaration_id": "fixture-population-declaration",
        "declaration_type": "population",
        "result_id": "captured-current",
        "context_digest": "supplied-context-digest",
        "column_ids": ["column_0", "column_1"],
        "issuer_kind": "fixture_catalog",
        "issuer_ref": "fixture-catalog:v1",
        "basis_ref": "captured-manifest:v1",
        "claims": {
            "population": {
                "population_scope_ref": "paid-sales-fixture",
                "coverage": "complete",
                "partition_key_domains": ["sales_region"],
            }
        },
        "evidence_grade": "trusted_declaration",
        "scope": {
            "population_scope_ref": "paid-sales-fixture",
            "key_domains": ["sales_region"],
        },
    }


def evidence_payload(role="current", presence="present", value="72.00"):
    known_cell = presence in ("present", "sql_null")
    return {
        "evidence_id": f"evidence-{role}",
        "context_role": role,
        "result_id": f"captured-{role}",
        "context_version": "1", "result_contract_version": "1",
        "context_digest": f"supplied-{role}-digest",
        "column_id": "column_1", "ordinal": 1,
        "row_index": 0 if known_cell else None,
        "key_columns": {"sales_region": "column_0"},
        "key_values": [key_component()],
        "source_fields": [LineageSource(
            database="fixture_db", table="captured_orders", field="paid_amount"
        )],
        "metric_semantic": {
            "context_role": role, "metric_id": "actual_paid_sales",
            "match_status": "matched", "mapping_id": "fixture-sales-mapping-v1",
        },
        "aggregation": "SUM",
        "observed_value": {
            "presence": presence, "value": value if presence == "present" else None,
            "unit_id": "fixture_currency", "evidence_id": f"evidence-{role}",
            "source_quality": {"source_fidelity": "exact", "source_kind": "decimal_text"},
        },
        "raw_value": value if presence == "present" else None,
        "dtype": "DECIMAL(18,2)", "value_encoding": "decimal_text",
        "representation_status": "preserved",
        "eligibility": {
            "completeness": "complete_query_output", "truncated": False,
            "returned_rows": 1, "total_rows": 1, "understanding_status": "resolved",
        },
    }


def s2_signal_payload():
    """Provided results only: there is no formula evaluation in this fixture."""
    current = evidence_payload()
    baseline = evidence_payload("baseline", value="0")
    return {
        "version": "1", "signal_id": "supplied-deterministic-signal-id",
        "signal_type": "regional_sales_change", "scope": "business_key",
        "status": "undefined", "policy_id": "fixture-sales-change",
        "policy_version": "1", "policy_digest": "supplied-policy-digest",
        "calculator_version": "1",
        "business_key": {"components": [key_component()]},
        "metric": [current["metric_semantic"], baseline["metric_semantic"]],
        "current_value": current["observed_value"],
        "reference_value": baseline["observed_value"],
        "computed_value": {
            "absolute_change": {
                "status": "computed", "value": "72.00", "unit_id": "fixture_currency",
                "formula_id": "absolute_change", "formula_version": "1",
                "input_evidence_ids": ["evidence-current", "evidence-baseline"],
                "numeric_quality": {"source_fidelity": "exact", "arithmetic_rounding": "exact"},
            },
            "change_rate": {
                "status": "undefined", "value": None, "unit_id": "ratio",
                "formula_id": "change_rate", "formula_version": "1",
                "input_evidence_ids": ["evidence-current", "evidence-baseline"],
                "reason_code": "ZERO_BASELINE",
            },
        },
        "evidence": [current, baseline],
        "limitations": [{
            "code": "ZERO_BASELINE", "stage": "computation", "context_role": "baseline",
            "result_id": "captured-baseline", "severity": "info",
            "evidence_paths": ["evidence.evidence-baseline.observed_value"],
            "message": "Provided fixture marks the rate undefined.",
        }],
    }


def compatibility_payload():
    return {
        "operation": "compare", "context_roles": ["current", "baseline"],
        "result_ids": {"current": "captured-current", "baseline": "captured-baseline"},
        "status": "compatible", "key_domains": ["sales_region"],
        "input_digests": {"current": "supplied-current-digest", "baseline": "supplied-baseline-digest"},
    }


class SignalModelTest(unittest.TestCase):
    def test_signal_status_accepts_exactly_the_five_public_states(self):
        adapter = TypeAdapter(models.SignalStatus)
        for status in (
            "computed", "insufficient_evidence", "incompatible_context", "unsupported", "undefined"
        ):
            with self.subTest(status=status):
                self.assertEqual(adapter.validate_python(status), status)

    def test_unknown_and_boolean_statuses_are_rejected(self):
        adapter = TypeAdapter(models.SignalStatus)
        for status in ("success", "fail", "compatible", "unknown", True, False, 1, None):
            with self.subTest(status=status), self.assertRaises(ValidationError):
                adapter.validate_python(status)

    def test_signal_input_preserves_context_facts_and_explicit_selection(self):
        context = captured_context()
        before = copy.deepcopy(context.model_dump())
        selection = models.SignalSelection(
            metric_column_id="column_1", key_column_ids={"sales_region": "column_0"},
            auxiliary_column_ids={"source_count": "column_2"},
        )
        signal_input = models.SignalInput(context=context, selection=selection)
        self.assertIsInstance(signal_input.context, BusinessContext)
        self.assertEqual(signal_input.context.model_dump(), before)
        self.assertEqual(signal_input.context.result_id, "captured-current")
        self.assertEqual(signal_input.selection.metric_column_id, "column_1")
        self.assertEqual(signal_input.selection.key_column_ids, {"sales_region": "column_0"})
        self.assertEqual(signal_input.declarations, [])
        self.assertEqual(context.model_dump(), before)

    def test_display_names_do_not_select_or_rewrite_column_ids(self):
        context = captured_context()
        explicit = models.SignalInput(
            context=context,
            selection=models.SignalSelection(
                metric_column_id="column_1", key_column_ids={"sales_region": "column_0"}
            ),
        )
        self.assertEqual(explicit.selection.metric_column_id, "column_1")
        unresolved = models.SignalInput(
            context=context,
            selection=models.SignalSelection(
                metric_column_id="duplicate_display_name", key_column_ids={}
            ),
        )
        # Existence is later compatibility work: the foundation never finds an alias.
        self.assertEqual(unresolved.selection.metric_column_id, "duplicate_display_name")
        with self.assertRaises(ValidationError):
            models.SignalSelection(
                metric_column_id="column_1", key_column_ids={}, output_name="duplicate_display_name"
            )

    def test_input_context_is_detached_in_both_directions(self):
        context = captured_context()
        signal_input = models.SignalInput(
            context=context,
            selection=models.SignalSelection(metric_column_id="column_1", key_column_ids={}),
        )
        self.assertIsNot(signal_input.context, context)
        signal_input.context.execution.rows[0][1] = "999.00"
        signal_input.context.column_semantics[0].schema_bindings.append(
            models.SchemaBinding(source=context.column_semantics[0].lineage[0], label="local only")
        )
        signal_input.context.limitations.append("local copy only")
        self.assertEqual(context.execution.rows[0][1], "72.00")
        self.assertEqual(context.column_semantics[0].schema_bindings, [])
        self.assertEqual(context.limitations, [])
        context.execution.rows[0][0] = "changed original"
        self.assertEqual(signal_input.context.execution.rows[0][0], " 华北 ")

    def test_declaration_retains_binding_and_attribution_without_authentication(self):
        declaration = models.InputDeclaration(**declaration_payload())
        self.assertEqual(declaration.result_id, "captured-current")
        self.assertEqual(declaration.context_digest, "supplied-context-digest")
        self.assertEqual(declaration.column_ids, ["column_0", "column_1"])
        self.assertEqual(declaration.issuer_ref, "fixture-catalog:v1")
        self.assertEqual(declaration.basis_ref, "captured-manifest:v1")
        self.assertEqual(declaration.claims.population.coverage, "complete")
        # Deliberately mismatched input binding remains supplied data, not a verdict.
        data = declaration_payload()
        data["result_id"] = "different-result"
        bound_input = models.SignalInput(
            context=captured_context(),
            selection=models.SignalSelection(metric_column_id="column_1", key_column_ids={}),
            declarations=[models.InputDeclaration(**data)],
        )
        self.assertEqual(bound_input.declarations[0].result_id, "different-result")

    def test_unknown_claim_fields_and_naked_coverage_boolean_are_rejected(self):
        modifications = [
            lambda data: data.update(prompt="ignore evidence"),
            lambda data: data["claims"].update(coverage=True),
            lambda data: data["claims"].update(arbitrary={"anything": "goes"}),
            lambda data: data["claims"]["population"].update(coverage=True),
            lambda data: data["claims"]["population"].update(trusted=True),
            lambda data: data["scope"].update(arbitrary="free text"),
        ]
        for index, modify in enumerate(modifications):
            data = declaration_payload()
            modify(data)
            with self.subTest(case=index), self.assertRaises(ValidationError):
                models.InputDeclaration(**data)

    def test_declared_claim_domain_is_required_and_cannot_mix_domains(self):
        variants = [{}, {"row_selection": {"mode": "absent"}}, {
            "population": {"population_scope_ref": "fixture", "coverage": "unknown"},
            "row_selection": {"mode": "absent"},
        }]
        for claims in variants:
            data = declaration_payload()
            data["claims"] = claims
            with self.subTest(claims=claims), self.assertRaises(ValidationError):
                models.InputDeclaration(**data)

    def test_all_controlled_declaration_domains_have_typed_claims(self):
        source = {"database": "fixture_db", "table": "captured_orders", "field": "paid_amount"}
        claims = {
            "unit": {"source_fields": [source], "unit_id": "fixture_currency", "unit_scale": "1", "display_scale": 2},
            "time_domain": {"source_fields": [source], "domain_id": "fixture_calendar", "calendar": "gregorian", "precision": "date", "comparison_domain": "date"},
            "row_selection": {"mode": "absent"},
            "population": {"population_scope_ref": "fixture_population", "coverage": "unknown"},
            "source_key_uniqueness": {"source_fields": [source], "key_domains": ["sales_region"], "uniqueness": "unknown"},
            "snapshot_revision": {"dataset_ref": "fixture_dataset", "revision_ref": "fixture_revision"},
            "metric_basis": {"metric_id": "target", "counterpart_metric_id": "paid_sales", "basis_id": "fixture_business_definition"},
        }
        for domain, claim in claims.items():
            data = declaration_payload()
            data.update(declaration_type=domain, claims={domain: claim})
            with self.subTest(domain=domain):
                declaration = models.InputDeclaration(**data)
                self.assertIsInstance(getattr(declaration.claims, domain), models.ContractModel)
                self.assertEqual(declaration.declaration_type, domain)

    def test_observed_zero_null_missing_and_unknown_are_distinct(self):
        present = models.ObservedValue(presence="present", value="0")
        self.assertEqual((present.presence, present.value), ("present", "0"))
        for presence in ("sql_null", "missing", "unknown_payload", "unknown_metadata"):
            with self.subTest(presence=presence):
                absent = models.ObservedValue(presence=presence)
                self.assertEqual(absent.presence, presence)
                self.assertIsNone(absent.value)
                self.assertNotEqual(absent, present)
                with self.assertRaises(ValidationError):
                    models.ObservedValue(presence=presence, value="0")

    def test_observed_values_are_text_without_numeric_conversion(self):
        value = models.ObservedValue(presence="present", value="00072.000")
        self.assertEqual(value.value, "00072.000")
        for value in (0, 1.5, False, None):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                models.ObservedValue(presence="present", value=value)

    def test_numeric_quality_retains_source_fidelity_and_rounding_separately(self):
        for fidelity in ("exact", "approximate", "unknown"):
            with self.subTest(fidelity=fidelity):
                quality = models.NumericQuality(
                    source_fidelity=fidelity,
                    source_kind="decimal_text" if fidelity == "exact" else "binary_float",
                    arithmetic_rounding="rounded", scale=12,
                )
                self.assertEqual(quality.source_fidelity, fidelity)
                self.assertEqual(quality.arithmetic_rounding, "rounded")
        with self.assertRaises(ValidationError):
            models.NumericQuality(source_fidelity="preserved")
        with self.assertRaises(ValidationError):
            models.NumericQuality(source_fidelity="exact", source_kind="binary_float")

    def test_key_raw_normalized_values_and_component_order_are_retained(self):
        region = key_component()
        month = key_component(
            domain_id="calendar_month", component_id="month", raw_value="2026-08", normalized_value="2026-08"
        )
        key = models.BusinessKey(components=[region, month])
        self.assertEqual([part.component_id for part in key.components], ["region", "month"])
        self.assertEqual((region.raw_value, region.normalized_value), (" 华北 ", "华北"))
        unchanged = key_component(raw_value=" NORTH ", normalized_value=" NORTH ")
        self.assertEqual(unchanged.normalized_value, " NORTH ")

    def test_integer_key_rejects_strings_booleans_and_floats(self):
        good = key_component(value_type="integer", raw_value=1, normalized_value=1)
        self.assertIs(type(good.normalized_value), int)
        for invalid in ("1", True, 1.0):
            for field in ("raw_value", "normalized_value"):
                args = {"value_type": "integer", "raw_value": 1, "normalized_value": 1, field: invalid}
                with self.subTest(field=field, value=invalid), self.assertRaises(ValidationError):
                    key_component(**args)

    def test_key_components_require_ordered_list_and_unique_component_identity(self):
        component = key_component()
        for components in ((component,), {component}, [component, component], []):
            with self.subTest(components=components), self.assertRaises(ValidationError):
                models.BusinessKey(components=components)

    def test_compatibility_status_is_independent_from_signal_status(self):
        for status in ("compatible", "insufficient_evidence", "incompatible_context", "unsupported"):
            data = compatibility_payload()
            data["status"] = status
            with self.subTest(status=status):
                self.assertEqual(models.ContextCompatibility(**data).status, status)
        for status in ("computed", "undefined", "valid", True):
            data = compatibility_payload()
            data["status"] = status
            with self.subTest(status=status), self.assertRaises(ValidationError):
                models.ContextCompatibility(**data)

    def test_issue_keeps_structured_diagnostics_and_message_without_interpretation(self):
        issue = models.Issue(
            code="UNIT_MISSING", stage="compatibility", context_role="current",
            result_id="captured-current", key=models.BusinessKey(components=[key_component()]),
            evidence_paths=["declarations.unit"], severity="error",
            message="A human explanation can be reworded without changing code.",
        )
        self.assertEqual(issue.code, "UNIT_MISSING")
        self.assertEqual(issue.evidence_paths, ["declarations.unit"])
        self.assertEqual(issue.key.components[0].raw_value, " 华北 ")
        with self.assertRaises(ValidationError):
            models.Issue(**{**issue.model_dump(), "valid": False})

    def test_evidence_retains_column_identity_and_original_unknown_metadata(self):
        data = evidence_payload()
        data.update(dtype=None, value_encoding=None, representation_status=None, source_fields=None)
        evidence = models.SignalEvidence(**data)
        self.assertEqual((evidence.column_id, evidence.ordinal, evidence.row_index), ("column_1", 1, 0))
        self.assertIsNone(evidence.dtype)
        self.assertIsNone(evidence.source_fields)
        self.assertEqual(evidence.observed_value.value, "72.00")
        with self.assertRaises(ValidationError):
            models.SignalEvidence(**{**data, "output_name": "paid_amount"})

    def test_evidence_sql_null_has_a_row_but_missing_and_unknown_payload_do_not(self):
        for presence in ("present", "sql_null", "missing", "unknown_payload"):
            with self.subTest(presence=presence):
                data = evidence_payload(presence=presence)
                evidence = models.SignalEvidence(**data)
                self.assertEqual(evidence.row_index, 0 if presence in ("present", "sql_null") else None)
                data["row_index"] = None if evidence.row_index == 0 else 0
                with self.assertRaises(ValidationError):
                    models.SignalEvidence(**data)

    def test_unknown_metadata_can_retain_a_raw_float_without_decoding_it(self):
        data = evidence_payload(presence="unknown_metadata")
        data.update(row_index=0, raw_value=0.30000000000000004, dtype=None, value_encoding=None)
        data["observed_value"]["source_quality"] = {"source_fidelity": "unknown"}
        evidence = models.SignalEvidence(**data)
        self.assertEqual(evidence.row_index, 0)
        self.assertIs(type(evidence.raw_value), float)
        self.assertEqual(evidence.raw_value, 0.30000000000000004)
        self.assertIsNone(evidence.observed_value.value)
        self.assertIsNone(evidence.dtype)
        restored = models.SignalEvidence.model_validate_json(evidence.model_dump_json())
        self.assertEqual(restored.raw_value, evidence.raw_value)
        data.update(row_index=None, raw_value=None)
        self.assertIsNone(models.SignalEvidence(**data).row_index)

    def test_raw_nonnull_value_needs_a_row_and_cannot_claim_sql_null(self):
        for presence in ("sql_null", "missing", "unknown_payload"):
            data = evidence_payload(presence=presence)
            data["raw_value"] = "0"
            with self.subTest(presence=presence), self.assertRaises(ValidationError):
                models.SignalEvidence(**data)

    def test_evidence_column_id_and_ordinal_are_a_pair(self):
        for field in ("column_id", "ordinal"):
            data = evidence_payload()
            data[field] = None
            with self.subTest(field=field), self.assertRaises(ValidationError):
                models.SignalEvidence(**data)

    def test_s2_carries_absolute_change_and_undefined_rate_without_calculating(self):
        signal = models.BusinessSignal(**s2_signal_payload())
        self.assertEqual(signal.status, "undefined")
        self.assertEqual(set(signal.computed_value), {"absolute_change", "change_rate"})
        self.assertEqual(signal.computed_value["absolute_change"].value, "72.00")
        self.assertEqual(signal.computed_value["change_rate"].status, "undefined")
        self.assertIsNone(signal.computed_value["change_rate"].value)
        self.assertEqual(signal.computed_value["change_rate"].reason_code, "ZERO_BASELINE")
        self.assertEqual(signal.current_value.value, "72.00")
        self.assertEqual(signal.reference_value.value, "0")
        self.assertEqual(signal.signal_id, "supplied-deterministic-signal-id")

    def test_output_keys_and_fixed_formula_ids_cannot_be_mixed(self):
        wrong_keys = s2_signal_payload()
        wrong_keys["computed_value"]["contribution_rate"] = wrong_keys["computed_value"].pop("change_rate")
        wrong_formula = s2_signal_payload()
        wrong_formula["computed_value"]["change_rate"]["formula_id"] = "attainment_rate"
        arbitrary_formula = s2_signal_payload()
        arbitrary_formula["computed_value"]["change_rate"]["formula_id"] = "eval(current/baseline)"
        scalar = s2_signal_payload()
        scalar["computed_value"] = "0.72"
        for data in (wrong_keys, wrong_formula, arbitrary_formula, scalar):
            with self.subTest(outputs=data["computed_value"]), self.assertRaises(ValidationError):
                models.BusinessSignal(**data)

    def test_scope_requires_a_real_key_only_for_business_key_results(self):
        data = s2_signal_payload()
        data["business_key"] = None
        with self.assertRaises(ValidationError):
            models.BusinessSignal(**data)
        data["scope"] = "context"
        signal = models.BusinessSignal(**data)
        self.assertIsNone(signal.business_key)
        data["business_key"] = {"components": [key_component()]}
        with self.assertRaises(ValidationError):
            models.BusinessSignal(**data)

    def test_computation_shape_never_turns_noncomputed_result_into_a_number(self):
        for status in ("insufficient_evidence", "incompatible_context", "unsupported", "undefined"):
            with self.subTest(status=status):
                result = models.ComputationResult(
                    status=status, formula_id="change_rate", input_evidence_ids=[]
                )
                self.assertIsNone(result.value)
                with self.assertRaises(ValidationError):
                    models.ComputationResult(
                        status=status, formula_id="change_rate", input_evidence_ids=[], value="0"
                    )
        with self.assertRaises(ValidationError):
            models.ComputationResult(status="computed", formula_id="change_rate", input_evidence_ids=[])

    def test_strict_bool_and_integer_fields_reject_text_coercion(self):
        period = {
            "domain_id": "sales_month", "calendar": "gregorian", "precision": "date",
            "lower": "2026-08-01", "upper": "2026-09-01", "lower_inclusive": True,
            "upper_inclusive": False,
        }
        cases = [
            (models.NormalizedPeriod, {**period, "upper_inclusive": "false"}),
            (models.EvidenceEligibility, {"truncated": "false"}),
            (models.EvidenceEligibility, {"returned_rows": "1"}),
            (models.NumericQuality, {"scale": "2"}),
            (models.NumericQuality, {"scale": True}),
            (models.RowSelectionClaim, {"mode": "limit", "limit": "1"}),
            (models.TypedFilterValue, {"value_type": "boolean", "value": "false"}),
            (models.TypedFilterValue, {"value_type": "integer", "value": "1"}),
        ]
        for model_type, data in cases:
            with self.subTest(model=model_type.__name__, data=data), self.assertRaises(ValidationError):
                model_type(**data)

    def test_nested_phase2_context_does_not_coerce_text_false(self):
        context = captured_context().model_dump()
        context["execution"]["success"] = "false"
        with self.assertRaises(ValidationError):
            models.SignalInput(
                context=context,
                selection=models.SignalSelection(metric_column_id="column_1", key_column_ids={}),
            )

    def test_version_fields_are_exact_supported_string_literals(self):
        cases = [
            (models.InputDeclaration, declaration_payload(), "version"),
            (models.BusinessSignal, s2_signal_payload(), "version"),
            (models.BusinessSignal, s2_signal_payload(), "policy_version"),
            (models.BusinessSignal, s2_signal_payload(), "calculator_version"),
            (models.SignalEvidence, evidence_payload(), "context_version"),
            (models.ComputationResult, s2_signal_payload()["computed_value"]["change_rate"], "formula_version"),
        ]
        for model_type, data, field in cases:
            for invalid in (1, "2", "", None):
                with self.subTest(model=model_type.__name__, field=field, value=invalid), self.assertRaises(ValidationError):
                    model_type(**{**data, field: invalid})
        # Evidence records rejected upstream versions without granting support.
        # Compatibility remains responsible for the supported-version gate.
        self.assertEqual(models.SignalEvidence(**{
            **evidence_payload(), "result_contract_version": "2",
        }).result_contract_version, "2")
        for invalid in (1, "", None):
            with self.subTest(evidence_version=invalid), self.assertRaises(ValidationError):
                models.SignalEvidence(**{**evidence_payload(), "result_contract_version": invalid})

    def test_nested_models_and_fixed_signals_survive_json_round_trip(self):
        selection = models.SignalSelection(metric_column_id="column_1", key_column_ids={"sales_region": "column_0"})
        values = [
            models.SignalInput(context=captured_context(), selection=selection, declarations=[models.InputDeclaration(**declaration_payload())]),
            models.InputDeclaration(**declaration_payload()),
            models.BusinessKey(components=[key_component(), key_component(domain_id="product", component_id="id", value_type="integer", raw_value=1, normalized_value=1)]),
            models.ObservedValue(presence="present", value="0"),
            models.ContextCompatibility(**compatibility_payload()),
            models.SignalEvidence(**evidence_payload()),
            models.BusinessSignal(**s2_signal_payload()),
        ]
        for value in values:
            with self.subTest(model=type(value).__name__):
                encoded = value.model_dump_json()
                decoded = type(value).model_validate_json(encoded)
                self.assertEqual(decoded, value)
                self.assertEqual(decoded.model_dump_json(), encoded)
                self.assertIsInstance(json.loads(encoded), dict)

    def test_json_input_cannot_coerce_integer_key_or_boolean_fields(self):
        key = key_component(value_type="integer", raw_value=1, normalized_value=1).model_dump()
        key["normalized_value"] = "1"
        with self.assertRaises(ValidationError):
            models.BusinessKeyComponent.model_validate_json(json.dumps(key))
        with self.assertRaises(ValidationError):
            models.EvidenceEligibility.model_validate_json('{"truncated":"false"}')

    def test_construction_has_no_external_execution_parsing_or_clock_access(self):
        context = captured_context()
        before = copy.deepcopy(context.model_dump())
        signal_payload = s2_signal_payload()
        declared = declaration_payload()
        original_import = builtins.__import__
        forbidden_imports = {
            "sqlglot", "duckdb", "duckdb_engine", "sql_parser", "builder", "agent",
            "agents", "workflow", "workflows", "llm", "retrieval", "openai", "database",
        }

        def guarded_import(name, *args, **kwargs):
            if forbidden_imports.intersection(name.split(".")):
                raise AssertionError(f"Foundation attempted forbidden import: {name}")
            return original_import(name, *args, **kwargs)

        class ForbiddenDateTime(datetime.datetime):
            @classmethod
            def now(cls, *args, **kwargs):
                raise AssertionError("Foundation read the current time")

            @classmethod
            def utcnow(cls, *args, **kwargs):
                raise AssertionError("Foundation read the current time")

            @classmethod
            def today(cls, *args, **kwargs):
                raise AssertionError("Foundation read the current date")

        with ExitStack() as stack:
            stack.enter_context(patch("builtins.__import__", guarded_import))
            blockers = [
                stack.enter_context(patch("builtins.open", side_effect=AssertionError("Foundation read a file"))),
                stack.enter_context(patch.object(uuid, "uuid4", side_effect=AssertionError("Foundation generated a random ID"))),
            ]
            for name in ("time", "time_ns", "monotonic", "perf_counter"):
                blockers.append(stack.enter_context(patch.object(time, name, side_effect=AssertionError("Foundation read a clock"))))
            stack.enter_context(patch.object(datetime, "datetime", ForbiddenDateTime))
            selection = models.SignalSelection(metric_column_id="column_1", key_column_ids={"sales_region": "column_0"})
            signal_input = models.SignalInput(
                context=context, selection=selection,
                declarations=[models.InputDeclaration(**declared)],
            )
            signal = models.BusinessSignal(**signal_payload)
            compatibility = models.ContextCompatibility(**compatibility_payload())
            self.assertEqual(signal_input.context.model_dump(), before)
            self.assertEqual(signal.computed_value["absolute_change"].value, "72.00")
            self.assertEqual(compatibility.status, "compatible")
            for blocker in blockers:
                blocker.assert_not_called()
        self.assertEqual(context.model_dump(), before)


class SignalDependencyBoundaryTest(unittest.TestCase):
    def test_foundation_modules_do_not_depend_on_execution_or_inference(self):
        forbidden = {
            "agent", "agents", "workflow", "workflows", "duckdb", "duckdb_engine",
            "sqlglot", "sql_parser", "builder", "lineage", "retrieval", "llm",
            "database", "langchain", "langgraph", "openai", "importlib",
        }
        forbidden_calls = {
            "parse_sql", "parse_one", "build_business_context", "execute",
            "execute_sql", "uuid4", "hash", "eval", "exec", "__import__",
            "now", "utcnow", "today", "time", "time_ns",
        }
        for filename in ("models.py", "policies.py"):
            with self.subTest(module=filename):
                source = Path(models.__file__).with_name(filename).read_text(
                    encoding="utf-8"
                )
                tree = ast.parse(source)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        modules = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        modules = [node.module or ""]
                    else:
                        modules = []
                    for imported in modules:
                        self.assertFalse(
                            forbidden.intersection(imported.split(".")), imported
                        )
                    if isinstance(node, ast.Call):
                        called = node.func
                        name = (
                            called.id if isinstance(called, ast.Name)
                            else called.attr if isinstance(called, ast.Attribute)
                            else None
                        )
                        self.assertNotIn(name, forbidden_calls)


if __name__ == "__main__":
    unittest.main()
