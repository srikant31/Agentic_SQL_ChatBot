import pytest
from safety import validate_readonly_sql, UnsafeQueryError


def test_allows_plain_select():
    """The basic case: a normal SELECT must pass. If this fails, nothing else matters."""
    validate_readonly_sql("SELECT * FROM EMPLOYEES")


def test_allows_select_case_insensitive():
    """SQL keywords aren't case-sensitive. Gemini might generate lowercase
    'select' — the guardrail shouldn't accidentally reject valid SQL just
    because of letter casing."""
    validate_readonly_sql("select * from employees")


def test_allows_select_with_trailing_semicolon_and_whitespace():
    """Real generated SQL often has a trailing semicolon and surrounding
    whitespace from formatting. This must not break parsing."""
    validate_readonly_sql("  SELECT * FROM EMPLOYEES;  ")


def test_allows_select_with_trailing_comment():
    """A SQL comment after the query (e.g. '-- explanation') is common in
    generated SQL and must not be mistaken for a second statement."""
    validate_readonly_sql("SELECT * FROM EMPLOYEES WHERE ID = 1 -- get one row")


def test_allows_cte_select():
    """A WITH...SELECT (common table expression) is a single, entirely
    read-only statement, and Gemini may reasonably generate one for
    multi-step questions like 'the full reporting chain'. This confirms
    the guardrail doesn't reject legitimate complex-but-safe SQL."""
    validate_readonly_sql(
        "WITH mgrs AS (SELECT MANAGER_ID FROM EMPLOYEES) SELECT * FROM mgrs"
    )


def test_blocks_delete():
    """The core promise of this guardrail: a DELETE must never pass, no
    matter what the AI decided to generate."""
    with pytest.raises(UnsafeQueryError):
        validate_readonly_sql("DELETE FROM EMPLOYEES")


def test_blocks_drop():
    """Same guarantee for DROP TABLE — the single most destructive
    statement this guardrail exists to prevent."""
    with pytest.raises(UnsafeQueryError):
        validate_readonly_sql("DROP TABLE EMPLOYEES")


def test_blocks_update():
    """UPDATE is arguably more dangerous than DELETE in some ways (silent
    data corruption vs. obvious data loss) — worth its own explicit test
    rather than assuming DELETE coverage implies UPDATE coverage."""
    with pytest.raises(UnsafeQueryError):
        validate_readonly_sql("UPDATE EMPLOYEES SET NAME = 'x'")


def test_blocks_stacked_statements():
    """The classic SQL injection pattern: a valid-looking SELECT followed
    by a destructive statement, relying on naive checks that only look at
    the first few characters. sqlglot parses the full string, so this
    must be caught as 'more than one statement', not silently allowed."""
    with pytest.raises(UnsafeQueryError):
        validate_readonly_sql("SELECT * FROM EMPLOYEES; DROP TABLE EMPLOYEES;")


def test_blocks_empty_string():
    """An empty or missing query should never be silently treated as
    'nothing to do' — it should be explicitly rejected so a bug upstream
    (e.g. Gemini returning an empty 'sql' field) is loud, not silent."""
    with pytest.raises(UnsafeQueryError):
        validate_readonly_sql("")


def test_blocks_whitespace_only_string():
    """Same intent as the empty-string test, but for the sneakier case of
    a string that LOOKS non-empty (has characters) but contains nothing
    meaningful once parsed."""
    with pytest.raises(UnsafeQueryError):
        validate_readonly_sql("   ")


def test_blocks_show_tables():
    """SHOW TABLES is technically read-only and harmless, but it's not a
    SELECT — this test documents the guardrail's actual behavior (reject
    it) as a deliberate choice, so a future reader knows this was tested
    and decided, not accidentally missed."""
    with pytest.raises(UnsafeQueryError):
        validate_readonly_sql("SHOW TABLES")


@pytest.mark.xfail(
    reason=(
        "KNOWN GAP: sqlglot parses a parenthesized top-level SELECT as a "
        "'Subquery' node, not 'Select'. isinstance() check misses this, so "
        "a harmless query like '(SELECT * FROM EMPLOYEES)' is incorrectly "
        "rejected. This is a false positive, not a security hole, but it's "
        "a real bug worth fixing — see safety.py's isinstance check."
    )
)
def test_allows_parenthesized_select():
    """This SHOULD pass (it's a safe, read-only query) but currently
    doesn't. Marked as an expected failure (xfail) rather than deleted,
    so pytest tracks it as a known issue instead of it silently
    disappearing from the test suite."""
    validate_readonly_sql("(SELECT * FROM EMPLOYEES)")

def test_allows_parenthesized_select():
    """Previously failed — a parenthesized SELECT parses as Subquery, not
    Select. Fixed by checking against sqlglot's Query base class instead."""
    validate_readonly_sql("(SELECT * FROM EMPLOYEES)")


def test_allows_union_of_selects():
    """A UNION combining two SELECTs is still fully read-only. Confirms
    the Query-based check correctly recognizes this shape too."""
    validate_readonly_sql("SELECT NAME FROM EMPLOYEES UNION SELECT NAME FROM EMPLOYEES")


def test_blocks_union_followed_by_stacked_drop():
    """A UNION can't smuggle in a DROP as a second 'branch' of the union
    (that's not valid SQL), but someone might try stacking a DROP after
    a valid UNION as a separate statement — confirms the multi-statement
    check still catches this regardless of the Query-type fix."""
    with pytest.raises(UnsafeQueryError):
        validate_readonly_sql(
            "SELECT * FROM EMPLOYEES UNION SELECT * FROM EMPLOYEES; DROP TABLE EMPLOYEES"
        )