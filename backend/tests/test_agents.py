"""Multi-agent investigation pipeline. LLM tests use a MOCKED model (no network); they are not live AI runs."""
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ai import llm_client  # noqa: E402
from api.main import app  # noqa: E402
from database.db import connect  # noqa: E402
from services import agents  # noqa: E402

pytestmark = pytest.mark.usefixtures("built_db")
RV = {"reviewer_id": "REV-01", "display_name": "Avery Chen", "role": "Investigator"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _case(i=0):
    with connect() as con:
        return con.execute("SELECT case_id FROM cases WHERE origin = 'monitoring' ORDER BY case_id").fetchall()[i][0]


def _owner():
    with connect() as con:
        return dict(con.execute("SELECT evidence_id, case_id FROM evidence").fetchall())


def _state(cid):
    with connect() as con:
        return (con.execute("SELECT status, updated_at_utc, assigned_reviewer_id FROM cases WHERE case_id = ?", (cid,)).fetchone()[:],
                con.execute("SELECT COUNT(*) FROM case_actions").fetchone()[0],
                con.execute("SELECT COUNT(*) FROM case_dispositions").fetchone()[0],
                con.execute("SELECT COUNT(*) FROM reports").fetchone()[0])


# ------------------------------------------------------------------ deterministic (simulated) pipeline
def test_one_case_produces_a_valid_structured_result():
    cid = _case()
    r = agents.run(cid, "deterministic", RV)
    assert r["case_id"] == cid and r["mode"] == "deterministic" and "Simulated analysis" in r["mode_label"]
    assert r["lead"]["assessment"] in agents.ASSESSMENTS
    for k in ("rationale", "recommended_next_step"):
        assert r["lead"][k] and not agents.ACCUSATORY.search(r["lead"][k])
    assert set(r["agents"]) == {"suspicion", "alternative"}
    for a in r["agents"].values():
        assert a["tool_calls"] and a["hypothesis_status"] in ("supported", "partially_supported", "not_supported", "undetermined")
    kinds = {f["kind"] for f in r["verified_findings"]}
    assert {"observation", "counterevidence", "missing_information"} <= kinds
    assert r["verified_findings"] and all(f["verification_status"] == "verified" for f in r["verified_findings"])
    assert "not a determination of fraud" in r["notice"]


def test_citations_are_valid_and_scoped_to_the_case():
    cid = _case(1)
    owner = _owner()
    r = agents.run(cid, "deterministic", RV)
    owner = _owner()                                    # include query_result items registered during the run
    for a in r["agents"].values():
        for c in a["tool_calls"]:
            assert all(owner[e] == cid for e in c["evidence_ids"]), c["tool"]       # tools only return this case
    retrieved = {e for a in r["agents"].values() for c in a["tool_calls"] for e in c["evidence_ids"]}
    for f in r["verified_findings"]:
        assert f["evidence_ids"] and all(owner[e] == cid and e in retrieved for e in f["evidence_ids"])
    lead_ids = [x["finding_id"] for k in ("strongest_supporting", "strongest_counterevidence", "missing_information")
                for x in r["lead"][k]]
    assert set(lead_ids) <= {f["finding_id"] for f in r["verified_findings"]}


def test_missing_evidence_is_acknowledged():
    r = agents.run(_case(2), "deterministic", RV)
    miss = [f for f in r["verified_findings"] if f["kind"] == "missing_information"]
    assert miss and r["lead"]["missing_information"]
    with connect() as con:
        types = {con.execute("SELECT type FROM evidence WHERE evidence_id = ?", (e,)).fetchone()[0]
                 for f in miss for e in f["evidence_ids"]}
    assert types == {"limitation"}


def test_agents_cannot_modify_reviewer_decisions_or_reach_write_tools():
    cid = _case(3)
    before = _state(cid)
    agents.run(cid, "deterministic", RV)
    assert _state(cid) == before                        # status, actions, dispositions, reports untouched
    assert not {"perform", "record", "record_disposition", "act", "start_review"} & set(agents.AGENT_TOOLS)
    with connect() as con:
        ts = agents.ToolSession(agents.CaseTools(con, cid), "suspicion")
        assert "not available" in ts.call("record_disposition", {"disposition": "substantiated"})["error"]
        assert "not available" in ts.call("get_previous_findings", {})["error"]   # must investigate, not rephrase
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(agents))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
               {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert not {"workflow", "dispositions", "services.workflow", "services.dispositions", "tx"} & imported
    code = "".join(c.value for c in ast.walk(tree) if isinstance(c, ast.Constant) and isinstance(c.value, str))
    assert "INSERT INTO" not in code and "UPDATE " not in code


# ------------------------------------------------------------------ LLM mode with a MOCKED model
class FakeModel:
    """Scripted stand-in for the OpenAI API: chooses tools, then returns findings (some deliberately invalid)."""

    def __init__(self, cid, other_case_evidence):
        self.cid, self.other, self.lead_prompts, self.agent_rounds = cid, other_case_evidence, [], 0
        self.seen = []

    def __call__(self, messages, *, tools=None, json_mode=False, **_k):
        system = messages[0]["content"]
        if "Lead investigator" in system:
            self.lead_prompts.append(messages[-1]["content"])
            ids = [f["finding_id"] for f in json.loads(messages[-1]["content"].split("\n", 1)[1])]
            return {"content": json.dumps({"assessment": "inconclusive", "rationale": "Findings point both ways.",
                                           "strongest_supporting": ids[:1] + ["F-99"], "strongest_counterevidence": ids[1:2],
                                           "missing_information": ids[-1:], "recommended_next_step": "Request the missing records."})}
        if tools:                                       # investigator tool rounds
            tool_msgs = [m for m in messages if m["role"] == "tool"]
            if not tool_msgs:
                return {"content": "", "tool_calls": [
                    {"id": "a", "type": "function", "function": {"name": "get_triggering_factors", "arguments": "{}"}},
                    {"id": "b", "type": "function", "function": {"name": "get_limitations", "arguments": "{}"}},
                    {"id": "c", "type": "function", "function": {"name": "record_disposition", "arguments": "{}"}}]}
            if len(tool_msgs) == 3:                     # second round: pick a follow-up based on what was returned
                return {"content": "", "tool_calls": [{"id": "d", "type": "function", "function": {
                    "name": "aggregate_transactions", "arguments": json.dumps({"group_by": "day"})}}]}
            self.seen = [json.loads(m["content"]) for m in tool_msgs]
            return {"content": "done"}
        # final findings
        factors = self.seen[0]["items"]
        lim = self.seen[1]["items"][0]
        fired = next(i for i in factors if i["type"] == "risk_factor")
        return {"content": json.dumps({"hypothesis_status": "partially_supported", "summary": "Mixed picture.", "findings": [
            {"kind": "observation", "text": f"Indicator recorded: {fired['title'].split(' · ')[0]}.", "evidence_ids": [fired["evidence_id"]]},
            {"kind": "observation", "text": "The subject made 987654 purchases.", "evidence_ids": [fired["evidence_id"]]},
            {"kind": "observation", "text": "Indicator recorded elsewhere.", "evidence_ids": [self.other]},
            {"kind": "missing_information", "text": lim["summary"], "evidence_ids": [lim["evidence_id"]]},
        ]})}


def test_mocked_llm_agents_choose_tools_and_lead_sees_verified_findings_only(monkeypatch):
    cid, other = _case(4), _case(5)
    with connect() as con:
        other_ev = con.execute("SELECT evidence_id FROM evidence WHERE case_id = ? LIMIT 1", (other,)).fetchone()[0]
    fake = FakeModel(cid, other_ev)
    monkeypatch.setattr(llm_client, "chat_message", fake)
    before = _state(cid)
    r = agents.run(cid, "llm", RV)
    assert r["mode"] == "llm" and r["agents"]["suspicion"]["mode"] == "llm"
    calls = r["agents"]["suspicion"]["tool_calls"]
    assert [c["tool"] for c in calls] == ["get_triggering_factors", "get_limitations", "record_disposition", "aggregate_transactions"]
    assert calls[2]["error"] and all(c["reason"] == "chosen by model" for c in calls)      # write attempt refused
    rejected = {f["text"]: f for f in r["rejected_findings"]}
    assert "The subject made 987654 purchases." in rejected                                  # invented number
    assert any("never retrieved" in x or "does not belong" in x or "not found" in x.lower()
               for x in rejected["Indicator recorded elsewhere."]["failures"])                # other case's evidence
    prompt = fake.lead_prompts[0]
    assert "987654" not in prompt and "Indicator recorded elsewhere" not in prompt
    sent = {f["finding_id"] for f in json.loads(prompt.split("\n", 1)[1])}
    assert sent == {f["finding_id"] for f in r["verified_findings"]}
    assert all(x["finding_id"] != "F-99" for x in r["lead"]["strongest_supporting"])         # invented reference dropped
    assert r["lead"]["missing_information"]
    assert _state(cid) == before


def test_llm_failure_falls_back_to_labelled_simulation(monkeypatch):
    def boom(*a, **k):
        raise llm_client.LLMUnavailable("no key (test)")
    monkeypatch.setattr(llm_client, "chat_message", boom)
    r = agents.run(_case(), "llm", RV)
    assert r["mode"] == "deterministic" and r["requested_mode"] == "llm"
    assert len(r["notes"]) == 3 and all("simulated" in n for n in r["notes"])


# ------------------------------------------------------------------ API
def _wait(client, h, inv_id, timeout=60):
    import time
    end = time.time() + timeout
    while time.time() < end:
        r = client.get(f"/api/investigations/{inv_id}", headers=h).json()
        if r["status"] != "running":
            return r
        time.sleep(0.2)
    raise AssertionError("investigation did not finish")


def test_api_start_runs_in_background_persists_and_keeps_history(client):
    cid = _case()
    assert client.post(f"/api/cases/{cid}/investigations", json={"mode": "deterministic"}).status_code == 401
    h = {"X-Reviewer-Session": client.post("/api/session", json={"reviewer_id": "REV-03"}).json()["token"]}
    r = client.post(f"/api/cases/{cid}/investigations", headers=h, json={"mode": "deterministic"})
    assert r.status_code == 202, r.text
    first = r.json()
    assert first["status"] in ("running", "completed") or first.get("already_running")
    done = _wait(client, h, first["investigation_id"])
    assert done["status"] == "completed" and done["lead"]["assessment"] in agents.ASSESSMENTS
    assert "database" in done["storage"]
    # explicit rerun adds a row; the earlier result is untouched
    second = _wait(client, h, client.post(f"/api/cases/{cid}/investigations", headers=h, json={"mode": "deterministic"}).json()["investigation_id"])
    assert second["investigation_id"] != done["investigation_id"]
    hist = client.get(f"/api/cases/{cid}/investigations", headers=h).json()
    ids = [x["investigation_id"] for x in hist]
    assert done["investigation_id"] in ids and second["investigation_id"] in ids and ids.index(second["investigation_id"]) < ids.index(done["investigation_id"])
    assert all(x["status"] == "completed" and x["mode"] == "deterministic" for x in hist if x["investigation_id"] in ids[:2])
    assert client.get(f"/api/investigations/{done['investigation_id']}", headers=h).json() == done   # unchanged by the rerun
    with connect() as con:                                           # stored in the database, not in memory
        row = con.execute("SELECT status, result_json FROM investigations WHERE investigation_id = ?", (done["investigation_id"],)).fetchone()
        assert row[0] == "completed" and json.loads(row[1])["lead"] == done["lead"]
        with pytest.raises(Exception, match="immutable"):
            con.execute("UPDATE investigations SET assessment = 'x' WHERE investigation_id = ?", (done["investigation_id"],))
        with pytest.raises(Exception, match="history"):
            con.execute("DELETE FROM investigations WHERE investigation_id = ?", (done["investigation_id"],))
    assert client.get(f"/api/investigations/{done['investigation_id']}").status_code == 401
    assert client.get("/api/investigations/INV-0000000000", headers=h).status_code == 404
    assert client.get("/api/investigations/INV-DROP%20TABLE", headers=h).status_code == 422
    assert client.post("/api/cases/CASE-99999/investigations", headers=h, json={}).status_code == 404
    assert client.post(f"/api/cases/{cid}/investigations", headers=h, json={"mode": "auto"}).status_code == 422
    assert "@example.invalid" not in json.dumps(done)                 # no identity data


def test_one_running_investigation_per_case_and_restart_marks_interrupted():
    from services import investigation_store as store
    cid = _case(6)
    rec = store.create(agents.new_id(), cid, "deterministic", "REV-01")      # simulate a run left running
    again = agents.start(cid, "deterministic", RV)
    assert again.get("already_running") and again["investigation_id"] == rec["investigation_id"]   # no duplicate
    assert store.mark_interrupted() >= 1                               # what server startup does
    got = store.get(rec["investigation_id"])
    assert got["status"] == "failed" and "Interrupted" in got["error"]


# ------------------------------------------------------------------ regression: invalid enum from the live model
class EnumModel:
    """MOCKED model reproducing the live failure: a finding with kind outside the enum (findings.4.kind)."""

    def __init__(self, fix_on_repair=True):
        self.fix, self.formats, self.repair_prompts, self.items = fix_on_repair, [], [], None

    def __call__(self, messages, *, tools=None, json_mode=False, response_format=None, **_k):
        if "Lead investigator" in messages[0]["content"]:
            return {"content": json.dumps({"assessment": "inconclusive", "rationale": "Mixed.", "strongest_supporting": [],
                                           "strongest_counterevidence": [], "missing_information": [],
                                           "recommended_next_step": "Request the missing records."})}
        if tools:
            if not any(m["role"] == "tool" for m in messages):
                return {"content": "", "tool_calls": [
                    {"id": "a", "type": "function", "function": {"name": "get_limitations", "arguments": "{}"}}]}
            self.items = json.loads(next(m for m in messages if m["role"] == "tool")["content"])["items"]
            return {"content": "done"}
        self.formats.append(response_format)
        lim = self.items[0]
        good = {"kind": "missing_information", "text": lim["summary"], "evidence_ids": [lim["evidence_id"]], "weight": "weak"}
        bad = {**good, "kind": "context_note"}                         # not one of the four allowed kinds
        repairing = "did not match the required schema" in messages[-1]["content"]
        if repairing:
            self.repair_prompts.append(messages[-1]["content"])
        findings = [good] * 4 + [good if (repairing and self.fix) else bad]
        return {"content": json.dumps({"findings": findings, "hypothesis_status": "undetermined", "summary": "Gaps only."})}


def test_invalid_enum_is_repaired_once_and_still_validated(monkeypatch):
    fake = EnumModel(fix_on_repair=True)
    monkeypatch.setattr(llm_client, "chat_message", fake)
    r = agents.run(_case(), "llm", RV)
    alt = r["agents"]["alternative"]
    assert alt["mode"] == "llm" and alt["stage_status"] == "live_repaired" and alt["fallback_reason"] is None
    fmt = fake.formats[0]                                              # strict structured output was requested
    kind = fmt["json_schema"]["schema"]["properties"]["findings"]["items"]["properties"]["kind"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] and kind["enum"] == agents.KIND_VALUES
    p = fake.repair_prompts[0]
    assert "findings.4.kind" in p and "observation, interpretation, counterevidence, missing_information" in p
    assert "Do not add new findings, facts or evidence IDs" in p
    assert len(fake.repair_prompts) == 2                               # exactly one repair per agent, never more
    for f in r["verified_findings"]:                                   # repaired output still went through the validator
        assert f["verification_status"] == "verified" and f["agent"] in ("suspicion", "alternative")
    assert r["mode"] == "llm" and r["lead"]["stage_status"] == "live"


def test_invalid_enum_twice_falls_back_with_reason(monkeypatch):
    fake = EnumModel(fix_on_repair=False)
    monkeypatch.setattr(llm_client, "chat_message", fake)
    r = agents.run(_case(), "llm", RV)
    for a in r["agents"].values():
        assert a["mode"] == "deterministic" and a["stage_status"] == "fallback"
        assert "after one repair attempt" in a["fallback_reason"] and a["failed_llm_tool_calls"]
    assert r["lead"]["stage_status"] == "live" and r["mode"] == "llm_partial_fallback"
    assert len(fake.repair_prompts) == 2                               # one per agent; no retry loop


def test_lead_ignoring_strong_counterevidence_is_flagged_not_overridden(monkeypatch):
    verified = [
        {"finding_id": "F-01", "agent": "suspicion", "kind": "observation", "weight": "strong", "text": "x", "evidence_ids": []},
        {"finding_id": "F-02", "agent": "alternative", "kind": "counterevidence", "weight": "strong", "text": "y", "evidence_ids": []}]
    lead = agents.LeadOutput(assessment="suspicion_supported", rationale="Indicators fired.", strongest_supporting=["F-01", "F-77"],
                             strongest_counterevidence=[], missing_information=[], recommended_next_step="Review the records.")
    out, warnings = agents._clean_lead(lead, verified)
    assert out.assessment == "suspicion_supported"                     # not forced to agree with the simulation
    assert out.strongest_supporting == ["F-01"]
    assert any("F-77" in w for w in warnings) and any("F-02" in w for w in warnings)
    assert "concern_reduced: strong counterevidence" in agents.LEAD_SYSTEM


# ------------------------------------------------------------------ presentation-readiness regressions (live run INV-97b269f1d5)
def _f(fid, agent, kind, weight, ev):
    return {"finding_id": fid, "agent": agent, "kind": kind, "weight": weight, "text": "t", "evidence_ids": ev}


def test_hypothesis_status_meaning_is_explicit_per_agent():
    r = agents.run(_case(), "deterministic", RV)
    alt, sus = r["agents"]["alternative"], r["agents"]["suspicion"]
    assert "ORDINARY-EXPLANATION" in alt["hypothesis_status_refers_to"]
    assert "SUSPICION" in sus["hypothesis_status_refers_to"]
    assert alt["conclusion"] == agents.ROLES["alternative"]["conclusions"][alt["hypothesis_status"]]
    assert agents.ROLES["alternative"]["conclusions"]["not_supported"] == "No ordinary explanation found in the records"
    assert "refers to YOUR hypothesis" in agents.AGENT_SYSTEM


def test_alternative_not_supported_with_strong_counterevidence_is_flagged():
    # live run: Alternative said not_supported while citing the jackpot week and a familiar retailer as strong counterevidence
    verified = [_f("F-12", "alternative", "counterevidence", "strong", ["EV-1"]),
                _f("F-14", "alternative", "missing_information", "strong", ["EV-2"])]
    w = agents.agent_consistency("alternative", "not_supported", verified)
    assert w and "F-12" in w[0] and "not supported" in w[0]
    assert agents.agent_consistency("alternative", "supported", verified) == []


def test_same_record_read_both_ways_is_linked_for_the_lead(monkeypatch):
    # live run: EV-000409 (80.5% at one retailer) was F-06 support AND F-13 counterevidence ("familiar retailer")
    fs = agents.mark_contested([_f("F-06", "suspicion", "observation", "strong", ["EV-409"]),
                                _f("F-13", "alternative", "counterevidence", "strong", ["EV-409"]),
                                _f("F-14", "alternative", "missing_information", "strong", ["EV-428"])])
    assert fs[0]["same_evidence_as"] == ["F-13"] and fs[1]["same_evidence_as"] == ["F-06"] and "same_evidence_as" not in fs[2]
    sent = {}

    def fake(messages, **_k):
        sent["payload"] = json.loads(messages[-1]["content"].split("\n", 1)[1])
        return {"content": json.dumps({"assessment": "inconclusive", "rationale": "One record, two readings.",
                                       "strongest_supporting": ["F-06"], "strongest_counterevidence": ["F-13", "F-14"],
                                       "missing_information": [], "recommended_next_step": "Check prior visits to the retailer."})}
    monkeypatch.setattr(llm_client, "chat_message", fake)
    lead, _rep = agents._lead_llm(fs, "CASE-X")
    assert sent["payload"][0]["same_evidence_as"] == ["F-13"]
    assert "one fact\nwith two readings" in agents.LEAD_SYSTEM or "one fact with two readings" in agents.LEAD_SYSTEM.replace("\n", " ")
    cleaned, warnings = agents._clean_lead(lead, fs)
    assert cleaned.strongest_counterevidence == ["F-13"]               # a gap is not counterevidence
    assert cleaned.missing_information == ["F-14"]                     # gaps are always surfaced
    assert any("wrong kind" in w and "F-14" in w for w in warnings)


def test_agent_prompt_asks_for_hedged_wording_without_touching_the_validator():
    assert "no unusual behaviour" in agents.AGENT_SYSTEM and "is consistent with" in agents.AGENT_SYSTEM
    from services import claims
    st, _ = claims.validate_claim({"section": "answer", "kind": "fact", "text": "The subject committed fraud.",
                                   "evidence_ids": []}, "CASE-X", {}, claims.Vocab([], []), None)
    assert st == "unverified"                                          # strict validator unchanged


# ---------------------------------------------------------------- cross-finding consistency (live-run regression)
def _replay():
    import copy
    from pathlib import Path
    d = json.loads((Path(__file__).parent / "fixtures" / "agents_case18016.json").read_text())
    return copy.deepcopy(d["findings"]), d["items"]


def _f(fid, agent, kind, text, ev, weight="strong"):
    return {"finding_id": fid, "agent": agent, "kind": kind, "weight": weight, "text": text, "evidence_ids": ev,
            "verification_status": "verified"}


def test_cross_check_rejects_network_share_misreading_and_history_contradiction():
    findings, items = _replay()
    kept, rej, warn = agents.cross_check(findings, items)
    out = {r["finding_id"]: r["failures"][0] for r in rej}
    assert set(out) == {"F-13", "F-14"}
    assert "share of the subject's own window transactions" in out["F-13"]          # 24.3% = 9 of 37, not the network
    assert "baseline EV-001227" in out["F-14"] and "49 earlier purchases" in out["F-14"]
    assert {f["finding_id"] for f in kept} == {f["finding_id"] for f in findings} - {"F-13", "F-14"}
    assert len(warn) == 2


def test_missing_history_beyond_the_baseline_is_allowed():
    _, items = _replay()
    ok = _f("F-90", "alternative", "missing_information",
            "The records do not include history older than the 23-day baseline period.", ["EV-001227"])
    kept, rej, _ = agents.cross_check([ok], items)
    assert kept and not rej


def test_unsupported_ordinary_explanation_is_marked_possible_and_peak_outside_event_noted():
    _, items = _replay()
    jackpot = _f("F-91", "alternative", "counterevidence",
                 "The window overlaps the jackpot draw week (2026-10-10 to 2026-10-11), which may explain higher activity.",
                 ["EV-001262"])
    kept, rej, _ = agents.cross_check([jackpot], items)
    assert not rej
    k = kept[0]
    notes = " ".join(k["cross_checks"])
    assert "Possible explanation, not verified" in notes and "24.3%" in notes
    assert "2026-10-12" in notes and "outside the event days" in notes           # peak burst is after the event
    assert k["weight"] == "weak"                                                  # covers < half of the activity
    lead = agents.LeadOutput(assessment="concern_reduced", rationale="test rationale.", strongest_supporting=[],
                             strongest_counterevidence=["F-91"], missing_information=[], recommended_next_step="test next step.")
    sup = _f("F-02", "suspicion", "observation", "x", ["EV-001231"])
    assert agents.lead_justification(lead, kept + [sup])                          # flagged, not overridden
    assert lead.assessment == "concern_reduced"


def test_alternative_finding_denying_anomalies_is_rejected():
    _, items = _replay()
    deny = _f("F-92", "alternative", "counterevidence",
              "Purchases were at familiar retailers, so there is no evidence of unusual behaviour.", ["EV-001226"])
    kept, rej, _ = agents.cross_check([deny], items)
    assert not kept and "Denies anomalies" in rej[0]["failures"][0]


def test_cross_check_leaves_assessment_to_the_lead():
    findings, items = _replay()
    kept, _, _ = agents.cross_check(findings, items)
    lead = agents.LeadOutput(assessment="suspicion_supported", rationale="test rationale.", strongest_supporting=["F-02"],
                             strongest_counterevidence=[], missing_information=[], recommended_next_step="test next step.")
    assert agents.lead_justification(lead, kept) == []
