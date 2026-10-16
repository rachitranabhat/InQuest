-- PRISM schema v1 for PostgreSQL (V2). Same tables, keys and constraints as the SQLite schema in
-- database/migrations/0001_initial.sql; differences: DOUBLE PRECISION for REAL, trigger functions for the
-- immutability rules, reviewers created before the tables that reference it. Timestamps stay ISO-8601 TEXT
-- (UTC, ending in 'Z') so stored values and evidence fingerprints are byte-identical to V1.
-- Applied by database/db.py inside schema "prism" (search_path), never in the Supabase-exposed "public" schema.

CREATE OR REPLACE FUNCTION prism_reject_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '%', TG_ARGV[0] USING ERRCODE = 'restrict_violation';
END;
$$;

-- SQLite's ROUND(real, digits) returns a real; PostgreSQL only has ROUND(numeric, int). Same result type as V1.
CREATE OR REPLACE FUNCTION round(double precision, integer) RETURNS double precision
    LANGUAGE sql IMMUTABLE STRICT AS $$ SELECT round($1::numeric, $2)::double precision $$;


CREATE TABLE reviewers (
    reviewer_id  TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    role         TEXT NOT NULL
);

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE locations (
    location_id TEXT PRIMARY KEY,
    city        TEXT NOT NULL,
    region      TEXT NOT NULL
);

CREATE TABLE retailers (
    retailer_id    TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    location_id    TEXT NOT NULL REFERENCES locations(location_id),
    city           TEXT NOT NULL,
    terminal_count INTEGER NOT NULL
);

CREATE TABLE players (
    player_id          TEXT PRIMARY KEY,
    home_location_id   TEXT REFERENCES locations(location_id),
    has_rewards_card   INTEGER NOT NULL,
    has_online_account INTEGER NOT NULL
);

CREATE TABLE accounts (
    account_id TEXT PRIMARY KEY,
    player_id  TEXT NOT NULL REFERENCES players(player_id),
    opened_on  TEXT NOT NULL
);

-- Original records. Immutable: see triggers below.
CREATE TABLE transactions (
    transaction_id   TEXT PRIMARY KEY,
    channel          TEXT NOT NULL CHECK (channel IN ('lottery_terminal', 'online_account')),
    player_id        TEXT REFERENCES players(player_id),      -- NULL = purchase not attributable
    account_id       TEXT REFERENCES accounts(account_id),
    retailer_id      TEXT REFERENCES retailers(retailer_id),
    location_id      TEXT REFERENCES locations(location_id),
    terminal_id      TEXT,
    ticket_id        TEXT,
    timestamp_utc    TEXT NOT NULL,
    amount           DOUBLE PRECISION NOT NULL CHECK (amount >= 0),
    transaction_type TEXT NOT NULL,
    game             TEXT,
    attribution      TEXT NOT NULL CHECK (attribution IN ('rewards_card_scan', 'account_holder', 'none')),
    is_synthetic     INTEGER NOT NULL DEFAULT 1 CHECK (is_synthetic = 1)
);
CREATE INDEX idx_tx_player ON transactions(player_id, timestamp_utc);
CREATE INDEX idx_tx_account ON transactions(account_id, timestamp_utc);
CREATE INDEX idx_tx_retailer ON transactions(retailer_id, timestamp_utc);
CREATE TRIGGER transactions_no_update BEFORE UPDATE ON transactions
    FOR EACH ROW EXECUTE FUNCTION prism_reject_change('transactions are immutable original records');
CREATE TRIGGER transactions_no_delete BEFORE DELETE ON transactions
    FOR EACH ROW EXECUTE FUNCTION prism_reject_change('transactions are immutable original records');

CREATE TABLE events (
    event_id    TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    start_local TEXT NOT NULL,
    end_local   TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE cases (
    case_id               TEXT PRIMARY KEY,
    alert_id              TEXT NOT NULL UNIQUE,
    channel               TEXT NOT NULL,
    subject_type          TEXT NOT NULL CHECK (subject_type IN ('player', 'account')),
    subject_id            TEXT NOT NULL,
    player_id             TEXT REFERENCES players(player_id),
    status                TEXT NOT NULL,
    priority              TEXT NOT NULL,
    priority_rationale    TEXT NOT NULL,          -- JSON list
    alert_score           DOUBLE PRECISION NOT NULL,
    score_band            TEXT NOT NULL,
    evidence_completeness TEXT NOT NULL,
    urgency               TEXT NOT NULL,
    primary_reason        TEXT NOT NULL,
    triggered_count       INTEGER NOT NULL,
    window_start_utc      TEXT NOT NULL,
    window_end_utc        TEXT NOT NULL,
    features_json         TEXT NOT NULL,
    factors_json          TEXT NOT NULL,
    anomaly_score         DOUBLE PRECISION,
    assigned_reviewer_id  TEXT REFERENCES reviewers(reviewer_id),
    curated_key           TEXT,
    scenario_title        TEXT,
    origin                TEXT NOT NULL DEFAULT 'monitoring',   -- 'monitoring' | 'scenario_lab'
    current_snapshot_id   TEXT,
    created_at_utc        TEXT NOT NULL,
    updated_at_utc        TEXT NOT NULL
);
CREATE INDEX idx_cases_status ON cases(status);

CREATE TABLE alerts (
    alert_id         TEXT PRIMARY KEY,
    case_id          TEXT NOT NULL REFERENCES cases(case_id),
    source           TEXT NOT NULL,
    alert_type       TEXT NOT NULL,
    rules_fired      TEXT NOT NULL,               -- JSON list
    triggered_at_utc TEXT NOT NULL,
    subject_type     TEXT NOT NULL,
    subject_id       TEXT NOT NULL,
    alert_score      DOUBLE PRECISION NOT NULL,
    indicators       TEXT NOT NULL,               -- JSON list of triggered factor keys
    transaction_ids  TEXT NOT NULL                -- JSON list
);

CREATE TABLE evidence_snapshots (
    snapshot_id    TEXT PRIMARY KEY,
    case_id        TEXT NOT NULL REFERENCES cases(case_id),
    evidence_hash  TEXT NOT NULL,
    item_count     INTEGER NOT NULL,
    created_at_utc TEXT NOT NULL
);

-- The evidence registry: every citable fact.
CREATE TABLE evidence (
    evidence_id    TEXT PRIMARY KEY,
    case_id        TEXT NOT NULL REFERENCES cases(case_id),
    snapshot_id    TEXT REFERENCES evidence_snapshots(snapshot_id),  -- NULL = created later by a query tool
    type           TEXT NOT NULL,
    title          TEXT NOT NULL,
    summary        TEXT NOT NULL,
    source_ids     TEXT NOT NULL,                 -- JSON list of original record IDs
    entities       TEXT NOT NULL,                 -- JSON list of entity IDs/names it is about
    computed       TEXT NOT NULL,                 -- JSON object of computed values
    provenance     TEXT NOT NULL,                 -- JSON: how it was computed
    created_at_utc TEXT NOT NULL
);
CREATE INDEX idx_evidence_case ON evidence(case_id, type);
CREATE TRIGGER evidence_no_update BEFORE UPDATE ON evidence
    FOR EACH ROW EXECUTE FUNCTION prism_reject_change('evidence items are immutable; create a new item instead');

CREATE TABLE reports (
    report_id      TEXT PRIMARY KEY,
    case_id        TEXT NOT NULL REFERENCES cases(case_id),
    version        INTEGER NOT NULL,
    mode           TEXT NOT NULL,                 -- deterministic | llm | llm_fallback
    model          TEXT,
    prompt_version TEXT NOT NULL,
    snapshot_id    TEXT NOT NULL REFERENCES evidence_snapshots(snapshot_id),
    evidence_hash  TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'locked')),
    validation     TEXT NOT NULL,                 -- JSON summary
    notes          TEXT,                          -- e.g. why an LLM run fell back
    created_at_utc TEXT NOT NULL,
    locked_at_utc  TEXT,
    UNIQUE (case_id, version)
);

CREATE TABLE claims (
    claim_id            TEXT PRIMARY KEY,
    report_id           TEXT NOT NULL REFERENCES reports(report_id),
    section             TEXT NOT NULL,
    position            INTEGER NOT NULL,
    kind                TEXT NOT NULL,            -- fact | interpretation | recommendation | limitation | status
    text                TEXT NOT NULL,
    evidence_ids        TEXT NOT NULL,            -- JSON list
    verification_status TEXT NOT NULL CHECK (verification_status IN ('verified', 'unverified')),
    failures            TEXT NOT NULL             -- JSON list of reasons (empty when verified)
);
CREATE INDEX idx_claims_report ON claims(report_id, position);
CREATE TRIGGER claims_no_update BEFORE UPDATE ON claims
    FOR EACH ROW EXECUTE FUNCTION prism_reject_change('claims are immutable; generate a new report version');

CREATE TABLE report_exports (
    export_id      TEXT PRIMARY KEY,
    report_id      TEXT NOT NULL REFERENCES reports(report_id),
    format         TEXT NOT NULL,
    sha256         TEXT NOT NULL,
    file_name      TEXT NOT NULL,
    reviewer_id    TEXT REFERENCES reviewers(reviewer_id),
    created_at_utc TEXT NOT NULL
);


CREATE TABLE sessions (
    token          TEXT PRIMARY KEY,
    reviewer_id    TEXT NOT NULL REFERENCES reviewers(reviewer_id),
    kind           TEXT NOT NULL DEFAULT 'simulated',
    created_at_utc TEXT NOT NULL
);

CREATE TABLE case_actions (
    action_id       TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES cases(case_id),
    action          TEXT NOT NULL,
    from_status     TEXT NOT NULL,
    to_status       TEXT NOT NULL,
    reviewer_id     TEXT NOT NULL REFERENCES reviewers(reviewer_id),
    session_kind    TEXT NOT NULL,
    notes           TEXT,
    report_id       TEXT REFERENCES reports(report_id),
    report_version  INTEGER,
    snapshot_id     TEXT,
    evidence_hash   TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at_utc  TEXT NOT NULL
);
CREATE INDEX idx_actions_case ON case_actions(case_id, created_at_utc);
CREATE TRIGGER case_actions_no_update BEFORE UPDATE ON case_actions
    FOR EACH ROW EXECUTE FUNCTION prism_reject_change('audit records are append-only');
CREATE TRIGGER case_actions_no_delete BEFORE DELETE ON case_actions
    FOR EACH ROW EXECUTE FUNCTION prism_reject_change('audit records are append-only');

CREATE TABLE chat_threads (
    thread_id      TEXT PRIMARY KEY,
    case_id        TEXT NOT NULL REFERENCES cases(case_id),
    reviewer_id    TEXT REFERENCES reviewers(reviewer_id),
    created_at_utc TEXT NOT NULL
);

CREATE TABLE chat_messages (
    message_id     TEXT PRIMARY KEY,
    thread_id      TEXT NOT NULL REFERENCES chat_threads(thread_id),
    role           TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content        TEXT NOT NULL,
    mode           TEXT,
    payload        TEXT NOT NULL DEFAULT '{}',    -- JSON: claims, tool calls, context
    created_at_utc TEXT NOT NULL
);
CREATE INDEX idx_chat_thread ON chat_messages(thread_id, created_at_utc);

CREATE TABLE id_counters (
    prefix TEXT PRIMARY KEY,
    next   INTEGER NOT NULL
);
