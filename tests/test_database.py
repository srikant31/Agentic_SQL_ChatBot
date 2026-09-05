import pytest
from sqlalchemy import create_engine
from database import run_query


@pytest.fixture
def test_engine(tmp_path):
    """
    A real, disposable SQLite database for this test only — created fresh
    in a temp directory pytest cleans up automatically. We deliberately do
    NOT mock the database layer here: a mock would only prove our mock
    behaves as we told it to, not that run_query() actually talks to a
    real SQL engine correctly. This mirrors LazyQL's own testing choice.
    """
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    with engine.connect() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE EMPLOYEES (ID INTEGER, NAME TEXT, MANAGER_ID INTEGER)"
        )
        conn.exec_driver_sql(
            "INSERT INTO EMPLOYEES VALUES (1, 'Sarah', NULL), (2, 'Jane', 1)"
        )
        conn.commit()
    return engine


def test_run_query_returns_correct_columns(test_engine):
    """Confirms the column names come back correctly and in order —
    if this breaks, every table displayed in the UI would show wrong headers."""
    columns, rows = run_query("SELECT ID, NAME FROM EMPLOYEES", engine=test_engine)
    assert columns == ["ID", "NAME"]


def test_run_query_returns_correct_row_count(test_engine):
    """Confirms we get back exactly the rows that exist — not silently
    truncated, not duplicated."""
    columns, rows = run_query("SELECT * FROM EMPLOYEES", engine=test_engine)
    assert len(rows) == 2


def test_run_query_filters_correctly(test_engine):
    """Confirms a WHERE clause actually filters — this catches a class of
    bug where a query 'runs successfully' but silently ignores its own
    WHERE clause due to a connection/transaction issue."""
    columns, rows = run_query(
        "SELECT NAME FROM EMPLOYEES WHERE MANAGER_ID = 1", engine=test_engine
    )
    assert len(rows) == 1
    assert rows[0][0] == "Jane"


def test_run_query_raises_on_invalid_sql(test_engine):
    """A syntactically broken query (e.g. a typo'd column name) should
    raise a real exception the UI can catch and display, not fail silently
    or return an empty, misleadingly 'successful' result."""
    with pytest.raises(Exception):
        run_query("SELECT NONEXISTENT_COLUMN FROM EMPLOYEES", engine=test_engine)