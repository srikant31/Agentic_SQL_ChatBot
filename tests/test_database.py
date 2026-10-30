import sqlite3
import pytest
from sqlalchemy import create_engine, text
from database import initialize_demo, run_query, update_job_title, get_diagnostics, get_schema
from rbac import USERS, User, AccessDenied, authenticate, require
from safety import UnsafeQueryError

@pytest.fixture
def engine(tmp_path):
    db = create_engine(f"sqlite:///{tmp_path}/roles.db")
    with db.begin() as conn:
        conn.execute(text("CREATE TABLE EMPLOYEES (ID INTEGER)"))
        conn.execute(text("INSERT INTO EMPLOYEES VALUES (999)"))
    initialize_demo(db)
    yield db
    db.dispose()

@pytest.mark.parametrize("name,password", [("employee", "employee123"), ("hr", "hr123"), ("admin", "admin123")])
def test_login(name, password):
    assert authenticate(name, password) == USERS[name]
    assert authenticate(name, "incorrect") is None
    assert authenticate("unknown", password) is None

@pytest.mark.parametrize("user", [None, User("employee", "it_admin"), User("unknown", "hr")])
def test_unauthenticated_or_forged_user_denied(engine, user):
    with pytest.raises(AccessDenied):
        run_query("SELECT * FROM EMPLOYEES", user, engine)

def test_employee_only_sees_own_department_despite_or_true(engine):
    columns, rows = run_query("SELECT * FROM EMPLOYEES WHERE 1=1", USERS["employee"], engine)
    assert len(rows) == 3
    assert set(row[columns.index("DEPARTMENT")] for row in rows) == {"Engineering"}
    assert "SALARY" not in columns

@pytest.mark.parametrize("name", ["employee", "admin"])
@pytest.mark.parametrize("sql", ["SELECT SALARY FROM EMPLOYEES", "WITH data AS (SELECT * FROM EMPLOYEES) SELECT SALARY FROM data", "SELECT NAME FROM EMPLOYEES UNION SELECT CAST(SALARY AS TEXT) FROM EMPLOYEES"])
def test_salary_cannot_be_recovered_by_non_hr(engine, name, sql):
    with pytest.raises(sqlite3.DatabaseError):
        run_query(sql, USERS[name], engine)
    assert "SALARY" not in get_schema(USERS[name])

def test_hr_sees_all_rows_and_salaries(engine):
    columns, rows = run_query("SELECT * FROM EMPLOYEES", USERS["hr"], engine)
    assert len(rows) == 6
    assert "SALARY" in columns
    assert {row[columns.index("DEPARTMENT")] for row in rows} == {"Engineering", "HR", "IT"}

@pytest.mark.parametrize("name", ["employee", "hr", "admin"])
@pytest.mark.parametrize("sql", ["UPDATE EMPLOYEES SET JOB_TITLE='Hacked'", "SELECT * FROM EMPLOYEES; DROP TABLE EMPLOYEES"])
def test_arbitrary_sql_writes_denied_for_every_role(engine, name, sql):
    with pytest.raises(UnsafeQueryError):
        run_query(sql, USERS[name], engine)

@pytest.mark.parametrize("sql", ["SELECT * FROM sqlite_master", "SELECT * FROM RBAC_DEMO_AUDIT", "SELECT * FROM RBAC_DEMO_EMPLOYEES", "SELECT load_extension('anything')"])
def test_queries_cannot_escape_snapshot(engine, sql):
    with pytest.raises(sqlite3.DatabaseError):
        run_query(sql, USERS["hr"], engine)

@pytest.mark.parametrize("name", ["employee", "hr"])
def test_non_admin_write_and_admin_page_permission_denied(engine, name):
    with pytest.raises(AccessDenied):
        update_job_title(USERS[name], 1, "Manager", confirmed=True, engine=engine)
    with pytest.raises(AccessDenied):
        require(USERS[name], "edit_title")

def test_employee_explorer_denied():
    with pytest.raises(AccessDenied):
        require(USERS["employee"], "explorer")

def test_admin_needs_confirmation(engine):
    with pytest.raises(PermissionError):
        update_job_title(USERS["admin"], 1, "Senior Engineer", engine=engine)
    assert not get_diagnostics(USERS["admin"], engine)["recent_changes"]

def test_admin_write_persists_and_creates_audit_without_salary_change(engine):
    update_job_title(USERS["admin"], 1, "Senior Software Engineer", confirmed=True, engine=engine)
    _, rows = run_query("SELECT JOB_TITLE, SALARY FROM EMPLOYEES WHERE EMPLOYEE_ID=1", USERS["hr"], engine)
    assert rows == [("Senior Software Engineer", 80000)]
    event = get_diagnostics(USERS["admin"], engine)["recent_changes"][0]
    assert event["ACTOR"] == "admin"
    assert event["OLD_TITLE"] == "Software Engineer"
    assert event["NEW_TITLE"] == "Senior Software Engineer"

def test_original_table_unchanged_and_seed_is_idempotent(engine):
    initialize_demo(engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT ID FROM EMPLOYEES")).scalar_one() == 999
        assert conn.execute(text("SELECT COUNT(*) FROM RBAC_DEMO_EMPLOYEES")).scalar_one() == 6

def test_sql_text_in_title_is_data_not_sql(engine):
    title = "Engineer'; DROP TABLE EMPLOYEES; --"
    update_job_title(USERS["admin"], 1, title, confirmed=True, engine=engine)
    assert get_diagnostics(USERS["admin"], engine)["demo_rows"] == 6
    with engine.connect() as conn:
        assert conn.execute(text("SELECT JOB_TITLE FROM RBAC_DEMO_EMPLOYEES WHERE EMPLOYEE_ID=1")).scalar_one() == title
