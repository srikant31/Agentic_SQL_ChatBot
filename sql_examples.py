"""Reviewed SQL demonstrations. Successful execution never promotes a record."""
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope

from business_context import analyze_intent
from context_models import SearchDocument, fingerprint
from rbac import allowed
from retrieval import cached_index
from safety import SchemaValidationError, UnsafeQueryError, validate_sql_schema
from schema_context import CatalogError, dependency_version
from semantic_validation import validate_sql

EXAMPLES_PATH = Path(__file__).resolve().parent / "metadata" / "sql_examples.jsonl"


def load_examples(path=EXAMPLES_PATH) -> tuple[dict, ...]:
    path = Path(path)
    if not path.exists():
        return ()
    if path.stat().st_size > 1_000_000:
        raise ValueError("SQL example collection exceeds its size limit.")
    result, seen = [], set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record, dict) or not isinstance(record.get("id"), str) or record["id"] in seen:
            raise ValueError("Invalid or duplicate SQL example record.")
        seen.add(record["id"])
        result.append(record)
    return tuple(result)


def eligible_examples(records, catalog, rules, user) -> tuple[dict, ...]:
    rule_versions = {rule.id: rule.version for rule in rules}
    result = []
    for record in records:
        if record.get("verification_status") != "approved" or record.get("sql_dialect") != catalog.dialect:
            continue
        if (not isinstance(record.get("template_family"), str) or not record["template_family"]
            or not isinstance(record.get("question"), str) or not 1 <= len(record["question"]) <= 4000
            or not isinstance(record.get("reviewer"), str) or not isinstance(record.get("reviewed_at"), str)):
            continue
        evidence = record.get("verification_evidence", {})
        if (not record.get("reviewer") or not record.get("reviewed_at") or not isinstance(evidence, dict)
            or evidence.get("semantic_review") is not True or evidence.get("expected_result_review") is not True
            or not evidence.get("fixture") or not evidence.get("test")):
            continue
        try:
            if not all(allowed(user, permission) for permission in record["required_permissions"]):
                continue
            if any(rule_versions.get(name) != version for name, version in record["business_rule_versions"].items()):
                continue
            if dependency_version(catalog, record["referenced_tables"], record["referenced_columns"]) != record["schema_version"]:
                continue
            tree = validate_sql_schema(record["sql"], catalog)
            actual_tables, actual_columns = set(), set()
            for scope in traverse_scope(tree):
                for source in scope.sources.values():
                    if isinstance(source, exp.Table):
                        actual_tables.add(source.name.upper())
                for column in scope.columns:
                    source = scope.sources.get(column.table)
                    if isinstance(source, exp.Table):
                        actual_columns.add(f"{source.name.upper()}.{column.name.upper()}")
            if (not actual_tables.issubset(record["referenced_tables"])
                or not actual_columns.issubset(record["referenced_columns"])):
                continue
            intent = analyze_intent(record["question"], catalog, rules, user)
            validate_sql(record["sql"], catalog, intent, rules)
        except (ValueError, KeyError, TypeError, AttributeError, SchemaValidationError, UnsafeQueryError):
            continue
        result.append(record)
    return tuple(result)


def retrieve_examples(question: str, records, *, k: int = 3) -> tuple[dict, ...]:
    documents = tuple(SearchDocument(record["id"], "example", record["question"],
                                      tuple(record["referenced_tables"])) for record in records)
    records_by_id = {record["id"]: record for record in records}
    selected, families = [], set()
    for hit in cached_index(documents).search(question, max(k * 4, k)):
        record = records_by_id[hit.document.id]
        family = record.get("template_family", record["id"])
        if family not in families:
            families.add(family)
            selected.append(record)
        if len(selected) >= k:
            break
    return tuple(selected)


def examples_version(records) -> str:
    return fingerprint(records)


def approve_example(record, engine, *, reviewer: str, review_note: str, expected_rows):
    """Explicit maintainer approval against a disposable fixture, never auto-promotion.

    The caller supplies independently reviewed expectations and a semantic review note.
    Matching results supplement that review; execution success alone is insufficient.
    """
    from business_context import load_business_rules
    from database import run_query
    from rbac import USERS
    from schema_context import get_catalog
    from utils import compare_result_rows

    if record.get("verification_status") != "draft":
        raise ValueError("Only a draft example can be approved. Re-review stale examples as new drafts.")
    if not reviewer.strip() or len(review_note.strip()) < 20 or not isinstance(expected_rows, list):
        raise ValueError("Approval requires a reviewer, a semantic review note and independent expected-result rows.")
    if engine.dialect.name != "sqlite":
        raise ValueError("Example approval must use a disposable local SQLite fixture, not the live source.")
    user = USERS["hr"]
    catalog = get_catalog(user, engine, refresh=True)
    rules = load_business_rules(catalog, user)
    intent = analyze_intent(record["question"], catalog, rules, user)
    validate_sql(record["sql"], catalog, intent, rules)
    _, rows = run_query(record["sql"], user, engine)
    if not compare_result_rows(rows, expected_rows, ordered="ORDER BY" in record["sql"].upper()):
        raise ValueError("The query result does not match the independently reviewed fixture expectation.")
    approved = {**record,
        "schema_version": dependency_version(catalog, record["referenced_tables"], record["referenced_columns"]),
        "business_rule_versions": {rule.id: rule.version for rule in rules if rule.id in set(intent.rule_ids) | {"employee_grain", "authorized_scope"}},
        "required_permissions": ["salary"] if any(reference.endswith(".SALARY") for reference in record["referenced_columns"]) else [],
        "verification_status": "approved", "reviewer": reviewer.strip(),
        "reviewed_at": datetime.now(timezone.utc).isoformat(), "expected_fixture_rows": expected_rows,
        "verification_evidence": {"semantic_review": True, "expected_result_review": True,
            "fixture": "fictional-employees-v1", "test": "explicit maintainer review and fixture comparison",
            "review_note": review_note.strip()}}
    if not eligible_examples([approved], catalog, rules, user):
        raise ValueError("Example dependencies, dialect or metadata are incomplete.")
    return approved
