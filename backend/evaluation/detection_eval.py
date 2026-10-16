"""Detection evaluation against the simulator's planted labels — synthetic data only.

What is evaluated: PRISM's rule-based monitoring (detection/monitoring.py), i.e. "did a player get an
alert?" versus "did the simulator plant a suspicious pattern for this player?". Unit = synthetic player
(an online-account alert counts for its account holder).

Leakage controls:
* Monitoring never reads labels; labels are joined only here, after alerts exist.
* The monitoring rules and thresholds were written while looking at the default dataset (seed 42), so seed
  42 is reported as the DEVELOPMENT set. Headline numbers come from HELD-OUT worlds generated with seeds
  that were never used while writing or tuning the rules (HELDOUT_SEEDS). Nothing is trained, so there is
  no train/test overlap to manage; if a learned model is added it must be fitted on development seeds only.
* Curated demo subjects are excluded from the population metrics (they are hand-designed showcase cases)
  and reported separately.

Limits (always shown with the numbers): the simulator and the rules were designed together, so these
figures are optimistic and say nothing about real-world performance. They are not production validation.

    python -m evaluation.detection_eval            (from backend/; ~15 s per seed)
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import config

DEV_SEED = 42
HELDOUT_SEEDS = [1001, 2002, 3003]
RESULTS_PATH = Path(__file__).resolve().parent / "results" / "detection_eval.json"
CAVEAT = ("Synthetic data only. The simulator and the monitoring rules were designed together, so these "
          "figures are optimistic and are not evidence of real-world or production performance.")


def metrics(y_true: list[int], y_pred: list[int]) -> dict:
    tp = sum(1 for t, p in zip(y_true, y_pred) if t and p)
    fp = sum(1 for t, p in zip(y_true, y_pred) if not t and p)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t and not p)
    tn = sum(1 for t, p in zip(y_true, y_pred) if not t and not p)
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else (0.0 if prec is not None and rec is not None else None)
    r = lambda v: None if v is None else round(v, 3)  # noqa: E731
    return {"n": len(y_true), "positives": tp + fn, "precision": r(prec), "recall": r(rec), "f1": r(f1),
            "false_positive_rate": r(fp / (fp + tn) if fp + tn else None),
            "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
            "matrix_layout": "rows = planted label (suspicious, not suspicious); columns = alerted, not alerted"}


def _score(labels: pd.DataFrame, alerted: set[str]) -> dict:
    from data.dataset_spec import category_for
    df = labels.copy()
    df["category"] = [category_for(p, s) for p, s in zip(df.profile, df.scenario)]
    df["alerted"] = df.player_id.isin(alerted).astype(int)
    pop = df[~df.profile.isin(["curated", "curated_partner"])]
    by_cat = (pop.groupby("category").agg(players=("player_id", "size"), alerted=("alerted", "sum"))
              .assign(alert_rate=lambda x: (x.alerted / x.players).round(3)).reset_index().to_dict("records"))
    cur = df[df.profile.isin(["curated", "curated_partner"])]
    return {"population": metrics(pop.label_suspicious.astype(int).tolist(), pop.alerted.tolist()),
            "by_category": by_cat,
            "curated_subjects": [{"curated_key": r.curated_key, "category": r.category, "planted": int(r.label_suspicious),
                                  "alerted": int(r.alerted)} for r in cur.itertuples()]}


def evaluate_world(seed: int, n_players: int = config.N_CUSTOMERS) -> dict:
    from data.generator import generate
    from detection.monitoring import run_monitoring
    w = generate(seed=seed, n_players=n_players)
    alerts = run_monitoring(w["transactions"], w["retailers"])      # labels are not passed in
    alerted = {a["player_id"] for a in alerts if a.get("player_id")}
    out = _score(w["labels"], alerted)
    out.update({"seed": seed, "n_players": n_players, "alerts": len(alerts)})
    return out


def evaluate_database() -> dict | None:
    """Development-set metrics from the database: monitoring cases vs scenario_labels (Scenario Lab cases excluded)."""
    from database.db import connect
    with connect() as con:
        lab = pd.DataFrame([dict(r) for r in con.execute(
            "SELECT player_id, profile, scenario, curated_key, label_suspicious FROM scenario_labels")])
        if lab.empty:
            return None
        alerted = {r[0] for r in con.execute("SELECT DISTINCT player_id FROM cases WHERE origin = 'monitoring' AND player_id IS NOT NULL")}
        dv = con.execute("SELECT dataset_version, seed FROM dataset_versions ORDER BY created_at_utc DESC LIMIT 1").fetchone()
    lab["scenario"] = lab["scenario"].fillna("")
    out = _score(lab, alerted)
    out.update({"dataset_version": dv[0] if dv else None, "seed": dv[1] if dv else None, "role": "development"})
    return out


def run(seeds=HELDOUT_SEEDS, n_players: int = config.N_CUSTOMERS) -> dict:
    held = [evaluate_world(s, n_players) for s in seeds]
    pooled_cm = {k: sum(h["population"]["confusion_matrix"][k] for h in held) for k in ("tp", "fp", "fn", "tn")}
    y_true = [1] * (pooled_cm["tp"] + pooled_cm["fn"]) + [0] * (pooled_cm["fp"] + pooled_cm["tn"])
    y_pred = [1] * pooled_cm["tp"] + [0] * pooled_cm["fn"] + [1] * pooled_cm["fp"] + [0] * pooled_cm["tn"]
    from timeutil import utc_now_iso
    return {"evaluated_at_utc": utc_now_iso(), "unit": "synthetic player", "detector": "rule-based monitoring (detection/monitoring.py)",
            "development": evaluate_world(DEV_SEED, n_players), "heldout": held,
            "heldout_pooled": metrics(y_true, y_pred), "heldout_seeds": list(seeds), "caveat": CAVEAT,
            "method": ("Held-out worlds are generated with seeds never used while writing the rules; labels are joined "
                       "only after monitoring has run; curated demo subjects are reported separately.")}


if __name__ == "__main__":
    res = run()
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(json.dumps({"development": res["development"]["population"], "heldout_pooled": res["heldout_pooled"]}, indent=2))
