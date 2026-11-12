"""Local diagnostics: one-line structured logs for failures the UI otherwise hides.

Deliberately never records result rows, SQL text, SQL parameters, exception messages or credentials.
Only the event name, the exception class and short identifier-like fields are written. Tracebacks are
attached only when SQL_AGENT_LOG_LEVEL=DEBUG (for local development).
"""
import logging
import os
import re
import sys

_SAFE_VALUE = re.compile(r"^[\w.\-]{1,40}$")
_LOGGER = logging.getLogger("sqlagent")
if not _LOGGER.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _LOGGER.addHandler(_handler)
    _LOGGER.setLevel(os.getenv("SQL_AGENT_LOG_LEVEL", "INFO").upper())
    _LOGGER.propagate = False


def _fields(fields: dict) -> str:
    return " ".join(f"{key}={value}" for key, value in fields.items()
                    if isinstance(value, (int, float, bool)) or (isinstance(value, str) and _SAFE_VALUE.match(value)))


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    _LOGGER.log(level, "event=%s %s", event, _fields(fields))


def log_failure(event: str, exc: BaseException, **fields) -> None:
    _LOGGER.error("event=%s error=%s %s", event, type(exc).__name__, _fields(fields),
                  exc_info=exc if _LOGGER.isEnabledFor(logging.DEBUG) else False)
