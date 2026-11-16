"""What happened to each question, in readable form: a step log and a full prompt log.

Tables
  query_events : one row per step (proposal, vote, rewrite, run, limit_reached), with the question,
                 SQL, explanation, answer and the user's hint as readable text.
  llm_calls    : one row per model request, with the exact system prompt, the user payload
                 (question, schema context, glossary, history), the raw response, timing and tokens.

Storage: FEEDBACK_DB_URL, else PG_URL (the checkpoint Postgres), else a local SQLite file.
The ColdChain MySQL source is never written to; its account is read-only by design.
FEEDBACK_STORE_TEXT=false keeps only numbers (for real, private data). Default: text is stored.
Logging is best-effort: a storage failure is logged and the chat carries on.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from sqlalchemy import (Column, DateTime, Integer, MetaData, String, Table, Text,
                        create_engine, desc, insert, inspect, select)

from diagnostics import log_failure

EVENTS = {"proposal", "vote", "rewrite", "run", "limit_reached"}
DEFAULT_SQLITE = Path(__file__).parent / "data" / "feedback_events.sqlite"
TEXT_LIMIT = 200_000   # a schema-plus-glossary prompt is tens of KB; this keeps whole prompts

metadata = MetaData()

query_events = Table(
    "query_events", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("username", String(80), nullable=False),        # demo account id, e.g. "employee"
    Column("display_name", String(120)),                   # fictional display name
    Column("role", String(20)),                            # ColdChain role: viewer / admin
    Column("request_id", String(36), nullable=False, index=True),   # one original question
    Column("version", Integer, nullable=False),            # 0 = first proposal, 1.. = rewrites
    Column("event", String(20), nullable=False),
    Column("route", String(20)),                           # "direct" now; "decomposed" later
    Column("model", String(80)),
    Column("model_calls", Integer),                        # model requests made during THIS step
    Column("latency_ms", Integer),
    Column("status", String(30)),                          # graph status / outcome
    Column("vote", String(10)),
    Column("question", Text),                              # the question as sent at this step
    Column("sql", Text),
    Column("explanation", Text),
    Column("message", Text),                               # answer, refusal or error shown to the user
    Column("hint_text", Text),                             # the user's "What should change?" text
    Column("rows_returned", Integer),
    Column("langsmith_run_id", String(36)),
    Column("detail", Text),                                # JSON for later fields (rules applied, checks)
)

llm_calls = Table(
    "llm_calls", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("username", String(80)),
    Column("role", String(20)),
    Column("request_id", String(36), index=True),
    Column("version", Integer),
    Column("node", String(40), nullable=False),            # classify / generate / summarize / rewrite_question
    Column("model", String(80)),
    Column("system_prompt", Text),
    Column("user_payload", Text),                          # JSON: question, history, schema context, glossary
    Column("response_text", Text),
    Column("error", String(200)),
    Column("latency_ms", Integer),
    Column("input_tokens", Integer),
    Column("output_tokens", Integer),
    Column("langsmith_run_id", String(36)),                # the proposal/run trace this call belongs to
)


def database_url():
    url = os.getenv("FEEDBACK_DB_URL") or os.getenv("PG_URL")
    if url:
        # PG_URL is written for psycopg directly; SQLAlchemy needs the driver named.
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url
    DEFAULT_SQLITE.parent.mkdir(exist_ok=True)
    return f"sqlite:///{DEFAULT_SQLITE}"


def store_text():
    return os.getenv("FEEDBACK_STORE_TEXT", "true").strip().lower() != "false"


def _text(value):
    if value is None or not store_text():
        return None
    return str(value)[:TEXT_LIMIT]


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class FeedbackStore:
    def __init__(self, url=None):
        self.engine = create_engine(url or database_url(), pool_pre_ping=True)
        existing = inspect(self.engine)
        if existing.has_table("query_events") and "session" in {c["name"] for c in existing.get_columns("query_events")}:
            raise RuntimeError("query_events uses the earlier hashed-session schema. Delete or rename that table "
                               "(local file: data/feedback_events.sqlite) and restart.")
        metadata.create_all(self.engine)

    def record(self, event, *, username, request_id, version, display_name=None, role=None, hint=None,
               question=None, sql=None, explanation=None, message=None, detail=None, **fields):
        """Write one step. Returns False instead of raising so the chat never fails on logging."""
        try:
            if event not in EVENTS:
                raise ValueError("Unknown feedback event.")
            row = {"ts": datetime.now(timezone.utc), "username": str(username)[:80], "request_id": str(request_id),
                   "version": int(version), "event": event,
                   "display_name": display_name and str(display_name)[:120], "role": role and str(role)[:20],
                   "question": _text(question), "sql": _text(sql), "explanation": _text(explanation),
                   "message": _text(message), "hint_text": _text(hint)}
            for key in ("route", "model", "status", "vote", "langsmith_run_id"):
                if fields.get(key) is not None:
                    row[key] = str(fields[key])[:80]
            for key in ("model_calls", "latency_ms", "rows_returned"):
                row[key] = _int(fields.get(key))
            if detail:
                row["detail"] = json.dumps(detail, default=str)[:20000]
            with self.engine.begin() as connection:
                connection.execute(insert(query_events).values(**row))
            return True
        except Exception as exc:
            log_failure("feedback_record_failed", exc, feedback_event=str(event)[:20])
            return False

    def record_llm_call(self, *, node, context=None, system=None, payload=None, response=None, error=None,
                        latency_ms=None, usage=None):
        try:
            context = context or {}
            usage = usage if isinstance(usage, dict) else {}
            payload_text = payload if isinstance(payload, str) or payload is None else json.dumps(payload, default=str, ensure_ascii=False)
            row = {"ts": datetime.now(timezone.utc), "node": str(node)[:40],
                   "username": context.get("username"), "role": context.get("role"),
                   "request_id": context.get("request_id"), "version": _int(context.get("version")),
                   "model": context.get("model") and str(context["model"])[:80],
                   "langsmith_run_id": context.get("run_id"),
                   "system_prompt": _text(system), "user_payload": _text(payload_text),
                   "response_text": _text(response), "error": error and str(error)[:200],
                   "latency_ms": _int(latency_ms), "input_tokens": _int(usage.get("input_tokens")),
                   "output_tokens": _int(usage.get("output_tokens"))}
            with self.engine.begin() as connection:
                connection.execute(insert(llm_calls).values(**row))
            return True
        except Exception as exc:
            log_failure("llm_call_record_failed", exc)
            return False

    # ------------------------------------------------------------------ reading
    def events(self, request_id=None):
        query = select(query_events).order_by(query_events.c.id)
        if request_id:
            query = query.where(query_events.c.request_id == request_id)
        with self.engine.connect() as connection:
            return [dict(row._mapping) for row in connection.execute(query)]

    def calls(self, request_id=None):
        query = select(llm_calls).order_by(llm_calls.c.id)
        if request_id:
            query = query.where(llm_calls.c.request_id == request_id)
        with self.engine.connect() as connection:
            return [dict(row._mapping) for row in connection.execute(query)]

    def recent_requests(self, limit=50, username=None):
        """Newest questions first: who asked, the original question, versions used and the outcome."""
        query = select(query_events).order_by(desc(query_events.c.id)).limit(5000)
        if username:
            query = query.where(query_events.c.username == username)
        with self.engine.connect() as connection:
            rows = [dict(r._mapping) for r in connection.execute(query)]
        requests = {}
        for row in reversed(rows):   # oldest first, so the first question seen is the original
            item = requests.setdefault(row["request_id"], {
                "request_id": row["request_id"], "started": row["ts"], "username": row["username"],
                "display_name": row["display_name"], "question": row["question"], "versions": 0, "outcome": "open"})
            item["versions"] = max(item["versions"], row["version"] + 1)
            if row["event"] == "run":
                item["outcome"] = "ran" if row["status"] == "complete" else "run failed"
            elif row["event"] == "limit_reached":
                item["outcome"] = "rewrite limit reached"
        return sorted(requests.values(), key=lambda r: r["started"], reverse=True)[:limit]

    def timeline(self, request_id):
        """Every step and every model call for one question, in time order."""
        steps = [{"kind": "step", **row} for row in self.events(request_id)]
        prompts = [{"kind": "model_call", **row} for row in self.calls(request_id)]
        return sorted(steps + prompts, key=lambda item: (item["ts"], item["kind"] == "step"))

    def summary(self):
        return summarize(self.events())


def summarize(events):
    """Headline numbers. User acceptance is behaviour, not correctness: use the golden set for that."""
    by_request = {}
    for event in events:
        by_request.setdefault(event["request_id"], []).append(event)
    asked = [items for items in by_request.values() if any(e["event"] == "proposal" for e in items)]
    total = len(asked)

    def first_accepted(items):
        # Accepted on the first proposal: a positive vote or a successful run at version 0, before any rewrite.
        return any(e["version"] == 0 and ((e["event"] == "vote" and e["vote"] == "positive")
                                          or (e["event"] == "run" and e["status"] == "complete")) for e in items)

    resolved = [items for items in asked if any(e["event"] == "run" and e["status"] == "complete" for e in items)]
    rewrites = [max((e["version"] for e in items), default=0) for items in asked]
    calls = [sum(e["model_calls"] or 0 for e in items) for items in asked]
    runs = [e for e in events if e["event"] == "run"]
    votes = [e for e in events if e["event"] == "vote"]
    ratio = lambda part, whole: round(part / whole, 3) if whole else None
    return {
        "questions": total,
        "accepted_first_proposal": ratio(sum(first_accepted(items) for items in asked), total),
        "resolved_with_successful_run": ratio(len(resolved), total),
        "avg_rewrites_per_question": ratio(sum(rewrites), total),
        "avg_model_calls_per_question": ratio(sum(calls), total),
        "rewrite_limit_reached": sum(any(e["event"] == "limit_reached" for e in items) for items in asked),
        "run_failure_rate": ratio(sum(e["status"] != "complete" for e in runs), len(runs)),
        "votes_positive": sum(e["vote"] == "positive" for e in votes),
        "votes_negative": sum(e["vote"] == "negative" for e in votes),
    }


_STORE = None
_UNAVAILABLE = False


def get_store():
    """One store per process. Returns None if storage is unavailable, so callers can skip logging.
    After one failed connection it stops retrying, so an unreachable database cannot slow every click."""
    global _STORE, _UNAVAILABLE
    if _STORE is None and not _UNAVAILABLE:
        try:
            _STORE = FeedbackStore()
        except Exception as exc:
            _UNAVAILABLE = True
            log_failure("feedback_store_unavailable", exc)
    return _STORE


def reset_store():
    """For tests and for a restart after fixing configuration."""
    global _STORE, _UNAVAILABLE
    _STORE, _UNAVAILABLE = None, False


def record(event, **fields):
    store = get_store()
    return store.record(event, **fields) if store else False
