from unittest.mock import Mock, patch
import pytest
from checkpointing import get_checkpointer, thread_config
from rbac import USERS


def test_thread_namespaces_prevent_cross_user_and_role_access():
    tid = "9f521a80-10a3-44a8-aaab-70acdb0c6685"
    employee = thread_config(USERS["employee"], tid, "viewer", "model")
    hr = thread_config(USERS["hr"], tid, "viewer", "model")
    elevated = thread_config(USERS["employee"], tid, "admin", "model")
    assert len({x["configurable"]["thread_id"] for x in [employee, hr, elevated]}) == 3
    with pytest.raises(ValueError): thread_config(USERS["hr"], "not-a-uuid", "viewer", "model")


def test_memory_fallback_when_pg_missing(monkeypatch):
    monkeypatch.delenv("PG_URL", raising=False)
    get_checkpointer.clear()
    assert not get_checkpointer().persistent
    get_checkpointer.clear()


def test_postgres_pool_setup_and_failure_cleanup(monkeypatch):
    monkeypatch.setenv("PG_URL", "postgresql://example.invalid/checkpoints")
    get_checkpointer.clear()
    with patch("psycopg_pool.ConnectionPool") as pool, patch("langgraph.checkpoint.postgres.PostgresSaver") as saver:
        resource = get_checkpointer()
        assert resource.persistent
        assert pool.call_args.kwargs["max_size"] == 5
        assert pool.call_args.kwargs["kwargs"]["autocommit"] is True
        saver.return_value.setup.assert_called_once()
    get_checkpointer.clear()
    with patch("psycopg_pool.ConnectionPool") as pool, patch("langgraph.checkpoint.postgres.PostgresSaver") as saver:
        saver.return_value.setup.side_effect = RuntimeError("unavailable")
        with pytest.raises(RuntimeError): get_checkpointer()
        pool.return_value.close.assert_called_once()
    get_checkpointer.clear()
