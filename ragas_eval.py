"""Partial-credit scoring of saved golden-set results with Ragas DataCompyScore. No LLM calls.

Step 1: python golden_eval/run_eval.py --predictor ... --out eval_results.csv   (strict pass/fail)
Step 2: python ragas_eval.py --results eval_results.csv --db-url <read-only URL>      (partial credit)

Why this wrapper exists: DataCompyScore compares row i with row i and column name with column name.
Model SQL rarely uses the gold column names or row order, so without alignment every case scores 0.
This module renames columns by matching values, sorts unordered results, then scores.
Install the optional extras first: pip install -r requirements-eval.txt
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _strict_grader():
    if str(ROOT / "golden_eval") not in sys.path:
        sys.path.insert(0, str(ROOT / "golden_eval"))
    import run_eval
    return run_eval


def _norm(value):
    """Same normalisation as the strict grader, so both scores agree on what 'equal' means."""
    return _strict_grader()._norm(value)


def align(gold_rows, pred_rows, ordered=False):
    """Return (gold_csv, pred_csv) with predicted columns renamed to match gold columns.

    Matching order: identical value multiset first, then the same position if still free.
    Extra predicted columns are dropped, as the strict grader allows extra columns."""
    gold = [tuple(_norm(v) for v in row) for row in gold_rows]
    pred = [tuple(_norm(v) for v in row) for row in pred_rows]
    width = len(gold[0]) if gold else 0
    pred_width = len(pred[0]) if pred else 0
    column = lambda rows, i: Counter(row[i] for row in rows)
    mapping, used = {}, set()
    for i in range(width):
        for j in range(pred_width):
            if j not in used and column(gold, i) == column(pred, j):
                mapping[i] = j
                used.add(j)
                break
    for i in range(width):
        if i not in mapping and i < pred_width and i not in used:
            mapping[i] = i
            used.add(i)
    names = [f"c{i}" for i in range(width)]
    gold_table = [list(row) for row in gold]
    pred_table = [[row[mapping[i]] if i in mapping else None for i in range(width)] for row in pred]
    if not ordered:
        key = lambda row: tuple("" if v is None else v for v in row)
        gold_table.sort(key=key)
        pred_table.sort(key=key)
    return _csv(names, gold_table), _csv(names, pred_table)


def _csv(names, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(names)
    writer.writerows(["" if v is None else v for v in row] for row in rows)
    return buffer.getvalue()


async def score_pair(gold_csv, pred_csv):
    try:
        from ragas.metrics.collections import DataCompyScore
    except ImportError as exc:
        raise SystemExit("Ragas is not installed. Run: pip install -r requirements-eval.txt") from exc
    rows_f1 = await DataCompyScore(mode="rows", metric="f1").ascore(reference=gold_csv, response=pred_csv)
    cols_recall = await DataCompyScore(mode="columns", metric="recall").ascore(reference=gold_csv, response=pred_csv)
    clean = lambda result: None if result.value is None or math.isnan(result.value) else round(float(result.value), 3)
    return {"rows_f1": clean(rows_f1), "columns_recall": clean(cols_recall)}


def evaluate(results_rows, cases, engine, validator, run_sql):
    by_id = {case["id"]: case for case in cases}
    report = []
    for row in results_rows:
        case = by_id.get(row["id"])
        if not case or case["kind"] != "sql":
            continue  # refuse/clarify/unsafe/row_limit have no gold rows: strict grading only
        entry = {"id": row["id"], "category": case["category"], "strict_pass": str(row["pass"]).lower() == "true"}
        sql = row.get("predicted_sql") or ""
        if not sql.strip():
            report.append({**entry, "rows_f1": 0.0, "columns_recall": 0.0, "note": "no SQL predicted"})
            continue
        try:
            predicted = run_sql(engine, validator(sql, case.get("role", "viewer")))
            gold = run_sql(engine, case["gold_sql"])
        except Exception as exc:
            report.append({**entry, "rows_f1": 0.0, "columns_recall": 0.0, "note": f"execution failed: {type(exc).__name__}"})
            continue
        gold_csv, pred_csv = align(gold, predicted, case.get("ordered", False))
        report.append({**entry, **asyncio.run(score_pair(gold_csv, pred_csv)), "note": ""})
    return report


def summarize(report):
    mean = lambda values: round(sum(values) / len(values), 3) if values else None
    by_category = defaultdict(list)
    for item in report:
        by_category[item["category"]].append(item)
    section = lambda items: {"cases": len(items),
                             "strict_pass_rate": mean([float(i["strict_pass"]) for i in items]),
                             "mean_rows_f1": mean([i["rows_f1"] for i in items if i["rows_f1"] is not None]),
                             "mean_columns_recall": mean([i["columns_recall"] for i in items if i["columns_recall"] is not None]),
                             "near_misses": sum((not i["strict_pass"]) and (i["rows_f1"] or 0) >= 0.5 for i in items)}
    return {"overall": section(report), "by_category": {k: section(v) for k, v in sorted(by_category.items())}}


def write_reports(report, summary, out_prefix):
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    Path(f"{out_prefix}.json").write_text(json.dumps({"generated": stamp, "summary": summary, "cases": report}, indent=2), encoding="utf-8")
    lines = [f"# Golden-set partial credit ({stamp})", "",
             "Strict pass = exact result match. Rows F1 / column recall = Ragas DataCompyScore after column alignment.",
             "", "| Category | Cases | Strict pass | Rows F1 | Column recall | Near misses |", "|---|---|---|---|---|---|"]
    for name, data in [("**Overall**", summary["overall"])] + list(summary["by_category"].items()):
        lines.append(f"| {name} | {data['cases']} | {data['strict_pass_rate']} | {data['mean_rows_f1']} | "
                     f"{data['mean_columns_recall']} | {data['near_misses']} |")
    Path(f"{out_prefix}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", default="eval_results.csv", help="CSV written by golden_eval/run_eval.py")
    parser.add_argument("--golden", default=str(ROOT / "golden_eval" / "golden.json"))
    parser.add_argument("--db-url", required=True, help="read-only ColdChain URL")
    parser.add_argument("--out", default="ragas_report", help="writes <out>.json and <out>.md")
    args = parser.parse_args()
    grader = _strict_grader()
    run_sql, default_validator = grader.run_sql, grader.default_validator
    from sqlalchemy import create_engine
    with open(args.results, newline="", encoding="utf-8") as handle:
        results_rows = list(csv.DictReader(handle))
    cases = json.loads(Path(args.golden).read_text(encoding="utf-8"))["cases"]
    engine = create_engine(args.db_url, pool_pre_ping=True)
    report = evaluate(results_rows, cases, engine, default_validator, run_sql)
    summary = summarize(report)
    write_reports(report, summary, args.out)
    print(json.dumps(summary["overall"], indent=2))
    print(f"Reports written to {args.out}.json and {args.out}.md")


if __name__ == "__main__":
    main()
