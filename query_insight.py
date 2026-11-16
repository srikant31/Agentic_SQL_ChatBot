"""What a proposed query will really do, written by code from the parsed SQL. No model calls.

analyze(question, sql) returns:
  summary      plain-English sentences describing sources, links, filters, grouping, outputs, order, limit
  rules        the business rules most relevant to this question and its SQL, ranked by BM25
               keyword match over the business glossary (term and definition, no verdicts)
  assumptions  things the SQL takes for granted that a non-SQL user should know

The model's own explanation describes what it MEANT to do; this describes what the SQL DOES.
Rule definitions come from golden_eval/business_glossary.md, the same file the model receives,
so the user sees exactly the definitions the model was given.
"""
from functools import lru_cache
from pathlib import Path
import re

import sqlglot
from sqlglot import exp

GLOSSARY_PATH = Path(__file__).parent / "golden_eval" / "business_glossary.md"
TODAY = "2026-06-30"

# Words in a question that make a glossary term relevant. Keys are glossary terms.
TERM_ALIASES = {
    "Revenue": ("revenue", "sales", "turnover", "income", "earned", "earning"),
    "Average order value (AOV)": ("average order value", "aov"),
    "Units sold": ("units sold", "quantity sold", "units", "how many items"),
    "Discount": ("discount",),
    "Cancelled": ("cancel",),
    "In transit": ("in transit", "transit", "undelivered", "not delivered"),
    "Late shipment": ("late", "delayed", "overdue", "on time", "on-time"),
    "Delivery time": ("delivery time", "days to deliver", "how long", "delivery days"),
    "Temperature excursion": ("excursion", "temperature", "too warm", "too cold"),
    "Excursion rate": ("excursion rate",),
    "Return rate": ("return rate", "returned", "returns"),
    "Northern region": ("north", "south", "east", "west", "northeast", "region"),
    "Bangalore / Bombay": ("bangalore", "bombay", "bengaluru", "mumbai"),
    "Sensitive data": ("salary", "salaries", "email", "e-mail"),
}
STATUSES = ("placed", "shipped", "delivered", "cancelled", "returned")


def load_glossary(path=GLOSSARY_PATH):
    """Term -> definition, read from the markdown table. Missing file means no rules, never an error."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    terms = {}
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 2 and cells[0] and cells[0] != "Term" and not set(cells[0]) <= set("-: "):
            terms[cells[0]] = cells[1].replace("`", "")
    return terms


# ----------------------------------------------------------------------------- naming helpers
def _singular(table):
    name = table.replace("_", " ")
    return name[:-1] if name.endswith("s") and not name.endswith("ss") else name


def _aliases(tree):
    ctes = {cte.alias for cte in tree.find_all(exp.CTE)}
    mapping, real = {}, set()
    for table in tree.find_all(exp.Table):
        target = "" if table.name in ctes else table.name
        mapping[table.alias_or_name] = target
        mapping[table.name] = target
        if target:
            real.add(target)
    # An unqualified column belongs to the only table, when there is exactly one.
    mapping[""] = next(iter(real)) if len(real) == 1 else ""
    return mapping


def _column(col, aliases):
    table = aliases.get(col.table, col.table) if col.table else aliases.get("", "")
    name = col.name.replace("_", " ")
    if table:
        owner = _singular(table)
        if name.startswith(owner + " ") or name == owner:
            return name                                    # orders.order_date -> "order date"
        return f"{owner} {name}"                           # orders.status -> "order status"
    return name


def _value(node):
    if isinstance(node, exp.Literal):
        return node.this if node.is_string else str(node.this)
    if isinstance(node, exp.Null):
        return "empty"
    return node.sql(dialect="mysql")


def _expr(node, aliases):
    """Arithmetic and functions in readable form; falls back to SQL text for anything unusual."""
    if isinstance(node, exp.Column):
        return _column(node, aliases)
    if isinstance(node, (exp.Literal, exp.Null)):
        return _value(node)
    if isinstance(node, exp.Paren):
        return f"({_expr(node.this, aliases)})"
    symbols = {exp.Mul: "×", exp.Sub: "−", exp.Add: "+", exp.Div: "÷"}
    for kind, symbol in symbols.items():
        if isinstance(node, kind):
            return f"{_expr(node.left, aliases)} {symbol} {_expr(node.right, aliases)}"
    if isinstance(node, exp.Coalesce):
        return f"{_expr(node.this, aliases)} (0 if missing)" if node.expressions else _expr(node.this, aliases)
    if isinstance(node, exp.Count):
        inner = node.this
        if isinstance(inner, exp.Distinct):
            return "number of different " + ", ".join(_expr(e, aliases) for e in inner.expressions)
        if inner is None or isinstance(inner, exp.Star):
            return "number of rows"
        return f"number of {_expr(inner, aliases)} values"
    for kind, word in ((exp.Sum, "total"), (exp.Avg, "average"), (exp.Min, "lowest"), (exp.Max, "highest")):
        if isinstance(node, kind):
            return f"{word} of {_expr(node.this, aliases)}"
    return node.sql(dialect="mysql")


# ----------------------------------------------------------------------------- filters
def _predicates(where):
    if where is None:
        return []
    node, stack, out = where.this, [where.this], []
    stack = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, exp.And):
            stack.extend([item.right, item.left])
        elif isinstance(item, exp.Paren) and isinstance(item.this, exp.And):
            stack.append(item.this)
        else:
            out.append(item)
    return out


def _is_date(node):
    if isinstance(node, exp.Column):
        return node.name.endswith(("_date", "_at"))
    if isinstance(node, exp.Literal) and node.is_string:
        return bool(re.match(r"\d{4}-\d{2}-\d{2}", node.this))
    return isinstance(node, (exp.CurrentDate, exp.CurrentTimestamp)) or any(
        isinstance(n, (exp.CurrentDate, exp.CurrentTimestamp)) for n in node.find_all(exp.Expression))


def _filter_text(pred, aliases):
    negated = isinstance(pred, exp.Not)
    core = pred.this if negated else pred
    if isinstance(core, exp.In) and isinstance(core.this, exp.Column):
        values = ", ".join(_value(v) for v in core.expressions)
        return f"{_column(core.this, aliases)} is {'not ' if negated else ''}one of: {values}"
    if isinstance(core, exp.Is) and isinstance(core.this, exp.Column):
        return f"{_column(core.this, aliases)} {'has a value' if negated else 'is empty'}"
    if isinstance(core, exp.Between):
        return (f"{_expr(core.this, aliases)} is between {_value(core.args['low'])} and "
                f"{_value(core.args['high'])} (both included)")
    if isinstance(core, exp.Like):
        return f"{_expr(core.this, aliases)} matches the pattern {_value(core.expression)}"
    dated = _is_date(core.left) or _is_date(core.right)
    words = {exp.EQ: "is", exp.NEQ: "is not",
             exp.GT: "is after" if dated else "is above", exp.GTE: "is on or after" if dated else "is at least",
             exp.LT: "is before" if dated else "is below", exp.LTE: "is on or before" if dated else "is at most"}
    for kind, word in words.items():
        if isinstance(core, kind):
            return f"{'not: ' if negated else ''}{_expr(core.left, aliases)} {word} {_expr(core.right, aliases)}"
    return pred.sql(dialect="mysql")


def _merge_ranges(preds, aliases):
    """col >= a AND col < b  ->  'col from a up to (not including) b'."""
    lows, highs, rest = {}, {}, []
    for pred in preds:
        if isinstance(pred, (exp.GTE, exp.GT)) and isinstance(pred.left, exp.Column) and isinstance(pred.right, exp.Literal):
            lows[_column(pred.left, aliases)] = (pred, _value(pred.right))
        elif isinstance(pred, (exp.LT, exp.LTE)) and isinstance(pred.left, exp.Column) and isinstance(pred.right, exp.Literal):
            highs[_column(pred.left, aliases)] = (pred, _value(pred.right))
        else:
            rest.append(pred)
    texts = []
    for name in list(lows):
        if name in highs:
            (low_pred, low), (high_pred, high) = lows.pop(name), highs.pop(name)
            low_word = "from" if isinstance(low_pred, exp.GTE) else "after"
            high_word = "up to (not including)" if isinstance(high_pred, exp.LT) else "up to and including"
            texts.append(f"{name} {low_word} {low} {high_word} {high}")
    rest.extend(pred for pred, _ in lows.values())
    rest.extend(pred for pred, _ in highs.values())
    return texts + [_filter_text(pred, aliases) for pred in rest]


# ----------------------------------------------------------------------------- description
def _main_select(tree):
    if isinstance(tree, exp.Select):
        return tree
    return tree.find(exp.Select)


def describe(sql):
    tree = sqlglot.parse_one(sql, read="mysql")
    aliases = _aliases(tree)
    lines = []
    ctes = list(tree.find_all(exp.CTE))
    if ctes:
        lines.append(f"Works in {len(ctes) + 1} steps.")
        for cte in ctes:
            lines.append(f"Step '{cte.alias}':")
            lines.extend("    " + line for line in _describe_select(cte.this, _aliases(cte.this), set()))
        lines.append("Final step:")
        body = tree.copy()
        body.set("with_", None)
        body.set("with", None)
        lines.extend("    " + line for line in _describe_select(_main_select(body), aliases, {c.alias for c in ctes}))
        return lines
    if isinstance(tree, exp.Union):
        lines.append("Combines the rows of several separate queries into one result.")
    select = _main_select(tree)
    if select is None:
        return lines or ["Could not describe this query."]
    return lines + _describe_select(select, aliases, set())


def _join_text(join, aliases):
    on = join.args.get("on")
    target = join.this.name.replace("_", " ") if isinstance(join.this, exp.Table) else "a sub-query"
    keep = " (keeping rows even when there is no match)" if (join.args.get("side") or "").upper() == "LEFT" else ""
    if isinstance(on, exp.EQ) and isinstance(on.left, exp.Column) and isinstance(on.right, exp.Column):
        left, right = on.left.name, on.right.name
        key = left.replace("_", " ") if left == right else f"{left.replace('_', ' ')} = {right.replace('_', ' ')}"
        return f"Links {target} by {key}{keep}."
    return f"Links {target} where {on.sql(dialect='mysql')}{keep}." if on is not None else f"Adds {target}{keep}."


def _describe_select(select, aliases, ctes):
    lines = []
    if select is None:
        return ["Could not describe this step."]

    from_node = select.args.get("from_") or select.args.get("from")
    sources = []
    if from_node is not None:
        sources.append(from_node.this)
    joins = select.args.get("joins") or []
    sources.extend(join.this for join in joins)
    names = []
    for source in sources:
        if isinstance(source, exp.Table):
            names.append(f"'{source.name}'" if source.name in ctes else source.name.replace("_", " "))
        else:
            names.append("a sub-query")
    if names:
        lines.append("Reads from: " + ", ".join(names) + ".")
    for join in joins:
        lines.append(_join_text(join, aliases))

    filters = _merge_ranges(_predicates(select.args.get("where")), aliases)
    if filters:
        lines.append("Keeps only rows where: " + "; ".join(filters) + ".")
    else:
        lines.append("No filters: every row is considered.")

    group = select.args.get("group")
    if group is not None:
        lines.append("Groups the results by " + ", ".join(_expr(e, aliases) for e in group.expressions) + ".")
    having = select.args.get("having")
    if having is not None:
        lines.append("After grouping, keeps only groups where " + "; ".join(
            _filter_text(p, aliases) for p in _predicates(exp.Where(this=having.this))) + ".")

    outputs = []
    for projection in select.expressions:
        inner = projection.this if isinstance(projection, exp.Alias) else projection
        label = _expr(inner, aliases) if not isinstance(inner, exp.Star) else "every column"
        outputs.append(f"{label} (shown as '{projection.alias}')" if isinstance(projection, exp.Alias) else label)
    lines.append("Shows: " + "; ".join(outputs) + ".")

    order = select.args.get("order")
    if order is not None:
        parts = [f"{_expr(o.this, aliases)} ({'highest' if o.args.get('desc') else 'lowest'} first)" for o in order.expressions]
        lines.append("Sorted by " + ", ".join(parts) + ".")
    limit = select.args.get("limit")
    if limit is not None:
        lines.append(f"Returns at most {_value(limit.expression)} rows.")
    return lines


# ----------------------------------------------------------------------------- business rules
def _status_filters(tree):
    """(operator, values) for every filter on a column named status."""
    found = []
    for node in tree.find_all(exp.EQ, exp.NEQ, exp.In):
        column = node.this if isinstance(node, exp.In) else node.left
        if isinstance(column, exp.Column) and column.name.lower() == "status":
            values = [_value(v) for v in node.expressions] if isinstance(node, exp.In) else [_value(node.right)]
            negated = isinstance(node.parent, exp.Not) or isinstance(node, exp.NEQ)
            found.append(("not" if negated else "in", [v.lower() for v in values]))
    return found


def _counted_statuses(tree):
    """Which order statuses the query lets through, or None if it has no status filter."""
    filters = _status_filters(tree)
    if not filters:
        return None
    allowed = set(STATUSES)
    for kind, values in filters:
        allowed = allowed & set(values) if kind == "in" else allowed - set(values)
    return allowed


STOPWORDS = {"the", "a", "an", "of", "in", "on", "for", "to", "and", "or", "is", "are", "was", "were", "by", "with",
             "what", "which", "how", "many", "much", "show", "me", "list", "give", "all", "each", "per", "from",
             "across", "between", "did", "do", "does", "we", "our", "my", "i", "it", "that", "this", "as", "at", "be"}
TODAY_RULE = ("Today's date", f"Today's date for all relative questions is {TODAY} (the data covers 2025-07-01 "
              f"to {TODAY}). Relative periods such as 'last month' are counted back from this date.")
TODAY_WORDS = "today yesterday last this previous past current recent latest week month quarter year ytd"


def _documents(glossary):
    """One searchable document per rule: term, definition and the question words that point to it."""
    docs = [(term, " ".join([term, definition, " ".join(TERM_ALIASES.get(term, ()))]))
            for term, definition in glossary.items()]
    docs.append((TODAY_RULE[0], " ".join([TODAY_RULE[0], TODAY_RULE[1], TODAY_WORDS])))
    return tuple(docs)


def _words(text):
    """Tokens with a light plural fold, so 'excursions' matches 'excursion' and 'shipments' matches 'shipment'."""
    from retrieval import tokenize
    return [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in tokenize(text)]


@lru_cache(maxsize=8)
def _index(docs):
    from rank_bm25 import BM25Okapi
    return BM25Okapi([_words(text) for _, text in docs])


QUESTION_WEIGHT, SQL_WEIGHT = 1.0, 0.3   # table/column names appear in many rules, so they count less
MIN_SCORE, RELATIVE_CUTOFF = 2.5, 0.6     # a rule must clearly match, and be close to the best match


def rules_for(question, sql, glossary=None, k=5):
    """The business rules most relevant to this question and its SQL, ranked by BM25 keyword match
    (plain BM25Okapi: unlike BM25Plus it gives no baseline score, so a cut-off is meaningful).
    The model receives the whole glossary; this shows which parts matter for this query. No verdicts."""
    glossary = load_glossary() if glossary is None else glossary
    if not glossary:
        return []
    question_words = [w for w in _words(question or "") if w not in STOPWORDS and not w.isdigit()]
    sql_words = []
    try:
        tree = sqlglot.parse_one(sql, read="mysql") if sql else None
    except Exception:
        tree = None
    if tree is not None:
        identifiers = {t.name for t in tree.find_all(exp.Table)} | {c.name for c in tree.find_all(exp.Column)}
        literals = {str(l.this) for l in tree.find_all(exp.Literal) if l.is_string and not re.match(r"\d{4}-", str(l.this))}
        sql_words = [w for w in _words(" ".join(sorted(identifiers | literals))) if not w.isdigit()]
    if not question_words and not sql_words:
        return []
    docs = _documents(glossary)
    model = _index(docs)
    scores = [QUESTION_WEIGHT * a + SQL_WEIGHT * b for a, b in
              zip(model.get_scores(question_words) if question_words else [0.0] * len(docs),
                  model.get_scores(sql_words) if sql_words else [0.0] * len(docs))]
    ranked = sorted(zip((term for term, _ in docs), scores), key=lambda item: -item[1])
    best = ranked[0][1] if ranked else 0.0
    definitions = {**glossary, TODAY_RULE[0]: TODAY_RULE[1]}
    return [{"term": term, "definition": definitions[term], "score": round(float(score), 2)}
            for term, score in ranked[:k] if score >= max(MIN_SCORE, RELATIVE_CUTOFF * best)]


# ----------------------------------------------------------------------------- assumptions
def assumptions_for(question, sql):
    tree = sqlglot.parse_one(sql, read="mysql")
    tables = {table.name for table in tree.find_all(exp.Table)}
    columns = {col.name for col in tree.find_all(exp.Column)}
    text = (question or "").lower()
    out = []
    if "orders" in tables and _counted_statuses(tree) is None:
        out.append("All order statuses are included: placed, shipped, delivered, cancelled and returned.")
    for name, meaning in (("order_date", "when the order was placed"), ("shipped_at", "when the shipment left"),
                          ("delivered_at", "when the shipment was delivered"), ("signup_date", "when the customer signed up")):
        if name in columns and any(name in (c.name for c in pred.find_all(exp.Column))
                                   for pred in tree.find_all(exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Between)):
            out.append(f"Dates are based on {name.replace('_', ' ')} ({meaning}).")
    if "regions" in tables:
        if "customers" in tables and "warehouses" not in tables:
            out.append("'Region' means the customer's region, not the warehouse's.")
        elif "warehouses" in tables and "customers" not in tables:
            out.append("'Region' means the fulfilling warehouse's region, not the customer's.")
    if re.search(r"\b(last|this|previous|past|current)\s+(day|week|month|quarter|year)|\btoday\b|\byesterday\b|\brecent", text):
        out.append(f"'Today' is taken as {TODAY}, the last day of the data.")
    aliases = _aliases(tree)
    price_tables = {aliases.get(col.table, col.table) if col.table else aliases.get("", "")
                    for col in tree.find_all(exp.Column) if col.name == "unit_price"}
    if "order_items" in price_tables:
        out.append("Prices are the prices charged at the time of sale, not today's list prices.")
    if "products" in price_tables:
        out.append("Prices are today's list prices from the product catalogue, not the prices actually charged.")
    limit = (tree if isinstance(tree, exp.Select) else _main_select(tree) or tree).args.get("limit")
    if limit is not None:
        out.append(f"At most {_value(limit.expression)} rows are shown.")
    return out


def analyze(question, sql, glossary=None):
    """Never raises: a description failure must not block the user from reviewing SQL."""
    try:
        return {"summary": describe(sql), "rules": rules_for(question, sql, glossary),
                "assumptions": assumptions_for(question, sql)}
    except Exception:
        return None
