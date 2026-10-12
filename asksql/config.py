"""Runtime settings, read from the environment (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(os.environ.get("ASKSQL_HOME", Path.cwd())).resolve()
RESOURCE_DIR = Path(__file__).resolve().parent / "resources"


def resource_path(relative: str) -> Path:
    """Use workspace assets when present, otherwise the bundled distribution assets."""
    local = ROOT / relative
    return local if local.is_file() else RESOURCE_DIR / relative


ALLOWED_TABLES = frozenset({"trips", "zones", "payment_types"})


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader: KEY=VALUE lines, existing environment wins."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


@dataclass(frozen=True)
class Settings:
    db_path: Path
    provider: str
    model: str
    ollama_url: str
    openai_base_url: str
    openai_api_key: str
    openai_model: str
    max_limit: int = 500  # hard cap the guard clamps LIMIT to
    timeout_s: float = 3.0  # per-query execution budget
    api_max_rows: int = 100  # rows returned by POST /ask
    llm_timeout_s: float = 180.0


def get_settings() -> Settings:
    _load_dotenv(ROOT / ".env")
    env = os.environ.get
    return Settings(
        db_path=Path(env("ASKSQL_DB", str(ROOT / "data" / "taxi.db"))),
        provider=env("ASKSQL_PROVIDER", "ollama"),
        model=env("ASKSQL_MODEL", "qwen2.5-coder:7b"),
        ollama_url=env("OLLAMA_URL", "http://localhost:11434"),
        openai_base_url=env("OPENAI_BASE_URL", ""),
        openai_api_key=env("OPENAI_API_KEY", ""),
        openai_model=env("OPENAI_MODEL", ""),
    )
