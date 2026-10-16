"""Case-scoped investigation copilot ("Ask AI").

Question → authorised case → controlled query tools → deterministic numbers →
(optional) LLM wording → claim verification → cited answer.

Demo mode: a deterministic planner maps the question to tool calls and writes
claims from the tool results. LLM mode: the model picks tools (bounded loop),
writes claims, and the claims are verified; if they fail after one repair, the
deterministic answer is shown and labelled as a fallback.
"""
from __future__ import annotations

import json
import re

import pandas as pd

import config
from ai import llm_client
from ai.prompts import CHAT_SYSTEM
from database.db import connect, dumps, loads, next_id, tx
from services import repo
from services.claims import (ACCUSATORY, NAMED_DATE_RE, NAMED_DATE_RE2, ClaimIn, _month, build_index,
                             validate_claim)
from services.query_tools import CaseTools, openai_tools
from services.report_writer import money, num, plural, ratio
from timeutil import utc_now_iso

SUGGESTED = [
    "Why was this case flagged?",
    "Which transactions contributed to the alert?",
    "Which retailer had the most relevant transactions?",
    "How much was spent during this period?",
    "What evidence contradicts the initial suspicion?",
    "What is missing from the records?",
    "Are there related entities?",
    "Compare current activity with the historical baseline.",
    "Generate a short case summary.",
]
MAX_TOOL_ROUNDS = 4


# ============================================================== deterministic planner
class Planner:
    def __init__(self, tools: CaseTools, context: dict):
        self.t = tools
        self.ctx = dict(context or {})
        self.claims: list[dict] = []
        self.calls: list[dict] = []
        self.year = pd.Timestamp(tools.case["window_start_utc"]).year

    def add(self, text, cites, kind="fact"):
        self.claims.append({"section": "answer", "kind": kind, "text": text,
                            "evidence_ids": [c["evidence_id"] for c in cites if c]})

    def call(self, name, args=None):
        res = self.t.call(name, args or {})
        self.calls.append({"tool": name, "args": args or {}})
        return res

    def k(self, key):
        return self.t.by_key.get(key)

    # -------------------------------------------------------------- parsing
    def _date(self, q: str):
        m = re.search(r"\b(20\d\d)-(\d\d)-(\d\d)\b", q)
        if m:
            return m.group(0)
        for rx, order in ((NAMED_DATE_RE, "md"), (NAMED_DATE_RE2, "dm")):
            m = rx.search(q)
            if m:
                mon, day = (m.group(1), m.group(2)) if order == "md" else (m.group(2), m.group(1))
                return f"{self.year}-{_month(mon):02d}-{int(day):02d}"
        if re.search(r"\b(next|following) day\b|\bday after\b", q, re.I) and self.ctx.get("date"):
            return (pd.Timestamp(self.ctx["date"]) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        if re.search(r"\b(previous|prior) day\b|\bday before\b", q, re.I) and self.ctx.get("date"):
            return (pd.Timestamp(self.ctx["date"]) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        if re.search(r"\bthat day\b|\bthen\b", q, re.I) and self.ctx.get("date"):
            return self.ctx["date"]
        return None

    def _retailer(self, q: str):
        m = re.search(r"\bRTL-\d{4}\b", q, re.I)
        if m:
            return m.group(0).upper()
        names = {it["computed"]["retailer_name"].lower(): it["computed"]["retailer_id"]
                 for it in self.t.of_type("aggregate_retailer")}
        for n, rid in sorted(names.items(), key=lambda kv: -len(kv[0])):
            if n in q.lower():
                return rid
        if re.search(r"\b(that|this|the same) (retailer|store|shop)\b|\bthere\?$|\bat that one\b", q, re.I) and self.ctx.get("retailer_id"):
            return self.ctx["retailer_id"]
        return None

    # --------------------------------------------------------------- answer
    def answer(self, q: str) -> list[dict]:
        ql = q.lower()
        is_acct = self.t.case["channel"] == "online_account"
        date, rid = self._date(q), self._retailer(q)
        if ACCUSATORY.search(q) or re.search(r"\b(is|are|was|did) (he|she|they|the (player|customer|account)) .*\b(fraud|guilty|cheat)", ql):
            self.add("I can't determine whether anyone committed fraud or broke a rule — that decision belongs to "
                     "the investigator. Here is what the records show.", [], kind="status")
            self._why()
        elif date:
            self._on_date(date, rid)
        elif re.search(r"\b(which|what|top|most|busiest|list)\b.*\b(retailers?|stores?|shops?|locations?|where)\b|\bretailers?\b.*\b(most|involved|used|visited)\b|\bwhere did\b", ql):
            if is_acct:
                self.add("This is an online account, so its transactions have no retailer or terminal; the dataset also "
                         "holds no device or geolocation records for online sessions.",
                         [self.k("rel:account"), self.k("lim:device")], kind="limitation")
            else:
                self._top_retailer()
        elif rid:
            self._at_retailer(rid)
        elif re.search(r"\b(how much|spent|spend|total|value|amount)\b", ql):
            self._spend()
        elif re.search(r"\b(contradict|against|innocent|legit|ordinary|other explanation|alternative|benign|normal reason|explain otherwise|counter)", ql):
            self._contradictions()
        elif re.search(r"\b(missing|unavailable|unknown|limitation|don't know|do not know|gaps?\b|can't see|cannot see|incomplete|lack)", ql):
            self._limitations()
        elif re.search(r"\b(related|relationship|entit|connected|connection|linked|other players?|associat|network)", ql):
            self._related()
        elif re.search(r"\b(compare|comparison|baseline|history|historical|usual|normally|typical)\b", ql):
            self._compare()
        elif re.search(r"\b(night|overnight|late|midnight|early morning)\b", ql):
            self._night()
        elif re.search(r"\b(contribut|which transactions|what transactions|show me the transactions|supporting)\b", ql):
            self._contributors()
        elif re.search(r"\b(deposit|withdraw|wager|payout|fund)", ql) and is_acct:
            self._fundflow()
        elif re.search(r"\b(summary|summari[sz]e|overview|brief|tl;?dr)\b", ql):
            self._summary()
        elif re.search(r"\b(why|flag|reason|trigger|cause|score)\b", ql):
            self._why()
        else:
            self.add("I can only answer from this case's records, and I couldn't map that question to them. Try asking "
                     "about a date, a retailer, totals, the baseline, related entities, limitations or why the case "
                     "was flagged.", [], kind="status")
        return self.claims

    # ------------------------------------------------------------- intents
    def _why(self):
        al = self.k("alert")
        a = al["computed"]
        self.add(f"The simulated monitoring feed raised a {a['alert_type'].lower()} alert with a prototype score of "
                 f"{num(a['alert_score'])} / 100 ({a['score_band']} band) — a rule-based measure, not a fraud probability.", [al])
        trig = sorted([f for f in self.t.of_type("risk_factor") if f["computed"]["triggered"]],
                      key=lambda f: -f["computed"]["points"])
        from services.report_writer import Writer
        w = Writer(self.t.case, self.t.items)
        for f in trig[:4]:
            self.add(w._factor_sentence(f), [f])
        if not trig:
            m = self.k("metric:window")
            self.add(f"No behavioural indicator reached its trigger level; the alert came from the volume rule, with "
                     f"{m['computed']['transaction_count']} attributed purchases in the review window.", [al, m])
        self.call("get_triggering_factors")

    def _on_date(self, date, rid=None):
        args = {"date": date, **({"retailer_id": rid} if rid else {})}
        res = self.call("list_transactions", {**args, "limit": 8})
        self.ctx["date"] = date
        if not res.get("matching_count"):
            when = pd.Timestamp(date).strftime("%B %d")
            who = "account" if self.t.case["channel"] == "online_account" else "player"
            self.add(f"No review-window transactions for this {who} are recorded on {when}" + (f" at {rid}" if rid else "")
                     + f". The window covers {self.k('alert')['computed']['window_start']} to "
                     f"{self.k('alert')['computed']['window_end']}.", [res["aggregate_evidence"], self.k("alert")])
            if who == "player":
                self.add("Anonymous purchases are not linked to anyone, so the records cannot show whether this player "
                         "made unscanned purchases that day.", [self.k("lim:identity")], kind="limitation")
            return
        agg = res["aggregate_evidence"]
        x = agg["computed"]
        self.add(f"On {date} the records show {plural(x['transaction_count'], 'transaction')} totalling "
                 f"{money(x['total_amount'])}, from {x['first_local'][11:]} to {x['last_local'][11:]}"
                 + (f" at {rid}." if rid else "."), [agg])
        rows = res["rows"][:5]
        idx = {it["evidence_id"]: it for it in self.t.items}
        for r in rows:
            it = idx[r["evidence_id"]]
            c = it["computed"]
            where = f" at {c['retailer_name']} ({c['city']})" if c.get("retailer_name") else ""
            self.add(f"{r['transaction_id']} at {c['time']}: {c['transaction_type']} of {money(c['amount'])}{where}.", [it])
        if res["matching_count"] > len(rows):
            self.add("More transactions from that day are listed in the evidence panel.", [agg], kind="status")

    def _top_retailer(self):
        res = self.call("aggregate_transactions", {"group_by": "retailer"})
        if "groups" not in res.get("computed", {}):
            self.add("No retailer-level records are available for this case.", [self.k("alert")], kind="limitation")
            return
        g = res["computed"]["groups"]
        top = g[0]
        self.ctx["retailer_id"] = top["key"]
        self.add(f"{top['retailer_name']} ({top['key']}, {top['city']}) had the most activity: "
                 f"{top['transaction_count']} of {res['computed']['transaction_count']} attributed purchases "
                 f"({num(top['share_pct'])}%), totalling {money(top['total_amount'])}.", [res])
        for other in g[1:3]:
            self.add(f"Next: {other['retailer_name']} ({other['key']}) with {plural(other['transaction_count'], 'purchase')} "
                     f"totalling {money(other['total_amount'])}.", [res])
        agg = self.k(f"agg_ret:{top['key']}")
        if agg and agg["computed"].get("new_for_subject"):
            self.add(f"This player did not use {top['retailer_name']} during the baseline period.", [agg])

    def _at_retailer(self, rid):
        self.ctx["retailer_id"] = rid
        res = self.call("list_transactions", {"retailer_id": rid, "limit": 5})
        if not res.get("matching_count"):
            self.add(f"No review-window transactions for this case are recorded at {rid}.", [self.k("metric:window")],
                     kind="limitation")
            return
        agg = res["aggregate_evidence"]
        x = agg["computed"]
        self.add(f"At {rid} the records show {plural(x['transaction_count'], 'transaction')} totalling "
                 f"{money(x['total_amount'])} between {x['first_local']} and {x['last_local']}.", [agg])

    def _spend(self):
        m = self.k("metric:window")
        x = m["computed"]
        label = "deposits" if self.t.case["channel"] == "online_account" else "attributed purchases"
        self.add(f"During the review window the records show {x['transaction_count']} {label} totalling "
                 f"{money(x['total_amount'])} (average {money(x['average_amount'])}, largest {money(x['max_amount'])}).", [m])
        cmp_ = self.k("cmp:week_total")
        if cmp_ and cmp_["computed"]["ratio"]:
            c = cmp_["computed"]
            self.add(f"A typical week in the baseline totalled {money(c['baseline'])}, so the window is "
                     f"{num(c['ratio'])}× the usual level.", [cmp_])
        if self.t.case["channel"] == "online_account":
            self._fundflow()

    def _fundflow(self):
        ff = self.k("metric:fundflow")
        if not ff:
            return
        x = ff["computed"]
        self.add(f"Deposits {money(x['deposit_total'])} ({x['deposit_count']}), wagers {money(x['wager_total'])}, payouts "
                 f"{money(x['payout_total'])}, withdrawals {money(x['withdrawal_total'])}; withdrawals equal "
                 f"{num(x['withdrawn_pct_of_deposits'])}% of deposits.", [ff])

    def _contradictions(self):
        res = self.call("get_context_and_contradictions")
        items = {i["evidence_id"]: i for i in self.t.items}
        found = False
        for b in res["items"]:
            it = items[b["evidence_id"]]
            x = it["computed"]
            if it["type"] == "context_event" and x.get("network_ratio"):
                self.add(f"{x['event_name']} ran from {x['start']} to {x['end']}; network-wide terminal sales were "
                         f"{num(x['network_ratio'])}× the baseline daily level, and "
                         f"{x['subject_transactions_during_event']} of this subject's transactions fall on those days.",
                         [it], kind="interpretation")
                found = True
            elif it["type"] == "co_presence":
                self.add(f"{x['other_player_id']} purchased at the same retailer within {x['window_minutes']} minutes, "
                         "but co-location is not evidence of a relationship.", [it], kind="interpretation")
                found = True
        unfired = [i for i in self.t.of_type("risk_factor") if not i["computed"]["triggered"]]
        if unfired:
            names = ", ".join(i["title"].split(" · ")[0] for i in unfired)
            self.add(f"Indicators that did not fire: {names}.", unfired, kind="interpretation")
            found = True
        known = [i for i in self.t.of_type("aggregate_retailer") if not i["computed"].get("new_for_subject")]
        if known:
            names = ", ".join(i["computed"]["retailer_name"] for i in known[:4])
            self.add(f"Retailers in the window that this player already used in the baseline: {names}.",
                     known[:4], kind="interpretation")
            found = True
        if self.t.case["alert_score"] < config.ALERT_THRESHOLD:
            self.add("Only the volume rule fired; compared with this player's own history the activity is close to normal.",
                     [self.k("alert"), self.k("cmp:per_day")], kind="interpretation")
            found = True
        if not found:
            self.add("The records contain no specific evidence pointing to an ordinary explanation, but they also "
                     "cannot show intent or who made each purchase.", [self.k("lim:identity")], kind="limitation")

    def _limitations(self):
        self.call("get_limitations")
        for lim in self.t.of_type("limitation"):
            self.add(lim["summary"], [lim], kind="limitation")

    def _related(self):
        self.call("get_related_entities")
        rel = self.k("rel:account") or self.k("rel:attribution")
        self.add(rel["summary"], [rel])
        rets = self.t.of_type("aggregate_retailer")[:3]
        for r in rets:
            x = r["computed"]
            self.add(f"{x['retailer_name']} ({x['retailer_id']}, {x['city']}): {plural(x['transaction_count'], 'purchase')}"
                     + (", not used in the baseline." if x.get("new_for_subject") else "."), [r])
        for cp in self.t.of_type("co_presence")[:3]:
            x = cp["computed"]
            self.add(f"{x['other_player_id']} made {plural(x['transaction_count'], 'purchase')} at the same retailer within "
                     f"{x['window_minutes']} minutes. This is co-location only, not a verified relationship.", [cp],
                     kind="interpretation")
        if not self.t.of_type("co_presence") and self.t.case["channel"] != "online_account":
            self.add("No other attributed player was repeatedly at the same retailers at the same times.",
                     [self.k("metric:window")], kind="interpretation")

    def _compare(self):
        self.call("get_baseline_comparison")
        base = self.k("baseline")
        b = base["computed"]
        self.add(f"The baseline covers {b['baseline_days']} days with {b['baseline_transaction_count']} transactions "
                 f"({num(b['transactions_per_day'])} per day, average {money(b['average_amount'])}).", [base])
        for c in self.t.of_type("comparison"):
            x = c["computed"]
            if x["ratio"] is None:
                continue
            self.add(f"{x['metric']}: {num(x['baseline'])} in the baseline vs. {num(x['current'])} in the window "
                     f"({ratio(x['ratio'])}).", [c])
        if not b["sufficient"]:
            self.add("The baseline is too short for reliable comparison.", [base, self.k("lim:baseline")], kind="limitation")

    def _night(self):
        res = self.call("list_transactions", {"hour_from": 0, "hour_to": 4, "limit": 6})
        tim = self.k("factor:timing")
        x = tim["computed"]
        self.add(f"{plural(x['night_transactions'], 'transaction')} took place between midnight and 5 am ({num(x['night_share_pct'])}% of "
                 f"the window vs. {num(x['baseline_night_share_pct'])}% in the baseline).", [tim])
        idx = {it["evidence_id"]: it for it in self.t.items}
        for r in res.get("rows", [])[:4]:
            c = idx[r["evidence_id"]]["computed"]
            self.add(f"{r['transaction_id']} on {c['date']} at {c['time']}: {money(c['amount'])}.", [idx[r["evidence_id"]]])

    def _contributors(self):
        trig = [f for f in self.t.of_type("risk_factor") if f["computed"]["triggered"]]
        weight = {}
        for f in trig:
            for t in f["source_ids"]:
                weight.setdefault(t, []).append(f)
        txn = {it["source_ids"][0]: it for it in self.t.of_type("transaction")}
        top = sorted(weight, key=lambda t: (-sum(f["computed"]["points"] for f in weight[t]), t))[:6]
        if not top:
            self.add("No individual transactions are linked to the indicators that fired.", trig[:1] or [self.k("alert")],
                     kind="limitation")
            return
        for t in top:
            it = txn.get(t)
            if not it:
                continue
            c = it["computed"]
            names = ", ".join(f["title"].split(" · ")[0] for f in weight[t])
            self.add(f"{t} ({c['timestamp_local']}, {money(c['amount'])}) is linked to: {names}.", [it] + weight[t])

    def _summary(self):
        from services.report_writer import write
        claims = write(self.t.case, self.t.of_type(*{i["type"] for i in self.t.items}))
        pick = [c for c in claims if c["section"] in ("case_overview", "observed_activity", "triggering_indicators")
                and c["kind"] != "status"][:5]
        for c in pick:
            self.claims.append({**c, "section": "answer"})
        lims = [c for c in claims if c["section"] == "missing_evidence"][:1]
        for c in lims:
            self.claims.append({**c, "section": "answer"})


# ======================================================================= service
def _thread(con, case_id, reviewer_id):
    r = con.execute("SELECT thread_id FROM chat_threads WHERE case_id = ? ORDER BY created_at_utc LIMIT 1", (case_id,)).fetchone()
    if r:
        return r[0]
    with tx(con):
        tid = next_id(con, "THR")
        con.execute("INSERT INTO chat_threads VALUES (?,?,?,?)", (tid, case_id, reviewer_id, utc_now_iso()))
    return tid


def history(con, case_id) -> list[dict]:
    r = con.execute("SELECT thread_id FROM chat_threads WHERE case_id = ? ORDER BY created_at_utc LIMIT 1", (case_id,)).fetchone()
    if not r:
        return []
    out = []
    for m in con.execute("SELECT * FROM chat_messages WHERE thread_id = ? ORDER BY created_at_utc, message_id", (r[0],)):
        d = dict(m)
        d["payload"] = loads(d["payload"], {})
        out.append(d)
    return out


def _verify(claims, tools: CaseTools, con):
    idx = build_index(tools.items)
    voc, look = repo.vocab(con), repo.evidence_owner(con)
    out = []
    for c in claims:
        st, f = validate_claim(c, tools.case_id, idx, voc, look)
        out.append({**c, "verification_status": st, "failures": f})
    return out


def _llm_answer(question, tools: CaseTools, prior: list[dict]):
    msgs = [{"role": "system", "content": CHAT_SYSTEM.format(case_id=tools.case_id)}]
    for m in prior[-6:]:
        msgs.append({"role": m["role"], "content": m["content"][:1500]})
    msgs.append({"role": "user", "content": question})
    calls = []
    specs = openai_tools()
    for _ in range(MAX_TOOL_ROUNDS):
        msg = llm_client.chat_message(msgs, tools=specs, temperature=0.1)
        tcs = msg.get("tool_calls") or []
        if not tcs:
            break
        msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tcs})
        for tc in tcs[:6]:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except ValueError:
                args = {}
            result = tools.call(name, args)
            calls.append({"tool": name, "args": args})
            msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(result, default=str)[:12000]})
    msgs.append({"role": "user", "content": "Now give the final answer as the JSON object described in the system message."})
    raw = llm_client.chat(msgs, json_mode=True, temperature=0.1)
    parsed = json.loads(raw)
    claims = [ClaimIn(section="answer", **{k: v for k, v in c.items() if k in ("kind", "text", "evidence_ids")}).model_dump()
              for c in parsed.get("claims", [])]
    if not claims:
        raise ValueError("LLM returned no claims")
    return claims, calls, msgs, raw


def ask(case_id: str, question: str, mode: str, reviewer_id: str) -> dict:
    question = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", question).strip()[:1000]
    if not question:
        raise ValueError("Question is empty")
    with connect() as con:
        tools = CaseTools(con, case_id)
        tid = _thread(con, case_id, reviewer_id)
        prior = history(con, case_id)
        ctx = next((m["payload"].get("context", {}) for m in reversed(prior) if m["role"] == "assistant"), {})
        used_mode, note, calls = "deterministic", None, []
        if mode == "llm":
            try:
                claims, calls, msgs, raw = _llm_answer(question, tools, prior)
                checked = _verify(claims, tools, con)
                bad = [c for c in checked if c["verification_status"] != "verified"]
                if bad:
                    msgs += [{"role": "assistant", "content": raw},
                             {"role": "user", "content": "These claims failed verification; fix them using only "
                              "the tool results, or remove them. Return the full JSON again.\n" + "\n".join(
                                  f"- \"{c['text']}\": {'; '.join(c['failures'])}" for c in bad)}]
                    raw = llm_client.chat(msgs, json_mode=True, temperature=0.1)
                    claims = [ClaimIn(section="answer", **{k: v for k, v in c.items() if k in ("kind", "text", "evidence_ids")}).model_dump()
                              for c in json.loads(raw).get("claims", [])]
                    checked = _verify(claims, tools, con)
                    bad = [c for c in checked if c["verification_status"] != "verified"]
                if bad:
                    raise ValueError(f"{len(bad)} claim(s) still failed verification after one repair")
                used_mode = "llm"
            except (llm_client.LLMUnavailable, ValueError, KeyError, TypeError) as e:
                note = f"LLM mode was requested but did not produce a verified answer ({e}). Showing the deterministic answer."
                used_mode = "llm_fallback"
        if used_mode != "llm":
            p = Planner(tools, ctx)
            checked = _verify(p.answer(question), tools, con)
            calls, ctx = p.calls, p.ctx
        text = " ".join(c["text"] for c in checked)
        now = utc_now_iso()
        with tx(con):
            con.execute("INSERT INTO chat_messages VALUES (?,?,?,?,?,?,?)",
                        (next_id(con, "MSG"), tid, "user", question, None, dumps({"reviewer_id": reviewer_id}), now))
            mid = next_id(con, "MSG")
            payload = {"claims": checked, "tool_calls": calls, "context": ctx, "note": note,
                       "new_evidence_ids": [i["evidence_id"] for i in tools.created]}
            con.execute("INSERT INTO chat_messages VALUES (?,?,?,?,?,?,?)", (mid, tid, "assistant", text, used_mode,
                                                                           dumps(payload), now))
        refs = {e for c in checked for e in c["evidence_ids"]}
        ev = {i["evidence_id"]: {"type": i["type"], "title": i["title"]} for i in tools.items if i["evidence_id"] in refs}
        return {"message_id": mid, "thread_id": tid, "mode": used_mode, "note": note, "claims": checked,
                "tool_calls": calls, "evidence_refs": ev, "created_at_utc": now, "question": question}
