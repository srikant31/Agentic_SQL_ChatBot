import sqlglot
from sqlglot.expressions import Query


class UnsafeQueryError(Exception):
    """Raised when a SQL query fails the read-only safety check."""
    pass


def validate_readonly_sql(sql: str) -> None:
    """
    Ensures the given SQL is a single, read-only query.
    Raises UnsafeQueryError if it isn't.

    Checks against sqlglot's `Query` base class rather than just `Select`,
    since a parenthesized SELECT parses as `Subquery`, and a UNION/INTERSECT/
    EXCEPT of SELECTs parses as its own node type — all of these are
    equally read-only, and `Query` is sqlglot's own semantic grouping for
    exactly that family, with no destructive statement type included in it.
    """
    try:
        statements = sqlglot.parse(sql)
    except Exception as exc:
        raise UnsafeQueryError(f"Unable to parse SQL query: {exc}") from exc

    if not statements or statements[0] is None:
        raise UnsafeQueryError("Empty SQL query.")

    if len(statements) > 1:
        raise UnsafeQueryError(
            "Multiple SQL statements are not allowed — only one query per request."
        )

    if not isinstance(statements[0], Query):
        raise UnsafeQueryError(
            "Only read-only queries (SELECT, or a UNION/INTERSECT/EXCEPT of "
            "SELECTs) are allowed. This query was rejected before it ever "
            "reached the database."
        )