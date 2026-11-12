from unittest.mock import patch
import pytest
from rbac import USERS
from sql_graph import SQLWorkflow


PROPOSAL = {"status": "proposal", "sql": "SELECT COUNT(*) FROM EMPLOYEES", "owner": "employee"}


def test_pause_reject_and_no_execution():
    workflow = SQLWorkflow(USERS["employee"])
    with patch("sql_graph.prepare_proposal", return_value=PROPOSAL), patch("sql_graph.validate_proposal"), patch("sql_graph.execute_proposal") as execute:
        assert workflow.start("Count employees", USERS["employee"])["__interrupt__"]
        execute.assert_not_called()
        assert workflow.resume("reject", USERS["employee"])["status"] == "rejected"
        execute.assert_not_called()


def test_approve_once_and_replay_is_denied():
    workflow = SQLWorkflow(USERS["employee"])
    with patch("sql_graph.prepare_proposal", return_value=PROPOSAL), patch("sql_graph.validate_proposal"), patch("sql_graph.execute_proposal", return_value=(["count"], [(3,)])) as execute:
        workflow.start("Count employees", USERS["employee"])
        result = workflow.resume("approve", USERS["employee"])
        assert result["rows"] == [(3,)] and result["status"] == "complete"
        execute.assert_called_once()
        with pytest.raises(ValueError):
            workflow.resume("approve", USERS["employee"])


def test_owner_and_session_isolation():
    first, second = SQLWorkflow(USERS["employee"]), SQLWorkflow(USERS["employee"])
    with patch("sql_graph.prepare_proposal", return_value=PROPOSAL), patch("sql_graph.validate_proposal"):
        first.start("Count", USERS["employee"])
        assert second.pending is False
        with pytest.raises(PermissionError):
            first.resume("approve", USERS["hr"])


def test_validation_retries_are_bounded():
    from semantic_validation import SemanticValidationError
    workflow = SQLWorkflow(USERS["employee"])
    with patch("sql_graph.prepare_proposal", side_effect=SemanticValidationError("bad SQL")) as generate:
        result = workflow.start("Count", USERS["employee"])
        assert result["status"] == "error" and result["attempts"] == 3
        assert generate.call_count == 3


def test_repair_after_approval_always_requires_new_approval():
    from semantic_validation import SemanticValidationError
    workflow = SQLWorkflow(USERS["employee"])
    with patch("sql_graph.prepare_proposal", return_value=PROPOSAL), patch("sql_graph.validate_proposal"), patch("sql_graph.execute_proposal", side_effect=SemanticValidationError("wrong edited SQL")) as execute:
        workflow.start("Count", USERS["employee"])
        result = workflow.resume("approve", USERS["employee"], "SELECT AVG(SALARY) FROM EMPLOYEES")
        assert result["__interrupt__"] and not result["approved"]
        assert execute.call_count == 1


def test_real_snapshot_and_edited_sql_validation(demo_engine):
    workflow = SQLWorkflow(USERS["employee"], demo_engine, max_attempts=1)
    with patch("sql_generator.generate_sql", return_value={"sql": PROPOSAL["sql"], "explanation": "Count", "confidence": .9}):
        workflow.start("How many employees can I access?", USERS["employee"])
        result = workflow.resume("approve", USERS["employee"], "SELECT SALARY FROM EMPLOYEES")
        assert result["status"] == "error" and result["rows"] == []
        workflow.start("How many employees can I access?", USERS["employee"])
        result = workflow.resume("approve", USERS["employee"])
        assert result["rows"] == [(3,)]


def test_unsupported_and_provider_failure_do_not_retry():
    from sql_generator import LLMProviderError
    for response in ({"status": "unsupported", "message": "No data"}, LLMProviderError("access denied")):
        workflow = SQLWorkflow(USERS["employee"])
        options = {"side_effect": response} if isinstance(response, Exception) else {"return_value": response}
        with patch("sql_graph.prepare_proposal", **options) as generate, patch("sql_graph.execute_proposal") as execute:
            result = workflow.start("Revenue", USERS["employee"])
            assert not result.get("__interrupt__")
            assert generate.call_count == 1
            execute.assert_not_called()
