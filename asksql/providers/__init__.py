from __future__ import annotations

from asksql.config import Settings
from asksql.providers.base import Provider, ProviderError
from asksql.providers.mock import MockProvider
from asksql.providers.ollama import OllamaProvider
from asksql.providers.openai_compat import OpenAICompatProvider

__all__ = [
    "MockProvider",
    "OllamaProvider",
    "OpenAICompatProvider",
    "Provider",
    "ProviderError",
    "get_provider",
]


def get_provider(settings: Settings, name: str | None = None, model: str | None = None) -> Provider:
    name = name or settings.provider
    if name == "ollama":
        return OllamaProvider(model or settings.model, settings.ollama_url, settings.llm_timeout_s)
    if name == "openai_compat":
        return OpenAICompatProvider(
            model or settings.openai_model,
            settings.openai_base_url,
            settings.openai_api_key,
            settings.llm_timeout_s,
        )
    if name == "mock":
        return MockProvider({})
    raise ProviderError(f"unknown provider: {name}")
