"""PostgreSQL-specific checks (V2). Translation tests always run; database tests need PRISM_TEST_BACKEND=postgres."""
import os

import pytest

from database import pg

PG = os.getenv("PRISM_TEST_BACKEND") == "postgres"
needs_pg = pytest.mark.skipif(not PG, reason="set PRISM_TEST_BACKEND=postgres to run against PostgreSQL")


@pytest.mark.parametrize("src,want", [
    ("SELECT * FROM t WHERE a = ? AND b LIKE ?", "SELECT * FROM t WHERE a = %s AND b ILIKE %s"),
    ("INSERT OR IGNORE INTO x VALUES (?,?)", "INSERT INTO x VALUES (%s,%s) ON CONFLICT DO NOTHING"),
    ("SELECT GROUP_CONCAT(c.case_id) FROM c", "SELECT string_agg(c.case_id, ',') FROM c"),
    ("SELECT id FROM e WHERE json_extract(provenance, '$.key') = ?", "SELECT id FROM e WHERE (provenance::jsonb ->> 'key') = %s"),
    ("SELECT 1 WHERE x IS NOT ? AND y IS ?", "SELECT 1 WHERE x IS DISTINCT FROM %s AND y IS NOT DISTINCT FROM %s"),
    ("SELECT '50% off?' WHERE a = ?", "SELECT '50%% off?' WHERE a = %s"),           # literals keep '?', % escaped
])
def test_translate(src, want):
    assert pg.translate(src) == want


def test_tls_is_enforced_for_hosted_databases():
    dsn = pg.safe_dsn("postgresql://u:secret@db.example.supabase.co:5432/postgres")
    assert "sslmode=require" in dsn
    with pytest.raises(ValueError):
        pg.safe_dsn("postgresql://u:p@db.example.supabase.co:5432/postgres?sslmode=disable")
    assert "sslmode" not in pg.safe_dsn("postgresql://postgres@localhost:5432/prism_test")
    assert "secret" not in pg.redacted("postgresql://u:secret@db.example.supabase.co:5432/postgres")


@needs_pg
@pytest.mark.usefixtures("built_db")
def test_schema_security_and_immutability():
    from database.db import connect
    with connect() as con:
        assert con.execute("SELECT current_schema()").fetchone()[0] == "prism"
        no_rls = con.execute("""SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                                WHERE n.nspname = 'prism' AND c.relkind = 'r' AND NOT c.relrowsecurity""").fetchall()
        assert [r[0] for r in no_rls] == []                     # RLS on every PRISM table (Data API sees nothing)
        assert con.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' "
                           "AND table_name IN ('cases', 'transactions')").fetchone()[0] == 0
        for sql, msg in [("UPDATE transactions SET amount = 0", "immutable"),
                         ("DELETE FROM transactions", "immutable"),
                         ("UPDATE evidence SET title = 'x'", "immutable")]:
            with pytest.raises(Exception, match=msg):
                con.execute(sql)


@needs_pg
@pytest.mark.usefixtures("built_db")
def test_writer_lock_serialises_id_allocation():
    import threading
    from database.db import connect, next_ids, tx
    got, errors = [], []

    def worker():
        try:
            with connect() as con:
                for _ in range(10):
                    with tx(con):
                        got.extend(next_ids(con, "LCK", 2))
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    ts = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors and len(got) == 80 and len(set(got)) == 80      # no duplicate IDs under concurrency


@pytest.mark.skipif(not os.getenv("PRISM_TEST_MIGRATION_URL"), reason="set PRISM_TEST_MIGRATION_URL (an empty test DB)")
def test_sqlite_to_postgres_copy_is_identical_and_repeatable(tmp_path):
    """Builds a small SQLite PRISM database, copies it into an empty PostgreSQL test database twice."""
    import json
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    url = os.environ["PRISM_TEST_MIGRATION_URL"]
    from urllib.parse import urlsplit
    assert "test" in urlsplit(url).path
    c = pg.connect(url)
    c._raw.execute("DROP SCHEMA IF EXISTS prism CASCADE")
    c.close()
    base = {**os.environ, "PRISM_DISABLE_DOTENV": "1", "PRISM_N_PLAYERS": "60", "PRISM_DATA_DIR": str(tmp_path)}
    src = tmp_path / "src.db"
    r = subprocess.run([sys.executable, "-c", "import pipeline; pipeline.build_dataset(verbose=False)"], cwd=root,
                       env={**base, "PRISM_DB_BACKEND": "sqlite", "PRISM_DB_PATH": str(src)}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1500:]
    shim = "from tests.support import pq_shim; pq_shim.install()\n" if os.getenv("PRISM_TEST_PQ_SHIM") == "1" else ""
    code = shim + f"from database import migrate_data; migrate_data.main(['--source', {str(src)!r}])"
    env = {**base, "PRISM_DB_BACKEND": "postgres", "DATABASE_URL": url}
    for run in (1, 2):
        r = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True, timeout=600)
        assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
        out = json.loads(r.stdout[r.stdout.rindex('{\n "tables"'):])
        assert out["all_identical"] and out["target_ok"]
        added = int(r.stdout.split("rows_added_total=")[1].split()[0])
        assert added > 0 if run == 1 else added == 0               # second run duplicates nothing
