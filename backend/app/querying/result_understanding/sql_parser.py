"""Parse a deliberately small SQL subset without executing or rewriting SQL."""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError


class UnsupportedSQL(ValueError):
    """The SQL cannot be safely handled by the first-stage lineage parser."""

    def __init__(self, message: str, *, statement: exp.Expression | None = None):
        super().__init__(message)
        # A rejected single AST may still carry scoped diagnostics (JOIN ON,
        # QUALIFY, etc.). This is not a supported ParsedSelect or new capability.
        # Syntax errors/multiple statements never choose a partial/first AST.
        self.statement = statement


def identifier_key(name: str) -> str:
    """DuckDB identifiers use ASCII case-insensitive matching, even if quoted.

    Keep the original spelling in output; do not casefold Unicode field names.
    """
    return name.translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"))


@dataclass(frozen=True)
class ParsedSelect:
    projections: tuple[exp.Expression, ...]
    aliases: tuple[str | None, ...]
    table: str | None
    qualifier: str | None
    # Keep the root already parsed above so downstream readers never reparse.
    # Optional/keyword-only preserves the original four-argument constructor.
    statement: exp.Select | None = field(default=None, kw_only=True, compare=False, repr=False)


def parse_sql(sql: str) -> ParsedSelect:
    """Allow one SELECT over at most one unqualified physical table.

    CTEs, set operations, windows, joins, subqueries and expanding projections
    are rejected before any result ordinal is mapped. Expression-level support
    is checked separately by lineage.py. No catalog, connection or model is used.
    """
    try:
        statements = [statement for statement in sqlglot.parse(sql, read="duckdb") if statement is not None]
    except (ParseError, TokenError) as exc:
        raise UnsupportedSQL("SQL could not be parsed as DuckDB SQL") from exc
    if len(statements) != 1:
        raise UnsupportedSQL("exactly one SQL statement is required")
    try:
        return inspect_select_ast(statements[0])
    except UnsupportedSQL as exc:
        raise UnsupportedSQL(str(exc), statement=statements[0]) from exc


def inspect_select_ast(statement: exp.Expression) -> ParsedSelect:
    """Inspect an existing AST using the same subset checks, without parsing.

    This only reads nodes and returns references; it does not normalize/mutate
    the AST. Downstream consumers can also reject their own unsupported shapes.
    """
    if not isinstance(statement, exp.Select):
        raise UnsupportedSQL("only a single SELECT is supported; set operations are unsupported")
    if statement.args.get("with_") is not None or statement.find(exp.CTE) is not None:
        raise UnsupportedSQL("CTEs are unsupported")
    if statement.find(exp.Window) is not None:
        raise UnsupportedSQL("window functions are unsupported")
    if statement.find(exp.Subquery) is not None or len(list(statement.find_all(exp.Select))) != 1:
        raise UnsupportedSQL("subqueries are unsupported")
    if statement.args.get("joins"):
        raise UnsupportedSQL("joins and multiple source tables are unsupported")
    if statement.args.get("into") is not None:
        raise UnsupportedSQL("SELECT INTO is unsupported")
    if statement.find(exp.Columns) is not None:
        raise UnsupportedSQL("expanding COLUMNS projections are unsupported")

    projections = tuple(
        projection.this if isinstance(projection, exp.Alias) else projection
        for projection in statement.expressions
    )
    if any(
        isinstance(projection, exp.Star)
        or isinstance(projection, exp.Column) and projection.is_star
        for projection in projections
    ):
        raise UnsupportedSQL("star projections cannot be aligned without a catalog")

    table = qualifier = None
    from_clause = statement.args.get("from_")
    if from_clause is not None:
        source = from_clause.this
        if not isinstance(source, exp.Table) or not isinstance(source.this, exp.Identifier):
            raise UnsupportedSQL("only a physical table source is supported")
        # DuckDB schema/catalog qualifiers are not AskData execution.database.
        if source.db or source.catalog:
            raise UnsupportedSQL("schema/catalog-qualified table sources are unsupported")
        if any(value for key, value in source.args.items() if key not in {"this", "alias"}):
            raise UnsupportedSQL("modified table sources (such as PIVOT or sampling) are unsupported")
        alias = source.args.get("alias")
        if alias is not None and alias.args.get("columns"):
            raise UnsupportedSQL("table aliases that rename source columns are unsupported")
        table = source.name
        qualifier = source.alias_or_name

    return ParsedSelect(
        projections=projections,
        aliases=tuple(
            projection.alias if isinstance(projection, exp.Alias) else None
            for projection in statement.expressions
        ),
        table=table,
        qualifier=qualifier,
        statement=statement,
    )


__all__ = ["ParsedSelect", "UnsupportedSQL", "inspect_select_ast", "parse_sql"]
