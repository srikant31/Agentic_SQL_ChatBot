from dataclasses import replace

import pytest

from context_models import ColumnRecord, RelationshipRecord, SchemaCatalog, SearchDocument, TableRecord
from retrieval import BM25Index, expand_relationships


def test_tiny_corpus_and_no_overlap_do_not_return_arbitrary_hits():
    index = BM25Index((SearchDocument("salary", "rule", "recorded salary total"),))
    assert index.search("recorded salary")[0].document.id == "salary"
    assert index.search("unrelated refunds") == ()
    assert BM25Index(()).search("anything") == ()
    assert BM25Index((SearchDocument("empty", "rule", ""),)).search("anything") == ()


def graph():
    tables = tuple(TableRecord(name, (ColumnRecord("ID", "INTEGER"), ColumnRecord("OTHER_ID", "INTEGER")))
                   for name in ("A", "BRIDGE", "C", "SECRET"))
    edges = (RelationshipRecord("ab", "A", ("OTHER_ID",), "BRIDGE", ("ID",)),
             RelationshipRecord("bc", "BRIDGE", ("OTHER_ID",), "C", ("ID",)))
    return SchemaCatalog(tables, edges)


def test_bridge_is_added_even_without_keyword_match():
    tables, edges = expand_relationships({"A", "C"}, graph())
    assert tables == {"A", "BRIDGE", "C"}
    assert {edge.name for edge in edges} == {"ab", "bc"}


def test_disconnected_and_over_budget_paths_fail():
    with pytest.raises(ValueError, match="No approved"):
        expand_relationships({"A", "SECRET"}, graph())
    with pytest.raises(ValueError, match="No approved"):
        expand_relationships({"A", "C"}, graph(), max_hops=1)


def test_hidden_join_keys_and_unapproved_edges_are_not_expanded():
    catalog = graph()
    hidden = replace(catalog.tables[1], columns=(ColumnRecord("OTHER_ID", "INTEGER"),))
    catalog = replace(catalog, tables=(catalog.tables[0], hidden) + catalog.tables[2:])
    with pytest.raises(ValueError):
        expand_relationships({"A", "C"}, catalog)
    catalog = graph()
    catalog = replace(catalog, relationships=(replace(catalog.relationships[0], approved=False), catalog.relationships[1]))
    with pytest.raises(ValueError):
        expand_relationships({"A", "C"}, catalog)


def test_ambiguous_join_paths_are_not_chosen_arbitrarily():
    catalog = graph()
    alternate = RelationshipRecord("alternate", "A", ("ID",), "BRIDGE", ("ID",))
    with pytest.raises(ValueError, match="Multiple"):
        expand_relationships({"A", "BRIDGE"}, replace(catalog, relationships=catalog.relationships + (alternate,)))
