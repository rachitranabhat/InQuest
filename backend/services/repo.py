"""Read helpers shared by services (all parameterised queries)."""
from __future__ import annotations

import sqlite3

from database.db import loads
from services.claims import Vocab


class NotFound(Exception):
    pass


def case_row(con: sqlite3.Connection, case_id: str) -> dict:
    r = con.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
    if r is None:
        raise NotFound(f"Case {case_id} not found")
    d = dict(r)
    d["features"] = loads(d.pop("features_json"), {})
    d["factors"] = loads(d.pop("factors_json"), {})
    d["priority_rationale"] = loads(d["priority_rationale"], [])
    a = con.execute("SELECT * FROM alerts WHERE alert_id = ?", (d["alert_id"],)).fetchone()
    d["alert"] = {**dict(a), "rules_fired": loads(a["rules_fired"], []), "indicators": loads(a["indicators"], []),
                  "transaction_ids": loads(a["transaction_ids"], [])}
    return d


def _ev(r) -> dict:
    d = dict(r)
    for k in ("source_ids", "entities", "computed", "provenance"):
        d[k] = loads(d[k], [] if k in ("source_ids", "entities") else {})
    return d


def evidence_items(con, case_id: str, snapshot_id: str | None = None, include_queries: bool = True) -> list[dict]:
    q = "SELECT * FROM evidence WHERE case_id = ?"
    params: list = [case_id]
    if snapshot_id:
        q += " AND (snapshot_id = ?" + (" OR snapshot_id IS NULL)" if include_queries else ")")
        params.append(snapshot_id)
    return [_ev(r) for r in con.execute(q + " ORDER BY evidence_id", params)]


def evidence_item(con, case_id: str, evidence_id: str) -> dict:
    r = con.execute("SELECT * FROM evidence WHERE evidence_id = ?", (evidence_id,)).fetchone()
    if r is None or r["case_id"] != case_id:
        raise NotFound(f"Evidence {evidence_id} not found for {case_id}")
    return _ev(r)


def evidence_owner(con):
    def lookup(eid: str):
        r = con.execute("SELECT case_id FROM evidence WHERE evidence_id = ?", (eid,)).fetchone()
        return r[0] if r else None
    return lookup


def vocab(con) -> Vocab:
    return Vocab(retailer_names=[r[0] for r in con.execute("SELECT name FROM retailers")],
                 cities=[r[0] for r in con.execute("SELECT city FROM locations")],
                 event_names=[r[0] for r in con.execute("SELECT name FROM events")])


def reviewer(con, reviewer_id: str) -> dict:
    r = con.execute("SELECT * FROM reviewers WHERE reviewer_id = ?", (reviewer_id,)).fetchone()
    if r is None:
        raise NotFound("Unknown reviewer")
    return dict(r)
