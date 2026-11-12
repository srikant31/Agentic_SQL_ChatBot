import os
from observability import configure_observability


def test_tracing_is_opt_in_and_redacted(monkeypatch):
    for key in ("LANGSMITH_TRACING", "LANGSMITH_HIDE_INPUTS", "LANGSMITH_HIDE_OUTPUTS"):
        monkeypatch.delenv(key, raising=False)
    configure_observability()
    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert os.environ["LANGSMITH_HIDE_INPUTS"] == "true"
    assert os.environ["LANGSMITH_HIDE_OUTPUTS"] == "true"


def test_only_allowlisted_streamlit_settings_are_copied(monkeypatch):
    monkeypatch.delenv("UNRELATED_SECRET", raising=False)
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    configure_observability({"LANGSMITH_PROJECT": "demo-project", "UNRELATED_SECRET": "hidden"})
    assert os.environ["LANGSMITH_PROJECT"] == "demo-project"
    assert "UNRELATED_SECRET" not in os.environ
