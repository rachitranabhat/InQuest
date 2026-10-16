# Evaluation (measured, synthetic data only)

Measured on 2026-10-15 against the default dataset (seed 42, 400 players + curated subjects, 55,567 transactions, 83 monitoring cases). These figures describe the prototype on **its own simulator**; the rules were written alongside the simulator, so they are not evidence of real-world detection performance.

## Report grounding

| Check | Result |
|---|---|
| Deterministic reports generated for all 83 monitoring cases | 3,565 claims, **3,565 verified, 0 unverified** |
| Copilot: 9 suggested questions × 8 curated cases (demo mode) | 72 answers, 314 claims, **314 verified**, 0 unmapped questions |

This shows the deterministic writer and the validator agree. It is a consistency check, not a measure of LLM quality. The validator's ability to *reject* bad claims is covered by unit tests (invented IDs, invented places, wrong totals, wrong dates, aggregate claims without aggregate evidence, accusatory wording, absence-as-proof, wrong qualifiers, citations from another case).

LLM mode was **not** evaluated in this environment (no API access from the build sandbox). With a key, LLM claims pass through the same validator; the tests use a monkeypatched model to confirm invented facts are marked unverified and that fallbacks are labelled.

## Alerts vs. the simulator's planted labels

Ground truth is in `backend/data/ground_truth_labels.csv` and is never read by detection or shown as evidence.

| | Alerted | Not alerted |
|---|---|---|
| Planted suspicious subjects (41) | 36 | 5 |
| Non-suspicious subjects (368) | 47 | 321 |

Missed: 3 of 12 multi-location and 2 of 6 night-activity subjects. Most non-suspicious alerts come from profiles deliberately designed to look unusual (13 of 34 benign spikes, 19 of 38 busy legitimate players) plus the curated ambiguous cases; 9 of 290 ordinary players alerted. PRISM's job is to make those cases fast to review and easy to close, not to remove them.

## Test suites (2026-10-15)

| Suite | Result |
|---|---|
| Backend pytest | 45 passed |
| Frontend Vitest | 8 passed |
| TypeScript `tsc -b` + Vite production build | passed, no warnings |
| Playwright E2E (Chromium, against FastAPI serving the build) | 3 passed: 14-step workflow, phone width (390 px, no horizontal scroll), relationship explorer |
| axe-core (WCAG 2.2 A/AA, serious + critical) on queue, workspace with drawer open, explorer | 0 violations |

## Plain-language findings (2026-10-15)

| Check | Result |
|---|---|
| Findings generated (6 indicators × 90 cases) | 540 |
| Finding sentences passing the report-claim validator | **540 / 540 findings verified** (headline, change, usual, recent: 4 sentences each) |
| Reports regenerated with the plain-language writer (det-2) | 90 reports, 3,613 statements, **3,613 verified** |
| Re-applied rule ramp vs. stored indicator share | matches within 0.02 for every scored finding (test) |
