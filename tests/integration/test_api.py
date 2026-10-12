from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from asksql.api import app, provider_dep, settings_dep
from asksql.config import get_settings
from asksql.providers import MockProvider

ANSWERS = {
    "cash trips": "```sql\nSELECT COUNT(*) AS n FROM trips WHERE payment_type = 2\n```",
    "all trips": "```sql\nSELECT trip_id FROM trips\n```",
    "drop it": "```sql\nDROP TABLE trips\n```",
    "broken": "```sql\nSELECT nope FROM trips\n```",
}


@pytest.fixture
def client(tiny_db):
    settings = replace(
        get_settings(), db_path=tiny_db, provider="mock", model="mock", api_max_rows=10
    )
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[provider_dep] = lambda: MockProvider(ANSWERS)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_ask_returns_the_documented_shape(client):
    response = client.post("/ask", json={"question": "cash trips", "strategy": "s1"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "sql",
        "columns",
        "rows",
        "row_count",
        "attempts",
        "latency_ms",
        "blocked_reason",
        "error",
    }
    assert body["columns"] == ["n"]
    assert body["rows"] == [[5]]
    assert body["row_count"] == 1
    assert body["attempts"] == 1
    assert body["blocked_reason"] is None


def test_ask_defaults_to_s2(client):
    assert client.post("/ask", json={"question": "cash trips"}).json()["rows"] == [[5]]


def test_ask_caps_returned_rows(client):
    body = client.post("/ask", json={"question": "all trips"}).json()
    assert len(body["rows"]) == 10
    assert body["row_count"] == 20


def test_blocked_query_reports_a_reason(client):
    body = client.post("/ask", json={"question": "drop it"}).json()
    assert body["rows"] == []
    assert "SELECT" in body["blocked_reason"]
    assert client.post("/ask", json={"question": "cash trips"}).json()["rows"] == [[5]]


def test_sql_error_is_reported(client):
    body = client.post("/ask", json={"question": "broken", "strategy": "s1"}).json()
    assert "no such column" in body["error"]


def test_bad_requests_are_rejected(client):
    assert client.post("/ask", json={"question": ""}).status_code == 422
    assert client.post("/ask", json={"question": "x", "strategy": "s9"}).status_code == 422


def test_missing_database_is_a_503(client, tmp_path):
    settings = replace(get_settings(), db_path=tmp_path / "missing.db")
    app.dependency_overrides[settings_dep] = lambda: settings
    assert client.post("/ask", json={"question": "cash trips"}).status_code == 503


def test_schema_lists_tables_and_columns(client):
    body = client.get("/schema").json()
    tables = {t["name"]: t for t in body["tables"]}
    assert set(tables) == {"trips", "zones", "payment_types"}
    assert "pickup_at" in {c["name"] for c in tables["trips"]["columns"]}
    assert all(c["description"] for c in tables["trips"]["columns"])
    assert body["data_quality"]


def test_healthz(client):
    body = client.get("/healthz").json()
    assert body == {"status": "ok", "provider": "mock", "model": "mock", "database_present": True}


def test_index_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "AskSQL" in response.text


def test_whitespace_question_is_rejected(client):
    assert client.post("/ask", json={"question": "  \t  "}).status_code == 422


def test_question_is_trimmed(client):
    assert client.post("/ask", json={"question": "  cash trips  "}).json()["rows"] == [[5]]
