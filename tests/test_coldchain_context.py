from sqlalchemy import create_engine, text
from coldchain_context import get_schema_context


def test_context_profiles_only_authorized_categorical_values():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, email TEXT, city TEXT, segment TEXT)"))
        conn.execute(text("INSERT INTO customers VALUES (1, 'private@example.invalid', 'Bengaluru', 'Hospital')"))
        conn.execute(text("CREATE TABLE employees (employee_id INTEGER PRIMARY KEY, salary_inr INTEGER)"))
        conn.execute(text("CREATE TABLE regions (region_id INTEGER PRIMARY KEY, name TEXT)"))
        conn.execute(text("INSERT INTO regions VALUES (1, 'North')"))
        conn.execute(text("CREATE TABLE unrelated_private (secret TEXT)"))
    context = get_schema_context("customers", "viewer", engine)
    assert "email" not in context["schema"]["customers"]
    assert "employees" not in context["schema"] and "unrelated_private" not in context["schema"]
    assert "private@example.invalid" not in context["text"]
    assert "Bengaluru" in context["text"] and "Hospital" in context["text"] and "North" in context["text"]
    assert "2026-06-30" in context["text"] and "Revenue" in context["text"]
    engine.dispose()
