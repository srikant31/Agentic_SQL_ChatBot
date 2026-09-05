# SQL Agent with LangChain

A hands-on project exploring how to connect Large Language Models to relational databases — starting from raw `sqlite3`, moving through `SQLAlchemy` as a universal database connector, and finally building a working **SQL Agent** using LangChain that can answer natural language questions by generating, executing, and explaining SQL queries.

## Overview

This project walks through the full stack needed to build a database-aware AI agent:

1. **SQLite3 fundamentals** — connecting, creating tables, inserting data, and querying with Python's built-in `sqlite3` module.
2. **SQLAlchemy** — a universal database toolkit that works across SQLite, MySQL, PostgreSQL, and more, using the same consistent API.
3. **MySQL integration** — connecting to a production-style MySQL database instead of a local file-based database.
4. **LangChain SQL Agent (toolkit-based)** — using LangChain's built-in `SQLDatabaseToolkit` to auto-generate the tools an agent needs to interact with a database.
5. **Manual Toolkit creation** — building the same set of database tools from scratch using LangChain's `@tool` decorator, to understand what the toolkit does under the hood.

## Why SQLite First, Then MySQL?

SQLite requires no server setup — it's a single file, making it ideal for quickly prototyping and testing an agent's logic. Once the agent's reasoning is verified, the same code can point to a production database (MySQL, PostgreSQL, Databricks) by simply swapping the connection string, since both `SQLAlchemy` and LangChain's `SQLDatabase` utility are database-agnostic.

## Project Structure

```
.
├── sql_agent.ipynb                          # Main notebook — full walkthrough
├── html_sql_agen1.py                        # HTML flow diagram: SQLite3 workflow
├── sql_alchemy_html_flow.py                 # HTML flow diagram: SQLAlchemy workflow
├── html_langchain_agent_flow.py             # HTML flow diagram: LangChain SQL Agent workflow
├── ktl_database.db                          # Local SQLite database (sample data)
├── .env                                     # Environment variables (API keys, DB credentials) — not committed
├── .gitignore
└── requirements.txt
|__ sqlapp.py                                # The application

```

## Sample Dataset

The notebook uses a simple `EMPLOYEES` table representing an organizational hierarchy:

| Column | Type | Description |
|---|---|---|
| `EMPLOYEE_ID` | INTEGER | Unique employee identifier |
| `NAME` | TEXT | Employee name |
| `MANAGER_ID` | INTEGER | ID of the employee's manager (nullable) |
| `MANAGER_NAME` | TEXT | Name of the employee's manager (nullable) |

This same schema is created in both SQLite (for local testing) and MySQL (for a production-style setup).

## Key Concepts Covered

- **Connect → Cursor → Create → Insert → Commit → Query → Close**: the core SQLite3 workflow, including why `commit()` is required before `close()` to persist changes.
- **SQLAlchemy as a universal connector**: one consistent API (`create_engine`, `text()`, `.connect()`) that works across different database engines by simply changing the connection string.
- **Safe credential handling**: using `urllib.parse.quote_plus()` to URL-encode passwords containing special characters (e.g., `@`) so they don't break the connection string.
- **LangChain's `SQLDatabase` utility**: wrapping a SQLAlchemy engine so an LLM can inspect table names and schemas before writing queries.
- **`SQLDatabaseToolkit`**: LangChain's built-in toolkit that auto-generates four tools — list tables, get schema, run a query, and check query syntax — from a single `SQLDatabase` object.
- **`create_agent`**: wiring an LLM (via `ChatOpenAI`) and the SQL tools together into an agent capable of multi-step reasoning (check schema → write query → execute → self-correct on error → explain result).
- **Manual tool creation**: rebuilding the toolkit's core functionality by hand using the `@tool` decorator and raw SQLAlchemy calls, to understand exactly what the toolkit abstracts away.

## How the Agent Works

```
User asks a question (natural language)
        ↓
Agent inspects the database schema
        ↓
Agent writes a SQL query
        ↓
Agent executes the query via a tool
        ↓
   ┌────┴────┐
 Success   Error
   │          │
   │     Agent fixes the query and retries
   ↓
Agent explains the result in plain language
```

## Setup

**1. Install dependencies**
```bash
pip install -r requirements.txt
```

**2. Set up environment variables**

Create a `.env` file in the project root:
```
OPENAI_API_KEY=your_openai_api_key
```

**3. Configure your database connection**

For MySQL, update the connection details in the notebook:
```python
MYSQL_USER = "root"
MYSQL_PASSWORD = "your_password"
MYSQL_HOST = "localhost"
MYSQL_PORT = "3306"
MYSQL_DATABASE = "your_database"
```

**4. Run the notebook**

Open `sql_agent.ipynb` and run the cells sequentially — it's structured as a progressive walkthrough, from raw SQLite3 to a fully working LangChain SQL Agent.

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

The agent inspects the schema, writes an appropriate `LEFT JOIN` query, executes it, and returns a natural-language, tabular-formatted answer.

---
<img width="645" height="762" alt="image" src="https://github.com/user-attachments/assets/ff78621e-40cf-4453-a035-01120f122320" />

---

## Tech Stack

- **Python 3.11+**
- **LangChain** (`langchain.agents.create_agent`)
- **LangChain OpenAI** (`ChatOpenAI`)
- **SQLAlchemy**
- **SQLite3** (built-in)
- **PyMySQL** (MySQL driver)
- **python-dotenv**

## Notes

- The `SQLDatabaseToolkit` internally relies on SQLAlchemy — using the toolkit doesn't remove the need for SQLAlchemy, it simply automates the tool-writing step.
- `ChatOpenAI` (not `OpenAI`) must be used as the model for `create_agent`, since chat models are required for tool-calling support.
- Passwords containing special characters (like `@`) must be URL-encoded with `quote_plus()` before being placed in a connection string, otherwise the connection parser misreads the credentials.
