"""Item 8: plain-English comparison between two versions of a query. No model calls."""
import query_insight as qi

MARCH = "SELECT COUNT(*) AS orders_placed FROM orders WHERE order_date >= '2026-03-01' AND order_date < '2026-04-01' LIMIT 100"
DELIVERED = ("SELECT COUNT(*) AS delivered_orders FROM orders WHERE status = 'delivered' "
             "AND order_date >= '2026-03-01' AND order_date < '2026-04-01' LIMIT 100")


def test_added_filter_and_renamed_output_are_reported_with_what_stayed_the_same():
    result = qi.compare(MARCH, DELIVERED)
    assert result["changes"] == ["Added filter: order status is delivered",
                                 "Output renamed: 'orders_placed' → 'delivered_orders'"]
    assert "tables read (orders)" in result["unchanged"]
    assert "filters: order date from 2026-03-01 up to (not including) 2026-04-01" in result["unchanged"]


def test_removed_filter_new_tables_grouping_sorting_and_limit():
    regional = ("SELECT r.name AS region, COUNT(*) AS delivered_orders FROM orders o JOIN customers c "
                "ON c.customer_id = o.customer_id JOIN regions r ON r.region_id = c.region_id "
                "WHERE o.order_date >= '2026-03-01' AND o.order_date < '2026-04-01' "
                "GROUP BY r.name ORDER BY delivered_orders DESC LIMIT 10")
    changes = qi.compare(DELIVERED, regional)["changes"]
    for expected in ("Now also reads: customers", "Now also reads: regions", "Removed filter: order status is delivered",
                     "Now grouped by: region name", "New output: region name (shown as 'region')",
                     "Row limit changed: 100 → 10"):
        assert expected in changes
    assert any(c.startswith("Sorting changed: delivered orders (highest first)") for c in changes)


def test_identical_queries_have_no_changes_and_unreadable_sql_returns_none():
    assert qi.compare(MARCH, MARCH)["changes"] == []
    assert qi.compare(MARCH, "SELEC nonsense (((") is None


def test_sql_diff_marks_changed_lines():
    diff = qi.sql_diff(MARCH, DELIVERED)
    assert diff.startswith("--- previous") and "+  status = 'delivered'" in diff.replace("\n", "\n")


# ----------------------------------------------------------------------------- on screen
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import json

from langgraph.checkpoint.memory import InMemorySaver
from streamlit.testing.v1 import AppTest

import feedback_store
from coldchain_graph import build_graph as real_build_graph
from sql_guard import fixture_schema

ROOT = Path(__file__).resolve().parents[1]


def run_app(llm_replies, execute, rewrite="Count delivered March 2026 orders"):
    llm = Mock()
    llm.invoke.side_effect = [Mock(content=json.dumps(item)) for item in llm_replies]

    def context(question, role):
        schema = fixture_schema()
        schema.pop("employees")
        schema["customers"].pop("email")
        return {"text": "schema", "schema": schema, "database": "coldchain"}

    def build(checkpointer, **kwargs):
        return real_build_graph(checkpointer, llm=llm, context_loader=context, executor=execute, **kwargs)

    patches = [patch("checkpointing.get_checkpointer", return_value=SimpleNamespace(saver=InMemorySaver(), persistent=True)),
               patch("coldchain_context.get_coldchain_engine", return_value=None),
               patch("coldchain_graph.build_graph", side_effect=build),
               patch("sql_generator.rewrite_question", return_value=rewrite)]
    for item in patches:
        item.start()
    app = AppTest.from_file(str(ROOT / "sqlapp.py"), default_timeout=20)
    app.session_state["authenticated_username"] = "employee"
    app.run()
    return app, patches


def markdown(app):
    return " ".join(str(m.value) for m in app.markdown)


def test_rewrite_shows_what_changed_and_logs_it(monkeypatch):
    monkeypatch.setenv("COLDCHAIN_DB_URL", "offline-test-configured")
    monkeypatch.setenv("COLDCHAIN_ADMIN_USERS", "")
    app, patches = run_app([{"kind": "proceed"}, {"sql": MARCH, "explanation": "Counts March orders."},
                            {"kind": "proceed"}, {"sql": DELIVERED, "explanation": "Counts delivered March orders."}],
                           Mock(return_value=(["n"], [[50]])))
    try:
        app.chat_input[0].set_value("How many orders in March 2026?").run()
        assert "What changed from the previous version" not in markdown(app)       # nothing to compare yet
        next(b for b in app.button if b.label == "Negative").click().run()
        next(a for a in app.text_area if a.label == "What should change?").set_value("Only delivered ones").run()
        next(b for b in app.button if b.label == "Rewrite query").click().run()
        assert not app.exception
        text = markdown(app)
        assert "What changed from the previous version" in text and "Added filter: order status is delivered" in text
        assert "Show SQL changes" in [e.label for e in app.expander]
        assert any("+  status = 'delivered'" in str(c.value) for c in app.code)
    finally:
        for item in patches:
            item.stop()
    rewritten = [e for e in feedback_store.get_store().events() if e["event"] == "proposal"][-1]
    assert "Added filter: order status is delivered" in json.loads(rewritten["detail"])["changes"]


def test_automatic_repair_shows_what_the_repair_changed(monkeypatch):
    monkeypatch.setenv("COLDCHAIN_DB_URL", "offline-test-configured")
    monkeypatch.setenv("COLDCHAIN_ADMIN_USERS", "")
    fixed = MARCH.replace("COUNT(*) AS orders_placed", "COUNT(order_id) AS orders_placed")
    app, patches = run_app([{"kind": "proceed"}, {"sql": MARCH, "explanation": "Counts March orders."},
                            {"sql": fixed, "explanation": "Counts March orders by ID."}],
                           Mock(side_effect=[Exception(1054, "Unknown column"), (["n"], [[60]])]))
    try:
        app.chat_input[0].set_value("How many orders in March 2026?").run()
        next(b for b in app.button if b.label == "Approve & run").click().run()
        assert not app.exception
        text = markdown(app)
        assert "What the automatic repair changed" in text
        assert "New output: number of order id values" in text or "Removed output: number of rows" in text
    finally:
        for item in patches:
            item.stop()
