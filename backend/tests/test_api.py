"""HTTP-level tests of the FastAPI app (requires fastapi + httpx)."""
import uuid

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

pytestmark = pytest.mark.usefixtures("built_db")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _login(client, rid="REV-01"):
    r = client.post("/api/session", json={"reviewer_id": rid})
    assert r.status_code == 200 and r.json()["kind"] == "simulated"
    return {"X-Reviewer-Session": r.json()["token"]}


def test_health_and_config(client):
    assert client.get("/api/health").json()["ok"]
    cfg = client.get("/api/config").json()
    assert "branding" in cfg and "OPENAI_API_KEY" not in str(cfg)


def test_end_to_end_investigation(client):
    h = _login(client)
    queue = client.get("/api/cases?sort=priority").json()
    assert queue["count"] > 0
    cid = queue["cases"][0]["case_id"]
    detail = client.get(f"/api/cases/{cid}").json()
    assert detail["case_id"] == cid and detail["factors"]
    ev = client.get(f"/api/cases/{cid}/evidence").json()
    assert any(e["type"] == "transaction" for e in ev)
    rep = client.post(f"/api/cases/{cid}/reports", json={"mode": "deterministic"}, headers=h).json()
    assert rep["validation"]["unverified"] == 0
    cited = rep["sections"][2]["claims"][0]["evidence_ids"][0]
    item = client.get(f"/api/cases/{cid}/evidence/{cited}").json()
    assert item["evidence_id"] == cited
    ans = client.post(f"/api/cases/{cid}/chat", json={"question": "Which retailer had the most transactions?"}, headers=h).json()
    assert ans["claims"] and all(c["verification_status"] == "verified" for c in ans["claims"])
    r = client.post(f"/api/cases/{cid}/actions", headers=h, json={"action": "start_review", "idempotency_key": uuid.uuid4().hex})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/cases/{cid}/actions", headers=h, json={
        "action": "escalate", "notes": "Pattern warrants specialist review.", "idempotency_key": uuid.uuid4().hex,
        "report_id": rep["report_id"], "expected_status": "Under Review"})
    assert r.status_code == 200 and r.json()["to_status"] == "Escalated"
    assert client.get(f"/api/cases/{cid}").json()["status"] == "Escalated"      # persisted
    pdf = client.get(f"/api/reports/{rep['report_id']}/pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert client.get(f"/api/reports/{rep['report_id']}").json()["status"] == "locked"


def test_validation_and_errors(client):
    h = _login(client, "REV-02")
    assert client.get("/api/cases/CASE-99999").status_code == 404
    assert client.get("/api/cases/DROP-TABLE").status_code == 422
    assert client.get("/api/cases/CASE-18001/evidence/EV-999999").status_code == 404
    other = client.get("/api/cases/CASE-18002/evidence").json()[0]["evidence_id"]
    assert client.get(f"/api/cases/CASE-18001/evidence/{other}").status_code == 404     # case scoping
    r = client.post("/api/cases/CASE-18001/actions", json={"action": "escalate", "notes": "x" * 20,
                                                          "idempotency_key": uuid.uuid4().hex})
    assert r.status_code == 401
    r = client.post("/api/cases/CASE-18001/actions", headers=h, json={"action": "close_no_action", "notes": "short",
                                                                      "idempotency_key": uuid.uuid4().hex})
    assert r.status_code == 422
    r = client.post("/api/cases/CASE-18001/actions", headers=h, json={"action": "delete_everything",
                                                                      "idempotency_key": uuid.uuid4().hex})
    assert r.status_code == 422


def test_graph_timeline_analytics_scenarios(client):
    h = _login(client)
    g = client.get("/api/cases/CASE-18005/graph").json()
    assert g["nodes"] and g["edges"]
    t = client.get("/api/cases/CASE-18005/timeline").json()
    assert t["transactions"] and len(t["hour_profile"]["window_total"]) == 24
    assert "open" in client.get("/api/analytics").json()
    sc = client.get("/api/scenarios").json()
    run = client.post(f"/api/scenarios/{sc[0]['key']}/run", headers=h).json()
    assert run["case_id"].startswith("CASE-")
    assert client.get(f"/api/cases/{run['case_id']}").json()["origin"] == "scenario_lab"


# ---------------------------------------------------------------- public-demo access controls
def test_demo_access_code_and_live_ai_limit(client, monkeypatch):
    from services import access
    monkeypatch.setenv("PRISM_DEMO_ACCESS_CODE", "test-code-123")
    monkeypatch.setenv("PRISM_LLM_DAILY_LIMIT", "1")
    access._USED.update(day="", n=0)
    assert client.get("/api/config").json()["access_code_required"] is True
    assert client.post("/api/session", json={"reviewer_id": "REV-01"}).status_code == 401
    assert client.post("/api/session", json={"reviewer_id": "REV-01", "access_code": "wrong"}).status_code == 401
    tok = client.post("/api/session", json={"reviewer_id": "REV-01", "access_code": "test-code-123"}).json()["token"]
    h = {"X-Reviewer-Session": tok}
    # anonymous visitors can read but not write or use live AI
    assert client.get("/api/cases").status_code == 200
    assert client.post("/api/cases/CASE-18001/reports", json={"mode": "deterministic"}).status_code == 401
    assert client.post("/api/cases/CASE-18001/chat", json={"question": "Why flagged?", "mode": "llm"}).status_code == 401
    # live-AI budget: one allowed, the next refused with 429 (no key in tests, so the allowed one falls back)
    assert client.post("/api/cases/CASE-18001/investigations", json={"mode": "llm"}, headers=h).status_code == 202
    r = client.post("/api/cases/CASE-18002/investigations", json={"mode": "llm"}, headers=h)
    assert r.status_code == 429
    # deterministic mode is never limited
    assert client.post("/api/cases/CASE-18002/investigations", json={"mode": "deterministic"}, headers=h).status_code == 202
