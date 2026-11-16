"""Ragas partial-credit plumbing. Alignment is always tested; scoring only when Ragas is installed."""
import asyncio

import pytest
from sqlalchemy import create_engine, text

import ragas_eval

GOLD = [("North", 10), ("South", 5)]


def test_alignment_ignores_column_names_order_and_extra_columns():
    predicted = [(5, "South", "x"), (10, "North", "y")]     # columns swapped, rows reordered, extra column
    gold_csv, pred_csv = ragas_eval.align(GOLD, predicted)
    assert gold_csv == pred_csv


def test_alignment_keeps_order_when_the_case_is_ordered():
    gold_csv, pred_csv = ragas_eval.align(GOLD, list(reversed(GOLD)), ordered=True)
    assert gold_csv != pred_csv


def test_alignment_falls_back_to_position_when_values_differ():
    gold_csv, pred_csv = ragas_eval.align(GOLD, [("North", 10), ("South", 7)])
    assert pred_csv.splitlines()[0] == "c0,c1" and "7.00" in pred_csv


def test_partial_credit_scores():
    pytest.importorskip("ragas")
    pytest.importorskip("datacompy")
    exact = asyncio.run(ragas_eval.score_pair(*ragas_eval.align(GOLD, [(5, "South"), (10, "North")])))
    assert exact == {"rows_f1": 1.0, "columns_recall": 1.0}
    half = asyncio.run(ragas_eval.score_pair(*ragas_eval.align(GOLD, [("North", 10), ("South", 7)])))
    assert half["rows_f1"] == 0.5 and half["columns_recall"] == 0.5   # region right, one value wrong


def test_evaluate_runs_saved_sql_and_reports_near_misses(tmp_path):
    pytest.importorskip("ragas")
    pytest.importorskip("datacompy")
    engine = create_engine(f"sqlite:///{tmp_path}/eval.db")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE sales (region TEXT, amount INT, status TEXT)"))
        connection.execute(text("INSERT INTO sales VALUES ('North', 10, 'ok'), ('South', 5, 'ok'), ('South', 2, 'cancelled')"))
    cases = [{"id": "A1", "category": "aggregation", "kind": "sql",
              "gold_sql": "SELECT region, SUM(amount) FROM sales WHERE status = 'ok' GROUP BY region"},
             {"id": "K1", "category": "refusal", "kind": "refuse"}]
    saved = [{"id": "A1", "pass": "False", "predicted_sql": "SELECT region, SUM(amount) AS total FROM sales GROUP BY region"},
             {"id": "K1", "pass": "True", "predicted_sql": ""}]
    run = lambda eng, sql: [tuple(r) for r in eng.connect().execute(text(sql)).fetchall()]
    report = ragas_eval.evaluate(saved, cases, engine, lambda sql, role: sql, run)
    assert [r["id"] for r in report] == ["A1"]                 # refusals stay strict-only
    assert report[0]["rows_f1"] == 0.5                         # counted cancelled sales: North right, South wrong
    summary = ragas_eval.summarize(report)
    assert summary["overall"]["near_misses"] == 1
    ragas_eval.write_reports(report, summary, str(tmp_path / "report"))
    assert "Near misses" in (tmp_path / "report.md").read_text()
