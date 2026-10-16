-- PRISM schema v2: investigator bookmarks and notes on saved evidence.
-- Workspace aids only: they never change evidence, reports or case status, and decisions stay in case_actions.
-- Removal is a soft delete (removed_at_utc) so nothing a reviewer saved silently disappears.

CREATE TABLE bookmarks (
    bookmark_id    TEXT PRIMARY KEY,
    case_id        TEXT NOT NULL REFERENCES cases(case_id),
    evidence_id    TEXT NOT NULL REFERENCES evidence(evidence_id),
    kind           TEXT NOT NULL CHECK (kind IN ('transaction', 'retailer', 'finding', 'evidence')),
    label          TEXT NOT NULL,
    note           TEXT,
    reviewer_id    TEXT NOT NULL REFERENCES reviewers(reviewer_id),
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    removed_at_utc TEXT
);
CREATE INDEX idx_bookmarks_case ON bookmarks(case_id, removed_at_utc);
