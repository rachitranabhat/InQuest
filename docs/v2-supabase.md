# PRISM V2 — Supabase PostgreSQL, versioned dataset, evaluation

V2 is an experimental copy of PRISM in `fraud-investigation-assistant-v2`. V1 (`fraud-investigation-assistant`) is untouched and keeps running on SQLite.

## V1 vs V2

| | V1 | V2 |
|---|---|---|
| Folder | `fraud-investigation-assistant` | `fraud-investigation-assistant-v2` (sibling) |
| Ports | API 8000 · Vite 5173 | API **8100** · Vite **5174** |
| Database | SQLite `backend/data/prism.db` | SQLite (default) **or** PostgreSQL / Supabase (`PRISM_DB_BACKEND=postgres`) |
| Schema | migrations 0001–0004 | same + 0005 (`dataset_versions`, `scenario_labels`); PostgreSQL copy in `database/migrations_pg/` |
| Dataset | seed 42, unversioned labels CSV | same generator and rows, plus a named version (`prism-synth-2.1.0-seed42-n400`), labels in the database, CSV/Parquet export and verified import |
| Evaluation | alert-vs-label counts in docs | precision / recall / F1 / FPR / confusion matrix on held-out seeds |
| Extra page | — | **Data & Methodology** (sidebar) |
| `.env` | its own | its own (`.env.example` in V2) |

## Architecture

```
React (5174) ──/api──▶ FastAPI (8100) ──▶ services (role checks, case-scoped tools) ──▶ database/db.py
                                                                                        ├─ SQLite file
                                                                                        └─ database/pg.py → PostgreSQL (schema "prism")
```

* The frontend and the AI never reach the database directly. The copilot keeps its approved, case-scoped, read-only query tools.
* `database/pg.py` is the adapter. It gives a psycopg 3 connection the sqlite3 API the services already used, so business logic was not rewritten:
  * `?` → `%s`;
  * `INSERT OR IGNORE`, `GROUP_CONCAT`, `json_extract`, `IS [NOT] ?` and case-insensitive `LIKE` are translated;
  * rows behave like `sqlite3.Row`.
  
  Source changes were needed in four places only: two `INSERT OR REPLACE` upserts, one `ORDER BY` alias, and the ID counter, which is now an atomic `INSERT … ON CONFLICT … RETURNING`.
* **Transactions:** `tx()` takes a transaction-scoped advisory lock, which reproduces SQLite's `BEGIN IMMEDIATE` (one writer at a time). The existing status checks, idempotency keys and ID allocation therefore keep their guarantees. A concurrency test confirms there are no duplicate IDs.
* **Kept from V1:** primary keys, foreign keys, evidence IDs, snapshot references and the immutability triggers. They are PL/pgSQL trigger functions with the same messages.
* **Timestamps** stay ISO-8601 UTC text, so fingerprints and stored values are byte-identical across backends.
* **Security on PostgreSQL:**
  * Tables live in schema `prism`, not Supabase's exposed `public`.
  * Row-level security is enabled on every table with no policies, and `anon`/`authenticated` are revoked. The Supabase Data API therefore sees nothing.
  * TLS (`sslmode=require`) is forced for any non-local host, and `sslmode=disable` is refused.
  * Credentials come only from V2's `.env`. They are never logged and never sent to React.
  * `pipeline.py reset` refuses to run against PostgreSQL.
* Roles are still the simulated reviewer sessions (a role-based demo, not production authentication). Every permission is checked in the backend.

## Synthetic dataset

| | Count (seed 42, 400 players + curated) |
|---|---|
| Synthetic players | 409 (+ Scenario Lab subjects added at run time) |
| Transactions | 55,567 (46,597 lottery terminal, 8,970 online account; 32,710 attributed, 22,857 anonymous) |
| Retailers / terminals / locations | 120 / 182 / 15 |
| Online accounts | 111 |
| Monitoring alerts = cases | 83 |
| Time range (UTC) | 2026-09-15 05:15 → 2026-10-15 03:56 (23-day history + 7-day review window) |

**Scenario categories** (`data/dataset_spec.py`). These are planted simulation facts, not findings:

| Group | Categories and counts |
|---|---|
| Normal and explainable | normal 290 · explainable high volume 39 · explainable spike 34 · explainable context event (jackpot week) 1 |
| Ambiguous or incomplete | ambiguous shared location 2 · ambiguous 1 · incomplete data 1 |
| Planted suspicious (41 in total) | location 12 · combined 7 · time 6 · frequency 5 · spending 4 · repeated amounts 3 · behaviour shift 3 · **AML-like pass-through 1** |

The AML-like pass-through is on an online account, the only place the data has deposits and withdrawals. It is labelled "not proof of money laundering".

Ground truth (`scenario_labels`) is separate from investigator-facing risk classifications:
* detection, evidence, reports and the copilot never read it, and a test enforces this;
* only the evaluation module and the senior-only technical view read it.

```bash
cd backend
python -m data.dataset_io export --out ../datasets/synth              # CSV + manifest.json (hashes, config, counts)
python -m data.dataset_io export --out ../datasets/synth --format parquet
python -m data.dataset_io import ../datasets/synth                    # into an EMPTY database; verified; never duplicates
```

Same version, seed and configuration reproduce identical rows. A test round-trips export → import, and the cases and evidence fingerprints come out equal.

## Detection evaluation (synthetic data only)

`python -m evaluation.detection_eval` (from `backend/`) evaluates the rule-based monitoring.

* **Unit:** a synthetic player, who either received an alert or not, compared with whether the simulator planted a pattern.
* **Leakage controls:**
  * Seed 42 is the development set, because the rules were written against it.
  * The headline figures come from held-out seeds 1001, 2002 and 3003, generated fresh.
  * Labels are joined only after monitoring has run.
  * Nothing is trained.
  * Curated demo subjects are reported separately.

Measured 2026-10-15 (population, n = 400 per world):

| Set | Precision | Recall | F1 | False-positive rate | TP / FP / FN / TN |
|---|---|---|---|---|---|
| Development (seed 42) | 44.6% | 86.8% | 0.589 | 11.3% | 33 / 41 / 5 / 321 |
| Held-out pooled (3 seeds, n = 1,200) | 50.9% | 99.3% | 0.673 | 12.2% | 135 / 130 / 1 / 934 |

Most false positives come from subjects designed to look unusual for legitimate reasons. On seed 42, 19 of 38 busy-legitimate players and 13 of 34 benign spikes were alerted, against 9 of 290 normal players.

**Caveat:** the simulator and the rules were designed together, so these figures are optimistic. They are not evidence of real-world or production performance.

## Running V1 and V2 side by side

```powershell
# V1 (unchanged)
cd fraud-investigation-assistant;    .venv\Scripts\activate; python scripts\dev.py     # http://localhost:5173
# V2 (own venv, own .env)
cd fraud-investigation-assistant-v2
py -m venv .venv; .venv\Scripts\activate
pip install -r requirements-v2.txt
cd frontend; npm install; cd ..
copy .env.example .env               # then edit (SQLite by default)
python scripts\dev.py                # http://localhost:5174  (API :8100)
```

## Connecting Supabase (needs you)

1. Sign in at supabase.com, then choose **New project**. Choose a name and region, and set a **database password**. Keep the password in your password manager.
2. When the project is ready, click **Connect** (top bar), then **Session pooler**, and copy the URI. It looks like `postgresql://postgres.<ref>:[YOUR-PASSWORD]@aws-0-<region>.pooler.supabase.com:5432/postgres`.
3. In `fraud-investigation-assistant-v2\.env`, set `PRISM_DB_BACKEND=postgres` and set `DATABASE_URL=<that URI with your password>?sslmode=require`. Do not paste the `anon` or `service_role` keys anywhere; PRISM does not use them.
4. With the V2 venv active, run these from `backend\`:
   * `python -m database.check_connection`: this is read-only and should say "TLS: yes".
   * `python -m database.migrate_data`: copies V1's snapshot into Supabase and prints a per-table "identical" check. It is safe to run again; it adds nothing the second time.
     * Or, for a fresh dataset instead: `python pipeline.py build`.
5. Run `python scripts\dev.py` and open http://localhost:5174. The Data & Methodology page shows "stored in PostgreSQL".

To run the backend tests against Supabase, use a **separate, throwaway** Supabase project (never the one with your data): set `PRISM_TEST_BACKEND=postgres`, `PRISM_TEST_DATABASE_URL=<that project's URI>` and `PRISM_TEST_DISPOSABLE_DATABASE=1`, then `python -m pytest -q`. The suite drops and rebuilds that project's `prism` schema.
