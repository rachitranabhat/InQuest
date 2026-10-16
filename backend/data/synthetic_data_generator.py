"""Synthetic transaction generator.

ALL DATA PRODUCED HERE IS FICTIONAL. Customer IDs, retailer IDs and behaviour are
randomly generated. City names are used only as generic location labels.

Behaviour model
---------------
* Every customer has a stable baseline profile (home city, 1-3 preferred
  retailers, typical daily activity rate, typical amount, typical hours).
* Most customers behave normally for the whole period.
* Some customers are "busy but legitimate" (high volume, but consistent with
  their own history) or have a single benign spike (e.g. a big-jackpot night).
  These make the problem realistic: high volume alone is not suspicious.
* A minority receive an injected *scenario* during the final review window
  (burst frequency, high value, multi-location, night activity, repeated
  amounts, behaviour shift, or a combination).

The scenario label is written to ``customers_ground_truth.csv``. It is used only
to train/evaluate the experimental ML model - the rule-based detection engine
never sees it.
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

CITIES = [
    "Toronto", "Ottawa", "Mississauga", "Hamilton", "London", "Windsor",
    "Kingston", "Sudbury", "Sault Ste. Marie", "Thunder Bay", "Barrie",
    "Kitchener", "Niagara Falls", "Peterborough", "Timmins",
]
TXN_TYPES = ["Lottery Ticket", "Instant Ticket", "Sports Wager", "Prize Claim"]

SUSPICIOUS_SCENARIOS = [
    "burst_frequency",
    "high_value",
    "multi_location",
    "night_activity",
    "repeated_amounts",
    "behaviour_shift",
    "combined",
]


class _Gen:
    def __init__(self, seed: int):
        self.rng = np.random.default_rng(seed)
        self.rows: list[dict] = []
        self.txn_counter = 0

    # ------------------------------------------------------------------ setup
    def build_retailers(self, n: int) -> pd.DataFrame:
        cities = self.rng.choice(CITIES, size=n, p=self._city_weights())
        return pd.DataFrame(
            {"retailer_id": [f"RTL-{i:04d}" for i in range(1, n + 1)], "location": cities}
        )

    def _city_weights(self) -> np.ndarray:
        w = np.array([10, 6, 6, 4, 4, 3, 2, 2, 2, 2, 2, 3, 2, 2, 1], dtype=float)
        return w / w.sum()

    def build_customer(self, idx: int, retailers: pd.DataFrame) -> dict:
        rng = self.rng
        home = rng.choice(CITIES, p=self._city_weights())
        local = retailers[retailers.location == home].retailer_id.tolist()
        if not local:
            local = retailers.retailer_id.tolist()
        k = int(min(len(local), rng.integers(1, 4)))
        preferred = list(rng.choice(local, size=k, replace=False))
        type_w = rng.dirichlet([6, 4, 2, 0.6])
        return {
            "customer_id": f"CUST-{idx:05d}",
            "home": home,
            "preferred": preferred,
            "local": local,
            "daily_rate": float(rng.gamma(2.0, 0.55)) + 0.15,   # ~1.2 txns/day avg
            "amount_mean": float(rng.lognormal(np.log(12), 0.55)),
            "hour_mean": float(rng.normal(15, 2.5)),
            "hour_sd": float(rng.uniform(1.5, 3.5)),
            "type_w": type_w,
            "profile": "normal",
            "scenario": "",
        }

    # ------------------------------------------------------------ primitives
    def _add(self, cust, ts, amount, retailer, location, ttype=None):
        self.txn_counter += 1
        if ttype is None:
            ttype = self.rng.choice(TXN_TYPES, p=cust["type_w"])
        self.rows.append(
            {
                "transaction_id": f"TXN-{self.txn_counter:07d}",
                "customer_id": cust["customer_id"],
                "retailer_id": retailer,
                "timestamp": ts,
                "amount": round(float(max(1.0, amount)), 2),
                "location": location,
                "transaction_type": ttype,
            }
        )

    def _normal_amount(self, cust, scale=1.0):
        return self.rng.lognormal(np.log(cust["amount_mean"] * scale), 0.45)

    def _normal_hour(self, cust):
        if self.rng.random() < 0.02:  # occasional late-night purchase
            return self.rng.uniform(0, 5)
        return float(np.clip(self.rng.normal(cust["hour_mean"], cust["hour_sd"]), 7, 23.5))

    def _pick_retailer(self, cust, retailers_by_id):
        r = self.rng.random()
        if r < 0.88:
            rid = self.rng.choice(cust["preferred"])
        elif r < 0.98:
            rid = self.rng.choice(cust["local"])
        else:
            rid = self.rng.choice(list(retailers_by_id.keys()))
        return rid, retailers_by_id[rid]

    # ---------------------------------------------------------- normal days
    def normal_activity(self, cust, start, days, retailers_by_id, rate_mult=1.0, amt_mult=1.0):
        for d in range(days):
            day = start + timedelta(days=d)
            n = self.rng.poisson(cust["daily_rate"] * rate_mult)
            for _ in range(n):
                h = self._normal_hour(cust)
                ts = day.replace(hour=0, minute=0, second=0) + timedelta(hours=h)
                rid, loc = self._pick_retailer(cust, retailers_by_id)
                self._add(cust, ts, self._normal_amount(cust, amt_mult), rid, loc)

    # ----------------------------------------------------- injected scenarios
    def inject(self, cust, scenario, window_start, retailers, retailers_by_id):
        rng = self.rng
        day = window_start + timedelta(days=int(rng.integers(1, config.WINDOW_DAYS - 1)))

        def burst(n, start_ts, span_min, multi_retailer=True, amount_scale=1.0):
            for _ in range(n):
                ts = start_ts + timedelta(minutes=float(rng.uniform(0, span_min)))
                if multi_retailer and rng.random() < 0.6:
                    rid = rng.choice(cust["local"])
                else:
                    rid = rng.choice(cust["preferred"])
                self._add(cust, ts, self._normal_amount(cust, amount_scale), rid, retailers_by_id[rid])

        if scenario == "burst_frequency":
            start = day.replace(hour=int(rng.integers(10, 20)), minute=0, second=0)
            burst(int(rng.integers(22, 45)), start, 60)
            if rng.random() < 0.5:
                burst(int(rng.integers(10, 20)), start + timedelta(days=1), 90)

        elif scenario == "high_value":
            for _ in range(int(rng.integers(4, 9))):
                ts = day.replace(hour=0, minute=0, second=0) + timedelta(
                    hours=self._normal_hour(cust), days=int(rng.integers(0, 2)))
                rid, loc = self._pick_retailer(cust, retailers_by_id)
                self._add(cust, ts, cust["amount_mean"] * rng.uniform(8, 20), rid, loc)

        elif scenario == "multi_location":
            cities = [c for c in CITIES if c != cust["home"]]
            chosen = rng.choice(cities, size=int(rng.integers(3, 6)), replace=False)
            t = day.replace(hour=9, minute=0, second=0)
            for city in chosen:
                pool = retailers[retailers.location == city].retailer_id.tolist()
                if not pool:
                    continue
                for _ in range(int(rng.integers(2, 5))):
                    t += timedelta(minutes=float(rng.uniform(20, 140)))
                    self._add(cust, t, self._normal_amount(cust, 1.8), rng.choice(pool), city)

        elif scenario == "night_activity":
            for d in range(int(rng.integers(3, 6))):
                base = (window_start + timedelta(days=d + 1)).replace(hour=0, minute=0, second=0)
                for _ in range(int(rng.integers(3, 7))):
                    ts = base + timedelta(hours=float(rng.uniform(0.5, 4.8)))
                    rid, loc = self._pick_retailer(cust, retailers_by_id)
                    self._add(cust, ts, self._normal_amount(cust, 1.5), rid, loc)

        elif scenario == "repeated_amounts":
            amount = float(rng.choice([250.0, 300.0, 450.0, 500.0, 950.0]))
            t = day.replace(hour=int(rng.integers(11, 18)), minute=0, second=0)
            for _ in range(int(rng.integers(7, 14))):
                t += timedelta(minutes=float(rng.uniform(0.5, 2.5)))
                rid = rng.choice(cust["local"])
                self._add(cust, t, amount, rid, retailers_by_id[rid], ttype="Prize Claim")

        elif scenario == "behaviour_shift":
            # the whole window is busier and more expensive than history
            self.normal_activity(cust, window_start, config.WINDOW_DAYS, retailers_by_id,
                                 rate_mult=rng.uniform(4, 7), amt_mult=rng.uniform(2.5, 4))

        elif scenario == "combined":
            start = day.replace(hour=int(rng.integers(0, 3)), minute=0, second=0)
            burst(int(rng.integers(20, 35)), start, 75, amount_scale=3.0)
            other = [c for c in CITIES if c != cust["home"]]
            for city in rng.choice(other, size=2, replace=False):
                pool = retailers[retailers.location == city].retailer_id.tolist()
                if pool:
                    for _ in range(3):
                        ts = start + timedelta(hours=float(rng.uniform(6, 20)))
                        self._add(cust, ts, self._normal_amount(cust, 2.5), rng.choice(pool), city)

    def benign_spike(self, cust, window_start, retailers_by_id):
        """One-off legitimate spike, e.g. a big-jackpot evening at the usual retailer."""
        day = window_start + timedelta(days=int(self.rng.integers(0, config.WINDOW_DAYS)))
        start = day.replace(hour=18, minute=0, second=0)
        for _ in range(int(self.rng.integers(5, 10))):
            ts = start + timedelta(minutes=float(self.rng.uniform(0, 180)))
            rid = self.rng.choice(cust["preferred"])
            self._add(cust, ts, self._normal_amount(cust, 1.6), rid, retailers_by_id[rid],
                      ttype="Lottery Ticket")


def generate(seed: int = config.RANDOM_SEED, n_customers: int = config.N_CUSTOMERS):
    """Return (transactions_df, customers_df, retailers_df)."""
    g = _Gen(seed)
    retailers = g.build_retailers(config.N_RETAILERS)
    retailers_by_id = dict(zip(retailers.retailer_id, retailers.location))

    total_days = config.HISTORY_DAYS + config.WINDOW_DAYS
    sim_start = (config.SIM_END - timedelta(days=total_days - 1)).replace(hour=0, minute=0, second=0)
    window_start = sim_start + timedelta(days=config.HISTORY_DAYS)

    customers = []
    for i in range(1, n_customers + 1):
        cust = g.build_customer(i, retailers)
        r = g.rng.random()
        if r < 0.11:
            cust["profile"] = "suspicious"
            cust["scenario"] = str(g.rng.choice(SUSPICIOUS_SCENARIOS))
        elif r < 0.19:
            cust["profile"] = "busy_legitimate"
            cust["daily_rate"] *= g.rng.uniform(4, 8)
        elif r < 0.27:
            cust["profile"] = "benign_spike"
        customers.append(cust)

        g.normal_activity(cust, sim_start, total_days, retailers_by_id)
        if cust["profile"] == "suspicious":
            g.inject(cust, cust["scenario"], window_start, retailers, retailers_by_id)
        elif cust["profile"] == "benign_spike":
            g.benign_spike(cust, window_start, retailers_by_id)

    tx = pd.DataFrame(g.rows)
    tx["timestamp"] = pd.to_datetime(tx["timestamp"]).dt.floor("s")
    tx = tx[tx.timestamp <= config.SIM_END].sort_values("timestamp").reset_index(drop=True)
    tx["is_synthetic"] = 1

    cust_df = pd.DataFrame(
        [
            {
                "customer_id": c["customer_id"],
                "home_location": c["home"],
                "profile": c["profile"],
                "scenario": c["scenario"],
                "label_suspicious": int(c["profile"] == "suspicious"),
            }
            for c in customers
        ]
    )
    return tx, cust_df, retailers


def main():
    tx, cust, _ = generate()
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tx.to_csv(config.TRANSACTIONS_CSV, index=False)
    cust.to_csv(config.CUSTOMERS_CSV, index=False)
    print(f"Generated {len(tx):,} SYNTHETIC transactions for {len(cust)} SYNTHETIC customers")
    print(cust.profile.value_counts().to_string())


if __name__ == "__main__":
    main()
