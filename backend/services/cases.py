"""Case queue, case detail, timeline, analytics."""
from __future__ import annotations

import statistics

import pandas as pd

import config
from database.db import connect, loads
from services import repo
from services.reports import latest as latest_report
from services.reports import list_for_case
from services.workflow import allowed_actions
from timeutil import utc_iso_to_local

PRIORITY_ORDER = {v: i for i, v in enumerate(["Critical review priority", "High review priority",
                                               "Medium review priority", "Lower review priority"])}


def list_cases(q=None, status=None, priority=None, alert_type=None, channel=None, reviewer=None,
               date_from=None, date_to=None, curated_only=False, sort="priority", limit=500, completeness=None) -> dict:
    sql = """SELECT c.case_id, c.alert_id, c.channel, c.subject_type, c.subject_id, c.player_id, c.status, c.priority,
                    c.alert_score, c.score_band, c.evidence_completeness, c.urgency, c.primary_reason, c.triggered_count,
                    c.created_at_utc, c.updated_at_utc, c.assigned_reviewer_id, c.curated_key, c.scenario_title, c.origin,
                    a.alert_type, r.display_name AS assigned_reviewer
             FROM cases c JOIN alerts a ON a.alert_id = c.alert_id
             LEFT JOIN reviewers r ON r.reviewer_id = c.assigned_reviewer_id WHERE 1=1"""
    params: list = []
    if q:
        sql += " AND (c.case_id LIKE ? OR c.subject_id LIKE ? OR c.player_id LIKE ? OR a.alert_type LIKE ? OR c.scenario_title LIKE ?)"
        like = f"%{q.strip()}%"
        params += [like] * 5
    for col, val in (("c.status", status), ("c.priority", priority), ("a.alert_type", alert_type), ("c.channel", channel),
                     ("c.evidence_completeness", completeness)):
        if val:
            vals = [v for v in val.split(",") if v]
            sql += f" AND {col} IN ({','.join('?' * len(vals))})"
            params += vals
    if reviewer == "unassigned":
        sql += " AND c.assigned_reviewer_id IS NULL"
    elif reviewer:
        sql += " AND c.assigned_reviewer_id = ?"
        params.append(reviewer)
    if date_from:
        sql += " AND c.created_at_utc >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND c.created_at_utc <= ?"
        params.append(date_to + "T23:59:59Z" if len(date_to) == 10 else date_to)
    if curated_only:
        sql += " AND c.curated_key IS NOT NULL"
    with connect() as con:
        rows = [dict(r) for r in con.execute(sql, params)]
        facets = {
            "statuses": config.ALL_STATUSES,
            "priorities": list(PRIORITY_ORDER),
            "alert_types": [r[0] for r in con.execute("SELECT DISTINCT alert_type FROM alerts ORDER BY 1")],
            "reviewers": [dict(r) for r in con.execute(
                "SELECT reviewer_id, display_name FROM reviewers WHERE reviewer_id != 'SYSTEM'")],
        }
        totals = {"all": con.execute("SELECT COUNT(*) FROM cases").fetchone()[0],
                  "open": con.execute(f"SELECT COUNT(*) FROM cases WHERE status IN ({','.join('?' * len(config.OPEN_STATUSES))})",
                                      config.OPEN_STATUSES).fetchone()[0]}
    if sort == "score":
        rows.sort(key=lambda r: -r["alert_score"])
    elif sort == "newest":
        rows.sort(key=lambda r: r["created_at_utc"], reverse=True)
    elif sort == "updated":
        rows.sort(key=lambda r: r["updated_at_utc"], reverse=True)
    else:
        rows.sort(key=lambda r: (r["status"] not in config.OPEN_STATUSES, PRIORITY_ORDER.get(r["priority"], 9),
                                 -r["alert_score"]))
    return {"cases": rows[:limit], "count": len(rows), "facets": facets, "totals": totals}


def detail(case_id: str) -> dict:
    with connect() as con:
        c = repo.case_row(con, case_id)
        snap = con.execute("SELECT * FROM evidence_snapshots WHERE snapshot_id = ?", (c["current_snapshot_id"],)).fetchone()
        counts = dict(con.execute("SELECT type, COUNT(*) FROM evidence WHERE case_id = ? GROUP BY type", (case_id,)).fetchall())
        rv = c["assigned_reviewer_id"] and repo.reviewer(con, c["assigned_reviewer_id"])
        rep = latest_report(con, case_id)
        out = {
            **{k: v for k, v in c.items() if k not in ("features",)},
            "factors": [{"key": k, "label": f["label"], "points": f["points"], "max_points": f["max_points"],
                         "share": f["share"], "triggered": f["triggered"], "measurement": f["measurement"],
                         "rule": f["rule"], "transaction_ids": f["transactions"]} for k, f in c["factors"].items()],
            "snapshot": dict(snap) if snap else None,
            "evidence_counts": counts,
            "assigned_reviewer": rv or None,
            "allowed_actions": allowed_actions(c["status"]),
            "latest_report": ({k: rep[k] for k in ("report_id", "version", "mode", "mode_label", "status", "validation",
                                                   "created_at_utc")} if rep else None),
            "reports": list_for_case(con, case_id),
            "subject_label": ("Online account" if c["channel"] == "online_account" else "Player (rewards-card attributed)"),
        }
        return out


def evidence_list(case_id: str, type_=None) -> list[dict]:
    with connect() as con:
        repo.case_row(con, case_id)
        items = repo.evidence_items(con, case_id)
    if type_:
        items = [i for i in items if i["type"] == type_]
    return items


def timeline(case_id: str) -> dict:
    """Transactions in the window (with evidence IDs) plus daily baseline averages for context."""
    with connect() as con:
        c = repo.case_row(con, case_id)
        items = repo.evidence_items(con, case_id, c["current_snapshot_id"], include_queries=False)
        col = "account_id" if c["channel"] == "online_account" else "player_id"
        base = pd.read_sql_query(f"""SELECT timestamp_utc, amount, transaction_type FROM transactions WHERE {col} = ?
                                     AND timestamp_utc < ? {"AND channel='lottery_terminal'" if col == 'player_id' else ''}""",
                                 con, params=[c["subject_id"], c["window_start_utc"]])
    txns = [{"evidence_id": i["evidence_id"], "transaction_id": i["source_ids"][0], **i["computed"]}
            for i in items if i["type"] == "transaction"]
    txns.sort(key=lambda t: t["timestamp_local"])
    linked: dict[str, list[str]] = {}
    for k, f in c["factors"].items():
        if f["triggered"]:
            for t in f["transactions"]:
                linked.setdefault(t, []).append(k)
    for t in txns:
        t["linked_factors"] = linked.get(t["transaction_id"], [])
    days = [{"date": i["computed"]["date"], "transaction_count": i["computed"]["transaction_count"],
             "total_amount": i["computed"]["total_amount"], "evidence_id": i["evidence_id"]}
            for i in items if i["type"] == "aggregate_day"]
    if c["channel"] == "online_account":
        base = base[base.transaction_type == "deposit"]
    base_local = utc_iso_to_local(base.timestamp_utc) if len(base) else pd.Series(dtype="datetime64[ns]")
    hour_base = (base_local.dt.hour.value_counts().reindex(range(24), fill_value=0) / config.HISTORY_DAYS).round(3).tolist() \
        if len(base) else [0.0] * 24
    hour_win = [0] * 24
    for t in txns:
        if c["channel"] != "online_account" or t["transaction_type"] == "deposit":
            hour_win[t["hour"]] += 1
    return {"transactions": txns, "days": sorted(days, key=lambda d: d["date"]),
            "baseline_daily_average": c["features"].get("hist_transactions_per_day"),
            "hour_profile": {"baseline_per_day": hour_base, "window_total": hour_win,
                             "window_days": config.WINDOW_DAYS, "baseline_days": config.HISTORY_DAYS}}


def analytics() -> dict:
    with connect() as con:
        status = dict(con.execute("SELECT status, COUNT(*) FROM cases GROUP BY status").fetchall())
        prio = dict(con.execute("SELECT priority, COUNT(*) FROM cases GROUP BY priority").fetchall())
        acts = [dict(r) for r in con.execute(
            "SELECT case_id, action, created_at_utc, reviewer_id FROM case_actions WHERE reviewer_id != 'SYSTEM' ORDER BY created_at_utc")]
        reports = dict(con.execute("SELECT mode, COUNT(*) FROM reports GROUP BY mode").fetchall())
        claim_stats = dict(con.execute("SELECT verification_status, COUNT(*) FROM claims GROUP BY verification_status").fetchall())
        exports = con.execute("SELECT COUNT(*) FROM report_exports").fetchone()[0]
        chats = con.execute("SELECT COUNT(*) FROM chat_messages WHERE role = 'user'").fetchone()[0]
        chat_modes = dict(con.execute("SELECT mode, COUNT(*) FROM chat_messages WHERE role='assistant' GROUP BY mode").fetchall())
    started, durations = {}, []
    reviewed = set()
    for a in acts:
        if a["action"] == "start_review":
            started.setdefault(a["case_id"], a["created_at_utc"])
        elif a["action"] in DECISION_ACTIONS:
            reviewed.add(a["case_id"])
            if a["case_id"] in started:
                d = (pd.Timestamp(a["created_at_utc"]) - pd.Timestamp(started.pop(a["case_id"]))).total_seconds() / 60
                durations.append(round(d, 2))
    by_day: dict[str, int] = {}
    for a in acts:
        if a["action"] in DECISION_ACTIONS:
            day = a["created_at_utc"][:10]
            by_day[day] = by_day.get(day, 0) + 1
    return {
        "status_counts": {s: status.get(s, 0) for s in config.ALL_STATUSES},
        "priority_counts": prio,
        "open": sum(status.get(s, 0) for s in config.OPEN_STATUSES),
        "reviewed": len(reviewed),
        "escalated": status.get(config.STATUS_ESCALATED, 0),
        "closed": status.get(config.STATUS_CLOSED, 0),
        "substantiated": status.get(config.STATUS_SUBSTANTIATED, 0),
        "review_minutes": {"n": len(durations), "median": statistics.median(durations) if durations else None,
                           "mean": round(statistics.mean(durations), 2) if durations else None,
                           "definition": "Minutes from a reviewer's 'Start review' to their first decision on that case, "
                                         "measured server-side from audit records."},
        "decisions_by_day": [{"date": d, "count": n} for d, n in sorted(by_day.items())],
        "reports_by_mode": reports, "claims": claim_stats, "exports": exports,
        "copilot_questions": chats, "copilot_modes": chat_modes,
        "actions_total": len(acts),
    }


DECISION_ACTIONS = ("close_no_action", "escalate", "request_info", "record_disposition")


def audit(limit=200) -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute(
            """SELECT a.*, r.display_name AS reviewer_name FROM case_actions a JOIN reviewers r ON r.reviewer_id = a.reviewer_id
               ORDER BY a.created_at_utc DESC, a.action_id DESC LIMIT ?""", (limit,))]


def case_audit(case_id: str) -> list[dict]:
    from services.reports import case_actions
    with connect() as con:
        repo.case_row(con, case_id)
        return case_actions(con, case_id)


def snapshot_hash_for(case_id: str) -> str:
    with connect() as con:
        c = repo.case_row(con, case_id)
        return con.execute("SELECT evidence_hash FROM evidence_snapshots WHERE snapshot_id = ?",
                           (c["current_snapshot_id"],)).fetchone()[0]


__all__ = ["list_cases", "detail", "evidence_list", "timeline", "analytics", "audit", "case_audit", "loads"]
