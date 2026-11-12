from copy import deepcopy

import pytest

from scripts.evaluate import check_leakage, compare_rows, evaluate, load_cases
from sql_examples import load_examples


def test_evaluation_has_representative_cases_and_family_isolation():
    cases = load_cases()
    assert len(cases) >= 50
    assert len([case for case in cases if case["split"] == "heldout"]) >= 50
    assert len({case["category"] for case in cases}) == 8
    check_leakage(cases, load_examples())
    leaked = {**cases[0], "template_family": load_examples()[0]["template_family"]}
    with pytest.raises(ValueError, match="leakage"):
        check_leakage([leaked], load_examples())


def test_all_offline_contracts_and_independent_expected_rows_match():
    report = evaluate(mode="D", split="all")
    assert report["passed"] == report["cases"] == 56
    assert report["actual_input_tokens"] is None
    assert report["estimated_api_cost"] is None
    assert "not_llm_accuracy" in report["measurement"]


def test_row_comparison_preserves_duplicates_and_ranking():
    assert compare_rows([(1, .1 + .2)], [[1, .3]], ordered=True)
    assert compare_rows([(2,), (1,)], [[1], [2]], ordered=False)
    assert not compare_rows([(2,), (1,)], [[1], [2]], ordered=True)
    assert not compare_rows([(1,), (1,)], [[1]], ordered=False)
