import json
from unittest.mock import patch, MagicMock
import pytest

from sql_generator import generate_sql


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