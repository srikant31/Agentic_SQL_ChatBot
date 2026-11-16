"""Opt-in LangSmith settings, loaded before LangChain/graph imports."""
import os

SETTINGS = ("LANGSMITH_API_KEY", "LANGSMITH_TRACING", "LANGSMITH_PROJECT",
            "LANGSMITH_ENDPOINT", "LANGSMITH_HIDE_INPUTS", "LANGSMITH_HIDE_OUTPUTS",
            "GROQ_API_KEY", "GROQ_LLM_MODEL", "LLM_PROVIDER", "SQL_WORKFLOW",
            "PG_URL", "COLDCHAIN_DB_URL", "EVAL_DB_URL", "COLDCHAIN_ADMIN_USERS")


def configure_observability(secrets=None):
    if secrets is not None:
        for key in SETTINGS:
            if key in secrets:
                os.environ[key] = str(secrets[key])
    os.environ.setdefault("LANGSMITH_TRACING", "false")
    os.environ.setdefault("LANGSMITH_PROJECT", "sql-chatbot")
    os.environ.setdefault("LANGSMITH_HIDE_INPUTS", "true")
    os.environ.setdefault("LANGSMITH_HIDE_OUTPUTS", "true")


def load_streamlit_settings():
    import streamlit as st
    try:
        # Only copy an explicit allowlist; never print the secrets mapping.
        configure_observability(st.secrets)
    except FileNotFoundError:
        configure_observability()


def redacted_trace(name):
    from langsmith import traceable
    return traceable(name=name, process_inputs=lambda _: {}, process_outputs=lambda _: {})
