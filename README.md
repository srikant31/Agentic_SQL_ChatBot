# SQL Agent with LangChain

A hands-on project exploring how to connect Large Language Models to relational
databases — starting from raw `sqlite3`, moving through `SQLAlchemy` as a
universal database connector, and finally building a working **SQL Agent**
that can answer natural language questions by generating, validating, and
explaining SQL queries. The live app lets anyone ask a question in plain
English — like "Who is Bob Brown's manager?" — and get a real, accurate
answer back, with no SQL knowledge required.

## Overview

This project walks through the full stack needed to build a database-aware AI tool:

1. **SQLite3 fundamentals** — connecting, creating tables, inserting data, and querying with Python's built-in `sqlite3` module.
2. **SQLAlchemy** — a universal database toolkit that works across SQLite, MySQL, PostgreSQL, and more, using the same consistent API.
3. **MySQL integration** — connecting to a production-style, cloud-hosted MySQL database instead of a local file-based database.
4. **LangChain SQL Agent (toolkit-based)** — using LangChain's built-in `SQLDatabaseToolkit` to auto-generate the tools an agent needs to interact with a database.
5. **Manual Toolkit creation** — building the same set of database tools from scratch using LangChain's `@tool` decorator, to understand what the toolkit does under the hood.
6. **A safer production design** — the live app moved away from the fully autonomous agent (below) to a single-shot generate-then-approve flow with a code-enforced safety guardrail, trading some AI autonomy for a much stronger safety guarantee.

## How the Live App Works

1. You type a question.
2. Gemini is given the database schema and asked to write exactly one SQL
   query, plus a plain-English explanation of what it does. This is a single
   request — the model does not execute anything itself.
3. Before you ever see it, the proposed query passes through a safety check
   (`sqlglot`) that parses it into a real syntax tree and rejects anything
   that isn't a genuine read-only query — a single `SELECT`, or a
   `UNION`/`INTERSECT`/`EXCEPT` combining `SELECT`s. No destructive statement
   (`DELETE`, `DROP`, `UPDATE`, etc.) can pass this check, regardless of what
   the model generated.
4. The validated query and explanation are shown to you. Nothing has run
   against the database yet.
5. Only when you click "Run this query" does it actually execute, and the
   results are displayed as a table.

This is a deliberate design choice: the AI proposes, a human approves. It
trades away autonomy (no self-correcting retry loop) for a guardrail that's
enforced in code, not requested via a prompt the AI could be talked out of
following.

```
User asks a question (natural language)
        ↓
Gemini writes ONE proposed SQL query + explanation
        ↓
sqlglot validates it's read-only (rejects if not)
        ↓
Query and explanation shown to the user — nothing executed yet
        ↓
User clicks "Run this query"
        ↓
Query executes, results displayed
```

The notebook (`sql_agent.ipynb`) explores a different, fully autonomous
design — a LangChain agent that inspects the schema, writes a query,
executes it, and self-corrects on error, all without human approval. That
version is preserved there as a learning exercise; it is not what the live
app runs.

## Why SQLite First, Then MySQL?

SQLite requires no server setup — it's a single file, making it ideal for
quickly prototyping and testing query logic in the notebook. Once verified,
the same code can point to a production database by simply swapping the
connection string, since both `SQLAlchemy` and LangChain's `SQLDatabase`
utility are database-agnostic. The deployed app connects to a hosted MySQL
instance (Aiven), not SQLite.

## Project Structure

```
.
├── sqlapp.py               # Entry point — page layout and orchestration only.
│                           # Wires together the other modules; no business
│                           # logic lives here.
├── config.py               # All settings in one place: database credentials
│                           # (read from .env), the connection string, sample
│                           # questions, and the per-session usage cap.
├── theme.py                # Custom CSS for the app's visual theme, isolated
│                           # so styling changes never touch application logic.
├── database.py             # All database access. get_db() connects for
│                           # schema introspection; get_engine()/run_query()
│                           # execute already-validated SQL directly — kept
│                           # separate from anything the AI touches.
├── sql_generator.py        # Single-shot AI call: takes a question + schema,
│                           # returns one proposed SQL query and a plain-
│                           # English explanation. Does not execute anything.
├── safety.py               # The guardrail. Parses generated SQL with sqlglot
│                           # into a real syntax tree and rejects anything
│                           # that isn't a genuine read-only query — enforced
│                           # in code, not requested via prompt.
├── utils.py                 # Small shared helpers, e.g. extract_text(),
│                           # which normalizes Gemini's response format.
├── tests/                    # pytest suite covering safety, utils,
│                           # sql_generator, and database.
├── sql_agent.ipynb          # Exploratory notebook — the original build
│                           # walkthrough, including the fully autonomous
│                           # agent design and a hand-built toolkit
│                           # implementation (neither used by the live app).
├── html_sql_agen1.py        # Standalone HTML diagram generator (SQLite3
│                           # workflow) — documentation aid, not used by the app.
├── sql_alchemy_html_flow.py # Standalone HTML diagram generator (SQLAlchemy
│                           # workflow) — documentation aid, not used by the app.
├── html_langchain_agent_flow.py # Standalone HTML diagram generator (agent
│                           # workflow) — documentation aid, not used by the app.
├── requirements.txt         # Exact pinned dependencies for the live app.
├── .env.example              # Template listing every required environment
│                           # variable, with placeholder values — safe to
│                           # commit, unlike the real .env.
├── .env                       # Real credentials (MySQL, Gemini API key).
│                           # Never committed — see .gitignore.
├── ca.pem                     # Aiven MySQL SSL certificate, required for the
│                           # connection string's ?ssl_ca= parameter. Never
│                           # committed.
├── .streamlit/config.toml    # Base Streamlit theme colors.
└── .gitignore
```

## Sample Dataset

The `EMPLOYEES` table represents an organizational hierarchy:

| Column | Type | Description |
|---|---|---|
| `EMPLOYEE_ID` | INTEGER | Unique employee identifier |
| `NAME` | TEXT | Employee name |
| `MANAGER_ID` | INTEGER | ID of the employee's manager (nullable) |
| `MANAGER_NAME` | TEXT | Name of the employee's manager (nullable) |

This same schema is explored in SQLite and MySQL in the notebook, and lives in
a hosted MySQL (Aiven) instance for the live app.

## Key Concepts Covered

- **Connect → Cursor → Create → Insert → Commit → Query → Close**: the core SQLite3 workflow, including why `commit()` is required before `close()` to persist changes.
- **SQLAlchemy as a universal connector**: one consistent API (`create_engine`, `text()`, `.connect()`) that works across different database engines by simply changing the connection string.
- **Safe credential handling**: using `urllib.parse.quote_plus()` to URL-encode passwords containing special characters (e.g., `@`) so they don't break the connection string.
- **LangChain's `SQLDatabase` utility**: wrapping a SQLAlchemy engine so an LLM can inspect table names and schemas before writing queries.
- **`SQLDatabaseToolkit` and `create_agent`** (explored in the notebook): LangChain's built-in toolkit and agent-construction function, capable of multi-step autonomous reasoning (check schema → write query → execute → self-correct on error → explain result).
- **Manual tool creation**: rebuilding the toolkit's core functionality by hand using the `@tool` decorator and raw SQLAlchemy calls, to understand exactly what the toolkit abstracts away.
- **Provider-agnostic model swapping**: LangChain's standardized model interface meant switching the live app from OpenAI to Google Gemini was a two-line code change, not a rewrite.
- **Secure hosted database connections**: connecting to Aiven's managed MySQL over SSL using a downloaded CA certificate, rather than an unauthenticated local connection.
- **Enforced query safety**: using `sqlglot` to parse generated SQL into a real syntax tree, rejecting anything that isn't a genuine read-only query — a guardrail that can't be bypassed by clever prompting, since it's checked in code after generation, not requested of the model.
- **Human-in-the-loop execution**: separating "the AI proposes a query" from "the query runs" into two distinct, user-confirmed steps.

## Setup

**1. Install dependencies**
```bash
pip install -r requirements.txt
```

**2. Set up your environment variables**

Copy `.env.example` to `.env` and fill in your real values:
```
MYSQL_USER=your_mysql_user
MYSQL_PASSWORD=your_mysql_password
MYSQL_HOST=your_mysql_host
MYSQL_PORT=your_mysql_port
MYSQL_DATABASE=your_database_name
GOOGLE_API_KEY=your_gemini_api_key
```

**3. Get a free Gemini API key**

Visit aistudio.google.com, sign in, and generate an API key — no credit card required.

**4. Set up your MySQL database**

This project uses Aiven's free MySQL tier. Aiven requires SSL — download your
service's CA certificate, save it as `ca.pem` in the project root, and create
the `EMPLOYEES` table using the schema above.

**5. Run the app**
```bash
streamlit run sqlapp.py
```

**Or, explore the build process:** open `sql_agent.ipynb` and run the cells
sequentially — it's structured as a progressive walkthrough, from raw
SQLite3 to a fully autonomous LangChain SQL Agent, including the manual
toolkit build.

## Testing

```bash
pip install pytest pytest-mock
pytest tests/ -v
```

The suite covers the safety guardrail (valid queries, destructive queries,
SQL-injection-style stacked statements, and edge cases like empty input,
parenthesized queries, and `UNION`s), the Gemini response-parsing helper, the
SQL generation function (with the AI call mocked out — no real API calls in
tests), and query execution against a disposable in-memory SQLite database.

Writing these tests surfaced a real bug: the original guardrail checked
`isinstance(statement, Select)`, which rejected a harmless parenthesized
query like `(SELECT * FROM EMPLOYEES)` because it parses to a different node
type (`Subquery`). Fixed by checking against sqlglot's `Query` base class
instead, which correctly covers `Select`, `Subquery`, and set operations
(`UNION`/`INTERSECT`/`EXCEPT`) — confirmed by directly testing that no
destructive statement type can be smuggled into any of those shapes before
making the change.

## Example Query

```python
question = (
    "Tell me the manager's name for each employee along with their employee ID "
    "and manager ID. If no manager exists, return 'CEO' as the manager name "
    "and 0 as the manager ID."
)

answer = sql_agent.invoke({'messages': [{'role': 'user', 'content': question}]})
print(answer['messages'][-1].content)
```

This example reflects the notebook's fully autonomous agent, which writes an
appropriate `LEFT JOIN` query, executes it, and returns a natural-language,
tabular-formatted answer without human approval. The live app instead shows
you the proposed query first and waits for you to confirm before running it.

## Tech Stack

- **Python 3.12**
- **Streamlit** — the live web UI
- **LangChain Google GenAI** (`ChatGoogleGenerativeAI`) — connects to Gemini
- **LangChain Community** (`SQLDatabase`) — schema introspection
- **sqlglot** — parses generated SQL into a real syntax tree to enforce the read-only guardrail
- **SQLAlchemy**
- **SQLite3** (built-in, notebook only)
- **PyMySQL** (MySQL driver)
- **python-dotenv**
- **pytest** / **pytest-mock** — test suite
- **Aiven for MySQL** — hosted database (SSL-only connection)
- *(notebook only)* **LangChain** (`langchain.agents.create_agent`) — the fully autonomous agent design, not used by the live app

## Notes

- Passwords containing special characters (like `@`) must be URL-encoded with `quote_plus()` before being placed in a connection string, otherwise the connection parser misreads the credentials.
- Aiven requires SSL for all connections — the connection string includes `?ssl_ca=ca.pem`, pointing at a locally downloaded (and gitignored) certificate.
- The `SQLDatabaseToolkit` explored in the notebook internally relies on SQLAlchemy — using the toolkit doesn't remove the need for SQLAlchemy, it simply automates the tool-writing step.

## Development Notes

This project went through a real cleanup and hardening pass after the initial
draft, working through each issue methodically rather than shipping the first
working version:

- **Dependency cleanup**: the original `requirements.txt` was a 415-package
  freeze of an unrelated ML environment (torch, transformers, spacy, etc.),
  saved in the wrong encoding (UTF-16 instead of UTF-8) and containing
  Windows-only packages that would fail to install on any Linux deploy
  target. Rebuilt from a clean, project-scoped virtual environment.
- **Fixed a real config bug**: the app told users to set `MYSQL_DATABASE` in
  their `.env`, but the code silently ignored it and used a hardcoded value.
  Fixed to actually read the environment variable.
- **Flattened the repo structure**: the project originally lived inside a
  redundant nested folder from an extracted zip. Restructured to a clean
  root layout.
- **Switched from OpenAI to Google Gemini**: to keep this project genuinely
  free to run and demo (no risk of an unexpected bill on a public-facing
  app), swapped `ChatOpenAI` for `ChatGoogleGenerativeAI`.
- **Added session-based usage limits**: since this runs as a public demo, a
  per-session question cap prevents any single visitor from exhausting the
  shared API quota.
- **Wired up a real hosted database**: connected to Aiven's managed MySQL
  with proper SSL certificate verification, replacing local-only testing.
- **Custom visual design**: restyled the default Streamlit theme with custom CSS.
- **Modularized the codebase**: split the original single-file app into
  focused modules (`config.py`, `database.py`, `safety.py`,
  `sql_generator.py`, `utils.py`, `theme.py`) — each independently readable
  and testable, rather than one growing script.
- **Replaced the autonomous agent with a human-in-the-loop design**: swapped
  the fully autonomous `create_agent` flow (which decided on its own when to
  run queries) for a single-shot generate-then-approve flow — a deliberate
  trade-off of AI autonomy for a stronger, code-enforced safety guarantee.
- **Added a real test suite** covering the safety guardrail, response
  parsing, SQL generation, and query execution — which caught and led to
  fixing a genuine false-positive bug in the guardrail logic.

*Note: a chunk of this work was done offline (local development and testing
without pushing incrementally), which is why some of this shows up as fewer,
larger commits rather than a granular step-by-step history.*

## Roadmap / Future Scope

- **Multi-database support**: let a visitor connect their own database
  (MySQL, Postgres, or an uploaded SQLite file) via a `DatabaseAdapter`
  interface, stored per-visitor in Streamlit's session state — no login
  required, since this only needs session isolation, not identity.
- **Authentication**: a login screen (via `streamlit-authenticator` or
  similar) so the app knows who's asking.
- **True role-based access control**: map each authenticated user's role to
  its own database user with distinct `GRANT` permissions — e.g. an HR role
  that can see salary data, and a general role that can't — enforced at the
  database level, separate from the multi-database feature above.
- **Permission-aware UI**: show each logged-in user which tables/columns
  they currently have access to, based on their real database grants.
- **Deployment**: Streamlit Community Cloud, with the SSL certificate and
  credentials handled through the platform's secrets manager rather than a
  local file.
