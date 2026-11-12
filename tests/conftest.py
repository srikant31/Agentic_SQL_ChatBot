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
