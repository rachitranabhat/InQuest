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

-- ---------------------------------------------------------------------------------------------------
-- Supabase hardening. The FastAPI backend is the only client: it connects with its own database role
-- through DATABASE_URL. Row-level security is enabled on every PRISM table with NO policies, so the
-- Supabase Data API roles (anon, authenticated) can read or write nothing even if the "prism" schema were
-- ever exposed. The table owner (the backend's role) is unaffected, as in any RLS setup without FORCE.
-- ---------------------------------------------------------------------------------------------------
DO $$
DECLARE t record;
BEGIN
    FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = current_schema() LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t.tablename);
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM anon', current_schema());
        EXECUTE format('REVOKE ALL ON SCHEMA %I FROM anon', current_schema());
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM authenticated', current_schema());
        EXECUTE format('REVOKE ALL ON SCHEMA %I FROM authenticated', current_schema());
    END IF;
END $$;
