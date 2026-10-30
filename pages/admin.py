import streamlit as st
from theme import apply_theme
from app_auth import require_login
from database import ensure_demo, run_query, update_job_title, get_diagnostics

st.set_page_config(page_title="IT Admin · RBAC", page_icon="🔧", layout="wide")
apply_theme()
user = require_login("edit_title")
st.title("IT admin · Approved job-title changes")
st.caption("Only this role can save job-title changes. Salary changes, arbitrary SQL writes and deletion are not supported.")
try:
    ensure_demo()
    columns, rows = run_query("SELECT EMPLOYEE_ID, NAME, JOB_TITLE FROM EMPLOYEES ORDER BY EMPLOYEE_ID", user)
except Exception:
    st.error("Could not connect to the live demo data.")
    st.stop()
records = {row[0]: row for row in rows}
with st.form("prepare_title"):
    employee_id = st.selectbox("Employee", list(records), format_func=lambda key: f"{key}: {records[key][1]} — {records[key][2]}")
    title = st.text_input("New job title", max_chars=80)
    prepare = st.form_submit_button("Review change")
if prepare:
    st.session_state.pending_edit = {"owner": user.username, "id": employee_id, "title": title.strip()}
pending = st.session_state.get("pending_edit")
if pending and pending.get("owner") == user.username:
    st.warning(f"Change employee {pending['id']} job title to: {pending['title']}")
    confirmed = st.checkbox("I confirm this change to the fictional Aiven demo record.", key=f"confirm_{pending['id']}_{pending['title']}")
    if st.button("Save confirmed change", type="primary", disabled=not confirmed):
        try:
            update_job_title(user, pending["id"], pending["title"], confirmed=confirmed)
            st.session_state.pending_edit = None
            st.success("Saved to Aiven and recorded in the audit log.")
        except (ValueError, PermissionError) as exc:
            st.error(str(exc))
        except Exception:
            st.error("Could not save the change. No success has been recorded.")
st.subheader("Live database check and audit log")
if st.button("Check Aiven connection / refresh audit log"):
    try:
        status = get_diagnostics(user)
        st.success(f"Aiven connection: {status['connection']} · {status['demo_rows']} demo rows")
        st.caption(f"Checked at {status['checked_at_utc']}")
        st.dataframe(status["recent_changes"], hide_index=True)
    except Exception:
        st.error("Database health check failed.")
