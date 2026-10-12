import pytest

from asksql import pipeline
from asksql.providers import MockProvider
from asksql.providers.base import ProviderError

GOOD = "```sql\nSELECT COUNT(*) AS n FROM trips WHERE payment_type = 2\n```"
BROKEN = "```sql\nSELECT COUNT(*) FROM trips WHERE no_such_column = 2\n```"


def test_answers_a_question(conn):
    provider = MockProvider({"cash trips": GOOD})
    result = pipeline.ask("cash trips", provider, conn, strategy="s1")
    assert result.failure is None
    assert result.columns == ["n"]
    assert result.rows == [(5,)]
    assert result.row_count == 1
    assert result.attempts == 1
    assert "LIMIT 500" in result.sql
    assert result.latency_ms >= 0


def test_s2_repairs_once_after_a_sql_error(conn):
    provider = MockProvider({"cash trips": [BROKEN, GOOD]})
    result = pipeline.ask("cash trips", provider, conn, strategy="s2")
    assert result.failure is None
    assert result.rows == [(5,)]
    assert result.attempts == 2
    assert len(provider.prompts) == 2
    assert "no such column: no_such_column" in provider.prompts[1]
    assert "no_such_column = 2" in provider.prompts[1]


def test_s2_never_repairs_twice(conn):
    provider = MockProvider({"cash trips": [BROKEN, BROKEN, GOOD]})
    result = pipeline.ask("cash trips", provider, conn, strategy="s2")
    assert result.failure == pipeline.EXEC_ERROR
    assert "no such column" in result.error
    assert result.attempts == 2
    assert len(provider.prompts) == 2
    assert result.rows == []


def test_s1_does_not_repair(conn):
    provider = MockProvider({"cash trips": [BROKEN, GOOD]})
    result = pipeline.ask("cash trips", provider, conn, strategy="s1")
    assert result.failure == pipeline.EXEC_ERROR
    assert result.attempts == 1
    assert len(provider.prompts) == 1


def test_blocked_query_returns_a_reason_and_is_not_retried(conn):
    provider = MockProvider({"wipe it": ["```sql\nDELETE FROM trips\n```", GOOD]})
    result = pipeline.ask("wipe it", provider, conn, strategy="s2")
    assert result.failure == pipeline.BLOCKED
    assert "SELECT" in result.blocked_reason
    assert result.attempts == 1
    assert result.rows == []
    assert pipeline.ask("cash trips", MockProvider({"cash trips": GOOD}), conn).rows == [(5,)]


def test_stacked_attack_is_blocked(conn):
    provider = MockProvider({"attack": "```sql\nSELECT 1 /* x */; DELETE FROM trips\n```"})
    result = pipeline.ask("attack", provider, conn, strategy="s2")
    assert result.failure == pipeline.BLOCKED
    assert "exactly one statement" in result.blocked_reason


def test_no_sql_in_model_output(conn):
    result = pipeline.ask("anything", MockProvider({}), conn, strategy="s2")
    assert result.failure == pipeline.NO_SQL
    assert result.sql is None
    assert result.attempts == 1


def test_timeout_is_reported_and_not_retried(conn):
    runaway = (
        "```sql\nWITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) "
        "SELECT COUNT(*) FROM r\n```"
    )
    provider = MockProvider({"loop": [runaway, GOOD]})
    result = pipeline.ask("loop", provider, conn, strategy="s2", timeout_s=0.3)
    assert result.failure == pipeline.TIMEOUT
    assert result.attempts == 1


def test_provider_failure_is_reported(conn):
    class Down:
        name = model = "down"

        def complete(self, system, prompt):
            raise ProviderError("connection refused")

    result = pipeline.ask("q", Down(), conn)
    assert result.failure == pipeline.PROVIDER_ERROR
    assert "connection refused" in result.error


def test_unknown_strategy(conn):
    with pytest.raises(ValueError):
        pipeline.ask("q", MockProvider({}), conn, strategy="s9")
