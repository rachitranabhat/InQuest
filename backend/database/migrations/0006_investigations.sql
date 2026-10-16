-- PRISM schema v6 (V2): persisted multi-agent investigations. Additive.
-- One row per run; reruns add rows (history is kept). A row may change only while status = 'running'
-- (to record its result or failure); after that it is immutable and can never be deleted.
CREATE TABLE investigations (
    investigation_id TEXT PRIMARY KEY,
    case_id          TEXT NOT NULL REFERENCES cases(case_id),
    requested_mode   TEXT NOT NULL CHECK (requested_mode IN ('deterministic', 'llm')),
    mode             TEXT,                    -- deterministic | llm | llm_partial_fallback (set when completed)
    status           TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    assessment       TEXT,
    requested_by     TEXT NOT NULL REFERENCES reviewers(reviewer_id),
    started_at_utc   TEXT NOT NULL,
    finished_at_utc  TEXT,
    error            TEXT,
    result_json      TEXT
);
CREATE INDEX idx_investigations_case ON investigations(case_id, started_at_utc);
CREATE TRIGGER investigations_final_no_update BEFORE UPDATE ON investigations
WHEN OLD.status != 'running'
BEGIN SELECT RAISE(ABORT, 'completed investigations are immutable'); END;
CREATE TRIGGER investigations_no_delete BEFORE DELETE ON investigations
BEGIN SELECT RAISE(ABORT, 'investigations are kept as history'); END;
