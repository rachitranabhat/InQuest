"""Detection engine: combines the transparent rule-based score with an
unsupervised anomaly signal (Isolation Forest).

The Isolation Forest result is shown to reviewers as a *supplementary* signal
only. It does not contribute points to the prototype risk score, because its
reasoning is harder to explain than the rule-based factors.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

import config
from detection.feature_engineering import build_feature_table, ml_matrix, window_bounds
from detection.risk_scoring import score_customer


def isolation_forest_scores(feats: pd.DataFrame, seed: int = config.RANDOM_SEED) -> np.ndarray:
    """Return an anomaly score in [0, 1] per customer (1 = most unusual)."""
    X = ml_matrix(feats)
    model = IsolationForest(n_estimators=300, contamination="auto", random_state=seed)
    model.fit(X)
    raw = -model.score_samples(X)  # higher = more anomalous
    return (raw - raw.min()) / (raw.max() - raw.min() + 1e-9)


def run_detection(tx: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Score every customer and return (feature_table, alerts)."""
    tx = tx.copy()
    tx["timestamp"] = pd.to_datetime(tx["timestamp"])
    feats = build_feature_table(tx)
    feats["isolation_forest_score"] = isolation_forest_scores(feats).round(3)

    _, window_start, end = window_bounds(tx)
    window_tx = tx[(tx.timestamp >= window_start) & (tx.timestamp <= end)]
    by_cust = {cid: g for cid, g in window_tx.groupby("customer_id")}

    alerts, scores = [], []
    for f in feats.to_dict("records"):
        # DataFrame round-trips turn None into NaN; restore None for clean JSON evidence
        f = {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in f.items()}
        ctx = by_cust.get(f["customer_id"], window_tx.iloc[0:0])
        result = score_customer(f, ctx)
        scores.append(result["risk_score"])
        if result["risk_score"] >= config.ALERT_THRESHOLD and len(ctx):
            alerts.append(
                {
                    "customer_id": f["customer_id"],
                    "features": f,
                    "window_start": window_start.isoformat(),
                    "window_end": end.isoformat(),
                    "created_at": (ctx.timestamp.max() + pd.Timedelta(minutes=15)).isoformat(),
                    **result,
                }
            )
    feats["risk_score"] = scores
    alerts.sort(key=lambda a: a["risk_score"], reverse=True)
    return feats, alerts
