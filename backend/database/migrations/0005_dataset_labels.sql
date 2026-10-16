-- PRISM schema v5 (V2): versioned synthetic dataset metadata and simulation ground-truth labels.
-- Additive. scenario_labels is the SIMULATOR's answer key: which synthetic players had a pattern planted.
-- It is never joined by detection, evidence, reports, the copilot or investigator screens; only the
-- evaluation module and the senior-only Data & Methodology technical view read it. A planted pattern is a
-- simulation fact, not confirmed fraud, and is kept separate from investigator-facing risk classifications.

CREATE TABLE dataset_versions (
    dataset_version   TEXT PRIMARY KEY,
    seed              INTEGER NOT NULL,
    generator         TEXT NOT NULL,          -- module and version that produced the rows
    config_json       TEXT NOT NULL,          -- the generation configuration (JSON)
    time_start_utc    TEXT NOT NULL,          -- first synthetic transaction
    time_end_utc      TEXT NOT NULL,          -- last synthetic transaction
    counts_json       TEXT NOT NULL,          -- record counts at generation time (JSON)
    created_at_utc    TEXT NOT NULL
);

CREATE TABLE scenario_labels (
    player_id         TEXT PRIMARY KEY REFERENCES players(player_id),
    dataset_version   TEXT NOT NULL REFERENCES dataset_versions(dataset_version),
    profile           TEXT NOT NULL,          -- normal | busy_legitimate | benign_spike | suspicious | curated | curated_partner
    scenario          TEXT,                   -- planted pattern, if any (e.g. burst_frequency)
    scenario_category TEXT NOT NULL,          -- documented grouping, see data/dataset_spec.py
    curated_key       TEXT,
    label_suspicious  INTEGER NOT NULL CHECK (label_suspicious IN (0, 1)),
    label_source      TEXT NOT NULL DEFAULT 'generator'
);
CREATE INDEX idx_labels_category ON scenario_labels(scenario_category);
