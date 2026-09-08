"""Content identity binding between an Alignment result and its receipt.

V1 canonical JSON sorts object keys, preserves array order and scalar types,
uses ASCII escapes and fixed separators, and rejects nonfinite numbers. The
unkeyed digests detect accidental receipt/result reuse; they are not signatures
or issuer authentication. No Compatibility or Alignment decisions run here.
"""

from __future__ import annotations

import hashlib
import json

from .models import AlignmentReceiptBinding, AlignmentResult, ContextCompatibility


def _digest(domain: str, value: object) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=True,
                         separators=(",", ":"), allow_nan=False)
    return domain + ":sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _binding_for(
    result: AlignmentResult, receipt: ContextCompatibility,
) -> AlignmentReceiptBinding:
    return AlignmentReceiptBinding(
        # Include the Compatibility binding so its complete input identity is
        # carried through without repeating any qualification checks.
        compatibility_digest=_digest(
            "alignment-compatibility-v1", receipt.model_dump(mode="python"),
        ),
        alignment_digest=_digest(
            "alignment-result-v1", result.model_dump(mode="python", exclude={"binding"}),
        ),
    )


def bind_alignment_result(
    result: AlignmentResult, receipt: ContextCompatibility,
) -> AlignmentResult:
    """Attach the receipt identity after the Alignment producer finishes.

    This records the producer's result without changing its status, pairs or
    issues. Consumers only compare the binding; they must not issue a new one.
    """
    return result.model_copy(update={"binding": _binding_for(result, receipt)}, deep=True)


def alignment_binding_matches(
    result: AlignmentResult, receipt: ContextCompatibility,
) -> bool:
    """Compare complete content identity without rerunning either stage."""
    if result.binding is None or result.binding.version != "1":
        return False
    return result.binding == _binding_for(result, receipt)


__all__ = ["bind_alignment_result", "alignment_binding_matches"]
