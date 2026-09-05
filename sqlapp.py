"""
SQL Agent Streamlit App
------------------------
Two-step flow: the AI proposes a SQL query from a plain-English question,
you review and approve it, and only then does it actually run against
the database.
"""

import streamlit as st

from config import SAMPLE_QUESTIONS, MAX_QUESTIONS_PER_SESSION
from theme import apply_theme
from database import get_db, run_query
from sql_generator import generate_sql
from safety import validate_readonly_sql, UnsafeQueryError

st.set_page_config(page_title="SQL Agent — Employees DB", page_icon="🗄️", layout="wide")
apply_theme()

st.title("SQL Agent — Employees Database")
st.caption("Ask a question. The AI proposes a SQL query — you approve it before anything runs.")

with st.sidebar:
    st.header("Database Info")
    try:
        db = get_db()
        st.success("Connected to MySQL ✅")
        st.write("**Tables:**")
        for t in db.get_usable_table_names():
            st.write(f"- {t}")
    except Exception as e:
        st.error(f"Connection failed: {e}")
        st.stop()

    st.divider()
    st.caption("Set MYSQL_USER, MYSQL_PASSWORD, MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE, and GOOGLE_API_KEY in your .env file.")

    if "questions_asked" not in st.session_state:
        st.session_state.questions_asked = 0
    remaining = MAX_QUESTIONS_PER_SESSION - st.session_state.questions_asked
    st.divider()
    st.caption(f"Questions remaining this session: {max(remaining, 0)} / {MAX_QUESTIONS_PER_SESSION}")

if "pending_query" not in st.session_state:
    st.session_state.pending_query = None

selected_sample = st.selectbox("Pick a sample question:", SAMPLE_QUESTIONS)

custom_question = st.text_area(
    "...or type your own question:",
    placeholder="e.g. Which employees report to Alice Johnson?",
    height=80,
)

question = custom_question.strip() if custom_question.strip() else (
    selected_sample if selected_sample != SAMPLE_QUESTIONS[0] else ""
)

session_limit_reached = st.session_state.get("questions_asked", 0) >= MAX_QUESTIONS_PER_SESSION

if session_limit_reached:
    st.warning("You've reached the question limit for this session. Refresh the page to reset.")

generate_clicked = st.button("Generate SQL", type="primary", disabled=(question == "" or session_limit_reached))

# ============================================================
# STAGE 1: GENERATE — no execution happens here
# ============================================================

if generate_clicked and question:
    st.session_state.questions_asked += 1
    st.session_state.pending_query = None

    with st.spinner("Writing SQL..."):
        try:
            schema_text = db.get_table_info()
            result = generate_sql(question, schema_text)
            validate_readonly_sql(result["sql"])
            st.session_state.pending_query = result
        except UnsafeQueryError as e:
            st.error(f"Generated query was rejected by the safety check: {e}")
        except Exception as e:
            st.error(f"Something went wrong: {e}")

# ============================================================
# STAGE 2: SHOW THE PROPOSED QUERY — wait for explicit confirmation
# ============================================================

if st.session_state.pending_query:
    st.subheader("Proposed query")
    st.code(st.session_state.pending_query["sql"], language="sql")
    st.caption(st.session_state.pending_query["explanation"])

    if st.button("Run this query", type="primary"):
        with st.spinner("Running query..."):
            try:
                columns, rows = run_query(st.session_state.pending_query["sql"])
                st.subheader("Results")
                st.dataframe([dict(zip(columns, row)) for row in rows])
            except Exception as e:
                st.error(f"Query failed: {e}")
        st.session_state.pending_query = None