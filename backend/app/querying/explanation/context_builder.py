"""Pure field-by-field projection from the existing SignalBatch display view.

No source object is dumped, copied or recursively validated. Only explicitly
named fields below are consumed. Free-form diagnostic text is never read;
unknown codes and upstream strings have scoped audit references instead.
"""

from __future__ import annotations

from typing import get_args

from ..business_signals.batch import SignalBatch
from .models import (
    EvidenceRef, EvidenceSummary, ExplanationContext, FilterSummary, FilterValueSummary,
    FormulaRef, KeyComponentSummary, KeySummary, LimitationRef, ObservationSummary,
    OutputFact, OutputRef, PeriodSummary, QualitySummary, RolePeriodSummary,
    SafeLimitation, SafeLimitationCode, SafeReasonCode, SignalFact, SignalRef,
    SignalView, StatusCounts,
)


_FORMULAS = {
    "monthly_regional_target_attainment": ("attainment_rate",),
    "regional_sales_change": ("absolute_change", "change_rate"),
    "product_contribution": ("contribution_rate",),
}
_STATUS_FIELDS = ("computed", "undefined", "insufficient_evidence", "incompatible_context", "unsupported")
_NOTICE = {
    "computed": "SIGNAL_NOT_DISPLAYABLE", "undefined": "SIGNAL_NOT_DISPLAYABLE",
    "insufficient_evidence": "INSUFFICIENT_EVIDENCE", "incompatible_context": "INCOMPATIBLE_CONTEXT",
    "unsupported": "UNSUPPORTED",
}


def _safe_code(code):
    return code if type(code) is str and code in get_args(SafeLimitationCode) else "UNEXPANDED_LIMITATION"


def _safe_reason(code):
    if code is None:
        return None
    return code if type(code) is str and code in get_args(SafeReasonCode) else "UNKNOWN_REASON"


def _quality(value):
    if value is None:
        return None
    return QualitySummary(
        source_fidelity=value.source_fidelity, source_kind=value.source_kind,
        arithmetic_rounding=value.arithmetic_rounding, scale=value.scale,
    )


def _period(value):
    if value is None:
        return None
    return PeriodSummary(
        domain_id=value.domain_id, calendar=value.calendar, precision=value.precision,
        lower=value.lower, upper=value.upper,
        lower_inclusive=value.lower_inclusive, upper_inclusive=value.upper_inclusive,
    )


def _key(value):
    if value is None:
        return None
    return KeySummary(
        components=tuple(KeyComponentSummary(
            domain_id=item.domain_id, component_id=item.component_id,
            value_type=item.value_type, normalized_value=item.normalized_value,
        ) for item in value.components),
        periods=tuple(RolePeriodSummary(context_role=item.context_role, period=_period(item.period))
                      for item in value.periods),
    )


def _filter_value(value):
    return None if value is None else FilterValueSummary(value_type=value.value_type, value=value.value)


def _filter(value):
    return FilterSummary(
        context_role=value.context_role, scope=value.scope, source_identity=value.source_identity,
        operator=value.operator, value=_filter_value(value.value),
        lower_bound=_filter_value(value.lower_bound), upper_bound=_filter_value(value.upper_bound),
    )


def _observation(value):
    if value is None:
        return None
    return ObservationSummary(
        presence=value.presence, value=value.value, unit_id=value.unit_id,
        numeric_quality=_quality(value.source_quality),
    )


def _unit_scale(evidence):
    # Only this previously accepted scalar is disclosed, never declaration
    # text, source fields, issuer metadata, or a newly inferred unit.
    declaration = evidence.unit_declaration
    if declaration is None or declaration.claims.unit is None:
        return None
    return declaration.claims.unit.unit_scale


def _evidence_summary(item, signal_index, limitation_refs):
    return EvidenceSummary(
        ref=EvidenceRef(signal_index=signal_index, evidence_id=item.evidence_id),
        context_role=item.context_role, result_id=item.result_id, context_digest=item.context_digest,
        context_version=item.context_version, result_contract_version=item.result_contract_version,
        column_id=item.column_id, ordinal=item.ordinal, row_index=item.row_index,
        observed_value=_observation(item.observed_value), numeric_quality=_quality(item.numeric_quality),
        unit_scale=_unit_scale(item),
        formula_refs=tuple(FormulaRef(formula_id=ref.formula_id, formula_version=ref.formula_version)
                           for ref in item.formula_refs),
        business_key=_key(item.business_key), normalized_period=_period(item.normalized_period),
        normalized_filters=tuple(_filter(value) for value in item.normalized_filters),
        aggregation=item.aggregation, alignment_broadcast=item.alignment_broadcast,
        limitation_refs=tuple(limitation_refs),
    )


def build_explanation_context(batch: SignalBatch) -> ExplanationContext:
    """Detach an immutable allowlist without widening Engine display rights.

    The caller supplies the current SignalEngine batch and keeps it read-only
    for this synchronous projection. References are local to that batch slot,
    not globally generated identities or an authentication mechanism.
    """
    if not isinstance(batch, SignalBatch):
        raise TypeError("build_explanation_context requires a SignalBatch")
    if batch.version != "1":
        raise ValueError("unsupported SignalBatch version")
    if type(batch.signals) is not list or type(batch.displayable_signal_indices) is not list:
        raise TypeError("SignalBatch must retain its ordered Signal and display lists")
    indices = tuple(batch.displayable_signal_indices)
    if any(type(index) is not int or index < 0 or index >= len(batch.signals) for index in indices):
        raise ValueError("display indices must be current nonnegative Signal positions")
    if indices != tuple(sorted(set(indices))):
        raise ValueError("display indices must remain unique and ordered")
    visible_indices = set(indices)
    if type(batch.status_counts) is not dict or set(batch.status_counts) != set(_STATUS_FIELDS):
        raise ValueError("SignalBatch must retain all five status counts")
    counts = StatusCounts(
        computed=batch.status_counts["computed"], undefined=batch.status_counts["undefined"],
        insufficient_evidence=batch.status_counts["insufficient_evidence"],
        incompatible_context=batch.status_counts["incompatible_context"], unsupported=batch.status_counts["unsupported"],
    )
    limitations = []
    signal_limits = [[] for _ in batch.signals]
    for index, item in enumerate(batch.limitations):
        ref = LimitationRef(scope="batch", signal_index=item.signal_index, limitation_index=index)
        limitations.append(SafeLimitation(ref=ref, code=_safe_code(item.code)))
        if ref.signal_index is not None:
            if ref.signal_index >= len(signal_limits):
                raise ValueError("a Batch limitation must reference a current Signal")
            signal_limits[ref.signal_index].append(ref)
    views, summaries = [], []
    for index, signal in enumerate(batch.signals):
        if type(signal.signal_type) is not str or signal.signal_type not in _FORMULAS:
            raise ValueError("unsupported Signal type")
        if type(signal.status) is not str or signal.status not in _STATUS_FIELDS:
            raise ValueError("unsupported Signal status")
        refs = signal_limits[index]
        for issue_index, issue in enumerate(signal.limitations):
            ref = LimitationRef(scope="signal", signal_index=index, limitation_index=issue_index)
            refs.append(ref)
            limitations.append(SafeLimitation(ref=ref, code=_safe_code(issue.code)))
        evidence_limits = {}
        for evidence_index, item in enumerate(signal.evidence):
            local_refs = []
            for issue_index, issue in enumerate(item.numeric_issues):
                ref = LimitationRef(scope="evidence_numeric", signal_index=index,
                                    evidence_id=item.evidence_id, evidence_index=evidence_index,
                                    limitation_index=issue_index)
                local_refs.append(ref)
                limitations.append(SafeLimitation(ref=ref, code=_safe_code(issue.code)))
            # The strings are not read, iterated or normalized. Their list
            # positions alone preserve the original audit locations.
            for issue_index in range(len(item.upstream_limitations)):
                ref = LimitationRef(scope="evidence_upstream", signal_index=index,
                                    evidence_id=item.evidence_id, evidence_index=evidence_index,
                                    limitation_index=issue_index)
                local_refs.append(ref)
                limitations.append(SafeLimitation(ref=ref, code="UPSTREAM_LIMITATION_PRESENT"))
            refs.extend(local_refs)
            if index in visible_indices and item.evidence_id in evidence_limits:
                raise ValueError("Evidence identities must remain unique inside each Signal")
            evidence_limits[item.evidence_id] = local_refs
        facts = None
        if index in visible_indices:
            if signal.status not in ("computed", "undefined"):
                raise ValueError("the supplied display view cannot authorize failure facts")
            if type(signal.computed_value) is not dict or set(signal.computed_value) != set(_FORMULAS[signal.signal_type]):
                raise ValueError("a visible Signal must preserve its fixed formula outputs")
            outputs = []
            for name in _FORMULAS[signal.signal_type]:
                output = signal.computed_value[name]
                if output.formula_id != name:
                    raise ValueError("an output must retain its declared formula identity")
                outputs.append(OutputFact(
                    ref=OutputRef(signal_index=index, formula_id=output.formula_id, formula_version=output.formula_version),
                    status=output.status, value=output.value, unit_id=output.unit_id,
                    numeric_quality=_quality(output.numeric_quality), reason_code=_safe_reason(output.reason_code),
                    input_evidence_refs=tuple(EvidenceRef(signal_index=index, evidence_id=identity)
                                              for identity in output.input_evidence_ids),
                ))
            operand_refs = outputs[0].input_evidence_refs
            by_id = {item.evidence_id: item for item in signal.evidence}
            for ref in operand_refs:
                if ref.evidence_id not in by_id:
                    raise ValueError("an operand Evidence reference does not resolve in this Signal")
                summaries.append(_evidence_summary(by_id[ref.evidence_id], index, evidence_limits[ref.evidence_id]))
            facts = SignalFact(
                policy_id=signal.policy_id, policy_version=signal.policy_version,
                policy_digest=signal.policy_digest, calculator_version=signal.calculator_version,
                business_key=_key(signal.business_key), outputs=tuple(outputs), evidence_refs=operand_refs,
            )
        else:
            ref = LimitationRef(scope="presentation", signal_index=index, limitation_index=0)
            refs.append(ref)
            limitations.append(SafeLimitation(ref=ref, code=_NOTICE[signal.status]))
        views.append(SignalView(ref=SignalRef(signal_index=index), signal_type=signal.signal_type,
                                status=signal.status, facts=facts, limitation_refs=tuple(refs)))
    return ExplanationContext(
        batch_id=batch.batch_id, signals=tuple(views), displayable_signal_indices=indices,
        evidence_refs=tuple(summaries), limitations=tuple(limitations), status_counts=counts,
    )


__all__ = ["build_explanation_context"]
