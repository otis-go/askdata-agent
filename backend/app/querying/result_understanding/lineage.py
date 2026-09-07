"""ResultContract -> ColumnSemantic list. No database, LLM or Workflow calls."""

from __future__ import annotations

from sqlglot import exp

from ..result_contract import ResultContract
from .models import Aggregation, ColumnSemantic, LineageSource
from .sql_parser import ParsedSelect, UnsupportedSQL, identifier_key, parse_sql


def _column_source(
    column: exp.Column, parsed: ParsedSelect, prior_aliases: set[str],
    database: str | None,
) -> LineageSource:
    if column.is_star or column.db or column.catalog or not isinstance(column.this, exp.Identifier):
        raise UnsupportedSQL("qualified catalogs, struct access and star fields are unsupported")
    if parsed.table is None:
        raise UnsupportedSQL("a field reference has no physical table source")
    if column.table:
        if identifier_key(column.table) != identifier_key(parsed.qualifier or ""):
            raise UnsupportedSQL("column qualifier does not match the source table alias")
    else:
        if identifier_key(column.name) == identifier_key(parsed.qualifier or ""):
            raise UnsupportedSQL("unqualified reference may denote a whole-row table alias")
        if identifier_key(column.name) in prior_aliases:
            # DuckDB supports lateral SELECT aliases. Without a catalog, p may
            # mean an earlier expression or a base field; never invent table.p.
            raise UnsupportedSQL("unqualified column may reference an earlier SELECT alias")
    return LineageSource(database=database, table=parsed.table, field=column.name)


def _is_literal(expression: exp.Expression) -> bool:
    return isinstance(expression, (exp.Literal, exp.Null, exp.Boolean))


def _projection_lineage(
    expression: exp.Expression, parsed: ParsedSelect, prior_aliases: set[str],
    database: str | None,
) -> tuple[list[LineageSource], Aggregation | None]:
    if isinstance(expression, exp.Column):
        return [_column_source(expression, parsed, prior_aliases, database)], None
    if _is_literal(expression):
        return [], None

    supported_aggregates = {exp.Sum: "SUM", exp.Avg: "AVG", exp.Count: "COUNT"}
    aggregation = supported_aggregates.get(type(expression))
    if aggregation is None:
        raise UnsupportedSQL("only direct fields, literals and simple SUM/AVG/COUNT are supported")
    # Do not discard DISTINCT, ordered arguments, FILTER, wrappers or extra args.
    if any(value for key, value in expression.args.items() if key not in {"this", "big_int"}):
        raise UnsupportedSQL("aggregate modifiers or multiple arguments are unsupported")
    argument = expression.this
    if isinstance(argument, exp.Column):
        return [_column_source(argument, parsed, prior_aliases, database)], aggregation
    if isinstance(expression, exp.Count) and (
        isinstance(argument, exp.Star) and not any(argument.args.values())
        or isinstance(argument, exp.Expression) and _is_literal(argument)
    ):
        if parsed.table is None:
            raise UnsupportedSQL("relation-level COUNT requires a physical table source")
        return [LineageSource(database=database, table=parsed.table, field=None)], aggregation
    raise UnsupportedSQL("aggregate argument is not a supported field or COUNT row-set argument")


def understand_columns(result_contract: ResultContract) -> list[ColumnSemantic]:
    """Describe supported projections using execution.sql and columns only.

    No rows are needed. Output names are copied for display, never used to infer
    a source. Missing columns raise ValueError: unknown metadata is not an empty
    result. Unsupported SQL produces one unsupported entry per known column;
    absent SQL/database/success evidence remains unknown. Input is not mutated.
    """
    if not isinstance(result_contract, ResultContract):
        raise TypeError("result_contract must be a ResultContract")
    execution = result_contract.execution
    columns = execution.columns
    if columns is None:
        raise ValueError("execution.columns is unknown; output column identities are required")
    if [column.ordinal for column in columns] != list(range(len(columns))) or len(
        {column.id for column in columns}
    ) != len(columns):
        raise ValueError("execution columns must have unique ids and consecutive ordinals")
    identities = [
        {"column_id": column.id, "ordinal": column.ordinal, "output_name": column.name}
        for column in columns
    ]
    if not columns:
        return []
    if execution.success is not True:
        return [ColumnSemantic(**identity, status="unknown", reason="successful execution is not confirmed") for identity in identities]
    if execution.sql is None or not execution.sql.strip():
        return [ColumnSemantic(**identity, status="unknown", reason="execution.sql is unknown") for identity in identities]

    try:
        parsed = parse_sql(execution.sql)
        if len(parsed.projections) != len(columns):
            raise UnsupportedSQL("SELECT projection count does not match execution columns")
    except UnsupportedSQL as exc:
        return [ColumnSemantic(**identity, status="unsupported", reason=str(exc)) for identity in identities]

    semantics: list[ColumnSemantic] = []
    prior_aliases: set[str] = set()
    for identity, expression, alias in zip(identities, parsed.projections, parsed.aliases):
        expression_sql = expression.sql(dialect="duckdb", comments=False)
        try:
            sources, aggregation = _projection_lineage(expression, parsed, prior_aliases, execution.database)
        except UnsupportedSQL as exc:
            semantics.append(ColumnSemantic(
                **identity, expression=expression_sql, status="unsupported", reason=str(exc),
            ))
        else:
            missing_database = bool(sources) and (execution.database is None or not execution.database.strip())
            semantics.append(ColumnSemantic(
                **identity, expression=expression_sql, lineage=sources, aggregation=aggregation,
                status="unknown" if missing_database else "resolved",
                reason="execution.database is unknown" if missing_database else None,
            ))
        if alias is not None:
            prior_aliases.add(identifier_key(alias))
    return semantics


__all__ = ["understand_columns"]
