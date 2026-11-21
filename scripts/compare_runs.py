"""Compare two evaluation runs of the same golden questions: how consistent is the model between runs?

Run from the project root (PowerShell, one line):
    $env:PYTHONIOENCODING="utf-8"; .\\venv\\Scripts\\python.exe scripts\\compare_runs.py presentation presentation_run3

Reads eval_runs/<A>.jsonl and eval_runs/<B>.jsonl (written by presentation_eval.py).
Writes eval_runs/consistency.md and eval_runs/consistency.json (eval_report_pdf.py adds a page from it).
No AI calls, no database access, no cost.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "eval_runs"
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass


def load(name):
    path = OUT / f"{name}.jsonl"
    if not path.exists():
        sys.exit(f"Missing {path.relative_to(ROOT).as_posix()}: run presentation_eval.py --name {name} first.")
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {r["id"]: r for r in records}


def main():
    if len(sys.argv) != 3:
        sys.exit("Usage: compare_runs.py RUN_A RUN_B   (names of eval_runs/*.jsonl files)")
    name_a, name_b = sys.argv[1], sys.argv[2]
    run_a, run_b = load(name_a), load(name_b)
    shared = [i for i in run_a if i in run_b
              and run_a[i]["outcome"] in ("PASS", "FAIL") and run_b[i]["outcome"] in ("PASS", "FAIL")]
    if not shared:
        sys.exit("The two runs share no graded questions.")

    rows, counts = [], {"both_pass": 0, "both_fail": 0, "pass_to_fail": 0, "fail_to_pass": 0}
    for i in shared:
        a, b = run_a[i]["outcome"], run_b[i]["outcome"]
        key = {("PASS", "PASS"): "both_pass", ("FAIL", "FAIL"): "both_fail",
               ("PASS", "FAIL"): "pass_to_fail", ("FAIL", "PASS"): "fail_to_pass"}[(a, b)]
        counts[key] += 1
        same_sql = (run_a[i].get("predicted_sql") or "").split() == (run_b[i].get("predicted_sql") or "").split()
        rows.append({"id": i, "category": run_a[i]["category"], "kind": run_a[i]["kind"], "a": a, "b": b,
                     "same_sql": same_sql, "question": run_a[i]["question"]})

    sql_rows = [r for r in rows if r["kind"] in ("sql", "row_limit")]
    n = len(sql_rows)
    acc = lambda run: sum(run[r["id"]]["outcome"] == "PASS" for r in sql_rows) / n if n else None
    consistent = sum(r["a"] == r["b"] for r in rows)
    failures = []
    for label, run in ((name_a, run_a), (name_b, run_b)):
        for r in sql_rows:
            rec = run[r["id"]]
            if rec["outcome"] == "FAIL":
                failures.append({"run": label, "id": r["id"], "category": r["category"], "reason": rec["reason"],
                                 "sql": rec.get("predicted_sql") or ""})

    summary = {
        "runs": [name_a, name_b], "questions_compared": len(rows), "sql_questions": n,
        "accuracy": {name_a: acc(run_a), name_b: acc(run_b)},
        "mean_accuracy": (acc(run_a) + acc(run_b)) / 2 if n else None,
        "same_outcome": consistent, "same_outcome_rate": consistent / len(rows),
        "always_correct": sum(r["a"] == r["b"] == "PASS" for r in sql_rows),
        "never_correct": sum(r["a"] == r["b"] == "FAIL" for r in sql_rows),
        "flipped": [r["id"] for r in rows if r["a"] != r["b"]],
        "identical_sql": sum(r["same_sql"] for r in sql_rows),
        "counts": counts, "rows": rows, "failures": failures,
    }
    (OUT / "consistency.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    pct = lambda x: f"{100 * x:.0f}%"
    lines = [f"# Consistency: {name_a} vs {name_b}", "",
             "| Measure | Result |", "|---|---|",
             f"| SQL accuracy, {name_a} / {name_b} | {pct(acc(run_a))} / {pct(acc(run_b))} |",
             f"| Mean SQL accuracy over both runs | {pct(summary['mean_accuracy'])} |",
             f"| Same outcome in both runs (all {len(rows)} questions) | {consistent}/{len(rows)} "
             f"({pct(summary['same_outcome_rate'])}) |",
             f"| SQL questions correct in both runs / wrong in both | {summary['always_correct']} / "
             f"{summary['never_correct']} (of {n}) |",
             f"| Flipped between runs | {', '.join(summary['flipped']) or 'none'} |",
             f"| Identical SQL text in both runs | {summary['identical_sql']}/{n} |", "",
             "| ID | Category | " + name_a + " | " + name_b + " | Same SQL |", "|---|---|---|---|---|"]
    lines += [f"| {r['id']} | {r['category']} | {r['a']} | {r['b']} | {'yes' if r['same_sql'] else 'no'} |" for r in rows]
    lines += ["", "## SQL behind every wrong answer", ""]
    for f in failures:
        lines += [f"**{f['id']}** ({f['category']}, run {f['run']}): {f['reason']}", "", "```sql", f["sql"], "```", ""]
    lines += ["Two runs show whether results are stable; they are not enough to give a precise variance."]
    text = "\n".join(lines) + "\n"
    (OUT / "consistency.md").write_text(text, encoding="utf-8")
    print(text)
    print("Written: eval_runs/consistency.md, eval_runs/consistency.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
