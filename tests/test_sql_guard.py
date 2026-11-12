import json
from pathlib import Path
import pytest
from sql_guard import validate, connected_catalog


@pytest.mark.parametrize("sql", ["DELETE FROM orders", "UPDATE orders SET status='cancelled'", "DROP TABLE orders",
    "SELECT 1; DROP TABLE orders", "SELECT * FROM information_schema.tables", "SELECT * FROM mysql.user",
    "SELECT * FROM employees", "SELECT email FROM customers", "SELECT * FROM customers",
    "SELECT * FROM (SELECT * FROM employees) x", "WITH employees AS (SELECT * FROM employees) SELECT * FROM employees",
    "SELECT * INTO OUTFILE '/tmp/out' FROM orders", "SELECT NOW()", "SELECT SLEEP(10)",
    "SELECT missing FROM orders", "SELECT customer_id FROM customers; SELECT 2"])
def test_rejects_unsafe_or_restricted(sql):
    with pytest.raises(ValueError): validate(sql)


@pytest.mark.parametrize("sql", ["WITH x AS (SELECT order_id FROM orders) SELECT * FROM x",
    "SELECT order_id FROM orders UNION SELECT order_id FROM orders", "SELECT COUNT(*) FROM customers",
    "SELECT order_id FROM orders"])
def test_allows_valid_queries_and_caps_results(sql):
    assert "LIMIT 100" in validate(sql)


def test_admin_and_explicit_caps():
    assert "LIMIT 100" in validate("SELECT * FROM employees", "admin")
    assert "LIMIT 100" in validate("SELECT * FROM orders LIMIT 900")
    assert "LIMIT 5" in validate("SELECT * FROM orders LIMIT 5")
    with pytest.raises(ValueError): validate("SELECT 1", "unknown")


def test_connected_catalog_only_narrows_access():
    with connected_catalog({"orders": {"order_id": "INT"}}, "tenant"):
        assert "LIMIT" in validate("SELECT order_id FROM tenant.orders")
        with pytest.raises(ValueError): validate("SELECT name FROM products")
        with pytest.raises(ValueError): validate("SELECT * FROM tenant.users", "admin")


def test_all_answerable_gold_queries_pass_static_guard():
    data = json.loads((Path(__file__).parents[1] / "golden_eval/golden.json").read_text(encoding="utf-8"))
    for case in data["cases"]:
        if case.get("gold_sql") and case["kind"] == "sql":
            try: validate(case["gold_sql"], case.get("role", "viewer"))
            except ValueError as exc: pytest.fail(f"{case['id']}: {exc}")
