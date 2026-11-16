from dataclasses import replace

import pytest

from business_context import analyze_intent, load_business_rules
from context_models import ColumnRecord, RelationshipRecord, SchemaCatalog, TableRecord
from rbac import USERS
from safety import SchemaValidationError, UnsafeQueryError, validate_readonly_sql
from semantic_validation import SemanticValidationError, validate_sql


def check(question, sql, catalog):
    rules = load_business_rules(catalog, USERS["hr"])
    return validate_sql(sql, catalog, analyze_intent(question, catalog, rules, USERS["hr"]), rules)


@pytest.mark.parametrize("sql", [
    "SELECT * INTO backup FROM EMPLOYEES",
    "WITH x AS (DELETE FROM EMPLOYEES RETURNING *) SELECT * FROM x",
    "SELECT * FROM EMPLOYEES FOR UPDATE",
    "SELECT 1; DELETE FROM EMPLOYEES",
])
def test_write_operations_anywhere_are_rejected(sql):
    with pytest.raises(UnsafeQueryError):
        validate_readonly_sql(sql)


@pytest.mark.parametrize("sql", [
    "SELECT MISSING FROM EMPLOYEES",
    "WITH x AS (SELECT * FROM EMPLOYEES) SELECT MISSING FROM x",
    "SELECT * FROM main.EMPLOYEES",
    "SELECT * FROM RBAC_DEMO_EMPLOYEES",
    "SELECT readfile('secret')",
    "SELECT load_extension('secret')",
])
def test_schema_and_function_escape_is_rejected(sql, hr_catalog):
    with pytest.raises(SchemaValidationError):
        validate_sql(sql, hr_catalog)


@pytest.mark.parametrize("sql", [
    "SELECT AVG(SALARY) FROM EMPLOYEES",
    "SELECT SUM(DISTINCT SALARY) FROM EMPLOYEES",
    "SELECT 0 FROM (SELECT SUM(SALARY) AS total FROM EMPLOYEES)",
    "WITH x AS (SELECT SUM(SALARY) AS total FROM EMPLOYEES) SELECT 42 FROM x",
    "SELECT SUM(SALARY)*2 FROM EMPLOYEES",
])
def test_wrong_or_unused_metric_does_not_count_as_semantic_proof(sql, hr_catalog):
    with pytest.raises(SemanticValidationError, match="approved recorded_salary_total"):
        check("Show recorded salary total", sql, hr_catalog)


def test_valid_metric_and_cte_output_lineage(hr_catalog):
    for sql in ["SELECT SUM(SALARY) FROM EMPLOYEES",
                "WITH x AS (SELECT SUM(SALARY) AS total FROM EMPLOYEES) SELECT total FROM x"]:
        check("Show recorded salary total", sql, hr_catalog)


def test_outer_filter_cannot_discard_a_correct_inner_metric(hr_catalog):
    with pytest.raises(SemanticValidationError, match="outer transformation"):
        check("Show recorded salary total", "WITH x AS (SELECT SUM(SALARY) AS total FROM EMPLOYEES) SELECT total FROM x WHERE total=0", hr_catalog)


def test_union_cannot_bypass_top_n_contract(hr_catalog):
    with pytest.raises(SemanticValidationError, match="Set-operation"):
        check("Show the top five salaries", "SELECT SALARY FROM EMPLOYEES UNION ALL SELECT SALARY FROM EMPLOYEES", hr_catalog)


@pytest.mark.parametrize("sql", ["SELECT COUNT(*)", "SELECT COUNT(SALARY) FROM EMPLOYEES",
    "SELECT COUNT(*) FROM (SELECT 1)",
    "SELECT COUNT(*) FROM (SELECT * FROM EMPLOYEES LIMIT 1)",
    "SELECT COUNT(*) FROM (SELECT COUNT(*) AS n FROM EMPLOYEES)",
    "SELECT COUNT(*) FROM (SELECT * FROM EMPLOYEES UNION ALL SELECT * FROM EMPLOYEES)",
    "SELECT COUNT(*) FROM EMPLOYEES WHERE DEPARTMENT='HR'"])
def test_count_requires_real_employee_population(sql, hr_catalog):
    with pytest.raises(SemanticValidationError):
        check("How many employees can I access?", sql, hr_catalog)


def test_grouping_must_match_question(hr_catalog):
    check("Show average salary by department", "SELECT DEPARTMENT, AVG(SALARY) FROM EMPLOYEES GROUP BY DEPARTMENT", hr_catalog)
    with pytest.raises(SemanticValidationError, match="GROUP BY"):
        check("Show average salary by department", "SELECT MANAGER_NAME, AVG(SALARY) FROM EMPLOYEES GROUP BY MANAGER_NAME", hr_catalog)
    with pytest.raises(SemanticValidationError, match="grouping dimension"):
        check("Show average salary by department", "SELECT AVG(SALARY) FROM EMPLOYEES GROUP BY DEPARTMENT", hr_catalog)


@pytest.mark.parametrize("where", ["", " WHERE DEPARTMENT='HR'", " WHERE DEPARTMENT='Engineering' OR 1=1"])
def test_required_filter_is_not_satisfied_by_wrong_or_optional_predicate(where, hr_catalog):
    with pytest.raises(SemanticValidationError, match="required filter"):
        check("Show recorded salary total in Engineering", "SELECT SUM(SALARY) FROM EMPLOYEES" + where, hr_catalog)


def test_missing_manager_filters_and_ranking(hr_catalog):
    question = "Show the top five departments by recorded salary total, excluding employees whose recorded manager is missing or the CEO placeholder."
    sql = "SELECT DEPARTMENT, SUM(SALARY) AS total FROM EMPLOYEES WHERE MANAGER_NAME IS NOT NULL AND TRIM(MANAGER_NAME) <> '' AND UPPER(TRIM(MANAGER_NAME)) <> 'CEO' GROUP BY DEPARTMENT ORDER BY total DESC, DEPARTMENT LIMIT 5"
    check(question, sql, hr_catalog)
    for broken in [sql.replace("AND UPPER(TRIM(MANAGER_NAME)) <> 'CEO'", ""), sql.replace("LIMIT 5", "LIMIT 10"),
                   sql.replace("ORDER BY total DESC", "ORDER BY DEPARTMENT DESC"), sql.replace("total DESC", "total ASC")]:
        with pytest.raises(SemanticValidationError):
            check(question, broken, hr_catalog)


def test_name_join_is_not_an_identity_relationship(hr_catalog):
    with pytest.raises(SemanticValidationError, match="approved complete key"):
        validate_sql("SELECT e.NAME, m.SALARY FROM EMPLOYEES e JOIN EMPLOYEES m ON e.MANAGER_NAME=m.NAME", hr_catalog)


def test_explicit_threshold_having_and_requested_output_are_enforced(hr_catalog):
    cases = [
        ("Show employees with recorded salary above 80000", "SELECT NAME FROM EMPLOYEES"),
        ("Count employees by department with at least two employees", "SELECT DEPARTMENT, COUNT(*) FROM EMPLOYEES GROUP BY DEPARTMENT"),
        ("Who is Bob Brown's manager?", "SELECT NAME FROM EMPLOYEES WHERE NAME='Bob Brown'"),
        ("Show the top five salaries", "SELECT SALARY FROM EMPLOYEES ORDER BY NAME DESC LIMIT 5"),
    ]
    for question, sql in cases:
        with pytest.raises(SemanticValidationError):
            check(question, sql, hr_catalog)


def test_equal_amounts_and_missing_managers_are_handled_without_distinct(demo_engine):
    from sqlalchemy import text
    from database import run_query
    with demo_engine.begin() as connection:
        connection.execute(text("UPDATE RBAC_DEMO_EMPLOYEES SET SALARY=75000 WHERE EMPLOYEE_ID=1"))
        connection.execute(text("INSERT INTO RBAC_DEMO_EMPLOYEES VALUES (7, 'Bob Brown', 'Engineering', 'Tester', NULL, 75000)"))
    _, rows = run_query("SELECT SUM(SALARY) FROM EMPLOYEES WHERE DEPARTMENT='Engineering'", USERS["hr"], demo_engine)
    assert rows == [(295000,)]
    _, rows = run_query("SELECT COUNT(*) FROM EMPLOYEES WHERE MANAGER_NAME IS NOT NULL AND TRIM(MANAGER_NAME)<>'' AND UPPER(TRIM(MANAGER_NAME))<>'CEO'", USERS["hr"], demo_engine)
    assert rows == [(5,)]


def test_composite_join_and_fanout_protection():
    parent = TableRecord("PARENT", (ColumnRecord("A", "INTEGER"), ColumnRecord("B", "INTEGER"), ColumnRecord("AMOUNT", "INTEGER")))
    child = TableRecord("CHILD", (ColumnRecord("A", "INTEGER"), ColumnRecord("B", "INTEGER"), ColumnRecord("AMOUNT", "INTEGER")))
    relation = RelationshipRecord("child_parent", "CHILD", ("A", "B"), "PARENT", ("A", "B"))
    catalog = SchemaCatalog((parent, child), (relation,))
    valid = "SELECT SUM(c.AMOUNT) FROM CHILD c JOIN PARENT p ON c.A=p.A AND c.B=p.B"
    validate_sql(valid, catalog)
    with pytest.raises(SemanticValidationError, match="complete key"):
        validate_sql(valid.replace(" AND c.B=p.B", ""), catalog)
    with pytest.raises(SemanticValidationError, match="multiply"):
        validate_sql(valid.replace("SUM(c.AMOUNT)", "SUM(p.AMOUNT)"), catalog)
    with pytest.raises(SemanticValidationError):
        validate_sql(valid.replace("c.A=p.A AND c.B=p.B", "c.A=p.A OR 1=1"), catalog)


def test_later_fact_join_can_multiply_an_earlier_fact():
    fact = lambda name: TableRecord(name, (ColumnRecord("PARENT_ID", "INTEGER"), ColumnRecord("AMOUNT", "INTEGER")))
    parent = TableRecord("PARENT", (ColumnRecord("ID", "INTEGER"),))
    edges = (RelationshipRecord("first_parent", "FIRST_FACT", ("PARENT_ID",), "PARENT", ("ID",)),
             RelationshipRecord("second_parent", "SECOND_FACT", ("PARENT_ID",), "PARENT", ("ID",)))
    catalog = SchemaCatalog((fact("FIRST_FACT"), parent, fact("SECOND_FACT")), edges)
    with pytest.raises(SemanticValidationError, match="multiply"):
        validate_sql("SELECT SUM(f.AMOUNT) FROM FIRST_FACT f JOIN PARENT p ON f.PARENT_ID=p.ID JOIN SECOND_FACT s ON s.PARENT_ID=p.ID", catalog)
