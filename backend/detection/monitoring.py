"""Simulated upstream monitoring: turns synthetic activity into alerts.

PRISM is an investigation layer that starts *after* an alert exists. We have no
access to any real monitoring system, so this module stands in for one, using
the project's own transparent prototype rules (detection/risk_scoring.py) plus a
simple volume rule. It does NOT reproduce DART or any OLG detection method.

Each alert carries: source, type, trigger time, subject, triggering indicators,
the prototype alert score (NOT a fraud probability) and the transaction IDs the
indicators point at.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from detection.anomaly_detection import isolation_forest_scores
from detection.feature_engineering import build_feature_table, window_bounds
from detection.risk_scoring import score_customer

ALERT_SOURCE = "Simulated monitoring feed (PRISM prototype rules)"


def _clean(f: dict) -> dict:
    return {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in f.items()}


def lottery_frame(tx: pd.DataFrame, retailers: pd.DataFrame) -> pd.DataFrame:
    """Attributed lottery purchases in the v1 detection format (customer_id = player)."""
    city = dict(zip(retailers.retailer_id, retailers.city))
    d = tx[(tx.channel == "lottery_terminal") & tx.player_id.notna()].copy()
    d["customer_id"] = d.player_id
    d["location"] = d.retailer_id.map(city)
    return d


def account_frame(tx: pd.DataFrame) -> pd.DataFrame:
    """Deposits per online account (customer_id = account) for the shared features."""
    d = tx[(tx.channel == "online_account") & (tx.transaction_type == "deposit")].copy()
    d["customer_id"] = d.account_id
    d["retailer_id"] = "ONLINE"
    d["location"] = "Online"
    return d


def _alert_type(channel: str, result: dict, window: pd.DataFrame, volume_hit: bool) -> str:
    if channel == "online_account":
        return "Account deposit pattern"
    if result["risk_score"] < config.ALERT_THRESHOLD and volume_hit:
        return "High purchase volume"
    f = result.get("features_for_type") or {}
    rep_val = f.get("repeated_amount_value")
    if (f.get("repeated_amount_count", 0) or 0) >= 3 and rep_val is not None:
        rep_rows = window[window.amount == rep_val]
        if len(rep_rows) and (rep_rows.transaction_type == "Prize Claim").mean() >= 0.5:
            return "Repeated prize claims"
    return "Behavioural deviation"


def run_monitoring(tx: pd.DataFrame, retailers: pd.DataFrame) -> list[dict]:
    """tx: local-time transactions (generator output). Returns alerts sorted by score."""
    tx = tx.copy()
    tx["timestamp"] = pd.to_datetime(tx["timestamp"])
    _, ws, end = window_bounds(tx)
    alerts = []
    for channel, frame in (("lottery_terminal", lottery_frame(tx, retailers)), ("online_account", account_frame(tx))):
        if frame.empty:
            continue
        feats = build_feature_table(frame)
        feats["isolation_forest_score"] = isolation_forest_scores(feats).round(3) if len(feats) > 10 else 0.0
        win = frame[(frame.timestamp >= ws) & (frame.timestamp <= end)]
        by_subject = {k: g for k, g in win.groupby("customer_id")}
        acct_all = tx[(tx.channel == "online_account") & (tx.timestamp >= ws) & (tx.timestamp <= end)]
        acct_by = {k: g for k, g in acct_all.groupby("account_id")}
        for f in feats.to_dict("records"):
            f = _clean(f)
            sid = f["customer_id"]
            w = by_subject.get(sid, win.iloc[0:0])
            if w.empty:
                continue
            res = score_customer(f, w, channel=channel, account_window_tx=acct_by.get(sid))
            volume_hit = channel == "lottery_terminal" and f["transaction_count"] >= config.VOLUME_RULE_MIN_TXNS
            if res["risk_score"] < config.ALERT_THRESHOLD and not volume_hit:
                continue
            rules = []
            if res["risk_score"] >= config.ALERT_THRESHOLD:
                rules.append("Behavioural deviation rule (prototype score ≥ %d)" % config.ALERT_THRESHOLD)
            if volume_hit:
                rules.append("Volume rule (≥ %d attributed purchases in %d days)"
                             % (config.VOLUME_RULE_MIN_TXNS, config.WINDOW_DAYS))
            subject_player = (w.player_id.iloc[0] if channel == "online_account" else sid)
            alerts.append({
                "channel": channel,
                "subject_type": "account" if channel == "online_account" else "player",
                "subject_id": sid,
                "player_id": subject_player,
                "alert_type": _alert_type(channel, {**res, "features_for_type": f}, w, volume_hit),
                "alert_source": ALERT_SOURCE,
                "rules_fired": rules,
                "triggered_at_local": (w.timestamp.max() + pd.Timedelta(minutes=15)).to_pydatetime(),
                "window_start_local": ws.to_pydatetime(),
                "window_end_local": end.to_pydatetime(),
                "features": f,
                **res,
            })
    alerts.sort(key=lambda a: (-a["risk_score"], a["subject_id"]))
    return alerts
