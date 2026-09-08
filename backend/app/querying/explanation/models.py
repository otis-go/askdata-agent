"""Immutable, allowlisted expression facts and request-local references.

These contracts describe already supplied facts. They do not qualify inputs,
interpret periods, parse numeric text or execute formulas. They deliberately
contain no Phase 3 object or open-ended metadata field.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


Text = Annotated[str, Field(min_length=1)]
Index = Annotated[int, Field(ge=0)]
SignalType = Literal[
    "monthly_regional_target_attainment", "regional_sales_change", "product_contribution",
]
SignalStatus = Literal[
    "computed", "undefined", "insufficient_evidence", "incompatible_context", "unsupported",
]
FormulaId = Literal["attainment_rate", "absolute_change", "change_rate", "contribution_rate"]
ContextRole = Literal["actual", "target", "current", "baseline", "parts", "total"]
SafeReasonCode = Literal["ZERO_DENOMINATOR", "ZERO_BASELINE", "ZERO_TOTAL", "UNKNOWN_REASON"]
SafeLimitationCode = Literal[
    "ZERO_DENOMINATOR", "ZERO_BASELINE", "ZERO_TOTAL", "UNKNOWN_REASON",
    "APPROXIMATE_INPUT", "RATIO_ROUNDED", "PARTITION_WITHIN_RELATIVE_TOLERANCE",
    "SIGNAL_IDENTITY_NOT_FROZEN", "SIGNAL_STATUS_MISMATCH", "SIGNAL_EVIDENCE_LINK_INVALID",
    "SIGNAL_NOT_DISPLAYABLE", "INSUFFICIENT_EVIDENCE", "INCOMPATIBLE_CONTEXT", "UNSUPPORTED",
    "UPSTREAM_LIMITATION_PRESENT", "UNEXPANDED_LIMITATION",
]


class ProjectionModel(BaseModel):
    model_config = ConfigDict(
        strict=True, extra="forbid", frozen=True, validate_default=True,
        revalidate_instances="always", allow_inf_nan=False,
    )


class SignalRef(ProjectionModel):
    source_batch_slot: Literal["input_batch"] = "input_batch"
    signal_index: Index


class OutputRef(SignalRef):
    formula_id: FormulaId
    formula_version: Literal["1"] = "1"


class EvidenceRef(SignalRef):
    evidence_id: Text


class LimitationRef(ProjectionModel):
    source_batch_slot: Literal["input_batch"] = "input_batch"
    scope: Literal["batch", "signal", "evidence_numeric", "evidence_upstream", "presentation"]
    signal_index: Index | None = None
    evidence_id: Text | None = None
    evidence_index: Index | None = None
    limitation_index: Index

    @model_validator(mode="after")
    def scoped_location(self) -> Self:
        if self.scope in ("signal", "evidence_numeric", "evidence_upstream") and self.signal_index is None:
            raise ValueError("a nested limitation requires its Signal index")
        if (self.scope in ("evidence_numeric", "evidence_upstream")) != (self.evidence_id is not None):
            raise ValueError("only Evidence limitations carry an Evidence identity")
        if (self.scope in ("evidence_numeric", "evidence_upstream")) != (self.evidence_index is not None):
            raise ValueError("Evidence limitations retain their original operand position")
        return self


class SafeLimitation(ProjectionModel):
    ref: LimitationRef
    code: SafeLimitationCode


class StatusCounts(ProjectionModel):
    computed: Index
    undefined: Index
    insufficient_evidence: Index
    incompatible_context: Index
    unsupported: Index


class QualitySummary(ProjectionModel):
    source_fidelity: Literal["exact", "approximate", "unknown"]
    source_kind: Literal["decimal_text", "integer", "binary_float", "unknown"]
    arithmetic_rounding: Literal["exact", "rounded", "unknown"]
    scale: Index | None

    @model_validator(mode="after")
    def source_shape(self) -> Self:
        if self.source_kind == "binary_float" and self.source_fidelity == "exact":
            raise ValueError("a binary floating source cannot claim exact decimal fidelity")
        return self


class KeyComponentSummary(ProjectionModel):
    domain_id: Text
    component_id: Text
    value_type: Literal["string", "integer"]
    normalized_value: str | int

    @model_validator(mode="after")
    def typed_literal(self) -> Self:
        if type(self.normalized_value) is not (str if self.value_type == "string" else int):
            raise ValueError("the normalized key must retain its declared scalar type")
        return self


class PeriodSummary(ProjectionModel):
    domain_id: Text
    calendar: Literal["gregorian"]
    precision: Literal["date", "month"]
    lower: Text
    upper: Text
    lower_inclusive: bool
    upper_inclusive: bool


class RolePeriodSummary(ProjectionModel):
    context_role: ContextRole
    period: PeriodSummary


class KeySummary(ProjectionModel):
    components: tuple[KeyComponentSummary, ...] = Field(min_length=1)
    periods: tuple[RolePeriodSummary, ...]


class FilterValueSummary(ProjectionModel):
    value_type: Literal["string", "integer", "numeric_text", "boolean", "null", "date_literal"]
    value: str | int | bool | None

    @model_validator(mode="after")
    def typed_literal(self) -> Self:
        expected = {"integer": int, "boolean": bool, "null": type(None)}.get(self.value_type, str)
        if type(self.value) is not expected:
            raise ValueError("the filter literal must retain its declared scalar type")
        return self


class FilterSummary(ProjectionModel):
    context_role: ContextRole
    scope: Literal["WHERE", "HAVING"]
    source_identity: Text
    operator: Literal["=", "!=", ">", ">=", "<", "<=", "BETWEEN"]
    value: FilterValueSummary | None
    lower_bound: FilterValueSummary | None
    upper_bound: FilterValueSummary | None

    @model_validator(mode="after")
    def predicate_shape(self) -> Self:
        if self.operator == "BETWEEN":
            if self.value is not None or self.lower_bound is None or self.upper_bound is None:
                raise ValueError("BETWEEN requires exactly two supplied bounds")
        elif self.value is None or self.lower_bound is not None or self.upper_bound is not None:
            raise ValueError("a scalar predicate requires exactly one supplied value")
        return self


class ObservationSummary(ProjectionModel):
    presence: Literal[
        "present", "sql_null", "missing", "unknown_payload", "unknown_metadata", "not_read", "rejected",
    ]
    value: Text | None
    unit_id: Text | None
    numeric_quality: QualitySummary

    @model_validator(mode="after")
    def value_presence(self) -> Self:
        if (self.presence == "present") != (self.value is not None):
            raise ValueError("only present observations carry a value")
        return self


class FormulaRef(ProjectionModel):
    formula_id: FormulaId
    formula_version: Literal["1"] = "1"


class EvidenceSummary(ProjectionModel):
    ref: EvidenceRef
    context_role: ContextRole
    result_id: Text
    context_digest: Text
    context_version: Literal["1"]
    result_contract_version: Text
    column_id: Text | None
    ordinal: Index | None
    row_index: Index | None
    observed_value: ObservationSummary | None
    numeric_quality: QualitySummary | None
    unit_scale: Text | None
    formula_refs: tuple[FormulaRef, ...]
    business_key: KeySummary | None
    normalized_period: PeriodSummary | None
    normalized_filters: tuple[FilterSummary, ...]
    aggregation: Literal["SUM", "AVG", "COUNT"] | None
    alignment_broadcast: bool | None
    limitation_refs: tuple[LimitationRef, ...]

    @model_validator(mode="after")
    def supplied_location(self) -> Self:
        if (self.column_id is None) != (self.ordinal is None):
            raise ValueError("column identity and ordinal must occur together")
        if self.row_index is not None and self.column_id is None:
            raise ValueError("a row reference requires column identity")
        if self.observed_value is not None and self.observed_value.presence in ("present", "sql_null"):
            if self.row_index is None:
                raise ValueError("a present observation requires a row reference")
        if self.numeric_quality is not None and self.observed_value is not None:
            if self.numeric_quality != self.observed_value.numeric_quality:
                raise ValueError("Evidence must preserve its observation quality")
        if self.alignment_broadcast is not None:
            if self.context_role not in ("parts", "total"):
                raise ValueError("a broadcast flag belongs only to the S3 operand roles")
            if self.alignment_broadcast and self.context_role == "total" and (
                self.row_index != 0 or self.business_key is not None
            ):
                raise ValueError("a broadcast total preserves row zero without a part key")
            if self.alignment_broadcast and self.context_role == "parts" and self.business_key is None:
                raise ValueError("a broadcast part preserves its own key")
        if any(item.context_role != self.context_role for item in self.normalized_filters):
            raise ValueError("normalized predicates retain their operand role")
        if len(set(self.limitation_refs)) != len(self.limitation_refs):
            raise ValueError("Evidence limitation references must be unique")
        if any(ref.scope not in ("evidence_numeric", "evidence_upstream")
               or ref.signal_index != self.ref.signal_index or ref.evidence_id != self.ref.evidence_id
               for ref in self.limitation_refs):
            raise ValueError("Evidence limitation references must retain this operand's own scope")
        return self


class OutputFact(ProjectionModel):
    ref: OutputRef
    status: Literal["computed", "undefined"]
    value: Text | None
    unit_id: Text | None
    numeric_quality: QualitySummary
    reason_code: SafeReasonCode | None
    input_evidence_refs: tuple[EvidenceRef, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def supplied_result(self) -> Self:
        if self.status == "computed":
            if self.value is None or self.unit_id is None:
                raise ValueError("computed facts require their original value and unit")
        elif self.value is not None:
            raise ValueError("undefined facts cannot carry a computed value")
        if any(ref.signal_index != self.ref.signal_index for ref in self.input_evidence_refs):
            raise ValueError("output inputs must remain in the same Signal scope")
        if len(set(self.input_evidence_refs)) != len(self.input_evidence_refs):
            raise ValueError("output input references must be unique")
        return self


class SignalFact(ProjectionModel):
    policy_id: Text
    policy_version: Literal["1"]
    policy_digest: Text
    calculator_version: Literal["1"]
    business_key: KeySummary | None
    outputs: tuple[OutputFact, ...] = Field(min_length=1)
    evidence_refs: tuple[EvidenceRef, ...] = Field(min_length=1)


class SignalView(ProjectionModel):
    ref: SignalRef
    signal_type: SignalType
    status: SignalStatus
    facts: SignalFact | None
    limitation_refs: tuple[LimitationRef, ...]

    @model_validator(mode="after")
    def display_shape(self) -> Self:
        if len(set(self.limitation_refs)) != len(self.limitation_refs):
            raise ValueError("Signal limitation references must be unique")
        if self.facts is None:
            return self
        if self.status not in ("computed", "undefined"):
            raise ValueError("failure Signals must not contain facts")
        expected = {
            "monthly_regional_target_attainment": ("attainment_rate",),
            "regional_sales_change": ("absolute_change", "change_rate"),
            "product_contribution": ("contribution_rate",),
        }[self.signal_type]
        if tuple(output.ref.formula_id for output in self.facts.outputs) != expected:
            raise ValueError("a displayed Signal must preserve every fixed output in order")
        expected_status = "undefined" if any(output.status == "undefined" for output in self.facts.outputs) else "computed"
        if self.status != expected_status:
            raise ValueError("the Signal and child output statuses must agree")
        refs = self.facts.evidence_refs
        if len(refs) != 2 or len(set(refs)) != 2:
            raise ValueError("a displayed Signal requires both distinct operand references")
        if any(ref.signal_index != self.ref.signal_index for ref in refs):
            raise ValueError("operand references must remain in their Signal scope")
        for output in self.facts.outputs:
            if output.ref.signal_index != self.ref.signal_index or output.input_evidence_refs != refs:
                raise ValueError("each fixed output must preserve the complete local operand pair")
        return self


class ExplanationContext(ProjectionModel):
    version: Literal["1"] = "1"
    projection_version: Literal["1"] = "1"
    source_batch_slot: Literal["input_batch"] = "input_batch"
    batch_id: Text | None
    signals: tuple[SignalView, ...]
    displayable_signal_indices: tuple[Index, ...]
    evidence_refs: tuple[EvidenceSummary, ...]
    limitations: tuple[SafeLimitation, ...]
    status_counts: StatusCounts

    @model_validator(mode="after")
    def closed_projection(self) -> Self:
        if tuple(view.ref.signal_index for view in self.signals) != tuple(range(len(self.signals))):
            raise ValueError("Signal views must retain all original positions")
        indices = self.displayable_signal_indices
        if indices != tuple(sorted(set(indices))) or any(index >= len(self.signals) for index in indices):
            raise ValueError("display indices must be unique, ordered and in range")
        if indices != tuple(index for index, view in enumerate(self.signals) if view.facts is not None):
            raise ValueError("facts must exist exactly for the supplied display view")
        for status in ("computed", "undefined", "insufficient_evidence", "incompatible_context", "unsupported"):
            if getattr(self.status_counts, status) != sum(view.status == status for view in self.signals):
                raise ValueError("status counts must preserve the complete Signal inventory")
        evidence = {item.ref: item for item in self.evidence_refs}
        if len(evidence) != len(self.evidence_refs):
            raise ValueError("Evidence references must be unique within Signal scope")
        expected_refs = tuple(ref for view in self.signals if view.facts is not None for ref in view.facts.evidence_refs)
        if tuple(item.ref for item in self.evidence_refs) != expected_refs:
            raise ValueError("Evidence summaries must match exactly the displayed operand pairs")
        limitations = {item.ref: item for item in self.limitations}
        if len(limitations) != len(self.limitations):
            raise ValueError("limitation references must be unique")
        limits_by_signal = {}
        limits_by_evidence = {}
        for item in self.limitations:
            if item.ref.signal_index is not None and item.ref.signal_index >= len(self.signals):
                raise ValueError("a limitation must retain its current Signal scope")
            limits_by_signal.setdefault(item.ref.signal_index, []).append(item.ref)
            if item.ref.evidence_id is not None:
                limits_by_evidence.setdefault((item.ref.signal_index, item.ref.evidence_id), []).append(item.ref)
        for view in self.signals:
            scoped_refs = tuple(limits_by_signal.get(view.ref.signal_index, ()))
            if view.limitation_refs != scoped_refs:
                raise ValueError("a Signal must retain every limitation in its own scope")
            presentation_refs = tuple(ref for ref in view.limitation_refs if ref.scope == "presentation")
            if view.facts is None:
                expected_code = {
                    "computed": "SIGNAL_NOT_DISPLAYABLE", "undefined": "SIGNAL_NOT_DISPLAYABLE",
                    "insufficient_evidence": "INSUFFICIENT_EVIDENCE", "incompatible_context": "INCOMPATIBLE_CONTEXT",
                    "unsupported": "UNSUPPORTED",
                }[view.status]
                if (len(presentation_refs) != 1 or presentation_refs[0].limitation_index != 0
                        or limitations[presentation_refs[0]].code != expected_code):
                    raise ValueError("each nondisplayable Signal requires its fixed safe status notice")
                continue
            if presentation_refs:
                raise ValueError("displayed facts cannot carry a nondisplayable notice")
            roles = {
                "monthly_regional_target_attainment": ("actual", "target"),
                "regional_sales_change": ("current", "baseline"),
                "product_contribution": ("parts", "total"),
            }[view.signal_type]
            if tuple(evidence[ref].context_role for ref in view.facts.evidence_refs) != roles:
                raise ValueError("operand roles must preserve the supplied Signal shape")
            for output in view.facts.outputs:
                for ref in output.input_evidence_refs:
                    item = evidence[ref]
                    if item.observed_value is None or item.observed_value.presence != "present":
                        raise ValueError("displayed formulas require the observed input pair")
                    if not any(formula.formula_id == output.ref.formula_id and formula.formula_version == output.ref.formula_version
                               for formula in item.formula_refs):
                        raise ValueError("formula references must resolve on both operand summaries")
        for item in self.evidence_refs:
            scoped_refs = tuple(limits_by_evidence.get((item.ref.signal_index, item.ref.evidence_id), ()))
            if item.limitation_refs != scoped_refs:
                raise ValueError("Evidence must retain every limitation in its operand scope")
        return self


__all__ = [
    "ProjectionModel", "SignalRef", "OutputRef", "EvidenceRef", "LimitationRef", "SafeLimitation",
    "SafeReasonCode", "SafeLimitationCode", "StatusCounts", "QualitySummary", "KeyComponentSummary",
    "PeriodSummary", "RolePeriodSummary", "KeySummary", "FilterValueSummary", "FilterSummary",
    "ObservationSummary", "FormulaRef", "EvidenceSummary", "OutputFact", "SignalFact", "SignalView",
    "ExplanationContext",
]
