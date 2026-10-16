"""Dashboard copilot: deterministic help about navigation, terms and the review workflow.

It has no database access at all — it cannot read cases, players, evidence or identity
records — so it cannot draw case-specific conclusions. Questions about a particular case are
answered with a pointer to that case's own evidence-grounded copilot.
"""
from __future__ import annotations

import re

import config

SUGGESTED = [
    "How do I review a case?",
    "What does the prototype score mean?",
    "How is review priority decided?",
    "What is the Scenario Lab for?",
    "What do the case statuses mean?",
    "What does previous activity mean?",
]

SCOPE = ("Dashboard help explains INQUEST itself. It cannot see case records; open a case and use its copilot "
         "for evidence-cited answers about that case.")

_CASE_RE = re.compile(r"\bCASE-\d{4,6}\b", re.I)
_CASE_WORDS = re.compile(r"\b(this|that|my) (case|player|subject|account)\b|\b(PLY|ACC|P)-\d+|\bwho is\b", re.I)

_NAV = [
    ("Queue", "/", "every open case, sorted by review priority, with filters for status, priority, channel and evidence completeness"),
    ("Compare", "/compare", "two or more cases side by side"),
    ("Scenario Lab", "/scenarios", "runs scripted synthetic scenarios through the same monitoring rules to create new demo cases"),
    ("Reports & history", "/reports", "generated reports and the audit trail of reviewer actions"),
    ("Analytics", "/analytics", "queue-level charts: priorities, alert types, statuses and outcomes"),
]

_TOPICS: list[tuple[str, tuple[str, ...], list[str], list[tuple[str, str]]]] = [
    ("status", ("status", "statuses", "in review", "analysis ready", "new case"),
     ["Case statuses: " + ", ".join(config.ALL_STATUSES) + ". Open statuses are " + ", ".join(config.OPEN_STATUSES) + ".",
      "Allowed actions: " + "; ".join(f"{config.ACTION_LABELS[a]} ({', '.join(sorted(m))})" for a, m in config.TRANSITIONS.items()) + "."],
     []),
    ("priority", ("priority", "prioritis", "prioritiz", "urgent", "critical", "order"),
     ["Review priority starts from the prototype score band (" + ", ".join(f"{label} from {lo}" for lo, label in config.RISK_LEVELS)
      + "). Four or more indicators raise it one level; a single indicator lowers a High or Critical band one level; "
      "an alert raised only by the volume rule gets Lower priority. Incomplete evidence is listed as a caution but "
      "does not change the level.",
      "Each case header lists the reasons for its priority. Priority orders the work; it is not a finding of wrongdoing."],
     [("Open the queue", "/")]),
    ("score", ("prototype score", "score", "alert score", "probability", "0-100", "points"),
     ["The prototype score is a 0-100 rule-based measure of how unusual recent activity is compared with the "
      "subject's own previous activity. It is not a probability of fraud and not a confidence value.",
      "An indicator counts toward the alert when it reaches %d%% of its maximum points." % round(config.FACTOR_TRIGGER_RATIO * 100)],
     []),
    ("scenario", ("scenario", "lab", "simulate", "demo case"),
     ["The Scenario Lab runs scripted synthetic situations through the same monitoring rules and evidence builder, "
      "creating new demo cases you can open like any other. A reviewer session is needed to run one."],
     [("Open the Scenario Lab", "/scenarios")]),
    ("evidence", ("evidence", "citation", "cite", "snapshot", "version", "source"),
     ["Every statement in a report or a case copilot answer cites stored evidence. Click a citation to open the "
      "record; the evidence version is a fingerprinted snapshot, and reports and decisions record which version they used."],
     []),
    ("restricted", ("restricted", "identity", "name", "contact", "personal", "data management", "database"),
     ["Senior investigators see Restricted Records and Data Management in the sidebar. Identity details are "
      "fictional, stay hidden until a reason is given, and every reveal is logged. This help cannot access them."],
     []),
    ("data", ("synthetic", "real data", "olg", "dart", "where does the data"),
     [config.PROJECT_NOTICE], []),
    ("workflow", ("review a case", "workflow", "how do i", "start review", "decision", "disposition", "substantiat", "close",
                  "escalat", "reopen", "request", "inconclusive"),
     ["Open a case from the Queue. Read Summary first, then Evidence (findings and the records behind them), then "
      "Historical Comparison. Record your decision in Review.",
      "Start review moves the case to " + config.STATUS_REVIEW + ". Then record an investigation decision in Review: "
      + "; ".join(v["label"] for v in config.DISPOSITIONS.values()) + ". Each needs a justification of at least "
      + str(config.MIN_JUSTIFICATION_CHARS) + " characters and cited evidence, and is written to the append-only audit trail.",
      "A substantiated finding by a regular reviewer is a recommendation until a senior investigator confirms it. "
      + config.DISPOSITION_NOTICE,
      "INQUEST never decides whether fraud occurred: findings are reasons to look, and the decision is the reviewer's."],
     [("Open the queue", "/")]),
]


def _term_answer(q: str) -> list[str]:
    out = []
    for plain, (technical, definition) in config.TERMS.items():
        if plain.lower() in q or technical.lower() in q:
            out.append(f"{plain} (technical name: {technical}): {definition}")
    return out


def answer(question: str) -> dict:
    q = " ".join((question or "").split())[:1000]
    ql = q.lower()
    m = _CASE_RE.search(q)
    if m or _CASE_WORDS.search(q):
        cid = m.group(0).upper() if m else None
        return {"topic": "case_specific", "scope": SCOPE,
                "answer": ["Dashboard help has no access to case records, so it cannot answer questions about a specific "
                           "case, player or account, or say whether anything suspicious happened.",
                           f"Open {cid} and ask its copilot: answers there use only that case's evidence and cite every statement."
                           if cid else "Open the case from the Queue and ask its copilot: answers there use only that case's "
                           "evidence and cite every statement."],
                "links": [{"label": f"Open {cid}", "to": f"/cases/{cid}"}] if cid else [{"label": "Open the queue", "to": "/"}]}
    terms = _term_answer(ql)
    for key, words, paras, links in _TOPICS:
        if any(w in ql for w in words):
            return {"topic": key, "scope": SCOPE, "answer": [*paras, *terms],
                    "links": [{"label": l, "to": t} for l, t in links]}
    if terms:
        return {"topic": "terms", "scope": SCOPE, "answer": terms, "links": []}
    if any(w in ql for w in ("where", "find", "page", "navigate", "menu", "sidebar", "go to")):
        return {"topic": "navigation", "scope": SCOPE,
                "answer": [f"{n}: {d}." for n, _t, d in _NAV], "links": [{"label": n, "to": t} for n, t, _ in _NAV]}
    return {"topic": "unknown", "scope": SCOPE,
            "answer": ["I can explain INQUEST's pages, terms such as the prototype score or previous activity, and the review "
                       "workflow. Try one of the suggested questions."],
            "links": []}
