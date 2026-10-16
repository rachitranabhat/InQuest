"""Deterministic regression replay: run the current consistency checks over a STORED investigation's original findings.

    python scripts\\validate_investigation.py INV-2f790604b4            # reads V2's database (read-only)
    python scripts\\validate_investigation.py --json replay.json        # {"result": <investigation>, "items": [evidence]}

No model calls, no writes. The stored investigation is never modified; this only reports what the checks would do.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services import agents  # noqa: E402


def load(argv):
    if argv[0] == "--json":
        d = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        return d["result"], d["items"]
    from database.db import connect
    from services import investigation_store, repo
    r = investigation_store.get(argv[0])
    if not r or r.get("status") != "completed":
        sys.exit(f"{argv[0]}: not a completed investigation")
    with connect() as con:
        return r, repo.evidence_items(con, r["case_id"])


def main(argv) -> int:
    r, items = load(argv)
    keys = ("finding_id", "agent", "kind", "weight", "text", "evidence_ids", "verification_status")
    original = [{k: f[k] for k in keys} for f in r["verified_findings"]]
    kept, rej, _ = agents.cross_check([dict(f) for f in original], items)
    by = {f["finding_id"]: f for f in kept}
    L = r["lead"]
    lead = agents.LeadOutput(assessment=L["assessment"], rationale=L["rationale"],
                             strongest_supporting=[f["finding_id"] for f in L["strongest_supporting"]],
                             strongest_counterevidence=[f["finding_id"] for f in L["strongest_counterevidence"]],
                             missing_information=[f["finding_id"] for f in L["missing_information"]],
                             recommended_next_step=L["recommended_next_step"])
    lead, drops = agents._clean_lead(lead, kept)
    flags = agents.lead_justification(lead, kept)
    summ = list(r["agents"].values())
    print(f"# Replay of {r['investigation_id']} ({r['case_id']}) · original mode {r['mode']} · model {r.get('model')}")
    print(f"Original Lead assessment (unchanged): {r['lead']['assessment']}\n")
    print("| Finding | Agent | Kind | Original weight | Result | Reason |\n|---|---|---|---|---|---|")
    rj = {x["finding_id"]: x for x in rej}
    for f in original:
        fid = f["finding_id"]
        if fid in rj:
            res, why = "REJECTED", rj[fid]["failures"][0]
        elif by[fid].get("cross_checks"):
            res = "ANNOTATED" + (" + DOWNGRADED" if by[fid]["weight"] != f["weight"] else "")
            why = " ".join(by[fid]["cross_checks"])
        else:
            res, why = "accepted", ""
        print(f"| {fid} | {f['agent']} | {f['kind']} | {f['weight']} | {res} | {why} |")
    print("\nSummary warnings:")
    for a in summ:
        if agents._DENIAL.search(a["summary"]):
            print(f"- {a['name']}: summary denies anomalies that fired indicators record.")
    print("\nLead references dropped (cite rejected findings):", *drops, sep="\n- ")
    print("\nAssessment-level flags:", *(flags or ["none"]), sep="\n- ")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["INV-2f790604b4"]))
