"""HTTP API: POST /ask, GET /schema, GET /healthz and the static page at /."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from asksql import pipeline
from asksql.config import Settings, get_settings
from asksql.db import open_readonly
from asksql.providers import Provider, ProviderError, get_provider
from asksql.schema import describe

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="AskSQL", version="0.1.0")


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    strategy: Literal["s1", "s2"] = "s2"

    @field_validator("question")
    @classmethod
    def trim_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must contain non-whitespace characters")
        return value


class AskResponse(BaseModel):
    sql: str | None
    columns: list[str]
    rows: list[list]
    row_count: int
    attempts: int
    latency_ms: float
    blocked_reason: str | None = None
    error: str | None = None


def settings_dep() -> Settings:
    return get_settings()


def provider_dep(settings: Settings = Depends(settings_dep)) -> Provider:
    try:
        return get_provider(settings)
    except ProviderError as err:
        raise HTTPException(status_code=503, detail=str(err)) from err


@app.post("/ask", response_model=AskResponse)
def ask(
    body: AskRequest,
    settings: Settings = Depends(settings_dep),
    provider: Provider = Depends(provider_dep),
) -> AskResponse:
    # A fresh read-only connection per request: sqlite3 connections are bound to one thread.
    try:
        conn = open_readonly(settings.db_path)
    except FileNotFoundError as err:
        raise HTTPException(status_code=503, detail=str(err)) from err
    try:
        answer = pipeline.ask(
            body.question,
            provider,
            conn,
            strategy=body.strategy,
            max_limit=settings.max_limit,
            timeout_s=settings.timeout_s,
        )
    finally:
        conn.close()
    return AskResponse(
        sql=answer.sql,
        columns=answer.columns,
        rows=[list(row) for row in answer.rows[: settings.api_max_rows]],
        row_count=answer.row_count,
        attempts=answer.attempts,
        latency_ms=answer.latency_ms,
        blocked_reason=answer.blocked_reason,
        error=None if answer.failure in (None, pipeline.BLOCKED) else answer.error,
    )


@app.get("/schema")
def schema() -> dict:
    return describe()


@app.get("/healthz")
def healthz(settings: Settings = Depends(settings_dep)) -> dict:
    model = settings.openai_model if settings.provider == "openai_compat" else settings.model
    return {
        "status": "ok",
        "provider": settings.provider,
        "model": model,
        "database_present": settings.db_path.is_file(),
    }


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
