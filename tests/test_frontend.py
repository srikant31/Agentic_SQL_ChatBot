from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
import pytest
from sqlalchemy import create_engine
from database import initialize_demo

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/frontend.db")
    initialize_demo(engine)
    with patch("database.get_engine", return_value=engine):
        yield engine
    engine.dispose()

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


def test_proposal_requires_click_to_execute_and_renders_validation():
    with patch("database.ensure_demo"), patch("sql_generator.generate_sql", return_value={
        "sql": "SELECT COUNT(*) AS employee_count FROM EMPLOYEES", "explanation": "Count visible employees", "confidence": .9
    }), patch("database.run_query", return_value=(["employee_count"], [(3,)])) as execute:
        app = AppTest.from_file(str(ROOT / "sqlapp.py"), default_timeout=20)
        app.session_state["authenticated_username"] = "employee"
        app.run()
        next(area for area in app.text_area if area.label == "...or type your own question:").set_value("How many employees can I access?").run()
        next(button for button in app.button if button.label == "Generate SQL").click().run()
        assert not app.exception
        assert app.session_state["pending_query"]["status"] == "proposal"
        execute.assert_not_called()
        next(button for button in app.button if button.label == "Run this query").click().run()
        assert not app.exception
        execute.assert_called_once()
        assert app.session_state["pending_query"] is None


def test_unsupported_question_shows_explanation_without_calling_provider():
    with patch("database.ensure_demo"), patch("sql_generator.generate_sql") as generate:
        app = AppTest.from_file(str(ROOT / "sqlapp.py"), default_timeout=20)
        app.session_state["authenticated_username"] = "hr"
        app.run()
        next(area for area in app.text_area if area.label == "...or type your own question:").set_value("Show revenue last month").run()
        next(button for button in app.button if button.label == "Generate SQL").click().run()
        assert not app.exception
        assert app.session_state["pending_query"] is None
        assert any("snapshot" in message.value for message in app.info)
        generate.assert_not_called()


def test_graph_ui_preserves_approval_gate():
    with patch("database.ensure_demo"), patch("sql_generator.generate_sql", return_value={
        "sql": "SELECT COUNT(*) FROM EMPLOYEES", "explanation": "Count", "confidence": .9
    }), patch("database.run_query", return_value=(["count"], [(3,)])) as execute:
        app = AppTest.from_file(str(ROOT / "sqlapp.py"), default_timeout=20)
        app.session_state["authenticated_username"] = "employee"
        app.run()
        next(box for box in app.checkbox if box.label == "Use controlled LangGraph workflow").check().run()
        next(area for area in app.text_area if area.label == "...or type your own question:").set_value("How many employees can I access?").run()
        next(button for button in app.button if button.label == "Generate SQL").click().run()
        assert not app.exception
        assert app.session_state["pending_query"]["workflow"] == "graph"
        execute.assert_not_called()
        next(button for button in app.button if button.label == "Run this query").click().run()
        assert not app.exception
        execute.assert_called_once()
        assert app.session_state["pending_query"] is None
