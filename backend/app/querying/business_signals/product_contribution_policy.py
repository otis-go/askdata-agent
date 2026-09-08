"""Explicit V1 definitions for category and product paid-sales contribution.

These factories describe supported rules; they do not establish input
eligibility. Database and issuer authority are supplied by the caller, and
global-total broadcast requires explicit permission. Definition fingerprints
bind content deterministically; they are not signatures or authentication.
"""

from __future__ import annotations

import hashlib
import json

from .models import IssuerKind
from .policies import NumericRules, ProductContributionPolicy


_PROFILES = {
    "category_sales_contribution_v1": ("category", "product-category", "string"),
    "product_sales_contribution_v1": ("product_id", "product-id", "integer"),
}


def _require_text(value: str, name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{name} must be a string")
    if not value.strip():
        raise ValueError(f"{name} must be explicitly supplied and nonblank")


def _definition_digest(policy: ProductContributionPolicy) -> str:
    content = policy.model_dump(mode="python", exclude={"definition_digest"})
    canonical = json.dumps(
        content, sort_keys=True, ensure_ascii=True,
        separators=(",", ":"), allow_nan=False,
    )
    return "policy-definition-v1:sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _make_policy(
    policy_id: str,
    *,
    database: str,
    accepted_issuer_kinds: list[IssuerKind],
    accepted_issuer_refs: list[str],
    numeric_rules: NumericRules | None,
    allow_global_total: bool,
) -> ProductContributionPolicy:
    _require_text(database, "database")
    for values, name in (
        (accepted_issuer_kinds, "accepted_issuer_kinds"),
        (accepted_issuer_refs, "accepted_issuer_refs"),
    ):
        if type(values) is not list:
            raise TypeError(f"{name} must be an explicit list")
        if not values:
            raise ValueError(f"{name} cannot be empty")
        for value in values:
            _require_text(value, name)
    if type(allow_global_total) is not bool:
        raise TypeError("allow_global_total must be an explicit boolean")
    if numeric_rules is not None and not isinstance(numeric_rules, NumericRules):
        raise TypeError("numeric_rules must be NumericRules when supplied")
    numeric = (
        NumericRules(profile="decimal_exact_v1", accepted_encodings=["native_json", "decimal_text"])
        if numeric_rules is None else NumericRules.model_validate(numeric_rules.model_dump(mode="python"))
    )
    key_field, key_domain, key_type = _PROFILES[policy_id]
    roles = ["parts", "total"]

    def source(field: str) -> dict[str, str]:
        return {"database": database, "table": "orders_current", "field": field}

    policy = ProductContributionPolicy.model_validate({
        "policy_id": policy_id,
        "version": "1",
        # Model validation expands defaults before content is fingerprinted.
        "definition_digest": "pending-definition-fingerprint",
        "supported_contract_versions": {
            "result_contract": ["1"], "business_context": ["1"], "business_signal": ["1"],
        },
        "metric_rules": [{
            "context_role": role, "metric_id": "actual_paid_sales", "mapping_id": f"{role}-paid-map",
            "allowed_sources": [source("paid_amount")], "allowed_aggregations": ["SUM"],
        } for role in roles],
        "relationship_rules": [{
            "relationship_id": "paid-contribution-v1", "operation": "divide",
            "left_role": "parts", "right_role": "total",
            "left_metric_id": "actual_paid_sales", "right_metric_id": "actual_paid_sales",
            "metric_relationship": "equivalent",
        }],
        "grain_rules": [{
            "context_role": "parts", "grain": "grouped", "grouping_sources": [source(key_field)],
        }, {
            "context_role": "total", "grain": "global_aggregate", "grouping_sources": [],
            "total_broadcast": "allow_global_total" if allow_global_total else "forbid",
        }],
        "key_rules": [{
            "domain_id": key_domain, "component_id": key_field, "value_type": key_type,
            "sources": [{"context_role": "parts", "source": source(key_field)}],
        }],
        "time_rules": {
            "relationship": "same_bounded_period",
            "sources": [{
                "context_role": role, "domain_id": "sales-calendar",
                "allowed_sources": [source("order_date")],
                "accepted_precision": "date", "accepted_range": "bounded_range",
            } for role in roles],
        },
        "filter_rules": {
            "comparison": "mapped_equal",
            "roles": [{
                "context_role": role, "required_conditions": [{
                    "domain_id": "payment-status", "source": source("status"), "operator": "=",
                    "value": {"value_type": "string", "value": "已支付"},
                }],
            } for role in roles],
        },
        "numeric_rules": numeric,
        "missing_rules": {},
        "duplicate_rules": {},
        "completeness_rules": {"population": "require_complete_partition_and_total"},
        "declaration_rules": [{
            "context_role": role,
            "required_types": ["unit", "time_domain", "row_selection", "population", "snapshot_revision"],
            "accepted_issuer_kinds": list(accepted_issuer_kinds),
            "accepted_issuer_refs": list(accepted_issuer_refs),
            "accepted_evidence_grades": ["trusted_declaration"],
        } for role in roles],
        "unit_rules": {},
        "limitation_rules": {},
        "formula_refs": [{
            "output_key": "contribution_rate", "formula_id": "contribution_rate", "input_roles": roles,
        }],
        "snapshot_rules": {"relationship": "same_revision"},
    })
    return policy.model_copy(update={"definition_digest": _definition_digest(policy)}, deep=True)


def category_sales_contribution_v1(
    *,
    database: str,
    accepted_issuer_kinds: list[IssuerKind],
    accepted_issuer_refs: list[str],
    numeric_rules: NumericRules | None = None,
    allow_global_total: bool = False,
) -> ProductContributionPolicy:
    """Define category/string parts and an independent global paid-sales total.

    Both roles use orders_current.paid_amount SUM with status='已支付', the
    same explicit bounded date period, full population coverage and revision.
    Issuer acceptance and database identity have no implicit defaults.

    The default forbids broadcast, so callers must pass allow_global_total=True
    before this definition belongs to the calculator's supported profile.
    NumericRules defaults to exact Decimal input; explicit rules may authorize
    approximate sources. Inputs and returned mutable containers are detached.
    """
    return _make_policy(
        "category_sales_contribution_v1", database=database,
        accepted_issuer_kinds=accepted_issuer_kinds, accepted_issuer_refs=accepted_issuer_refs,
        numeric_rules=numeric_rules, allow_global_total=allow_global_total,
    )


def product_sales_contribution_v1(
    *,
    database: str,
    accepted_issuer_kinds: list[IssuerKind],
    accepted_issuer_refs: list[str],
    numeric_rules: NumericRules | None = None,
    allow_global_total: bool = False,
) -> ProductContributionPolicy:
    """Define product_id/integer parts under the same explicit sales rules.

    Product IDs retain their integer type; this definition does not authorize
    conversion from string IDs, grouping by category too, or inferred mappings.
    As with the category factory, global-total broadcast must be enabled by
    the caller, and no issuer, database, unit or snapshot fact is inferred.
    """
    return _make_policy(
        "product_sales_contribution_v1", database=database,
        accepted_issuer_kinds=accepted_issuer_kinds, accepted_issuer_refs=accepted_issuer_refs,
        numeric_rules=numeric_rules, allow_global_total=allow_global_total,
    )


def _profile_definition(policy: ProductContributionPolicy) -> dict:
    """Retain fixed scope while removing only explicitly configurable fields."""
    content = policy.model_dump(mode="python")
    for name in ("definition_digest", "numeric_rules"):
        content.pop(name)
    for rule in content["declaration_rules"]:
        for name in ("accepted_issuer_kinds", "accepted_issuer_refs"):
            rule.pop(name)
    for rule in content["key_rules"]:
        # Typed identity or explicit maps do not change the fixed source,
        # component, value type or partition domain. Alignment applies them.
        for name in ("normalization", "mapping_id", "mapping_version", "value_mappings"):
            rule.pop(name)
    return content


def supports_product_contribution_v1(policy: ProductContributionPolicy) -> bool:
    """Check only the two supported Policy definitions, never captured inputs.

    Both the fixed ID/version and expanded rule content must agree with one
    approved profile. A freshly issued Compatibility receipt does not enlarge
    that scope. NumericRules, issuer allowlists and typed key mappings remain
    explicit configuration; all other rules remain fixed. The claimed digest
    must match the actual definition, including configurable fields.

    Canonical fingerprints exclude only definition_digest, sort object keys,
    preserve array order and scalar types, and use ASCII escapes with fixed
    separators. No clock, SQL, Context, declaration or receipt is consulted.
    """
    if type(policy) is not ProductContributionPolicy:
        return False
    try:
        captured = ProductContributionPolicy.model_validate(policy.model_dump(mode="python"))
        if captured.policy_id not in _PROFILES or captured.version != "1":
            return False
        if captured.definition_digest != _definition_digest(captured):
            return False
        issuer = captured.declaration_rules[0]
        reference = _make_policy(
            captured.policy_id,
            database=captured.metric_rules[0].allowed_sources[0].database,
            accepted_issuer_kinds=list(issuer.accepted_issuer_kinds),
            accepted_issuer_refs=list(issuer.accepted_issuer_refs),
            numeric_rules=captured.numeric_rules, allow_global_total=True,
        )
    except (TypeError, ValueError):
        return False
    return _profile_definition(captured) == _profile_definition(reference)


__all__ = [
    "category_sales_contribution_v1", "product_sales_contribution_v1",
    "supports_product_contribution_v1",
]
