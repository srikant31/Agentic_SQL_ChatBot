"""Read-only reflection, explicit logical projection, and bounded metadata caching."""
import hashlib
import re

import streamlit as st
from sqlalchemy import inspect

from context_models import ColumnRecord, RelationshipRecord, SchemaCatalog, TableRecord
from rbac import require, scope_description, visible_columns

SOURCE_TABLE = "RBAC_DEMO_EMPLOYEES"
METADATA_TTL_SECONDS = 300
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class CatalogError(ValueError):
    pass


def extract_catalog(engine, allowed_sources: set[str]) -> SchemaCatalog:
    """Inspect only configured sources; discovering a table does not grant access."""
    inspector = inspect(engine)
    tables, relationships = [], []
    for name in sorted(allowed_sources):
        if not _IDENTIFIER.fullmatch(name) or not inspector.has_table(name):
            raise CatalogError("An approved source table is unavailable.")
        columns = []
        for column in inspector.get_columns(name):
            if not _IDENTIFIER.fullmatch(column["name"]):
                raise CatalogError("An approved source contains an unsupported identifier.")
            source_type = str(column["type"])
            affinity = getattr(column["type"], "_type_affinity", type(column["type"])).__name__.lower()
            if "int" in affinity:
                logical_type = "INTEGER"
            elif any(word in affinity for word in ("numeric", "float", "real")):
                logical_type = "REAL"
            elif "binary" in affinity:
                logical_type = "BLOB"
            else:
                logical_type = "TEXT"
            columns.append(ColumnRecord(column["name"], logical_type, column.get("nullable", True),
                                        column.get("comment") or "", source_type))
        primary_key = tuple(inspector.get_pk_constraint(name).get("constrained_columns") or ())
        unique_keys = {primary_key} | {tuple(item.get("column_names") or ()) for item in inspector.get_unique_constraints(name)}
        try:
            description = inspector.get_table_comment(name).get("text") or ""
        except NotImplementedError:
            description = ""
        tables.append(TableRecord(name, tuple(columns), primary_key, name, description))
        for index, fk in enumerate(inspector.get_foreign_keys(name)):
            if fk["referred_table"] in allowed_sources:
                relationships.append(RelationshipRecord(
                    fk.get("name") or f"{name}_fk_{index}", name, tuple(fk["constrained_columns"]),
                    fk["referred_table"], tuple(fk["referred_columns"]),
                    "one_to_one" if tuple(fk["constrained_columns"]) in unique_keys else "many_to_one"))
    return SchemaCatalog(tuple(tables), tuple(relationships))


@st.cache_data(ttl=METADATA_TTL_SECONDS, max_entries=16, show_spinner=False)
def _cached_extract(source_key: str, _engine) -> SchemaCatalog:
    return extract_catalog(_engine, {SOURCE_TABLE})


def project_catalog(catalog: SchemaCatalog, user) -> SchemaCatalog:
    require(user, "query")
    source = next((table for table in catalog.tables if table.name == SOURCE_TABLE), None)
    if source is None:
        raise CatalogError("The approved employee source is unavailable.")
    names = visible_columns(user)
    available = {column.name: column for column in source.columns}
    if not set(names).issubset(available):
        raise CatalogError("The employee schema changed. Refresh the approved mapping before querying.")
    if source.primary_key != ("EMPLOYEE_ID",):
        raise CatalogError("The employee identity key changed. Review the snapshot grain before querying.")
    # These are the types used by the existing snapshot, now verified against reflection.
    for name in names:
        expected = "INTEGER" if name in {"EMPLOYEE_ID", "SALARY"} else "TEXT"
        if available[name].data_type != expected:
            raise CatalogError("An employee column changed type. Review the snapshot mapping.")
    table = TableRecord("EMPLOYEES", tuple(available[name] for name in names),
                        tuple(c for c in source.primary_key if c in names), SOURCE_TABLE,
                        "One row per authorized employee. Manager name is a label, not a unique join key.")
    # No other physical source or candidate relationship is exposed by this mapping.
    return SchemaCatalog((table,), scope=scope_description(user))


def get_catalog(user, engine, *, refresh: bool = False) -> SchemaCatalog:
    require(user, "query")
    if refresh or engine.url.database in {None, "", ":memory:"}:
        physical = extract_catalog(engine, {SOURCE_TABLE})
    else:
        # Identity only; the URI is never emitted or used as a human-readable cache key.
        identity = engine.url.render_as_string(hide_password=False)
        source_key = hashlib.sha256(identity.encode()).hexdigest()
        physical = _cached_extract(source_key, engine)
    return project_catalog(physical, user)


def dependency_version(catalog: SchemaCatalog, tables, columns) -> str:
    from context_models import fingerprint
    schema = catalog.sqlglot_schema()
    selected = {}
    for table in sorted(tables):
        if table not in schema:
            raise CatalogError("Example references an unavailable table.")
        selected[table] = {}
    for reference in sorted(columns):
        table, column = reference.split(".", 1)
        if table not in selected or column not in schema.get(table, {}):
            raise CatalogError("Example references an unavailable column.")
        selected[table][column] = schema[table][column]
    return fingerprint({"dialect": catalog.dialect, "dependencies": selected})
