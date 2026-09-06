import streamlit as st
from sqlalchemy import create_engine, text
from langchain_community.utilities import SQLDatabase

from config import DB_URI


@st.cache_resource(show_spinner="Connecting to database...")
def get_db():
    """Used for schema introspection (table list, column info)."""
    return SQLDatabase.from_uri(DB_URI, engine_args={"pool_pre_ping": True, "pool_recycle": 280})


@st.cache_resource(show_spinner=False)
def get_engine():
    """Raw SQLAlchemy engine, used only to run already-validated queries."""
    return create_engine(DB_URI, pool_pre_ping=True, pool_recycle=280)


def run_query(sql: str, engine=None):
    """Execute a validated SQL query and return (columns, rows)."""
    if engine is None:
        engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        columns = list(result.keys())
        rows = result.fetchall()
    return columns, rows