from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]

def test_login_and_logout_clear_pending_actions():
    with patch("database.ensure_demo"), patch("database.run_query") as query:
        app = AppTest.from_file(str(ROOT / "sqlapp.py"), default_timeout=20).run()
        assert not app.exception
        app.text_input[0].set_value("employee")
        app.text_input[1].set_value("employee123")
        app.button[0].click().run()
        assert not app.exception
        assert app.session_state["authenticated_username"] == "employee"
        query.assert_not_called()
        app.session_state["pending_edit"] = {"owner": "employee", "id": 1, "title": "Test"}
        next(b for b in app.button if b.label == "Log out / switch account").click().run()
        assert "authenticated_username" not in app.session_state
        assert "pending_edit" not in app.session_state
        assert not app.exception

def test_bad_password_does_not_authenticate():
    app = AppTest.from_file(str(ROOT / "sqlapp.py"), default_timeout=20).run()
    app.text_input[0].set_value("hr")
    app.text_input[1].set_value("wrong")
    app.button[0].click().run()
    assert app.error[0].value == "Incorrect username or password."
    assert "authenticated_username" not in app.session_state

def test_direct_admin_link_denies_hr_before_database_access():
    with patch("database.ensure_demo") as prepare:
        app = AppTest.from_file(str(ROOT / "pages/admin.py"))
        app.session_state["authenticated_username"] = "hr"
        app.run()
        assert not app.exception
        assert "Access denied" in app.error[0].value
        prepare.assert_not_called()

def test_direct_explorer_link_denies_employee():
    with patch("database.ensure_demo") as prepare:
        app = AppTest.from_file(str(ROOT / "pages/data explorer.py"))
        app.session_state["authenticated_username"] = "employee"
        app.run()
        assert "Access denied" in app.error[0].value
        prepare.assert_not_called()
