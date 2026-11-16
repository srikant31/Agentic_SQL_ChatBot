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


def terms(question, sql):
    return [r["term"] for r in qi.rules_for(question, sql)]


@pytest.mark.parametrize("question, sql, expected", [
    ("What were total sales in Bangalore across May and June?", SALES_NO_STATUS, {"Revenue", "Bangalore / Bombay"}),
    ("Which carrier had the most late shipments last month?",
     "SELECT c.name FROM shipments s JOIN carriers c ON c.carrier_id = s.carrier_id WHERE DATE(s.delivered_at) > s.promised_date",
     {"Late shipment", "Today's date"}),
    ("How many shipments are still in transit?", "SELECT COUNT(*) FROM shipments WHERE delivered_at IS NULL", {"In transit"}),
    ("Which products had temperature excursions?", "SELECT p.name FROM products p", {"Temperature excursion"}),
    ("List hospital customers in the North region",
     "SELECT c.name FROM customers c JOIN regions r ON r.region_id = c.region_id WHERE r.name = 'North'", {"Northern region"}),
])
def test_relevant_business_rules_are_listed(question, sql, expected):
    assert expected <= set(terms(question, sql))


def test_rules_carry_glossary_definitions_and_no_verdicts():
    rules = qi.rules_for("total sales in Bengaluru", SALES_NO_STATUS)
    revenue = next(r for r in rules if r["term"] == "Revenue")
    assert "shipped" in revenue["definition"] and "Cancelled and returned orders are excluded" in revenue["definition"]
    assert set(revenue) == {"term", "definition", "score"}          # what the rule says, not whether it was followed


def test_questions_without_a_special_rule_show_none():
    assert terms("How many delivered orders in March 2026?", "SELECT COUNT(*) FROM orders WHERE status = 'delivered'") == []


def test_assumptions_still_explain_what_is_included():
    result = qi.analyze("Total sales in Bangalore across May and June", SALES_NO_STATUS)
    assert "All order statuses are included: placed, shipped, delivered, cancelled and returned." in result["assumptions"]
    ok = qi.analyze("Total sales in Bengaluru across May and June", SALES_OK)
    text = " ".join(ok["summary"])
    assert "order date from 2026-05-01 up to (not including) 2026-07-01" in text
    assert "order status is one of: shipped, delivered" in text and "Links order items by order id" in text


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
        assert "What this query will fetch" in text and "Business rules for this query" in text and "Assumptions" in text
        assert "**Revenue**:" in text and "**Bangalore / Bombay**:" in text
        assert not app.warning                                         # rules are shown, not judged
        assert [e.label for e in app.expander if e.label in ("How the AI described it", "Show SQL")] == \
               ["How the AI described it", "Show SQL"]
        assert any("SUM(oi.quantity" in str(c.value) for c in app.code)

    (proposal,) = [e for e in feedback_store.get_store().events() if e["event"] == "proposal"]
    detail = json.loads(proposal["detail"])
    assert "Revenue" in [r["term"] for r in detail["rules"]]
