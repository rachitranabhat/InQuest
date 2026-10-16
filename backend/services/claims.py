"""Structured claims and their deterministic validation.

A claim is a single statement in a report or chat answer:
    {section, kind, text, evidence_ids, assertions?}
kind: fact | interpretation | recommendation | limitation | status

Validation is deterministic and checks the claim ONLY against the evidence it
cites (not against "anything in the case"):

1. citations   — every cited ID exists, belongs to this case; non-status claims cite ≥ 1 item
2. numbers     — every number in the text equals a value in the cited items, allowing only
                 rounding consistent with how it is written (21.5 → "22×" ok, "77" vs 78 not ok)
3. dates/times — every date or clock time in the text appears in the cited items
4. entities    — every record ID, retailer name, city or event name in the text appears in
                 the cited items' entities/source records (invented places are caught by a
                 vocabulary that also holds well-known places outside the dataset)
5. qualifiers  — words like "overnight", "new city", "increase", "anonymous" must be backed by
                 the cited items' structured values
6. assertions  — optional {evidence_id, field, value} triples must match the cited field exactly
7. policy      — no accusatory language; missing data must never be presented as proof

A claim that fails any check is stored as "unverified" with its reasons; it is
never shown as a verified fact.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, Field, field_validator

KINDS = ("fact", "interpretation", "recommendation", "limitation", "status")
SECTIONS = [
    ("case_overview", "Case overview"),
    ("initial_alert", "Initial alert"),
    ("observed_activity", "Summary of observed activity"),
    ("triggering_indicators", "Triggering indicators"),
    ("supporting_evidence", "Supporting evidence"),
    ("historical_comparison", "Historical comparison"),
    ("related_entities", "Related entities and transactions"),
    ("alternative_explanations", "Alternative explanations"),
    ("missing_evidence", "Missing or conflicting evidence"),
    ("recommended_checks", "Recommended investigative checks"),
    ("review_status", "Human review status"),
]
SECTION_KEYS = [k for k, _ in SECTIONS]
# Investigator-facing section headings (SECTIONS above keep the specification names, shown as a tooltip).
PLAIN_SECTION_LABELS = {
    "case_overview": "Case overview",
    "initial_alert": "Why the alert was raised",
    "observed_activity": "What happened",
    "triggering_indicators": "Key findings",
    "supporting_evidence": "Supporting records",
    "historical_comparison": "Compared with previous activity",
    "related_entities": "Retailers, accounts and other players",
    "alternative_explanations": "Other possible explanations",
    "missing_evidence": "Missing or conflicting information",
    "recommended_checks": "Suggested next checks",
    "review_status": "Review status",
}

ID_RE = re.compile(r"\b(?:TXN|RTL|PLY|ACC|TRM|TKT|LOC|AL|CASE|EV|EVT|SNP|RPT|CL|ACT|REV)-[A-Z0-9]+(?:-[A-Z0-9]+)*\b")
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
MONTH_ALT = "|".join(sorted(list(MONTHS) + [m[:3] for m in MONTHS] + ["sept"], key=len, reverse=True))
ISO_DATE_RE = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
NAMED_DATE_RE = re.compile(rf"\b({MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(20\d\d))?\b", re.I)
NAMED_DATE_RE2 = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({MONTH_ALT})\b(?:,?\s+(20\d\d))?", re.I)
WEEKDAY_RE = re.compile(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?,?\s", re.I)
CLOCK_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)(?:\s*([ap])\.?m\.?)?\b", re.I)
AMPM_RE = re.compile(r"\b(1[0-2]|0?[1-9])\s*([ap])\.?m\.?\b", re.I)
NUM_RE = re.compile(r"(?<![\w.])[-−]?\$?\d[\d,]*(?:\.\d+)?")
WORD_NUMS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty".split())}
WORD_NUM_RE = re.compile(r"\b(" + "|".join(WORD_NUMS) + r")\b(?=\s+(?:transactions?|purchases?|deposits?|withdrawals?|"
                         r"wagers?|retailers?|cities|city|locations?|days?|players?|accounts?|times?|claims?|"
                         r"indicators?|signals?|pairs?))", re.I)
# definitional constants of the methodology, allowed only when followed by their unit
DEFINITION_UNITS = re.compile(r"^\s*(?:-\s*)?(days?|minutes?|mins?|hours?|h\b|am|pm|a\.m\.|p\.m\.|points?|pts|/\s*100|percentile|th percentile)", re.I)
DEFINITION_VALUES = {0, 1, 2, 5, 7, 23, 24, 30, 60, 95, 100}
EXTRA_PLACES = ["Vancouver", "Montreal", "Montréal", "Calgary", "Edmonton", "Winnipeg", "Halifax", "Quebec City",
                "Regina", "Saskatoon", "Victoria", "St. John's", "Fredericton", "Charlottetown", "Gatineau", "Oshawa",
                "Brampton", "Markham", "Vaughan", "Guelph", "Sarnia", "North Bay", "Cornwall", "Belleville",
                "New York", "Detroit", "Buffalo", "Chicago", "Las Vegas", "Atlantic City", "London, UK", "Paris"]
ACCUSATORY = re.compile(
    r"\b(committed (?:fraud|a crime)|is (?:a )?(?:fraudster|criminal|guilty)|guilty|criminal(?:ly)?|"
    r"money[- ]launder\w*|launder(?:ed|ing|s)?|stole|theft|fraudulent(?:ly)?|is fraud\b|was fraud\b|"
    r"definitely|undeniabl\w*|proves?\b|proven|confirms? (?:that )?(?:fraud|wrongdoing))\b", re.I)
ABSENCE = re.compile(r"\b(did not occur|didn't occur|never happened|did not happen|no (?:one|other person)|"
                     r"rules? out|ruled out|proves? (?:that )?(?:no|nothing)|confirms? (?:that )?(?:no|nothing)|"
                     r"there (?:was|were) no)\b", re.I)


class ClaimIn(BaseModel):
    """Shape an LLM (or the deterministic writer) must produce."""
    section: str
    kind: str = "fact"
    text: str = Field(min_length=3, max_length=700)
    evidence_ids: list[str] = Field(default_factory=list, max_length=40)
    assertions: list[dict] = Field(default_factory=list, max_length=12)

    @field_validator("section")
    @classmethod
    def _sec(cls, v):
        if v not in SECTION_KEYS and v != "answer":
            raise ValueError(f"unknown section {v!r}")
        return v

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        if v not in KINDS:
            raise ValueError(f"unknown kind {v!r}")
        return v

    @field_validator("text")
    @classmethod
    def _clean(cls, v):
        return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", v).strip()


@dataclass
class Vocab:
    retailer_names: list[str]
    cities: list[str]
    event_names: list[str] = field(default_factory=list)

    def terms(self):
        out = [(n, "retailer") for n in self.retailer_names] + [(c, "city") for c in self.cities + EXTRA_PLACES]
        out += [(e, "event") for e in self.event_names]
        return sorted(out, key=lambda t: -len(t[0]))


# ------------------------------------------------------------------ value pools
def _walk(obj, nums: set, strs: list):
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        nums.add(float(obj))
    elif isinstance(obj, str):
        strs.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk(v, nums, strs)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk(v, nums, strs)


def fmt_half_up(x: float, decimals: int) -> str:
    """Format exactly as the validator rounds (half-up), so writer and checker never disagree."""
    q = Decimal(1).scaleb(-decimals)
    return str(Decimal(str(x)).quantize(q, rounding=ROUND_HALF_UP))


def _pools(items: list[dict]):
    nums, strs = set(), []
    entities = set()
    for it in items:
        _walk(it["computed"], nums, strs)
        entities |= set(it["entities"]) | set(it["source_ids"]) | {it["evidence_id"]}
    dates, times, hours = set(), set(), set()
    for s in strs:
        for y, m, d in ISO_DATE_RE.findall(s):
            dates.add((int(m), int(d)))
        for hh, mm, _ in CLOCK_RE.findall(s):
            times.add((int(hh), int(mm)))
            hours.add(int(hh))
    for it in items:
        h = it["computed"].get("hour")
        if isinstance(h, int):
            hours.add(h)
    # numbers quoted verbatim inside cited text values (e.g. a rule "score ≥ 20"), dates/times excluded
    for s_ in strs:
        clean = CLOCK_RE.sub(" ", ISO_DATE_RE.sub(" ", s_))
        for m in NUM_RE.finditer(clean):
            try:
                nums.add(float(m.group(0).replace("$", "").replace(",", "")))
            except ValueError:
                pass
    return nums, entities, dates, times, hours, strs


def _round_eq(text_value: Decimal, decimals: int, v: float) -> bool:
    q = Decimal(1).scaleb(-decimals)
    return Decimal(str(v)).quantize(q, rounding=ROUND_HALF_UP) == text_value.quantize(q)


def _num_matches(raw: str, pool: set) -> bool:
    s = raw.replace("$", "").replace(",", "").replace("−", "-")
    try:
        val = Decimal(s)
    except Exception:  # noqa: BLE001
        return True
    decimals = max(0, -val.as_tuple().exponent)
    for v in pool:
        if _round_eq(val, decimals, v) or _round_eq(-val, decimals, v):
            return True
    return False


# ------------------------------------------------------------------- validation
def validate_claim(claim: dict, case_id: str, index: dict, vocab: Vocab, global_lookup=None) -> tuple[str, list[str]]:
    """index: evidence_id -> item (THIS case only). global_lookup(eid) -> case_id or None."""
    fails: list[str] = []
    text = claim["text"]
    kind = claim.get("kind", "fact")
    cited_ids = list(dict.fromkeys(claim.get("evidence_ids") or []))

    # 1. citations ---------------------------------------------------------------
    if kind != "status" and not cited_ids:
        fails.append("No evidence cited.")
    cited = []
    for eid in cited_ids:
        if eid in index:
            cited.append(index[eid])
        else:
            other = global_lookup(eid) if global_lookup else None
            fails.append(f"{eid} belongs to {other}, not {case_id}." if other else f"{eid} does not exist.")
    nums, entities, dates, times, hours, strs = _pools(cited)
    if kind == "status":
        return ("verified" if not fails else "unverified"), fails

    # 7. policy --------------------------------------------------------------------
    if ACCUSATORY.search(text):
        fails.append(f"Accusatory or conclusive language (\"{ACCUSATORY.search(text).group(0)}\"); "
                     "findings must describe patterns, not guilt.")
    if any(c["type"] == "limitation" for c in cited) and ABSENCE.search(text):
        fails.append("Missing data is presented as proof that something did not happen.")

    work = text
    # 4. entities --------------------------------------------------------------------
    for tok in set(ID_RE.findall(work)):
        if tok == case_id or tok in entities:
            continue
        fails.append(f"{tok} is not in the cited evidence.")
    work = ID_RE.sub(" ", work)
    low = work.lower()
    for term, kind_t in vocab.terms():
        pat = re.compile(r"(?<![\w])" + re.escape(term.lower()) + r"(?![\w])")
        if pat.search(low):
            if term not in entities and not any(term.lower() in s.lower() for s in strs):
                fails.append(f"{kind_t.capitalize()} \"{term}\" is not in the cited evidence.")
            low = pat.sub(" ", low)
            work = re.sub(r"(?<![\w])" + re.escape(term) + r"(?![\w])", " ", work, flags=re.I)

    # 3. dates / times ---------------------------------------------------------------
    def _date_ok(m, d):
        if (m, d) not in dates:
            fails.append(f"Date {MONTH_NAMES[m - 1]} {d} is not in the cited evidence.")

    for y, m, d in ISO_DATE_RE.findall(work):
        _date_ok(int(m), int(d))
    work = ISO_DATE_RE.sub(" ", work)
    for mon, d, y in NAMED_DATE_RE.findall(work):
        _date_ok(_month(mon), int(d))
    work = NAMED_DATE_RE.sub(" ", work)
    for d, mon, y in NAMED_DATE_RE2.findall(work):
        _date_ok(_month(mon), int(d))
    work = NAMED_DATE_RE2.sub(" ", work)
    for hh, mm, ap in CLOCK_RE.findall(work):
        h = int(hh) % 12 + (12 if ap and ap.lower() == "p" else 0) if ap else int(hh)
        if (h, int(mm)) not in times:
            fails.append(f"Time {hh}:{mm} is not in the cited evidence.")
    work = CLOCK_RE.sub(" ", work)
    for m in AMPM_RE.finditer(work):
        h = int(m.group(1)) % 12 + (12 if m.group(2).lower() == "p" else 0)
        if h not in hours and h not in DEFINITION_VALUES:
            fails.append(f"Time {m.group(0)} is not in the cited evidence.")
    work = AMPM_RE.sub(" ", work)

    # 2. numbers ----------------------------------------------------------------------
    work_w = WORD_NUM_RE.sub(lambda m: str(WORD_NUMS[m.group(1).lower()]), work)
    for m in NUM_RE.finditer(work_w):
        raw = m.group(0)
        if _num_matches(raw, nums):
            continue
        after = work_w[m.end(): m.end() + 16]
        before = work_w[max(0, m.start() - 3): m.start()]
        try:
            v = float(raw.replace("$", "").replace(",", ""))
        except ValueError:
            continue
        if v in DEFINITION_VALUES and "$" not in raw and (DEFINITION_UNITS.match(after) or
                                                          (v == 100 and before.rstrip().endswith("/"))):
            continue
        fails.append(f"Number {raw} does not match the cited evidence.")

    # 5. qualifiers -------------------------------------------------------------------
    for rx, pred, msg in QUALIFIERS:
        if rx.search(text) and not any(pred(c) for c in cited):
            fails.append(msg)

    # 6. assertions -------------------------------------------------------------------
    for a in claim.get("assertions") or []:
        eid, fld, val = a.get("evidence_id"), a.get("field"), a.get("value")
        if eid not in index or eid not in cited_ids:
            fails.append(f"Assertion cites {eid}, which is not among this claim's citations.")
            continue
        comp = index[eid]["computed"]
        if fld not in comp:
            fails.append(f"{eid} has no field '{fld}'.")
        elif isinstance(comp[fld], (int, float)) and not isinstance(comp[fld], bool):
            try:
                if abs(float(val) - float(comp[fld])) > 0.005:
                    fails.append(f"{eid}.{fld} is {comp[fld]}, not {val}.")
            except (TypeError, ValueError):
                fails.append(f"{eid}.{fld} is {comp[fld]}, not {val}.")
        elif comp[fld] != val:
            fails.append(f"{eid}.{fld} is {comp[fld]!r}, not {val!r}.")
    return ("verified" if not fails else "unverified"), fails


MONTH_NAMES = [m.capitalize() for m in MONTHS]


def _month(name: str) -> int:
    n = name.lower().rstrip(".")
    if n == "sept":
        return 9
    for full, i in MONTHS.items():
        if full.startswith(n[:3]):
            return i
    return 0


def _c(item, *keys):
    return [item["computed"].get(k) for k in keys]


QUALIFIERS = [
    (re.compile(r"\b(overnight|night[- ]?time|at night|late[- ]night|after midnight|between midnight)\b", re.I),
     lambda it: (it["computed"].get("hour") is not None and it["computed"]["hour"] < 5)
     or (it["computed"].get("night_transactions") or 0) > 0 or (it["computed"].get("night_share_pct") or 0) > 0
     or "night" in str(it["computed"].get("metric", "")).lower()
     or it["computed"].get("night_transactions") is not None
     or it["type"] in ("baseline", "limitation"),
     "Says activity was at night, but no cited item shows night-time activity."),
    (re.compile(r"\bnew (cit(y|ies)|retailers?|locations?)\b|\bnot (?:seen|used) (?:in|during) the baseline\b", re.I),
     lambda it: it["computed"].get("new_for_subject") is True or it["computed"].get("in_baseline") is False
     or (it["computed"].get("new_city_count") or 0) > 0 or (it["computed"].get("new_retailer_count") or 0) > 0,
     "Says something was new, but no cited item shows it was absent from the baseline."),
    (re.compile(r"\b(increase[ds]?|higher than|more than (?:usual|normal|the baseline)|above (?:the )?baseline|rose|jump(?:ed)?)\b", re.I),
     lambda it: (it["computed"].get("ratio") or 0) > 1 or (it["computed"].get("frequency_ratio") or 0) > 1
     or (it["computed"].get("spend_ratio") or 0) > 1 or (it["computed"].get("peak_hour_ratio") or 0) > 1
     or (it["computed"].get("avg_ratio") or 0) > 1 or (it["computed"].get("network_ratio") or 0) > 1
     or it["type"] in ("query_result",) and (it["computed"].get("ratio") or 0) > 1,
     "Describes an increase, but no cited comparison shows one."),
    (re.compile(r"\b(decrease[ds]?|lower than|less than (?:usual|normal|the baseline)|below (?:the )?baseline|dropped)\b", re.I),
     lambda it: it["computed"].get("ratio") is not None and it["computed"]["ratio"] < 1,
     "Describes a decrease, but no cited comparison shows one."),
    (re.compile(r"\b(anonymous|unattributed|cannot be attributed|not attributed)\b", re.I),
     lambda it: it["type"] == "limitation" or it["computed"].get("attribution") == "none"
     or "anonymous_nearby_count" in it["computed"] or it["type"] == "relationship",
     "Mentions anonymous purchases, but cites no attribution evidence."),
    (re.compile(r"\b(related|relationship|connected|associate[ds]?|linked to)\b", re.I),
     lambda it: it["type"] in ("relationship", "co_presence", "transaction", "aggregate_retailer", "risk_factor",
                               "limitation", "query_result", "retailer", "alert", "sequence"),
     "Describes a relationship, but cites no relationship evidence."),
]


def build_index(items: list[dict]) -> dict:
    return {it["evidence_id"]: it for it in items}
