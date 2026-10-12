from asksql.config import RESOURCE_DIR, ROOT, resource_path
from asksql.prompts import build_s2
from asksql.schema import describe


def test_bundled_assets_match_workspace_assets():
    for relative in (
        "data/descriptions.yaml",
        "eval/fewshot.jsonl",
        "eval/questions.jsonl",
        "eval/adversarial.jsonl",
        "tests/fixtures/tiny.sql",
    ):
        assert (RESOURCE_DIR / relative).read_bytes() == (ROOT / relative).read_bytes()


def test_installed_resources_work_without_workspace(monkeypatch, tmp_path):
    import asksql.config as config

    monkeypatch.setattr(config, "ROOT", tmp_path)
    assert resource_path("eval/fewshot.jsonl").is_file()
    from asksql.prompts import load_fewshot
    from asksql.schema import descriptions_text

    assert "CREATE TABLE trips" in build_s2(
        "Count trips",
        load_fewshot(resource_path("eval/fewshot.jsonl")),
        descriptions_text(resource_path("data/descriptions.yaml")),
    )
    assert len(describe(resource_path("data/descriptions.yaml"))["tables"]) == 3
