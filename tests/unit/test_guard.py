import pytest

from asksql.config import ALLOWED_TABLES
from asksql.guard import check_sql

ALLOWED = [
    ("plain select", "SELECT trip_id, fare_amount FROM trips"),
    (
        "join",
        "SELECT z.zone, COUNT(*) FROM trips t JOIN zones z ON z.zone_id = t.pu_zone_id GROUP BY z.zone",
    ),
    ("cte", "WITH big AS (SELECT * FROM trips WHERE fare_amount > 50) SELECT COUNT(*) FROM big"),
    (
        "subquery",
        "SELECT COUNT(*) FROM trips WHERE fare_amount > (SELECT AVG(fare_amount) FROM trips)",
    ),
    (
        "union",
        "SELECT zone FROM zones WHERE borough = 'Queens' UNION SELECT name FROM payment_types",
    ),
    ("lowercase", "select count(*) from trips"),
    ("uppercase", "SELECT COUNT(*) FROM TRIPS"),
    ("mixed case table", "Select Count(*) From Trips"),
    (
        "window",
        "SELECT vendor_id, RANK() OVER (ORDER BY COUNT(*) DESC) FROM trips GROUP BY vendor_id",
    ),
    ("keyword in a string", "SELECT COUNT(*) FROM zones WHERE zone = 'DROP TABLE trips; DELETE'"),
    ("date functions", "SELECT strftime('%H', pickup_at), julianday(dropoff_at) FROM trips"),
]

BLOCKED = [
    ("drop", "DROP TABLE trips"),
    ("delete", "DELETE FROM trips"),
    ("update", "UPDATE trips SET tip_amount = 0"),
    ("insert", "INSERT INTO payment_types VALUES (9, 'x')"),
    ("stacked", "SELECT 1; DROP TABLE trips"),
    ("comment-hidden stacked", "SELECT 1 /* x */; DELETE FROM trips"),
    ("cte then delete", "WITH x AS (SELECT 1) DELETE FROM trips"),
    ("pragma", "PRAGMA table_info(trips)"),
    ("pragma set", "PRAGMA query_only = OFF"),
    ("attach", "ATTACH DATABASE 'x.db' AS x"),
    ("vacuum", "VACUUM"),
    ("create", "CREATE TABLE t AS SELECT * FROM trips"),
    ("alter", "ALTER TABLE trips ADD COLUMN x INTEGER"),
    ("select into", "SELECT * INTO copy FROM trips"),
    ("replace", "REPLACE INTO payment_types VALUES (1, 'x')"),
    ("explain", "EXPLAIN SELECT * FROM trips"),
    ("sqlite_master", "SELECT name, sql FROM sqlite_master"),
    (
        "sqlite_master in subquery",
        "SELECT * FROM trips WHERE trip_id IN (SELECT rootpage FROM sqlite_master)",
    ),
    ("unknown table", "SELECT * FROM meta"),
    ("schema-qualified", "SELECT * FROM main.trips"),
    ("table-valued pragma", "SELECT * FROM pragma_table_info('trips')"),
    ("load_extension", "SELECT load_extension('evil.dll')"),
    ("denied function, mixed case", "SELECT Load_Extension('evil.dll') FROM trips"),
    ("empty", ""),
    ("whitespace", "   \n "),
    ("garbage", "hello, this is not sql"),
    ("unbalanced", "SELECT (((( FROM trips"),
]


@pytest.mark.parametrize("sql", [c[1] for c in ALLOWED], ids=[c[0] for c in ALLOWED])
def test_allowed_queries_pass(sql):
    result = check_sql(sql, ALLOWED_TABLES, 500)
    assert result.ok, result.reason
    assert result.reason is None
    assert "LIMIT" in result.sql.upper()


@pytest.mark.parametrize("sql", [c[1] for c in BLOCKED], ids=[c[0] for c in BLOCKED])
def test_dangerous_or_invalid_queries_are_blocked(sql):
    result = check_sql(sql, ALLOWED_TABLES, 500)
    assert not result.ok
    assert result.sql is None
    assert result.reason


def test_cte_name_is_not_treated_as_a_table():
    sql = "WITH busiest AS (SELECT pu_zone_id FROM trips) SELECT * FROM busiest"
    assert check_sql(sql, ALLOWED_TABLES, 500).ok


def test_cte_cannot_hide_a_forbidden_table():
    sql = "WITH x AS (SELECT * FROM sqlite_master) SELECT * FROM x"
    result = check_sql(sql, ALLOWED_TABLES, 500)
    assert not result.ok
    assert "sqlite_master" in result.reason


def test_allow_list_is_what_the_caller_passes():
    assert not check_sql("SELECT * FROM zones", {"trips"}, 500).ok


def test_limit_is_added_when_missing():
    result = check_sql("SELECT * FROM trips", ALLOWED_TABLES, 500)
    assert result.sql.upper().endswith("LIMIT 500")


def test_large_limit_is_clamped():
    result = check_sql("SELECT * FROM trips LIMIT 10000", ALLOWED_TABLES, 500)
    assert result.sql.upper().endswith("LIMIT 500")
    assert "10000" not in result.sql


def test_small_limit_is_kept():
    result = check_sql("SELECT * FROM trips ORDER BY fare_amount DESC LIMIT 5", ALLOWED_TABLES, 500)
    assert result.sql.upper().endswith("LIMIT 5")


def test_limit_only_in_subquery_still_gets_outer_limit():
    result = check_sql("SELECT * FROM (SELECT * FROM trips LIMIT 5)", ALLOWED_TABLES, 500)
    assert result.sql.upper().endswith("LIMIT 500")
    assert "LIMIT 5)" in result.sql.upper()


def test_negative_limit_is_replaced():
    # In SQLite, LIMIT -1 means "no limit".
    result = check_sql("SELECT * FROM trips LIMIT -1", ALLOWED_TABLES, 500)
    assert result.ok
    assert result.sql.upper().endswith("LIMIT 500")


def test_union_gets_one_outer_limit():
    result = check_sql(
        "SELECT zone FROM zones UNION SELECT name FROM payment_types", ALLOWED_TABLES, 50
    )
    assert result.sql.upper().endswith("LIMIT 50")


def test_limit_keeps_offset():
    result = check_sql("SELECT * FROM trips LIMIT 9999 OFFSET 3", ALLOWED_TABLES, 500)
    assert "LIMIT 500" in result.sql.upper()
    assert "OFFSET 3" in result.sql.upper()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM secret WHERE EXISTS (WITH secret AS (SELECT 1) SELECT * FROM secret)",
        "WITH x AS (WITH secret AS (SELECT 1) SELECT * FROM secret) SELECT * FROM secret",
        "SELECT * FROM secret UNION ALL SELECT * FROM (WITH secret AS (SELECT 1) SELECT * FROM secret)",
    ],
)
def test_cte_alias_cannot_exempt_an_unrelated_table(sql):
    assert not check_sql(sql, ALLOWED_TABLES).ok


def test_cte_names_follow_sqlite_case_insensitivity():
    assert check_sql("WITH Big AS (SELECT * FROM trips) SELECT * FROM BIG", ALLOWED_TABLES).ok


def test_sqlite_forward_cte_reference_is_allowed():
    sql = "WITH x AS (SELECT * FROM later), later AS (SELECT * FROM trips) SELECT * FROM x"
    assert check_sql(sql, ALLOWED_TABLES).ok
