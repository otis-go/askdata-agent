"""Read-only aggregation contracts for already produced BusinessSignals.

Signals and their nested Evidence are retained by reference. Only outer
containers and small context identity references are created here; neither
Signal nor Evidence is serialized, rebuilt or copied for validation. As with
the existing contracts, freezing is shallow: callers must treat nested
containers as read-only after handing them to a batch.

Validation concerns status, display indexes and local references only. It
does not parse numbers, evaluate formulas or rejudge business eligibility.
"""

from __future__ import annotations

from typing import Self, get_args

from pydantic import Field, model_validator

from .models import (
    BusinessSignal, ComputationResult, ContextRole, ContractModel, ContractVersion, EvidenceFormulaRef, FormulaId,
    NonEmptyStr, ObservedValue, Presence, SignalEvidence, SignalStatus,
)


_STATUSES = get_args(SignalStatus)
_STATUS_PRIORITY = {
    "computed": 0,
    "undefined": 1,
    "insufficient_evidence": 2,
    "incompatible_context": 3,
    "unsupported": 4,
}
_SIGNAL_SHAPES = {
    "monthly_regional_target_attainment": (("attainment_rate",), ("actual", "target")),
    "regional_sales_change": (("absolute_change", "change_rate"), ("current", "baseline")),
    "product_contribution": (("contribution_rate",), ("parts", "total")),
}


class BatchContextRef(ContractModel):
    """An existing captured context identity, never a newly created Context."""

    result_id: NonEmptyStr
    context_digest: NonEmptyStr
    context_version: NonEmptyStr
    result_contract_version: NonEmptyStr


class BatchLimitation(ContractModel):
    code: NonEmptyStr
    signal_index: int | None = Field(default=None, ge=0)
    message: NonEmptyStr


def _require_signal(signal: BusinessSignal) -> None:
    if not isinstance(signal, BusinessSignal):
        raise TypeError("signals must contain BusinessSignal objects")
    if type(signal.status) is not str or signal.status not in _STATUS_PRIORITY:
        raise ValueError("a Signal must have a known status")
    if type(signal.signal_type) is not str or signal.signal_type not in _SIGNAL_SHAPES:
        raise ValueError("a Signal must have a known signal_type")


def _nonempty_id(value: object) -> bool:
    return type(value) is str and len(value) > 0


def _require_observation(observation: ObservedValue) -> None:
    if not isinstance(observation, ObservedValue):
        raise TypeError("Signal operands must retain ObservedValue objects")
    if type(observation.presence) is not str or observation.presence not in get_args(Presence):
        raise ValueError("an observation must retain a known presence state")
    # Existing after-validation checks presence versus value without copying
    # the model. Only supplied observation labels are consumed by this layer.
    ObservedValue.model_validate(observation)
    if observation.presence == "present" and not _nonempty_id(observation.value):
        raise ValueError("a present observation requires its nonempty value text")
    for label in (observation.evidence_id, observation.unit_id):
        if label is not None and not _nonempty_id(label):
            raise ValueError("observation labels must be nonempty strings when supplied")


def inspect_signal(signal: BusinessSignal) -> list[str]:
    """Return stable display-consistency codes without changing a Signal.

    Failure Signals retain their status and may lack Evidence. Computed and
    undefined Signals need consistent child states and the existing ordered
    operand references for their type. Evidence links are resolved only inside
    this Signal; equal IDs in another Signal cannot supply a missing operand.
    No numeric value, source, grain, filter, time or Policy is interpreted.
    """
    _require_signal(signal)
    formulas, roles = _SIGNAL_SHAPES[signal.signal_type]
    if type(signal.computed_value) is not dict:
        raise TypeError("computed_value must retain its output dictionary")
    children = list(signal.computed_value.values())
    if any(not isinstance(child, ComputationResult) for child in children):
        raise TypeError("computed_value must contain ComputationResult objects")
    if any(type(child.status) is not str or child.status not in _STATUS_PRIORITY for child in children):
        raise ValueError("a formula output must have a known status")
    for child in children:
        if type(child.formula_id) is not str or child.formula_id not in get_args(FormulaId):
            raise ValueError("a formula output must have a known formula identity")
        if type(child.formula_version) is not str or child.formula_version not in get_args(ContractVersion):
            raise ValueError("a formula output must use a supported contract version")
        # Instance after-validation checks the existing result shape without
        # cloning it. A malformed output cannot be retained as a valid wire
        # record merely by hiding it from the display view.
        ComputationResult.model_validate(child)
        if any(value is not None and not _nonempty_id(value) for value in (child.value, child.unit_id)):
            raise ValueError("formula value and unit must be nonempty strings when supplied")
        if type(child.input_evidence_ids) is not list:
            raise TypeError("input_evidence_ids must remain a list")
        if any(not _nonempty_id(identity) for identity in child.input_evidence_ids):
            raise ValueError("input_evidence_ids must contain nonempty strings")

    status_valid = set(signal.computed_value) == set(formulas) and bool(children)
    if children:
        expected = max((child.status for child in children), key=_STATUS_PRIORITY.__getitem__)
        status_valid = status_valid and signal.status == expected
    for name, child in signal.computed_value.items():
        status_valid = status_valid and child.formula_id == name
    issues = [] if status_valid else ["SIGNAL_STATUS_MISMATCH"]
    if type(signal.evidence) is not list or any(
        not isinstance(item, SignalEvidence) for item in signal.evidence
    ):
        raise TypeError("evidence must retain its SignalEvidence objects")
    for item in signal.evidence:
        if not _nonempty_id(item.evidence_id):
            raise ValueError("Evidence identity must remain a nonempty string")
        if type(item.context_role) is not str or item.context_role not in get_args(ContextRole):
            raise ValueError("Evidence must retain a known context role")
        if type(item.formula_refs) is not list or any(not isinstance(ref, EvidenceFormulaRef) for ref in item.formula_refs):
            raise TypeError("formula_refs must retain EvidenceFormulaRef objects")
        if any(type(ref.formula_id) is not str or ref.formula_id not in get_args(FormulaId) for ref in item.formula_refs):
            raise ValueError("an Evidence formula reference must have a known formula identity")
        if any(type(ref.formula_version) is not str or ref.formula_version not in get_args(ContractVersion)
               for ref in item.formula_refs):
            raise ValueError("an Evidence formula reference must use a supported contract version")
    if signal.status not in ("computed", "undefined"):
        return issues

    observations = [signal.current_value, signal.reference_value]
    for observation in observations:
        _require_observation(observation)
    operand_ids = [observation.evidence_id for observation in observations]
    links_valid = (
        all(_nonempty_id(identity) for identity in operand_ids)
        and operand_ids[0] != operand_ids[1]
        and all(observation.presence == "present" for observation in observations)
    )
    evidence_by_id: dict[str, list[SignalEvidence]] = {}
    for item in signal.evidence:
        evidence_by_id.setdefault(item.evidence_id, []).append(item)
    if any(len(matches) != 1 for matches in evidence_by_id.values()):
        links_valid = False
    for role, observation in zip(roles, observations):
        matches = evidence_by_id.get(observation.evidence_id, [])
        if len(matches) != 1:
            links_valid = False
            continue
        matched = matches[0]
        if matched.observed_value is not None:
            _require_observation(matched.observed_value)
        if (matched.context_role != role or matched.observed_value != observation
                or matched.observed_value is None
                or matched.observed_value.evidence_id != matched.evidence_id):
            links_valid = False
    for child in children:
        references = child.input_evidence_ids
        if (not references or len(references) != len(set(references))
                or references != operand_ids):
            links_valid = False
            continue
        for identity in references:
            matches = evidence_by_id.get(identity, [])
            if len(matches) != 1:
                links_valid = False
                continue
            formula_refs = matches[0].formula_refs
            if not any(
                ref.formula_id == child.formula_id and ref.formula_version == child.formula_version
                for ref in formula_refs
            ):
                links_valid = False
    if not links_valid:
        issues.append("SIGNAL_EVIDENCE_LINK_INVALID")
    return issues


def count_statuses(signals: list[BusinessSignal]) -> dict[SignalStatus, int]:
    """Count supplied top-level statuses, including all five zero buckets."""
    counts = dict.fromkeys(_STATUSES, 0)
    for signal in signals:
        _require_signal(signal)
        counts[signal.status] += 1
    return counts


def derived_contexts(signals: list[BusinessSignal]) -> list[BatchContextRef]:
    """Extract first-seen complete identity tuples from existing Evidence.

    Equal result IDs with distinct digests or versions remain distinct
    snapshots. These references do not infer or instantiate BusinessContext.
    """
    references = []
    seen = set()
    for signal in signals:
        _require_signal(signal)
        for evidence in signal.evidence:
            if not isinstance(evidence, SignalEvidence):
                raise TypeError("evidence must contain SignalEvidence objects")
            identity = (
                evidence.result_id, evidence.context_digest,
                evidence.context_version, evidence.result_contract_version,
            )
            if identity not in seen:
                seen.add(identity)
                references.append(BatchContextRef(
                    result_id=identity[0], context_digest=identity[1],
                    context_version=identity[2], result_contract_version=identity[3],
                ))
    return references


class SignalBatch(ContractModel):
    """All original Signals plus one display view and captured identity refs.

    The input list is detached by normal Pydantic collection validation;
    its Signal and Evidence objects retain their original identity. There is
    no second Signal list or Evidence pool in the serialized contract.
    """

    version: ContractVersion = "1"
    batch_id: NonEmptyStr | None = None
    signals: list[BusinessSignal]
    created_contexts: list[BatchContextRef]
    displayable_signal_indices: list[int]
    status_counts: dict[SignalStatus, int]
    limitations: list[BatchLimitation]

    @model_validator(mode="after")
    def consistent_views(self) -> Self:
        inspected = [inspect_signal(signal) for signal in self.signals]
        if self.status_counts != count_statuses(self.signals):
            raise ValueError("status_counts must include and match every supplied Signal status")
        if self.created_contexts != derived_contexts(self.signals):
            raise ValueError("created_contexts must match the first-seen captured identity references")
        indexes = self.displayable_signal_indices
        if indexes != sorted(set(indexes)) or any(index < 0 or index >= len(self.signals) for index in indexes):
            raise ValueError("display indexes must be unique, increasing and in range")
        for index in indexes:
            signal = self.signals[index]
            if signal.status not in ("computed", "undefined") or inspected[index]:
                raise ValueError("display indexes may reference only consistent computed or undefined Signals")
        if any(item.signal_index is not None and item.signal_index >= len(self.signals) for item in self.limitations):
            raise ValueError("a limitation must reference a Signal in this batch")
        return self

    @property
    def displayable_signals(self) -> tuple[BusinessSignal, ...]:
        """A nonserialized view retaining each selected Signal object."""
        return tuple(self.signals[index] for index in self.displayable_signal_indices)


__all__ = [
    "BatchContextRef", "BatchLimitation", "SignalBatch", "inspect_signal",
    "derived_contexts", "count_statuses",
]
