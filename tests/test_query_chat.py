from copy import deepcopy
import pytest
from query_chat import (new_chat, start_request, add_response, feedback, begin_rewrite,
                        executable, latest_response, record_result, LIMIT_MESSAGE)


def proposal():
    return {"sql": "SELECT COUNT(*) FROM EMPLOYEES", "explanation": "Counts visible employees."}


def test_feedback_is_not_approval_and_negative_feedback_blocks_execution():
    request = start_request(new_chat("employee", "employee"), "How many employees?")
    add_response(request, proposal())
    assert executable(request)
    feedback(request, "positive", 0)
    assert not latest_response(request)["execution_attempted"]
    feedback(request, "negative", 0)
    assert request["feedback_open"] and not executable(request)
    feedback(request, "positive", 0)
    assert executable(request)


def test_three_rewrites_keep_original_and_cannot_be_replayed():
    request = start_request(new_chat("hr", "employee"), "Count employees")
    add_response(request, proposal())
    for revision in range(3):
        feedback(request, "negative", revision)
        begin_rewrite(request, f"Modification {revision + 1}", revision)
        assert not executable(request)
        with pytest.raises(ValueError):
            begin_rewrite(request, "Replay old event", revision)
        add_response(request, proposal())
    restored = deepcopy(request)
    feedback(restored, "negative", 3)
    assert restored["exhausted"] and not restored["feedback_open"]
    with pytest.raises(ValueError):
        begin_rewrite(restored, "Fourth rewrite", 3)
    assert restored["original_question"] == "Count employees"
    assert len(restored["modifications"]) == 3
    assert restored["messages"][0] == {"role": "user", "text": "Count employees"}


def test_new_question_has_a_new_budget_and_old_results_stay_with_old_response():
    chat = new_chat("hr", "employee")
    first = start_request(chat, "Count employees")
    add_response(first, proposal())
    record_result(first, ["count"], [(3,)])
    assert not executable(first)
    second = start_request(chat, "List departments")
    assert second["id"] != first["id"] and second["rewrites"] == 0
    assert latest_response(first)["rows"] == [(3,)]


def test_invalid_feedback_does_not_consume_budget():
    request = start_request(new_chat("hr", "employee"), "Count employees")
    add_response(request, proposal())
    feedback(request, "negative", 0)
    for value in (" ", "a" * 2001):
        with pytest.raises(ValueError):
            begin_rewrite(request, value, 0)
    assert request["rewrites"] == 0
