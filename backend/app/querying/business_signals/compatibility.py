"""Deterministic Context qualification, without row alignment or formulas.

SQL/expression strings are opaque. Content digests bind supplied evidence;
they neither authenticate it nor generate Signal identity. Calendar checks use
only supplied Gregorian literals, never a clock or database.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import re

from ..result_contract import ColumnMetadata, ExecutionData
from ..result_understanding.models import BusinessContext, LineageSource
from .models import (
    ContextCompatibility, ContextRole, DeclarationRef, InputDeclaration, Issue, Operation,
    NormalizedFilter, NormalizedPeriod, RoleMetricRef, RolePeriod,
    SignalInput, SignalSelection, TypedFilterValue,
)
from .numeric import check_numeric_column
from .receipt_binding import bind_receipt
from .policies import (
    BaseSignalPolicy, ProductContributionPolicy, SalesChangePolicy,
    TargetAttainmentPolicy,
)


_RANK = {"compatible": 0, "insufficient_evidence": 1, "incompatible_context": 2, "unsupported": 3}
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
_INTEGER_DTYPES = frozenset({
    "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
    "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT",
})


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def _digest(label: str, value: object) -> str:
    return label + ":sha256:" + hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _known_text(value: object) -> bool:
    # Blank references cannot prove a business fact. Valid identities retain
    # their original bytes for comparison; this is not normalization.
    return type(value) is str and bool(value.strip())


def context_digest(context: BusinessContext) -> str:
    """V1 content binding, including opaque SQL and ordered canonical rows.

    This is not SQL equivalence, proof of provenance, or a Signal ID. V1 native
    JSON preserves int/float distinctions and signed zero in serialized text.
    """
    if not isinstance(context, BusinessContext):
        raise TypeError("context must be BusinessContext")
    return _digest("context-v1", context.model_dump(mode="python"))


def _source(source: object) -> tuple | None:
    if source is None:
        return None
    database, table, name = source.database, source.table, source.field
    if not all(type(item) is str and item.strip() for item in (database, table, name)):
        return None
    return database, table.translate(_ASCII_LOWER), name.translate(_ASCII_LOWER)


def _condition_data(condition: object) -> dict:
    return {
        "scope": condition.scope, "operator": condition.operator,
        "sources": sorted([_source(item) for item in condition.lineage or []], key=_json),
        "lineage_known": condition.lineage is not None,
        "value": condition.value, "value_type": condition.value_type,
        "lower": None if condition.lower_bound is None else {
            "value": condition.lower_bound.value, "value_type": condition.lower_bound.value_type,
        },
        "upper": None if condition.upper_bound is None else {
            "value": condition.upper_bound.value, "value_type": condition.upper_bound.value_type,
        },
        "status": condition.status,
    }


def filter_scope_digest(context: BusinessContext) -> str:
    """Bind structured WHERE facts, including time, independent of AND order.

    Original source identities and literal types remain distinct. Expression
    and value_sql are not parsed or used for predicate equivalence.
    """
    if not isinstance(context, BusinessContext):
        raise TypeError("context must be BusinessContext")
    conditions = sorted({_json(_condition_data(item)) for item in context.filters.filters if item.scope == "WHERE"})
    return _digest("filter-v1", {"status": context.filters.status, "conditions": conditions})


def _date_parts(value: object) -> tuple[int, int, int]:
    if type(value) is not str or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ValueError("expected an exact ISO date")
    year, month, day = (int(part) for part in value.split("-"))
    if not 1 <= year <= 9999 or not 1 <= month <= 12:
        raise ValueError("invalid Gregorian year or month")
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days = (31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    if not 1 <= day <= days[month - 1]:
        raise ValueError("invalid Gregorian day")
    return year, month, day


def _month_bounds(value: str) -> tuple[str, str]:
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}", value) is None:
        raise ValueError("expected an exact month")
    year, month, _ = _date_parts(value + "-01")
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    if next_year > 9999:
        raise ValueError("month is outside the bounded V1 calendar")
    return value + "-01", f"{next_year:04d}-{next_month:02d}-01"


def _full_month(period: NormalizedPeriod) -> bool:
    return (
        period.lower.endswith("-01") and period.lower_inclusive and not period.upper_inclusive
        and _month_bounds(period.lower[:7]) == (period.lower, period.upper)
    )


@dataclass
class _Role:
    role: str
    supplied: SignalInput
    digest: str
    metric_column: ColumnMetadata | None = None
    metric_source: LineageSource | None = None
    metric_ref: RoleMetricRef | None = None
    time_source: LineageSource | None = None
    period: NormalizedPeriod | None = None
    raw_time: object | None = None
    filters: list[NormalizedFilter] = field(default_factory=list)
    filters_complete: bool = False
    sources: set[tuple] = field(default_factory=set)
    declarations: dict[str, InputDeclaration] = field(default_factory=dict)
    key_sources: list[tuple] = field(default_factory=list)
    eligible_version: bool = True

    @property
    def context(self) -> BusinessContext:
        return self.supplied.context


class _Check:
    def __init__(self, policy: BaseSignalPolicy, operation: str):
        self.policy = policy
        self.operation = operation
        self.status = "compatible"
        self.issues: list[Issue] = []
        self.roles: list[_Role] = []

    def add(self, status: str, code: str, role: _Role | None, path: str, message: str) -> None:
        if _RANK[status] > _RANK[self.status]:
            self.status = status
        self.issues.append(Issue(
            code=code, stage="compatibility", context_role=None if role is None else role.role,
            result_id=None if role is None else role.context.result_id,
            evidence_paths=[path], severity="warning" if status == "insufficient_evidence" else "error",
            message=message,
        ))

    def upstream(self, value: object, role: _Role, path: str) -> bool:
        status = value.status
        if status not in ("resolved", "unknown", "unsupported"):
            raise ValueError("invalid semantic status")
        if status != "resolved":
            self.add("unsupported" if status == "unsupported" else "insufficient_evidence",
                     "UNSUPPORTED_UNDERSTANDING" if status == "unsupported" else "UNKNOWN_UNDERSTANDING",
                     role, path + ".status", "Required upstream semantics are not resolved.")
        limitations = getattr(value, "limitations", [])
        if limitations:
            self.add("unsupported" if status == "unsupported" else "insufficient_evidence",
                     "UPSTREAM_LIMITATIONS", role, path + ".limitations", "Unresolved upstream limitations remain.")
        return status == "resolved" and not limitations

    def structure(self, role: _Role) -> None:
        context = role.context
        if type(context.result_id) is not str or not context.result_id.strip():
            raise ValueError("result_id must be nonempty")
        supported = self.policy.supported_contract_versions
        for name, versions in (("version", supported.business_context), ("result_contract_version", supported.result_contract)):
            if getattr(context, name) not in versions:
                self.add("unsupported", "UNSUPPORTED_CONTEXT_VERSION", role, name, "Context version is not supported by Policy.")
                role.eligible_version = False
        if not role.eligible_version:
            return
        # Structural validation only; no SQL readers or business row values.
        ExecutionData.model_validate(context.execution.model_dump())
        SignalSelection.model_validate(role.supplied.selection.model_dump())
        execution = context.execution
        if execution.success is not True:
            self.add("incompatible_context" if execution.success is False else "insufficient_evidence",
                     "FAILED_EXECUTION" if execution.success is False else "UNKNOWN_EXECUTION",
                     role, "execution.success", "A successful execution is required.")
        if execution.rows is None or execution.columns is None:
            self.add("insufficient_evidence", "UNKNOWN_EXECUTION_PAYLOAD", role, "execution", "Rows and columns must be supplied.")
        if context.understanding_status not in ("resolved", "unknown", "unsupported"):
            raise ValueError("invalid overall understanding status")
        if context.understanding_status != "resolved":
            self.add("unsupported" if context.understanding_status == "unsupported" else "insufficient_evidence",
                     "UNSUPPORTED_UNDERSTANDING" if context.understanding_status == "unsupported" else "UNKNOWN_UNDERSTANDING",
                     role, "understanding_status", "Required Context understanding is not resolved.")
        if context.limitations:
            self.add("unsupported" if context.understanding_status == "unsupported" else "insufficient_evidence",
                     "UPSTREAM_LIMITATIONS", role, "limitations", "Context limitations are retained, not interpreted.")
        self.upstream(context.query_bindings, role, "query_bindings")
        provenance = execution.provenance
        if provenance is not None and (
            provenance.sql_submitted is False and execution.success is True
            or provenance.submitted_sql is not None and execution.sql is not None and provenance.submitted_sql != execution.sql
        ):
            self.add("incompatible_context", "EXECUTION_PROVENANCE_CONFLICT", role, "execution.provenance", "Captured execution provenance conflicts with execution facts.")
        if execution.completeness == "partial_query_output" or execution.truncated is True:
            self.add("incompatible_context", "PARTIAL_QUERY_OUTPUT", role, "execution.completeness", "A partial or truncated output is not eligible.")
        if execution.completeness is None or execution.truncated is None or execution.returned_rows is None or execution.total_rows is None:
            self.add("insufficient_evidence", "UNKNOWN_COMPLETENESS", role, "execution", "Completeness, truncation and counts must be known.")
        if execution.rows == []:
            self.add("insufficient_evidence", "NO_OBSERVED_ROWS", role, "execution.rows", "No observed rows are available; no key is inferred missing.")

    def semantics(self, role: _Role, index: int) -> None:
        context, selection = role.context, role.supplied.selection
        for binding in context.query_bindings.bindings:
            if (identity := _source(binding.source)) is not None:
                role.sources.add(identity)
        for item in context.column_semantics:
            role.sources.update(identity for source in item.lineage or [] if (identity := _source(source)) is not None)
        for condition in context.filters.filters:
            role.sources.update(identity for source in condition.lineage or [] if (identity := _source(source)) is not None)
        role.key_sources = [_source(source.source) for key in self.policy.key_rules for source in key.sources if source.context_role == role.role]
        columns = context.execution.columns
        if columns is None:
            return
        metadata = {item.id: item for item in columns}
        requested = [selection.metric_column_id, *selection.key_column_ids.values(), *selection.auxiliary_column_ids.values()]
        if any(item not in metadata for item in requested):
            raise ValueError("selection column_id is not present in execution.columns")
        if len(set(selection.key_column_ids.values())) != len(selection.key_column_ids):
            raise ValueError("key components must select distinct column identities")
        if selection.metric_column_id in selection.key_column_ids.values():
            self.add("incompatible_context", "METRIC_KEY_OVERLAP", role, "selection", "V1 SUM metrics cannot also be grouping key columns.")
        by_id = {}
        for item in context.column_semantics:
            if item.column_id in by_id or item.column_id not in metadata or item.ordinal != metadata[item.column_id].ordinal:
                raise ValueError("column semantics have conflicting column identity or ordinal")
            by_id[item.column_id] = item
        role.metric_column = metadata[selection.metric_column_id]
        metric_rule = self.policy.metric_rules[index]
        semantic = by_id.get(selection.metric_column_id)
        match_status = "unknown"
        if semantic is None:
            self.add("insufficient_evidence", "MISSING_COLUMN_SEMANTIC", role, "column_semantics", "Selected metric semantic evidence is missing.")
        elif self.upstream(semantic, role, f"column_semantics[{semantic.ordinal}]"):
            identities = [_source(source) for source in semantic.lineage or []]
            if semantic.lineage is None or None in identities:
                self.add("insufficient_evidence", "METRIC_SOURCE_UNKNOWN", role, "column_semantics.lineage", "A complete metric field identity is required.")
            elif len(identities) != 1 or identities[0] not in [_source(source) for source in metric_rule.allowed_sources]:
                match_status = "incompatible"
                self.add("incompatible_context", "METRIC_SOURCE_MISMATCH", role, "column_semantics.lineage", "Metric source is not explicitly authorized by Policy.")
            else:
                role.metric_source = semantic.lineage[0]
                match_status = "matched"
                if metric_rule.require_schema_binding:
                    matches = [binding for binding in semantic.schema_bindings if _source(binding.source) == identities[0]]
                    if len(matches) != 1:
                        match_status = "unknown"
                        self.add("insufficient_evidence", "METRIC_BINDING_UNKNOWN", role, "column_semantics.schema_bindings", "A unique source-matched SchemaBinding is required.")
            if semantic.aggregation not in metric_rule.allowed_aggregations:
                match_status = "incompatible"
                self.add("incompatible_context", "AGGREGATION_MISMATCH", role, "column_semantics.aggregation", "Actual aggregation differs from the allowed operation.")
        role.metric_ref = RoleMetricRef(
            context_role=role.role, metric_id=metric_rule.metric_id, mapping_id=metric_rule.mapping_id,
            match_status=match_status, source_fields=None if semantic is None else deepcopy(semantic.lineage),
        )
        numeric = check_numeric_column(role.metric_column, self.policy.numeric_rules)
        if numeric.status != "ready":
            self.add(numeric.status, numeric.code, role, f"execution.columns[{role.metric_column.ordinal}]", numeric.message)
        grain_rule = self.policy.grain_rules[index]
        grain_ok = self.upstream(context.grain, role, "grain")
        actual_grain = context.grain.grouping_columns
        if grain_ok:
            if actual_grain is None or context.grain.query_grain is None or any(_source(item) is None for item in actual_grain):
                self.add("insufficient_evidence", "UNKNOWN_GRAIN", role, "grain", "Grouping evidence is incomplete.")
            elif context.grain.query_grain != grain_rule.grain or sorted(_source(item) for item in actual_grain) != sorted(_source(item) for item in grain_rule.grouping_sources):
                self.add("incompatible_context", "GRAIN_MISMATCH", role, "grain", "Actual grouping sources differ from Policy; no regrouping is performed.")
        if grain_rule.grain == "global_aggregate" and context.execution.rows is not None and len(context.execution.rows) != 1:
            self.add("incompatible_context" if context.execution.rows else "insufficient_evidence", "GLOBAL_ROW_COUNT", role, "execution.rows", "A global denominator requires exactly one observed row.")
        required_keys = {rule.component_id: rule for rule in self.policy.key_rules if any(item.context_role == role.role for item in rule.sources)}
        if set(selection.key_column_ids) != set(required_keys):
            self.add("incompatible_context", "KEY_SELECTION_MISMATCH", role, "selection.key_column_ids", "Key selections must cover the Policy components exactly.")
        for component, rule in required_keys.items():
            source_rule = next(item for item in rule.sources if item.context_role == role.role)
            column_id = selection.key_column_ids.get(component)
            if column_id is None:
                continue
            column, key_semantic = metadata[column_id], by_id.get(column_id)
            if key_semantic is None:
                self.add("insufficient_evidence", "KEY_SEMANTIC_UNKNOWN", role, "column_semantics", "Key semantic evidence is missing.")
                continue
            if self.upstream(key_semantic, role, f"column_semantics[{key_semantic.ordinal}]"):
                identities = [_source(source) for source in key_semantic.lineage or []]
                if key_semantic.lineage is None or None in identities:
                    self.add("insufficient_evidence", "KEY_SOURCE_UNKNOWN", role, "column_semantics.lineage", "Key source identity is unknown.")
                elif identities != [_source(source_rule.source)] or key_semantic.aggregation is not None or _source(source_rule.source) not in [_source(item) for item in grain_rule.grouping_sources]:
                    self.add("incompatible_context", "KEY_SOURCE_MISMATCH", role, "column_semantics", "Key is not the authorized unaggregated grouping source.")
            if column.representation_status == "unsupported":
                self.add("unsupported", "KEY_REPRESENTATION_UNSUPPORTED", role, "execution.columns", "Key representation is unsupported.")
            elif column.representation_status == "lossy":
                self.add("incompatible_context", "KEY_REPRESENTATION_LOSSY", role, "execution.columns", "Key representation is lossy.")
            elif column.dtype is None or column.value_encoding is None or column.representation_status is None:
                self.add("insufficient_evidence", "KEY_METADATA_UNKNOWN", role, "execution.columns", "Key metadata is incomplete.")
            elif column.value_encoding == "native_json" and column.dtype in _INTEGER_DTYPES | {"VARCHAR"} and not (column.dtype == "VARCHAR" if rule.value_type == "string" else column.dtype in _INTEGER_DTYPES):
                self.add("incompatible_context", "KEY_TYPE_MISMATCH", role, "execution.columns", "Known key dtype conflicts with the Policy value type.")
            elif column.value_encoding != "native_json" or not (column.dtype == "VARCHAR" if rule.value_type == "string" else column.dtype in _INTEGER_DTYPES):
                self.add("unsupported", "KEY_TYPE_UNSUPPORTED", role, "execution.columns", "Key dtype and codec do not support the declared value type.")

    def time(self, role: _Role, index: int) -> None:
        rule = self.policy.time_rules.sources[index]
        constraints = role.context.time_constraints
        if not constraints:
            self.add("insufficient_evidence", "TIME_UNKNOWN", role, "time_constraints", "An explicit bounded period is required.")
            return
        usable = [item for item in constraints if self.upstream(item, role, "time_constraints")]
        if len(usable) != len(constraints):
            return
        if len(usable) != 1:
            self.add("incompatible_context", "TIME_AMBIGUOUS", role, "time_constraints", "V1 requires one unambiguous authorized time source and scope.")
            return
        item = usable[0]
        if _source(item.source_field) is None:
            self.add("insufficient_evidence", "TIME_SOURCE_UNKNOWN", role, "time_constraints.source_field", "Time source identity is incomplete.")
            return
        if _source(item.source_field) not in [_source(source) for source in rule.allowed_sources] or item.scope != "WHERE":
            self.add("incompatible_context", "TIME_SOURCE_MISMATCH", role, "time_constraints", "Time source or scope is not authorized.")
            return
        role.time_source, role.raw_time = item.source_field, item
        role.sources.add(_source(item.source_field))
        if item.lower is None or item.upper is None or item.inclusive.lower is None or item.inclusive.upper is None or item.is_empty is None or item.precision is None:
            self.add("insufficient_evidence", "TIME_BOUNDS_UNKNOWN", role, "time_constraints", "Both period bounds and their semantics must be known.")
            return
        if item.is_empty or item.precision != rule.accepted_precision:
            self.add("incompatible_context", "TIME_PERIOD_MISMATCH", role, "time_constraints", "Time precision or empty range violates Policy.")
            return
        try:
            if rule.accepted_range == "month_equality":
                if item.precision != "month" or item.operator != "=" or item.lower != item.upper or not (item.inclusive.lower and item.inclusive.upper):
                    raise ValueError("expected an explicit month equality")
                lower, upper = _month_bounds(item.lower)
                inc_lower, inc_upper = True, False
            else:
                if item.precision != "date":
                    raise ValueError("expected date bounds")
                _date_parts(item.lower)
                _date_parts(item.upper)
                lower, upper = item.lower, item.upper
                inc_lower, inc_upper = item.inclusive.lower, item.inclusive.upper
                if lower > upper or lower == upper and not (inc_lower and inc_upper):
                    raise ValueError("empty or reversed date range")
            period = NormalizedPeriod(
                domain_id=rule.domain_id, calendar=self.policy.time_rules.calendar,
                precision="date", lower=lower, upper=upper,
                lower_inclusive=inc_lower, upper_inclusive=inc_upper,
            )
            if rule.accepted_range == "closed_open_month" and not _full_month(period):
                raise ValueError("expected a complete half-open calendar month")
            role.period = period
        except ValueError:
            self.add("incompatible_context", "TIME_PERIOD_MISMATCH", role, "time_constraints", "Explicit bounds do not meet the V1 calendar shape.")

    def filters(self, role: _Role, index: int) -> None:
        info = role.context.filters
        fully_known = self.upstream(info, role, "filters")
        if info.excluded_scopes or any(item.scope not in ("WHERE", "HAVING") for item in info.filters):
            self.add("unsupported", "UNSUPPORTED_FILTER_SCOPE", role, "filters.excluded_scopes", "Excluded filter scopes remain unsupported.")
        if info.having_expression is not None or any(item.scope == "HAVING" for item in info.filters):
            self.add("incompatible_context", "HAVING_NOT_ALLOWED", role, "filters", "HAVING is not eligible for the V1 Signals.")
        if info.where_expression is not None and not any(item.scope == "WHERE" for item in info.filters):
            self.add("insufficient_evidence", "FILTER_STRUCTURE_UNKNOWN", role, "filters", "A WHERE expression has no corresponding structured facts.")
        role_rule = self.policy.filter_rules.roles[index]
        time_rule = self.policy.time_rules.sources[index]
        time_conditions = []
        normalized = []
        captured_predicates = set()
        for item in info.filters:
            consumable = self.upstream(item, role, "filters.filters")
            if not consumable:
                fully_known = False
            if not consumable or item.scope != "WHERE":
                continue
            if item.aggregation_expression is not None:
                self.add("unsupported", "UNSUPPORTED_FILTER_AGGREGATION", role, "filters.filters", "Input filters must reference plain fields.")
                continue
            identities = [_source(source) for source in item.lineage or []]
            if len(identities) != 1 or identities[0] is None:
                fully_known = False
                self.add("insufficient_evidence", "FILTER_SOURCE_UNKNOWN", role, "filters.filters.lineage", "A complete single filter source is required.")
                continue
            if identities[0] in [_source(source) for source in time_rule.allowed_sources]:
                time_conditions.append(item)
                continue
            candidates = [rule for rule in role_rule.required_conditions if _source(rule.source) == identities[0]]
            domains = {rule.domain_id for rule in candidates}
            if len(domains) != 1:
                self.add("incompatible_context", "FILTER_MISMATCH", role, "filters.filters", "A non-time filter source lacks an explicit Policy mapping.")
                continue
            try:
                value = None if item.operator == "BETWEEN" else TypedFilterValue(value_type=item.value_type, value=item.value)
                lower = None if item.lower_bound is None else TypedFilterValue(value_type=item.lower_bound.value_type, value=item.lower_bound.value)
                upper = None if item.upper_bound is None else TypedFilterValue(value_type=item.upper_bound.value_type, value=item.upper_bound.value)
                condition = NormalizedFilter(
                    context_role=role.role, scope="WHERE", source_identity=next(iter(domains)),
                    operator=item.operator, value=value, lower_bound=lower, upper_bound=upper,
                )
                normalized.append(condition)
                captured_predicates.add((identities[0], _filter_signature(condition)))
            except ValueError:
                fully_known = False
                self.add("unsupported", "UNSUPPORTED_FILTER_LITERAL", role, "filters.filters", "Filter operator or typed literal is outside V1.")
        # AND order is irrelevant; no implication, coercion or expression parsing.
        by_signature = {_filter_signature(item): item for item in normalized}
        role.filters = [by_signature[key] for key in sorted(by_signature)]
        expected = {
            (_source(rule.source), _filter_signature(NormalizedFilter(
                context_role=role.role, scope=rule.scope, source_identity=rule.domain_id,
                operator=rule.operator, value=rule.value,
                lower_bound=rule.lower_bound, upper_bound=rule.upper_bound,
            ))) for rule in role_rule.required_conditions
        }
        role.filters_complete = fully_known
        if fully_known and captured_predicates != expected:
            self.add("incompatible_context", "FILTER_MISMATCH", role, "filters.filters", "The role's non-time conditions differ from Policy.")
        if not time_conditions or role.raw_time is None:
            self.add("insufficient_evidence", "TIME_FILTER_UNKNOWN", role, "filters.filters", "Time constraints must be supported by captured structured time predicates.")
            return
        if any(_source(item.lineage[0]) != _source(role.time_source) for item in time_conditions):
            self.add("incompatible_context", "TIME_FILTER_MISMATCH", role, "filters.filters", "Multiple time sources cannot be silently consumed.")
            return
        try:
            lower = upper = None
            incl_lower = incl_upper = None
            for item in time_conditions:
                lo, hi, il, iu = _time_predicate_bounds(item, role.raw_time.precision)
                if lo is not None:
                    if lower is None or lo > lower:
                        lower, incl_lower = lo, il
                    elif lo == lower:
                        incl_lower = incl_lower and il
                if hi is not None:
                    if upper is None or hi < upper:
                        upper, incl_upper = hi, iu
                    elif hi == upper:
                        incl_upper = incl_upper and iu
            expected_bounds = (role.raw_time.lower, role.raw_time.upper, role.raw_time.inclusive.lower, role.raw_time.inclusive.upper)
            if (lower, upper, incl_lower, incl_upper) != expected_bounds:
                self.add("incompatible_context", "TIME_FILTER_MISMATCH", role, "time_constraints", "Captured time predicates and TimeConstraintInfo disagree.")
        except ValueError:
            self.add("unsupported", "UNSUPPORTED_TIME_FILTER", role, "filters.filters", "A time predicate cannot be consumed using the approved literal domain.")

    def declarations(self, role: _Role, index: int) -> None:
        rule = self.policy.declaration_rules[index]
        selection = role.supplied.selection
        selected = {selection.metric_column_id, *selection.key_column_ids.values(), *selection.auxiliary_column_ids.values()}
        columns = {item.id for item in role.context.execution.columns or []}
        key_domains = {item.domain_id for item in self.policy.key_rules}
        grouped: dict[str, list[InputDeclaration]] = {}
        for declaration in sorted(role.supplied.declarations, key=lambda item: (item.declaration_type, item.declaration_id)):
            start = len(self.issues)
            path = f"declarations[{declaration.declaration_id}]"
            if declaration.version != "1":
                self.add("unsupported", "UNSUPPORTED_DECLARATION_VERSION", role, path + ".version", "Declaration version is unsupported.")
                continue
            if declaration.declaration_type not in InputDeclaration.model_fields["declaration_type"].annotation.__args__:
                self.add("unsupported", "UNSUPPORTED_DECLARATION_TYPE", role, path, "Declaration type is unsupported.")
                continue
            if not _known_text(declaration.context_digest):
                self.add("insufficient_evidence", "DECLARATION_DIGEST_UNKNOWN", role, path + ".context_digest", "Declaration content binding is missing.")
                continue
            # Validate structure after version handling; unknown versions must
            # not be collapsed into generic Pydantic input errors.
            InputDeclaration.model_validate(declaration.model_dump())
            if not all(_known_text(getattr(declaration, name)) for name in ("declaration_id", "issuer_ref", "basis_ref")):
                self.add("insufficient_evidence", "DECLARATION_REFERENCE_UNKNOWN", role, path, "Declaration identity, issuer and evidence basis must be known references.")
            if declaration.result_id != role.context.result_id:
                self.add("incompatible_context", "DECLARATION_RESULT_MISMATCH", role, path + ".result_id", "Declaration is bound to another execution.")
            if declaration.context_digest != role.digest:
                self.add("incompatible_context", "DECLARATION_DIGEST_MISMATCH", role, path + ".context_digest", "Declaration content binding does not match this Context.")
            if declaration.issuer_kind not in rule.accepted_issuer_kinds or declaration.issuer_ref not in rule.accepted_issuer_refs or declaration.evidence_grade not in rule.accepted_evidence_grades or declaration.declaration_type not in rule.required_types:
                self.add("insufficient_evidence", "UNTRUSTED_DECLARATION", role, path, "Declaration is not on the role's explicit Policy allowlist.")
            if role.context.execution.columns is None:
                self.add("insufficient_evidence", "DECLARATION_COLUMNS_UNKNOWN", role, path + ".column_ids", "Column binding cannot be verified without column metadata.")
            elif len(declaration.column_ids) != len(set(declaration.column_ids)) or not set(declaration.column_ids) <= columns:
                self.add("incompatible_context", "DECLARATION_COLUMNS_MISMATCH", role, path + ".column_ids", "Declared column identities are duplicate or absent.")
            if not selected <= set(declaration.column_ids):
                self.add("insufficient_evidence", "DECLARATION_COLUMNS_INCOMPLETE", role, path + ".column_ids", "Declaration must cover the explicit selected columns.")
            scope = declaration.scope
            scope_sources = {_source(source) for source in scope.source_fields}
            if not scope_sources or scope.period is None or not _known_text(scope.population_scope_ref) or not _known_text(scope.filter_scope_ref) or set(scope.key_domains) != key_domains or not all(_known_text(item) for item in scope.key_domains):
                self.add("insufficient_evidence", "DECLARATION_SCOPE_UNKNOWN", role, path + ".scope", "Source, period, population, filter and key-domain scope are required.")
            if not scope_sources <= role.sources:
                self.add("incompatible_context", "DECLARATION_SOURCE_SCOPE_MISMATCH", role, path + ".scope.source_fields", "Declaration scope contains sources absent from this Context.")
            if role.period is not None and scope.period is not None and scope.period != role.period:
                self.add("incompatible_context", "DECLARATION_PERIOD_MISMATCH", role, path + ".scope.period", "Declaration period differs from the approved Context period.")
            if _known_text(scope.filter_scope_ref) and scope.filter_scope_ref != filter_scope_digest(role.context):
                self.add("incompatible_context", "DECLARATION_FILTER_MISMATCH", role, path + ".scope.filter_scope_ref", "Declaration filtering scope is not bound to the captured predicates.")
            claim = getattr(declaration.claims, declaration.declaration_type)
            proof_fields = {
                "unit": ("unit_id", "unit_scale"), "time_domain": ("domain_id",),
                "population": ("population_scope_ref",),
                "snapshot_revision": ("dataset_ref", "revision_ref"),
                "metric_basis": ("metric_id", "counterpart_metric_id", "basis_id"),
            }.get(declaration.declaration_type, ())
            if not all(_known_text(getattr(claim, name)) for name in proof_fields):
                self.add("insufficient_evidence", "DECLARATION_CLAIM_UNKNOWN", role, path + ".claims", "Claim identities and proof references must be known, nonblank values.")
            claim_sources = {_source(source) for source in getattr(claim, "source_fields", [])}
            if not claim_sources <= scope_sources:
                self.add("incompatible_context", "DECLARATION_CLAIM_SCOPE_MISMATCH", role, path + ".claims", "Claim sources exceed the declaration scope.")
            if declaration.declaration_type == "unit" and role.metric_source is not None and claim_sources != {_source(role.metric_source)}:
                self.add("incompatible_context", "UNIT_SOURCE_MISMATCH", role, path + ".claims.unit", "Unit claim must name the selected metric source exactly.")
            if declaration.declaration_type == "time_domain":
                time_rule = self.policy.time_rules.sources[index]
                if role.time_source is not None and claim_sources != {_source(role.time_source)} or claim.domain_id != time_rule.domain_id or claim.precision != time_rule.accepted_precision or claim.calendar != self.policy.time_rules.calendar:
                    self.add("incompatible_context", "TIME_DOMAIN_MISMATCH", role, path + ".claims.time_domain", "Declared time domain differs from Policy and Context.")
                allowed_domains = {"date", "iso_date_text"} if time_rule.accepted_precision == "date" else {"iso_month_text"}
                if claim.comparison_domain not in allowed_domains or claim.timezone is not None:
                    self.add("unsupported", "UNSUPPORTED_TIME_DOMAIN", role, path + ".claims.time_domain", "V1 accepts declared day/month domains without timezone conversion.")
            if declaration.declaration_type == "population" and claim.population_scope_ref != scope.population_scope_ref:
                self.add("incompatible_context", "POPULATION_SCOPE_MISMATCH", role, path + ".claims.population", "Population claim and scope differ.")
            if declaration.declaration_type in ("source_key_uniqueness", "metric_basis") and not _known_text(scope.target_version):
                self.add("insufficient_evidence", "TARGET_VERSION_UNKNOWN", role, path + ".scope.target_version", "A target definition version is required.")
            if declaration.declaration_type == "source_key_uniqueness":
                required_sources = {*role.key_sources}
                if role.time_source is not None:
                    required_sources.add(_source(role.time_source))
                expected_domains = {item.domain_id for item in self.policy.key_rules} | {self.policy.time_rules.sources[index].domain_id}
                if role.time_source is None:
                    self.add("insufficient_evidence", "UNIQUENESS_SCOPE_UNKNOWN", role, path, "Source uniqueness needs an approved time source.")
                elif claim_sources != required_sources or set(claim.key_domains) != expected_domains:
                    self.add("incompatible_context", "UNIQUENESS_SCOPE_MISMATCH", role, path + ".claims", "Source uniqueness must cover exactly the key plus period fields.")
            if len(self.issues) == start:
                grouped.setdefault(declaration.declaration_type, []).append(declaration)
        for kind, declarations in grouped.items():
            definitions = {_json({"claims": item.claims.model_dump(), "scope": item.scope.model_dump()}) for item in declarations}
            if len(definitions) != 1:
                self.add("incompatible_context", "DECLARATION_CONFLICT", role, "declarations", "Trusted declarations of the same domain conflict.")
            else:
                role.declarations[kind] = declarations[0]
        required = set(rule.required_types) | {"unit", "time_domain", "row_selection", "population"}
        if role.role in self.policy.duplicate_rules.source_uniqueness_required_roles:
            required.add("source_key_uniqueness")
        if isinstance(self.policy, TargetAttainmentPolicy) and role.role == "target":
            required.update({"metric_basis", "source_key_uniqueness"})
        snapshot_ref = role.context.execution.provenance.snapshot_ref if role.context.execution.provenance is not None else None
        if self.policy.snapshot_rules.require_revision_evidence and not _known_text(snapshot_ref):
            required.add("snapshot_revision")
        if _known_text(snapshot_ref):
            required.discard("snapshot_revision")
        for kind in sorted(required - role.declarations.keys()):
            code = {"unit": "MISSING_UNIT_DECLARATION", "row_selection": "ROW_SELECTION_UNKNOWN", "snapshot_revision": "REVISION_UNKNOWN"}.get(kind, "MISSING_" + kind.upper() + "_DECLARATION")
            self.add("insufficient_evidence", code, role, "declarations", "A required trusted declaration is missing or unusable.")
        self.coverage(role)

    def coverage(self, role: _Role) -> None:
        declarations = role.declarations
        row_selection = declarations.get("row_selection")
        if row_selection is not None and row_selection.claims.row_selection.mode != "absent":
            self.add("incompatible_context", "ROW_SELECTION_PRESENT", role, "declarations.row_selection", "V1 excludes LIMIT, OFFSET, top-N and other result selection.")
        population = declarations.get("population")
        if population is not None:
            claim = population.claims.population
            if claim.coverage != "complete":
                self.add("incompatible_context" if claim.coverage == "incomplete" else "insufficient_evidence",
                         "POPULATION_INCOMPLETE" if claim.coverage == "incomplete" else "POPULATION_UNKNOWN",
                         role, "declarations.population", "Population coverage must be explicitly complete.")
            domains = {item.domain_id for item in self.policy.key_rules}
            if isinstance(self.policy, ProductContributionPolicy) and role.role == "parts" and set(claim.partition_key_domains) != domains:
                self.add("insufficient_evidence", "PARTITION_COVERAGE_UNKNOWN", role, "declarations.population", "Parts require complete partition evidence for the selected key domain.")
            for declaration in declarations.values():
                if declaration.scope.population_scope_ref != claim.population_scope_ref:
                    self.add("incompatible_context", "DECLARATION_POPULATION_MISMATCH", role, "declarations.scope", "Role declarations refer to different populations.")
        unique = declarations.get("source_key_uniqueness")
        if unique is not None and unique.claims.source_key_uniqueness.uniqueness != "unique":
            known_duplicate = unique.claims.source_key_uniqueness.uniqueness == "duplicate"
            self.add("incompatible_context" if known_duplicate else "insufficient_evidence",
                     "SOURCE_KEY_DUPLICATE" if known_duplicate else "SOURCE_UNIQUENESS_UNKNOWN",
                     role, "declarations.source_key_uniqueness", "Source uniqueness is not established; no result rows are deduplicated.")

    def cross(self) -> None:
        left, right = self.roles
        policy = self.policy
        relations = [rule for rule in policy.relationship_rules if rule.operation == self.operation]
        if self.operation != "align":
            if len(relations) != 1:
                self.add("incompatible_context", "RELATIONSHIP_NOT_AUTHORIZED", None, "policy.relationship_rules", "The requested operation needs one explicit metric relationship.")
            else:
                relation = relations[0]
                expected_relationship = "actual_to_target" if isinstance(policy, TargetAttainmentPolicy) else "equivalent"
                if relation.metric_relationship != expected_relationship:
                    self.add("incompatible_context", "METRIC_RELATIONSHIP_MISMATCH", None, "policy.relationship_rules", "Relationship kind does not match the Typed Policy's business operation.")
                if self.operation == "compare" and (relation.metric_relationship != "equivalent" or relation.left_metric_id != relation.right_metric_id):
                    self.add("incompatible_context", "METRIC_RELATIONSHIP_MISMATCH", None, "policy.relationship_rules", "Comparison requires the same authorized metric semantic.")
                if relation.metric_relationship == "equivalent" and relation.left_metric_id != relation.right_metric_id:
                    self.add("incompatible_context", "METRIC_RELATIONSHIP_MISMATCH", None, "policy.relationship_rules", "Equivalent metric IDs must agree.")
                for role in self.roles:
                    if role.metric_ref is not None:
                        role.metric_ref = role.metric_ref.model_copy(update={"relationship_id": relation.relationship_id})
        for key in policy.key_rules:
            source_roles = {item.context_role for item in key.sources}
            expected_roles = {left.role, right.role}
            if isinstance(policy, ProductContributionPolicy):
                expected_roles = {"parts"}
                if policy.grain_rules[1].total_broadcast != "allow_global_total" or policy.grain_rules[1].grain != "global_aggregate":
                    self.add("incompatible_context", "KEY_BROADCAST_NOT_AUTHORIZED", None, "policy.grain_rules", "S3 total broadcast must be explicitly authorized.")
            if source_roles != expected_roles:
                self.add("incompatible_context", "KEY_DOMAIN_NOT_AUTHORIZED", None, "policy.key_rules", "The Policy key domain must map all required roles.")
        if left.period is not None and right.period is not None:
            a, b = left.period, right.period
            try:
                if isinstance(policy, TargetAttainmentPolicy):
                    valid = policy.time_rules.relationship == "same_calendar_month" and _full_month(a) and _full_month(b) and (a.lower, a.upper) == (b.lower, b.upper)
                elif isinstance(policy, SalesChangePolicy):
                    ay, am, _ = _date_parts(a.lower)
                    by, bm, _ = _date_parts(b.lower)
                    valid = policy.time_rules.relationship == "adjacent_calendar_months" and _full_month(a) and _full_month(b) and ay * 12 + am == by * 12 + bm + 1 and a.domain_id == b.domain_id
                else:
                    valid = policy.time_rules.relationship == "same_bounded_period" and a == b
            except ValueError:
                valid = False
            if not valid:
                self.add("incompatible_context", "TIME_PERIOD_MISMATCH", None, "time_constraints", "Role periods do not meet the authorized time relationship.")
        if isinstance(policy, TargetAttainmentPolicy):
            self.target_basis(left, right)
            if policy.filter_rules.comparison == "mapped_equal" and left.filters_complete and right.filters_complete and {_filter_signature(item) for item in left.filters} != {_filter_signature(item) for item in right.filters}:
                self.add("incompatible_context", "FILTER_MISMATCH", None, "policy.filter_rules.comparison", "Policy requires equality of all mapped non-time filters.")
        elif policy.filter_rules.comparison != "mapped_equal" or policy.filter_rules.require_metric_basis_declaration:
            self.add("unsupported", "UNSUPPORTED_FILTER_POLICY", None, "policy.filter_rules", "V1 metric-basis filter bridging is supported only for actual/target roles.")
        elif left.filters_complete and right.filters_complete and {_filter_signature(item) for item in left.filters} != {_filter_signature(item) for item in right.filters}:
            self.add("incompatible_context", "FILTER_MISMATCH", None, "filters", "Mapped non-time filter signatures differ across roles.")
        units = [role.declarations.get("unit") for role in self.roles]
        if all(units):
            a, b = [item.claims.unit for item in units]
            if (a.unit_id, a.unit_scale) != (b.unit_id, b.unit_scale):
                self.add("incompatible_context", "UNIT_MISMATCH", None, "declarations.unit", "Known units and scales must match; no conversion is performed.")
        populations = [role.declarations.get("population") for role in self.roles]
        if all(populations) and populations[0].claims.population.population_scope_ref != populations[1].claims.population.population_scope_ref:
            self.add("incompatible_context", "POPULATION_SCOPE_MISMATCH", None, "declarations.population", "Contexts refer to different declared business populations.")
        self.revisions()

    def target_basis(self, actual: _Role, target: _Role) -> None:
        declaration = target.declarations.get("metric_basis")
        if declaration is None:
            return
        claim = declaration.claims.metric_basis
        relations = [rule for rule in self.policy.relationship_rules if rule.metric_relationship == "actual_to_target" and rule.relationship_id == claim.basis_id]
        actual_metric, target_metric = [item.metric_id for item in self.policy.metric_rules]
        if len(relations) != 1 or (claim.metric_id, claim.counterpart_metric_id) != (target_metric, actual_metric):
            self.add("incompatible_context", "METRIC_BASIS_MISMATCH", target, "declarations.metric_basis", "The target basis must match the Policy relationship and metric identities.")
        actual_conditions = self.policy.filter_rules.roles[0].required_conditions
        target_conditions = self.policy.filter_rules.roles[1].required_conditions
        target_domains = {condition.domain_id for condition in target_conditions}
        asymmetric = [condition for condition in actual_conditions if condition.domain_id not in target_domains]
        # V1 bridge is exactly one explicitly required string equality (paid
        # status). Other population filters must still match across roles.
        if asymmetric:
            if len(asymmetric) != 1 or asymmetric[0].operator != "=" or asymmetric[0].value is None or asymmetric[0].value.value_type != "string" or claim.status_value != asymmetric[0].value.value:
                self.add("incompatible_context", "METRIC_BASIS_FILTER_MISMATCH", target, "declarations.metric_basis", "Target basis does not authorize the actual-only status condition.")
        elif claim.status_value is not None:
            self.add("incompatible_context", "METRIC_BASIS_FILTER_MISMATCH", target, "declarations.metric_basis", "The basis declares a status absent from actual Policy conditions.")
        excluded = {condition.domain_id for condition in asymmetric}
        actual_common = {_filter_signature(item) for item in actual.filters if item.source_identity not in excluded}
        if actual.filters_complete and target.filters_complete and actual_common != {_filter_signature(item) for item in target.filters}:
            self.add("incompatible_context", "FILTER_MISMATCH", None, "filters", "Non-status population conditions must still match for S1.")
        unique = target.declarations.get("source_key_uniqueness")
        if unique is not None and unique.scope.target_version != declaration.scope.target_version:
            self.add("incompatible_context", "TARGET_VERSION_MISMATCH", target, "declarations.scope.target_version", "Target basis and source uniqueness concern different target versions.")

    def revisions(self) -> None:
        revisions = []
        for role in self.roles:
            declaration = role.declarations.get("snapshot_revision")
            provenance = role.context.execution.provenance
            snapshot = provenance.snapshot_ref if provenance is not None else None
            if declaration is not None:
                claim = declaration.claims.snapshot_revision
                if _known_text(snapshot) and snapshot != claim.revision_ref:
                    self.add("incompatible_context", "REVISION_CONFLICT", role, "execution.provenance.snapshot_ref", "Captured snapshot and declared revision disagree.")
                revisions.append((claim.dataset_ref, claim.revision_ref))
            elif _known_text(snapshot):
                revisions.append((role.context.execution.database, snapshot))
            else:
                self.add("insufficient_evidence", "REVISION_UNKNOWN", role, "execution.provenance.snapshot_ref", "A snapshot or trusted revision declaration is required.")
                revisions.append(None)
        if any(item is None for item in revisions):
            return
        left, right = revisions
        if self.policy.snapshot_rules.relationship == "same_revision":
            valid = left == right
        else:
            valid = any(
                left == (pair.left_dataset_ref, pair.left_revision_ref) and right == (pair.right_dataset_ref, pair.right_revision_ref)
                for pair in self.policy.snapshot_rules.authorized_revision_pairs
            )
        if not valid:
            self.add("incompatible_context", "REVISION_CONFLICT", None, "policy.snapshot_rules", "Revisions do not meet the explicit Policy relationship.")


def _filter_signature(item: NormalizedFilter) -> str:
    return _json(item.model_dump(exclude={"context_role"}))


def _time_predicate_bounds(item: object, precision: str) -> tuple:
    def literal(value: object, value_type: str) -> str:
        if value_type not in ("string", "date_literal") or type(value) is not str:
            raise ValueError("time requires a typed calendar literal")
        if precision == "month":
            if value_type != "string":
                raise ValueError("month requires a string equality")
            _month_bounds(value)
        elif precision == "date":
            _date_parts(value)
        else:
            raise ValueError("unsupported time precision")
        return value
    if precision == "month" and item.operator != "=":
        raise ValueError("month supports equality only")
    if item.operator == "BETWEEN":
        if item.lower_bound is None or item.upper_bound is None:
            raise ValueError("BETWEEN needs both bounds")
        return literal(item.lower_bound.value, item.lower_bound.value_type), literal(item.upper_bound.value, item.upper_bound.value_type), True, True
    value = literal(item.value, item.value_type)
    if item.operator == "=":
        return value, value, True, True
    if item.operator in (">", ">="):
        return value, None, item.operator == ">=", None
    if item.operator in ("<", "<="):
        return None, value, None, item.operator == "<="
    raise ValueError("unsupported time operator")


def check_context_compatibility(
    inputs: dict[ContextRole, SignalInput],
    policy: TargetAttainmentPolicy | SalesChangePolicy | ProductContributionPolicy,
    *,
    operation: Operation,
) -> ContextCompatibility:
    """Check named role inputs; never pair, index or compare business-key rows.

    Structural call/model errors raise TypeError/ValueError. Semantic failures
    accumulate stable Issues with unsupported > incompatible > insufficient.
    """
    if type(policy) not in (TargetAttainmentPolicy, SalesChangePolicy, ProductContributionPolicy):
        raise TypeError("a concrete Typed Policy is required")
    if type(inputs) is not dict or any(not isinstance(value, SignalInput) for value in inputs.values()):
        raise TypeError("inputs must map explicit roles to SignalInput")
    if type(operation) is not str or operation not in ("align", "compare", "divide"):
        raise ValueError("operation must be align, compare or divide")
    policy = type(policy).model_validate(policy.model_dump())
    if set(inputs) != set(policy.required_roles):
        raise ValueError("input roles must match the Typed Policy exactly")
    if len({rule.component_id for rule in policy.key_rules}) != len(policy.key_rules):
        raise ValueError("selection component names must be unambiguous")
    snapshots = deepcopy(inputs)
    check = _Check(policy, operation)
    contexts_by_id, declarations_by_id = {}, {}
    for role_name in policy.required_roles:
        supplied = snapshots[role_name]
        if not isinstance(supplied.context, BusinessContext):
            raise TypeError("SignalInput.context must be BusinessContext")
        digest = context_digest(supplied.context)
        role = _Role(role_name, supplied, digest)
        check.roles.append(role)
        check.structure(role)
        previous = contexts_by_id.get(role.context.result_id)
        if previous is not None and previous != digest:
            check.add("incompatible_context", "RESULT_ID_CONFLICT", role, "result_id", "One execution identity has different Context contents in this call.")
        contexts_by_id[role.context.result_id] = digest
        for declaration in supplied.declarations:
            if not isinstance(declaration, InputDeclaration):
                raise TypeError("declarations must contain InputDeclaration")
            content = _json(declaration.model_dump())
            previous = declarations_by_id.get(declaration.declaration_id)
            if previous is not None and previous != content:
                check.add("incompatible_context", "DECLARATION_ID_CONFLICT", role, "declarations", "One declaration identity has conflicting contents.")
            declarations_by_id[declaration.declaration_id] = content
    for index, role in enumerate(check.roles):
        if not role.eligible_version:
            continue
        check.semantics(role, index)
        check.time(role, index)
        check.filters(role, index)
        check.declarations(role, index)
    if all(role.eligible_version for role in check.roles):
        check.cross()
    ordered_issues = sorted(check.issues, key=lambda item: (
        policy.required_roles.index(item.context_role) if item.context_role in policy.required_roles else len(policy.required_roles),
        item.code, tuple(item.evidence_paths), item.message,
    ))
    issues = list({_json(item.model_dump()): item for item in ordered_issues}.values())
    result = ContextCompatibility(
        operation=operation, context_roles=list(policy.required_roles),
        result_ids={role.role: role.context.result_id for role in check.roles},
        status=check.status, issues=issues,
        normalized_metric_refs=[role.metric_ref for role in check.roles if role.metric_ref is not None],
        key_domains=list(dict.fromkeys(rule.domain_id for rule in policy.key_rules)),
        periods=[RolePeriod(context_role=role.role, period=role.period) for role in check.roles if role.period is not None],
        non_time_filters=[item for role in check.roles for item in role.filters],
        declarations_used=[DeclarationRef(
            declaration_id=item.declaration_id, declaration_type=item.declaration_type,
            result_id=item.result_id, context_digest=item.context_digest,
        ) for role in check.roles for _, item in sorted(role.declarations.items())],
        input_digests={role.role: role.digest for role in check.roles},
    )
    return bind_receipt(result, snapshots, policy)


__all__ = ["check_context_compatibility", "context_digest", "filter_scope_digest"]
