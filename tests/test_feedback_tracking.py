"""Feedback event store, LangSmith linking and model-call counting. All offline."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import json
import uuid

from langgraph.checkpoint.memory import InMemorySaver
from streamlit.testing.v1 import AppTest

import feedback_store
import observability
from coldchain_graph import build_graph as real_build_graph
from sql_guard import fixture_schema

ROOT = Path(__file__).resolve().parents[1]


def event(store, name, **fields):
    return store.record(name, owner="employee:viewer", request_id="r1", version=fields.pop("version", 0), **fields)


def test_summary_counts_questions_rewrites_calls_and_runs(tmp_path):
    store = feedback_store.FeedbackStore(f"sqlite:///{tmp_path}/events.sqlite")
    event(store, "proposal", model_calls=2, status="proposed")
    event(store, "vote", vote="negative")
    event(store, "rewrite", version=1, hint="Only March")
    event(store, "proposal", version=1, model_calls=3, status="proposed")
    event(store, "vote", version=1, vote="positive")
    event(store, "run", version=1, status="complete", rows_returned=1, model_calls=1)
    store.record("proposal", owner="employee:viewer", request_id="r2", version=0, model_calls=2, status="proposed")
    store.record("vote", owner="employee:viewer", request_id="r2", version=0, vote="positive")
    summary = store.summary()
    assert summary["questions"] == 2
    assert summary["accepted_first_proposal"] == 0.5          # r2 only; r1 needed a rewrite
    assert summary["resolved_with_successful_run"] == 0.5     # r2 was never run
    assert summary["avg_rewrites_per_question"] == 0.5
    assert summary["avg_model_calls_per_question"] == 4.0     # (2+3+1 + 2) / 2
    assert summary["votes_negative"] == 1 and summary["run_failure_rate"] == 0.0


def test_hints_are_hashed_unless_text_storage_is_enabled(tmp_path, monkeypatch):
    store = feedback_store.FeedbackStore(f"sqlite:///{tmp_path}/events.sqlite")
    event(store, "rewrite", version=1, hint="exclude cancelled orders")
    monkeypatch.setenv("FEEDBACK_STORE_HINTS", "true")
    event(store, "rewrite", version=2, hint="exclude cancelled orders")
    first, second = store.events()
    assert first["hint_text"] is None and first["hint_chars"] == 24 and len(first["hint_sha"]) == 16
    assert second["hint_text"] == "exclude cancelled orders"
    assert first["session"] != "employee:viewer"              # usernames are never stored


def test_logging_failures_never_raise(tmp_path):
    store = feedback_store.FeedbackStore(f"sqlite:///{tmp_path}/events.sqlite")
    assert event(store, "not-an-event") is False
    with patch.object(feedback_store, "FeedbackStore", side_effect=RuntimeError("down")):
        feedback_store.reset_store()
        assert feedback_store.record("proposal", owner="u", request_id="r", version=0) is False
        assert feedback_store.get_store() is None                # gives up instead of retrying every click


def test_postgres_urls_get_the_psycopg_driver(monkeypatch):
    monkeypatch.delenv("FEEDBACK_DB_URL", raising=False)
    monkeypatch.setenv("PG_URL", "postgresql://user:pw@host:5432/db")
    assert feedback_store.database_url() == "postgresql+psycopg://user:pw@host:5432/db"


def test_trace_sanitiser_keeps_shape_not_text():
    safe = observability.sanitize_inputs({"original_question": "Revenue for Acme in May", "modifications": ["a", "b"]})
    assert safe == {"original_question": "23 chars", "modifications": "list[2]"}
    assert "Acme" not in json.dumps(observability.sanitize_outputs({"sql": "SELECT 'Acme'", "status": "complete"}))


def test_workspace_id_is_allowlisted_and_feedback_is_skipped_without_tracing(monkeypatch):
    monkeypatch.delenv("LANGSMITH_WORKSPACE_ID", raising=False)
    observability.configure_observability({"LANGSMITH_WORKSPACE_ID": "ws-123"})
    assert observability.tracing_enabled() is False
    assert observability.send_feedback(str(uuid.uuid4()), "user_vote", 1) is False


def test_coldchain_chat_records_every_step_with_model_calls_and_trace_ids(monkeypatch):
    monkeypatch.setenv("COLDCHAIN_DB_URL", "offline-test-configured")
    monkeypatch.setenv("COLDCHAIN_ADMIN_USERS", "")
    responses = [{"kind": "proceed"}, {"sql": "SELECT COUNT(*) FROM orders", "explanation": "Counts all orders."},
                 {"kind": "proceed"}, {"sql": "SELECT COUNT(*) FROM orders WHERE order_date >= '2026-03-01' AND order_date < '2026-04-01'",
                                       "explanation": "Counts orders placed in March 2026."}, {"answer": "3 orders"}]
    llm = Mock()
    llm.invoke.side_effect = [Mock(content=json.dumps(item)) for item in responses]
    execute = Mock(return_value=(["count"], [[3]]))

    def context(question, role):
        schema = fixture_schema()
        schema.pop("employees")
        schema["customers"].pop("email")
        return {"text": "authorized ColdChain schema", "schema": schema, "database": "coldchain"}

    def build(checkpointer, **kwargs):
        return real_build_graph(checkpointer, llm=llm, context_loader=context, executor=execute,
                                review_all=kwargs["review_all"], max_attempts=kwargs["max_attempts"], explain_sql=kwargs["explain_sql"])

    with patch("checkpointing.get_checkpointer", return_value=SimpleNamespace(saver=InMemorySaver(), persistent=True)), \
         patch("coldchain_context.get_coldchain_engine", return_value=None), \
         patch("coldchain_graph.build_graph", side_effect=build), \
         patch("sql_generator.rewrite_question", return_value="Count March 2026 orders"):
        app = AppTest.from_file(str(ROOT / "sqlapp.py"), default_timeout=20)
        app.session_state["authenticated_username"] = "employee"
        app.run()
        app.chat_input[0].set_value("Count all orders").run()
        next(b for b in app.button if b.label == "👎 Needs changes").click().run()
        next(a for a in app.text_area if a.label == "What should change?").set_value("Only March 2026").run()
        next(b for b in app.button if b.label == "Rewrite query").click().run()
        next(b for b in app.button if b.label == "👍 Looks good").click().run()
        next(b for b in app.button if b.label == "Approve & run").click().run()
        assert not app.exception

    rows = feedback_store.get_store().events()
    steps = [(r["event"], r["version"], r["model_calls"], r["status"] or r["vote"]) for r in rows]
    assert steps == [("proposal", 0, 2, "proposed"), ("vote", 0, None, "negative"), ("rewrite", 1, None, None),
                     ("proposal", 1, 3, "proposed"), ("vote", 1, None, "positive"), ("run", 1, 1, "complete")]
    assert llm.invoke.call_count == 5                          # graph counter agrees with the real calls (+1 rewrite mocked)
    assert rows[-1]["rows_returned"] == 1 and rows[2]["hint_chars"] == len("Only March 2026")
    proposals = [r for r in rows if r["event"] == "proposal"]
    assert all(uuid.UUID(r["langsmith_run_id"]) for r in proposals)
    assert rows[4]["langsmith_run_id"] == proposals[1]["langsmith_run_id"]   # vote linked to the trace it judged
