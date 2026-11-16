"""Chat feedback around ColdChain's existing checked, read-only LangGraph."""
from copy import deepcopy
import time
import uuid
import streamlit as st
from langgraph.types import Command

from config import MAX_QUESTIONS_PER_SESSION
from diagnostics import log_failure
import feedback_store
import sql_generator
from observability import send_feedback
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

    owner = f"{user.username}:{role}"
    model = cfg.get("metadata", {}).get("model")

    def traced(name, request):
        """Per-call config: a fresh LangSmith run ID, tagged with this request and version."""
        run_id = uuid.uuid4()
        call_cfg = {**cfg, "run_id": run_id, "run_name": name,
                    "metadata": {**cfg.get("metadata", {}), "request_id": request["id"],
                                 "version": request["rewrites"]}}
        return call_cfg, str(run_id)

    def log(event, request, version=None, **fields):
        feedback_store.record(event, owner=owner, request_id=request["id"],
                              version=request["rewrites"] if version is None else version,
                              model=model, route="direct", **fields)

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
        started, run_id, extra_calls = time.perf_counter(), None, 0
        elapsed = lambda: int((time.perf_counter() - started) * 1000)
        try:
            with st.spinner("Preparing your updated ColdChain proposal..." if rewrite else "Preparing your ColdChain proposal..."):
                if rewrite:
                    extra_calls = 1  # the question-rewrite request runs outside the graph
                    request["current_question"] = sql_generator.rewrite_question(
                        request["original_question"], request["current_question"], request["modifications"])
                history = [{"role": message["role"], "content": message["text"][:4000]}
                           for prior in chat["requests"] for message in prior["messages"]][:-1]
                call_cfg, run_id = traced("coldchain_proposal", request)
                output = graph.invoke({"question": request["current_question"], "history": history[-20:],
                    "role": role, "attempts": 0, "model_calls": 0, "approved": False, "refused": False,
                    "needs_clarification": False, "rows": [], "columns": [], "sql": "", "explanation": "",
                    "error": "", "answer": "", "review_context": deepcopy(chat)}, call_cfg)
                calls = output.get("model_calls", 0) + extra_calls
                if output.get("__interrupt__"):
                    add_response(request, proposal={"sql": output["sql"], "explanation": output["explanation"],
                        "owner": user.username, "request_id": request["id"], "revision": request["rewrites"],
                        "trace_id": run_id})
                    log("proposal", request, status="proposed", model_calls=calls,
                        latency_ms=elapsed(), langsmith_run_id=run_id)
                else:
                    add_response(request, message=output.get("answer", "No query was proposed."),
                                 error=output.get("status") in {"error", "give_up", "provider_error", "source_error"})
                    save_closed_chat(output.get("status", "chat_error"))
                    log("proposal", request, status=output.get("status", "no_query"), model_calls=calls,
                        latency_ms=elapsed(), langsmith_run_id=run_id)
        except Exception as error:
            log_failure("coldchain_chat_proposal_failed", error)
            log("proposal", request, status="exception", model_calls=extra_calls or None,
                latency_ms=elapsed(), langsmith_run_id=run_id)
            add_response(request, message=error_message(error), error=True)
            save_closed_chat("chat_error")

    def run_proposal(request):
        status, run_id, rows_returned, calls = "complete", None, None, None
        started = time.perf_counter()
        try:
            proposal = latest_response(request)["proposal"]
            current = graph.get_state(cfg)
            if proposal["owner"] != user.username or proposal["request_id"] != request["id"] or proposal["revision"] != request["rewrites"] or current.values.get("question") != request["current_question"] or current.values.get("sql") != proposal["sql"] or not any(task.interrupts for task in current.tasks):
                raise PermissionError("This proposal is no longer active. Request a fresh proposal.")
            call_cfg, run_id = traced("coldchain_run", request)
            before = current.values.get("model_calls", 0)
            output = graph.invoke(Command(resume={"action": "approve"}), call_cfg)
            calls = max(output.get("model_calls", before) - before, 0)
            if output.get("status") != "complete":
                raise ValueError(output.get("answer", "The query could not be executed."))
            record_result(request, output["columns"], output["rows"])
            rows_returned = len(output["rows"])
        except Exception as error:
            status = "chat_error"
            log_failure("coldchain_chat_execution_failed", error)
            record_result(request, error=error_message(error))
        save_closed_chat(status)
        log("run", request, status=status, rows_returned=rows_returned, model_calls=calls,
            latency_ms=int((time.perf_counter() - started) * 1000), langsmith_run_id=run_id)

    def handle(event, request):
        if event["action"] in {"positive", "negative"}:
            feedback(request, event["action"], event["version"])
            proposal = latest_response(request).get("proposal") or {}
            log("vote", request, version=event["version"], vote=event["action"],
                langsmith_run_id=proposal.get("trace_id"))
            # The vote also lands on the LangSmith trace, so a disliked answer can be opened and debugged.
            send_feedback(proposal.get("trace_id"), "user_vote", 1 if event["action"] == "positive" else 0)
            if request["exhausted"]:
                log("limit_reached", request, version=event["version"])
        elif event["action"] == "rewrite" and remaining > 0:
            begin_rewrite(request, event["text"], event["version"])
            log("rewrite", request, hint=event["text"].strip())
            discard_pending()
            st.session_state.coldchain_questions_asked += 1
            generate(request, rewrite=True)
        elif event["action"] == "run" and executable(request):
            run_proposal(request)

    if notice := st.session_state.pop("coldchain_notice", None):
        st.warning(notice)
    event = render_conversation(chat, "coldchain_chat", run_label="Approve & run", can_generate=remaining > 0)
    if event:
        try:
            handle(event, active_request(chat))
        except ValueError as stale:
            # A click from an older tab or response: explain instead of showing a traceback.
            st.session_state.coldchain_notice = str(stale)
        st.rerun()

    if question := st.chat_input("Ask about ColdChain orders, shipments or customers", max_chars=4000, disabled=remaining <= 0):
        discard_pending()
        request = start_request(chat, question)
        st.session_state.coldchain_questions_asked += 1
        generate(request)
        st.rerun()
