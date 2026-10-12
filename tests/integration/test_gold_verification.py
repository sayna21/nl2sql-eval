from asksql.config import resource_path
from asksql.evaluation.verify_gold import verify


def test_independent_reference_calculations_match_all_gold_queries(tiny_db):
    result = verify(tiny_db, resource_path("eval/questions.jsonl"))
    assert result["n"] == result["passed"] == 40
    assert result["human_verified"] is False
    assert result["database_sha256_before"] == result["database_sha256_after"]


def test_independent_checks_detect_wrong_gold_sql(tiny_db, tmp_path):
    import json

    source = resource_path("eval/questions.jsonl")
    questions = [json.loads(line) for line in source.read_text().splitlines()]
    questions[0]["gold_sql"] = "SELECT 999999"
    changed = tmp_path / "questions.jsonl"
    changed.write_text("".join(json.dumps(q) + "\n" for q in questions))
    result = verify(tiny_db, changed)
    assert result["passed"] == 39
    assert not result["items"][0]["passed"]
