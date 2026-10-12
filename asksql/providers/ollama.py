"""Local models served by Ollama."""

from __future__ import annotations

import httpx

from asksql.providers.base import ProviderError


class OllamaProvider:
    name = "ollama"

    def __init__(
        self, model: str, base_url: str = "http://localhost:11434", timeout_s: float = 180.0
    ):
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def complete(self, system: str, prompt: str) -> str:
        payload = {
            "model": self.model,
            "system": system,
            "prompt": prompt,
            "stream": False,
            # temperature 0 and a fixed seed keep runs repeatable.
            "options": {"temperature": 0, "seed": 0, "num_predict": 400, "num_ctx": 4096},
        }
        try:
            response = httpx.post(
                f"{self._base_url}/api/generate", json=payload, timeout=self._timeout_s
            )
            response.raise_for_status()
            return response.json()["response"]
        except (httpx.HTTPError, KeyError, ValueError) as err:
            raise ProviderError(f"ollama request failed: {err}") from err

    def is_up(self) -> bool:
        try:
            return httpx.get(f"{self._base_url}/api/tags", timeout=2.0).status_code == 200
        except httpx.HTTPError:
            return False

    def model_digest(self) -> str | None:
        """Digest of the pulled model, so a results file pins the exact weights."""
        try:
            tags = httpx.get(f"{self._base_url}/api/tags", timeout=5.0).json()
        except (httpx.HTTPError, ValueError):
            return None
        for entry in tags.get("models", []):
            if entry.get("name") == self.model or entry.get("model") == self.model:
                return entry.get("digest")
        return None
