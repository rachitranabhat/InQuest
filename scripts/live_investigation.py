"""Run ONE live multi-agent investigation (real OpenAI calls) on an existing case and show who used the model.

    .venv\\Scripts\\activate
    python scripts\\live_investigation.py CASE-18007

Reads OPENAI_API_KEY / OPENAI_MODEL from V2's .env (never printed). Uses V2's own database (SQLite by default,
or PostgreSQL if PRISM_DB_BACKEND=postgres). Read-only for the case: no status, action or decision changes.
The full JSON result is saved to backend/data/exports/<investigation_id>.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import config  # noqa: E402
from ai import llm_client  # noqa: E402


def main() -> int:
    case_id = sys.argv[1] if len(sys.argv) > 1 else "CASE-18007"
    if not llm_client.llm_available():
        print("OPENAI_API_KEY is not set in V2's .env (" + str(config.REPO_ROOT / ".env") + ").")
        return 1
    print(f"Key loaded: yes ({len(config.OPENAI_API_KEY)} characters, not shown) · model: {llm_client.model_name()}"
          f" · endpoint: {config.OPENAI_BASE_URL or 'https://api.openai.com/v1'}")
    try:                                   # one tiny call so a bad key / network problem is reported clearly
        llm_client.chat([{"role": "user", "content": "Reply with the word ok."}], timeout=30)
        print("OpenAI connectivity: ok")
    except llm_client.LLMUnavailable as e:
        print(f"OpenAI connectivity FAILED: {str(e)[:300]}")
        return 2

    import pipeline
    from database.db import connect
    from services import agents, repo
    pipeline.ensure_built()
    with connect() as con:
        reviewer = repo.reviewer(con, "REV-01")
    print(f"Running live investigation on {case_id} (this makes several model calls, ~30-90 s) ...")
    r = agents.run(case_id, "llm", reviewer)

    print(f"\nInvestigation {r['investigation_id']} · overall mode: {r['mode']} · model: {r['model']}")
    print(r["mode_label"])
    for role, a in r["agents"].items():
        live = {"live": "LIVE MODEL", "live_repaired": "LIVE MODEL (after one schema repair)",
                "fallback": "FELL BACK to deterministic"}.get(a.get("stage_status"), a["mode"])
        print(f"\n[{a['name']}] {live} · {a.get('conclusion', a['hypothesis_status'])} · verified {a['verified']} / rejected {a['rejected']}")
        for w in a.get("warnings", []):
            print(f"   WARNING: {w}")
        for c in a["tool_calls"]:
            print(f"   tool {c['tool']}({json.dumps(c['args'])}) -> {len(c['evidence_ids'])} evidence items"
                  + (f"  ERROR: {c['error']}" if c.get("error") else ""))
        print(f"   summary: {a['summary']}")
        if a.get("fallback_reason"):
            print(f"   fallback reason: {a['fallback_reason']}")
    lead = r["lead"]
    print(f"\n[Lead investigator] " + {"live": "LIVE MODEL", "live_repaired": "LIVE MODEL (after one schema repair)",
                                      "fallback": "FELL BACK to deterministic"}.get(lead.get("stage_status"), lead["mode"]))
    for w in lead.get("warnings", []):
        print(f"   WARNING: {w}")
    print(f"   assessment: {lead['assessment']}\n   rationale: {lead['rationale']}")
    for k in ("strongest_supporting", "strongest_counterevidence", "missing_information"):
        print(f"   {k}:")
        for f in lead[k]:
            print(f"     {f['finding_id']} {f['text']} {f['evidence_ids']}")
    print(f"   next step: {lead['recommended_next_step']}")
    for f in r["rejected_findings"]:
        print(f"   REJECTED by validator ({f['agent']}): {f['text'][:120]} -> {'; '.join(f['failures'])[:160]}")
    for n in r["notes"]:
        print(f"   NOTE: {n}")
    out = config.EXPORT_DIR / f"{r['investigation_id']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(r, indent=2), encoding="utf-8")
    print(f"\nFull result saved to {out}")
    return 0 if r["mode"] == "llm" else 3


if __name__ == "__main__":
    sys.exit(main())
