"""Deterministic, explainable review prioritisation.

Kept deliberately separate from the alert score:
  alert score  — how unusual the activity is under the prototype rules (0–100)
  priority     — how soon a human should look (Critical / High / Medium / Lower review priority)
  completeness — how much of the picture the records can show
  urgency      — whether activity is recent / ongoing
None of these is a probability of fraud.
"""
from __future__ import annotations

import pandas as pd

import config

ORDER = ["Low", "Medium", "High", "Critical"]


def compute_priority(alert: dict, completeness: str) -> dict:
    band = alert["risk_level"]
    idx = ORDER.index(band)
    trig = alert["triggered_count"]
    why = [f"Prototype alert score {alert['risk_score']:.1f} is in the {band} band."]
    if alert["risk_score"] < config.ALERT_THRESHOLD:
        idx = 0
        why.append("Only the volume rule fired; the behavioural-deviation rule did not, so activity is close to "
                   "this subject's own history.")
    elif trig >= 4 and idx < 3:
        idx += 1
        why.append(f"{trig} independent indicators fired, which raises priority one level.")
    elif trig <= 1 and idx >= 2:
        idx -= 1
        why.append("Only one indicator fired; single-indicator alerts often have ordinary explanations, "
                   "so priority is lowered one level.")
    else:
        why.append(f"{trig} indicator(s) fired, consistent with the score band.")
    if completeness != "Complete":
        why.append(f"Evidence completeness is {completeness.lower()}: some relevant records are unavailable, "
                   "which the reviewer should weigh before concluding anything.")
    last = pd.Timestamp(alert["triggered_at_local"]) - pd.Timedelta(minutes=15)
    recent = (pd.Timestamp(alert["window_end_local"]) - last) <= pd.Timedelta(hours=24)
    urgency = "Recent activity (last 24 h of the window)" if recent else "No activity in the last 24 h of the window"
    level = ORDER[idx]
    return {"priority": config.PRIORITY_LABELS[level], "priority_level": level, "rationale": why, "urgency": urgency}
