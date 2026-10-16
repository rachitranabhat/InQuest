"""Versioned synthetic dataset: version, generation configuration and scenario categories.

The generator itself (data/generator.py, built on data/synthetic_data_generator.py) is unchanged from V1;
this module only names and documents what it produces so a dataset can be identified, reproduced and
evaluated. Same version + same seed + same configuration => byte-identical rows.

Scenario categories group the generator's planted patterns. They describe the SIMULATION, not an
investigator's conclusion: "suspicious_*" means a pattern was deliberately planted, which is still not
confirmed fraud, and "explainable_*" subjects look unusual for a legitimate, recorded reason.
"""
from __future__ import annotations

import hashlib
import json

import config

GENERATOR = "data.generator v2 (behaviour model: data.synthetic_data_generator)"
DATASET_VERSION = f"prism-synth-2.1.0-seed{config.RANDOM_SEED}-n{config.N_CUSTOMERS}"


def generation_config() -> dict:
    from data import generator as g
    return {
        "seed": config.RANDOM_SEED,
        "n_players": config.N_CUSTOMERS,
        "n_retailers": config.N_RETAILERS,
        "history_days": config.HISTORY_DAYS,
        "review_window_days": config.WINDOW_DAYS,
        "simulation_end_local": config.SIM_END.isoformat(),
        "display_timezone": config.DISPLAY_TZ,
        "population_mix": {"suspicious": 0.10, "busy_legitimate": 0.08, "benign_spike": 0.08, "normal": 0.74},
        "suspicious_scenarios": list(g.SUSPICIOUS_SCENARIOS),
        "curated_subjects": [k for k, _s, _t in g.CURATED],
        "online_accounts": "first 110 normal/busy players + 1 curated deposit pass-through account",
        "context_event": {"name": "jackpot week", "window_day_offsets": list(g.JACKPOT_DAYS), "rate_multiplier": g.JACKPOT_MULT},
    }


def config_fingerprint() -> str:
    return hashlib.sha256(json.dumps(generation_config(), sort_keys=True).encode()).hexdigest()


# planted scenario -> documented category (all synthetic)
CATEGORY = {
    # population profiles
    ("normal", None): "normal",
    ("busy_legitimate", None): "explainable_high_volume",
    ("benign_spike", None): "explainable_spike",
    # population: planted suspicious patterns
    ("suspicious", "burst_frequency"): "suspicious_frequency",
    ("suspicious", "high_value"): "suspicious_spending",
    ("suspicious", "repeated_amounts"): "suspicious_spending_pattern",
    ("suspicious", "night_activity"): "suspicious_time",
    ("suspicious", "multi_location"): "suspicious_location",
    ("suspicious", "behaviour_shift"): "suspicious_behaviour_shift",
    ("suspicious", "combined"): "suspicious_combined",
    # curated demo subjects
    ("curated", "burst_frequency"): "suspicious_frequency",
    ("curated", "repeated_amounts"): "suspicious_spending_pattern",
    ("curated", "deposit_passthrough"): "aml_like_passthrough",          # online deposits/withdrawals only
    ("curated", "seasonal_jackpot"): "explainable_context_event",
    ("curated", "high_volume_legit"): "explainable_high_volume",
    ("curated", "shared_retailer"): "ambiguous_shared_location",
    ("curated_partner", "shared_retailer_partner"): "ambiguous_shared_location",
    ("curated", "multi_retailer_ambiguous"): "ambiguous",
    ("curated", "incomplete_attribution"): "incomplete_data",
}

CATEGORY_DESCRIPTIONS = {
    "normal": "Ordinary play with stable habits.",
    "explainable_high_volume": "High but steady, legitimate volume.",
    "explainable_spike": "A short legitimate spike (benign burst).",
    "explainable_context_event": "Activity largely explained by the network-wide jackpot week.",
    "ambiguous_shared_location": "Co-presence with another player at one retailer; no recorded link.",
    "ambiguous": "Unusual spread that the records cannot explain either way.",
    "incomplete_data": "Relevant purchases are anonymous, so the picture is incomplete.",
    "suspicious_frequency": "Planted: many purchases in a short time.",
    "suspicious_spending": "Planted: unusually high amounts.",
    "suspicious_spending_pattern": "Planted: repeated identical amounts.",
    "suspicious_time": "Planted: activity at unusual hours.",
    "suspicious_location": "Planted: purchases across unusual locations.",
    "suspicious_behaviour_shift": "Planted: a shift away from the player's own pattern.",
    "suspicious_combined": "Planted: several patterns at once.",
    "aml_like_passthrough": "Planted: deposits quickly withdrawn on an online account (AML-like pattern, not proof of laundering).",
}


def category_for(profile: str, scenario) -> str:
    scenario = scenario if isinstance(scenario, str) and scenario else None
    return CATEGORY.get((profile, scenario)) or CATEGORY.get((profile, None)) or "uncategorised"


def label_rows(labels_df) -> list[tuple]:
    """scenario_labels rows from the generator's label frame."""
    out = []
    for r in labels_df.itertuples(index=False):
        scenario = r.scenario if isinstance(r.scenario, str) and r.scenario else None
        curated = r.curated_key if isinstance(r.curated_key, str) and r.curated_key else None
        out.append((r.player_id, DATASET_VERSION, r.profile, scenario, category_for(r.profile, scenario), curated,
                    int(r.label_suspicious), "generator"))
    return out


def record_dataset(con, labels_df) -> dict:
    """Write dataset_versions + scenario_labels (idempotent: existing rows are kept, never duplicated)."""
    from database.db import dumps
    from timeutil import utc_now_iso
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("players", "accounts", "retailers", "locations", "transactions", "events")}
    t_start, t_end = con.execute("SELECT MIN(timestamp_utc), MAX(timestamp_utc) FROM transactions").fetchone()
    con.execute("""INSERT INTO dataset_versions VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(dataset_version) DO NOTHING""",
                (DATASET_VERSION, config.RANDOM_SEED, GENERATOR,
                 dumps({**generation_config(), "config_sha256": config_fingerprint()}), t_start, t_end, dumps(counts),
                 utc_now_iso()))
    rows = [r for r in label_rows(labels_df)
            if con.execute("SELECT 1 FROM players WHERE player_id = ?", (r[0],)).fetchone()]
    con.executemany("INSERT INTO scenario_labels VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(player_id) DO NOTHING", rows)
    return {"dataset_version": DATASET_VERSION, "labels": len(rows), "counts": counts}
