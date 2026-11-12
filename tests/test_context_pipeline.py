from copy import deepcopy
import json
from unittest.mock import patch

import pytest
from sqlalchemy import text

from business_context import RULES_PATH, analyze_intent, load_business_rules
from context_pipeline import execute_proposal, prepare_context, prepare_proposal
from rbac import USERS
from schema_context import get_catalog
from semantic_validation import SemanticValidationError


@pytest.mark.parametrize("question,status", [
    ("Top customers by net revenue last month excluding refunds", "unsupported"),
    ("Show salary growth", "unsupported"),
    ("Who joined last month?", "unsupported"),
    ("Show the top five departments", "clarification"),
    ("Show payroll", "clarification"),
    ("Who is the best employee?", "clarification"),
    ("Show each employee's manager's salary", "unsupported"),
])
def test_capability_checks_do_not_call_the_llm(question, status, demo_engine):
    with patch("sql_generator.generate_sql") as generate:
        outcome = prepare_proposal(question, USERS["hr"], demo_engine)
    assert outcome["status"] == status
    generate.assert_not_called()


def test_role_context_contains_no_salary_definitions_or_examples(demo_engine):
    context = prepare_context("Show staff by position", USERS["employee"], demo_engine)
    assert "SALARY" not in context.prompt_context
    assert all(not rule.permission for rule in context.rules)
    denied = prepare_proposal("Show average salary", USERS["employee"], demo_engine)
    assert denied["status"] == "denied"


def test_small_schema_is_kept_and_context_limits_fail_without_truncation(hr_catalog):
    context = prepare_context("How many employees can I access?", USERS["hr"], catalog=hr_catalog)
    assert context.catalog.tables == hr_catalog.tables
    assert context.hits
    assert context.intent.metric_ids == ("employee_count",)
    with pytest.raises(ValueError, match="exceeds the budget"):
        prepare_context("How many employees can I access?", USERS["hr"], catalog=hr_catalog, max_characters=20)


def test_generation_is_separate_from_execution_and_owner_bound(demo_engine):
    with patch("sql_generator.generate_sql", return_value={"sql": "SELECT COUNT(*) FROM EMPLOYEES", "explanation": "Count", "confidence": .9}), patch("database.run_query") as execute:
        proposal = prepare_proposal("How many employees can I access?", USERS["employee"], demo_engine)
        assert proposal["status"] == "proposal"
        execute.assert_not_called()
    columns, rows = execute_proposal(proposal, USERS["employee"], demo_engine)
    assert rows == [(3,)]
    assert proposal["validation"]["checks"]
    with pytest.raises(PermissionError):
        execute_proposal(proposal, USERS["hr"], demo_engine)


def test_wrong_aggregate_never_becomes_pending_proposal(demo_engine):
    with patch("sql_generator.generate_sql", return_value={"sql": "SELECT SUM(SALARY) FROM EMPLOYEES", "explanation": "Average", "confidence": 1}):
        with pytest.raises(SemanticValidationError):
            prepare_proposal("Show average recorded salary", USERS["hr"], demo_engine)


def test_reviewed_definition_change_invalidates_pending_query(demo_engine, tmp_path):
    rules_path = tmp_path / "rules.yaml"
    original = RULES_PATH.read_text(encoding="utf-8")
    rules_path.write_text(original, encoding="utf-8")
    with patch("sql_generator.generate_sql", return_value={"sql": "SELECT COUNT(*) FROM EMPLOYEES", "explanation": "Count", "confidence": .9}):
        proposal = prepare_proposal("How many employees can I access?", USERS["hr"], demo_engine, rules_path=rules_path)
    rules_path.write_text(original.replace("Visible employee count", "Current authorized employee count"), encoding="utf-8")
    with patch("database.run_query") as execute:
        with pytest.raises(SemanticValidationError, match="changed"):
            execute_proposal(proposal, USERS["hr"], demo_engine, rules_path=rules_path)
        execute.assert_not_called()


def test_changed_sql_is_revalidated_at_execution(demo_engine):
    with patch("sql_generator.generate_sql", return_value={"sql": "SELECT SUM(SALARY) FROM EMPLOYEES", "explanation": "Sum", "confidence": .9}):
        proposal = prepare_proposal("Show recorded salary total", USERS["hr"], demo_engine)
    proposal["sql"] = "SELECT AVG(SALARY) FROM EMPLOYEES"
    with pytest.raises(SemanticValidationError):
        execute_proposal(proposal, USERS["hr"], demo_engine)


def test_source_drift_is_checked_fresh_at_execution(demo_engine):
    with patch("sql_generator.generate_sql", return_value={"sql": "SELECT COUNT(*) FROM EMPLOYEES", "explanation": "Count", "confidence": .9}):
        proposal = prepare_proposal("How many employees can I access?", USERS["hr"], demo_engine)
    with demo_engine.begin() as connection:
        connection.execute(text("ALTER TABLE RBAC_DEMO_EMPLOYEES RENAME COLUMN SALARY TO LEGACY_SALARY"))
    with pytest.raises(ValueError, match="schema changed"):
        execute_proposal(proposal, USERS["hr"], demo_engine)
