"""
SQL Agent Streamlit App
------------------------
A small UI around the LangChain SQL Agent connected to a MySQL database.
Lets the user pick from a list of predefined sample questions, or type
their own natural-language question, and see the agent's reasoning +
final answer.
"""

import os
import streamlit as st
from dotenv import load_dotenv
from urllib.parse import quote_plus

from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit

load_dotenv()

# ============================================================
# CONFIG
# ============================================================

st.set_page_config(page_title="SQL Agent — Employees DB", page_icon="🗄️", layout="wide")

MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = quote_plus(os.getenv("MYSQL_PASSWORD", ""))
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")


DB_URI = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/ktl"

# Predefined questions for the EMPLOYEES table (id, name, manager_id, manager_name)
SAMPLE_QUESTIONS = [
    "Select a sample question...",
    "Tell me the manager's name for each employee along with their employee ID and manager ID. If no manager exists, return 'CEO' as the manager name and 0 as the manager ID.",
    "Who is Bob Brown's manager?",
    "How many employees report directly to Jane Smith?",
    "List all employees who have no manager.",
    "Which employee has the most direct reports?",
    "Show me the full reporting chain for Hannah Clark.",
]

# ============================================================
# CACHED RESOURCES — built once per session
# ============================================================

@st.cache_resource(show_spinner="Connecting to database...")
def get_db():
    return SQLDatabase.from_uri(DB_URI)


@st.cache_resource(show_spinner="Setting up the SQL agent...")
def get_agent():
    db = get_db()
    llm = ChatOpenAI(temperature=0, model="gpt-4.1-mini")
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    tools = toolkit.get_tools()

    system_prompt = """
    - You are a SQL agent that can interact with a MySQL database.
    - Check the database schema and table information before answering any questions.
    - Use the tools provided to you to execute SQL queries and retrieve data from the database.
    - Present the output in a clear, readable format (use a table when appropriate).
    """

    return create_agent(tools=tools, model=llm, system_prompt=system_prompt)


# ============================================================
# UI
# ============================================================

st.title("🗄️ SQL Agent — Employees Database")
st.caption("Ask questions in plain English. The agent inspects the schema, writes SQL, runs it, and explains the result.")

with st.sidebar:
    st.header("Database Info")
    try:
        db = get_db()
        st.success("Connected to MySQL ✅")
        st.write("**Tables:**")
        for t in db.get_usable_table_names():
            st.write(f"- {t}")
    except Exception as e:
        st.error(f"Connection failed: {e}")
        st.stop()

    st.divider()
    st.caption("Set MYSQL_USER, MYSQL_PASSWORD, MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE, and OPENAI_API_KEY in your .env file.")

# --- Question input ---
selected_sample = st.selectbox("Pick a sample question:", SAMPLE_QUESTIONS)

custom_question = st.text_area(
    "...or type your own question:",
    placeholder="e.g. Which employees report to Alice Johnson?",
    height=80,
)

question = custom_question.strip() if custom_question.strip() else (
    selected_sample if selected_sample != SAMPLE_QUESTIONS[0] else ""
)

run_clicked = st.button("Ask the Agent", type="primary", disabled=(question == ""))

# ============================================================
# RUN AGENT
# ============================================================

if run_clicked and question:
    agent = get_agent()

    with st.spinner("Agent is thinking..."):
        try:
            result = agent.invoke({"messages": [{"role": "user", "content": question}]})
        except Exception as e:
            st.error(f"Something went wrong: {e}")
            st.stop()

    final_answer = result["messages"][-1].content

    st.subheader("Answer")
    st.markdown(final_answer)

    with st.expander("See agent's full reasoning (tool calls, queries run, etc.)"):
        for msg in result["messages"]:
            role = msg.__class__.__name__
            content = getattr(msg, "content", "")
            tool_calls = getattr(msg, "tool_calls", None)

            st.markdown(f"**{role}**")
            if content:
                st.code(content, language=None)
            if tool_calls:
                for tc in tool_calls:
                    st.markdown(f"🔧 Tool call: `{tc.get('name')}` — args: `{tc.get('args')}`")
            st.divider()