"""Behavioural feature engineering.

For each customer we compare the *review window* (last ``WINDOW_DAYS`` days)
with the customer's own *baseline history* (the ``HISTORY_DAYS`` before it).
Every feature is a plain, explainable number so that a reviewer can trace each
risk point back to transactions.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config

NIGHT_HOURS = range(0, 5)        # 00:00-04:59
RAPID_GAP_MIN = 2.0              # consecutive transactions within 2 minutes
REPEAT_MIN_AMOUNT = 20.0         # repeated identical amounts only count above $20


def window_bounds(tx: pd.DataFrame):
    end = pd.Timestamp(config.SIM_END)
    window_start = (end - pd.Timedelta(days=config.WINDOW_DAYS - 1)).normalize()
    history_start = window_start - pd.Timedelta(days=config.HISTORY_DAYS)
    return history_start, window_start, end


def _peak_60min(ts: pd.Series):
    """Max number of transactions inside any rolling 60-minute window."""
    if ts.empty:
        return 0, None, None
    t = ts.sort_values().to_numpy()
    best, best_i, best_j, j = 0, 0, 0, 0
    for i in range(len(t)):
        while t[i] - t[j] > np.timedelta64(60, "m"):
            j += 1
        if i - j + 1 > best:
            best, best_i, best_j = i - j + 1, i, j
    return int(best), pd.Timestamp(t[best_j]), pd.Timestamp(t[best_i])


def _daily_peak_avg(ts: pd.Series) -> float:
    """Average (over active days) of the busiest 60-minute window that day."""
    if ts.empty:
        return 0.0
    peaks = [_peak_60min(g)[0] for _, g in ts.groupby(ts.dt.date)]
    return float(np.mean(peaks)) if peaks else 0.0


def customer_features(cust_tx: pd.DataFrame, history_start, window_start, end) -> dict:
    hist = cust_tx[(cust_tx.timestamp >= history_start) & (cust_tx.timestamp < window_start)]
    cur = cust_tx[(cust_tx.timestamp >= window_start) & (cust_tx.timestamp <= end)].sort_values("timestamp")

    h_days = config.HISTORY_DAYS
    w_days = config.WINDOW_DAYS

    peak, peak_start, peak_end = _peak_60min(cur.timestamp)
    hist_peak_max, _, _ = _peak_60min(hist.timestamp)

    gaps = cur.timestamp.diff().dt.total_seconds().div(60).dropna()
    rapid_pairs = int((gaps <= RAPID_GAP_MIN).sum())

    big = cur[cur.amount >= REPEAT_MIN_AMOUNT]
    repeat_count, repeat_amount = 0, None
    if not big.empty:
        vc = big.amount.value_counts()
        repeat_count, repeat_amount = int(vc.iloc[0]), float(vc.index[0])
        if repeat_count < 2:
            repeat_count, repeat_amount = 0, None

    hist_locs = set(hist.location)
    hist_rets = set(hist.retailer_id)
    new_locs = sorted(set(cur.location) - hist_locs)
    new_rets = sorted(set(cur.retailer_id) - hist_rets)

    hist_mean = float(hist.amount.mean()) if len(hist) else 0.0
    hist_std = float(hist.amount.std(ddof=0)) if len(hist) > 1 else 0.0
    hist_p95 = float(hist.amount.quantile(0.95)) if len(hist) else 0.0

    cur_night = float(cur.timestamp.dt.hour.isin(NIGHT_HOURS).mean()) if len(cur) else 0.0
    hist_night = float(hist.timestamp.dt.hour.isin(NIGHT_HOURS).mean()) if len(hist) else 0.0

    return {
        "customer_id": cust_tx.customer_id.iloc[0],
        # current window
        "transaction_count": int(len(cur)),
        "total_amount": round(float(cur.amount.sum()), 2),
        "average_transaction_amount": round(float(cur.amount.mean()), 2) if len(cur) else 0.0,
        "max_transaction_amount": round(float(cur.amount.max()), 2) if len(cur) else 0.0,
        "transactions_per_day": round(len(cur) / w_days, 2),
        "peak_hour_transactions": peak,
        "peak_hour_start": peak_start.isoformat() if peak_start is not None else None,
        "peak_hour_end": peak_end.isoformat() if peak_end is not None else None,
        "unique_retailers": int(cur.retailer_id.nunique()),
        "unique_locations": int(cur.location.nunique()),
        "new_locations": new_locs,
        "new_retailers": new_rets,
        "new_location_count": len(new_locs),
        "new_retailer_count": len(new_rets),
        "average_time_between_transactions_min": round(float(gaps.mean()), 1) if len(gaps) else None,
        "rapid_pairs": rapid_pairs,
        "night_transaction_ratio": round(cur_night, 3),
        "night_transaction_count": int(cur.timestamp.dt.hour.isin(NIGHT_HOURS).sum()),
        "repeated_amount_count": repeat_count,
        "repeated_amount_value": repeat_amount,
        # historical baseline
        "hist_transaction_count": int(len(hist)),
        "hist_transactions_per_day": round(len(hist) / h_days, 2),
        "hist_average_amount": round(hist_mean, 2),
        "hist_amount_std": round(hist_std, 2),
        "hist_p95_amount": round(hist_p95, 2),
        "hist_weekly_total": round(float(hist.amount.sum()) / h_days * w_days, 2),
        "hist_peak_hour_avg": round(_daily_peak_avg(hist.timestamp), 2),
        "hist_peak_hour_max": hist_peak_max,
        "hist_night_ratio": round(hist_night, 3),
        "hist_unique_locations": len(hist_locs),
        "hist_unique_retailers": len(hist_rets),
        "home_locations": sorted(hist_locs),
    }


def build_feature_table(tx: pd.DataFrame) -> pd.DataFrame:
    tx = tx.copy()
    tx["timestamp"] = pd.to_datetime(tx["timestamp"])
    hs, ws, end = window_bounds(tx)
    rows = [customer_features(g, hs, ws, end) for _, g in tx.groupby("customer_id")]
    feats = pd.DataFrame(rows)
    # derived ratios (guarded against zero baselines)
    feats["frequency_ratio"] = (
        feats.transactions_per_day / feats.hist_transactions_per_day.clip(lower=0.1)
    ).round(2)
    feats["peak_hour_ratio"] = (
        feats.peak_hour_transactions / feats.hist_peak_hour_avg.clip(lower=1.0)
    ).round(2)
    feats["avg_amount_ratio"] = (
        feats.average_transaction_amount / feats.hist_average_amount.clip(lower=1.0)
    ).round(2)
    feats["max_vs_hist_p95"] = (
        feats.max_transaction_amount / feats.hist_p95_amount.clip(lower=1.0)
    ).round(2)
    feats["spend_ratio"] = (feats.total_amount / feats.hist_weekly_total.clip(lower=1.0)).round(2)
    feats["historical_deviation"] = (feats.spend_ratio - 1).round(2)
    return feats


# Columns used by the ML models (numeric only)
ML_FEATURES = [
    "transaction_count", "total_amount", "average_transaction_amount",
    "transactions_per_day", "peak_hour_transactions", "unique_retailers",
    "unique_locations", "new_location_count", "new_retailer_count", "rapid_pairs",
    "night_transaction_ratio", "repeated_amount_count", "hist_transactions_per_day",
    "hist_average_amount", "frequency_ratio", "peak_hour_ratio", "avg_amount_ratio",
    "max_vs_hist_p95", "spend_ratio", "average_time_between_transactions_min",
]


def ml_matrix(feats: pd.DataFrame) -> pd.DataFrame:
    X = feats[ML_FEATURES].copy()
    X["average_time_between_transactions_min"] = X["average_time_between_transactions_min"].fillna(
        24 * 60 * config.WINDOW_DAYS
    )
    return X.fillna(0).astype(float)
