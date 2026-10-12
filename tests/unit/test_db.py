import sqlite3
import time

import pytest

from asksql.db import QueryError, QueryTimeout, execute, file_sha256, open_readonly

INFINITE = "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT COUNT(*) FROM r"

WRITES = [
    "DELETE FROM trips",
    "UPDATE trips SET tip_amount = 0",
    "INSERT INTO payment_types VALUES (9, 'x')",
    "DROP TABLE trips",
    "CREATE TABLE evil (x INTEGER)",
    "ATTACH DATABASE 'leak.db' AS leak",
    "PRAGMA query_only = OFF",
]


def test_select_returns_columns_and_rows(conn):
    result = execute(conn, "SELECT trip_id, fare_amount FROM trips ORDER BY trip_id LIMIT 2")
    assert result.columns == ["trip_id", "fare_amount"]
    assert result.rows == [(1, 12.0), (2, 70.0)]
    assert result.truncated is False


@pytest.mark.parametrize("sql", WRITES)
def test_writes_are_denied_without_the_guard(conn, tiny_db, sql):
    before = file_sha256(tiny_db)
    with pytest.raises(QueryError):
        execute(conn, sql)
    assert file_sha256(tiny_db) == before
    assert execute(conn, "SELECT COUNT(*) FROM trips").rows == [(20,)]


def test_authorizer_denies_before_query_only_is_reached(conn):
    with pytest.raises(QueryError, match="not authorized"):
        execute(conn, "DELETE FROM trips")


@pytest.mark.parametrize("table", ["sqlite_master", "sqlite_schema", "SQLITE_MASTER"])
def test_schema_catalogue_cannot_be_read_without_the_guard(conn, table):
    with pytest.raises(QueryError):
        execute(conn, f"SELECT name, sql FROM {table}")


def test_stacked_statements_are_rejected(conn):
    with pytest.raises(QueryError):
        execute(conn, "SELECT 1; DELETE FROM trips")
    assert execute(conn, "SELECT COUNT(*) FROM trips").rows == [(20,)]


def test_runaway_recursive_cte_hits_the_timeout(conn):
    started = time.monotonic()
    with pytest.raises(QueryTimeout):
        execute(conn, INFINITE, timeout_s=0.5)
    assert 0.4 < time.monotonic() - started < 3.0


def test_connection_is_usable_after_a_timeout(conn):
    with pytest.raises(QueryTimeout):
        execute(conn, INFINITE, timeout_s=0.2)
    assert execute(conn, "SELECT COUNT(*) FROM zones").rows == [(6,)]


def test_row_cap(conn):
    result = execute(conn, "SELECT trip_id FROM trips", max_rows=5)
    assert len(result.rows) == 5
    assert result.truncated is True


def test_sql_error_is_reported(conn):
    with pytest.raises(QueryError, match="no such column"):
        execute(conn, "SELECT nope FROM trips")


def test_open_fails_when_file_is_missing(tmp_path):
    missing = tmp_path / "nope.db"
    with pytest.raises(FileNotFoundError):
        open_readonly(missing)
    assert not missing.exists()


def test_query_only_alone_blocks_writes(tiny_db):
    # The layer under the authorizer: a read-only handle with no authorizer installed.
    raw = sqlite3.connect(f"{tiny_db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            raw.execute("DELETE FROM trips")
    finally:
        raw.close()
