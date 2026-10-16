"""Controlled, case-scoped query tools for the copilot.

The LLM (or the deterministic intent parser) can only call these functions.
They read ONE case's evidence registry — never raw SQL, never another case.
Aggregates they compute are registered as new `query_result` evidence items so
answers built on them are citable and re-verifiable.
"""
from __future__ import annotations

import hashlib
from typing import Literal, Optional

import pandas as pd
from pydantic import BaseModel, Field, ValidationError

from database.db import dumps, next_id, tx
from services import repo
from timeutil import utc_now_iso


class TxnFilter(BaseModel):
    date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Local date YYYY-MM-DD")
    date_from: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    hour_from: Optional[int] = Field(None, ge=0, le=23)
    hour_to: Optional[int] = Field(None, ge=0, le=23)
    retailer_id: Optional[str] = Field(None, pattern=r"^RTL-\d{4}$")
    city: Optional[str] = Field(None, max_length=40)
    min_amount: Optional[float] = Field(None, ge=0)
    max_amount: Optional[float] = Field(None, ge=0)
    transaction_type: Optional[str] = Field(None, max_length=40)


class ListArgs(TxnFilter):
    limit: int = Field(25, ge=1, le=100)
    sort: Literal["time", "amount_desc"] = "time"


class AggArgs(TxnFilter):
    group_by: Literal["retailer", "city", "day", "hour", "transaction_type"] = "retailer"


class NoArgs(BaseModel):
    pass


TOOL_SPECS = {
    "list_transactions": (ListArgs, "List this case's review-window transactions, optionally filtered by local date, "
                                    "hour range, retailer, city, amount or type. Returns each row's evidence ID."),
    "aggregate_transactions": (AggArgs, "Count and total this case's review-window transactions grouped by retailer, "
                                        "city, day, hour or type (with optional filters). Registers the result as evidence."),
    "get_triggering_factors": (NoArgs, "The prototype risk indicators for this case with points and linked transactions."),
    "get_baseline_comparison": (NoArgs, "Historical baseline and baseline-vs-window comparisons."),
    "get_related_entities": (NoArgs, "Retailers, locations, verified relationships and co-location observations."),
    "get_limitations": (NoArgs, "What the records cannot show (data-availability limitations)."),
    "get_context_and_contradictions": (NoArgs, "Evidence that may point to ordinary explanations: context events, "
                                               "normal comparisons, unfired indicators, co-location caveats. In a context_event, "
                                               "subject_share_pct is the share of the SUBJECT'S OWN window transactions "
                                               "that fall on the event days (not a share of network transactions)."),
    "get_case_summary": (NoArgs, "The initial alert and the review-window totals."),
    "get_previous_findings": (NoArgs, "Verified claims from this case's latest saved report."),
}


def openai_tools() -> list[dict]:
    out = []
    for name, (model, desc) in TOOL_SPECS.items():
        schema = model.model_json_schema()
        schema.pop("title", None)
        for p in schema.get("properties", {}).values():
            p.pop("title", None)
        out.append({"type": "function", "function": {"name": name, "description": desc, "parameters": schema}})
    return out


def _brief(it: dict) -> dict:
    return {"evidence_id": it["evidence_id"], "type": it["type"], "title": it["title"], "summary": it["summary"],
            "computed": it["computed"]}


class CaseTools:
    def __init__(self, con, case_id: str):
        self.con = con
        self.case = repo.case_row(con, case_id)
        self.case_id = case_id
        self.items = repo.evidence_items(con, case_id)
        self.by_key = {it["provenance"].get("key"): it for it in self.items}
        rows = []
        for it in self.items:
            if it["type"] != "transaction":
                continue
            c = it["computed"]
            rows.append({"evidence_id": it["evidence_id"], "transaction_id": it["source_ids"][0], **c})
        self.tx = pd.DataFrame(rows)
        self.created: list[dict] = []

    def of_type(self, *types):
        return [it for it in self.items if it["type"] in types and it["snapshot_id"] is not None]

    # ------------------------------------------------------------- dispatch
    def call(self, name: str, args: dict | None) -> dict:
        if name not in TOOL_SPECS:
            return {"error": f"Unknown tool {name}"}
        model = TOOL_SPECS[name][0]
        try:
            parsed = model(**(args or {}))
        except ValidationError as e:
            return {"error": "Invalid arguments", "details": e.errors(include_url=False)[:3]}
        return getattr(self, name)(parsed)

    # --------------------------------------------------------------- filters
    def _filter(self, a: TxnFilter) -> pd.DataFrame:
        d = self.tx
        if d.empty:
            return d
        if a.date and a.date not in set(d.date):
            return d.iloc[0:0]
        if a.date:
            d = d[d.date == a.date]
        if a.date_from:
            d = d[d.date >= a.date_from]
        if a.date_to:
            d = d[d.date <= a.date_to]
        if a.hour_from is not None:
            d = d[d.hour >= a.hour_from]
        if a.hour_to is not None:
            d = d[d.hour <= a.hour_to]
        if a.retailer_id and "retailer_id" in d:
            d = d[d.retailer_id == a.retailer_id]
        if a.city and "city" in d:
            d = d[d.city.fillna("").str.lower() == a.city.lower()]
        if a.min_amount is not None:
            d = d[d.amount >= a.min_amount]
        if a.max_amount is not None:
            d = d[d.amount <= a.max_amount]
        if a.transaction_type:
            d = d[d.transaction_type.str.lower() == a.transaction_type.lower()]
        return d

    def _filters_text(self, a: TxnFilter) -> dict:
        return {k: v for k, v in a.model_dump().items() if v is not None and k not in ("limit", "sort", "group_by")}

    # ------------------------------------------------------------------ tools
    def list_transactions(self, a: ListArgs) -> dict:
        d = self._filter(a)
        total_n = int(len(d))
        d = d.sort_values("amount", ascending=False) if a.sort == "amount_desc" else d.sort_values("timestamp_local")
        cols = [c for c in ("evidence_id", "transaction_id", "timestamp_local", "amount", "transaction_type",
                            "retailer_id", "retailer_name", "city", "account_id") if c in d]
        res = {"scope": "review window only", "filters": self._filters_text(a), "matching_count": total_n,
               "rows": d[cols].head(a.limit).to_dict("records") if total_n else []}
        res["aggregate_evidence"] = self._register_aggregate("list_transactions", a, d, group_by=None)
        return res

    def aggregate_transactions(self, a: AggArgs) -> dict:
        d = self._filter(a)
        if d.empty:
            return {"filters": self._filters_text(a), "matching_count": 0, "groups": [],
                    "note": "No review-window transactions match these filters."}
        return self._register_aggregate("aggregate_transactions", a, d, group_by=a.group_by)

    def _register_aggregate(self, tool: str, a, d: pd.DataFrame, group_by: str | None) -> dict:
        col = {"retailer": "retailer_id", "city": "city", "day": "date", "hour": "hour",
               "transaction_type": "transaction_type", None: None}[group_by]
        computed = {"transaction_count": int(len(d)), "total_amount": round(float(d.amount.sum()), 2),
                    "filters": self._filters_text(a)}
        entities = set(d.transaction_id)
        if "date" in d and len(d):
            computed["dates"] = sorted(d.date.unique().tolist())
            computed["first_local"], computed["last_local"] = d.timestamp_local.min(), d.timestamp_local.max()
        groups = []
        if col:
            if col not in d or d[col].isna().all():
                return {"error": f"Grouping by {group_by} is not available for this case's records."}
            for key, g in d.groupby(col):
                row = {"key": key, "transaction_count": int(len(g)), "total_amount": round(float(g.amount.sum()), 2),
                       "share_pct": round(len(g) / len(d) * 100, 1)}
                if col == "retailer_id":
                    row.update({"retailer_name": g.retailer_name.iloc[0], "city": g.city.iloc[0]})
                    entities |= {key, g.retailer_name.iloc[0], g.city.iloc[0]}
                if col == "city":
                    entities.add(key)
                groups.append(row)
            groups.sort(key=lambda r: (-r["transaction_count"], -r["total_amount"], str(r["key"])))
            computed["groups"] = groups
            computed["top_group"] = groups[0]["key"]
        for k in ("retailer_id", "city"):
            v = getattr(a, k, None)
            if v:
                entities.add(v)
        if "retailer_id" in d:
            for rid, name, city in d[["retailer_id", "retailer_name", "city"]].dropna().drop_duplicates().itertuples(index=False):
                entities |= {rid, name, city}
        args_key = dumps({"tool": tool, **a.model_dump()})
        key = "query:" + hashlib.sha1(args_key.encode()).hexdigest()[:16]
        existing = self.con.execute("SELECT evidence_id FROM evidence WHERE case_id = ? AND json_extract(provenance, '$.key') = ?",
                                    (self.case_id, key)).fetchone()
        title = (f"Query: transactions grouped by {group_by}" if group_by else "Query: filtered transactions") + \
                (f" ({', '.join(f'{k}={v}' for k, v in computed['filters'].items())})" if computed["filters"] else "")
        summary = f"{computed['transaction_count']} transactions totalling ${computed['total_amount']:,.2f}"
        if groups:
            top = groups[0]
            summary += (f"; most in {top.get('retailer_name') or top['key']} "
                        f"({top['transaction_count']} transactions, ${top['total_amount']:,.2f})")
        if existing:
            eid = existing[0]
        else:
            with tx(self.con):
                eid = next_id(self.con, "EV")
                self.con.execute("INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                 (eid, self.case_id, None, "query_result", title, summary,
                                  dumps(sorted(d.transaction_id)), dumps(sorted(str(e) for e in entities if e)),
                                  dumps(computed), dumps({"key": key, "tool": tool, "args": a.model_dump(),
                                                          "computed_from": "case review-window transaction evidence"}),
                                  utc_now_iso()))
        item = repo.evidence_item(self.con, self.case_id, eid)
        if item not in self.items:
            self.items.append(item)
            self.created.append(item)
        return _brief(item)

    def get_triggering_factors(self, _a) -> dict:
        return {"items": [_brief(i) for i in self.of_type("alert", "risk_factor")]}

    def get_baseline_comparison(self, _a) -> dict:
        return {"items": [_brief(i) for i in self.of_type("baseline", "comparison")]}

    def get_related_entities(self, _a) -> dict:
        return {"items": [_brief(i) for i in self.of_type("relationship", "aggregate_retailer", "location", "co_presence")]}

    def get_limitations(self, _a) -> dict:
        return {"items": [_brief(i) for i in self.of_type("limitation")]}

    def get_context_and_contradictions(self, _a) -> dict:
        out = [i for i in self.of_type("context_event", "co_presence")]
        out += [i for i in self.of_type("comparison") if i["computed"].get("ratio") is not None and i["computed"]["ratio"] <= 1.25]
        out += [i for i in self.of_type("risk_factor") if not i["computed"]["triggered"]]
        out += [i for i in self.of_type("aggregate_retailer") if not i["computed"].get("new_for_subject")]
        return {"items": [_brief(i) for i in out]}

    def get_case_summary(self, _a) -> dict:
        return {"items": [_brief(i) for i in self.of_type("alert", "metric", "sequence")]}

    def get_previous_findings(self, _a) -> dict:
        r = self.con.execute("SELECT report_id, version FROM reports WHERE case_id = ? ORDER BY version DESC LIMIT 1",
                             (self.case_id,)).fetchone()
        if not r:
            return {"note": "No saved report exists for this case yet."}
        rows = self.con.execute("""SELECT section, text, evidence_ids FROM claims WHERE report_id = ?
                                   AND verification_status = 'verified' AND kind != 'status' ORDER BY position""", (r[0],)).fetchall()
        return {"report_id": r[0], "version": r[1],
                "findings": [{"section": x[0], "text": x[1], "evidence_ids": x[2]} for x in rows][:30]}
