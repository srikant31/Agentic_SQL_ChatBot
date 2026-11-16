"""Chat feedback around ColdChain's existing checked, read-only LangGraph."""
from copy import deepcopy
import streamlit as st
from langgraph.types import Command

from config import MAX_QUESTIONS_PER_SESSION
from diagnostics import log_failure
import sql_generator
from query_errors import error_message
from query_chat import (new_chat, start_request, add_response, active_request, latest_response,
                        feedback, begin_rewrite, executable, record_result, render_conversation)


def render_coldchain_chat(graph, cfg, user, role, snapshot):
    scope = f"coldchain:{role}:{cfg['configurable']['thread_id']}"
    chat = st.session_state.get("coldchain_query_chat")
    if not chat or chat["owner"] != user.username or chat["scope"] != scope:
        saved = snapshot.values.get("review_context", {})
        chat = (deepcopy(saved) if saved.get("owner") == user.username and saved.get("scope") == scope
                else new_chat(user.username, scope))
        st.session_state.coldchain_query_chat = chat
        if not chat["requests"] and snapshot.values.get("question"):
            start_request(chat, snapshot.values["question"])
        request = active_request(chat)
        previous = latest_response(request) if request else None
        if request and (not previous or previous["version"] != request["rewrites"]):
            state = snapshot.values
            pending = any(task.interrupts for task in snapshot.tasks)
            if pending and state.get("sql"):
                add_response(request, proposal={"sql": state["sql"],
                    "explanation": state.get("explanation") or "This saved query reads the displayed columns from your authorized ColdChain data. Review the SQL before running it.",
                    "owner": user.username, "request_id": request["id"], "revision": request["rewrites"]})
            else:
                add_response(request, message=state.get("answer") or "The previous request was interrupted. No new query was run; you can describe your modifications or start a new question.")
                if state.get("status") == "complete":
                    record_result(request, state.get("columns", []), state.get("rows", []))

    st.session_state.setdefault("coldchain_questions_asked", 0)
    remaining = MAX_QUESTIONS_PER_SESSION - st.session_state.coldchain_questions_asked
    st.caption("Review your question, explanation and SQL. Thumbs feedback lets you request up to three rewrites; it never runs SQL.")
    st.caption(f"Questions remaining: {max(remaining, 0)} / {MAX_QUESTIONS_PER_SESSION}")

    def discard_pending():
        current = graph.get_state(cfg)
        if any(task.interrupts for task in current.tasks):
            graph.invoke(Command(resume={"action": "reject"}), cfg)

    def save_closed_chat(status="chat_pending"):
        values = {"review_context": deepcopy(chat), "status": status, "approved": False}
        if status == "chat_pending":
            values.update(question=active_request(chat)["current_question"], sql="", explanation="",
                          rows=[], columns=[], answer="", error="")
        graph.update_state(cfg, values, as_node="chat_checkpoint")

    def generate(request, *, rewrite=False):
        # Persist the reserved rewrite before any provider request; refresh cannot reset its count.
        save_closed_chat()
        try:
            with st.spinner("Preparing your updated ColdChain proposal..." if rewrite else "Preparing your ColdChain proposal..."):
                if rewrite:
                    request["current_question"] = sql_generator.rewrite_question(
                        request["original_question"], request["current_question"], request["modifications"])
                history = [{"role": message["role"], "content": message["text"][:4000]}
                           for prior in chat["requests"] for message in prior["messages"]][:-1]
                output = graph.invoke({"question": request["current_question"], "history": history[-20:],
                    "role": role, "attempts": 0, "approved": False, "refused": False,
                    "needs_clarification": False, "rows": [], "columns": [], "sql": "", "explanation": "",
                    "error": "", "answer": "", "review_context": deepcopy(chat)}, cfg)
                if output.get("__interrupt__"):
                    add_response(request, proposal={"sql": output["sql"], "explanation": output["explanation"],
                        "owner": user.username, "request_id": request["id"], "revision": request["rewrites"]})
                else:
                    add_response(request, message=output.get("answer", "No query was proposed."),
                                 error=output.get("status") in {"error", "give_up", "provider_error", "source_error"})
                    save_closed_chat(output.get("status", "chat_error"))
        except Exception as error:
            log_failure("coldchain_chat_proposal_failed", error)
            add_response(request, message=error_message(error), error=True)
            save_closed_chat("chat_error")

    event = render_conversation(chat, "coldchain_chat", run_label="Approve & run", can_generate=remaining > 0)
    if event:
        request = active_request(chat)
        if event["action"] in {"positive", "negative"}:
            feedback(request, event["action"], event["version"])
        elif event["action"] == "rewrite" and remaining > 0:
            begin_rewrite(request, event["text"], event["version"])
            discard_pending()
            st.session_state.coldchain_questions_asked += 1
            generate(request, rewrite=True)
        elif event["action"] == "run" and executable(request):
            execution_status = "complete"
            try:
                proposal = latest_response(request)["proposal"]
                current = graph.get_state(cfg)
                if proposal["owner"] != user.username or proposal["request_id"] != request["id"] or proposal["revision"] != request["rewrites"] or current.values.get("question") != request["current_question"] or current.values.get("sql") != proposal["sql"] or not any(task.interrupts for task in current.tasks):
                    raise PermissionError("This proposal is no longer active. Request a fresh proposal.")
                output = graph.invoke(Command(resume={"action": "approve"}), cfg)
                if output.get("status") != "complete":
                    raise ValueError(output.get("answer", "The query could not be executed."))
                record_result(request, output["columns"], output["rows"])
            except Exception as error:
                execution_status = "chat_error"
                log_failure("coldchain_chat_execution_failed", error)
                record_result(request, error=error_message(error))
            save_closed_chat(execution_status)
        st.rerun()

    if question := st.chat_input("Ask about ColdChain orders, shipments or customers", max_chars=4000, disabled=remaining <= 0):
        discard_pending()
        request = start_request(chat, question)
        st.session_state.coldchain_questions_asked += 1
        generate(request)
        st.rerun()
