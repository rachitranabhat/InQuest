"""Database access: connections, migrations, ID allocation — SQLite (V1 default) or PostgreSQL (V2).

PRISM_DB_BACKEND=postgres switches every connection to database/pg.py, which gives a psycopg
connection the sqlite3 API the services already use. Passing an explicit SQLite ``path`` always
uses SQLite (migration tooling reads the V1 file that way).

* Foreign keys are enforced on every connection.
* Migrations are numbered .sql files in database/migrations, applied once and
  recorded in schema_migrations. They never drop or rewrite existing data.
* All queries elsewhere use parameters (no string-built SQL from user input).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

import config
from timeutil import utc_now_iso

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
PG_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations_pg"


def using_postgres(path=None) -> bool:
    return path is None and config.DB_BACKEND == "postgres"


def _pg_connect():
    from database import pg
    if not config.DATABASE_URL:
        raise RuntimeError("PRISM_DB_BACKEND=postgres but DATABASE_URL is not set (see .env.example).")
    return pg.connect(config.DATABASE_URL)
_lock = threading.Lock()


def _db_path(path=None) -> Path:
    return Path(path or config.DB_PATH)


@contextmanager
def connect(path=None):
    if using_postgres(path):
        con = _pg_connect()
        try:
            yield con
        finally:
            if con.in_tx:
                con.end(False)
            con.close()
        return
    p = _db_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=15, isolation_level=None)  # autocommit; use tx() for transactions
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA busy_timeout = 15000")
    try:
        yield con
    finally:
        con.close()


@contextmanager
def tx(con: sqlite3.Connection):
    """BEGIN IMMEDIATE … COMMIT, rolled back on any exception."""
    con.execute("BEGIN IMMEDIATE")
    try:
        yield con
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise


def migrate(path=None) -> list[str]:
    """Apply pending migrations. Returns the names applied (empty list = up to date)."""
    applied_now = []
    if using_postgres(path):
        return _migrate_pg()
    with _lock, connect(path) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                         version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at_utc TEXT NOT NULL)""")
        done = {r[0] for r in con.execute("SELECT version FROM schema_migrations")}
        for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = int(f.name.split("_", 1)[0])
            if version in done:
                continue
            sql = f.read_text(encoding="utf-8")
            con.execute("BEGIN IMMEDIATE")
            try:
                for stmt in _split_sql(sql):
                    con.execute(stmt)
                con.execute("INSERT INTO schema_migrations VALUES (?,?,?)", (version, f.name, utc_now_iso()))
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
            applied_now.append(f.name)
    return applied_now


def _migrate_pg() -> list[str]:
    """Apply database/migrations_pg/*.sql once each, inside schema "prism", under the writer lock."""
    from database import pg
    applied_now = []
    with _lock, connect() as con:
        raw = con._raw
        raw.execute(f"CREATE SCHEMA IF NOT EXISTS {pg.SCHEMA}")
        raw.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                         version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at_utc TEXT NOT NULL)""")
        for f in sorted(PG_MIGRATIONS_DIR.glob("*.sql")):
            version = int(f.name.split("_", 1)[0])
            con.begin()                                    # BEGIN + advisory lock: one migrator at a time
            try:
                if raw.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (version,)).fetchone():
                    con.end(False)
                    continue
                raw.execute(f.read_text(encoding="utf-8"))  # whole file: dollar-quoted bodies stay intact
                raw.execute("INSERT INTO schema_migrations VALUES (%s,%s,%s)", (version, f.name, utc_now_iso()))
                con.end(True)
            except BaseException:
                con.end(False)
                raise
            applied_now.append(f.name)
    return applied_now


def _split_sql(sql: str) -> list[str]:
    """Split a migration into statements, keeping trigger bodies (BEGIN … END;) intact."""
    stmts, buf, depth = [], [], 0
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buf.append(line)
        upper = stripped.upper()
        if upper.startswith("CREATE TRIGGER"):
            depth = 1
        if depth and upper.endswith("END;"):
            depth = 0
            stmts.append("\n".join(buf))
            buf = []
            continue
        if not depth and stripped.endswith(";"):
            stmts.append("\n".join(buf))
            buf = []
    if buf:
        stmts.append("\n".join(buf))
    return stmts


def schema_version(path=None) -> int:
    with connect(path) as con:
        try:
            return con.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0
        except Exception:  # noqa: BLE001 - no migrations table yet (either backend)
            return 0


def next_ids(con: sqlite3.Connection, prefix: str, n: int = 1, width: int = 6) -> list[str]:
    """Allocate n sequential IDs like EV-000001. Call inside a transaction."""
    # one atomic upsert (SQLite >= 3.35 and PostgreSQL): no read-then-write gap between concurrent writers
    nxt = con.execute("""INSERT INTO id_counters(prefix, next) VALUES (?, ?)
                         ON CONFLICT(prefix) DO UPDATE SET next = id_counters.next + ? RETURNING next""",
                      (prefix, 1 + n, n)).fetchone()[0]
    start = nxt - n
    return [f"{prefix}-{i:0{width}d}" for i in range(start, start + n)]


def next_id(con: sqlite3.Connection, prefix: str, width: int = 6) -> str:
    return next_ids(con, prefix, 1, width)[0]


def dumps(obj) -> str:
    return json.dumps(obj, default=_default, sort_keys=True, separators=(",", ":"))


def _default(o):
    import numpy as np
    import pandas as pd
    from datetime import datetime

    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.isoformat()
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(type(o))


def loads(s, default=None):
    if s is None:
        return default
    return json.loads(s)


def get_meta(con, key, default=None):
    r = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return r[0] if r else default


def set_meta(con, key, value):
    con.execute("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)))
