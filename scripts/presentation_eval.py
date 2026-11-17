"""Golden-set evaluation of the ColdChain assistant, with numbers for slides and LangSmith records.

Runs the real ColdChain graph (real Groq model, real read-only database) on golden questions,
grades each answer with golden_eval/run_eval.py (the result rows must equal the reference query's),
and writes presentation-ready numbers. Every question becomes one LangSmith trace with a
"correct" score attached, in its own LangSmith project.

Run from the project root (PowerShell, one line):
    $env:PYTHONIOENCODING="utf-8"; .\\venv\\Scripts\\python.exe scripts\\presentation_eval.py

Options:
    --subset presentation   24 stratified questions: 18 answerable + 6 safety/behaviour (default)
    --subset all            all 64 questions (about 420,000 tokens: more than one day of Groq free tier)
    --ids B01,J02           only these questions
    --name NAME             run name; results go to eval_runs/NAME.* (default: presentation)
    --resume                skip questions already graded in eval_runs/NAME.jsonl (use after a stop)
    --dry-run               no model calls: check the database, the golden data, the grader and LangSmith
    --tpm-budget N          tokens per minute to stay under (default 7000; Groq free tier is 8000)
    --langsmith-project P   LangSmith project for the traces (default coldchain-golden-eval)
    --hide-trace-text       keep question and SQL text out of LangSmith (default: shown; the golden
                            data is synthetic, so showing it is safe and makes traces readable)

Cost (presentation subset): about 40-50 Groq calls, roughly 140,000-170,000 tokens (most of one day's
free limit), and about 25-35 minutes because of the per-minute token limit. If Groq's daily limit is
reached, the run stops cleanly; rerun the same command with --resume after the limit resets.
Never prints keys, URLs or .env values.
"""
import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / "golden_eval"))
os.chdir(ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

# Stratified sample: every answerable category the slides talk about, plus the safety behaviours.
PRESENTATION_IDS = [
    # answerable (18)
    "B02", "J01", "J02", "J06", "D01", "N02", "N03", "V01", "V04", "F01",
    "L01", "T01", "P01", "W01", "X02", "A01", "H01", "C01",
    # behaviour (6): clarify, unanswerable, delete request, prompt injection, two access-control requests
    "Q01", "U01", "K01", "K03", "R01", "R03",
]
EVAL_TODAY_NOTE = "The golden data's fixed 'today' is 2026-06-30 (the model is told this)."


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", choices=["presentation", "all"], default="presentation")
    ap.add_argument("--ids")
    ap.add_argument("--name", default="presentation")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--tpm-budget", type=int, default=7000)
    ap.add_argument("--langsmith-project", default="coldchain-golden-eval")
    ap.add_argument("--hide-trace-text", action="store_true")
    ap.add_argument("--max-consecutive-errors", type=int, default=2)
    return ap.parse_args()


ARGS = parse_args()
# Must be set before config/observability load .env (they never override existing variables).
os.environ["LANGSMITH_PROJECT"] = ARGS.langsmith_project
os.environ["LANGSMITH_HIDE_INPUTS"] = "true" if ARGS.hide_trace_text else "false"
os.environ["LANGSMITH_HIDE_OUTPUTS"] = "true" if ARGS.hide_trace_text else "false"

import config  # noqa: E402,F401  loads .env and Streamlit secrets, writes ca.pem if needed
from observability import configure_observability, tracing_enabled  # noqa: E402
configure_observability()

from langchain_core.callbacks import BaseCallbackHandler  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

import run_eval  # noqa: E402  golden_eval/run_eval.py: the same grader as the golden README
from sql_guard import validate  # noqa: E402
from sql_generator import provider_settings  # noqa: E402

OUT_DIR = ROOT / "eval_runs"


# ---------------------------------------------------------------------------- helpers
def git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              timeout=10).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def wilson(passed, total, z=1.96):
    """95% confidence interval for a pass rate (honest error bars for a small sample)."""
    if total == 0:
        return 0.0, 0.0
    p = passed / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return max(0.0, centre - margin), min(1.0, centre + margin)


def pct(x):
    return f"{100 * x:.0f}%"


class CallRecorder(BaseCallbackHandler):
    """Counts tokens per question and records model API failures (rate limits, outages), so a
    failure caused by the provider is not counted as a wrong answer."""

    def __init__(self):
        self.errors = []
        self.tokens = {"input": 0, "output": 0, "total": 0}

    def on_llm_end(self, response, **kwargs):
        for generations in response.generations:
            for generation in generations:
                usage = getattr(getattr(generation, "message", None), "usage_metadata", None) or {}
                self.tokens["input"] += usage.get("input_tokens", 0)
                self.tokens["output"] += usage.get("output_tokens", 0)
                self.tokens["total"] += usage.get("total_tokens", 0)

    def on_llm_error(self, error, **kwargs):
        text = str(error).lower()
        if "per day" in text or "tpd" in text or "rpd" in text:
            kind = "daily_limit"
        elif "rate limit" in text or "429" in text or "per minute" in text:
            kind = "rate_limit"
        else:
            kind = type(error).__name__        # class name only: messages can contain account ids
        self.errors.append(kind)


class TokenPacer:
    """Waits so the tokens sent in any 60-second window stay under the per-minute budget."""

    def __init__(self, budget):
        self.budget, self.window, self.per_case = budget, [], 6500

    def wait(self):
        waited = 0
        while True:
            now = time.time()
            self.window = [(t, n) for t, n in self.window if now - t < 60]
            used = sum(n for _, n in self.window)
            if not self.window or used + self.per_case <= self.budget:
                return waited
            time.sleep(2)
            waited += 2

    def add(self, tokens, cases_done):
        self.window.append((time.time(), tokens))
        if tokens:
            # running average, so the pacer learns the real cost per question
            self.per_case = int((self.per_case * cases_done + tokens) / (cases_done + 1))
        self.per_case = min(self.per_case, self.budget)


def build_graph():
    from sql_graph import build_graph as graph_factory
    return graph_factory(InMemorySaver(), predict_only=True)


def predict(case, model_name, run_label):
    """Same flow as golden_eval/adapter.py, plus run id, tokens, attempts, latency and API errors."""
    graph = build_graph()
    errors = CallRecorder()
    run_id = uuid.uuid4()
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}, "recursion_limit": 40, "run_id": run_id,
           "run_name": f"golden {case['id']} {case['category']}", "callbacks": [errors],
           "tags": ["sql-chatbot", "golden-eval", run_label, case["category"]],
           "metadata": {"model": model_name, "role": case.get("role", "viewer"), "case_id": case["id"],
                        "category": case["category"], "expected_kind": case["kind"], "eval_run": run_label}}
    started = time.perf_counter()
    output = graph.invoke({"question": case["question"], "history": case.get("history", []),
                           "role": case.get("role", "viewer"), "attempts": 0}, cfg)
    for _ in range(3):
        if not output.get("__interrupt__"):
            break
        resume_cfg = {**cfg, "run_id": uuid.uuid4(), "run_name": f"golden {case['id']} approve"}
        output = graph.invoke(Command(resume={"action": "approve"}), resume_cfg)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    tokens = errors.tokens
    if output.get("needs_clarification"):
        result = {"kind": "clarify", "sql": None}
    elif output.get("refused") or output.get("status") != "complete":
        result = {"kind": "refuse", "sql": None}
    else:
        result = {"kind": "sql", "sql": output["sql"]}
    # A refusal caused by an API failure is not the model's answer: mark it as an error, not a fail.
    provider_failed = bool(errors.errors) and output.get("status") in ("error", "give_up", "provider_error")
    return result, {"run_id": str(run_id), "status": output.get("status"), "attempts": output.get("attempts", 0),
                    "model_calls": output.get("model_calls", 0), "tokens": tokens, "ms": elapsed_ms,
                    "api_errors": errors.errors, "provider_failed": provider_failed}


# ---------------------------------------------------------------------------- reporting
def summarize(records, meta):
    graded = [r for r in records if r["outcome"] in ("PASS", "FAIL")]
    answerable = [r for r in graded if r["kind"] in ("sql", "row_limit")]
    behaviour = [r for r in graded if r["kind"] not in ("sql", "row_limit")]
    errors = [r for r in records if r["outcome"] == "ERROR"]
    passed = sum(r["outcome"] == "PASS" for r in answerable)
    first_try = sum(r["outcome"] == "PASS" and r["attempts"] <= 1 for r in answerable)
    after_retry = sum(r["outcome"] == "PASS" and r["attempts"] > 1 for r in answerable)
    beh_passed = sum(r["outcome"] == "PASS" for r in behaviour)
    lo, hi = wilson(passed, len(answerable))
    lat = sorted(r["ms"] for r in graded)
    tok = [r["tokens"]["total"] for r in graded if r["tokens"]["total"]]
    calls = [r["model_calls"] for r in graded]
    by_cat = defaultdict(lambda: [0, 0])
    for r in graded:
        by_cat[r["category"]][0] += r["outcome"] == "PASS"
        by_cat[r["category"]][1] += 1

    s = {
        "run": meta, "graded": len(graded), "errors_not_counted": len(errors),
        "answerable": {"passed": passed, "total": len(answerable),
                       "accuracy": passed / len(answerable) if answerable else None,
                       "ci95": [lo, hi], "first_try": first_try, "after_retry": after_retry},
        "behaviour": {"passed": beh_passed, "total": len(behaviour)},
        "latency_ms": {"median": statistics.median(lat) if lat else None,
                       "p90": lat[min(len(lat) - 1, int(0.9 * len(lat)))] if lat else None},
        "tokens_per_question": {"mean": int(statistics.mean(tok)) if tok else None, "total": sum(tok)},
        "model_calls_per_question": round(statistics.mean(calls), 2) if calls else None,
        "by_category": {k: {"passed": v[0], "total": v[1]} for k, v in sorted(by_cat.items())},
        "failures": [{"id": r["id"], "category": r["category"], "reason": r["reason"]}
                     for r in graded if r["outcome"] == "FAIL"],
    }

    a = s["answerable"]
    lines = [
        f"# ColdChain assistant: golden-set results ({meta['name']})", "",
        f"Model `{meta['model']}` on Groq | commit `{meta['commit']}` | {meta['finished']} | "
        f"LangSmith project `{meta['langsmith_project']}`", "",
        "## Headline numbers", "",
        "| Measure | Result |", "|---|---|",
    ]
    if a["total"]:
        lines.append(f"| Correct answers (result rows match the reference query) | **{a['passed']}/{a['total']} "
                     f"({pct(a['accuracy'])})**, 95% range {pct(lo)}-{pct(hi)} |")
        lines.append(f"| Correct on the first try / after a self-correction retry | {first_try} / {after_retry} |")
    if behaviour:
        lines.append(f"| Safety and behaviour (clarify, decline, block, access control) | **{beh_passed}/{len(behaviour)}** |")
    if lat:
        lines.append(f"| Time per question, median / 90th percentile | {s['latency_ms']['median'] / 1000:.1f} s / "
                     f"{s['latency_ms']['p90'] / 1000:.1f} s |")
    if tok:
        lines.append(f"| Tokens per question (average) / whole run | {s['tokens_per_question']['mean']:,} / "
                     f"{s['tokens_per_question']['total']:,} |")
    if calls:
        lines.append(f"| Model calls per question (average) | {s['model_calls_per_question']} |")
    if errors:
        lines.append(f"| API errors (rate limits), not counted as right or wrong | {len(errors)} |")
    lines += ["", "## By category", "", "| Category | Passed |", "|---|---|"]
    lines += [f"| {k} | {v['passed']}/{v['total']} |" for k, v in s["by_category"].items()]
    lines += ["", "## Questions it got wrong", ""]
    lines += [f"- **{f['id']}** ({f['category']}): {f['reason']}" for f in s["failures"]] or ["- none"]
    lines += ["", "## How to read these numbers", "",
              f"- {a['total']} answerable questions is a small sample: the 95% range above is the honest error bar.",
              "- Grading is strict: the SQL is executed and its rows must equal the reference query's rows.",
              "- Model output varies between runs; record the model and date with any number you quote.",
              f"- {EVAL_TODAY_NOTE}",
              "- Behaviour cases check the kind of response (clarified, declined, blocked), not its wording."]
    return s, "\n".join(lines) + "\n"


def load_existing(path):
    if not path.exists():
        return {}
    done = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            done[r["id"]] = r
    return done


def attach_feedback(records):
    """Adds a 'correct' score (1/0) and the reason to each question's LangSmith trace."""
    if not tracing_enabled():
        print("LangSmith: tracing is off or no key, so no traces or scores were recorded.")
        return
    from langchain_core.tracers.langchain import wait_for_all_tracers
    from langsmith import Client
    wait_for_all_tracers()
    client, ok, failed = Client(), 0, 0
    for r in records:
        if r["outcome"] not in ("PASS", "FAIL") or r.get("feedback_sent"):
            continue
        try:
            client.create_feedback(run_id=r["run_id"], trace_id=r["run_id"], key="correct",
                                   score=1 if r["outcome"] == "PASS" else 0,
                                   comment=r["reason"] or "result rows match the reference query")
            client.create_feedback(run_id=r["run_id"], trace_id=r["run_id"], key="model_calls",
                                   score=r["model_calls"])
            r["feedback_sent"] = True
            ok += 1
        except Exception as exc:
            failed += 1
            print(f"LangSmith: could not score {r['id']} ({type(exc).__name__})")
    print(f"LangSmith: scored {ok} traces in project '{ARGS.langsmith_project}'" + (f", {failed} failed" if failed else ""))


# ---------------------------------------------------------------------------- main
def main():
    golden = json.loads((ROOT / "golden_eval/golden.json").read_text(encoding="utf-8"))["cases"]
    by_id = {c["id"]: c for c in golden}
    ids = ARGS.ids.split(",") if ARGS.ids else (PRESENTATION_IDS if ARGS.subset == "presentation" else list(by_id))
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        sys.exit(f"Unknown golden ids: {unknown}")
    cases = [by_id[i] for i in ids]

    from coldchain_context import get_coldchain_engine
    engine = get_coldchain_engine()
    _, _, _, _, model_name = provider_settings()

    # Free checks first: the reference queries must reproduce on this database before anything is graded.
    print(f"Checking {len(cases)} reference queries on the database (no model calls)...")
    for c in cases:
        if c["kind"] == "sql":
            rows = run_eval.run_sql(engine, c["gold_sql"])
            if len(rows) != c["expected_row_count"]:
                sys.exit(f"STOP: reference query {c['id']} returned {len(rows)} rows, expected "
                         f"{c['expected_row_count']}. The database does not match the golden data.")
    print("Reference queries OK.")

    traps = [c for c in cases if c["kind"] == "sql" and c.get("wrong_sql")]
    caught = sum(not run_eval.grade(c, {"kind": "sql", "sql": c["wrong_sql"]}, engine, validate)[0] for c in traps)
    print(f"Grader check: {caught}/{len(traps)} planted common-mistake queries are graded wrong (should be all).")
    if caught != len(traps):
        sys.exit("STOP: the grader accepted a planted mistake; results would not be trustworthy.")

    print(f"LangSmith: {'ON' if tracing_enabled() else 'OFF'}; project '{ARGS.langsmith_project}'; "
          f"trace text {'hidden' if ARGS.hide_trace_text else 'shown'}. Model: {model_name}.")
    if ARGS.dry_run:
        print("Dry run finished: no model calls were made.")
        return 0

    OUT_DIR.mkdir(exist_ok=True)
    store = OUT_DIR / f"{ARGS.name}.jsonl"
    done = load_existing(store) if ARGS.resume else {}
    if store.exists() and not ARGS.resume:
        store.rename(store.with_suffix(f".jsonl.old-{int(time.time())}"))
    records = {k: v for k, v in done.items() if v["outcome"] != "ERROR"}
    todo = [c for c in cases if c["id"] not in records]
    print(f"{len(records)} already graded, {len(todo)} to run. Pausing between questions to stay under "
          f"{ARGS.tpm_budget:,} tokens/minute.\n")

    pacer, consecutive_errors, stopped = TokenPacer(ARGS.tpm_budget), 0, None
    for n, case in enumerate(todo, 1):
        pacer.wait()
        try:
            pred, info = predict(case, model_name, ARGS.name)
        except Exception as exc:
            pred, info = {"kind": "refuse", "sql": None}, {"run_id": "", "status": "crash", "attempts": 0,
                         "model_calls": 0, "tokens": {"input": 0, "output": 0, "total": 0}, "ms": 0,
                         "api_errors": [type(exc).__name__], "provider_failed": True}
        pacer.add(info["tokens"]["total"], n - 1)
        if info["provider_failed"]:
            outcome, reason = "ERROR", f"API error ({', '.join(info['api_errors'])}); not counted"
            consecutive_errors += 1
        else:
            consecutive_errors = 0
            try:
                ok, why = run_eval.grade(case, pred, engine, validate)
            except Exception as exc:
                ok, why = False, f"grading error: {type(exc).__name__}"
            outcome, reason = ("PASS" if ok else "FAIL"), ("" if ok else why)
        record = {"id": case["id"], "category": case["category"], "kind": case["kind"], "outcome": outcome,
                  "reason": reason, "question": case["question"], "predicted_kind": pred.get("kind"),
                  "predicted_sql": pred.get("sql") or "", **info}
        records[case["id"]] = record
        with store.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        print(f"[{n}/{len(todo)}] {outcome:<5} {case['id']:<4} {case['category']:<20} "
              f"{info['ms'] / 1000:5.1f}s {info['tokens']['total']:>6} tok  attempts={info['attempts']}  {reason}")
        if consecutive_errors >= ARGS.max_consecutive_errors:
            stopped = ("daily_limit" in info["api_errors"] and "Groq's daily token limit was reached") or \
                      "repeated API errors"
            break

    ordered = [records[i] for i in ids if i in records]
    attach_feedback(ordered)
    store.write_text("".join(json.dumps(r) + "\n" for r in ordered), encoding="utf-8")
    meta = {"name": ARGS.name, "model": model_name, "commit": git_commit(),
            "finished": datetime.now().strftime("%Y-%m-%d %H:%M"), "langsmith_project": ARGS.langsmith_project,
            "questions_planned": len(ids)}
    summary, markdown = summarize(ordered, meta)
    (OUT_DIR / f"{ARGS.name}_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (OUT_DIR / f"{ARGS.name}_summary.md").write_text(markdown, encoding="utf-8")
    print("\n" + markdown)
    remaining = [i for i in ids if i not in records or records[i]["outcome"] == "ERROR"]
    if stopped or remaining:
        print(f"STOPPED EARLY: {stopped or 'some questions had API errors'}. {len(remaining)} question(s) not graded: "
              f"{','.join(remaining)}.\nRerun the same command with --resume once the limit resets.")
        return 2
    print(f"Results: eval_runs/{ARGS.name}_summary.md, eval_runs/{ARGS.name}_summary.json, eval_runs/{ARGS.name}.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
