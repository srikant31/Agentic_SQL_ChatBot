"""Opt-in LangSmith settings, loaded before LangChain/graph imports."""
import os

SETTINGS = ("LANGSMITH_API_KEY", "LANGSMITH_TRACING", "LANGSMITH_PROJECT",
            "LANGSMITH_ENDPOINT", "LANGSMITH_HIDE_INPUTS", "LANGSMITH_HIDE_OUTPUTS",
            "LANGSMITH_WORKSPACE_ID", "LANGSMITH_AGENT_ID", "LANGSMITH_AGENT_ENVIRONMENT",
            "GROQ_API_KEY", "GROQ_LLM_MODEL", "LLM_PROVIDER", "SQL_WORKFLOW",
            "PG_URL", "COLDCHAIN_DB_URL", "EVAL_DB_URL", "COLDCHAIN_ADMIN_USERS",
            "FEEDBACK_DB_URL", "FEEDBACK_STORE_TEXT")

# Statuses are application enums; anything else could be model text, so it is dropped from traces.
TRACE_STATUSES = {"proposal", "proposed", "complete", "error", "denied", "refuse", "clarify", "proceed",
                  "unsupported", "provider_error", "source_error", "give_up", "generated", "validated",
                  "invalid", "rejected", "chat_error", "chat_pending", "no_query"}


def configure_observability(secrets=None):
    if secrets is not None:
        for key in SETTINGS:
            if key in secrets:
                os.environ[key] = str(secrets[key])
    os.environ.setdefault("LANGSMITH_TRACING", "false")
    os.environ.setdefault("LANGSMITH_PROJECT", "sql-chatbot")
    # This project's LangSmith organisation lives in the APAC region; US/EU endpoints return 403.
    os.environ.setdefault("LANGSMITH_ENDPOINT", "https://apac.api.smith.langchain.com")
    os.environ.setdefault("LANGSMITH_AGENT_ID", "sql-chatbot")
    os.environ.setdefault("LANGSMITH_AGENT_ENVIRONMENT", "local")
    # Run callbacks in the foreground so traces are not lost when Streamlit reruns the script.
    os.environ.setdefault("LANGCHAIN_CALLBACKS_BACKGROUND", "false")
    os.environ.setdefault("LANGSMITH_HIDE_INPUTS", "true")
    os.environ.setdefault("LANGSMITH_HIDE_OUTPUTS", "true")


def load_streamlit_settings():
    import streamlit as st
    try:
        # Only copy an explicit allowlist; never print the secrets mapping.
        configure_observability(st.secrets)
    except FileNotFoundError:
        configure_observability()


def agent_metadata():
    return {"agent_id": os.getenv("LANGSMITH_AGENT_ID", "sql-chatbot"),
            "agent_environment": os.getenv("LANGSMITH_AGENT_ENVIRONMENT", "local")}


def tracing_enabled():
    return (os.getenv("LANGSMITH_TRACING", "false").strip().lower() == "true"
            and bool(os.getenv("LANGSMITH_API_KEY", "").strip()))


def _shape(value):
    """Describe a value without copying its text: lengths and types only."""
    if isinstance(value, str):
        return f"{len(value)} chars"
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return f"{type(value).__name__}[{len(value)}]"
    if isinstance(value, dict):
        return f"dict[{len(value)}]"
    return type(value).__name__


def sanitize_inputs(inputs):
    """Keep argument shape, never question/schema text or nested values."""
    if not isinstance(inputs, dict):
        return {"type": type(inputs).__name__}
    return {str(key): _shape(value) for key, value in inputs.items()}


def sanitize_outputs(output):
    if isinstance(output, dict):
        status = output.get("status")
        return {"keys": sorted(str(key) for key in output),
                "status": status if isinstance(status, str) and status in TRACE_STATUSES else None}
    return {"type": type(output).__name__}


# Names used by the earlier local tracing work.
_safe_in, _safe_out = sanitize_inputs, sanitize_outputs


def redacted_trace(name):
    from langsmith import traceable
    return traceable(name=name, metadata=agent_metadata(),
                     process_inputs=sanitize_inputs, process_outputs=sanitize_outputs)


_CLIENT = None


def send_feedback(run_id, key, score, comment=None):
    """Attach a user vote to a LangSmith run. Never raises: tracing must not break the app."""
    global _CLIENT
    if not run_id or not tracing_enabled():
        return False
    try:
        if _CLIENT is None:
            from langsmith import Client
            _CLIENT = Client()
        _CLIENT.create_feedback(run_id=run_id, key=key, score=score,
                                comment=(comment or None) and str(comment)[:200])
        return True
    except Exception as exc:  # network, auth or quota problems only lose the feedback
        from diagnostics import log_failure
        log_failure("langsmith_feedback_failed", exc)
        return False
