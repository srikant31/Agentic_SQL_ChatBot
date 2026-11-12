import json
from unittest.mock import patch, MagicMock
import pytest

from sql_generator import LLMProviderError, generate_sql


@pytest.fixture(autouse=True)
def isolate_provider(monkeypatch):
    # These legacy response-parser tests mock Gemini; local .env settings must not switch them to a real provider.
    monkeypatch.setenv("LLM_PROVIDER", "gemini")


def make_fake_response(text: str):
    """Builds a fake object mimicking what ChatGoogleGenerativeAI.invoke()
    returns, so we never make a real network call in tests — tests should
    be fast, free, and deterministic, not dependent on Gemini being up."""
    fake = MagicMock()
    fake.content = text
    return fake


@patch("sql_generator.ChatGoogleGenerativeAI")
def test_generate_sql_parses_valid_json(mock_llm_class):
    """The core happy path: Gemini returns well-formed JSON, and we should
    get back a clean dict with 'sql' and 'explanation'."""
    mock_llm_class.return_value.invoke.return_value = make_fake_response(
        '{"sql": "SELECT * FROM EMPLOYEES", "explanation": "Gets everyone."}'
    )
    result = generate_sql("show me everyone", "EMPLOYEES(ID, NAME)")
    assert result["sql"] == "SELECT * FROM EMPLOYEES"
    assert result["explanation"] == "Gets everyone."


@patch("sql_generator.ChatGoogleGenerativeAI")
def test_generate_sql_strips_markdown_fences(mock_llm_class):
    """Gemini sometimes wraps JSON in ```json ... ``` code fences even when
    told not to — this is a real, observed LLM quirk (LazyQL's own code
    handles the identical case), so it must be stripped before parsing."""
    mock_llm_class.return_value.invoke.return_value = make_fake_response(
        '```json\n{"sql": "SELECT 1", "explanation": "test"}\n```'
    )
    result = generate_sql("test question", "schema")
    assert result["sql"] == "SELECT 1"


@patch("sql_generator.ChatGoogleGenerativeAI")
def test_generate_sql_raises_on_invalid_json(mock_llm_class):
    """If Gemini returns something that isn't valid JSON at all (a full
    sentence instead of the requested format), this must fail loudly with
    a clear error, not silently return garbage as if it were a SQL query."""
    mock_llm_class.return_value.invoke.return_value = make_fake_response(
        "Sorry, I can't help with that."
    )
    with pytest.raises(RuntimeError, match="invalid JSON"):
        generate_sql("test question", "schema")


@patch("sql_generator.ChatGoogleGenerativeAI")
def test_generate_sql_raises_when_sql_key_missing(mock_llm_class):
    """Valid JSON, but missing the one field we actually need. This
    confirms the function checks for the field's presence rather than
    assuming it's always there and crashing with a confusing KeyError
    somewhere else downstream."""
    mock_llm_class.return_value.invoke.return_value = make_fake_response(
        '{"explanation": "no sql provided"}'
    )
    with pytest.raises(RuntimeError, match="did not return a SQL query"):
        generate_sql("test question", "schema")


@patch("sql_generator.ChatGoogleGenerativeAI")
def test_generate_sql_defaults_missing_explanation(mock_llm_class):
    """The 'explanation' field is treated as optional with a fallback —
    this confirms that fallback actually works rather than raising."""
    mock_llm_class.return_value.invoke.return_value = make_fake_response(
        '{"sql": "SELECT 1"}'
    )
    result = generate_sql("test question", "schema")
    assert result["explanation"] == "Query generated."


@pytest.mark.parametrize("payload", [[], None, {"sql": ["SELECT 1"]}, {"sql": "SELECT 1", "explanation": 42}, {"status": {}, "sql": "SELECT 1"}])
@patch("sql_generator.ChatGoogleGenerativeAI")
def test_malformed_response_shapes_are_rejected(mock_llm_class, payload):
    mock_llm_class.return_value.invoke.return_value = make_fake_response(json.dumps(payload))
    with pytest.raises(RuntimeError):
        generate_sql("test", "schema")


@patch("sql_generator.ChatGoogleGenerativeAI")
def test_provider_clarification_and_real_usage_metadata(mock_llm_class):
    response = make_fake_response('{"status":"clarification","message":"Which metric?"}')
    response.usage_metadata = {"input_tokens": 100, "output_tokens": 12, "total_tokens": 112, "other": "ignored"}
    mock_llm_class.return_value.invoke.return_value = response
    result = generate_sql("top departments", "schema")
    assert result["status"] == "clarification"
    assert result["usage"] == {"input_tokens": 100, "output_tokens": 12, "total_tokens": 112}


@patch("sql_generator.ChatGoogleGenerativeAI")
def test_nonfinite_model_confidence_is_not_presented_as_certainty(mock_llm_class):
    mock_llm_class.return_value.invoke.return_value = make_fake_response('{"sql":"SELECT 1","confidence":"NaN"}')
    assert generate_sql("test", "schema")["confidence"] == .5


@patch("sql_generator.ChatGoogleGenerativeAI")
def test_provider_denial_is_actionable_and_does_not_echo_response(mock_llm_class):
    PermissionDenied = type("GooglePermissionDeniedError", (Exception,), {})
    mock_llm_class.return_value.invoke.side_effect = PermissionDenied("untrusted provider details and fake credential")
    with pytest.raises(LLMProviderError, match="Gemini denied access") as error:
        generate_sql("test", "schema")
    assert "untrusted provider details" not in str(error.value)
