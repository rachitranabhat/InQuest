"""Export and import the versioned synthetic dataset (CSV or Parquet).

    python -m data.dataset_io export --out ../datasets/synth            # generator output, CSV
    python -m data.dataset_io export --out ../datasets/synth --format parquet
    python -m data.dataset_io export --out ../datasets/db --source db   # what the current database holds
    python -m data.dataset_io import ../datasets/synth                  # build an EMPTY database from files

A dataset folder holds one file per table plus ``manifest.json`` (dataset version, seed, generation
configuration, record counts, label composition and a SHA-256 per file).

Import is safe and repeatable: it checks every file hash and the dataset version, then loads the rows
through the normal build (monitoring rules → cases → evidence snapshots) into an empty database. If the
database already holds a dataset, nothing is written, so rows are never duplicated. ``scenario_labels``
is the simulator's answer key; it is exported for evaluation, never shown to investigators.
Identity records (player_identities) are never exported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

import config
from data import dataset_spec

RAW = ["locations", "retailers", "players", "accounts", "events", "transactions", "scenario_labels"]


def _write(df: pd.DataFrame, path: Path, fmt: str) -> Path:
    if fmt == "parquet":
        try:
            import pyarrow  # noqa: F401
        except ImportError as e:
            raise SystemExit("Parquet needs pyarrow: pip install -r requirements-v2.txt (or use --format csv)") from e
        f = path.with_suffix(".parquet")
        df.to_parquet(f, index=False)
    else:
        f = path.with_suffix(".csv")
        df.to_csv(f, index=False, lineterminator="\n")
    return f


def _read(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, keep_default_na=False, na_values=[""], dtype=str)


def _sha(f: Path) -> str:
    return hashlib.sha256(f.read_bytes()).hexdigest()


def frames_from_generator() -> dict[str, pd.DataFrame]:
    from data.generator import generate
    from timeutil import local_series_to_utc_iso
    w = generate()
    tx = w["transactions"].copy()
    tx["timestamp_utc"] = local_series_to_utc_iso(tx["timestamp"])
    tx["timestamp_local"] = pd.to_datetime(tx["timestamp"]).dt.strftime("%Y-%m-%dT%H:%M:%S")
    from pipeline import TX_COLS
    labels = pd.DataFrame(dataset_spec.label_rows(w["labels"]),
                          columns=["player_id", "dataset_version", "profile", "scenario", "scenario_category",
                                   "curated_key", "label_suspicious", "label_source"])
    return {"locations": w["locations"][["location_id", "city", "region"]], "retailers": w["retailers"],
            "players": w["players"], "accounts": w["accounts"], "events": w["events"],
            "transactions": tx[TX_COLS + ["timestamp_local"]], "scenario_labels": labels}


def frames_from_db() -> dict[str, pd.DataFrame]:
    from database.db import connect
    out = {}
    with connect() as con:
        for t in RAW:
            out[t] = pd.read_sql_query(f"SELECT * FROM {t} ORDER BY 1", con)
        out["cases"] = pd.read_sql_query(
            """SELECT case_id, alert_id, channel, subject_type, subject_id, player_id, status, priority, alert_score,
                      score_band, evidence_completeness, origin, created_at_utc FROM cases ORDER BY case_id""", con)
        out["alerts"] = pd.read_sql_query("SELECT alert_id, case_id, source, alert_type, triggered_at_utc, subject_id, alert_score FROM alerts ORDER BY alert_id", con)
    return out


def export(out: Path, fmt: str = "csv", source: str = "generator") -> dict:
    out.mkdir(parents=True, exist_ok=True)
    frames = frames_from_generator() if source == "generator" else frames_from_db()
    files = {}
    for name, df in frames.items():
        f = _write(df, out / name, fmt)
        files[f.name] = {"rows": int(len(df)), "sha256": _sha(f)}
    labels = frames["scenario_labels"]
    tx = frames["transactions"]
    manifest = {
        "dataset_version": dataset_spec.DATASET_VERSION, "generator": dataset_spec.GENERATOR,
        "source": source, "format": fmt, "generation_config": dataset_spec.generation_config(),
        "config_sha256": dataset_spec.config_fingerprint(),
        "time_range_utc": [str(tx.timestamp_utc.min()), str(tx.timestamp_utc.max())] if len(tx) else None,
        "files": files,
        "composition": {
            "by_category": labels.scenario_category.value_counts().sort_index().to_dict() if len(labels) else {},
            "planted_suspicious": int(pd.to_numeric(labels.label_suspicious).sum()) if len(labels) else 0,
            "by_channel": tx.channel.value_counts().to_dict() if len(tx) else {},
            "attributed_vs_anonymous": {"attributed": int(tx.player_id.notna().sum()), "anonymous": int(tx.player_id.isna().sum())},
        },
        "note": ("Synthetic data only. scenario_labels marks which subjects had a pattern planted by the simulator; "
                 "a planted pattern is not confirmed fraud and is never shown to investigators."),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return manifest


def load_world(folder: Path) -> dict:
    """Read and verify a dataset folder; returns the generator-shaped ``world`` dict the pipeline builds from."""
    man = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    for name, info in man["files"].items():
        f = folder / name
        if not f.exists() or _sha(f) != info["sha256"]:
            raise SystemExit(f"{name}: missing or changed since export (hash mismatch). Nothing was imported.")
    if man["dataset_version"] != dataset_spec.DATASET_VERSION or man["config_sha256"] != dataset_spec.config_fingerprint():
        raise SystemExit(f"Dataset {man['dataset_version']} does not match this configuration "
                         f"({dataset_spec.DATASET_VERSION}); set PRISM_SEED / PRISM_N_PLAYERS to match. Nothing was imported.")
    if man.get("source") != "generator":
        raise SystemExit("Only generator exports can be imported (database exports are for analysis).")
    ext = ".parquet" if man["format"] == "parquet" else ".csv"
    f = {t: _read(folder / f"{t}{ext}") for t in RAW}
    tx = f["transactions"].copy()
    tx["timestamp"] = pd.to_datetime(tx.pop("timestamp_local"))
    tx = tx.drop(columns=["timestamp_utc"])
    tx["amount"] = tx["amount"].astype(float)
    tx["is_synthetic"] = tx["is_synthetic"].astype(int)
    for c in ("player_id", "account_id", "retailer_id", "location_id", "terminal_id", "ticket_id", "game"):
        tx[c] = tx[c].where(tx[c].notna(), None)
    players = f["players"].astype({"has_rewards_card": int, "has_online_account": int})
    retailers = f["retailers"].astype({"terminal_count": int})
    lab = f["scenario_labels"]
    labels = pd.DataFrame({"player_id": lab.player_id, "profile": lab.profile, "scenario": lab.scenario.fillna(""),
                           "curated_key": lab.curated_key.fillna(""), "label_suspicious": lab.label_suspicious.astype(int)})
    from data.generator import CURATED
    keys = {k for k, _s, _t in CURATED}                     # same mapping the generator returns (no partner)
    curated = {r.curated_key: r.player_id for r in labels.itertuples() if r.curated_key in keys}
    return {"transactions": tx, "players": players, "accounts": f["accounts"], "retailers": retailers,
            "locations": f["locations"], "events": f["events"], "labels": labels, "curated_ids": curated}


def import_folder(folder: Path) -> dict:
    import pipeline
    from database.db import connect, get_meta, migrate
    world = load_world(folder)
    migrate()
    with connect() as con:
        if get_meta(con, "dataset_built"):
            return {"imported": False, "reason": "The database already holds a dataset; nothing was written."}
    return {"imported": True, "status": pipeline.build_dataset(verbose=False, world=world)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--out", type=Path, required=True)
    e.add_argument("--format", choices=["csv", "parquet"], default="csv")
    e.add_argument("--source", choices=["generator", "db"], default="generator")
    i = sub.add_parser("import")
    i.add_argument("folder", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "export":
        m = export(a.out, a.format, a.source)
        print(json.dumps({k: m[k] for k in ("dataset_version", "time_range_utc", "composition")}, indent=2))
        print({k: v["rows"] for k, v in m["files"].items()})
    else:
        print(json.dumps(import_folder(a.folder), indent=2, default=str))


if __name__ == "__main__":
    main()
