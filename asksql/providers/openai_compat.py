"""Any server that speaks the OpenAI chat-completions API. Optional; configured via .env."""

from __future__ import annotations

import httpx

from asksql.providers.base import ProviderError


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(self, model: str, base_url: str, api_key: str, timeout_s: float = 60.0):
        if not base_url or not model:
            raise ProviderError("OPENAI_BASE_URL and OPENAI_MODEL must be set for this provider")
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_s = timeout_s

    def complete(self, system: str, prompt: str) -> str:
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self._timeout_s,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as err:
            raise ProviderError(f"chat-completions request failed: {err}") from err
