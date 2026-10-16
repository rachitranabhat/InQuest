-- PRISM schema v3: restricted identity records (FICTIONAL) and an append-only identity-access log.
-- Additive only: no existing table, evidence snapshot or record is changed.
-- player_identities holds invented names and reserved/fictional contact details (example.invalid e-mail,
-- 555-01xx phone numbers) for registered synthetic players. It is never joined by case, evidence, report,
-- copilot or analytics code; only services/restricted.py reads it, behind a senior-role check.

CREATE TABLE player_identities (
    player_id      TEXT PRIMARY KEY REFERENCES players(player_id),
    full_name      TEXT NOT NULL,
    email          TEXT NOT NULL,
    phone          TEXT NOT NULL,
    record_source  TEXT NOT NULL,            -- 'rewards card' | 'online account' | 'rewards card and online account'
    is_fictional   INTEGER NOT NULL DEFAULT 1 CHECK (is_fictional = 1),
    created_at_utc TEXT NOT NULL
);

CREATE TABLE restricted_access_log (
    access_id      TEXT PRIMARY KEY,
    player_id      TEXT NOT NULL REFERENCES players(player_id),
    case_id        TEXT REFERENCES cases(case_id),
    reviewer_id    TEXT NOT NULL REFERENCES reviewers(reviewer_id),
    reviewer_role  TEXT NOT NULL,
    session_kind   TEXT NOT NULL,
    reason         TEXT NOT NULL,
    fields         TEXT NOT NULL,            -- JSON list of the fields that were revealed
    created_at_utc TEXT NOT NULL
);
CREATE INDEX idx_restricted_log_player ON restricted_access_log(player_id, created_at_utc);
CREATE TRIGGER restricted_log_no_update BEFORE UPDATE ON restricted_access_log
BEGIN SELECT RAISE(ABORT, 'identity access records are append-only'); END;
CREATE TRIGGER restricted_log_no_delete BEFORE DELETE ON restricted_access_log
BEGIN SELECT RAISE(ABORT, 'identity access records are append-only'); END;
