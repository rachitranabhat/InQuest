"""Data & Methodology: what the synthetic dataset contains and how detection performs on it.

* overview — any signed-in reviewer: dataset version, generation configuration, record counts, time range
  and the AGGREGATE scenario composition (no per-player labels).
* labels, evaluation — senior investigator only: the simulator's per-player answer key and the detection
  evaluation. These are development/demo tools, kept off every investigator screen.
Identity records are never part of any response here.
"""
from __future__ import annotations

import json

from database.db import connect, get_meta, loads, schema_version
from data import dataset_spec
from services.restricted import require_senior
from services.workflow import WorkflowError

LABEL_FILTERS = {"category": "scenario_category", "planted": "label_suspicious", "profile": "profile"}


def _require_reviewer(rv):
    if rv is None:
        raise WorkflowError("A simulated reviewer session is required. Choose a reviewer first.", 401)
    return rv


def overview(rv) -> dict:
    _require_reviewer(rv)
    with connect() as con:
        q = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
        counts = {
            "players": q("SELECT COUNT(*) FROM players"),
            "accounts": q("SELECT COUNT(*) FROM accounts"),
            "transactions": q("SELECT COUNT(*) FROM transactions"),
            "retailers": q("SELECT COUNT(*) FROM retailers"),
            "terminals": q("SELECT COUNT(DISTINCT terminal_id) FROM transactions WHERE terminal_id IS NOT NULL"),
            "alerts": q("SELECT COUNT(*) FROM alerts"),
            "cases": q("SELECT COUNT(*) FROM cases"),
            "scenario_lab_cases": q("SELECT COUNT(*) FROM cases WHERE origin = 'scenario_lab'"),
            "evidence_items": q("SELECT COUNT(*) FROM evidence"),
        }
        t0, t1 = con.execute("SELECT MIN(timestamp_utc), MAX(timestamp_utc) FROM transactions").fetchone()
        by_channel = dict(con.execute("SELECT channel, COUNT(*) FROM transactions GROUP BY channel").fetchall())
        attributed = q("SELECT COUNT(*) FROM transactions WHERE player_id IS NOT NULL")
        dv = con.execute("SELECT * FROM dataset_versions ORDER BY created_at_utc DESC LIMIT 1").fetchone()
        cats = con.execute("SELECT scenario_category, COUNT(*) FROM scenario_labels GROUP BY scenario_category "
                           "ORDER BY scenario_category").fetchall()
        meta_version = get_meta(con, "dataset_version")
    return {
        "dataset_version": dv["dataset_version"] if dv else meta_version,
        "seed": dv["seed"] if dv else None, "generator": dv["generator"] if dv else None,
        "generation_config": loads(dv["config_json"], {}) if dv else None,
        "generated_counts": loads(dv["counts_json"], {}) if dv else None,
        "counts": counts, "time_range_utc": [t0, t1],
        "transactions_by_channel": by_channel,
        "attribution": {"attributed": attributed, "anonymous": counts["transactions"] - attributed},
        "scenario_categories": [{"category": c, "players": n, "description": dataset_spec.CATEGORY_DESCRIPTIONS.get(c, "")}
                                for c, n in cats],
        "storage": "PostgreSQL" if getattr(con, "backend", "sqlite") == "postgres" else "SQLite",
        "schema_version": schema_version(),
        "notes": [
            "All records are synthetic. Scenario categories describe what the simulator planted, not investigator findings.",
            "A planted suspicious pattern is not confirmed fraud; AML-like patterns are not proof of money laundering.",
        ],
    }


def labels(rv, *, category=None, planted=None, profile=None, q=None, limit=50, offset=0) -> dict:
    require_senior(rv)
    where, args = [], []
    for key, val in (("category", category), ("planted", planted), ("profile", profile)):
        if val not in (None, ""):
            where.append(f"l.{LABEL_FILTERS[key]} = ?")
            args.append(int(val) if key == "planted" else val)
    if q:
        where.append("l.player_id LIKE ?")
        args.append(f"%{q}%")
    w = f" WHERE {' AND '.join(where)}" if where else ""
    with connect() as con:
        total = con.execute(f"SELECT COUNT(*) FROM scenario_labels l{w}", args).fetchone()[0]
        rows = con.execute(f"""
            SELECT l.player_id, l.profile, l.scenario, l.scenario_category, l.curated_key, l.label_suspicious,
                   l.dataset_version,
                   (SELECT COUNT(*) FROM cases c WHERE c.player_id = l.player_id AND c.origin = 'monitoring') AS monitoring_cases
            FROM scenario_labels l{w} ORDER BY l.player_id LIMIT ? OFFSET ?""", [*args, limit, offset]).fetchall()
    return {"total": total, "limit": limit, "offset": offset, "rows": [dict(r) for r in rows],
            "notice": "Simulation answer key for development and demo evaluation. Not shown on investigator screens."}


def evaluation(rv) -> dict:
    require_senior(rv)
    from evaluation.detection_eval import CAVEAT, RESULTS_PATH, evaluate_database
    stored = json.loads(RESULTS_PATH.read_text(encoding="utf-8")) if RESULTS_PATH.exists() else None
    return {"current_database": evaluate_database(), "heldout": stored, "caveat": CAVEAT,
            "how_to_refresh": "python -m evaluation.detection_eval (from backend/)"}
