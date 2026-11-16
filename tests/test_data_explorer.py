"""Admin Data Explorer: reachable only by ColdChain admins; read-only previews and table details."""
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
RECORDS = [{"table": "customers", "comment": "B2B customers",
            "columns": [{"name": "customer_id", "type": "INT", "comment": ""},
                        {"name": "email", "type": "VARCHAR(120)", "comment": "PII"}]},
           {"table": "orders", "comment": "Customer orders", "columns": [{"name": "order_id", "type": "INT", "comment": ""}]}]
CALLS = []


def fake_execute(sql, role, engine=None):
    CALLS.append((sql, role))
    if "COUNT" in sql:
        return ["row_count"], [[60]]
    limit = int(sql.rsplit("LIMIT", 1)[1])
    return ["customer_id"], [[i] for i in range(1, limit + 1)]


@pytest.fixture
def app_for(monkeypatch):
    monkeypatch.setenv("COLDCHAIN_DB_URL", "offline-test-configured")
    CALLS.clear()

    def build(username, admins):
        monkeypatch.setenv("COLDCHAIN_ADMIN_USERS", admins)
        patches = [patch("coldchain_context.get_schema_context", return_value={"records": RECORDS}),
                   patch("coldchain_context.execute_readonly", side_effect=fake_execute),
                   patch("checkpointing.get_checkpointer"), patch("coldchain_context.get_coldchain_engine")]
        for item in patches:
            item.start()
        app = AppTest.from_file(str(ROOT / "sqlapp.py"), default_timeout=20)
        app.session_state["authenticated_username"] = username
        app.run()
        return app, patches
    yield build
    patch.stopall()


def test_admin_can_open_the_explorer_and_see_table_details(app_for):
    app, _ = app_for("admin", "admin")
    app.switch_page("pages/coldchain_explorer.py").run()
    assert not app.exception and [t.value for t in app.title] == ["ColdChain Data Explorer"]
    assert app.metric[0].value == "60"
    columns = app.dataframe[0].value
    assert list(columns["Column"]) == ["customer_id", "email"] and columns["Sensitive"][1] == "Yes, an admin only"
    assert len(app.dataframe[1].value) == 10                         # first 10 rows by default
    app.toggle[0].set_value(True).run()
    assert len(app.dataframe[1].value) == 100                        # up to 100 on request
    assert all(role == "admin" for _, role in CALLS)                  # every read goes through the guarded path


@pytest.mark.parametrize("username", ["employee", "sales", "ops", "finance", "hr", "admin"])
def test_non_admins_have_no_explorer_page(app_for, username):
    app, _ = app_for(username, "")                                    # nobody on the allowlist
    with pytest.raises(ValueError, match="Could not find a navigation page"):
        app.switch_page("pages/coldchain_explorer.py")


def test_opening_the_page_file_directly_is_refused_for_non_admins(monkeypatch):
    monkeypatch.setenv("COLDCHAIN_ADMIN_USERS", "")
    with patch("coldchain_context.get_schema_context") as schema:
        app = AppTest.from_file(str(ROOT / "pages/coldchain_explorer.py"), default_timeout=20)
        app.session_state["authenticated_username"] = "sales"
        app.run()
        assert app.error[0].value == "The Data Explorer is available to admins only."
        schema.assert_not_called()                                   # refused before any database access
