# Feedback tracking, LangSmith linking and Ragas scoring

This is Step 1 of the build plan: measuring before changing behaviour. It adds no new model calls.

## 1. Event store (`feedback_store.py`)

One append-only table, `query_events`. Rows are added and never edited, so the history cannot be rewritten.

| Event | When it is written |
|---|---|
| `proposal` | A proposal (or a clarify/refuse/error answer) was produced |
| `vote` | 👍 or 👎 was clicked |
| `rewrite` | The user submitted "What should change?" |
| `run` | "Approve & run" finished, successfully or not |
| `limit_reached` | 👎 on the last allowed version |

Each row carries `request_id` (one original question), `version` (0 = first proposal), `model`, `route` (`direct` today, `decomposed` later), `model_calls` for that step, `latency_ms`, `status`, `rows_returned` and `langsmith_run_id`. A JSON `detail` column is reserved for later fields such as the rules applied and their checks, so adding them needs no migration.

**Storage:** `FEEDBACK_DB_URL`, else `PG_URL`, else `data/feedback_events.sqlite`. The ColdChain MySQL account is read-only and is never written to. On Streamlit Cloud the disk is temporary, so set a Postgres URL there.

**Privacy:** usernames are stored as a short hash. Rewrite hints are stored as length plus hash. Set `FEEDBACK_STORE_HINTS=true` to keep their text (truncated to 500 characters). Do this only while the data is fictional.

**Never breaks the chat:** a storage failure is logged by `diagnostics.py` and the chat carries on. After one failed connection the store stops retrying for that process.

**Headline numbers:** `feedback_store.get_store().summary()`, shown to ColdChain admins in the "System performance" expander:
questions, accepted on first proposal, resolved with a successful run, average rewrites, average model calls, rewrite-limit hits, run failure rate, and vote counts.
Acceptance measures user behaviour, not correctness. Correctness comes from the golden set.

## 2. Model-call counting (`coldchain_graph.py`)

The graph state has a `model_calls` field. `classify`, `generate` and `summarize` each add the number of model requests they made, counting before each request, because a failed request still costs quota. The chat adds 1 for the question-rewrite request, which runs outside the graph. The ColdChain AppTest confirms the counts (2, 3, 1) match the calls actually made.

## 3. LangSmith (`observability.py`)

- `LANGSMITH_WORKSPACE_ID` is now copied from Streamlit secrets.
- `@redacted_trace` keeps the shape of inputs and outputs (character counts, list lengths, keys, status) without their text.
- Every graph call gets its own `run_id`, `run_name` (`coldchain_proposal` / `coldchain_run`) and metadata (`request_id`, `version`, `model`, `role`). The same run ID is saved in the event row.
- 👍/👎 is sent to LangSmith as feedback key `user_vote` (1 or 0) on that run. This only happens when tracing is on, and a failure only loses the feedback.
- `LANGSMITH_HIDE_INPUTS`/`OUTPUTS` still default to `true`, which hides prompts in model traces. Set them to `false` in `.env` to see prompts for fictional data.

Not yet verified: an actual upload to LangSmith. The offline tests prove the IDs and calls are made, not that the service accepted them.

## 4. Ragas partial credit (`ragas_eval.py`)

Optional install: `pip install -r requirements-eval.txt` (Ragas 0.4.4, datacompy 0.19.5; datacompy 1.x is incompatible).

```
python golden_eval/run_eval.py --predictor golden_eval.adapter:predict --out eval_results.csv
python ragas_eval.py --results eval_results.csv --db-url <read-only ColdChain URL> --out ragas_report
```

The first command is the existing strict grader, which spends model calls. The second re-runs the saved SQL and the gold SQL on the read-only database and scores them with Ragas `DataCompyScore`. It spends no model calls. Before scoring, it:

- renames predicted columns to match gold columns by value, falling back to position, and drops extra columns;
- sorts rows unless the case is ordered;
- normalises values exactly as the strict grader does.

The output is `ragas_report.json` and `ragas_report.md`, with strict pass rate, rows F1, column recall and near misses (strict fail but rows F1 ≥ 0.5) per category. Refuse, clarify and unsafe cases have no gold rows, so they stay strict-only. No LLM judge such as `SQLSemanticEquivalence` is used yet.

## Tests

`tests/test_feedback_tracking.py` and `tests/test_ragas_eval.py`. Ragas scoring tests are skipped automatically when Ragas is not installed.
