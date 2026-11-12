"""Reviewed file-based business definitions and deliberately bounded intent analysis."""
from functools import lru_cache
from pathlib import Path
import re

import yaml
import sqlglot
from sqlglot import exp

from context_models import BusinessRule, Intent, fingerprint
from rbac import allowed, require

RULES_PATH = Path(__file__).resolve().parent / "metadata" / "business_rules.yaml"
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10}
WRITE_REQUEST = r"(?:^|[.;]\s*|\b(?:and|then|please)\s+)(?:delete|drop|truncate|insert|update|alter|create)\b"
UNSUPPORTED_DATA = (r"\b(customers?|revenue|refunds?|cancelled|hired?|hiring|joined|tenure|audit|history|growth|active employees|employment|title changes)\b"
                    r"|\b(?:customer|sales|purchase|placed)\s+orders?\b|\borders?\s+(?:placed|total|count|value)\b"
                    r"|\b(last|this|previous)\s+(month|year|quarter|week)\b|\bas of\b|\bmonthly\b")
LOCATION_WORDS = r"\b(?:city|cities|location|locations|region|regions|country|countries)\b"
# Case-sensitive on purpose: a capitalized place-like word that is not a known department.
NAMED_GROUP = r"\b(?:in|for|from|at|of)\s+(?!(?:Engineering|HR|IT)\b)[A-Z][a-z]+\s+(?:employees|staff|people)\b"


@lru_cache(maxsize=16)
def _parse_rules(content: str) -> tuple[dict, ...]:
    data = yaml.safe_load(content)
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise ValueError("Invalid business-rule file.")
    seen = set()
    for record in data["rules"]:
        if (not isinstance(record, dict) or not isinstance(record.get("id"), str)
            or record["id"] in seen or not isinstance(record.get("version"), int)
            or record.get("kind") not in {"definition", "dimension", "metric", "filter"}
            or not isinstance(record.get("description"), str)
            or not isinstance(record.get("aliases"), list) or not isinstance(record.get("columns"), list)
            or not all(isinstance(s, str) for s in record["aliases"] + record["columns"])):
            raise ValueError("Invalid or duplicate business-rule record.")
        seen.add(record["id"])
    return tuple(data["rules"])


def load_business_rules(catalog, user, path=RULES_PATH) -> tuple[BusinessRule, ...]:
    require(user, "query")
    schema, result = catalog.sqlglot_schema(), []
    for record in _parse_rules(Path(path).read_text(encoding="utf-8")):
        if record.get("status") != "approved":
            continue
        permission = record.get("permission", "")
        if permission and not allowed(user, permission):
            continue
        for reference in record["columns"]:
            table, column = reference.split(".", 1)
            if column not in schema.get(table, {}):
                raise ValueError("An approved business definition references an unavailable field.")
        if record["kind"] == "metric":
            field = record.get("field")
            if (record.get("aggregate") not in {"COUNT", "SUM", "AVG", "MIN", "MAX"}
                or not isinstance(field, str) or not field
                or (field == "*" and record["aggregate"] != "COUNT")
                or (field != "*" and not any(reference.endswith("." + field) for reference in record["columns"]))):
                raise ValueError("Unsupported approved metric definition.")
        predicates = record.get("predicates", [])
        if not isinstance(predicates, list) or not all(isinstance(predicate, str) for predicate in predicates):
            raise ValueError("Business-rule predicates must be SQL expression strings.")
        for predicate in predicates:
            parsed = sqlglot.parse(predicate, read="sqlite")
            if len(parsed) != 1 or parsed[0] is None or parsed[0].find(exp.Query):
                raise ValueError("Business-rule predicates must be single filter expressions.")
            fields = {reference.split(".")[1] for reference in record["columns"]}
            if any(column.name not in fields for column in parsed[0].find_all(exp.Column)):
                raise ValueError("A business-rule predicate references an undeclared field.")
        result.append(BusinessRule(
            id=record["id"], kind=record["kind"], description=record["description"],
            aliases=tuple(record["aliases"]), columns=tuple(record["columns"]), version=record["version"],
            aggregate=record.get("aggregate", ""), field=record.get("field", ""),
            predicates=tuple(record.get("predicates", ())), permission=permission,
            distinct=record.get("distinct", False), unit=record.get("unit", ""),
            time_basis=record.get("time_basis", "")))
    return tuple(result)


def rules_version(rules) -> str:
    from dataclasses import asdict
    return fingerprint([asdict(rule) for rule in rules])


def phrase_matches(phrase: str, question: str) -> bool:
    pattern = re.escape(phrase.lower()).replace(r"\ ", r"\s+")
    return re.search(r"(?<!\w)" + pattern + r"(?!\w)", question.lower()) is not None


def analyze_intent(question: str, catalog, rules, user) -> Intent:
    """Recognize supported contracts; this is not a general natural-language parser."""
    require(user, "query")
    if not isinstance(question, str) or not question.strip() or len(question) > 4000:
        return Intent("clarification", "Enter a question of 1–4,000 characters.")
    q = question.lower().strip()
    if re.search(r"\b(salar(?:y|ies)|payroll|compensation|wages?|pay)\b", q) and not allowed(user, "salary"):
        return Intent("denied", "Your role cannot query salary information.")
    # Imperative write verbs only (start of the request or after and/then/please/;), so questions like
    # "which employees can update their title?" are not rejected. This is a UX pre-check; the SQL parser
    # and the SQLite authorizer remain the actual enforcement.
    if re.search(WRITE_REQUEST, q):
        return Intent("unsupported", "The SQL assistant supports read-only analytics. Use the approved admin screen for job-title edits.")
    if re.search(r"other database tables|sqlite_master|information_schema|ignore.+schema", q):
        return Intent("denied", "Only the authorized logical employee table is available.")
    if re.search(UNSUPPORTED_DATA, q):
        return Intent("unsupported", "The authorized employee snapshot has no customer, order, historical, employment-date, or activity data for this request.")
    # No location column exists. Naming a place ("Pune employees") must not silently become an unfiltered query.
    if re.search(LOCATION_WORDS, q) or re.search(NAMED_GROUP, question):
        return Intent("unsupported", "The authorized employee snapshot has no location data, and the named group is not a recorded department.")
    if re.search(r"\b(join|manager.s manager|manager.s salary|manager.s department|reporting chain|manager(?: employee)? id)\b", q):
        return Intent("unsupported", "No approved identity-based join or reporting-chain relationship is available. Recorded manager names are labels only.")
    if re.search(r"\b(best employee|manager performance|payroll|jane.s team)\b", q) or q in {"show managers", "list managers"}:
        return Intent("clarification", "Specify the metric and population. Salary values have no defined currency or pay period; manager labels do not establish manager identities.")
    selected = [rule for rule in rules if any(phrase_matches(alias, q) for alias in rule.aliases)]
    metrics = [rule for rule in selected if rule.kind == "metric"]
    if re.search(r"\btop\s+(?:\d+|one|two|three|four|five|ten)\b", q) and not re.search(r"\bdepartments?\b", q):
        metrics = [rule for rule in metrics if rule.aggregate != "MAX"]
    groups = []
    if metrics and re.search(r"\b(?:by|per|each|every)\s+(?:recorded\s+)?department\b|\btop\s+\w+\s+departments\b", q):
        groups.append("DEPARTMENT")
    if metrics and re.search(r"\b(?:by|per|each|every)\s+(?:recorded\s+)?manager(?: label)?\b", q):
        groups.append("MANAGER_NAME")
    if re.search(r"\btop\s+\w+\s+departments\b", q) and not metrics:
        return Intent("clarification", "Which metric should rank the departments: employee count, average recorded salary, or recorded salary total?")
    predicates = [predicate for rule in selected if rule.kind == "filter" for predicate in rule.predicates]
    departments = [("Engineering", r"\bengineering\b"), ("HR", r"\bhr\b"),
                   ("IT", r"\bit department\b|\bdepartment it\b|\b(?:in|from|for|of)\s+it\b(?!\s+(?:is|was|are|has|have))")]
    mentioned = [value for value, pattern in departments if re.search(pattern, q)]
    if len(mentioned) == 1:
        operation = exp.NEQ if re.search(r"\b(outside|excluding|except)\s+" + re.escape(mentioned[0].lower()), q) else exp.EQ
        predicates.append(operation(this=exp.column("DEPARTMENT"), expression=exp.Literal.string(mentioned[0])).sql(dialect="sqlite"))
    name = re.search(r"(?:who is|what is|show|tell me) ([A-Za-z]+(?: [A-Za-z]+){1,3})(?:'s|’s) (.+?)[.?]?$", question.strip(), re.I)
    requested_columns = []
    if name:
        # Stored names are capitalized; SQLite '=' is case-sensitive, so normalize the typed name.
        predicates.append(exp.EQ(this=exp.column("NAME"), expression=exp.Literal.string(name.group(1).title())).sql(dialect="sqlite"))
        for pattern, column in ((r"manager|boss", "MANAGER_NAME"), (r"department", "DEPARTMENT"), (r"position|job title", "JOB_TITLE"), (r"salary", "SALARY")):
            if re.search(pattern, name.group(2), re.I):
                requested_columns.append(column)
    manager = re.search(r"(?:report directly to|reporting to|report to|recorded manager is)\s+([A-Za-z]+(?: [A-Za-z]+){1,3})[.?]?$", question.strip(), re.I)
    if manager:
        predicates.append(exp.EQ(this=exp.column("MANAGER_NAME"), expression=exp.Literal.string(manager.group(1))).sql(dialect="sqlite"))
    comparison = re.search(r"(?:recorded )?salar(?:y|ies)\s+(above|over|greater than|below|under|less than|at least|at most)\s+(\d[\d,]*(?:\.\d+)?)", q)
    if comparison:
        operations = {"above": exp.GT, "over": exp.GT, "greater than": exp.GT, "below": exp.LT,
                      "under": exp.LT, "less than": exp.LT, "at least": exp.GTE, "at most": exp.LTE}
        predicates.append(operations[comparison[1]](this=exp.column("SALARY"), expression=exp.Literal.number(comparison[2].replace(",", ""))).sql(dialect="sqlite"))
    salary_range = re.search(r"salar(?:y|ies) between (\d[\d,]*) and (\d[\d,]*)", q)
    if salary_range:
        predicates.append(exp.Between(this=exp.column("SALARY"), low=exp.Literal.number(salary_range[1].replace(",", "")), high=exp.Literal.number(salary_range[2].replace(",", ""))).sql(dialect="sqlite"))
    top = re.search(r"\b(top|bottom)\s+(\d+|one|two|three|four|five|ten)\b", q)
    limit, descending = None, None
    if top:
        limit = NUMBERS[top[2]] if top[2] in NUMBERS else int(top[2])
        if not 1 <= limit <= 500:
            return Intent("clarification", "Choose a result limit between 1 and 500.")
        descending = top[1] == "top"
    threshold = re.search(r"at least (\d+|one|two|three|four|five|ten) (?:visible )?employees", q)
    threshold_value = (NUMBERS[threshold[1]] if threshold[1] in NUMBERS else int(threshold[1])) if threshold else None
    having = (f"COUNT(*) >= {threshold_value}",) if threshold and any(rule.id == "employee_count" for rule in metrics) else ()
    normalized = re.sub(r"\s+", " ", q.rstrip(".?"))
    strict_population = bool(re.fullmatch(
        r"(?:show )?(?:recorded salary total|average recorded salary|average salary|employee count|headcount)(?: by department)?|how many employees (?:can i access|are there)|count employees(?: by department)?", normalized))
    return Intent(rule_ids=tuple(rule.id for rule in selected), metric_ids=tuple(rule.id for rule in metrics),
                  group_by=tuple(groups), predicates=tuple(predicates), limit=limit, descending=descending,
                  rank_by="SALARY" if top and not metrics and re.search(r"\bsalar(?:y|ies)\b", q) else "",
                  having_predicates=having, requested_columns=tuple(requested_columns),
                  strict_population=strict_population)
