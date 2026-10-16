# PROGRESS — PRISM V2 (experimental, Supabase-ready)

_Last updated: 2026-10-15 (V2 created; PostgreSQL adapter, versioned dataset, evaluation; waiting for Supabase credentials)_

## AI Investigation — concise view, background runs, saved history (2026-10-16)
- **Layout:** the Lead card comes first and shows the assessment, a one-sentence summary and the next step. Below it:
  - up to 3 points toward suspicion;
  - up to 3 points for ordinary explanations;
  - the missing information.
  Every point keeps clickable citations. The agent details, validation & warnings and the full rationale are collapsible sections.
- **Background runs:** POST `/api/cases/{id}/investigations` returns 202 with a running record, and the run continues in a server thread. Switching tabs or reloading never interrupts it or starts a new one, and a case allows only one running investigation at a time. While a run is going, the tab polls `GET /api/cases/{id}/investigations` every 2 s.
- **Storage:** results are saved in the V2 database (migration 0006, `investigations` table, schema v6; SQLite and PostgreSQL). They survive a refresh and a restart. Triggers keep finished runs unchanged and prevent deletion. A rerun adds a new row, and the run picker lists the history. A run that was in progress when the server restarted is marked failed ("Interrupted").
- **Labels:** each run is shown as Live AI, Partial fallback, Live AI unavailable — simulated, Simulated analysis or Failed investigation. Every agent also has its own stage badge.
- **Tests:** backend 110 passed / 3 skipped (SQLite), plus the PG agent and postgres tests (24 passed). e2e `ai-investigation.spec.ts` covers tab switching, reload, rerun history, citations and the mocked live, partial, failed and running states. Full Playwright 19/19; vitest 19/19.
- The UI verbosity audit for the other tabs is in `UI_VERBOSITY_AUDIT.md` (audit only, no changes).

## AI Investigation tab — frontend (2026-10-16, superseded: storage is now the database)
- **New "AI Investigation" tab** in the case workspace, second after Summary; Summary, Evidence, Historical Comparison and Review are unchanged.
- **Run AI Investigation** uses the top-bar Demo/LLM switch. It calls the existing `POST /api/cases/{id}/investigations` and is read-only for the case.
- **What the tab shows:**
  - the Lead's assessment, rationale and next step, as the most prominent element;
  - the strongest support and counterevidence;
  - the Suspicion and Alternative agents side by side, each with a conclusion and expandable verified findings, with clickable citations that open the evidence drawer;
  - missing or unresolved evidence;
  - validation counts, rejected findings and warnings.
- **Labels:** Simulated analysis · Live AI · Partial fallback · Live AI unavailable (simulated) · Failed investigation. Each stage also has its own badge: Live AI / repaired / Fell back / Simulated.
- **Storage:** results live in **server memory** and are lost when the server restarts. The tab reopens the last run for the case while the server still has it.
- **Tests:**
  - `tsc` and build clean; Vitest 19 passed.
  - Playwright 18 passed, including the new `e2e/ai-investigation.spec.ts`: a simulated run against the real backend, plus a label check using **mocked** API responses for the live, partial and failed states.

## Multi-agent investigation — milestone 1 (2026-10-16, backend only)
- `backend/services/agents.py`: the pipeline runs Suspicion agent → Alternative-explanation agent → the existing claim validator → Lead investigator.
  - The two investigators use the case-scoped read-only tools (`CaseTools`, everything except the saved-report lookup) and choose their next tool from what they have seen.
  - Only verified findings reach the Lead, which returns `suspicion_supported | concern_reduced | inconclusive | insufficient_evidence`.
  - Nothing changes case status, actions or dispositions.
- Endpoints (reviewer session required):
  - `POST /api/cases/{id}/investigations` with `{"mode": "deterministic" | "llm"}`;
  - `GET /api/investigations/{INV-…}`.
  - Results are **in memory only** for now and are lost on restart.
- Modes:
  - `deterministic` is labelled "Simulated analysis".
  - `llm` uses real OpenAI tool calling. If a call fails, that agent falls back to the simulated analysis, and the result says so.
- Tests: `tests/test_agents.py`, 7 tests, LLM parts **mocked**. Full suite 102 passed, 3 skipped (SQLite); agent tests also pass on PostgreSQL. **Not yet run against a live LLM.**
- Next: a live LLM run, persisted investigations, a frontend view, cross-examination.

## V2 status

**Checkpoint:** everything up to the Supabase connection is built and tested against a real PostgreSQL 16. Connecting to your Supabase project needs your credentials and the `psycopg` driver on your machine — see "Next step (you)" below and `docs/v2-supabase.md`. Nothing has been connected to Supabase yet, so no claim is made that the cloud integration works.

**Milestones**
1. **V2 created as a sibling folder** (`fraud-investigation-assistant-v2`).
   - Copied: source, tests, docs and config templates. Not copied: `.venv`, `node_modules`, build output, vendor archives, V1's `.env`.
   - V1's database was copied read-only (SQLite backup API; V1's file is unchanged) to `backend/data/v1-snapshot/prism-v1.db`. It holds 419 players, 56,378 transactions, 93 cases, 7,836 evidence items and 26 audit rows.
   - Ports 8100/5174. V2 was confirmed working on SQLite before migration: 81/81 backend, 19/19 Vitest, build clean, 15/15 Playwright.
2. **PostgreSQL adapter and migrations** (`database/pg.py`, `database/migrations_pg/0001–0005`).
   - The schema mirrors SQLite: same tables, keys, foreign keys, evidence IDs, snapshot references and immutability triggers.
   - New: schema `prism`, RLS on every table, `anon`/`authenticated` revoked, TLS enforced, an advisory writer lock, and reset refused on PostgreSQL.
3. **Data migration** (`python -m database.migrate_data`).
   - The V1 snapshot was copied into PostgreSQL: 66,224 rows. All 23 copied tables are **identical** (row counts and per-table content SHA-256).
   - All 93 evidence snapshot hashes were recomputed and match. 555 claim citations were checked: none point to another case.
   - A second run added 0 rows. 409 scenario labels were regenerated from the seed and match V1's `ground_truth_labels.csv` exactly.
4. **Versioned dataset.**
   - `data/dataset_spec.py` holds the version `prism-synth-2.1.0-seed42-n400`, the configuration with its SHA-256, and the scenario categories.
   - The `dataset_versions` and `scenario_labels` tables were added.
   - `data/dataset_io.py` exports CSV or Parquet with a manifest, and imports with verified hashes into an empty database without duplicates. The round trip is identical.
   - The generator logic is unchanged.
5. **Data & Methodology page** (sidebar).
   - For any reviewer: dataset version, counts, time range and scenario composition.
   - For seniors: a separated technical view with scenario labels and the evaluation.
   - Record browsing is in the existing Data Management page (senior), and identities stay in Restricted Records.
6. **Detection evaluation** (`evaluation/detection_eval.py`).
   - Development seed 42: precision 44.6%, recall 86.8%, F1 0.589, FPR 11.3%.
   - Held-out seeds 1001/2002/3003 (pooled): precision 50.9%, recall 99.3%, F1 0.673, FPR 12.2%.
   - Synthetic only and optimistic, because the rules and the simulator were co-designed.

**Tests (actually run, 2026-10-15)**

| Suite | SQLite | PostgreSQL 16 (local server) |
|---|---|---|
| Backend pytest (all suites incl. 17 new) | 95 passed, 3 skipped (PostgreSQL-only) | **98 passed** |
| New: migration copy identical + repeatable, RLS/schema/TLS, immutability, concurrent ID allocation, SQL translation, dataset round trip, labels isolation, methodology permissions, metrics | ✓ | ✓ |
| Frontend `tsc -b`, `vite build` | clean | — |
| Vitest | 19 passed | — |
| Playwright (Chromium) | **16 passed** against V2 on SQLite | **16 passed** against V2 served from PostgreSQL holding the migrated V1 data |

The 16 browser tests cover:
- the full workflow;
- dispositions with senior confirmation;
- restricted records;
- dashboard copilot;
- theme;
- sidebar;
- Scenario Lab;
- the new Data & Methodology page.

After the browser runs, the PostgreSQL database still passed every integrity check: 97 snapshot hashes and 808 claims.

**How PostgreSQL was tested here.** The build sandbox cannot download Python packages, so `psycopg` isn't available. The PostgreSQL runs used a small test-only stand-in over the system libpq (`backend/tests/support/pq_shim.py`, enabled only by `PRISM_TEST_PQ_SHIM=1`) against a real PostgreSQL 16 server. The SQL, schema, triggers, RLS and data are real. The driver layer still needs one confirmation run with real `psycopg` on your machine.

**Next step (you)** — see `docs/v2-supabase.md` → "Connecting Supabase":
1. Create the Supabase project and copy the Session pooler URI.
2. Fill V2's `.env`.
3. `pip install -r requirements-v2.txt`
4. `python -m database.check_connection`, then `python -m database.migrate_data`.

**Limitations**
- Roles are still simulated sessions, not production authentication.
- Use a direct connection or the Session pooler: the Transaction pooler does not keep `search_path`.
- Parquet export needs `pyarrow`, which is not installed here, so only CSV was tested.
- `ml/train.py` (experimental, from V1) is stale and is not part of the evaluation.
- Only Chromium was tested.

---

# V1 history (copied from V1 at the time of the split)

# PROGRESS

_Last updated: 2026-10-15 (final investigation dispositions)_

## Status summary

The FastAPI + React migration is functionally complete for the core workflow and verified end to end in a real browser. Streamlit has been removed from the running app (kept read-only in `legacy_streamlit/`).

## Final investigation dispositions (2026-10-15)

**What it adds.** An **Investigation decision** section in the Review tab, below the review workflow card. It has:
- the type of concern (Fraud / potential AML pattern / safer-gambling);
- one of four dispositions: Suspected Fraud Substantiated · Fraud Not Substantiated · Inconclusive / More Information Required · Escalate for Further Investigation;
- a required justification of at least 30 characters and at least one cited evidence item (chosen from a searchable picker);
- a confirmation summary with the status change, cited items, report version and the legal notice;
- the current decision with its approval state, and the decision history.

AML wording reads "Suspicious AML Pattern Substantiated (not proof of money laundering)". The notice reads: substantiated is the investigator's assessment, not a legal determination of guilt. "Start review" and "Reopen" stay as separate workflow actions. The UI's old Request info / Close / Escalate buttons are replaced by the dispositions, which lead to the same statuses. The old API actions still work.

**Backend (additive).**
- Migration `0004_dispositions.sql` (schema v4) adds the append-only `case_dispositions` table. No existing data is reset or changed.
- Each entry saves the case, reviewer, role, session kind, disposition, concern type, justification, cited evidence IDs, report ID and version, evidence version, evidence fingerprint, UTC time, approval status and from/to status.
- The same transaction writes a `case_actions` row (`record_disposition`, `confirm_disposition`, `return_disposition`), so the existing immutable audit trail stays the single history. The report version used is locked.
- `services/dispositions.py` with `GET/POST /api/cases/{id}/dispositions` and `POST /api/cases/{id}/dispositions/{DSP-id}/review`. Checks enforced on the server:
  - a reviewer session (no session → 401);
  - status must be Under Review or Information Requested (otherwise 409);
  - a report must exist;
  - cited evidence must belong to the case and the report's evidence version;
  - an idempotency key, and the stale-screen check (`expected_status`).
- New status **Closed — Suspicion Substantiated**.
- **Senior authorization** (reuses the reviewer roles):
  - A regular reviewer's "Substantiated" is a recommendation: the case stays open with "Awaiting senior confirmation".
  - A different senior investigator confirms (the case closes as substantiated) or returns it (the case stays under review). A later decision supersedes an unconfirmed recommendation.
  - A senior's own substantiated decision is confirmed directly.
  - Only a senior can reopen a confirmed substantiated case.
  - Other roles get 403 on every one of these. Roles come from the simulated reviewer session (a role-based demo, not real authentication).
- **Human oversight**: the copilot and report writer have no route to dispositions, and the SYSTEM account cannot sign in. A test asks the copilot to "mark this case substantiated" and checks that nothing is recorded.
- Also updated: the analytics "substantiated" count; the PDF "Final disposition" line, with the decision and the notice; the dashboard help text; queue and analytics status chips and colours.

**Verified (actually run):**

| Check | Result |
|---|---|
| Backend `pytest -q` | **81 passed** (71 existing + 10 new in `tests/test_dispositions.py`) |
| Frontend `tsc -b`, `vite build` | clean |
| Frontend `vitest run` | 19 passed |
| Playwright (Chromium) | **15 passed**. The core workflow now escalates through the decision form, with justification and evidence validation. New `e2e/decision.spec.ts`: a reviewer's substantiated recommendation → API refuses their confirmation (403) → the senior confirms → status, history and audit are checked. axe shows 0 serious/critical on the confirmation dialog. |

The backend tests cover:
- every disposition and its resulting status;
- required justification and evidence, unknown or foreign evidence, and unknown values;
- the stale-screen check (409), review-not-started (409), and no session (401);
- senior confirm, return, supersede, self-confirm blocked, and confirming only once;
- idempotent replay and the append-only triggers;
- the copilot cannot record a decision;
- the old workflow actions still work;
- reports still verify and PDF export works after a disposition.

**Limitations:**
- Roles are simulated: anyone can choose the senior reviewer.
- Recorded decisions cannot be edited. Corrections are new entries, or a reopen followed by a new decision.
- Concern type is chosen by the reviewer, not inferred.
- Only Chromium was tested.

## Database visibility, senior access, dashboard copilot, theme (2026-10-15)

**Reused:** the SQLite database and migration runner, the existing `reviewers.role` values (REV-02 Jordan Patel is "Senior investigator"), the simulated `X-Reviewer-Session` header, the append-only trigger pattern used by `case_actions`, the floating copilot window and its case-scoped API, and the Tailwind `@theme` colour tokens.

**Backend (minimal, additive):**
- Migration `0003_restricted_identity.sql` (schema v3) adds two tables and changes nothing else. `player_identities` holds **fictional** details (invented names, `@example.invalid` e-mail, `555-01xx` phone) for players with a rewards card or online account; anonymous players have none. Rows are created insert-only at startup. The existing database is migrated in place, never reset; generator, evidence snapshots and existing records are untouched. `restricted_access_log` is append-only (update/delete triggers).
- `services/restricted.py`: `require_senior()` runs on the server for every restricted request (401 without a session, 403 for Investigator/Analyst). `GET /api/restricted/records` lists only player ID, linked case IDs, record source and access counts. `POST /api/restricted/players/{id}/reveal` needs a reason of at least 15 characters, checks that the case belongs to the player, writes the access log (reviewer, role, player, case, UTC time, reason, fields revealed) and returns the details with `Cache-Control: no-store`. `GET /api/restricted/access-log` returns the log.
- `services/data_admin.py`: `GET /api/admin/summary` (counts for players, transactions, retailers, cases, alerts, audit records, plus evidence and reports) and `GET /api/admin/tables/{table}` for six whitelisted tables, with fixed columns, fixed search columns and fixed filters, all values bound, max 100 rows. No SQL text is accepted, nothing writes, and identity tables are not browsable.
- `services/guide.py` + `POST /api/guide`: deterministic dashboard help about pages, terms, priority rules and the workflow. It has no database access; questions about a specific case get a pointer to that case's copilot.
- Identity data is never read by case, evidence, findings, report, copilot, graph or analytics code, and is never written to application logs (the access log in uvicorn shows only the synthetic player ID in the path).

**Frontend:**
- **Restricted Records** and **Data Management** sidebar items appear only for the senior role. The pages have a route guard, but the API is what enforces access. A reveal opens a dialog with a case selector and a required reason; revealed details stay in page memory only (no query cache), carry a "Fictional" tag, can be hidden, and disappear when the reviewer changes.
- **Dashboard copilot**: the same floating launcher on every page except the case workspace, in "Dashboard help" mode (3 suggestions + "N more"). Inside a case the existing case-scoped, cited copilot is unchanged.
- **Light/Dark theme**: a sun/moon sliding switch (`role="switch"`) at the top right. Dark is the default; the choice is saved in `localStorage` and applied in `index.html` before first paint. Light tokens redefine the same CSS variables, so navigation, tables, cards, inputs, chips, drawers and chat switch together. Recharts colours are now CSS variables; the Cytoscape graph resolves the variables and restyles when the theme changes. Hard-coded hex colours in components were replaced with tokens. No CSS filter or inversion; reduced-motion is respected.
- Phone header: the reviewer select is narrower below 640 px so the toggle fits at 390 px.

**Verified (actually run in the sandbox):**

| Check | Result |
|---|---|
| Backend `pytest -q` | **71 passed** (63 existing + 8 new in `tests/test_restricted.py`) |
| Frontend `tsc -b` and `vite build` | clean |
| Frontend `vitest run` | 19 passed |
| Playwright (Chromium, FastAPI serving the build) | **14 passed**: 9 existing + 5 new in `e2e/senior.spec.ts` |
| axe WCAG 2.2 A/AA serious/critical | 0 in light theme (queue, Summary, Evidence, Historical Comparison, Review, case copilot, dashboard copilot, Analytics, Restricted Records, Data Management) and dark theme (Summary, Restricted Records, Data Management) |

The new tests check that:
- Investigator and Analyst sessions get 403, and no session gets 401, on every restricted and admin endpoint (direct API calls, including a forged token).
- A reveal without a reason of 15 or more characters is refused. A reveal adds exactly one log row with the reviewer, player, case, time and reason, and the log stores the fields revealed, not their values. Deleting from the log fails, and a case that belongs to another player is refused.
- After a reveal, the fictional name, surname, e-mail and phone appear nowhere in case detail, evidence, findings, history, completeness, timeline, graph, audit, queue, analytics, data management, copilot answers (demo and LLM path) or reports (LLM path). They also never appear in the messages that would be sent to the LLM, including tool results; this was checked with a stubbed LLM client.
- Admin browsing rejects unknown tables (`player_identities`, `sqlite_master`), treats injection-like filters as plain values, and does not change row counts.
- The dashboard help refuses case-specific questions without showing records, evidence or amounts, and links to the case copilot. The theme defaults to dark, toggles by keyboard, persists across reloads in both directions, and uses no filter.

**Limitations (prototype):**
- **Not production authorization.** Roles come from the simulated reviewer session: anyone can choose any reviewer, sessions do not expire, and there is no sign-in. The server-side role checks show where real authorization would go; production would need real identity (e.g. SSO), signed and expiring sessions, and access policy outside the app.
- Denied attempts (401/403) are not written to the access log; only successful reveals are.
- Identity search covers player and case IDs only, by design (no search by name).
- The other existing case endpoints still do not require a session, as before this change.
- The dashboard help is rule-based and only knows the topics written in `services/guide.py`. LLM mode against a real model was not run here.
- Only Chromium was tested. No manual screen-reader pass was done.

## Verification (earlier, 2026-10-15)

| Check | Result |
|---|---|
| Backend `pytest -q` | **45 passed** (incl. 4 FastAPI TestClient tests that were previously skipped) |
| Frontend `tsc -b` | clean |
| Frontend `vite build` | clean, no chunk warnings (vendor split into react / ui / charts / graph) |
| Frontend `vitest run` | **8 passed** |
| FastAPI started, serving built React | `/api/health` OK; no 4xx/5xx in the server log during E2E |
| Playwright E2E (Chromium 1194, 1440×900) | **3 passed**: 14-step workflow, 390 px phone layout, relationship explorer |
| axe-core WCAG 2.2 A/AA (serious/critical) | 0 violations on queue, workspace with drawer open, explorer |
| Browser console errors during E2E | none (Google Fonts requests are blocked on purpose in the sandbox and excluded by URL) |
| Grounding measurement | 83 cases → 3,565 deterministic claims, all verified; copilot 72 answers / 314 claims, all verified (see docs/evaluation.md) |

The 14 E2E steps: queue loads → search filter → simulated reviewer → Scenario lab creates a case → generate report → 11 sections with verification → citation opens drawer with that evidence → Back to report restores focus → Ask AI returns cited answer → start review → short note rejected → escalate + persistence after reload → audit row has report version, evidence hash, report locked → PDF export is a real PDF.

### Not verified here (and why)

- **LLM mode** against a real model: the sandbox cannot reach OpenAI and the real key stays on your machine. Covered only by monkeypatched tests. Try it locally with `.env` set.
- **Firefox/WebKit**: only Chromium is installed here.
- **Windows run of `scripts/dev.py`**: written for Windows paths but only exercised on Linux here.
- Keyboard-only and screen-reader passes were not done manually; axe and focus-return are automated.

## Clarity and readability pass (2026-10-15)

**What changed (presentation only; no detection rule, score, history value or stored record changed):**
- `backend/services/findings.py` + `GET /api/cases/{id}/findings`: one finding per indicator in three levels (headline + change + comparison → evidence → calculation & sources). Every number is read from the case's stored evidence; ratios reuse the stored detection ratios and are suppressed when the detection denominator was clipped.
- Every finding's plain sentences run through the **same deterministic validator as report claims** at request time; each card shows its verified status.
- Zero baselines: percentages compare in **percentage points** ("Increase: 74.2 percentage points"); "no previous records" ("Insufficient previous activity to establish a typical pattern.") is distinct from "observed zero"; period lengths (23 vs 7 days) and normalization are stated in the details.
- Plain labels (`config.PLAIN_FACTOR_LABELS`, `config.TERMS`, `claims.PLAIN_SECTION_LABELS`), technical names kept in tooltips and "Calculation & sources".
- Report: section 4 is rendered as finding cards with each report statement inside its card; reference sections (supporting records, comparisons, related entities, alternatives, missing info) are collapsible and show their statement count and any unverified count; non-triggered indicators are behind "Also checked: within the normal range".
- Report writer (new versions only; locked versions unchanged): plain wording; comparisons already shown with a finding are no longer repeated in "Compared with previous activity"; average/largest and busiest-hour sentences are not repeated in "What happened" when the matching finding exists. Prompt version `det-2`.
- Evidence drawer: friendly field names, "Not recorded" instead of "—", "Data sources" / "Evidence version", raw field names and provenance under "Technical details". Bare "—" placeholders removed app-wide.
- Workspace: side menu collapses behind the toggle below 1536 px on case pages so the report column has room; comparison bars stack under their labels.

**Verified:** pytest 58 passed (13 new in `tests/test_findings.py`); Vitest 12 passed (4 new); `tsc -b` and `vite build` clean; Playwright 4 passed (new: key findings three levels on CASE-18009, keyboard disclosure, record → drawer → focus return, technical details, "Also checked", axe with cards expanded, no horizontal overflow). All 540 findings across 90 cases pass the validator; all 3,613 report statements across 90 regenerated reports verify.

**Found and fixed during this pass:** the validator rejected 112 of my first-draft finding sentences (e.g. "95% of amounts" quoted a definition, "0 new cities" tripped the novelty check, "$20" rule constant) — reworded rather than relaxing the validator. axe caught invalid `<dl>` structure in the comparison bars.

**Not done / remaining:** copilot answers still use some technical wording ("baseline"); no case in the current data has insufficient previous activity, so that state is covered by backend and component tests only; PDF uses the new plain section headings but does not include the finding cards.

## Done

- Backend: config/branding, UTC time handling, v2 synthetic world (anonymous vs. account-based, curated cases, jackpot week, decoys), monitoring/alerts, migrations with immutability triggers, evidence registry + snapshot hashes, priority, structured claims + validator, deterministic writer, LLM path with one repair and labelled fallback, case-scoped query tools, copilot with context, workflow state machine + idempotency + locking, graph, PDF export, Scenario lab, analytics, FastAPI layer.
- Frontend: app shell (mode switch, simulated session, nav, disclaimer), queue, workspace (evidence/report/copilot/decision; 3-col ≥1280, 2-col ≥900, tabs below), citation → drawer → timeline/graph sync → focus return, relationship explorer, reports & history, scenario lab, analytics, Obsidian theme tokens, reduced motion.
- Tests: backend suite, Vitest units, Playwright E2E + axe.
- Docs: README, docs/architecture.md, docs/evaluation.md, docs/demo-scenarios.md, .env.example, .gitignore.

## Fixed in this session

- Two TypeScript errors (Cytoscape collection typing; `assigned_reviewer` is an object in case detail).
- Analytics JSX fragment error.
- **Copilot did not understand plural "retailers"/"stores"/"locations"** — found by E2E; fixed + regression tests.
- **Accessibility:** Recharts adds unlabeled `role="img"` to every scatter point (54 axe violations). Chart graphics are now `aria-hidden` with a screen-reader description and the equivalent list/table.
- **Phone layout:** header overflowed by 203 px at 390 px; reviewer select, logo text and mode switch now compact below `sm`.
- Removed unused imports/props (copilot.py, generator.py, ReportPanel).

## Remaining / nice to have

- Workspace at 1280–1440 px is tight with the sidebar; consider collapsing the sidebar in the workspace.
- Timeline chart legend text is slightly clipped at the top of the chart.
- Session is per-tab (sessionStorage); a new tab asks for a reviewer again.
- Graph node positions are not persisted between visits.
- No multi-user concurrency testing beyond the expected-status 409 check.

## Dependency notes

- npm and PyPI are blocked from the build sandbox. Packages came from `scripts\setup-windows.ps1 -BundleForClaude` on your machine (Windows node_modules + Linux native binaries for esbuild 0.25.12, rollup 4.64.7, lightningcss 1.32.0, tailwind oxide 4.3.3; cp313 manylinux wheels).
- Resolved versions: FastAPI 0.143.1, Pydantic 2.x, pandas 3.0, React 19.3.1, react-router 7.18.4, TanStack Query 5.104, Recharts 2.15.4, Cytoscape 3.34.3, Tailwind 4.3.3, Vite 6.4.4, TypeScript 5.8.3, Vitest 3.2.7, Playwright 1.56.0.
- `frontend/package-lock.json` exists in your Windows folder (created by the setup script); commit it so installs are reproducible.
- Your folder layout (synced 2026-10-15): old Streamlit files moved into `legacy_streamlit/` (nothing deleted); `.env`, `.venv`, `vendor/` and `frontend/node_modules` untouched. `vendor/prism-sync.tgz` is the sync bundle and can be deleted.

## Run commands

```bash
pip install -r requirements.txt && (cd frontend && npm install)
python scripts/dev.py                 # API :8000 + React :5173
python scripts/dev.py --prod          # build + serve everything from :8000
cd backend && python -m pytest -q
cd frontend && npm test && npm run build && npm run e2e
```

## AI Investigation consistency review (2026-10-16, CASE-18016 live run INV-2f790604b4)
- Added `cross_check` (agents.py), run after the evidence validator and before the Lead. It is deterministic and reads only the case's own evidence.
- It rejects a finding that:
  - misreads a context event's `subject_share_pct` as a share of network transactions;
  - claims history is unavailable when a verified baseline exists (asking for history beyond the baseline is allowed);
  - denies anomalies that fired indicators record.
- Context-event counterevidence gets `cross_checks` notes: "possible, not verified", how much of the activity falls on the event days, and whether the peak burst is outside the event. If the event covers under half of the activity, the weight is lowered to weak.
- `lead_justification` flags, but never overrides, a concern_reduced with no strong counterevidence that covers the main pattern.
- Prompt changes:
  - Agents: ordinary explanations are possible, not verified; baseline counts as history; anomalies are never denied.
  - Lead: a possible explanation that does not cover the main pattern doesn't reduce concern; a one-sentence lead (30 words max); a one-sentence next step (25 words max).
- Tool description: defines `subject_share_pct`.
- UI: shows the cross-check notes under the finding.
- Regression fixture: `backend/tests/fixtures/agents_case18016.json`.
