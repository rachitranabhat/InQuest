"""Workspace views: history comparison, completeness breakdown, bookmarks (service + HTTP)."""
import pytest

from database.db import connect
from services import cases, repo, workspace

pytestmark = pytest.mark.usefixtures("built_db")


def _case(channel="lottery_terminal"):
    return next(c["case_id"] for c in cases.list_cases()["cases"] if c["channel"] == channel)


def _evidence(case_id):
    with connect() as con:
        c = repo.case_row(con, case_id)
        return {i["provenance"]["key"]: i for i in repo.evidence_items(con, case_id, c["current_snapshot_id"], False)}


def test_history_rows_are_derived_from_stored_evidence():
    cid = _case()
    h = workspace.history(cid)
    ev = _evidence(cid)
    assert h["available"]
    rows = {r["key"]: r for r in h["rows"]}
    per_day = ev["cmp:per_day"]["computed"]
    assert rows["per_day"]["previous"] == per_day["baseline"] and rows["per_day"]["current"] == per_day["current"]
    assert ev["cmp:per_day"]["evidence_id"] in rows["per_day"]["evidence_ids"]
    # spend per day is the stored weekly totals divided by period length
    assert rows["spend_per_day"]["previous"] == round(ev["baseline"]["computed"]["typical_week_total"] / 7, 2)
    assert rows["spend_per_day"]["current"] == round(ev["metric:window"]["computed"]["total_amount"] / 7, 2)
    # shares change in percentage points, never as a % of a zero
    ns = rows["overnight_share"]
    assert ns["change_unit"] == "pp" and ns["change"] == round(ns["current"] - ns["previous"], 2)
    # previous active days are not in the evidence: shown as unavailable, not invented
    assert rows["active_days"]["previous"] is None and rows["active_days"]["reliability"] == "unavailable"
    # unnormalized counts are flagged
    assert rows["retailers"]["reliability"] == "caution" and "different length" in rows["retailers"]["note"]
    every_id = {i["evidence_id"] for i in ev.values()}
    assert all(set(r["evidence_ids"]) <= every_id for r in h["rows"])


def test_history_zero_previous_value_has_no_percentage():
    cid = _case()
    h = workspace.history(cid)
    for r in h["rows"]:
        if r["previous"] == 0 and r["kind"] != "share":
            assert r["change"] is None and r["change_unit"] == "none_before"


def test_completeness_breakdown():
    cid = _case()
    out = workspace.completeness(cid)
    keys = {i["key"]: i for i in out["items"]}
    assert keys["timestamps"]["state"] == "available"
    assert keys["identity"]["state"] == "missing"
    assert keys["linkage"]["state"] in {"verified", "partial", "ambiguous"}
    assert sum(out["counts"].values()) == len(out["items"])
    assert out["overall"] in {"Complete", "Partial", "Limited"}
    acct = workspace.completeness(_case("online_account"))
    assert {"device", "payment"} <= {i["key"] for i in acct["items"]}


def test_bookmarks_http(client_and_login):
    client, h = client_and_login
    cid = _case()
    ev = client.get(f"/api/cases/{cid}/evidence").json()
    txn = next(e for e in ev if e["type"] == "transaction")
    assert client.post(f"/api/cases/{cid}/bookmarks", json={"evidence_id": txn["evidence_id"]}).status_code == 401
    b = client.post(f"/api/cases/{cid}/bookmarks", headers=h, json={"evidence_id": txn["evidence_id"], "note": "check"}).json()
    assert b["kind"] == "transaction" and b["note"] == "check"
    again = client.post(f"/api/cases/{cid}/bookmarks", headers=h, json={"evidence_id": txn["evidence_id"]}).json()
    assert again["bookmark_id"] == b["bookmark_id"] and again["note"] == "check"       # one active bookmark per item
    n = client.post(f"/api/cases/{cid}/bookmarks/{b['bookmark_id']}/note", headers=h, json={"note": "seen twice"}).json()
    assert n["note"] == "seen twice"
    assert [x["bookmark_id"] for x in client.get(f"/api/cases/{cid}/bookmarks").json()] == [b["bookmark_id"]]
    other = next(c["case_id"] for c in cases.list_cases()["cases"] if c["case_id"] != cid)
    foreign = client.get(f"/api/cases/{other}/evidence").json()[0]["evidence_id"]
    assert client.post(f"/api/cases/{cid}/bookmarks", headers=h, json={"evidence_id": foreign}).status_code == 404
    assert client.post(f"/api/cases/{other}/bookmarks/{b['bookmark_id']}/remove", headers=h).status_code == 404
    assert client.post(f"/api/cases/{cid}/bookmarks/{b['bookmark_id']}/remove", headers=h).status_code == 200
    assert client.get(f"/api/cases/{cid}/bookmarks").json() == []


def test_queue_completeness_filter_and_history_endpoints(client_and_login):
    client, _ = client_and_login
    q = client.get("/api/cases?completeness=Partial").json()
    assert all(c["evidence_completeness"] == "Partial" for c in q["cases"])
    assert client.get("/api/cases?completeness=Bogus").status_code == 422
    assert client.get("/api/cases?sort=updated").status_code == 200
    cid = q["cases"][0]["case_id"] if q["cases"] else _case()
    assert client.get(f"/api/cases/{cid}/history").json()["rows"]
    assert client.get(f"/api/cases/{cid}/completeness").json()["items"]


@pytest.fixture(scope="module")
def client_and_login():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from api.main import app
    with TestClient(app) as c:
        r = c.post("/api/session", json={"reviewer_id": "REV-01"})
        yield c, {"X-Reviewer-Session": r.json()["token"]}
