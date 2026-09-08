"""Versioned rules for later Signal consumers; no input facts or calculations.

Callers construct these policies explicitly. Nothing here reads SCHEMA, parses
SQL, authenticates a declaration, checks a Context, or evaluates a formula.
Frozen models prevent field reassignment, not mutation of nested lists; later
consumers must take independent snapshots before inspecting input policy data.
"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .models import (
    ContextRole,
    ContractModel,
    ContractVersion,
    DeclarationType,
    EvidenceGrade,
    FormulaId,
    IssuerKind,
    NonEmptyStr,
    SignalType,
    SourceField,
    TypedFilterValue,
)


PolicyOperation = Literal["align", "compare", "divide"]
KeyValueType = Literal["string", "integer"]
NonEmptySources = Annotated[list[SourceField], Field(min_length=1)]


class SupportedContractVersions(ContractModel):
    result_contract: Annotated[list[ContractVersion], Field(min_length=1)]
    business_context: Annotated[list[ContractVersion], Field(min_length=1)]
    business_signal: Annotated[list[ContractVersion], Field(min_length=1)]


class MetricRule(ContractModel):
    context_role: ContextRole
    metric_id: NonEmptyStr
    mapping_id: NonEmptyStr
    allowed_sources: NonEmptySources
    allowed_aggregations: Annotated[list[Literal["SUM"]], Field(min_length=1)]
    require_schema_binding: bool = True


class RelationshipRule(ContractModel):
    relationship_id: NonEmptyStr
    operation: PolicyOperation
    left_role: ContextRole
    right_role: ContextRole
    left_metric_id: NonEmptyStr
    right_metric_id: NonEmptyStr
    metric_relationship: Literal["equivalent", "actual_to_target"]
    unit_relationship: Literal["same_unit"] = "same_unit"


class GrainRule(ContractModel):
    context_role: ContextRole
    grain: Literal["grouped", "global_aggregate"]
    grouping_sources: list[SourceField]
    total_broadcast: Literal["forbid", "allow_global_total"] = "forbid"

    @model_validator(mode="after")
    def coherent_grain_rule(self) -> Self:
        if self.grain == "grouped" and not self.grouping_sources:
            raise ValueError("a grouped grain rule needs grouping sources")
        if self.grain == "global_aggregate" and self.grouping_sources:
            raise ValueError("a global grain rule cannot have grouping sources")
        if self.total_broadcast == "allow_global_total" and (
            self.context_role != "total" or self.grain != "global_aggregate"
        ):
            raise ValueError("only a global total role can authorize broadcast")
        return self


class KeySourceRule(ContractModel):
    context_role: ContextRole
    source: SourceField


class KeyValueMapping(ContractModel):
    raw_value: str | int
    normalized_value: str | int


class KeyRule(ContractModel):
    domain_id: NonEmptyStr
    component_id: NonEmptyStr
    value_type: KeyValueType
    sources: Annotated[list[KeySourceRule], Field(min_length=1)]
    normalization: Literal["identity", "explicit_mapping"] = "identity"
    mapping_id: NonEmptyStr | None = None
    mapping_version: ContractVersion | None = None
    value_mappings: list[KeyValueMapping] = Field(default_factory=list)
    null_key: Literal["insufficient_evidence"] = "insufficient_evidence"

    @model_validator(mode="after")
    def coherent_mapping_definition(self) -> Self:
        roles = [source.context_role for source in self.sources]
        if len(roles) != len(set(roles)):
            raise ValueError("key source roles must be unique within a component")
        if self.normalization == "identity":
            if self.mapping_id or self.mapping_version or self.value_mappings:
                raise ValueError("identity normalization cannot carry a value map")
        elif not (self.mapping_id and self.mapping_version and self.value_mappings):
            raise ValueError("an explicit map needs an id, version and entries")
        value_type = str if self.value_type == "string" else int
        for entry in self.value_mappings:
            if type(entry.raw_value) is not value_type or type(entry.normalized_value) is not value_type:
                raise ValueError("mapping values must preserve the declared key type")
        raw_values = [entry.raw_value for entry in self.value_mappings]
        if len(raw_values) != len(set(raw_values)):
            raise ValueError("a value map cannot define one raw value twice")
        return self


class TimeSourceRule(ContractModel):
    context_role: ContextRole
    domain_id: NonEmptyStr
    allowed_sources: NonEmptySources
    accepted_precision: Literal["date", "month"]
    accepted_range: Literal["closed_open_month", "month_equality", "bounded_range"]


class TimeRules(ContractModel):
    relationship: Literal["same_calendar_month", "adjacent_calendar_months", "same_bounded_period"]
    calendar: Literal["gregorian"] = "gregorian"
    sources: Annotated[list[TimeSourceRule], Field(min_length=1)]
    require_bounded_period: bool = True
    require_complete_period: bool = True
    unbounded_period: Literal["reject"] = "reject"


class FilterPredicate(ContractModel):
    domain_id: NonEmptyStr
    source: SourceField
    scope: Literal["WHERE"] = "WHERE"
    operator: Literal["=", "!=", ">", ">=", "<", "<=", "BETWEEN"]
    value: TypedFilterValue | None = None
    lower_bound: TypedFilterValue | None = None
    upper_bound: TypedFilterValue | None = None

    @model_validator(mode="after")
    def predicate_arity(self) -> Self:
        if self.operator == "BETWEEN":
            if self.value is not None or self.lower_bound is None or self.upper_bound is None:
                raise ValueError("BETWEEN needs only a lower and upper bound")
        elif self.value is None or self.lower_bound is not None or self.upper_bound is not None:
            raise ValueError("a scalar predicate needs only one literal operand")
        return self


class RoleFilterRule(ContractModel):
    context_role: ContextRole
    required_conditions: list[FilterPredicate]
    additional_conditions: Literal["reject"] = "reject"


class FilterRules(ContractModel):
    comparison: Literal["mapped_equal", "role_specific_metric_basis"]
    roles: Annotated[list[RoleFilterRule], Field(min_length=1)]
    having: Literal["reject"] = "reject"
    unsupported_boolean_forms: Literal["reject"] = "reject"
    require_metric_basis_declaration: bool = False


class NumericRules(ContractModel):
    profile: Literal["decimal_exact_v1", "reporting_approx_v1"]
    accepted_encodings: Annotated[list[Literal["native_json", "decimal_text"]], Field(min_length=1)]
    required_representation: Literal["preserved"] = "preserved"
    allow_binary_float: bool = False
    decimal_precision: Annotated[int, Field(ge=80, le=80)] = 80
    max_input_scale: Annotated[int, Field(ge=0, le=18)] = 18
    max_abs_exponent: Annotated[int, Field(ge=1, le=38)] = 38
    ratio_scale: Annotated[int, Field(ge=12, le=12)] = 12
    max_parts: Annotated[int, Field(ge=1, le=10000)] = 10000
    rounding: Literal["ROUND_HALF_EVEN"] = "ROUND_HALF_EVEN"
    negative_inputs: Literal["reject"] = "reject"
    zero_denominator: Literal["undefined"] = "undefined"
    reconciliation: Literal["exact", "relative_tolerance"] = "exact"
    relative_tolerance: Literal["1e-12"] | None = None

    @model_validator(mode="after")
    def coherent_numeric_profile(self) -> Self:
        if self.ratio_scale > self.decimal_precision or self.max_input_scale > self.decimal_precision:
            raise ValueError("scales cannot exceed the working precision")
        if self.profile == "decimal_exact_v1":
            if self.allow_binary_float or self.reconciliation != "exact" or self.relative_tolerance is not None:
                raise ValueError("the exact profile cannot authorize approximate arithmetic")
        elif not self.allow_binary_float:
            raise ValueError("the approximate profile must explicitly authorize binary floats")
        if (self.reconciliation == "relative_tolerance") != (self.relative_tolerance is not None):
            raise ValueError("relative reconciliation needs an explicit tolerance")
        return self


class MissingRules(ContractModel):
    sql_null: Literal["insufficient_evidence"] = "insufficient_evidence"
    missing_key: Literal["insufficient_evidence"] = "insufficient_evidence"
    unknown_payload: Literal["insufficient_evidence"] = "insufficient_evidence"
    unknown_metadata: Literal["insufficient_evidence"] = "insufficient_evidence"
    alignment: Literal["outer_known_keys"] = "outer_known_keys"


class DuplicateRules(ContractModel):
    output_keys: Literal["reject"] = "reject"
    normalization_collisions: Literal["reject"] = "reject"
    source_uniqueness_required_roles: list[ContextRole] = Field(default_factory=list)
    known_source_duplicates: Literal["reject"] = "reject"


class CompletenessRules(ContractModel):
    required_output: Literal["complete_query_output"] = "complete_query_output"
    require_untruncated: bool = True
    require_known_equal_counts: bool = True
    row_selection: Literal["require_no_selection_declaration"] = "require_no_selection_declaration"
    population: Literal["require_scope_declaration", "require_complete_partition_and_total"]
    missing_evidence: Literal["insufficient_evidence"] = "insufficient_evidence"


class DeclarationRule(ContractModel):
    context_role: ContextRole
    required_types: Annotated[list[DeclarationType], Field(min_length=1)]
    accepted_issuer_kinds: Annotated[list[IssuerKind], Field(min_length=1)]
    accepted_issuer_refs: Annotated[list[NonEmptyStr], Field(min_length=1)]
    accepted_evidence_grades: Annotated[list[EvidenceGrade], Field(min_length=1)]
    require_result_binding: bool = True
    require_context_digest_binding: bool = True
    require_scope_binding: bool = True


class UnitRules(ContractModel):
    require_known_unit: bool = True
    require_known_scale: bool = True
    relationship: Literal["same_unit_and_scale"] = "same_unit_and_scale"
    conversion: Literal["forbid"] = "forbid"
    unknown_unit: Literal["insufficient_evidence"] = "insufficient_evidence"


class LimitationRules(ContractModel):
    unresolved_upstream: Literal["reject"] = "reject"
    free_text_interpretation: Literal["forbid"] = "forbid"
    retain_upstream_limitations: bool = True


class FormulaReference(ContractModel):
    output_key: FormulaId
    formula_id: FormulaId
    formula_version: ContractVersion = "1"
    input_roles: Annotated[list[ContextRole], Field(min_length=2, max_length=2)]

    @model_validator(mode="after")
    def fixed_output_identity(self) -> Self:
        if self.output_key != self.formula_id:
            raise ValueError("V1 output keys must reference their fixed formula")
        return self


class AuthorizedRevisionPair(ContractModel):
    """An explicit ordered authorization, not a caller's shared group label."""

    left_dataset_ref: NonEmptyStr
    left_revision_ref: NonEmptyStr
    right_dataset_ref: NonEmptyStr
    right_revision_ref: NonEmptyStr


class SnapshotRules(ContractModel):
    relationship: Literal["same_revision", "authorized_revision_pair"]
    require_revision_evidence: bool = True
    captured_at_as_revision_proof: Literal["forbid"] = "forbid"
    missing_revision: Literal["insufficient_evidence"] = "insufficient_evidence"
    authorized_revision_pairs: list[AuthorizedRevisionPair] = Field(default_factory=list)


class BaseSignalPolicy(ContractModel):
    policy_id: NonEmptyStr
    version: ContractVersion = "1"
    definition_digest: NonEmptyStr
    signal_type: SignalType
    supported_contract_versions: SupportedContractVersions
    required_roles: Annotated[list[ContextRole], Field(min_length=2, max_length=2)]
    metric_rules: Annotated[list[MetricRule], Field(min_length=2, max_length=2)]
    relationship_rules: Annotated[list[RelationshipRule], Field(min_length=1)]
    grain_rules: Annotated[list[GrainRule], Field(min_length=2, max_length=2)]
    key_rules: Annotated[list[KeyRule], Field(min_length=1)]
    time_rules: TimeRules
    filter_rules: FilterRules
    numeric_rules: NumericRules
    missing_rules: MissingRules
    duplicate_rules: DuplicateRules
    completeness_rules: CompletenessRules
    declaration_rules: Annotated[list[DeclarationRule], Field(min_length=2, max_length=2)]
    unit_rules: UnitRules
    limitation_rules: LimitationRules
    formula_refs: Annotated[list[FormulaReference], Field(min_length=1, max_length=2)]
    snapshot_rules: SnapshotRules

    @model_validator(mode="after")
    def internally_consistent_definition(self) -> Self:
        # These checks inspect only the rule definition. They do not establish
        # that any input has the required sources, periods, coverage or units.
        role_pairs = {
            "monthly_regional_target_attainment": ["actual", "target"],
            "regional_sales_change": ["current", "baseline"],
            "product_contribution": ["parts", "total"],
        }
        output_keys = {
            "monthly_regional_target_attainment": ["attainment_rate"],
            "regional_sales_change": ["absolute_change", "change_rate"],
            "product_contribution": ["contribution_rate"],
        }
        if self.required_roles != role_pairs[self.signal_type]:
            raise ValueError("required_roles must match the Signal's fixed ordered role pair")
        for rules in (
            self.metric_rules, self.grain_rules, self.time_rules.sources,
            self.filter_rules.roles, self.declaration_rules,
        ):
            if [rule.context_role for rule in rules] != self.required_roles:
                raise ValueError("role-specific rules must cover the fixed ordered role pair exactly")
        metric_ids = {rule.context_role: rule.metric_id for rule in self.metric_rules}
        for rule in self.relationship_rules:
            if [rule.left_role, rule.right_role] != self.required_roles:
                raise ValueError("a relationship must refer to the fixed ordered role pair")
            if rule.left_metric_id != metric_ids[rule.left_role] or rule.right_metric_id != metric_ids[rule.right_role]:
                raise ValueError("relationship metric references must match declared metric rules")
        components = [(rule.domain_id, rule.component_id) for rule in self.key_rules]
        if len(components) != len(set(components)):
            raise ValueError("business key components must be unique")
        for rule in self.key_rules:
            if any(source.context_role not in self.required_roles for source in rule.sources):
                raise ValueError("a key source cannot refer to an undeclared context role")
        unique_roles = self.duplicate_rules.source_uniqueness_required_roles
        if len(unique_roles) != len(set(unique_roles)) or any(role not in self.required_roles for role in unique_roles):
            raise ValueError("source uniqueness rules need distinct declared roles")
        if [ref.output_key for ref in self.formula_refs] != output_keys[self.signal_type]:
            raise ValueError("formula_refs must match the Signal's fixed ordered outputs")
        if any(ref.input_roles != self.required_roles for ref in self.formula_refs):
            raise ValueError("formula input roles must match the Signal's fixed ordered role pair")
        return self


class TargetAttainmentPolicy(BaseSignalPolicy):
    signal_type: Literal["monthly_regional_target_attainment"] = "monthly_regional_target_attainment"
    required_roles: Annotated[list[ContextRole], Field(min_length=2, max_length=2)] = Field(
        default_factory=lambda: ["actual", "target"]
    )


class SalesChangePolicy(BaseSignalPolicy):
    signal_type: Literal["regional_sales_change"] = "regional_sales_change"
    required_roles: Annotated[list[ContextRole], Field(min_length=2, max_length=2)] = Field(
        default_factory=lambda: ["current", "baseline"]
    )


class ProductContributionPolicy(BaseSignalPolicy):
    signal_type: Literal["product_contribution"] = "product_contribution"
    required_roles: Annotated[list[ContextRole], Field(min_length=2, max_length=2)] = Field(
        default_factory=lambda: ["parts", "total"]
    )
