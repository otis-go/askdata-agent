"""Policy definition tests: strict configuration, never Context qualification."""

import ast
import copy
import inspect
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.querying.business_signals import policies
from app.querying.business_signals.models import TypedFilterValue
from app.querying.business_signals.policies import (
    BaseSignalPolicy,
    FilterPredicate,
    KeyRule,
    NumericRules,
    ProductContributionPolicy,
    SalesChangePolicy,
    TargetAttainmentPolicy,
)


POLICY_TYPES = (
    ("monthly_regional_target_attainment", TargetAttainmentPolicy, ["actual", "target"], ["attainment_rate"]),
    ("regional_sales_change", SalesChangePolicy, ["current", "baseline"], ["absolute_change", "change_rate"]),
    ("product_contribution", ProductContributionPolicy, ["parts", "total"], ["contribution_rate"]),
)


def source(table, field):
    return {"database": "contract_fixture", "table": table, "field": field}


def policy_definition(signal_type="regional_sales_change"):
    """Explicit synthetic caller rules; these are not production business facts."""
    _, _, roles, outputs = next(item for item in POLICY_TYPES if item[0] == signal_type)
    metrics = ["observed_sales", "planned_sales" if roles[1] == "target" else "observed_sales"]
    key_roles = roles[:1] if roles[1] == "total" else roles
    return {
        "policy_id": "fixture-policy",
        "version": "1",
        "definition_digest": "caller-provided-policy-digest",
        "signal_type": signal_type,
        "required_roles": roles.copy(),
        "supported_contract_versions": {
            "result_contract": ["1"], "business_context": ["1"], "business_signal": ["1"],
        },
        "metric_rules": [
            {
                "context_role": role, "metric_id": metric, "mapping_id": f"{role}-metric-map",
                "allowed_sources": [source(role, "amount")], "allowed_aggregations": ["SUM"],
            }
            for role, metric in zip(roles, metrics)
        ],
        "relationship_rules": [{
            "relationship_id": "fixture-relationship",
            "operation": "compare" if roles[0] == "current" else "divide",
            "left_role": roles[0], "right_role": roles[1],
            "left_metric_id": metrics[0], "right_metric_id": metrics[1],
            "metric_relationship": "actual_to_target" if roles[1] == "target" else "equivalent",
        }],
        "grain_rules": [
            {
                "context_role": role,
                "grain": "global_aggregate" if role == "total" else "grouped",
                "grouping_sources": [] if role == "total" else [source(role, "key")],
                "total_broadcast": "allow_global_total" if role == "total" else "forbid",
            }
            for role in roles
        ],
        "key_rules": [{
            "domain_id": "fixture-region", "component_id": "region", "value_type": "string",
            "sources": [{"context_role": role, "source": source(role, "key")} for role in key_roles],
        }],
        "time_rules": {
            "relationship": "adjacent_calendar_months" if roles[0] == "current" else "same_calendar_month",
            "sources": [
                {
                    "context_role": role, "domain_id": "fixture-calendar",
                    "allowed_sources": [source(role, "period")],
                    "accepted_precision": "month" if role == "target" else "date",
                    "accepted_range": "month_equality" if role == "target" else "closed_open_month",
                }
                for role in roles
            ],
        },
        "filter_rules": {
            "comparison": "role_specific_metric_basis" if roles[1] == "target" else "mapped_equal",
            "roles": [{"context_role": role, "required_conditions": []} for role in roles],
            "require_metric_basis_declaration": roles[1] == "target",
        },
        "numeric_rules": {"profile": "decimal_exact_v1", "accepted_encodings": ["native_json", "decimal_text"]},
        "missing_rules": {},
        "duplicate_rules": {"source_uniqueness_required_roles": ["target"] if roles[1] == "target" else []},
        "completeness_rules": {
            "population": "require_complete_partition_and_total" if roles[1] == "total" else "require_scope_declaration",
        },
        "declaration_rules": [
            {
                "context_role": role,
                "required_types": ["unit", "time_domain", "row_selection", "population", "snapshot_revision"]
                + (["source_key_uniqueness", "metric_basis"] if role == "target" else []),
                "accepted_issuer_kinds": ["fixture_catalog"],
                "accepted_issuer_refs": ["fixture-catalog-v1"],
                "accepted_evidence_grades": ["trusted_declaration"],
            }
            for role in roles
        ],
        "unit_rules": {},
        "limitation_rules": {},
        "formula_refs": [
            {"output_key": output, "formula_id": output, "input_roles": roles.copy()}
            for output in outputs
        ],
        "snapshot_rules": {"relationship": "same_revision"},
    }


class BusinessSignalPolicyTests(unittest.TestCase):
    def test_three_typed_policies_have_fixed_signal_and_role_identity(self):
        for signal_type, model, roles, _ in POLICY_TYPES:
            with self.subTest(signal_type=signal_type):
                definition = policy_definition(signal_type)
                del definition["signal_type"]
                del definition["required_roles"]
                policy = model.model_validate(definition)
                self.assertEqual(policy.signal_type, signal_type)
                self.assertEqual(policy.required_roles, roles)

    def test_wrong_signal_type_cannot_be_passed_to_another_policy(self):
        for source_type, _, _, _ in POLICY_TYPES:
            for target_type, model, _, _ in POLICY_TYPES:
                if target_type == source_type:
                    continue
                with self.subTest(source=source_type, target=target_type), self.assertRaises(ValidationError):
                    model.model_validate(policy_definition(source_type))
        sales = SalesChangePolicy.model_validate(policy_definition())
        with self.assertRaises(ValidationError):
            TargetAttainmentPolicy.model_validate(sales)

    def test_base_policy_rejects_a_mismatched_or_reversed_role_pair(self):
        for roles in (["actual", "target"], ["baseline", "current"], ["current", "current"]):
            definition = policy_definition()
            definition["required_roles"] = roles
            with self.subTest(roles=roles), self.assertRaises(ValidationError):
                BaseSignalPolicy.model_validate(definition)

    def test_role_specific_rule_lists_must_cover_exact_roles(self):
        for group in ("metric_rules", "grain_rules", "declaration_rules"):
            definition = policy_definition()
            definition[group][1]["context_role"] = "current"
            with self.subTest(group=group), self.assertRaises(ValidationError):
                SalesChangePolicy.model_validate(definition)
        for group, child in (("time_rules", "sources"), ("filter_rules", "roles")):
            definition = policy_definition()
            definition[group][child].pop()
            with self.subTest(group=group), self.assertRaises(ValidationError):
                SalesChangePolicy.model_validate(definition)

    def test_all_rule_groups_are_required(self):
        for group in (
            "metric_rules", "relationship_rules", "grain_rules", "key_rules", "time_rules", "filter_rules",
            "numeric_rules", "missing_rules", "duplicate_rules", "completeness_rules", "declaration_rules",
            "unit_rules", "limitation_rules", "formula_refs", "snapshot_rules",
        ):
            definition = policy_definition()
            del definition[group]
            with self.subTest(group=group), self.assertRaises(ValidationError):
                SalesChangePolicy.model_validate(definition)

    def test_policy_and_nested_versions_reject_unknowns_and_numeric_coercion(self):
        for version in ("2", 1, True, ""):
            definition = policy_definition()
            definition["version"] = version
            with self.subTest(version=version), self.assertRaises(ValidationError):
                SalesChangePolicy.model_validate(definition)
        for group in ("result_contract", "business_context", "business_signal"):
            definition = policy_definition()
            definition["supported_contract_versions"][group] = ["999"]
            with self.subTest(group=group), self.assertRaises(ValidationError):
                SalesChangePolicy.model_validate(definition)
        definition = policy_definition()
        definition["formula_refs"][0]["formula_version"] = "2"
        with self.assertRaises(ValidationError):
            SalesChangePolicy.model_validate(definition)

    def test_prompt_sql_code_and_unknown_nested_rules_are_forbidden(self):
        for field in ("prompt", "sql", "code", "callback", "arbitrary_rules"):
            definition = policy_definition()
            definition[field] = "not executable"
            with self.subTest(field=field), self.assertRaises(ValidationError):
                SalesChangePolicy.model_validate(definition)
        for field in ("prompt", "sql", "code", "unknown"):
            definition = policy_definition()
            definition["metric_rules"][0][field] = "not executable"
            with self.subTest(nested=field), self.assertRaises(ValidationError):
                SalesChangePolicy.model_validate(definition)

    def test_policy_rules_cannot_be_supplied_as_current_input_proof(self):
        for group, field, value in (
            ("completeness_rules", "coverage", True),
            ("unit_rules", "units_are_equal", True),
            ("snapshot_rules", "snapshot_ref", "current-snapshot"),
            ("numeric_rules", "computed_value", "100"),
        ):
            definition = policy_definition()
            definition[group][field] = value
            with self.subTest(group=group, field=field), self.assertRaises(ValidationError):
                SalesChangePolicy.model_validate(definition)
        for field in ("result_id", "context_digest", "claims", "coverage"):
            definition = policy_definition()
            definition["declaration_rules"][0][field] = "fact"
            with self.subTest(declaration=field), self.assertRaises(ValidationError):
                SalesChangePolicy.model_validate(definition)

    def test_false_string_does_not_become_false_and_numbers_stay_strict(self):
        for group, field in (
            ("numeric_rules", "allow_binary_float"), ("unit_rules", "require_known_unit"),
            ("completeness_rules", "require_untruncated"), ("time_rules", "require_complete_period"),
        ):
            definition = policy_definition()
            definition[group][field] = "false"
            with self.subTest(group=group), self.assertRaises(ValidationError):
                SalesChangePolicy.model_validate(definition)
        for value in ("12", True, 12.0):
            definition = policy_definition()
            definition["numeric_rules"]["ratio_scale"] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                SalesChangePolicy.model_validate(definition)

    def test_all_three_policies_have_stable_json_and_python_round_trips(self):
        for signal_type, model, _, _ in POLICY_TYPES:
            original = model.model_validate(policy_definition(signal_type))
            with self.subTest(signal_type=signal_type):
                encoded = original.model_dump_json()
                self.assertEqual(model.model_validate_json(encoded).model_dump(), original.model_dump())
                self.assertEqual(model.model_validate(original.model_dump()).model_dump_json(), encoded)

    def test_unknown_enums_are_rejected_through_json_too(self):
        original = SalesChangePolicy.model_validate(policy_definition())
        encoded = original.model_dump_json().replace('"ROUND_HALF_EVEN"', '"ROUND_ANYTHING"')
        with self.assertRaises(ValidationError):
            SalesChangePolicy.model_validate_json(encoded)
        encoded = original.model_dump_json().replace('"allow_binary_float":false', '"allow_binary_float":"false"')
        with self.assertRaises(ValidationError):
            SalesChangePolicy.model_validate_json(encoded)

    def test_construction_copies_caller_containers_and_does_not_normalize_keys(self):
        definition = policy_definition()
        definition["key_rules"][0].update({
            "normalization": "explicit_mapping", "mapping_id": "fixture-map", "mapping_version": "1",
            "value_mappings": [{"raw_value": " North ", "normalized_value": "NORTH"}],
        })
        before = copy.deepcopy(definition)
        policy = SalesChangePolicy.model_validate(definition)
        self.assertEqual(definition, before)
        definition["key_rules"][0]["value_mappings"][0]["normalized_value"] = "changed"
        self.assertEqual(policy.key_rules[0].value_mappings[0].raw_value, " North ")
        self.assertEqual(policy.key_rules[0].value_mappings[0].normalized_value, "NORTH")

    def test_policy_and_nested_models_disallow_reassignment(self):
        policy = SalesChangePolicy.model_validate(policy_definition())
        with self.assertRaises(ValidationError):
            policy.policy_id = "changed"
        with self.assertRaises(ValidationError):
            policy.numeric_rules.ratio_scale = 3
        with self.assertRaises(ValidationError):
            policy.metric_rules[0].mapping_id = "changed"

    def test_role_defaults_are_not_shared_between_instances(self):
        definition = policy_definition()
        del definition["required_roles"]
        first = SalesChangePolicy.model_validate(definition)
        second = SalesChangePolicy.model_validate(definition)
        first.required_roles.append("target")
        self.assertEqual(second.required_roles, ["current", "baseline"])

    def test_formula_refs_are_fixed_outputs_and_explicit_operands(self):
        for changed in (
            [{"output_key": "attainment_rate", "formula_id": "attainment_rate", "input_roles": ["current", "baseline"]}],
            [{"output_key": "absolute_change", "formula_id": "change_rate", "input_roles": ["current", "baseline"]}],
        ):
            definition = policy_definition()
            definition["formula_refs"] = changed
            with self.assertRaises(ValidationError):
                SalesChangePolicy.model_validate(definition)
        definition = policy_definition()
        definition["formula_refs"][0]["input_roles"] = ["baseline", "current"]
        with self.assertRaises(ValidationError):
            SalesChangePolicy.model_validate(definition)

    def test_relationship_metric_refs_must_exist_in_definition(self):
        definition = policy_definition()
        definition["relationship_rules"][0]["right_metric_id"] = "undeclared"
        with self.assertRaises(ValidationError):
            SalesChangePolicy.model_validate(definition)

    def test_global_grain_and_broadcast_are_structurally_distinct(self):
        definition = policy_definition("product_contribution")
        definition["grain_rules"][1]["grouping_sources"] = [source("total", "key")]
        with self.assertRaises(ValidationError):
            ProductContributionPolicy.model_validate(definition)
        definition = policy_definition()
        definition["grain_rules"][0]["total_broadcast"] = "allow_global_total"
        with self.assertRaises(ValidationError):
            SalesChangePolicy.model_validate(definition)

    def test_explicit_integer_maps_never_coerce_strings_or_booleans(self):
        definition = policy_definition()["key_rules"][0]
        definition.update({
            "value_type": "integer", "normalization": "explicit_mapping",
            "mapping_id": "integer-map", "mapping_version": "1",
            "value_mappings": [{"raw_value": 1, "normalized_value": 2}],
        })
        self.assertEqual(KeyRule.model_validate(definition).value_mappings[0].raw_value, 1)
        for value in ("1", True):
            definition["value_mappings"][0]["raw_value"] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                KeyRule.model_validate(definition)

    def test_mapping_needs_versioned_entries_and_unique_raw_keys(self):
        definition = policy_definition()["key_rules"][0]
        definition["normalization"] = "explicit_mapping"
        with self.assertRaises(ValidationError):
            KeyRule.model_validate(definition)
        definition.update({
            "mapping_id": "map", "mapping_version": "1", "value_mappings": [
                {"raw_value": "North", "normalized_value": "N"},
                {"raw_value": "North", "normalized_value": "S"},
            ],
        })
        with self.assertRaises(ValidationError):
            KeyRule.model_validate(definition)

    def test_filter_literals_keep_types_and_predicates_enforce_arity(self):
        for literal in ({"value_type": "boolean", "value": "false"}, {"value_type": "integer", "value": "1"}):
            with self.assertRaises(ValidationError):
                TypedFilterValue.model_validate(literal)
        predicate = {
            "domain_id": "fixture-status", "source": source("current", "status"),
            "operator": "=", "value": {"value_type": "string", "value": "paid"},
        }
        self.assertEqual(FilterPredicate.model_validate(predicate).value.value, "paid")
        for changed in (
            {"value": None}, {"operator": "IN"}, {"operator": "IS NULL"},
            {"operator": "BETWEEN"}, {"upper_bound": {"value_type": "integer", "value": 10}},
        ):
            with self.subTest(changed=changed), self.assertRaises(ValidationError):
                FilterPredicate.model_validate({**predicate, **changed})
        between = FilterPredicate.model_validate({
            **predicate, "operator": "BETWEEN", "value": None,
            "lower_bound": {"value_type": "integer", "value": 1},
            "upper_bound": {"value_type": "integer", "value": 10},
        })
        self.assertEqual(between.lower_bound.value, 1)
        self.assertEqual(between.upper_bound.value, 10)

    def test_v1_working_precision_and_ratio_scale_are_fixed_strict_integers(self):
        for field, values in (("decimal_precision", (1, 18, 79, 81, 80.0, "80", True)),
                              ("ratio_scale", (0, 11, 13, 12.0, "12", True))):
            for value in values:
                definition = policy_definition()["numeric_rules"]
                definition[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    NumericRules.model_validate(definition)

    def test_exact_profile_cannot_silently_authorize_binary_floats(self):
        definition = {"profile": "decimal_exact_v1", "accepted_encodings": ["decimal_text"], "allow_binary_float": True}
        with self.assertRaises(ValidationError):
            NumericRules.model_validate(definition)
        definition.update({
            "profile": "reporting_approx_v1", "accepted_encodings": ["native_json"],
            "reconciliation": "relative_tolerance", "relative_tolerance": "1e-12",
        })
        numeric = NumericRules.model_validate(definition)
        self.assertTrue(numeric.allow_binary_float)
        self.assertEqual(numeric.relative_tolerance, "1e-12")
        self.assertEqual(numeric.ratio_scale, 12)

    def test_configuration_validation_does_not_read_clock_or_files(self):
        definition = policy_definition()
        with (
            patch("builtins.open", side_effect=AssertionError("file access")),
            patch("time.time", side_effect=AssertionError("clock access")),
            patch("uuid.uuid4", side_effect=AssertionError("random identity")),
        ):
            policy = SalesChangePolicy.model_validate(definition)
            self.assertEqual(policy.definition_digest, "caller-provided-policy-digest")

    def test_policy_module_has_only_contract_imports_and_no_execution_dependencies(self):
        tree = ast.parse(inspect.getsource(policies))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append("." * node.level + (node.module or ""))
        self.assertEqual(imports, ["typing", "pydantic", ".models"])
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        forbidden = {"eval", "exec", "parse_sql", "execute", "connect", "uuid4", "now", "time", "hash"}
        for call in calls:
            called = call.func.id if isinstance(call.func, ast.Name) else getattr(call.func, "attr", None)
            self.assertNotIn(called, forbidden)


if __name__ == "__main__":
    unittest.main()
