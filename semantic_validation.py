"""Conservative, deterministic checks for recognized analytical contracts.

This validates supported SQL shapes, not arbitrary equivalence to natural language.
An LLM explanation/confidence score is never a verification signal.
"""
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope

from context_models import ValidationResult
from safety import validate_sql_schema


class SemanticValidationError(ValueError):
    pass


def _conjuncts(node):
    if isinstance(node, exp.Paren):
        return _conjuncts(node.this)
    if isinstance(node, exp.And):
        return _conjuncts(node.this) + _conjuncts(node.expression)
    return [node]


def _canonical(node):
    copied = node.copy()
    for column in copied.find_all(exp.Column):
        column.set("table", None)
        column.set("db", None)
        column.set("catalog", None)
    for identifier in copied.find_all(exp.Identifier):
        identifier.set("quoted", False)
        identifier.set("this", identifier.name.upper())
    return copied.sql(dialect="sqlite")


def _resolve(expression, scope, depth=0):
    """Follow an output alias through simple CTE/subquery projections only."""
    if depth > 12:
        raise SemanticValidationError("Query projection is too deeply nested to verify.")
    while isinstance(expression, (exp.Alias, exp.Paren)):
        expression = expression.this
    if isinstance(expression, exp.Column):
        source = scope.sources.get(expression.table)
        if isinstance(source, Scope) and isinstance(source.expression, exp.Select):
            match = next((item for item in source.expression.expressions
                          if item.alias_or_name.lower() == expression.name.lower()), None)
            if match is not None:
                return _resolve(match, source, depth + 1)
    return expression, scope


def _is_metric(expression, scope, rule):
    expression, scope = _resolve(expression, scope)
    # A harmless rounding wrapper is supported. Arbitrary arithmetic is not proof.
    if isinstance(expression, exp.Round):
        expression = expression.this
    if not isinstance(expression, exp.AggFunc) or expression.sql_name() != rule.aggregate:
        return None
    argument = expression.this
    distinct = isinstance(argument, exp.Distinct)
    if distinct:
        argument = argument.expressions[0] if len(argument.expressions) == 1 else None
    if distinct != rule.distinct or expression.args.get("expressions"):
        return None
    if rule.field == "*":
        if not isinstance(argument, exp.Star):
            return None
        tables = _base_tables(scope)
        expected = {reference.split(".")[0] for reference in rule.columns}
        if tables != expected:
            return None
        return scope
    if not isinstance(argument, exp.Column):
        return None
    column, source_scope = _resolve(argument, scope)
    if not isinstance(column, exp.Column) or column.name.upper() != rule.field.upper():
        return None
    source = source_scope.sources.get(column.table)
    expected = {reference.split(".")[0] for reference in rule.columns if reference.endswith("." + rule.field)}
    if not isinstance(source, exp.Table) or source.name.upper() not in expected:
        return None
    return scope


def _base_tables(scope, depth=0):
    if depth > 12:
        raise SemanticValidationError("Query sources are too deeply nested to verify.")
    tables = set()
    for _, source in scope.selected_sources.values():
        if isinstance(source, exp.Table):
            tables.add(source.name.upper())
        elif isinstance(source, Scope):
            tables.update(_base_tables(source, depth + 1))
    return tables


def _join_checks(scopes, catalog):
    for scope in scopes:
        if not isinstance(scope.expression, exp.Select):
            continue
        joins = scope.expression.args.get("joins") or []
        from_clause = scope.expression.args.get("from_")
        joined_aliases = {from_clause.this.alias_or_name} if from_clause is not None else set()
        for join in joins:
            predicate = join.args.get("on")
            if predicate is None:
                raise SemanticValidationError("A join needs an explicit approved key relationship; Cartesian/NATURAL/USING joins are not approved.")
            pairs = set()
            for condition in _conjuncts(predicate):
                if isinstance(condition, exp.EQ) and isinstance(condition.this, exp.Column) and isinstance(condition.expression, exp.Column):
                    left, right = condition.this, condition.expression
                    pairs.add(((left.table, left.name.upper()), (right.table, right.name.upper())))
            right_alias = join.this.alias_or_name
            right_source = scope.sources.get(right_alias)
            if not isinstance(right_source, exp.Table):
                raise SemanticValidationError("Joins through derived tables require a separately approved analytical view.")
            matched = []
            for alias, source in scope.sources.items():
                if alias == right_alias or not isinstance(source, exp.Table):
                    continue
                for relationship in catalog.relationships:
                    if not relationship.approved:
                        continue
                    for first_alias, first, second_alias, second in ((alias, source, right_alias, right_source), (right_alias, right_source, alias, source)):
                        if first.name.upper() != relationship.from_table.upper() or second.name.upper() != relationship.to_table.upper():
                            continue
                        expected = {((first_alias, a.upper()), (second_alias, b.upper()))
                                    for a, b in zip(relationship.from_columns, relationship.to_columns)}
                        present = pairs | {(b, a) for a, b in pairs}
                        if expected and expected.issubset(present):
                            matched.append((relationship, first_alias, second_alias))
            if not matched:
                raise SemanticValidationError("The join does not use an approved complete key relationship. Names are not identity keys.")
            # Added ON predicates can silently drop rows; accept exactly the approved key conjuncts.
            relationship, from_alias, to_alias = matched[0]
            if len(_conjuncts(predicate)) != len(relationship.from_columns):
                raise SemanticValidationError("Additional join conditions need an approved relationship definition.")
            if relationship.cardinality == "many_to_many":
                raise SemanticValidationError("Many-to-many analytics require a reviewed preaggregated view.")
            many_alias = from_alias if relationship.cardinality == "many_to_one" else to_alias
            # Joining another fact table through a dimension can duplicate all prior facts.
            duplicated_aliases = set(joined_aliases) if right_alias == many_alias else {right_alias}
            if relationship.cardinality != "one_to_one":
                for aggregate in scope.expression.find_all(exp.AggFunc):
                    if aggregate.find_ancestor(exp.Select) is not scope.expression:
                        continue
                    columns = list(aggregate.find_all(exp.Column))
                    if (isinstance(aggregate, (exp.Sum, exp.Avg, exp.Count))
                        and any(column.table in duplicated_aliases for column in columns)
                        and not isinstance(aggregate.this, exp.Distinct)):
                        raise SemanticValidationError("This aggregate can multiply values across a one-to-many join. Preaggregate at the fact grain.")
            joined_aliases.add(right_alias)


def _population_scopes(scope):
    """Filters can flow through single-source projections, but not alternate branches."""
    result, seen = [], set()
    while isinstance(scope.expression, exp.Select) and id(scope) not in seen:
        seen.add(id(scope))
        result.append(scope)
        sources = list(scope.selected_sources.values())
        if len(sources) != 1 or not isinstance(sources[0][1], Scope):
            break
        scope = sources[0][1]
    if not isinstance(scope.expression, exp.Select):
        raise SemanticValidationError("A set operation in the metric population needs a separately approved contract.")
    return result


def validate_sql(sql: str, catalog, intent=None, rules=()) -> ValidationResult:
    tree = validate_sql_schema(sql, catalog)
    scopes = list(traverse_scope(tree))
    _join_checks(scopes, catalog)
    checks = ["single read-only SQLite query", "authorized tables and columns", "approved joins and aggregation grain"]
    warnings = ["Deterministic checks cover recognized contracts; review the question and SQL before execution."]
    if intent is None:
        return ValidationResult(tuple(checks), tuple(warnings))
    if intent.status != "query":
        raise SemanticValidationError("This question requires clarification or is not supported.")
    if not scopes or not isinstance(scopes[-1].expression, exp.Select):
        if (intent.metric_ids or intent.predicates or intent.group_by or intent.limit is not None
            or intent.requested_columns or intent.having_predicates):
            raise SemanticValidationError("Set-operation semantics are not verified for this analytical contract.")
        return ValidationResult(tuple(checks), tuple(warnings))
    root = scopes[-1]
    for required in intent.requested_columns:
        projected = [_resolve(item, root)[0] for item in root.expression.expressions]
        if not any(isinstance(item, exp.Column) and item.name.upper() == required for item in projected):
            raise SemanticValidationError("The result omits a specifically requested employee field.")
    rule_map = {rule.id: rule for rule in rules}
    metric_scopes = []
    for metric_id in intent.metric_ids:
        if metric_id not in rule_map:
            raise SemanticValidationError("The requested metric definition is unavailable.")
        rule = rule_map[metric_id]
        matches = [_is_metric(item, root, rule) for item in root.expression.expressions]
        matches = [scope for scope in matches if scope is not None]
        if not matches:
            raise SemanticValidationError(f"The output must use the approved {rule.id} definition ({rule.aggregate}({rule.field})).")
        metric_scopes.extend(matches)
    if intent.metric_ids:
        checks.append("approved metric expressions appear in the result")
    relevant_scopes = metric_scopes or [root]
    for scope in relevant_scopes:
        if scope is not root and intent.metric_ids:
            for stage in _population_scopes(root):
                if stage is scope:
                    break
                if any(stage.expression.args.get(key) for key in ("where", "having", "group", "distinct", "offset", "joins")):
                    raise SemanticValidationError("An outer transformation changes the reviewed metric output.")
        group = scope.expression.args.get("group")
        actual = {_canonical(item) for item in group.expressions} if group else set()
        if intent.metric_ids and actual != set(intent.group_by):
            raise SemanticValidationError("GROUP BY does not match the requested analytical grain.")
        if intent.group_by:
            for name in intent.group_by:
                projected = [_resolve(item, root)[0] for item in root.expression.expressions]
                if not any(isinstance(item, exp.Column) and item.name.upper() == name for item in projected):
                    raise SemanticValidationError("The result must include the requested grouping dimension.")
        predicates = set()
        for population in _population_scopes(scope):
            if intent.metric_ids and population is not scope:
                source = population.expression
                if (source.args.get("limit") or source.args.get("offset") or source.args.get("distinct")
                    or source.args.get("group") or any(node.find_ancestor(exp.Select) is source for node in source.find_all(exp.AggFunc))):
                    raise SemanticValidationError("An upstream limit, aggregation or DISTINCT changes the metric population.")
            where = population.expression.args.get("where")
            if where:
                predicates.update(_canonical(item) for item in _conjuncts(where.this))
        for required in intent.predicates:
            expected = _canonical(sqlglot.parse_one(required, read="sqlite"))
            if expected not in predicates:
                raise SemanticValidationError(f"A required filter is missing or not guaranteed: {required}")
        if intent.strict_population:
            expected = {_canonical(sqlglot.parse_one(required, read="sqlite")) for required in intent.predicates}
            if predicates != expected:
                raise SemanticValidationError("An unrequested filter changes the metric population.")
        having = scope.expression.args.get("having")
        having_terms = {_canonical(item) for item in _conjuncts(having.this)} if having else set()
        for required in intent.having_predicates:
            if _canonical(sqlglot.parse_one(required, read="sqlite")) not in having_terms:
                raise SemanticValidationError(f"A required aggregate filter is missing: {required}")
    if intent.predicates:
        checks.append("required filters apply to the metric population")
    if intent.metric_ids:
        checks.append("requested grouping grain")
    if intent.limit is not None:
        limit = root.expression.args.get("limit")
        if limit is None or not isinstance(limit.expression, exp.Literal) or str(limit.expression.this) != str(intent.limit):
            raise SemanticValidationError("LIMIT does not match the requested number of results.")
        order = root.expression.args.get("order")
        if not order or not order.expressions or bool(order.expressions[0].args.get("desc")) != intent.descending:
            raise SemanticValidationError("The requested top/bottom ranking needs the correct ORDER BY direction.")
        ordered = order.expressions[0].this
        if intent.metric_ids:
            if isinstance(ordered, exp.Column) and not ordered.table:
                ordered = next((item for item in root.expression.expressions if item.alias_or_name.lower() == ordered.name.lower()), ordered)
            if not any(_is_metric(ordered, root, rule_map[metric_id]) is not None for metric_id in intent.metric_ids):
                raise SemanticValidationError("Rank by the requested metric, not another field.")
        elif intent.rank_by:
            resolved, _ = _resolve(ordered, root)
            if not isinstance(resolved, exp.Column) or resolved.name.upper() != intent.rank_by:
                raise SemanticValidationError("Rank by the requested employee field.")
        checks.append("requested ranking direction, metric and limit")
    return ValidationResult(tuple(checks), tuple(warnings))
