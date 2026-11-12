"""Explicitly configured ColdChain source, metadata/value context and bounded reads."""
import json
import os
from pathlib import Path

import streamlit as st
from sqlalchemy import create_engine, inspect, text
from sql_guard import _SCHEMA, connected_catalog, validate


@st.cache_resource(show_spinner=False)
def get_coldchain_engine():
    url = os.getenv("COLDCHAIN_DB_URL") or os.getenv("EVAL_DB_URL")
    if not url:
        raise ValueError("Configure COLDCHAIN_DB_URL with a read-only ColdChain MySQL account.")
    engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=0,
                           connect_args={"connect_timeout": 10, "read_timeout": 15})
    if engine.dialect.name != "mysql":
        engine.dispose()
        raise ValueError("The ColdChain source must use MySQL with a read-only account.")
    return engine


def get_schema_context(question="", role="viewer", engine=None):
    if role not in {"viewer", "admin"}:
        raise ValueError("Unknown analytics role.")
    engine = engine if engine is not None else get_coldchain_engine()
    inspector = inspect(engine)
    names = set(inspector.get_table_names()) & set(_SCHEMA)
    if role == "viewer":
        names.discard("employees")
    if not names:
        raise ValueError("No approved ColdChain tables exist in the configured database.")
    records, schema = [], {}
    quote = engine.dialect.identifier_preparer.quote
    with engine.connect() as connection:
        for table in sorted(names):
            columns = []
            schema[table] = {}
            for col in inspector.get_columns(table):
                name = col["name"]
                if role == "viewer" and name.lower() in {"email", "salary_inr"}:
                    continue
                schema[table][name] = str(col["type"])
                entry = {"name": name, "type": str(col["type"]), "comment": col.get("comment") or "",
                         "nullable": col.get("nullable", True)}
                values = getattr(col["type"], "enums", None)
                if values:
                    entry["values"] = values
                elif name in {"status", "segment", "category", "city"} or (table == "regions" and name == "name"):
                    result = connection.execute(text(f"SELECT DISTINCT {quote(name)} FROM {quote(table)} WHERE {quote(name)} IS NOT NULL LIMIT 21"))
                    values = [row[0] for row in result]
                    if len(values) <= 20:
                        entry["values"] = values
                columns.append(entry)
            try:
                comment = inspector.get_table_comment(table).get("text") or ""
            except NotImplementedError:
                comment = ""
            foreign_keys = [fk for fk in inspector.get_foreign_keys(table) if fk["referred_table"] in names]
            records.append({"table": table, "comment": comment, "columns": columns,
                            "primary_key": inspector.get_pk_constraint(table).get("constrained_columns"),
                            "relationships": foreign_keys})
    glossary = (Path(__file__).parent / "golden_eval/business_glossary.md").read_text(encoding="utf-8")
    return {"schema": schema, "database": engine.url.database or "coldchain",
            "text": "Evaluation date: 2026-06-30. Never use NOW() or CURDATE().\n"
                    + json.dumps(records, default=str) + "\n" + glossary}


def execute_readonly(sql, role, engine=None):
    engine = engine if engine is not None else get_coldchain_engine()
    context = get_schema_context(role=role, engine=engine)
    with connected_catalog(context["schema"], context["database"]):
        safe = validate(sql, role)
    with engine.connect() as connection:
        connection.execute(text("SET SESSION MAX_EXECUTION_TIME=10000"))
        connection.execute(text("SET TRANSACTION READ ONLY"))
        result = connection.execute(text(safe))
        rows = result.fetchmany(101)
        if len(rows) > 100:
            raise ValueError("Result exceeded the 100-row guard cap.")
        columns = list(result.keys())
        return columns, [list(row) for row in rows]
