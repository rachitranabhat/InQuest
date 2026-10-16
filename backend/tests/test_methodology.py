"""Data & Methodology API and the detection evaluation (synthetic data only)."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402
from evaluation import detection_eval as ev  # noqa: E402

pytestmark = pytest.mark.usefixtures("built_db")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _h(client, rid):
    return {"X-Reviewer-Session": client.post("/api/session", json={"reviewer_id": rid}).json()["token"]}


def test_overview_for_any_reviewer_with_counts_and_aggregate_categories(client):
    assert client.get("/api/methodology").status_code == 401
    o = client.get("/api/methodology", headers=_h(client, "REV-03")).json()
    assert o["dataset_version"].startswith("prism-synth-") and o["seed"] == 42
    for k in ("players", "transactions", "retailers", "terminals", "alerts", "cases"):
        assert o["counts"][k] > 0
    assert o["time_range_utc"][0] < o["time_range_utc"][1]
    assert sum(c["players"] for c in o["scenario_categories"]) == o["generated_counts"]["players"]
    text = str(o)
    assert "player_id" not in text and "label_suspicious" not in text and "@example.invalid" not in text


def test_labels_and_evaluation_are_senior_only(client):
    for rid in ("REV-01", "REV-03"):
        h = _h(client, rid)
        assert client.get("/api/methodology/labels", headers=h).status_code == 403
        assert client.get("/api/methodology/evaluation", headers=h).status_code == 403
    s = _h(client, "REV-02")
    lab = client.get("/api/methodology/labels?planted=1", headers=s).json()
    assert lab["total"] > 0 and all(r["label_suspicious"] == 1 for r in lab["rows"])
    assert not {"full_name", "email", "phone"} & set(lab["rows"][0])
    cat = client.get("/api/methodology/labels?category=normal&limit=5", headers=s).json()
    assert len(cat["rows"]) == 5 and {r["scenario_category"] for r in cat["rows"]} == {"normal"}
    assert client.get("/api/methodology/labels?category=x';--", headers=s).status_code == 422
    e = client.get("/api/methodology/evaluation", headers=s).json()
    pop = e["current_database"]["population"]
    cm = pop["confusion_matrix"]
    assert cm["tp"] + cm["fp"] + cm["fn"] + cm["tn"] == pop["n"]
    assert "Synthetic data only" in e["caveat"]


def test_metrics_arithmetic():
    m = ev.metrics([1, 1, 1, 0, 0, 0, 0, 0], [1, 1, 0, 1, 0, 0, 0, 0])
    assert m["confusion_matrix"] == {"tp": 2, "fp": 1, "fn": 1, "tn": 4}
    assert (m["precision"], m["recall"], m["f1"], m["false_positive_rate"]) == (0.667, 0.667, 0.667, 0.2)
    assert ev.metrics([0, 0], [0, 0])["precision"] is None          # undefined, not invented


def test_heldout_evaluation_has_no_label_leakage():
    import inspect
    from detection import monitoring
    assert "label" not in str(inspect.signature(monitoring.run_monitoring))   # rules never see labels
    assert ev.DEV_SEED not in ev.HELDOUT_SEEDS
    r = ev.evaluate_world(seed=ev.HELDOUT_SEEDS[0], n_players=60)
    cm = r["population"]["confusion_matrix"]
    assert sum(cm.values()) == r["population"]["n"] and r["seed"] != ev.DEV_SEED
    assert r["curated_subjects"] and all("curated_key" in c for c in r["curated_subjects"])
