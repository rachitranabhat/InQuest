"""Senior-only, read-only Data Management view over the SQLite database.

No SQL text ever comes from the client: each browsable table has a fixed column list, fixed
search columns and fixed filters, and every value is passed as a bound parameter. Identity
tables (player_identities, restricted_access_log) are never browsable here, and the player
listing has no name or contact fields.
"""
from __future__ import annotations

import config
from database.db import connect, get_meta, schema_version
from services.restricted import require_senior

COUNTS = {
    "players": "SELECT COUNT(*) FROM players",
    "transactions": "SELECT COUNT(*) FROM transactions",
    "retailers": "SELECT COUNT(*) FROM retailers",
    "cases": "SELECT COUNT(*) FROM cases",
    "alerts": "SELECT COUNT(*) FROM alerts",
    "audit_records": "SELECT COUNT(*) FROM case_actions",
    "evidence_items": "SELECT COUNT(*) FROM evidence",
    "reports": "SELECT COUNT(*) FROM reports",
    "identity_records": "SELECT COUNT(*) FROM player_identities",
    "identity_access_records": "SELECT COUNT(*) FROM restricted_access_log",
}

# table key -> (FROM clause, select columns, searchable columns, {filter name: column})
TABLES = {
    "players": ("players p LEFT JOIN locations l ON l.location_id = p.home_location_id",
                ["p.player_id", "l.city AS home_city", "p.has_rewards_card", "p.has_online_account",
                 "(SELECT COUNT(*) FROM cases c WHERE c.player_id = p.player_id) AS case_count"],
                ["p.player_id"], {"city": "l.city"}, "p.player_id"),
    "transactions": ("transactions t",
                     ["t.transaction_id", "t.timestamp_utc", "t.channel", "t.player_id", "t.account_id", "t.retailer_id",
                      "t.amount", "t.transaction_type", "t.game", "t.attribution"],
                     ["t.transaction_id", "t.player_id", "t.account_id", "t.retailer_id"],
                     {"channel": "t.channel", "attribution": "t.attribution"}, "t.timestamp_utc DESC, t.transaction_id"),
    "retailers": ("retailers r", ["r.retailer_id", "r.name", "r.city", "r.terminal_count"],
                  ["r.retailer_id", "r.name", "r.city"], {"city": "r.city"}, "r.retailer_id"),
    "cases": ("cases c", ["c.case_id", "c.status", "c.priority", "c.alert_score", "c.channel", "c.subject_id", "c.player_id",
                          "c.evidence_completeness", "c.origin", "c.created_at_utc"],
              ["c.case_id", "c.subject_id", "c.player_id"],
              {"status": "c.status", "priority": "c.priority", "channel": "c.channel"}, "c.case_id"),
    "alerts": ("alerts a", ["a.alert_id", "a.case_id", "a.alert_type", "a.source", "a.subject_id", "a.alert_score",
                            "a.triggered_at_utc"],
               ["a.alert_id", "a.case_id", "a.subject_id", "a.alert_type"], {"source": "a.source"}, "a.alert_id"),
    "audit": ("case_actions x", ["x.action_id", "x.case_id", "x.action", "x.from_status", "x.to_status", "x.reviewer_id",
                                 "x.session_kind", "x.report_version", "x.created_at_utc"],
              ["x.action_id", "x.case_id", "x.reviewer_id", "x.action"], {"action": "x.action"}, "x.created_at_utc DESC"),
}


def summary(rv: dict | None) -> dict:
    require_senior(rv)
    with connect() as con:
        counts = {k: con.execute(sql).fetchone()[0] for k, sql in COUNTS.items()}
        return {"engine": "SQLite", "file": config.DB_PATH.name, "schema_version": schema_version(),
                "dataset": {"built_utc": get_meta(con, "dataset_built"), "seed": get_meta(con, "seed"),
                            "version": get_meta(con, "dataset_version")},
                "counts": counts, "tables": sorted(TABLES),
                "notice": "Read-only summary of synthetic records. Identity details are only available in Restricted Records."}


def browse(rv: dict | None, table: str, q: str | None = None, filters: dict | None = None,
           limit: int = 25, offset: int = 0) -> dict:
    require_senior(rv)
    if table not in TABLES:
        raise ValueError("Unknown table")
    frm, cols, search, allowed, order = TABLES[table]
    where, args = [], []
    if q:
        where.append("(" + " OR ".join(f"{c} LIKE ?" for c in search) + ")")
        args += [f"%{q}%"] * len(search)
    for k, v in (filters or {}).items():
        if v in (None, ""):
            continue
        if k not in allowed:
            raise ValueError(f"Unknown filter '{k}'")
        where.append(f"{allowed[k]} = ?")
        args.append(v)
    w = f" WHERE {' AND '.join(where)}" if where else ""
    with connect() as con:
        total = con.execute(f"SELECT COUNT(*) FROM {frm}{w}", args).fetchone()[0]
        rows = con.execute(f"SELECT {', '.join(cols)} FROM {frm}{w} ORDER BY {order} LIMIT ? OFFSET ?",
                           [*args, limit, offset]).fetchall()
        return {"table": table, "total": total, "limit": limit, "offset": offset,
                "columns": [c.split(" AS ")[-1].split(".")[-1] for c in cols], "filters": sorted(allowed),
                "rows": [dict(r) for r in rows]}
