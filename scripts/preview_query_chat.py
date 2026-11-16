"""Local UI preview: actual employee screen, fictional SQLite, no model/network calls.

Run: python -m streamlit run scripts/preview_query_chat.py --server.address 127.0.0.1
"""
import os
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
import observability
observability.load_streamlit_settings = lambda: observability.configure_observability()
import config
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
import app_auth
import database
import sql_generator
import theme
from rbac import USERS


@st.cache_resource
def fixture():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    database.initialize_demo(engine)
    return engine


database.get_engine = fixture
database.get_read_engine = fixture
database.ensure_demo = lambda: True
app_auth.require_login = lambda *args, **kwargs: USERS["hr"]


def example_response(question, schema):
    filtered = "engineering" in question.lower()
    return {"sql": "SELECT DEPARTMENT, COUNT(*) AS employee_count FROM EMPLOYEES"
                   + (" WHERE DEPARTMENT = 'Engineering'" if filtered else "") + " GROUP BY DEPARTMENT",
            "explanation": "I will read the employee records available to your role"
                   + (", keep only the Engineering department" if filtered else "")
                   + ", and count employees in each department. The output will contain DEPARTMENT and employee_count, with one row per department. No query has run yet.",
            "confidence": .9}


def example_rewrite(original, current, modifications):
    engineering = "engineering" in " ".join(modifications).lower()
    return "Count employees by department" + (" in Engineering" if engineering else "")


sql_generator.generate_sql = example_response
sql_generator.rewrite_question = example_rewrite
original_theme = theme.apply_theme


def preview_theme():
    original_theme()
    st.info("Local preview · fictional SQLite records and demonstration model responses. No Aiven or LLM calls.")
    st.caption("Try: Count employees by department. Then choose Needs changes and request: Only Engineering.")


theme.apply_theme = preview_theme
runpy.run_path(str(ROOT / "tests/fixtures/employee_app.py"), run_name="__main__")
