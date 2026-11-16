"""Append-only record of what happened to each question: proposals, votes, rewrites and runs.

Storage choice: FEEDBACK_DB_URL, else PG_URL (the checkpoint Postgres), else a local SQLite file.
The ColdChain MySQL source is never written to; its account is read-only by design.
Logging is best-effort: a storage failure is logged and the chat carries on.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import (Column, DateTime, Integer, MetaData, String, Table, Text,
                        create_engine, insert, select)

from diagnostics import log_failure

EVENTS = {"proposal", "vote", "rewrite", "run", "limit_reached"}
DEFAULT_SQLITE = Path(__file__).parent / "data" / "feedback_events.sqlite"

metadata = MetaData()
query_events = Table(
    "query_events", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("session", String(16), nullable=False),        # hash of user+role, never the username
    Column("request_id", String(36), nullable=False),     # one original question
    Column("version", Integer, nullable=False),           # 0 = first proposal, 1.. = rewrites
    Column("event", String(20), nullable=False),
    Column("route", String(20)),                          # "direct" now; "decomposed" later
    Column("model", String(80)),
    Column("model_calls", Integer),                       # calls made during THIS event
    Column("latency_ms", Integer),
    Column("status", String(30)),                         # graph status / outcome
    Column("vote", String(10)),
    Column("hint_chars", Integer),
    Column("hint_sha", String(16)),
    Column("hint_text", Text),                            # only when FEEDBACK_STORE_HINTS=true
    Column("rows_returned", Integer),
    Column("langsmith_run_id", String(36)),
    Column("detail", Text),                               # JSON for fields added later (rules, warnings)
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


class FeedbackStore:
    def __init__(self, url=None):
        self.engine = create_engine(url or database_url(), pool_pre_ping=True)
        metadata.create_all(self.engine, tables=[query_events])

    def record(self, event, *, owner, request_id, version, hint=None, detail=None, **fields):
        """Write one event. Returns False instead of raising so the chat never fails on logging."""
        try:
            if event not in EVENTS:
                raise ValueError("Unknown feedback event.")
            row = {"ts": datetime.now(timezone.utc), "session": _digest(owner), "request_id": str(request_id),
                   "version": int(version), "event": event}
            for key in ("route", "model", "status", "vote", "langsmith_run_id"):
                if fields.get(key) is not None:
                    row[key] = str(fields[key])[:80]
            for key in ("model_calls", "latency_ms", "rows_returned"):
                if isinstance(fields.get(key), int) and not isinstance(fields[key], bool):
                    row[key] = fields[key]
            if hint:
                row["hint_chars"], row["hint_sha"] = len(hint), _digest(hint)
                if os.getenv("FEEDBACK_STORE_HINTS", "false").strip().lower() == "true":
                    row["hint_text"] = hint[:500]
            if detail:
                row["detail"] = json.dumps(detail, default=str)[:4000]
            with self.engine.begin() as connection:
                connection.execute(insert(query_events).values(**row))
            return True
        except Exception as exc:
            log_failure("feedback_record_failed", exc, feedback_event=str(event)[:20])
            return False

    def events(self):
        with self.engine.connect() as connection:
            return [dict(row._mapping) for row in connection.execute(select(query_events).order_by(query_events.c.id))]

    def summary(self):
        return summarize(self.events())


def _digest(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:16]


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
