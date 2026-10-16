"""Human review workflow: state transitions, audit records, simulated sessions.

Every action is one transaction that (1) checks the transition is allowed from
the current status, (2) checks the caller's expected status (stale-UI guard),
(3) de-duplicates on the idempotency key, (4) writes an append-only audit row
with the report version and evidence hash the reviewer was looking at, and
(5) updates the case status. The AI never calls this.
"""
from __future__ import annotations

import secrets

import config
from database.db import connect, next_id, tx
from services import repo
from services.reports import lock as lock_report
from timeutil import utc_now_iso

DECISIONS = {"request_info", "close_no_action", "escalate"}


class WorkflowError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# ------------------------------------------------------------ simulated session
def create_session(reviewer_id: str) -> dict:
    with connect() as con:
        rv = repo.reviewer(con, reviewer_id)
        if reviewer_id == "SYSTEM":
            raise WorkflowError("The system account cannot sign in", 403)
        token = secrets.token_urlsafe(24)
        with tx(con):
            con.execute("INSERT INTO sessions VALUES (?,?,?,?)", (token, reviewer_id, "simulated", utc_now_iso()))
        return {"token": token, "reviewer": rv, "kind": "simulated",
                "notice": "Simulated reviewer session for the prototype — this is not authentication."}


def session_reviewer(token: str | None) -> dict | None:
    if not token:
        return None
    with connect() as con:
        r = con.execute("""SELECT r.*, s.kind FROM sessions s JOIN reviewers r ON r.reviewer_id = s.reviewer_id
                           WHERE s.token = ?""", (token,)).fetchone()
        return dict(r) if r else None


def reviewers() -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM reviewers WHERE reviewer_id != 'SYSTEM' ORDER BY reviewer_id")]


# ------------------------------------------------------------------- actions
def report_context(con, case_id: str, report_id: str | None):
    """The report version on screen (or the latest) plus the evidence version and fingerprint it was built from."""
    if report_id:
        rep = con.execute("SELECT report_id, version, snapshot_id, evidence_hash, case_id FROM reports "
                          "WHERE report_id = ?", (report_id,)).fetchone()
        if rep is None or rep["case_id"] != case_id:
            raise WorkflowError("That report version does not belong to this case.", 422)
    else:
        rep = con.execute("SELECT report_id, version, snapshot_id, evidence_hash, case_id FROM reports "
                          "WHERE case_id = ? ORDER BY version DESC LIMIT 1", (case_id,)).fetchone()
    snap = rep["snapshot_id"] if rep else con.execute(
        "SELECT current_snapshot_id FROM cases WHERE case_id = ?", (case_id,)).fetchone()[0]
    h = rep["evidence_hash"] if rep else con.execute(
        "SELECT evidence_hash FROM evidence_snapshots WHERE snapshot_id = ?", (snap,)).fetchone()[0]
    return rep, snap, h



def allowed_actions(status: str) -> list[str]:
    return [a for a, m in config.TRANSITIONS.items() if status in m]


def perform(case_id: str, action: str, reviewer: dict, *, notes: str | None, idempotency_key: str,
            expected_status: str | None = None, report_id: str | None = None) -> dict:
    if action not in config.TRANSITIONS:
        raise WorkflowError(f"Unknown action '{action}'")
    notes = (notes or "").strip()
    if action in config.NOTES_REQUIRED and len(notes) < config.MIN_NOTE_CHARS:
        raise WorkflowError(f"Notes of at least {config.MIN_NOTE_CHARS} characters are required for this action.", 422)
    if len(notes) > config.MAX_NOTE_CHARS:
        raise WorkflowError(f"Notes are limited to {config.MAX_NOTE_CHARS} characters.", 422)
    if not idempotency_key or len(idempotency_key) > 100:
        raise WorkflowError("A valid idempotency key is required.", 422)
    with connect() as con:
        with tx(con):
            dup = con.execute("SELECT * FROM case_actions WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if dup:
                if dup["case_id"] != case_id or dup["action"] != action:
                    raise WorkflowError("This idempotency key was already used for a different action.", 409)
                return {**dict(dup), "duplicate": True}
            row = con.execute("SELECT status FROM cases WHERE case_id = ?", (case_id,)).fetchone()
            if row is None:
                raise WorkflowError(f"Case {case_id} not found", 404)
            current = row[0]
            if expected_status and expected_status != current:
                raise WorkflowError(f"The case is now '{current}', not '{expected_status}'. Reload and try again.", 409)
            if current not in config.TRANSITIONS[action]:
                raise WorkflowError(f"'{config.ACTION_LABELS[action]}' is not allowed while the case is '{current}'. "
                                    f"Allowed: {', '.join(config.ACTION_LABELS[a] for a in allowed_actions(current))}.", 409)
            target = config.TRANSITIONS[action][current] or current
            if action == "reopen" and current == config.STATUS_SUBSTANTIATED and reviewer.get("role") not in config.SENIOR_ROLES:
                raise WorkflowError("Only a senior investigator can reopen a confirmed substantiated finding.", 403)
            rep, snap, h = report_context(con, case_id, report_id)
            if action in DECISIONS and rep is None:
                raise WorkflowError("Generate and read an investigation report before recording a decision.", 409)
            now = utc_now_iso()
            aid = next_id(con, "ACT")
            con.execute("INSERT INTO case_actions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (aid, case_id, action, current, target, reviewer["reviewer_id"], reviewer.get("kind", "simulated"),
                         notes or None, rep["report_id"] if rep else None, rep["version"] if rep else None, snap, h,
                         idempotency_key, now))
            assign = ", assigned_reviewer_id = ?" if action == "start_review" else ""
            params = [target, now] + ([reviewer["reviewer_id"]] if assign else []) + [case_id]
            con.execute(f"UPDATE cases SET status = ?, updated_at_utc = ?{assign} WHERE case_id = ?", params)
            if rep and action != "add_note":
                lock_report(con, rep["report_id"])
            out = dict(con.execute("SELECT * FROM case_actions WHERE action_id = ?", (aid,)).fetchone())
        out["duplicate"] = False
        out["reviewer_name"] = reviewer["display_name"]
        return out
