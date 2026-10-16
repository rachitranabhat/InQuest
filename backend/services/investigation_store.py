"""Persistence for multi-agent investigations (schema v6). Separate from services/agents.py so the agent
module itself never contains write SQL; this module only writes the `investigations` table.

Every run is its own row (history is kept; reruns never overwrite). A row is written as 'running' first and
finished once ('completed' or 'failed'); triggers make finished rows immutable and undeletable.
"""
from __future__ import annotations

import threading

from database.db import connect, dumps, loads, tx
from services import repo
from timeutil import utc_now_iso

INTERRUPTED = "Interrupted: the server stopped before this run finished. Nothing about the case changed; run it again."


def create(investigation_id: str, case_id: str, mode: str, reviewer_id: str) -> dict:
    now = utc_now_iso()
    with connect() as con, tx(con):
        con.execute("INSERT INTO investigations (investigation_id, case_id, requested_mode, status, requested_by, "
                    "started_at_utc) VALUES (?,?,?,?,?,?)", (investigation_id, case_id, mode, "running", reviewer_id, now))
    return summary_row({"investigation_id": investigation_id, "case_id": case_id, "requested_mode": mode, "mode": None,
                        "status": "running", "assessment": None, "requested_by": reviewer_id, "started_at_utc": now,
                        "finished_at_utc": None, "error": None})


def complete(result: dict) -> None:
    with connect() as con, tx(con):
        exists = con.execute("SELECT status FROM investigations WHERE investigation_id = ?", (result["investigation_id"],)).fetchone()
        if exists is None:
            con.execute("INSERT INTO investigations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (result["investigation_id"], result["case_id"], result["requested_mode"], result["mode"], "completed",
                         result["lead"]["assessment"], result["requested_by"], result["started_at_utc"],
                         result["finished_at_utc"], None, dumps(result)))
        else:
            con.execute("UPDATE investigations SET status = 'completed', mode = ?, assessment = ?, finished_at_utc = ?, "
                        "result_json = ? WHERE investigation_id = ? AND status = 'running'",
                        (result["mode"], result["lead"]["assessment"], result["finished_at_utc"], dumps(result),
                         result["investigation_id"]))


def fail(investigation_id: str, error: str) -> None:
    with connect() as con, tx(con):
        con.execute("UPDATE investigations SET status = 'failed', finished_at_utc = ?, error = ? "
                    "WHERE investigation_id = ? AND status = 'running'", (utc_now_iso(), error[:500], investigation_id))


def mark_interrupted() -> int:
    """At startup: runs left 'running' by a previous server process can never finish."""
    with connect() as con, tx(con):
        n = con.execute("SELECT COUNT(*) FROM investigations WHERE status = 'running'").fetchone()[0]
        if n:
            con.execute("UPDATE investigations SET status = 'failed', finished_at_utc = ?, error = ? WHERE status = 'running'",
                        (utc_now_iso(), INTERRUPTED))
    return n


def summary_row(r) -> dict:
    d = {k: r[k] for k in ("investigation_id", "case_id", "requested_mode", "mode", "status", "assessment",
                           "requested_by", "started_at_utc", "finished_at_utc", "error")}
    return d


def get(investigation_id: str) -> dict:
    with connect() as con:
        r = con.execute("SELECT * FROM investigations WHERE investigation_id = ?", (investigation_id,)).fetchone()
    if r is None:
        raise repo.NotFound("Investigation not found.")
    if r["status"] == "completed":
        return {**loads(r["result_json"], {}), "status": "completed"}
    return summary_row(r)


def history(case_id: str, limit: int = 20) -> list[dict]:
    with connect() as con:
        repo.case_row(con, case_id)
        rows = con.execute("SELECT * FROM investigations WHERE case_id = ? ORDER BY started_at_utc DESC, investigation_id DESC "
                           "LIMIT ?", (case_id, limit)).fetchall()
    return [summary_row(r) for r in rows]


def running_for(case_id: str) -> dict | None:
    with connect() as con:
        r = con.execute("SELECT * FROM investigations WHERE case_id = ? AND status = 'running' "
                        "ORDER BY started_at_utc DESC LIMIT 1", (case_id,)).fetchone()
    return summary_row(r) if r else None


_START_LOCK = threading.Lock()
