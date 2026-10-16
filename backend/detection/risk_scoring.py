"""Transparent PROTOTYPE risk scoring.

This is an illustrative methodology designed for explainability. It is NOT any
real organisation's scoring system.

Each factor earns between 0 and its maximum points using a simple linear ramp
between a "starts to matter" value and a "fully anomalous" value:

    points = max_points * clip((measurement - start) / (full - start), 0, 1)

The function ``score_customer`` returns the total, the per-factor breakdown,
human-readable evidence strings and the IDs of the transactions that drove each
factor, so every point in the score can be traced back to data.
"""
from __future__ import annotations

import math

import pandas as pd

import config
from detection.feature_engineering import NIGHT_HOURS, RAPID_GAP_MIN, REPEAT_MIN_AMOUNT



def _ramp(x, start, full) -> float:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return 0.0
    return float(min(1.0, max(0.0, (x - start) / (full - start))))


def _raw(x, start, full) -> float:
    """Unclipped ramp — how far past the 'fully anomalous' point a measurement goes.
    Used only to break ties when choosing the primary reason (several factors can sit at 100%)."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return 0.0
    return float(max(0.0, (x - start) / (full - start)))


# Human-readable description of each rule (shown in the UI's methodology panel)
RULES = {
    "frequency": "max of: daily rate vs. baseline (1.5x→5x) and busiest 60-min window vs. baseline busiest hour (1.5x→6x)",
    "value": "max of: average amount vs. baseline (1.5x→5x) and largest amount vs. baseline 95th percentile (1.5x→6x)",
    "location": "max of: cities not seen in baseline (0→3) and 0.6 × new retailers (2→8)",
    "timing": "share of 00:00-04:59 activity above baseline share (+5pp→+40pp), needs ≥3 night transactions",
    "historical": "window spend vs. baseline spend for an equal period (1.5x→8x)",
    "playthrough": "withdrawn ÷ deposited (30%→90%) × share of deposits never wagered (40%→90%)",
    "pattern": "max of: back-to-back transactions within 2 min (2→10 pairs) and identical amounts ≥$20 (3→8 repeats)",
}


BASELINE_DEPENDENT = ("frequency", "value", "location", "historical")
MIN_BASELINE_TXNS = 5


def score_customer(f: dict, cust_window_tx: pd.DataFrame, channel: str = "lottery_terminal",
                   account_window_tx: pd.DataFrame | None = None) -> dict:
    """Score one subject. For online accounts, ``cust_window_tx`` holds the deposits and
    ``account_window_tx`` every account transaction in the window (for play-through)."""
    tx = cust_window_tx.sort_values("timestamp")
    factors = {}
    weights = config.ACCOUNT_FACTOR_WEIGHTS if channel == "online_account" else config.FACTOR_WEIGHTS

    # ---------------------------------------------------------------- frequency
    s_rate = _ramp(f["frequency_ratio"], 1.5, 5)
    s_peak = _ramp(f["peak_hour_ratio"], 1.5, 6)
    ids = []
    if f["peak_hour_start"]:
        ps, pe = pd.Timestamp(f["peak_hour_start"]), pd.Timestamp(f["peak_hour_end"])
        ids = tx[(tx.timestamp >= ps) & (tx.timestamp <= pe)].transaction_id.tolist()
    factors["frequency"] = {
        "share": max(s_rate, s_peak),
        "intensity": max(_raw(f["frequency_ratio"], 1.5, 5), _raw(f["peak_hour_ratio"], 1.5, 6)),
        "measurement": f"{f['peak_hour_transactions']} txns in busiest hour vs. {f['hist_peak_hour_avg']} baseline; "
                       f"{f['transactions_per_day']}/day vs. {f['hist_transactions_per_day']}/day",
        "evidence": [
            f"{f['transaction_count']} transactions in the {config.WINDOW_DAYS}-day review window "
            f"({f['transactions_per_day']}/day vs. a baseline of {f['hist_transactions_per_day']}/day, "
            f"{f['frequency_ratio']}x)",
            f"{f['peak_hour_transactions']} transactions within a single 60-minute period "
            f"(baseline busiest hour averages {f['hist_peak_hour_avg']}, {f['peak_hour_ratio']}x)",
        ],
        "transactions": ids if max(s_rate, s_peak) > 0 else [],
    }

    # -------------------------------------------------------------------- value
    s_avg = _ramp(f["avg_amount_ratio"], 1.5, 5)
    s_max = _ramp(f["max_vs_hist_p95"], 1.5, 6)
    thr = max(f["hist_p95_amount"] * 1.5, 1)
    ids = tx[tx.amount >= thr].transaction_id.tolist()
    factors["value"] = {
        "share": max(s_avg, s_max),
        "intensity": max(_raw(f["avg_amount_ratio"], 1.5, 5), _raw(f["max_vs_hist_p95"], 1.5, 6)),
        "measurement": f"avg ${f['average_transaction_amount']:,.2f} vs. ${f['hist_average_amount']:,.2f}; "
                       f"max ${f['max_transaction_amount']:,.2f} vs. p95 ${f['hist_p95_amount']:,.2f}",
        "evidence": [
            f"Average transaction ${f['average_transaction_amount']:,.2f} vs. baseline "
            f"${f['hist_average_amount']:,.2f} ({f['avg_amount_ratio']}x)",
            f"Largest transaction ${f['max_transaction_amount']:,.2f} vs. baseline 95th percentile "
            f"${f['hist_p95_amount']:,.2f} ({f['max_vs_hist_p95']}x)",
            f"{len(ids)} transaction(s) at or above 1.5x the baseline 95th percentile (${thr:,.2f})",
        ],
        "transactions": ids if max(s_avg, s_max) > 0 else [],
    }

    # ----------------------------------------------------------------- location
    if channel == "online_account":
        factors["playthrough"] = _playthrough(account_window_tx if account_window_tx is not None else tx)
    s_loc = _ramp(f["new_location_count"], 0, 3)
    s_ret = 0.6 * _ramp(f["new_retailer_count"], 2, 8)
    new_locs = f["new_locations"]
    ids = tx[tx.location.isin(new_locs) | tx.retailer_id.isin(f["new_retailers"])].transaction_id.tolist()
    loc_factor = {
        "share": max(s_loc, s_ret),
        "intensity": max(_raw(f["new_location_count"], 0, 3), 0.6 * _raw(f["new_retailer_count"], 2, 8)),
        "measurement": f"{f['new_location_count']} new cities, {f['new_retailer_count']} new retailers",
        "evidence": [
            f"Activity in {f['unique_locations']} location(s) and at {f['unique_retailers']} retailer(s) "
            f"during the window",
            (f"{len(new_locs)} location(s) not seen in baseline: {', '.join(new_locs)}"
             if new_locs else "No locations outside the customer's baseline"),
            f"{f['new_retailer_count']} retailer(s) not used during the baseline period",
            f"Baseline locations: {', '.join(f['home_locations']) or 'none recorded'}",
        ],
        "transactions": ids if max(s_loc, s_ret) > 0 else [],
    }
    if channel != "online_account":
        factors["location"] = loc_factor

    # ------------------------------------------------------------------- timing
    diff = f["night_transaction_ratio"] - f["hist_night_ratio"]
    s_time = _ramp(diff, 0.05, 0.40) if f["night_transaction_count"] >= 3 else 0.0
    ids = tx[tx.timestamp.dt.hour.isin(NIGHT_HOURS)].transaction_id.tolist()
    factors["timing"] = {
        "share": s_time,
        "intensity": _raw(diff, 0.05, 0.40) if f["night_transaction_count"] >= 3 else 0.0,
        "measurement": f"{f['night_transaction_ratio']:.0%} night activity vs. {f['hist_night_ratio']:.0%} baseline",
        "evidence": [
            f"{f['night_transaction_count']} transaction(s) between 00:00 and 04:59 "
            f"({f['night_transaction_ratio']:.0%} of window activity vs. {f['hist_night_ratio']:.0%} baseline)",
        ],
        "transactions": ids if s_time > 0 else [],
    }

    # -------------------------------------------------------------- historical
    s_hist = _ramp(f["spend_ratio"], 1.5, 8)
    factors["historical"] = {
        "share": s_hist,
        "intensity": _raw(f["spend_ratio"], 1.5, 8),
        "measurement": f"${f['total_amount']:,.2f} vs. ${f['hist_weekly_total']:,.2f} expected",
        "evidence": [
            f"Total window value ${f['total_amount']:,.2f} vs. ${f['hist_weekly_total']:,.2f} for an equivalent "
            f"baseline period ({f['spend_ratio']}x, {f['historical_deviation']:+.0%} deviation)",
        ],
        "transactions": [],
    }

    # ------------------------------------------------------------------ pattern
    s_rapid = _ramp(f["rapid_pairs"], 2, 10)
    s_rep = _ramp(f["repeated_amount_count"], 3, 8)
    gaps = tx.timestamp.diff().dt.total_seconds().div(60)
    rapid_mask = (gaps <= RAPID_GAP_MIN) | (gaps.shift(-1) <= RAPID_GAP_MIN)
    ids = set(tx[rapid_mask.fillna(False)].transaction_id) if s_rapid > 0 else set()
    if s_rep > 0 and f["repeated_amount_value"] is not None:
        ids |= set(tx[(tx.amount == f["repeated_amount_value"]) & (tx.amount >= REPEAT_MIN_AMOUNT)].transaction_id)
    rep_txt = (f"Amount ${f['repeated_amount_value']:,.2f} repeated {f['repeated_amount_count']} times"
               if f["repeated_amount_value"] is not None else "No repeated identical amounts ≥ $20")
    factors["pattern"] = {
        "share": max(s_rapid, s_rep),
        "intensity": max(_raw(f["rapid_pairs"], 2, 10), _raw(f["repeated_amount_count"], 3, 8)),
        "measurement": f"{f['rapid_pairs']} rapid pairs; {f['repeated_amount_count']} identical amounts",
        "evidence": [
            f"{f['rapid_pairs']} pair(s) of consecutive transactions less than {RAPID_GAP_MIN:.0f} minutes apart",
            rep_txt,
        ],
        "transactions": sorted(ids),
    }

    # -------------------------------------------------- insufficient baseline
    baseline_ok = f.get("hist_transaction_count", 0) >= MIN_BASELINE_TXNS
    if not baseline_ok:
        for key in BASELINE_DEPENDENT:
            if key in factors:
                factors[key]["share"] = 0.0
                factors[key]["intensity"] = 0.0
                factors[key]["transactions"] = []
                factors[key]["evidence"].append(
                    f"Not scored: the baseline has only {f.get('hist_transaction_count', 0)} transaction(s), "
                    f"fewer than {MIN_BASELINE_TXNS}, so comparisons with history are unreliable")

    # ------------------------------------------------------------------ totals
    order = {k: i for i, k in enumerate(weights)}
    factors = dict(sorted(factors.items(), key=lambda kv: order[kv[0]]))
    for key, fac in factors.items():
        fac["key"] = key
        fac["label"] = config.FACTOR_LABELS[key]
        fac["max_points"] = weights[key]
        fac["points"] = round(weights[key] * fac["share"], 1)
        fac["intensity"] = round(float(fac.get("intensity", fac["share"])), 3)
        fac["triggered"] = fac["share"] >= config.FACTOR_TRIGGER_RATIO
        fac["rule"] = RULES[key]
        fac["share"] = round(fac["share"], 3)

    total = round(min(100.0, sum(x["points"] for x in factors.values())), 1)
    # strongest factor = highest share; ties (several at 100%) broken by how far past the threshold
    ranked = sorted(factors.values(), key=lambda x: (x["share"], x["intensity"], x["points"]), reverse=True)
    primary = ranked[0]["label"] if ranked[0]["points"] > 0 else "No dominant factor"
    return {
        "risk_score": total,
        "risk_level": config.risk_level(total),
        "primary_reason": primary,
        "factors": factors,
        "triggered_count": sum(1 for x in factors.values() if x["triggered"]),
        "baseline_sufficient": baseline_ok,
        "channel": channel,
    }


def _playthrough(atx: pd.DataFrame) -> dict:
    by = atx.groupby("transaction_type").amount.sum() if len(atx) else pd.Series(dtype=float)
    dep, wag = float(by.get("deposit", 0.0)), float(by.get("wager", 0.0))
    wd, pay = float(by.get("withdrawal", 0.0)), float(by.get("payout", 0.0))
    played = min(1.0, wag / dep) if dep else 1.0
    withdrawn = wd / dep if dep else 0.0
    share = _ramp(withdrawn, 0.30, 0.90) * _ramp(1 - played, 0.40, 0.90)
    intensity = _raw(withdrawn, 0.30, 0.90) * _raw(1 - played, 0.40, 0.90)
    ids = atx[atx.transaction_type.isin(["deposit", "withdrawal"])].transaction_id.tolist() if share > 0 else []
    return {
        "share": share, "intensity": intensity,
        "measurement": f"wagered {played:.0%} of ${dep:,.2f} deposited; withdrew ${wd:,.2f} ({withdrawn:.0%})",
        "evidence": [
            f"Deposits ${dep:,.2f}, wagers ${wag:,.2f}, payouts ${pay:,.2f}, withdrawals ${wd:,.2f} in the window",
            f"{played:.0%} of deposited funds were wagered; withdrawals equal {withdrawn:.0%} of deposits",
        ],
        "transactions": ids,
        "values": {"deposits": round(dep, 2), "wagers": round(wag, 2), "payouts": round(pay, 2),
                   "withdrawals": round(wd, 2), "played_ratio": round(played, 3), "withdrawn_ratio": round(withdrawn, 3)},
    }
