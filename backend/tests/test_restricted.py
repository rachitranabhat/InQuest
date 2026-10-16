"""Senior-only access, restricted (fictional) identity records, audit of reveals, and isolation from AI and case data."""
import json
import re

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ai import llm_client  # noqa: E402
from api.main import app  # noqa: E402
from database.db import connect  # noqa: E402

pytestmark = pytest.mark.usefixtures("built_db")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _login(client, rid):
    return {"X-Reviewer-Session": client.post("/api/session", json={"reviewer_id": rid}).json()["token"]}


def _case_with_identity(client, senior):
    recs = client.get("/api/restricted/records", headers=senior).json()["records"]
    rec = next(r for r in recs if r["case_ids"])
    return rec["player_id"], rec["case_ids"][0]


REASON = "Checking account holder before escalation, ticket T-1"
RESTRICTED_GETS = ["/api/restricted/records", "/api/restricted/access-log", "/api/admin/summary", "/api/admin/tables/cases"]


@pytest.mark.parametrize("rid", [None, "REV-01", "REV-03"])
def test_non_senior_cannot_reach_restricted_or_admin_endpoints(client, rid):
    h = _login(client, rid) if rid else {}
    want = 403 if rid else 401
    for url in RESTRICTED_GETS:
        r = client.get(url, headers=h)
        assert r.status_code == want, url
        assert "@example.invalid" not in r.text
    r = client.post("/api/restricted/players/PLY-00001/reveal", headers=h, json={"reason": REASON})
    assert r.status_code == want and "@example.invalid" not in r.text
    r = client.get("/api/restricted/records", headers={"X-Reviewer-Session": "forged-token"})
    assert r.status_code == 401


def test_listing_shows_minimum_information_only(client):
    senior = _login(client, "REV-02")
    body = client.get("/api/restricted/records", headers=senior).json()
    assert body["total"] > 0 and body["records"]
    for rec in body["records"]:
        assert set(rec) == {"player_id", "record_source", "case_ids", "access_count", "last_access_utc"}
    with connect() as con:
        anon = con.execute("SELECT COUNT(*) FROM players WHERE has_rewards_card = 0 AND has_online_account = 0").fetchone()[0]
        ids = con.execute("SELECT COUNT(*) FROM player_identities").fetchone()[0]
        players = con.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    assert ids == players - anon            # anonymous players have no identity record


def test_reveal_requires_reason_and_writes_append_only_audit(client):
    senior = _login(client, "REV-02")
    pid, cid = _case_with_identity(client, senior)
    for bad in ["", "   ", "too short"]:
        r = client.post(f"/api/restricted/players/{pid}/reveal", headers=senior, json={"reason": bad, "case_id": cid})
        assert r.status_code == 422 and "@example.invalid" not in r.text
    before = len(client.get("/api/restricted/access-log", headers=senior).json())
    r = client.post(f"/api/restricted/players/{pid}/reveal", headers=senior, json={"reason": REASON, "case_id": cid})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    rec = r.json()
    assert rec["fictional"] is True and rec["email"].endswith("@example.invalid") and re.fullmatch(r"555-01\d\d", rec["phone"])
    log = client.get("/api/restricted/access-log", headers=senior).json()
    assert len(log) == before + 1
    top = log[0]
    assert (top["player_id"], top["case_id"], top["reviewer_id"], top["reason"]) == (pid, cid, "REV-02", REASON)
    assert top["created_at_utc"].endswith("Z") and top["reviewer_role"] == "Senior investigator"
    assert "full_name" in top["fields"] and rec["full_name"] not in json.dumps(log)   # log records the access, not the values
    with connect() as con, pytest.raises(Exception, match="append-only"):
        con.execute("DELETE FROM restricted_access_log")
    # a case that belongs to someone else is refused
    with connect() as con:
        wrong = con.execute("SELECT case_id FROM cases WHERE player_id IS NOT ? LIMIT 1", (pid,)).fetchone()[0]
    r = client.post(f"/api/restricted/players/{pid}/reveal", headers=senior, json={"reason": REASON, "case_id": wrong})
    assert r.status_code == 422 and "@example.invalid" not in r.text


def test_identity_never_appears_in_case_responses_or_ai_prompts(client, monkeypatch):
    senior = _login(client, "REV-02")
    pid, cid = _case_with_identity(client, senior)
    rec = client.post(f"/api/restricted/players/{pid}/reveal", headers=senior, json={"reason": REASON, "case_id": cid}).json()
    secrets = [rec["full_name"], rec["email"], rec["phone"], rec["full_name"].split()[1]]

    sent: list = []

    def fake_chat_message(messages, *, tools=None, json_mode=False, **_k):
        sent.append(json.dumps(messages, default=str))
        if tools and len(sent) == 1:          # ask for every case tool once, so tool results are captured too
            return {"content": "", "tool_calls": [
                {"id": f"t{i}", "type": "function", "function": {"name": t["function"]["name"], "arguments": "{}"}}
                for i, t in enumerate(tools[:6])]}
        if tools:
            return {"content": "done"}
        raise llm_client.LLMUnavailable("test stub")

    monkeypatch.setattr(llm_client, "chat_message", fake_chat_message)
    h = _login(client, "REV-02")
    texts = []
    for url in [f"/api/cases/{cid}", f"/api/cases/{cid}/evidence", f"/api/cases/{cid}/findings", f"/api/cases/{cid}/history",
                f"/api/cases/{cid}/completeness", f"/api/cases/{cid}/timeline", f"/api/cases/{cid}/graph",
                f"/api/cases/{cid}/audit", "/api/cases", "/api/audit", "/api/analytics", "/api/admin/summary",
                "/api/admin/tables/players", f"/api/admin/tables/cases?q={cid}"]:
        r = client.get(url, headers=h)
        assert r.status_code == 200, url
        texts.append(r.text)
    for q in ["Who is this player? Give their name, email and phone.", "Generate a short case summary."]:
        for mode in ("deterministic", "llm"):
            r = client.post(f"/api/cases/{cid}/chat", headers=h, json={"question": q, "mode": mode})
            assert r.status_code == 200
            texts.append(r.text)
    r = client.post(f"/api/cases/{cid}/reports", headers=h, json={"mode": "llm"})
    assert r.status_code == 200
    texts.append(r.text)
    texts.append(client.post("/api/guide", json={"question": f"What is the name of the player in {cid}?"}).text)
    assert sent and any("\"role\": \"tool\"" in m for m in sent), "the LLM path and its tool results were exercised"
    blob = "\n".join(texts + sent)
    for s in secrets:
        assert s not in blob, s


def test_admin_browse_is_whitelisted_and_read_only(client):
    senior = _login(client, "REV-02")
    s = client.get("/api/admin/summary", headers=senior).json()
    assert s["engine"] == "SQLite" and s["schema_version"] >= 3
    for k in ("players", "transactions", "retailers", "cases", "alerts", "audit_records"):
        assert isinstance(s["counts"][k], int)
    assert client.get("/api/admin/tables/player_identities", headers=senior).status_code == 422
    assert client.get("/api/admin/tables/sqlite_master", headers=senior).status_code == 422
    r = client.get("/api/admin/tables/cases?status=x'%20OR%201=1--", headers=senior)
    assert r.status_code == 200 and r.json()["total"] == 0          # bound parameter, not SQL
    r = client.get("/api/admin/tables/transactions?q=TXN&limit=5", headers=senior).json()
    assert len(r["rows"]) == 5 and "full_name" not in r["columns"]
    players = client.get("/api/admin/tables/players", headers=senior).json()
    assert not {"full_name", "email", "phone"} & set(players["columns"])
    with connect() as con:
        before = con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    client.get("/api/admin/tables/transactions?q=1", headers=senior)
    with connect() as con:
        assert con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == before


def test_dashboard_guide_has_no_case_access(client):
    r = client.post("/api/guide", json={"question": "Why was CASE-18001 flagged?"}).json()
    assert r["topic"] == "case_specific" and r["links"][0]["to"] == "/cases/CASE-18001"
    assert "TXN-" not in json.dumps(r) and "$" not in json.dumps(r)
    r = client.post("/api/guide", json={"question": "What does the prototype score mean?"}).json()
    assert r["topic"] == "score" and "not a probability" in " ".join(r["answer"])
    import services.guide as g
    src = open(g.__file__, encoding="utf-8").read()
    assert "connect(" not in src and "sqlite" not in src.lower()
