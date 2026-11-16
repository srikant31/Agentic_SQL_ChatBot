import pytest
import os
os.environ["LANGSMITH_TRACING"] = "false"
from sqlalchemy import create_engine

from database import initialize_demo
from rbac import USERS
from schema_context import get_catalog


@pytest.fixture(autouse=True)
def no_cloud_traces(monkeypatch):
    import observability
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setattr(observability, "load_streamlit_settings", lambda: None)


@pytest.fixture
def demo_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/intelligence.db")
    initialize_demo(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def hr_catalog(demo_engine):
    return get_catalog(USERS["hr"], demo_engine)


@pytest.fixture(autouse=True)
def isolated_feedback_store(tmp_path, monkeypatch):
    """Every test writes feedback events to its own throwaway SQLite file, never to data/."""
    import feedback_store
    monkeypatch.setenv("FEEDBACK_DB_URL", f"sqlite:///{tmp_path}/feedback.sqlite")
    monkeypatch.delenv("FEEDBACK_STORE_TEXT", raising=False)
    feedback_store.reset_store()
    yield
    feedback_store.reset_store()
