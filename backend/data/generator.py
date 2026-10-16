"""Synthetic world generator (v2). ALL DATA IS FICTIONAL.

Builds on synthetic_data_generator.py (the original behaviour model, preserved)
and adds the structure an investigation copilot needs:

* locations and named retailers, each with lottery terminals;
* lottery-terminal transactions that are **anonymous by default**: a purchase is
  linked to a player only when the (fictional) rewards card was scanned;
* account-based online gaming transactions (deposit / wager / payout /
  withdrawal) where the account holder *is* known;
* a network-wide "jackpot week" surge — legitimate seasonal activity that an
  investigator should be able to see as an alternative explanation;
* curated demo subjects with distinct investigative characteristics.

Ground-truth scenario labels are returned separately and never stored in the
tables the investigator-facing API reads.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta

import numpy as np
import pandas as pd

import config
from data.synthetic_data_generator import CITIES, SUSPICIOUS_SCENARIOS, _Gen

STORE_PREFIX = ["Maple", "Northern", "Lakeside", "Harbour", "Pinecrest", "Riverside", "Cedar", "Summit",
                "Birch", "Granite", "Willow", "Bayview", "Elm", "Highland", "Meadow", "Prospect"]
STORE_KIND = ["Variety", "Convenience", "Gas & Go", "Market", "Corner Store", "News & Gifts", "Grocer"]
GAMES = {"Lottery Ticket": "Weekly Draw (fictional)", "Instant Ticket": "Instant Scratch (fictional)",
         "Sports Wager": "Sports Pick (fictional)", "Prize Claim": "Prize claim"}
JACKPOT_DAYS = (2, 3)            # window day offsets of the network-wide jackpot surge
JACKPOT_MULT = 1.8

# Curated demo subjects: key -> (scenario injected, short investigator-facing title)
CURATED = [
    ("lottery_burst", "burst_frequency", "Unusual lottery purchase frequency"),
    ("multi_retailer", "multi_retailer_ambiguous", "Ambiguous multi-retailer pattern"),
    ("deposit_anomaly", "deposit_passthrough", "Account-based deposit anomaly"),
    ("incomplete_attribution", "incomplete_attribution", "Incomplete customer attribution"),
    ("high_volume_legit", "high_volume_legit", "High-volume player activity"),
    ("jackpot_week", "seasonal_jackpot", "Activity during the jackpot week"),
    ("shared_retailer", "shared_retailer", "Two players at the same retailer"),
    ("prize_claims", "repeated_amounts", "Repeated identical prize claims"),
]


def _stable_rng(*parts) -> np.random.Generator:
    h = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return np.random.default_rng(int(h[:16], 16))


class World(_Gen):
    """Extends the original generator with the v2 entities."""

    def __init__(self, seed: int):
        super().__init__(seed)
        self.seed = seed
        self.labels: list[dict] = []

    # ------------------------------------------------------------- entities
    def build_locations_retailers(self):
        locs = pd.DataFrame({"location_id": [f"LOC-{i + 1:02d}" for i in range(len(CITIES))],
                             "city": CITIES, "region": "Ontario"})
        city_to_loc = dict(zip(locs.city, locs.location_id))
        base = self.build_retailers(config.N_RETAILERS)
        names, used = [], set()
        for i, _ in enumerate(base.itertuples()):
            while True:
                n = f"{self.rng.choice(STORE_PREFIX)} {self.rng.choice(STORE_KIND)}"
                if n not in used:
                    break
                n = f"{n} #{i + 1}"
                if n not in used:
                    break
            used.add(n)
            names.append(n)
        retailers = pd.DataFrame({
            "retailer_id": base.retailer_id,
            "name": names,
            "location_id": base.location.map(city_to_loc),
            "city": base.location,
            "terminal_count": self.rng.integers(1, 3, size=len(base)),
        })
        return locs, retailers

    def build_customer(self, idx, retailers):
        """v1 behaviour model, but never in a home city with fewer than 3 retailers (v1 then fell back to
        retailers anywhere in the province, which made 'local' players look like travellers)."""
        for _ in range(20):
            cust = super().build_customer(idx, retailers)
            if len(retailers[retailers.location == cust["home"]]) >= 3:
                return cust
        return cust

    # ------------------------------------------------------- online accounts
    def account_activity(self, acc, start, days, rate=1.0, amt=1.0):
        rows, rng = [], self.rng
        for d in range(days):
            day = start + timedelta(days=d)
            if rng.random() < acc["deposit_p"] * rate:
                dep = round(float(rng.lognormal(np.log(acc["deposit_mean"] * amt), 0.35)), 2)
                t0 = day + timedelta(hours=float(np.clip(rng.normal(acc["hour"], 2.5), 6, 23.5)))
                rows.append(("deposit", t0, dep))
                n_w = int(rng.integers(3, 12))
                spent = 0.0
                for k in range(n_w):
                    w = round(min(dep - spent, float(rng.lognormal(np.log(dep / n_w), 0.3))), 2)
                    if w <= 0.5:
                        break
                    spent += w
                    rows.append(("wager", t0 + timedelta(minutes=5 + 7 * k), w))
                if rng.random() < 0.35:
                    rows.append(("payout", t0 + timedelta(minutes=90), round(spent * float(rng.uniform(0.3, 1.4)), 2)))
            if rng.random() < 0.03:
                rows.append(("withdrawal", day + timedelta(hours=20), round(float(rng.uniform(20, 120)), 2)))
        return rows

    def add_account_rows(self, acc, rows):
        for kind, ts, amount in rows:
            self.txn_counter += 1
            self.rows.append({
                "transaction_id": f"TXN-{self.txn_counter:07d}", "customer_id": acc["player_id"],
                "retailer_id": None, "timestamp": ts, "amount": round(max(1.0, amount), 2), "location": None,
                "transaction_type": kind, "channel": "online_account", "account_id": acc["account_id"],
            })

    # ------------------------------------------------------ anonymous sales
    def anonymous_sales(self, retailers, start, days, window_start):
        rng = self.rng
        for r in retailers.itertuples():
            base_rate = float(rng.uniform(3, 9))
            for d in range(days):
                day = start + timedelta(days=d)
                mult = JACKPOT_MULT if (day - window_start).days in JACKPOT_DAYS else 1.0
                for _ in range(rng.poisson(base_rate * mult)):
                    ts = day + timedelta(hours=float(np.clip(rng.normal(15, 3.5), 6, 23.6)))
                    ttype = rng.choice(["Lottery Ticket", "Instant Ticket", "Prize Claim"], p=[0.6, 0.35, 0.05])
                    self.txn_counter += 1
                    self.rows.append({
                        "transaction_id": f"TXN-{self.txn_counter:07d}", "customer_id": None,
                        "retailer_id": r.retailer_id, "timestamp": ts,
                        "amount": round(float(rng.lognormal(np.log(9), 0.6)), 2), "location": r.city,
                        "transaction_type": ttype, "channel": "lottery_terminal", "account_id": None,
                    })


def _local_window():
    total_days = config.HISTORY_DAYS + config.WINDOW_DAYS
    sim_start = (config.SIM_END - timedelta(days=total_days - 1)).replace(hour=0, minute=0, second=0)
    window_start = sim_start + timedelta(days=config.HISTORY_DAYS)
    return sim_start, window_start, total_days


def inject_v2(w: World, cust, scenario, window_start, retailers_df, rid_city, rng):
    """Scenarios added in v2 (the original ones are handled by _Gen.inject)."""
    w_rng_backup = w.rng
    w.rng = rng
    try:
        if scenario == "multi_retailer_ambiguous":
            # several different retailers in the home city, modest amounts: unusual spread, plausible errands
            pool = retailers_df[retailers_df.city == cust["home"]].retailer_id.tolist()
            for d in range(2, 6):
                day = window_start + timedelta(days=d)
                for k, rid in enumerate(rng.choice(pool, size=min(len(pool), 4), replace=False)):
                    ts = day.replace(hour=11) + timedelta(minutes=35 * k + float(rng.uniform(0, 20)))
                    w._add(cust, ts, w._normal_amount(cust, 1.3), rid, rid_city[rid], ttype="Lottery Ticket")
        elif scenario == "incomplete_attribution":
            # modest attributed rise; many anonymous purchases at the same retailers and times
            day = window_start + timedelta(days=4)
            for k in range(9):
                rid = cust["preferred"][k % len(cust["preferred"])]
                ts = day.replace(hour=19) + timedelta(minutes=6 * k)
                w._add(cust, ts, w._normal_amount(cust, 1.5), rid, rid_city[rid], ttype="Instant Ticket")
            for k in range(26):  # anonymous, same retailers, overlapping minutes — cannot be attributed
                rid = cust["preferred"][k % len(cust["preferred"])]
                w.txn_counter += 1
                w.rows.append({"transaction_id": f"TXN-{w.txn_counter:07d}", "customer_id": None, "retailer_id": rid,
                               "timestamp": day.replace(hour=19) + timedelta(minutes=2 * k + 1),
                               "amount": round(float(rng.uniform(18, 40)), 2), "location": rid_city[rid],
                               "transaction_type": "Instant Ticket", "channel": "lottery_terminal",
                               "account_id": None})
        elif scenario == "high_volume_legit":
            pass  # behaviour comes from the profile (very high, stable rate); see generate()
        elif scenario == "seasonal_jackpot":
            for d in JACKPOT_DAYS:
                day = window_start + timedelta(days=d)
                for k in range(int(rng.integers(9, 12))):
                    rid = cust["preferred"][0]
                    ts = day.replace(hour=17) + timedelta(minutes=14 * k + float(rng.uniform(0, 6)))
                    w._add(cust, ts, w._normal_amount(cust, 1.2), rid, rid_city[rid], ttype="Lottery Ticket")
        elif scenario == "shared_retailer":
            day = window_start + timedelta(days=3)
            rid = cust["preferred"][0]
            for k in range(12):
                ts = day.replace(hour=13) + timedelta(minutes=4 * k)
                w._add(cust, ts, w._normal_amount(cust, 2.0), rid, rid_city[rid], ttype="Instant Ticket")
        else:
            w.inject(cust, scenario, window_start, retailers_df.rename(columns={"city": "location"}), rid_city)
    finally:
        w.rng = w_rng_backup


def generate(seed: int = config.RANDOM_SEED, n_players: int = config.N_CUSTOMERS) -> dict:
    """Return a dict of DataFrames + ground-truth labels. Times are local (display timezone), naive."""
    w = World(seed)
    locations, retailers = w.build_locations_retailers()
    rid_city = dict(zip(retailers.retailer_id, retailers.city))
    sim_start, window_start, total_days = _local_window()

    players, accounts = [], []
    # --- population (same behaviour model as v1) -------------------------------------------
    for i in range(1, n_players + 1):
        cust = w.build_customer(i, retailers.rename(columns={"city": "location"}))
        cust["customer_id"] = f"PLY-{i:05d}"
        r = w.rng.random()
        if r < 0.10:
            cust["profile"], cust["scenario"] = "suspicious", str(w.rng.choice(SUSPICIOUS_SCENARIOS))
        elif r < 0.18:
            cust["profile"] = "busy_legitimate"
            cust["daily_rate"] *= w.rng.uniform(4, 8)
        elif r < 0.26:
            cust["profile"] = "benign_spike"
        players.append(cust)
        w.normal_activity(cust, sim_start, config.HISTORY_DAYS, rid_city)
        # review window, with the network-wide jackpot surge on JACKPOT_DAYS
        for d in range(config.WINDOW_DAYS):
            mult = JACKPOT_MULT if d in JACKPOT_DAYS else 1.0
            w.normal_activity(cust, window_start + timedelta(days=d), 1, rid_city, rate_mult=mult)
        if cust["profile"] == "suspicious":
            w.inject(cust, cust["scenario"], window_start, retailers.rename(columns={"city": "location"}), rid_city)
        elif cust["profile"] == "benign_spike":
            w.benign_spike(cust, window_start, rid_city)

    # --- curated demo subjects (stable regardless of population randomness) ------------------
    curated_ids = {}
    for j, (key, scenario, title) in enumerate(CURATED):
        rng = _stable_rng(seed, "curated", key)
        backup = w.rng
        w.rng = rng
        cust = w.build_customer(n_players + 1 + j, retailers.rename(columns={"city": "location"}))
        w.rng = backup
        cust["customer_id"] = f"PLY-{n_players + 1 + j:05d}"
        cust["profile"], cust["scenario"], cust["curated_key"] = "curated", scenario, key
        if scenario == "high_volume_legit":
            cust["daily_rate"] = 6.5
        if scenario == "shared_retailer":
            cust["daily_rate"] = 0.9
        players.append(cust)
        curated_ids[key] = cust["customer_id"]
        if scenario == "deposit_passthrough":
            continue  # online-only subject, built below
        backup = w.rng
        w.rng = rng
        w.normal_activity(cust, sim_start, config.HISTORY_DAYS, rid_city)
        for d in range(config.WINDOW_DAYS):
            w.normal_activity(cust, window_start + timedelta(days=d), 1, rid_city,
                              rate_mult=JACKPOT_MULT if d in JACKPOT_DAYS else 1.0)
        w.rng = backup
        inject_v2(w, cust, scenario, window_start, retailers, rid_city, rng)
    # the "shared retailer" partner: another curated-style player at the same retailer, same afternoon
    partner_rng = _stable_rng(seed, "curated", "shared_partner")
    sr = next(p for p in players if p.get("curated_key") == "shared_retailer")
    partner = dict(sr)
    partner.update({"customer_id": f"PLY-{n_players + 1 + len(CURATED):05d}", "profile": "curated_partner",
                    "scenario": "shared_retailer_partner", "curated_key": "shared_partner",
                    "amount_mean": sr["amount_mean"] * 1.1})
    players.append(partner)
    backup = w.rng
    w.rng = partner_rng
    w.normal_activity(partner, sim_start, config.HISTORY_DAYS + config.WINDOW_DAYS, rid_city)
    day = window_start + timedelta(days=3)
    for k in range(10):
        w._add(partner, day.replace(hour=13) + timedelta(minutes=4 * k + 2), w._normal_amount(partner, 2.0),
               sr["preferred"][0], rid_city[sr["preferred"][0]], ttype="Instant Ticket")
    w.rng = backup

    # mark v1 rows as rewards-card-attributed lottery purchases
    for row in w.rows:
        row.setdefault("channel", "lottery_terminal")
        row.setdefault("account_id", None)

    # --- online accounts ---------------------------------------------------------------------
    acct_rng = _stable_rng(seed, "accounts")
    backup = w.rng
    w.rng = acct_rng
    online_players = [p for p in players if p["profile"] in ("normal", "busy_legitimate")][:110]
    for k, p in enumerate(online_players):
        acc = {"player_id": p["customer_id"], "account_id": f"ACC-{10001 + k}",
               "deposit_p": float(acct_rng.uniform(0.15, 0.5)), "deposit_mean": float(acct_rng.lognormal(np.log(45), 0.4)),
               "hour": float(acct_rng.normal(20, 2))}
        accounts.append(acc)
        w.add_account_rows(acc, w.account_activity(acc, sim_start, total_days))
    # curated deposit anomaly: online-only player with a pass-through pattern in the window
    dp = next(p for p in players if p.get("curated_key") == "deposit_anomaly")
    acc = {"player_id": dp["customer_id"], "account_id": f"ACC-{10001 + len(online_players)}",
           "deposit_p": 0.55, "deposit_mean": 40.0, "hour": 20.0}
    accounts.append(acc)
    w.add_account_rows(acc, w.account_activity(acc, sim_start, config.HISTORY_DAYS))
    w.add_account_rows(acc, passthrough_rows(window_start, acct_rng))
    w.rng = backup

    # --- anonymous terminal sales -------------------------------------------------------------
    w.rng = _stable_rng(seed, "anonymous")
    w.anonymous_sales(retailers, sim_start, total_days, window_start)
    w.rng = backup

    tx = finalize_rows(w.rows, retailers, seed)
    player_df = pd.DataFrame([{
        "player_id": p["customer_id"], "home_location_id": dict(zip(locations.city, locations.location_id))[p["home"]],
        "has_rewards_card": 1, "has_online_account": int(any(a["player_id"] == p["customer_id"] for a in accounts)),
    } for p in players])
    account_df = pd.DataFrame([{"account_id": a["account_id"], "player_id": a["player_id"],
                                "opened_on": (sim_start - timedelta(days=200)).date().isoformat()} for a in accounts])
    labels = pd.DataFrame([{
        "player_id": p["customer_id"], "profile": p["profile"], "scenario": p["scenario"],
        "curated_key": p.get("curated_key", ""),
        "label_suspicious": int(p["profile"] == "suspicious" or p["scenario"] in (
            "burst_frequency", "deposit_passthrough", "repeated_amounts")),
    } for p in players])
    return {"transactions": tx, "players": player_df, "accounts": account_df, "retailers": retailers,
            "locations": locations, "events": events_frame(window_start), "labels": labels, "curated_ids": curated_ids,
            "sim_start": sim_start, "window_start": window_start}


def passthrough_rows(window_start, rng):
    rows, t = [], window_start + timedelta(days=3, hours=1, minutes=10)
    for amt in [500.0, 500.0, 750.0, 500.0, 900.0]:
        rows.append(("deposit", t, amt))
        t += timedelta(minutes=float(rng.uniform(6, 14)))
    rows += [("wager", t + timedelta(minutes=3), 20.0), ("wager", t + timedelta(minutes=9), 15.0),
             ("payout", t + timedelta(minutes=14), 12.0),
             ("withdrawal", t + timedelta(hours=2, minutes=5), 3000.0)]
    return rows


def events_frame(window_start):
    return pd.DataFrame([{
        "event_id": "EVT-JACKPOT-01", "name": "Jackpot draw week (fictional)",
        "start_local": (window_start + timedelta(days=JACKPOT_DAYS[0])).date().isoformat(),
        "end_local": (window_start + timedelta(days=JACKPOT_DAYS[-1])).date().isoformat(),
        "description": "Large advertised jackpot; network-wide lottery sales rise on these days.",
    }])


def finalize_rows(rows, retailers, seed) -> pd.DataFrame:
    for row in rows:
        row.setdefault("channel", "lottery_terminal")
        row.setdefault("account_id", None)
    tx = pd.DataFrame(rows)
    tx = tx.rename(columns={"customer_id": "player_id"})
    tx["timestamp"] = pd.to_datetime(tx["timestamp"]).dt.floor("s")
    tx = tx[tx.timestamp <= config.SIM_END].sort_values(["timestamp", "transaction_id"]).reset_index(drop=True)
    tx["attribution"] = np.where(tx.channel == "online_account", "account_holder",
                                 np.where(tx.player_id.notna(), "rewards_card_scan", "none"))
    tx["game"] = tx.transaction_type.map(GAMES).fillna("Online play (fictional)")
    term = {r.retailer_id: int(r.terminal_count) for r in retailers.itertuples()}
    trng = _stable_rng(seed, "terminals")
    tx["terminal_id"] = [
        f"TRM-{rid[4:]}-{int(trng.integers(1, term[rid] + 1))}" if isinstance(rid, str) else None
        for rid in tx.retailer_id]
    tx["ticket_id"] = [f"TKT-{int(hashlib.md5(f'{t}|{seed}'.encode()).hexdigest()[:8], 16) % 10**9:09d}"
                       if c == "lottery_terminal" else None for t, c in zip(tx.transaction_id, tx.channel)]
    tx["location_id"] = tx.retailer_id.map(dict(zip(retailers.retailer_id, retailers.location_id)))
    tx = tx.drop(columns=["location"])
    tx["is_synthetic"] = 1
    return tx


def scenario_subject(key: str, run_no: int, retailers: pd.DataFrame, seed: int = config.RANDOM_SEED) -> dict:
    """Scenario Lab: a brand-new synthetic subject for one curated scenario.
    Transaction IDs are temporary (TMP-…); the caller assigns permanent IDs."""
    scenario = {k: s_ for k, s_, _ in CURATED}[key]
    rng = _stable_rng(seed, "lab", key, run_no)
    w = World(seed)
    w.rng = rng
    rid_city = dict(zip(retailers.retailer_id, retailers.city))
    sim_start, window_start, total_days = _local_window()
    cust = w.build_customer(0, retailers.rename(columns={"city": "location"}))
    cust["customer_id"] = "PLY-NEW"
    if scenario == "high_volume_legit":
        cust["daily_rate"] = 6.5
    if scenario == "shared_retailer":
        cust["daily_rate"] = 0.9
    account = None
    if scenario == "deposit_passthrough":
        account = {"player_id": "PLY-NEW", "account_id": "ACC-NEW", "deposit_p": 0.55, "deposit_mean": 40.0, "hour": 20.0}
        w.add_account_rows(account, w.account_activity(account, sim_start, config.HISTORY_DAYS))
        w.add_account_rows(account, passthrough_rows(window_start, rng))
    else:
        w.normal_activity(cust, sim_start, config.HISTORY_DAYS, rid_city)
        for d in range(config.WINDOW_DAYS):
            w.normal_activity(cust, window_start + timedelta(days=d), 1, rid_city,
                              rate_mult=JACKPOT_MULT if d in JACKPOT_DAYS else 1.0)
        inject_v2(w, cust, scenario, window_start, retailers, rid_city, rng)
    tx = finalize_rows(w.rows, retailers, seed + run_no)
    tx = tx[tx.timestamp >= sim_start]
    return {"transactions": tx, "home_city": cust["home"], "account": account, "scenario": scenario}


if __name__ == "__main__":
    out = generate()
    tx = out["transactions"]
    print(len(tx), "transactions;", tx.channel.value_counts().to_dict(), tx.attribution.value_counts().to_dict())
    print(out["curated_ids"])
