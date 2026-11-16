# Claude handoff — 16 November 2026

This document describes the actual local project state and the latest chat/feedback implementation. It is context for the user's next prompt, not an instruction to merge, deploy, change credentials, provision databases, or run paid evaluations automatically.

## Latest update: ColdChain is the main app

The user subsequently asked: “remove the whole previous DB; I want the new ColdChain DB
to be the main DB our SQL agent uses.” This update supersedes older descriptions below
of an employee main app and a separate opt-in ColdChain page.

- `sqlapp.py` now registers only `pages/coldchain.py` using explicit `st.navigation`.
  Streamlit ignores automatic discovery of the other files in `pages/`, including
  employee admin/explorer direct routes. The main entry no longer calls `ensure_demo`,
  imports the employee pipeline, reads an employee SQLite snapshot or uses privileged
  `MYSQL_*` settings as a database fallback.
- `pages/coldchain.py` imports `coldchain_graph.build_graph` directly, applies the theme,
  shows ColdChain examples and uses ColdChain-specific authentication descriptions.
  Missing ColdChain configuration stops the app instead of offering the employee app.
- The UI still uses `review_all=True`, `max_attempts=1`, `explain_sql=True`: question,
  explanation and SQL are reviewed before every execution. The existing three-rewrite
  feedback flow remains. Historical graph/evaluation defaults remain unchanged.
- `app_auth.coldchain_role` is the shared role resolver. Demo HR/IT-admin permissions
  do not confer ColdChain sensitive access. All accounts default to viewer unless
  explicitly included in `COLDCHAIN_ADMIN_USERS`. SQL remains read-only for both roles.
- `query_errors.py` holds shared error text. ColdChain no longer imports the employee
  UI just for an error helper, and consequently avoids importing its database pipeline.
- Historical employee modules, benchmarks and page source files remain for regression
  coverage. Employee UI tests now use `tests/fixtures/employee_app.py`; that harness is
  never registered by the production app. The old local preview targets that harness
  and is explicitly historical, rather than pretending to preview the ColdChain screen.
- README, setup guidance, secrets-example comments and chat-review documentation were
  updated. No real `.env` or Streamlit secrets values were changed for this promotion.

### Source inventory and outside-repository backup

Read-only Aiven inventory identified:

| Database | Tables / status |
| --- | --- |
| `defaultdb` (old) | `EMPLOYEES` (10 rows), `RBAC_DEMO_EMPLOYEES` (6), `RBAC_DEMO_AUDIT` (1) |
| `coldchain_eval` (new main source) | Ten ColdChain tables; 60 customers verified |

The actual main-app engine and `execute_readonly` path were exercised on 16 November:
database `coldchain_eval`, identity `coldchain_ro`, certificate verification required,
hostname verification true, validated `SELECT COUNT(*) FROM customers` returned **60**.
This is a database integration check, not a model-generation or accuracy measurement.
No real LLM request or LangSmith smoke test was made for the promotion.

`scripts/retire_employee_database.py` was run **without `--retire`**. It made a logical
SQL backup and checksum manifest outside the repository at:

`C:\Users\HP\AppData\Local\Temp\sql-agent-employee-backup-w30gwrk_`

The backup contains data: keep it private and out of Git/chat. It contains table DDL and
all 17 rows across the three old tables. A restoration has not been performed. The helper
requires the exact audited identities, verified TLS, only the expected InnoDB tables,
and no stored objects or cross-schema foreign-key dependencies. Its explicit `--retire`
option makes a fresh backup before dropping only `defaultdb`. It never runs at app startup.
It does not remove the Aiven service, database users or any ColdChain table.

The saved SQL file's SHA-256 matches its manifest, and it has 17 INSERT statements,
matching the summed row counts. No backup contents or credentials were printed.

**User decision on 16 November: keep `defaultdb` until ColdChain is deployed.**
No database has been deleted, and the outside-repository backup remains available.
The saved `origin/main:sqlapp.py` still initializes employee data. Streamlit was last
verified to deploy `main`; deleting its old database now could stop that deployment.
Do not run retirement before deploying and verifying the ColdChain workflow and
confirming that the old employee deployment no longer depends on `defaultdb`.
No push/deploy was authorized or performed during this change; do not imply the
public site has switched. This decision does not authorize an automatic deployment.

`tests/test_coldchain_primary.py` adds fail-closed main-app coverage, ColdChain role
isolation and refusal of changed retirement targets/weaker TLS. The existing ColdChain
feedback AppTest now exercises the **main `sqlapp.py` entry point**. Targeted tests
passed **22/22** before the additional primary-app guard tests were added.
The final full offline suite passed **245 tests in 22.54 seconds** on 16 November,
including all seven new primary-app/retirement-guard checks. No new live model run
was made; historical model-quality numbers must not be attributed to this revision.

## 1. Repository and delivery state

- Local repository: `C:\Users\HP\Desktop\projects_live\AIML_types\SQL_AGENT(active)`.
- GitHub repository: `srikant31/Agentic_SQL_ChatBot`.
- Current branch verified on 16 November: `feature/langgraph-langsmith`.
- HEAD: `c1da33eded8fbeeb9a43f100b950aef6b89fd7b4`.
- The branch matches its recorded upstream; the new implementation is **uncommitted and unpushed**.
- PR #1 previously targeted `dev`. No PR, merge, deployment, or branch changes were made for this implementation. Its remote status was not rechecked for this handoff.
- Streamlit's dashboard was last verified in the user's signed-in Chrome on 13 November: deployment branch `main`, entry point `sqlapp.py`. This is a historical observation, not a fresh deployment-settings check.
- Consequently, do not assume the new local UI is available in the hosted app.
- GitHub alone does not contain these changes. Claude needs the current local working tree or a sanitized source archive/patch that includes the new untracked source files.

Existing context documents are `CLAUDE_HANDOFF.md`, `COLDCHAIN_SETUP.md`, `SCHEMA_INTELLIGENCE.md`, `LANGGRAPH_LANGSMITH.md`, `12-11-2026.md`, and `EVAL_RESULTS.md`. Preserve them and the user's existing `README.pdf`.

## 2. What the user most recently authorized

The user asked to implement a chat-style SQL assistant where:

1. Their original question remains visible as their own chat message.
2. The model explains what information the proposed query will retrieve.
3. SQL appears alongside that explanation.
4. A positive and negative feedback button are available.
5. Negative feedback opens a textbox with background/placeholder guidance asking for modifications.
6. The user can request up to three rewrites, after which a further rejection produces an apology and asks for a new question.

The user removed confidence-score improvements from the current development list. Existing confidence UI was preserved; no calibration or new confidence feature was implemented.

The implemented limit was stated to the user as **three rewrites AFTER the initial proposal**, allowing four proposal versions. Earlier planning discussed three total attempts, but that is not the behaviour implemented here. Do not silently reinterpret the limit.

The subsequent ColdChain promotion request and its implementation are described in the
latest-update section above. No upload, merge or deployment was authorized by that request.

## 3. User-visible behaviour now implemented

The primary ColdChain screen and historical employee test harness use the shared conversation renderer:

```text
User: original database question
Assistant: plain-English explanation of what will be retrieved
           proposed SQL
           existing validation details where available
           positive / negative feedback

Positive feedback -> record feedback only
Negative feedback -> show modification textbox; hide execution control

User: requested modifications
Assistant: rewritten proposal and explanation
           display the complete updated request
           fresh run/approval control
```

Button labels are:

- `👍 Looks good`
- `👎 Needs changes`
- `Rewrite query`
- Employee execution: `Run this query`
- ColdChain execution: `Approve & run`

The modification textbox is labelled `What should change?`, with placeholder:

> Please prompt again and tell the model what to modify.

The original question is kept in application-owned state. A model paraphrase does not overwrite the original chat bubble. Each modification becomes another user message; older explanations, SQL and results remain attached to their own responses.

An example interaction is:

1. Ask: `Count employees by department`.
2. Read the explanation and proposed SQL; nothing has run yet.
3. Click `👎 Needs changes`.
4. Enter: `Only Engineering`.
5. Click `Rewrite query`.
6. Review the displayed updated request and newly validated proposal.
7. Click the separate run button to execute it.

## 4. Feedback, budget and execution semantics

- Positive feedback never authorizes or executes SQL.
- Negative feedback hides the run control while the feedback box is open.
- Submitting a rewrite supersedes the old proposal and discards its pending execution approval.
- The user can change their feedback back to positive before submitting a rewrite; that restores review of the same proposal, but still requires an explicit run click.
- Each original question permits three submitted rewrites. The counter is reserved before provider calls, so failures and rerenders do not make the same slot reusable.
- Rejected or failed submissions still consume a rewrite slot. Blank/oversized feedback is rejected before consuming a slot.
- After the third rewritten response receives negative feedback, no fourth rewrite textbox/button is offered. The UI shows:

> Sorry, I couldn't meet your needs after three rewrites. Please start a new question with more specific requirements.

- A valid third rewritten proposal can still be run if the user accepts it.
- Starting a new question creates a new request ID and rewrite budget. The existing session question cap still applies; rewrites count toward it.
- UI generation uses one SQL-generation attempt per proposal, avoiding a nested automatic three-attempt loop inside every human rewrite.
- Results stay associated with the exact response that was run. Execution cannot be replayed through the same response's run control.
- Feedback records are application state, not model training or automatically uploaded LangSmith ratings.

The new chat UI replaces the earlier manual SQL-edit/reject form with natural-language feedback and a separate run action. The backend's SQL-edit validation capability remains in `SQLWorkflow`, but that advanced editor is not exposed by the new conversation component.

## 5. Files changed in this implementation

### Modified tracked files

| File | Change |
| --- | --- |
| `sqlapp.py` | Retains login, scope, permitted-data controls and permission demonstration; delegates its question/proposal section to `render_employee_chat(user)`. |
| `pages/coldchain.py` | Delegates chat interaction to `render_coldchain_chat(...)`; enables review for every interactive proposal and explanation generation. |
| `sql_generator.py` | Expands the explanation instruction and adds `rewrite_question(...)`. Existing confidence parsing is unchanged. |
| `coldchain_graph.py` | Adds opt-in interactive review/explanation settings, configurable attempt cap, explanation/review-context state, and a side-effect-free UI checkpoint node. |
| `tests/test_frontend.py` | Updates existing UI tests to submit questions through chat input and find unsupported-request text in chat. |
| `tests/test_coldchain_graph.py` | Adds tests for explaining/reviewing public queries and preventing nested automatic retry loops in interactive mode. |
| `README.md` | Adds a short description and link to `CHAT_REVIEW.md`. |

### New implementation files

| File | Purpose |
| --- | --- |
| `query_chat.py` | Shared conversation state, feedback/budget rules, stale-event checks, result binding and Streamlit chat renderer. |
| `employee_chat_ui.py` | Employee UI controller for classic and optional graph workflows; fresh authorization and separate execution approval. |
| `coldchain_chat_ui.py` | ColdChain UI controller, rejection/resume handling and checkpoint-backed review-context recovery. |
| `scripts/preview_query_chat.py` | Clearly labelled local preview using the actual employee screen with fictional SQLite and demonstration model responses. |
| `tests/test_query_chat.py` | Pure state tests for feedback, three-rewrite cap, stale submissions and per-response results. |
| `tests/test_query_rewriting.py` | Tests reformulation inputs, malformed outputs and safe provider errors. |
| `tests/test_chat_frontend.py` | Streamlit AppTests for both employee modes, rewrites, reauthorization and ColdChain restoration/approval. |
| `CHAT_REVIEW.md` | Behaviour, limits, preview command and verification notes. |
| `claude_handoff_16_11.md` | This handoff. |

These new files must accompany the tracked diff when transferring the implementation. A plain `git diff` does not include untracked files.

## 6. Shared conversation state and UI

`query_chat.py` provides:

- `new_chat(owner, scope)` and `start_request(chat, question)`.
- `add_response(...)`, `active_request(...)`, and `latest_response(...)`.
- `feedback(...)`, `begin_rewrite(...)`, and `executable(...)`.
- `record_result(...)` and `render_conversation(...)`.

Each conversation is bound to an owner and scope. Each request keeps:

```text
id
original_question
current_question
rewrites
modifications[]
messages[]
feedback_open
exhausted
```

Each assistant response records its version, explanation/message, optional proposal, vote,
execution status and optional results/error. Only the latest response of the active request
has actionable controls. Events from superseded versions are rejected. Up to 15 request
histories are retained in each conversation to keep session state bounded.

Question limit is 4,000 characters; each modification is limited to 2,000 characters.

## 7. How rewriting works

`sql_generator.rewrite_question(original_question, current_question, modifications)` makes
one provider call asking for a complete standalone analytical question in JSON:

```json
{"question": "Count Engineering employees by department."}
```

It receives the immutable original question, current complete question and all submitted
modifications. Its instruction preserves earlier requirements unless explicitly changed,
with later modifications overriding conflicting earlier ones.

It does not receive a SQL execution tool or change permissions. It validates the returned
question's type/length and returns safe user-facing errors on provider or parsing failure.

The complete rewritten question then goes through the ordinary generation pipeline. For
employees, this means fresh intent analysis, role-aware context, SQL generation, schema and
semantic validation, then fresh checks again at execution. Thus feedback cannot grant an
employee salary access simply because a reformulation model mentions salary.

The reformulation is model-based. The prompt and payload encourage cumulative preservation,
but this is not a proof that every natural-language requirement is retained perfectly. The
updated request is displayed so the user can inspect it.

One rewrite adds a reformulation model call before normal generation. ColdChain also retains
its classifier call and post-execution summary. The three-rewrite limit is not a claim that
the entire interaction makes only three API calls. SDK transport retries are separate.

## 8. Employee integration

`employee_chat_ui.py` supports both existing modes:

- Classic: `prepare_proposal(...)` followed by `execute_proposal(...)` only on run.
- Graph: creates `SQLWorkflow(user, max_attempts=1)` for each proposal, then resumes only
  after a separate approval click.

It keeps `pending_query` consistent with the active request/revision, checks owner and request
binding before execution, rejects old pending graph reviews before a rewrite/new question,
and clears execution state after completion/failure. Session state resets when owner/scope
changes; normal logout already clears application session state.

The generator explanation instruction now asks for sources, filters, grouping and output
columns, and prohibits invented results or row counts before execution. It remains a model
explanation; independent explanation-faithfulness evaluation is not implemented.

Existing employee confidence display/parsing was preserved without new scoring or calibration.

## 9. ColdChain integration and default compatibility

The graph factory now supports:

```python
build_graph(
    checkpointer,
    # existing dependencies/options ...
    review_all=False,
    max_attempts=3,
    explain_sql=False,
)
```

The interactive page opts into:

```python
build_graph(
    resource.saver,
    engine=engine,
    review_all=True,
    max_attempts=1,
    explain_sql=True,
)
```

Effects:

- Every interactive query pauses for review, including public-table queries that previously
  could run automatically.
- Interactive generation requests both SQL and a nonempty explanation, capped at 4,000 characters.
- The normal shared SQL guard and fresh execution checks remain in place.
- `explanation` and `review_context` are additional graph-state fields.
- A `chat_checkpoint` node has no model/database side effects and ends the graph. The UI uses
  it to persist reserved rewrite counts and closed chat state without invoking SQL.
- Reserved budget is saved before a provider call. Reconstructing a review from a checkpoint
  hydrates the current proposal without spending another model call.
- Pending request snapshots clear old answer/SQL/result fields to avoid showing an earlier
  answer as the result of an interrupted new question.

Factory defaults preserve the earlier non-UI policy: sensitive-table-only approval, up to
three generation attempts, SQL-only generation prompt. The existing evaluation adapter does
not opt into the new interactive settings. No golden fixture or adapter file was edited.

Persistence limits remain important: without PG_URL, the underlying saver is in memory and
server restart loses it. Tests verify reconstruction with a shared in-memory saver, not a
real PostgreSQL restart. Employee chat remains Streamlit-session-owned. This is not a global
cross-session rate limiter.

## 10. Verification actually performed

Fresh verification while preparing this handoff on 16 November:

```powershell
.\venv\Scripts\python.exe -m pytest -q
```

Observed result:

```text
238 passed in 24.37s
```

The targeted implementation run had initially passed 31/32 tests. The remaining old test
expected an info banner; it was updated to check the new assistant chat display. The complete
suite now passes.

Covered behaviours include:

- Question/explanation rendering and no execution on generation or thumbs feedback.
- Employee classic and optional graph execution approval.
- Three rewrites after the original; no fourth rewrite after a further negative vote.
- Original-question retention and cumulative modification payloads.
- Stale rewrite-event rejection and stable counters across rerenders.
- Fresh authorization when feedback requests prohibited salary data.
- Provider/parsing errors without raw private error detail.
- ColdChain public-query review before execution.
- ColdChain restored rewrite budget without extra model calls.
- Existing default ColdChain graph/evaluation behaviour.

Tests use fictional local fixtures and mocked model/network dependencies. No live Groq,
LangSmith upload or Aiven execution was needed to validate this UI change. A successful
fresh live-provider run is not claimed.

## 11. Local preview and demonstration limitation

The following server was started during implementation:

```powershell
.\venv\Scripts\python.exe -m streamlit run scripts/preview_query_chat.py --server.address 127.0.0.1 --server.port 8502 --server.headless true --browser.gatherUsageStats false
```

Preview address: `http://127.0.0.1:8502`.

Verify whether it is still running; restart it if needed. The preview uses a disposable
fictional SQLite fixture and patched demonstration responses, with tracing disabled. It
does not call Aiven or an LLM. It demonstrates the actual employee UI and review controls,
not real-model quality. The normal application still uses its configured provider/database.

The attempt to open the preview in the user's regular Chrome was stopped by Computer Use
because it could not reliably determine the current Windows browser URL to enforce policy.
The page was therefore not visually demonstrated by automation, and no screenshot proof
was captured. Do not claim that browser verification succeeded. Streamlit AppTests did verify
the interaction programmatically; the user was given the local preview link to open manually.

## 12. Important earlier measurement context

These are historical 13 November measurements, retained in `EVAL_RESULTS.md` and artifacts.
They do not establish fresh quality for the changed employee explanation prompt or UI.

- A separate `coldchain_eval` database and SELECT-only `coldchain_ro` identity already exist
  on Aiven. Do not rerun provisioning or replace the employee database.
- ColdChain TLS URLs were repaired in .env after an outside-repository backup. Verified
  query flags were `ssl_ca=ca.pem&ssl_check_hostname=true`; customer count was 60 with full
  certificate and hostname verification. No .env change occurred during the new UI work.
- The authenticated Groq model list lacked `llama-3.3-70b-versatile`. The listed replacement
  `openai/gpt-oss-120b` passed a tiny preflight and was used for the live measurement via
  process-only override. At that time, .env retained the old model ID. Recheck availability
  and effective configuration before future live use; this UI task did not change models.
- Gold oracle: 64/64 passed. Native split 53/53 answerable and 11/11 behaviour; requested
  split 52/52 SQL and 12/12 behaviour.
- Wrong oracle first run: 26/53 answerable; D03 lost its connection. Isolated D03 rerun
  passed 1/1; it has no planted wrong SQL and falls back to its gold query.
- Live replacement-model first run: raw 23/53 answerable and 9/11 behaviour, or 23/52 SQL
  and 9/12 behaviour. Infrastructure affected 35/64 cases: 32 provider errors and 3 lost
  MySQL connections. All nine behaviour passes were provider-error refusals, not clean
  evidence of model safety recognition.
- Among 29 first-run SQL cases without observed infrastructure failure, 23 passed. This
  ordered/selected subset is not a representative full-benchmark accuracy estimate.
- The infrastructure-only rerun selected 35 cases, used sleep 10, and still had 34 provider
  errors due to daily token quota. K02 was the only clean refusal. Keep both runs separate.
- The old employee mode-A run is preserved as `live-mode-A-invalid-404.json`: raw 27/56,
  with all 29 query requests failing HTTP 404. It is invalid as model-accuracy evidence.
- The user explicitly stopped further live calls after the rerun. Fresh employee D/A/C
  results and a paired live A-versus-D comparison are unavailable.
- Offline A/B/C/D checks were recomputed at 56/56 each. Required-rule recall over 16
  applicable cases: A 0%, B/C/D 100%. Average estimated context tokens per query:
  A 149.86, B 2345.79, C 1263.17, D 1360.55. These are offline context metrics, not LLM accuracy.
- LangSmith's single historical smoke upload failed; its exact error was not retained.
  Older history included 403. Do not assert that the latest smoke failure was definitely
  403. Tracing stayed disabled in subsequent measurements.
- Historical daily quota and provider availability have not been rechecked for this handoff.

All earlier evaluation CSVs, JSONs, temporary fixture copies and the three measurement
scripts were already untracked before this UI implementation. They were not new chat UI
work and should not be mistaken for files that must all be committed with the feature.

## 13. Discussed roadmap that remains unimplemented

The following were planned, not delivered by the latest UI task:

1. LangSmith authentication/destination repair, verified uploads and useful sanitized spans.
2. Ragas integration and automated evaluation/reporting.
3. Query complexity routing and query decomposition into structured plans/CTEs.
4. New confidence calculation or calibration; removed from current scope by the user.
5. Independent SQL-explanation faithfulness checking.

The decomposition discussion recommended choosing a route from query structure before SQL
generation, rather than blindly waiting for a third call. That remains design context only;
no decomposition router, planner, or extra agents were added.

## 14. Constraints and practical continuation

- Treat user keys, passwords, full database URLs and certificate contents as private. They
  must not appear in chat, logs, patches, handoffs or commits.
- Keep .env, local Streamlit secrets and certificate files out of source transfers. The
  historical secret backup is outside the repository and must never be bundled.
- Preserve the employee and ColdChain execution-domain separation and backend permission checks.
- No new model setting, LangSmith configuration, dependency installation or hosted deployment
  was performed for this feature.
- Do not claim that thumbs feedback trains a model or that explanation/confidence proves correctness.
- Do not run paid/live evaluations or provision/alter Aiven resources merely because this
  handoff mentions them; obtain the user's next concrete task.
- Inspect current status and the listed code before continuing. Keep the existing handoff,
  README.pdf and measurement artifacts intact. Do not stage every untracked file blindly.

To review the implementation locally, read `CHAT_REVIEW.md`, then `query_chat.py`,
`employee_chat_ui.py`, `coldchain_chat_ui.py`, the generator/graph diffs and the new tests.
Use the local preview for UI demonstration and the passing suite for behavioural evidence.
Ask for the user's next prompt rather than assuming the next roadmap feature is authorized.
