"""Plain-language findings: accuracy, zero baselines, no undefined values, auditability."""
import copy
import json
import re

import pytest

from database.db import connect
from services import findings, repo
from services.findings import compare_values

pytestmark = pytest.mark.usefixtures("built_db")


def _all_cases():
    with connect() as con:
        return [r[0] for r in con.execute("SELECT case_id FROM cases ORDER BY case_id")]


def _case(curated):
    with connect() as con:
        return con.execute("SELECT case_id FROM cases WHERE curated_key = ? AND origin = 'monitoring'",
                           (curated,)).fetchone()[0]


@pytest.fixture(scope="module")
def every_case():
    return {cid: findings.for_case(cid) for cid in _all_cases()}


# ---------------------------------------------------------------- accuracy
def test_every_plain_sentence_passes_the_claim_validator(every_case):
    n = 0
    for cid, r in every_case.items():
        for f in r["findings"]:
            n += 1
            assert f["verification"]["status"] == "verified", (cid, f["key"], f["verification"]["failures"])
    assert n >= 6 * len(every_case)


def test_comparison_values_are_the_stored_evidence_values(every_case):
    for cid, r in every_case.items():
        with connect() as con:
            items = {i["evidence_id"]: i for i in repo.evidence_items(con, cid, include_queries=False)}
        for f in r["findings"]:
            fac = items[f["evidence_id"]]["computed"]
            assert f["points"] == fac["points"] and f["max_points"] == fac["max_points"]
            stored = {m["field"]: m["value"] for m in f["technical"]["metrics"] if not m["field"].startswith("cmp:")}
            for field, v in stored.items():
                assert fac[field] == v, (cid, f["key"], field)
            if f["key"] == "timing":
                prev, rec = f["comparison"]["rows"]
                assert prev["value"] == fac["baseline_night_share_pct"] and rec["value"] == fac["night_share_pct"]
            if f["key"] == "historical":
                prev, rec = f["comparison"]["rows"]
                assert prev["value"] == fac["typical_week_total"] and rec["value"] == fac["window_total"]


def test_rule_ramp_reproduces_the_stored_score(every_case):
    """The 'normalized value' shown in the technical details must agree with the detection score."""
    for cid, r in every_case.items():
        for f in r["findings"]:
            if not f["scored"]:
                assert f["points"] == 0
                continue
            subs = [s["normalized"] for s in f["technical"]["sub_measures"]]
            re_share = subs[0] * subs[1] if f["key"] == "playthrough" else max(subs)
            assert abs(re_share - f["technical"]["normalized_share"]) <= 0.02, (cid, f["key"], re_share)


def test_ratios_use_stored_detection_ratios(every_case):
    from services.claims import fmt_half_up
    field = {"historical": "spend_ratio"}
    for r in every_case.values():
        for f in r["findings"]:
            d = (f.get("comparison") or {}).get("delta") or {}
            if f["key"] in field and d.get("ratio") is not None:
                stored = next(m["value"] for m in f["technical"]["metrics"] if m["field"] == field[f["key"]])
                assert d["ratio"] == float(fmt_half_up(stored, 1))


# ------------------------------------------------------------ zero baselines
def test_zero_previous_share_is_shown_in_percentage_points():
    d = compare_values(0.0, 74.2, kind="pct", previous_n=12)
    assert d["text"] == "Increase: 74.2 percentage points"
    assert d["state"] == "zero_observed" and "ratio" not in d


def test_no_previous_records_is_not_the_same_as_observed_zero():
    none = compare_values(0.0, 74.2, kind="pct", previous_n=0)
    assert none["state"] == "no_previous"
    assert none["text"] == "Insufficient previous activity to establish a typical pattern."
    zero = compare_values(0, 5, kind="count", previous_n=8)
    assert zero["state"] == "zero_observed" and zero["text"].startswith("None previously")


def test_clipped_denominator_never_produces_an_inflated_ratio():
    # previous 0.04/day: the detection ratio divides by 0.1, so a stored ratio must not be shown
    d = compare_values(0.04, 3.0, kind="count", previous_n=1, stored_ratio=30.0, floor=0.1)
    assert "×" not in d["text"] and d["text"] == "Up from 0.04 to 3"


def test_decrease_and_no_change():
    assert compare_values(10.7, 0.0, kind="pct", previous_n=28)["text"] == "Decrease: 10.7 percentage points"
    assert compare_values(5.0, 5.0, kind="count", previous_n=9)["text"] == "No change"


def test_insufficient_previous_activity_is_explained_not_scored():
    cid = _case("lottery_burst")
    with connect() as con:
        case = repo.case_row(con, cid)
        items = copy.deepcopy(repo.evidence_items(con, cid, include_queries=False))
        vocab = repo.vocab(con)
    for it in items:
        if it["provenance"].get("key") == "baseline":
            it["computed"].update({"baseline_transaction_count": 0, "sufficient": False})
    r = findings.build(case, items, vocab)
    freq = next(f for f in r["findings"] if f["key"] == "frequency")
    assert not freq["scored"]
    assert freq["headline"] == "Not scored: too little previous activity"
    assert freq["comparison"]["delta"]["state"] == "no_previous"
    timing = next(f for f in r["findings"] if f["key"] == "timing")
    assert timing["comparison"]["delta"]["text"] == "Insufficient previous activity to establish a typical pattern."


def test_no_undefined_or_infinite_values_in_any_text(every_case):
    bad = re.compile(r"\b(inf|Infinity|NaN|nan|None|null|undefined)\b|∞|—|n/a")
    for r in every_case.values():
        for f in r["findings"]:
            texts = [f["headline"], f["change"], f["contribution"], f["attention"],
                     *f["explain"].values(), *(l["text"] for l in f["limitations"])]
            cmp_ = f.get("comparison") or {}
            texts += [row["display"] for row in cmp_.get("rows", [])]
            if cmp_.get("delta"):
                texts.append(cmp_["delta"]["text"])
            for t in texts:
                assert not bad.search(str(t)), (f["key"], t)


# ------------------------------------------------------------ reliability
def test_lottery_findings_never_attribute_anonymous_purchases(every_case):
    for r in every_case.values():
        if r["scope"] != "linked purchases":
            continue
        for f in r["findings"]:
            if f["key"] in ("frequency", "value", "historical", "timing", "location"):
                assert any("rewards card" in l["text"] for l in f["limitations"]), f["key"]


def test_every_finding_cites_its_indicator_and_supporting_records_exist(every_case):
    for cid, r in every_case.items():
        with connect() as con:
            ev = {i["evidence_id"]: i for i in repo.evidence_items(con, cid, include_queries=False)}
        txns = {i["source_ids"][0] for i in ev.values() if i["type"] == "transaction"}
        for f in r["findings"]:
            assert f["evidence_ids"][0] == f["evidence_id"]
            assert all(e in ev for e in f["evidence_ids"])
            assert all(l["evidence_id"] in ev for l in f["limitations"])
            assert set(f["supporting_transaction_ids"]) <= txns


def test_technical_details_keep_original_terms_and_snapshot(every_case):
    r = every_case[_case("lottery_burst")]
    assert r["snapshot_id"].startswith("SNP-")
    assert r["periods"]["previous_days"] == 23 and r["periods"]["recent_days"] == 7
    f = r["findings"][0]
    assert f["technical"]["technical_label"].endswith(("anomaly", "deviation", "play-through"))
    assert f["technical"]["rule"]
    json.dumps(r)  # serialisable for the API
