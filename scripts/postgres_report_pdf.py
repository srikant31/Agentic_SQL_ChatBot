"""PDF of the app's feedback store (Postgres): what is stored and the results of three read-only queries.

Run from the project root (PowerShell, one line):
    $env:PYTHONIOENCODING="utf-8"; .\\venv\\Scripts\\python.exe scripts\\postgres_report_pdf.py

Output: eval_runs/Postgres_feedback_store_<date>.pdf
        (with --publish, also copied to golden_eval/results/)
Read-only (SELECT only), no AI calls, no cost. Never prints the connection URL, host, user or password.
Needs the fpdf2 package.
"""
import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

import config  # noqa: E402,F401  loads .env and Streamlit secrets
import feedback_store  # noqa: E402
from eval_report_pdf import ACCENT, BAD, GOOD, INK, LINE, MUTED, clean  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402


def queries(dialect):
    left = "LEFT(question, 60)" if dialect != "sqlite" else "SUBSTR(question, 1, 60)"
    return [
        ("What is stored",
         "Rows in each table and how many distinct questions they cover.",
         "SELECT (SELECT COUNT(*) FROM query_events) AS query_events,\n"
         "       (SELECT COUNT(DISTINCT request_id) FROM query_events) AS questions,\n"
         "       (SELECT COUNT(*) FROM llm_calls) AS llm_calls,\n"
         "       (SELECT COUNT(DISTINCT username) FROM query_events) AS demo_accounts"),
        ("Latest steps",
         "Every user action is one row: question, proposal, approval, run, vote, rewrite.",
         "SELECT ts, display_name, role, version, event, status, vote,\n"
         f"       {left} AS question\n"
         "FROM query_events ORDER BY id DESC LIMIT 15"),
        ("Model calls by step",
         "Every AI request is logged with its latency and token counts.",
         "SELECT node, COUNT(*) AS calls,\n"
         "       ROUND(AVG(latency_ms)) AS avg_ms,\n"
         "       ROUND(AVG(input_tokens)) AS avg_in_tokens,\n"
         "       ROUND(AVG(output_tokens)) AS avg_out_tokens,\n"
         "       SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS errors\n"
         "FROM llm_calls GROUP BY node ORDER BY calls DESC"),
        ("Questions and votes by department",
         "Who uses the assistant, and how they rate it.",
         "SELECT role,\n"
         "       COUNT(DISTINCT request_id) AS questions,\n"
         "       SUM(CASE WHEN vote = 'positive' THEN 1 ELSE 0 END) AS positive_votes,\n"
         "       SUM(CASE WHEN vote = 'negative' THEN 1 ELSE 0 END) AS negative_votes\n"
         "FROM query_events GROUP BY role ORDER BY questions DESC"),
    ]


def fmt(value):
    if value is None:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%m-%d %H:%M")
    if isinstance(value, float):
        return f"{value:,.0f}"
    try:                      # Decimal from ROUND(AVG(...)) on Postgres
        from decimal import Decimal
        if isinstance(value, Decimal):
            return f"{int(value):,}"
    except Exception:
        pass
    return str(value)


def build(out_path):
    from fpdf import FPDF
    from fpdf.fonts import FontFace

    url = feedback_store.database_url()
    engine = create_engine(url, pool_pre_ping=True)
    dialect = engine.dialect.name
    backend = {"postgresql": "Postgres", "sqlite": "SQLite (local file, not Postgres)"}.get(dialect, dialect)
    host = engine.url.host or ""
    provider = "Neon" if "neon" in host else "Aiven" if "aiven" in host else "Supabase" if "supabase" in host else None
    from sqlalchemy import inspect as sa_inspect, select
    if not sa_inspect(engine).has_table("query_events"):
        raise RuntimeError("no feedback tables yet")
    results = []
    with engine.connect() as connection:
        if dialect == "postgresql":
            connection.execute(text("SET TRANSACTION READ ONLY"))
        events = [dict(r._mapping) for r in connection.execute(
            select(feedback_store.query_events).order_by(feedback_store.query_events.c.id))]
        summary = feedback_store.summarize(events)
        for title, note, sql in queries(dialect):
            result = connection.execute(text(sql))
            results.append((title, note, sql, list(result.keys()), [list(r) for r in result.fetchall()]))

    class Report(FPDF):
        def footer(self):
            self.set_y(-12)
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*MUTED)
            self.cell(0, 6, "ColdChain assistant - feedback store report (read-only queries)", align="L")
            self.cell(0, 6, f"Page {self.page_no()}/{{nb}}", align="R")

    pdf = Report(format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(True, margin=16)
    pdf.set_margins(15, 15, 15)

    def para(t, size=10, colour=INK, style=""):
        pdf.set_font("Helvetica", style, size)
        pdf.set_text_color(*colour)
        pdf.multi_cell(0, 5, clean(t), align="L", new_x="LMARGIN", new_y="NEXT")

    def table(rows, size=8.5, widths=None):
        pdf.set_font("Helvetica", "", size)
        pdf.set_text_color(*INK)
        pdf.set_draw_color(*LINE)
        pdf.set_fill_color(255, 255, 255)
        with pdf.table(col_widths=widths, text_align="LEFT", line_height=4.6, first_row_as_headings=True, cell_fill_mode="NONE",
                       headings_style=FontFace(emphasis="BOLD", fill_color=(241, 243, 245)),
                       borders_layout="HORIZONTAL_LINES", padding=1.2) as t:
            for row in rows:
                r = t.row()
                for value in row:
                    r.cell(clean(fmt(value), 70))

    pdf.add_page()
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*INK)
    pdf.cell(0, 10, "Feedback store: query results", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*MUTED)
    where = f"{backend}" + (f" on {provider}" if provider else "")
    pdf.cell(0, 7, clean(f"Database: {where}  |  generated {datetime.now():%Y-%m-%d %H:%M}"), new_x="LMARGIN", new_y="NEXT")
    if dialect != "postgresql":
        para("Warning: FEEDBACK_DB_URL / PG_URL is not set to Postgres on this machine, so these results come from "
             "the local SQLite file.", 9.5, BAD, "B")
    pdf.ln(2)
    para("The ColdChain business database (MySQL on Aiven) is read-only for the app. The app's own records go to this "
         "separate, writable database: query_events (every user action) and llm_calls (every AI request with prompt, "
         "response, latency and tokens). All queries below are read-only.", 9.5, MUTED)
    pdf.ln(3)

    share = lambda v: "n/a" if v is None else f"{100 * v:.0f}%"
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*INK)
    pdf.cell(0, 8, "Headline numbers", new_x="LMARGIN", new_y="NEXT")
    table([["Measure", "Value"],
           ["Questions asked", summary.get("questions")],
           ["Accepted on the first proposal", share(summary.get("accepted_first_proposal"))],
           ["Ended with a successful run", share(summary.get("resolved_with_successful_run"))],
           ["Rewrites per question (average)", summary.get("avg_rewrites_per_question")],
           ["Model calls per question (average)", summary.get("avg_model_calls_per_question")],
           ["Questions that hit the 3-rewrite limit", summary.get("rewrite_limit_reached")],
           ["Run failure rate", share(summary.get("run_failure_rate"))],
           ["Votes positive / negative", f"{summary.get('votes_positive')} / {summary.get('votes_negative')}"]], size=9)
    para("Acceptance is what users clicked, not correctness; correctness comes from the golden-set evaluation.", 8.5, MUTED)

    for i, (title, note, sql, columns, rows) in enumerate(results, 1):
        if pdf.get_y() > pdf.h - 80:
            pdf.add_page()
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(*ACCENT)
        pdf.cell(0, 8, clean(f"Query {i}: {title}"), new_x="LMARGIN", new_y="NEXT")
        para(note, 9, MUTED)
        pdf.set_font("Courier", "", 8)
        pdf.set_text_color(*INK)
        pdf.set_fill_color(246, 247, 249)
        pdf.multi_cell(0, 4, clean(sql), fill=True, align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1.5)
        if rows:
            widths = (20, 26, 20, 13, 17, 19, 15, 50) if len(columns) == 8 else None
            table([columns] + rows, size=7.5 if len(columns) > 6 else 8.5, widths=widths)
        else:
            para("No rows yet.", 9, BAD)
        para(f"{len(rows)} row(s) returned.", 8, GOOD)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return backend, summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true", help="also copy the PDF to golden_eval/results/")
    args = ap.parse_args()
    try:
        import fpdf  # noqa: F401
    except ImportError:
        print("The fpdf2 package is missing. Install it with: .\\venv\\Scripts\\python.exe -m pip install fpdf2")
        return 1
    out = ROOT / "eval_runs" / f"Postgres_feedback_store_{datetime.now():%Y-%m-%d}.pdf"
    try:
        backend, summary = build(out)
    except Exception as exc:
        reason = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        print(f"Could not build the report: {reason} (check FEEDBACK_DB_URL / PG_URL; details not shown).")
        return 1
    print(f"Database: {backend}. Questions in store: {summary.get('questions')}.")
    print(f"PDF: {out.relative_to(ROOT).as_posix()}")
    if args.publish:
        target = ROOT / "golden_eval" / "results" / out.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out, target)
        print(f"Published: {target.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
