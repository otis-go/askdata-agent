"""Pure assembly of existing V1 semantics; no new SQL/Schema/time algorithms."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..result_consistency import validate_execution_provenance
from ..result_contract import ResultContract
from .filter import _identity, understand_filters
from .grain import understand_grain
from .lineage import understand_columns
from .models import (
    BusinessContext, ColumnSemantic, FilterInfo, GrainInfo, QueryBindingsInfo,
    SemanticStatus,
)
from .schema_binding import bind_schema, prepare_query_bindings
from .sql_parser import ParsedSelect, UnsupportedSQL, parse_sql
from .time_constraint import understand_time_constraints


def _binding_limitations(columns: Sequence[ColumnSemantic]) -> list[str]:
    """Check binding cardinality by existing identity, without looking up Schema.

    Resolved lineage is not a binding-completeness claim. Relation COUNT sources
    and constants have no physical field to bind and must not acquire one here.
    """
    limitations: list[str] = []
    for column in columns:
        if column.status != "resolved":
            continue
        for source in column.lineage or []:
            if source.field is None:
                continue
            matches = [
                binding for binding in column.schema_bindings
                if _identity(binding.source) == _identity(source)
            ]
            if len(matches) != 1:
                limitations.append(
                    f"{column.column_id}: physical source lacks a unique SchemaBinding: "
                    f"{source.database}.{source.table}.{source.field}"
                )
    return limitations


def _source_free_constants(parsed: ParsedSelect | None, columns: Sequence[ColumnSemantic]) -> bool:
    """Evidence applicability, not a new grain algorithm or grain override.

    Only a source-free literal SELECT has no grouping/database-field evidence
    obligation. SELECT literals FROM a table and all detail-field queries still
    require the existing Grain reader's evidence. Nested stage results stay
    unchanged, including its unknown grain and diagnostic.
    """
    return (
        parsed is not None and parsed.statement is not None and parsed.table is None
        and all(parsed.statement.args.get(name) is None for name in ("where", "having", "group"))
        and bool(columns)
        and all(
            column.status == "resolved" and column.lineage == [] and column.aggregation is None
            for column in columns
        )
    )


def build_business_context(
    result_contract: ResultContract, schema: Sequence[Mapping[str, Any]],
) -> BusinessContext:
    """Assemble detached execution and semantic evidence without executing SQL.

    Contradictory execution/provenance facts are rejected before any semantics.
    Missing optional provenance stays compatible. Failed/unconfirmed execution,
    missing SQL and absent/empty column identities raise explicitly. A SQL
    outside the V1 subset yields unsupported diagnostics while preserving the
    execution facts. Unexpected programming/metadata errors are not swallowed.

    Overall status is unsupported > unknown > resolved over required evidence.
    For a source-free literal SELECT only, unknown grain (and unknown database
    query binding when no database was supplied) is not required evidence. This
    does not change either nested status or infer a new query/business grain.

    P2-02 remains: parse_sql here and inside understand_columns each parse the
    original SQL once. All subsequent stages read the retained AST/evidence.
    """
    if not isinstance(result_contract, ResultContract):
        raise TypeError("result_contract must be a ResultContract")
    if not isinstance(schema, Sequence) or isinstance(schema, (str, bytes)) or any(
        not isinstance(table, Mapping) for table in schema
    ):
        raise TypeError("schema must be a sequence of table mappings")
    execution = result_contract.execution
    consistency = validate_execution_provenance(execution)
    if consistency.conflicts:
        raise ValueError(
            "contradictory execution/provenance facts: "
            + "; ".join(f"{issue.field}: {issue.reason}" for issue in consistency.conflicts)
        )
    if execution.success is not True:
        raise ValueError("successful execution is not confirmed; BusinessContext was not built")
    if execution.sql is None or not execution.sql.strip():
        raise ValueError("execution.sql is unknown; BusinessContext was not built")
    if execution.columns is None:
        raise ValueError("execution.columns is unknown; output column identities are required")
    if not execution.columns:
        raise ValueError("execution.columns is empty; a SELECT output requires column identities")

    parsed = None
    parse_reason = None
    try:
        parsed = parse_sql(execution.sql)
        statement = parsed
    except UnsupportedSQL as exc:
        parse_reason = str(exc)
        statement = exc.statement

    columns = [bind_schema(column, schema) for column in understand_columns(result_contract)]
    if statement is None:
        # No usable single AST exists: never invent an empty supported clause
        # set or select the first statement of a multi-statement request.
        reason = f"no single usable SQL AST: {parse_reason}"
        query_bindings = QueryBindingsInfo(status="unsupported", limitations=[reason])
        grain = GrainInfo(status="unsupported", limitations=[reason])
        filters = FilterInfo(status="unsupported", limitations=[reason])
    else:
        query_bindings = prepare_query_bindings(statement, execution.database, schema)
        grain = understand_grain(statement, columns)
        filters = understand_filters(statement, columns, query_bindings.bindings)
    times = understand_time_constraints(filters, columns, query_bindings.bindings)

    statuses: list[SemanticStatus] = [column.status for column in columns]
    limitations: list[str] = []

    def record(stage: str, messages: Sequence[str]) -> None:
        limitations.extend(f"{stage}: {message}" for message in messages)

    if parse_reason is not None:
        statuses.append("unsupported")
        record("parser", [parse_reason])
    for column in columns:
        if column.reason is not None:
            record("lineage", [f"{column.column_id}: {column.reason}"])
    binding_limitations = _binding_limitations(columns)
    if binding_limitations:
        statuses.append("unknown")
    record("schema_binding", binding_limitations)

    constants_only = _source_free_constants(parsed, columns)
    # Never suppress unsupported; only omit unknown evidence that this precise
    # source-free case does not require. Do not upgrade the nested stage object.
    if not (
        constants_only and query_bindings.status == "unknown"
        and (execution.database is None or not execution.database.strip())
    ):
        statuses.append(query_bindings.status)
    record("query_bindings", query_bindings.limitations)
    if not (constants_only and grain.status == "unknown"):
        statuses.append(grain.status)
    record("grain", grain.limitations)
    statuses.append(filters.status)
    record("filter", filters.limitations)
    for condition in [*filters.filters, *filters.excluded_scopes]:
        statuses.append(condition.status)
        record("filter", condition.limitations)
    for constraint in times:
        statuses.append(constraint.status)
        record("time", constraint.limitations)
    status: SemanticStatus = (
        "unsupported" if "unsupported" in statuses
        else "unknown" if "unknown" in statuses
        else "resolved"
    )
    return BusinessContext(
        result_id=result_contract.result_id,
        result_contract_version=result_contract.version,
        execution=execution,
        column_semantics=columns,
        query_bindings=query_bindings,
        grain=grain,
        filters=filters,
        time_constraints=times,
        understanding_status=status,
        limitations=list(dict.fromkeys(limitations)),
    ).model_copy(deep=True)


__all__ = ["build_business_context"]
