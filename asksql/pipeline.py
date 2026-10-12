"""Question in, guarded SQL and rows out."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field

from asksql import prompts
from asksql.config import ALLOWED_TABLES
from asksql.db import QueryError, QueryTimeout, execute
from asksql.extract import extract_sql
from asksql.guard import check_sql
from asksql.providers.base import Provider, ProviderError

STRATEGIES = ("s1", "s2")

# Why a request produced no rows. None means it ran.
NO_SQL = "no_sql"
BLOCKED = "blocked"
EXEC_ERROR = "exec_error"
TIMEOUT = "timeout"
PROVIDER_ERROR = "provider_error"


@dataclass
class AskResult:
    question: str
    strategy: str
    sql: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    row_count: int = 0
    attempts: int = 0
    latency_ms: float = 0.0
    failure: str | None = None
    blocked_reason: str | None = None
    error: str | None = None


def ask(
    question: str,
    provider: Provider,
    conn: sqlite3.Connection,
    strategy: str = "s2",
    max_limit: int = 500,
    timeout_s: float = 3.0,
) -> AskResult:
    """Generate SQL for a question, check it, run it, and repair once under S2."""
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy: {strategy}")

    result = AskResult(question=question, strategy=strategy)
    started = time.perf_counter()
    prompt = prompts.build_prompt(strategy, question)
    max_attempts = 2 if strategy == "s2" else 1

    while result.attempts < max_attempts:
        result.attempts += 1
        try:
            raw = provider.complete(prompts.SYSTEM, prompt)
        except ProviderError as err:
            result.failure, result.error = PROVIDER_ERROR, str(err)
            break

        sql = extract_sql(raw)
        if sql is None:
            result.failure, result.error = NO_SQL, "no SQL found in the model output"
            break
        result.sql = sql

        verdict = check_sql(sql, ALLOWED_TABLES, max_limit)
        if not verdict.ok:
            # Never retry a blocked query: the model must not get to probe the guard.
            result.failure, result.blocked_reason = BLOCKED, verdict.reason
            break
        result.sql = verdict.sql

        try:
            outcome = execute(conn, verdict.sql, timeout_s=timeout_s, max_rows=max_limit)
        except QueryTimeout as err:
            result.failure, result.error = TIMEOUT, str(err)
            break
        except QueryError as err:
            result.failure, result.error = EXEC_ERROR, str(err)
            # Only a database error is worth sending back, and only once.
            prompt = prompts.build_repair(prompt, sql, str(err))
            continue

        result.failure = result.error = None
        result.columns, result.rows = outcome.columns, outcome.rows
        result.row_count = len(outcome.rows)
        break

    result.latency_ms = round((time.perf_counter() - started) * 1000, 1)
    return result
