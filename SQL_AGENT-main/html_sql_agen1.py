def generate_html_sql_workflow():
    html_content = """

<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>SQLite3 Workflow</title>
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
    width: 480px;
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
    font-size: 14px;
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
    width: 480px;
    text-align: center;
    color: #ffd166;
    font-weight: bold;
  }
</style>
</head>
<body>

<h1>SQLite3 Workflow</h1>

<div class="box">
  <div class="step-title">STEP 1 — CONNECT</div>
  <code>conn = sqlite3.connect("database.db")</code>
  <div class="desc">Opens the database file. Creates it if it doesn't exist yet.</div>
</div>
<div class="arrow">&#8595;</div>

<div class="box">
  <div class="step-title">STEP 2 — CREATE CURSOR</div>
  <code>cursor = conn.cursor()</code>
  <div class="desc">The cursor executes SQL commands and fetches results.</div>
</div>
<div class="arrow">&#8595;</div>

<div class="box">
  <div class="step-title">STEP 3 — CREATE TABLE</div>
  <code>cursor.execute("CREATE TABLE IF NOT EXISTS ...")</code>
  <div class="desc">Defines column names and data types.</div>
</div>
<div class="arrow">&#8595;</div>

<div class="box">
  <div class="step-title">STEP 4 — INSERT DATA</div>
  <code>cursor.execute("INSERT INTO table VALUES (...)")</code>
  <div class="desc">Adds rows. Changes are still PENDING at this point — not yet permanent.</div>
</div>
<div class="arrow">&#8595;</div>

<div class="box warning">
  <div class="step-title">STEP 5 — COMMIT (most forgotten step)</div>
  <code>conn.commit()</code>
  <div class="desc">Permanently saves pending changes to disk. Skip this and your inserts can vanish.</div>
</div>
<div class="arrow">&#8595;</div>

<div class="box">
  <div class="step-title">STEP 6 — QUERY / READ</div>
  <code>cursor.execute("SELECT * FROM table")
results = cursor.fetchall()   # all rows
results = cursor.fetchone()   # first row only
results = cursor.fetchmany(n) # n rows</code>
  <div class="desc">Retrieve data back from the table.</div>
</div>
<div class="arrow">&#8595;</div>

<div class="box warning">
  <div class="step-title">STEP 7 — CLOSE</div>
  <code>conn.close()</code>
  <div class="desc">Releases the database file. Always commit() BEFORE closing.</div>
</div>

<div class="rule">
  GOLDEN RULE: CREATE / INSERT / UPDATE / DELETE &rarr; commit() &rarr; then close()
</div>

</body>
</html>
"""
    return html_content;




