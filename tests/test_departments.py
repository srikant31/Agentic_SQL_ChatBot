"""Department access: every department x every table, hidden columns, and bypass attempts."""
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from streamlit.testing.v1 import AppTest

import departments as d
from coldchain_context import get_schema_context
from sql_guard import validate

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("role", d.ROLES)
@pytest.mark.parametrize("table", d.ALL_TABLES)
def test_every_department_reaches_exactly_its_own_tables(role, table):
    sql = f"SELECT COUNT(*) FROM {table}"
    if table in d.allowed_tables(role):
        assert "LIMIT 100" in validate(sql, role)
    else:
        with pytest.raises(ValueError, match="may not read"):
            validate(sql, role)


HIDDEN = [("viewer", "SELECT email FROM customers"), ("sales", "SELECT email FROM customers"),
          ("finance", "SELECT name, email FROM customers"), ("operations", "SELECT unit_price FROM products"),
          ("operations", "SELECT discount_pct FROM orders"), ("operations", "SELECT freight_cost FROM shipments")]


@pytest.mark.parametrize("role, sql", HIDDEN)
def test_hidden_columns_are_rejected(role, sql):
    with pytest.raises(ValueError, match="may not read"):
        validate(sql, role)


@pytest.mark.parametrize("role, sql", [("hr", "SELECT full_name, salary_inr FROM employees"),
                                       ("admin", "SELECT email FROM customers"),
                                       ("finance", "SELECT SUM(freight_cost) FROM shipments"),
                                       ("operations", "SELECT AVG(temp_c) FROM temperature_readings"),
                                       ("sales", "SELECT SUM(quantity * unit_price) FROM order_items")])
def test_departments_can_read_their_own_sensitive_or_money_columns(role, sql):
    assert validate(sql, role)


BYPASSES = [
    ("viewer", "SELECT e.salary_inr AS pay FROM employees e"),                       # alias
    ("sales", "SELECT SALARY_INR FROM EMPLOYEES"),                                    # upper case
    ("sales", "SELECT `email` FROM `customers`"),                                     # backtick quoting
    ("sales", "SELECT /* harmless */ email FROM customers"),                          # comment
    ("sales", "WITH staff AS (SELECT * FROM employees) SELECT COUNT(*) FROM staff"),  # CTE
    ("sales", "SELECT name FROM customers WHERE customer_id IN (SELECT employee_id FROM employees)"),  # sub-query
    ("sales", "SELECT name FROM customers UNION SELECT full_name FROM employees"),   # UNION
    ("operations", "SELECT name FROM customers"),                                     # other department's table
    ("operations", "SELECT o.order_id, oi.unit_price FROM orders o JOIN order_items oi ON oi.order_id = o.order_id"),
    ("operations", "SELECT * FROM products"),                                         # star exposes unit_price
    ("sales", "SELECT * FROM customers"),                                             # star exposes email
    ("sales", "WITH c AS (SELECT * FROM customers) SELECT name FROM c"),              # star inside a CTE
    ("hr", "SELECT * FROM coldchain_eval.orders"),                                    # database prefix
    ("finance", "SELECT reading_id FROM temperature_readings"),
    ("hr", "SELECT name FROM customers"),
]


@pytest.mark.parametrize("role, sql", BYPASSES)
def test_bypass_attempts_are_rejected(role, sql):
    with pytest.raises(ValueError):
        validate(sql, role)


def test_unknown_department_is_rejected():
    with pytest.raises(ValueError, match="Unknown analytics role"):
        validate("SELECT 1", "marketing")


def test_count_star_is_allowed_even_where_select_star_is_not():
    assert validate("SELECT COUNT(*) FROM customers", "sales")


def make_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/dept.db")
    with engine.begin() as connection:
        for ddl in ("CREATE TABLE regions (region_id INTEGER PRIMARY KEY, name TEXT)",
                    "CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, name TEXT, email TEXT, region_id INTEGER)",
                    "CREATE TABLE products (product_id INTEGER PRIMARY KEY, name TEXT, unit_price REAL)",
                    "CREATE TABLE shipments (shipment_id INTEGER PRIMARY KEY, freight_cost REAL, delivered_at TEXT)",
                    "CREATE TABLE employees (employee_id INTEGER PRIMARY KEY, full_name TEXT, salary_inr INTEGER)"):
            connection.execute(text(ddl))
    return engine


def test_model_sees_only_its_departments_tables_and_columns(tmp_path):
    engine = make_engine(tmp_path)
    ops = get_schema_context("q", "operations", engine)
    assert set(ops["schema"]) == {"regions", "products", "shipments"}
    assert "unit_price" not in ops["schema"]["products"] and "freight_cost" not in ops["schema"]["shipments"]
    assert "customers (Sales)" in ops["text"] and "employees (HR)" in ops["text"]   # names the owning team
    hr = get_schema_context("q", "hr", engine)
    assert set(hr["schema"]) == {"regions", "employees"} and "salary_inr" in hr["schema"]["employees"]
    admin = get_schema_context("q", "admin", engine)
    assert "email" in admin["schema"]["customers"] and "Not available" not in admin["text"]


def test_scope_text_is_plain_english():
    assert d.scope_text("operations") == ("Operations: you can ask about regions, warehouses, carriers, products, "
                                          "orders, shipments, temperature readings. Not included: discounts, freight "
                                          "costs, prices. Read-only.")


def test_login_lists_department_accounts_and_sidebar_shows_scope(monkeypatch):
    monkeypatch.setenv("COLDCHAIN_DB_URL", "")
    app = AppTest.from_file(str(ROOT / "sqlapp.py"), default_timeout=20).run()
    usernames = list(app.table[0].value["Username"])
    assert usernames == ["employee", "hr", "admin", "sales", "ops", "finance"]
    app.text_input[0].set_value("ops")
    app.text_input[1].set_value("ops123")
    app.button[0].click().run()
    assert app.session_state["authenticated_username"] == "ops"
    assert "Department: Operations" in [c.value for c in app.sidebar.caption]
    assert any("Operations: you can ask about" in str(i.value) for i in app.sidebar.info)
