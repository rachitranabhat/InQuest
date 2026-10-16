"""Copy a PRISM SQLite database into PostgreSQL — safely and repeatably — and verify the result.

* The SQLite source is opened READ-ONLY (V1's own file is never written; use the V2 snapshot copy).
* Rows are inserted with ON CONFLICT (primary key) DO NOTHING in foreign-key order, so a second run adds
  nothing and nothing is ever deleted, updated or reset in the target.
* Simulated reviewer session tokens are not copied (sessions are per-run and act like credentials).
* After copying: row counts and per-table content fingerprints must match the source exactly, evidence
  snapshot hashes are recomputed, and citation/audit references are checked. Any mismatch is reported.

    python -m database.migrate_data --source data/v1-snapshot/prism-v1.db         (run from backend/)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from database import db, verify

SKIP = {"sessions"}           # simulated tokens: never migrated
BATCH = 1000


def _src(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def copy(source: Path, log=print) -> dict:
    if not db.using_postgres():
        raise SystemExit("Set PRISM_DB_BACKEND=postgres and DATABASE_URL first.")
    src = _src(source)
    src_version = src.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    db.migrate()
    src_built = src.execute("SELECT value FROM meta WHERE key = 'dataset_built'").fetchone()
    with db.connect() as con:
        tgt_built = con.execute("SELECT value FROM meta WHERE key = 'dataset_built'").fetchone()
    if tgt_built and (not src_built or tgt_built[0] != src_built[0]):
        raise SystemExit("The target already holds a different PRISM dataset. Migrate into an empty 'prism' schema "
                         "(nothing was changed).")
    added = {}
    with db.connect() as con:
        for table, pk in verify.TABLES.items():
            if table in SKIP:
                continue
            try:
                cols = [d[0] for d in src.execute(f"SELECT * FROM {table} LIMIT 0").description]
            except sqlite3.OperationalError:
                continue                                       # table newer than the source schema
            before = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
                   f"ON CONFLICT ({', '.join(pk)}) DO NOTHING")
            cur = src.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY {', '.join(pk)}")
            with db.tx(con):
                while True:
                    rows = cur.fetchmany(BATCH)
                    if not rows:
                        break
                    con.executemany(sql, [tuple(r) for r in rows])
            added[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] - before
            log(f"  {table:24s} +{added[table]}")
        # id counters must never go backwards (a second run or later activity in the target)
        with db.tx(con):
            for r in src.execute("SELECT prefix, next FROM id_counters"):
                con.execute("UPDATE id_counters SET next = ? WHERE prefix = ? AND next < ?", (r["next"], r["prefix"], r["next"]))
    return {"source_schema": src_version, "added": added}


def compare(source: Path) -> dict:
    """Source vs target: rows, fingerprints and integrity. Tables only in the target are listed separately."""
    src = _src(source)
    with db.connect() as con:
        tgt = verify.report(con)
    s = verify.report(src)
    tables = {}
    for t, info in s["tables"].items():
        if t in SKIP or "missing" in info:
            continue
        ti = tgt["tables"].get(t, {})
        tables[t] = {"source_rows": info["rows"], "target_rows": ti.get("rows"),
                     "identical": info.get("sha256") == ti.get("sha256")}
    return {"tables": tables, "all_identical": all(v["identical"] for v in tables.values()),
            "source_integrity": {"snapshots": s["snapshots"], "citations": s["citations"]},
            "target_integrity": {"snapshots": tgt["snapshots"], "citations": tgt["citations"]},
            "target_ok": verify.ok(tgt)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "v1-snapshot" / "prism-v1.db")
    ap.add_argument("--verify-only", action="store_true")
    a = ap.parse_args(argv)
    if not a.source.exists():
        raise SystemExit(f"Source not found: {a.source}")
    if not a.verify_only:
        print(f"Copying {a.source.name} → PostgreSQL ({db.config.DATABASE_URL and 'DATABASE_URL set'})")
        res = copy(a.source)
        print(json.dumps(res, indent=1))
        print(f"rows_added_total={sum(res['added'].values())}")
        import pipeline
        n = pipeline.backfill_labels()
        print(f"  scenario_labels backfilled: {n}")
    out = compare(a.source)
    print(json.dumps(out, indent=1))
    sys.exit(0 if out["all_identical"] and out["target_ok"] else 1)


if __name__ == "__main__":
    main()
