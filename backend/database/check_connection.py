"""Check the PostgreSQL / Supabase connection from V2's .env — read-only, changes nothing.

    cd backend && python -m database.check_connection

Prints the server version, whether TLS is in use, and whether the "prism" schema exists yet.
The password is never printed.
"""
from __future__ import annotations

import sys

import config
from database import pg


def main() -> int:
    if config.DB_BACKEND != "postgres":
        print("PRISM_DB_BACKEND is not 'postgres' in V2's .env — nothing to check (V2 is using SQLite).")
        return 1
    if not config.DATABASE_URL:
        print("DATABASE_URL is empty. Paste the Supabase Session pooler connection string into V2's .env.")
        return 1
    print(f"Connecting to {pg.redacted(config.DATABASE_URL)} ...")
    try:
        con = pg.connect(config.DATABASE_URL)
    except Exception as e:  # noqa: BLE001
        msg = str(e).replace(config.DATABASE_URL, "<DATABASE_URL>")
        print(f"Connection failed: {msg.strip()[:400]}")
        return 2
    try:
        version = con.execute("SHOW server_version").fetchone()[0]
        ssl = con.execute("SELECT ssl, version FROM pg_stat_ssl WHERE pid = pg_backend_pid()").fetchone()
        schema = con.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = ?", (pg.SCHEMA,)).fetchone()
        print(f"Connected. PostgreSQL {version}; TLS: {'yes (' + str(ssl[1]) + ')' if ssl and ssl[0] else 'NO'}; "
              f"schema '{pg.SCHEMA}': {'present' if schema else 'not created yet'}")
        local = pg.urlsplit(config.DATABASE_URL).hostname in ("localhost", "127.0.0.1", "::1")
        if not (ssl and ssl[0]) and not local:
            print("Refusing to continue without TLS.")
            return 3
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
