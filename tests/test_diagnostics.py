import logging

import diagnostics


class _Collect(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def _capture(action):
    handler = _Collect()
    diagnostics._LOGGER.addHandler(handler)
    try:
        action()
    finally:
        diagnostics._LOGGER.removeHandler(handler)
    return " ".join(handler.lines)


def test_failure_logs_exception_class_but_never_message_sql_or_free_text():
    text = _capture(lambda: diagnostics.log_failure(
        "query_failed", ValueError("password=hunter2 SELECT SALARY FROM EMPLOYEES"),
        table="EMPLOYEES", sql="SELECT * FROM t WHERE a = 'x y'", note="has spaces"))
    assert "event=query_failed" in text and "error=ValueError" in text and "table=EMPLOYEES" in text
    assert "hunter2" not in text and "SELECT" not in text and "has spaces" not in text


def test_event_accepts_numbers_and_safe_identifiers_only():
    text = _capture(lambda: diagnostics.log_event("retrieval", count=3, example="visible-count", raw="a b"))
    assert "count=3" in text and "example=visible-count" in text and "a b" not in text
