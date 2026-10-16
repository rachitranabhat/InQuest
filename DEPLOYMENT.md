# INQUEST: public deployment (Vercel + Render + Supabase)

```
Browser ──▶ Vercel (React build, frontend/dist) ──/api/* rewrite──▶ Render (FastAPI) ──▶ Supabase PostgreSQL (schema "prism")
                                                                     └──▶ OpenAI API (key on Render only)
```

The browser only ever calls `/api` on the Vercel domain. Vercel forwards those calls to Render.

* No API URL is built into the frontend, so no `VITE_*` variable is needed.
* CORS is still set to the exact Vercel origin (no wildcard).

## Settings

**Vercel** (project root `frontend/`; `frontend/vercel.json` is already in the repo):

| Setting | Value |
|---|---|
| Framework preset | Vite |
| Root directory | `frontend` |
| Build command | `npm run build` |
| Output directory | `dist` |
| Install command | `npm install` (default) |
| Environment variables | none |

* `vercel.json` sends `/api/*` to `https://inquest-api.onrender.com`. If your Render URL is different, change that one line.
* Every other path goes to `index.html`, so direct visits such as `/cases/CASE-18016` work.

**Render** (web service; `render.yaml` at the repo root):

| Setting | Value |
|---|---|
| Runtime | Python 3 (`PYTHON_VERSION=3.12.7`) |
| Root directory | *(repo root)* |
| Build command | `pip install -r requirements-v2.txt` |
| Start command | `uvicorn api.main:app --app-dir backend --host 0.0.0.0 --port $PORT --workers 1` |
| Health check path | `/api/health` |

**Render environment variables** (enter values in the dashboard; never commit them):

| Name | Purpose |
|---|---|
| `PRISM_DB_BACKEND` | `postgres` |
| `DATABASE_URL` | Supabase **Session pooler** URI ending in `?sslmode=require` |
| `OPENAI_API_KEY` | live AI agents (server-side only) |
| `OPENAI_MODEL` | `gpt-4o-mini` |
| `PRISM_CORS_ORIGINS` | exact Vercel URL, e.g. `https://<project>.vercel.app` |
| `PRISM_DEMO_ACCESS_CODE` | shared code needed to start a reviewer session |
| `PRISM_LLM_DAILY_LIMIT` | live-AI requests allowed per UTC day (e.g. `40`) |

## Supabase

* Use **Connect → Session pooler** (port 5432, IPv4). Do not use the transaction pooler: INQUEST uses session settings and advisory locks.
* Tables live in schema `prism`. Row-level security is on and the `anon`/`authenticated` roles have no access, so the Supabase Data API exposes nothing.
* Do not use the `anon` or `service_role` keys anywhere.
* On start, the backend applies migrations 0001–0006 (0006 adds saved investigations).
* It builds the synthetic dataset **only if the database is empty**. It never resets or overwrites data.
* **Seed before launch:** run `python -m database.migrate_data` once from your PC, so Render doesn't spend its first start generating 55k rows.

## Access model (demo)

* Reviewer sessions are **simulated**. Anyone holding the access code can act as any listed reviewer, including the senior one. This is demo access control on synthetic data, not real authentication.
* Without a session (no code), visitors can **read** cases, evidence and saved reports. They cannot generate reports, use the copilot, run investigations, record decisions or bookmarks, run scenarios, or reveal identities. The server returns 401.
* Live AI (reports, copilot, investigations in LLM mode) requires a session and is capped per day by `PRISM_LLM_DAILY_LIMIT`; over the cap the server returns 429. Demo mode is never capped.
