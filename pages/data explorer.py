import streamlit as st
from theme import apply_theme
from app_auth import require_login
from database import ensure_demo, run_query
from diagnostics import log_failure

st.set_page_config(page_title="RBAC Data Explorer", page_icon="📊", layout="wide")
apply_theme()
user = require_login("explorer")
st.title("Data Explorer")
st.caption("HR sees salaries; IT admin sees the directory without salaries. Employee accounts cannot open this page.")
try:
    ensure_demo()
    columns, rows = run_query("SELECT * FROM EMPLOYEES ORDER BY EMPLOYEE_ID", user)
    st.dataframe([dict(zip(columns, row)) for row in rows], hide_index=True)
    st.caption(f"{len(rows)} authorized records.")
except Exception as exc:
    log_failure("explorer_load_failed", exc)
    st.error("Could not read the live demo data.")
