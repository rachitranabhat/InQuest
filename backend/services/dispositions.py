"""Final investigation dispositions: the reviewer's documented conclusion on a case.

* Only a human reviewer session can record one (the API requires a session; the SYSTEM account cannot sign
  in, and the copilot and report writer have no route to this module).
* A review must be in progress (Under Review or Information Requested) and a report must exist, as for the
  existing decisions. Each entry records the report version, evidence version and evidence fingerprint.
* A justification and at least one cited evidence item from the same case and evidence version are required.
* "Substantiated" recorded by a regular reviewer is a recommendation: the case stays open until a senior
  investigator confirms it (or returns it). A senior's own substantiated decision is confirmed directly.
  Roles come from the simulated reviewer session — a role-based demo, not production authorization.
* Every entry is append-only and is also written to case_actions in the same transaction, so the existing
  audit trail stays the single history of status changes.
"""
from __future__ import annotations

import config
from database.db import connect, dumps, loads, next_id, tx
from services.reports import lock as lock_report
from services.workflow import WorkflowError, report_context
from timeutil import utc_now_iso


def _senior(rv: dict) -> bool:
    return rv.get("role") in config.SENIOR_ROLES


def _check_reviewer(rv: dict | None) -> dict:
    if rv is None:
        raise WorkflowError("A simulated reviewer session is required. Choose a reviewer first.", 401)
    if rv.get("reviewer_id") == "SYSTEM":
        raise WorkflowError("Dispositions are recorded by a human reviewer only.", 403)
    return rv


def _dedupe(con, key: str, case_id: str, action: str):
    if not key or len(key) > 100:
        raise WorkflowError("A valid idempotency key is required.", 422)
    dup = con.execute("SELECT * FROM case_actions WHERE idempotency_key = ?", (key,)).fetchone()
    if dup is None:
        return None
    if dup["case_id"] != case_id or dup["action"] != action:
        raise WorkflowError("This idempotency key was already used for a different action.", 409)
    row = con.execute("SELECT * FROM case_dispositions WHERE action_id = ?", (dup["action_id"],)).fetchone()
    return {**_row(row), "duplicate": True}


def _row(r) -> dict:
    d = dict(r)
    d["evidence_ids"] = loads(d["evidence_ids"], [])
    d["label"] = config.disposition_label(d["disposition"], d["concern_type"])
    return d


def _status(con, case_id: str, expected: str | None) -> str:
    row = con.execute("SELECT status FROM cases WHERE case_id = ?", (case_id,)).fetchone()
    if row is None:
        raise WorkflowError(f"Case {case_id} not found", 404)
    if expected and expected != row[0]:
        raise WorkflowError(f"The case is now '{row[0]}', not '{expected}'. Reload and try again.", 409)
    return row[0]


def _write(con, *, case_id, rv, action, entry_type, parent_id, disposition, concern, justification, evidence_ids,
           rep, snap, h, approval, current, target, key) -> str:
    now = utc_now_iso()
    aid = next_id(con, "ACT")
    con.execute("INSERT INTO case_actions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (aid, case_id, action, current, target, rv["reviewer_id"], rv.get("kind", "simulated"), justification,
                 rep["report_id"] if rep else None, rep["version"] if rep else None, snap, h, key, now))
    did = next_id(con, "DSP")
    con.execute("INSERT INTO case_dispositions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (did, case_id, aid, entry_type, parent_id, disposition, concern, justification, dumps(evidence_ids),
                 rv["reviewer_id"], rv.get("role", ""), rv.get("kind", "simulated"),
                 rep["report_id"] if rep else None, rep["version"] if rep else None, snap, h, approval, current, target, now))
    if target != current:
        con.execute("UPDATE cases SET status = ?, updated_at_utc = ? WHERE case_id = ?", (target, now, case_id))
    else:
        con.execute("UPDATE cases SET updated_at_utc = ? WHERE case_id = ?", (now, case_id))
    if rep:
        lock_report(con, rep["report_id"])
    return did


def record(case_id: str, rv: dict | None, *, disposition: str, concern_type: str, justification: str,
           evidence_ids: list[str], idempotency_key: str, expected_status: str | None = None,
           report_id: str | None = None) -> dict:
    rv = _check_reviewer(rv)
    if disposition not in config.DISPOSITIONS:
        raise WorkflowError("Unknown disposition.", 422)
    if concern_type not in config.CONCERN_TYPES:
        raise WorkflowError("Unknown concern type.", 422)
    justification = (justification or "").strip()
    if len(justification) < config.MIN_JUSTIFICATION_CHARS:
        raise WorkflowError(f"A justification of at least {config.MIN_JUSTIFICATION_CHARS} characters is required.", 422)
    if len(justification) > config.MAX_NOTE_CHARS:
        raise WorkflowError(f"Justifications are limited to {config.MAX_NOTE_CHARS} characters.", 422)
    ids = list(dict.fromkeys(e.strip() for e in (evidence_ids or []) if e and e.strip()))
    if not ids:
        raise WorkflowError("Cite at least one evidence item that supports this decision.", 422)
    if len(ids) > config.MAX_DISPOSITION_EVIDENCE:
        raise WorkflowError(f"Cite at most {config.MAX_DISPOSITION_EVIDENCE} evidence items.", 422)
    with connect() as con:
        with tx(con):
            dup = _dedupe(con, idempotency_key, case_id, "record_disposition")
            if dup:
                return dup
            current = _status(con, case_id, expected_status)
            if current not in config.DISPOSITION_FROM:
                raise WorkflowError(f"Start the review before recording an investigation decision (the case is '{current}').", 409)
            rep, snap, h = report_context(con, case_id, report_id)
            if rep is None:
                raise WorkflowError("Generate and read an investigation report before recording a decision.", 409)
            for eid in ids:
                ev = con.execute("SELECT case_id, snapshot_id FROM evidence WHERE evidence_id = ?", (eid,)).fetchone()
                if ev is None or ev["case_id"] != case_id:
                    raise WorkflowError(f"Evidence {eid} does not belong to {case_id}.", 422)
                if ev["snapshot_id"] not in (None, snap):
                    raise WorkflowError(f"Evidence {eid} is from a different evidence version than report v{rep['version']}.", 422)
            spec = config.DISPOSITIONS[disposition]
            if spec["needs_senior"] and not _senior(rv):
                approval, target = "pending_senior", current          # a recommendation: the case stays open
            else:
                approval, target = ("confirmed" if spec["needs_senior"] else "not_required"), spec["status"]
            did = _write(con, case_id=case_id, rv=rv, action="record_disposition", entry_type="decision", parent_id=None,
                         disposition=disposition, concern=concern_type, justification=justification, evidence_ids=ids,
                         rep=rep, snap=snap, h=h, approval=approval, current=current, target=target, key=idempotency_key)
            out = _row(con.execute("SELECT * FROM case_dispositions WHERE disposition_id = ?", (did,)).fetchone())
    return {**out, "duplicate": False, "reviewer_name": rv["display_name"]}


def review(case_id: str, disposition_id: str, rv: dict | None, *, decision: str, notes: str,
           idempotency_key: str, expected_status: str | None = None) -> dict:
    """Senior confirmation or return of a pending 'substantiated' recommendation."""
    rv = _check_reviewer(rv)
    if not _senior(rv):
        raise WorkflowError("Only a senior investigator can confirm or return a substantiated recommendation.", 403)
    if decision not in ("confirm", "return"):
        raise WorkflowError("Decision must be 'confirm' or 'return'.", 422)
    notes = (notes or "").strip()
    if len(notes) < config.MIN_NOTE_CHARS:
        raise WorkflowError(f"Notes of at least {config.MIN_NOTE_CHARS} characters are required.", 422)
    action = "confirm_disposition" if decision == "confirm" else "return_disposition"
    with connect() as con:
        with tx(con):
            dup = _dedupe(con, idempotency_key, case_id, action)
            if dup:
                return dup
            current = _status(con, case_id, expected_status)
            target_row = con.execute("SELECT * FROM case_dispositions WHERE disposition_id = ? AND case_id = ?",
                                     (disposition_id, case_id)).fetchone()
            if target_row is None:
                raise WorkflowError("Disposition not found for this case.", 404)
            state = _effective(con, case_id).get(disposition_id)
            if target_row["entry_type"] != "decision" or state != "pending_senior":
                raise WorkflowError("Only the latest pending 'substantiated' recommendation can be confirmed or returned.", 409)
            if current not in config.DISPOSITION_FROM:
                raise WorkflowError(f"The case is '{current}'; reopen it before confirming.", 409)
            if target_row["reviewer_id"] == rv["reviewer_id"]:
                raise WorkflowError("A different reviewer must confirm this recommendation.", 409)
            rep = con.execute("SELECT report_id, version, snapshot_id, evidence_hash FROM reports WHERE report_id = ?",
                              (target_row["report_id"],)).fetchone()
            target = config.STATUS_SUBSTANTIATED if decision == "confirm" else current
            did = _write(con, case_id=case_id, rv=rv, action=action, entry_type="confirmation" if decision == "confirm" else "return",
                         parent_id=disposition_id, disposition=target_row["disposition"], concern=target_row["concern_type"],
                         justification=notes, evidence_ids=loads(target_row["evidence_ids"], []), rep=rep,
                         snap=target_row["snapshot_id"], h=target_row["evidence_hash"],
                         approval="confirmed" if decision == "confirm" else "returned",
                         current=current, target=target, key=idempotency_key)
            out = _row(con.execute("SELECT * FROM case_dispositions WHERE disposition_id = ?", (did,)).fetchone())
    return {**out, "duplicate": False, "reviewer_name": rv["display_name"]}


def _effective(con, case_id: str) -> dict[str, str]:
    """Current approval state of each decision entry: confirmed / returned / pending_senior / superseded / not_required."""
    rows = con.execute("SELECT * FROM case_dispositions WHERE case_id = ? ORDER BY created_at_utc, disposition_id",
                       (case_id,)).fetchall()
    state: dict[str, str] = {}
    last_decision = None
    for r in rows:
        if r["entry_type"] == "decision":
            if last_decision and state[last_decision] == "pending_senior":
                state[last_decision] = "superseded"
            state[r["disposition_id"]] = r["approval_status"]
            last_decision = r["disposition_id"]
        elif r["parent_id"] in state:
            state[r["parent_id"]] = r["approval_status"]
    # a pending recommendation is superseded by any later status-changing action (e.g. a legacy close)
    if last_decision and state[last_decision] == "pending_senior":
        dec = next(r for r in rows if r["disposition_id"] == last_decision)
        later = con.execute("""SELECT 1 FROM case_actions WHERE case_id = ? AND action_id > ? AND from_status != to_status
                               LIMIT 1""", (case_id, dec["action_id"])).fetchone()
        if later:
            state[last_decision] = "superseded"
    return state


def history(case_id: str) -> dict:
    with connect() as con:
        c = con.execute("SELECT status FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        if c is None:
            raise WorkflowError(f"Case {case_id} not found", 404)
        rows = con.execute("""SELECT d.*, r.display_name AS reviewer_name FROM case_dispositions d
                              JOIN reviewers r ON r.reviewer_id = d.reviewer_id WHERE d.case_id = ?
                              ORDER BY d.created_at_utc, d.disposition_id""", (case_id,)).fetchall()
        state = _effective(con, case_id)
    entries = []
    for r in rows:
        e = _row(r)
        if e["entry_type"] == "decision":
            e["current_approval"] = state.get(e["disposition_id"], e["approval_status"])
        entries.append(e)
    decisions = [e for e in entries if e["entry_type"] == "decision"]
    current = decisions[-1] if decisions else None
    return {"case_id": case_id, "status": c["status"], "current": current, "entries": entries,
            "pending_senior": bool(current and current["current_approval"] == "pending_senior"),
            "can_record": c["status"] in config.DISPOSITION_FROM}


def options() -> dict:
    return {"dispositions": [{"key": k, "label": v["label"], "help": v["help"], "needs_senior": v["needs_senior"],
                              "status": v["status"]} for k, v in config.DISPOSITIONS.items()],
            "concern_types": [{"key": k, "label": v} for k, v in config.CONCERN_TYPES.items()],
            "labels": config.DISPOSITION_LABELS, "min_justification_chars": config.MIN_JUSTIFICATION_CHARS,
            "notice": config.DISPOSITION_NOTICE, "senior_roles": sorted(config.SENIOR_ROLES)}
