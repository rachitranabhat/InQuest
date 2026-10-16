-- PRISM schema v4: final investigation dispositions.
-- Additive only. Every entry is also written to case_actions (the existing audit trail) in the same
-- transaction; this table adds the disposition, concern type, justification, cited evidence and approval.
-- Append-only: a senior confirmation or return is a NEW row that points at the decision it reviews.

CREATE TABLE case_dispositions (
    disposition_id  TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES cases(case_id),
    action_id       TEXT NOT NULL UNIQUE REFERENCES case_actions(action_id),
    entry_type      TEXT NOT NULL CHECK (entry_type IN ('decision', 'confirmation', 'return')),
    parent_id       TEXT REFERENCES case_dispositions(disposition_id),   -- the decision a confirmation/return reviews
    disposition     TEXT NOT NULL CHECK (disposition IN ('substantiated', 'not_substantiated', 'inconclusive', 'escalate')),
    concern_type    TEXT NOT NULL CHECK (concern_type IN ('fraud', 'aml', 'safer_gambling')),
    justification   TEXT NOT NULL,
    evidence_ids    TEXT NOT NULL,            -- JSON list of cited evidence IDs (same case, same evidence version)
    reviewer_id     TEXT NOT NULL REFERENCES reviewers(reviewer_id),
    reviewer_role   TEXT NOT NULL,
    session_kind    TEXT NOT NULL,
    report_id       TEXT REFERENCES reports(report_id),
    report_version  INTEGER,
    snapshot_id     TEXT,
    evidence_hash   TEXT,
    approval_status TEXT NOT NULL CHECK (approval_status IN ('not_required', 'pending_senior', 'confirmed', 'returned')),
    from_status     TEXT NOT NULL,
    to_status       TEXT NOT NULL,
    created_at_utc  TEXT NOT NULL
);
CREATE INDEX idx_dispositions_case ON case_dispositions(case_id, created_at_utc);
CREATE TRIGGER case_dispositions_no_update BEFORE UPDATE ON case_dispositions
BEGIN SELECT RAISE(ABORT, 'disposition records are append-only'); END;
CREATE TRIGGER case_dispositions_no_delete BEFORE DELETE ON case_dispositions
BEGIN SELECT RAISE(ABORT, 'disposition records are append-only'); END;
