import json
from dataclasses import replace
from pathlib import Path

import pytest

from asksql.config import ALLOWED_TABLES, get_settings
from asksql.db import execute, file_sha256
from asksql.evaluation import report
from asksql.evaluation.compare import results_match
from asksql.evaluation.run_eval import (
    ADVERSARIAL_PATH,
    QUESTIONS_PATH,
    load_jsonl,
    mock_answer_key,
    run_eval,
    select_questions,
)
from asksql.guard import check_sql
from asksql.providers import MockProvider
from asksql.schema import build_db_from_script

FIXTURES = Path(__file__).parent.parent / "fixtures"

QUESTIONS = [
    {"id": "q1", "question": "cash trips", "category": "filter_agg", "ordered": False,
     "gold_sql": "SELECT COUNT(*) FROM trips WHERE payment_type = 2", "verified_by": "tester"},
    {"id": "q2", "question": "trips by vendor", "category": "group_order", "ordered": False,
     "gold_sql": "SELECT vendor_id, COUNT(*) FROM trips GROUP BY vendor_id", "verified_by": "tester"},
    {"id": "q3", "question": "top fare", "category": "filter_agg", "ordered": False,
     "gold_sql": "SELECT MAX(fare_amount) FROM trips", "verified_by": "tester"},
    {"id": "q4", "question": "jfk pickups", "category": "join", "ordered": False,
     "gold_sql": "SELECT COUNT(*) FROM trips t JOIN zones z ON z.zone_id = t.pu_zone_id "
                 "WHERE z.zone = 'JFK Airport'", "verified_by": "tester"},
    {"id": "q5", "question": "not checked yet", "category": "join", "ordered": False,
     "gold_sql": "SELECT COUNT(*) FROM zones", "verified_by": None},
]  # fmt: skip

# Three right answers, written differently from the gold SQL, and one wrong one
# (drop-off instead of pick-up): 3/4 = 75%.
MOCK_ANSWERS = {
    "cash trips": "SELECT COUNT(*) FROM trips WHERE payment_type = 2",
    "trips by vendor": "SELECT vendor_id, COUNT(*) AS n FROM trips GROUP BY vendor_id ORDER BY n",
    "top fare": "SELECT fare_amount FROM trips ORDER BY fare_amount DESC LIMIT 1",
    "jfk pickups": "SELECT COUNT(*) FROM trips t JOIN zones z ON z.zone_id = t.do_zone_id "
    "WHERE z.zone = 'JFK Airport'",
}


# A short timeout keeps the runaway-CTE attack from costing 3 s on each of its three paths.
SETTINGS = replace(get_settings(), timeout_s=0.5)


@pytest.fixture(scope="module")
def eval_run(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("eval")
    tiny_db = build_db_from_script(FIXTURES / "tiny.sql", tmp_path / "tiny.db")
    questions_path = tmp_path / "questions.jsonl"
    questions_path.write_text("\n".join(json.dumps(q) for q in QUESTIONS), encoding="utf-8")
    adversarial = load_jsonl(ADVERSARIAL_PATH)
    answers = {q: f"```sql\n{sql}\n```" for q, sql in MOCK_ANSWERS.items()}
    answers.update({a["prompt"]: f"```sql\n{a['sql']}\n```" for a in adversarial})
    before = file_sha256(tiny_db)
    out_path, result = run_eval(
        MockProvider(answers),
        tiny_db,
        SETTINGS,
        ["s1", "s2"],
        questions_path=questions_path,
        out_dir=tmp_path / "results",
        run_tests=False,
    )
    return {"path": out_path, "result": result, "db": tiny_db, "sha_before": before}


def test_only_verified_questions_are_scored(eval_run):
    result = eval_run["result"]
    assert result["n_questions"] == 5
    assert result["n_verified"] == 4
    assert result["n_evaluated"] == 4


def test_known_answer_key_gives_known_accuracy(eval_run):
    for strategy in ("s1", "s2"):
        summary = eval_run["result"]["strategies"][strategy]
        assert (summary["correct"], summary["n"]) == (3, 4)
        assert summary["accuracy"] == 0.75


def test_accuracy_breakdown(eval_run):
    summary = eval_run["result"]["strategies"]["s2"]
    by_id = {item["id"]: item for item in summary["items"]}
    assert by_id["q1"]["ok"] and by_id["q2"]["ok"] and by_id["q3"]["ok"]
    assert by_id["q4"]["failure_type"] == "wrong_result"
    assert summary["by_category"]["filter_agg"] == {"n": 2, "correct": 2, "accuracy": 1.0}
    assert summary["by_category"]["join"] == {"n": 1, "correct": 0, "accuracy": 0.0}
    assert summary["failures_by_type"] == {"wrong_result": 1}
    assert summary["p50_latency_ms"] is not None


def test_database_is_unchanged_by_the_run(eval_run):
    result = eval_run["result"]
    assert result["db_sha256_before"] == result["db_sha256_after"] == eval_run["sha_before"]
    assert file_sha256(eval_run["db"]) == eval_run["sha_before"]


def test_every_adversarial_item_passes(eval_run):
    result = eval_run["result"]
    assert result["adversarial_total"] == 10
    assert result["adversarial_pass"] == 10
    assert result["false_blocks"] == 0
    by_attack = {item["attack"]: item for item in result["adversarial"]["items"]}
    assert by_attack["drop_table"]["guard"].startswith("blocked")
    assert by_attack["drop_table"]["executor_without_guard"].startswith("denied")
    assert by_attack["attach"]["executor_without_guard"].startswith("denied")
    assert by_attack["sqlite_master"]["executor_without_guard"].startswith("denied")
    # The runaway CTE is a valid SELECT, so the guard lets it through and the timeout stops it.
    assert by_attack["infinite_recursion"]["guard"] == "allowed: timeout"
    assert by_attack["infinite_recursion"]["model"] == "timeout"


def test_result_file_has_provenance(eval_run):
    saved = json.loads(eval_run["path"].read_text(encoding="utf-8"))
    for key in (
        "git_sha", "dirty", "started_at", "finished_at", "command", "params", "machine",
        "python", "tests", "model_tag", "data_source", "trip_rows", "n_verified",
        "adversarial_pass", "adversarial_total", "false_blocks",
        "db_sha256_before", "db_sha256_after",
    ):  # fmt: skip
        assert key in saved, key
    assert eval_run["path"].name.startswith("eval-")
    assert saved["trip_rows"] == 20
    assert saved["data_source"] == "fixture"
    assert set(saved["machine"]) == {"os", "cpu", "cores", "ram_gb"}
    assert saved["params"]["strategies"] == ["s1", "s2"]


def test_report_is_generated_from_the_json(eval_run):
    out = report.write_latest(eval_run["path"].parent)
    text = out.read_text(encoding="utf-8")
    assert eval_run["path"].name in text
    assert "| S2 | 3/4 | 75.0% |" in text
    assert "10/10" in text
    assert "jfk pickups" in text
    assert "DRAFT" not in text


def test_report_marks_unverified_runs_as_draft(tiny_db, tmp_path):
    questions = load_jsonl(QUESTIONS_PATH)
    adversarial = load_jsonl(ADVERSARIAL_PATH)
    out_path, result = run_eval(
        MockProvider(mock_answer_key(questions, adversarial)),
        tiny_db,
        SETTINGS,
        ["s2"],
        out_dir=tmp_path,
        include_unverified=True,
        run_tests=False,
    )
    assert result["n_evaluated"] == 40
    assert result["strategies"]["s2"]["accuracy"] == 1.0
    assert "DRAFT" in report.write_latest(tmp_path).read_text(encoding="utf-8")


def test_select_questions():
    assert [q["id"] for q in select_questions(QUESTIONS, include_unverified=False)] == [
        "q1", "q2", "q3", "q4",
    ]  # fmt: skip
    assert len(select_questions(QUESTIONS, include_unverified=True)) == 5


@pytest.mark.parametrize("question", load_jsonl(QUESTIONS_PATH), ids=lambda q: q["id"])
def test_gold_sql_passes_the_guard_and_keeps_its_meaning(conn, question):
    """The guard rewrites SQL through the AST; that must not change what a query returns."""
    verdict = check_sql(question["gold_sql"], ALLOWED_TABLES, 500)
    assert verdict.ok, verdict.reason
    raw = execute(conn, question["gold_sql"])
    guarded = execute(conn, verdict.sql)
    assert len(raw.rows) <= 100
    assert results_match(guarded.rows, raw.rows, ordered=True)
