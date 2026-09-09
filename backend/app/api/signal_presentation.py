"""Small HTTP views of already validated Signals; no business computation."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..querying.business_signals.batch import SignalBatch
from ..querying.business_signals.models import (
    BusinessKey, ComputationResult, ContextRole, EvidenceFormulaRef, FormulaId,
    SignalStatus, SignalType,
)
from ..querying.result_understanding.models import LineageSource


class EvidenceDisplay(BaseModel):
    """Operand location and formula references, without the full Evidence."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    context_role: ContextRole
    result_id: str
    column_id: str | None
    row_index: int | None
    source_fields: list[LineageSource] | None
    business_key: BusinessKey | None
    formula_refs: list[EvidenceFormulaRef]


class BusinessSignalDisplay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_index: int = Field(ge=0)
    signal_type: SignalType
    status: SignalStatus
    business_key: BusinessKey | None
    computed_value: dict[FormulaId, ComputationResult]
    evidence_summary: list[EvidenceDisplay]


def present_business_signals(
    supplied: SignalBatch | dict[str, Any] | None,
) -> list[BusinessSignalDisplay]:
    """Preserve the Engine's display eligibility, order, values and references.

    This projection does not depend on LLM generation or response validation.
    Deep copies keep mutable API containers separate from the captured batch.
    """
    if supplied is None:
        return []
    try:
        wire = supplied.model_dump_json() if isinstance(supplied, SignalBatch) else json.dumps(supplied, allow_nan=False)
        batch = SignalBatch.model_validate_json(wire)
    except (ValueError, TypeError):
        # A presentation adapter must never discard the successful SQL table.
        return []
    return [
        BusinessSignalDisplay(
            signal_index=index,
            signal_type=signal.signal_type,
            status=signal.status,
            business_key=signal.business_key,
            computed_value=signal.computed_value,
            evidence_summary=[
                EvidenceDisplay(
                    evidence_id=evidence.evidence_id,
                    context_role=evidence.context_role,
                    result_id=evidence.result_id,
                    column_id=evidence.column_id,
                    row_index=evidence.row_index,
                    source_fields=evidence.source_fields,
                    business_key=evidence.business_key,
                    formula_refs=evidence.formula_refs,
                )
                for evidence in signal.evidence
            ],
        ).model_copy(deep=True)
        for index in batch.displayable_signal_indices
        for signal in [batch.signals[index]]
    ]
