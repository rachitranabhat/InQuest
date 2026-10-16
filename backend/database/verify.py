"""Integrity checks that run against either backend (SQLite or PostgreSQL).

* counts per table
* content fingerprints per table (rows ordered by primary key, values normalised) — equal fingerprints
  mean the same rows, column for column, in both databases
* evidence snapshots: each stored evidence_hash recomputed from its evidence rows
* citations: every report claim and investigation decision cites evidence of its own case
* audit references: every action's report belongs to the same case; dispositions point at real actions
"""
from __future__ import annotations

import hashlib
import json

from database.db import loads

# table -> primary-key columns (also the FK-safe copy order)
TABLES = {
    "meta": ["key"], "locations": ["location_id"], "retailers": ["retailer_id"], "reviewers": ["reviewer_id"],
    "players": ["player_id"], "accounts": ["account_id"], "transactions": ["transaction_id"], "events": ["event_id"],
    "cases": ["case_id"], "alerts": ["alert_id"], "evidence_snapshots": ["snapshot_id"], "evidence": ["evidence_id"],
    "reports": ["report_id"], "claims": ["claim_id"], "report_exports": ["export_id"], "sessions": ["token"],
    "case_actions": ["action_id"], "chat_threads": ["thread_id"], "chat_messages": ["message_id"],
    "id_counters": ["prefix"], "bookmarks": ["bookmark_id"], "player_identities": ["player_id"],
    "restricted_access_log": ["access_id"], "case_dispositions": ["disposition_id"],
    "dataset_versions": ["dataset_version"], "scenario_labels": ["player_id"],
}


def columns(con, table: str) -> list[str]:
    r = con.execute(f"SELECT * FROM {table} LIMIT 0")
    return [d[0] for d in r.description]


def _norm(v):
    if isinstance(v, float):
        return repr(round(v, 9))
    return v


def table_fingerprint(con, table: str, exclude: tuple = ()) -> tuple[int, str]:
    cols = [c for c in columns(con, table) if c not in exclude]
    pk = TABLES[table]
    h = hashlib.sha256()
    n = 0
    for row in con.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY {', '.join(pk)}"):
        h.update(json.dumps([_norm(v) for v in row], default=str).encode())
        h.update(b"\n")
        n += 1
    return n, h.hexdigest()


def snapshot_integrity(con) -> dict:
    from services import repo
    from services.evidence_registry import snapshot_hash
    bad = []
    snaps = con.execute("SELECT snapshot_id, case_id, evidence_hash, item_count FROM evidence_snapshots").fetchall()
    for s in snaps:
        items = repo.evidence_items(con, s["case_id"], s["snapshot_id"], include_queries=False)
        if len(items) != s["item_count"] or snapshot_hash(items) != s["evidence_hash"]:
            bad.append(s["snapshot_id"])
    return {"snapshots": len(snaps), "hash_mismatches": bad}


def citation_integrity(con) -> dict:
    owner = dict(con.execute("SELECT evidence_id, case_id FROM evidence").fetchall())
    bad_claims = []
    for r in con.execute("SELECT c.claim_id, c.evidence_ids, r.case_id FROM claims c JOIN reports r ON r.report_id = c.report_id"):
        if any(owner.get(e) != r["case_id"] for e in loads(r["evidence_ids"], [])):
            bad_claims.append(r["claim_id"])
    bad_dsp = []
    for r in con.execute("SELECT disposition_id, case_id, evidence_ids FROM case_dispositions"):
        if any(owner.get(e) != r["case_id"] for e in loads(r["evidence_ids"], [])):
            bad_dsp.append(r["disposition_id"])
    bad_actions = [r[0] for r in con.execute(
        """SELECT a.action_id FROM case_actions a JOIN reports r ON r.report_id = a.report_id
           WHERE r.case_id != a.case_id""")]
    orphan_dsp = [r[0] for r in con.execute(
        """SELECT d.disposition_id FROM case_dispositions d LEFT JOIN case_actions a ON a.action_id = d.action_id
           WHERE a.action_id IS NULL OR a.case_id != d.case_id""")]
    return {"claims_checked": con.execute("SELECT COUNT(*) FROM claims").fetchone()[0],
            "claims_citing_other_cases": bad_claims, "dispositions_citing_other_cases": bad_dsp,
            "actions_with_foreign_report": bad_actions, "dispositions_without_audit_row": orphan_dsp}


def report(con, tables=None) -> dict:
    out = {"tables": {}}
    for t in tables or TABLES:
        try:
            n, h = table_fingerprint(con, t)
        except Exception as e:  # noqa: BLE001 - table absent in an older schema
            out["tables"][t] = {"missing": str(e)[:80]}
            if getattr(con, "backend", "sqlite") == "postgres" and con.in_tx:
                con.end(False)
            continue
        out["tables"][t] = {"rows": n, "sha256": h}
    out["snapshots"] = snapshot_integrity(con)
    out["citations"] = citation_integrity(con)
    return out


def ok(rep: dict) -> bool:
    c = rep["citations"]
    return not rep["snapshots"]["hash_mismatches"] and not any(c[k] for k in c if k != "claims_checked")
