"""Scenario Lab: create a fresh synthetic subject for a predefined scenario,
run the simulated monitoring rules on it, and open a real case with evidence.

New records are only ever appended; nothing existing is modified.
"""
from __future__ import annotations

import pandas as pd

import config
from data.generator import CURATED, scenario_subject
from database.db import connect, get_meta, next_ids, set_meta, tx
from detection.feature_engineering import build_feature_table, window_bounds
from detection.monitoring import ALERT_SOURCE, _alert_type, _clean, account_frame, lottery_frame
from detection.risk_scoring import score_customer
from pipeline import case_context, insert_transactions, load_transactions, network_daily

DESCRIPTIONS = {
    "lottery_burst": "A rewards-card player suddenly makes dozens of purchases within one hour across nearby retailers.",
    "multi_retailer": "Purchases spread over several retailers in the player's home city on consecutive days — "
                      "unusual spread, but each visit is ordinary in size.",
    "deposit_anomaly": "An online account deposits several large amounts in quick succession, barely plays, and "
                       "withdraws almost everything.",
    "incomplete_attribution": "A modest rise in scanned purchases alongside many anonymous sales at the same "
                              "retailers and minutes — the records cannot say who made them.",
    "high_volume_legit": "A player who always buys a lot trips the simple volume rule, although behaviour matches "
                         "their own history.",
    "jackpot_week": "Increased purchases that coincide with a network-wide jackpot surge.",
    "shared_retailer": "A player whose burst of purchases overlaps with other players at the same store — "
                       "co-location, not a proven relationship.",
    "prize_claims": "Repeated identical high-value prize claims at several retailers.",
}


def catalogue() -> list[dict]:
    return [{"key": k, "title": t, "description": DESCRIPTIONS.get(k, ""), "scenario": s} for k, s, t in CURATED]


def run(key: str, reviewer_id: str | None = None) -> dict:
    if key not in {k for k, _, _ in CURATED}:
        raise ValueError(f"Unknown scenario '{key}'")
    with connect() as con:
        retailers = pd.read_sql_query("SELECT * FROM retailers", con)
        locations = pd.read_sql_query("SELECT * FROM locations", con)
        events = pd.read_sql_query("SELECT * FROM events", con)
        run_no = int(get_meta(con, f"lab_runs:{key}", 0)) + 1
        sub = scenario_subject(key, run_no, retailers)
        tx_new = sub["transactions"].copy()
        with tx(con):
            pid = _next_player(con)
            tx_new.loc[tx_new.player_id == "PLY-NEW", "player_id"] = pid
            home = locations.set_index("city").loc[sub["home_city"], "location_id"]
            con.execute("INSERT INTO players VALUES (?,?,?,?)", (pid, home, 1, int(sub["account"] is not None)))
            acc_id = None
            if sub["account"] is not None:
                acc_id = _next_account(con)
                tx_new.loc[tx_new.account_id == "ACC-NEW", "account_id"] = acc_id
                con.execute("INSERT INTO accounts VALUES (?,?,?)", (acc_id, pid, "2026-03-01"))
            ids = next_ids(con, "TXN", len(tx_new), width=7)
            tx_new["transaction_id"] = ids
            tx_new["ticket_id"] = [f"TKT-L{i[4:]}" if c == "lottery_terminal" else None
                                   for i, c in zip(ids, tx_new.channel)]
            insert_transactions(con, tx_new)
            set_meta(con, f"lab_runs:{key}", run_no)
        # monitoring on this subject only
        alert = _score_subject(tx_new, retailers, pid, acc_id)
        _, ws, we = window_bounds(tx_new)
        rets = list(set(tx_new.retailer_id.dropna()))
        if rets:
            q = (f"WHERE channel = 'lottery_terminal' AND retailer_id IN ({','.join('?' * len(rets))}) "
                 f"AND timestamp_utc >= ?")
            nearby = load_transactions(con, q, (*rets, (ws - pd.Timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")))
        else:
            nearby = load_transactions(con, "WHERE 1 = 0")
        ctx_tx = pd.concat([nearby[~nearby.transaction_id.isin(tx_new.transaction_id)], load_transactions(
            con, "WHERE player_id = ? OR account_id = ?", (pid, acc_id or "-"))], ignore_index=True)
        nd = network_daily(con)
        from pipeline import create_case
        title = {k: t for k, _, t in CURATED}[key]
        with tx(con):
            case_id = create_case(con, alert, case_context(alert, ctx_tx, retailers, locations, events, nd),
                                  curated_key=key, scenario_title=f"Scenario Lab: {title} (run {run_no})",
                                  origin="scenario_lab")
    return {"case_id": case_id, "scenario": key, "run": run_no, "subject_id": alert["subject_id"],
            "rules_fired": alert["rules_fired"], "alert_score": alert["risk_score"]}


def _next_player(con) -> str:
    n = con.execute("SELECT MAX(CAST(SUBSTR(player_id, 5) AS INTEGER)) FROM players").fetchone()[0] or 0
    return f"PLY-{n + 1:05d}"


def _next_account(con) -> str:
    n = con.execute("SELECT MAX(CAST(SUBSTR(account_id, 5) AS INTEGER)) FROM accounts").fetchone()[0] or 10000
    return f"ACC-{n + 1}"


def _score_subject(tx_new: pd.DataFrame, retailers, pid, acc_id) -> dict:
    tx_new = tx_new.copy()
    tx_new["timestamp"] = pd.to_datetime(tx_new["timestamp"])
    _, ws, end = window_bounds(tx_new)
    channel = "online_account" if acc_id else "lottery_terminal"
    frame = account_frame(tx_new) if acc_id else lottery_frame(tx_new, retailers)
    f = _clean(build_feature_table(frame).to_dict("records")[0])
    f["isolation_forest_score"] = None
    win = frame[(frame.timestamp >= ws) & (frame.timestamp <= end)]
    acct_win = tx_new[(tx_new.channel == "online_account") & (tx_new.timestamp >= ws) & (tx_new.timestamp <= end)]
    res = score_customer(f, win, channel=channel, account_window_tx=acct_win if acc_id else None)
    volume_hit = channel == "lottery_terminal" and f["transaction_count"] >= config.VOLUME_RULE_MIN_TXNS
    rules = []
    if res["risk_score"] >= config.ALERT_THRESHOLD:
        rules.append("Behavioural deviation rule (prototype score ≥ %d)" % config.ALERT_THRESHOLD)
    if volume_hit:
        rules.append("Volume rule (≥ %d attributed purchases in %d days)" % (config.VOLUME_RULE_MIN_TXNS, config.WINDOW_DAYS))
    if not rules:
        rules.append("Scenario Lab trigger (no prototype rule fired)")
    return {"channel": channel, "subject_type": "account" if acc_id else "player", "subject_id": acc_id or pid,
            "player_id": pid, "alert_type": _alert_type(channel, {**res, "features_for_type": f}, win, volume_hit),
            "alert_source": ALERT_SOURCE + " · Scenario Lab", "rules_fired": rules,
            "triggered_at_local": (win.timestamp.max() + pd.Timedelta(minutes=15)).to_pydatetime(),
            "window_start_local": ws.to_pydatetime(), "window_end_local": end.to_pydatetime(), "features": f, **res}
