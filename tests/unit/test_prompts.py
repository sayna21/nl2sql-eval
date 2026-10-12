import json
import re
from collections import Counter

import sqlglot

from asksql import prompts
from asksql.config import ROOT
from asksql.evaluation.run_eval import ADVERSARIAL_PATH, QUESTIONS_PATH, load_jsonl

EXPECTED_CATEGORIES = {
    "filter_agg": 10,
    "group_order": 10,
    "join": 8,
    "time": 6,
    "window_subquery": 4,
    "data_quality": 2,
}


def _norm_text(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", text.lower())).strip()


def _norm_sql(sql: str) -> str:
    return sqlglot.parse_one(sql, read="sqlite").sql(dialect="sqlite").lower()


def test_s1_is_schema_only():
    prompt = prompts.build_s1("How many trips?")
    assert "CREATE TABLE trips" in prompt
    assert "Column descriptions" not in prompt
    assert "Examples:" not in prompt
    assert prompt.rstrip().endswith("Question: How many trips?\nSQL:")


def test_s2_includes_descriptions_and_fewshot():
    fewshot = prompts.load_fewshot()
    prompt = prompts.build_s2("How many trips?")
    assert "CREATE TABLE trips" in prompt
    assert "Column descriptions" in prompt
    assert "joins to zones.zone_id" in prompt
    assert "Data quality notes" in prompt
    assert len(fewshot) == 3
    for example in fewshot:
        assert example["question"] in prompt
        assert example["sql"] in prompt
    assert prompt.rstrip().endswith("Question: How many trips?\nSQL:")


def test_question_comes_last_so_the_prefix_is_shared():
    a, b = prompts.build_s2("first question"), prompts.build_s2("second question")
    shared = len(a) - len("first question\nSQL:")
    assert a[:shared] == b[:shared]


def test_repair_prompt_carries_the_sql_and_the_error():
    prompt = prompts.build_repair(
        "BASE\nQuestion: q\nSQL:", "SELECT nope FROM trips", "no such column: nope"
    )
    assert prompt.startswith("BASE")
    assert "SELECT nope FROM trips" in prompt
    assert "no such column: nope" in prompt


def test_fewshot_examples_cover_join_time_and_group_by():
    assert {e["kind"] for e in prompts.load_fewshot()} == {"join", "time", "group_by"}


def test_fewshot_does_not_overlap_the_eval_set():
    questions = load_jsonl(QUESTIONS_PATH)
    eval_text = {_norm_text(q["question"]) for q in questions}
    eval_sql = {_norm_sql(q["gold_sql"]) for q in questions}
    for example in prompts.load_fewshot():
        assert _norm_text(example["question"]) not in eval_text, example["id"]
        assert _norm_sql(example["sql"]) not in eval_sql, example["id"]


def test_eval_set_shape():
    questions = load_jsonl(QUESTIONS_PATH)
    assert len(questions) == 40
    assert len({q["id"] for q in questions}) == 40
    assert len({_norm_text(q["question"]) for q in questions}) == 40
    assert Counter(q["category"] for q in questions) == EXPECTED_CATEGORIES
    required = {
        "id",
        "question",
        "gold_sql",
        "category",
        "ordered",
        "difficulty",
        "verified_by",
        "notes",
    }
    for q in questions:
        assert required <= set(q), q["id"]
        assert isinstance(q["ordered"], bool)


def test_adversarial_set_shape():
    attacks = load_jsonl(ADVERSARIAL_PATH)
    assert len(attacks) == 10
    assert len({a["attack"] for a in attacks}) == 10
    for attack in attacks:
        assert {"id", "prompt", "attack", "sql"} <= set(attack)


def test_eval_files_are_valid_jsonl():
    for name in ("questions.jsonl", "adversarial.jsonl", "fewshot.jsonl"):
        for line in (ROOT / "eval" / name).read_text(encoding="utf-8").splitlines():
            if line.strip():
                json.loads(line)
