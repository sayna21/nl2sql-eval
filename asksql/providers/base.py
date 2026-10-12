"""The interface every LLM provider implements."""

from __future__ import annotations

from typing import Protocol


class ProviderError(Exception):
    """The provider could not produce a completion (network, HTTP or config error)."""


class Provider(Protocol):
    name: str
    model: str

    def complete(self, system: str, prompt: str) -> str:
        """Return the model's raw text for one system + user prompt."""
        ...
