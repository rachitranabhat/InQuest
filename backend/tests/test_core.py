"""Preserved v1 detection logic: generator determinism and transparent scoring."""
import pandas as pd

import config
from data.synthetic_data_generator import generate as generate_v1
from detection.anomaly_detection import run_detection

TX, CUST, _ = generate_v1(seed=7, n_customers=120)
FEATS, ALERTS = run_detection(TX)


def test_v1_generator_is_deterministic_and_synthetic():
    tx2, _, _ = generate_v1(seed=7, n_customers=120)
    assert len(tx2) == len(TX)
    assert TX.is_synthetic.eq(1).all()


def test_scores_are_bounded_and_sum_of_factors():
    assert ALERTS
    for a in ALERTS:
        assert 0 <= a["risk_score"] <= 100
        assert abs(min(100, sum(f["points"] for f in a["factors"].values())) - a["risk_score"]) < 0.2
        assert a["risk_level"] == config.risk_level(a["risk_score"])


def test_suspicious_customers_score_higher_on_average():
    df = FEATS.merge(CUST, on="customer_id")
    assert df[df.label_suspicious == 1].risk_score.mean() > df[df.label_suspicious == 0].risk_score.mean() + 15


def test_primary_reason_is_not_always_frequency():
    reasons = {a["primary_reason"] for a in ALERTS}
    assert len(reasons) >= 3
