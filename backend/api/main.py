"""PRISM FastAPI application.

Run (from the repository root):
    python -m uvicorn api.main:app --app-dir backend --port 8100

All endpoints are under /api. Case-scoped endpoints validate the case ID format
and existence; reviewer actions require a (simulated) reviewer session token in
the X-Reviewer-Session header. If frontend/dist exists it is served at "/".
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import Depends, FastAPI, Header, HTTPException, Path as P, Query, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

import config  # noqa: E402
import pipeline  # noqa: E402
from ai import llm_client  # noqa: E402
from database.db import connect, schema_version  # noqa: E402
from schemas import api as S  # noqa: E402
from services import access  # noqa: E402
from services import (agents, cases, copilot, data_admin, dispositions, findings, graph, guide, methodology, pdf_export, reports, repo, restricted,  # noqa: E402
                      scenarios, workflow, workspace)


@asynccontextmanager
async def lifespan(_app):
    pipeline.ensure_built()          # builds only if the database is empty; never resets
    with connect() as con:           # additive: fictional identity rows for registered synthetic players
        restricted.ensure_identities(con)
    from services import investigation_store
    investigation_store.mark_interrupted()   # runs cut off by a previous shutdown are recorded as failed
    yield


app = FastAPI(title="INQUEST investigation API", version="1.0.0", lifespan=lifespan,
              description="Prototype API over synthetic data. Not affiliated with OLG.")
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=False,
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Reviewer-Session"])


@app.exception_handler(repo.NotFound)
async def _nf(_r: Request, e: repo.NotFound):
    return JSONResponse(status_code=404, content={"detail": str(e)})


@app.exception_handler(workflow.WorkflowError)
async def _wf(_r: Request, e: workflow.WorkflowError):
    return JSONResponse(status_code=e.status_code, content={"detail": str(e)})


@app.exception_handler(ValueError)
async def _ve(_r: Request, e: ValueError):
    return JSONResponse(status_code=422, content={"detail": str(e)})


CaseId = P(..., pattern=S.CASE_ID)
ReportId = P(..., pattern=S.REPORT_ID)
EvidenceId = P(..., pattern=S.EVIDENCE_ID)


def reviewer_session(x_reviewer_session: str | None = Header(default=None)) -> dict:
    rv = workflow.session_reviewer(x_reviewer_session)
    if rv is None:
        raise HTTPException(401, "A simulated reviewer session is required. Choose a reviewer first.")
    return rv


def optional_reviewer(x_reviewer_session: str | None = Header(default=None)) -> dict | None:
    return workflow.session_reviewer(x_reviewer_session)


# ------------------------------------------------------------------ meta
@app.get("/api/health")
def health():
    return {"ok": True, "schema_version": schema_version(), "dataset": pipeline.status()}


@app.get("/api/config")
def app_config():
    return {"branding": config.branding(), "llm_available": llm_client.llm_available(),
            "llm_model": llm_client.model_name() if llm_client.llm_available() else None,
            "statuses": config.ALL_STATUSES, "open_statuses": config.OPEN_STATUSES,
            "action_labels": config.ACTION_LABELS, "notes_required": sorted(config.NOTES_REQUIRED),
            "min_note_chars": config.MIN_NOTE_CHARS, "disclaimer": config.DISCLAIMER,
            "project_notice": config.PROJECT_NOTICE, "suggested_questions": copilot.SUGGESTED,
            "auth": "simulated reviewer sessions (not production authentication)",
            "access_code_required": bool(access.access_code()),
            "senior_roles": sorted(restricted.SENIOR_ROLES), "guide_suggested_questions": guide.SUGGESTED,
            "dispositions": dispositions.options(),
            "terms": {k: {"technical": v[0], "definition": v[1]} for k, v in config.TERMS.items()},
            "factor_labels": config.PLAIN_FACTOR_LABELS}


@app.get("/api/reviewers", response_model=list[S.Reviewer])
def list_reviewers():
    return workflow.reviewers()


@app.post("/api/session", response_model=S.SessionOut)
def start_session(body: S.SessionRequest):
    access.check_code(body.access_code)
    return workflow.create_session(body.reviewer_id)


@app.get("/api/session")
def whoami(rv: dict | None = Depends(optional_reviewer)):
    return {"reviewer": rv}


# ------------------------------------------------------------------ cases
@app.get("/api/cases", response_model=S.CaseList)
def get_cases(q: str | None = Query(None, max_length=80), status: str | None = Query(None, max_length=300),
              priority: str | None = Query(None, max_length=300), alert_type: str | None = Query(None, max_length=300),
              channel: str | None = Query(None, pattern=r"^(lottery_terminal|online_account)$"),
              reviewer: str | None = Query(None, pattern=r"^(REV-\d{2}|unassigned)$"),
              date_from: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}"),
              date_to: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}"),
              completeness: str | None = Query(None, pattern=r"^(Complete|Partial|Limited)(,(Complete|Partial|Limited))*$"),
              sort: str = Query("priority", pattern=r"^(priority|score|newest|updated)$")):
    return cases.list_cases(q, status, priority, alert_type, channel, reviewer, date_from, date_to, sort=sort,
                            completeness=completeness)


@app.get("/api/cases/{case_id}")
def get_case(case_id: str = CaseId):
    return cases.detail(case_id)


@app.get("/api/cases/{case_id}/evidence", response_model=list[S.EvidenceItem])
def get_evidence(case_id: str = CaseId, type: str | None = Query(None, pattern=r"^[a-z_]+$")):  # noqa: A002
    return cases.evidence_list(case_id, type)


@app.get("/api/cases/{case_id}/evidence/{evidence_id}", response_model=S.EvidenceItem)
def get_evidence_item(case_id: str = CaseId, evidence_id: str = EvidenceId):
    with connect() as con:
        return repo.evidence_item(con, case_id, evidence_id)


@app.get("/api/cases/{case_id}/findings")
def case_findings(case_id: str = CaseId):
    """Plain-language findings (three levels) derived from the case's stored evidence."""
    return findings.for_case(case_id)


@app.get("/api/cases/{case_id}/history")
def case_history(case_id: str = CaseId):
    """Previous vs. recent activity on normalized measures, with reliability notes and evidence IDs."""
    return workspace.history(case_id)


@app.get("/api/cases/{case_id}/completeness")
def case_completeness(case_id: str = CaseId):
    """What the evidence version has, lacks or leaves ambiguous, item by item."""
    return workspace.completeness(case_id)


@app.get("/api/cases/{case_id}/bookmarks")
def get_bookmarks(case_id: str = CaseId):
    return workspace.bookmarks(case_id)


@app.post("/api/cases/{case_id}/bookmarks")
def add_bookmark(body: S.BookmarkRequest, case_id: str = CaseId, rv: dict = Depends(reviewer_session)):
    return workspace.save_bookmark(case_id, body.evidence_id, rv, body.note, body.label)


@app.post("/api/cases/{case_id}/bookmarks/{bookmark_id}/note")
def edit_bookmark_note(body: S.BookmarkNoteRequest, case_id: str = CaseId,
                       bookmark_id: str = P(..., pattern=S.BOOKMARK_ID), rv: dict = Depends(reviewer_session)):
    return workspace.update_note(case_id, bookmark_id, body.note)


@app.post("/api/cases/{case_id}/bookmarks/{bookmark_id}/remove")
def delete_bookmark(case_id: str = CaseId, bookmark_id: str = P(..., pattern=S.BOOKMARK_ID),
                    rv: dict = Depends(reviewer_session)):
    return workspace.remove_bookmark(case_id, bookmark_id)


@app.get("/api/cases/{case_id}/timeline")
def get_timeline(case_id: str = CaseId):
    return cases.timeline(case_id)


@app.get("/api/cases/{case_id}/graph")
def get_graph(case_id: str = CaseId):
    return graph.build(case_id)


@app.get("/api/cases/{case_id}/audit")
def get_case_audit(case_id: str = CaseId):
    return cases.case_audit(case_id)


# ---------------------------------------------------------------- reports
@app.get("/api/cases/{case_id}/reports")
def get_reports(case_id: str = CaseId):
    with connect() as con:
        repo.case_row(con, case_id)
        return reports.list_for_case(con, case_id)


@app.post("/api/cases/{case_id}/reports", response_model=S.Report)
def create_report(body: S.ReportRequest, case_id: str = CaseId, rv: dict | None = Depends(optional_reviewer)):
    access.writes(rv)
    access.live_ai(body.mode, rv)
    return reports.generate(case_id, body.mode, rv["reviewer_id"] if rv else "SYSTEM")


@app.get("/api/reports/{report_id}", response_model=S.Report)
def get_report(report_id: str = ReportId):
    with connect() as con:
        return reports.get(con, report_id)


@app.get("/api/reports/{report_id}/pdf")
def export_pdf(report_id: str = ReportId, rv: dict | None = Depends(optional_reviewer)):
    pdf, meta = pdf_export.render(report_id, rv["reviewer_id"] if rv else None)
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{meta["file_name"]}"',
        "X-Export-Id": meta["export_id"], "X-Content-SHA256": meta["sha256"],
        "Access-Control-Expose-Headers": "Content-Disposition, X-Export-Id, X-Content-SHA256"})


# ------------------------------------------------------------------ copilot
@app.get("/api/cases/{case_id}/chat")
def chat_history(case_id: str = CaseId):
    with connect() as con:
        repo.case_row(con, case_id)
        return copilot.history(con, case_id)


@app.post("/api/cases/{case_id}/chat", response_model=S.ChatAnswer)
def chat(body: S.ChatRequest, case_id: str = CaseId, rv: dict | None = Depends(optional_reviewer)):
    access.writes(rv)
    access.live_ai(body.mode, rv)
    return copilot.ask(case_id, body.question, body.mode, rv["reviewer_id"] if rv else "SYSTEM")


# ------------------------------------------- multi-agent investigation (persisted; runs in the background)
@app.post("/api/cases/{case_id}/investigations", status_code=202)
def start_investigation(body: S.InvestigationRequest, case_id: str = CaseId, rv: dict = Depends(reviewer_session)):
    """Starts a run and returns its 'running' record; poll GET /api/investigations/{id}. Read-only for the case."""
    access.live_ai(body.mode, rv)
    return agents.start(case_id, body.mode, rv)


@app.get("/api/cases/{case_id}/investigations")
def list_investigations(case_id: str = CaseId, rv: dict = Depends(reviewer_session)):
    return agents.history(case_id)


@app.get("/api/investigations/{investigation_id}")
def get_investigation(investigation_id: str = P(..., pattern=S.INVESTIGATION_ID), rv: dict = Depends(reviewer_session)):
    return agents.get(investigation_id)


# ------------------------------------------------------------------ review
@app.post("/api/cases/{case_id}/actions", response_model=S.ActionOut)
def act(body: S.ActionRequest, case_id: str = CaseId, rv: dict = Depends(reviewer_session)):
    return workflow.perform(case_id, body.action, rv, notes=body.notes, idempotency_key=body.idempotency_key,
                            expected_status=body.expected_status, report_id=body.report_id)


# ------------------------------------------------- final investigation dispositions (human only)
@app.get("/api/cases/{case_id}/dispositions")
def case_dispositions(case_id: str = CaseId):
    return dispositions.history(case_id)


@app.post("/api/cases/{case_id}/dispositions")
def record_disposition(body: S.DispositionRequest, case_id: str = CaseId, rv: dict = Depends(reviewer_session)):
    return dispositions.record(case_id, rv, disposition=body.disposition, concern_type=body.concern_type,
                               justification=body.justification, evidence_ids=body.evidence_ids,
                               idempotency_key=body.idempotency_key, expected_status=body.expected_status,
                               report_id=body.report_id)


@app.post("/api/cases/{case_id}/dispositions/{disposition_id}/review")
def review_disposition(body: S.DispositionReviewRequest, case_id: str = CaseId,
                       disposition_id: str = P(..., pattern=S.DISPOSITION_ID), rv: dict = Depends(reviewer_session)):
    return dispositions.review(case_id, disposition_id, rv, decision=body.decision, notes=body.notes,
                               idempotency_key=body.idempotency_key, expected_status=body.expected_status)


@app.get("/api/audit")
def audit(limit: int = Query(200, ge=1, le=1000)):
    return cases.audit(limit)


@app.get("/api/analytics")
def analytics():
    return cases.analytics()


# ------------------------------------------------------------------ scenarios
@app.get("/api/scenarios")
def list_scenarios():
    return scenarios.catalogue()


@app.post("/api/scenarios/{key}/run")
def run_scenario(key: str = P(..., pattern=r"^[a-z_]{3,40}$"), rv: dict = Depends(reviewer_session)):
    return scenarios.run(key, rv["reviewer_id"])


# ------------------------------------------- dashboard help (no case or identity access)
@app.post("/api/guide")
def dashboard_guide(body: S.GuideRequest):
    return guide.answer(body.question)


# ------------------------------------------- senior-only: data management and restricted records
# Role checks run on the server for every request (services/restricted.require_senior). The session is a
# simulated reviewer session, so this is a role-based demo, not production authorization.
NO_STORE = {"Cache-Control": "no-store"}


@app.get("/api/admin/summary")
def admin_summary(rv: dict | None = Depends(optional_reviewer)):
    return data_admin.summary(rv)


@app.get("/api/admin/tables/{table}")
def admin_browse(table: str = P(..., pattern=r"^[a-z]{3,20}$"), q: str | None = Query(None, max_length=60),
                 status: str | None = Query(None, max_length=40), priority: str | None = Query(None, max_length=40),
                 channel: str | None = Query(None, pattern=r"^(lottery_terminal|online_account)$"),
                 city: str | None = Query(None, max_length=60), source: str | None = Query(None, max_length=40),
                 attribution: str | None = Query(None, max_length=40), action: str | None = Query(None, max_length=40),
                 limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0, le=1_000_000),
                 rv: dict | None = Depends(optional_reviewer)):
    given = {"status": status, "priority": priority, "channel": channel, "city": city, "source": source,
             "attribution": attribution, "action": action}
    return data_admin.browse(rv, table, q, {k: v for k, v in given.items() if v}, limit, offset)


# ------------------------------------------- Data & Methodology (overview: any reviewer; labels/evaluation: senior)
@app.get("/api/methodology")
def methodology_overview(rv: dict | None = Depends(optional_reviewer)):
    return methodology.overview(rv)


@app.get("/api/methodology/labels")
def methodology_labels(category: str | None = Query(None, pattern=r"^[a-z_]{2,40}$"),
                       planted: int | None = Query(None, ge=0, le=1),
                       profile: str | None = Query(None, pattern=r"^[a-z_]{2,40}$"),
                       q: str | None = Query(None, max_length=20, pattern=r"^[A-Za-z0-9\-]*$"),
                       limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                       rv: dict | None = Depends(optional_reviewer)):
    return methodology.labels(rv, category=category, planted=planted, profile=profile, q=q, limit=limit, offset=offset)


@app.get("/api/methodology/evaluation")
def methodology_evaluation(rv: dict | None = Depends(optional_reviewer)):
    return methodology.evaluation(rv)


@app.get("/api/restricted/records")
def restricted_records(q: str | None = Query(None, max_length=40, pattern=r"^[A-Za-z0-9\-]*$"),
                       limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                       rv: dict | None = Depends(optional_reviewer)):
    return JSONResponse(restricted.list_records(rv, q, limit, offset), headers=NO_STORE)


@app.post("/api/restricted/players/{player_id}/reveal")
def restricted_reveal(body: S.RevealRequest, player_id: str = P(..., pattern=S.PLAYER_ID),
                      rv: dict | None = Depends(optional_reviewer)):
    return JSONResponse(restricted.reveal(rv, player_id, body.reason, body.case_id), headers=NO_STORE)


@app.get("/api/restricted/access-log")
def restricted_log(player_id: str | None = Query(None, pattern=S.PLAYER_ID), limit: int = Query(100, ge=1, le=500),
                   rv: dict | None = Depends(optional_reviewer)):
    return JSONResponse(restricted.access_log(rv, player_id, limit), headers=NO_STORE)


# ------------------------------------------------------- built frontend (optional)
DIST = config.REPO_ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "Not found")
        f = DIST / full_path
        if full_path and f.is_file() and DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
