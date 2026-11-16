"""Cached checkpoint resource and identity-bound browser thread configuration."""
from dataclasses import dataclass
import hashlib
import os
import uuid

import streamlit as st
from langgraph.checkpoint.memory import InMemorySaver


@dataclass
class CheckpointResource:
    saver: object
    persistent: bool
    pool: object = None


@st.cache_resource(show_spinner=False)
def get_checkpointer():
    url = os.getenv("PG_URL")
    if not url:
        return CheckpointResource(InMemorySaver(), False)
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
    from langgraph.checkpoint.postgres import PostgresSaver
    pool = ConnectionPool(url, min_size=1, max_size=5,
                          kwargs={"autocommit": True, "row_factory": dict_row})
    try:
        pool.wait(timeout=10)
        saver = PostgresSaver(pool)
        saver.setup()
    except Exception:
        pool.close()
        raise
    return CheckpointResource(saver, True, pool)


def thread_config(user, tid, role, model):
    from rbac import check_user
    check_user(user)
    # Auth already exists: bind thread IDs to server-owned identity AND policy role.
    # TODO replace shared demo identities before allowing private production data.
    token = str(uuid.UUID(str(tid)))
    owner = hashlib.sha256(f"{user.username}:{role}".encode()).hexdigest()
    return {"configurable": {"thread_id": f"coldchain:{owner}:{token}"}, "recursion_limit": 40,
            "tags": ["sql-chatbot"], "metadata": {"model": model, "role": role}}
