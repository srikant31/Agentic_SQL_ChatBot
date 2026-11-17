# Chat review and feedback — 16 November 2026

The main ColdChain screen displays the saved user question and model explanation as chat messages,
followed by the proposed SQL. Prior questions, modifications and results remain associated
with their own responses. The original question is never replaced by a model paraphrase.

- **Looks good** records positive feedback; it does not approve or execute SQL.
- **Needs changes** hides the run button and opens **What should change?**, with placeholder
  “Please prompt again and tell the model what to modify.”
- **Rewrite query** sends the original question, current complete request and all prior
  modifications to the model. Later changes override conflicting earlier ones. The complete
  updated request is displayed and goes through fresh authorization/context/SQL validation.
- Under **Needs changes / Negative**, a proposed query also offers **The query does not
  follow the business rules**. Select it and click **Rewrite query**, with optional details
  naming the rule. The reason asks the rewrite to re-check the supplied glossary while
  preserving the request; it is saved with the rewrite hint and a `business_rules` reason
  in the ColdChain event log. Selecting it alone makes no model or SQL call. The normal
  three-rewrite budget, permission checks and separate execution approval still apply.
- Each original request allows **three rewrites after the initial proposal**. After a third
  rewritten response receives negative feedback, the UI shows an apology and requires a new
  question. Rerenders do not replenish the counter. ColdChain also checkpoints the reserved
  count, so restoring an interrupted review retains its budget.
- Every proposed SQL in these interactive pages needs a separate run/approval click. A rewrite
  invalidates the old proposal. Positive feedback never doubles as approval.
- UI workflows use one generation attempt per proposal instead of nesting three automatic
  attempts inside each human rewrite. Existing non-UI graph defaults/evaluation policy remain.
- A rewrite uses one model request to reformulate the question, followed by the ordinary
  generation workflow; ColdChain also retains its classification call. Submitted rewrites
  consume a slot even on failure and count towards the existing session question cap.

Historical employee test-harness responses explain sources, filters, grouping and expected output without inventing
result rows. ColdChain's interactive graph additionally requests a query explanation before
approval. Existing employee confidence display is preserved; no confidence-score feature,
LangSmith reconfiguration, Ragas integration or decomposition was added in this change.

## Local demonstration

```powershell
.\venv\Scripts\python.exe -m streamlit run scripts/preview_query_chat.py --server.address 127.0.0.1 --server.port 8502
```

This opens the historical employee UI test harness with a disposable fictional SQLite database and clearly
labelled demonstration responses. It makes no Aiven or model requests. Ask “Count employees
by department”, choose **Needs changes**, enter “Only Engineering”, then choose **Rewrite
query**. This is not the main ColdChain screen. The normal `sqlapp.py` entry point exclusively
opens ColdChain, using the configured provider and read-only MySQL database. Employee admin
and explorer pages are not registered in its navigation.

## Validation

Tests cover positive/negative feedback without execution, three-rewrite exhaustion, stale
event rejection, original-question retention, reauthorization after feedback, both employee
workflow modes, ColdChain review before public SQL execution, checkpoint restoration and
preservation of the default ColdChain evaluation flow. Existing measurement artifacts are
left unchanged and describe the earlier application version.
