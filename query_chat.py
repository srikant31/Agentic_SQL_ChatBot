"""Session-owned query conversations. Feedback never authorizes SQL execution."""
from copy import deepcopy
import uuid

MAX_REWRITES = 3
LIMIT_MESSAGE = "Sorry, I couldn't meet your needs after three rewrites. Please start a new question with more specific requirements."


def new_chat(owner, scope):
    return {"owner": owner, "scope": scope, "requests": []}


def start_request(chat, question):
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 4000:
        raise ValueError("Enter a question of at most 4,000 characters.")
    request = {"id": str(uuid.uuid4()), "original_question": question.strip(),
               "current_question": question.strip(), "rewrites": 0, "modifications": [],
               "feedback_open": False, "exhausted": False,
               "messages": [{"role": "user", "text": question.strip()}]}
    chat["requests"].append(request)
    chat["requests"] = chat["requests"][-15:]
    return request


def add_response(request, proposal=None, message=None, *, error=False):
    entry = {"role": "assistant", "version": request["rewrites"],
             "text": proposal["explanation"] if proposal else (message or "No query was proposed."),
             "question": request["current_question"], "execution_attempted": False,
             "kind": "error" if error else "response"}
    if proposal:
        entry["proposal"] = deepcopy(proposal)
    request["messages"].append(entry)
    return entry


def active_request(chat):
    return chat["requests"][-1] if chat["requests"] else None


def latest_response(request):
    return next((m for m in reversed(request["messages"]) if m["role"] == "assistant"), None)


def feedback(request, vote, version):
    entry = latest_response(request)
    if vote not in {"positive", "negative"} or not entry or entry["version"] != version or version != request["rewrites"]:
        raise ValueError("This feedback belongs to an older response.")
    entry["vote"] = vote
    request["feedback_open"] = vote == "negative" and request["rewrites"] < MAX_REWRITES
    request["exhausted"] = vote == "negative" and request["rewrites"] >= MAX_REWRITES


def begin_rewrite(request, modification, version):
    entry = latest_response(request)
    if not entry or entry["version"] != version or version != request["rewrites"] or not request["feedback_open"]:
        raise ValueError("Choose negative feedback on the latest response before rewriting.")
    if request["rewrites"] >= MAX_REWRITES:
        raise ValueError(LIMIT_MESSAGE)
    modification = modification.strip()
    if not 1 <= len(modification) <= 2000:
        raise ValueError("Describe your modifications in 1 to 2,000 characters.")
    # Reserve before any model call. A rerun or failed request cannot replay the same submission.
    request["rewrites"] += 1
    request["modifications"].append(modification)
    request["messages"].append({"role": "user", "text": modification, "kind": "modification"})
    request["feedback_open"] = False
    entry["superseded"] = True


def executable(request):
    entry = latest_response(request)
    return bool(entry and entry["version"] == request["rewrites"] and entry.get("proposal") and not entry.get("superseded")
                and not entry["execution_attempted"] and not request["feedback_open"]
                and not request["exhausted"] and entry.get("vote") != "negative")


def record_result(request, columns=None, rows=None, error=None):
    entry = latest_response(request)
    entry["execution_attempted"] = True
    if error:
        entry["execution_error"] = error
    else:
        entry["columns"], entry["rows"] = list(columns), list(rows)


def render_conversation(chat, prefix, *, run_label="Run this query", can_generate=True):
    """Render saved messages and return a single latest-response UI event."""
    import streamlit as st

    active = active_request(chat)
    for request in chat["requests"]:
        latest = latest_response(request)
        for entry in request["messages"]:
            with st.chat_message(entry["role"]):
                if entry.get("kind") == "modification":
                    st.caption("Requested changes")
                if entry.get("kind") == "error":
                    st.error(entry["text"])
                else:
                    st.write(entry["text"])
                proposal = entry.get("proposal")
                if proposal:
                    if entry["version"]:
                        st.caption("Updated request: " + entry["question"])
                    st.caption(f"Original proposal" if not entry["version"] else f"Rewrite {entry['version']} of {MAX_REWRITES}")
                    st.code(proposal["sql"], language="sql")
                    if proposal.get("validation"):
                        with st.expander("Context and validation"):
                            st.write("Checks passed:", proposal["validation"]["checks"])
                            st.write("Business definitions:", proposal["context"]["rules"])
                            st.write("Reviewed examples:", proposal["context"]["examples"] or "None needed")
                    # Preserve the existing employee estimate; confidence work is out of scope.
                    if "confidence" in proposal:
                        st.progress(proposal["confidence"], text=f"Model confidence (not a correctness guarantee): {proposal['confidence']:.0%}")
                if "rows" in entry:
                    st.dataframe([dict(zip(entry["columns"], row)) for row in entry["rows"]], hide_index=True)
                    st.caption(f"{len(entry['rows'])} result rows within your authorized scope.")
                if entry.get("execution_error"):
                    st.error(entry["execution_error"])
                if entry["role"] != "assistant" or request is not active or entry is not latest:
                    continue
                key = f"{prefix}:{request['id']}:{entry['version']}"
                positive, negative = st.columns(2)
                if positive.button("👍 Looks good", key=key + ":positive"):
                    return {"action": "positive", "version": entry["version"]}
                if negative.button("👎 Needs changes", key=key + ":negative"):
                    return {"action": "negative", "version": entry["version"]}
                if entry.get("vote") == "positive":
                    st.caption("Thanks for your feedback. SQL runs only when you click the run button.")
                if request["exhausted"]:
                    st.info(LIMIT_MESSAGE)
                elif request["feedback_open"]:
                    changes = st.text_area("What should change?", placeholder="Please prompt again and tell the model what to modify.",
                                           max_chars=2000, key=key + ":changes")
                    st.caption(f"{MAX_REWRITES - request['rewrites']} of {MAX_REWRITES} rewrites remaining")
                    if st.button("Rewrite query", key=key + ":rewrite", disabled=not changes.strip() or not can_generate):
                        return {"action": "rewrite", "version": entry["version"], "text": changes}
                if executable(request) and st.button(run_label, type="primary", key=key + ":run"):
                    return {"action": "run", "version": entry["version"]}
    return None
