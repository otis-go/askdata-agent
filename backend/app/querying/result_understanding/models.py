"""SQL-derived semantics and explicitly bound Schema metadata; no inference."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..result_contract import ExecutionData


SemanticStatus = Literal["resolved", "unsupported", "unknown"]
Aggregation = Literal["SUM", "AVG", "COUNT"]
QueryGrain = Literal["grouped", "global_aggregate"]
FilterValueType = Literal[
    "string", "integer", "numeric_text", "boolean", "null",
    "date_literal", "timestamp_literal",
]


class LineageSource(BaseModel):
    """A syntactic source, not proof of field existence or business meaning.

    ``database`` comes only from the execution contract. ``field=None`` is
    reserved for relation-level COUNT(*) / COUNT(literal), never a fake '*'
    column. Missing database identity remains None.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    database: str | None
    table: str
    field: str | None


class SchemaBinding(BaseModel):
    """Metadata looked up by lineage identity, never by a display name.

    source retains the lineage identity/spelling. default_aggregation is the
    Schema's default, not the SQL operation. Missing metadata remains None;
    aliases=[] is a known empty declaration, distinct from missing aliases.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    source: LineageSource
    label: str | None = None
    aliases: list[str] | None = None
    description: str | None = None
    role: str | None = None
    default_aggregation: str | None = None


class QueryBindingsInfo(BaseModel):
    """Schema evidence for referenced fields, not additional output columns.

    Scope is SELECT/WHERE/HAVING/plain GROUP BY in the V1 SQL subset. Bindings
    are all-or-nothing: unknown/unsupported has no consumable bindings. An empty
    list is only known absence of field metadata when status is resolved (for
    example COUNT(*)). This is not an overall SQL-understanding status.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    bindings: list[SchemaBinding] = Field(default_factory=list)
    status: SemanticStatus
    limitations: list[str] = Field(default_factory=list)


class ColumnSemantic(BaseModel):
    """One entry per result column, matched by ordinal rather than output name.

    expression is DuckDB SQL rendered from the projection without its outer AS
    alias. It is not evaluated. lineage=[] means a known constant with no field
    dependencies; lineage=None means no supported lineage was established.
    resolved certifies only this module's narrow structural analysis, not SQL
    validity, data fidelity, aggregation correctness, or business semantics.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    column_id: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    output_name: str
    expression: str | None = None
    lineage: list[LineageSource] | None = None
    aggregation: Aggregation | None = None
    status: SemanticStatus
    reason: str | None = None
    # Added only by explicit Schema binding. status still describes SQL lineage;
    # a resolved column may have no binding if its source is absent/ambiguous.
    schema_bindings: list[SchemaBinding] = Field(default_factory=list)


class GrainInfo(BaseModel):
    """Query grouping evidence, not entity uniqueness or population coverage.

    business_grain contains ordered Schema labels for the proven grouping
    sources, never keys inferred from roles. None means unavailable; [] means
    known absence of grouping expressions/columns (a global aggregate).
    resolved describes structural grain even if business labels are missing.
    A global aggregate does not promise an output row: HAVING can remove it.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    query_grain: QueryGrain | None = None
    business_grain: list[str] | None = None
    grouping_expressions: list[str] | None = None
    grouping_columns: list[LineageSource] | None = None
    status: SemanticStatus
    limitations: list[str] = Field(default_factory=list)


class FilterLiteral(BaseModel):
    """A literal captured from the original AST, never parsed from SQL text."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    value: str | int | bool | None
    value_type: FilterValueType
    value_sql: str


class FilterCondition(BaseModel):
    """A scoped predicate, not an evaluated truth or a business conclusion.

    expression/value_sql are rendered from the supplied AST, not verbatim SQL
    substrings. Numeric fractions/exponents stay exact text (numeric_text).
    DATE/TIMESTAMP literals retain text only: no calendar/range interpretation.
    SQL NULL has value_type='null', distinct from an unavailable value.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    scope: Literal["WHERE", "HAVING", "JOIN ON", "QUALIFY"]
    expression: str
    operator: Literal["=", "!=", ">", ">=", "<", "<=", "BETWEEN"] | None = None
    lineage: list[LineageSource] | None = None
    value: str | int | bool | None = None
    value_type: FilterValueType | None = None
    value_sql: str | None = None
    # BETWEEN keeps both literals, without rewriting it into invented SQL.
    lower_bound: FilterLiteral | None = None
    upper_bound: FilterLiteral | None = None
    aggregation_expression: str | None = None
    schema_bindings: list[SchemaBinding] = Field(default_factory=list)
    status: SemanticStatus
    limitations: list[str] = Field(default_factory=list)


class FilterInfo(BaseModel):
    """Only WHERE/HAVING go in filters, always with their original scope.

    Each supported scope is an AND conjunction, never a conjunction across
    scopes. Unsupported OR/NOT scopes are preserved whole, not flattened.
    JOIN ON/QUALIFY live separately in excluded_scopes and remain unsupported.
    Inspect status before treating this as complete predicate understanding:
    filters=[] on an unsupported/unknown AST does not prove absence of filters.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    filters: list[FilterCondition] = Field(default_factory=list)
    excluded_scopes: list[FilterCondition] = Field(default_factory=list)
    where_expression: str | None = None
    having_expression: str | None = None
    status: SemanticStatus
    limitations: list[str] = Field(default_factory=list)


class TimeInclusivity(BaseModel):
    """Each endpoint has its own inclusivity; an absent endpoint is unknown."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    lower: bool | None = None
    upper: bool | None = None


class TimeConstraintInfo(BaseModel):
    """One source/scope's explicit temporal predicates, not result coverage.

    Bounds retain ISO date or month literal precision, never expand a month
    into calendar days. is_empty checks explicit reversed/equal-exclusive
    bounds only: False means no such contradiction was found, not that a
    physical DATE domain has a member or that rows exist. Unknown stays None.
    resolved is structural/declared time-role evidence, not physical dtype or
    a guarantee about implicit database casts or populated date coverage.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    source_field: LineageSource | None = None
    operator: Literal["=", ">", ">=", "<", "<=", "BETWEEN", "AND"] | None = None
    lower: str | None = None
    upper: str | None = None
    inclusive: TimeInclusivity = Field(default_factory=TimeInclusivity)
    scope: Literal["WHERE", "HAVING", "JOIN ON", "QUALIFY"] | None = None
    expression: str | None = None
    status: SemanticStatus
    limitations: list[str] = Field(default_factory=list)
    precision: Literal["date", "month"] | None = None
    schema_bindings: list[SchemaBinding] = Field(default_factory=list)
    is_empty: bool | None = None


class BusinessContext(BaseModel):
    """Versioned assembly of execution facts and supported semantic evidence.

    Build through builder.build_business_context. Execution is a detached copy,
    not a newly inferred result. column_semantics describes actual output
    ordinals only; query_bindings can also describe unprojected predicate fields.
    understanding_status covers the required V1 semantic evidence, never data
    fidelity, SQL validity, row coverage or business-population completeness.
    Empty time_constraints does not assert all-time coverage.

    Frozen prevents field reassignment, not mutation of nested lists. The public
    builder isolates these lists from the input and from other build results.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    version: Literal["1"] = "1"
    result_id: str = Field(min_length=1)
    result_contract_version: str = Field(min_length=1)
    execution: ExecutionData
    column_semantics: list[ColumnSemantic]
    query_bindings: QueryBindingsInfo
    grain: GrainInfo
    filters: FilterInfo
    time_constraints: list[TimeConstraintInfo]
    understanding_status: SemanticStatus
    limitations: list[str] = Field(default_factory=list)


__all__ = [
    "Aggregation", "BusinessContext", "ColumnSemantic", "FilterCondition", "FilterInfo", "FilterLiteral",
    "FilterValueType", "GrainInfo", "TimeConstraintInfo", "TimeInclusivity",
    "LineageSource", "QueryBindingsInfo", "QueryGrain", "SchemaBinding", "SemanticStatus",
]
