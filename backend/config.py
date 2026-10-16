"""Central configuration for the PRISM / Casefile investigation copilot prototype.

Everything here is a *prototype* setting. None of these values reflect any real
organisation's thresholds, scoring methodology or monitoring rules.
Branding (name, tagline, disclaimer) lives in ../branding.json.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent          # backend/
REPO_ROOT = ROOT.parent
DATA_DIR = Path(os.getenv("PRISM_DATA_DIR", ROOT / "data"))
DB_PATH = Path(os.getenv("PRISM_DB_PATH", os.getenv("FIA_DB_PATH", DATA_DIR / "prism.db")))
GROUND_TRUTH_CSV = DATA_DIR / "ground_truth_labels.csv"   # never served to the investigator UI
ML_ARTIFACT_DIR = ROOT / "ml" / "artifacts"
EXPORT_DIR = Path(os.getenv("PRISM_EXPORT_DIR", DATA_DIR / "exports"))
BACKUP_DIR = DATA_DIR / "backups"
BRANDING_PATH = REPO_ROOT / "branding.json"
ENV_PATHS = [REPO_ROOT / ".env", ROOT / ".env"]

DOTENV_ENABLED = os.getenv("PRISM_DISABLE_DOTENV", "") != "1"   # tests disable .env so they never use a real key

try:  # optional dependency
    from dotenv import load_dotenv

    for _p in (ENV_PATHS if DOTENV_ENABLED else []):
        if _p.exists():
            load_dotenv(_p)
except Exception:  # noqa: BLE001
    pass

# ---------------------------------------------------------------------------
# V2 persistence: "sqlite" (default, same as V1) or "postgres" (Supabase or any PostgreSQL 14+).
# DATABASE_URL is read from the environment / V2's own .env only; it is never sent to the browser.
# ---------------------------------------------------------------------------
DB_BACKEND = os.getenv("PRISM_DB_BACKEND", "sqlite").strip().lower()
if DB_BACKEND not in ("sqlite", "postgres"):
    raise ValueError("PRISM_DB_BACKEND must be 'sqlite' or 'postgres'")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


def branding() -> dict:
    try:
        return json.loads(BRANDING_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"product_name": "INQUEST", "tagline": "Evidence-grounded investigation platform",
                "display_timezone": "America/Toronto", "disclaimer": "Synthetic data only."}


DISPLAY_TZ = branding().get("display_timezone", "America/Toronto")

# ---------------------------------------------------------------------------
# Synthetic data settings
# ---------------------------------------------------------------------------
RANDOM_SEED = int(os.getenv("PRISM_SEED", os.getenv("FIA_SEED", "42")))
N_CUSTOMERS = int(os.getenv("PRISM_N_PLAYERS", os.getenv("FIA_N_CUSTOMERS", "400")))
N_RETAILERS = 120
SIM_END = datetime(2026, 10, 14, 23, 59, 59)   # local (display-timezone) end of the simulation
HISTORY_DAYS = 23                               # baseline period
WINDOW_DAYS = 7                                 # review window

# ---------------------------------------------------------------------------
# Prototype alert scoring (max points per factor, total = 100)
# ---------------------------------------------------------------------------
FACTOR_WEIGHTS = {
    "frequency": 25,
    "value": 20,
    "location": 20,
    "timing": 10,
    "historical": 15,
    "pattern": 10,
}
# Online accounts have no terminal location; play-through replaces the location factor.
ACCOUNT_FACTOR_WEIGHTS = {
    "frequency": 25,
    "value": 20,
    "playthrough": 20,
    "timing": 10,
    "historical": 15,
    "pattern": 10,
}
FACTOR_LABELS = {
    "frequency": "Frequency anomaly",
    "value": "Value anomaly",
    "location": "Location anomaly",
    "playthrough": "Low play-through",
    "timing": "Timing anomaly",
    "historical": "Historical deviation",
    "pattern": "Repeated-pattern anomaly",
}
# Investigator-facing names. FACTOR_LABELS above stay the technical names (stored in evidence titles);
# the UI shows these and keeps the technical name in a tooltip / the "Calculation & sources" details.
PLAIN_FACTOR_LABELS = {
    "frequency": "Unusual transaction frequency",
    "value": "Unusual spending amounts",
    "location": "New or unusual locations",
    "playthrough": "Money withdrawn with little play",
    "timing": "Unusual transaction timing",
    "historical": "Change from previous activity",
    "pattern": "Repeated or back-to-back transactions",
}
# plain term -> (technical term, one-line definition)
TERMS = {
    "Previous activity": ("Baseline", "The subject's own records in the 23 days before the recent period."),
    "Recent activity": ("Review window", "The 7 days of activity that the alert looked at."),
    "Data sources": ("Provenance", "Where a piece of evidence came from and how it was calculated."),
    "Evidence version": ("Snapshot", "A fixed, fingerprinted copy of the case evidence. Reports and decisions record which version they used."),
    "Prototype score": ("Prototype alert score", "0-100 measure of how unusual the activity is under simple rules. Not a probability of fraud."),
    "Indicator": ("Risk factor", "One rule that compares recent activity with previous activity."),
    "Linked purchases": ("Attributed purchases", "Lottery purchases where the player's rewards card was scanned. Other purchases are anonymous."),
    "Percentage points": ("pp", "The plain difference between two percentages, e.g. 0% to 74.2% is 74.2 percentage points."),
}

RISK_LEVELS = [  # (lower bound inclusive, label) — label of the *simulated alert score* band
    (80, "Critical"),
    (60, "High"),
    (30, "Medium"),
    (0, "Low"),
]
PRIORITY_LABELS = {
    "Critical": "Critical review priority",
    "High": "High review priority",
    "Medium": "Medium review priority",
    "Low": "Lower review priority",
}
ALERT_THRESHOLD = 20          # behavioural-deviation rule: subjects scoring below this do not alert
VOLUME_RULE_MIN_TXNS = 40     # simulated volume rule: alert on raw volume regardless of score
FACTOR_TRIGGER_RATIO = 0.25   # a factor counts as "triggered" at >= 25% of its max

# ---------------------------------------------------------------------------
# Case workflow
# ---------------------------------------------------------------------------
STATUS_NEW = "New"
STATUS_READY = "Analysis Ready"
STATUS_REVIEW = "Under Review"
STATUS_INFO = "Information Requested"
STATUS_CLOSED = "Closed — No Further Action"
STATUS_ESCALATED = "Escalated"
STATUS_SUBSTANTIATED = "Closed — Suspicion Substantiated"   # investigator's assessment, never a legal finding
ALL_STATUSES = [STATUS_NEW, STATUS_READY, STATUS_REVIEW, STATUS_INFO, STATUS_CLOSED, STATUS_ESCALATED, STATUS_SUBSTANTIATED]
OPEN_STATUSES = [STATUS_NEW, STATUS_READY, STATUS_REVIEW, STATUS_INFO]

# action -> {from_status: to_status}; None target = status unchanged
TRANSITIONS = {
    "start_review": {STATUS_NEW: STATUS_REVIEW, STATUS_READY: STATUS_REVIEW, STATUS_INFO: STATUS_REVIEW},
    "add_note": {s: None for s in ALL_STATUSES},
    "request_info": {STATUS_REVIEW: STATUS_INFO},
    "close_no_action": {STATUS_REVIEW: STATUS_CLOSED, STATUS_INFO: STATUS_CLOSED},
    "escalate": {STATUS_REVIEW: STATUS_ESCALATED, STATUS_INFO: STATUS_ESCALATED},
    "reopen": {STATUS_CLOSED: STATUS_REVIEW, STATUS_ESCALATED: STATUS_REVIEW, STATUS_SUBSTANTIATED: STATUS_REVIEW},
}
ACTION_LABELS = {
    "start_review": "Start review",
    "add_note": "Add note",
    "request_info": "Request more information",
    "close_no_action": "Close — no further action",
    "escalate": "Escalate",
    "reopen": "Reopen",
    # final investigation dispositions (services/dispositions.py; not in TRANSITIONS on purpose)
    "record_disposition": "Investigation decision",
    "confirm_disposition": "Senior confirmation",
    "return_disposition": "Returned by senior reviewer",
}
# ---------------------------------------------------------------------------
# Final investigation dispositions. A disposition records the investigator's assessment of whether the
# suspicion is supported by the evidence; it is not a legal determination of guilt.
# ---------------------------------------------------------------------------
SENIOR_ROLES = {"Senior investigator", "Admin"}
DISPOSITION_FROM = [STATUS_REVIEW, STATUS_INFO]          # a review must be in progress
MIN_JUSTIFICATION_CHARS = 30
MAX_DISPOSITION_EVIDENCE = 50
DISPOSITIONS = {
    "substantiated": {"label": "Suspected Fraud Substantiated", "status": STATUS_SUBSTANTIATED, "needs_senior": True,
                      "help": "The evidence supports the suspicion. Needs senior confirmation."},
    "not_substantiated": {"label": "Fraud Not Substantiated", "status": STATUS_CLOSED, "needs_senior": False,
                          "help": "The evidence does not support the suspicion. Case closes."},
    "inconclusive": {"label": "Inconclusive / More Information Required", "status": STATUS_INFO, "needs_senior": False,
                     "help": "The records cannot settle it. Case waits for more information."},
    "escalate": {"label": "Escalate for Further Investigation", "status": STATUS_ESCALATED, "needs_senior": False,
                 "help": "Needs specialist review beyond this workspace."},
}
CONCERN_TYPES = {"fraud": "Fraud", "aml": "Potential money-laundering (AML) pattern", "safer_gambling": "Safer-gambling concern"}
# wording by concern type: AML and safer-gambling outcomes never claim fraud or proven money laundering
DISPOSITION_LABELS = {
    "fraud": {"substantiated": "Suspected Fraud Substantiated", "not_substantiated": "Fraud Not Substantiated"},
    "aml": {"substantiated": "Suspicious AML Pattern Substantiated (not proof of money laundering)",
            "not_substantiated": "Suspicious AML Pattern Not Substantiated"},
    "safer_gambling": {"substantiated": "Safer-Gambling Concern Substantiated",
                       "not_substantiated": "Safer-Gambling Concern Not Substantiated"},
}
DISPOSITION_NOTICE = ("A substantiated finding is the investigator's assessment that the evidence supports the suspicion. "
                      "It is not a legal determination of guilt or proof that fraud or money laundering occurred.")


def disposition_label(disposition: str, concern_type: str = "fraud") -> str:
    return DISPOSITION_LABELS.get(concern_type, {}).get(disposition) or DISPOSITIONS[disposition]["label"]


NOTES_REQUIRED = {"add_note", "request_info", "close_no_action", "escalate", "reopen"}
MIN_NOTE_CHARS = 10
MAX_NOTE_CHARS = 4000

# ---------------------------------------------------------------------------
# AI settings (server-side only; never sent to the browser)
# ---------------------------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "").strip() or None
LLM_MAX_RETRIES = 1
CORS_ORIGINS = [o.strip() for o in os.getenv(
    "PRISM_CORS_ORIGINS", "http://localhost:5174,http://127.0.0.1:5174").split(",") if o.strip()]


def refresh_llm_settings():
    """Re-read .env so a key added while the server runs is picked up without a restart."""
    global OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL
    vals: dict = {}
    try:
        from dotenv import dotenv_values

        for p in (ENV_PATHS if DOTENV_ENABLED else []):
            if p.exists():
                vals.update({k: v for k, v in dotenv_values(p).items() if v})
    except Exception:  # noqa: BLE001
        pass
    OPENAI_API_KEY = (vals.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY", "")).strip()
    OPENAI_MODEL = (vals.get("OPENAI_MODEL") or os.getenv("OPENAI_MODEL", "") or "gpt-4o-mini").strip()
    OPENAI_BASE_URL = (vals.get("OPENAI_BASE_URL") or os.getenv("OPENAI_BASE_URL", "")).strip() or None


DISCLAIMER = branding().get("report_disclaimer") or (
    "This report identifies potentially suspicious patterns and does not establish "
    "that fraudulent activity occurred. Final determination requires human review."
)
PROJECT_NOTICE = (
    "This project is an independent research prototype inspired by publicly described "
    "transaction-monitoring concepts. It is not affiliated with or connected to OLG and does "
    "not reproduce OLG's proprietary DART system. All data is synthetic."
)


def risk_level(score: float) -> str:
    for lower, label in RISK_LEVELS:
        if score >= lower:
            return label
    return "Low"
