"""Pure assembly of captured operand facts for any Phase 3 Signal.

The caller owns qualification, receipt validation, alignment, numeric reading
and formula execution. This module never reads execution.rows, evaluates a
formula or recomputes an input digest. Compatibility, when supplied, contains
normalized facts already accepted by the caller; it is not judged here.
NumericReadResult does not bind its own cell identity: the caller must supply
the result of its read of the selected operand. Local shape checks cannot
authenticate that origin or replace any upstream gate.
"""

from __future__ import annotations

from typing import Literal

from ..result_understanding.models import BusinessContext
from .models import (
    AlignmentPair, ContextCompatibility, ContextRole, EvidenceEligibility,
    EvidenceFormulaRef, InputDeclaration, NumericQuality, ObservedValue,
    SignalEvidence, SignalSelection,
)
from .numeric import NumericReadResult


def build_signal_evidence(
    *,
    context: BusinessContext,
    selection: SignalSelection,
    context_role: ContextRole,
    evidence_id: str,
    context_digest: str,
    row_index: int | None,
    numeric_result: NumericReadResult | None,
    alignment_pair: AlignmentPair | None,
    alignment_side: Literal["left", "right"] | None,
    formula_refs: list[EvidenceFormulaRef],
    compatibility: ContextCompatibility | None = None,
    unit_declaration: InputDeclaration | None = None,
    alignment_broadcast: bool | None = None,
) -> SignalEvidence:
    """Return detached evidence, without reading a cell or deciding eligibility.

    Pass no pair/side/row for a context-level rejection. A trusted pair supplies
    the side key and missing state; row_index must agree with that side. Only a
    NumericReadResult may supply raw_value or an observed numeric value. Formula
    references describe association, including unsuccessful calculations.

    Contradictory locations or supplied numeric labels raise ValueError, rather
    than silently attaching a reading to another operand. Optional missing
    labels can be filled from the caller's explicit ID and accepted unit fact.

    S3 may explicitly project a matched pair's broadcast flag. None preserves
    the legacy wire shape; neither row count nor grain implies broadcast here.
    The flag describes the pair, so the part keeps its own left-side key and
    the broadcast total retains row zero with no fabricated side key.
    """
    for value, expected, name, optional in (
        (context, BusinessContext, "context", False),
        (selection, SignalSelection, "selection", False),
        (numeric_result, NumericReadResult, "numeric_result", True),
        (alignment_pair, AlignmentPair, "alignment_pair", True),
        (compatibility, ContextCompatibility, "compatibility", True),
        (unit_declaration, InputDeclaration, "unit_declaration", True),
    ):
        if not (optional and value is None) and not isinstance(value, expected):
            raise TypeError(f"{name} must be {expected.__name__}")
    if row_index is not None and (type(row_index) is not int or row_index < 0):
        raise ValueError("row_index must be a nonnegative integer or None")
    if type(formula_refs) is not list or any(not isinstance(ref, EvidenceFormulaRef) for ref in formula_refs):
        raise TypeError("formula_refs must contain explicit EvidenceFormulaRef objects")
    if alignment_broadcast is not None and type(alignment_broadcast) is not bool:
        raise TypeError("alignment_broadcast must be a boolean or None")
    # Compare already supplied identity labels only: no digest recomputation,
    # receipt qualification, metric rules, or unit compatibility checks.
    if compatibility is not None:
        if compatibility.result_ids.get(context_role) != context.result_id:
            raise ValueError("Compatibility facts reference a different operand result")
        if (context_role in compatibility.input_digests
                and compatibility.input_digests[context_role] != context_digest):
            raise ValueError("Compatibility facts reference a different context digest")

    side_key = None
    missing = False
    if alignment_pair is None:
        if alignment_side is not None or row_index is not None:
            raise ValueError("a context-level operand cannot claim an aligned position")
    else:
        if alignment_side not in ("left", "right"):
            raise ValueError("an alignment pair requires an explicit left or right side")
        expected_row = getattr(alignment_pair, f"{alignment_side}_row_index")
        if row_index != expected_row:
            raise ValueError("row_index does not match the supplied alignment side")
        missing = alignment_pair.status == f"missing_{alignment_side}"
        side_key = None if missing else getattr(alignment_pair, f"{alignment_side}_key")
    if missing and numeric_result is not None:
        raise ValueError("a missing operand cannot have a numeric reading")
    if alignment_broadcast is not None:
        if (context_role not in ("parts", "total") or alignment_pair is None
                or alignment_pair.status != "matched"):
            raise ValueError("an explicit broadcast fact requires a matched S3 pair")
        expected_side = "left" if context_role == "parts" else "right"
        if alignment_side != expected_side or alignment_broadcast != alignment_pair.broadcast:
            raise ValueError("broadcast role, side and flag must match the supplied pair")
        if alignment_broadcast and (
            alignment_pair.right_row_index != 0 or alignment_pair.right_key is not None
            or alignment_pair.left_key is None
        ):
            raise ValueError("a broadcast pair requires its part key and an unkeyed total at row zero")

    unit_id = None
    if unit_declaration is not None:
        if unit_declaration.declaration_type != "unit" or unit_declaration.claims.unit is None:
            raise ValueError("unit_declaration must record an existing unit claim")
        if (unit_declaration.result_id != context.result_id
                or unit_declaration.context_digest != context_digest
                or selection.metric_column_id not in unit_declaration.column_ids):
            raise ValueError("unit declaration labels do not identify the selected operand")
        unit_id = unit_declaration.claims.unit.unit_id

    if numeric_result is None:
        observed = ObservedValue(presence="missing" if missing else "not_read",
                                 unit_id=unit_id, evidence_id=evidence_id)
        quality = observed.source_quality
    else:
        quality = numeric_result.numeric_quality
        observed = numeric_result.observed_value
        if observed is None:
            observed = ObservedValue(presence="rejected", unit_id=unit_id,
                                     evidence_id=evidence_id, source_quality=quality)
        else:
            if observed.evidence_id is not None and observed.evidence_id != evidence_id:
                raise ValueError("the numeric observation references a different evidence_id")
            if unit_id is not None and observed.unit_id is not None and observed.unit_id != unit_id:
                raise ValueError("the numeric observation contradicts the supplied unit label")
            observed = observed.model_copy(update={
                "evidence_id": evidence_id,
                "unit_id": observed.unit_id if observed.unit_id is not None else unit_id,
            }, deep=True)

    execution = context.execution
    columns = [column for column in execution.columns or [] if column.id == selection.metric_column_id]
    column = columns[0] if len(columns) == 1 else None
    semantics = [semantic for semantic in context.column_semantics
                 if semantic.column_id == selection.metric_column_id]
    semantic = semantics[0] if len(semantics) == 1 else None
    if column is None or observed.presence in ("missing", "unknown_payload"):
        row_index = None

    metric = next((ref for ref in compatibility.normalized_metric_refs
                   if ref.context_role == context_role), None) if compatibility is not None else None
    period = next((ref.period for ref in compatibility.periods
                   if ref.context_role == context_role), None) if compatibility is not None else None
    declarations = [ref for ref in compatibility.declarations_used
                    if ref.result_id == context.result_id
                    and ref.context_digest == context_digest] if compatibility is not None else []
    limitations = [*context.limitations, *context.query_bindings.limitations,
                   *context.grain.limitations, *context.filters.limitations]
    if semantic is not None and semantic.reason is not None:
        limitations.append(semantic.reason)
    limitations.extend(item for condition in [*context.filters.filters, *context.filters.excluded_scopes]
                       for item in condition.limitations)
    limitations.extend(item for constraint in context.time_constraints for item in constraint.limitations)

    return SignalEvidence(
        evidence_id=evidence_id, context_role=context_role, result_id=context.result_id,
        context_version=context.version, result_contract_version=context.result_contract_version,
        context_digest=context_digest,
        column_id=column.id if column else None, ordinal=column.ordinal if column else None,
        row_index=row_index, key_columns=selection.key_column_ids,
        key_values=side_key.components if side_key else [], business_key=side_key,
        alignment_status=alignment_pair.status if alignment_pair is not None else None,
        alignment_broadcast=alignment_broadcast,
        source_fields=semantic.lineage if semantic else None, metric_semantic=metric,
        schema_metadata=semantic.schema_bindings if semantic else [],
        aggregation=semantic.aggregation if semantic else None,
        grain=context.grain, time=context.time_constraints, normalized_period=period,
        filters=context.filters,
        normalized_filters=[item for item in compatibility.non_time_filters
                            if item.context_role == context_role] if compatibility is not None else [],
        observed_value=observed, numeric_quality=quality,
        numeric_issues=list(numeric_result.issues) if numeric_result is not None else [],
        formula_refs=formula_refs,
        raw_value=numeric_result.raw_value if numeric_result is not None and row_index is not None else None,
        dtype=column.dtype if column else None,
        value_encoding=column.value_encoding if column else None,
        representation_status=column.representation_status if column else None,
        eligibility=EvidenceEligibility(
            completeness=execution.completeness, truncated=execution.truncated,
            returned_rows=execution.returned_rows, total_rows=execution.total_rows,
            understanding_status=context.understanding_status, declarations=declarations,
        ), unit_declaration=unit_declaration, provenance=execution.provenance,
        upstream_limitations=limitations,
    ).model_copy(deep=True)


__all__ = ["build_signal_evidence"]
