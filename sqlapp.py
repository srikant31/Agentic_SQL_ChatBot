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

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import create_agent
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit

load_dotenv()

# ============================================================
# CONFIG
# ============================================================

st.set_page_config(page_title="SQL Agent — Employees DB", page_icon="🗄️", layout="wide")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, sans-serif;
    color: #1E1A16;
}

.stApp {
    background-color: #C7A07A;
}

.block-container {
    max-width: 760px;
    padding-top: 3rem;
    padding-bottom: 3rem;
}

h1 {
    font-weight: 600;
    font-size: 2.1rem;
    letter-spacing: -0.01em;
    color: #1E1A16;
}

[data-testid="stCaptionContainer"] {
    color: #4A3F35;
}

[data-testid="stSidebar"] {
    background-color: #C7A07A;
    border-right: 2px solid #000000;
}

hr, [data-testid="stDivider"] {
    border-color: #000000 !important;
}

.stTextArea textarea, .stSelectbox div[data-baseweb="select"] {
    background-color: #C7A07A !important;
    border: 1.5px solid #000000 !important;
    border-radius: 4px !important;
    box-shadow: none !important;
    color: #1E1A16 !important;
}

.stButton button {
    background-color: #000000;
    color: #F3E6D8;
    border: 1.5px solid #000000;
    border-radius: 4px;
    padding: 0.4rem 1rem;
    font-weight: 500;
    box-shadow: none;
    transition: opacity 0.15s ease;
}
.stButton button:hover {
    opacity: 0.8;
    color: #F3E6D8;
}
.stButton button:disabled {
    background-color: transparent;
    border-color: #4A3F35;
    color: #4A3F35;
}

[data-testid="stExpander"] {
    border: 1.5px solid #000000;
    border-radius: 4px;
    background-color: #C7A07A;
}

[data-testid="stAlert"] {
    border: 1.5px solid #000000;
    border-radius: 4px;
    background-color: #C7A07A;
}

code, .stCodeBlock {
    background-color: #B78F68 !important;
    border: 1px solid #000000 !important;
    border-radius: 4px;
    color: #1E1A16 !important;
}
</style>
""", unsafe_allow_html=True)
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = quote_plus(os.getenv("MYSQL_PASSWORD", ""))
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "ktl")

DB_URI = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?ssl_ca=ca.pem"

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

# Cap on questions per browser session, so one visitor can't burn
# the whole free-tier quota alone on a public demo.
MAX_QUESTIONS_PER_SESSION = 15

# ============================================================
# HELPERS
# ============================================================

def extract_text(content):
    """
    Gemini's chat responses can come back as either a plain string
    (like OpenAI's) or a list of content blocks, e.g.:
    [{'type': 'text', 'text': 'OK', 'extras': {'signature': '...'}}]
    This normalizes either shape into plain displayable text.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts) if parts else str(content)
    return str(content)


# ============================================================
# CACHED RESOURCES — built once per session
# ============================================================

@st.cache_resource(show_spinner="Connecting to database...")
def get_db():
    return SQLDatabase.from_uri(DB_URI)


@st.cache_resource(show_spinner="Setting up the SQL agent...")
def get_agent():
    db = get_db()
    llm = ChatGoogleGenerativeAI(temperature=0, model="gemini-3.6-flash")
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

st.title("SQL Agent — Employees Database")
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
    st.caption("Set MYSQL_USER, MYSQL_PASSWORD, MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE, and GOOGLE_API_KEY in your .env file.")

    if "questions_asked" not in st.session_state:
        st.session_state.questions_asked = 0
    remaining = MAX_QUESTIONS_PER_SESSION - st.session_state.questions_asked
    st.divider()
    st.caption(f"Questions remaining this session: {max(remaining, 0)} / {MAX_QUESTIONS_PER_SESSION}")

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

session_limit_reached = st.session_state.get("questions_asked", 0) >= MAX_QUESTIONS_PER_SESSION

if session_limit_reached:
    st.warning("You've reached the question limit for this session. Refresh the page to reset (this demo caps usage to keep it free for everyone).")

run_clicked = st.button("Ask the Agent", type="primary", disabled=(question == "" or session_limit_reached))

# ============================================================
# RUN AGENT
# ============================================================

if run_clicked and question:
    st.session_state.questions_asked += 1
    agent = get_agent()

    with st.spinner("Agent is thinking..."):
        try:
            result = agent.invoke({"messages": [{"role": "user", "content": question}]})
        except Exception as e:
            st.error(f"Something went wrong: {e}")
            st.stop()

    final_answer = extract_text(result["messages"][-1].content)

    st.subheader("Answer")
    st.markdown(final_answer)

    with st.expander("See agent's full reasoning (tool calls, queries run, etc.)"):
        for msg in result["messages"]:
            role = msg.__class__.__name__
            content = extract_text(getattr(msg, "content", ""))
            tool_calls = getattr(msg, "tool_calls", None)

            st.markdown(f"**{role}**")
            if content:
                st.code(content, language=None)
            if tool_calls:
                for tc in tool_calls:
                    st.markdown(f"🔧 Tool call: `{tc.get('name')}` — args: `{tc.get('args')}`")
            st.divider()