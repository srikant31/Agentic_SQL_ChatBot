
def generate_html_langchain_sql_agent_workflow():
    html_content = """

<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>LangChain SQL Agent Workflow</title>
<style>
  body {
    font-family: 'Segoe UI', Arial, sans-serif;
    background: #0f1117;
    color: #e6e6e6;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 40px 20px;
  }
  h1 {
    color: #ffffff;
    margin-bottom: 30px;
  }
  .box {
    background: #1b1e27;
    border: 2px solid #4f8cff;
    border-radius: 10px;
    padding: 16px 24px;
    width: 560px;
    text-align: left;
    box-shadow: 0 0 12px rgba(79,140,255,0.25);
  }
  .box.warning {
    border-color: #ff9f43;
    box-shadow: 0 0 12px rgba(255,159,67,0.25);
  }
  .box.highlight {
    border-color: #7CFC9A;
    box-shadow: 0 0 12px rgba(124,252,154,0.25);
  }
  .step-title {
    font-weight: bold;
    font-size: 16px;
    color: #4f8cff;
    margin-bottom: 6px;
  }
  .box.warning .step-title { color: #ff9f43; }
  .box.highlight .step-title { color: #7CFC9A; }
  code {
    display: block;
    background: #0b0d12;
    color: #7CFC9A;
    padding: 8px 10px;
    border-radius: 6px;
    margin: 8px 0;
    font-size: 13px;
    white-space: pre-wrap;
  }
  .desc {
    font-size: 14px;
    color: #c7c7c7;
  }
  .arrow {
    font-size: 26px;
    color: #4f8cff;
    margin: 6px 0;
  }
  .rule {
    margin-top: 40px;
    background: #1b1e27;
    border: 2px dashed #ffd166;
    border-radius: 10px;
    padding: 16px 24px;
    width: 560px;
    text-align: center;
    color: #ffd166;
    font-weight: bold;
  }
</style>
</head>
<body>

<h1>LangChain SQL Agent Workflow</h1>

<div class="box">
  <div class="step-title">STEP 1 — CONNECT TO THE DATABASE</div>
  <code>from langchain_community.utilities import SQLDatabase

db = SQLDatabase.from_uri("mysql+pymysql://user:pass@host:3306/dbname")</code>
  <div class="desc">Wraps any SQLAlchemy-compatible connection (SQLite, MySQL, PostgreSQL, Databricks) into a LangChain-friendly object.</div>
</div>
<div class="arrow">&#8595;</div>

<div class="box">
  <div class="step-title">STEP 2 — VERIFY THE CONNECTION</div>
  <code>print(db.get_usable_table_names())
print(db.get_table_info())</code>
  <div class="desc">Confirms the tables are visible and shows their schema, which the LLM will later read to write correct queries.</div>
</div>
<div class="arrow">&#8595;</div>

<div class="box">
  <div class="step-title">STEP 3 — BUILD THE SQL TOOLKIT</div>
  <code>from langchain_community.agent_toolkits import SQLDatabaseToolkit

toolkit = SQLDatabaseToolkit(db=db, llm=llm)
tools = toolkit.get_tools()</code>
  <div class="desc">Auto-generates four tools: list tables, get schema, run a query, and check query syntax before running it.</div>
</div>
<div class="arrow">&#8595;</div>

<div class="box">
  <div class="step-title">STEP 4 — CREATE THE AGENT</div>
  <code>from langchain.agents import create_agent

sql_agent = create_agent(
    model=llm,
    tools=tools,
    system_prompt="You are a SQL expert. Check the schema, "
                  "write a correct query, run it, and explain the result."
)</code>
  <div class="desc">Wires the LLM and the SQL tools together into a single agent that can reason step by step.</div>
</div>
<div class="arrow">&#8595;</div>

<div class="box highlight">
  <div class="step-title">STEP 5 — ASK A QUESTION</div>
  <code>result = sql_agent.invoke({
    "messages": [{"role": "user", "content": "Who is Bob Brown's manager?"}]
})
print(result["messages"][-1].content)</code>
  <div class="desc">The agent decides which tables to check, writes the SQL, runs it, and replies in plain language.</div>
</div>

<div class="rule">
  INTERNAL LOOP: Question &rarr; check schema &rarr; write SQL &rarr; run it &rarr; error? fix and retry &rarr; explain result in plain language
</div>

</body>
</html>
"""
    return html_content