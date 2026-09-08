"""Context qualification from explicit, synthetic captured facts and attestations.

Fixtures do not build, parse or execute SQL. Each declaration is deliberately
issued by a Policy-authorized fixture catalog for one independently captured
Context. No fixture performs key alignment or computes a business formula.
"""

import ast
import builtins
import copy
import inspect
import socket
import time
import unittest
import uuid
from unittest.mock import patch

from app.querying.business_signals import compatibility, numeric
from app.querying.business_signals.models import InputDeclaration, SignalInput
from app.querying.business_signals.policies import (
    ProductContributionPolicy, SalesChangePolicy, TargetAttainmentPolicy,
)
from app.querying.result_understanding.models import BusinessContext


ROLE_TABLES = {
    "actual": "orders_current", "target": "sales_targets",
    "current": "orders_current", "baseline": "orders_history",
    "parts": "orders_current", "total": "orders_current",
}
KINDS = {
    "s1": (TargetAttainmentPolicy, ["actual", "target"], ["attainment_rate"]),
    "s2": (SalesChangePolicy, ["current", "baseline"], ["absolute_change", "change_rate"]),
    "s3": (ProductContributionPolicy, ["parts", "total"], ["contribution_rate"]),
}


def source(role, field):
    return {"database": "askdata_mock", "table": ROLE_TABLES[role], "field": field}


def metric_field(role):
    return "target_amount" if role == "target" else "paid_amount"


def time_field(role):
    return "target_month" if role == "target" else "order_date"


def key_field(kind):
    return "category" if kind == "s3" else "region"


def key_domain(kind):
    return "product-category" if kind == "s3" else "sales-region"


def metric_id(role):
    return "regional_monthly_sales_target" if role == "target" else "actual_paid_sales"


def typed_policy(kind="s2", **changes):
    """Business rules are stated here, never learned from display names."""
    model, roles, outputs = KINDS[kind]
    definition = {
        "policy_id": f"compatibility-{kind}-fixture", "definition_digest": "fixture-policy-v1",
        "supported_contract_versions": {
            "result_contract": ["1"], "business_context": ["1"], "business_signal": ["1"],
        },
        "metric_rules": [{
            "context_role": role, "metric_id": metric_id(role), "mapping_id": f"{role}-paid-map",
            "allowed_sources": [source(role, metric_field(role))], "allowed_aggregations": ["SUM"],
        } for role in roles],
        "relationship_rules": [{
            "relationship_id": "paid-target-basis-v1" if kind == "s1" else "paid-comparison-v1",
            "operation": "compare" if kind == "s2" else "divide",
            "left_role": roles[0], "right_role": roles[1],
            "left_metric_id": metric_id(roles[0]), "right_metric_id": metric_id(roles[1]),
            "metric_relationship": "actual_to_target" if kind == "s1" else "equivalent",
        }],
        "grain_rules": [{
            "context_role": role, "grain": "global_aggregate" if role == "total" else "grouped",
            "grouping_sources": [] if role == "total" else [source(role, key_field(kind))],
            "total_broadcast": "allow_global_total" if role == "total" else "forbid",
        } for role in roles],
        "key_rules": [{
            "domain_id": key_domain(kind), "component_id": key_field(kind), "value_type": "string",
            "sources": [{"context_role": role, "source": source(role, key_field(kind))}
                        for role in roles if role != "total"],
        }],
        "time_rules": {
            "relationship": {"s1": "same_calendar_month", "s2": "adjacent_calendar_months",
                             "s3": "same_bounded_period"}[kind],
            "sources": [{
                "context_role": role, "domain_id": "sales-calendar",
                "allowed_sources": [source(role, time_field(role))],
                "accepted_precision": "month" if role == "target" else "date",
                "accepted_range": "month_equality" if role == "target" else "closed_open_month",
            } for role in roles],
        },
        "filter_rules": {
            "comparison": "role_specific_metric_basis" if kind == "s1" else "mapped_equal",
            "roles": [{"context_role": role, "required_conditions": [] if role == "target" else [{
                "domain_id": "payment-status", "source": source(role, "status"), "operator": "=",
                "value": {"value_type": "string", "value": "已支付"},
            }]} for role in roles],
            "require_metric_basis_declaration": kind == "s1",
        },
        "numeric_rules": {"profile": "decimal_exact_v1", "accepted_encodings": ["native_json", "decimal_text"]},
        "missing_rules": {},
        "duplicate_rules": {"source_uniqueness_required_roles": ["target"] if kind == "s1" else []},
        "completeness_rules": {
            "population": "require_complete_partition_and_total" if kind == "s3" else "require_scope_declaration",
        },
        "declaration_rules": [{
            "context_role": role,
            "required_types": ["unit", "time_domain", "row_selection", "population", "snapshot_revision"]
                              + (["source_key_uniqueness", "metric_basis"] if role == "target" else []),
            "accepted_issuer_kinds": ["fixture_catalog"], "accepted_issuer_refs": ["demo_v1"],
            "accepted_evidence_grades": ["trusted_declaration"],
        } for role in roles],
        "unit_rules": {}, "limitation_rules": {},
        "formula_refs": [{"output_key": output, "formula_id": output, "input_roles": roles.copy()}
                         for output in outputs],
        "snapshot_rules": {"relationship": "same_revision"},
    }
    definition.update(changes)
    return model.model_validate(definition)


def binding(identity):
    return {"source": identity, "label": "display only", "default_aggregation": "sum"}


def predicate(identity, operator, value, value_type="string", scope="WHERE"):
    return {
        "scope": scope, "expression": "opaque expression; never parse",
        "operator": operator, "lineage": [identity], "value": value,
        "value_type": value_type, "value_sql": "opaque literal",
        "schema_bindings": [binding(identity)], "status": "resolved",
    }


def captured_context(kind, role, lower=None, upper=None):
    lower = lower or ("2026-07-01" if role == "baseline" else "2026-08-01")
    upper = upper or ("2026-08-01" if role == "baseline" else "2026-09-01")
    target = role == "target"
    metric_source = source(role, metric_field(role))
    temporal_source = source(role, time_field(role))
    grouping = [] if role == "total" else [source(role, key_field(kind))]
    columns = [] if role == "total" else [{
        "id": "col_k", "ordinal": 0, "name": "display_key", "dtype": "VARCHAR",
        "value_encoding": "native_json", "representation_status": "preserved",
    }]
    semantics = [] if role == "total" else [{
        "column_id": "col_k", "ordinal": 0, "output_name": "display_key",
        "expression": "opaque key", "lineage": grouping, "status": "resolved",
        "schema_bindings": [binding(grouping[0])],
    }]
    columns.append({
        "id": "col_m", "ordinal": len(columns), "name": "sales_amount", "dtype": "DECIMAL(18,2)",
        "value_encoding": "decimal_text", "representation_status": "preserved",
    })
    semantics.append({
        "column_id": "col_m", "ordinal": len(semantics), "output_name": "sales_amount",
        "expression": "opaque amount", "lineage": [metric_source], "aggregation": "SUM",
        "status": "resolved", "schema_bindings": [binding(metric_source)],
    })
    conditions = ([predicate(temporal_source, "=", lower[:7])] if target else [
        predicate(temporal_source, ">=", lower), predicate(temporal_source, "<", upper),
        predicate(source(role, "status"), "=", "已支付"),
    ])
    raw_sources = grouping + [metric_source, temporal_source] + ([] if target else [source(role, "status")])
    return {
        "result_id": f"captured-{kind}-{role}", "result_contract_version": "1",
        "execution": {
            "database": "askdata_mock", "sql": "opaque SQL; neither parse nor execute",
            "success": True, "columns": columns,
            "rows": [["90.00"]] if role == "total" else [["华东", "90.00"]],
            "returned_rows": 1, "total_rows": 1, "truncated": False,
            "completeness": "complete_query_output",
        },
        "column_semantics": semantics,
        "query_bindings": {"status": "resolved", "bindings": [binding(item) for item in raw_sources]},
        "grain": {"status": "resolved", "query_grain": "global_aggregate" if role == "total" else "grouped",
                  "grouping_columns": grouping, "grouping_expressions": [] if role == "total" else ["opaque key"],
                  "business_grain": [] if role == "total" else ["display only"]},
        "filters": {"status": "resolved", "filters": conditions, "where_expression": "opaque AND"},
        "time_constraints": [{
            "source_field": temporal_source, "operator": "=" if target else "AND",
            "lower": lower[:7] if target else lower, "upper": lower[:7] if target else upper,
            "inclusive": {"lower": True, "upper": target}, "scope": "WHERE",
            "expression": "opaque temporal expression", "status": "resolved",
            "precision": "month" if target else "date", "is_empty": False,
            "schema_bindings": [binding(temporal_source)],
        }],
        "understanding_status": "resolved",
    }


def scope_period(context):
    constraint = context.time_constraints[0] if context.time_constraints else None
    if constraint is None or constraint.lower is None or constraint.upper is None:
        return None
    if constraint.precision == "month":
        year, month = map(int, constraint.lower.split("-"))
        lower = f"{year:04d}-{month:02d}-01"
        upper = f"{year + (month == 12):04d}-{month % 12 + 1:02d}-01"
    else:
        lower, upper = constraint.lower, constraint.upper
    return {"domain_id": "sales-calendar", "calendar": "gregorian", "precision": "date",
            "lower": lower, "upper": upper, "lower_inclusive": True, "upper_inclusive": False}


def supplied_input(kind, role, context_data=None):
    context = BusinessContext.model_validate(context_data or captured_context(kind, role))
    metric = next(item for item in context.column_semantics if item.column_id == "col_m")
    metric_sources = [item.model_dump() for item in metric.lineage or [] if item.field is not None]
    if not metric_sources:
        metric_sources = [source(role, metric_field(role))]
    temporal_sources = [source(role, time_field(role))]
    fields = [item.source.model_dump() for item in context.query_bindings.bindings]
    fields = [item for item in fields if item["field"] is not None]
    scope = {
        "source_fields": fields, "period": scope_period(context),
        "population_scope_ref": "fixture-paid-population-v1", "filter_scope_ref": compatibility.filter_scope_digest(context),
        "key_domains": [key_domain(kind)],
        "target_version": "fixture-target-plan-v1" if role == "target" else None,
    }
    claims = {
        "unit": {"source_fields": metric_sources, "unit_id": "CNY", "unit_scale": "1", "display_scale": 2},
        "time_domain": {"source_fields": temporal_sources, "domain_id": "sales-calendar", "calendar": "gregorian",
                        "precision": "month" if role == "target" else "date",
                        "comparison_domain": "iso_month_text" if role == "target" else "iso_date_text"},
        "row_selection": {"mode": "absent"},
        "population": {"population_scope_ref": "fixture-paid-population-v1", "coverage": "complete",
                       "partition_key_domains": [key_domain(kind)] if kind == "s3" else []},
        "snapshot_revision": {"dataset_ref": "fixture-sales-dataset", "revision_ref": "revision-7"},
    }
    if role == "target":
        claims["source_key_uniqueness"] = {
            "source_fields": [source(role, "region"), source(role, "target_month")],
            "key_domains": [key_domain(kind), "sales-calendar"], "uniqueness": "unique",
        }
        claims["metric_basis"] = {
            "metric_id": metric_id(role), "counterpart_metric_id": "actual_paid_sales",
            "basis_id": "paid-target-basis-v1", "status_value": "已支付",
        }
    column_ids = ["col_m"] + ([] if role == "total" else ["col_k"])
    declarations = [InputDeclaration.model_validate({
        "declaration_id": f"{role}-{name}-v1", "declaration_type": name, "result_id": context.result_id,
        "context_digest": compatibility.context_digest(context), "column_ids": column_ids.copy(),
        "issuer_kind": "fixture_catalog", "issuer_ref": "demo_v1", "basis_ref": f"fixture:{role}:{name}",
        "claims": {name: claim}, "evidence_grade": "trusted_declaration", "scope": copy.deepcopy(scope),
    }) for name, claim in claims.items()]
    return SignalInput(context=context, selection={
        "metric_column_id": "col_m", "key_column_ids": {} if role == "total" else {key_field(kind): "col_k"},
    }, declarations=declarations)


def inputs_fixture(kind="s2"):
    return {role: supplied_input(kind, role) for role in KINDS[kind][1]}


def replace_context(inputs, role, mutate, kind="s2"):
    raw = inputs[role].context.model_dump(mode="python")
    mutate(raw)
    inputs[role] = supplied_input(kind, role, raw)


def replace_declaration(inputs, role, name, mutate):
    value = inputs[role]
    declarations = []
    for declaration in value.declarations:
        if declaration.declaration_type == name:
            raw = declaration.model_dump(mode="python")
            mutate(raw)
            declaration = InputDeclaration.model_validate(raw)
        declarations.append(declaration)
    inputs[role] = value.model_copy(update={"declarations": declarations}, deep=True)


def remove_declaration(inputs, role, name):
    value = inputs[role]
    inputs[role] = value.model_copy(update={
        "declarations": [item for item in value.declarations if item.declaration_type != name],
    }, deep=True)


class BusinessSignalCompatibilityTests(unittest.TestCase):
    def check(self, inputs=None, policy=None, operation=None, kind="s2"):
        policy = policy or typed_policy(kind)
        return compatibility.check_context_compatibility(
            inputs if inputs is not None else inputs_fixture(kind), policy,
            operation=operation or ("compare" if kind == "s2" else "divide"),
        )

    def assert_status(self, expected, inputs, policy=None, kind="s2", code=None):
        result = self.check(inputs, policy, kind=kind)
        self.assertEqual(result.status, expected, result.model_dump())
        if expected != "compatible":
            self.assertTrue(result.issues)
            self.assertTrue(all(item.code and item.evidence_paths for item in result.issues))
        if code:
            self.assertTrue(any(code in item.code for item in result.issues), result.model_dump())
        return result

    def test_s1_actual_target_qualified_with_distinct_authorized_metrics(self):
        result = self.check(kind="s1")
        self.assertEqual(result.status, "compatible", result.model_dump())
        self.assertEqual([item.metric_id for item in result.normalized_metric_refs],
                         ["actual_paid_sales", "regional_monthly_sales_target"])

    def test_s2_current_baseline_qualified_for_adjacent_months(self):
        self.assertEqual(self.check().status, "compatible")

    def test_s3_parts_total_qualified_for_identical_period(self):
        self.assertEqual(self.check(kind="s3").status, "compatible")

    def test_alias_cannot_make_order_amount_the_paid_metric(self):
        inputs = inputs_fixture()
        def change(raw):
            metric = raw["column_semantics"][1]
            metric["lineage"] = [source("current", "order_amount")]
            metric["schema_bindings"] = [binding(source("current", "order_amount"))]
        replace_context(inputs, "current", change)
        self.assert_status("incompatible_context", inputs, code="SOURCE")

    def test_actual_avg_does_not_inherit_schema_default_sum(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["column_semantics"][1].update(aggregation="AVG"))
        self.assert_status("incompatible_context", inputs, code="AGGREGATION")

    def test_unknown_business_context_is_insufficient(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw.update(understanding_status="unknown"))
        self.assert_status("insufficient_evidence", inputs, code="UNDERSTANDING")

    def test_unsupported_business_context_remains_unsupported(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw.update(understanding_status="unsupported"))
        self.assert_status("unsupported", inputs)

    def test_partial_output_is_incompatible(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["execution"].update(
            completeness="partial_query_output", truncated=True, total_rows=2))
        self.assert_status("incompatible_context", inputs, code="PARTIAL")

    def test_truncation_is_incompatible_even_without_completeness_label(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["execution"].update(
            completeness=None, truncated=True, total_rows=2))
        self.assert_status("incompatible_context", inputs)

    def test_nonexistent_metric_column_id_is_structural_failure(self):
        inputs = inputs_fixture()
        selection = inputs["current"].selection.model_copy(update={"metric_column_id": "sales_amount"})
        inputs["current"] = inputs["current"].model_copy(update={"selection": selection})
        with self.assertRaises((TypeError, ValueError)):
            self.check(inputs)

    def test_duplicate_output_names_do_not_defeat_explicit_column_ids(self):
        inputs = inputs_fixture()
        def change(raw):
            for column in raw["execution"]["columns"]:
                column["name"] = "same-name"
            for column in raw["column_semantics"]:
                column["output_name"] = "same-name"
        replace_context(inputs, "current", change)
        self.assert_status("compatible", inputs)

    def test_additional_grouping_source_is_not_automatically_collapsed(self):
        inputs = inputs_fixture()
        def change(raw):
            raw["grain"]["grouping_columns"].append(source("current", "category"))
            raw["grain"]["grouping_expressions"].append("category")
        replace_context(inputs, "current", change)
        self.assert_status("incompatible_context", inputs, code="GRAIN")

    def test_unknown_grain_is_not_inferred_from_dimension_binding(self):
        inputs = inputs_fixture()
        def change(raw):
            raw["grain"].update(status="unknown", grouping_columns=None, query_grain=None)
            raw["column_semantics"][0]["schema_bindings"][0]["role"] = "dimension"
        replace_context(inputs, "current", change)
        result = self.assert_status("insufficient_evidence", inputs, code="UNKNOWN_UNDERSTANDING")
        self.assertTrue(any("grain.status" in item.evidence_paths for item in result.issues))

    def test_and_filter_order_does_not_change_compatibility(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["filters"]["filters"].reverse())
        self.assert_status("compatible", inputs)

    def test_missing_status_on_one_side_is_filter_mismatch(self):
        inputs = inputs_fixture()
        replace_context(inputs, "baseline", lambda raw: raw["filters"]["filters"].pop())
        self.assert_status("incompatible_context", inputs, code="FILTER")

    def test_typed_string_and_integer_filters_are_not_equated(self):
        inputs = inputs_fixture()
        policy_raw = typed_policy().model_dump()
        for role_rule in policy_raw["filter_rules"]["roles"]:
            role_rule["required_conditions"][0]["value"] = {"value_type": "string", "value": "1"}
        replace_context(inputs, "current", lambda raw: raw["filters"]["filters"][-1].update(value="1"))
        replace_context(inputs, "baseline", lambda raw: raw["filters"]["filters"][-1].update(value=1, value_type="integer"))
        self.assert_status("incompatible_context", inputs, SalesChangePolicy.model_validate(policy_raw), code="FILTER")

    def test_having_is_not_authorized_by_full_returned_output(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["filters"]["filters"].append(
            predicate(source("current", "paid_amount"), ">", 1, "integer", "HAVING")))
        self.assert_status("incompatible_context", inputs, code="HAVING")

    def test_unsupported_boolean_filter_is_unsupported(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["filters"].update(
            status="unsupported", limitations=["opaque unsupported boolean form"]))
        self.assert_status("unsupported", inputs)

    def test_cross_year_adjacent_months_are_supported(self):
        inputs = {"current": supplied_input("s2", "current", captured_context("s2", "current", "2027-01-01", "2027-02-01")),
                  "baseline": supplied_input("s2", "baseline", captured_context("s2", "baseline", "2026-12-01", "2027-01-01"))}
        self.assert_status("compatible", inputs)

    def test_partial_month_is_incompatible(self):
        inputs = inputs_fixture()
        def change(raw):
            raw["time_constraints"][0]["lower"] = "2026-08-02"
            raw["filters"]["filters"][0]["value"] = "2026-08-02"
        replace_context(inputs, "current", change)
        self.assert_status("incompatible_context", inputs, code="TIME")

    def test_absent_time_does_not_mean_all_history(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw.update(time_constraints=[]))
        self.assert_status("insufficient_evidence", inputs, code="TIME")

    def test_s3_different_ranges_are_incompatible(self):
        inputs = inputs_fixture("s3")
        inputs["total"] = supplied_input("s3", "total", captured_context("s3", "total", "2026-07-01", "2026-08-01"))
        self.assert_status("incompatible_context", inputs, kind="s3", code="TIME")

    def test_missing_unit_does_not_guess_currency(self):
        inputs = inputs_fixture()
        remove_declaration(inputs, "current", "unit")
        self.assert_status("insufficient_evidence", inputs, code="UNIT")

    def test_known_different_units_are_incompatible(self):
        inputs = inputs_fixture()
        replace_declaration(inputs, "current", "unit", lambda raw: raw["claims"]["unit"].update(unit_id="USD"))
        self.assert_status("incompatible_context", inputs, code="UNIT")

    def test_declaration_wrong_result_id_is_incompatible(self):
        inputs = inputs_fixture()
        replace_declaration(inputs, "current", "unit", lambda raw: raw.update(result_id="wrong-result"))
        self.assert_status("incompatible_context", inputs)

    def test_declaration_wrong_digest_is_incompatible(self):
        inputs = inputs_fixture()
        replace_declaration(inputs, "current", "unit", lambda raw: raw.update(context_digest="context-v1:sha256:" + "0" * 64))
        self.assert_status("incompatible_context", inputs, code="DIGEST")

    def test_self_claimed_fixture_catalog_is_not_whitelist_authorization(self):
        inputs = inputs_fixture()
        replace_declaration(inputs, "current", "unit", lambda raw: raw.update(issuer_ref="fake_source"))
        self.assert_status("insufficient_evidence", inputs)

    def test_unknown_declaration_version_returns_unsupported(self):
        inputs = inputs_fixture()
        declarations = inputs["current"].declarations.copy()
        declarations[0] = declarations[0].model_copy(update={"version": "2"})
        inputs["current"] = inputs["current"].model_copy(update={"declarations": declarations})
        self.assert_status("unsupported", inputs, code="VERSION")

    def test_missing_row_selection_declaration_is_insufficient(self):
        inputs = inputs_fixture()
        remove_declaration(inputs, "current", "row_selection")
        self.assert_status("insufficient_evidence", inputs, code="ROW_SELECTION")

    def test_known_limit_is_incompatible(self):
        inputs = inputs_fixture()
        replace_declaration(inputs, "current", "row_selection", lambda raw: raw["claims"]["row_selection"].update(mode="limit", limit=10))
        self.assert_status("incompatible_context", inputs, code="ROW_SELECTION")

    def test_known_top_n_is_incompatible(self):
        inputs = inputs_fixture()
        replace_declaration(inputs, "current", "row_selection", lambda raw: raw["claims"]["row_selection"].update(mode="top_n", limit=10))
        self.assert_status("incompatible_context", inputs, code="ROW_SELECTION")

    def test_unknown_population_coverage_is_insufficient(self):
        inputs = inputs_fixture()
        replace_declaration(inputs, "current", "population", lambda raw: raw["claims"]["population"].update(coverage="unknown"))
        self.assert_status("insufficient_evidence", inputs, code="POPULATION")

    def test_known_incomplete_population_is_incompatible(self):
        inputs = inputs_fixture()
        replace_declaration(inputs, "current", "population", lambda raw: raw["claims"]["population"].update(coverage="incomplete"))
        self.assert_status("incompatible_context", inputs, code="POPULATION")

    def test_missing_revision_is_insufficient(self):
        inputs = inputs_fixture()
        remove_declaration(inputs, "current", "snapshot_revision")
        self.assert_status("insufficient_evidence", inputs, code="REVISION")

    def test_conflicting_revisions_are_incompatible(self):
        inputs = inputs_fixture()
        replace_declaration(inputs, "current", "snapshot_revision", lambda raw: raw["claims"]["snapshot_revision"].update(revision_ref="revision-8"))
        self.assert_status("incompatible_context", inputs, code="REVISION")

    def test_double_cannot_pass_exact_profile(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["execution"]["columns"][1].update(dtype="DOUBLE", value_encoding="native_json"))
        self.assert_status("incompatible_context", inputs)

    def test_explicit_approximate_profile_accepts_double_metadata(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["execution"]["columns"][1].update(dtype="DOUBLE", value_encoding="native_json"))
        policy = typed_policy(numeric_rules={"profile": "reporting_approx_v1", "allow_binary_float": True,
                                            "accepted_encodings": ["native_json", "decimal_text"]})
        with patch.object(numeric, "read_numeric_value", side_effect=AssertionError("no arbitrary row read")):
            self.assert_status("compatible", inputs, policy)

    def test_lossy_representation_is_incompatible(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["execution"]["columns"][1].update(representation_status="lossy"))
        self.assert_status("incompatible_context", inputs)

    def test_unsupported_numeric_codec_is_unsupported(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["execution"]["columns"][1].update(value_encoding="iso_date"))
        self.assert_status("unsupported", inputs)

    def test_unknown_numeric_dtype_is_insufficient(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["execution"]["columns"][1].update(dtype=None))
        self.assert_status("insufficient_evidence", inputs)

    def test_unknown_numeric_representation_is_insufficient(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["execution"]["columns"][1].update(representation_status=None))
        self.assert_status("insufficient_evidence", inputs)

    def test_missing_required_role_is_structural_error(self):
        inputs = inputs_fixture()
        inputs.pop("baseline")
        with self.assertRaises((TypeError, ValueError)):
            self.check(inputs)

    def test_extra_role_is_structural_error(self):
        inputs = inputs_fixture()
        inputs["actual"] = inputs["current"]
        with self.assertRaises((TypeError, ValueError)):
            self.check(inputs)

    def test_wrong_typed_policy_cannot_guess_other_roles(self):
        with self.assertRaises((TypeError, ValueError)):
            self.check(inputs_fixture("s1"), typed_policy("s2"))

    def test_positional_context_list_cannot_guess_roles(self):
        with self.assertRaises((TypeError, ValueError)):
            self.check(list(inputs_fixture().values()))

    def test_non_signal_input_is_structural_error(self):
        inputs = inputs_fixture()
        inputs["current"] = inputs["current"].context
        with self.assertRaises((TypeError, ValueError)):
            self.check(inputs)

    def test_unsupported_operation_is_structural_error(self):
        with self.assertRaises((TypeError, ValueError)):
            self.check(operation="calculate")

    def test_unknown_contract_version_is_unsupported(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw.update(result_contract_version="2"))
        self.assert_status("unsupported", inputs, code="VERSION")

    def test_unknown_business_context_version_is_unsupported(self):
        inputs = inputs_fixture()
        context = inputs["current"].context.model_copy(update={"version": "2"})
        inputs["current"] = inputs["current"].model_copy(update={"context": context})
        self.assert_status("unsupported", inputs, code="VERSION")

    def test_empty_result_identity_is_structural_error(self):
        inputs = inputs_fixture()
        context = inputs["current"].context.model_copy(update={"result_id": ""})
        inputs["current"] = inputs["current"].model_copy(update={"context": context})
        with self.assertRaises((TypeError, ValueError)):
            self.check(inputs)

    def test_same_result_id_with_different_context_is_identity_conflict(self):
        inputs = inputs_fixture()
        replace_context(inputs, "baseline", lambda raw: raw.update(result_id=inputs["current"].context.result_id))
        self.assert_status("incompatible_context", inputs, code="RESULT_ID_CONFLICT")

    def test_distinct_result_ids_are_preserved_in_normalized_output(self):
        inputs = inputs_fixture("s3")
        result = self.check(inputs, kind="s3")
        self.assertEqual(result.status, "compatible")
        self.assertEqual(result.result_ids, {role: item.context.result_id for role, item in inputs.items()})
        self.assertEqual(len(set(result.result_ids.values())), 2)

    def test_failed_execution_never_qualifies(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["execution"].update(success=False, error="captured failure"))
        self.assertNotEqual(self.check(inputs).status, "compatible")

    def test_unknown_rows_are_insufficient(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["execution"].update(rows=None, returned_rows=None, total_rows=None))
        self.assert_status("insufficient_evidence", inputs)

    def test_unknown_required_counts_are_insufficient(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["execution"].update(returned_rows=None, total_rows=None))
        self.assert_status("insufficient_evidence", inputs)

    def test_inconsistent_nested_execution_facts_are_structural_error(self):
        inputs = inputs_fixture()
        inputs["current"].context.execution.returned_rows = 17
        with self.assertRaises((TypeError, ValueError)):
            self.check(inputs)

    def test_nonexistent_key_column_id_is_structural_error(self):
        inputs = inputs_fixture()
        selection = inputs["current"].selection.model_copy(update={"key_column_ids": {"region": "missing-column"}})
        inputs["current"] = inputs["current"].model_copy(update={"selection": selection})
        with self.assertRaises((TypeError, ValueError)):
            self.check(inputs)

    def test_missing_key_component_is_not_qualified(self):
        inputs = inputs_fixture()
        selection = inputs["current"].selection.model_copy(update={"key_column_ids": {}})
        inputs["current"] = inputs["current"].model_copy(update={"selection": selection})
        self.assert_status("incompatible_context", inputs)

    def test_key_source_identity_must_match_authorized_domain(self):
        inputs = inputs_fixture()
        def change(raw):
            raw["column_semantics"][0]["lineage"] = [source("current", "category")]
            raw["column_semantics"][0]["schema_bindings"] = [binding(source("current", "category"))]
        replace_context(inputs, "current", change)
        self.assert_status("incompatible_context", inputs)

    def test_key_dtype_must_support_declared_string_domain(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["execution"]["columns"][0].update(dtype="BIGINT"))
        self.assert_status("incompatible_context", inputs)

    def test_resolved_metric_without_required_schema_binding_is_insufficient(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["column_semantics"][1].update(schema_bindings=[]))
        self.assert_status("insufficient_evidence", inputs)

    def test_relation_level_count_source_is_not_a_sales_amount(self):
        inputs = inputs_fixture()
        def change(raw):
            raw["column_semantics"][1].update(
                lineage=[{"database": "askdata_mock", "table": "orders_current", "field": None}],
                aggregation="COUNT", schema_bindings=[])
        replace_context(inputs, "current", change)
        self.assert_status("incompatible_context", inputs)

    def test_align_does_not_require_equal_metric_semantics(self):
        result = self.check(kind="s1", operation="align")
        self.assertEqual(result.status, "compatible", result.model_dump())

    def test_compare_requires_an_explicit_relationship_authorization(self):
        result = self.check(kind="s1", operation="compare")
        self.assertEqual(result.status, "incompatible_context", result.model_dump())
        self.assertTrue(any("RELATIONSHIP" in item.code for item in result.issues))

    def test_s1_missing_target_metric_basis_is_insufficient(self):
        inputs = inputs_fixture("s1")
        remove_declaration(inputs, "target", "metric_basis")
        self.assert_status("insufficient_evidence", inputs, kind="s1")

    def test_s1_target_output_sum_does_not_prove_source_uniqueness(self):
        inputs = inputs_fixture("s1")
        remove_declaration(inputs, "target", "source_key_uniqueness")
        self.assert_status("insufficient_evidence", inputs, kind="s1")

    def test_s1_known_duplicate_source_targets_are_incompatible(self):
        inputs = inputs_fixture("s1")
        replace_declaration(inputs, "target", "source_key_uniqueness",
                            lambda raw: raw["claims"]["source_key_uniqueness"].update(uniqueness="duplicate"))
        self.assert_status("incompatible_context", inputs, kind="s1")

    def test_different_unit_scale_is_not_automatically_converted(self):
        inputs = inputs_fixture()
        replace_declaration(inputs, "current", "unit", lambda raw: raw["claims"]["unit"].update(unit_scale="10000"))
        self.assert_status("incompatible_context", inputs, code="UNIT")

    def test_declaration_without_selected_metric_column_is_insufficient(self):
        inputs = inputs_fixture()
        replace_declaration(inputs, "current", "unit", lambda raw: raw.update(column_ids=["col_k"]))
        self.assert_status("insufficient_evidence", inputs, code="DECLARATION_COLUMNS_INCOMPLETE")

    def test_declaration_wrong_scope_source_is_incompatible(self):
        inputs = inputs_fixture()
        replace_declaration(inputs, "current", "unit", lambda raw: raw["scope"].update(
            source_fields=[source("current", "order_amount")]))
        self.assert_status("incompatible_context", inputs)

    def test_declaration_wrong_scope_filter_reference_is_incompatible(self):
        inputs = inputs_fixture()
        replace_declaration(inputs, "current", "population", lambda raw: raw["scope"].update(filter_scope_ref="arbitrary-paid-proof"))
        self.assert_status("incompatible_context", inputs)

    def test_captured_timestamps_do_not_replace_snapshot_evidence(self):
        inputs = inputs_fixture()
        for role in inputs:
            replace_context(inputs, role, lambda raw: raw["execution"].update(provenance={"captured_at": "2026-09-01T00:00:00Z"}))
            remove_declaration(inputs, role, "snapshot_revision")
        self.assert_status("insufficient_evidence", inputs, code="REVISION")

    def test_upstream_limitations_remain_insufficient_without_text_interpretation(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw.update(limitations=["only a tiny harmless message"] ))
        self.assert_status("insufficient_evidence", inputs)

    def test_unsupported_has_priority_over_incompatible_and_insufficient(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["filters"].update(status="unsupported"))
        replace_declaration(inputs, "baseline", "unit", lambda raw: raw["claims"]["unit"].update(unit_id="USD"))
        remove_declaration(inputs, "baseline", "row_selection")
        result = self.assert_status("unsupported", inputs)
        self.assertTrue(any("UNIT" in item.code for item in result.issues))
        self.assertTrue(any("ROW_SELECTION" in item.code for item in result.issues))

    def test_incompatible_has_priority_over_insufficient(self):
        inputs = inputs_fixture()
        replace_declaration(inputs, "baseline", "unit", lambda raw: raw["claims"]["unit"].update(unit_id="USD"))
        remove_declaration(inputs, "baseline", "row_selection")
        result = self.assert_status("incompatible_context", inputs)
        self.assertTrue(any("ROW_SELECTION" in item.code for item in result.issues))

    def test_normalized_compatible_output_is_complete_and_deterministic(self):
        inputs = inputs_fixture()
        result = self.check(inputs)
        self.assertEqual(result.status, "compatible", result.model_dump())
        self.assertEqual(result.context_roles, ["current", "baseline"])
        self.assertEqual(result.operation, "compare")
        self.assertEqual(result.key_domains, ["sales-region"])
        self.assertEqual(len(result.periods), 2)
        self.assertEqual(len(result.non_time_filters), 2)
        self.assertEqual(len(result.declarations_used), 10)
        self.assertEqual(set(result.input_digests), {"current", "baseline"})
        self.assertTrue(all(item.match_status == "matched" for item in result.normalized_metric_refs))
        self.assertFalse(result.issues)

    def test_input_dict_order_does_not_assign_or_change_roles(self):
        inputs = inputs_fixture()
        reversed_inputs = {"baseline": inputs["baseline"], "current": inputs["current"]}
        self.assertEqual(self.check(inputs).model_dump(), self.check(reversed_inputs).model_dump())

    def test_a_to_b_to_a_and_deep_input_purity(self):
        inputs = inputs_fixture()
        policy = typed_policy()
        before = copy.deepcopy({"inputs": {role: item.model_dump() for role, item in inputs.items()},
                                "policy": policy.model_dump()})
        first = self.check(inputs, policy).model_dump()
        other = inputs_fixture()
        remove_declaration(other, "current", "unit")
        self.check(other)
        self.assertEqual(first, self.check(inputs, policy).model_dump())
        self.assertEqual(before, {"inputs": {role: item.model_dump() for role, item in inputs.items()},
                                  "policy": policy.model_dump()})

    def test_output_is_detached_from_later_mutation_of_input(self):
        inputs = inputs_fixture()
        result = self.check(inputs)
        before = copy.deepcopy(result.model_dump())
        inputs["current"].context.filters.filters.reverse()
        inputs["current"].declarations[0].scope.key_domains.append("later-mutation")
        self.assertEqual(before, result.model_dump())

    def test_issue_order_is_stable_across_repeat_calls(self):
        inputs = inputs_fixture()
        remove_declaration(inputs, "current", "unit")
        remove_declaration(inputs, "baseline", "population")
        first = self.check(inputs)
        second = self.check(inputs)
        self.assertEqual(first.model_dump(), second.model_dump())
        self.assertTrue(first.issues)

    def test_duplicate_key_rows_are_left_for_alignment(self):
        inputs = inputs_fixture()
        def change(raw):
            raw["execution"].update(rows=[["华东", "90.00"], ["华东", "10.00"]], returned_rows=2, total_rows=2)
        replace_context(inputs, "current", change)
        self.assert_status("compatible", inputs)

    def test_missing_counterpart_region_is_left_for_alignment(self):
        inputs = inputs_fixture()
        replace_context(inputs, "baseline", lambda raw: raw["execution"].update(rows=[["华南", "90.00"]]))
        self.assert_status("compatible", inputs)

    def test_null_or_unmapped_row_key_values_are_not_aligned_here(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["execution"].update(rows=[[None, "90.00"]]))
        self.assert_status("compatible", inputs)

    def test_zero_denominator_does_not_produce_undefined_or_formula_result(self):
        inputs = inputs_fixture()
        replace_context(inputs, "baseline", lambda raw: raw["execution"].update(rows=[["华东", "0.00"]]))
        result = self.assert_status("compatible", inputs)
        self.assertNotIn("computed_value", result.model_dump())
        self.assertNotIn("signal_id", result.model_dump())

    def test_context_digest_binds_content_without_creating_a_signal_id(self):
        context = inputs_fixture()["current"].context
        digest = compatibility.context_digest(context)
        self.assertTrue(digest.startswith("context-v1:sha256:"))
        clone = context.model_copy(deep=True)
        self.assertEqual(digest, compatibility.context_digest(clone))
        clone.execution.rows[0][1] = "91.00"
        self.assertNotEqual(digest, compatibility.context_digest(clone))

    def test_filter_scope_digest_ignores_and_order_and_rendered_expressions(self):
        context = inputs_fixture()["current"].context
        expected = compatibility.filter_scope_digest(context)
        raw = context.model_dump()
        raw["filters"]["filters"].reverse()
        for condition in raw["filters"]["filters"]:
            condition["expression"] = "a wholly unrelated opaque string"
            condition["value_sql"] = "do not parse this"
        self.assertEqual(expected, compatibility.filter_scope_digest(BusinessContext.model_validate(raw)))

    def test_sql_text_is_opaque_to_qualification(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["execution"].update(sql="unparseable prose LIMIT 1 OFFSET 2"))
        self.assert_status("compatible", inputs)

    def test_no_parser_sql_execution_network_clock_or_file_access(self):
        inputs, policy = inputs_fixture(), typed_policy()
        def forbidden(*args, **kwargs):
            raise AssertionError("Compatibility attempted a forbidden side effect")
        with patch.object(builtins, "open", forbidden), patch.object(time, "time", forbidden), \
                patch.object(time, "monotonic", forbidden), patch.object(uuid, "uuid4", forbidden), \
                patch.object(socket, "create_connection", forbidden), \
                patch.object(numeric, "read_numeric_value", forbidden):
            result = self.check(inputs, policy)
        self.assertEqual(result.status, "compatible")

    def test_module_dependencies_and_calls_do_not_include_forbidden_layers(self):
        tree = ast.parse(inspect.getsource(compatibility))
        forbidden = ("sqlglot", "duckdb", "duckdb_engine", "agent", "workflow", "retrieval", "openai",
                     "anthropic", "requests", "httpx", "socket", "time", "database", "builder")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [entry.name for entry in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                self.assertFalse(any(part in forbidden for part in name.lower().split(".")), name)
        denied_calls = {"now", "utcnow", "today", "parse_sql", "parse_one", "execute", "connect", "read_csv", "read_numeric_value"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""
                self.assertNotIn(name, denied_calls)

    def test_empty_declaration_scope_cannot_supply_trusted_evidence(self):
        inputs = inputs_fixture()
        replace_declaration(inputs, "current", "unit", lambda raw: raw.update(scope={}))
        result = self.check(inputs)
        self.assertIn(result.status, ["insufficient_evidence", "incompatible_context"])
        self.assertTrue(result.issues)

    def test_same_declaration_id_with_different_content_is_incompatible(self):
        inputs = inputs_fixture()
        unit = inputs["current"].declarations[0]
        raw = unit.model_dump()
        raw["claims"]["unit"]["unit_id"] = "USD"
        inputs["current"].declarations.append(InputDeclaration.model_validate(raw))
        self.assert_status("incompatible_context", inputs)

    def test_contradictory_unit_declarations_cannot_select_first_one(self):
        inputs = inputs_fixture()
        raw = inputs["current"].declarations[0].model_dump()
        raw["declaration_id"] = "another-current-unit"
        raw["claims"]["unit"]["unit_id"] = "USD"
        inputs["current"].declarations.append(InputDeclaration.model_validate(raw))
        self.assert_status("incompatible_context", inputs)

    def test_s1_source_unique_claim_must_cover_region_and_month(self):
        inputs = inputs_fixture("s1")
        replace_declaration(inputs, "target", "source_key_uniqueness", lambda raw: raw["claims"]["source_key_uniqueness"].update(
            source_fields=[source("target", "target_amount")]))
        self.assert_status("incompatible_context", inputs, kind="s1")

    def test_extra_temporal_predicate_cannot_hide_behind_full_month_constraint(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["filters"]["filters"].append(
            predicate(source("current", "order_date"), "<", "2026-08-15")))
        self.assert_status("incompatible_context", inputs)

    def test_nonempty_where_expression_with_no_structured_predicates_is_not_qualified(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["filters"].update(filters=[]))
        self.assertNotEqual(self.check(inputs).status, "compatible")

    def test_s1_target_version_disagreement_is_incompatible(self):
        inputs = inputs_fixture("s1")
        replace_declaration(inputs, "target", "metric_basis", lambda raw: raw["scope"].update(target_version="another-target-plan"))
        self.assert_status("incompatible_context", inputs, kind="s1")

    def test_same_snapshot_provenance_can_prove_revision_without_revision_declarations(self):
        inputs = inputs_fixture()
        for role in inputs:
            replace_context(inputs, role, lambda raw: raw["execution"].update(provenance={"snapshot_ref": "revision-7"}))
            remove_declaration(inputs, role, "snapshot_revision")
        self.assert_status("compatible", inputs)

    def test_snapshot_provenance_and_declaration_conflict_is_incompatible(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["execution"].update(provenance={"snapshot_ref": "revision-other"}))
        self.assert_status("incompatible_context", inputs)

    def test_explicit_authorized_revision_pair_is_compatible(self):
        inputs = inputs_fixture()
        replace_declaration(inputs, "current", "snapshot_revision", lambda raw: raw["claims"]["snapshot_revision"].update(revision_ref="revision-8"))
        policy = typed_policy(snapshot_rules={
            "relationship": "authorized_revision_pair", "authorized_revision_pairs": [{
                "left_dataset_ref": "fixture-sales-dataset", "left_revision_ref": "revision-8",
                "right_dataset_ref": "fixture-sales-dataset", "right_revision_ref": "revision-7",
            }],
        })
        self.assert_status("compatible", inputs, policy)

    def test_matching_comparison_group_does_not_authorize_revision_pair(self):
        inputs = inputs_fixture()
        for role in inputs:
            replace_declaration(inputs, role, "snapshot_revision", lambda raw: raw["claims"]["snapshot_revision"].update(
                comparison_group_ref="self-declared-pair"))
        policy = typed_policy(snapshot_rules={"relationship": "authorized_revision_pair"})
        self.assert_status("incompatible_context", inputs, policy, code="REVISION_CONFLICT")

    def test_s3_partition_declaration_must_cover_selected_key_domain(self):
        inputs = inputs_fixture("s3")
        replace_declaration(inputs, "parts", "population", lambda raw: raw["claims"]["population"].update(partition_key_domains=[]))
        self.assert_status("insufficient_evidence", inputs, kind="s3")

    def test_s2_divide_cannot_redefine_baseline_as_unrelated_target_metric(self):
        raw = typed_policy().model_dump()
        raw["metric_rules"][1]["metric_id"] = "unrelated_target"
        raw["relationship_rules"][0].update(
            operation="divide", metric_relationship="actual_to_target", right_metric_id="unrelated_target")
        result = self.check(policy=SalesChangePolicy.model_validate(raw), operation="divide")
        self.assertEqual(result.status, "incompatible_context", result.model_dump())
        self.assertTrue(any("RELATIONSHIP" in item.code for item in result.issues))

    def test_s3_divide_cannot_redefine_total_as_unrelated_target_metric(self):
        raw = typed_policy("s3").model_dump()
        raw["metric_rules"][1]["metric_id"] = "unrelated_target"
        raw["relationship_rules"][0].update(metric_relationship="actual_to_target", right_metric_id="unrelated_target")
        result = self.check(policy=ProductContributionPolicy.model_validate(raw), kind="s3")
        self.assertEqual(result.status, "incompatible_context", result.model_dump())
        self.assertTrue(any("RELATIONSHIP" in item.code for item in result.issues))

    def test_join_predicate_is_unsupported_even_when_not_in_excluded_list(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["filters"]["filters"].append(
            predicate(source("current", "status"), "=", "已支付", scope="JOIN ON")))
        self.assert_status("unsupported", inputs)

    def test_qualify_predicate_is_unsupported_even_when_not_in_excluded_list(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["filters"]["filters"].append(
            predicate(source("current", "status"), "=", "已支付", scope="QUALIFY")))
        self.assert_status("unsupported", inputs)

    def test_unknown_columns_are_insufficient_without_inventing_binding_conflicts(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["execution"].update(columns=None))
        self.assert_status("insufficient_evidence", inputs)

    def test_unknown_filter_info_is_not_compared_as_known_absence(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["filters"].update(status="unknown"))
        self.assert_status("insufficient_evidence", inputs)

    def test_unknown_filter_condition_is_not_compared_as_known_absence(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["filters"]["filters"][-1].update(status="unknown"))
        self.assert_status("insufficient_evidence", inputs)

    def test_blank_unit_identity_or_scale_cannot_prove_compatibility(self):
        for name in ("unit_id", "unit_scale"):
            with self.subTest(name=name):
                inputs = inputs_fixture()
                for role in inputs:
                    replace_declaration(inputs, role, "unit", lambda raw: raw["claims"]["unit"].update({name: " \t "}))
                self.assert_status("insufficient_evidence", inputs, code="DECLARATION_CLAIM_UNKNOWN")

    def test_blank_snapshot_provenance_is_missing_revision_evidence(self):
        inputs = inputs_fixture()
        for role in inputs:
            replace_context(inputs, role, lambda raw: raw["execution"].update(provenance={"snapshot_ref": "   "}))
            remove_declaration(inputs, role, "snapshot_revision")
        self.assert_status("insufficient_evidence", inputs, code="REVISION_UNKNOWN")

    def test_blank_snapshot_provenance_does_not_contradict_trusted_revision(self):
        inputs = inputs_fixture()
        replace_context(inputs, "current", lambda raw: raw["execution"].update(provenance={"snapshot_ref": "   "}))
        self.assert_status("compatible", inputs)

    def test_blank_revision_claim_references_are_insufficient(self):
        for name in ("dataset_ref", "revision_ref"):
            with self.subTest(name=name):
                inputs = inputs_fixture()
                for role in inputs:
                    replace_declaration(inputs, role, "snapshot_revision", lambda raw: raw["claims"]["snapshot_revision"].update({name: " "}))
                self.assert_status("insufficient_evidence", inputs, code="DECLARATION_CLAIM_UNKNOWN")

    def test_blank_population_scope_does_not_prove_same_population(self):
        inputs = inputs_fixture()
        for role in inputs:
            for declaration in inputs[role].declarations:
                def change(raw):
                    raw["scope"]["population_scope_ref"] = " "
                    if raw["declaration_type"] == "population":
                        raw["claims"]["population"]["population_scope_ref"] = " "
                replace_declaration(inputs, role, declaration.declaration_type, change)
        self.assert_status("insufficient_evidence", inputs, code="DECLARATION_SCOPE_UNKNOWN")

    def test_blank_target_version_is_not_uniqueness_or_basis_proof(self):
        inputs = inputs_fixture("s1")
        for name in ("metric_basis", "source_key_uniqueness"):
            replace_declaration(inputs, "target", name, lambda raw: raw["scope"].update(target_version=" "))
        self.assert_status("insufficient_evidence", inputs, kind="s1", code="TARGET_VERSION_UNKNOWN")

    def test_blank_declaration_basis_reference_is_insufficient(self):
        inputs = inputs_fixture()
        replace_declaration(inputs, "current", "unit", lambda raw: raw.update(basis_ref=" "))
        self.assert_status("insufficient_evidence", inputs, code="DECLARATION_REFERENCE_UNKNOWN")

    def test_blank_issuer_reference_is_insufficient_even_if_allowlisted(self):
        inputs = inputs_fixture()
        replace_declaration(inputs, "current", "unit", lambda raw: raw.update(issuer_ref=" "))
        raw = typed_policy().model_dump()
        raw["declaration_rules"][0]["accepted_issuer_refs"].append(" ")
        self.assert_status("insufficient_evidence", inputs, SalesChangePolicy.model_validate(raw), code="DECLARATION_REFERENCE_UNKNOWN")

    def test_blank_context_digest_is_unknown_not_a_known_conflict(self):
        inputs = inputs_fixture()
        replace_declaration(inputs, "current", "unit", lambda raw: raw.update(context_digest=" "))
        self.assert_status("insufficient_evidence", inputs, code="DECLARATION_DIGEST_UNKNOWN")

    def test_filter_policy_mapped_equal_forbids_actual_only_status_bridge(self):
        raw = typed_policy("s1").model_dump()
        raw["filter_rules"]["comparison"] = "mapped_equal"
        self.assert_status("incompatible_context", inputs_fixture("s1"), TargetAttainmentPolicy.model_validate(raw), kind="s1", code="FILTER_MISMATCH")

    def test_metric_basis_filter_policy_has_no_implicit_s2_or_s3_bridge(self):
        for kind in ("s2", "s3"):
            with self.subTest(kind=kind):
                raw = typed_policy(kind).model_dump()
                raw["filter_rules"]["comparison"] = "role_specific_metric_basis"
                self.assert_status("unsupported", inputs_fixture(kind), KINDS[kind][0].model_validate(raw), kind=kind, code="UNSUPPORTED_FILTER_POLICY")

    def test_same_filter_domain_cannot_hide_missing_required_physical_predicate(self):
        raw = typed_policy().model_dump()
        extra = copy.deepcopy(raw["filter_rules"]["roles"][0]["required_conditions"][0])
        extra["source"] = source("current", "category")
        raw["filter_rules"]["roles"][0]["required_conditions"].append(extra)
        self.assert_status("incompatible_context", inputs_fixture(), SalesChangePolicy.model_validate(raw), code="FILTER_MISMATCH")


if __name__ == "__main__":
    unittest.main()
