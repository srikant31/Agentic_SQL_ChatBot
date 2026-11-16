from dataclasses import replace

import pytest
from sqlalchemy import text

from business_context import load_business_rules
from rbac import USERS
from schema_context import CatalogError, dependency_version, extract_catalog, get_catalog, project_catalog


def test_reflection_is_allowlisted_and_projection_is_role_specific(demo_engine):
    with demo_engine.begin() as connection:
        connection.execute(text("CREATE TABLE SECRET (VALUE TEXT)"))
    physical = extract_catalog(demo_engine, {"RBAC_DEMO_EMPLOYEES"})
    assert [table.name for table in physical.tables] == ["RBAC_DEMO_EMPLOYEES"]
    assert physical.tables[0].primary_key == ("EMPLOYEE_ID",)
    assert physical.relationships == ()
    employee = project_catalog(physical, USERS["employee"])
    hr = project_catalog(physical, USERS["hr"])
    admin = project_catalog(physical, USERS["admin"])
    assert "SALARY" not in employee.render()
    assert "SALARY" not in admin.render()
    assert "SALARY" in hr.render()
    assert "RBAC_DEMO" not in hr.render()
    assert len({employee.version, hr.version, admin.version}) == 3


def test_fk_reflection_preserves_composite_key(demo_engine):
    with demo_engine.begin() as connection:
        connection.execute(text("CREATE TABLE PARENT (A INTEGER, B INTEGER, PRIMARY KEY(A,B))"))
        connection.execute(text("CREATE TABLE CHILD (ID INTEGER PRIMARY KEY, A INTEGER, B INTEGER, FOREIGN KEY(A,B) REFERENCES PARENT(A,B))"))
    catalog = extract_catalog(demo_engine, {"PARENT", "CHILD"})
    relationship, = catalog.relationships
    assert relationship.from_columns == ("A", "B")
    assert relationship.to_columns == ("A", "B")
    assert relationship.cardinality == "many_to_one"


def test_refresh_detects_structural_drift(demo_engine):
    before = get_catalog(USERS["hr"], demo_engine)
    with demo_engine.begin() as connection:
        connection.execute(text("ALTER TABLE RBAC_DEMO_EMPLOYEES RENAME COLUMN SALARY TO LEGACY_SALARY"))
    with pytest.raises(CatalogError, match="schema changed"):
        get_catalog(USERS["hr"], demo_engine, refresh=True)
    assert before.tables[0].name == "EMPLOYEES"


def test_missing_identity_key_fails_closed(demo_engine):
    physical = extract_catalog(demo_engine, {"RBAC_DEMO_EMPLOYEES"})
    broken = replace(physical, tables=(replace(physical.tables[0], primary_key=()),))
    with pytest.raises(CatalogError, match="identity key"):
        project_catalog(broken, USERS["hr"])


def test_dependency_version_ignores_unreferenced_columns(hr_catalog):
    reference = dependency_version(hr_catalog, ["EMPLOYEES"], ["EMPLOYEES.EMPLOYEE_ID"])
    employee_catalog = replace(hr_catalog, tables=(replace(hr_catalog.tables[0], columns=hr_catalog.tables[0].columns[:-1]),))
    assert reference == dependency_version(employee_catalog, ["EMPLOYEES"], ["EMPLOYEES.EMPLOYEE_ID"])
    with pytest.raises(CatalogError):
        dependency_version(employee_catalog, ["EMPLOYEES"], ["EMPLOYEES.SALARY"])


def test_restricted_business_definitions_are_never_loaded(demo_engine):
    catalog = get_catalog(USERS["employee"], demo_engine)
    rules = load_business_rules(catalog, USERS["employee"])
    assert all(not rule.permission for rule in rules)
    assert "SALARY" not in repr(rules)


def test_broken_approved_definition_is_rejected(hr_catalog, tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text('rules:\n- id: bad\n  version: 1\n  kind: definition\n  status: approved\n  description: bad\n  aliases: [bad]\n  columns: [EMPLOYEES.UNKNOWN]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="unavailable field"):
        load_business_rules(hr_catalog, USERS["hr"], path)
