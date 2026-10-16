"""Deterministic one-line fact statements for each signal.

These are NOT AI-generated: they are fixed sentences filled in with numbers
computed by the detection engine, so they can be shown as facts.
"""
from __future__ import annotations


def _r(x) -> str:
    """Readable multiple: 21.5 -> '22×', 3.42 -> '3.4×'."""
    return f"{x:.0f}×" if x >= 10 else f"{x:.1f}×"


def _n(x) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


def signal_fact(key: str, f: dict) -> str:
    if key == "frequency":
        r = f.get("peak_hour_ratio")
        return (f"{f['peak_hour_transactions']} transactions in one hour — normally about "
                f"{_n(f['hist_peak_hour_avg'])}" + (f" ({_r(r)})" if r else ""))
    if key == "value":
        return (f"Largest ${f['max_transaction_amount']:,.2f} vs. a usual top of "
                f"${f['hist_p95_amount']:,.2f}; average ${f['average_transaction_amount']:,.2f} "
                f"vs. ${f['hist_average_amount']:,.2f}")
    if key == "location":
        n = f["new_location_count"]
        where = f" ({', '.join(f['new_locations'])})" if n else ""
        return f"{n} new {'city' if n == 1 else 'cities'}{where} and {f['new_retailer_count']} new retailers"
    if key == "timing":
        return (f"{f['night_transaction_count']} transactions between midnight and 5 am — "
                f"{f['night_transaction_ratio']:.0%} of the week vs. {f['hist_night_ratio']:.0%} normally")
    if key == "historical":
        return (f"${f['total_amount']:,.2f} this week vs. ${f['hist_weekly_total']:,.2f} in a typical week "
                f"({_r(f['spend_ratio'])})")
    if key == "pattern":
        rep = (f"; ${f['repeated_amount_value']:,.2f} repeated {f['repeated_amount_count']}×"
               if f.get("repeated_amount_value") else "")
        return f"{f['rapid_pairs']} back-to-back pairs under 2 minutes apart{rep}"
    return ""


def case_headline(f: dict, factors: dict) -> str:
    """Short headline from the strongest signal (used on triage cards)."""
    top = max(factors.values(), key=lambda x: (x["share"], x["points"]))
    if top["points"] <= 0:
        return "Several weak signals; no single strong indicator"
    return signal_fact(top["key"], f)


def also_fired(factors: dict) -> list[str]:
    """Names of the other signals that fired, strongest first (excluding the headline one)."""
    import config

    ranked = sorted(factors.values(), key=lambda x: (x["share"], x["points"]), reverse=True)
    return [config.FACTOR_LABELS[x["key"]] for x in ranked[1:] if x["triggered"]]
