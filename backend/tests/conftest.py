"""Test setup: an isolated database built from a small seeded dataset (never the dev database)."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_tmp = Path(tempfile.mkdtemp(prefix="prism-test-"))
os.environ["PRISM_DB_PATH"] = str(_tmp / "test.db")
os.environ["PRISM_DATA_DIR"] = str(_tmp)
os.environ["PRISM_EXPORT_DIR"] = str(_tmp / "exports")
os.environ.setdefault("PRISM_N_PLAYERS", "150")
os.environ["OPENAI_API_KEY"] = ""          # tests never call a real LLM
os.environ["PRISM_DISABLE_DOTENV"] = "1"

# V2: PRISM_TEST_BACKEND=postgres runs the same suite against PostgreSQL. It needs PRISM_TEST_DATABASE_URL
# pointing at a DISPOSABLE database whose name contains "test" (or PRISM_TEST_DISPOSABLE_DATABASE=1 for a
# throwaway Supabase project, whose database is always called "postgres"); its "prism" schema is DROPPED.
TEST_BACKEND = os.getenv("PRISM_TEST_BACKEND", "sqlite")
if TEST_BACKEND == "postgres":
    _url = os.environ["PRISM_TEST_DATABASE_URL"]
    from urllib.parse import urlsplit
    if "test" not in urlsplit(_url).path and os.getenv("PRISM_TEST_DISPOSABLE_DATABASE") != "1":
        raise SystemExit("Refusing to run: PRISM_TEST_DATABASE_URL must name a disposable *test* database.")
    os.environ["PRISM_DB_BACKEND"] = "postgres"
    os.environ["DATABASE_URL"] = _url
    try:
        import psycopg  # noqa: F401
    except ImportError:
        if os.getenv("PRISM_TEST_PQ_SHIM") == "1":       # sandbox only: see tests/support/pq_shim.py
            from tests.support import pq_shim
            pq_shim.install()
        else:
            raise
    from database import pg as _pg
    _c = _pg.connect(_url)
    _c._raw.execute("DROP SCHEMA IF EXISTS prism CASCADE")
    _c.close()
else:
    os.environ["PRISM_DB_BACKEND"] = "sqlite"

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def built_db():
    import pipeline

    return pipeline.build_dataset(verbose=False)
