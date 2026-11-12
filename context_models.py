"""Immutable contracts for the authorized analytics context (never database rows)."""
from dataclasses import asdict, dataclass
import hashlib
import json


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class ColumnRecord:
    name: str
    data_type: str
    nullable: bool = True
    description: str = ""
    source_type: str = ""


@dataclass(frozen=True)
class TableRecord:
    name: str
    columns: tuple[ColumnRecord, ...]
    primary_key: tuple[str, ...] = ()
    source_name: str = ""
    description: str = ""


@dataclass(frozen=True)
class RelationshipRecord:
    name: str
    from_table: str
    from_columns: tuple[str, ...]
    to_table: str
    to_columns: tuple[str, ...]
    cardinality: str = "many_to_one"
    provenance: str = "database_fk"
    approved: bool = True


@dataclass(frozen=True)
class SchemaCatalog:
    tables: tuple[TableRecord, ...]
    relationships: tuple[RelationshipRecord, ...] = ()
    dialect: str = "sqlite"
    scope: str = ""

    @property
    def version(self) -> str:
        # Metadata descriptions affect retrieval too, so changes invalidate proposals.
        return fingerprint({
            "dialect": self.dialect, "scope": self.scope,
            "tables": [{"name": t.name, "description": t.description,
                        "columns": [(c.name, c.data_type, c.nullable, c.description) for c in t.columns],
                        "primary_key": t.primary_key} for t in self.tables],
            "relationships": [asdict(r) for r in self.relationships],
        })

    def sqlglot_schema(self) -> dict:
        return {t.name: {c.name: c.data_type for c in t.columns} for t in self.tables}

    def render(self) -> str:
        statements = ["CREATE TABLE " + t.name + " (" + ", ".join(
            f"{c.name} {c.data_type}" for c in t.columns) + ");" for t in self.tables]
        return "\n".join(statements) + f"\nExecution dialect: {self.dialect}. Authorized scope: {self.scope}"


@dataclass(frozen=True)
class BusinessRule:
    id: str
    kind: str
    description: str
    aliases: tuple[str, ...]
    columns: tuple[str, ...]
    version: int = 1
    aggregate: str = ""
    field: str = ""
    predicates: tuple[str, ...] = ()
    permission: str = ""
    distinct: bool = False
    unit: str = ""
    time_basis: str = ""


@dataclass(frozen=True)
class Intent:
    status: str = "query"
    message: str = ""
    rule_ids: tuple[str, ...] = ()
    metric_ids: tuple[str, ...] = ()
    group_by: tuple[str, ...] = ()
    predicates: tuple[str, ...] = ()
    limit: int | None = None
    descending: bool | None = None
    rank_by: str = ""
    having_predicates: tuple[str, ...] = ()
    requested_columns: tuple[str, ...] = ()
    strict_population: bool = False


@dataclass(frozen=True)
class SearchDocument:
    id: str
    kind: str
    text: str
    tables: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchHit:
    document: SearchDocument
    score: float


@dataclass(frozen=True)
class ContextPackage:
    catalog: SchemaCatalog
    rules: tuple[BusinessRule, ...]
    intent: Intent
    hits: tuple[SearchHit, ...]
    examples: tuple[dict, ...]
    version: str
    prompt_context: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationResult:
    checks: tuple[str, ...]
    warnings: tuple[str, ...] = ()

