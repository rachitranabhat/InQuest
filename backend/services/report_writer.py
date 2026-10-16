"""Deterministic report writer.

Builds every report section as structured claims whose numbers, dates and names
are copied from the cited evidence items. The output is validated exactly like
LLM output — it is not trusted just because code wrote it.
"""
from __future__ import annotations

import config
from services.claims import fmt_half_up

PROMPT_VERSION = "det-2"

# comparison evidence (cmp:<key>) that each indicator already presents with its finding
COVERED_BY = {
    "frequency": ("per_day", "busiest_hour"),
    "value": ("avg_amount",),
    "historical": ("week_total",),
    "timing": ("night_share",),
    "location": ("cities", "retailers"),
}


def money(x) -> str:
    v = fmt_half_up(float(x), 2)
    whole, frac = v.split(".")
    return f"${int(whole):,}.{frac}" if not whole.startswith("-") else f"-${int(whole[1:]):,}.{frac}"


def num(x) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return f"{x:g}" if isinstance(x, float) else str(x)


def plural(n, one, many=None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def ratio(x) -> str:
    return f"{fmt_half_up(x, 1)}×" if x is not None else "n/a"


class Writer:
    def __init__(self, case: dict, items: list[dict], actions: list[dict] | None = None):
        self.case = case
        self.items = items
        self.by_key = {it["provenance"].get("key"): it for it in items}
        self.by_type: dict[str, list[dict]] = {}
        for it in items:
            self.by_type.setdefault(it["type"], []).append(it)
        self.actions = actions or []
        self.claims: list[dict] = []

    def k(self, key):
        return self.by_key.get(key)

    def add(self, section, text, cites, kind="fact", assertions=None):
        ids = [c["evidence_id"] for c in cites if c]
        self.claims.append({"section": section, "kind": kind, "text": text, "evidence_ids": ids,
                            "assertions": assertions or []})

    # ------------------------------------------------------------------ sections
    def build(self) -> list[dict]:
        c, alert = self.case, self.k("alert")
        is_acct = c["channel"] == "online_account"
        rel = self.k("rel:account") or self.k("rel:attribution")
        metric = self.k("metric:window")
        a = alert["computed"]

        # 1 overview
        if is_acct:
            self.add("case_overview", f"{c['case_id']} concerns online account {c['subject_id']}, held by player "
                     f"{c['player_id']} according to the account records.", [alert, rel])
        else:
            self.add("case_overview", f"{c['case_id']} concerns player {c['subject_id']}. Only purchases where the "
                     f"player's rewards card was scanned are linked to them; other purchases are anonymous.", [alert, rel])
        self.add("case_overview", f"The prototype alert score is {num(a['alert_score'])} / 100 ({a['score_band']} band). "
                 "It measures how unusual the activity is under transparent rules; it is not a probability of fraud.",
                 [alert])
        self.add("case_overview", f"Review priority: {c['priority']}. Evidence completeness: "
                 f"{c['evidence_completeness']}. {c['urgency']}.", [alert], kind="status")

        # 2 initial alert
        rules = "; ".join(a["rules_fired"])
        self.add("initial_alert", f"Alert {c['alert_id']} ({a['alert_type']}) was raised by the simulated monitoring "
                 f"feed at {a['triggered_at_local']}. Rules that fired: {rules}.", [alert])
        trig = [f for f in self.by_type.get("risk_factor", []) if f["computed"]["triggered"]]
        if trig:
            names = ", ".join(self._plain(f).lower() for f in trig)
            self.add("initial_alert", f"{plural(len(trig), 'indicator')} reached the level that counts: {names}.",
                     [alert] + trig)
        self.add("initial_alert", f"The alert looked at the recent {a['window_days']} days ({a['window_start']} to "
                 f"{a['window_end']}) and compared them with the previous {a['baseline_days']} days.", [alert])

        # 3 observed activity
        m = metric["computed"]
        label = "deposits" if is_acct else "linked purchases"
        trig_keys = {f["provenance"]["key"].split(":")[1] for f in trig}
        self.add("observed_activity", f"The records show {m['transaction_count']} {label} totalling "
                 f"{money(m['total_amount'])} between {m['first_local']} and {m['last_local']}, on "
                 f"{m['days_active']} of the {m['window_days']} days.", [metric])
        if "value" not in trig_keys:  # otherwise stated once, in the key findings
            self.add("observed_activity", f"The average was {money(m['average_amount'])} and the largest single amount "
                     f"was {money(m['max_amount'])}.", [metric])
        if is_acct:
            ff = self.k("metric:fundflow")["computed"]
            self.add("observed_activity", f"Deposits totalled {money(ff['deposit_total'])} ({ff['deposit_count']}), "
                     f"wagers {money(ff['wager_total'])} ({ff['wager_count']}) and withdrawals "
                     f"{money(ff['withdrawal_total'])} ({ff['withdrawal_count']}); "
                     f"{num(ff['wagered_pct_of_deposits'])}% of deposited funds were wagered.", [self.k("metric:fundflow")])
        elif m.get("unique_retailers") is not None:
            self.add("observed_activity", f"Purchases were made at {plural(m['unique_retailers'], 'retailer')} in "
                     f"{plural(m['unique_cities'], 'city', 'cities')}.", [metric])
        seq = self.k("seq:peak")
        if seq and "frequency" not in trig_keys:
            s = seq["computed"]
            self.add("observed_activity", f"The busiest 60 minutes held {s['transaction_count']} transactions "
                     f"({money(s['total_amount'])}) between {s['start_local']} and {s['end_time']}.", [seq])
        days = sorted(self.by_type.get("aggregate_day", []), key=lambda d: -d["computed"]["transaction_count"])
        if days:
            d = days[0]["computed"]
            self.add("observed_activity", f"The busiest day was {d['date']}, with {d['transaction_count']} transactions "
                     f"totalling {money(d['total_amount'])}.", [days[0]])

        # 4 triggering indicators
        for f in sorted(trig, key=lambda x: -x["computed"]["points"]):
            self.add("triggering_indicators", self._factor_sentence(f), [f])
        if not trig:
            self.add("triggering_indicators", "No individual indicator reached its trigger level.",
                     self.by_type.get("risk_factor", [])[:1])

        # 5 supporting evidence: transactions referenced by the most points
        weight: dict[str, float] = {}
        for f in trig:
            for t in f["source_ids"]:
                weight[t] = weight.get(t, 0) + f["computed"]["points"]
        txn_items = {it["source_ids"][0]: it for it in self.by_type.get("transaction", [])}
        top = sorted(weight, key=lambda t: (-weight[t], t))[:5]
        for t in top:
            it = txn_items.get(t)
            if not it:
                continue
            x = it["computed"]
            where = f" at {x['retailer_name']} ({x['city']})" if x.get("retailer_name") else ""
            self.add("supporting_evidence", f"{t}: {x['transaction_type']} of {money(x['amount'])} on "
                     f"{x['timestamp_local']}{where}.", [it])
        for r in self.by_type.get("aggregate_retailer", [])[:3]:
            x = r["computed"]
            self.add("supporting_evidence", f"{x['retailer_name']} ({x['retailer_id']}, {x['city']}) accounts for "
                     f"{x['transaction_count']} purchases ({money(x['total_amount'])}, {num(x['share_pct'])}% of recent "
                     "activity).", [r])

        # 6 historical comparison
        base = self.k("baseline")
        b = base["computed"]
        self.add("historical_comparison", f"Previous activity: {b['baseline_transaction_count']} {label} over "
                 f"{b['baseline_days']} days ({num(b['transactions_per_day'])} per day on average).", [base])
        covered = {k for f in trig for k in COVERED_BY.get(f["provenance"]["key"].split(":")[1], ())}
        shown_elsewhere = 0
        for cmp_ in self.by_type.get("comparison", []):
            x = cmp_["computed"]
            if cmp_["provenance"].get("key", "").split(":")[-1] in covered:
                shown_elsewhere += 1  # the same comparison is presented with its finding
                continue
            if x["ratio"] is None:
                if x["current"]:
                    self.add("historical_comparison", f"{x['metric']}: {num(x['current'])} recently, "
                             "with none in the previous period.", [cmp_, base])
                continue
            if abs(x["ratio"] - 1) < 0.25:
                continue
            word = "higher" if x["ratio"] > 1 else "lower"
            self.add("historical_comparison", f"{x['metric']}: {num(x['baseline'])} before vs. "
                     f"{num(x['current'])} recently ({ratio(x['ratio'])}, {word} than before).",
                     [cmp_])
        if shown_elsewhere:
            self.add("historical_comparison", "The comparisons behind each key finding are shown with that finding.",
                     [], kind="status")
        if not b["sufficient"]:
            self.add("historical_comparison", "There is too little previous activity for a reliable comparison, so "
                     "indicators that depend on it were not scored.", [base, self.k("lim:baseline")], kind="limitation")

        # 7 related entities
        self.add("related_entities", rel["summary"].split(". Purchases without")[0] + ".", [rel])
        for r in self.by_type.get("retailer", [])[:4]:
            x = r["computed"]
            agg = self.k(f"agg_ret:{x['retailer_id']}")
            new = agg and agg["computed"]["new_for_subject"]
            self.add("related_entities", f"{x['retailer_name']} ({x['retailer_id']}) is in {x['city']} and has "
                     f"{x['terminal_count']} terminal(s)" + ("; this player had not used it before." if new else "."),
                     [r, agg] if agg else [r])
        for cp in self.by_type.get("co_presence", [])[:3]:
            x = cp["computed"]
            self.add("related_entities", f"{x['other_player_id']} made {x['transaction_count']} purchases at the same "
                     f"retailer within {x['window_minutes']} minutes of this player's purchases. This is co-location "
                     "only; the records show no verified relationship between them.", [cp],
                     kind="interpretation")

        # 8 alternative explanations
        self._alternatives(trig)

        # 9 missing or conflicting evidence
        for lim in self.by_type.get("limitation", []):
            self.add("missing_evidence", lim["summary"], [lim], kind="limitation")

        # 10 recommended checks
        self._recommendations(trig)

        # 11 review status (system statements from the audit log)
        self._status()
        return self.claims

    @staticmethod
    def _plain(f: dict) -> str:
        return config.PLAIN_FACTOR_LABELS.get(f["provenance"].get("key", "").split(":")[-1], f["title"].split(" · ")[0])

    def _factor_sentence(self, f: dict) -> str:
        k = f["provenance"].get("key", "").split(":")[1]
        x = f["computed"]
        head = f"{self._plain(f)} ({num(x['points'])} of {x['max_points']} points): "
        if k == "frequency":
            return head + (f"{x['peak_hour_transactions']} transactions in one hour vs. a previous busiest hour of "
                           f"{num(x['baseline_busiest_hour'])} ({ratio(x['peak_hour_ratio'])}); "
                           f"{num(x['transactions_per_day'])} per day vs. {num(x['baseline_per_day'])}.")
        if k == "value":
            return head + (f"largest amount {money(x['max_amount'])} vs. a previous 95th percentile of "
                           f"{money(x['baseline_p95'])}; average {money(x['average_amount'])} vs. "
                           f"{money(x['baseline_average'])}.")
        if k == "location":
            cities = ", ".join(x["new_cities"]) if x["new_cities"] else "none"
            return head + (f"{x['new_city_count']} new cities ({cities}) and {x['new_retailer_count']} new retailers "
                           "compared with previous activity.")
        if k == "timing":
            return head + (f"{x['night_transactions']} transactions between midnight and 5 am "
                           f"({num(x['night_share_pct'])}% of recent activity vs. {num(x['baseline_night_share_pct'])}% before).")
        if k == "historical":
            return head + (f"{money(x['window_total'])} in the recent period vs. {money(x['typical_week_total'])} in a "
                           f"typical week before ({ratio(x['spend_ratio'])}).")
        if k == "pattern":
            rep = (f"; {money(x['repeated_amount'])} repeated {x['repeated_amount_count']} times"
                   if x.get("repeated_amount") else "")
            return head + f"{x['rapid_pairs']} pairs of transactions less than 2 minutes apart{rep}."
        if k == "playthrough":
            return head + (f"{num(x['wagered_pct'])}% of {money(x['deposits'])} deposited was wagered, and withdrawals of "
                           f"{money(x['withdrawals'])} equal {num(x['withdrawn_pct'])}% of deposits.")
        return head + f["summary"]

    def _alternatives(self, trig):
        sec = "alternative_explanations"
        ev = self.by_type.get("context_event", [])
        for e in ev:
            x = e["computed"]
            if x.get("subject_transactions_during_event") and x.get("network_ratio"):
                self.add(sec, f"The recent period includes {x['event_name']} ({x['start']} to {x['end']}). "
                         f"Network-wide terminal sales on those days were {ratio(x['network_ratio'])} the baseline daily "
                         f"level, and {x['subject_transactions_during_event']} of this subject's transactions fall on "
                         "those days, so part of the increase may reflect the jackpot rather than individual behaviour.",
                         [e], kind="interpretation")
        loc = self.k("factor:location")
        if loc and not self.case["channel"] == "online_account" and loc["computed"]["new_retailer_count"] == 0 \
                and loc["computed"]["new_city_count"] == 0:
            self.add(sec, "Every recent purchase was at a retailer this player had already used before, "
                     "which is consistent with routine local activity.", [loc], kind="interpretation")
        if self.case["alert_score"] < config.ALERT_THRESHOLD:
            self.add(sec, "Only the volume rule fired. Measured against this player's own history the activity is "
                     "close to normal, which suggests a habitually high-volume player rather than a change in behaviour.",
                     [self.k("alert"), self.k("cmp:per_day")], kind="interpretation")
        if len(trig) == 1:
            self.add(sec, "Only one indicator fired. Single-indicator alerts often have ordinary explanations such as a "
                     "one-off occasion.", [self.k("alert")] + trig, kind="interpretation")
        if self.case["channel"] == "online_account":
            ff = self.k("metric:fundflow")
            self.add(sec, "Depositing and then withdrawing with little play can have ordinary causes, such as a "
                     "player changing their mind; the records alone cannot distinguish this from moving funds through "
                     "the account.", [ff, self.k("lim:payment")], kind="interpretation")
        self.add(sec, "Changes in personal circumstances, a prize win or shared use of a rewards card could also explain "
                 "unusual activity; the records cannot distinguish between these.", [self.k("lim:identity")],
                 kind="interpretation")

    def _recommendations(self, trig):
        sec = "recommended_checks"
        keys = {f["provenance"]["key"].split(":")[1] for f in trig}
        seq = self.k("seq:peak")
        rets = self.by_type.get("aggregate_retailer", [])
        if self.case["channel"] == "online_account":
            self.add(sec, f"Review the funding source of the deposits and the destination of the withdrawals for "
                     f"{self.case['subject_id']}; these details are not in the available records.",
                     [self.k("metric:fundflow"), self.k("lim:payment")], kind="recommendation")
            self.add(sec, "Check device and login history for the session in which the deposits were made.",
                     [self.k("lim:device")], kind="recommendation")
        if "frequency" in keys and seq and rets:
            r = rets[0]["computed"]
            self.add(sec, f"Ask {r['retailer_name']} ({r['retailer_id']}) whether terminal logs or staff can account "
                     f"for the burst of purchases on {seq['computed']['date']}.", [seq, rets[0],
                     self.k("lim:retailer_records")], kind="recommendation")
        lim_un = self.k("lim:unattributed")
        if lim_un and lim_un["computed"].get("case_specific"):
            self.add(sec, "Before drawing conclusions, consider the nearby anonymous purchases: request terminal-level "
                     "records for the same retailers and times to see whether activity was split across scanned and "
                     "unscanned sales.", [lim_un], kind="recommendation")
        if "location" in keys:
            self.add(sec, "Check whether travel or a change of address explains purchases in new cities.",
                     [self.k("factor:location")], kind="recommendation")
        if "pattern" in keys:
            pat = self.k("factor:pattern")
            if pat["computed"].get("repeated_amount"):
                self.add(sec, "Verify the ticket validation records behind the repeated identical amounts.",
                         [pat], kind="recommendation")
            else:
                self.add(sec, "Review the back-to-back transactions to see whether they were single multi-ticket "
                         "purchases rung up separately.", [pat], kind="recommendation")
        if any(e["computed"].get("network_ratio") for e in self.by_type.get("context_event", [])):
            self.add(sec, "Compare this subject's increase with other players' activity during the jackpot week.",
                     self.by_type["context_event"][:1], kind="recommendation")
        if self.by_type.get("co_presence"):
            self.add(sec, "Treat the co-located players as separate subjects unless independent records show a link.",
                     self.by_type["co_presence"][:1], kind="recommendation")
        self.add(sec, "Record a reviewer decision with notes. The copilot does not make the determination.",
                 [self.k("alert")], kind="recommendation")

    def _status(self):
        acts = [a for a in self.actions if a["action"] != "report_generated"]
        if not acts:
            self.add("review_status", f"Status: {self.case['status']}. No reviewer action has been recorded yet.",
                     [], kind="status")
            return
        last = acts[-1]
        self.add("review_status", f"Status: {self.case['status']}. {len(acts)} reviewer action(s) recorded; the most "
                 f"recent was \"{config.ACTION_LABELS.get(last['action'], last['action'])}\" by "
                 f"{last.get('reviewer_name', last['reviewer_id'])} at {last['created_at_utc']}.", [], kind="status")


def write(case: dict, items: list[dict], actions=None) -> list[dict]:
    return Writer(case, items, actions).build()
