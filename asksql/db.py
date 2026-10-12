"""Read-only SQLite access with a statement authorizer, a timeout and a row cap.

This layer does not trust the guard. Even if a write statement reaches
`execute()`, the connection cannot change the database.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

# The only action codes a statement may use. SQLITE_RECURSIVE is allowed so that a
# runaway recursive CTE reaches the timeout instead of failing at compile time.
_ALLOWED_ACTIONS = frozenset(
    {
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_FUNCTION,
        sqlite3.SQLITE_RECURSIVE,
    }
)

# How many SQLite virtual-machine instructions run between timeout checks.
_PROGRESS_STEPS = 10_000


class QueryError(Exception):
    """The query failed to compile or run."""


class QueryTimeout(QueryError):
    """The query was aborted because it exceeded its time budget."""


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool  # True when more than max_rows rows were available


def _authorizer(action: int, arg1, arg2, db_name, trigger) -> int:
    """Called by SQLite while it compiles a statement, once per action it would perform."""
    if action not in _ALLOWED_ACTIONS:
        return sqlite3.SQLITE_DENY
    # For SQLITE_READ, arg1 is the table name. Keep SQLite's own catalogue
    # (sqlite_master, sqlite_schema, sqlite_stat1...) out of reach.
    if action == sqlite3.SQLITE_READ and arg1 and arg1.lower().startswith("sqlite_"):
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def open_readonly(path: str | Path) -> sqlite3.Connection:
    """Open an existing database file so that nothing on this connection can write."""
    db_file = Path(path)
    if not db_file.is_file():
        raise FileNotFoundError(f"database file not found: {db_file}")
    # mode=ro also stops SQLite from creating the file if it is missing.
    conn = sqlite3.connect(f"{db_file.resolve().as_uri()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    # 64 MB page cache. With the 2 MB default, GROUP BY over an index re-reads pages
    # constantly and legitimate queries drift towards the timeout.
    conn.execute("PRAGMA cache_size = -65536")
    # Installed after the PRAGMAs: the authorizer would deny the PRAGMA statements.
    conn.set_authorizer(_authorizer)
    return conn


def execute(
    conn: sqlite3.Connection, sql: str, timeout_s: float = 3.0, max_rows: int = 500
) -> QueryResult:
    """Run one statement, aborting after timeout_s and returning at most max_rows rows."""
    deadline = time.monotonic() + timeout_s

    def _check_deadline() -> int:
        # A non-zero return makes SQLite interrupt the running statement.
        return 1 if time.monotonic() > deadline else 0

    conn.set_progress_handler(_check_deadline, _PROGRESS_STEPS)
    try:
        cursor = conn.execute(sql)
        columns = [d[0] for d in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(max_rows + 1)
        cursor.close()
    except sqlite3.Error as err:
        if time.monotonic() > deadline:
            raise QueryTimeout(f"query exceeded {timeout_s:g} s and was aborted") from err
        raise QueryError(str(err)) from err
    except sqlite3.Warning as err:  # e.g. more than one statement in the string
        raise QueryError(str(err)) from err
    finally:
        conn.set_progress_handler(None, 0)

    truncated = len(rows) > max_rows
    return QueryResult(columns=columns, rows=rows[:max_rows], truncated=truncated)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
