"""Phase 3 foundation data contracts, with structural validation only.

No SQL parsing, acquisition, compatibility decisions, key normalization,
numeric decoding, formula evaluation or identity generation happens here.
IDs/digests and declarations are supplied facts, not verified authenticity.
Frozen models are shallow: consumers must not mutate their nested containers.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..result_contract import (
    Completeness, ExecutionProvenance, JsonScalar, RepresentationStatus, ValueEncoding,
)
from ..result_understanding.models import (
    Aggregation, BusinessContext, FilterInfo, GrainInfo, LineageSource,
    SchemaBinding, SemanticStatus, TimeConstraintInfo,
)


NonEmptyStr = Annotated[str, Field(min_length=1)]
ContractVersion = Literal["1"]
SignalStatus = Literal[
    "computed", "insufficient_evidence", "incompatible_context", "unsupported", "undefined",
]
CompatibilityStatus = Literal[
    "compatible", "insufficient_evidence", "incompatible_context", "unsupported",
]
SignalType = Literal[
    "monthly_regional_target_attainment", "regional_sales_change", "product_contribution",
]
ContextRole = Literal["actual", "target", "current", "baseline", "parts", "total"]
Operation = Literal["align", "compare", "divide"]
FormulaId = Literal["attainment_rate", "absolute_change", "change_rate", "contribution_rate"]
DeclarationType = Literal[
    "unit", "time_domain", "row_selection", "population", "source_key_uniqueness",
    "snapshot_revision", "metric_basis",
]
IssuerKind = Literal["fixture_catalog", "approved_capture"]
EvidenceGrade = Literal["trusted_declaration"]
Presence = Literal[
    "present", "sql_null", "missing", "unknown_payload", "unknown_metadata",
    "not_read", "rejected",
]


class ContractModel(BaseModel):
    """Reject coercion and extensions; do not manufacture missing observations."""

    model_config = ConfigDict(
        strict=True, extra="forbid", frozen=True, validate_default=True, allow_inf_nan=False,
    )


class SourceField(ContractModel):
    """Complete, explicitly supplied identity for rules and declarations.

    Evidence uses Phase 2 LineageSource instead, retaining unknown identities.
    """

    database: NonEmptyStr
    table: NonEmptyStr
    field: NonEmptyStr


class NumericQuality(ContractModel):
    """Source fidelity and arithmetic rounding are independent observations."""

    source_fidelity: Literal["exact", "approximate", "unknown"] = "unknown"
    source_kind: Literal["decimal_text", "integer", "binary_float", "unknown"] = "unknown"
    arithmetic_rounding: Literal["exact", "rounded", "unknown"] = "unknown"
    scale: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def binary_float_is_not_exact(self) -> NumericQuality:
        if self.source_kind == "binary_float" and self.source_fidelity == "exact":
            raise ValueError("binary float source cannot claim exact decimal fidelity")
        return self


class ObservedValue(ContractModel):
    """An observation, or an explicit reason that no numeric value is supplied.

    not_read means a gate prevented reading; rejected means a read cell failed
    Numeric validation. Neither state implies missing metadata or a zero.
    """

    presence: Presence
    value: NonEmptyStr | None = None
    unit_id: NonEmptyStr | None = None
    evidence_id: NonEmptyStr | None = None
    source_quality: NumericQuality = Field(default_factory=NumericQuality)

    @model_validator(mode="after")
    def value_matches_presence(self) -> ObservedValue:
        if (self.presence == "present") != (self.value is not None):
            raise ValueError("only present observations must carry a value")
        return self


class BusinessKeyComponent(ContractModel):
    domain_id: NonEmptyStr
    component_id: NonEmptyStr
    value_type: Literal["string", "integer"]
    raw_value: str | int
    normalized_value: str | int

    @model_validator(mode="after")
    def values_match_declared_type(self) -> BusinessKeyComponent:
        expected = str if self.value_type == "string" else int
        if type(self.raw_value) is not expected or type(self.normalized_value) is not expected:
            raise ValueError("key values must match value_type without coercion")
        return self


class NormalizedPeriod(ContractModel):
    """Already supplied bounds; this model does not interpret calendar dates."""

    domain_id: NonEmptyStr
    calendar: Literal["gregorian"]
    precision: Literal["date", "month"]
    lower: NonEmptyStr
    upper: NonEmptyStr
    lower_inclusive: bool
    upper_inclusive: bool


class RolePeriod(ContractModel):
    context_role: ContextRole
    period: NormalizedPeriod


class BusinessKey(ContractModel):
    """Ordered components and role-specific periods, never a dict/set hash."""

    components: list[BusinessKeyComponent] = Field(min_length=1)
    periods: list[RolePeriod] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_component_identity(self) -> BusinessKey:
        identities = [(item.domain_id, item.component_id) for item in self.components]
        if any(identity in identities[:index] for index, identity in enumerate(identities)):
            raise ValueError("business key component identities must be unique")
        return self


class Issue(ContractModel):
    """Consumers branch on code/typed facts, never on explanatory message text."""

    code: NonEmptyStr
    stage: Literal[
        "input", "policy", "declaration", "compatibility", "alignment", "numeric",
        "computation", "evidence",
    ]
    context_role: ContextRole | None = None
    result_id: NonEmptyStr | None = None
    key: BusinessKey | None = None
    evidence_paths: list[NonEmptyStr] = Field(default_factory=list)
    severity: Literal["info", "warning", "error"]
    message: str


class SignalSelection(ContractModel):
    """Explicit local column IDs only; no lookup or fallback by output name."""

    metric_column_id: NonEmptyStr
    key_column_ids: dict[NonEmptyStr, NonEmptyStr]
    auxiliary_column_ids: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)


class DeclarationScope(ContractModel):
    source_fields: list[SourceField] = Field(default_factory=list)
    period: NormalizedPeriod | None = None
    population_scope_ref: NonEmptyStr | None = None
    filter_scope_ref: NonEmptyStr | None = None
    key_domains: list[NonEmptyStr] = Field(default_factory=list)
    target_version: NonEmptyStr | None = None


class UnitClaim(ContractModel):
    source_fields: list[SourceField] = Field(min_length=1)
    unit_id: NonEmptyStr
    unit_scale: NonEmptyStr
    display_scale: int | None = Field(default=None, ge=0)


class TimeDomainClaim(ContractModel):
    source_fields: list[SourceField] = Field(min_length=1)
    domain_id: NonEmptyStr
    calendar: Literal["gregorian"]
    precision: Literal["date", "month"]
    comparison_domain: Literal["date", "iso_date_text", "iso_month_text"]
    timezone: NonEmptyStr | None = None


class RowSelectionClaim(ContractModel):
    mode: Literal["absent", "limit", "offset", "top_n", "other"]
    limit: int | None = Field(default=None, ge=0)
    offset: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def absent_has_no_bounds(self) -> RowSelectionClaim:
        if self.mode == "absent" and (self.limit is not None or self.offset is not None):
            raise ValueError("absent row selection cannot carry selection bounds")
        return self


class PopulationClaim(ContractModel):
    population_scope_ref: NonEmptyStr
    coverage: Literal["complete", "incomplete", "unknown"]
    partition_key_domains: list[NonEmptyStr] = Field(default_factory=list)


class SourceKeyUniquenessClaim(ContractModel):
    source_fields: list[SourceField] = Field(min_length=1)
    key_domains: list[NonEmptyStr] = Field(min_length=1)
    uniqueness: Literal["unique", "duplicate", "unknown"]


class SnapshotRevisionClaim(ContractModel):
    dataset_ref: NonEmptyStr
    revision_ref: NonEmptyStr
    comparison_group_ref: NonEmptyStr | None = None


class MetricBasisClaim(ContractModel):
    """Explicit business definition reference, not metric equivalence inference."""

    metric_id: NonEmptyStr
    counterpart_metric_id: NonEmptyStr
    basis_id: NonEmptyStr
    status_value: NonEmptyStr | None = None


class DeclarationClaims(ContractModel):
    """Closed claim domains; no arbitrary dict or universal coverage boolean."""

    unit: UnitClaim | None = None
    time_domain: TimeDomainClaim | None = None
    row_selection: RowSelectionClaim | None = None
    population: PopulationClaim | None = None
    source_key_uniqueness: SourceKeyUniquenessClaim | None = None
    snapshot_revision: SnapshotRevisionClaim | None = None
    metric_basis: MetricBasisClaim | None = None


class InputDeclaration(ContractModel):
    """Bound, attributed claim. Construction does not authenticate its issuer.

    Actual result/digest/scope matching belongs to future compatibility logic.
    One declaration carries exactly its named domain, never unrelated claims.
    """

    version: ContractVersion = "1"
    declaration_id: NonEmptyStr
    declaration_type: DeclarationType
    result_id: NonEmptyStr
    context_digest: NonEmptyStr
    column_ids: list[NonEmptyStr]
    issuer_kind: IssuerKind
    issuer_ref: NonEmptyStr
    basis_ref: NonEmptyStr
    claims: DeclarationClaims
    evidence_grade: EvidenceGrade
    scope: DeclarationScope

    @model_validator(mode="after")
    def claim_matches_domain(self) -> InputDeclaration:
        populated = [name for name in type(self.claims).model_fields if getattr(self.claims, name) is not None]
        if populated != [self.declaration_type]:
            raise ValueError("claims must contain exactly the declared domain")
        return self


class SignalInput(ContractModel):
    """Detached copy of supplied facts, not a rebuilt or newly acquired Context.

    IDs are preserved. Selection existence, provenance and declarations are
    deliberately not judged here; later compatibility checks own that work.
    """

    context: BusinessContext
    selection: SignalSelection
    declarations: list[InputDeclaration] = Field(default_factory=list)

    @field_validator("context")
    @classmethod
    def detach_context(cls, value: BusinessContext) -> BusinessContext:
        return value.model_copy(deep=True)


class ProductContributionInput(ContractModel):
    """Explicit parts/total facts; neither role is discovered or acquired."""

    parts: SignalInput
    total: SignalInput

    @field_validator("parts", "total")
    @classmethod
    def detach_role(cls, value: SignalInput) -> SignalInput:
        return value.model_copy(deep=True)


class SignalOperandReference(ContractModel):
    """Minimal S3 location handoff, not integrated SignalEvidence.

    A verified Alignment supplies row positions and its pair-level broadcast
    flag. An unverified/unlocated operand has no row or broadcast assertion.
    No numeric reading or formula result is stored in this reference.
    """

    context_role: Literal["parts", "total"]
    result_id: NonEmptyStr
    context_digest: NonEmptyStr
    column_id: NonEmptyStr | None = None
    ordinal: int | None = Field(default=None, ge=0)
    row_index: int | None = Field(default=None, ge=0)
    alignment_broadcast: bool | None = None

    @model_validator(mode="after")
    def location_shape(self) -> SignalOperandReference:
        if (self.column_id is None) != (self.ordinal is None):
            raise ValueError("column_id and ordinal must be supplied together")
        if self.row_index is not None and self.column_id is None:
            raise ValueError("a row location requires a selected column")
        return self


class DeclarationRef(ContractModel):
    declaration_id: NonEmptyStr
    declaration_type: DeclarationType
    result_id: NonEmptyStr
    context_digest: NonEmptyStr


class RoleMetricRef(ContractModel):
    context_role: ContextRole
    metric_id: NonEmptyStr
    match_status: Literal["matched", "unknown", "incompatible"]
    mapping_id: NonEmptyStr | None = None
    relationship_id: NonEmptyStr | None = None
    source_fields: list[LineageSource] | None = None


class TypedFilterValue(ContractModel):
    value_type: Literal["string", "integer", "numeric_text", "boolean", "null", "date_literal"]
    value: str | int | bool | None

    @model_validator(mode="after")
    def value_matches_type(self) -> TypedFilterValue:
        expected = {"integer": int, "boolean": bool, "null": type(None)}.get(self.value_type, str)
        if type(self.value) is not expected:
            raise ValueError("filter literal must match value_type without coercion")
        return self


class NormalizedFilter(ContractModel):
    """A supplied Policy-mapped predicate signature, not SQL text interpretation."""

    context_role: ContextRole
    scope: Literal["WHERE", "HAVING"]
    source_identity: NonEmptyStr
    operator: Literal["=", "!=", ">", ">=", "<", "<=", "BETWEEN"]
    value: TypedFilterValue | None = None
    lower_bound: TypedFilterValue | None = None
    upper_bound: TypedFilterValue | None = None

    @model_validator(mode="after")
    def predicate_shape(self) -> NormalizedFilter:
        if self.operator == "BETWEEN":
            if self.value is not None or self.lower_bound is None or self.upper_bound is None:
                raise ValueError("BETWEEN requires two bounds and no scalar value")
        elif self.value is None or self.lower_bound is not None or self.upper_bound is not None:
            raise ValueError("scalar comparison requires value and no bounds")
        return self


class DeclarationContentBinding(ContractModel):
    """Captured declaration identity plus a digest of every declaration field."""

    declaration_id: str
    declaration_type: str
    result_id: str
    context_digest: str
    content_digest: NonEmptyStr


class SignalInputBinding(ContractModel):
    result_id: str
    context_digest: NonEmptyStr
    selection_digest: NonEmptyStr
    declarations: list[DeclarationContentBinding]
    input_digest: NonEmptyStr


class CompatibilityReceiptBinding(ContractModel):
    """Versioned content binding, not a signature or issuer authentication.

    Unknown versions remain readable so the Alignment gate can reject them.
    policy_digest is computed from actual content; definition_digest retains
    the caller's identity label and is not trusted as a computed fingerprint.
    """

    version: NonEmptyStr = "1"
    policy_id: NonEmptyStr
    policy_version: NonEmptyStr
    definition_digest: NonEmptyStr
    policy_digest: NonEmptyStr
    input_bindings: dict[ContextRole, SignalInputBinding]
    semantics_digest: NonEmptyStr


class ContextCompatibility(ContractModel):
    """Qualification result; Alignment requires its complete content binding."""

    operation: Operation
    context_roles: list[ContextRole] = Field(min_length=1)
    result_ids: dict[ContextRole, NonEmptyStr]
    status: CompatibilityStatus
    issues: list[Issue] = Field(default_factory=list)
    normalized_metric_refs: list[RoleMetricRef] = Field(default_factory=list)
    key_domains: list[NonEmptyStr] = Field(default_factory=list)
    periods: list[RolePeriod] = Field(default_factory=list)
    non_time_filters: list[NormalizedFilter] = Field(default_factory=list)
    declarations_used: list[DeclarationRef] = Field(default_factory=list)
    input_digests: dict[ContextRole, NonEmptyStr] = Field(default_factory=dict)
    # Old serialized results still load, but cannot authorize key extraction.
    binding: CompatibilityReceiptBinding | None = None


class AlignmentPair(ContractModel):
    """An observed key bucket, with no chosen row for an ambiguous side.

    key is a deterministic observed representative. Side keys preserve both
    raw observations when an explicit mapping equates different raw values.
    A broadcast total has a row index but no fabricated BusinessKey.
    """

    key: BusinessKey
    left_row_index: int | None = Field(default=None, ge=0)
    right_row_index: int | None = Field(default=None, ge=0)
    left_key: BusinessKey | None = None
    right_key: BusinessKey | None = None
    status: Literal["matched", "missing_left", "missing_right", "ambiguous", "unresolved"]
    broadcast: bool = False

    @model_validator(mode="after")
    def pair_presence(self) -> AlignmentPair:
        if self.status == "matched" and (self.left_row_index is None or self.right_row_index is None):
            raise ValueError("matched pairs require both row indexes")
        if self.status == "missing_left" and (self.left_row_index is not None or self.right_row_index is None):
            raise ValueError("missing_left requires only a right row")
        if self.status == "missing_right" and (self.right_row_index is not None or self.left_row_index is None):
            raise ValueError("missing_right requires only a left row")
        if self.status in ("ambiguous", "unresolved") and self.left_row_index is not None and self.right_row_index is not None:
            raise ValueError("ambiguous or unresolved pairs cannot select both rows")
        return self


class DuplicateKey(ContractModel):
    context_role: ContextRole
    key: BusinessKey
    row_indexes: list[Annotated[int, Field(ge=0)]] = Field(min_length=2)
    raw_keys: list[BusinessKey] = Field(min_length=2)
    normalization_collision: bool = False

    @model_validator(mode="after")
    def preserve_all_rows(self) -> DuplicateKey:
        if len(self.row_indexes) != len(self.raw_keys) or len(set(self.row_indexes)) != len(self.row_indexes):
            raise ValueError("duplicate keys require one raw key per distinct row index")
        return self


class AlignmentReceiptBinding(ContractModel):
    """Producer content linkage, not a signature or an authenticity claim."""

    version: NonEmptyStr = "1"
    compatibility_digest: NonEmptyStr
    alignment_digest: NonEmptyStr


class AlignmentResult(ContractModel):
    """Row correspondence only, never a computed Signal or business value."""

    status: Literal["aligned", "insufficient_evidence", "incompatible_context", "unsupported"]
    operation: Operation
    left_role: ContextRole
    right_role: ContextRole
    key_domain: list[NonEmptyStr] = Field(min_length=1)
    pairs: list[AlignmentPair] = Field(default_factory=list)
    missing_left_keys: list[BusinessKey] = Field(default_factory=list)
    missing_right_keys: list[BusinessKey] = Field(default_factory=list)
    duplicate_keys: list[DuplicateKey] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    broadcastable: bool = False
    broadcast_role: ContextRole | None = None
    # Legacy results load, but cannot authorize downstream computation.
    binding: AlignmentReceiptBinding | None = None


class EvidenceEligibility(ContractModel):
    completeness: Completeness | None = None
    truncated: bool | None = None
    returned_rows: int | None = Field(default=None, ge=0)
    total_rows: int | None = Field(default=None, ge=0)
    understanding_status: SemanticStatus | None = None
    declarations: list[DeclarationRef] = Field(default_factory=list)


class EvidenceFormulaRef(ContractModel):
    """Formula association only; neither a computed value nor execution proof."""

    formula_id: FormulaId
    formula_version: ContractVersion = "1"


class SignalEvidence(ContractModel):
    """Operand facts and formula references, never a computed Signal value.

    row_index is a captured result position, not a source ID. business_key is
    this operand's observed side key, not an inferred key for a missing side.
    Existing field names retain their wire meaning: schema_metadata contains
    SchemaBinding objects; time contains captured time constraints.
    """

    evidence_id: NonEmptyStr
    context_role: ContextRole
    result_id: NonEmptyStr
    context_version: ContractVersion
    # Rejected inputs still retain the version that made them unsupported.
    result_contract_version: NonEmptyStr
    context_digest: NonEmptyStr
    column_id: NonEmptyStr | None = None
    ordinal: int | None = Field(default=None, ge=0)
    row_index: int | None = Field(default=None, ge=0)
    key_columns: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)
    key_values: list[BusinessKeyComponent] = Field(default_factory=list)
    business_key: BusinessKey | None = None
    alignment_status: Literal["matched", "missing_left", "missing_right", "ambiguous", "unresolved"] | None = None
    # Optional S3 pair fact; omit only this field on unchanged legacy paths.
    alignment_broadcast: bool | None = Field(default=None, exclude_if=lambda value: value is None)
    source_fields: list[LineageSource] | None = None
    metric_semantic: RoleMetricRef | None = None
    schema_metadata: list[SchemaBinding] = Field(default_factory=list)
    aggregation: Aggregation | None = None
    grain: GrainInfo | None = None
    time: list[TimeConstraintInfo] | None = None
    normalized_period: NormalizedPeriod | None = None
    filters: FilterInfo | None = None
    normalized_filters: list[NormalizedFilter] = Field(default_factory=list)
    observed_value: ObservedValue | None = None
    # None permits legacy evidence; the Builder always supplies known/unknown
    # quality from the captured numeric observation, never formula rounding.
    numeric_quality: NumericQuality | None = None
    numeric_issues: list[Issue] = Field(default_factory=list)
    formula_refs: list[EvidenceFormulaRef] = Field(default_factory=list)
    raw_value: JsonScalar = None
    dtype: NonEmptyStr | None = None
    value_encoding: ValueEncoding | None = None
    representation_status: RepresentationStatus | None = None
    eligibility: EvidenceEligibility | None = None
    unit_declaration: InputDeclaration | None = None
    provenance: ExecutionProvenance | None = None
    upstream_limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def observation_location_shape(self) -> SignalEvidence:
        if (self.column_id is None) != (self.ordinal is None):
            raise ValueError("column_id and ordinal must be supplied together")
        if self.row_index is not None and self.column_id is None:
            raise ValueError("an observed cell requires column identity")
        if self.raw_value is not None and self.row_index is None:
            raise ValueError("a raw cell value requires an observed row")
        if self.observed_value is not None:
            presence = self.observed_value.presence
            if presence in ("present", "sql_null") and self.row_index is None:
                raise ValueError("present or SQL NULL observations require row_index")
            if presence in ("missing", "unknown_payload") and self.row_index is not None:
                raise ValueError("missing or unknown payload cannot claim an observed row")
            if presence == "sql_null" and self.raw_value is not None:
                raise ValueError("SQL NULL cannot carry a non-NULL raw value")
            if presence == "not_read" and self.raw_value is not None:
                raise ValueError("an unread observation cannot claim a raw cell value")
            if presence == "rejected" and self.row_index is None:
                raise ValueError("a rejected numeric cell requires row_index")
        if self.unit_declaration is not None and self.unit_declaration.declaration_type != "unit":
            raise ValueError("unit evidence must contain a unit declaration")
        if self.business_key is not None and self.business_key.components != self.key_values:
            raise ValueError("business_key and key_values must describe the same operand")
        if (self.numeric_quality is not None and self.observed_value is not None
                and self.numeric_quality != self.observed_value.source_quality):
            raise ValueError("numeric quality must preserve the observation's source quality")
        if self.alignment_broadcast is not None:
            if self.context_role not in ("parts", "total") or self.alignment_status != "matched":
                raise ValueError("an explicit broadcast fact requires a matched S3 operand")
            if self.alignment_broadcast and self.context_role == "total" and (
                self.row_index != 0 or self.business_key is not None or self.key_values
            ):
                raise ValueError("a broadcast total must retain row zero without a business key")
            if self.alignment_broadcast and self.context_role == "parts" and self.business_key is None:
                raise ValueError("a broadcast part must retain its own business key")
        return self


class ComputationResult(ContractModel):
    """Fixed formula result shape, with no numerical or status decision engine."""

    status: SignalStatus
    value: NonEmptyStr | None = None
    unit_id: NonEmptyStr | None = None
    formula_id: FormulaId
    formula_version: ContractVersion = "1"
    input_evidence_ids: list[NonEmptyStr]
    numeric_quality: NumericQuality = Field(default_factory=NumericQuality)
    reason_code: NonEmptyStr | None = None

    @model_validator(mode="after")
    def result_shape(self) -> ComputationResult:
        if self.status == "computed":
            if self.value is None or self.unit_id is None:
                raise ValueError("computed output requires value and unit")
        elif self.value is not None:
            raise ValueError("non-computed output cannot carry a computed value")
        return self


class BusinessSignal(ContractModel):
    """One key or a context-level rejection; identity and status are supplied.

    Only fixed output shapes are checked here. No formula is evaluated, and
    top-level status precedence and evidence binding are future logic.
    """

    version: ContractVersion = "1"
    # The global Signal identity algorithm has not been frozen yet.
    signal_id: NonEmptyStr | None = None
    signal_type: SignalType
    scope: Literal["business_key", "context"]
    status: SignalStatus
    policy_id: NonEmptyStr
    policy_version: ContractVersion
    policy_digest: NonEmptyStr
    calculator_version: ContractVersion
    business_key: BusinessKey | None = None
    metric: list[RoleMetricRef]
    current_value: ObservedValue
    reference_value: ObservedValue
    computed_value: dict[FormulaId, ComputationResult]
    evidence: list[SignalEvidence]
    # Retain the Phase 3.4.3 locations alongside integrated SignalEvidence.
    # Omit just this absent field, preserving all existing S1/S2 null fields.
    operand_references: list[SignalOperandReference] | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )
    limitations: list[Issue] = Field(default_factory=list)

    @model_validator(mode="after")
    def fixed_shape(self) -> BusinessSignal:
        if (self.scope == "business_key") != (self.business_key is not None):
            raise ValueError("business_key is required exactly for business_key scope")
        expected = {
            "monthly_regional_target_attainment": ["attainment_rate"],
            "regional_sales_change": ["absolute_change", "change_rate"],
            "product_contribution": ["contribution_rate"],
        }[self.signal_type]
        if sorted(self.computed_value) != sorted(expected):
            raise ValueError("computed_value must contain the fixed outputs for signal_type")
        if any(name != result.formula_id for name, result in self.computed_value.items()):
            raise ValueError("each output must reference its fixed formula")
        if self.operand_references is not None and (
            self.signal_type != "product_contribution"
            or [ref.context_role for ref in self.operand_references] != ["parts", "total"]
        ):
            raise ValueError("minimal operand references require the ordered S3 role pair")
        return self
