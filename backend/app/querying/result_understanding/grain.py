"""Read query grain from an existing AST and its column semantics only.

No SQL parsing/execution, Schema lookup, role-based inference or Workflow calls.
The first version maps plain grouping fields to resolved projected lineage.
Hidden grouping keys remain unknown, rather than silently dropping a key.
"""

from __future__ import annotations

from typing import Sequence

from sqlglot import exp

from .models import ColumnSemantic, GrainInfo, LineageSource
from .sql_parser import ParsedSelect, UnsupportedSQL, identifier_key, inspect_select_ast


def _unsupported(reason: str, expressions: list[str] | None = None) -> GrainInfo:
    return GrainInfo(status="unsupported", grouping_expressions=expressions, limitations=[reason])


def _field_identity(column: exp.Column, parsed: ParsedSelect) -> tuple[str, str] | None:
    if (
        parsed.table is None or column.is_star or column.db or column.catalog
        or not isinstance(column.this, exp.Identifier)
    ):
        return None
    if column.table and identifier_key(column.table) != identifier_key(parsed.qualifier or ""):
        return None
    return identifier_key(parsed.table), identifier_key(column.name)


def _source_identity(source: LineageSource) -> tuple[str | None, str, str | None]:
    return (
        source.database, identifier_key(source.table),
        identifier_key(source.field) if source.field is not None else None,
    )


def _aligned_columns(parsed: ParsedSelect, columns: Sequence[ColumnSemantic]) -> bool:
    if len(parsed.projections) != len(columns):
        return False
    if [column.ordinal for column in columns] != list(range(len(columns))):
        return False
    if len({column.column_id for column in columns}) != len(columns):
        return False
    return all(
        column.expression == expression.sql(dialect="duckdb", comments=False)
        for expression, column in zip(parsed.projections, columns)
    )


def _valid_source(
    column: ColumnSemantic, field: exp.Column | None, parsed: ParsedSelect,
) -> LineageSource | None:
    if column.status != "resolved" or column.lineage is None or len(column.lineage) != 1:
        return None
    source = column.lineage[0]
    if source.database is None or not source.database.strip() or parsed.table is None:
        return None
    if field is None:
        matches = source.field is None and identifier_key(source.table) == identifier_key(parsed.table)
    else:
        expected = _field_identity(field, parsed)
        matches = expected is not None and _source_identity(source)[1:] == expected
    return source if matches else None


def _business_label(columns: Sequence[ColumnSemantic], source: LineageSource) -> str | None:
    labels = {
        binding.label
        for column in columns
        for binding in column.schema_bindings
        if _source_identity(binding.source) == _source_identity(source)
        and binding.label is not None and binding.label.strip()
    }
    return next(iter(labels)) if len(labels) == 1 else None


def _grouped_grain(
    parsed: ParsedSelect, columns: Sequence[ColumnSemantic], grouping: Sequence[exp.Column],
) -> GrainInfo:
    expressions = [key.sql(dialect="duckdb", comments=False) for key in grouping]
    sources: list[LineageSource] = []
    labels: list[str] = []
    limitations: list[str] = []
    aliases = {identifier_key(alias) for alias in parsed.aliases if alias is not None}
    for key, text in zip(grouping, expressions):
        # GROUP BY alias/base-name precedence needs catalog evidence not present
        # here. Do not infer its source from an output display name.
        if not key.table and identifier_key(key.name) in aliases:
            return _unsupported("GROUP BY SELECT aliases are unsupported", expressions)
        identity = _field_identity(key, parsed)
        if identity is None:
            return _unsupported("grouping field has an unsupported qualifier or source", expressions)
        candidates = [
            (projection, column)
            for projection, column in zip(parsed.projections, columns)
            if isinstance(projection, exp.Column)
            and _field_identity(projection, parsed) == identity
        ]
        matching: list[ColumnSemantic] = []
        candidate_sources: list[LineageSource] = []
        for projection, column in candidates:
            if column.status != "resolved":
                continue
            source = _valid_source(column, projection, parsed)
            if source is None or column.aggregation is not None:
                return GrainInfo(
                    query_grain="grouped", grouping_expressions=expressions, status="unknown",
                    limitations=[f"grouping source does not match projected lineage: {text}"],
                )
            matching.append(column)
            candidate_sources.append(source)
        identities = {_source_identity(source) for source in candidate_sources}
        if len(identities) != 1:
            return GrainInfo(
                query_grain="grouped", grouping_expressions=expressions, status="unknown",
                limitations=[f"grouping key lacks unique resolved projected lineage (possibly hidden): {text}"],
            )
        source = candidate_sources[0]
        sources.append(source.model_copy(deep=True))
        label = _business_label(matching, source)
        if label is None:
            limitations.append(f"no unique Schema label for grouping source: {text}")
        else:
            labels.append(label)
    if len({source.database for source in sources}) != 1:
        return GrainInfo(
            query_grain="grouped", grouping_expressions=expressions, status="unknown",
            limitations=["grouping sources do not belong to one execution database"],
        )
    return GrainInfo(
        query_grain="grouped", grouping_expressions=expressions, grouping_columns=sources,
        business_grain=labels if not limitations else None, status="resolved", limitations=limitations,
    )


def _global_grain(parsed: ParsedSelect, columns: Sequence[ColumnSemantic]) -> GrainInfo:
    if not any(projection.find(exp.AggFunc) is not None for projection in parsed.projections):
        return GrainInfo(
            grouping_expressions=[], status="unknown",
            limitations=["no explicit GROUP BY or supported global aggregate; roles do not establish grain"],
        )
    aggregates = {exp.Sum: "SUM", exp.Avg: "AVG", exp.Count: "COUNT"}
    databases: set[str] = set()
    for projection, column in zip(parsed.projections, columns):
        if isinstance(projection, (exp.Literal, exp.Null, exp.Boolean)):
            if column.status == "resolved" and column.lineage == [] and column.aggregation is None:
                continue
            return GrainInfo(status="unknown", limitations=["constant projection semantics are not resolved"])
        operation = aggregates.get(type(projection))
        if operation is None:
            return _unsupported("global aggregates support only simple SUM/AVG/COUNT and literal projections")
        if any(value for name, value in projection.args.items() if name not in {"this", "big_int"}):
            return _unsupported("complex aggregate arguments are unsupported")
        argument = projection.this
        if isinstance(argument, exp.Column):
            field = argument
        elif isinstance(projection, exp.Count) and (
            isinstance(argument, exp.Star) and not any(argument.args.values())
            or isinstance(argument, (exp.Literal, exp.Null, exp.Boolean))
        ):
            field = None
        else:
            return _unsupported("complex global aggregate expressions are unsupported")
        if column.status == "unsupported":
            return _unsupported("aggregate column lineage is unsupported")
        source = _valid_source(column, field, parsed)
        if source is None or column.aggregation != operation:
            return GrainInfo(status="unknown", limitations=["aggregate lineage/operation does not match the AST"])
        databases.add(source.database)
    if len(databases) > 1:
        return GrainInfo(status="unknown", limitations=["aggregate sources disagree on execution database"])
    return GrainInfo(
        query_grain="global_aggregate", grouping_expressions=[], grouping_columns=[], status="resolved",
    )


def understand_grain(
    statement: exp.Expression | ParsedSelect, columns: Sequence[ColumnSemantic],
) -> GrainInfo:
    """Read an already parsed AST; never parse semantic expression strings.

    The supplied columns must correspond to this AST by ordinal and expression.
    Plain GROUP BY keys require matching resolved projected lineage; hidden or
    unresolved keys yield unknown with the complete grouping expression list.
    Business labels are optional source-matched Schema annotations, not evidence
    of entity uniqueness, filters, temporal coverage or business correctness.
    """
    if isinstance(statement, ParsedSelect):
        statement = statement.statement
        if statement is None:
            return GrainInfo(status="unknown", limitations=["ParsedSelect has no retained root AST"])
    if not isinstance(statement, exp.Expression):
        raise TypeError("statement must be an already parsed SQLGlot AST or ParsedSelect")
    if any(not isinstance(column, ColumnSemantic) for column in columns):
        raise TypeError("columns must contain ColumnSemantic objects")
    try:
        parsed = inspect_select_ast(statement)
    except UnsupportedSQL as exc:
        return _unsupported(str(exc))

    group = statement.args.get("group")
    if group is not None:
        expressions = [key.sql(dialect="duckdb", comments=False) for key in group.expressions]
        if any(value is not None for name, value in group.args.items() if name != "expressions"):
            return _unsupported("CUBE/ROLLUP/GROUPING SETS/GROUP BY ALL are unsupported", expressions)
        if not group.expressions or any(
            not isinstance(key, exp.Column) or key.is_star for key in group.expressions
        ):
            return _unsupported("only plain field GROUP BY keys are supported", expressions)
    if not _aligned_columns(parsed, columns):
        return GrainInfo(status="unknown", limitations=["AST projections and column semantics are not aligned"])
    if group is not None:
        return _grouped_grain(parsed, columns, group.expressions)
    return _global_grain(parsed, columns)


__all__ = ["GrainInfo", "understand_grain"]
