import pytest

from evidenceloop.llm import LLMClient


def test_generation_requires_provider_credentials(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY is required"):
        LLMClient(provider="gemini").generate_tests("prompt")


def test_generation_does_not_hide_provider_failure(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = LLMClient(provider="gemini")

    def fail_request(prompt, **kwargs):
        raise OSError("provider unavailable")

    client._call_gemini = fail_request

    with pytest.raises(RuntimeError, match="Gemini test generation failed"):
        client.generate_tests("prompt")


def test_generation_passes_output_token_limit_to_provider(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = LLMClient(provider="gemini", max_output_tokens=37)
    captured = {}

    def return_test(prompt, **kwargs):
        captured.update(kwargs)
        return ["def test_generated():\n    assert True"]

    client._call_gemini = return_test

    client.generate_tests("prompt")

    assert captured["max_output_tokens"] == 37


def test_generation_retries_only_up_to_configured_attempts(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = LLMClient(provider="gemini", max_attempts=3)
    calls = []

    def fail_retryable(prompt, **kwargs):
        calls.append(prompt)
        raise ConnectionError("provider unavailable")

    client._call_gemini = fail_retryable

    with pytest.raises(RuntimeError, match="Gemini test generation failed"):
        client.generate_tests("prompt")

    assert calls == ["prompt", "prompt", "prompt"]


def test_generation_stops_on_non_retryable_failure(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = LLMClient(provider="gemini", max_attempts=3)
    calls = []

    def fail_hard(prompt, **kwargs):
        calls.append(prompt)
        raise OSError("provider unavailable")

    client._call_gemini = fail_hard

    with pytest.raises(RuntimeError, match="Gemini test generation failed"):
        client.generate_tests("prompt")

    assert calls == ["prompt"]


def test_token_usage_accumulates_across_calls():
    client = LLMClient(provider="gemini")

    client._accumulate_usage({"prompt_token_count": 10, "total_token_count": 15})
    client._accumulate_usage({"prompt_token_count": 20, "total_token_count": 30})

    assert client.total_usage == {"prompt_token_count": 30, "total_token_count": 45}