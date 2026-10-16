"""TEST-ONLY stand-in for the parts of psycopg 3 that database/pg.py uses, built on the system libpq.

Why: the build sandbox cannot download Python packages, but it has PostgreSQL 16 and libpq. This shim
lets the full backend suite run against a real PostgreSQL server here. Production and your machine use
the real ``psycopg[binary]`` (requirements-v2.txt); the shim is only installed when
PRISM_TEST_PQ_SHIM=1 and psycopg is not importable. It supports text-format parameters and results only.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import re
import sys
import types
from decimal import Decimal

_lib = ctypes.CDLL(ctypes.util.find_library("pq") or "libpq.so.5")
_c = ctypes.c_char_p
_lib.PQconnectdb.restype = ctypes.c_void_p
_lib.PQconnectdb.argtypes = [_c]
_lib.PQstatus.argtypes = [ctypes.c_void_p]
_lib.PQerrorMessage.restype = _c
_lib.PQerrorMessage.argtypes = [ctypes.c_void_p]
_lib.PQfinish.argtypes = [ctypes.c_void_p]
_lib.PQexecParams.restype = ctypes.c_void_p
_lib.PQexecParams.argtypes = [ctypes.c_void_p, _c, ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(_c), ctypes.c_void_p,
                              ctypes.c_void_p, ctypes.c_int]
_lib.PQexec.restype = ctypes.c_void_p
_lib.PQexec.argtypes = [ctypes.c_void_p, _c]
for fn, rt in (("PQresultStatus", ctypes.c_int), ("PQntuples", ctypes.c_int), ("PQnfields", ctypes.c_int)):
    getattr(_lib, fn).restype = rt
    getattr(_lib, fn).argtypes = [ctypes.c_void_p]
_lib.PQfname.restype = _c
_lib.PQfname.argtypes = [ctypes.c_void_p, ctypes.c_int]
_lib.PQftype.restype = ctypes.c_uint
_lib.PQftype.argtypes = [ctypes.c_void_p, ctypes.c_int]
_lib.PQgetvalue.restype = ctypes.c_void_p
_lib.PQgetvalue.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
_lib.PQgetlength.restype = ctypes.c_int
_lib.PQgetlength.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
_lib.PQgetisnull.restype = ctypes.c_int
_lib.PQgetisnull.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
_lib.PQcmdTuples.restype = _c
_lib.PQcmdTuples.argtypes = [ctypes.c_void_p]
_lib.PQresultErrorMessage.restype = _c
_lib.PQresultErrorMessage.argtypes = [ctypes.c_void_p]
_lib.PQresultErrorField.restype = _c
_lib.PQresultErrorField.argtypes = [ctypes.c_void_p, ctypes.c_int]
_lib.PQclear.argtypes = [ctypes.c_void_p]

PGRES_COMMAND_OK, PGRES_TUPLES_OK = 1, 2
PG_DIAG_SQLSTATE = ord("C")
_INT = {20, 21, 23, 26}
_FLOAT = {700, 701}


class Error(Exception):
    sqlstate = None


class DatabaseError(Error):
    pass


class IntegrityError(DatabaseError):
    pass


class OperationalError(DatabaseError):
    pass


class ProgrammingError(DatabaseError):
    pass


def _convert(text: str, oid: int):
    if oid in _INT:
        return int(text)
    if oid in _FLOAT:
        return float(text)
    if oid == 1700:
        return Decimal(text)
    if oid == 16:
        return text == "t"
    return text


def _to_text(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return b"true" if v else b"false"
    return str(v).encode()


_PH = re.compile(r"%%|%s")


def _numbered(sql: str) -> tuple[str, int]:
    n = 0

    def sub(m):
        nonlocal n
        if m.group(0) == "%%":
            return "%"
        n += 1
        return f"${n}"
    return _PH.sub(sub, sql), n


class _Col:
    def __init__(self, name):
        self.name = name


class Cursor:
    def __init__(self, conn):
        self._conn = conn
        self._rows, self.description, self.rowcount, self._i = [], None, -1, 0

    def execute(self, sql, params=None):
        self._rows, self.description, self._i = [], None, 0
        res = self._conn._run(sql, params)
        try:
            status = _lib.PQresultStatus(res)
            if status == PGRES_TUPLES_OK:
                nf = _lib.PQnfields(res)
                self.description = [_Col(_lib.PQfname(res, j).decode()) for j in range(nf)]
                types_ = [_lib.PQftype(res, j) for j in range(nf)]
                for i in range(_lib.PQntuples(res)):
                    row = []
                    for j in range(nf):
                        if _lib.PQgetisnull(res, i, j):
                            row.append(None)
                        else:
                            raw = ctypes.string_at(_lib.PQgetvalue(res, i, j), _lib.PQgetlength(res, i, j)).decode()
                            row.append(_convert(raw, types_[j]))
                    self._rows.append(tuple(row))
            ct = (_lib.PQcmdTuples(res) or b"").decode()
            self.rowcount = int(ct) if ct.isdigit() else -1
        finally:
            _lib.PQclear(res)
        return self

    def executemany(self, sql, seq):
        for p in seq:
            self.execute(sql, p)

    def fetchone(self):
        if self._i >= len(self._rows):
            return None
        self._i += 1
        return self._rows[self._i - 1]

    def fetchall(self):
        out, self._i = self._rows[self._i:], len(self._rows)
        return out

    def fetchmany(self, size=None):
        size = size or 1
        out = self._rows[self._i:self._i + size]
        self._i += len(out)
        return out

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class Connection:
    def __init__(self, conninfo: str):
        self._pg = _lib.PQconnectdb(conninfo.encode())
        if _lib.PQstatus(self._pg) != 0:
            msg = _lib.PQerrorMessage(self._pg).decode()
            _lib.PQfinish(self._pg)
            raise OperationalError(msg)

    def _run(self, sql, params):
        if params is None:
            res = _lib.PQexec(self._pg, sql.encode())
        else:
            q, n = _numbered(sql)
            vals = [_to_text(v) for v in params]
            if len(vals) != n:
                raise ProgrammingError(f"query has {n} placeholders but {len(vals)} parameters were passed")
            arr = (_c * max(n, 1))(*vals)
            res = _lib.PQexecParams(self._pg, q.encode(), n, None, arr, None, None, 0)
        status = _lib.PQresultStatus(res)
        if status not in (PGRES_COMMAND_OK, PGRES_TUPLES_OK):
            msg = (_lib.PQresultErrorMessage(res) or b"").decode().strip()
            state = (_lib.PQresultErrorField(res, PG_DIAG_SQLSTATE) or b"").decode()
            _lib.PQclear(res)
            cls = IntegrityError if state.startswith("23") else OperationalError if state.startswith("08") else DatabaseError
            e = cls(msg)
            e.sqlstate = state
            raise e
        return res

    def execute(self, sql, params=None):
        return Cursor(self).execute(sql, params)

    def cursor(self):
        return Cursor(self)

    def close(self):
        if self._pg:
            _lib.PQfinish(self._pg)
            self._pg = None


def connect(conninfo="", autocommit=True, connect_timeout=15, options=None, application_name=None):
    extra = {"connect_timeout": str(connect_timeout)}
    if options:
        extra["options"] = options
    if application_name:
        extra["application_name"] = application_name
    if conninfo.startswith(("postgres://", "postgresql://")):
        from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
        u = urlsplit(conninfo)
        q = dict(parse_qsl(u.query))
        q.update(extra)
        return Connection(urlunsplit(u._replace(query=urlencode(q, quote_via=quote))))
    return Connection(" ".join([conninfo] + [f"{k}='{v}'" for k, v in extra.items()]))


def install():
    mod = types.ModuleType("psycopg")
    for k, v in {"connect": connect, "Error": Error, "DatabaseError": DatabaseError, "IntegrityError": IntegrityError,
                 "OperationalError": OperationalError, "ProgrammingError": ProgrammingError, "__shim__": True}.items():
        setattr(mod, k, v)
    errs = types.ModuleType("psycopg.errors")
    errs.IntegrityError = IntegrityError
    mod.errors = errs
    sys.modules["psycopg"] = mod
    sys.modules["psycopg.errors"] = errs
