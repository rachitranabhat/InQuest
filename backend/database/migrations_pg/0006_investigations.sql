-- PRISM schema v6 (V2, PostgreSQL): persisted multi-agent investigations. Same rules as the SQLite file.
CREATE TABLE investigations (
    investigation_id TEXT PRIMARY KEY,
    case_id          TEXT NOT NULL REFERENCES cases(case_id),
    requested_mode   TEXT NOT NULL CHECK (requested_mode IN ('deterministic', 'llm')),
    mode             TEXT,
    status           TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    assessment       TEXT,
    requested_by     TEXT NOT NULL REFERENCES reviewers(reviewer_id),
    started_at_utc   TEXT NOT NULL,
    finished_at_utc  TEXT,
    error            TEXT,
    result_json      TEXT
);
CREATE INDEX idx_investigations_case ON investigations(case_id, started_at_utc);
CREATE OR REPLACE FUNCTION prism_investigation_final() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status <> 'running' THEN
        RAISE EXCEPTION 'completed investigations are immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER investigations_final_no_update BEFORE UPDATE ON investigations
    FOR EACH ROW EXECUTE FUNCTION prism_investigation_final();
CREATE TRIGGER investigations_no_delete BEFORE DELETE ON investigations
    FOR EACH ROW EXECUTE FUNCTION prism_reject_change('investigations are kept as history');
ALTER TABLE investigations ENABLE ROW LEVEL SECURITY;
