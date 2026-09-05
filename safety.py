import sqlglot
from sqlglot.expressions import Select


class UnsafeQueryError(Exception):
    """Raised when a SQL query fails the read-only safety check."""
    pass


def validate_readonly_sql(sql: str) -> None:
    """
    Ensures the given SQL is a single, read-only SELECT statement.
    Raises UnsafeQueryError if it isn't.
    """
    try:
        statements = sqlglot.parse(sql)
    except Exception as exc:
        raise UnsafeQueryError(f"Unable to parse SQL query: {exc}") from exc

    if not statements:
        raise UnsafeQueryError("Empty SQL query.")

    if len(statements) > 1:
        raise UnsafeQueryError(
            "Multiple SQL statements are not allowed — only one SELECT per query."
        )

    if not isinstance(statements[0], Select):
        raise UnsafeQueryError(
            "Only SELECT statements are allowed. This query was rejected before it "
            "ever reached the database."
        )