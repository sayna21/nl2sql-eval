"""Prompt strategies.

S1: schema DDL only.
S2: DDL + column descriptions + fixed few-shot examples (+ one repair turn, see pipeline).

Each prompt puts the fixed material first and the question last, so a local model
can reuse its cached prefix from one question to the next.
"""

from __future__ import annotations

import json
from pathlib import Path

from asksql.config import resource_path
from asksql.schema import DDL, descriptions_text

FEWSHOT_PATH = resource_path("eval/fewshot.jsonl")

SYSTEM = (
    "You translate questions about New York City taxi trips into one SQLite SELECT query. "
    "Use only the tables and columns in the schema. "
    "Reply with the SQL only, inside a ```sql fenced block, with no explanation."
)


def load_fewshot(path: Path = FEWSHOT_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def build_s1(question: str) -> str:
    return f"Schema (SQLite):\n{DDL}\nQuestion: {question}\nSQL:"


def build_s2(
    question: str, fewshot: list[dict] | None = None, descriptions: str | None = None
) -> str:
    fewshot = load_fewshot() if fewshot is None else fewshot
    descriptions = descriptions_text() if descriptions is None else descriptions
    parts = [
        f"Schema (SQLite):\n{DDL}",
        f"Column descriptions:\n{descriptions}\n",
        "Examples:",
    ]
    for example in fewshot:
        parts.append(f"Question: {example['question']}\nSQL:\n```sql\n{example['sql']}\n```\n")
    parts.append(f"Question: {question}\nSQL:")
    return "\n".join(parts)


def build_repair(prompt: str, failed_sql: str, error: str) -> str:
    """Follow-up prompt for S2: show the model its SQL and the database error."""
    return (
        f"{prompt}\n```sql\n{failed_sql}\n```\n\n"
        f"That query failed in SQLite with this error:\n{error}\n\n"
        "Write a corrected query for the same question.\nSQL:"
    )


def build_prompt(strategy: str, question: str) -> str:
    if strategy == "s1":
        return build_s1(question)
    if strategy == "s2":
        return build_s2(question)
    raise ValueError(f"unknown strategy: {strategy}")
