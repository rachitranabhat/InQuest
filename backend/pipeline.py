"""Dataset build and case creation.

    python pipeline.py status          show what is in the database
    python pipeline.py build           build only if the database is empty (safe; default on server start)
    python pipeline.py reset --yes     back up the database, then rebuild from the seed

Restarting the server never regenerates data: build is a no-op once the
dataset exists. Reset always writes a timestamped backup first.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from data.generator import generate  # noqa: E402
from data import dataset_spec  # noqa: E402
from database.db import connect, dumps, using_postgres, get_meta, migrate, next_ids, set_meta, tx as transaction  # noqa: E402
from detection.monitoring import ALERT_SOURCE, run_monitoring  # noqa: E402
from services.evidence_registry import build_items, completeness, persist_items  # noqa: E402
from services.priority import compute_priority  # noqa: E402
from timeutil import local_series_to_utc_iso, local_to_utc_iso, utc_iso_to_local, utc_now_iso  # noqa: E402

SYSTEM_REVIEWER = ("SYSTEM", "PRISM system", "System")
REVIEWERS = [  # fictional reviewer personas for the simulated session
    ("REV-01", "Avery Chen", "Investigator"),
    ("REV-02", "Jordan Patel", "Senior investigator"),
    ("REV-03", "Sam Rivera", "Analyst"),
]
TX_COLS = ["transaction_id", "channel", "player_id", "account_id", "retailer_id", "location_id", "terminal_id",
           "ticket_id", "timestamp_utc", "amount", "transaction_type", "game", "attribution", "is_synthetic"]


def _none(v):
    return None if (v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NA) else v


def insert_transactions(con: sqlite3.Connection, tx_local: pd.DataFrame):
    df = tx_local.copy()
    df["timestamp_utc"] = local_series_to_utc_iso(df["timestamp"])
    rows = [tuple(_none(v) for v in r) for r in df[TX_COLS].itertuples(index=False, name=None)]
    con.executemany(f"INSERT INTO transactions ({','.join(TX_COLS)}) VALUES ({','.join('?' * len(TX_COLS))})", rows)


def load_transactions(con, where: str = "", params=()) -> pd.DataFrame:
    df = pd.read_sql_query(f"SELECT * FROM transactions {where}", con, params=params)
    df["timestamp"] = utc_iso_to_local(df["timestamp_utc"]) if len(df) else pd.Series(dtype="datetime64[ns]")
    return df


def network_daily(con) -> pd.Series:
    df = pd.read_sql_query("SELECT timestamp_utc FROM transactions WHERE channel = 'lottery_terminal'", con)
    days = utc_iso_to_local(df.timestamp_utc).dt.strftime("%Y-%m-%d")
    return days.value_counts().sort_index()


def case_context(alert: dict, tx: pd.DataFrame, retailers, locations, events, nd) -> dict:
    ws, we = pd.Timestamp(alert["window_start_local"]), pd.Timestamp(alert["window_end_local"])
    if alert["channel"] == "online_account":
        subj = tx[tx.account_id == alert["subject_id"]]
    else:
        subj = tx[(tx.player_id == alert["subject_id"]) & (tx.channel == "lottery_terminal")]
    window = subj[(subj.timestamp >= ws) & (subj.timestamp <= we)]
    base = subj[subj.timestamp < ws]
    ctx = {"window_tx": window, "baseline_tx": base, "retailers": retailers, "locations": locations,
           "events": events, "network_daily": nd}
    if alert["channel"] == "lottery_terminal":
        rets = set(window.retailer_id.dropna())
        lot = tx[(tx.channel == "lottery_terminal") & tx.retailer_id.isin(rets) &
                 (tx.timestamp >= ws) & (tx.timestamp <= we)]
        ctx["anon_window_tx"] = lot[lot.player_id.isna()]
        ctx["other_attributed_tx"] = lot[lot.player_id.notna() & (lot.player_id != alert["subject_id"])]
    return ctx


def create_case(con, alert: dict, ctx: dict, *, curated_key=None, scenario_title=None, origin="monitoring") -> str:
    """Persist alert + case + evidence snapshot. Call inside a transaction."""
    case_id = next_ids(con, "CASE", 1, width=5)[0]
    alert_id = "AL-" + case_id.split("-")[1]
    win = ctx["window_tx"]
    alert_tx = sorted({t for fac in alert["factors"].values() if fac["triggered"] for t in fac["transactions"]})
    case_view = {**alert, "case_id": case_id, "alert_id": alert_id, "alert_transaction_ids": alert_tx}
    items = build_items(case_view, ctx)
    comp = completeness(items)
    pr = compute_priority(alert, comp)
    now = utc_now_iso()
    trig_utc = local_to_utc_iso(alert["triggered_at_local"])
    con.execute(
        """INSERT INTO cases (case_id, alert_id, channel, subject_type, subject_id, player_id, status, priority,
             priority_rationale, alert_score, score_band, evidence_completeness, urgency, primary_reason,
             triggered_count, window_start_utc, window_end_utc, features_json, factors_json, anomaly_score,
             curated_key, scenario_title, origin, created_at_utc, updated_at_utc)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (case_id, alert_id, alert["channel"], alert["subject_type"], alert["subject_id"], alert["player_id"],
         config.STATUS_NEW, pr["priority"], dumps(pr["rationale"]), alert["risk_score"], alert["risk_level"], comp,
         pr["urgency"], alert["primary_reason"], alert["triggered_count"], local_to_utc_iso(alert["window_start_local"]),
         local_to_utc_iso(alert["window_end_local"]), dumps(alert["features"]), dumps(alert["factors"]),
         alert["features"].get("isolation_forest_score"), curated_key, scenario_title, origin, trig_utc, now))
    con.execute("INSERT INTO alerts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (alert_id, case_id, ALERT_SOURCE, alert["alert_type"], dumps(alert["rules_fired"]), trig_utc,
                 alert["subject_type"], alert["subject_id"], alert["risk_score"],
                 dumps([k for k, f in alert["factors"].items() if f["triggered"]]), dumps(alert_tx)))
    persist_items(con, case_id, items)
    return case_id


def build_dataset(path=None, verbose=True, world=None) -> dict:
    """Generate (or take a verified imported ``world``) and build the database. Refuses if already built."""
    log = print if verbose else (lambda *a, **k: None)
    t0 = time.time()
    migrate(path)
    with connect(path) as con:
        if get_meta(con, "dataset_built"):
            log("Dataset already present — nothing to do (use 'reset --yes' to rebuild).")
            return status(path)
    if world is None:
        log("[1/4] Generating synthetic world (seed %d) ..." % config.RANDOM_SEED)
        world = generate()
    else:
        log("[1/4] Using imported synthetic dataset files ...")
    tx = world["transactions"]
    log("[2/4] Running simulated monitoring rules ...")
    alerts = run_monitoring(tx, world["retailers"])
    curated_by_player = {v: k for k, v in world["curated_ids"].items()}
    from data.generator import CURATED
    titles = {k: t for k, _, t in CURATED}
    log("[3/4] Writing records and building evidence for %d alerts ..." % len(alerts))
    with connect(path) as con, transaction(con):
        con.executemany("INSERT INTO locations VALUES (?,?,?)", world["locations"][["location_id", "city", "region"]].itertuples(index=False, name=None))
        con.executemany("INSERT INTO retailers VALUES (?,?,?,?,?)", [
            (r.retailer_id, r.name, r.location_id, r.city, int(r.terminal_count)) for r in world["retailers"].itertuples()])
        con.executemany("INSERT INTO reviewers VALUES (?,?,?)", REVIEWERS + [SYSTEM_REVIEWER])
        con.executemany("INSERT INTO players VALUES (?,?,?,?)", world["players"].itertuples(index=False, name=None))
        con.executemany("INSERT INTO accounts VALUES (?,?,?)", world["accounts"].itertuples(index=False, name=None))
        con.executemany("INSERT INTO events VALUES (?,?,?,?,?)", world["events"].itertuples(index=False, name=None))
        insert_transactions(con, tx)
        max_txn = int(tx.transaction_id.str[4:].astype(int).max())
        for prefix, nxt in (("TXN", max_txn + 1), ("CASE", 18001)):   # portable upsert (SQLite and PostgreSQL)
            con.execute("INSERT INTO id_counters(prefix, next) VALUES (?, ?) "
                        "ON CONFLICT(prefix) DO UPDATE SET next = excluded.next", (prefix, nxt))
        nd = network_daily(con)
        # curated cases first so their IDs are easy to find in a demo, then by score
        alerts.sort(key=lambda a: (a["player_id"] not in curated_by_player, -a["risk_score"]))
        for a in alerts:
            ctx = case_context(a, tx, world["retailers"], world["locations"], world["events"], nd)
            key = curated_by_player.get(a["player_id"])
            create_case(con, a, ctx, curated_key=key, scenario_title=titles.get(key))
        set_meta(con, "dataset_built", utc_now_iso())
        set_meta(con, "seed", config.RANDOM_SEED)
        set_meta(con, "dataset_version", dataset_spec.DATASET_VERSION)
        dataset_spec.record_dataset(con, world["labels"])
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    world["labels"].to_csv(config.GROUND_TRUTH_CSV, index=False)  # kept outside the database on purpose
    log("[4/4] Done in %.1fs" % (time.time() - t0))
    return status(path)


def status(path=None) -> dict:
    migrate(path)
    with connect(path) as con:
        q = lambda s: con.execute(s).fetchone()[0]  # noqa: E731
        where = "PostgreSQL (schema prism)" if using_postgres(path) else str(config.DB_PATH if path is None else path)
        return {"db": where, "built": get_meta(con, "dataset_built"),
                "transactions": q("SELECT COUNT(*) FROM transactions"), "cases": q("SELECT COUNT(*) FROM cases"),
                "evidence": q("SELECT COUNT(*) FROM evidence"), "reports": q("SELECT COUNT(*) FROM reports"),
                "actions": q("SELECT COUNT(*) FROM case_actions")}


def reset(path=None) -> dict:
    if using_postgres(path):
        raise SystemExit("Reset is disabled for PostgreSQL: PRISM never drops or rebuilds a hosted database.")
    p = Path(path or config.DB_PATH)
    if p.exists():
        config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        dest = config.BACKUP_DIR / f"{p.stem}-{time.strftime('%Y%m%dT%H%M%S')}.db"
        with connect(p) as con:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        shutil.copy2(p, dest)
        print(f"Backed up existing database to {dest}")
        for suffix in ("", "-wal", "-shm"):
            Path(str(p) + suffix).unlink(missing_ok=True)
    return build_dataset(path)


def ensure_built(path=None) -> dict:
    out = build_dataset(path, verbose=False)
    backfill_labels(path)
    return out


def backfill_labels(path=None) -> int:
    """For a database built before schema v5 (e.g. migrated from V1): regenerate the same seeded world and
    record its dataset version and labels. Insert-only; refuses if the regenerated rows do not match."""
    with connect(path) as con:
        if con.execute("SELECT COUNT(*) FROM scenario_labels").fetchone()[0]:
            return 0
        if str(get_meta(con, "seed")) != str(config.RANDOM_SEED):
            return 0
        world = generate()
        n_db = con.execute("SELECT COUNT(*) FROM transactions WHERE transaction_id <= ?",
                           (world["transactions"].transaction_id.max(),)).fetchone()[0]
        if n_db != len(world["transactions"]):
            return 0                                   # not the same generated dataset: leave unlabeled
        with transaction(con):
            return dataset_spec.record_dataset(con, world["labels"])["labels"]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["status", "build", "reset"], nargs="?", default="build")
    ap.add_argument("--yes", action="store_true", help="confirm reset (a backup is written first)")
    a = ap.parse_args()
    if a.command == "status":
        print(status())
    elif a.command == "build":
        print(build_dataset())
    else:
        if not a.yes:
            sys.exit("Refusing to reset without --yes. A backup is written to data/backups/ first.")
        print(reset())
