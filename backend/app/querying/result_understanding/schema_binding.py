"""Bind resolved SQL lineage to an explicitly supplied, read-only Schema.

No SQL parsing/execution, global Schema import, LLM, or Workflow dependency.
Identity lookup never uses output_name, expression aliases, labels or scores.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from sqlglot import exp

from .filter import _and_terms, _identity, _predicate_operand
from .lineage import _projection_lineage
from .models import ColumnSemantic, LineageSource, QueryBindingsInfo, SchemaBinding
from .sql_parser import ParsedSelect, UnsupportedSQL, identifier_key, inspect_select_ast


def _same_identifier(declared: object, referenced: str) -> bool:
    # Match SQL identifiers with the parser's DuckDB ASCII-only case rule.
    # This is not fuzzy/alias matching. Execution database identity stays exact.
    return isinstance(declared, str) and identifier_key(declared) == identifier_key(referenced)


def _field_definition(
    source: LineageSource, schema: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    if (
        source.database is None or not source.database.strip()
        or not source.table.strip()
        or source.field is None or not source.field.strip()
    ):
        # COUNT(*) has a relation source, not a field to which metadata binds.
        return None
    tables = [
        table for table in schema
        if isinstance(table, Mapping)
        and table.get("database") == source.database
        and _same_identifier(table.get("id"), source.table)
    ]
    if len(tables) != 1:
        # Never choose the first/last duplicate or fall back to a different DB.
        return None
    fields = tables[0].get("fields")
    if not isinstance(fields, (list, tuple)):
        return None
    matches = [
        field for field in fields
        if isinstance(field, Mapping) and _same_identifier(field.get("name"), source.field)
    ]
    return matches[0] if len(matches) == 1 else None


def _bind_source(
    source: LineageSource, schema: Sequence[Mapping[str, Any]],
) -> SchemaBinding | None:
    """One shared exact lookup/metadata codec for output and query bindings."""
    definition = _field_definition(source, schema)
    if definition is None:
        return None
    return SchemaBinding(
        source=source.model_copy(deep=True),
        label=definition.get("label"),
        aliases=definition.get("aliases"),
        description=definition.get("description"),
        role=definition.get("role"),
        default_aggregation=definition.get("aggregation"),
    ).model_copy(deep=True)


def bind_schema(
    column: ColumnSemantic, schema: Sequence[Mapping[str, Any]],
) -> ColumnSemantic:
    """Return a detached copy enriched only from uniquely matched sources.

    Only resolved lineage is eligible. Unknown/unsupported, relation-only,
    absent and ambiguous sources receive no field binding. All original lineage
    entries/order and SQL aggregation/status/reason remain unchanged, even if
    only some sources match. Consumers must not equate status='resolved' with
    complete Schema binding.

    Rebinding replaces old bindings instead of accumulating stale metadata.
    Neither the input object nor the supplied Schema shares mutable lists with
    the returned result. Invalid metadata types fail Pydantic validation rather
    than being coerced into a fabricated definition.
    """
    if not isinstance(column, ColumnSemantic):
        raise TypeError("column must be a ColumnSemantic")
    result = column.model_copy(deep=True, update={"schema_bindings": []})
    if result.status != "resolved":
        return result

    for source in result.lineage or []:
        binding = _bind_source(source, schema)
        if binding is not None:
            result.schema_bindings.append(binding)
    return result


def prepare_query_bindings(
    statement: ParsedSelect | exp.Expression, database: str | None,
    schema: Sequence[Mapping[str, Any]],
) -> QueryBindingsInfo:
    """Prepare exact Schema evidence for supported fields actually used by SQL.

    Read the retained root AST; never reparse SQL or create ColumnSemantic.
    database must come from the same execution contract, never from SCHEMA.
    Sources are visited SELECT -> WHERE -> HAVING -> GROUP BY, then deduplicated
    by the existing database/table/field identity rule, retaining first spelling.
    COUNT(*)/COUNT(literal) are relation sources, not fake field bindings.

    This V1 capability covers the four scopes above, not ORDER BY/LIMIT or
    overall query semantics. Unsupported forms or missing/ambiguous identities
    return no bindings plus a non-resolved status. Check that status before
    consuming .bindings in understand_filters/understand_time_constraints.
    Existing output column bindings remain separate and are never extended.
    """
    if isinstance(statement, ParsedSelect):
        statement = statement.statement
        if statement is None:
            return QueryBindingsInfo(status="unknown", limitations=["ParsedSelect has no retained root AST"])
    if not isinstance(statement, exp.Expression):
        raise TypeError("statement must be an already parsed SQLGlot AST or ParsedSelect")
    if database is not None and not isinstance(database, str):
        raise TypeError("database must be a string or None from the execution contract")

    sources: list[LineageSource] = []
    try:
        parsed = inspect_select_ast(statement)
        if statement.args.get("qualify") is not None:
            raise UnsupportedSQL("QUALIFY/window filtering is unsupported")
        if statement.find(exp.Filter) is not None:
            raise UnsupportedSQL("aggregate-local FILTER scopes are unsupported")
        prior_aliases: set[str] = set()
        for projection, alias in zip(parsed.projections, parsed.aliases):
            current, _ = _projection_lineage(projection, parsed, prior_aliases, database)
            sources.extend(current)
            if alias is not None:
                prior_aliases.add(identifier_key(alias))
        # All aliases are in scope for predicates/grouping, including aliases
        # that could shadow base fields. The shared resolver rejects ambiguity.
        for scope, name in (("WHERE", "where"), ("HAVING", "having")):
            clause = statement.args.get(name)
            if clause is None:
                continue
            if clause.this.find(exp.Or, exp.Not) is not None:
                raise UnsupportedSQL("OR/NOT scopes cannot provide V1 query bindings")
            for predicate in _and_terms(clause.this):
                operand = _predicate_operand(scope, predicate, {})
                current, _ = _projection_lineage(operand, parsed, prior_aliases, database)
                sources.extend(current)
        group = statement.args.get("group")
        if group is not None:
            if any(value is not None for key, value in group.args.items() if key != "expressions"):
                raise UnsupportedSQL("CUBE/ROLLUP/GROUPING SETS/GROUP BY ALL are unsupported")
            if not group.expressions or any(not isinstance(key, exp.Column) or key.is_star for key in group.expressions):
                raise UnsupportedSQL("only plain field GROUP BY keys are supported")
            for key in group.expressions:
                current, _ = _projection_lineage(key, parsed, prior_aliases, database)
                sources.extend(current)
    except UnsupportedSQL as exc:
        return QueryBindingsInfo(status="unsupported", limitations=[str(exc)])
    if database is None or not database.strip():
        return QueryBindingsInfo(status="unknown", limitations=["execution database identity is unknown"])

    seen: set[tuple[str | None, str, str | None]] = set()
    bindings: list[SchemaBinding] = []
    limitations: list[str] = []
    for source in sources:
        if source.field is None or _identity(source) in seen:
            continue
        seen.add(_identity(source))
        binding = _bind_source(source, schema)
        if binding is None:
            limitations.append(f"missing or ambiguous Schema identity: {source.database}.{source.table}.{source.field}")
        else:
            bindings.append(binding)
    if limitations:
        return QueryBindingsInfo(status="unknown", limitations=limitations)
    return QueryBindingsInfo(bindings=bindings, status="resolved")


__all__ = ["QueryBindingsInfo", "bind_schema", "prepare_query_bindings"]
