"""Dialect-aware statement and identifier checks; SQLite remains the execution boundary."""
import sqlite3

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, traverse_scope


class UnsafeQueryError(Exception):
    """Raised when a SQL query fails the read-only safety check."""
    pass


class SchemaValidationError(sqlite3.DatabaseError):
    """The query cannot bind to the authorized logical schema."""


def parse_readonly_sql(sql: str):
    if not isinstance(sql, str) or not sql.strip():
        raise UnsafeQueryError("Empty SQL query.")
    if len(sql) > 20_000:
        raise UnsafeQueryError("SQL exceeds the 20,000-character limit.")
    try:
        statements = sqlglot.parse(sql, read="sqlite")
    except Exception as exc:
        raise UnsafeQueryError("Unable to parse the SQLite query.") from exc

    if len(statements) != 1:
        raise UnsafeQueryError(
            "Multiple SQL statements are not allowed — only one query per request."
        )

    tree = statements[0]
    if tree is None or not isinstance(tree, exp.Query):
        raise UnsafeQueryError(
            "Only read-only queries (SELECT, or a UNION/INTERSECT/EXCEPT of "
            "SELECTs) are allowed. This query was rejected before it ever "
            "reached the database."
        )
    forbidden = (exp.DML, exp.DDL, exp.Into, exp.Lock, exp.Command, exp.Pragma,
                 exp.Attach, exp.Transaction, exp.Grant, exp.Revoke)
    if any(isinstance(node, forbidden) for node in tree.walk()):
        raise UnsafeQueryError("Write operations, output targets and locking are not allowed anywhere in a query.")
    return tree


def validate_readonly_sql(sql: str) -> None:
    parse_readonly_sql(sql)


def validate_sql_schema(sql: str, catalog):
    tree = parse_readonly_sql(sql)
    available = {table.name.upper() for table in catalog.tables}
    for node in tree.walk():
        if isinstance(node, exp.Func) and node.sql_name().lower() in {"readfile", "writefile", "load_extension"}:
            raise SchemaValidationError("File and extension functions are unavailable.")
        if isinstance(node, exp.Anonymous) and node.name.lower() in {"readfile", "writefile", "load_extension", "eval"}:
            raise SchemaValidationError("File and extension functions are unavailable.")
    for scope in traverse_scope(tree):
        for source in scope.sources.values():
            if isinstance(source, exp.Table):
                if source.db or source.catalog or not isinstance(source.this, exp.Identifier) or source.name.upper() not in available:
                    raise SchemaValidationError("A table is outside your authorized logical schema.")
            elif not isinstance(source, Scope):
                raise SchemaValidationError("Only authorized tables and query scopes are supported.")
    try:
        return qualify(tree.copy(), dialect=catalog.dialect, schema=catalog.sqlglot_schema(),
                       infer_schema=False, validate_qualify_columns=True)
    except Exception as exc:
        raise SchemaValidationError("A column, alias or query scope does not match your authorized schema.") from exc
