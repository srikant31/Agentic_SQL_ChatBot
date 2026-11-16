"""Evaluation-only autoapproval; SQL is executed once by the independent runner."""
import uuid
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
import config  # local dotenv / hosted secrets
from sql_graph import build_graph
from sql_generator import provider_settings


def predict(question: str, history: list, role: str) -> dict:
    # No graph/execution state is shared between evaluation cases.
    graph = build_graph(InMemorySaver(), predict_only=True)
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}, "recursion_limit": 40,
           "tags": ["sql-chatbot", "golden-eval"],
           "metadata": {"model": provider_settings()[4], "role": role}}
    output = graph.invoke({"question": question, "history": history, "role": role, "attempts": 0}, cfg)
    for _ in range(3):
        if not output.get("__interrupt__"):
            break
        output = graph.invoke(Command(resume={"action": "approve"}), cfg)
    if output.get("needs_clarification"):
        return {"kind": "clarify", "sql": None}
    if output.get("refused") or output.get("status") != "complete":
        return {"kind": "refuse", "sql": None}
    return {"kind": "sql", "sql": output["sql"]}
