"""Chat feedback around ColdChain's existing checked, read-only LangGraph."""
from copy import deepcopy
import time
import uuid
import streamlit as st
from langgraph.types import Command

from config import MAX_QUESTIONS_PER_SESSION
from diagnostics import log_failure
import feedback_store
import query_insight
import prompt_log
import sql_generator
from observability import send_feedback
from query_errors import error_message
from query_chat import (new_chat, start_request, add_response, active_request, latest_response,
                        feedback, result_feedback, begin_rewrite, executable, record_result, render_conversation)

# Real graph steps, shown while the user waits. Each label appears only when that step actually starts.
STAGES = {"classify": "Understanding your question...", "generate": "Writing the SQL query...",
          "validate": "Checking the query against the schema and your permissions...",
          "approve": "Getting the query ready for your review...", "execute": "Running the read-only query...",
          "summarize": "Summarising the result...", "give_up": "Stopping: no safe query could be produced..."}
REPAIRED_NOTICE = ("The first version of this query failed in the database, so it was corrected automatically. "
                   "Review the corrected SQL below and approve it to run.")


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
                    "owner": user.username, "request_id": request["id"], "revision": request["rewrites"],
                    "insight": query_insight.analyze(request["current_question"], state["sql"])})
            else:
                add_response(request, message=state.get("answer") or "The previous request was interrupted. No new query was run; you can describe your modifications or start a new question.")
                if state.get("status") == "complete":
                    record_result(request, state.get("columns", []), state.get("rows", []))

    st.session_state.setdefault("coldchain_questions_asked", 0)
    remaining = MAX_QUESTIONS_PER_SESSION - st.session_state.coldchain_questions_asked
    st.caption("Review your question, explanation and SQL. Rate each proposal Positive or Negative: Negative lets you "
               "request up to three rewrites. Rating never runs SQL.")
    st.caption(f"Questions remaining: {max(remaining, 0)} / {MAX_QUESTIONS_PER_SESSION}")

    model = cfg.get("metadata", {}).get("model")
    who = {"username": user.username, "display_name": user.display_name or user.username, "role": role}

    def traced(name, request):
        """Per-call config: a fresh LangSmith run ID. The root keeps the name coldchain_turn;
        `step` says whether this turn was a proposal or an approved run."""
        run_id = uuid.uuid4()
        call_cfg = {**cfg, "run_id": run_id,
                    "metadata": {**cfg.get("metadata", {}), "step": name, "request_id": request["id"],
                                 "version": request["rewrites"]}}
        return call_cfg, str(run_id)

    def insight_detail(insight, old_sql=None, new_sql=None):
        """Compact record for the log: rules shown, assumptions, and what changed from the previous SQL."""
        detail = {}
        if insight:
            detail.update(rules=[{"term": r["term"], "score": r["score"]} for r in insight["rules"]],
                          assumptions=insight["assumptions"])
        if old_sql and new_sql:
            comparison = query_insight.compare(old_sql, new_sql)
            if comparison is not None:
                detail["changes"] = comparison["changes"]
        return detail or None

    def last_proposal_sql(request):
        return next((m["proposal"]["sql"] for m in reversed(request["messages"]) if m.get("proposal")), None)

    def log(event, request, version=None, **fields):
        feedback_store.record(event, **who, request_id=request["id"],
                              version=request["rewrites"] if version is None else version,
                              model=model, route="direct", **fields)

    def prompts_for(request, run_id):
        """Tags every model call made inside this block with who asked, the question and the version."""
        return prompt_log.bind(username=user.username, role=role, request_id=request["id"],
                               version=request["rewrites"], model=model, run_id=run_id)

    def run_graph(graph_input, call_cfg, progress):
        """Stream the graph so each real step can update the progress message, then read the final state."""
        for chunk in graph.stream(graph_input, call_cfg, stream_mode="updates"):
            for node in chunk:
                if node in STAGES:
                    progress.update(label=STAGES[node])
        snapshot = graph.get_state(cfg)
        output = dict(snapshot.values)
        if any(task.interrupts for task in snapshot.tasks):
            output["__interrupt__"] = True
        return output

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
        started, extra_calls = time.perf_counter(), 0
        elapsed = lambda: int((time.perf_counter() - started) * 1000)
        call_cfg, run_id = traced("proposal", request)
        try:
            with st.status("Preparing your ColdChain proposal...") as progress, prompts_for(request, run_id):
                if rewrite:
                    progress.update(label="Applying your changes to the question...")
                    extra_calls = 1  # the question-rewrite request runs outside the graph
                    request["current_question"] = sql_generator.rewrite_question(
                        request["original_question"], request["current_question"], request["modifications"])
                history = [{"role": message["role"], "content": message["text"][:4000]}
                           for prior in chat["requests"] for message in prior["messages"]][:-1]
                output = run_graph({"question": request["current_question"], "history": history[-20:],
                    "role": role, "attempts": 0, "model_calls": 0, "approved": False, "refused": False,
                    "needs_clarification": False, "rows": [], "columns": [], "sql": "", "explanation": "",
                    "error": "", "answer": "", "review_context": deepcopy(chat)}, call_cfg, progress)
                progress.update(label="Proposal ready for your review" if output.get("__interrupt__") else "Finished",
                              state="complete")
                calls = output.get("model_calls", 0) + extra_calls
                if output.get("__interrupt__"):
                    earlier_sql = last_proposal_sql(request)
                    insight = query_insight.analyze(request["current_question"], output["sql"])
                    add_response(request, proposal={"sql": output["sql"], "explanation": output["explanation"],
                        "owner": user.username, "request_id": request["id"], "revision": request["rewrites"],
                        "trace_id": run_id, "insight": insight})
                    log("proposal", request, status="proposed", model_calls=calls, latency_ms=elapsed(),
                        langsmith_run_id=run_id, question=request["current_question"],
                        sql=output["sql"], explanation=output["explanation"],
                        detail=insight_detail(insight, earlier_sql, output["sql"]))
                else:
                    add_response(request, message=output.get("answer", "No query was proposed."),
                                 error=output.get("status") in {"error", "give_up", "provider_error", "source_error"})
                    save_closed_chat(output.get("status", "chat_error"))
                    log("proposal", request, status=output.get("status", "no_query"), model_calls=calls,
                        latency_ms=elapsed(), langsmith_run_id=run_id, question=request["current_question"],
                        message=output.get("answer"))
        except Exception as error:
            log_failure("coldchain_chat_proposal_failed", error)
            log("proposal", request, status="exception", model_calls=extra_calls or None,
                latency_ms=elapsed(), langsmith_run_id=run_id, question=request["current_question"],
                message=error_message(error))
            add_response(request, message=error_message(error), error=True)
            save_closed_chat("chat_error")

    def run_proposal(request):
        status, run_id, rows_returned, calls, answer = "complete", None, None, None, None
        started = time.perf_counter()
        try:
            proposal = latest_response(request)["proposal"]
            current = graph.get_state(cfg)
            if proposal["owner"] != user.username or proposal["request_id"] != request["id"] or proposal["revision"] != request["rewrites"] or current.values.get("question") != request["current_question"] or current.values.get("sql") != proposal["sql"] or not any(task.interrupts for task in current.tasks):
                raise PermissionError("This proposal is no longer active. Request a fresh proposal.")
            call_cfg, run_id = traced("run", request)
            before = current.values.get("model_calls", 0)
            with st.status("Running your approved query...") as progress, prompts_for(request, run_id):
                output = run_graph(Command(resume={"action": "approve"}), call_cfg, progress)
                progress.update(label="Done", state="complete")
            answer = output.get("answer")
            if output.get("__interrupt__"):
                # The database rejected the SQL and one automatic repair produced new SQL. Changed SQL always
                # needs a fresh approval, so show it as the same version (not a user rewrite) and stop here.
                entry = latest_response(request)
                failed_sql = entry["proposal"]["sql"]
                entry["proposal"] = {**entry["proposal"], "sql": output["sql"], "explanation": output["explanation"],
                                     "trace_id": run_id, "repaired": True, "repaired_from": failed_sql,
                                     "insight": query_insight.analyze(request["current_question"], output["sql"])}
                entry["text"], entry["notice"], entry["vote"] = output["explanation"], REPAIRED_NOTICE, None
                # No checkpoint write here: updating state while paused would re-queue the approval step and
                # drop the pending interrupt. After a refresh, the restore path rebuilds this proposal from
                # the graph's pending SQL.
                log("proposal", request, status="repaired", model_calls=max(output.get("model_calls", before) - before, 0),
                    latency_ms=int((time.perf_counter() - started) * 1000), langsmith_run_id=run_id,
                    question=request["current_question"], sql=output["sql"], explanation=output["explanation"],
                    detail=insight_detail(entry["proposal"]["insight"], failed_sql, output["sql"]))
                return
            calls = max(output.get("model_calls", before) - before, 0)
            if output.get("status") != "complete":
                raise ValueError(output.get("answer", "The query could not be executed."))
            record_result(request, output["columns"], output["rows"])
            latest_response(request)["run_trace_id"] = run_id
            rows_returned = len(output["rows"])
        except Exception as error:
            status = "chat_error"
            log_failure("coldchain_chat_execution_failed", error)
            answer = error_message(error)
            record_result(request, error=answer)
        save_closed_chat(status)
        log("run", request, status=status, rows_returned=rows_returned, model_calls=calls,
            latency_ms=int((time.perf_counter() - started) * 1000), langsmith_run_id=run_id,
            sql=(latest_response(request).get("proposal") or {}).get("sql"), message=answer)

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
            log("rewrite", request, hint=event["text"].strip(),
                detail={"reason": "business_rules"} if event.get("reason") == "business_rules" else None)
            discard_pending()
            st.session_state.coldchain_questions_asked += 1
            generate(request, rewrite=True)
        elif event["action"] == "run" and executable(request):
            run_proposal(request)
        elif event["action"] in {"result_positive", "result_negative"}:
            vote = event["action"].removeprefix("result_")
            result_feedback(request, vote, event["version"])
            entry = latest_response(request)
            log("result_vote", request, version=event["version"], vote=vote, langsmith_run_id=entry.get("run_trace_id"))
            send_feedback(entry.get("run_trace_id"), "result_vote", 1 if vote == "positive" else 0)

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
