"""Static SQL guard: parse to an AST and reject anything that is not a bounded read.

The guard fails closed. If sqlglot cannot parse the text, or parses it into
something we do not recognise, the query is blocked.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import Scope, traverse_scope

# sqlglot warns when it falls back to an opaque Command node; we block those anyway.
logging.getLogger("sqlglot").setLevel(logging.ERROR)

DIALECT = "sqlite"

# Statement and clause types that write, change schema or touch connection state.
# Command is sqlglot's catch-all for syntax it does not model (VACUUM, EXPLAIN, REPLACE...).
FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Merge,
    exp.TruncateTable,
    exp.Into,
    exp.Pragma,
    exp.Attach,
    exp.Detach,
    exp.Set,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Command,
)

DENIED_FUNCTIONS = frozenset(
    {
        "load_extension",
        "readfile",
        "writefile",
        "edit",
        "fts3_tokenizer",
        "zeroblob",
        "randomblob",
        "sqlite_compileoption_get",
        "sqlite_compileoption_used",
    }
)


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    sql: str | None = None  # the SQL to execute, with LIMIT enforced
    reason: str | None = None  # why it was blocked


def _blocked(reason: str) -> GuardResult:
    return GuardResult(ok=False, reason=reason)


def _function_name(node: exp.Func) -> str:
    name = node.name if isinstance(node, exp.Anonymous) else node.sql_name()
    return name.lower()


def _enforce_limit(root: exp.Query, max_limit: int) -> exp.Query:
    """Make sure the outermost query has a LIMIT no larger than max_limit."""
    limit = root.args.get("limit")
    if limit is None:
        return root.limit(max_limit)
    value = limit.expression
    # Anything other than a small non-negative integer literal is replaced: an
    # expression, a huge number, or SQLite's LIMIT -1 ("no limit").
    if isinstance(value, exp.Literal) and value.is_int and 0 <= int(value.this) <= max_limit:
        return root
    limit.set("expression", exp.Literal.number(max_limit))
    return root


def check_sql(sql: str, allowed_tables: Iterable[str], max_limit: int = 500) -> GuardResult:
    """Validate one SQL string and return it with an enforced LIMIT, or a block reason."""
    if not sql or not sql.strip():
        return _blocked("empty query")

    try:
        statements = [s for s in sqlglot.parse(sql, read=DIALECT) if s is not None]
    except (SqlglotError, RecursionError, ValueError) as err:
        return _blocked(f"could not parse SQL: {str(err).splitlines()[0][:120]}")

    if len(statements) != 1:
        return _blocked(f"expected exactly one statement, got {len(statements)}")
    root = statements[0]

    if not isinstance(root, exp.Select | exp.SetOperation):
        return _blocked(f"only SELECT queries are allowed, got {root.key.upper()}")

    for node in root.walk():
        if isinstance(node, FORBIDDEN_NODES):
            return _blocked(f"forbidden statement or clause: {node.key.upper()}")

    allowed = {t.lower() for t in allowed_tables}
    # SQLite identifiers are case-insensitive, including CTE names. Normalize a copy
    # for scope resolution without changing the returned query or string literals.
    normalized = root.copy()
    for identifier in normalized.find_all(exp.Identifier):
        identifier.set("this", identifier.this.lower())
    cte_references = set()
    try:
        for scope in traverse_scope(normalized):
            for table in scope.tables:
                source = scope.sources.get(table.alias_or_name)
                parent = scope.parent
                # SQLite permits a CTE to reference a later CTE in the same WITH.
                while not isinstance(source, Scope) and parent is not None:
                    source = parent.cte_sources.get(table.alias_or_name)
                    parent = parent.parent
                if isinstance(source, Scope):
                    cte_references.add(id(table))
    except (SqlglotError, RecursionError, ValueError) as err:
        return _blocked(f"could not resolve query scopes: {err}")
    for table in normalized.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            return _blocked("table-valued functions are not allowed")
        if table.db or table.catalog:
            return _blocked(f"schema-qualified table is not allowed: {table.sql(dialect=DIALECT)}")
        name = table.name.lower()
        if name not in allowed and id(table) not in cte_references:
            return _blocked(f"table is not in the allow-list: {table.name}")

    for func in root.find_all(exp.Func):
        name = _function_name(func)
        if name in DENIED_FUNCTIONS:
            return _blocked(f"function is not allowed: {name}")

    root = _enforce_limit(root, max_limit)
    return GuardResult(ok=True, sql=root.sql(dialect=DIALECT))
