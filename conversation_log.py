"""Admin-only reader for the feedback store: every question, every step and every prompt."""
import json

import streamlit as st


def _when(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if hasattr(value, "strftime") else str(value or "")


def _payload(text):
    try:
        st.json(json.loads(text), expanded=False)
    except (TypeError, ValueError):
        st.code(text or "", language="text")


def _step(item):
    label = f"v{item['version']} · {item['event']}"
    outcome = item.get("vote") or item.get("status") or ""
    st.markdown(f"**{label}** · {_when(item['ts'])} · {outcome}")
    if item.get("hint_text"):
        st.write("User asked for changes:", item["hint_text"])
    if item.get("question") and item["event"] == "proposal":
        st.write("Question sent:", item["question"])
    if item.get("explanation"):
        st.write("Explanation:", item["explanation"])
    if item.get("sql"):
        st.code(item["sql"], language="sql")
    if item.get("message"):
        st.write("Shown to user:", item["message"])
    try:
        detail = json.loads(item["detail"]) if item.get("detail") else {}
    except ValueError:
        detail = {}
    if detail.get("rules"):
        marks = {"ok": "✅", "warn": "⚠️", "info": "ℹ️"}
        st.caption("Rules: " + ", ".join(f"{marks.get(r['status'], '')} {r['term']}" for r in detail["rules"]))
    facts = {key: item.get(key) for key in ("model_calls", "latency_ms", "rows_returned", "langsmith_run_id")
             if item.get(key) is not None}
    if facts:
        st.caption(" · ".join(f"{key}: {value}" for key, value in facts.items()))


def _model_call(item):
    tokens = ""
    if item.get("input_tokens") is not None:
        tokens = f" · {item['input_tokens']} in / {item.get('output_tokens')} out tokens"
    title = f"Model call · {item['node']} · v{item.get('version')} · {item.get('latency_ms')} ms{tokens}"
    with st.expander(title + (" · ERROR" if item.get("error") else "")):
        st.caption(f"{_when(item['ts'])} · model: {item.get('model')} · trace: {item.get('langsmith_run_id')}")
        st.markdown("**System prompt**")
        st.code(item.get("system_prompt") or "(not stored)", language="text")
        st.markdown("**Payload sent (question, history, schema context, glossary)**")
        _payload(item.get("user_payload"))
        st.markdown("**Raw model response**")
        st.code(item.get("response_text") or "(none)", language="json")
        if item.get("error"):
            st.error(f"Request failed: {item['error']}")


def render_conversation_log(store):
    if not st.toggle("Show conversation log (admins only)", key="conversation_log_open"):
        return
    st.subheader("Conversation log")
    st.caption("Every question, rewrite, vote and run, with the exact prompts sent to the model. "
               "Data is fictional; set FEEDBACK_STORE_TEXT=false before using private data.")
    try:
        everyone = store.recent_requests(limit=200)
    except Exception:
        st.info("The conversation log could not be loaded.")
        return
    if not everyone:
        st.info("No questions have been logged yet.")
        return
    names = sorted({row["username"] for row in everyone})
    chosen_user = st.selectbox("User", ["Everyone"] + names, key="conversation_log_user")
    rows = everyone if chosen_user == "Everyone" else [r for r in everyone if r["username"] == chosen_user]
    st.dataframe([{"started": _when(r["started"]), "user": r["display_name"] or r["username"],
                   "question": r["question"], "versions": r["versions"], "outcome": r["outcome"]} for r in rows],
                 hide_index=True)
    labels = {f"{_when(r['started'])} · {r['display_name'] or r['username']} · {(r['question'] or '')[:70]}": r["request_id"]
              for r in rows}
    picked = st.selectbox("Open a question", list(labels), key="conversation_log_request")
    if not picked:
        return
    timeline = store.timeline(labels[picked])
    st.download_button("Download this conversation (JSON)", json.dumps(timeline, default=str, indent=2),
                       file_name=f"conversation-{labels[picked]}.json", mime="application/json")
    for item in timeline:
        if item["kind"] == "step":
            _step(item)
        else:
            _model_call(item)
