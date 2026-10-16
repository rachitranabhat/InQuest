"""Evidence registry, claim validation, reports, copilot tools, workflow, graph, export."""
import uuid

import pytest

import config
from database.db import connect
from services import cases, copilot, graph, pdf_export, reports, repo, scenarios, workflow
from services.claims import build_index, validate_claim
from services.query_tools import CaseTools

pytestmark = pytest.mark.usefixtures("built_db")


def _case(curated):
    with connect() as con:
        return con.execute("SELECT case_id FROM cases WHERE curated_key = ? AND origin = 'monitoring'",
                           (curated,)).fetchone()[0]


def _ctx(case_id):
    con_ctx = connect()
    con = con_ctx.__enter__()
    items = repo.evidence_items(con, case_id)
    return con_ctx, con, items, build_index(items), repo.vocab(con), repo.evidence_owner(con)


def _check(case_id, text, ids, assertions=None):
    cm, con, items, idx, voc, look = _ctx(case_id)
    try:
        return validate_claim({"text": text, "evidence_ids": ids, "kind": "fact", "assertions": assertions or []},
                              case_id, idx, voc, look)
    finally:
        cm.__exit__(None, None, None)


def _key(case_id, key):
    cm, con, items, *_ = _ctx(case_id)
    cm.__exit__(None, None, None)
    return next(i for i in items if i["provenance"].get("key") == key)


# ------------------------------------------------------------------ registry
def test_registry_ids_provenance_and_immutability():
    cid = _case("lottery_burst")
    with connect() as con:
        items = repo.evidence_items(con, cid)
        assert len({i["evidence_id"] for i in items}) == len(items)
        assert all(i["evidence_id"].startswith("EV-") for i in items)
        txns = [i for i in items if i["type"] == "transaction"]
        assert txns and all(len(i["source_ids"]) == 1 for i in txns)
        for t in txns[:5]:
            row = con.execute("SELECT amount FROM transactions WHERE transaction_id = ?", (t["source_ids"][0],)).fetchone()
            assert round(row[0], 2) == t["computed"]["amount"]
        assert any(i["type"] == "limitation" and i["computed"]["absence_is_not_proof"] for i in items)
        with pytest.raises(Exception):
            con.execute("UPDATE transactions SET amount = 0 WHERE transaction_id = ?", (txns[0]["source_ids"][0],))
        with pytest.raises(Exception):
            con.execute("UPDATE evidence SET title = 'x' WHERE evidence_id = ?", (items[0]["evidence_id"],))
        snap = con.execute("SELECT evidence_hash, item_count FROM evidence_snapshots WHERE case_id = ?", (cid,)).fetchone()
        assert len(snap[0]) == 64 and snap[1] == len([i for i in items if i["snapshot_id"]])


def test_metric_aggregate_is_recomputable_from_source_records():
    cid = _case("lottery_burst")
    m = _key(cid, "metric:window")
    with connect() as con:
        ids = m["source_ids"]
        n, total = con.execute(f"SELECT COUNT(*), ROUND(SUM(amount), 2) FROM transactions WHERE transaction_id IN "
                               f"({','.join('?' * len(ids))})", ids).fetchone()
    assert n == m["computed"]["transaction_count"] and abs(total - m["computed"]["total_amount"]) < 0.01


def test_anonymous_purchases_are_never_attributed():
    with connect() as con:
        bad = con.execute("SELECT COUNT(*) FROM transactions WHERE attribution = 'none' AND player_id IS NOT NULL").fetchone()[0]
        assert bad == 0
        cid = _case("incomplete_attribution")
        c = repo.case_row(con, cid)
        assert c["evidence_completeness"] in ("Partial", "Limited")


# ------------------------------------------------------------- claim checks
def test_deterministic_reports_fully_verify_for_every_case():
    with connect() as con:
        ids = [r[0] for r in con.execute("SELECT case_id FROM cases")]
    from services.report_writer import write
    for cid in ids[:40]:
        cm, con, items, idx, voc, look = _ctx(cid)
        try:
            case = repo.case_row(con, cid)
            for cl in write(case, items):
                st, f = validate_claim(cl, cid, idx, voc, look)
                assert st == "verified", (cid, cl["text"], f)
        finally:
            cm.__exit__(None, None, None)


def test_invented_transaction_id_and_location_are_rejected():
    cid = _case("lottery_burst")
    t = next(i for i in _ctx(cid)[2] if i["type"] == "transaction")
    st, f = _check(cid, "The player spent $2,050.00 at RTL-9999 in Vancouver on TXN-0000001.", [t["evidence_id"]])
    assert st == "unverified"
    joined = " ".join(f)
    assert "RTL-9999" in joined and "TXN-0000001" in joined and "Vancouver" in joined and "$2,050.00" in joined


def test_incorrect_total_is_rejected_and_correct_total_accepted():
    cid = _case("lottery_burst")
    m = _key(cid, "metric:window")
    x = m["computed"]
    good = f"{x['transaction_count']} purchases totalling ${x['total_amount']:,.2f}."
    assert _check(cid, good, [m["evidence_id"]])[0] == "verified"
    bad = f"{x['transaction_count']} purchases totalling ${x['total_amount'] + 25:,.2f}."
    assert _check(cid, bad, [m["evidence_id"]])[0] == "unverified"
    # near-miss numbers that fooled the old checker
    assert _check(cid, f"They made {x['transaction_count'] + 31} transactions.", [m["evidence_id"]])[0] == "unverified"


def test_invalid_citations_rejected():
    a, b = _case("lottery_burst"), _case("deposit_anomaly")
    other = _key(b, "metric:window")["evidence_id"]
    st, f = _check(a, "Something happened.", ["EV-999999"])
    assert st == "unverified" and "does not exist" in f[0]
    st, f = _check(a, "Something happened.", [other])
    assert st == "unverified" and "belongs to" in f[0]
    assert _check(a, "The player bought tickets.", [])[0] == "unverified"


def test_aggregate_claim_needs_aggregate_evidence():
    cid = _case("lottery_burst")
    t = next(i for i in _ctx(cid)[2] if i["type"] == "transaction")
    st, _ = _check(cid, f"In total the two purchases came to ${t['computed']['amount'] * 2:,.2f}.", [t["evidence_id"]])
    assert st == "unverified"


def test_policy_accusation_and_absence_as_proof():
    cid = _case("lottery_burst")
    m, lim = _key(cid, "metric:window"), _key(cid, "lim:identity")
    assert _check(cid, "The player committed fraud.", [m["evidence_id"]])[0] == "unverified"
    assert _check(cid, "There were no other buyers, so it did not occur by chance.", [lim["evidence_id"]])[0] == "unverified"


def test_missing_historical_data_is_handled():
    from detection.risk_scoring import score_customer
    import pandas as pd
    f = {k: 0 for k in ["frequency_ratio", "peak_hour_ratio", "avg_amount_ratio", "max_vs_hist_p95", "new_location_count",
                        "new_retailer_count", "night_transaction_ratio", "hist_night_ratio", "night_transaction_count",
                        "spend_ratio", "rapid_pairs", "repeated_amount_count", "transaction_count", "transactions_per_day",
                        "hist_transactions_per_day", "peak_hour_transactions", "hist_peak_hour_avg",
                        "average_transaction_amount", "hist_average_amount", "max_transaction_amount", "hist_p95_amount",
                        "unique_locations", "unique_retailers", "total_amount", "hist_weekly_total", "historical_deviation"]}
    f.update({"frequency_ratio": 50, "spend_ratio": 40, "new_location_count": 4, "hist_transaction_count": 0,
              "peak_hour_start": None, "peak_hour_end": None, "new_locations": ["Ottawa"], "new_retailers": [],
              "home_locations": [], "repeated_amount_value": None})
    empty = pd.DataFrame({"timestamp": pd.Series(dtype="datetime64[ns]"), "transaction_id": pd.Series(dtype=str),
                          "amount": pd.Series(dtype=float), "location": pd.Series(dtype=str),
                          "retailer_id": pd.Series(dtype=str)})
    res = score_customer(f, empty)
    assert res["baseline_sufficient"] is False
    for k in ("frequency", "value", "location", "historical"):
        assert res["factors"][k]["points"] == 0


def test_wrong_date_and_qualifier_rejected():
    cid = _case("lottery_burst")
    t = next(i for i in _ctx(cid)[2] if i["type"] == "transaction" and i["computed"]["hour"] >= 8)
    assert _check(cid, "This purchase happened overnight.", [t["evidence_id"]])[0] == "unverified"
    assert _check(cid, "This purchase was on October 2.", [t["evidence_id"]])[0] == "unverified"


# ------------------------------------------------------------- reports
def test_report_versioning_and_llm_fallback_label():
    cid = _case("prize_claims")
    r1 = reports.generate(cid, "deterministic")
    r2 = reports.generate(cid, "llm")              # no key in tests
    assert r2["version"] == r1["version"] + 1
    assert r2["mode"] == "llm_fallback" and "deterministic" in r2["notes"]
    assert r1["validation"]["unverified"] == 0
    keys = [s["key"] for s in r1["sections"]]
    assert keys[0] == "case_overview" and keys[-1] == "review_status" and len(keys) == 11
    with connect() as con:
        assert repo.case_row(con, cid)["status"] == config.STATUS_READY
        with pytest.raises(Exception):
            con.execute("UPDATE claims SET text = 'x' WHERE report_id = ?", (r1["report_id"],))


def test_llm_output_with_invented_facts_is_marked_unverified(monkeypatch):
    import json
    from ai import llm_client
    cid = _case("lottery_burst")
    m = _key(cid, "metric:window")

    def fake_chat(msgs, json_mode=False, temperature=0.1, timeout=90):
        return json.dumps({"claims": [
            {"section": "observed_activity", "kind": "fact", "text": "The records show 999 purchases totalling $1.00.",
             "evidence_ids": [m["evidence_id"]]},
            {"section": "observed_activity", "kind": "fact",
             "text": f"The records show {m['computed']['transaction_count']} purchases.", "evidence_ids": [m["evidence_id"]]}]})
    monkeypatch.setattr(llm_client, "llm_available", lambda: True)
    monkeypatch.setattr(llm_client, "chat", fake_chat)
    monkeypatch.setattr(llm_client, "model_name", lambda: "fake-model")
    r = reports.generate(cid, "llm")
    assert r["mode"] == "llm" and r["validation"]["unverified"] == 1 and "failed verification" in r["notes"]
    bad = [c for s in r["sections"] for c in s["claims"] if c["verification_status"] == "unverified"]
    assert bad and "999" in bad[0]["text"]


# ------------------------------------------------------------- copilot
@pytest.mark.parametrize("q", copilot.SUGGESTED + ["What happened on October 11?", "Is the player guilty?",
                                                   "What's the weather?"])
def test_copilot_answers_are_cited_and_verified(q):
    cid = _case("lottery_burst")
    r = copilot.ask(cid, q, "deterministic", "REV-01")
    assert r["claims"]
    for c in r["claims"]:
        assert c["verification_status"] == "verified", (q, c)
        if c["kind"] != "status":
            assert c["evidence_ids"]
    if "guilty" in q:
        assert "can't determine" in r["claims"][0]["text"]


@pytest.mark.parametrize("q", ["Which retailers were involved?", "Where did the purchases happen?",
                               "List the stores used", "Which locations were visited?"])
def test_copilot_routes_retailer_phrasings(q):
    r = copilot.ask(_case("multi_retailer"), q, "deterministic", "REV-01")
    assert r["claims"][0]["kind"] != "status", (q, r["claims"][0]["text"])
    assert all(c["verification_status"] == "verified" for c in r["claims"])


def test_query_tool_accuracy_against_database():
    cid = _case("lottery_burst")
    with connect() as con:
        t = CaseTools(con, cid)
        res = t.call("aggregate_transactions", {"group_by": "retailer"})
        groups = res["computed"]["groups"]
        top = groups[0]
        c = repo.case_row(con, cid)
        n = con.execute("""SELECT COUNT(*) FROM transactions WHERE player_id = ? AND retailer_id = ?
                           AND timestamp_utc >= ? AND timestamp_utc <= ?""",
                        (c["subject_id"], top["key"], c["window_start_utc"], c["window_end_utc"])).fetchone()[0]
        assert n == top["transaction_count"]
        assert sum(g["transaction_count"] for g in groups) == res["computed"]["transaction_count"]
        bad = t.call("list_transactions", {"retailer_id": "DROP TABLE"})
        assert "error" in bad
        assert t.call("run_sql", {"q": "select 1"})["error"]


def test_copilot_is_case_scoped():
    a, b = _case("lottery_burst"), _case("deposit_anomaly")
    with connect() as con:
        ta = CaseTools(con, a)
        b_subject = repo.case_row(con, b)["subject_id"]
        rows = ta.call("list_transactions", {"limit": 100})["rows"]
        assert all(r.get("account_id") != b_subject for r in rows)


def test_followup_uses_conversation_context():
    cid = _case("lottery_burst")
    copilot.ask(cid, "What happened on October 11?", "deterministic", "REV-01")
    r = copilot.ask(cid, "What about the next day?", "deterministic", "REV-01")
    assert "2026-10-12" in r["claims"][0]["text"] or "October 12" in r["claims"][0]["text"]


# ------------------------------------------------------------- workflow
def _session():
    s = workflow.create_session("REV-02")
    return workflow.session_reviewer(s["token"])


def test_status_transitions_and_audit_persistence():
    cid = _case("multi_retailer")
    rv = _session()
    with pytest.raises(workflow.WorkflowError):        # decisions need a report
        workflow.perform(cid, "start_review", rv, notes="", idempotency_key=uuid.uuid4().hex)
        workflow.perform(cid, "escalate", rv, notes="Needs escalation now.", idempotency_key=uuid.uuid4().hex)
    rep = reports.generate(cid)
    with pytest.raises(workflow.WorkflowError) as e:   # wrong transition
        workflow.perform(cid, "reopen", rv, notes="reopen this case", idempotency_key=uuid.uuid4().hex)
    assert e.value.status_code == 409
    with pytest.raises(workflow.WorkflowError) as e:   # notes validated server-side
        workflow.perform(cid, "request_info", rv, notes="short", idempotency_key=uuid.uuid4().hex)
    assert e.value.status_code == 422
    with pytest.raises(workflow.WorkflowError) as e:   # stale UI
        workflow.perform(cid, "request_info", rv, notes="Need retailer logs please", idempotency_key=uuid.uuid4().hex,
                         expected_status="New")
    a = workflow.perform(cid, "request_info", rv, notes="Need retailer logs for the burst.",
                         idempotency_key="idem-1", report_id=rep["report_id"])
    assert a["to_status"] == config.STATUS_INFO and a["report_version"] == rep["version"] and len(a["evidence_hash"]) == 64
    again = workflow.perform(cid, "request_info", rv, notes="Need retailer logs for the burst.", idempotency_key="idem-1")
    assert again["duplicate"] is True
    with connect() as con:
        assert con.execute("SELECT COUNT(*) FROM case_actions WHERE idempotency_key='idem-1'").fetchone()[0] == 1
        assert con.execute("SELECT status FROM reports WHERE report_id=?", (rep["report_id"],)).fetchone()[0] == "locked"
        with pytest.raises(Exception):
            con.execute("DELETE FROM case_actions WHERE idempotency_key='idem-1'")
    workflow.perform(cid, "close_no_action", rv, notes="Retailer confirmed routine errands.", idempotency_key=uuid.uuid4().hex)
    assert cases.detail(cid)["status"] == config.STATUS_CLOSED
    assert cases.analytics()["closed"] >= 1


# ------------------------------------------------------------- graph / export / lab
def test_graph_edges_reference_real_nodes_and_never_link_players():
    for key in ("shared_retailer", "deposit_anomaly", "incomplete_attribution"):
        g = graph.build(_case(key))
        ids = {n["id"] for n in g["nodes"]}
        assert all(e["source"] in ids and e["target"] in ids for e in g["edges"])
        types = {n["id"]: n["type"] for n in g["nodes"]}
        for e in g["edges"]:
            assert not (types[e["source"]] == "player" and types[e["target"]] == "player")
            assert e["meaning"]
        if key == "shared_retailer":
            assert any(e["relation"] == "co_located" for e in g["edges"])


def test_pdf_export_matches_saved_version():
    cid = _case("prize_claims")
    with connect() as con:
        rep = reports.latest(con, cid)
    pdf, meta = pdf_export.render(rep["report_id"], "REV-01")
    assert pdf[:4] == b"%PDF" and meta["file_name"].endswith(f"v{rep['version']}.pdf")
    with connect() as con:
        assert con.execute("SELECT report_id FROM report_exports WHERE export_id=?", (meta["export_id"],)).fetchone()[0] == rep["report_id"]


def test_scenario_lab_creates_real_case_without_touching_existing_records():
    with connect() as con:
        before = con.execute("SELECT COUNT(*), MAX(transaction_id) FROM transactions").fetchone()
    out = scenarios.run("deposit_anomaly")
    with connect() as con:
        after = con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        c = repo.case_row(con, out["case_id"])
    assert after > before[0] and c["origin"] == "scenario_lab" and c["channel"] == "online_account"
    r = reports.generate(out["case_id"])
    assert r["validation"]["unverified"] == 0


def test_restart_does_not_regenerate():
    import pipeline
    before = pipeline.status()
    pipeline.ensure_built()
    assert pipeline.status() == before
