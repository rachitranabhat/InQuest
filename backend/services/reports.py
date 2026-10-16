"""Report versions: generation (deterministic or LLM), validation, persistence, locking."""
from __future__ import annotations

import json

import config
from ai import llm_client
from ai.prompts import PROMPT_VERSION as LLM_PROMPT_VERSION
from ai.prompts import REPAIR_TASK, REPORT_TASK, SYSTEM
from database.db import connect, dumps, loads, next_id, next_ids, tx
from services import repo
from services.claims import PLAIN_SECTION_LABELS, SECTIONS, ClaimIn, build_index, validate_claim
from services.report_writer import PROMPT_VERSION as DET_PROMPT_VERSION
from services.report_writer import write
from timeutil import utc_now_iso

MODE_LABELS = {
    "deterministic": "Deterministic (demo mode, no LLM)",
    "llm": "LLM-written, validated",
    "llm_fallback": "Deterministic fallback after LLM failure",
}


def case_actions(con, case_id) -> list[dict]:
    rows = con.execute("""SELECT a.*, r.display_name AS reviewer_name FROM case_actions a
                          JOIN reviewers r ON r.reviewer_id = a.reviewer_id
                          WHERE case_id = ? ORDER BY created_at_utc, action_id""", (case_id,)).fetchall()
    return [dict(r) for r in rows]


def _validate_all(claims, case_id, items, vocab, lookup):
    idx = build_index(items)
    out = []
    for c in claims:
        st, f = validate_claim(c, case_id, idx, vocab, lookup)
        out.append({**c, "verification_status": st, "failures": f})
    return out


def _llm_claims(case, items, det_claims, vocab, lookup):
    """Ask the LLM for claims, validate, repair once. Raises LLMUnavailable/ValueError on hard failure."""
    cards = [{"section": c["section"], "kind": c["kind"], "text": c["text"], "evidence_ids": c["evidence_ids"]}
             for c in det_claims if c["section"] != "review_status"]
    evidence = [{"id": it["evidence_id"], "type": it["type"], "title": it["title"], "computed": it["computed"]}
                for it in items]
    sections = "\n".join(f"- {k}: {label}" for k, label in SECTIONS if k != "review_status")
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": REPORT_TASK.format(sections=sections, cards=json.dumps(cards, indent=0),
                                                           evidence=json.dumps(evidence, separators=(",", ":")))}]
    attempts = []
    for attempt in range(config.LLM_MAX_RETRIES + 1):
        raw = llm_client.chat(msgs, json_mode=True, temperature=0.2)
        try:
            parsed = json.loads(raw)
            claims = [ClaimIn(**c).model_dump() for c in parsed.get("claims", []) if c.get("section") != "review_status"]
        except (ValueError, TypeError) as e:
            raise ValueError(f"LLM output was not valid claim JSON ({e.__class__.__name__})") from e
        if not claims:
            raise ValueError("LLM returned no claims")
        checked = _validate_all(claims, case["case_id"], items, vocab, lookup)
        bad = [c for c in checked if c["verification_status"] != "verified"]
        attempts.append(len(bad))
        if not bad or attempt == config.LLM_MAX_RETRIES:
            return checked, attempts
        msgs += [{"role": "assistant", "content": raw},
                 {"role": "user", "content": REPAIR_TASK.format(failures="\n".join(
                     f"- [{c['section']}] \"{c['text']}\" cites {c['evidence_ids']}: {'; '.join(c['failures'])}"
                     for c in bad))}]
    return checked, attempts


def generate(case_id: str, mode: str = "deterministic", reviewer_id: str = "SYSTEM") -> dict:
    if mode not in ("deterministic", "llm"):
        raise ValueError("mode must be 'deterministic' or 'llm'")
    with connect() as con:
        case = repo.case_row(con, case_id)
        snap = case["current_snapshot_id"]
        h = con.execute("SELECT evidence_hash FROM evidence_snapshots WHERE snapshot_id = ?", (snap,)).fetchone()[0]
        items = repo.evidence_items(con, case_id, snap, include_queries=False)
        vocab, lookup = repo.vocab(con), repo.evidence_owner(con)
        actions = case_actions(con, case_id)
        det = write(case, items, actions)
        notes, model, used_mode, prompt_version = None, None, "deterministic", DET_PROMPT_VERSION
        status_claims = [c for c in det if c["section"] == "review_status"]
        if mode == "llm":
            try:
                llm_checked, attempts = _llm_claims(case, items, det, vocab, lookup)
                checked = llm_checked + _validate_all(status_claims, case_id, items, vocab, lookup)
                used_mode, model, prompt_version = "llm", llm_client.model_name(), LLM_PROMPT_VERSION
                if attempts and attempts[-1]:
                    notes = (f"{attempts[-1]} LLM claim(s) still failed verification after "
                             f"{len(attempts) - 1} repair attempt(s); they are shown as unverified.")
            except (llm_client.LLMUnavailable, ValueError) as e:
                checked = _validate_all(det, case_id, items, vocab, lookup)
                used_mode, notes = "llm_fallback", f"LLM mode was requested but failed: {e}. " \
                                                   "This report was written by the deterministic generator."
        else:
            checked = _validate_all(det, case_id, items, vocab, lookup)
        order = {k: i for i, (k, _) in enumerate(SECTIONS)}
        checked.sort(key=lambda c: order.get(c["section"], 99))
        summary = {"claims": len(checked),
                   "verified": sum(c["verification_status"] == "verified" for c in checked),
                   "unverified": sum(c["verification_status"] != "verified" for c in checked)}
        now = utc_now_iso()
        with tx(con):
            version = (con.execute("SELECT MAX(version) FROM reports WHERE case_id = ?", (case_id,)).fetchone()[0] or 0) + 1
            rid = next_id(con, "RPT")
            con.execute("INSERT INTO reports VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (rid, case_id, version, used_mode, model, prompt_version, snap, h, "draft", dumps(summary),
                         notes, now, None))
            cids = next_ids(con, "CL", len(checked))
            con.executemany("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?)", [
                (cid, rid, c["section"], i, c["kind"], c["text"], dumps(c["evidence_ids"]), c["verification_status"],
                 dumps(c["failures"])) for i, (cid, c) in enumerate(zip(cids, checked))])
            cur = con.execute("SELECT status FROM cases WHERE case_id = ?", (case_id,)).fetchone()[0]
            if cur == config.STATUS_NEW:
                con.execute("UPDATE cases SET status = ?, updated_at_utc = ? WHERE case_id = ?",
                            (config.STATUS_READY, now, case_id))
            con.execute("INSERT INTO case_actions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (next_id(con, "ACT"), case_id, "report_generated", cur,
                         config.STATUS_READY if cur == config.STATUS_NEW else cur, reviewer_id or "SYSTEM",
                         "simulated" if reviewer_id != "SYSTEM" else "system",
                         f"Report version {version} generated ({MODE_LABELS[used_mode]}).", rid, version, snap, h,
                         f"report:{rid}", now))
        return get(con, rid)


def get(con, report_id: str) -> dict:
    r = con.execute("SELECT * FROM reports WHERE report_id = ?", (report_id,)).fetchone()
    if r is None:
        raise repo.NotFound(f"Report {report_id} not found")
    rep = dict(r)
    rep["validation"] = loads(rep["validation"], {})
    rep["mode_label"] = MODE_LABELS.get(rep["mode"], rep["mode"])
    claims = [{**dict(c), "evidence_ids": loads(c["evidence_ids"], []), "failures": loads(c["failures"], [])}
              for c in con.execute("SELECT * FROM claims WHERE report_id = ? ORDER BY position", (report_id,))]
    labels = dict(SECTIONS)
    sections = []
    for key, label in SECTIONS:
        cs = [c for c in claims if c["section"] == key]
        if cs:
            sections.append({"key": key, "label": PLAIN_SECTION_LABELS.get(key, labels[key]),
                             "technical_label": labels[key], "claims": cs})
    cited = sorted({e for c in claims for e in c["evidence_ids"]})
    ev = {}
    if cited:
        q = f"SELECT evidence_id, type, title FROM evidence WHERE evidence_id IN ({','.join('?' * len(cited))})"
        ev = {row[0]: {"type": row[1], "title": row[2]} for row in con.execute(q, cited)}
    rep.update({"sections": sections, "evidence_refs": ev, "disclaimer": config.DISCLAIMER})
    return rep


def list_for_case(con, case_id: str) -> list[dict]:
    rows = con.execute("""SELECT report_id, case_id, version, mode, model, status, validation, notes, created_at_utc,
                                 locked_at_utc, evidence_hash, snapshot_id FROM reports WHERE case_id = ?
                          ORDER BY version DESC""", (case_id,)).fetchall()
    return [{**dict(r), "validation": loads(r["validation"], {}), "mode_label": MODE_LABELS.get(r["mode"], r["mode"])}
            for r in rows]


def latest(con, case_id: str) -> dict | None:
    r = con.execute("SELECT report_id FROM reports WHERE case_id = ? ORDER BY version DESC LIMIT 1", (case_id,)).fetchone()
    return get(con, r[0]) if r else None


def lock(con, report_id: str):
    """Freeze a report version once a reviewer acts on it (call inside a transaction)."""
    con.execute("UPDATE reports SET status = 'locked', locked_at_utc = COALESCE(locked_at_utc, ?) WHERE report_id = ?",
                (utc_now_iso(), report_id))
