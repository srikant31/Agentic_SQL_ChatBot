"""ColdChain MySQL guard shared by the graph and independent golden evaluator."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, traverse_scope


def fixture_schema():
    result = {}
    for statement in sqlglot.parse((Path(__file__).parent / "golden_eval/schema.sql").read_text(encoding="utf-8"), read="mysql"):
        if isinstance(statement, exp.Create) and isinstance(statement.this, exp.Schema):
            result[statement.this.this.name.lower()] = {column.name.lower(): column.args["kind"].sql(dialect="mysql")
                for column in statement.this.expressions if isinstance(column, exp.ColumnDef)}
    return result


_SCHEMA = fixture_schema()
_CONNECTED = ContextVar("coldchain_catalog", default=None)


@contextmanager
def connected_catalog(schema, database="coldchain"):
    """Request-local connected schema; cannot broaden the approved domain table set."""
    token = _CONNECTED.set((schema, database))
    try:
        yield
    finally:
        _CONNECTED.reset(token)


def inspect_query(sql, role="viewer"):
    from departments import allowed_tables, hidden_columns, label
    allowed, hidden = allowed_tables(role), hidden_columns(role)   # raises ValueError for unknown roles
    if not isinstance(sql, str) or not sql.strip() or len(sql) > 20000:
        raise ValueError("Enter a single query of at most 20000 characters.")
    try:
        statements = sqlglot.parse(sql, read="mysql")
    except Exception as exc:
        raise ValueError("Cannot parse MySQL query.") from exc
    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union)):
        raise ValueError("Exactly one SELECT or UNION is allowed.")
    stmt = statements[0]
    forbidden = (exp.DML, exp.DDL, exp.Into, exp.Lock, exp.Command)
    if any(isinstance(node, forbidden) for node in stmt.walk()):
        raise ValueError("Writes, output targets and locking are not allowed.")
    for function in stmt.find_all(exp.Func):
        name = function.name.lower() if isinstance(function, exp.Anonymous) else function.sql_name().lower()
        if name in {"load_file", "sleep", "benchmark", "get_lock", "release_lock", "now", "curdate", "current_date", "current_timestamp", "sysdate"}:
            raise ValueError("Side-effecting or non-deterministic functions are unavailable; use 2026-06-30.")
    if any(isinstance(node, (exp.Parameter, exp.SessionParameter)) for node in stmt.walk()):
        raise ValueError("Session variables are unavailable.")
    schema, database = _CONNECTED.get() or (_SCHEMA, "coldchain")
    tables = set()
    for scope in traverse_scope(stmt):
        for source in scope.sources.values():
            if isinstance(source, exp.Table):
                name = source.name.lower()
                if source.catalog or (source.db and source.db.lower() != database.lower()):
                    raise ValueError("Other database schemas are unavailable.")
                if not isinstance(source.this, exp.Identifier) or name not in _SCHEMA or name not in schema:
                    raise ValueError("Table outside the approved connected catalog.")
                if name not in allowed:
                    raise ValueError(f"The {label(role)} department may not read {name}.")
                tables.add(name)
                # Normalize an approved explicit database prefix for schema qualification.
                source.set("db", None)
            elif not isinstance(source, Scope):
                raise ValueError("Unsupported query source.")
    if hidden:
        if any(column.name.lower() in hidden for column in stmt.find_all(exp.Column)):
            raise ValueError(f"The {label(role)} department may not read: " + ", ".join(sorted(hidden)) + ".")
        # SELECT * would return hidden columns, so it is refused on any table that has one (COUNT(*) is fine).
        if any(set(_SCHEMA.get(table, {})) & hidden for table in tables):
            for select in stmt.find_all(exp.Select):
                source = select.args.get("from_")
                if select is stmt and source and isinstance(source.this, exp.Subquery) and isinstance(source.this.this, exp.Union):
                    continue  # generated UNION cap; inner projections/columns remain checked
                if any(isinstance(item, exp.Star) or (isinstance(item, exp.Column) and isinstance(item.this, exp.Star)) for item in select.expressions):
                    raise ValueError("SELECT * could expose columns this department may not read; name the columns (COUNT(*) is allowed).")
    try:
        qualify(stmt.copy(), dialect="mysql", schema=schema, infer_schema=False, validate_qualify_columns=True)
    except Exception as exc:
        raise ValueError("Unknown or ambiguous field in the connected schema.") from exc
    return stmt, tables


def validate(sql: str, role: str = "viewer", limit: int = 100) -> str:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("Result cap must be between 1 and 100.")
    stmt, _ = inspect_query(sql, role)
    if isinstance(stmt, exp.Union):
        stmt = exp.select("*").from_(stmt.subquery("capped")).limit(limit)
    else:
        current = stmt.args.get("limit")
        if current:
            amount = current.expression
            if not isinstance(amount, exp.Literal) or not amount.is_int:
                raise ValueError("LIMIT must be a nonnegative integer literal.")
            if int(amount.this) < 0:
                raise ValueError("LIMIT must be nonnegative.")
            limit = min(limit, int(amount.this))
        stmt = stmt.limit(limit)
    return stmt.sql(dialect="mysql")
