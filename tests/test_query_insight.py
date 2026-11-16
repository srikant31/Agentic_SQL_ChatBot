"""Step 2: plain-English description, rule checks and assumptions, all written by code from the SQL."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from streamlit.testing.v1 import AppTest

import feedback_store
import query_insight as qi
from coldchain_graph import build_graph as real_build_graph
from sql_guard import fixture_schema

ROOT = Path(__file__).resolve().parents[1]
SALES_NO_STATUS = ("SELECT SUM(oi.quantity * oi.unit_price * (1 - COALESCE(o.discount_pct, 0) / 100)) AS total_sales "
                   "FROM orders o JOIN customers c ON c.customer_id = o.customer_id JOIN order_items oi ON oi.order_id = o.order_id "
                   "WHERE c.city = 'Bengaluru' AND o.order_date >= '2026-05-01' AND o.order_date < '2026-07-01' LIMIT 100")
SALES_OK = SALES_NO_STATUS.replace("WHERE ", "WHERE o.status IN ('shipped', 'delivered') AND ")


def rule(result, term):
    return next(r for r in result["rules"] if r["term"] == term)


def test_counting_cancelled_sales_is_flagged():
    result = qi.analyze("Total sales in Bangalore across May and June", SALES_NO_STATUS)
    revenue = rule(result, "Revenue")
    assert revenue["status"] == "warn" and "cancelled" in revenue["detail"]
    assert "shipped" in revenue["definition"]                      # definition comes from the glossary file
    assert "All order statuses are included: placed, shipped, delivered, cancelled and returned." in result["assumptions"]


def test_correct_revenue_query_passes_and_reads_naturally():
    result = qi.analyze("Total sales in Bengaluru across May and June", SALES_OK)
    assert rule(result, "Revenue")["status"] == "ok" and rule(result, "Discount")["status"] == "ok"
    text = " ".join(result["summary"])
    assert "order date from 2026-05-01 up to (not including) 2026-07-01" in text
    assert "order status is one of: shipped, delivered" in text and "Links order items by order id" in text
    assert "Prices are the prices charged at the time of sale, not today's list prices." in result["assumptions"]


@pytest.mark.parametrize("sql, term, phrase", [
    ("SELECT COUNT(*) FROM customers WHERE city = 'Bangalore'", "Bangalore / Bombay", "Bengaluru"),
    ("SELECT COUNT(*) FROM orders WHERE status = 'canceled'", "Cancelled", "cancelled"),
    ("SELECT COUNT(*) FROM orders WHERE order_date BETWEEN '2026-05-01' AND '2026-05-31'", "Date ranges", "after midnight"),
    ("SELECT COUNT(*) FROM orders WHERE order_date >= CURDATE() - INTERVAL 30 DAY", "Today's date", "2026-06-30"),
    ("SELECT SUM(oi.quantity * p.unit_price) FROM order_items oi JOIN products p ON p.product_id = oi.product_id "
     "JOIN orders o ON o.order_id = oi.order_id WHERE o.status IN ('shipped','delivered')", "Revenue", "list price"),
    ("SELECT SUM(oi.quantity) FROM order_items oi JOIN orders o ON o.order_id = oi.order_id", "Units sold", "cancelled"),
    ("SELECT SUM(oi.quantity * oi.unit_price * (1 - o.discount_pct / 100)) FROM orders o JOIN order_items oi "
     "ON oi.order_id = o.order_id WHERE o.status IN ('shipped','delivered')", "Discount", "missing discount"),
])
def test_rule_breaks_are_flagged(sql, term, phrase):
    question = "units sold" if term == "Units sold" else "revenue for orders"
    found = rule(qi.analyze(question, sql), term)
    assert found["status"] == "warn" and phrase in found["detail"]


def test_single_table_columns_and_multi_step_queries_are_described():
    single = qi.describe("SELECT COUNT(*) AS n FROM orders WHERE status = 'delivered'")
    assert "Keeps only rows where: order status is delivered." in single
    steps = qi.describe("WITH a AS (SELECT r.name AS region, COUNT(*) AS n FROM orders o JOIN customers c "
                        "ON c.customer_id = o.customer_id JOIN regions r ON r.region_id = c.region_id GROUP BY r.name) "
                        "SELECT a.region, a.n FROM a ORDER BY a.n DESC")
    assert steps[0] == "Works in 2 steps." and "Step 'a':" in steps and "Final step:" in steps
    assert "    Sorted by n (highest first)." in steps


def test_region_meaning_and_relative_dates_become_assumptions():
    result = qi.analyze("Orders by region last month", "SELECT r.name, COUNT(*) FROM orders o JOIN warehouses w "
                        "ON w.warehouse_id = o.warehouse_id JOIN regions r ON r.region_id = w.region_id GROUP BY r.name")
    assert "'Region' means the fulfilling warehouse's region, not the customer's." in result["assumptions"]
    assert "'Today' is taken as 2026-06-30, the last day of the data." in result["assumptions"]


def test_unparseable_sql_or_missing_glossary_never_break_the_chat(tmp_path):
    assert qi.analyze("anything", "THIS IS NOT SQL (((") is None
    assert qi.rules_for("revenue", SALES_NO_STATUS, glossary=qi.load_glossary(tmp_path / "missing.md")) == []


def test_proposal_screen_shows_description_rules_and_logs_the_checks(monkeypatch):
    monkeypatch.setenv("COLDCHAIN_DB_URL", "offline-test-configured")
    monkeypatch.setenv("COLDCHAIN_ADMIN_USERS", "")
    llm = Mock()
    llm.invoke.side_effect = [Mock(content=json.dumps(x)) for x in
                              [{"kind": "proceed"}, {"sql": SALES_NO_STATUS, "explanation": "Adds up sales in Bengaluru."}]]

    def context(question, role):
        schema = fixture_schema()
        schema.pop("employees")
        schema["customers"].pop("email")
        return {"text": "schema", "schema": schema, "database": "coldchain"}

    def build(checkpointer, **kwargs):
        return real_build_graph(checkpointer, llm=llm, context_loader=context, executor=Mock(), **kwargs)

    with patch("checkpointing.get_checkpointer", return_value=SimpleNamespace(saver=InMemorySaver(), persistent=True)), \
         patch("coldchain_context.get_coldchain_engine", return_value=None), \
         patch("coldchain_graph.build_graph", side_effect=build):
        app = AppTest.from_file(str(ROOT / "sqlapp.py"), default_timeout=20)
        app.session_state["authenticated_username"] = "employee"
        app.run()
        app.chat_input[0].set_value("Total sales in Bangalore across May and June").run()
        assert not app.exception
        text = " ".join(str(m.value) for m in app.markdown)
        assert "What this query will fetch" in text and "Rules applied" in text and "Assumptions" in text
        assert "cancelled and returned orders are counted too" in text
        assert any("may not be followed" in str(w.value) for w in app.warning)
        assert [e.label for e in app.expander if e.label in ("How the AI described it", "Show SQL")] == \
               ["How the AI described it", "Show SQL"]
        assert any("SUM(oi.quantity" in str(c.value) for c in app.code)

    (proposal,) = [e for e in feedback_store.get_store().events() if e["event"] == "proposal"]
    detail = json.loads(proposal["detail"])
    assert {"term": "Revenue", "status": "warn"} in detail["rules"]
