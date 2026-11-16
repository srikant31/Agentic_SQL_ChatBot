"""Admin-only Data Explorer for the ColdChain database. Read-only, through the same guarded path as the chat."""
import os

import streamlit as st

import config  # noqa: F401  (bootstrap env/secrets)
import coldchain_context
from app_auth import coldchain_role, require_login
from departments import ALL_TABLES, COLUMN_OWNERS, PLAIN_NAMES
from diagnostics import log_failure
from theme import apply_theme

st.set_page_config(page_title="ColdChain Data Explorer", page_icon="🔎", layout="wide")
apply_theme()
user = require_login(domain="coldchain")
# The page is only listed in the menu for admins; this check also stops anyone opening it directly.
if coldchain_role(user) != "admin":
    st.error("The Data Explorer is available to admins only.")
    st.stop()
st.title("ColdChain Data Explorer")
st.caption("Admin view of every ColdChain table. Read-only: the same validator, read-only transaction and "
           "100-row cap as the chat.")
if not (os.getenv("COLDCHAIN_DB_URL") or os.getenv("EVAL_DB_URL")):
    st.error("ColdChain is not configured. Add COLDCHAIN_DB_URL in Streamlit Secrets, then restart the app.")
    st.stop()


@st.cache_data(ttl=300, show_spinner=False)
def table_details():
    return {record["table"]: record for record in coldchain_context.get_schema_context(role="admin")["records"]}


try:
    details = table_details()
except Exception as exc:
    log_failure("explorer_schema_failed", exc)
    st.error("Could not read the ColdChain schema. Check the database connection.")
    st.stop()

tables = [t for t in ALL_TABLES if t in details]
table = st.selectbox("Table", tables, format_func=lambda t: f"{PLAIN_NAMES[t]} ({t})")
record = details[table]
if record.get("comment"):
    st.caption(record["comment"])
try:
    _, rows = coldchain_context.execute_readonly(f"SELECT COUNT(*) AS row_count FROM {table}", "admin")
    st.metric("Rows", rows[0][0])
except Exception as exc:
    log_failure("explorer_count_failed", exc)
    st.warning("Row count unavailable.")

st.markdown("**Columns**")
st.dataframe([{"Column": c["name"], "Type": c["type"], "Description": c.get("comment", ""),
               "Sensitive": "Yes, " + COLUMN_OWNERS[c["name"]] + " only" if c["name"] in {"email", "salary_inr"} else ""}
              for c in record["columns"]], hide_index=True)

limit = 100 if st.toggle("Show up to 100 rows", key=f"explorer_all_{table}") else 10
try:
    columns, rows = coldchain_context.execute_readonly(f"SELECT * FROM {table} LIMIT {limit}", "admin")
    st.markdown(f"**First {len(rows)} rows**")
    st.dataframe([dict(zip(columns, row)) for row in rows], hide_index=True)
except Exception as exc:
    log_failure("explorer_preview_failed", exc)
    st.error("Could not load rows for this table.")
