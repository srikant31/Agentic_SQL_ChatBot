"""Role-scoped live Aiven reads; generated SQL executes only on an authorized snapshot."""
import sqlite3
import time
import uuid
from datetime import datetime, timezone
import streamlit as st
from sqlalchemy import create_engine, text
from config import DB_URI, READONLY_DB_URI
from rbac import require, visible_columns
from safety import validate_readonly_sql
from schema_context import get_catalog
from semantic_validation import validate_sql

DEMO_TABLE = "RBAC_DEMO_EMPLOYEES"
AUDIT_TABLE = "RBAC_DEMO_AUDIT"
SEED_ROWS = [
    (1, "Bob Brown", "Engineering", "Software Engineer", "Jane Smith", 80000),
    (2, "Emily Davis", "Engineering", "Data Analyst", "Jane Smith", 75000),
    (3, "Michael Lee", "Engineering", "QA Engineer", "Jane Smith", 70000),
    (4, "Jane Smith", "HR", "HR Manager", "Sarah Connor", 95000),
    (5, "Sarah Connor", "HR", "HR Director", "CEO", 120000),
    (6, "David Kim", "IT", "IT Administrator", "Sarah Connor", 90000),
]

@st.cache_resource(show_spinner=False)
def get_engine():
    return create_engine(DB_URI, pool_pre_ping=True, pool_recycle=280,
                         connect_args={"connect_timeout": 10, "read_timeout": 15, "write_timeout": 15})

@st.cache_resource(show_spinner=False)
def get_read_engine():
    """Engine for the question-answering path (reflection and authorized snapshot reads only).

    Uses the optional least-privilege account when MYSQL_READONLY_USER is set; otherwise falls back to
    the existing engine so current deployments keep working. Writes always use get_engine().
    """
    if not READONLY_DB_URI:
        return get_engine()
    return create_engine(READONLY_DB_URI, pool_pre_ping=True, pool_recycle=280,
                         connect_args={"connect_timeout": 10, "read_timeout": 15})

def initialize_demo(engine=None):
    """Add isolated demo tables. Never alter or overwrite existing EMPLOYEES."""
    engine = engine if engine is not None else get_engine()
    with engine.begin() as conn:
        conn.execute(text(f"""CREATE TABLE IF NOT EXISTS {DEMO_TABLE} (
            EMPLOYEE_ID INTEGER PRIMARY KEY, NAME VARCHAR(100) NOT NULL,
            DEPARTMENT VARCHAR(50) NOT NULL, JOB_TITLE VARCHAR(100) NOT NULL,
            MANAGER_NAME VARCHAR(100), SALARY INTEGER NOT NULL)"""))
        conn.execute(text(f"""CREATE TABLE IF NOT EXISTS {AUDIT_TABLE} (
            EVENT_ID VARCHAR(36) PRIMARY KEY, ACTOR VARCHAR(50) NOT NULL,
            EMPLOYEE_ID INTEGER NOT NULL, OLD_TITLE VARCHAR(100),
            NEW_TITLE VARCHAR(100), CHANGED_AT VARCHAR(40) NOT NULL)"""))
        for row in SEED_ROWS:
            conn.execute(text(f"""INSERT INTO {DEMO_TABLE}
                (EMPLOYEE_ID, NAME, DEPARTMENT, JOB_TITLE, MANAGER_NAME, SALARY)
                SELECT :id, :name, :department, :title, :manager, :salary
                WHERE NOT EXISTS (SELECT 1 FROM {DEMO_TABLE} WHERE EMPLOYEE_ID=:id)"""),
                dict(zip(("id", "name", "department", "title", "manager", "salary"), row)))

@st.cache_resource(show_spinner="Preparing fictional RBAC demo records...")
def ensure_demo():
    initialize_demo()
    return True

def get_schema(user, engine=None):
    require(user, "query")
    engine = engine if engine is not None else get_read_engine()
    return get_catalog(user, engine).render()

def _authorized_rows(user, engine):
    require(user, "query")
    columns = visible_columns(user)
    statement = f"SELECT {', '.join(columns)} FROM {DEMO_TABLE}"
    params = {}
    if user.role == "employee":
        statement += " WHERE DEPARTMENT = :department"
        params["department"] = user.department
    statement += " LIMIT 10001"
    with engine.connect() as conn:
        rows = [tuple(row) for row in conn.execute(text(statement), params).fetchmany(10_001)]
        if len(rows) > 10_000:
            raise ValueError("Authorized snapshot exceeds 10,000 employees. Narrow the approved source before querying.")
    return columns, rows

def run_query(sql, user=None, engine=None):
    require(user, "query")
    validate_readonly_sql(sql)
    engine = engine if engine is not None else get_read_engine()
    validate_sql(sql, get_catalog(user, engine))
    columns, rows = _authorized_rows(user, engine)
    with sqlite3.connect(":memory:") as sandbox:
        sandbox.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1_000_000)
        sandbox.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 20_000)
        sandbox.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 100)
        definitions = ", ".join(f"{c} {'INTEGER' if c in ('EMPLOYEE_ID', 'SALARY') else 'TEXT'}{' PRIMARY KEY' if c == 'EMPLOYEE_ID' else ''}" for c in columns)
        sandbox.execute(f"CREATE TABLE EMPLOYEES ({definitions})")
        sandbox.executemany(f"INSERT INTO EMPLOYEES VALUES ({','.join('?' for _ in columns)})", rows)
        sandbox.commit()
        sandbox.execute("PRAGMA query_only = ON")
        def authorize(action, arg1, arg2, database, trigger):
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_READ and arg1.upper() == "EMPLOYEES":
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() not in {"load_extension", "readfile", "writefile"}:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        sandbox.set_authorizer(authorize)
        deadline = time.monotonic() + 3
        sandbox.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        cursor = sandbox.execute(sql)
        result = cursor.fetchmany(501)
        if len(result) > 500:
            raise ValueError("Result exceeds 500 rows. Add a LIMIT or aggregate the result.")
        return [c[0] for c in cursor.description], result

def update_job_title(user, employee_id, new_title, confirmed=False, engine=None):
    require(user, "edit_title")
    if not confirmed:
        raise PermissionError("Explicit confirmation is required before saving a change.")
    if isinstance(employee_id, bool) or not isinstance(employee_id, int):
        raise ValueError("Choose a valid employee ID.")
    new_title = new_title.strip()
    if not 2 <= len(new_title) <= 80 or any(ord(char) < 32 for char in new_title):
        raise ValueError("Job title must contain 2–80 printable characters.")
    engine = engine if engine is not None else get_engine()
    with engine.begin() as conn:
        old = conn.execute(text(f"SELECT JOB_TITLE FROM {DEMO_TABLE} WHERE EMPLOYEE_ID=:id"), {"id": employee_id}).first()
        if old is None:
            raise ValueError("Employee does not exist.")
        conn.execute(text(f"UPDATE {DEMO_TABLE} SET JOB_TITLE=:title WHERE EMPLOYEE_ID=:id"), {"title": new_title, "id": employee_id})
        conn.execute(text(f"INSERT INTO {AUDIT_TABLE} VALUES (:event, :actor, :id, :old, :new, :at)"),
                     {"event": str(uuid.uuid4()), "actor": user.username, "id": employee_id,
                      "old": old[0], "new": new_title, "at": datetime.now(timezone.utc).isoformat()})

def get_diagnostics(user, engine=None):
    require(user, "diagnostics")
    engine = engine if engine is not None else get_engine()
    with engine.connect() as conn:
        ping = conn.execute(text("SELECT 1")).scalar_one()
        count = conn.execute(text(f"SELECT COUNT(*) FROM {DEMO_TABLE}")).scalar_one()
        events = [dict(row) for row in conn.execute(text(f"SELECT ACTOR, EMPLOYEE_ID, OLD_TITLE, NEW_TITLE, CHANGED_AT FROM {AUDIT_TABLE} ORDER BY CHANGED_AT DESC LIMIT 20")).mappings()]
    return {"connection": "Live" if ping == 1 else "Unavailable", "demo_rows": count,
            "checked_at_utc": datetime.now(timezone.utc).isoformat(), "recent_changes": events}
