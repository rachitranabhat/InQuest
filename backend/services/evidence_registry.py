"""Evidence registry: turns a case's raw records into citable, immutable evidence items.

Every item has
  evidence_id  stable ID (EV-000123), never reused
  type         transaction | alert | risk_factor | metric | baseline | comparison |
               aggregate_retailer | aggregate_day | retailer | location | sequence |
               relationship | co_presence | context_event | limitation | query_result
  source_ids   original record IDs it is computed from (provenance)
  entities     IDs and names it is *about* — what a claim citing it may name
  computed     the numbers/dates a claim citing it may state
  provenance   how it was computed (rule, period, query)

A snapshot hash over all items of a case is stored so reports and reviewer
actions can record exactly which evidence they were based on.
"""
from __future__ import annotations

import hashlib
import sqlite3

import pandas as pd

import config
from database.db import dumps, next_ids
from detection.feature_engineering import NIGHT_HOURS
from timeutil import utc_now_iso

CO_PRESENCE_MINUTES = 30


def _fmt_ts(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M")


def _r2(x) -> float:
    return round(float(x), 2)


class _Collector:
    def __init__(self, case_id: str):
        self.case_id = case_id
        self.items: list[dict] = []

    def add(self, type_, title, summary, source_ids=(), entities=(), computed=None, provenance=None, key=None):
        self.items.append({
            "key": key or f"{type_}:{len(self.items)}",
            "type": type_, "title": title, "summary": summary,
            "source_ids": sorted(set(source_ids)), "entities": sorted({str(e) for e in entities if e}),
            "computed": computed or {}, "provenance": provenance or {},
        })
        return self.items[-1]


def build_items(case: dict, ctx: dict) -> list[dict]:
    """Pure function: compute evidence items for one case. ``ctx`` (all local times):
      window_tx, baseline_tx  subject's transactions (all types for accounts)
      retailers               DataFrame retailer_id,name,city,location_id,terminal_count
      locations               DataFrame location_id,city
      anon_window_tx          anonymous terminal sales in the window at the subject's retailers
      other_attributed_tx     other players' attributed sales in the window at the subject's retailers
      events                  DataFrame of calendar events
      network_daily           Series date -> network-wide lottery transaction count
    """
    c = _Collector(case["case_id"])
    f, factors = case["features"], case["factors"]
    win: pd.DataFrame = ctx["window_tx"].sort_values("timestamp")
    base: pd.DataFrame = ctx["baseline_tx"]
    rmeta = ctx["retailers"].set_index("retailer_id")
    is_account = case["channel"] == "online_account"
    subject = case["subject_id"]
    win_ids = win.transaction_id.tolist()

    def rname(rid):
        return rmeta.loc[rid, "name"] if isinstance(rid, str) and rid in rmeta.index else None

    def rcity(rid):
        return rmeta.loc[rid, "city"] if isinstance(rid, str) and rid in rmeta.index else None

    # ---------------------------------------------------------------- transactions
    for r in win.itertuples():
        ts = pd.Timestamp(r.timestamp)
        comp = {"amount": _r2(r.amount), "timestamp_local": _fmt_ts(ts), "date": ts.strftime("%Y-%m-%d"),
                "time": ts.strftime("%H:%M"), "hour": int(ts.hour), "transaction_type": r.transaction_type,
                "channel": r.channel, "attribution": r.attribution}
        ents = [r.transaction_id, subject, case.get("player_id")]
        if isinstance(r.retailer_id, str):
            comp.update({"retailer_id": r.retailer_id, "retailer_name": rname(r.retailer_id), "city": rcity(r.retailer_id),
                         "terminal_id": r.terminal_id, "ticket_id": r.ticket_id})
            ents += [r.retailer_id, rname(r.retailer_id), rcity(r.retailer_id), r.location_id, r.terminal_id, r.ticket_id]
        if isinstance(r.account_id, str):
            comp["account_id"] = r.account_id
            ents.append(r.account_id)
        where = f" at {rname(r.retailer_id)} ({rcity(r.retailer_id)})" if isinstance(r.retailer_id, str) else ""
        c.add("transaction", f"{r.transaction_id} · {r.transaction_type}",
              f"{r.transaction_type} of ${r.amount:,.2f} on {comp['timestamp_local']}{where}",
              [r.transaction_id], ents, comp, {"table": "transactions", "record": r.transaction_id},
              key=f"txn:{r.transaction_id}")

    # ---------------------------------------------------------------------- alert
    c.add("alert", f"Alert {case['alert_id']} · {case['alert_type']}",
          f"{case['alert_source']} raised a {case['alert_type'].lower()} alert at {_fmt_ts(case['triggered_at_local'])} "
          f"with a prototype alert score of {case['risk_score']:.1f} / 100 (not a fraud probability).",
          case["alert_transaction_ids"], [case["alert_id"], case["case_id"], subject],
          {"alert_score": case["risk_score"], "score_band": case["risk_level"], "alert_type": case["alert_type"],
           "triggered_at_local": _fmt_ts(case["triggered_at_local"]), "date": pd.Timestamp(case["triggered_at_local"]).strftime("%Y-%m-%d"),
           "rules_fired": case["rules_fired"], "indicators_fired": case["triggered_count"],
           "window_start": pd.Timestamp(case["window_start_local"]).strftime("%Y-%m-%d"),
           "window_end": pd.Timestamp(case["window_end_local"]).strftime("%Y-%m-%d"),
           "window_days": config.WINDOW_DAYS, "baseline_days": config.HISTORY_DAYS},
          {"source": case["alert_source"], "rules": case["rules_fired"]}, key="alert")

    # ---------------------------------------------------------------- risk factors
    for k, fac in factors.items():
        comp = {"points": fac["points"], "max_points": fac["max_points"], "share_pct": round(fac["share"] * 100, 1),
                "triggered": bool(fac["triggered"])}
        comp.update(_factor_values(k, f, fac))
        ents = [subject]
        if k == "location":
            ents += list(f.get("new_locations") or []) + list(f.get("new_retailers") or [])
            ents += [rname(x) for x in (f.get("new_retailers") or [])]
        c.add("risk_factor", f"{fac['label']} · {fac['points']:.1f} / {fac['max_points']} pts",
              f"{fac['measurement']}. Rule: {fac['rule']}.", fac["transactions"], ents, comp,
              {"rule": fac["rule"], "engine": "detection/risk_scoring.py"}, key=f"factor:{k}")

    # -------------------------------------------------------------- window metric
    scoped = win[win.transaction_type == "deposit"] if is_account else win
    days_active = int(scoped.timestamp.dt.date.nunique()) if len(scoped) else 0
    metric = {"transaction_count": int(len(scoped)), "total_amount": _r2(scoped.amount.sum()),
              "average_amount": _r2(scoped.amount.mean()) if len(scoped) else 0.0,
              "max_amount": _r2(scoped.amount.max()) if len(scoped) else 0.0,
              "days_active": days_active, "window_days": config.WINDOW_DAYS,
              "first_local": _fmt_ts(scoped.timestamp.min()) if len(scoped) else None,
              "last_local": _fmt_ts(scoped.timestamp.max()) if len(scoped) else None,
              "night_transactions": int(scoped.timestamp.dt.hour.isin(NIGHT_HOURS).sum())}
    if not is_account:
        metric.update({"unique_retailers": int(scoped.retailer_id.nunique()),
                       "unique_cities": int(scoped.retailer_id.map(rcity).nunique())})
    label = "deposits" if is_account else "attributed purchases"
    c.add("metric", f"Review-window totals ({label})",
          f"{metric['transaction_count']} {label} totalling ${metric['total_amount']:,.2f} between "
          f"{metric['first_local']} and {metric['last_local']}.", scoped.transaction_id.tolist(), [subject], metric,
          {"period": f"{config.WINDOW_DAYS}-day review window", "scope": label}, key="metric:window")
    if is_account:
        by = win.groupby("transaction_type").amount.agg(["count", "sum"])
        flow = {f"{t}_count": int(by.loc[t, "count"]) if t in by.index else 0 for t in ("deposit", "wager", "payout", "withdrawal")}
        flow.update({f"{t}_total": _r2(by.loc[t, "sum"]) if t in by.index else 0.0 for t in ("deposit", "wager", "payout", "withdrawal")})
        dep = flow["deposit_total"]
        flow["wagered_pct_of_deposits"] = round(min(100.0, flow["wager_total"] / dep * 100), 1) if dep else None
        flow["withdrawn_pct_of_deposits"] = round(flow["withdrawal_total"] / dep * 100, 1) if dep else None
        c.add("metric", "Account fund flow in the review window",
              f"Deposits ${flow['deposit_total']:,.2f} ({flow['deposit_count']}), wagers ${flow['wager_total']:,.2f} "
              f"({flow['wager_count']}), payouts ${flow['payout_total']:,.2f}, withdrawals ${flow['withdrawal_total']:,.2f} "
              f"({flow['withdrawal_count']}).", win_ids, [subject], flow,
              {"period": f"{config.WINDOW_DAYS}-day review window"}, key="metric:fundflow")

    # ------------------------------------------------------------ baseline metric
    bscoped = base[base.transaction_type == "deposit"] if is_account else base
    bcomp = {"baseline_transaction_count": int(len(bscoped)), "baseline_days": config.HISTORY_DAYS,
             "transactions_per_day": f["hist_transactions_per_day"], "average_amount": f["hist_average_amount"],
             "p95_amount": f["hist_p95_amount"], "typical_week_total": f["hist_weekly_total"],
             "busiest_hour_average": f["hist_peak_hour_avg"], "night_share_pct": round(f["hist_night_ratio"] * 100, 1),
             "sufficient": bool(case.get("baseline_sufficient", True))}
    if not is_account:
        bcomp["usual_cities"] = f["home_locations"]
    c.add("baseline", f"Historical baseline ({config.HISTORY_DAYS} days before the window)",
          f"{bcomp['baseline_transaction_count']} {label} in the baseline period, {bcomp['transactions_per_day']}/day, "
          f"average ${bcomp['average_amount']:,.2f}.", [], [subject] + bcomp.get("usual_cities", []), bcomp,
          {"period": f"{config.HISTORY_DAYS} days before the review window",
           "note": "Aggregated from the subject's own earlier records; individual baseline records are not listed."},
          key="baseline")

    # --------------------------------------------------------------- comparisons
    comps = [
        ("per_day", "Transactions per day", f["hist_transactions_per_day"], f["transactions_per_day"]),
        ("busiest_hour", "Busiest hour (transactions)", f["hist_peak_hour_avg"], f["peak_hour_transactions"]),
        ("avg_amount", "Average amount ($)", f["hist_average_amount"], f["average_transaction_amount"]),
        ("week_total", "Total for a week ($)", f["hist_weekly_total"], f["total_amount"]),
        ("night_share", "Share at night, 12–5 am (%)", round(f["hist_night_ratio"] * 100, 1), round(f["night_transaction_ratio"] * 100, 1)),
    ]
    if not is_account:
        comps += [("cities", "Cities", f["hist_unique_locations"], f["unique_locations"]),
                  ("retailers", "Retailers", f["hist_unique_retailers"], f["unique_retailers"])]
    for key, name, h, cur in comps:
        ratio = round(cur / h, 2) if h else None
        change = round((cur - h) / h * 100, 1) if h else None
        c.add("comparison", f"{name}: baseline vs. review window",
              f"{name}: {h:g} in a typical period vs. {cur:g} in the review window"
              + (f" ({ratio:g}×)" if ratio is not None else " (no baseline activity)"),
              scoped.transaction_id.tolist() if key in ("per_day", "week_total", "avg_amount") else [],
              [subject], {"metric": name, "baseline": h, "current": cur, "ratio": ratio, "change_pct": change},
              {"baseline_period_days": config.HISTORY_DAYS, "window_days": config.WINDOW_DAYS}, key=f"cmp:{key}")

    # ------------------------------------------------------- per-retailer / city
    if not is_account and len(win):
        base_rets = set(base.retailer_id.dropna())
        g = win.groupby("retailer_id")
        total = len(win)
        for rid, grp in sorted(g, key=lambda kv: (-len(kv[1]), kv[0])):
            comp = {"retailer_id": rid, "retailer_name": rname(rid), "city": rcity(rid),
                    "transaction_count": int(len(grp)), "total_amount": _r2(grp.amount.sum()),
                    "share_pct": round(len(grp) / total * 100, 1),
                    "first_local": _fmt_ts(grp.timestamp.min()), "last_local": _fmt_ts(grp.timestamp.max()),
                    "new_for_subject": rid not in base_rets}
            c.add("aggregate_retailer", f"{rname(rid)} ({rid})",
                  f"{comp['transaction_count']} attributed purchases totalling ${comp['total_amount']:,.2f} at {rname(rid)}, "
                  f"{rcity(rid)} ({comp['share_pct']:g}% of the window)" + (" — not used in the baseline" if comp["new_for_subject"] else ""),
                  grp.transaction_id.tolist(), [rid, rname(rid), rcity(rid), subject], comp,
                  {"group_by": "retailer_id", "period": "review window"}, key=f"agg_ret:{rid}")
            m = rmeta.loc[rid]
            c.add("retailer", f"Retailer {m['name']}", f"{m['name']} ({rid}) in {m['city']}, {int(m['terminal_count'])} terminal(s).",
                  [rid], [rid, m["name"], m["city"], m["location_id"]],
                  {"retailer_id": rid, "retailer_name": m["name"], "city": m["city"], "location_id": m["location_id"],
                   "terminal_count": int(m["terminal_count"])}, {"table": "retailers"}, key=f"ret:{rid}")
        for city, grp in win.groupby(win.retailer_id.map(rcity)):
            loc = ctx["locations"].set_index("city").loc[city, "location_id"]
            c.add("location", f"{city} ({loc})",
                  f"{len(grp)} attributed purchases in {city}" + ("" if city in f["home_locations"] else " — not in the baseline"),
                  grp.transaction_id.tolist(), [city, loc], {"city": city, "location_id": loc,
                  "transaction_count": int(len(grp)), "total_amount": _r2(grp.amount.sum()),
                  "in_baseline": city in f["home_locations"]}, {"group_by": "city"}, key=f"loc:{city}")

    # ------------------------------------------------------------------- per day
    for day, grp in scoped.groupby(scoped.timestamp.dt.strftime("%Y-%m-%d")):
        comp = {"date": day, "transaction_count": int(len(grp)), "total_amount": _r2(grp.amount.sum()),
                "first_time": grp.timestamp.min().strftime("%H:%M"), "last_time": grp.timestamp.max().strftime("%H:%M")}
        if not is_account:
            comp["retailer_count"] = int(grp.retailer_id.nunique())
        c.add("aggregate_day", f"Activity on {pd.Timestamp(day).strftime('%a %b %d')}",
              f"{comp['transaction_count']} {label} totalling ${comp['total_amount']:,.2f} on {day}, "
              f"{comp['first_time']}–{comp['last_time']}.", grp.transaction_id.tolist(), [subject], comp,
              {"group_by": "local date"}, key=f"day:{day}")

    # --------------------------------------------------------------- sequences
    if f.get("peak_hour_start"):
        ps, pe = pd.Timestamp(f["peak_hour_start"]), pd.Timestamp(f["peak_hour_end"])
        burst = scoped[(scoped.timestamp >= ps) & (scoped.timestamp <= pe)]
        if len(burst) >= 3:
            comp = {"transaction_count": int(len(burst)), "total_amount": _r2(burst.amount.sum()),
                    "start_local": _fmt_ts(ps), "end_local": _fmt_ts(pe), "date": ps.strftime("%Y-%m-%d"),
                    "start_time": ps.strftime("%H:%M"), "end_time": pe.strftime("%H:%M"),
                    "minutes": int((pe - ps).total_seconds() // 60)}
            ents = [subject]
            if not is_account:
                comp["retailer_count"] = int(burst.retailer_id.nunique())
                ents += [x for rid in burst.retailer_id.unique() for x in (rid, rname(rid), rcity(rid))]
            c.add("sequence", f"Busiest 60 minutes: {comp['transaction_count']} transactions",
                  f"{comp['transaction_count']} {label} between {comp['start_local']} and {comp['end_time']} "
                  f"(${comp['total_amount']:,.2f}).", burst.transaction_id.tolist(), ents, comp,
                  {"rule": "max transactions in any rolling 60-minute window"}, key="seq:peak")

    # ----------------------------------------------------------- relationships
    if is_account:
        c.add("relationship", f"Account {subject} belongs to {case['player_id']}",
              f"Verified in the synthetic account records: {subject} is held by player {case['player_id']}.",
              [subject], [subject, case["player_id"]], {"relationship": "account_holder", "verified": True},
              {"table": "accounts"}, key="rel:account")
    else:
        n_att = int((win.attribution == "rewards_card_scan").sum())
        c.add("relationship", f"Purchases linked to {subject} by rewards-card scans",
              f"{n_att} purchases in the window were linked to {subject} because the player's rewards card was scanned. "
              "Purchases without a scan are anonymous and are not linked to anyone.",
              win_ids, [subject], {"relationship": "rewards_card_attribution", "verified": True, "attributed_count": n_att},
              {"table": "transactions", "field": "attribution"}, key="rel:attribution")

    # ---------------------------------------------------- co-presence (not a link)
    other = ctx.get("other_attributed_tx")
    if not is_account and other is not None and len(other) and len(win):
        hits = []
        for r in win.itertuples():
            near = other[(other.retailer_id == r.retailer_id) &
                         ((other.timestamp - r.timestamp).abs() <= pd.Timedelta(minutes=CO_PRESENCE_MINUTES))]
            hits.append(near)
        near_all = pd.concat(hits).drop_duplicates("transaction_id") if hits else other.iloc[0:0]
        if len(near_all):
            for pid, grp in near_all.groupby("player_id"):
                if len(grp) < 3:
                    continue
                rids = sorted(grp.retailer_id.unique())
                c.add("co_presence", f"{pid} also purchased at the same retailer(s) nearby in time",
                      f"{len(grp)} purchases attributed to {pid} at {', '.join(rname(x) for x in rids)} within "
                      f"{CO_PRESENCE_MINUTES} minutes of {subject}'s purchases. Being at the same retailer at similar "
                      "times is NOT evidence of any relationship between the two players.",
                      grp.transaction_id.tolist(), [pid] + rids + [rname(x) for x in rids],
                      {"other_player_id": pid, "transaction_count": int(len(grp)), "window_minutes": CO_PRESENCE_MINUTES,
                       "verified_relationship": False},
                      {"rule": f"same retailer, ±{CO_PRESENCE_MINUTES} min"}, key=f"co:{pid}")

    # --------------------------------------------------------- context events
    nd = ctx.get("network_daily")
    for e in ctx["events"].itertuples():
        if not (e.start_local <= pd.Timestamp(case["window_end_local"]).strftime("%Y-%m-%d")
                and e.end_local >= pd.Timestamp(case["window_start_local"]).strftime("%Y-%m-%d")):
            continue
        ev_days = pd.date_range(e.start_local, e.end_local).strftime("%Y-%m-%d")
        sub_ev = scoped[scoped.timestamp.dt.strftime("%Y-%m-%d").isin(ev_days)]
        comp = {"event_name": e.name, "start": e.start_local, "end": e.end_local,
                "subject_transactions_during_event": int(len(sub_ev)),
                "subject_share_pct": round(len(sub_ev) / len(scoped) * 100, 1) if len(scoped) else 0.0}
        if nd is not None and not is_account:
            base_days = [d for d in nd.index if d < pd.Timestamp(case["window_start_local"]).strftime("%Y-%m-%d")]
            during = [nd[d] for d in ev_days if d in nd.index]
            if base_days and during:
                b = float(nd[base_days].mean())
                comp.update({"network_daily_baseline": round(b, 1), "network_daily_during_event": round(sum(during) / len(during), 1),
                             "network_ratio": round(sum(during) / len(during) / b, 2)})
        c.add("context_event", f"{e.name}, {e.start_local} to {e.end_local}",
              f"{e.description}" + (f" Network-wide terminal sales averaged {comp['network_daily_during_event']:g}/day on those days "
                                    f"vs. {comp['network_daily_baseline']:g}/day in the baseline ({comp['network_ratio']:g}×)."
                                    if "network_ratio" in comp else "")
              + f" {comp['subject_transactions_during_event']} of this subject's window transactions fall on those days.",
              sub_ev.transaction_id.tolist(), [e.event_id, e.name], comp,
              {"table": "events + transactions (network-wide daily counts)"}, key=f"event:{e.event_id}")

    # ------------------------------------------------------------- limitations
    def limitation(key, title, summary, comp, case_specific):
        comp = {**comp, "case_specific": case_specific, "absence_is_not_proof": True}
        c.add("limitation", title, summary, comp.pop("_sources", []), [subject], comp,
              {"kind": "data availability"}, key=f"lim:{key}")

    anon = ctx.get("anon_window_tx")
    if not is_account and anon is not None and len(win):
        near = []
        for r in win.itertuples():
            near.append(anon[(anon.retailer_id == r.retailer_id) &
                             ((anon.timestamp - r.timestamp).abs() <= pd.Timedelta(minutes=CO_PRESENCE_MINUTES))])
        near_df = pd.concat(near).drop_duplicates("transaction_id") if near else anon.iloc[0:0]
        n_near = int(len(near_df))
        limitation("unattributed", f"{n_near} nearby purchases cannot be attributed",
                   f"{n_near} anonymous purchases (no rewards-card scan) were made at the same retailers within "
                   f"{CO_PRESENCE_MINUTES} minutes of this player's purchases. Who made them is unknown; they are "
                   "neither evidence for nor against this player's involvement.",
                   {"anonymous_nearby_count": n_near, "window_minutes": CO_PRESENCE_MINUTES,
                    "attributed_count": int(len(win)), "_sources": near_df.transaction_id.tolist()},
                   case_specific=n_near >= max(5, len(win) // 2))
    if not case.get("baseline_sufficient", True):
        limitation("baseline", "Historical baseline is too short",
                   f"Only {bcomp['baseline_transaction_count']} baseline transactions exist, so comparisons with "
                   "history were not scored.", {"baseline_transaction_count": bcomp["baseline_transaction_count"]}, True)
    if is_account:
        limitation("device", "No device, IP or geolocation data",
                   "The synthetic dataset has no device, IP address or geolocation records for online sessions.", {}, False)
        limitation("payment", "No payment-instrument details",
                   "Funding sources and destination accounts for deposits and withdrawals are not in the dataset.", {}, False)
    else:
        limitation("retailer_records", "No retailer-side records",
                   "No retailer statements, staff logs or video are available; terminal records are the only source.", {}, False)
    limitation("identity", "No identity or intent information",
               "The records show transactions only. They do not show who physically made a purchase, why, or "
               "whether any rule or law was broken.", {}, False)
    return c.items


def _factor_values(k: str, f: dict, fac: dict) -> dict:
    if k == "frequency":
        return {"peak_hour_transactions": f["peak_hour_transactions"], "baseline_busiest_hour": f["hist_peak_hour_avg"],
                "peak_hour_ratio": f["peak_hour_ratio"], "transactions_per_day": f["transactions_per_day"],
                "baseline_per_day": f["hist_transactions_per_day"], "frequency_ratio": f["frequency_ratio"]}
    if k == "value":
        return {"average_amount": f["average_transaction_amount"], "baseline_average": f["hist_average_amount"],
                "max_amount": f["max_transaction_amount"], "baseline_p95": f["hist_p95_amount"],
                "avg_ratio": f["avg_amount_ratio"], "max_vs_p95": f["max_vs_hist_p95"]}
    if k == "location":
        return {"new_city_count": f["new_location_count"], "new_cities": f["new_locations"],
                "new_retailer_count": f["new_retailer_count"], "unique_cities": f["unique_locations"],
                "unique_retailers": f["unique_retailers"]}
    if k == "timing":
        return {"night_transactions": f["night_transaction_count"], "night_share_pct": round(f["night_transaction_ratio"] * 100, 1),
                "baseline_night_share_pct": round(f["hist_night_ratio"] * 100, 1)}
    if k == "historical":
        return {"window_total": f["total_amount"], "typical_week_total": f["hist_weekly_total"], "spend_ratio": f["spend_ratio"]}
    if k == "pattern":
        return {"rapid_pairs": f["rapid_pairs"], "repeated_amount_count": f["repeated_amount_count"],
                "repeated_amount": f["repeated_amount_value"]}
    if k == "playthrough":
        v = fac.get("values", {})
        return {"deposits": v.get("deposits"), "wagers": v.get("wagers"), "withdrawals": v.get("withdrawals"),
                "payouts": v.get("payouts"), "wagered_pct": round((v.get("played_ratio") or 0) * 100, 1),
                "withdrawn_pct": round((v.get("withdrawn_ratio") or 0) * 100, 1)}
    return {}


def snapshot_hash(items: list[dict]) -> str:
    canon = [{k: it[k] for k in ("evidence_id", "type", "title", "source_ids", "entities", "computed")}
             for it in sorted(items, key=lambda x: x["evidence_id"])]
    return hashlib.sha256(dumps(canon).encode()).hexdigest()


def persist_items(con: sqlite3.Connection, case_id: str, items: list[dict]) -> tuple[str, str]:
    """Insert items + a snapshot (call inside a transaction). Returns (snapshot_id, hash)."""
    ids = next_ids(con, "EV", len(items))
    now = utc_now_iso()
    for it, eid in zip(items, ids):
        it["evidence_id"] = eid
    h = snapshot_hash(items)
    snap = next_ids(con, "SNP", 1)[0]
    con.execute("INSERT INTO evidence_snapshots VALUES (?,?,?,?,?)", (snap, case_id, h, len(items), now))
    con.executemany(
        "INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(it["evidence_id"], case_id, snap, it["type"], it["title"], it["summary"], dumps(it["source_ids"]),
          dumps(it["entities"]), dumps(it["computed"]), dumps({**it["provenance"], "key": it["key"]}), now) for it in items])
    con.execute("UPDATE cases SET current_snapshot_id = ? WHERE case_id = ?", (snap, case_id))
    return snap, h


def completeness(items: list[dict]) -> str:
    specific = [i for i in items if i["type"] == "limitation" and i["computed"].get("case_specific")]
    if not specific:
        return "Complete"
    return "Limited" if any(i["key"] == "lim:baseline" for i in specific) or len(specific) >= 2 else "Partial"
