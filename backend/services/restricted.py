"""Restricted identity records (fictional) and senior-only access checks.

Prototype only. Roles come from the simulated reviewer session: the role check is enforced
on the server for every restricted endpoint, but the session itself is not authentication
(anyone can choose any reviewer). See PROGRESS.md "Limitations".

Rules kept here:
* Identity rows are invented: names from fixed lists, e-mail at the reserved example.invalid
  domain, phone numbers in the fictional 555-01xx range. No real person's details are stored.
* Only players with a rewards card or online account have a record; anonymous purchases have none.
* Nothing outside this module reads player_identities: case, evidence, report, copilot and
  analytics responses never contain these fields.
* A reveal needs a written reason and always writes an append-only restricted_access_log row
  (reviewer, role, player, case, UTC time, reason, fields revealed). Values are never logged to
  application logs.
"""
from __future__ import annotations

import hashlib

import config

from database.db import connect, dumps, loads, next_id, tx
from services.workflow import WorkflowError
from timeutil import utc_now_iso

SENIOR_ROLES = config.SENIOR_ROLES
MIN_REASON_CHARS = 15
MAX_REASON_CHARS = 500
REVEALED_FIELDS = ["full_name", "email", "phone"]

_FIRST = ["Avery", "Blair", "Casey", "Dakota", "Emerson", "Finley", "Harper", "Hayden", "Jamie", "Kendall",
          "Logan", "Morgan", "Parker", "Quinn", "Reese", "Riley", "Rowan", "Sawyer", "Skyler", "Taylor"]
_LAST = ["Ashgrove", "Birchfield", "Calloway", "Dunmore", "Elmsworth", "Fairbank", "Glenhaven", "Hollis",
         "Ironwood", "Kestrel", "Larkspur", "Marlowe", "Northcott", "Oakridge", "Pemberly", "Quarry",
         "Redfern", "Stonebridge", "Thornbury", "Wexley"]


def is_senior(rv: dict | None) -> bool:
    return bool(rv) and rv.get("role") in SENIOR_ROLES


def require_senior(rv: dict | None) -> dict:
    if rv is None:
        raise WorkflowError("A simulated reviewer session is required. Choose a reviewer first.", 401)
    if not is_senior(rv):
        raise WorkflowError("Senior investigator access is required for restricted records.", 403)
    return rv


def _fictional(player_id: str) -> tuple[str, str, str]:
    h = hashlib.sha256(f"prism-fictional-identity:{player_id}".encode()).digest()
    first, last = _FIRST[h[0] % len(_FIRST)], _LAST[h[1] % len(_LAST)]
    num = int.from_bytes(h[2:4], "big") % 10000
    return (f"{first} {last}", f"{first}.{last}.{num:04d}@example.invalid".lower(), f"555-01{h[4] % 100:02d}")


def ensure_identities(con) -> int:
    """Create missing fictional records for registered players. Insert-only; never alters other tables."""
    rows = con.execute("""SELECT p.player_id, p.has_rewards_card, p.has_online_account FROM players p
                          LEFT JOIN player_identities i ON i.player_id = p.player_id
                          WHERE i.player_id IS NULL AND (p.has_rewards_card = 1 OR p.has_online_account = 1)""").fetchall()
    if not rows:
        return 0
    now = utc_now_iso()
    out = []
    for r in rows:
        src = " and ".join(s for s, on in (("rewards card", r["has_rewards_card"]), ("online account", r["has_online_account"])) if on)
        out.append((r["player_id"], *_fictional(r["player_id"]), src, 1, now))
    with tx(con):
        con.executemany("INSERT OR IGNORE INTO player_identities VALUES (?,?,?,?,?,?,?)", out)
    return len(out)


def list_records(rv: dict | None, q: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    """Minimum information only: synthetic IDs, linked cases, record source, access history counts. No identity values."""
    require_senior(rv)
    with connect() as con:
        ensure_identities(con)
        where, args = "", []
        if q:
            where = """WHERE i.player_id LIKE ? OR EXISTS (SELECT 1 FROM cases c2 WHERE c2.player_id = i.player_id AND c2.case_id LIKE ?)"""
            args = [f"%{q}%", f"%{q}%"]
        total = con.execute(f"SELECT COUNT(*) FROM player_identities i {where}", args).fetchone()[0]
        rows = con.execute(f"""
            SELECT * FROM (SELECT i.player_id, i.record_source,
                   (SELECT GROUP_CONCAT(c.case_id) FROM (SELECT case_id FROM cases WHERE player_id = i.player_id ORDER BY case_id) c) AS case_ids,
                   (SELECT COUNT(*) FROM restricted_access_log l WHERE l.player_id = i.player_id) AS access_count,
                   (SELECT MAX(created_at_utc) FROM restricted_access_log l WHERE l.player_id = i.player_id) AS last_access_utc
            FROM player_identities i {where}) x
            ORDER BY (case_ids IS NULL), player_id LIMIT ? OFFSET ?""", [*args, limit, offset]).fetchall()
        return {"total": total, "limit": limit, "offset": offset,
                "records": [{**dict(r), "case_ids": (r["case_ids"] or "").split(",") if r["case_ids"] else []} for r in rows],
                "notice": "Fictional identity records for synthetic players. Details stay hidden until revealed with a reason."}


def reveal(rv: dict | None, player_id: str, reason: str, case_id: str | None = None) -> dict:
    require_senior(rv)
    reason = (reason or "").strip()
    if len(reason) < MIN_REASON_CHARS:
        raise WorkflowError(f"Give a reason of at least {MIN_REASON_CHARS} characters before revealing identifying details.", 422)
    if len(reason) > MAX_REASON_CHARS:
        raise WorkflowError(f"Reasons are limited to {MAX_REASON_CHARS} characters.", 422)
    with connect() as con:
        ensure_identities(con)
        row = con.execute("SELECT * FROM player_identities WHERE player_id = ?", (player_id,)).fetchone()
        if row is None:
            exists = con.execute("SELECT 1 FROM players WHERE player_id = ?", (player_id,)).fetchone()
            raise WorkflowError("Unknown player." if not exists else
                                "No identity record: this player has no rewards card or online account (anonymous).", 404)
        if case_id:
            c = con.execute("SELECT player_id FROM cases WHERE case_id = ?", (case_id,)).fetchone()
            if c is None or c["player_id"] != player_id:
                raise WorkflowError("That case is not linked to this player.", 422)
        now = utc_now_iso()
        with tx(con):
            aid = next_id(con, "IDA")
            con.execute("INSERT INTO restricted_access_log VALUES (?,?,?,?,?,?,?,?,?)",
                        (aid, player_id, case_id, rv["reviewer_id"], rv["role"], rv.get("kind", "simulated"),
                         reason, dumps(REVEALED_FIELDS), now))
        return {"player_id": player_id, "case_id": case_id, "full_name": row["full_name"], "email": row["email"],
                "phone": row["phone"], "record_source": row["record_source"], "fictional": True,
                "access_id": aid, "logged_at_utc": now,
                "notice": "Fictional record. This access was recorded with your reason."}


def access_log(rv: dict | None, player_id: str | None = None, limit: int = 100) -> list[dict]:
    require_senior(rv)
    with connect() as con:
        sql = """SELECT l.access_id, l.player_id, l.case_id, l.reviewer_id, r.display_name AS reviewer_name,
                        l.reviewer_role, l.session_kind, l.reason, l.fields, l.created_at_utc
                 FROM restricted_access_log l JOIN reviewers r ON r.reviewer_id = l.reviewer_id"""
        args: list = []
        if player_id:
            sql += " WHERE l.player_id = ?"
            args.append(player_id)
        rows = con.execute(sql + " ORDER BY l.created_at_utc DESC, l.access_id DESC LIMIT ?", [*args, limit]).fetchall()
        return [{**dict(r), "fields": loads(r["fields"], [])} for r in rows]
