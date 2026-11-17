"""Presentation numbers from real usage: the app's feedback database (Postgres when FEEDBACK_DB_URL/PG_URL
points at it, otherwise the local SQLite file) and LangSmith project statistics.

Run from the project root (PowerShell, one line):
    $env:PYTHONIOENCODING="utf-8"; .\\venv\\Scripts\\python.exe scripts\\usage_stats.py

Writes eval_runs/usage_stats.md and eval_runs/usage_stats.json (eval_report_pdf.py adds them to the PDF).
Read-only: it only SELECTs from the feedback tables and reads LangSmith statistics. No AI calls, no cost.
Never prints URLs, keys, question text or user names beyond the fictional demo display names' counts.
"""
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

import config  # noqa: E402,F401  loads .env and Streamlit secrets
from observability import configure_observability, tracing_enabled  # noqa: E402
configure_observability()

EVAL_PROJECT = "coldchain-golden-eval"


def pctl(values, q):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    return values[min(len(values) - 1, int(q * len(values)))]


def feedback_numbers():
    import feedback_store
    url = feedback_store.database_url()
    backend = "Postgres" if url.startswith("postgresql") else "SQLite (local file)" if url.startswith("sqlite") else "other"
    store = feedback_store.FeedbackStore(url)
    events = [e for e in store.events() if not feedback_store.is_test_run(e["username"])]
    calls = [c for c in store.calls() if not feedback_store.is_test_run(c["username"])]
    test_runs = sorted({e["display_name"] for e in store.events() if feedback_store.is_test_run(e["username"])})
    summary = feedback_store.summarize(events)

    asked = {e["request_id"] for e in events if e["event"] == "proposal"}
    roles = Counter()
    for request_id in asked:
        first = next(e for e in events if e["request_id"] == request_id)
        roles[first["role"] or "unknown"] += 1
    reasons = Counter()
    for e in events:
        if e["event"] == "vote" and e["vote"] == "negative" and e.get("detail"):
            try:
                reasons[json.loads(e["detail"]).get("reason") or "free-text hint"] += 1
            except (TypeError, ValueError):
                pass
    nodes = defaultdict(list)
    for c in calls:
        nodes[c["node"]].append(c)
    per_node = {}
    for node, items in sorted(nodes.items()):
        latency = [c["latency_ms"] for c in items if c["latency_ms"] is not None]
        tokens_in = [c["input_tokens"] for c in items if c["input_tokens"] is not None]
        tokens_out = [c["output_tokens"] for c in items if c["output_tokens"] is not None]
        per_node[node] = {
            "calls": len(items), "errors": sum(1 for c in items if c["error"]),
            "latency_median_ms": int(statistics.median(latency)) if latency else None,
            "latency_p90_ms": pctl(latency, 0.9),
            "avg_input_tokens": int(statistics.mean(tokens_in)) if tokens_in else None,
            "avg_output_tokens": int(statistics.mean(tokens_out)) if tokens_out else None,
            "total_tokens": sum(tokens_in) + sum(tokens_out)}
    stamps = [e["ts"] for e in events if e["ts"] is not None]
    return {
        "backend": backend,
        "tables": {"query_events": len(events), "llm_calls": len(calls)},
        "period": {"first": str(min(stamps))[:16] if stamps else None, "last": str(max(stamps))[:16] if stamps else None},
        "summary": summary, "questions_by_role": dict(roles.most_common()),
        "negative_vote_reasons": dict(reasons.most_common()), "model_calls_by_node": per_node,
        "users": len({e["username"] for e in events}),
        "excluded_test_runs": test_runs,
    }


def langsmith_numbers():
    if not tracing_enabled():
        return {"available": False, "reason": "tracing is off or no LangSmith key"}
    from langsmith import Client
    client = Client()
    projects = {}
    for name in (os.getenv("LANGSMITH_PROJECT", "sql-chatbot"), EVAL_PROJECT):
        try:
            p = client.read_project(project_name=name, include_stats=True)
        except Exception as exc:
            projects[name] = {"found": False, "reason": type(exc).__name__}
            continue
        seconds = lambda v: round(v.total_seconds(), 2) if isinstance(v, timedelta) else v
        feedback = {}
        for key, stats in (getattr(p, "feedback_stats", None) or {}).items():
            if isinstance(stats, dict):
                feedback[key] = {"n": stats.get("n"), "avg": round(stats["avg"], 3) if stats.get("avg") is not None else None}
        projects[name] = {
            "found": True,
            "runs": getattr(p, "run_count", None),
            "latency_p50_s": seconds(getattr(p, "latency_p50", None)),
            "latency_p99_s": seconds(getattr(p, "latency_p99", None)),
            "total_tokens": getattr(p, "total_tokens", None),
            "prompt_tokens": getattr(p, "prompt_tokens", None),
            "completion_tokens": getattr(p, "completion_tokens", None),
            "error_rate": round(p.error_rate, 3) if getattr(p, "error_rate", None) is not None else None,
            "first_run": str(getattr(p, "first_start_time", "") or "")[:16] or None,
            "last_run": str(getattr(p, "last_run_start_time", None) or getattr(p, "last_start_time", "") or "")[:16] or None,
            "feedback": feedback,
        }
        try:   # traces = top-level runs (one per question or user turn)
            projects[name]["traces"] = sum(1 for _ in client.list_runs(project_name=name, is_root=True, limit=5000))
        except Exception:
            projects[name]["traces"] = None
    return {"available": True, "endpoint_region": "APAC" if "apac" in os.getenv("LANGSMITH_ENDPOINT", "") else "default",
            "projects": projects}


def to_markdown(data):
    f, l = data["feedback_store"], data["langsmith"]
    s = f.get("summary", {})
    r = lambda v: "n/a" if v is None else (f"{100 * v:.0f}%" if isinstance(v, float) and v <= 1 else f"{v:,}" if isinstance(v, int) else str(v))
    lines = [f"# Usage numbers ({data['generated']})", "", f"## App database ({f.get('backend', 'n/a')})", ""]
    if "error" in f:
        lines.append(f"Unavailable: {f['error']}")
    else:
        lines += [f"Records: {f['tables']['query_events']:,} query events and {f['tables']['llm_calls']:,} model calls, "
                  f"{f['period']['first']} to {f['period']['last']}, {f['users']} demo accounts.", "",
                  "| Measure | Value |", "|---|---|",
                  f"| Questions asked | {r(s.get('questions'))} |",
                  f"| Accepted on the first proposal | {r(s.get('accepted_first_proposal'))} |",
                  f"| Ended with a successful run | {r(s.get('resolved_with_successful_run'))} |",
                  f"| Rewrites per question (average) | {s.get('avg_rewrites_per_question')} |",
                  f"| Model calls per question (average) | {s.get('avg_model_calls_per_question')} |",
                  f"| Hit the 3-rewrite limit | {r(s.get('rewrite_limit_reached'))} |",
                  f"| Run failure rate | {r(s.get('run_failure_rate'))} |",
                  f"| Votes positive / negative | {s.get('votes_positive')} / {s.get('votes_negative')} |", ""]
        if f["questions_by_role"]:
            lines += ["Questions by department: " + ", ".join(f"{k} {v}" for k, v in f["questions_by_role"].items()), ""]
        if f["negative_vote_reasons"]:
            lines += ["Negative-vote reasons: " + ", ".join(f"{k} {v}" for k, v in f["negative_vote_reasons"].items()), ""]
        if f["model_calls_by_node"]:
            lines += ["| Model step | Calls | Errors | Median / p90 latency | Avg tokens in / out |", "|---|---|---|---|---|"]
            for node, n in f["model_calls_by_node"].items():
                lat = f"{n['latency_median_ms'] / 1000:.1f} s / {n['latency_p90_ms'] / 1000:.1f} s" if n["latency_median_ms"] else "n/a"
                tok = f"{n['avg_input_tokens'] or 0:,} / {n['avg_output_tokens'] or 0:,}"
                lines.append(f"| {node} | {n['calls']} | {n['errors']} | {lat} | {tok} |")
            lines.append("")
    if f.get("excluded_test_runs"):
        lines += ["Excluded from these numbers (labelled test runs): " + ", ".join(f["excluded_test_runs"]), ""]
    lines += ["## LangSmith", ""]
    if not l.get("available"):
        lines.append(f"Unavailable: {l.get('reason')}")
    else:
        lines += ["| Project | Traces | Runs | Median / p99 latency | Tokens | Error rate | Feedback (average) |",
                  "|---|---|---|---|---|---|---|"]
        for name, p in l["projects"].items():
            if not p.get("found"):
                lines.append(f"| {name} | not found | | | | | |")
                continue
            fb = ", ".join(f"{k} {v['avg']} (n={v['n']})" for k, v in p["feedback"].items()) or "none"
            lat = f"{p['latency_p50_s']} s / {p['latency_p99_s']} s" if p["latency_p50_s"] is not None else "n/a"
            lines.append(f"| {name} | {r(p.get('traces'))} | {r(p['runs'])} | {lat} | {r(p['total_tokens'])} | "
                         f"{r(p['error_rate'])} | {fb} |")
        lines += ["", "Traces = one per question or user turn. Runs include every step inside a trace."]
    lines += ["", "User acceptance shows what users clicked, not whether answers were correct; correctness comes "
              "from the golden-set evaluation."]
    return "\n".join(lines) + "\n"


def main():
    data = {"generated": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")}
    try:
        data["feedback_store"] = feedback_numbers()
    except Exception as exc:
        data["feedback_store"] = {"error": type(exc).__name__}
    try:
        data["langsmith"] = langsmith_numbers()
    except Exception as exc:
        data["langsmith"] = {"available": False, "reason": type(exc).__name__}
    out = ROOT / "eval_runs"
    out.mkdir(exist_ok=True)
    (out / "usage_stats.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    markdown = to_markdown(data)
    (out / "usage_stats.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    print("Written: eval_runs/usage_stats.md, eval_runs/usage_stats.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
