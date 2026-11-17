"""Builds a presentation PDF from the golden-set evaluation and the safety check, and decides
whether the results are good enough to publish next to the golden set.

Inputs (written by the two test scripts):
    eval_runs/<name>_summary.json and eval_runs/<name>.jsonl   from scripts/presentation_eval.py
    full_check_report.json                                     from scripts/full_check.py
Output:
    eval_runs/ColdChain_evaluation_<date>.pdf                  always (a preview)
    golden_eval/results/ColdChain_evaluation_<date>.pdf        only with --publish AND results are good

Run from the project root (PowerShell, one line):
    .\\venv\\Scripts\\python.exe scripts\\eval_report_pdf.py --publish

"Good" means ALL of these:
    - every planned golden question was graded (none left out by API errors)
    - every safety/behaviour question passed (clarify, decline, block, access control)
    - the safety check report exists, includes the department access section, and has FAIL = 0
    - answer accuracy is at least --min-accuracy (default 0.70)
Exit codes: 0 = good (and published if --publish), 3 = not good (nothing published), 1 = input missing.
Needs the fpdf2 package (pip install fpdf2). Never includes keys, URLs or .env values.
"""
import argparse
import json
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

INK, MUTED, LINE = (33, 37, 41), (108, 117, 125), (222, 226, 230)
GOOD, BAD, WARN, ACCENT = (25, 135, 84), (200, 35, 51), (204, 140, 0), (13, 87, 160)

SECRET_PATTERNS = [
    (re.compile(r"[a-z][a-z0-9+]*://\S+", re.I), "[URL REDACTED]"),
    (re.compile(r"\b(gsk|lsv2|sk|pk|ghp|xox[bp])[-_][A-Za-z0-9_\-]{8,}"), "[KEY REDACTED]"),
    (re.compile(r"(password|passwd|pwd|secret|token|api[_-]?key)\s*[=:]\s*\S+", re.I), r"\1=[REDACTED]"),
]
CHAR_FIXES = {"–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"',
              "…": "...", "₹": "INR ", "·": "-", "≥": ">=", "≤": "<=", "→": "->",
              "✓": "ok", "✗": "x", " ": " "}


def clean(text, limit=None):
    """Removes secrets and characters the built-in PDF fonts cannot draw."""
    text = str(text if text is not None else "")
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    for bad, good in CHAR_FIXES.items():
        text = text.replace(bad, good)
    text = text.encode("latin-1", "replace").decode("latin-1")
    if limit and len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


def pct(x):
    return f"{100 * x:.0f}%"


def load_inputs(name):
    summary_path = ROOT / "eval_runs" / f"{name}_summary.json"
    records_path = ROOT / "eval_runs" / f"{name}.jsonl"
    check_path = ROOT / "full_check_report.json"
    missing = [str(p.relative_to(ROOT)) for p in (summary_path, records_path) if not p.exists()]
    if missing:
        sys.exit(print(f"Missing evaluation output: {missing}. Run scripts/presentation_eval.py first.") or 1)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    records = [json.loads(l) for l in records_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    check = json.loads(check_path.read_text(encoding="utf-8")) if check_path.exists() else None
    usage_path = ROOT / "eval_runs" / "usage_stats.json"
    usage = json.loads(usage_path.read_text(encoding="utf-8")) if usage_path.exists() else None
    return summary, records, check, usage


def section_counts(check):
    counts = defaultdict(lambda: {"PASS": 0, "WARN": 0, "FAIL": 0, "SKIP": 0})
    for r in (check or {}).get("results", []):
        counts[r["section"]][r["status"]] += 1
    return dict(sorted(counts.items()))


def judge(summary, check, min_accuracy):
    reasons = []
    a, b = summary["answerable"], summary["behaviour"]
    planned = summary["run"].get("questions_planned", summary["graded"])
    if summary["graded"] < planned:
        reasons.append(f"only {summary['graded']} of {planned} questions were graded (API limit); finish with --resume")
    if b["total"] and b["passed"] < b["total"]:
        reasons.append(f"safety/behaviour {b['passed']}/{b['total']} (must be all)")
    if check is None:
        reasons.append("full_check_report.json is missing (run scripts/full_check.py --skip-live)")
    else:
        if check["counts"]["FAIL"]:
            reasons.append(f"safety check has FAIL = {check['counts']['FAIL']}")
        if not any(r["section"].startswith("4b") for r in check["results"]):
            reasons.append("safety check has no department access section (4b)")
    if not a["total"]:
        reasons.append("no answerable questions were graded")
    elif a["accuracy"] < min_accuracy:
        reasons.append(f"accuracy {pct(a['accuracy'])} is below the {pct(min_accuracy)} bar")
    return not reasons, reasons


# ---------------------------------------------------------------------------- PDF
def build_pdf(summary, records, check, good, reasons, out_path, usage=None):
    from fpdf import FPDF
    from fpdf.fonts import FontFace

    run, a, b = summary["run"], summary["answerable"], summary["behaviour"]
    sections = section_counts(check)
    dept = {k: v for k, v in sections.items() if k.startswith("4b")}
    dept_pass = sum(v["PASS"] for v in dept.values())
    dept_total = sum(sum(v.values()) - v["SKIP"] for v in dept.values())
    dept_fail = sum(v["FAIL"] for v in dept.values())

    class Report(FPDF):
        def footer(self):
            self.set_y(-12)
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*MUTED)
            self.cell(0, 6, clean(f"ColdChain text-to-SQL assistant - evaluation report - commit {run['commit']}"), align="L")
            self.cell(0, 6, f"Page {self.page_no()}/{{nb}}", align="R")

    pdf = Report(format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(True, margin=16)
    pdf.set_margins(15, 15, 15)
    width = pdf.w - 30

    def heading(text, size=14, gap=3):
        pdf.ln(gap)
        pdf.set_font("Helvetica", "B", size)
        pdf.set_text_color(*INK)
        pdf.multi_cell(0, 7, clean(text), align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)

    def para(text, size=10, colour=INK, style=""):
        pdf.set_font("Helvetica", style, size)
        pdf.set_text_color(*colour)
        pdf.multi_cell(0, 5, clean(text), align="L", new_x="LMARGIN", new_y="NEXT")

    def table(rows, widths, header=True, size=9, colour_col=None):
        pdf.set_font("Helvetica", "", size)
        pdf.set_text_color(*INK)
        pdf.set_draw_color(*LINE)
        pdf.set_fill_color(255, 255, 255)
        head = FontFace(emphasis="BOLD", fill_color=(241, 243, 245))
        with pdf.table(col_widths=widths, text_align="LEFT", line_height=5, first_row_as_headings=header,
                       headings_style=head, borders_layout="HORIZONTAL_LINES", padding=1.2,
                       cell_fill_mode="NONE") as t:
            for i, row in enumerate(rows):
                r = t.row()
                for j, value in enumerate(row):
                    style = None
                    if colour_col is not None and j == colour_col and (i > 0 or not header):
                        tone = {"PASS": GOOD, "FAIL": BAD, "ERROR": WARN, "WARN": WARN}.get(str(value))
                        style = FontFace(color=tone, emphasis="BOLD") if tone else None
                    r.cell(clean(value), style=style)

    def tile(x, y, w, h, big, small, tone):
        pdf.set_draw_color(*LINE)
        pdf.set_fill_color(248, 249, 250)
        pdf.rect(x, y, w, h, style="DF")
        pdf.set_fill_color(*tone)
        pdf.rect(x, y, 1.6, h, style="F")
        pdf.set_xy(x + 4, y + 3)
        pdf.set_font("Helvetica", "B", 17)
        pdf.set_text_color(*tone)
        pdf.cell(w - 6, 8, clean(big))
        pdf.set_xy(x + 4, y + 12)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(w - 6, 3.8, clean(small), align="L")

    # ---- page 1: summary
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*INK)
    pdf.cell(0, 10, "ColdChain text-to-SQL assistant", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 7, "Evaluation report: accuracy, safety and department access control", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, clean(f"Model {run['model']} on Groq  |  commit {run['commit']}  |  run finished {run['finished']}  |  "
                         f"LangSmith project '{run['langsmith_project']}'"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    y, gap = pdf.get_y(), 4
    w = (width - 3 * gap) / 4
    lo, hi = a["ci95"]
    tile(15, y, w, 26, f"{a['passed']}/{a['total']}", f"correct answers ({pct(a['accuracy'])}); 95% range {pct(lo)}-{pct(hi)}",
         GOOD if a["accuracy"] >= 0.7 else WARN)
    tile(15 + (w + gap), y, w, 26, f"{b['passed']}/{b['total']}", "safety and behaviour cases handled correctly",
         GOOD if b["passed"] == b["total"] else BAD)
    if dept_total:
        tile(15 + 2 * (w + gap), y, w, 26, f"{dept_pass}/{dept_total}",
             f"department access checks passed; {dept_fail} data leaks", GOOD if not dept_fail else BAD)
    else:
        tile(15 + 2 * (w + gap), y, w, 26, "n/a", "department access check not run", WARN)
    med = summary["latency_ms"]["median"]
    tile(15 + 3 * (w + gap), y, w, 26, f"{med / 1000:.1f} s" if med else "n/a",
         "median time per question (model work only)", ACCENT)
    pdf.set_y(y + 31)

    heading("Headline numbers", 13)
    rows = [["Measure", "Result"],
            ["Correct answers (the SQL is run; its rows must equal the reference answer)",
             f"{a['passed']}/{a['total']} ({pct(a['accuracy'])}), 95% range {pct(lo)}-{pct(hi)}"],
            ["Correct on the first try / after a self-correction retry", f"{a['first_try']} / {a['after_retry']}"],
            ["Safety and behaviour (asks to clarify, declines, blocks deletes and injection, access control)",
             f"{b['passed']}/{b['total']}"]]
    if dept_total:
        rows.append(["Department access checks on the real database (6 roles, all tables, bypass attempts)",
                     f"{dept_pass}/{dept_total} passed, {dept_fail} failed"])
    if med:
        rows.append(["Time per question: median / 90th percentile",
                     f"{med / 1000:.1f} s / {summary['latency_ms']['p90'] / 1000:.1f} s"])
    tokens = summary["tokens_per_question"]
    if tokens["mean"]:
        rows.append(["Tokens per question (average) / whole run", f"{tokens['mean']:,} / {tokens['total']:,}"])
    rows.append(["Model calls per question (average)", str(summary["model_calls_per_question"])])
    if summary["errors_not_counted"]:
        rows.append(["Questions hit by API rate limits (not counted)", str(summary["errors_not_counted"])])
    table(rows, (120, 60))

    heading("Correct answers by category", 13, gap=5)
    cats = summary["by_category"]
    label_w, bar_w, row_h = 45, width - 45 - 22, 5.6
    pdf.set_font("Helvetica", "", 8.5)
    for cat, v in cats.items():
        if pdf.get_y() > pdf.h - 30:
            pdf.add_page()
        y = pdf.get_y()
        pdf.set_text_color(*INK)
        pdf.set_xy(15, y)
        pdf.cell(label_w, row_h, clean(cat.replace("_", " ")))
        share = v["passed"] / v["total"] if v["total"] else 0
        pdf.set_fill_color(236, 239, 242)
        pdf.rect(15 + label_w, y + 1, bar_w, row_h - 2, style="F")
        pdf.set_fill_color(*(GOOD if share == 1 else WARN if share > 0 else BAD))
        if share:
            pdf.rect(15 + label_w, y + 1, bar_w * share, row_h - 2, style="F")
        pdf.set_xy(15 + label_w + bar_w + 2, y)
        pdf.cell(20, row_h, f"{v['passed']}/{v['total']}")
        pdf.set_y(y + row_h)

    # ---- page 2: safety and access control
    pdf.add_page()
    heading("Safety and department access control", 15, gap=0)
    if check:
        c = check["counts"]
        para(f"Automated check run {check['finished']} on commit {check['commit']}: PASS {c['PASS']}, WARN {c['WARN']}, "
             f"FAIL {c['FAIL']}, SKIP {c['SKIP']}. The department section signs in as each role and runs real read-only "
             "queries: every allowed table must work, every other table and every hidden column (emails, salaries, "
             "prices for Operations) must be blocked, including bypass attempts such as aliases, subqueries, UNION, "
             "comments and SELECT *.", 9.5, MUTED)
        pdf.ln(2)
        rows = [["Section", "Pass", "Warn", "Fail", "Skip"]]
        rows += [[name, v["PASS"], v["WARN"], v["FAIL"], v["SKIP"]] for name, v in sections.items()]
        table(rows, (100, 20, 20, 20, 20))
        issues = [r for r in check["results"] if r["status"] in ("FAIL", "WARN")]
        if issues:
            heading("Warnings and failures in the safety check", 11, gap=4)
            table([["Status", "Check", "Detail"]] +
                  [[r["status"], clean(f"{r['section']}: {r['check']}", 70), clean(r["detail"], 150)] for r in issues],
                  (16, 70, 94), colour_col=0, size=8)
        if any(v["SKIP"] for v in sections.values()):
            para("SKIP rows are the live AI scenarios, which were not repeated here; the golden-set run measured the "
                 "live model instead.", 8.5, MUTED)
    else:
        para("The safety check report was not found, so this section is empty.", 10, BAD)

    para("", 6)
    heading("Access by department (what each role may read)", 12, gap=4)
    try:
        sys.path.insert(0, str(ROOT))
        from departments import ROLES, scope_text
        table([["Role", "Can ask about"]] + [[role, clean(scope_text(role), 220)] for role in ROLES], (28, 152), size=8.5)
    except Exception as exc:
        para(f"(Department summary unavailable: {type(exc).__name__})", 9, MUTED)

    # ---- usage page: app database (Postgres) and LangSmith
    if usage:
        pdf.add_page()
        heading("Real usage: app database and LangSmith", 15, gap=0)
        f, l = usage.get("feedback_store", {}), usage.get("langsmith", {})
        if "error" in f or not f:
            para(f"App database unavailable ({f.get('error', 'not run')}).", 10, BAD)
        else:
            s = f["summary"]
            share = lambda v: "n/a" if v is None else pct(v)
            para(f"Source: {f['backend']} feedback store. {f['tables']['query_events']:,} query events and "
                 f"{f['tables']['llm_calls']:,} logged model calls from {f['period']['first']} to {f['period']['last']}, "
                 f"{f['users']} demo accounts.", 9.5, MUTED)
            pdf.ln(2)
            table([["Measure", "Value"],
                   ["Questions asked", s.get("questions")],
                   ["Accepted on the first proposal", share(s.get("accepted_first_proposal"))],
                   ["Ended with a successful run", share(s.get("resolved_with_successful_run"))],
                   ["Rewrites per question (average)", s.get("avg_rewrites_per_question")],
                   ["Model calls per question (average)", s.get("avg_model_calls_per_question")],
                   ["Questions that hit the 3-rewrite limit", s.get("rewrite_limit_reached")],
                   ["Run failure rate", share(s.get("run_failure_rate"))],
                   ["Votes positive / negative", f"{s.get('votes_positive')} / {s.get('votes_negative')}"],
                   ["Questions by department", ", ".join(f"{k} {v}" for k, v in f["questions_by_role"].items()) or "-"],
                   ["Reasons given for negative votes", ", ".join(f"{k} {v}" for k, v in f["negative_vote_reasons"].items()) or "-"]],
                  (90, 90))
            if f.get("model_calls_by_node"):
                heading("Model calls by step (from the database log)", 11, gap=4)
                rows = [["Step", "Calls", "Errors", "Median latency", "p90 latency", "Avg tokens in / out"]]
                for node, n in f["model_calls_by_node"].items():
                    ms = lambda v: f"{v / 1000:.1f} s" if v else "n/a"
                    rows.append([node, n["calls"], n["errors"], ms(n["latency_median_ms"]), ms(n["latency_p90_ms"]),
                                 f"{n['avg_input_tokens'] or 0:,} / {n['avg_output_tokens'] or 0:,}"])
                table(rows, (40, 18, 18, 30, 30, 44), size=8.5)
        heading("LangSmith projects", 12, gap=5)
        if not l.get("available"):
            para(f"LangSmith unavailable ({l.get('reason')}).", 10, BAD)
        else:
            rows = [["Project", "Traces", "Runs", "Median / p99", "Tokens", "Errors", "Feedback (average)"]]
            for name, p in l["projects"].items():
                if not p.get("found"):
                    rows.append([name, "not found", "", "", "", "", ""])
                    continue
                lat = f"{p['latency_p50_s']} s / {p['latency_p99_s']} s" if p.get("latency_p50_s") is not None else "n/a"
                fb = ", ".join(f"{k} {v['avg']} (n={v['n']})" for k, v in p["feedback"].items()) or "none"
                err = pct(p["error_rate"]) if p.get("error_rate") is not None else "n/a"
                tokens = f"{p['total_tokens']:,}" if p.get("total_tokens") is not None else "n/a"
                rows.append([name, p.get("traces") if p.get("traces") is not None else "n/a", p.get("runs"), lat, tokens, err, fb])
            table(rows, (36, 15, 14, 27, 20, 14, 54), size=8)
            para("Traces: one per question or user turn. Runs: every step inside a trace (each model call, each graph "
                 "node). 'correct' is the golden-set score; user votes are what people clicked, not correctness.", 8.5, MUTED)

    # ---- page 3+: per question
    pdf.add_page()
    heading("Every question in this run", 15, gap=0)
    para("Result PASS means the produced SQL returned exactly the reference rows (answerable questions) or the right "
         "kind of response (safety questions). ERROR means an API rate limit hit; those are not counted.", 9, MUTED)
    pdf.ln(2)
    rows = [["ID", "Category", "Question", "Result", "Tries", "Time", "Tokens"]]
    for r in records:
        rows.append([r["id"], r["category"].replace("_", " "), clean(r["question"], 80), r["outcome"],
                     r["attempts"], f"{r['ms'] / 1000:.1f}s", f"{r['tokens']['total']:,}"])
    table(rows, (11, 28, 80, 16, 12, 14, 19), colour_col=3, size=8)

    wrong = [r for r in records if r["outcome"] == "FAIL"]
    if pdf.get_y() > pdf.h - 60:
        pdf.add_page()
    heading("Questions it got wrong", 13, gap=6)
    if not wrong:
        para("None.", 10)
    for r in wrong:
        if pdf.get_y() > pdf.h - 50:
            pdf.add_page()
        para(f"{r['id']} ({r['category'].replace('_', ' ')}): {r['question']}", 10, INK, "B")
        para(f"Why it failed: {r['reason']}", 9, BAD)
        if r.get("predicted_sql"):
            pdf.set_font("Courier", "", 7.5)
            pdf.set_text_color(*INK)
            pdf.set_fill_color(246, 247, 249)
            pdf.multi_cell(0, 3.8, clean(r["predicted_sql"], 900), fill=True, align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    # ---- method
    if pdf.get_y() > pdf.h - 90:
        pdf.add_page()
    heading("How this was measured", 13, gap=6)
    for line in [
        f"Golden set: {summary['run'].get('questions_planned', len(records))} questions chosen to cover every category "
        "(joins, dates, missing values, business definitions, ties, window functions, follow-ups, Hinglish, "
        "self-correction) plus safety cases. Each has a reference SQL query checked against the database.",
        "The real app ran each question: the same Groq model, prompts, business-rule retrieval and SQL safety checker "
        "as production. Generated SQL was checked by the safety checker, run read-only, and its rows compared with "
        "the reference rows (order ignored unless the question asks for an order).",
        "Every question is one trace in LangSmith with a 'correct' score (1 or 0), so each answer can be opened and audited.",
        f"Honest limits: {a['total']} answerable questions is a small sample, so the 95% range is the real error bar. "
        "The model's output varies between runs. The data is synthetic; 'today' in the data is fixed at 2026-06-30.",
    ]:
        para("- " + line, 9.5)
        pdf.ln(1)

    status = "Meets the publishing bar." if good else "Does NOT meet the publishing bar: " + "; ".join(reasons)
    para("", 4)
    para(f"Report generated {datetime.now():%Y-%m-%d %H:%M}. {status}", 8.5, GOOD if good else BAD)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="presentation")
    ap.add_argument("--publish", action="store_true", help="copy the PDF to golden_eval/results/ if results are good")
    ap.add_argument("--min-accuracy", type=float, default=0.70)
    args = ap.parse_args()
    try:
        import fpdf  # noqa: F401
    except ImportError:
        print("The fpdf2 package is missing. Install it with: .\\venv\\Scripts\\python.exe -m pip install fpdf2")
        return 1

    summary, records, check, usage = load_inputs(args.name)
    good, reasons = judge(summary, check, args.min_accuracy)
    stamp = datetime.now().strftime("%Y-%m-%d")
    preview = ROOT / "eval_runs" / f"ColdChain_evaluation_{stamp}.pdf"
    build_pdf(summary, records, check, good, reasons, preview, usage)
    print(f"Preview PDF: {preview.relative_to(ROOT)}")
    if not good:
        print("NOT GOOD - not published:")
        for reason in reasons:
            print(f"  - {reason}")
        return 3
    print("GOOD - results meet the publishing bar.")
    if args.publish:
        target = ROOT / "golden_eval" / "results" / preview.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(preview, target)
        print(f"Published: {target.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
