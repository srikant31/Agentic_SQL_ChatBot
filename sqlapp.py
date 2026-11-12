import streamlit as st
from theme import apply_theme
from app_auth import require_login
from rbac import scope_description
from database import ensure_demo, get_schema, run_query
from context_pipeline import prepare_proposal, execute_proposal
from safety import SchemaValidationError, UnsafeQueryError
from semantic_validation import SemanticValidationError
from sql_generator import LLMProviderError
from config import MAX_QUESTIONS_PER_SESSION
from diagnostics import log_failure


def show_query_error(exc):
    if isinstance(exc, (SemanticValidationError, SchemaValidationError, UnsafeQueryError, PermissionError, ValueError)):
        log_failure("query_rejected", exc)
        st.error(f"Denied or invalid query: {exc}")
    else:
        log_failure("query_failed", exc)
        st.error("The query could not be completed. Check the connection and try a narrower question.")

st.set_page_config(page_title="SQL Agent · RBAC Demo", page_icon="🗄️", layout="wide")
apply_theme()
user = require_login()
st.title("SQL Agent · RBAC Demo")
st.info(scope_description(user))
st.caption("Fictional demo records on the existing Aiven service. SQL queries read a fresh, role-filtered snapshot. Only IT admin can edit job titles through the approval screen.")
try:
    ensure_demo()
except Exception as exc:
    log_failure("demo_setup_failed", exc)
    st.error("Could not prepare the Aiven demo data. Check the database service and credentials.")
    st.stop()

with st.sidebar:
    st.caption("Schema intelligence · Backend-enforced permissions")
    try:
        st.code(get_schema(user), language="sql")
    except Exception as exc:
        log_failure("schema_load_failed", exc)
        st.error("The approved schema could not be loaded. Check the database connection or source mapping.")
        st.stop()
if st.button("Show my permitted data"):
    try:
        columns, rows = run_query("SELECT * FROM EMPLOYEES ORDER BY EMPLOYEE_ID", user)
        st.dataframe([dict(zip(columns, row)) for row in rows], hide_index=True)
        st.success(f"{len(rows)} authorized rows. Only your permitted columns are returned.")
    except Exception as exc:
        log_failure("permitted_data_failed", exc)
        st.error("The live database could not be queried.")

with st.expander("Demonstrate a denied query"):
    st.caption("Employee/admin: try SELECT SALARY FROM EMPLOYEES. HR: try UPDATE EMPLOYEES SET JOB_TITLE='Manager'. The same backend checks protect AI-generated queries.")
    probe = st.text_area("SQL permission check", value="SELECT SALARY FROM EMPLOYEES")
    if st.button("Check query permissions"):
        try:
            columns, rows = run_query(probe, user)
            st.dataframe([dict(zip(columns, row)) for row in rows], hide_index=True)
            st.success("Allowed for your role.")
        except Exception as exc:
            show_query_error(exc)

st.subheader("Ask the SQL assistant")
st.caption("The AI proposes a read-only query. Review it before running it.")
examples = ["Select a sample question...", "How many employees can I access?", "List all employees I can access with their department and job title.", "Who is Bob Brown's manager?", "Show average salary by department."]
sample = st.selectbox("Pick a sample question:", examples)
custom = st.text_area("...or type your own question:")
question = custom.strip() or (sample if sample != examples[0] else "")
st.session_state.setdefault("questions_asked", 0)
st.session_state.setdefault("pending_query", None)
remaining = MAX_QUESTIONS_PER_SESSION - st.session_state.questions_asked
st.caption(f"Questions remaining: {max(remaining, 0)} / {MAX_QUESTIONS_PER_SESSION}")
if st.button("Generate SQL", type="primary", disabled=not question or remaining <= 0):
    st.session_state.questions_asked += 1
    st.session_state.pending_query = None
    try:
        with st.spinner("Writing SQL for your permitted schema..."):
            result = prepare_proposal(question, user)
            if result["status"] == "proposal":
                st.session_state.pending_query = result
            elif result["status"] == "denied":
                st.error(result["message"])
            else:
                st.info(result["message"])
    except (SemanticValidationError, SchemaValidationError, UnsafeQueryError) as exc:
        log_failure("proposal_validation_failed", exc)
        st.error(f"Query validation failed: {exc}")
    except LLMProviderError as exc:
        log_failure("llm_provider_failed", exc)
        st.error(str(exc))
    except Exception as exc:
        log_failure("proposal_failed", exc)
        st.error("Could not generate an allowed query. Try a question about the columns in your permitted schema.")

pending = st.session_state.pending_query
if pending:
    if pending.get("owner") != user.username or pending.get("status") != "proposal" or not pending.get("context_version"):
        st.session_state.pending_query = None
        st.rerun()
    st.subheader("Proposed query")
    st.progress(pending.get("confidence", 0.5), text=f"Model confidence (not a correctness guarantee): {pending.get('confidence', 0.5):.0%}")
    st.code(pending["sql"], language="sql")
    st.caption(pending["explanation"])
    with st.expander("Context and validation"):
        st.write("Checks passed:", pending["validation"]["checks"])
        st.write("Business definitions:", pending["context"]["rules"])
        st.write("Reviewed examples:", pending["context"]["examples"] or "None needed")
        for warning in (*pending["validation"]["warnings"], *pending["context"]["warnings"]):
            st.caption(warning)
    if st.button("Run this query", type="primary"):
        try:
            columns, rows = execute_proposal(pending, user)
            st.subheader("Results")
            st.dataframe([dict(zip(columns, row)) for row in rows], hide_index=True)
            st.caption(f"{len(rows)} result rows within your authorized scope.")
        except Exception as exc:
            show_query_error(exc)
        st.session_state.pending_query = None
