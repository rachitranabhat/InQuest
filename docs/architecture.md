# Architecture

```
React (Vite, TS)  ──/api──►  FastAPI (backend/api/main.py)
                               │  Pydantic request/response models (schemas/api.py)
                               ▼
                    services/                         detection/
                    ├ cases.py      queue, detail, timeline, analytics, audit
                    ├ evidence_registry.py  builds immutable evidence + snapshot hash
                    ├ claims.py     structured claims + deterministic validator
                    ├ report_writer.py  deterministic 11-section report
                    ├ reports.py    generate / version / lock (demo, LLM, LLM fallback)
                    ├ query_tools.py  9 case-scoped tools (no SQL from the model)
                    ├ copilot.py    planner (demo) or tool-calling loop (LLM) → validated claims
                    ├ workflow.py   state machine, notes, idempotency, sessions
                    ├ graph.py      recorded relationships only
                    ├ pdf_export.py ReportLab, from a saved version
                    └ scenarios.py  Scenario lab
                               ▼
                    SQLite (database/db.py, migrations/0001_initial.sql)
```

## Data model highlights

- **transactions** — immutable (UPDATE/DELETE triggers). Anonymous lottery sales have `attribution = none`; purchases are linked to a player only when a rewards card was scanned; online accounts are `account_holder`.
- **evidence** — `EV-######`, typed (transaction, aggregate_retailer, comparison, limitation, …), with provenance and `case_id`. Immutable. Aggregates store their inputs so they can be recomputed.
- **evidence_snapshots** — `SNP-` with a sha256 over the case's evidence; every reviewer action records it.
- **reports / claims** — versioned per case; a report is `locked` the moment a reviewer acts on it.
- **case_actions** — append-only (UPDATE/DELETE triggers), unique idempotency key.
- **sessions / reviewers** — simulated reviewer sessions, `X-Reviewer-Session` header.

All timestamps are stored as UTC ISO-8601 (`Z`); the UI shows them in the display timezone from `branding.json` (America/Toronto).

## Report generation

1. Load the case's evidence and build the validator vocabulary (IDs, numbers, dates, names in each item).
2. **Demo mode:** `report_writer.py` writes claims from evidence fields. **LLM mode:** the model gets fact cards + evidence and must return JSON claims.
3. Every claim goes through `validate_claim`. In LLM mode failing claims are sent back once for repair; if any still fail the deterministic report is used and labelled `llm_fallback`.
4. Report + claims are stored; status `New → Analysis Ready`; a SYSTEM audit row is written.

## Copilot

Questions are sanitised, limited to 1000 chars and answered only through `CaseTools` (pydantic-validated args, case ID fixed server-side). Query results become `query_result` evidence so answers can cite them. Prompt-injection text inside evidence is treated as data; the system prompt forbids conclusions about guilt, and the validator rejects accusatory claims regardless.

## Frontend

`src/features/workspace/selection.tsx` is the shared selection state that ties citations, the evidence drawer, the timeline and the graph together. Server state lives in TanStack Query (`src/hooks/queries.ts`); all API calls go through `src/lib/api.ts`. Theme tokens ("Obsidian Intelligence") are in `src/styles/index.css` (`@theme`).
