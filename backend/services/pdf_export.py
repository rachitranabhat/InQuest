"""PDF export of a saved report version (ReportLab).

The PDF is rendered only from stored data — the report version's claims, the
case record, the evidence items it cites and the audit log — so an export can
always be traced back to exactly one report version and evidence hash.
"""
from __future__ import annotations

import hashlib
import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import config
from database.db import connect, next_id, tx
from services import repo
from services.reports import case_actions, get as get_report
from timeutil import utc_now_iso

INK = colors.HexColor("#0B1220")
MUTED = colors.HexColor("#4A5568")
RULE = colors.HexColor("#CBD5E1")
ACCENT = colors.HexColor("#0E5A8A")


def _styles():
    ss = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=ss["Normal"], fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=INK,
                          alignment=TA_LEFT)
    return {
        "base": base,
        "small": ParagraphStyle("small", parent=base, fontSize=8, leading=11, textColor=MUTED),
        "h1": ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=17, leading=21, spaceAfter=4),
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=11.5, leading=15, spaceBefore=10,
                             spaceAfter=4, textColor=ACCENT),
        "mono": ParagraphStyle("mono", parent=base, fontName="Courier", fontSize=8, leading=10.5),
        "claim": ParagraphStyle("claim", parent=base, leftIndent=8, spaceAfter=3),
    }


def render(report_id: str, reviewer_id: str | None = None) -> tuple[bytes, dict]:
    with connect() as con:
        rep = get_report(con, report_id)
        case = repo.case_row(con, rep["case_id"])
        items = {i["evidence_id"]: i for i in repo.evidence_items(con, rep["case_id"])}
        acts = [a for a in case_actions(con, rep["case_id"])]
    b = config.branding()
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=f"{case['case_id']} investigation report v{rep['version']}",
                            author=b.get("product_name", "INQUEST"))
    now = utc_now_iso()
    flow = [Paragraph(escape(f"{b.get('product_name', 'INQUEST')} · Investigation report"), st["small"]),
            Paragraph(escape(f"{case['case_id']} — {case['alert']['alert_type']}"), st["h1"]),
            Paragraph(escape("SYNTHETIC DATA · RESEARCH PROTOTYPE · " + b.get("disclaimer", "")), st["small"]),
            Spacer(1, 6)]
    meta = [
        ["Case", case["case_id"], "Report version", f"{rep['version']} ({rep['report_id']})"],
        ["Subject", f"{case['subject_id']} ({case['subject_type']})", "Report mode", rep["mode_label"]],
        ["Alert", f"{case['alert_id']} · {case['alert']['source']}", "Report created", rep["created_at_utc"]],
        ["Alert score", f"{case['alert_score']:.1f} / 100 (prototype, not a probability)", "Exported", now],
        ["Review priority", case["priority"], "Report status", rep["status"]],
        ["Case status", case["status"], "Evidence hash", rep["evidence_hash"][:16] + "…"],
    ]
    t = Table([[Paragraph(escape(str(c)), st["small"] if i % 2 == 0 else st["base"]) for i, c in enumerate(row)]
               for row in meta], colWidths=[24 * mm, 62 * mm, 26 * mm, 62 * mm])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    flow += [t, Spacer(1, 4)]
    v = rep["validation"]
    flow.append(Paragraph(escape(f"Claim verification: {v.get('verified', 0)} of {v.get('claims', 0)} claims verified "
                                 "against cited evidence. Unverified claims are listed separately and are not findings."),
                          st["small"]))
    if rep.get("notes"):
        flow.append(Paragraph(escape(rep["notes"]), st["small"]))
    cited = set()
    unverified = []
    for sec in rep["sections"]:
        flow.append(Paragraph(escape(sec["label"]), st["h2"]))
        for c in sec["claims"]:
            if c["verification_status"] != "verified":
                unverified.append((sec["label"], c))
                continue
            refs = ", ".join(c["evidence_ids"])
            cited |= set(c["evidence_ids"])
            tag = {"interpretation": "Interpretation: ", "recommendation": "Check: ", "limitation": "Limitation: "}.get(c["kind"], "")
            flow.append(Paragraph(f"• {escape(tag + c['text'])} <font color='#4A5568' size='7.5'>[{escape(refs)}]</font>"
                                  if refs else f"• {escape(tag + c['text'])}", st["claim"]))
    if unverified:
        flow.append(Paragraph("Unverified statements (excluded from findings)", st["h2"]))
        for label, c in unverified:
            flow.append(Paragraph(escape(f"[{label}] {c['text']} — failed: {'; '.join(c['failures'])}"), st["small"]))
    tx_rows = [items[e] for e in sorted(cited) if e in items and items[e]["type"] == "transaction"]
    if tx_rows:
        flow.append(Paragraph("Cited transaction records", st["h2"]))
        data = [["Evidence", "Transaction", "Local time", "Type", "Amount", "Retailer / account"]]
        for it in tx_rows[:60]:
            x = it["computed"]
            data.append([it["evidence_id"], it["source_ids"][0], x["timestamp_local"], x["transaction_type"],
                         f"${x['amount']:,.2f}", x.get("retailer_name") and f"{x['retailer_name']} ({x['city']})"
                         or x.get("account_id", "")])
        tt = Table([[Paragraph(escape(str(c)), st["mono"]) for c in r] for r in data],
                   colWidths=[20 * mm, 22 * mm, 27 * mm, 25 * mm, 18 * mm, 62 * mm], repeatRows=1)
        tt.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.3, RULE), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2F7"))]))
        flow.append(tt)
    flow.append(Paragraph("Evidence index", st["h2"]))
    for e in sorted(cited):
        if e in items and items[e]["type"] != "transaction":
            flow.append(Paragraph(f"<b>{escape(e)}</b> · {escape(items[e]['type'])} · {escape(items[e]['title'])}", st["small"]))
    flow.append(Paragraph("Reviewer actions and notes", st["h2"]))
    human = [a for a in acts if a["reviewer_id"] != "SYSTEM"]
    if not human:
        flow.append(Paragraph("No reviewer action recorded at export time. Final disposition: pending.", st["base"]))
    for a in human:
        flow.append(KeepTogether([Paragraph(escape(
            f"{a['created_at_utc']} · {a['reviewer_name']} ({a['session_kind']} session) · "
            f"{config.ACTION_LABELS.get(a['action'], a['action'])} · {a['from_status']} → {a['to_status']} · "
            f"viewed report v{a['report_version'] or '–'}"), st["small"]),
            Paragraph(escape(a["notes"] or "(no notes)"), st["claim"])]))
    final = case["status"] if case["status"] in (config.STATUS_CLOSED, config.STATUS_ESCALATED, config.STATUS_SUBSTANTIATED) \
        else "Pending (case still open)"
    from services.dispositions import history as disposition_history
    cur = disposition_history(case["case_id"])["current"]
    if cur:
        state = {"pending_senior": "awaiting senior confirmation", "confirmed": "confirmed by a senior investigator",
                 "returned": "returned by a senior investigator", "superseded": "superseded"}.get(cur["current_approval"], "recorded")
        final += f" · Investigation decision: {cur['label']} ({state}; {cur['reviewer_name']}, {cur['created_at_utc']})"
    flow += [Spacer(1, 6), Paragraph(escape(f"Final disposition: {final}"), st["base"]),
             Paragraph(escape(config.DISPOSITION_NOTICE), st["small"]), Spacer(1, 8),
             Paragraph(escape(config.DISCLAIMER), st["base"]),
             Paragraph(escape(config.PROJECT_NOTICE), st["small"])]

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 10 * mm, f"{case['case_id']} · report v{rep['version']} · synthetic prototype data")
        canvas.drawRightString(LETTER[0] - 18 * mm, 10 * mm, f"Page {d.page}")
        canvas.restoreState()

    doc.build(flow, onFirstPage=footer, onLaterPages=footer)
    pdf = buf.getvalue()
    digest = hashlib.sha256(pdf).hexdigest()
    fname = f"{case['case_id']}_report_v{rep['version']}.pdf"
    with connect() as con, tx(con):
        eid = next_id(con, "EXP")
        con.execute("INSERT INTO report_exports VALUES (?,?,?,?,?,?,?)",
                    (eid, report_id, "pdf", digest, fname, reviewer_id, now))
    config.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    (config.EXPORT_DIR / f"{eid}_{fname}").write_bytes(pdf)
    return pdf, {"export_id": eid, "file_name": fname, "sha256": digest}
