"""Versioned dataset: reproducible generation, export/import round trip, labels kept apart from investigators."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.usefixtures("built_db")

SNIPPET = r"""
import json, sys
from database import db, verify
mode, folder = sys.argv[1], sys.argv[2]
if mode == "export":
    from data.dataset_io import export
    export(__import__("pathlib").Path(folder), "csv", "generator")
    print("{}"); sys.exit(0)
elif mode == "import":
    from data.dataset_io import import_folder
    print(json.dumps(import_folder(__import__("pathlib").Path(folder)), default=str)[:200], file=sys.stderr)
else:
    import pipeline; pipeline.build_dataset(verbose=False)
with db.connect() as con:
    out = {t: verify.table_fingerprint(con, t) for t in
           ["locations", "retailers", "players", "accounts", "events", "transactions", "scenario_labels"]}
    out["snapshot_hashes"] = sorted(r[0] for r in con.execute("SELECT evidence_hash FROM evidence_snapshots"))
    out["cases"] = verify.table_fingerprint(con, "cases", exclude=("created_at_utc", "updated_at_utc"))
    out["dataset"] = [tuple(r)[:2] for r in con.execute("SELECT dataset_version, seed FROM dataset_versions")]
print(json.dumps(out))
"""


def _run(tmp: Path, name: str, mode: str, folder: Path) -> dict:
    env = {**os.environ, "PRISM_DB_BACKEND": "sqlite", "PRISM_DB_PATH": str(tmp / f"{name}.db"),
           "PRISM_DATA_DIR": str(tmp / name), "PRISM_N_PLAYERS": "60", "PRISM_DISABLE_DOTENV": "1"}
    r = subprocess.run([sys.executable, "-c", SNIPPET, mode, str(folder)], cwd=ROOT, env=env, capture_output=True,
                       text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_export_import_round_trip_is_identical_and_not_duplicated(tmp_path):
    folder = tmp_path / "synth"
    direct = _run(tmp_path, "direct", "build", folder)
    _run(tmp_path, "exporter", "export", folder)
    man = json.loads((folder / "manifest.json").read_text())
    assert man["generation_config"]["seed"] == 42 and man["dataset_version"].startswith("prism-synth-")
    assert set(man["files"]) >= {"transactions.csv", "players.csv", "scenario_labels.csv", "retailers.csv"}
    assert "player_identities.csv" not in man["files"]
    assert man["composition"]["planted_suspicious"] > 0
    imported = _run(tmp_path, "imported", "import", folder)
    assert imported == direct                                   # same rows, cases and evidence fingerprints
    again = _run(tmp_path, "imported", "import", folder)        # second import into the same database
    assert again["transactions"][0] == direct["transactions"][0]   # no duplicated rows
    # a modified file is rejected before anything is written
    f = folder / "transactions.csv"
    f.write_text(f.read_text().replace(",lottery_terminal,", ",online_account,", 1))
    env = {**os.environ, "PRISM_DB_PATH": str(tmp_path / "x.db"), "PRISM_DATA_DIR": str(tmp_path / "x"),
           "PRISM_N_PLAYERS": "60", "PRISM_DB_BACKEND": "sqlite"}
    r = subprocess.run([sys.executable, "-m", "data.dataset_io", "import", str(folder)], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode != 0 and "hash mismatch" in (r.stdout + r.stderr)


def test_labels_are_recorded_and_categorised():
    from database.db import connect
    with connect() as con:
        n_players = con.execute("SELECT COUNT(*) FROM players").fetchone()[0]
        rows = con.execute("SELECT scenario_category, label_suspicious FROM scenario_labels").fetchall()
        dv = con.execute("SELECT * FROM dataset_versions").fetchone()
    generated = json.loads(dv["counts_json"])["players"]
    assert len(rows) == generated <= n_players        # every generated player has a label (lab subjects come later)
    cats = {r[0] for r in rows}
    assert "uncategorised" not in cats and "normal" in cats
    assert all(r[1] == 1 for r in rows if r[0].startswith("suspicious_") or r[0] == "aml_like_passthrough")
    assert all(r[1] == 0 for r in rows if r[0].startswith(("explainable_", "ambiguous", "normal")))
    cfg = json.loads(dv["config_json"])
    assert cfg["seed"] == 42 and cfg["config_sha256"] and dv["time_start_utc"] < dv["time_end_utc"]


def test_labels_never_reach_investigator_code():
    for mod in ["copilot", "query_tools", "reports", "report_writer", "evidence_registry", "findings", "cases",
                "workspace", "context", "graph", "claims", "pdf_export"]:
        p = ROOT / "services" / f"{mod}.py"
        if p.exists():
            src = p.read_text(encoding="utf-8")
            assert "scenario_labels" not in src and "label_suspicious" not in src, mod
    for p in (ROOT / "detection").glob("*.py"):
        assert "scenario_labels" not in p.read_text(encoding="utf-8"), p.name
