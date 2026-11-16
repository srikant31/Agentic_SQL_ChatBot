from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import json
import pytest
from sqlalchemy import create_engine
from streamlit.testing.v1 import AppTest
from langgraph.checkpoint.memory import InMemorySaver
from database import initialize_demo
from coldchain_graph import build_graph as real_build_graph
from sql_guard import fixture_schema

ROOT = Path(__file__).resolve().parents[1]
QUESTION = "How many employees can I access?"
COUNT = {"sql": "SELECT COUNT(*) AS employee_count FROM EMPLOYEES", "explanation": "Counts the employee records available to your role.", "confidence": .9}


def button(app, label):
    return next(item for item in app.button if item.label == label)


@pytest.fixture
def employee_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/chat.db")
    initialize_demo(engine)
    with patch("database.get_engine", return_value=engine), patch("database.get_read_engine", return_value=engine), patch("database.ensure_demo"):
        yield
    engine.dispose()


def area(app):
    return next(item for item in app.text_area if item.label == "What should change?")


@pytest.mark.parametrize("graph_mode", [False, True])
def test_chat_keeps_question_explanation_and_feedback_separate_from_execution(employee_database, graph_mode):
    revised = {**COUNT, "sql": "SELECT COUNT(*) AS employee_count FROM EMPLOYEES WHERE DEPARTMENT = 'Engineering'", "explanation": "Counts only Engineering employees within your permitted data."}
    with patch("sql_generator.generate_sql", side_effect=[COUNT, revised]), patch("sql_generator.rewrite_question", return_value="How many employees are in Engineering?") as rewrite, patch("database.run_query", return_value=(["employee_count"], [(3,)])) as execute:
        app = AppTest.from_file(str(ROOT / "tests/fixtures/employee_app.py"), default_timeout=20)
        app.session_state["authenticated_username"] = "hr"
        app.run()
        if graph_mode:
            next(box for box in app.checkbox if box.label == "Use controlled LangGraph workflow").check().run()
        app.chat_input[0].set_value(QUESTION).run()
        assert not app.exception
        assert any(item.value == QUESTION for item in app.markdown)
        assert any("Counts the employee" in item.value for item in app.markdown)
        execute.assert_not_called()
        button(app, "👍 Looks good").click().run()
        execute.assert_not_called()
        button(app, "👎 Needs changes").click().run()
        assert not app.exception
        assert "Please prompt again" in area(app).proto.placeholder
        assert not any(item.label == "Run this query" for item in app.button)
        area(app).set_value("Only Engineering please").run()
        button(app, "Rewrite query").click().run()
        assert not app.exception
        request = app.session_state["employee_query_chat"]["requests"][-1]
        assert request["original_question"] == QUESTION and request["rewrites"] == 1
        assert request["modifications"] == ["Only Engineering please"]
        rewrite.assert_called_once_with(QUESTION, QUESTION, ["Only Engineering please"])
        execute.assert_not_called()
        button(app, "Run this query").click().run()
        assert not app.exception
        execute.assert_called_once()
        assert "Engineering" in execute.call_args.args[0]
        assert app.session_state["pending_query"] is None
        assert request["messages"][-1]["rows"] == [(3,)]


def test_three_rewrites_then_apology_without_fourth_generation(employee_database):
    with patch("sql_generator.generate_sql", return_value=COUNT) as generate, patch("sql_generator.rewrite_question", return_value=QUESTION) as rewrite, patch("database.run_query") as execute:
        app = AppTest.from_file(str(ROOT / "tests/fixtures/employee_app.py"), default_timeout=20)
        app.session_state["authenticated_username"] = "employee"
        app.run()
        app.chat_input[0].set_value(QUESTION).run()
        for number in range(3):
            button(app, "👎 Needs changes").click().run()
            area(app).set_value(f"Please make the explanation clearer, revision {number + 1}").run()
            button(app, "Rewrite query").click().run()
            assert not app.exception
        button(app, "👎 Needs changes").click().run()
        app.run()
        assert any("three rewrites" in item.value for item in app.info)
        assert not any(item.label == "Rewrite query" for item in app.button)
        assert generate.call_count == 4 and rewrite.call_count == 3
        assert app.session_state["employee_query_chat"]["requests"][-1]["rewrites"] == 3
        execute.assert_not_called()


def test_rewritten_question_is_authorized_again(employee_database):
    with patch("sql_generator.generate_sql", return_value=COUNT) as generate, patch("sql_generator.rewrite_question", return_value="Show all employee salaries"), patch("database.run_query") as execute:
        app = AppTest.from_file(str(ROOT / "tests/fixtures/employee_app.py"), default_timeout=20)
        app.session_state["authenticated_username"] = "employee"
        app.run()
        app.chat_input[0].set_value(QUESTION).run()
        button(app, "👎 Needs changes").click().run()
        area(app).set_value("Include salaries").run()
        button(app, "Rewrite query").click().run()
        assert not app.exception
        assert app.session_state["pending_query"] is None
        assert not any(item.label == "Run this query" for item in app.button)
        generate.assert_called_once()
        execute.assert_not_called()


def test_coldchain_feedback_restores_rewrite_budget_and_requires_approval(monkeypatch):
    monkeypatch.setenv("COLDCHAIN_DB_URL", "offline-test-configured")
    monkeypatch.setenv("COLDCHAIN_ADMIN_USERS", "")
    saver = InMemorySaver()
    responses = [{"kind": "proceed"}, {"sql": "SELECT COUNT(*) FROM orders", "explanation": "Counts all orders."},
                 {"kind": "proceed"}, {"sql": "SELECT COUNT(*) FROM orders WHERE order_date >= '2026-03-01' AND order_date < '2026-04-01'", "explanation": "Counts orders placed in March 2026."}, {"answer": "3 orders"}]
    llm = Mock()
    llm.invoke.side_effect = [Mock(content=json.dumps(item)) for item in responses]
    execute = Mock(return_value=(["count"], [[3]]))

    def context(question, role):
        schema = fixture_schema()
        schema.pop("employees")
        schema["customers"].pop("email")
        return {"text": "authorized ColdChain schema", "schema": schema, "database": "coldchain"}

    def build(checkpointer, **kwargs):
        return real_build_graph(checkpointer, llm=llm, context_loader=context, executor=execute,
                                review_all=kwargs["review_all"], max_attempts=kwargs["max_attempts"], explain_sql=kwargs["explain_sql"])

    with patch("checkpointing.get_checkpointer", return_value=SimpleNamespace(saver=saver, persistent=True)), patch("coldchain_context.get_coldchain_engine", return_value=None), patch("coldchain_graph.build_graph", side_effect=build), patch("sql_generator.rewrite_question", return_value="Count March 2026 orders"):
        app = AppTest.from_file(str(ROOT / "sqlapp.py"), default_timeout=20)
        app.session_state["authenticated_username"] = "employee"
        app.run()
        app.chat_input[0].set_value("Count all orders").run()
        assert not app.exception
        execute.assert_not_called()
        button(app, "👎 Needs changes").click().run()
        area(app).set_value("Only March 2026").run()
        button(app, "Rewrite query").click().run()
        assert not app.exception
        assert app.session_state["coldchain_query_chat"]["requests"][-1]["rewrites"] == 1
        del app.session_state["coldchain_query_chat"]
        app.run()
        assert not app.exception
        assert app.session_state["coldchain_query_chat"]["requests"][-1]["rewrites"] == 1
        assert llm.invoke.call_count == 4
        button(app, "👍 Looks good").click().run()
        execute.assert_not_called()
        button(app, "Approve & run").click().run()
        assert not app.exception
        execute.assert_called_once()
