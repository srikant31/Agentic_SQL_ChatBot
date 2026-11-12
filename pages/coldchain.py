"""Opt-in ColdChain analytics; the existing employee app remains independent."""
import os
import uuid
import streamlit as st
import config  # bootstrap env/secrets before model/graph imports
from app_auth import require_login
from checkpointing import get_checkpointer, thread_config
from coldchain_context import get_coldchain_engine
from sql_graph import build_graph
from sql_generator import provider_settings
from langgraph.types import Command
from diagnostics import log_failure


st.set_page_config(page_title="ColdChain analytics", page_icon="📦", layout="wide")
user = require_login()
st.title("ColdChain analytics")
st.caption("Fictional ColdChain evaluation data. Relative dates use 2026-06-30.")
if not (os.getenv("COLDCHAIN_DB_URL") or os.getenv("EVAL_DB_URL")):
    st.info("ColdChain is not configured. Add a read-only COLDCHAIN_DB_URL in Streamlit Secrets. The employee demo remains available.")
    st.stop()

# Existing demo IT-admin does not automatically gain salary/PII permissions in a new domain.
admins = {name.strip() for name in os.getenv("COLDCHAIN_ADMIN_USERS", "").split(",") if name.strip()}
role = "admin" if user.username in admins else "viewer"
try:
    resource = get_checkpointer()
    if not resource.persistent:
        st.warning("In-memory approvals will not survive a restart or app sleep.")
    engine = get_coldchain_engine()
    graph = build_graph(resource.saver, engine=engine)
    try:
        tid = str(uuid.UUID(st.query_params.get("tid", "")))
    except (ValueError, TypeError):
        tid = str(uuid.uuid4())
        st.query_params["tid"] = tid
    cfg = thread_config(user, tid, role, provider_settings()[4])
    snapshot = graph.get_state(cfg)
except Exception as exc:
    log_failure("coldchain_setup_failed", exc)
    st.error("ColdChain storage/source could not be initialized. Check the configured URLs and permissions.")
    st.stop()

pending = [item.value for task in snapshot.tasks for item in task.interrupts]
if pending:
    edited = st.text_area("Review SQL", pending[0]["sql"], key=f"coldchain_review:{tid}:{snapshot.values.get('attempts', 0)}")
    if st.button("Approve & run"):
        graph.invoke(Command(resume={"action": "approve", "sql": edited}), cfg)
        st.rerun()
    if st.button("Reject"):
        graph.invoke(Command(resume={"action": "reject"}), cfg)
        st.rerun()
    st.stop()

state = snapshot.values
if state.get("answer"):
    st.write(state["answer"])
if state.get("rows"):
    st.dataframe([dict(zip(state["columns"], row)) for row in state["rows"]], hide_index=True)
if question := st.chat_input("Ask about ColdChain orders, shipments or customers"):
    previous = list(state.get("history", []))
    if state.get("question"):
        previous.extend([{"role": "user", "content": state["question"]},
                         {"role": "assistant", "content": state.get("answer", "")}])
    # Reset all decision/result fields for each new turn; never carry old approval.
    graph.invoke({"question": question, "history": previous[-20:], "role": role,
                  "attempts": 0, "approved": False, "refused": False,
                  "needs_clarification": False, "rows": [], "sql": "", "error": "", "answer": ""}, cfg)
    st.rerun()
