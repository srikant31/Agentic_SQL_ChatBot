"""Records every model request with the exact prompt it was given.

The chat binds who/which question/which version around a graph call with `bind(...)`. Model code
then calls `capture(...)`; outside a bound context (evaluation scripts, tests) capture does nothing,
so the graph and evaluation adapter behave exactly as before.
"""
from contextlib import contextmanager
import contextvars

_CONTEXT = contextvars.ContextVar("prompt_log_context", default=None)


@contextmanager
def bind(**context):
    token = _CONTEXT.set(context)
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def current():
    return _CONTEXT.get()


def capture(node, *, system, payload, response=None, error=None, latency_ms=None, usage=None):
    context = _CONTEXT.get()
    if context is None:
        return False
    import feedback_store
    store = feedback_store.get_store()
    if store is None:
        return False
    return store.record_llm_call(node=node, context=context, system=system, payload=payload,
                                 response=response, error=error, latency_ms=latency_ms, usage=usage)
