"""Chat review UI for the authorized employee proposal pipeline."""
import os
import streamlit as st

from config import MAX_QUESTIONS_PER_SESSION
from context_pipeline import prepare_proposal, execute_proposal
from diagnostics import log_failure
from query_errors import error_message
import sql_generator
from query_chat import (new_chat, start_request, add_response, active_request, latest_response,
                        feedback, begin_rewrite, executable, record_result, render_conversation)


def render_employee_chat(user):
    use_graph = st.sidebar.checkbox("Use controlled LangGraph workflow", value=os.getenv("SQL_WORKFLOW", "classic") == "graph")
    scope = f"employee:{user.role}:{user.department}"
    chat = st.session_state.get("employee_query_chat")
    if not chat or chat["owner"] != user.username or chat["scope"] != scope:
        chat = new_chat(user.username, scope)
        st.session_state.employee_query_chat = chat
        st.session_state.pending_query = None
        st.session_state.pop("sql_workflow", None)
    st.session_state.setdefault("questions_asked", 0)
    st.session_state.setdefault("pending_query", None)
    remaining = MAX_QUESTIONS_PER_SESSION - st.session_state.questions_asked
    st.subheader("Chat with your database")
    st.caption("See your question and what the query will retrieve. Use thumbs feedback to request up to three rewrites. Feedback never runs SQL.")
    st.caption(f"Questions remaining: {max(remaining, 0)} / {MAX_QUESTIONS_PER_SESSION}")

    def discard_pending():
        workflow = st.session_state.pop("sql_workflow", None)
        if workflow is not None and workflow.pending:
            workflow.resume("reject", user)
        st.session_state.pending_query = None

    def generate(request, *, rewrite=False):
        try:
            with st.spinner("Updating your question and preparing a read-only proposal..." if rewrite else "Preparing your read-only proposal..."):
                if rewrite:
                    request["current_question"] = sql_generator.rewrite_question(
                        request["original_question"], request["current_question"], request["modifications"])
                if use_graph:
                    from sql_graph import SQLWorkflow
                    # Human feedback owns the rewrite budget; do not nest automatic three-attempt loops.
                    workflow = SQLWorkflow(user, max_attempts=1)
                    st.session_state.sql_workflow = workflow
                    output = workflow.start(request["current_question"], user)
                    result = ({**output["proposal"], "workflow": "graph"} if output.get("__interrupt__")
                              else {"status": output["status"], "message": output.get("message", "No query was proposed.")})
                else:
                    result = prepare_proposal(request["current_question"], user)
                if result["status"] == "proposal":
                    result = {**result, "original_question": request["original_question"],
                              "request_id": request["id"], "revision": request["rewrites"]}
                    st.session_state.pending_query = result
                    add_response(request, result)
                else:
                    add_response(request, message=result["message"], error=result["status"] in {"denied", "error"})
        except Exception as error:
            log_failure("chat_proposal_failed", error)
            st.session_state.pending_query = None
            add_response(request, message=error_message(error), error=True)

    examples = ["Select a sample question...", "How many employees can I access?",
                "List all employees I can access with their department and job title.",
                "Who is Bob Brown's manager?", "Show average salary by department."]
    with st.expander("Try a sample question"):
        sample = st.selectbox("Pick a sample question:", examples)
        if st.button("Generate SQL", disabled=sample == examples[0] or remaining <= 0):
            discard_pending()
            request = start_request(chat, sample)
            st.session_state.questions_asked += 1
            generate(request)
            st.rerun()

    event = render_conversation(chat, "employee_chat", can_generate=remaining > 0)
    if event:
        request = active_request(chat)
        if event["action"] in {"positive", "negative"}:
            feedback(request, event["action"], event["version"])
            st.session_state.pending_query = (latest_response(request)["proposal"] if executable(request) else None)
        elif event["action"] == "rewrite" and remaining > 0:
            begin_rewrite(request, event["text"], event["version"])
            discard_pending()
            st.session_state.questions_asked += 1
            generate(request, rewrite=True)
        elif event["action"] == "run" and executable(request):
            proposal = st.session_state.pending_query
            try:
                if not proposal or proposal.get("owner") != user.username or proposal.get("request_id") != request["id"] or proposal.get("revision") != request["rewrites"]:
                    raise PermissionError("This proposal is no longer active. Request a fresh proposal.")
                if proposal.get("workflow") == "graph":
                    output = st.session_state.sql_workflow.resume("approve", user)
                    if output.get("status") != "complete":
                        raise ValueError(output.get("message", "The query could not be executed."))
                    columns, rows = output["columns"], output["rows"]
                else:
                    columns, rows = execute_proposal(proposal, user)
                record_result(request, columns, rows)
            except Exception as error:
                log_failure("chat_execution_failed", error)
                record_result(request, error=error_message(error))
            st.session_state.pending_query = None
            st.session_state.pop("sql_workflow", None)
        st.rerun()

    if question := st.chat_input("Ask a question about your permitted data", max_chars=4000, disabled=remaining <= 0):
        discard_pending()
        request = start_request(chat, question)
        st.session_state.questions_asked += 1
        generate(request)
        st.rerun()
