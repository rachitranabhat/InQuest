"""Evidence relationship graph for one case.

Edges only represent relationships that exist in the records, each with a
stated meaning. Players seen at the same retailer are connected to the
*retailer*, never to each other, and the edge says "co-location only".
Anonymous sales are shown as a counted group at the retailer, linked to nobody.
"""
from __future__ import annotations

from database.db import connect
from services import repo

EDGE_MEANING = {
    "opened_from": "Case was opened from this alert",
    "triggered_by": "Alert indicator that fired",
    "supported_by": "Transaction that contributed to this indicator",
    "attributed_to": "Purchase linked to the player by a rewards-card scan",
    "made_from": "Transaction recorded on this online account",
    "held_by": "Account holder (verified in account records)",
    "sold_at": "Transaction recorded on a terminal at this retailer",
    "located_in": "Retailer location",
    "co_located": "Also purchased at this retailer within 30 minutes — co-location only, not a relationship",
    "anonymous_at": "Unattributed sales at this retailer near the player's purchases — buyer unknown",
    "overlaps": "Context event overlapping the review window",
}


def build(case_id: str) -> dict:
    with connect() as con:
        c = repo.case_row(con, case_id)
        items = repo.evidence_items(con, case_id, c["current_snapshot_id"], include_queries=False)
        lim0 = next((i for i in items if i["provenance"].get("key") == "lim:unattributed"), None)
        anon_by_ret = {}
        if lim0 and lim0["source_ids"]:
            ids = lim0["source_ids"]
            q = f"SELECT retailer_id, COUNT(*) FROM transactions WHERE transaction_id IN ({','.join('?' * len(ids))}) GROUP BY retailer_id"
            anon_by_ret = dict(con.execute(q, ids).fetchall())
    by_key = {i["provenance"].get("key"): i for i in items}
    nodes, edges = {}, []

    def node(nid, type_, label, evidence_ids=(), **data):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "type": type_, "label": label, "evidence_ids": list(evidence_ids), "data": data}
        else:
            nodes[nid]["evidence_ids"] = sorted(set(nodes[nid]["evidence_ids"]) | set(evidence_ids))
        return nid

    def edge(src, dst, rel, evidence_ids=()):
        edges.append({"id": f"{src}>{rel}>{dst}", "source": src, "target": dst, "relation": rel,
                      "meaning": EDGE_MEANING[rel], "evidence_ids": list(evidence_ids)})

    alert = by_key["alert"]
    node(case_id, "case", case_id, [], status=c["status"], priority=c["priority"])
    node(c["alert_id"], "alert", f"{c['alert_id']} · {c['alert']['alert_type']}", [alert["evidence_id"]],
         score=c["alert_score"])
    edge(case_id, c["alert_id"], "opened_from", [alert["evidence_id"]])
    is_acct = c["channel"] == "online_account"
    subj = node(c["subject_id"], "account" if is_acct else "player", c["subject_id"], [])
    if is_acct:
        rel = by_key.get("rel:account")
        node(c["player_id"], "player", c["player_id"], [rel["evidence_id"]] if rel else [])
        edge(subj, c["player_id"], "held_by", [rel["evidence_id"]] if rel else [])
    factor_nodes = {}
    for it in items:
        if it["type"] == "risk_factor" and it["computed"]["triggered"]:
            k = it["provenance"]["key"].split(":")[1]
            fid = f"IND-{k}"
            factor_nodes[k] = fid
            node(fid, "indicator", it["title"].split(" · ")[0], [it["evidence_id"]], points=it["computed"]["points"],
                 max_points=it["computed"]["max_points"])
            edge(c["alert_id"], fid, "triggered_by", [it["evidence_id"]])
    linked = {}
    for k, f in c["factors"].items():
        if k in factor_nodes:
            for t in f["transactions"]:
                linked.setdefault(t, []).append(k)
    for it in items:
        if it["type"] != "transaction":
            continue
        x, tid = it["computed"], it["source_ids"][0]
        node(tid, "transaction", f"{tid}", [it["evidence_id"]], amount=x["amount"], timestamp_local=x["timestamp_local"],
             transaction_type=x["transaction_type"], linked_factors=linked.get(tid, []))
        edge(tid, subj, "made_from" if is_acct else "attributed_to", [it["evidence_id"]])
        for k in linked.get(tid, []):
            edge(factor_nodes[k], tid, "supported_by", [it["evidence_id"]])
        if x.get("retailer_id"):
            ret = by_key.get(f"ret:{x['retailer_id']}")
            node(x["retailer_id"], "retailer", x["retailer_name"], [ret["evidence_id"]] if ret else [], city=x["city"])
            edge(tid, x["retailer_id"], "sold_at", [it["evidence_id"]])
    for it in items:
        if it["type"] == "retailer":
            x = it["computed"]
            loc = by_key.get(f"loc:{x['city']}")
            node(x["location_id"], "location", x["city"], [loc["evidence_id"]] if loc else [])
            edge(x["retailer_id"], x["location_id"], "located_in", [it["evidence_id"]])
        elif it["type"] == "co_presence":
            x = it["computed"]
            pid = x["other_player_id"]
            node(pid, "player", pid, [it["evidence_id"]], co_located=True)
            for rid in [e for e in it["entities"] if e.startswith("RTL-")]:
                if rid in nodes:
                    edge(pid, rid, "co_located", [it["evidence_id"]])
        elif it["type"] == "context_event":
            eid = [e for e in it["entities"] if e.startswith("EVT-")][0]
            node(eid, "event", it["computed"]["event_name"], [it["evidence_id"]])
            edge(eid, case_id, "overlaps", [it["evidence_id"]])
    lim = by_key.get("lim:unattributed")
    for rid, n in sorted(anon_by_ret.items()):
        if rid not in nodes:
            continue
        nid = f"ANON-{rid}"
        node(nid, "anonymous_group", f"{n} anonymous sale{'s' if n != 1 else ''}", [lim["evidence_id"]], count=n,
             retailer_id=rid)
        edge(nid, rid, "anonymous_at", [lim["evidence_id"]])
    types = sorted({n["type"] for n in nodes.values()})
    return {"case_id": case_id, "nodes": list(nodes.values()), "edges": edges, "node_types": types,
            "edge_meanings": EDGE_MEANING}
