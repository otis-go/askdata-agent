"""Explicit definition of the V1 monthly regional paid-sales comparison.

This factory supplies rules, not evidence that a Context meets them. Database
identity and accepted issuers come from the caller; no environment, Schema,
clock or business data is inspected. The definition digest is a deterministic
content fingerprint, not a signature or an authentication mechanism.
"""

from __future__ import annotations

import hashlib
import json

from .models import IssuerKind
from .policies import NumericRules, SalesChangePolicy


def _require_text(value: str, name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{name} must be a string")
    if not value.strip():
        raise ValueError(f"{name} must be explicitly supplied and nonblank")


def monthly_sales_change_v1(
    *,
    database: str,
    accepted_issuer_kinds: list[IssuerKind],
    accepted_issuer_refs: list[str],
    numeric_rules: NumericRules | None = None,
) -> SalesChangePolicy:
    """Construct current-versus-baseline rules for complete adjacent months.

    ``current`` is the month immediately after ``baseline``. Both operands are
    SUM(paid_amount) grouped by region with status='已支付': orders_current for
    current and orders_history for baseline, inside the supplied database.
    Units, populations and revisions still require captured declarations.

    The caller must explicitly choose accepted issuer kinds and references;
    this function does not authorize any fixture or production issuer by
    default. An explicitly supplied NumericRules may permit approximate
    sources; omission selects decimal_exact_v1 without float permission.

    Canonical JSON includes all expanded policy defaults, sorts object keys,
    preserves list order and scalar types, uses ASCII escapes/fixed separators,
    and excludes only definition_digest itself. No caller-supplied digest is
    accepted. Returned mutable containers are detached from caller arguments.
    """
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
    if numeric_rules is not None and not isinstance(numeric_rules, NumericRules):
        raise TypeError("numeric_rules must be NumericRules when supplied")
    rules = (
        NumericRules(profile="decimal_exact_v1", accepted_encodings=["native_json", "decimal_text"])
        if numeric_rules is None else NumericRules.model_validate(numeric_rules.model_dump(mode="python"))
    )

    roles = ["current", "baseline"]
    tables = {"current": "orders_current", "baseline": "orders_history"}

    def source(role: str, field: str) -> dict[str, str]:
        return {"database": database, "table": tables[role], "field": field}

    policy = SalesChangePolicy.model_validate({
        "policy_id": "monthly_sales_change_v1",
        "version": "1",
        # Validation expands every default before the final digest is made.
        "definition_digest": "pending-definition-fingerprint",
        "supported_contract_versions": {
            "result_contract": ["1"], "business_context": ["1"], "business_signal": ["1"],
        },
        "metric_rules": [{
            "context_role": role, "metric_id": "actual_paid_sales", "mapping_id": f"{role}-paid-map",
            "allowed_sources": [source(role, "paid_amount")], "allowed_aggregations": ["SUM"],
        } for role in roles],
        "relationship_rules": [{
            "relationship_id": "paid-comparison-v1", "operation": "compare",
            "left_role": "current", "right_role": "baseline",
            "left_metric_id": "actual_paid_sales", "right_metric_id": "actual_paid_sales",
            "metric_relationship": "equivalent",
        }],
        "grain_rules": [{
            "context_role": role, "grain": "grouped", "grouping_sources": [source(role, "region")],
        } for role in roles],
        "key_rules": [{
            "domain_id": "sales-region", "component_id": "region", "value_type": "string",
            "sources": [{"context_role": role, "source": source(role, "region")} for role in roles],
        }],
        "time_rules": {
            "relationship": "adjacent_calendar_months",
            "sources": [{
                "context_role": role, "domain_id": "sales-calendar",
                "allowed_sources": [source(role, "order_date")],
                "accepted_precision": "date", "accepted_range": "closed_open_month",
            } for role in roles],
        },
        "filter_rules": {
            "comparison": "mapped_equal",
            "roles": [{
                "context_role": role, "required_conditions": [{
                    "domain_id": "payment-status", "source": source(role, "status"), "operator": "=",
                    "value": {"value_type": "string", "value": "已支付"},
                }],
            } for role in roles],
        },
        "numeric_rules": rules,
        "missing_rules": {},
        "duplicate_rules": {},
        "completeness_rules": {"population": "require_scope_declaration"},
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
            "output_key": formula_id, "formula_id": formula_id, "input_roles": list(roles),
        } for formula_id in ["absolute_change", "change_rate"]],
        "snapshot_rules": {"relationship": "same_revision"},
    })
    content = policy.model_dump(mode="python", exclude={"definition_digest"})
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    digest = "policy-definition-v1:sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return policy.model_copy(update={"definition_digest": digest}, deep=True)


def _profile_definition(policy: SalesChangePolicy) -> dict:
    """Keep supported semantics while excluding caller-configurable labels."""
    content = policy.model_dump(mode="python")
    for name in ("policy_id", "definition_digest", "numeric_rules"):
        content.pop(name)
    for rule in content["metric_rules"]:
        rule.pop("mapping_id")
    for rule in content["relationship_rules"]:
        rule.pop("relationship_id")
    for rule in content["declaration_rules"]:
        for name in ("accepted_issuer_kinds", "accepted_issuer_refs"):
            rule.pop(name)
    for rule in content["key_rules"]:
        # Key normalization is explicitly typed and belongs to Alignment. Both
        # identity and a supplied region value map retain the same S2 profile.
        for name in ("normalization", "mapping_id", "mapping_version", "value_mappings"):
            rule.pop(name)
    return content


def supports_monthly_sales_change_v1(policy: SalesChangePolicy) -> bool:
    """Whether a rule definition belongs to this calculator's supported scope.

    This checks only Policy content. It neither qualifies a Context nor checks
    a receipt, source observation, declaration issuer or captured time range.
    Equivalent definitions may use another policy ID or reference labels.
    NumericRules and accepted issuers remain caller-configurable, as does an
    explicit mapping within the fixed region business-key domain.

    Broader SalesChangePolicy definitions, such as customer/category grain,
    order_amount metrics, bounded partial periods or a different status basis,
    are not this monthly regional paid-sales calculator's supported profile.
    """
    if type(policy) is not SalesChangePolicy:
        return False
    try:
        captured = SalesChangePolicy.model_validate(policy.model_dump(mode="python"))
        issuer = captured.declaration_rules[0]
        reference = monthly_sales_change_v1(
            database=captured.metric_rules[0].allowed_sources[0].database,
            accepted_issuer_kinds=list(issuer.accepted_issuer_kinds),
            accepted_issuer_refs=list(issuer.accepted_issuer_refs),
            numeric_rules=captured.numeric_rules,
        )
    except (TypeError, ValueError):
        return False
    return _profile_definition(captured) == _profile_definition(reference)


__all__ = ["monthly_sales_change_v1", "supports_monthly_sales_change_v1"]
