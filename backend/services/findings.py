"""Investigator-facing findings: one card per indicator, in three levels.

Level 1  headline + one sentence on what changed + a compact comparison
Level 2  why it matters, what was usual, limitations, supporting records (cited)
Level 3  exact metric names, periods, rule thresholds, raw and normalized values, evidence IDs

Everything here is *presentation* of evidence that already exists. Every number is read
from the case's stored evidence items (risk_factor, comparison, baseline, alert ...).
The only arithmetic is
  * differences/ratios between two stored values that are shown side by side, and
  * the rule's own linear ramp, re-applied to the stored measurements so the
    "normalized value" in the technical details can be checked against the stored points.
No detection score, threshold or history value is changed.
"""
from __future__ import annotations

from datetime import date, timedelta

import config
from database.db import connect
from services import repo
from services.report_writer import money, num

ATTENTION = "Worth a closer look. This is a reason to review, not proof of wrongdoing."
NOT_UNUSUAL = "Within the range this rule treats as normal."

# The rule ramps from detection/risk_scoring.py (start, full). Mirrored here only to show the
# calculation; tests assert the re-applied ramp reproduces the stored score for every case.
RAMPS = {
    "frequency": [("Transactions per day ratio", "frequency_ratio", 1.5, 5.0, 1.0),
                  ("Busiest-hour ratio", "peak_hour_ratio", 1.5, 6.0, 1.0)],
    "value": [("Average amount ratio", "avg_ratio", 1.5, 5.0, 1.0),
              ("Largest amount ÷ previous 95th percentile", "max_vs_p95", 1.5, 6.0, 1.0)],
    "location": [("New cities", "new_city_count", 0.0, 3.0, 1.0),
                 ("New retailers (weighted 0.6)", "new_retailer_count", 2.0, 8.0, 0.6)],
    "historical": [("Spend ratio (recent ÷ typical week)", "spend_ratio", 1.5, 8.0, 1.0)],
    "pattern": [("Back-to-back pairs (< 2 min)", "rapid_pairs", 2.0, 10.0, 1.0),
                ("Repeated identical amounts (≥ $20)", "repeated_amount_count", 3.0, 8.0, 1.0)],
}
BASELINE_DEPENDENT = ("frequency", "value", "location", "historical")


def _ramp(x, start, full) -> float:
    if x is None:
        return 0.0
    return float(min(1.0, max(0.0, (x - start) / (full - start))))


def _pct(x) -> str:
    return f"{num(round(float(x), 1))}%"


def _ratio(cur, prev) -> float | None:
    return round(cur / prev, 1) if prev else None


def _new_places(x: dict) -> str:
    parts = []
    if x["new_city_count"]:
        parts.append(_plural(x["new_city_count"], "new city", "new cities"))
    if x["new_retailer_count"]:
        parts.append(_plural(x["new_retailer_count"], "new retailer"))
    return (" and ".join(parts) + ".") if parts else "Every city and retailer had been used before."


def _times(r: float) -> str:
    return f"{num(r)}×"


def _plural(n, one, many=None) -> str:
    return f"{num(n)} {one if n == 1 else (many or one + 's')}"


def compare_values(prev, cur, *, kind: str, previous_n: int, unit: str = "",
                   stored_ratio: float | None = None, floor: float = 0.0) -> dict:
    """Describe a previous-vs-recent change without misleading percentages.

    kind: "pct"    two percentages → difference in percentage points
          "amount" money values    → ratio when the previous value is above zero
          "count"  plain numbers   → ratio when the previous value is above zero
    previous_n: number of previous records. 0 means there was nothing to compare with,
    which is different from records that were observed and showed zero activity.
    """
    if previous_n == 0:
        return {"state": "no_previous", "text": "Insufficient previous activity to establish a typical pattern.",
                "direction": None}
    if kind == "pct":
        d = round(float(cur) - float(prev), 1)
        direction = "up" if d > 0 else "down" if d < 0 else "same"
        word = {"up": "Increase", "down": "Decrease", "same": "No change"}[direction]
        text = f"{word}: {num(abs(d))} percentage points" if d else "No change"
        return {"state": "zero_observed" if not prev else "observed", "text": text, "direction": direction,
                "difference": d, "difference_unit": "percentage points"}
    if not prev:
        fmt = money(cur) if kind == "amount" else num(cur)
        return {"state": "zero_observed", "direction": "up" if cur else "same",
                "text": (f"None previously; {fmt}{(' ' + unit) if unit else ''} recently" if cur else "None previously or recently")}
    # The detection ratios divide by max(previous, floor). Only reuse the stored ratio when the floor
    # was not applied; otherwise it would overstate the change.
    if stored_ratio is not None and float(prev) >= floor:
        from services.claims import fmt_half_up
        r = float(fmt_half_up(float(stored_ratio), 1))
    elif float(prev) < floor:
        fmt = money(cur) if kind == "amount" else num(cur)
        return {"state": "observed", "direction": "up" if cur > prev else "same",
                "text": f"Up from {money(prev) if kind == 'amount' else num(prev)} to {fmt}"}
    else:
        r = _ratio(float(cur), float(prev))
    direction = "up" if cur > prev else "down" if cur < prev else "same"
    if direction == "same":
        text = "No change"
    elif r is not None and r >= 1.1:
        text = f"{_times(r)} the previous level"
    elif r is not None and r <= 0.9:
        text = f"Lower: {_times(r)} the previous level"
    else:
        text = "About the same as before"
    return {"state": "observed", "text": text, "direction": direction, "ratio": r}


class _Case:
    def __init__(self, case: dict, items: list[dict]):
        self.case = case
        self.items = [i for i in items if i["type"] != "query_result"]
        self.by_key = {i["provenance"].get("key"): i for i in self.items}
        self.txn_ev = {i["source_ids"][0]: i["evidence_id"] for i in self.items if i["type"] == "transaction" and i["source_ids"]}
        self.is_acct = case["channel"] == "online_account"
        a = self.by_key["alert"]["computed"]
        self.w_days, self.b_days = a["window_days"], a["baseline_days"]
        ws = date.fromisoformat(a["window_start"])
        self.periods = {
            "previous_days": self.b_days, "recent_days": self.w_days,
            "previous_start": (ws - timedelta(days=self.b_days)).isoformat(),
            "previous_end": (ws - timedelta(days=1)).isoformat(),
            "recent_start": a["window_start"], "recent_end": a["window_end"],
        }
        b = self.by_key["baseline"]["computed"]
        self.base_n = int(b["baseline_transaction_count"])
        self.base_ok = bool(b.get("sufficient", True))
        self.scope = "deposits" if self.is_acct else "linked purchases"
        self.scope_one = "deposit" if self.is_acct else "linked purchase"

    def ev(self, key):
        it = self.by_key.get(key)
        return it["evidence_id"] if it else None

    def ids(self, *keys):
        return [e for e in (self.ev(k) for k in keys) if e]

    # ------------------------------------------------------------------ helpers
    def _limitations(self, k: str) -> list[dict]:
        out = []
        lim = self.by_key.get("lim:baseline")
        if lim and k in BASELINE_DEPENDENT:
            out.append({"text": f"Only {_plural(self.base_n, 'previous ' + self.scope_one, 'previous ' + self.scope)}: "
                                "too few to establish a typical pattern, so this indicator was not scored.",
                        "evidence_id": lim["evidence_id"]})
        if not self.is_acct and k in ("frequency", "value", "historical", "timing", "location"):
            out.append({"text": "Counts only purchases where the player's rewards card was scanned. "
                                "Anonymous purchases are not linked to anyone and are not included.",
                        "evidence_id": self.ev("rel:attribution")})
        un = self.by_key.get("lim:unattributed")
        if un and un["computed"].get("case_specific") and k in ("frequency", "historical"):
            out.append({"text": f"{_plural(un['computed']['anonymous_nearby_count'], 'anonymous purchase')} happened at the "
                                "same retailers around the same times. Who made them is unknown.",
                        "evidence_id": un["evidence_id"]})
        if k in ("frequency", "historical", "value"):
            for e in (i for i in self.items if i["type"] == "context_event"):
                x = e["computed"]
                if x.get("network_ratio") and x.get("subject_transactions_during_event"):
                    out.append({"text": f"{x['event_name']} ({x['start']} to {x['end']}) raised activity across all "
                                        f"terminals to {_times(x['network_ratio'])} the usual daily level.",
                                "evidence_id": e["evidence_id"]})
        if self.is_acct and k == "playthrough":
            out.append({"text": "Funding sources and withdrawal destinations are not in the records.",
                        "evidence_id": self.ev("lim:payment")})
        return out

    def _supporting(self, fac: dict, fallback_key: str | None = None) -> list[str]:
        src = [s for s in fac["source_ids"] if s.startswith("TXN-")]
        if not src and fallback_key and self.by_key.get(fallback_key):
            src = [s for s in self.by_key[fallback_key]["source_ids"] if s.startswith("TXN-")]
        return src

    def _technical(self, k: str, x: dict, fac: dict, metrics: list[tuple[str, str, object]],
                   definitions: list[str], normalization: str | None) -> dict:
        subs = []
        for name, field, start, full, weight in RAMPS.get(k, []):
            v = x.get(field)
            subs.append({"name": name, "field": field, "value": v, "starts_at": start, "full_at": full, "weight": weight,
                         "normalized": round(weight * _ramp(v, start, full), 3)})
        if k == "timing":
            d = round((x["night_share_pct"] - x["baseline_night_share_pct"]) / 100, 3)
            subs.append({"name": "Overnight share minus previous share", "field": "night_share_pct − baseline_night_share_pct",
                         "value": d, "starts_at": 0.05, "full_at": 0.40, "weight": 1.0,
                         "normalized": round(_ramp(d, 0.05, 0.40) if x["night_transactions"] >= 3 else 0.0, 3),
                         "note": "Needs at least 3 overnight transactions."})
        if k == "playthrough":
            wd, unplayed = x["withdrawn_pct"] / 100, 1 - x["wagered_pct"] / 100
            subs.append({"name": "Withdrawn ÷ deposited", "field": "withdrawn_pct", "value": round(wd, 3),
                         "starts_at": 0.30, "full_at": 0.90, "weight": 1.0, "normalized": round(_ramp(wd, 0.30, 0.90), 3)})
            subs.append({"name": "Share of deposits never wagered", "field": "100 − wagered_pct", "value": round(unplayed, 3),
                         "starts_at": 0.40, "full_at": 0.90, "weight": 1.0, "normalized": round(_ramp(unplayed, 0.40, 0.90), 3),
                         "note": "The two parts are multiplied."})
        return {
            "technical_label": config.FACTOR_LABELS[k],
            "rule": fac["provenance"].get("rule"),
            "engine": fac["provenance"].get("engine"),
            "metrics": [{"label": lbl, "field": f, "value": v} for lbl, f, v in metrics],
            "sub_measures": subs,
            "normalized_share": x["share_pct"] / 100,
            "points": x["points"], "max_points": x["max_points"],
            "trigger_at_share": config.FACTOR_TRIGGER_RATIO,
            "definitions": definitions,
            "normalization": normalization,
        }

    # ------------------------------------------------------------------ factors
    def finding(self, fac: dict) -> dict:
        k = fac["provenance"]["key"].split(":")[1]
        x = fac["computed"]
        scored = not (k in BASELINE_DEPENDENT and not self.base_ok)
        build = getattr(self, f"_f_{k}")
        body = build(x, fac)
        if not scored:
            body["headline"] = "Not scored: too little previous activity"
            body["change"] = (f"Only {_plural(self.base_n, 'previous ' + self.scope_one, 'previous ' + self.scope)} "
                              "were found, which is too few to establish a typical pattern.")
        triggered = bool(x["triggered"])
        return {
            "key": k,
            "evidence_id": fac["evidence_id"],
            "label": config.PLAIN_FACTOR_LABELS[k],
            "technical_label": config.FACTOR_LABELS[k],
            "triggered": triggered,
            "scored": scored,
            "points": x["points"], "max_points": x["max_points"],
            "contribution": (f"Added {num(x['points'])} of a possible {x['max_points']} points to the prototype score."
                             if x["points"] else f"Added 0 of a possible {x['max_points']} points to the prototype score."),
            "attention": ATTENTION if triggered else NOT_UNUSUAL,
            **body,
            "limitations": [l for l in self._limitations(k) if l["evidence_id"]],
            "evidence_ids": [e for e in dict.fromkeys([fac["evidence_id"], *body.pop("evidence_ids")]) if e],
        }

    def _period_rows(self, prev_disp, cur_disp, prev_val, cur_val, unit):
        return [
            {"period": "previous", "label": f"Previous {self.b_days} days", "value": prev_val, "display": prev_disp, "unit": unit},
            {"period": "recent", "label": f"Recent {self.w_days} days", "value": cur_val, "display": cur_disp, "unit": unit},
        ]

    def _f_frequency(self, x, fac):
        rate_s = _ramp(x["frequency_ratio"], 1.5, 5)
        peak_s = _ramp(x["peak_hour_ratio"], 1.5, 6)
        peak_first = (peak_s, x["peak_hour_ratio"] / 6) >= (rate_s, x["frequency_ratio"] / 5)
        if peak_first:
            headline = f"{_plural(x['peak_hour_transactions'], self.scope_one, self.scope)} within a single hour"
            change = (f"The busiest hour in the recent {self.w_days} days had {_plural(x['peak_hour_transactions'], self.scope_one, self.scope)}; "
                      f"before, the busiest hour of an active day averaged {num(x['baseline_busiest_hour'])}.")
            rows = self._period_rows(num(x["baseline_busiest_hour"]), num(x["peak_hour_transactions"]),
                                     x["baseline_busiest_hour"], x["peak_hour_transactions"], "in the busiest hour")
            delta = compare_values(x["baseline_busiest_hour"], x["peak_hour_transactions"], kind="count", previous_n=self.base_n,
                                   stored_ratio=x["peak_hour_ratio"], floor=1.0)
            unit = "transactions in the busiest hour"
        else:
            headline = (f"{self.scope.capitalize()} were more frequent than before" if x["transactions_per_day"] > x["baseline_per_day"]
                        else f"{self.scope.capitalize()} were about as frequent as before")
            change = (f"{num(x['transactions_per_day'])} per day in the recent {self.w_days} days, compared with "
                      f"{num(x['baseline_per_day'])} per day in the previous {self.b_days} days.")
            rows = self._period_rows(num(x["baseline_per_day"]), num(x["transactions_per_day"]),
                                     x["baseline_per_day"], x["transactions_per_day"], "per day")
            delta = compare_values(x["baseline_per_day"], x["transactions_per_day"], kind="count", previous_n=self.base_n,
                                   stored_ratio=x["frequency_ratio"], floor=0.1)
            unit = "transactions per day"
        return {
            "headline": headline, "change": change,
            "comparison": {"kind": "previous_vs_recent", "unit": unit, "rows": rows, "delta": delta},
            "explain": {
                "measured": f"How many {self.scope} happened per day, and the most in any 60 minutes.",
                "usual": (f"{num(x['baseline_per_day'])} per day; the busiest hour of an active day averaged "
                          f"{num(x['baseline_busiest_hour'])}."),
                "changed": (f"{num(x['transactions_per_day'])} per day; the busiest hour had "
                            f"{num(x['peak_hour_transactions'])}."),
                "why": ("Counts once activity reaches 1.5× the previous level, with full points at 5× (per day) "
                        "or 6× (busiest hour). Bursts are worth checking against terminal records; they also "
                        "happen for ordinary reasons, such as buying for a group."),
            },
            "supporting_transaction_ids": self._supporting(fac, "seq:peak"),
            "technical": self._technical("frequency", x, fac, [
                ("Recent transactions per day", "transactions_per_day", x["transactions_per_day"]),
                ("Previous transactions per day", "baseline_per_day", x["baseline_per_day"]),
                ("Per-day ratio", "frequency_ratio", x["frequency_ratio"]),
                ("Recent busiest 60 minutes", "peak_hour_transactions", x["peak_hour_transactions"]),
                ("Previous busiest hour (average of active days)", "baseline_busiest_hour", x["baseline_busiest_hour"]),
                ("Busiest-hour ratio", "peak_hour_ratio", x["peak_hour_ratio"]),
            ], [
                f"Per day = number of {self.scope} ÷ days in the period ({self.b_days} previous, {self.w_days} recent).",
                "Recent busiest hour = the most transactions in any rolling 60 minutes of the recent period.",
                "Previous busiest hour = the average, over days with activity, of each day's busiest 60 minutes.",
                "Ratios divide by at least 0.1 per day (1 for the busiest hour) to avoid dividing by zero.",
            ], "Per-day counts are normalized by period length; busiest-hour values are not period totals."),
            "evidence_ids": self.ids("cmp:per_day", "cmp:busiest_hour", "seq:peak", "baseline"),
        }

    def _f_value(self, x, fac):
        avg_s = _ramp(x["avg_ratio"], 1.5, 5)
        max_s = _ramp(x["max_vs_p95"], 1.5, 6)
        largest_first = (max_s, x["max_vs_p95"] / 6) >= (avg_s, x["avg_ratio"] / 5)
        noun = "deposit" if self.is_acct else "purchase"
        if largest_first:
            headline = (f"The largest {noun}, {money(x['max_amount'])}, was {'well ' if x['triggered'] else ''}above the usual range"
                        if x["max_amount"] > x["baseline_p95"] else f"No {noun} was above the usual range")
            change = (f"The largest amount was {money(x['max_amount'])}; the usual high before "
                      f"(95th percentile) was {money(x['baseline_p95'])}.")
            rows = [
                {"period": "previous", "label": f"Previous {self.b_days} days (95th percentile)", "value": x["baseline_p95"],
                 "display": money(x["baseline_p95"]), "unit": "$"},
                {"period": "recent", "label": f"Recent {self.w_days} days (largest)", "value": x["max_amount"],
                 "display": money(x["max_amount"]), "unit": "$"},
            ]
            delta = compare_values(x["baseline_p95"], x["max_amount"], kind="amount", previous_n=self.base_n,
                                   stored_ratio=x["max_vs_p95"], floor=1.0)
            unit = "largest amount vs. usual high"
        else:
            headline = (f"Average {noun} amount was higher than before" if x["average_amount"] > x["baseline_average"]
                        else f"Average {noun} amount was similar to before")
            change = (f"Average {money(x['average_amount'])} in the recent {self.w_days} days, compared with "
                      f"{money(x['baseline_average'])} in the previous {self.b_days} days.")
            rows = self._period_rows(money(x["baseline_average"]), money(x["average_amount"]),
                                     x["baseline_average"], x["average_amount"], "$")
            delta = compare_values(x["baseline_average"], x["average_amount"], kind="amount", previous_n=self.base_n,
                                   stored_ratio=x["avg_ratio"], floor=1.0)
            unit = "average amount"
        return {
            "headline": headline, "change": change,
            "comparison": {"kind": "previous_vs_recent", "unit": unit, "rows": rows, "delta": delta},
            "explain": {
                "measured": f"The average and the largest {noun} amount.",
                "usual": (f"Average {money(x['baseline_average'])}; usual high (95th percentile) "
                          f"{money(x['baseline_p95'])}."),
                "changed": f"Average {money(x['average_amount'])}; largest {money(x['max_amount'])}.",
                "why": ("Counts once the average reaches 1.5× the previous average, or the largest amount reaches "
                        "1.5× the previous 95th percentile (full points at 5× and 6×). Large one-off amounts are "
                        "worth matching to ticket or prize records."),
            },
            "supporting_transaction_ids": self._supporting(fac),
            "technical": self._technical("value", x, fac, [
                ("Recent average amount", "average_amount", x["average_amount"]),
                ("Previous average amount", "baseline_average", x["baseline_average"]),
                ("Average ratio", "avg_ratio", x["avg_ratio"]),
                ("Recent largest amount", "max_amount", x["max_amount"]),
                ("Previous 95th percentile", "baseline_p95", x["baseline_p95"]),
                ("Largest ÷ previous 95th percentile", "max_vs_p95", x["max_vs_p95"]),
            ], [
                "95th percentile = the amount that 95% of previous amounts were at or below.",
                "Supporting records are amounts at or above 1.5× the previous 95th percentile.",
                "Ratios divide by at least $1 to avoid dividing by zero.",
            ], "Averages and percentiles do not depend on period length."),
            "evidence_ids": self.ids("cmp:avg_amount", "baseline"),
        }

    def _f_location(self, x, fac):
        cities = self.by_key.get("cmp:cities")
        rets = self.by_key.get("cmp:retailers")
        usual = self.by_key["baseline"]["computed"].get("usual_cities") or []
        if x["new_city_count"]:
            headline = f"Purchases in {_plural(x['new_city_count'], 'city', 'cities')} not seen before"
        elif x["new_retailer_count"]:
            headline = f"Purchases at {_plural(x['new_retailer_count'], 'retailer')} not used before"
        else:
            headline = "All purchases were at familiar places"
        new_txt = f" New: {', '.join(x['new_cities'])}." if x["new_cities"] else ""
        incl = f", including {_plural(x['new_retailer_count'], 'retailer')} not used before" if x["new_retailer_count"] else \
            ", all used before"
        change = (f"{_plural(x['unique_cities'], 'city', 'cities')} and {_plural(x['unique_retailers'], 'retailer')} "
                  f"in the recent {self.w_days} days{incl}.{new_txt}")
        rows = []
        if cities:
            c = cities["computed"]
            rows.append({"period": "previous", "label": f"Cities, previous {self.b_days} days", "value": c["baseline"], "display": num(c["baseline"]), "unit": "cities"})
            rows.append({"period": "recent", "label": f"Cities, recent {self.w_days} days", "value": c["current"], "display": num(c["current"]), "unit": "cities"})
        return {
            "headline": headline, "change": change,
            "comparison": {"kind": "previous_vs_recent", "unit": "distinct cities", "rows": rows,
                           "delta": {"state": "no_previous", "text": "Insufficient previous activity to establish a typical pattern.",
                                     "direction": None} if self.base_n == 0 else
                           {"state": "observed", "direction": "up" if x["new_city_count"] else "same",
                            "text": _new_places(x).rstrip(".")},
                           "note": f"Distinct places are counted over different lengths ({self.b_days} vs. {self.w_days} days) and are not adjusted."},
            "explain": {
                "measured": "Cities and retailers used in the recent period that were never used before.",
                "usual": f"Previously used: {', '.join(usual)}." if usual else "No previous places on record.",
                "changed": _new_places(x),
                "why": ("Counts from the first new city (full points at 3), or from 2 new retailers (full at 8, "
                        "weighted 0.6). Travel or moving are common reasons; new places are worth confirming."),
            },
            "supporting_transaction_ids": self._supporting(fac),
            "technical": self._technical("location", x, fac, [
                ("New cities", "new_city_count", x["new_city_count"]),
                ("New city names", "new_cities", x["new_cities"]),
                ("New retailers", "new_retailer_count", x["new_retailer_count"]),
                ("Recent distinct cities", "unique_cities", x["unique_cities"]),
                ("Recent distinct retailers", "unique_retailers", x["unique_retailers"]),
                ("Previous distinct cities", "cmp:cities.baseline", cities["computed"]["baseline"] if cities else None),
                ("Previous distinct retailers", "cmp:retailers.baseline", rets["computed"]["baseline"] if rets else None),
            ], [
                "New = not used at all in the previous period.",
                "Supporting records are the purchases at new cities or new retailers.",
            ], f"Not normalized: distinct counts over {self.b_days} and {self.w_days} days."),
            "evidence_ids": self.ids("cmp:cities", "cmp:retailers", "baseline")
                            + [i["evidence_id"] for i in self.items if i["type"] == "aggregate_retailer" and i["computed"].get("new_for_subject")][:4],
        }

    def _f_timing(self, x, fac):
        share, base = x["night_share_pct"], x["baseline_night_share_pct"]
        if share >= 50:
            headline = f"Most recent {self.scope} happened overnight"
        elif share > base and x["night_transactions"] >= 3:
            headline = f"More {self.scope} happened overnight than before"
        elif x["night_transactions"]:
            headline = "Some overnight activity, similar to before" if share <= base else "A little overnight activity"
        else:
            headline = "No overnight activity"
        change = (f"{_pct(share)} occurred between midnight and 5 AM, compared with {_pct(base)} during the previous "
                  f"{self.b_days} days.") if self.base_n else \
            f"{_pct(share)} occurred between midnight and 5 AM. There is no previous activity to compare with."
        delta = compare_values(base, share, kind="pct", previous_n=self.base_n)
        note = (f"None of the {_plural(self.base_n, 'previous ' + self.scope_one, 'previous ' + self.scope)} were overnight (observed zero)."
                if self.base_n and not base else None)
        return {
            "headline": headline, "change": change,
            "comparison": {"kind": "previous_vs_recent", "unit": "share overnight (12–5 AM)",
                           "rows": self._period_rows(_pct(base), _pct(share), base, share, "%"), "delta": delta,
                           "scale_max": 100, "note": note},
            "explain": {
                "measured": f"The share of {self.scope} between 00:00 and 04:59.",
                "usual": (f"{_pct(base)} overnight; none of the {_plural(self.base_n, 'previous ' + self.scope_one, 'previous ' + self.scope)} "
                          "were overnight." if self.base_n and not base else f"{_pct(base)} overnight."),
                "changed": f"{_pct(share)} overnight ({_plural(x['night_transactions'], 'transaction')}).",
                "why": ("Counts when the overnight share is at least 5 percentage points above the previous share "
                        "(full points at 40), and only with 3 or more overnight transactions. A shift to overnight "
                        "play is worth confirming; shift work is an ordinary explanation."),
            },
            "supporting_transaction_ids": self._supporting(fac),
            "technical": self._technical("timing", x, fac, [
                ("Recent overnight transactions", "night_transactions", x["night_transactions"]),
                ("Recent overnight share (%)", "night_share_pct", share),
                ("Previous overnight share (%)", "baseline_night_share_pct", base),
            ], [
                "Overnight = local time 00:00 to 04:59 (America/Toronto).",
                "Shares are percentages of each period's own transactions, so period length does not matter.",
            ], "Shares are already normalized (percent of each period)."),
            "evidence_ids": self.ids("cmp:night_share", "baseline"),
        }

    def _f_historical(self, x, fac):
        higher = x["window_total"] > x["typical_week_total"]
        headline = "Spending was higher than in a typical week before" if higher else "Spending was at or below a typical week before"
        change = (f"{money(x['window_total'])} in the recent {self.w_days} days, compared with "
                  f"{money(x['typical_week_total'])} for a typical {self.w_days} days before.")
        return {
            "headline": headline, "change": change,
            "comparison": {"kind": "previous_vs_recent", "unit": f"total per {self.w_days} days",
                           "rows": [
                               {"period": "previous", "label": f"Typical {self.w_days} days (from previous {self.b_days})",
                                "value": x["typical_week_total"], "display": money(x["typical_week_total"]), "unit": "$"},
                               {"period": "recent", "label": f"Recent {self.w_days} days", "value": x["window_total"],
                                "display": money(x["window_total"]), "unit": "$"}],
                           "delta": compare_values(x["typical_week_total"], x["window_total"], kind="amount", previous_n=self.base_n,
                                                   stored_ratio=x["spend_ratio"], floor=1.0)},
            "explain": {
                "measured": f"Total value of {self.scope} in the recent period.",
                "usual": f"{money(x['typical_week_total'])} for a typical {self.w_days} days.",
                "changed": f"{money(x['window_total'])} in the recent {self.w_days} days.",
                "why": ("Counts from 1.5× a typical week (full points at 8×). A sustained rise in spending is "
                        "worth understanding; a prize win or a jackpot can explain it."),
            },
            "supporting_transaction_ids": self._supporting(fac, "cmp:week_total"),
            "technical": self._technical("historical", x, fac, [
                ("Recent total", "window_total", x["window_total"]),
                (f"Typical {self.w_days}-day total", "typical_week_total", x["typical_week_total"]),
                ("Spend ratio", "spend_ratio", x["spend_ratio"]),
            ], [
                "Ratio divides by at least $1 to avoid dividing by zero.",
            ], f"Typical {self.w_days}-day total = previous total ÷ {self.b_days} days × {self.w_days} days."),
            "evidence_ids": self.ids("cmp:week_total", "metric:window", "baseline"),
        }

    def _f_pattern(self, x, fac):
        rapid_s = _ramp(x["rapid_pairs"], 2, 10)
        rep_s = _ramp(x["repeated_amount_count"], 3, 8)
        if x.get("repeated_amount") and (rep_s, x["repeated_amount_count"] / 8) > (rapid_s, x["rapid_pairs"] / 10):
            headline = f"The same amount, {money(x['repeated_amount'])}, appeared {_plural(x['repeated_amount_count'], 'time')}"
        elif x["rapid_pairs"]:
            headline = f"{_plural(x['rapid_pairs'], 'pair')} of transactions less than 2 minutes apart"
        else:
            headline = "No back-to-back or repeated transactions"
        parts = []
        if x["rapid_pairs"]:
            parts.append(f"{_plural(x['rapid_pairs'], 'pair')} of consecutive transactions less than 2 minutes apart")
        if x.get("repeated_amount"):
            parts.append(f"{money(x['repeated_amount'])} appeared {_plural(x['repeated_amount_count'], 'time')}")
        change = ("; ".join(parts) + ".") if parts else \
            "No back-to-back transactions and no repeated large amounts."
        change = change[0].upper() + change[1:] if parts else change
        rows = [{"period": "recent", "label": "Back-to-back pairs", "value": x["rapid_pairs"], "display": num(x["rapid_pairs"]),
                 "unit": "pairs", "starts_at": 2, "full_at": 10},
                {"period": "recent", "label": "Repeated identical amounts", "value": x["repeated_amount_count"],
                 "display": num(x["repeated_amount_count"]), "unit": "times", "starts_at": 3, "full_at": 8}]
        return {
            "headline": headline, "change": change,
            "comparison": {"kind": "recent_only", "unit": "against the rule's range", "rows": rows,
                           "delta": None, "note": "This rule looks only at the recent period; it does not use previous activity."},
            "explain": {
                "measured": "Transactions less than 2 minutes apart, and identical amounts of $20 or more.",
                "usual": "Not compared with previous activity.",
                "changed": f"{_plural(x['rapid_pairs'], 'pair')}; {_plural(x['repeated_amount_count'], 'repeated amount')}.",
                "why": ("Counts from 2 back-to-back pairs (full at 10) or 3 repeats (full at 8). Repeated prize "
                        "amounts are worth matching to validation records; multi-ticket purchases rung up "
                        "separately are a common ordinary cause."),
            },
            "supporting_transaction_ids": self._supporting(fac),
            "technical": self._technical("pattern", x, fac, [
                ("Back-to-back pairs", "rapid_pairs", x["rapid_pairs"]),
                ("Repeated identical amounts", "repeated_amount_count", x["repeated_amount_count"]),
                ("Repeated amount", "repeated_amount", x.get("repeated_amount")),
            ], ["Back-to-back = consecutive transactions less than 2 minutes apart.",
                "Only identical amounts of $20 or more are counted as repeats."], None),
            "evidence_ids": [],
        }

    def _f_playthrough(self, x, fac):
        triggered = x["triggered"]
        # "without being played" only when the withdrawn share fits inside the never-wagered share
        fits = x["withdrawn_pct"] <= 100 - x["wagered_pct"]
        headline = ("Most deposited money was withdrawn without being played" if triggered and fits and x["withdrawn_pct"] >= 50
                    else "Money was withdrawn after little play" if triggered
                    else "Deposits were mostly played")
        change = (f"{_pct(x['wagered_pct'])} of the {money(x['deposits'])} deposited was wagered; withdrawals of "
                  f"{money(x['withdrawals'])} equal {_pct(x['withdrawn_pct'])} of deposits.")
        rows = [{"period": "recent", "label": lbl, "value": x[f], "display": money(x[f]), "unit": "$"}
                for lbl, f in (("Deposited", "deposits"), ("Wagered", "wagers"), ("Withdrawn", "withdrawals"))]
        return {
            "headline": headline, "change": change,
            "comparison": {"kind": "flow", "unit": f"money in the recent {self.w_days} days", "rows": rows, "delta": None},
            "explain": {
                "measured": "How much of the deposited money was wagered, and how much was withdrawn.",
                "usual": "Not compared with previous activity.",
                "changed": f"{_pct(x['wagered_pct'])} wagered; {_pct(x['withdrawn_pct'])} withdrawn.",
                "why": ("Counts when withdrawals exceed 30% of deposits and more than 40% of deposits were never "
                        "wagered (full points at 90% for both). Depositing and withdrawing with little play is "
                        "worth checking; a player changing their mind is an ordinary explanation."),
            },
            "supporting_transaction_ids": self._supporting(fac),
            "technical": self._technical("playthrough", x, fac, [
                ("Deposits", "deposits", x["deposits"]), ("Wagers", "wagers", x["wagers"]),
                ("Payouts", "payouts", x["payouts"]), ("Withdrawals", "withdrawals", x["withdrawals"]),
                ("Wagered % of deposits", "wagered_pct", x["wagered_pct"]),
                ("Withdrawn % of deposits", "withdrawn_pct", x["withdrawn_pct"]),
            ], ["Wagered % is capped at 100%."], None),
            "evidence_ids": self.ids("metric:fundflow"),
        }


VALIDATED_FIELDS = ("headline", "change")
VALIDATED_EXPLAIN = ("usual", "changed")


def _verify(c: "_Case", f: dict, vocab) -> dict:
    """Run the finding's plain-language sentences through the report-claim validator.
    They may only state numbers, dates and names found in the evidence they cite
    (the finding's evidence plus the alert record, which holds the period lengths)."""
    from services.claims import build_index, validate_claim
    idx = build_index(c.items)
    cited = [*f["evidence_ids"], c.ev("alert")]
    texts = [f[k] for k in VALIDATED_FIELDS] + [f["explain"][k] for k in VALIDATED_EXPLAIN]
    failures: list[str] = []
    for t in texts:
        st, fl = validate_claim({"section": "triggering_indicators", "kind": "fact", "text": t, "evidence_ids": cited},
                                c.case["case_id"], idx, vocab)
        failures += [f"{t} — {x}" for x in fl]
    return {"status": "unverified" if failures else "verified", "failures": failures,
            "checked": len(texts), "method": "Same deterministic validator as report claims"}


def build(case: dict, items: list[dict], vocab=None) -> dict:
    c = _Case(case, items)
    factors = [i for i in c.items if i["type"] == "risk_factor"]
    out = [c.finding(f) for f in factors]
    if vocab is not None:
        for f in out:
            f["verification"] = _verify(c, f, vocab)
    out.sort(key=lambda f: (not f["triggered"], -f["points"]))
    snap = next((i["snapshot_id"] for i in c.items if i.get("snapshot_id")), None)
    return {
        "case_id": case["case_id"],
        "snapshot_id": snap,
        "periods": c.periods,
        "scope": c.scope,
        "previous_transaction_count": c.base_n,
        "previous_sufficient": c.base_ok,
        "findings": out,
    }


def for_case(case_id: str) -> dict:
    with connect() as con:
        case = repo.case_row(con, case_id)
        items = repo.evidence_items(con, case_id, include_queries=False)
        vocab = repo.vocab(con)
    return build(case, items, vocab)
