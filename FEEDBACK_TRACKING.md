# Feedback tracking, LangSmith linking and Ragas scoring

This is Step 1 of the build plan: measuring before changing behaviour. It adds no new model calls.

## 1. Event store and prompt log (`feedback_store.py`, `prompt_log.py`)

Two tables in the same database. Rows are only ever added, never edited.

**`query_events`**: one row per step, readable:

| Event | When it is written | Readable text stored |
|---|---|---|
| `proposal` | A proposal (or a clarify/refuse/error answer) was produced | question sent, SQL, explanation, or the message shown |
| `vote` | 👍 or 👎 was clicked | the vote |
| `rewrite` | The user submitted "What should change?" | the user's hint |
| `run` | "Approve & run" finished | the SQL run and the answer or error shown |
| `limit_reached` | 👎 on the last allowed version | |

Each row also has `username`, `display_name` (fictional: Asha Verma, Rohan Mehta, Neha Iyer), `role`, `request_id` (one original question), `version` (0 = first proposal), `model`, `route` (`direct` now, `decomposed` later), `model_calls`, `latency_ms`, `status`, `rows_returned` and `langsmith_run_id`. A JSON `detail` column is reserved for Step 2 fields (rules applied and their checks).

**`llm_calls`**: one row per model request, with:
- `node`: classify, generate, summarize or rewrite_question;
- the exact `system_prompt`;
- the `user_payload`: the question, conversation history, schema context and business glossary, which is everything your context-building added;
- the raw `response_text`, saved even when it failed to parse;
- `error`, `latency_ms` and token counts;
- the LangSmith run ID.

Model code calls `prompt_log.capture(...)`. The chat wraps each graph call in `prompt_log.bind(...)` (a Python context variable). That way the graph knows nothing about users, and evaluation runs outside the chat log nothing.

The full table definitions are in `docs/feedback_schema_postgres.sql`.

**Storage:** `FEEDBACK_DB_URL`, else `PG_URL`, else `data/feedback_events.sqlite`. The ColdChain MySQL account is read-only and is never written to. On Streamlit Cloud the disk is temporary, so set a Postgres URL there.

**Text storage:** on by default, because the data is fictional. `FEEDBACK_STORE_TEXT=false` keeps only numbers, for real or private data. Prompts can include result rows (the summarize step), so this switch matters.

**Never breaks the chat:** a storage failure is logged by `diagnostics.py` and the chat carries on. After one failed connection the store stops retrying for that process. A database created with the earlier hashed-session schema is refused with a clear message: delete `data/feedback_events.sqlite` and restart.

**Reading it (admins only):**
- "System performance": headline numbers from `summary()`, unchanged.
- "Show conversation log": every question with user, versions and outcome. Opening one shows each step and each model call, with its system prompt, payload and raw reply. A JSON download is provided.

Acceptance measures user behaviour, not correctness. Correctness comes from the golden set.

## 2. Model-call counting (`coldchain_graph.py`)

The graph state has a `model_calls` field. `classify`, `generate` and `summarize` each add the number of model requests they made, counting before each request, because a failed request still costs quota. The chat adds 1 for the question-rewrite request, which runs outside the graph. The ColdChain AppTest confirms the counts (2, 3, 1) match the calls actually made.

## 3. LangSmith (`observability.py`)

- `LANGSMITH_WORKSPACE_ID`, `LANGSMITH_AGENT_ID` and `LANGSMITH_AGENT_ENVIRONMENT` are copied from Streamlit secrets. The endpoint defaults to APAC (`https://apac.api.smith.langchain.com`), where this project's LangSmith organisation lives.
- Trace statuses are kept only if they are known application values; anything else could be model text and is dropped.
- `@redacted_trace` keeps the shape of inputs and outputs (character counts, list lengths, keys, status) without their text.
- Every graph call gets its own `run_id`. Roots keep the name `coldchain_turn` (from `checkpointing.thread_config`), with metadata `step` (`proposal` or `run`), `request_id`, `version`, `model`, `role`, `agent_id` and `agent_environment`. The same run ID is saved in the event row.
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

## Ragas with an LLM judge (later, optional)

Use a different model from the one that generates SQL, so the judge does not share the generator's blind spots. It also uses separate quota, because Groq limits are per model. Free options as of November 2026 (check your own console, limits change):

| Provider | Free limit (approx.) | Notes |
|---|---|---|
| Groq, e.g. `qwen/qwen3.8-27b` | 30 requests/min, 1,000/day, 200K tokens/day per model | Same key as the app; separate per-model quota |
| Cerebras (`gpt-oss-120b`, `qwen-3.8-27b`) | 5 requests/min, 1M tokens/day | OpenAI-compatible; slow per minute but large daily budget |
| OpenRouter `:free` models | 20 requests/min, 50/day (1,000/day after a one-time $10 top-up) | Free models rotate and can be rate-limited at peak times |

A 52-case golden run with `SQLSemanticEquivalence` needs about 52 judge calls, which fits any of these.

## Tests

`tests/test_feedback_tracking.py` and `tests/test_ragas_eval.py`. Ragas scoring tests are skipped automatically when Ragas is not installed.
