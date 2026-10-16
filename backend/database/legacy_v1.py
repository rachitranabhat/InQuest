"""SQLite persistence layer.

Tables
------
transactions  - synthetic transactions
cases         - alerts produced by the detection engine (evidence stored as JSON)
reviews       - human reviewer decisions (the only place a "decision" is recorded)
ai_reports    - cached AI-generated reports, labelled with the mode that made them
ai_questions  - log of "Ask AI" questions and answers
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id   TEXT PRIMARY KEY,
    customer_id      TEXT NOT NULL,
    retailer_id      TEXT NOT NULL,
    timestamp        TEXT NOT NULL,
    amount           REAL NOT NULL,
    location         TEXT NOT NULL,
    transaction_type TEXT NOT NULL,
    is_synthetic     INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_tx_customer ON transactions(customer_id, timestamp);

CREATE TABLE IF NOT EXISTS cases (
    case_id          TEXT PRIMARY KEY,
    customer_id      TEXT NOT NULL,
    risk_score       REAL NOT NULL,
    risk_level       TEXT NOT NULL,
    status           TEXT NOT NULL,
    primary_reason   TEXT NOT NULL,
    triggered_count  INTEGER NOT NULL,
    created_at       TEXT NOT NULL,
    window_start     TEXT NOT NULL,
    window_end       TEXT NOT NULL,
    features_json    TEXT NOT NULL,
    factors_json     TEXT NOT NULL,
    ml_probability   REAL,
    anomaly_score    REAL
);

CREATE TABLE IF NOT EXISTS reviews (
    review_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id          TEXT NOT NULL REFERENCES cases(case_id),
    decision         TEXT NOT NULL,
    new_status       TEXT NOT NULL,
    notes            TEXT NOT NULL,
    reviewer         TEXT NOT NULL,
    review_condition TEXT NOT NULL,
    opened_at        TEXT,
    decided_at       TEXT NOT NULL,
    review_seconds   REAL
);

CREATE TABLE IF NOT EXISTS ai_reports (
    case_id          TEXT NOT NULL,
    mode             TEXT NOT NULL,
    content_json     TEXT NOT NULL,
    generated_at     TEXT NOT NULL,
    PRIMARY KEY (case_id, mode)
);

CREATE TABLE IF NOT EXISTS ai_questions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id          TEXT NOT NULL,
    mode             TEXT NOT NULL,
    question         TEXT NOT NULL,
    answer           TEXT NOT NULL,
    asked_at         TEXT NOT NULL
);
"""


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.isoformat()
    raise TypeError(type(o))


def dumps(obj) -> str:
    return json.dumps(obj, default=_json_default)


@contextmanager
def connect(db_path: Path | str = None):
    path = Path(db_path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db(reset: bool = False, db_path=None):
    path = Path(db_path or config.DB_PATH)
    if reset and path.exists():
        path.unlink()
    with connect(path) as con:
        con.executescript(SCHEMA)


def is_initialized(db_path=None) -> bool:
    path = Path(db_path or config.DB_PATH)
    if not path.exists():
        return False
    try:
        with connect(path) as con:
            return con.execute("SELECT COUNT(*) FROM cases").fetchone()[0] > 0
    except sqlite3.Error:
        return False


# ----------------------------------------------------------------- writing
def insert_transactions(tx: pd.DataFrame):
    df = tx.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    cols = ["transaction_id", "customer_id", "retailer_id", "timestamp", "amount",
            "location", "transaction_type", "is_synthetic"]
    with connect() as con:
        con.executemany(
            f"INSERT INTO transactions ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            df[cols].itertuples(index=False, name=None),
        )


def insert_cases(alerts: list[dict]):
    with connect() as con:
        for i, a in enumerate(alerts):
            case_id = f"CASE-{10001 + i}"
            a["case_id"] = case_id
            con.execute(
                """INSERT INTO cases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    case_id, a["customer_id"], a["risk_score"], a["risk_level"], config.STATUS_NEW,
                    a["primary_reason"], a["triggered_count"], a["created_at"], a["window_start"],
                    a["window_end"], dumps(a["features"]), dumps(a["factors"]),
                    a.get("ml_probability"), a["features"].get("isolation_forest_score"),
                ),
            )


def record_review(case_id, decision, notes, reviewer, condition, opened_at=None):
    new_status = config.DECISIONS[decision]
    now = datetime.now()
    secs = None
    if opened_at:
        secs = round((now - datetime.fromisoformat(opened_at)).total_seconds(), 1)
    with connect() as con:
        con.execute(
            """INSERT INTO reviews (case_id, decision, new_status, notes, reviewer, review_condition,
                                    opened_at, decided_at, review_seconds)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (case_id, decision, new_status, notes.strip(), reviewer.strip() or "Reviewer",
             condition, opened_at, now.isoformat(timespec="seconds"), secs),
        )
        con.execute("UPDATE cases SET status=? WHERE case_id=?", (new_status, case_id))
    return new_status


def save_report(case_id, mode, content: dict):
    with connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO ai_reports VALUES (?,?,?,?)",
            (case_id, mode, dumps(content), datetime.now().isoformat(timespec="seconds")),
        )


def log_question(case_id, mode, question, answer):
    with connect() as con:
        con.execute(
            "INSERT INTO ai_questions (case_id, mode, question, answer, asked_at) VALUES (?,?,?,?,?)",
            (case_id, mode, question, answer, datetime.now().isoformat(timespec="seconds")),
        )


# ----------------------------------------------------------------- reading
def get_cases() -> pd.DataFrame:
    with connect() as con:
        df = pd.read_sql_query(
            """SELECT case_id, customer_id, risk_score, risk_level, status, primary_reason,
                      triggered_count, created_at, ml_probability, anomaly_score, factors_json
               FROM cases ORDER BY risk_score DESC""",
            con,
        )
    df["created_at"] = pd.to_datetime(df["created_at"])
    df["anomaly_types"] = df.factors_json.map(
        lambda s: [v["label"] for v in json.loads(s).values() if v["triggered"]]
    )
    return df.drop(columns=["factors_json"])


def get_case(case_id: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["features"] = json.loads(d.pop("features_json"))
    d["factors"] = json.loads(d.pop("factors_json"))
    return d


def get_transactions(customer_id: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    q = "SELECT * FROM transactions WHERE customer_id=?"
    params = [customer_id]
    if start:
        q += " AND timestamp >= ?"
        params.append(pd.Timestamp(start).strftime("%Y-%m-%d %H:%M:%S"))
    if end:
        q += " AND timestamp <= ?"
        params.append(pd.Timestamp(end).strftime("%Y-%m-%d %H:%M:%S"))
    with connect() as con:
        df = pd.read_sql_query(q + " ORDER BY timestamp", con, params=params)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def get_reviews(case_id: str | None = None) -> pd.DataFrame:
    q = "SELECT * FROM reviews"
    params = []
    if case_id:
        q += " WHERE case_id=?"
        params.append(case_id)
    with connect() as con:
        df = pd.read_sql_query(q + " ORDER BY decided_at DESC", con, params=params)
    return df


def get_report(case_id, mode) -> dict | None:
    with connect() as con:
        row = con.execute(
            "SELECT content_json, generated_at FROM ai_reports WHERE case_id=? AND mode=?", (case_id, mode)
        ).fetchone()
    if not row:
        return None
    d = json.loads(row["content_json"])
    d["generated_at"] = row["generated_at"]
    return d


def get_questions(case_id) -> pd.DataFrame:
    with connect() as con:
        return pd.read_sql_query(
            "SELECT * FROM ai_questions WHERE case_id=? ORDER BY id", con, params=[case_id]
        )


def counts() -> dict:
    with connect() as con:
        tx = con.execute("SELECT COUNT(*), COUNT(DISTINCT customer_id) FROM transactions").fetchone()
        return {"transactions": tx[0], "customers": tx[1],
                "cases": con.execute("SELECT COUNT(*) FROM cases").fetchone()[0]}


def get_case_cards() -> list[dict]:
    """All cases with parsed factors/features (for the triage board)."""
    with connect() as con:
        rows = con.execute(
            """SELECT case_id, customer_id, risk_score, risk_level, status, primary_reason, triggered_count,
                      created_at, features_json, factors_json FROM cases ORDER BY risk_score DESC"""
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["features"] = json.loads(d.pop("features_json"))
        d["factors"] = json.loads(d.pop("factors_json"))
        out.append(d)
    return out


def last_decision_times() -> dict:
    """case_id -> most recent decision timestamp."""
    with connect() as con:
        return dict(con.execute("SELECT case_id, MAX(decided_at) FROM reviews GROUP BY case_id").fetchall())
