"""Read explicit time constraints from FilterInfo, never SQL text or rows.

Only resolved field lineage plus exact Schema role='time' establishes a time
field. Literal validation uses ISO calendar dates/months; no clock, query text,
table-name inference, SQL parsing/execution or model calls are involved.
"""

from __future__ import annotations

from datetime import date
from typing import Sequence

from .models import (
    ColumnSemantic, FilterCondition, FilterInfo, LineageSource, SchemaBinding,
    TimeConstraintInfo, TimeInclusivity,
)
from .sql_parser import identifier_key


def _identity(source: LineageSource) -> tuple[str | None, str, str | None]:
    return (
        source.database, identifier_key(source.table),
        identifier_key(source.field) if source.field is not None else None,
    )


def _expression(conditions: Sequence[FilterCondition]) -> str:
    if len(conditions) == 1:
        return conditions[0].expression
    # Display-only composition of already recorded predicates, not SQL parsing.
    return " AND ".join(f"({condition.expression})" for condition in conditions)


def _source(condition: FilterCondition) -> LineageSource | None:
    if condition.status != "resolved" or condition.lineage is None or len(condition.lineage) != 1:
        return None
    source = condition.lineage[0]
    if (
        source.database is None or not source.database.strip() or not source.table.strip()
        or source.field is None or not source.field.strip()
    ):
        return None
    return source


def _bindings(
    condition: FilterCondition, source: LineageSource,
    columns: Sequence[ColumnSemantic], supplied: Sequence[SchemaBinding],
) -> list[SchemaBinding]:
    candidates = [*condition.schema_bindings, *supplied]
    for column in columns:
        if column.status != "resolved":
            continue
        identities = {_identity(item) for item in column.lineage or []}
        candidates.extend(
            binding for binding in column.schema_bindings if _identity(binding.source) in identities
        )
    return [binding for binding in candidates if _identity(binding.source) == _identity(source)]


def _calendar_literal(value: object, value_type: str | None) -> tuple[str, str]:
    if value_type not in {"string", "date_literal"} or not isinstance(value, str):
        raise ValueError("only ISO date literals or month equality strings are supported; timestamps/dynamic values are not")
    parts = value.split("-")
    if not all(part.isascii() and part.isdigit() for part in parts):
        raise ValueError("time literal is not an exact ISO date/month")
    if len(value) == 10 and [len(part) for part in parts] == [4, 2, 2]:
        date(int(parts[0]), int(parts[1]), int(parts[2]))
        return value, "date"
    if value_type == "string" and len(value) == 7 and [len(part) for part in parts] == [4, 2]:
        # Calendar validation only. No day is emitted or used as a month bound.
        date(int(parts[0]), int(parts[1]), 1)
        return value, "month"
    raise ValueError("time literal is not an exact ISO date/month")


def _condition_range(condition: FilterCondition, source: LineageSource, binding: SchemaBinding) -> TimeConstraintInfo:
    base = dict(
        source_field=source.model_copy(deep=True), scope=condition.scope,
        expression=condition.expression, schema_bindings=[binding.model_copy(deep=True)],
    )
    if condition.scope != "WHERE" or condition.aggregation_expression is not None:
        return TimeConstraintInfo(
            **base, status="unsupported",
            limitations=["aggregate/result-scope predicates are not input-row time constraints"],
        )
    operator = condition.operator
    if operator not in {"=", ">", ">=", "<", "<=", "BETWEEN"}:
        return TimeConstraintInfo(**base, status="unsupported", limitations=["unsupported time comparison operator"])
    base["operator"] = operator
    if operator == "BETWEEN":
        if condition.lower_bound is None or condition.upper_bound is None:
            return TimeConstraintInfo(**base, status="unknown", limitations=["BETWEEN lacks captured literal bounds"])
        literals = [condition.lower_bound, condition.upper_bound]
        values = [(literal.value, literal.value_type) for literal in literals]
    else:
        if condition.value_type is None:
            return TimeConstraintInfo(**base, status="unknown", limitations=["comparison literal evidence is missing"])
        values = [(condition.value, condition.value_type)]
    try:
        decoded = [_calendar_literal(value, kind) for value, kind in values]
    except ValueError as exc:
        return TimeConstraintInfo(**base, status="unsupported", limitations=[str(exc)])
    precisions = {precision for _, precision in decoded}
    if len(precisions) != 1:
        return TimeConstraintInfo(**base, status="unsupported", limitations=["mixed date/month bounds cannot be combined"])
    precision = decoded[0][1]
    if precision == "month" and operator != "=":
        return TimeConstraintInfo(**base, status="unsupported", limitations=["month literals support equality only; no month-to-day expansion"])
    lower = upper = None
    include_lower = include_upper = None
    if operator == "BETWEEN":
        lower, upper = decoded[0][0], decoded[1][0]
        include_lower = include_upper = True
    elif operator == "=":
        lower = upper = decoded[0][0]
        include_lower = include_upper = True
    elif operator in {">", ">="}:
        lower, include_lower = decoded[0][0], operator == ">="
    else:
        upper, include_upper = decoded[0][0], operator == "<="
    return TimeConstraintInfo(
        **base, lower=lower, upper=upper,
        inclusive=TimeInclusivity(lower=include_lower, upper=include_upper),
        precision=precision, status="resolved", is_empty=False,
    )


def _merge(conditions: Sequence[FilterCondition], ranges: Sequence[TimeConstraintInfo]) -> TimeConstraintInfo:
    """Intersect only one proven source/scope, never different temporal fields."""
    first = ranges[0]
    base = dict(
        source_field=first.source_field.model_copy(deep=True), scope=first.scope,
        expression=_expression(conditions),
        operator=first.operator if len(ranges) == 1 else "AND",
    )
    limitations = list(dict.fromkeys(message for item in ranges for message in item.limitations))
    if any(item.status != "resolved" for item in ranges):
        status = "unsupported" if any(item.status == "unsupported" for item in ranges) else "unknown"
        return TimeConstraintInfo(**base, status=status, limitations=limitations)
    if len({item.precision for item in ranges}) != 1:
        return TimeConstraintInfo(**base, status="unsupported", limitations=["mixed date/month predicates cannot form one range"])
    definitions = [item.schema_bindings[0].model_dump(exclude={"source"}) for item in ranges]
    if any(definition != definitions[0] for definition in definitions[1:]):
        return TimeConstraintInfo(**base, status="unknown", limitations=["conflicting Schema metadata across predicates"])
    lower = upper = None
    include_lower = include_upper = None
    for item in ranges:
        # ISO strings are sortable only after exact format/calendar validation
        # above and the same-precision check. No timestamp codec is implied.
        if item.lower is not None:
            if lower is None or item.lower > lower:
                lower, include_lower = item.lower, item.inclusive.lower
            elif item.lower == lower:
                include_lower = include_lower and item.inclusive.lower
        if item.upper is not None:
            if upper is None or item.upper < upper:
                upper, include_upper = item.upper, item.inclusive.upper
            elif item.upper == upper:
                include_upper = include_upper and item.inclusive.upper
    empty = lower is not None and upper is not None and (
        lower > upper or lower == upper and not (include_lower and include_upper)
    )
    if empty:
        limitations.append("explicit temporal constraints have an empty intersection; no rows were inspected")
    return TimeConstraintInfo(
        **base, lower=lower, upper=upper,
        inclusive=TimeInclusivity(lower=include_lower, upper=include_upper),
        status="resolved", limitations=limitations, precision=first.precision, is_empty=empty,
        schema_bindings=[first.schema_bindings[0].model_copy(deep=True)],
    )


def understand_time_constraints(
    filter_info: FilterInfo, columns: Sequence[ColumnSemantic],
    schema_bindings: Sequence[SchemaBinding] = (),
) -> list[TimeConstraintInfo]:
    """Return one constraint per temporal field/scope, in first-appearance order.

    [] means known absence of explicit temporal predicates in the supported
    filters, NOT all-time coverage. Upstream unknown/unsupported information is
    propagated as nonempty diagnostic entries, never upgraded by parsing SQL
    expression text. WHERE and HAVING/JOIN ON/QUALIFY never merge.

    Schema role='time' identifies the declared business role only. Date/month
    precision comes from a validated literal, not an inferred physical dtype.
    Neither table names, Query text, rows nor wall-clock time are inputs.
    """
    if not isinstance(filter_info, FilterInfo):
        raise TypeError("filter_info must be a FilterInfo")
    if any(not isinstance(column, ColumnSemantic) for column in columns):
        raise TypeError("columns must contain ColumnSemantic objects")
    if any(not isinstance(binding, SchemaBinding) for binding in schema_bindings):
        raise TypeError("schema_bindings must contain SchemaBinding objects")
    all_conditions = [*filter_info.filters, *filter_info.excluded_scopes]
    statuses = {filter_info.status, *(condition.status for condition in all_conditions)}
    if (
        statuses != {"resolved"} or filter_info.excluded_scopes
        or filter_info.limitations or any(condition.limitations for condition in all_conditions)
    ):
        status = "unsupported" if "unsupported" in statuses or filter_info.excluded_scopes else "unknown"
        reason = "upstream filter understanding is incomplete; no complete time range can be claimed"
        return [TimeConstraintInfo(
            scope=condition.scope, expression=condition.expression, status=status,
            limitations=list(dict.fromkeys([reason, *filter_info.limitations, *condition.limitations])),
        ) for condition in all_conditions] or [TimeConstraintInfo(
            status=status, limitations=[reason, *filter_info.limitations],
        )]

    missing_scopes = [
        (scope, text) for scope, text in (
            ("WHERE", filter_info.where_expression), ("HAVING", filter_info.having_expression),
        ) if text is not None and not any(condition.scope == scope for condition in filter_info.filters)
    ]
    if missing_scopes:
        return [TimeConstraintInfo(
            scope=scope, expression=text, status="unknown",
            limitations=["scope expression exists but structured filter conditions are missing"],
        ) for scope, text in missing_scopes]

    # Schema is source-level evidence: consider all already resolved predicate
    # bindings together, so one condition cannot hide another's conflicting role.
    available_bindings = list(schema_bindings)
    for condition in filter_info.filters:
        source = _source(condition)
        if source is not None:
            available_bindings.extend(
                binding for binding in condition.schema_bindings
                if _identity(binding.source) == _identity(source)
            )

    # Each slot is either a diagnostic item or a same-source/scope group.
    slots: list[TimeConstraintInfo | tuple] = []
    groups: dict[tuple, tuple[list[FilterCondition], list[TimeConstraintInfo]]] = {}
    for condition in filter_info.filters:
        source = _source(condition)
        base = dict(scope=condition.scope, expression=condition.expression)
        if source is None:
            slots.append(TimeConstraintInfo(**base, status="unknown", limitations=["one resolved field lineage is required"]))
            continue
        base["source_field"] = source.model_copy(deep=True)
        bindings = _bindings(condition, source, columns, available_bindings)
        roles = {binding.role for binding in bindings}
        if not bindings or len(roles) != 1 or any(role is None or not role.strip() for role in roles):
            item = TimeConstraintInfo(**base, status="unknown", limitations=["Schema time-role evidence is missing or conflicting"])
        elif roles != {"time"}:
            # A date-shaped region/customer label is not a temporal predicate.
            continue
        else:
            definition = bindings[0].model_dump(exclude={"source"})
            if any(binding.model_dump(exclude={"source"}) != definition for binding in bindings[1:]):
                item = TimeConstraintInfo(**base, status="unknown", limitations=["conflicting Schema metadata was not selected"])
            else:
                item = _condition_range(condition, source, bindings[0])
        key = (*_identity(source), condition.scope)
        if key not in groups:
            groups[key] = ([], [])
            slots.append(key)
        groups[key][0].append(condition)
        groups[key][1].append(item)
    return [slot if isinstance(slot, TimeConstraintInfo) else _merge(*groups[slot]) for slot in slots]


__all__ = ["TimeConstraintInfo", "TimeInclusivity", "understand_time_constraints"]
