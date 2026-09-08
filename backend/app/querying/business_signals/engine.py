"""Organize already produced Signals without calculation or acquisition.

All supplied Signals remain in the batch. Display indices select eligible
computed/undefined records; other states remain available for audit. The
engine creates only outer collections and metadata references, and shares
the existing Signal/Evidence objects under their read-only usage contract.
"""

from __future__ import annotations

from .batch import (
    BatchLimitation, SignalBatch, count_statuses, derived_contexts, inspect_signal,
)
from .models import BusinessSignal


_TYPE_ORDER = {
    "monthly_regional_target_attainment": 0,
    "regional_sales_change": 1,
    "product_contribution": 2,
}
_DISPLAYABLE_STATUSES = {"computed", "undefined"}
_MESSAGES = {
    "SIGNAL_STATUS_MISMATCH": "The supplied Signal status disagrees with its formula result statuses.",
    "SIGNAL_EVIDENCE_LINK_INVALID": "The Signal's operand and formula references do not close within its Evidence.",
    "SIGNAL_NOT_DISPLAYABLE": "The Signal is retained for audit; its status is not eligible for display.",
}


class SignalEngine:
    """Stateless V1 batch assembly; no dispatch, scoring or recomputation.

    Stable type order is S1, S2, S3. The caller's order is preserved within
    each type, including repeated Signals. No numerical ranking, deduplication
    or cross-Signal business qualification is implied by that order.
    """

    __slots__ = ()

    def build(self, signals: list[BusinessSignal] | tuple[BusinessSignal, ...]) -> SignalBatch:
        """Retain inputs and expose validated display indices without edits.

        An unordered collection, wrong item type or malformed consumed field
        is a caller contract error. Typed failure states and inconsistent display
        references are retained with a per-Signal batch limitation; they do
        not suppress otherwise eligible Signals. Undefined remains undefined.

        The input collection is not sorted in place. Signal and Evidence
        objects are intentionally shared, not cloned; consumers must continue
        to treat their shallow-frozen nested containers as read-only.
        """
        if type(signals) not in (list, tuple):
            raise TypeError("signals must be an ordered list or tuple of BusinessSignal objects")
        supplied = list(signals)
        inspected = []
        for signal in supplied:
            if not isinstance(signal, BusinessSignal):
                raise TypeError("each item must be a BusinessSignal")
            if type(signal.signal_type) is not str or signal.signal_type not in _TYPE_ORDER:
                raise ValueError("unsupported Signal type")
            codes = inspect_signal(signal)
            # Model instance validation preserves identity. Display validation
            # first checks consumed fields, including unsafe model_copy edits.
            BusinessSignal.model_validate(signal)
            inspected.append((signal, codes))
        inspected.sort(key=lambda entry: _TYPE_ORDER[entry[0].signal_type])
        ordered = [signal for signal, _ in inspected]
        displayable = []
        limitations = []
        for index, (signal, codes) in enumerate(inspected):
            if signal.status not in _DISPLAYABLE_STATUSES:
                codes = [*codes, "SIGNAL_NOT_DISPLAYABLE"]
            if not codes:
                displayable.append(index)
            limitations.extend(BatchLimitation(
                code=code, signal_index=index, message=_MESSAGES[code],
            ) for code in codes)
        return SignalBatch(
            batch_id=None, signals=ordered,
            created_contexts=derived_contexts(ordered),
            displayable_signal_indices=displayable,
            status_counts=count_statuses(ordered), limitations=limitations,
        )


__all__ = ["SignalEngine"]
