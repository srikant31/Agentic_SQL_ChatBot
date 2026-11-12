"""Context preparation and proposal lifecycle. Generation never executes SQL."""
from dataclasses import asdict
import json
import time

from business_context import RULES_PATH, analyze_intent, load_business_rules, rules_version
from context_models import ContextPackage, SchemaCatalog, fingerprint
from rbac import require
from retrieval import build_documents, cached_index, expand_relationships
from schema_context import get_catalog
from semantic_validation import SemanticValidationError, validate_sql
from sql_examples import EXAMPLES_PATH, eligible_examples, examples_version, load_examples, retrieve_examples
import sql_generator

CONTEXT_MAX_CHARACTERS = 18_000


def _engine(engine):
    if engine is None:
        from database import get_engine
        return get_engine()
    return engine


def prepare_context(question, user, engine=None, *, catalog=None, mode="D", refresh=False,
                    rules_path=RULES_PATH, examples_path=EXAMPLES_PATH,
                    max_characters=CONTEXT_MAX_CHARACTERS) -> ContextPackage:
    require(user, "query")
    if mode not in {"A", "B", "C", "D"}:
        raise ValueError("Unknown context configuration.")
    catalog = catalog if catalog is not None else get_catalog(user, _engine(engine), refresh=refresh)
    rules = load_business_rules(catalog, user, rules_path)
    intent = analyze_intent(question, catalog, rules, user)
    # Rejected requests never retrieve examples or call an LLM.
    if intent.status != "query":
        return ContextPackage(catalog, (), intent, (), (), fingerprint({"catalog": catalog.version, "rules": rules_version(rules)}), "")
    documents = build_documents(catalog, rules)
    # Independent channels prevent table text from crowding out business definitions.
    expanded_question = question + " " + " ".join(rule.id for rule in rules if rule.id in intent.rule_ids)
    table_hits = cached_index(tuple(d for d in documents if d.kind == "table")).search(expanded_question, 3)
    rule_hits = cached_index(tuple(d for d in documents if d.kind == "rule")).search(expanded_question, 5)
    hits = table_hits + rule_hits if mode in {"C", "D"} else ()
    required_rule_ids = set(intent.rule_ids) | {"employee_grain", "authorized_scope"}
    if any(rule.permission == "salary" and rule.id in required_rule_ids for rule in rules):
        required_rule_ids.add("salary_units")
    selected_rule_ids = required_rule_ids | {hit.document.id.removeprefix("rule:") for hit in rule_hits}
    selected_rules = tuple(rule for rule in rules if mode == "B" or rule.id in selected_rule_ids) if mode != "A" else ()
    # Retain a full small schema. Prune only when multiple table documents exceed the budget.
    selected_tables = {table.name for table in catalog.tables}
    if len(catalog.tables) > 3 and len(catalog.render()) > max_characters // 2 and mode in {"C", "D"}:
        selected_tables = {name for hit in table_hits for name in hit.document.tables}
        selected_tables.update(reference.split(".")[0] for rule in selected_rules for reference in rule.columns)
        if not selected_tables:
            raise ValueError("No relevant schema matched; clarify the requested entities.")
    expanded, relationships = expand_relationships(selected_tables, catalog)
    selected_catalog = SchemaCatalog(tuple(table for table in catalog.tables if table.name in expanded),
                                     relationships, catalog.dialect, catalog.scope)
    eligible = eligible_examples(load_examples(examples_path), catalog, rules, user) if mode == "D" else ()
    examples = retrieve_examples(question, eligible) if mode == "D" else ()
    version = fingerprint({"catalog": catalog.version, "rules": rules_version(rules),
                           "examples": examples_version(eligible), "mode": mode})

    def render(chosen_rules, chosen_examples):
        payload = {
            "schema": selected_catalog.render(),
            "table_metadata": [{"name": table.name, "description": table.description,
                                "primary_key": table.primary_key,
                                "columns": [{"name": column.name, "description": column.description}
                                            for column in table.columns if column.description]}
                               for table in selected_catalog.tables],
            "relationships": [asdict(relationship) for relationship in relationships],
            "business_definitions": [asdict(rule) for rule in chosen_rules],
            "required_contract": asdict(intent) if mode != "A" else {},
            "verified_demonstrations": [{"id": example["id"], "question": example["question"], "sql": example["sql"]} for example in chosen_examples],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    prompt = render(selected_rules, examples)
    warnings = []
    while len(prompt) > max_characters and examples:
        examples = examples[:-1]
        prompt = render(selected_rules, examples)
        warnings.append("An optional demonstration was omitted to fit the context budget.")
    if len(prompt) > max_characters:
        selected_rules = tuple(rule for rule in selected_rules if rule.id in required_rule_ids)
        prompt = render(selected_rules, examples)
        warnings.append("Optional business definitions were omitted to fit the context budget.")
    if len(prompt) > max_characters:
        raise ValueError("Required context exceeds the budget; narrow the question. Required definitions were not truncated.")
    return ContextPackage(selected_catalog, selected_rules, intent, hits, examples, version, prompt, tuple(warnings))


def prepare_proposal(question, user, engine=None, *, mode="D", rules_path=RULES_PATH, examples_path=EXAMPLES_PATH):
    started = time.perf_counter()
    context = prepare_context(question, user, engine, mode=mode, rules_path=rules_path, examples_path=examples_path)
    if context.intent.status != "query":
        return {"status": context.intent.status, "message": context.intent.message}
    # The full catalog's semantic rules are used even when optional prompt context was dropped.
    rules = load_business_rules(context.catalog, user, rules_path)
    generated = sql_generator.generate_sql(question, context.prompt_context)
    if generated.get("status", "proposal") != "proposal":
        return generated
    validation = validate_sql(generated["sql"], context.catalog, context.intent, rules)
    return {**generated, "status": "proposal", "owner": user.username, "question": question,
            "context_version": context.version, "mode": mode,
            "validation": asdict(validation), "context": {
                "tables": [table.name for table in context.catalog.tables],
                "rules": [rule.id for rule in context.rules],
                "examples": [example["id"] for example in context.examples],
                "retrieval": [{"id": hit.document.id, "score": round(hit.score, 4)} for hit in context.hits],
                "characters": len(context.prompt_context),
                "estimated_tokens": (len(context.prompt_context) + 3) // 4,
                "warnings": list(context.warnings)},
            "preparation_seconds": round(time.perf_counter() - started, 4)}


def execute_proposal(proposal, user, engine=None, *, rules_path=RULES_PATH, examples_path=EXAMPLES_PATH):
    require(user, "query")
    if proposal.get("status") != "proposal" or proposal.get("owner") != user.username:
        raise PermissionError("The query proposal belongs to another session or is invalid.")
    engine = _engine(engine)
    context = prepare_context(proposal["question"], user, engine, mode=proposal.get("mode", "D"), refresh=True,
                              rules_path=rules_path, examples_path=examples_path)
    if context.intent.status != "query" or context.version != proposal.get("context_version"):
        raise SemanticValidationError("Schema, permissions or reviewed context changed. Generate and review a new proposal.")
    validate_sql(proposal["sql"], context.catalog, context.intent, load_business_rules(context.catalog, user, rules_path))
    from database import run_query
    return run_query(proposal["sql"], user, engine=engine)
