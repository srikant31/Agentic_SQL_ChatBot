"""Primary ColdChain analytics screen, with review before every execution."""
import os
import uuid
import streamlit as st
import config  # bootstrap env/secrets before model/graph imports
from app_auth import require_login, coldchain_role
from checkpointing import get_checkpointer, thread_config
from coldchain_context import get_coldchain_engine
from coldchain_graph import build_graph
from sql_generator import provider_settings
from diagnostics import log_failure
from theme import apply_theme


st.set_page_config(page_title="ColdChain analytics", page_icon="📦", layout="wide")
apply_theme()
user = require_login(domain="coldchain")
st.title("ColdChain analytics")
st.caption("Main database: ColdChain · Aiven MySQL · read-only queries")
st.caption("Fictional ColdChain evaluation data. Relative dates use 2026-06-30.")
if not (os.getenv("COLDCHAIN_DB_URL") or os.getenv("EVAL_DB_URL")):
    st.error("ColdChain is not configured. Add the read-only COLDCHAIN_DB_URL and AIVEN_CA_CERT in Streamlit Secrets, then restart the app.")
    st.stop()

# Existing demo IT-admin does not automatically gain salary/PII permissions in a new domain.
role = coldchain_role(user)
with st.expander("What can I ask?"):
    from departments import EXAMPLES, scope_text
    st.write(scope_text(role))
    st.markdown("For example:\n" + "\n".join(f"- {example}" for example in EXAMPLES[role]))
try:
    resource = get_checkpointer()
    if not resource.persistent:
        st.warning("In-memory approvals will not survive a restart or app sleep.")
    engine = get_coldchain_engine()
    # max_attempts=2: one automatic repair when validation or the database rejects the SQL. It never
    # counts against the user's three rewrites, and repaired SQL still needs a fresh approval.
    graph = build_graph(resource.saver, engine=engine, review_all=True, max_attempts=2, explain_sql=True)
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

from coldchain_chat_ui import render_coldchain_chat

if role == "admin":
    import feedback_store
    with st.expander("System performance (admins only)"):
        store = feedback_store.get_store()
        if store is None:
            st.info("Feedback storage is unavailable. Check FEEDBACK_DB_URL or PG_URL.")
        else:
            try:
                st.json(store.summary())
                st.caption("Acceptance shows what users clicked, not whether answers were correct. "
                           "Correctness comes from the golden-set evaluation.")
            except Exception as exc:
                log_failure("feedback_summary_failed", exc)
                st.info("Feedback summary could not be loaded.")
    if store is not None:
        from conversation_log import render_conversation_log
        render_conversation_log(store)

render_coldchain_chat(graph, cfg, user, role, snapshot)
