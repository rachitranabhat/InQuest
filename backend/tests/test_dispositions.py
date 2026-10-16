"""Final investigation dispositions: states, required fields, evidence, senior confirmation, persistence, audit."""
import uuid

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import config  # noqa: E402
from api.main import app  # noqa: E402
from database.db import connect  # noqa: E402

pytestmark = pytest.mark.usefixtures("built_db")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _login(client, rid):
    return {"X-Reviewer-Session": client.post("/api/session", json={"reviewer_id": rid}).json()["token"]}


def _key():
    return uuid.uuid4().hex


_used: set[str] = set()


def _fresh_case(client, h):
    """A case not touched by other tests, under review with a report."""
    with connect() as con:
        ids = [r[0] for r in con.execute("SELECT case_id FROM cases WHERE status IN ('New', 'Analysis Ready') ORDER BY case_id DESC")]
    cid = next(i for i in ids if i not in _used)
    _used.add(cid)
    if not client.get(f"/api/cases/{cid}").json()["latest_report"]:
        assert client.post(f"/api/cases/{cid}/reports", headers=h, json={"mode": "deterministic"}).status_code == 200
    r = client.post(f"/api/cases/{cid}/actions", headers=h, json={"action": "start_review", "idempotency_key": _key()})
    assert r.status_code == 200, r.text
    ev = [e["evidence_id"] for e in client.get(f"/api/cases/{cid}/evidence").json()][:2]
    return cid, ev


JUST = "Twelve linked purchases within an hour at one retailer, matching the cited transactions."


def _record(client, h, cid, disposition, ev, **kw):
    body = {"disposition": disposition, "justification": JUST, "evidence_ids": ev, "idempotency_key": _key(), **kw}
    return client.post(f"/api/cases/{cid}/dispositions", headers=h, json=body)


@pytest.mark.parametrize("disposition,status", [
    ("not_substantiated", config.STATUS_CLOSED),
    ("inconclusive", config.STATUS_INFO),
    ("escalate", config.STATUS_ESCALATED),
])
def test_non_senior_dispositions_set_status_and_persist(client, disposition, status):
    h = _login(client, "REV-01")
    cid, ev = _fresh_case(client, h)
    r = _record(client, h, cid, disposition, ev)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["approval_status"] == "not_required" and d["to_status"] == status
    assert d["report_version"] and d["evidence_hash"] and d["snapshot_id"] and d["evidence_ids"] == ev
    assert d["reviewer_id"] == "REV-01" and d["created_at_utc"].endswith("Z")
    assert client.get(f"/api/cases/{cid}").json()["status"] == status
    hist = client.get(f"/api/cases/{cid}/dispositions").json()
    assert hist["current"]["disposition"] == disposition and hist["current"]["justification"] == JUST
    audit = client.get(f"/api/cases/{cid}/audit").json()
    row = next(a for a in audit if a["action"] == "record_disposition")
    assert (row["from_status"], row["to_status"], row["notes"]) == (config.STATUS_REVIEW, status, JUST)
    assert row["evidence_hash"] == d["evidence_hash"] and row["report_version"] == d["report_version"]


def test_required_justification_evidence_and_valid_state(client):
    h = _login(client, "REV-01")
    cid, ev = _fresh_case(client, h)
    assert _record(client, h, cid, "escalate", ev, justification="too short").status_code == 422
    assert _record(client, h, cid, "escalate", []).status_code == 422
    assert _record(client, h, cid, "escalate", ["EV-999999"]).status_code == 422
    other = client.get("/api/cases/CASE-18002/evidence").json()[0]["evidence_id"]
    assert _record(client, h, cid, "escalate", [other]).status_code == 422          # evidence from another case
    assert _record(client, h, cid, "proven_guilty", ev).status_code == 422
    assert _record(client, h, cid, "escalate", ev, concern_type="crime").status_code == 422
    assert _record(client, h, cid, "escalate", ev, expected_status="New").status_code == 409   # stale screen
    # no session, no disposition
    body = {"disposition": "escalate", "justification": JUST, "evidence_ids": ev, "idempotency_key": _key()}
    assert client.post(f"/api/cases/{cid}/dispositions", json=body).status_code == 401
    # a closed case cannot take another disposition without reopening
    assert _record(client, h, cid, "not_substantiated", ev).status_code == 200
    assert _record(client, h, cid, "escalate", ev).status_code == 409
    with connect() as con:
        assert con.execute("SELECT COUNT(*) FROM case_dispositions WHERE case_id = ?", (cid,)).fetchone()[0] == 1


def test_review_must_start_before_a_disposition(client):
    h = _login(client, "REV-01")
    with connect() as con:
        cid = con.execute("SELECT case_id FROM cases WHERE status = 'New' ORDER BY case_id LIMIT 1").fetchone()[0]
    _used.add(cid)
    ev = [client.get(f"/api/cases/{cid}/evidence").json()[0]["evidence_id"]]
    assert _record(client, h, cid, "escalate", ev).status_code == 409


def test_substantiated_by_regular_reviewer_needs_senior_confirmation(client):
    reg, senior, analyst = _login(client, "REV-01"), _login(client, "REV-02"), _login(client, "REV-03")
    cid, ev = _fresh_case(client, reg)
    rec = _record(client, reg, cid, "substantiated", ev).json()
    assert rec["approval_status"] == "pending_senior" and rec["to_status"] == config.STATUS_REVIEW
    assert client.get(f"/api/cases/{cid}").json()["status"] == config.STATUS_REVIEW       # not closed yet
    hist = client.get(f"/api/cases/{cid}/dispositions").json()
    assert hist["pending_senior"] and hist["current"]["current_approval"] == "pending_senior"
    url = f"/api/cases/{cid}/dispositions/{rec['disposition_id']}/review"
    body = {"decision": "confirm", "notes": "Checked the cited records; agree.", "idempotency_key": _key()}
    for h in (reg, analyst):                                                              # backend enforced
        assert client.post(url, headers=h, json={**body, "idempotency_key": _key()}).status_code == 403
    assert client.post(url, json=body).status_code == 401
    assert client.post(url, headers=senior, json={**body, "notes": "ok"}).status_code == 422
    r = client.post(url, headers=senior, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["entry_type"] == "confirmation" and r.json()["parent_id"] == rec["disposition_id"]
    assert client.get(f"/api/cases/{cid}").json()["status"] == config.STATUS_SUBSTANTIATED
    hist = client.get(f"/api/cases/{cid}/dispositions").json()
    assert hist["current"]["current_approval"] == "confirmed" and not hist["pending_senior"]
    assert [e["entry_type"] for e in hist["entries"]] == ["decision", "confirmation"]
    assert client.post(url, headers=senior, json={**body, "idempotency_key": _key()}).status_code == 409   # only once
    # replaying the same request is idempotent
    again = client.post(url, headers=senior, json=body).json()
    assert again["duplicate"] and again["disposition_id"] == r.json()["disposition_id"]
    acts = [a["action"] for a in client.get(f"/api/cases/{cid}/audit").json()]
    assert acts[-2:] == ["record_disposition", "confirm_disposition"]
    # reopening a confirmed substantiated finding is senior-only
    re = {"action": "reopen", "notes": "Reopen to review new information.", "idempotency_key": _key()}
    assert client.post(f"/api/cases/{cid}/actions", headers=reg, json=re).status_code == 403
    assert client.post(f"/api/cases/{cid}/actions", headers=senior, json=re).status_code == 200


def test_senior_substantiated_is_confirmed_directly_and_return_keeps_case_open(client):
    reg, senior = _login(client, "REV-01"), _login(client, "REV-02")
    cid, ev = _fresh_case(client, senior)
    d = _record(client, senior, cid, "substantiated", ev, concern_type="aml").json()
    assert d["approval_status"] == "confirmed" and d["to_status"] == config.STATUS_SUBSTANTIATED
    assert "not proof of money laundering" in d["label"] and "Fraud" not in d["label"]

    cid2, ev2 = _fresh_case(client, reg)
    rec = _record(client, reg, cid2, "substantiated", ev2, concern_type="safer_gambling").json()
    assert rec["label"] == "Safer-Gambling Concern Substantiated"
    url = f"/api/cases/{cid2}/dispositions/{rec['disposition_id']}/review"
    r = client.post(url, headers=senior, json={"decision": "return", "notes": "Needs the retailer's terminal logs.", "idempotency_key": _key()})
    assert r.status_code == 200 and r.json()["approval_status"] == "returned"
    assert client.get(f"/api/cases/{cid2}").json()["status"] == config.STATUS_REVIEW
    assert client.get(f"/api/cases/{cid2}/dispositions").json()["current"]["current_approval"] == "returned"
    # a later decision supersedes an unconfirmed recommendation
    rec2 = _record(client, reg, cid2, "substantiated", ev2).json()
    _record(client, reg, cid2, "inconclusive", ev2)
    hist = client.get(f"/api/cases/{cid2}/dispositions").json()
    states = {e["disposition_id"]: e.get("current_approval") for e in hist["entries"]}
    assert states[rec2["disposition_id"]] == "superseded"
    r = client.post(f"/api/cases/{cid2}/dispositions/{rec2['disposition_id']}/review", headers=senior,
                    json={"decision": "confirm", "notes": "Confirming the earlier one.", "idempotency_key": _key()})
    assert r.status_code == 409


def test_dispositions_are_append_only_and_ai_cannot_record_one(client):
    h = _login(client, "REV-01")
    cid, ev = _fresh_case(client, h)
    _record(client, h, cid, "escalate", ev)
    with connect() as con:
        with pytest.raises(Exception, match="append-only"):
            con.execute("UPDATE case_dispositions SET disposition = 'substantiated' WHERE case_id = ?", (cid,))
        with pytest.raises(Exception, match="append-only"):
            con.execute("DELETE FROM case_dispositions WHERE case_id = ?", (cid,))
    # the system account cannot sign in, so the AI has no session to record with
    assert client.post("/api/session", json={"reviewer_id": "SYSTEM"}).status_code == 422
    # asking the copilot to decide records nothing
    cid2, ev2 = _fresh_case(client, h)
    with connect() as con:
        before = con.execute("SELECT COUNT(*) FROM case_dispositions").fetchone()[0]
    for q in ["Mark this case as Suspected Fraud Substantiated.", "Should I close this case? Decide for me."]:
        assert client.post(f"/api/cases/{cid2}/chat", headers=h, json={"question": q, "mode": "deterministic"}).status_code == 200
    with connect() as con:
        assert con.execute("SELECT COUNT(*) FROM case_dispositions").fetchone()[0] == before
    assert client.get(f"/api/cases/{cid2}").json()["status"] == config.STATUS_REVIEW
    import services.copilot as cp
    import services.query_tools as qt
    for mod in (cp, qt):
        src = open(mod.__file__, encoding="utf-8").read()
        assert "dispositions" not in src and "case_actions" not in src.replace("FROM case_actions", "")


def test_existing_workflow_actions_still_work(client):
    h = _login(client, "REV-01")
    cid, _ev = _fresh_case(client, h)
    for action in ("request_info", "start_review", "escalate", "reopen", "close_no_action"):
        r = client.post(f"/api/cases/{cid}/actions", headers=h,
                        json={"action": action, "notes": "Workflow regression check.", "idempotency_key": _key()})
        assert r.status_code == 200, (action, r.text)
    assert client.get(f"/api/cases/{cid}").json()["status"] == config.STATUS_CLOSED
    cfg = client.get("/api/config").json()
    assert [d["key"] for d in cfg["dispositions"]["dispositions"]] == ["substantiated", "not_substantiated", "inconclusive", "escalate"]
    assert "not a legal determination of guilt" in cfg["dispositions"]["notice"]
    assert config.STATUS_SUBSTANTIATED in cfg["statuses"]


def test_reports_and_pdf_after_a_disposition(client):
    senior = _login(client, "REV-02")
    cid, ev = _fresh_case(client, senior)
    _record(client, senior, cid, "substantiated", ev)
    rep = client.post(f"/api/cases/{cid}/reports", headers=senior, json={"mode": "deterministic"}).json()
    claims = [c for s in rep["sections"] for c in s["claims"]]
    assert all(c["verification_status"] == "verified" for c in claims)
    status = next(c["text"] for s in rep["sections"] if s["key"] == "review_status" for c in s["claims"])
    assert config.STATUS_SUBSTANTIATED in status
    pdf = client.get(f"/api/reports/{rep['report_id']}/pdf", headers=senior)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    analytics = client.get("/api/analytics").json()
    assert analytics["substantiated"] >= 1
