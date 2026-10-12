import json

import httpx
import pytest
import respx

from asksql.config import get_settings
from asksql.providers import (
    MockProvider,
    OllamaProvider,
    OpenAICompatProvider,
    ProviderError,
    get_provider,
)


def test_mock_answers_by_question_regardless_of_case_and_punctuation():
    provider = MockProvider({"How many trips?": "SELECT COUNT(*) FROM trips"})
    assert (
        provider.complete("sys", "Question: how many TRIPS\nSQL:") == "SELECT COUNT(*) FROM trips"
    )


def test_mock_uses_the_last_question_in_the_prompt():
    provider = MockProvider({"real": "SELECT 2", "example": "SELECT 1"})
    prompt = "Question: example\nSQL: SELECT 1\n\nQuestion: real\nSQL:"
    assert provider.complete("sys", prompt) == "SELECT 2"


def test_mock_returns_scripted_replies_in_order_then_repeats_the_last():
    provider = MockProvider({"q": ["first", "second"]})
    replies = [provider.complete("sys", "Question: q\nSQL:") for _ in range(3)]
    assert replies == ["first", "second", "second"]


def test_mock_default_for_unknown_question():
    assert "cannot" in MockProvider({}).complete("sys", "Question: unknown\nSQL:")


@respx.mock
def test_ollama_sends_temperature_zero_and_returns_the_response():
    route = respx.post("http://localhost:11434/api/generate").mock(
        return_value=httpx.Response(200, json={"response": "```sql\nSELECT 1\n```"})
    )
    provider = OllamaProvider("qwen2.5-coder:7b")
    assert provider.complete("system text", "user text") == "```sql\nSELECT 1\n```"
    sent = json.loads(route.calls.last.request.content)
    assert sent["model"] == "qwen2.5-coder:7b"
    assert sent["system"] == "system text"
    assert sent["prompt"] == "user text"
    assert sent["stream"] is False
    assert sent["options"]["temperature"] == 0


@respx.mock
def test_ollama_http_error_becomes_provider_error():
    respx.post("http://localhost:11434/api/generate").mock(return_value=httpx.Response(500))
    with pytest.raises(ProviderError):
        OllamaProvider("m").complete("s", "p")


@respx.mock
def test_ollama_connection_error_becomes_provider_error():
    respx.post("http://localhost:11434/api/generate").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(ProviderError):
        OllamaProvider("m").complete("s", "p")


@respx.mock
def test_ollama_is_up_and_digest():
    respx.get("http://localhost:11434/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "m:1", "digest": "abc123"}]})
    )
    provider = OllamaProvider("m:1")
    assert provider.is_up()
    assert provider.model_digest() == "abc123"


@respx.mock
def test_openai_compat_request_and_response():
    route = respx.post("https://llm.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "SELECT 1"}}]})
    )
    provider = OpenAICompatProvider("some-model", "https://llm.test/v1/", "test-key")
    assert provider.complete("sys", "user") == "SELECT 1"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer test-key"
    sent = json.loads(request.content)
    assert sent["temperature"] == 0
    assert [m["role"] for m in sent["messages"]] == ["system", "user"]


def test_openai_compat_needs_configuration():
    with pytest.raises(ProviderError):
        OpenAICompatProvider("", "", "")


def test_get_provider_rejects_unknown_names():
    with pytest.raises(ProviderError):
        get_provider(get_settings(), "nope")
