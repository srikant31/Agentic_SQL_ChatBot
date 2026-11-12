"""Regression tests for intent-analysis false positives and gaps found in the Nov 12 audit."""
import pytest

from business_context import analyze_intent, load_business_rules
from rbac import USERS


def intent(question, catalog, user="hr"):
    return analyze_intent(question, catalog, load_business_rules(catalog, USERS[user]), USERS[user])


@pytest.mark.parametrize("question", [
    "List employees in alphabetical order",
    "Show employees sorted in order of salary",
    "Which employees can update their title?",
])
def test_ordinary_phrasing_is_not_rejected(hr_catalog, question):
    assert intent(question, hr_catalog).status == "query"


@pytest.mark.parametrize("question", [
    "Delete all employees.",
    "Update Bob Brown's salary using generated SQL.",
    "Show employees and then drop the table",
    "Please insert a new employee",
])
def test_imperative_write_requests_are_still_rejected(hr_catalog, question):
    assert intent(question, hr_catalog).status == "unsupported"


@pytest.mark.parametrize("question", [
    "Show customer orders for October",
    "How many orders placed last month?",
])
def test_order_data_requests_remain_unsupported(hr_catalog, question):
    assert intent(question, hr_catalog).status == "unsupported"


@pytest.mark.parametrize("question", [
    "Show the average salary for Pune employees",
    "How many employees are in each city?",
    "List staff by location",
])
def test_unknown_location_is_not_silently_ignored(hr_catalog, question):
    assert intent(question, hr_catalog).status == "unsupported"


@pytest.mark.parametrize("question", [
    "How many people work in Engineering?",
    "Show the average salary for Engineering employees",
    "List employees for IT",
])
def test_known_departments_are_not_treated_as_locations(hr_catalog, question):
    assert intent(question, hr_catalog).status == "query"


def test_in_it_adds_the_department_filter(hr_catalog):
    assert "DEPARTMENT = 'IT'" in intent("How many employees are in IT?", hr_catalog).predicates


def test_typed_name_case_is_normalized(hr_catalog):
    assert "NAME = 'Bob Brown'" in intent("who is bob brown's manager?", hr_catalog).predicates
