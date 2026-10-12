"""Pull a SQL statement out of free-form model output."""

from __future__ import annotations

import re

_FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+-]*)[ \t]*\r?\n(.*?)```", re.DOTALL)
_SQL_START = re.compile(r"^\s*(?:with|select)\b", re.IGNORECASE)
_SQL_LINE = re.compile(r"^[ \t]*(?:with|select)\b", re.IGNORECASE | re.MULTILINE)


def _clean(sql: str) -> str:
    return sql.strip().rstrip(";").strip()


def extract_sql(text: str) -> str | None:
    """Return the first SQL statement in `text`, or None if there is none.

    Order of preference: the first fenced block tagged sql, then the first fenced
    block that starts like a query, then the first line that starts with SELECT or
    WITH. Only trailing semicolons are removed, so a stacked query such as
    "SELECT 1; DROP TABLE t" reaches the guard intact and is blocked there.
    """
    if not text or not text.strip():
        return None

    blocks = _FENCE.findall(text)
    for lang, body in blocks:
        if lang.lower() in {"sql", "sqlite"} and body.strip():
            return _clean(body)
    for _, body in blocks:
        if _SQL_START.match(body):
            return _clean(body)

    match = _SQL_LINE.search(text)
    if match is None:
        return None
    candidate = text[match.start() :]
    if ";" in candidate:
        # Drop prose after the last statement terminator.
        candidate = candidate[: candidate.rindex(";") + 1]
    else:
        # No terminator: the statement ends at the first blank line.
        candidate = re.split(r"\r?\n[ \t]*\r?\n", candidate, maxsplit=1)[0]
    return _clean(candidate) or None
