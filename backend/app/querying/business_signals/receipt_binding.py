"""Pure content binding for Compatibility results and their complete inputs.

V1 canonical JSON sorts object keys, preserves array order and native scalar
types, uses ASCII escapes and fixed separators, and rejects nonfinite numbers.
These unkeyed digests prevent accidental stale-receipt reuse; they do not prove
issuer authenticity or prevent someone from deliberately recomputing a binding.
No eligibility rules, parsing, acquisition, row alignment or formulas run here.
"""

from __future__ import annotations

import hashlib
import json

from .models import (
    CompatibilityReceiptBinding, ContextCompatibility, ContextRole,
    DeclarationContentBinding, SignalInput, SignalInputBinding,
)
from .policies import ProductContributionPolicy, SalesChangePolicy, TargetAttainmentPolicy


TypedPolicy = TargetAttainmentPolicy | SalesChangePolicy | ProductContributionPolicy


def _digest(domain: str, value: object) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=True,
                         separators=(",", ":"), allow_nan=False)
    return domain + ":sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _input_binding(supplied: SignalInput) -> SignalInputBinding:
    content = supplied.model_dump(mode="python")
    # Hash every supplied declaration, including unused ones and all claim /
    # scope fields. List position and multiplicity are part of the snapshot.
    declarations = [DeclarationContentBinding(
        declaration_id=item["declaration_id"], declaration_type=item["declaration_type"],
        result_id=item["result_id"], context_digest=item["context_digest"],
        content_digest=_digest("compat-declaration-v1", item),
    ) for item in content["declarations"]]
    return SignalInputBinding(
        result_id=supplied.context.result_id,
        context_digest=_digest("context-v1", content["context"]),
        selection_digest=_digest("compat-selection-v1", content["selection"]),
        declarations=declarations,
        input_digest=_digest("compat-input-v1", content),
    )


def _binding_for(
    receipt: ContextCompatibility, inputs: dict[ContextRole, SignalInput], policy: TypedPolicy,
) -> CompatibilityReceiptBinding:
    return CompatibilityReceiptBinding(
        policy_id=policy.policy_id, policy_version=policy.version,
        definition_digest=policy.definition_digest,
        policy_digest=_digest("compat-policy-v1", policy.model_dump(mode="python")),
        input_bindings={role: _input_binding(inputs[role]) for role in sorted(inputs)},
        # Includes operation, status, issues, identities, complete metric and
        # relationship refs, periods, filters, domains and declarations_used.
        # Only the binding itself is excluded to avoid a recursive digest.
        semantics_digest=_digest("compat-semantics-v1", receipt.model_dump(
            mode="python", exclude={"binding"},
        )),
    )


def bind_receipt(
    receipt: ContextCompatibility, inputs: dict[ContextRole, SignalInput], policy: TypedPolicy,
) -> ContextCompatibility:
    """Bind a checker-produced result to the snapshots it actually checked.

    This helper grants no eligibility: production calls it only after the
    Compatibility checks. It never changes status or any normalized fact.
    """
    return receipt.model_copy(update={"binding": _binding_for(receipt, inputs, policy)}, deep=True)


def receipt_binding_matches(
    receipt: ContextCompatibility, inputs: dict[ContextRole, SignalInput], policy: TypedPolicy,
) -> bool:
    """Compare content bindings only; never rerun Compatibility decisions."""
    if receipt.binding is None or receipt.binding.version != "1":
        return False
    return receipt.binding == _binding_for(receipt, inputs, policy)


__all__ = ["bind_receipt", "receipt_binding_matches"]
