"""Small in-process BM25 index and approved relationship-path expansion."""
from collections import deque
from functools import lru_cache
import re

from rank_bm25 import BM25Plus

from context_models import SearchDocument, SearchHit


def tokenize(text: str) -> list[str]:
    identifiers = re.findall(r"[a-z0-9_]+", text.lower())
    return [part for token in identifiers for part in ([token] + token.split("_") if "_" in token else [token])]


class BM25Index:
    def __init__(self, documents):
        self.documents = tuple(documents)
        self.tokens = tuple(tuple(tokenize(document.text)) for document in self.documents)
        self.model = BM25Plus([list(tokens) for tokens in self.tokens]) if any(self.tokens) else None

    def search(self, question: str, k: int = 5) -> tuple[SearchHit, ...]:
        query = tokenize(question)
        if not self.model or not query or k <= 0:
            return ()
        scores = self.model.get_scores(query)
        # BM25Plus has a smoothing baseline: nonzero scores do not prove lexical overlap.
        eligible = [i for i, tokens in enumerate(self.tokens) if set(query).intersection(tokens)]
        ranked = sorted(eligible, key=lambda i: (-float(scores[i]), self.documents[i].id))[:k]
        return tuple(SearchHit(self.documents[i], float(scores[i])) for i in ranked)


@lru_cache(maxsize=32)
def cached_index(documents: tuple[SearchDocument, ...]) -> BM25Index:
    return BM25Index(documents)


def build_documents(catalog, rules) -> tuple[SearchDocument, ...]:
    documents = [SearchDocument(f"table:{table.name}", "table",
        f"{table.name} {table.description} " + " ".join(f"{c.name} {c.description}" for c in table.columns),
        (table.name,)) for table in catalog.tables]
    documents.extend(SearchDocument(f"rule:{rule.id}", "rule",
        f"{rule.description} {' '.join(rule.aliases)} {' '.join(rule.columns)}",
        tuple(sorted({column.split('.')[0] for column in rule.columns}))) for rule in rules)
    return tuple(documents)


def expand_relationships(selected_tables: set[str], catalog, *, max_hops: int = 2):
    """Connect selected endpoints using unique bounded approved paths. Never invent edges."""
    available = {table.name: {column.name for column in table.columns} for table in catalog.tables}
    if not selected_tables.issubset(available):
        raise ValueError("A selected table is outside the authorized catalog.")
    edges = []
    for relationship in catalog.relationships:
        if not relationship.approved:
            continue
        if not relationship.from_columns or len(relationship.from_columns) != len(relationship.to_columns):
            raise ValueError("Invalid composite relationship.")
        if (relationship.from_table in available and relationship.to_table in available
            and set(relationship.from_columns).issubset(available[relationship.from_table])
            and set(relationship.to_columns).issubset(available[relationship.to_table])):
            edges.append(relationship)
    graph = {name: [] for name in available}
    for edge in edges:
        graph[edge.from_table].append((edge.to_table, edge))
        graph[edge.to_table].append((edge.from_table, edge))
    chosen, connected = {}, set()
    targets = sorted(selected_tables)
    if targets:
        connected.add(targets[0])
    for target in targets[1:]:
        queue = deque((start, (), frozenset({start})) for start in sorted(connected))
        found, shortest = [], None
        while queue:
            node, path, visited = queue.popleft()
            if node == target:
                shortest = len(path)
                found.append(path)
                continue
            if len(path) >= max_hops or (shortest is not None and len(path) >= shortest):
                continue
            for neighbor, edge in graph[node]:
                if neighbor not in visited:
                    queue.append((neighbor, path + (edge,), visited | {neighbor}))
        distinct = {tuple(edge.name for edge in path): path for path in found}
        if not distinct:
            raise ValueError("No approved relationship path connects the requested tables.")
        if len(distinct) != 1:
            raise ValueError("Multiple approved join paths exist; clarify the relationship.")
        for edge in next(iter(distinct.values())):
            chosen[edge.name] = edge
            connected.update((edge.from_table, edge.to_table))
    return frozenset(connected), tuple(chosen[name] for name in sorted(chosen))
