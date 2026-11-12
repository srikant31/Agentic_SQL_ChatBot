from copy import deepcopy
import json

import pytest

from business_context import load_business_rules
from rbac import USERS
from schema_context import dependency_version, get_catalog
from sql_examples import approve_example, eligible_examples, load_examples, retrieve_examples


def record(catalog):
    tables, columns = ["EMPLOYEES"], ["EMPLOYEES.DEPARTMENT", "EMPLOYEES.SALARY"]
    return {"id": "test-average", "question": "Show average recorded salary by department",
            "sql": "SELECT DEPARTMENT, AVG(SALARY) AS mean FROM EMPLOYEES GROUP BY DEPARTMENT",
            "sql_dialect": "sqlite", "referenced_tables": tables, "referenced_columns": columns,
            "schema_version": dependency_version(catalog, tables, columns),
            "business_rule_versions": {"average_recorded_salary": 1}, "required_permissions": ["salary"],
            "verification_status": "approved", "reviewer": "test-reviewer", "reviewed_at": "2026-11-12",
            "verification_evidence": {"semantic_review": True, "expected_result_review": True,
                                      "fixture": "fictional-employees-v1", "test": "golden comparison"},
            "template_family": "department-average"}


def test_only_reviewed_compatible_examples_are_eligible(hr_catalog):
    rules = load_business_rules(hr_catalog, USERS["hr"])
    original = record(hr_catalog)
    assert eligible_examples([original], hr_catalog, rules, USERS["hr"]) == (original,)
    variants = [{"verification_status": "draft"}, {"verification_status": "stale"},
                {"sql_dialect": "mysql"}, {"schema_version": "old"},
                {"business_rule_versions": {"average_recorded_salary": 2}},
                {"reviewer": ""}, {"verification_evidence": {"execution_success": True}},
                {"sql": "SELECT UNKNOWN FROM EMPLOYEES"}, {"sql": "DELETE FROM EMPLOYEES"},
                {"referenced_columns": []}]
    for changes in variants:
        candidate = {**deepcopy(original), **changes}
        assert eligible_examples([candidate], hr_catalog, rules, USERS["hr"]) == ()
        assert candidate["verification_status"] == changes.get("verification_status", "approved")


def test_restricted_examples_cannot_leak_even_if_permissions_are_mislabeled(hr_catalog, demo_engine):
    candidate = record(hr_catalog)
    candidate["required_permissions"] = []
    catalog = get_catalog(USERS["employee"], demo_engine)
    assert eligible_examples([candidate], catalog, load_business_rules(catalog, USERS["employee"]), USERS["employee"]) == ()


def test_question_retrieval_deduplicates_patterns_and_rejects_no_match(hr_catalog):
    first = record(hr_catalog)
    second = {**first, "id": "duplicate", "question": "Mean recorded salary by department"}
    assert len(retrieve_examples("average salary department", [first, second])) == 1
    assert retrieve_examples("galactic migration", [first]) == ()


def test_collection_errors_are_explicit(tmp_path):
    path = tmp_path / "examples.jsonl"
    path.write_text('{"id":"duplicate"}\n{"id":"duplicate"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_examples(path)


def test_bundled_examples_are_reviewed_against_expected_results(demo_engine, hr_catalog):
    from database import run_query
    records = load_examples()
    assert len(records) >= 3
    eligible = eligible_examples(records, hr_catalog, load_business_rules(hr_catalog, USERS["hr"]), USERS["hr"])
    assert len(eligible) == len(records)
    for example in eligible:
        _, rows = run_query(example["sql"], USERS["hr"], demo_engine)
        assert [list(row) for row in rows] == example["expected_fixture_rows"]


def test_approval_requires_explicit_review_and_independent_results(demo_engine, hr_catalog):
    draft = {**record(hr_catalog), "verification_status": "draft"}
    expected = [["Engineering", 75000.0], ["HR", 107500.0], ["IT", 90000.0]]
    with pytest.raises(ValueError, match="reviewer"):
        approve_example(draft, demo_engine, reviewer="", review_note="x", expected_rows=expected)
    with pytest.raises(ValueError, match="does not match"):
        approve_example(draft, demo_engine, reviewer="maintainer", review_note="Reviewed AVG at employee grain and department grouping.", expected_rows=[["Engineering", 999]])
    approved = approve_example(draft, demo_engine, reviewer="maintainer", review_note="Reviewed AVG at employee grain and department grouping.", expected_rows=expected)
    assert approved["verification_status"] == "approved"
    assert draft["verification_status"] == "draft"
    assert approved["required_permissions"] == ["salary"]
