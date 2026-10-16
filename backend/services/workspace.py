"""Investigator workspace views derived from a case's stored evidence.

* history(): previous vs. recent activity on normalized measures (per day, shares, busiest hour).
* completeness(): what the evidence version has, lacks, or leaves ambiguous, item by item.
* bookmarks: saved evidence with optional notes (workspace aids; never evidence, never decisions).

Every number here is read from, or arithmetically derived from, values in the case's current
evidence version, and every row carries the evidence IDs it came from. Nothing re-reads raw records.
"""
from __future__ import annotations

import config
from database.db import connect, next_id, tx
from services import repo
from timeutil import utc_now_iso

LOW_PREVIOUS_COUNT = 10      # below this many previous transactions, per-day rates are flagged as fragile


def _current(con, case_id: str) -> tuple[dict, dict[str, dict]]:
    c = repo.case_row(con, case_id)
    items = repo.evidence_items(con, case_id, c["current_snapshot_id"], include_queries=False)
    return c, {i["provenance"].get("key", i["evidence_id"]): i for i in items}


def _r(x, d=2):
    return None if x is None else round(float(x), d)


# =================================================================== history
def history(case_id: str) -> dict:
    with connect() as con:
        c, by = _current(con, case_id)
    base, met = by.get("baseline"), by.get("metric:window")
    is_account = c["channel"] == "online_account"
    scope = "deposits" if is_account else "linked purchases"
    if not base or not met:
        return {"case_id": case_id, "available": False, "reason": "This evidence version has no previous-activity summary.",
                "rows": [], "scope": scope}
    b, m = base["computed"], met["computed"]
    prev_days, win_days = b.get("baseline_days") or config.HISTORY_DAYS, m.get("window_days") or config.WINDOW_DAYS
    n_prev = b.get("baseline_transaction_count") or 0
    sufficient = bool(b.get("sufficient", True))

    def cmp(key):
        it = by.get(f"cmp:{key}")
        return (it["computed"], it["evidence_id"]) if it else (None, None)

    rows = []

    def row(key, label, unit, prev, cur, kind, evs, *, how, reliability="ok", note=None):
        if prev is None or cur is None:
            diff, change, change_unit = None, None, None
        else:
            diff = _r(cur - prev)
            if kind == "share":
                change, change_unit = diff, "pp"
            elif prev:
                change, change_unit = _r((cur - prev) / prev * 100, 1), "%"
            else:
                change, change_unit = None, "none_before"
        if not sufficient and reliability == "ok" and prev is not None:
            reliability, note = "unreliable", (note or "Too little previous activity for a dependable comparison.")
        rows.append({"key": key, "label": label, "unit": unit, "previous": prev, "current": cur, "difference": diff,
                     "change": change, "change_unit": change_unit, "kind": kind, "reliability": reliability,
                     "note": note, "how": how, "evidence_ids": [e for e in evs if e]})

    frag = (f"Only {n_prev} previous {scope}; rates can swing on a few records."
            if sufficient and n_prev < LOW_PREVIOUS_COUNT else None)

    per_day, ev_pd = cmp("per_day")
    row("per_day", "Transactions per day", "per day", per_day and per_day["baseline"], per_day and per_day["current"],
        "rate", [ev_pd, base["evidence_id"], met["evidence_id"]],
        how=f"Count ÷ days in each period ({prev_days} previous, {win_days} recent).",
        reliability="caution" if frag else "ok", note=frag)

    wk, ev_wk = cmp("week_total")
    prev_spend = _r(b["typical_week_total"] / 7) if b.get("typical_week_total") is not None else None
    cur_spend = _r(m["total_amount"] / win_days) if m.get("total_amount") is not None else None
    row("spend_per_day", "Spend per day", "$ per day", prev_spend, cur_spend, "money",
        [ev_wk, base["evidence_id"], met["evidence_id"]],
        how=f"Previous: typical 7-day total ÷ 7. Recent: total ÷ {win_days} days.",
        reliability="caution" if frag else "ok", note=frag)

    avg, ev_avg = cmp("avg_amount")
    row("avg_amount", "Average amount", "$", avg and avg["baseline"], avg and avg["current"], "money",
        [ev_avg, base["evidence_id"], met["evidence_id"]], how="Mean amount per transaction in each period.")

    bh, ev_bh = cmp("busiest_hour")
    row("busiest_hour", "Busiest hour", "transactions", bh and bh["baseline"], bh and bh["current"], "count",
        [ev_bh, base["evidence_id"], by.get("seq:peak", {}).get("evidence_id")],
        how="Previous: average of the busiest hour per active day. Recent: most transactions in any 60 minutes.",
        reliability="caution",
        note="Average vs. single peak; indicative only.")

    row("active_days", "Active days", f"of {win_days} days", None, m.get("days_active"), "count", [met["evidence_id"]],
        how="Days with at least one transaction.", reliability="unavailable",
        note="Previous active days are not in this evidence version.")

    if not is_account:
        rt, ev_rt = cmp("retailers")
        row("retailers", "Retailers used", "retailers", rt and rt["baseline"], rt and rt["current"], "count",
            [ev_rt, met["evidence_id"]], how="Distinct retailers in each period.", reliability="caution",
            note=f"Not per day: periods of different length ({prev_days} vs. {win_days} days).")
        ct, ev_ct = cmp("cities")
        row("cities", "Cities", "cities", ct and ct["baseline"], ct and ct["current"], "count",
            [ev_ct, met["evidence_id"]], how="Distinct cities in each period.", reliability="caution",
            note=f"Not per day: periods of different length ({prev_days} vs. {win_days} days).")

    ns, ev_ns = cmp("night_share")
    row("overnight_share", "Overnight share (12–5 AM)", "%", ns and ns["baseline"], ns and ns["current"], "share",
        [ev_ns, base["evidence_id"], met["evidence_id"]], how="Share of transactions between 00:00 and 04:59.")

    return {"case_id": case_id, "available": True, "scope": scope, "sufficient": sufficient,
            "reason": None if sufficient else "Too little previous activity to establish a typical pattern.",
            "periods": {"previous_days": prev_days, "recent_days": win_days, "previous_count": n_prev,
                        "recent_count": m.get("transaction_count")},
            "snapshot_id": c["current_snapshot_id"], "rows": rows}


# ============================================================== completeness
STATES = ("verified", "available", "partial", "ambiguous", "missing")


def completeness(case_id: str) -> dict:
    with connect() as con:
        c, by = _current(con, case_id)
    is_account = c["channel"] == "online_account"
    txns = [i for k, i in by.items() if k.startswith("txn:")]
    items: list[dict] = []

    def add(key, label, state, detail, evs):
        items.append({"key": key, "label": label, "state": state, "detail": detail, "evidence_ids": [e for e in evs if e]})

    stamped = sum(1 for t in txns if t["computed"].get("timestamp_local"))
    add("timestamps", "Timestamps", "available" if txns and stamped == len(txns) else ("partial" if stamped else "missing"),
        f"{stamped} of {len(txns)} records have a time." if txns else "No transaction records in this version.",
        [t["evidence_id"] for t in txns[:1]])

    if not is_account:
        named = sum(1 for t in txns if t["computed"].get("retailer_name"))
        add("retailers", "Retailer details", "available" if txns and named == len(txns) else ("partial" if named else "missing"),
            f"{named} of {len(txns)} records name a retailer and city.", [by.get(k, {}).get("evidence_id")
                                                                         for k in by if k.startswith("ret:")][:1])
        rel, unat = by.get("rel:attribution"), by.get("lim:unattributed")
        n_near = (unat or {}).get("computed", {}).get("anonymous_nearby_count", 0)
        if rel and n_near and unat["computed"].get("case_specific"):
            state, detail = "ambiguous", f"Linked by card scans, but {n_near} anonymous purchases nearby could be anyone's."
        elif rel and n_near:
            state, detail = "partial", f"Card-scan links verified; {n_near} nearby anonymous purchases cannot be linked."
        elif rel:
            state, detail = "verified", "Every listed purchase was linked by a rewards-card scan."
        else:
            state, detail = "missing", "No rewards-card linkage recorded."
        add("linkage", "Rewards-card linkage", state, detail, [(rel or {}).get("evidence_id"), (unat or {}).get("evidence_id")])
    else:
        rel = by.get("rel:account")
        add("linkage", "Account ownership", "verified" if rel else "missing",
            "Account holder confirmed in account records." if rel else "No account-holder link recorded.",
            [(rel or {}).get("evidence_id")])

    base = by.get("baseline")
    if base:
        n = base["computed"].get("baseline_transaction_count", 0)
        ok = base["computed"].get("sufficient", True)
        add("history", "Previous activity", "available" if ok and n >= LOW_PREVIOUS_COUNT else ("partial" if ok else "missing"),
            f"{n} previous transactions over {base['computed'].get('baseline_days')} days"
            + ("" if ok else "; too few to compare.") + (" (thin history)." if ok and n < LOW_PREVIOUS_COUNT else "."),
            [base["evidence_id"], by.get("lim:baseline", {}).get("evidence_id")])
    else:
        add("history", "Previous activity", "missing", "No previous-activity summary.", [])

    ctx = [i for k, i in by.items() if k.startswith("event:")]
    if ctx:
        add("context", "External context", "available", f"{len(ctx)} context event(s) overlap the period, e.g. {ctx[0]['computed'].get('event_name')}.",
            [i["evidence_id"] for i in ctx])

    lim_labels = {"identity": "Customer identity & intent", "retailer_records": "Retailer-side records",
                  "device": "Device / IP / location data", "payment": "Payment-instrument details"}
    for k, label in lim_labels.items():
        it = by.get(f"lim:{k}")
        if it:
            add(k, label, "missing", it["summary"], [it["evidence_id"]])

    counts = {s: sum(1 for i in items if i["state"] == s) for s in STATES}
    return {"case_id": case_id, "overall": c["evidence_completeness"], "snapshot_id": c["current_snapshot_id"],
            "items": items, "counts": counts}


# ================================================================= bookmarks
KINDS = {"transaction", "retailer", "finding", "evidence"}
MAX_NOTE = 2000


def _kind_for(item: dict) -> str:
    return {"transaction": "transaction", "retailer": "retailer", "aggregate_retailer": "retailer",
            "risk_factor": "finding"}.get(item["type"], "evidence")


def bookmarks(case_id: str) -> list[dict]:
    with connect() as con:
        repo.case_row(con, case_id)
        return [dict(r) for r in con.execute(
            """SELECT b.*, r.display_name AS reviewer_name FROM bookmarks b JOIN reviewers r ON r.reviewer_id = b.reviewer_id
               WHERE b.case_id = ? AND b.removed_at_utc IS NULL ORDER BY b.created_at_utc, b.bookmark_id""", (case_id,))]


def save_bookmark(case_id: str, evidence_id: str, reviewer: dict, note: str | None = None, label: str | None = None) -> dict:
    note = (note or "").strip() or None
    if note and len(note) > MAX_NOTE:
        raise ValueError(f"Notes are limited to {MAX_NOTE} characters.")
    with connect() as con:
        repo.case_row(con, case_id)
        item = repo.evidence_item(con, case_id, evidence_id)      # 404 if not this case's evidence
        now = utc_now_iso()
        with tx(con):
            cur = con.execute("SELECT bookmark_id FROM bookmarks WHERE case_id = ? AND evidence_id = ? AND removed_at_utc IS NULL",
                              (case_id, evidence_id)).fetchone()
            if cur:
                bid = cur[0]
                con.execute("UPDATE bookmarks SET note = COALESCE(?, note), updated_at_utc = ? WHERE bookmark_id = ?",
                            (note, now, bid))
            else:
                bid = next_id(con, "BMK")
                con.execute("INSERT INTO bookmarks VALUES (?,?,?,?,?,?,?,?,?,NULL)",
                            (bid, case_id, evidence_id, _kind_for(item), (label or item["title"])[:200], note,
                             reviewer["reviewer_id"], now, now))
        return _one(con, bid)


def update_note(case_id: str, bookmark_id: str, note: str | None) -> dict:
    note = (note or "").strip() or None
    if note and len(note) > MAX_NOTE:
        raise ValueError(f"Notes are limited to {MAX_NOTE} characters.")
    with connect() as con:
        _owned(con, case_id, bookmark_id)
        with tx(con):
            con.execute("UPDATE bookmarks SET note = ?, updated_at_utc = ? WHERE bookmark_id = ?", (note, utc_now_iso(), bookmark_id))
        return _one(con, bookmark_id)


def remove_bookmark(case_id: str, bookmark_id: str) -> dict:
    with connect() as con:
        _owned(con, case_id, bookmark_id)
        now = utc_now_iso()
        with tx(con):
            con.execute("UPDATE bookmarks SET removed_at_utc = ?, updated_at_utc = ? WHERE bookmark_id = ?", (now, now, bookmark_id))
        return _one(con, bookmark_id)


def _owned(con, case_id, bookmark_id):
    r = con.execute("SELECT case_id, removed_at_utc FROM bookmarks WHERE bookmark_id = ?", (bookmark_id,)).fetchone()
    if r is None or r[0] != case_id or r[1] is not None:
        raise repo.NotFound(f"Bookmark {bookmark_id} not found for {case_id}")


def _one(con, bid) -> dict:
    return dict(con.execute("""SELECT b.*, r.display_name AS reviewer_name FROM bookmarks b
                               JOIN reviewers r ON r.reviewer_id = b.reviewer_id WHERE b.bookmark_id = ?""", (bid,)).fetchone())
