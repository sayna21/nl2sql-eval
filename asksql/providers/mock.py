"""A deterministic provider for tests, the demo and the CI eval run."""

from __future__ import annotations

import re
from collections import defaultdict

_QUESTION = re.compile(r"^Question:[ \t]*(.+)$", re.MULTILINE)


def normalise_question(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower().rstrip("?.! ")


class MockProvider:
    """Answers from a fixed table keyed by question.

    A value may be a single string, or a list of strings that are returned on
    successive calls for the same question (used to script a repair attempt).
    """

    name = "mock"
    model = "mock"

    def __init__(self, answers: dict[str, str | list[str]], default: str = "I cannot answer that."):
        self._answers = {
            normalise_question(q): ([a] if isinstance(a, str) else list(a))
            for q, a in answers.items()
        }
        self._default = default
        self._calls: dict[str, int] = defaultdict(int)
        self.prompts: list[str] = []

    def complete(self, system: str, prompt: str) -> str:
        self.prompts.append(prompt)
        found = _QUESTION.findall(prompt)
        if not found:
            return self._default
        key = normalise_question(found[-1])
        replies = self._answers.get(key)
        if not replies:
            return self._default
        index = min(self._calls[key], len(replies) - 1)
        self._calls[key] += 1
        return replies[index]
