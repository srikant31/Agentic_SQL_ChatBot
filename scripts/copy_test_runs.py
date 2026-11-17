"""Copy labelled test runs (users test_run_N) from the local SQLite feedback file into the configured
Postgres feedback store, unchanged (same timestamps, questions, SQL, grades and model-call logs).

Use it when a test run was recorded locally before FEEDBACK_DB_URL / PG_URL pointed at Postgres.

Run from the project root (PowerShell, one line each):
    .\\venv\\Scripts\\python.exe scripts\\copy_test_runs.py --dry-run
    .\\venv\\Scripts\\python.exe scripts\\copy_test_runs.py

- Source: data/feedback_events.sqlite (or --source URL). Only rows whose username starts with "test_run".
- Target: the feedback store from FEEDBACK_DB_URL / PG_URL. Must be Postgres, otherwise it stops.
- Safe to run twice: a question (request_id) already present in the target is skipped.
No AI calls. Never prints URLs, hosts or passwords.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

import config  # noqa: E402,F401  loads .env and Streamlit secrets
import feedback_store  # noqa: E402
from sqlalchemy import create_engine, insert, select  # noqa: E402

TABLES = (feedback_store.query_events, feedback_store.llm_calls)


def is_test_run(table):
    return table.c.username.like("test_run%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=f"sqlite:///{feedback_store.DEFAULT_SQLITE.as_posix()}")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    target_url = feedback_store.database_url()
    if not target_url.startswith("postgresql"):
        print("STOP: FEEDBACK_DB_URL / PG_URL is not set to Postgres, so there is nowhere to copy to.")
        return 1
    if not feedback_store.DEFAULT_SQLITE.exists() and args.source.startswith("sqlite:///" + feedback_store.DEFAULT_SQLITE.as_posix()):
        print("STOP: the local feedback file data/feedback_events.sqlite was not found.")
        return 1

    source = create_engine(args.source)
    try:
        feedback_store.FeedbackStore(target_url)          # creates the tables in Postgres if they are missing
        target = create_engine(target_url, pool_pre_ping=True)
    except Exception as exc:
        print(f"STOP: could not open the Postgres feedback store ({type(exc).__name__}).")
        return 1
    print("Source: local SQLite file. Target: Postgres.")

    with source.connect() as src, target.connect() as dst:
        events = [dict(r._mapping) for r in src.execute(
            select(feedback_store.query_events).where(is_test_run(feedback_store.query_events))
            .order_by(feedback_store.query_events.c.id))]
        calls = [dict(r._mapping) for r in src.execute(
            select(feedback_store.llm_calls).where(is_test_run(feedback_store.llm_calls))
            .order_by(feedback_store.llm_calls.c.id))]
        present = {r[0] for r in dst.execute(
            select(feedback_store.query_events.c.request_id).where(is_test_run(feedback_store.query_events)))}

    runs = sorted({e["display_name"] for e in events if e["display_name"]})
    new_events = [e for e in events if e["request_id"] not in present]
    new_requests = {e["request_id"] for e in new_events}
    new_calls = [c for c in calls if c["request_id"] in new_requests]
    for row in new_events + new_calls:
        row.pop("id", None)                                # Postgres assigns its own row ids

    print(f"Test runs found locally: {', '.join(runs) or 'none'}")
    print(f"Questions: {len({e['request_id'] for e in events})} local, {len(present)} already in Postgres, "
          f"{len(new_requests)} to copy ({len(new_events)} events, {len(new_calls)} model calls).")
    if args.dry_run or not new_events:
        print("Dry run: nothing written." if args.dry_run else "Nothing to copy.")
        return 0

    with target.begin() as dst:                            # one transaction: all rows or none
        dst.execute(insert(feedback_store.query_events), new_events)
        if new_calls:
            dst.execute(insert(feedback_store.llm_calls), new_calls)
    with target.connect() as dst:
        copied = dst.execute(select(feedback_store.query_events.c.request_id)
                             .where(is_test_run(feedback_store.query_events))).fetchall()
    print(f"Copied. Postgres now holds {len({r[0] for r in copied})} test-run questions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
