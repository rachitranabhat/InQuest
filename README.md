# INQUEST

### One Alert. Multiple Perspectives. Verified Evidence.

**An explainable, AI-assisted fraud investigation prototype for gaming and lottery transactions.**  
Built for **ThunderHacks II — OLG: Intelligent Player Protection & Fraud Detection**.

INQUEST helps investigators move from *an alert* to *an evidence-backed review*. Instead of treating unusual activity as proof of fraud, the system combines transparent behavioral monitoring, competing AI investigations, deterministic evidence checks, and human oversight.

> **Demo and research prototype.** All case and transaction data are synthetic. INQUEST does not determine whether a person committed fraud, and its scores are not probabilities of fraud. It is not a production compliance or player-protection system.

## Why INQUEST?

Unusual activity does not always mean wrongdoing. A burst of lottery purchases could merit investigation, but context such as a promotion or jackpot may matter. A high spending deviation is an *alert*, not a verdict.

INQUEST is designed to help investigators answer three questions:

1. **What changed?** Explainable rules show how recent activity differs from the subject's history.
2. **What does the evidence support?** Two AI agents actively examine competing interpretations.
3. **What should happen next?** Validated findings inform a provisional assessment; a human reviewer makes the decision.

## Key features

- **Transparent 0–100 behavioral score** from transaction-level rules and historical comparisons.
- **Case prioritization** using score bands, number of triggered indicators, recent activity, and evidence completeness.
- **Two complementary investigation agents:** Suspicion Agent and Alternative Explanation Agent.
- **Case-scoped, read-only evidence tools** for AI investigations.
- **Deterministic checks** for evidence references, numerical claims, and selected inconsistencies.
- **Lead AI synthesis** with provisional outcomes such as *suspicion supported*, *concern reduced*, *inconclusive*, or *insufficient evidence*.
- **Human-in-the-loop workflow**, saved investigation runs, and review history; substantiated findings require senior confirmation in the demo workflow.
- **Synthetic lottery and online-account scenarios** that make the workflow demonstrable without real customer information.

## How it works

```text
Synthetic transaction records
          |
          v
Feature engineering and historical comparison
          |
          v
Deterministic monitoring rules -> Risk score and alert -> Case priority
                                                         |
                                                         v
                                            Case-scoped evidence tools
                                                         |
                          +------------------------------+-----------------------------+
                          |                                                            |
                          v                                                            v
                   Suspicion Agent                                          Alternative Explanation Agent
                          |                                                            |
                          +------------------------------+-----------------------------+
                                                         |
                                                         v
                                      Evidence and consistency validation
                                                         |
                                                         v
                                             Lead AI provisional assessment
                                                         |
                                                         v
                                          Human investigator / senior review
```

The detection score and the AI assessment are **separate**. AI agents do not alter detection rules, case scores, or case status.

## Detection rules

The scoring engine contains seven defined rules. **Six apply to an individual case**, because lottery cases use the location/retailer rule while online-account cases use the play-through rule.

| Indicator | What is examined | Maximum points |
| --- | --- | ---: |
| Transaction frequency | Transactions per day and busiest 60-minute period versus baseline | 25 |
| Transaction value | Average amount and largest amount versus historical values | 20 |
| New locations / retailers *(lottery only)* | Cities and retailers not observed in the baseline | 20 |
| Money withdrawn with little play *(online only)* | Withdrawal-to-deposit ratio and deposits not wagered | 20 |
| Unusual timing | Increase in activity between midnight and 4:59 AM | 10 |
| Historical spending change | Seven-day spend versus expected spend from baseline | 15 |
| Repeated transactions | Transactions within two minutes and repeated identical amounts | 10 |
| **Maximum per case** | | **100** |

### Time windows and scoring

For the synthetic dataset supplied with this prototype, the monitoring simulation ends **October 14, 2026**:

- **Review period:** October 8–14 (7 days)
- **Historical baseline:** September 15–October 7 (23 days)
- **Expected weekly spending:** baseline total / 23 × 7

For most indicators, points scale linearly between an initial threshold and a threshold for full points:

```text
points = max_points * clamp((observed - start) / (full - start), 0, 1)
```

An indicator is considered triggered once it reaches at least 25% of its maximum points. The overall risk score is the sum of rule points, capped at 100.

| Score | Risk band |
| ---: | --- |
| 80–100 | Critical |
| 60–79.9 | High |
| 30–59.9 | Medium |
| Below 30 | Low |

Monitoring creates an alert for **behavioral deviation at a score of at least 20**, or for **40 or more linked purchases in seven days**, even if the score is lower. Priority can differ from the risk band; for example, triggering at least four indicators raises priority by one level.

**Important:** 76.7/100 means strong deviation under these configured rules—not a 76.7% likelihood of fraud.

### What role does machine learning play?

Operational scoring is **rule-based**, not generated by an LLM. An unsupervised **Isolation Forest** anomaly value is computed and retained as a supplementary signal, but contributes **zero points** to the operational 0–100 score. A Random Forest implementation exists in the codebase but is not part of the live case-scoring path.

This separation keeps the monitoring score interpretable and lets investigators trace points back to rule inputs.

## Why two AI agents instead of one?

A single model can summarize a suspicious case, but it can also reinforce the initial alert without sufficiently testing alternative explanations.

INQUEST assigns two explicit roles:

- **Suspicion Agent:** examines the evidence that supports concern, including abnormal amounts, bursts, timing, and patterns.
- **Alternative Explanation Agent:** actively looks for benign context, contradictory evidence, and information gaps.

The results pass through **deterministic evidence validation and cross-checking** before a **Lead AI** synthesizes a provisional assessment. This approach encourages structured disagreement and better traceability; it does **not** guarantee impartial or correct conclusions. Demonstrating superiority over a one-agent design would require controlled evaluation.

## Example investigation

In the synthetic **CASE-18016**:

- The busiest hour contains **12 transactions**, compared with a historical baseline of **1.42**.
- Average transaction value rises to **$90.10**, versus **$12.44** historically.
- Seven-day spending is **$3,333.66**, versus **$185.46** expected.
- The system finds **12 identical $250 transactions** and activity in one new city.
- The rule score is **76.7 (High)**, while multiple triggered indicators elevate investigation **priority to Critical**.

This case illustrates why a score must lead to review rather than an automatic fraud decision: contextual explanations must be checked against the actual records and their scope.

## Tech stack

| Layer | Technology |
| --- | --- |
| Frontend | React, TypeScript, Vite |
| Backend/API | Python, FastAPI |
| AI investigation | OpenAI API, structured case-scoped tools |
| Detection and analytics | Python, deterministic rules, scikit-learn Isolation Forest |
| Data storage | PostgreSQL / Supabase (cloud); local database option for development |
| Deployment | Vercel (frontend), Render (API) |
| Source control | Git, GitHub |

## Repository layout

The principal application areas are:

```text
frontend/                   React / TypeScript investigator interface
backend/api/                FastAPI routes and application
backend/database/           Database adapters, connection checks, migration utilities
backend/detection/          Features, anomaly analysis, monitoring and risk scoring
backend/services/           Application and priority services
backend/tests/              Backend tests
```

> The layout above highlights major areas rather than listing every file. Inspect the repository for the exact module structure.

## Local development

**Requirements:** Python 3.12+, Node.js, npm, and an OpenAI API key for live AI investigations.

```powershell
# From the repository root, create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install Python dependencies
pip install -r requirements-v2.txt

# Install frontend dependencies
cd frontend
npm install
```

Set the backend's environment variables in your local, ignored `.env` file. Example variable names:

```dotenv
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gpt-4o-mini
PRISM_DB_BACKEND=postgres
DATABASE_URL=postgresql://USER:URL_ENCODED_PASSWORD@HOST:5432/postgres?sslmode=require
PRISM_DEMO_ACCESS_CODE=replace_with_demo_access_code
PRISM_LLM_DAILY_LIMIT=40
PRISM_CORS_ORIGINS=http://localhost:5173
```

**Never commit `.env`, API keys, connection passwords, or access codes.** Use a PostgreSQL `sslmode=require` connection and verify the certificate/security requirements appropriate to your environment.

From `backend/`, verify a PostgreSQL connection before running any database initialization:

```powershell
python -m database.check_connection
```

If setting up a new, **intended and empty** database, review the migration script and use the project's existing migration command:

```powershell
python -m database.migrate_data
```

**Start the API** from the repository root:

```powershell
uvicorn api.main:app --app-dir backend --reload
```

**Start the frontend** in another terminal:

```powershell
cd frontend
npm run dev
```

The exact environment and local-database settings may depend on the checked-out revision. Consult the included configuration and scripts before modifying a populated database.

## Validation and tests

```powershell
# From the repository root, with the virtual environment active
python -m pytest -q backend/tests
```

A PostgreSQL TLS check can also be run with:

```powershell
cd backend
python -m database.check_connection
```

Live agent calls require a valid API key and may incur API usage charges. Offline unit tests should not require making live model calls unless explicitly configured.

## Deployment notes

The intended cloud deployment uses:

- **Vercel** for the React application.
- **Render** for the FastAPI application.
- **Supabase PostgreSQL** for shared persistent case and investigation records.

The frontend must point to the deployed backend; configure the API's allowed CORS origins to match the real frontend domain. Configure all credentials and database URLs as secret environment variables on the hosting platforms. Do not assume an online demo is available until health checks and case loading have been verified.

## Evaluation and limitations

- The current scenarios are **synthetic**, not OLG customer records.
- The risk score is an **explainable anomaly prioritization score**, not a calibrated fraud probability.
- The available held-out synthetic evaluation reported approximately **50.9% precision** and **99.3% recall** for the rules, but these figures may be optimistic because the simulator and rules were developed together; they are **not real-world performance claims**.
- Anonymous lottery transactions are **excluded from personal risk scores** and surfaced only as a data limitation. Short historical baselines also limit which indicators can be scored.
- Evidence may lack identity, intent, retailer, device, network, or payment information.
- Evidence validation checks defined classes of errors; it cannot guarantee that every AI inference is correct.
- The demonstration review/access-code flow is **not enterprise authentication or authorization**.
- Any production adoption would require domain review, independent benchmarking, privacy/security controls, and regulatory assessment.

## What comes next

- Evaluate on independently sourced, appropriately authorized datasets.
- Benchmark one-agent versus two-agent investigations under controlled conditions.
- Measure reviewer time, false-positive handling, evidence quality, and decision consistency.
- Expand authorized evidence sources and strengthen access controls and auditability.
- Calibrate thresholds with fraud, AML, and responsible-gaming experts rather than relying on synthetic scenarios alone.

## Hackathon

**ThunderHacks II**  
**Challenge:** OLG — Intelligent Player Protection & Fraud Detection  
**Repository:** https://github.com/rachitranabhat/fraud-investigation-assistant-v2

Built as a hackathon demonstration of **human-centered, evidence-grounded AI investigation**.
