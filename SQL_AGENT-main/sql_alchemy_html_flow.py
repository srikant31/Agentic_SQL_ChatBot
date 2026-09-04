
def sql_alchemy_workflow_ktl():


    html_content = """

    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <title>SQLAlchemy Workflow</title>
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
        width: 500px;
        text-align: left;
        box-shadow: 0 0 12px rgba(79,140,255,0.25);
    }
    .box.warning {
        border-color: #ff9f43;
        box-shadow: 0 0 12px rgba(255,159,67,0.25);
    }
    .step-title {
        font-weight: bold;
        font-size: 16px;
        color: #4f8cff;
        margin-bottom: 6px;
    }
    .box.warning .step-title {
        color: #ff9f43;
    }
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
        width: 500px;
        text-align: center;
        color: #ffd166;
        font-weight: bold;
    }
    </style>
    </head>
    <body>

    <h1>SQLAlchemy Workflow</h1>

    <div class="box">
    <div class="step-title">STEP 1 — CREATE THE ENGINE</div>
    <code>from sqlalchemy import create_engine
    engine = create_engine("mysql+pymysql://user:pass@host/db")</code>
    <div class="desc">The engine is a connection blueprint — it defines which database, where it lives, and what credentials to use. No actual connection is opened yet.</div>
    </div>
    <div class="arrow">&#8595;</div>

    <div class="box">
    <div class="step-title">STEP 2 — OPEN A CONNECTION</div>
    <code>with engine.connect() as conn:</code>
    <div class="desc">The engine opens a live connection to the database. Using "with" ensures it closes automatically afterward.</div>
    </div>
    <div class="arrow">&#8595;</div>

    <div class="box">
    <div class="step-title">STEP 3 — EXECUTE A QUERY</div>
    <code>from sqlalchemy import text
    result = conn.execute(text("SELECT * FROM employees"))</code>
    <div class="desc">Raw SQL strings must be wrapped in text() so SQLAlchemy knows to run them as literal SQL.</div>
    </div>
    <div class="arrow">&#8595;</div>

    <div class="box">
    <div class="step-title">STEP 4 — FETCH RESULTS</div>
    <code>rows = result.fetchall()   # all rows
    row  = result.fetchone()   # first row only</code>
    <div class="desc">Same fetch methods as raw sqlite3 — fetchall(), fetchone(), etc.</div>
    </div>
    <div class="arrow">&#8595;</div>

    <div class="box warning">
    <div class="step-title">STEP 5 — COMMIT (only for INSERT / UPDATE / DELETE)</div>
    <code>conn.commit()</code>
    <div class="desc">Required whenever data is modified. Not needed for plain SELECT queries.</div>
    </div>

    <div class="rule">
    KEY IDEA: The engine's connection STRING changes per database (SQLite, MySQL, PostgreSQL, Databricks) — but the REST of the code stays exactly the same.
    </div>

    </body>
    </html>
    """
    return html_content
        