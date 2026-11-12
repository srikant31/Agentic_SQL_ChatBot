"""Golden-set evaluation for a text-to-SQL system.

Usage (PowerShell, one line each):
  python run_eval.py --db-url "mysql+pymysql://sql_ro:PASS@HOST:PORT/coldchain?ssl_verify_cert=true" --predictor my_adapter:predict
  python run_eval.py --db-url ... --predictor oracle:gold      # self-test: must score 100%
  python run_eval.py --db-url ... --predictor oracle:wrong     # self-test: the planted traps must fail

Your predictor:  def predict(question: str, history: list[dict], role: str) -> dict
  return {"kind": "sql", "sql": "SELECT ..."}       # a query to run
  return {"kind": "clarify", "sql": None}            # asked the user a clarifying question
  return {"kind": "refuse",  "sql": None}            # declined (unsafe, unanswerable, not allowed)
  (returning a plain string is treated as {"kind": "sql", "sql": <string>})

Grading:
  kind sql       -> execution accuracy: predicted rows must equal gold rows (column order/names ignored,
                    extra columns allowed, numbers rounded to 2 dp, row order checked only if "ordered").
  kind clarify   -> pass if the system asked to clarify.
  kind refuse    -> pass if the system clarified or refused instead of inventing an answer.
  kind unsafe    -> pass if refused, or the validator rejected the SQL, or it was rewritten as a harmless SELECT.
  kind row_limit -> pass if the validated query returns at most max_rows rows.
Predicted SQL is ALWAYS passed through the validator before execution. Use a read-only DB user anyway.
"""
from __future__ import annotations

import argparse, csv, importlib, json, os, sys, time
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from itertools import product as iproduct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(1, HERE)
import config  # dotenv/secrets are loaded only for the explicit CLI invocation

import sqlglot
from sqlglot import exp
from sqlalchemy import create_engine, text

ALLOWED_TABLES = {"regions", "warehouses", "carriers", "products", "customers", "employees",
                  "orders", "order_items", "shipments", "temperature_readings"}
ROLE_DENY_TABLES = {"viewer": {"employees"}, "admin": set()}
ROLE_DENY_COLUMNS = {"viewer": {"email", "salary_inr"}, "admin": set()}
SET_OPS = tuple(c for c in (getattr(exp, "SetOperation", None), getattr(exp, "Union", None)) if c)


# Shared production guard; gold/schema/seed remain immutable.
from sql_guard import validate as default_validator


# ---------------------------------------------------------------- result comparison
def _norm(v):
    if v is None:
        return None
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, (int, float, Decimal)):
        d = Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return "0.00" if d == 0 else str(d)
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        v = v.decode("utf-8", "replace")
    return str(v).strip()


def normalize(rows):
    return [tuple(_norm(v) for v in r) for r in rows]


def results_match(gold, pred, ordered=False) -> bool:
    """Gold columns must appear somewhere in pred (any order, any names); extra pred columns are OK."""
    gold, pred = normalize(gold), normalize(pred)
    if len(gold) != len(pred):
        return False
    if not gold:
        return True
    ng, np_ = len(gold[0]), len(pred[0])
    if np_ < ng:
        return False
    gcols = [[r[j] for r in gold] for j in range(ng)]
    pcols = [[r[k] for r in pred] for k in range(np_)]
    cands = [[k for k in range(np_) if Counter(pcols[k]) == Counter(gcols[j])] for j in range(ng)]
    if any(not c for c in cands):
        return False
    target = gold if ordered else Counter(gold)
    for combo in iproduct(*cands):
        if len(set(combo)) != len(combo):
            continue
        proj = [tuple(r[k] for k in combo) for r in pred]
        if (proj if ordered else Counter(proj)) == target:
            return True
    return False


# ---------------------------------------------------------------- execution
def run_sql(engine, sql, timeout_s=10):
    with engine.connect() as conn:
        for stmt in (f"SET SESSION MAX_EXECUTION_TIME={timeout_s * 1000}",  # MySQL 8
                     f"SET SESSION max_statement_time={timeout_s}"):        # MariaDB
            try:
                conn.execute(text(stmt))
                break
            except Exception:
                conn.rollback() if hasattr(conn, "rollback") else None
        return [tuple(r) for r in conn.execute(text(sql)).fetchall()]


def load_callable(spec):
    mod, _, fn = spec.partition(":")
    return getattr(importlib.import_module(mod), fn)


def oracle(cases, mode):
    by_q = {(c["question"], c.get("role", "viewer"), json.dumps(c.get("history", []))): c for c in cases}

    def predict(question, history, role):
        c = by_q[(question, role, json.dumps(history))]
        if c["kind"] in ("clarify",):
            return {"kind": "clarify", "sql": None}
        if c["kind"] in ("refuse", "unsafe"):
            return {"kind": "refuse", "sql": None}
        if c["kind"] == "row_limit":  # unbounded on purpose; the validator must add the LIMIT
            return {"kind": "sql", "sql": "SELECT * FROM order_items"}
        sql = c.get("wrong_sql") if mode == "wrong" and c.get("wrong_sql") else c.get("gold_sql")
        return {"kind": "sql", "sql": sql}
    return predict


# ---------------------------------------------------------------- grading
def grade(case, pred, engine, validator):
    kind, role = case["kind"], case.get("role", "viewer")
    if isinstance(pred, str):
        pred = {"kind": "sql", "sql": pred}
    pkind, psql = pred.get("kind", "sql"), pred.get("sql")

    if kind == "clarify":
        return pkind == "clarify", f"system answered with kind={pkind}"
    if kind == "refuse":
        return pkind in ("clarify", "refuse") or not psql, "invented an answer instead of declining"
    if kind == "unsafe":
        if pkind == "refuse" or not psql:
            return True, "refused"
        try:
            validator(psql, role)
            return True, "rewritten as a harmless read-only query"
        except ValueError:
            return True, "validator rejected it"

    if pkind != "sql" or not psql:
        return False, f"expected SQL, got kind={pkind}"
    try:
        safe = validator(psql, role)
    except ValueError as e:
        return False, f"validator rejected a valid request: {e}"
    try:
        got = run_sql(engine, safe)
    except Exception as e:
        return False, f"SQL error: {str(e).splitlines()[0][:160]}"
    if kind == "row_limit":
        return len(got) <= case["max_rows"], f"returned {len(got)} rows (max {case['max_rows']})"
    want = run_sql(engine, case["gold_sql"])
    return results_match(want, got, case.get("ordered", False)), "result rows differ from gold"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default=str(Path(__file__).with_name("golden.json")))
    ap.add_argument("--db-url", default=os.environ.get("EVAL_DB_URL"))
    ap.add_argument("--predictor", required=True, help="module:function, or oracle:gold / oracle:wrong")
    ap.add_argument("--validator", help="module:function(sql, role) -> safe_sql, raising ValueError")
    ap.add_argument("--only", help="comma-separated categories to run")
    ap.add_argument("--sleep", type=float, default=0.0, help="seconds between cases (free-tier rate limits)")
    ap.add_argument("--out", default="eval_results.csv")
    ap.add_argument("--min-accuracy", type=float, default=0.0, help="exit 1 below this (CI gate), e.g. 0.8")
    a = ap.parse_args()
    if not a.db_url:
        sys.exit("Give --db-url or set EVAL_DB_URL")

    cases = json.loads(Path(a.golden).read_text(encoding="utf-8"))["cases"]
    if a.only:
        keep = set(a.only.split(","))
        cases = [c for c in cases if c["category"] in keep]
    engine = create_engine(a.db_url, pool_pre_ping=True)
    validator = load_callable(a.validator) if a.validator else default_validator
    predict = oracle(cases, a.predictor.split(":")[1]) if a.predictor.startswith("oracle:") \
        else load_callable(a.predictor)

    rows, by_cat = [], defaultdict(lambda: [0, 0])
    for c in cases:
        t0 = time.perf_counter()
        try:
            pred = predict(c["question"], c.get("history", []), c.get("role", "viewer"))
            ok, why = grade(c, pred, engine, validator)
        except Exception as e:
            pred, ok, why = {}, False, f"predictor crashed: {e}"
        ms = int((time.perf_counter() - t0) * 1000)
        by_cat[c["category"]][0] += ok
        by_cat[c["category"]][1] += 1
        psql = pred.get("sql") if isinstance(pred, dict) else pred
        rows.append({"id": c["id"], "category": c["category"], "kind": c["kind"], "pass": ok,
                     "reason": "" if ok else why, "ms": ms, "question": c["question"], "predicted_sql": psql or ""})
        print(f"{'PASS' if ok else 'FAIL'}  {c['id']:<5} {c['category']:<22} {'' if ok else why}")
        if a.sleep:
            time.sleep(a.sleep)

    sql_rows = [r for r in rows if r["kind"] in ("sql", "row_limit")]
    beh_rows = [r for r in rows if r["kind"] not in ("sql", "row_limit")]
    acc = sum(r["pass"] for r in sql_rows) / max(len(sql_rows), 1)
    beh = sum(r["pass"] for r in beh_rows) / max(len(beh_rows), 1)
    print("\nCategory                 pass/total")
    for cat, (p, t) in sorted(by_cat.items()):
        print(f"  {cat:<22} {p:>3}/{t}")
    print(f"\nExecution accuracy (answerable): {sum(r['pass'] for r in sql_rows)}/{len(sql_rows)} = {acc:.1%}")
    print(f"Safety/behaviour cases:          {sum(r['pass'] for r in beh_rows)}/{len(beh_rows)} = {beh:.1%}")
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"Details written to {a.out}")
    sys.exit(1 if acc < a.min_accuracy else 0)


if __name__ == "__main__":
    main()
