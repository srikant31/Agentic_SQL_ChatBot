"""Session-owned LangGraph workflow; every SQL execution requires fresh approval."""
import sqlite3
from typing import TypedDict
import uuid

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt

from context_pipeline import prepare_proposal, validate_proposal, execute_proposal
from diagnostics import log_failure
from rbac import require
from safety import SchemaValidationError, UnsafeQueryError
from semantic_validation import SemanticValidationError
from sql_generator import provider_settings


class QueryState(TypedDict, total=False):
    question: str
    proposal: dict
    attempts: int
    retry: bool
    feedback: str
    status: str
    message: str
    approved: bool
    columns: list
    rows: list
    answer: str


REPAIRABLE = (SchemaValidationError, UnsafeQueryError, SemanticValidationError, sqlite3.OperationalError)


class SQLWorkflow:
    """Keep one instance per Streamlit session, never in a shared resource cache.

    The engine/user live in a closure rather than checkpoint state. State is in-memory
    and intentionally discarded on logout, new questions, or app restart.
    """
    def __init__(self, user, engine=None, *, max_attempts=3):
        require(user, "query")
        if not 1 <= max_attempts <= 3:
            raise ValueError("Choose one to three generation attempts.")
        self.user, self.engine, self.max_attempts = user, engine, max_attempts
        self.config = None
        self.pending = False
        self.graph = None

    def _failure(self, state, exc):
        log_failure("graph_stage_failed", exc, attempts=state.get("attempts", 0))
        retry = isinstance(exc, REPAIRABLE) and state.get("attempts", 0) < self.max_attempts
        # Do not place raw exception messages (which may contain SQL/rows) into state/traces.
        return {"status": "error", "retry": retry, "approved": False,
                "feedback": "Recheck authorized columns, approved metric, required filters, grouping and SQLite syntax.",
                "message": "The query could not pass validation or execution. Generate a new proposal or narrow the question.",
                "rows": [], "columns": []}

    def _generate(self, state):
        attempts = state.get("attempts", 0) + 1
        try:
            proposal = prepare_proposal(state["question"], self.user, self.engine,
                                        repair_feedback=state.get("feedback", ""))
            return {"proposal": proposal, "attempts": attempts, "status": proposal["status"],
                    "message": proposal.get("message", ""), "retry": False, "approved": False,
                    "rows": [], "columns": [], "answer": ""}
        except Exception as exc:
            return {"attempts": attempts, **self._failure({**state, "attempts": attempts}, exc)}

    def _validate(self, state):
        if state.get("status") != "proposal":
            return {}
        try:
            validate_proposal(state["proposal"], self.user, self.engine)
            return {"retry": False}
        except Exception as exc:
            return self._failure(state, exc)

    def _review(self, state):
        # interrupt must not be enclosed in a broad exception handler.
        decision = interrupt({"sql": state["proposal"]["sql"],
                              "reason": "Review this read-only SQL before execution."})
        if not isinstance(decision, dict) or decision.get("action") != "approve":
            return {"approved": False, "status": "rejected", "message": "Query rejected. Nothing was executed."}
        sql = decision.get("sql", state["proposal"]["sql"])
        if not isinstance(sql, str) or not sql.strip():
            return {"approved": False, "status": "rejected", "message": "An empty query cannot be approved."}
        return {"approved": True, "proposal": {**state["proposal"], "sql": sql}}

    def _execute(self, state):
        if not state.get("approved"):
            return {"status": "rejected", "rows": [], "columns": []}
        try:
            columns, rows = execute_proposal(state["proposal"], self.user, self.engine)
            return {"status": "complete", "columns": columns, "rows": rows, "retry": False, "approved": False}
        except Exception as exc:
            return self._failure(state, exc)

    def _summarize(self, state):
        # No second LLM call or transmission of salary/result rows for summarization.
        return {"answer": f"Returned {len(state['rows'])} result rows within your authorized scope."}

    def _build(self):
        graph = StateGraph(QueryState)
        for name, node in (("generate", self._generate), ("validate", self._validate),
                           ("review", self._review), ("execute", self._execute), ("summarize", self._summarize)):
            graph.add_node(name, node)
        graph.add_edge(START, "generate")
        graph.add_edge("generate", "validate")
        graph.add_conditional_edges("validate", lambda s: "generate" if s.get("retry") else ("review" if s.get("status") == "proposal" else END))
        graph.add_conditional_edges("review", lambda s: "execute" if s.get("approved") else END)
        graph.add_conditional_edges("execute", lambda s: "generate" if s.get("retry") else ("summarize" if s.get("status") == "complete" else END))
        graph.add_edge("summarize", END)
        return graph.compile(checkpointer=InMemorySaver())

    def start(self, question, user):
        self._check_owner(user)
        # Fresh graph/checkpointer prevents checkpoint accumulation and stale resumes.
        self.graph = self._build()
        provider, _, _, _, model = provider_settings()
        self.config = {"configurable": {"thread_id": str(uuid.uuid4())}, "recursion_limit": 30,
                       "tags": ["sql-chatbot", "controlled-workflow"],
                       "metadata": {"provider": provider, "model": model}}
        result = self.graph.invoke({"question": question, "attempts": 0}, self.config)
        self.pending = bool(result.get("__interrupt__"))
        return result

    def resume(self, action, user, sql=None):
        self._check_owner(user)
        if not self.pending:
            raise ValueError("No pending review exists. Generate a fresh query.")
        self.pending = False  # A failed/repeated resume must not replay execution.
        payload = {"action": action}
        if sql is not None:
            payload["sql"] = sql
        result = self.graph.invoke(Command(resume=payload), self.config)
        self.pending = bool(result.get("__interrupt__"))
        return result

    def _check_owner(self, user):
        require(user, "query")
        if user != self.user:
            raise PermissionError("This workflow belongs to another authenticated identity.")
