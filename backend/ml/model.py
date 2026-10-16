"""Load the experimental model and its evaluation metrics."""
from __future__ import annotations

import json

import joblib
import pandas as pd

from detection.feature_engineering import ml_matrix
from ml.train import METRICS_PATH, MODEL_PATH


def load_model():
    return joblib.load(MODEL_PATH) if MODEL_PATH.exists() else None


def load_metrics() -> dict | None:
    return json.loads(METRICS_PATH.read_text()) if METRICS_PATH.exists() else None


def predict_proba(feats: pd.DataFrame) -> pd.Series:
    model = load_model()
    if model is None:
        return pd.Series([None] * len(feats), index=feats.index)
    return pd.Series(model.predict_proba(ml_matrix(feats))[:, 1].round(3), index=feats.index)
