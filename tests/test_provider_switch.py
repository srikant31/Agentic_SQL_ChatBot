"""LLM_PROVIDER selection: Gemini stays the default; Groq is opt-in. No network calls."""
import json
from unittest.mock import MagicMock, patch

import pytest

import sql_generator
from sql_generator import LLMProviderError, generate_sql, provider_settings


def fake_response(payload):
    response = MagicMock()
    response.content = json.dumps(payload)
    response.usage_metadata = {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}
    return response


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("LLM_PROVIDER", "GROQ_LLM_MODEL", "GEMINI_LLM_MODEL", "GROQ_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_gemini_is_the_default_provider():
    provider, label, key_env, model_env, model = provider_settings()
    assert (provider, label, key_env, model_env) == ("gemini", "Gemini", "GOOGLE_API_KEY", "GEMINI_LLM_MODEL")
    assert model == "gemini-3.6-flash"


def test_groq_settings_and_model_override(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", " GROQ ")
    assert provider_settings()[:4] == ("groq", "Groq", "GROQ_API_KEY", "GROQ_LLM_MODEL")
    assert provider_settings()[4] == "llama-3.3-70b-versatile"
    monkeypatch.setenv("GROQ_LLM_MODEL", "openai/gpt-oss-120b")
    assert provider_settings()[4] == "openai/gpt-oss-120b"


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "other")
    with pytest.raises(LLMProviderError, match="Unknown LLM_PROVIDER"):
        generate_sql("question", "schema")


def test_groq_path_builds_groq_client_and_returns_proposal(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    built = {}

    class FakeGroq:
        def __init__(self, **kwargs):
            built.update(kwargs)

        def invoke(self, messages):
            return fake_response({"sql": "SELECT 1", "explanation": "One.", "confidence": 0.9})

    monkeypatch.setattr("langchain_groq.ChatGroq", FakeGroq)
    with patch("sql_generator.ChatGoogleGenerativeAI") as gemini:
        result = generate_sql("question", "schema")
    assert built == {"temperature": 0, "model": "llama-3.3-70b-versatile"}
    gemini.assert_not_called()
    assert result["status"] == "proposal" and result["usage"]["total_tokens"] == 18


def test_groq_errors_name_groq_not_gemini(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")

    class PermissionDeniedError(Exception):
        pass

    class FakeGroq:
        def __init__(self, **kwargs):
            pass

        def invoke(self, messages):
            raise PermissionDeniedError("secret response body")

    monkeypatch.setattr("langchain_groq.ChatGroq", FakeGroq)
    with pytest.raises(LLMProviderError) as excinfo:
        generate_sql("question", "schema")
    assert "Groq denied access" in str(excinfo.value) and "GROQ_LLM_MODEL" in str(excinfo.value)
    assert "secret" not in str(excinfo.value) and "Gemini" not in str(excinfo.value)


def test_missing_groq_key_gives_actionable_error(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")  # real ChatGroq, no key set, no network call
    with pytest.raises(LLMProviderError, match="Check GROQ_API_KEY and GROQ_LLM_MODEL"):
        generate_sql("question", "schema")
