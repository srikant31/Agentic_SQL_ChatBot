"""Patch 5: cache-friendly prompts, deterministic schema text, result ratings, one repair with fresh approval."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import json

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine, text
from streamlit.testing.v1 import AppTest

import feedback_store
from coldchain_graph import CONTEXT_PREFIX, build_graph as real_build_graph
from sql_guard import fixture_schema

ROOT = Path(__file__).resolve().parents[1]


def context(question, role):
    schema = fixture_schema()
    schema.pop("employees")
    schema["customers"].pop("email")
    return {"text": "SCHEMA+GLOSSARY BLOCK", "schema": schema, "database": "coldchain"}


def replies(*items):
    llm = Mock()
    llm.invoke.side_effect = [Mock(content=json.dumps(item)) for item in items]
    return llm


def test_schema_block_is_an_identical_first_message_for_classify_and_generate():
    llm = replies({"kind": "proceed"}, {"sql": "SELECT COUNT(*) FROM orders"}, {"answer": "3"})
    graph = real_build_graph(InMemorySaver(), llm=llm, context_loader=context, executor=Mock(return_value=(["n"], [[3]])))
    graph.invoke({"question": "Count orders", "history": [], "role": "viewer"}, {"configurable": {"thread_id": "p5"}})
    classify, generate, summarize = (call.args[0] for call in llm.invoke.call_args_list)
    assert classify[0].content == generate[0].content == CONTEXT_PREFIX + "SCHEMA+GLOSSARY BLOCK"
    assert "schema" not in json.loads(classify[-1].content) and "schema" not in json.loads(generate[-1].content)
    assert "Count orders" in generate[-1].content                 # the varying part comes last
    assert len(summarize) == 2                                     # summary sends no schema


def test_sample_values_are_sorted_so_the_schema_text_never_changes(tmp_path):
    from coldchain_context import get_schema_context
    engine = create_engine(f"sqlite:///{tmp_path}/c.db")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE orders (order_id INTEGER PRIMARY KEY, status TEXT)"))
        connection.execute(text("INSERT INTO orders (status) VALUES ('shipped'), ('cancelled'), ('placed'), ('delivered')"))
    first = get_schema_context("q", "viewer", engine)["text"]
    assert first == get_schema_context("q", "viewer", engine)["text"]
    assert '"values": ["cancelled", "delivered", "placed", "shipped"]' in first


def test_existing_database_gains_new_columns_without_losing_rows(tmp_path):
    url = f"sqlite:///{tmp_path}/old.sqlite"
    store = feedback_store.FeedbackStore(url)
    with store.engine.begin() as connection:
        connection.execute(text("ALTER TABLE llm_calls DROP COLUMN cached_tokens"))
        connection.execute(text("INSERT INTO llm_calls (ts, node) VALUES ('2026-11-16 10:00:00', 'generate')"))
    reopened = feedback_store.FeedbackStore(url)
    reopened.record_llm_call(node="classify", usage={"input_tokens": 3400, "output_tokens": 90,
                                                      "input_token_details": {"cache_read": 3100}})
    rows = reopened.calls()
    assert len(rows) == 2 and rows[-1]["cached_tokens"] == 3100


def test_result_rating_and_one_automatic_repair_that_needs_fresh_approval(monkeypatch):
    monkeypatch.setenv("COLDCHAIN_DB_URL", "offline-test-configured")
    monkeypatch.setenv("COLDCHAIN_ADMIN_USERS", "")
    bad = "SELECT COUNT(*) FROM orders WHERE order_date >= '2026-03-01' AND order_date < '2026-04-01'"
    good = "SELECT COUNT(order_id) FROM orders WHERE order_date >= '2026-03-01' AND order_date < '2026-04-01'"
    llm = replies({"kind": "proceed"}, {"sql": bad, "explanation": "Counts March orders."},
                  {"sql": good, "explanation": "Counts March orders by ID."}, {"answer": "60 orders"})
    execute = Mock(side_effect=[Exception(1054, "Unknown column"), (["n"], [[60]])])

    def build(checkpointer, **kwargs):
        assert kwargs["max_attempts"] == 2                          # one repair allowed in the app
        return real_build_graph(checkpointer, llm=llm, context_loader=context, executor=execute, **kwargs)

    with patch("checkpointing.get_checkpointer", return_value=SimpleNamespace(saver=InMemorySaver(), persistent=True)), \
         patch("coldchain_context.get_coldchain_engine", return_value=None), \
         patch("coldchain_graph.build_graph", side_effect=build):
        app = AppTest.from_file(str(ROOT / "sqlapp.py"), default_timeout=20)
        app.session_state["authenticated_username"] = "employee"
        app.run()
        app.chat_input[0].set_value("How many orders in March 2026?").run()
        assert "How does this query look?" in [c.value for c in app.caption]
        next(b for b in app.button if b.label == "Approve & run").click().run()
        assert not app.exception
        assert execute.call_count == 1                               # failed once; repaired SQL is NOT run yet
        assert any("corrected automatically" in str(i.value) for i in app.info)
        assert good in [c.value.replace(" LIMIT 100", "") for c in app.code]
        del app.session_state["coldchain_query_chat"]                 # simulate a page refresh
        app.run()
        assert not app.exception and good in [c.value.replace(" LIMIT 100", "") for c in app.code]
        next(b for b in app.button if b.label == "Approve & run").click().run()   # fresh approval
        assert execute.call_count == 2 and not app.exception
        assert "How was your result?" in [c.value for c in app.caption]
        next(b for b in app.button if b.label == "Positive").click().run()
        assert not app.exception

    events = [(e["event"], e["version"], e["status"] or e["vote"]) for e in feedback_store.get_store().events()]
    assert events == [("proposal", 0, "proposed"), ("proposal", 0, "repaired"), ("run", 0, "complete"),
                      ("result_vote", 0, "positive")]
    assert app.session_state["coldchain_query_chat"]["requests"][-1]["rewrites"] == 0   # repair cost no rewrite


def test_feedback_is_linked_to_trace_and_project(monkeypatch):
    import observability
    client = Mock()
    client.read_project.return_value = SimpleNamespace(id="project-uuid")
    monkeypatch.setattr(observability, "_CLIENT", client)
    monkeypatch.setattr(observability, "_PROJECT_ID", None)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    assert observability.send_feedback("run-1", "result_vote", 1) is True
    assert observability.send_feedback("run-2", "user_vote", 0) is True
    first = client.create_feedback.call_args_list[0].kwargs
    assert first["trace_id"] == "run-1" and first["session_id"] == "project-uuid" and first["key"] == "result_vote"
    client.read_project.assert_called_once()                       # looked up once, then reused
