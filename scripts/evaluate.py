"""Offline fixture checks by default; --live-llm explicitly enables paid provider calls.

Run from the repository root: python scripts/evaluate.py --mode D --split heldout
"""
import argparse
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine

from business_context import load_business_rules
from context_pipeline import execute_proposal, prepare_context, prepare_proposal
from database import initialize_demo, run_query
from rbac import USERS
from semantic_validation import validate_sql
from sql_examples import load_examples
from sql_generator import provider_settings
from utils import compare_result_rows as compare_rows
from context_models import fingerprint
from business_context import RULES_PATH


def load_cases(path=ROOT / "evaluation" / "questions.jsonl"):
    return tuple(json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip())


def check_leakage(cases, examples):
    """Keep reviewed demonstrations and their paraphrases out of held-out families."""
    from sqlglot import parse_one
    def normalized(sql):
        return parse_one(sql, read="sqlite").sql(dialect="sqlite", normalize=True)
    questions = {example["question"].strip().lower().rstrip(".?") for example in examples}
    families = {example["template_family"] for example in examples}
    statements = {normalized(example["sql"]) for example in examples}
    for case in cases:
        if case["split"] != "heldout":
            continue
        if (case["template_family"] in families
            or case["question"].strip().lower().rstrip(".?") in questions
            or (case.get("gold_sql") and normalized(case["gold_sql"]) in statements)):
            raise ValueError(f"Held-out example leakage in {case['id']}; move the entire semantic family to development.")


def evaluate(*, mode="D", split="heldout", live_llm=False, cases=None,
             input_price_per_million=None, output_price_per_million=None):
    all_cases = tuple(cases if cases is not None else load_cases())
    check_leakage(all_cases, load_examples())
    selected = [case for case in all_cases if split == "all" or case["split"] == split]
    engine = create_engine("sqlite:///:memory:")
    initialize_demo(engine)  # Disposable local fixture only. Never initialize the live service here.
    records = []
    try:
        for case in selected:
            started = time.perf_counter()
            record = {"id": case["id"], "category": case["category"], "correct": False,
                      "execution_success": None, "usage": {}}
            try:
                user = USERS[case["role"]]
                context = prepare_context(case["question"], user, engine, mode=mode)
                record["action"] = context.intent.status
                record["context_characters"] = len(context.prompt_context)
                record["estimated_context_tokens"] = (len(context.prompt_context) + 3) // 4
                record["example_ids"] = [example["id"] for example in context.examples]
                record["context_version"] = context.version
                if context.intent.status == "query":
                    wanted_tables = set(case.get("gold_tables", ()))
                    selected_tables = {table.name for table in context.catalog.tables}
                    required_rules = set(case.get("required_rules", ()))
                    selected_rules = {rule.id for rule in context.rules}
                    record["table_context_recall"] = len(wanted_tables & selected_tables) / len(wanted_tables) if wanted_tables else None
                    record["rule_context_recall"] = len(required_rules & selected_rules) / len(required_rules) if required_rules else None
                if live_llm:
                    proposal = prepare_proposal(case["question"], user, engine, mode=mode)
                    action = "query" if proposal["status"] == "proposal" else proposal["status"]
                    record["action"] = action
                    record["usage"] = proposal.get("usage", {})
                    if action == "query":
                        _, rows = execute_proposal(proposal, user, engine)
                        record["execution_success"] = True
                        record["correct"] = case["expected_action"] == "query" and compare_rows(rows, case["expected_rows"], ordered="ORDER BY" in case.get("gold_sql", "").upper())
                    else:
                        record["correct"] = action == case["expected_action"]
                elif case["expected_action"] == "query":
                    # This checks the reviewed oracle and deterministic contracts, not LLM accuracy.
                    validate_sql(case["gold_sql"], context.catalog, context.intent, load_business_rules(context.catalog, user))
                    _, rows = run_query(case["gold_sql"], user, engine)
                    record["execution_success"] = True
                    record["correct"] = context.intent.status == "query" and compare_rows(rows, case["expected_rows"], ordered="ORDER BY" in case["gold_sql"].upper())
                else:
                    record["correct"] = context.intent.status == case["expected_action"]
            except Exception as exc:
                record["error_type"] = type(exc).__name__
                if case["expected_action"] == "query":
                    record["execution_success"] = False
            record["seconds"] = time.perf_counter() - started
            records.append(record)
    finally:
        engine.dispose()
    latencies = sorted(record["seconds"] for record in records)
    usages = [record["usage"] for record in records]
    usage_available = any(usage for usage in usages)
    input_tokens = sum(usage.get("input_tokens", 0) for usage in usages)
    output_tokens = sum(usage.get("output_tokens", 0) for usage in usages)
    cost = ((input_tokens * input_price_per_million + output_tokens * output_price_per_million) / 1_000_000
            if usage_available and input_price_per_million is not None and output_price_per_million is not None else None)
    executions = [record["execution_success"] for record in records if record["execution_success"] is not None]
    return {"mode": mode, "split": split,
            "provider": provider_settings()[0],
            "model": provider_settings()[4],
            "dataset_version": fingerprint(all_cases),
            "example_corpus_version": fingerprint(load_examples()),
            "business_file_version": fingerprint(RULES_PATH.read_text(encoding="utf-8")),
            "measurement": "live_llm_fixture_evaluation" if live_llm else "offline_contract_and_oracle_checks_not_llm_accuracy",
            "fixture": "fictional-employees-v1", "cases": len(records),
            "passed": sum(record["correct"] for record in records),
            "execution_success_rate": sum(executions) / len(executions) if executions else None,
            "p50_seconds": statistics.median(latencies) if latencies else None,
            "p95_seconds": latencies[min(len(latencies)-1, math.ceil(len(latencies)*.95)-1)] if latencies else None,
            "actual_input_tokens": input_tokens if usage_available else None,
            "actual_output_tokens": output_tokens if usage_available else None,
            "estimated_api_cost": cost,
            "cost_basis": "Caller-supplied per-million rates and reported usage; unreported or failed-call usage is excluded.",
            "results": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=list("ABCD"), default="D")
    parser.add_argument("--split", choices=["heldout", "development", "all"], default="heldout")
    parser.add_argument("--live-llm", action="store_true", help="Make real provider calls against disposable fixture data; may incur API charges.")
    parser.add_argument("--input-price-per-million", type=float)
    parser.add_argument("--output-price-per-million", type=float)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(mode=args.mode, split=args.split, live_llm=args.live_llm,
                      input_price_per_million=args.input_price_per_million,
                      output_price_per_million=args.output_price_per_million)
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0 if report["passed"] == report["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
