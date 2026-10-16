"""PostgreSQL (Supabase) adapter for PRISM V2.

The services were written against Python's sqlite3 API (``con.execute(sql, params)``, ``?``
placeholders, rows readable by index and by column name). This module gives a psycopg 3
connection that same surface so the business logic does not need rewriting:

* ``?`` placeholders become ``%s``; literal ``%`` is escaped.
* The few SQLite-only constructs PRISM uses are translated in one place (``translate``):
  ``INSERT OR IGNORE``, ``GROUP_CONCAT``, ``json_extract(col, '$.key')`` and case-insensitive ``LIKE``.
* Rows behave like ``sqlite3.Row`` (index, key, ``keys()``, ``dict(row)``); NUMERIC values come back
  as int/float like SQLite's.
* Autocommit by default; ``tx()`` in database/db.py opens an explicit transaction and takes a
  transaction-scoped advisory lock, which reproduces SQLite's ``BEGIN IMMEDIATE`` (one writer at a
  time) so the existing check-then-write logic (status checks, idempotency keys, ID counters)
  keeps its guarantees.
* Every connection sets ``search_path`` to the ``prism`` schema, not Supabase's exposed ``public``
  (use a direct connection or the Session pooler; the Transaction pooler does not keep session settings).
* Hosted connections must use TLS: ``sslmode`` is forced to ``require`` unless the host is local.

Credentials only come from the environment (DATABASE_URL); nothing here logs them.
"""
from __future__ import annotations

import re
import warnings
from decimal import Decimal
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

SCHEMA = "prism"
# pandas.read_sql_query works with any DB-API connection but warns that it only "supports" SQLAlchemy
warnings.filterwarnings("ignore", message=".*pandas only supports SQLAlchemy.*", category=UserWarning)
WRITE_LOCK_KEY = 728_000_001          # arbitrary constant: the single PRISM writer lock

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}

try:  # imported lazily so V2 still runs on SQLite without the driver installed
    import psycopg
    from psycopg import errors as pg_errors
except ImportError:  # pragma: no cover - exercised only when the driver is missing
    psycopg = None
    pg_errors = None


class DriverMissing(RuntimeError):
    pass


def safe_dsn(url: str) -> str:
    """Return the DSN with TLS enforced for non-local hosts. Never log the result (it has the password)."""
    parts = urlsplit(url)
    if parts.scheme not in ("postgres", "postgresql"):
        raise ValueError("DATABASE_URL must start with postgresql://")
    q = dict(parse_qsl(parts.query))
    host = (parts.hostname or "").lower()
    if host not in _LOCAL_HOSTS and not host.startswith("/"):
        if q.get("sslmode", "require") in ("disable", "allow", "prefer"):
            raise ValueError("Hosted databases must use TLS: remove sslmode=disable/allow/prefer from DATABASE_URL.")
        q.setdefault("sslmode", "require")
    return urlunsplit(parts._replace(query=urlencode(q, quote_via=quote)))


def redacted(url: str) -> str:
    """host:port/db for messages, without user or password."""
    p = urlsplit(url)
    return f"{p.hostname}:{p.port or 5432}{p.path}"


# ------------------------------------------------------------------ SQL translation
_STR = re.compile(r"'(?:[^']|'')*'")


def _outside_strings(sql: str, fn) -> str:
    out, pos = [], 0
    for m in _STR.finditer(sql):
        out.append(fn(sql[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(fn(sql[pos:]))
    return "".join(out)


_JSON = re.compile(r"json_extract\(\s*([\w.]+)\s*,\s*'\$\.(\w+)'\s*\)", re.I)
_GROUP_CONCAT = re.compile(r"GROUP_CONCAT\(\s*([\w.]+)\s*\)", re.I)
_INSERT_IGNORE = re.compile(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO", re.I)


def translate(sql: str) -> str:
    """SQLite dialect used by PRISM → PostgreSQL. Covered by tests/test_pg_translate.py."""
    sql = _JSON.sub(lambda m: f"({m[1]}::jsonb ->> '{m[2]}')", sql)       # before quoting rules (contains a literal)
    ignore = bool(_INSERT_IGNORE.match(sql))
    if ignore:
        sql = _INSERT_IGNORE.sub("INSERT INTO", sql, count=1)

    sql = sql.replace("%", "%%")      # psycopg reads % everywhere (also inside literals) when params are bound

    def code(part: str) -> str:
        part = re.sub(r"\bIS\s+NOT\s+\?", "IS DISTINCT FROM ?", part, flags=re.I)   # SQLite null-safe comparisons
        part = re.sub(r"\bIS\s+\?", "IS NOT DISTINCT FROM ?", part, flags=re.I)
        part = part.replace("?", "%s")
        part = _GROUP_CONCAT.sub(lambda m: f"string_agg({m[1]}, ',')", part)
        return re.sub(r"\bLIKE\b", "ILIKE", part)

    sql = _outside_strings(sql, code)
    if ignore:
        sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return sql


# ------------------------------------------------------------------ rows and cursors
def _norm(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


class Row(tuple):
    """sqlite3.Row look-alike: row[0], row['col'], row.keys(), dict(row)."""
    __slots__ = ()
    _cols: tuple = ()

    def __new__(cls, values, cols):
        r = super().__new__(cls, [_norm(v) for v in values])
        return r

    def __getitem__(self, k):
        if isinstance(k, str):
            return tuple.__getitem__(self, self._index[k])
        return tuple.__getitem__(self, k)

    def keys(self):
        return list(self._cols)


def _row_class(cols: tuple):
    return type("Row", (Row,), {"_cols": cols, "_index": {c: i for i, c in enumerate(cols)}, "__slots__": ()})


class Cursor:
    def __init__(self, cur):
        self._cur = cur
        self._cls = None

    def _wrap(self, r):
        if r is None:
            return None
        if self._cls is None:
            self._cls = _row_class(tuple(d.name for d in self._cur.description))
        return self._cls(r, None)

    @property
    def description(self):
        return [(d.name, None, None, None, None, None, None) for d in (self._cur.description or [])]

    @property
    def rowcount(self):
        return self._cur.rowcount

    def execute(self, sql, params=()):
        self._cls = None
        self._cur.execute(translate(sql), tuple(params or ()))
        return self

    def fetchone(self):
        return self._wrap(self._cur.fetchone()) if self._cur.description else None

    def fetchall(self):
        return [self._wrap(r) for r in self._cur.fetchall()] if self._cur.description else []

    def fetchmany(self, size=None):
        return [self._wrap(r) for r in self._cur.fetchmany(size)]

    def __iter__(self):
        return iter(self.fetchall())

    def close(self):
        self._cur.close()


class Connection:
    """The subset of sqlite3.Connection that PRISM uses (and pandas.read_sql_query needs)."""
    backend = "postgres"

    def __init__(self, raw):
        self._raw = raw
        self.in_tx = False

    def execute(self, sql, params=()):
        s = sql.strip().upper()
        if s in ("BEGIN", "BEGIN IMMEDIATE"):
            return self.begin()
        if s in ("COMMIT", "ROLLBACK"):
            return self.end(s == "COMMIT")
        return Cursor(self._raw.cursor()).execute(sql, params)

    def executemany(self, sql, seq):
        rows = [tuple(r) for r in seq]
        if rows:
            with self._raw.cursor() as cur:
                cur.executemany(translate(sql), rows)
        return None

    def begin(self):
        self._raw.execute("BEGIN")
        self._raw.execute("SELECT pg_advisory_xact_lock(%s)", (WRITE_LOCK_KEY,))
        self.in_tx = True

    def end(self, commit: bool):
        self._raw.execute("COMMIT" if commit else "ROLLBACK")
        self.in_tx = False

    def cursor(self):
        return Cursor(self._raw.cursor())

    def commit(self):  # pandas may call these; autocommit makes them no-ops outside tx()
        if self.in_tx:
            self.end(True)

    def rollback(self):
        if self.in_tx:
            self.end(False)

    def close(self):
        self._raw.close()

    def tls(self) -> tuple[bool, str | None]:
        """TLS on THIS client connection, from libpq (PQsslInUse / PQsslAttribute). Unlike pg_stat_ssl this is
        correct behind a pooler such as Supabase Supavisor, where pg_stat_ssl describes the pooler's own
        internal link to the database rather than ours."""
        pq = self._raw.pgconn
        if not pq.ssl_in_use:
            return False, None
        try:
            proto = pq.ssl_attribute(b"protocol")
        except Exception:  # noqa: BLE001 - attribute lookup only; TLS itself is already confirmed
            proto = None
        return True, (proto.decode() if isinstance(proto, bytes) else proto) or "TLS"


def connect(url: str) -> Connection:
    if psycopg is None:
        raise DriverMissing("PostgreSQL mode needs the 'psycopg[binary]' package: pip install -r requirements-v2.txt")
    raw = psycopg.connect(safe_dsn(url), autocommit=True, connect_timeout=15, application_name="prism-v2")
    # session settings (works on direct connections and Supabase's session pooler; not the transaction pooler)
    raw.execute(f"SET search_path TO {SCHEMA}")
    raw.execute("SET statement_timeout = 60000")
    return Connection(raw)


def is_integrity_error(e: BaseException) -> bool:
    return pg_errors is not None and isinstance(e, psycopg.IntegrityError)
