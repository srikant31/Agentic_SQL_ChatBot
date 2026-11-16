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


def test_agent_identity_and_workspace_settings_are_loaded(monkeypatch):
    from checkpointing import thread_config
    from rbac import USERS
    values = {"LANGSMITH_ENDPOINT": "https://apac.api.smith.langchain.com",
              "LANGSMITH_AGENT_ID": "sql-chatbot", "LANGSMITH_AGENT_ENVIRONMENT": "local",
              "LANGSMITH_WORKSPACE_ID": "fixture-workspace"}
    for key in values:
        monkeypatch.delenv(key, raising=False)
    configure_observability(values)
    assert all(os.environ[key] == value for key, value in values.items())
    cfg = thread_config(USERS["employee"], "00000000-0000-0000-0000-000000000001", "viewer", "fixture-model")
    assert cfg["run_name"] == "coldchain_turn"
    assert cfg["metadata"]["agent_id"] == "sql-chatbot"
    assert cfg["metadata"]["agent_environment"] == "local"


def test_trace_summaries_preserve_shape_without_payloads():
    from observability import _safe_in, _safe_out
    assert _safe_in({"question": "private question", "history": [{"secret": "hidden"}]}) == {
        "question": "16 chars", "history": "list[1]"}
    assert _safe_out({"sql": "SELECT private", "rows": [["hidden"]], "status": "complete"}) == {
        "keys": ["rows", "sql", "status"], "status": "complete"}
    assert _safe_out({"status": "secret free text"})["status"] is None
    assert _safe_out("secret answer") == {"type": "str"}
