import json
from langchain_google_genai import ChatGoogleGenerativeAI

from utils import extract_text


def generate_sql(question: str, schema_text: str) -> dict:
    """
    Single call to Gemini: given the schema and a question, generate
    exactly one SQL query plus a short explanation. Does not execute it.
    """
    llm = ChatGoogleGenerativeAI(temperature=0, model="gemini-3.6-flash")

    prompt = f"""
You are a SQL assistant for a MySQL database.

Convert the user's natural-language question into a SQL query using ONLY
the tables and columns shown in the schema below.

STRICT RULES:
1. Use ONLY tables and columns present in the schema.
2. NEVER invent a table or column.
3. Generate READ-ONLY SQL only — a single SELECT statement.
4. NEVER use INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, or any
   other statement that isn't a SELECT.
5. Give a short, plain-English explanation of what the query does.
6. Return ONLY valid JSON in this exact shape, nothing else:

{{"sql": "SELECT ...;", "explanation": "Short explanation."}}

DATABASE SCHEMA:
{schema_text}

USER QUESTION:
{question}
"""

    response = llm.invoke(prompt)
    text = extract_text(response.content).strip()

    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Gemini returned invalid JSON: {text}") from exc

    sql = result.get("sql")
    if not sql:
        raise RuntimeError("Gemini did not return a SQL query.")

    return {"sql": sql.strip(), "explanation": result.get("explanation", "Query generated.").strip()}