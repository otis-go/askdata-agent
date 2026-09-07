"""Deterministic WHERE/HAVING extraction from an already parsed SQL AST.

No parsing, execution, LLM, Schema lookup, time inference or Workflow calls.
Predicate-only fields need explicit source evidence, not display-name guesses.
"""

from __future__ import annotations

from typing import Sequence

from sqlglot import exp

from .lineage import _projection_lineage
from .models import ColumnSemantic, FilterCondition, FilterInfo, FilterLiteral, LineageSource, SchemaBinding
from .sql_parser import ParsedSelect, UnsupportedSQL, identifier_key, inspect_select_ast


class _MissingEvidence(ValueError):
    pass


def _sql(node: exp.Expression) -> str:
    return node.sql(dialect="duckdb", comments=False)


def _identity(source: LineageSource) -> tuple[str | None, str, str | None]:
    return (
        source.database, identifier_key(source.table),
        identifier_key(source.field) if source.field is not None else None,
    )


def _evidence(
    parsed: ParsedSelect, columns: Sequence[ColumnSemantic],
) -> tuple[str | None, list[LineageSource], list[SchemaBinding]]:
    if (
        len(parsed.projections) != len(columns)
        or [column.ordinal for column in columns] != list(range(len(columns)))
        or len({column.column_id for column in columns}) != len(columns)
        or any(column.expression != _sql(projection) for projection, column in zip(parsed.projections, columns))
    ):
        raise _MissingEvidence("AST projections and column semantics are not aligned")
    sources: list[LineageSource] = []
    bindings: list[SchemaBinding] = []
    prior_aliases: set[str] = set()
    for projection, alias, column in zip(parsed.projections, parsed.aliases, columns):
        if column.status == "resolved":
            database = column.lineage[0].database if column.lineage else None
            try:
                expected, aggregation = _projection_lineage(projection, parsed, prior_aliases, database)
            except UnsupportedSQL as exc:
                raise _MissingEvidence("resolved column does not match a supported AST projection") from exc
            if (
                column.lineage is None
                or [_identity(source) for source in expected] != [_identity(source) for source in column.lineage]
                or column.aggregation != aggregation
                or any(source.database is None or not source.database.strip() for source in expected)
            ):
                raise _MissingEvidence("resolved lineage/aggregation conflicts with the AST or lacks database identity")
            sources.extend(column.lineage)
            identities = {_identity(source) for source in column.lineage}
            bindings.extend(binding for binding in column.schema_bindings if _identity(binding.source) in identities)
        if alias is not None:
            prior_aliases.add(identifier_key(alias))
    databases = {source.database for source in sources}
    if len(databases) > 1:
        raise _MissingEvidence("column sources disagree on execution database")
    return next(iter(databases)) if databases else None, sources, bindings


def _literal(node: exp.Expression) -> tuple[str | int | bool | None, str, str]:
    rendered = _sql(node)
    if isinstance(node, exp.Literal) and node.is_string:
        return node.this, "string", rendered
    numeric = node
    sign = ""
    if isinstance(node, exp.Neg):
        numeric, sign = node.this, "-"
    if isinstance(numeric, exp.Literal) and not numeric.is_string:
        text = sign + numeric.this
        if numeric.this.isascii() and numeric.this.isdigit():
            try:
                return int(text), "integer", rendered
            except ValueError:
                # Extremely long integers can exceed Python's conversion limit.
                pass
        return text, "numeric_text", rendered
    if isinstance(node, exp.Boolean) and type(node.this) is bool:
        return node.this, "boolean", rendered
    if isinstance(node, exp.Null):
        return None, "null", rendered
    if type(node) is exp.Cast and isinstance(node.this, exp.Literal) and node.this.is_string:
        target = node.args.get("to")
        if isinstance(target, exp.DataType):
            kinds = {
                exp.DataType.Type.DATE: "date_literal",
                exp.DataType.Type.TIMESTAMP: "timestamp_literal",
                exp.DataType.Type.TIMESTAMPNTZ: "timestamp_literal",
            }
            kind = kinds.get(target.this)
            if kind is not None and not target.expressions:
                return node.this.this, kind, rendered
    raise UnsupportedSQL("only scalar literals and DATE/TIMESTAMP string literals are supported on the right")


def _unwrap(node: exp.Expression) -> exp.Expression:
    while isinstance(node, exp.Paren):
        node = node.this
    return node


def _and_terms(node: exp.Expression) -> list[exp.Expression]:
    node = _unwrap(node)
    if isinstance(node, exp.And):
        return [*_and_terms(node.this), *_and_terms(node.expression)]
    return [node]


def _metadata(
    source: LineageSource, bindings: Sequence[SchemaBinding],
) -> tuple[list[SchemaBinding], list[str]]:
    matches = [binding for binding in bindings if _identity(binding.source) == _identity(source)]
    if not matches:
        return [], []
    # Ignore identity spelling when comparing metadata for the same SQL source.
    definition = matches[0].model_dump(exclude={"source"})
    if any(binding.model_dump(exclude={"source"}) != definition for binding in matches[1:]):
        return [], ["conflicting Schema metadata was not attached"]
    return [matches[0].model_copy(deep=True)], []


def _predicate_operand(scope: str, node: exp.Expression, details: dict) -> exp.Expression:
    """Check V1 predicate shape/literals and return the source-bearing operand.

    Shared by filter interpretation and query binding preparation, so evidence
    preparation cannot admit predicates the filter reader does not understand.
    details is caller-owned scratch output, never an input semantic object.
    """
    operators = {
        exp.EQ: "=", exp.NEQ: "!=", exp.GT: ">", exp.GTE: ">=", exp.LT: "<", exp.LTE: "<=",
        exp.Between: "BETWEEN",
    }
    operator = operators.get(type(node))
    if operator is None:
        raise UnsupportedSQL("only simple comparison predicates are supported")
    details["operator"] = operator
    if operator == "BETWEEN":
        if any(value for key, value in node.args.items() if key not in {"this", "low", "high"}):
            raise UnsupportedSQL("BETWEEN modifiers are unsupported")
        for argument, key in (("low", "lower_bound"), ("high", "upper_bound")):
            value, value_type, value_sql = _literal(_unwrap(node.args[argument]))
            details[key] = FilterLiteral(value=value, value_type=value_type, value_sql=value_sql)
    else:
        value, value_type, value_sql = _literal(_unwrap(node.expression))
        details.update(value=value, value_type=value_type, value_sql=value_sql)
    operand = _unwrap(node.this)
    if scope == "WHERE" and not isinstance(operand, exp.Column):
        raise UnsupportedSQL("WHERE requires a plain field on the left")
    if scope == "HAVING":
        if type(operand) not in (exp.Sum, exp.Avg, exp.Count):
            raise UnsupportedSQL("HAVING requires a simple SUM/AVG/COUNT expression on the left")
        details["aggregation_expression"] = _sql(operand)
    return operand


def _condition(
    scope: str, node: exp.Expression, parsed: ParsedSelect, database: str | None,
    known_sources: Sequence[LineageSource], bindings: Sequence[SchemaBinding],
) -> FilterCondition:
    base = {"scope": scope, "expression": _sql(node)}
    try:
        operand = _predicate_operand(scope, node, base)
        aliases = {identifier_key(alias) for alias in parsed.aliases if alias is not None}
        proposed, _ = _projection_lineage(operand, parsed, aliases, database)
        if database is None:
            raise _MissingEvidence("execution database is not established by resolved column lineage")
        if len(proposed) != 1:
            raise UnsupportedSQL("predicate operand must have one field or relation source")
        source = proposed[0]
        # A relation-level COUNT has no field metadata. Field existence/source
        # evidence must come from resolved lineage or an explicit exact binding.
        if source.field is not None and not any(
            _identity(candidate) == _identity(source)
            for candidate in [*known_sources, *(binding.source for binding in bindings)]
        ):
            raise _MissingEvidence("predicate field has no resolved lineage or exact SchemaBinding evidence")
        metadata, limitations = _metadata(source, bindings) if source.field is not None else ([], [])
        return FilterCondition(
            **base, lineage=[source.model_copy(deep=True)], schema_bindings=metadata,
            status="resolved", limitations=limitations,
        )
    except UnsupportedSQL as exc:
        return FilterCondition(**base, status="unsupported", limitations=[str(exc)])
    except _MissingEvidence as exc:
        return FilterCondition(**base, status="unknown", limitations=[str(exc)])


def understand_filters(
    statement: exp.Expression | ParsedSelect, columns: Sequence[ColumnSemantic],
    schema_bindings: Sequence[SchemaBinding] = (),
) -> FilterInfo:
    """Extract scoped predicates without reparsing SQL or evaluating values.

    Explicit bindings may supply filter-only field evidence, but never invent an
    execution database. WHERE/HAVING can each split pure AND; OR/NOT retain the
    entire scope as unsupported. JOIN ON and QUALIFY are recorded separately,
    not added to the supported filter list. BETWEEN retains both scalar bounds;
    dates remain literals here, not interpreted time ranges.
    """
    if isinstance(statement, ParsedSelect):
        statement = statement.statement
        if statement is None:
            return FilterInfo(status="unknown", limitations=["ParsedSelect has no retained root AST"])
    if not isinstance(statement, exp.Expression):
        raise TypeError("statement must be an already parsed SQLGlot AST or ParsedSelect")
    if any(not isinstance(column, ColumnSemantic) for column in columns):
        raise TypeError("columns must contain ColumnSemantic objects")
    if any(not isinstance(binding, SchemaBinding) for binding in schema_bindings):
        raise TypeError("schema_bindings must contain SchemaBinding objects")

    clauses = [
        (scope, clause.this)
        for scope, name in (("WHERE", "where"), ("HAVING", "having"))
        if (clause := statement.args.get(name)) is not None
    ]
    excluded: list[FilterCondition] = []
    for join in statement.args.get("joins") or []:
        if (on := join.args.get("on")) is not None:
            excluded.append(FilterCondition(
                scope="JOIN ON", expression=_sql(on), status="unsupported",
                limitations=["JOIN ON is not a WHERE/HAVING predicate and is not interpreted"],
            ))
    if (qualify := statement.args.get("qualify")) is not None:
        excluded.append(FilterCondition(
            scope="QUALIFY", expression=_sql(qualify.this), status="unsupported",
            limitations=["QUALIFY/window filtering is unsupported"],
        ))
    scope_text = {
        "where_expression": next((_sql(node) for scope, node in clauses if scope == "WHERE"), None),
        "having_expression": next((_sql(node) for scope, node in clauses if scope == "HAVING"), None),
    }
    try:
        parsed = inspect_select_ast(statement)
        local_filters = list(statement.find_all(exp.Filter))
        if local_filters:
            # Aggregate FILTER (WHERE ...) has its own input scope. It must
            # never disappear as an apparently known-empty root WHERE/HAVING.
            raise UnsupportedSQL(
                "aggregate-local FILTER scopes are unsupported, not root WHERE/HAVING: "
                + "; ".join(_sql(node) for node in local_filters)
            )
    except UnsupportedSQL as exc:
        return FilterInfo(
            **scope_text, status="unsupported", excluded_scopes=excluded, limitations=[str(exc)],
            filters=[FilterCondition(scope=scope, expression=_sql(node), status="unsupported", limitations=[str(exc)]) for scope, node in clauses],
        )
    try:
        database, sources, bindings = _evidence(parsed, columns)
    except _MissingEvidence as exc:
        return FilterInfo(
            **scope_text, status="unsupported" if excluded else "unknown", excluded_scopes=excluded,
            limitations=[str(exc)], filters=[
                FilterCondition(scope=scope, expression=_sql(node), status="unknown", limitations=[str(exc)])
                for scope, node in clauses
            ],
        )
    bindings = [*bindings, *schema_bindings]
    filters: list[FilterCondition] = []
    for scope, node in clauses:
        if node.find(exp.Or, exp.Not) is not None:
            filters.append(FilterCondition(
                scope=scope, expression=_sql(node), status="unsupported",
                limitations=["OR/NOT scopes are preserved whole, not flattened into AND"],
            ))
            continue
        filters.extend(_condition(scope, term, parsed, database, sources, bindings) for term in _and_terms(node))
    conditions = [*filters, *excluded]
    status = (
        "unsupported" if any(item.status == "unsupported" for item in conditions)
        else "unknown" if any(item.status == "unknown" for item in conditions)
        else "resolved"
    )
    limitations = list(dict.fromkeys(message for item in conditions for message in item.limitations))
    return FilterInfo(
        **scope_text, filters=filters, excluded_scopes=excluded, status=status, limitations=limitations,
    )


__all__ = ["FilterCondition", "FilterInfo", "understand_filters"]
