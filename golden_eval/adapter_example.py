"""Adapter: connects run_eval.py to your LangGraph app. Edit the two imports and the state keys to match your code.

Assumes the graph from our earlier plan: state keys question / schema / attempts in, sql / rows / answer / error out,
and an approval interrupt for sensitive tables.

Run (PowerShell, one line):
  python run_eval.py --db-url $env:EVAL_DB_URL --predictor adapter_example:predict --sleep 2
"""
import uuid

from langgraph.types import Command

from sql_graph import build_graph                 # <- your graph module
from schema_context import get_schema_context     # <- your schema retriever (rename to yours)

GRAPH = build_graph()


def predict(question: str, history: list, role: str) -> dict:
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())},   # fresh thread per case: no memory leaks between cases
           "tags": ["golden-eval"], "metadata": {"role": role}}  # tags/metadata show up in LangSmith traces
    state = {"question": question, "history": history, "role": role,
             "schema": get_schema_context(question), "attempts": 0}
    out = GRAPH.invoke(state, cfg)
    if "__interrupt__" in out:                    # approval gate: approve unchanged SQL during evaluation
        out = GRAPH.invoke(Command(resume={"action": "approve"}), cfg)

    if out.get("needs_clarification"):           # add a clarify node to your graph, then set this key
        return {"kind": "clarify", "sql": None}
    if out.get("refused") or "rows" not in out:   # declined, blocked, or gave up after retries
        return {"kind": "refuse", "sql": None}
    return {"kind": "sql", "sql": out.get("sql")}
