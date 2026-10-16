import * as RTooltip from "@radix-ui/react-tooltip";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import type { Finding, FindingComparison, Findings } from "../../types/api";
import { SelectionProvider, useSelection } from "../workspace/selection";
import { CompareBars } from "./CompareBars";
import { FindingCard, importanceOf, keyNumbers } from "./FindingCard";

const wrap = (ui: ReactNode) => render(
  <RTooltip.Provider><SelectionProvider items={[]}>{ui}</SelectionProvider></RTooltip.Provider>,
);

const timingCmp = (state: "zero_observed" | "no_previous", text: string): FindingComparison => ({
  kind: "previous_vs_recent", unit: "share overnight (12–5 AM)", scale_max: 100,
  rows: [
    { period: "previous", label: "Previous 23 days", value: 0, display: "0%", unit: "%" },
    { period: "recent", label: "Recent 7 days", value: 74.2, display: "74.2%", unit: "%" },
  ],
  delta: { state, text, direction: state === "no_previous" ? null : "up" },
});

const finding: Finding = {
  key: "timing", evidence_id: "EV-000010", label: "Unusual transaction timing", technical_label: "Timing anomaly",
  triggered: true, scored: true, points: 10, max_points: 10,
  contribution: "Added 10 of a possible 10 points to the prototype score.",
  attention: "Worth a closer look. This is a reason to review, not proof of wrongdoing.",
  headline: "Most recent linked purchases happened overnight",
  change: "74.2% occurred between midnight and 5 AM, compared with 0% during the previous 23 days.",
  comparison: timingCmp("zero_observed", "Increase: 74.2 percentage points"),
  explain: { measured: "The share between 00:00 and 04:59.", usual: "0% overnight.", changed: "74.2% overnight.", why: "Counts from +5 percentage points." },
  limitations: [{ text: "Counts only purchases where the player's rewards card was scanned.", evidence_id: "EV-000040" }],
  supporting_transaction_ids: ["TXN-0000001", "TXN-0000002"],
  evidence_ids: ["EV-000010", "EV-000020"],
  verification: { status: "verified", failures: [], checked: 4, method: "Same deterministic validator as report claims" },
  technical: {
    technical_label: "Timing anomaly", rule: "share of 00:00-04:59 activity above baseline share (+5pp→+40pp)", engine: "detection/risk_scoring.py",
    metrics: [{ label: "Recent overnight share (%)", field: "night_share_pct", value: 74.2 }],
    sub_measures: [{ name: "Overnight share minus previous share", field: "x", value: 0.742, starts_at: 0.05, full_at: 0.4, weight: 1, normalized: 1 }],
    normalized_share: 1, points: 10, max_points: 10, trigger_at_share: 0.25, definitions: ["Overnight = 00:00 to 04:59."], normalization: null,
  },
};
const ctx: Findings = {
  case_id: "CASE-18009", snapshot_id: "SNP-000009", scope: "linked purchases", previous_transaction_count: 5, previous_sufficient: true,
  periods: { previous_days: 23, recent_days: 7, previous_start: "2026-09-15", previous_end: "2026-10-07", recent_start: "2026-10-08", recent_end: "2026-10-14" },
  findings: [finding],
};

describe("CompareBars", () => {
  it("shows a zero previous share as a percentage-point increase, never an infinite %", () => {
    wrap(<CompareBars cmp={timingCmp("zero_observed", "Increase: 74.2 percentage points")} emphasis />);
    expect(screen.getByText("Increase: 74.2 percentage points")).toBeInTheDocument();
    expect(screen.getByText("0%")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/∞|Infinity|NaN|—/);
  });
  it("explains missing previous records instead of drawing a zero", () => {
    wrap(<CompareBars cmp={timingCmp("no_previous", "Insufficient previous activity to establish a typical pattern.")} emphasis />);
    expect(screen.getByText("Insufficient previous activity to establish a typical pattern.")).toBeInTheDocument();
    expect(screen.getByText("No previous records")).toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });
});

describe("finding summaries", () => {
  it("key numbers come from the comparison rows and never invent a ratio", () => {
    expect(keyNumbers(finding)).toEqual({ main: "0% → 74.2%", delta: "Increase: 74.2 percentage points" });
    const none = { ...finding, comparison: timingCmp("no_previous", "x") };
    expect(keyNumbers(none)).toEqual({ main: "74.2%", delta: "No previous records" });
  });
  it("importance follows the share of maximum points", () => {
    expect(importanceOf(finding)).toBe("high");
    expect(importanceOf({ ...finding, points: 5 })).toBe("moderate");
    expect(importanceOf({ ...finding, triggered: false })).toBe("low");
  });
});

function SelProbe() {
  const s = useSelection();
  return <output data-testid="sel">{`${s.evidenceId ?? ""}|${[...s.highlightTxnIds].join(",")}`}</output>;
}

describe("FindingCard", () => {
  it("level 1 is short: title, one sentence, key numbers; details stay closed", () => {
    wrap(<FindingCard f={finding} ctx={ctx} claims={[]} refs={{}} />);
    const card = screen.getByRole("article", { name: finding.label });
    expect(within(card).getByText(finding.headline)).toBeInTheDocument();
    expect(within(card).getByText("0% → 74.2%")).toBeInTheDocument();
    expect(within(card).getByText("High importance")).toBeInTheDocument();
    expect(within(card).queryByText("What was measured")).not.toBeInTheDocument();
    expect(within(card).queryByText(finding.change)).not.toBeInTheDocument();
  });

  it("View evidence highlights the supporting records", () => {
    wrap(<><FindingCard f={finding} ctx={ctx} claims={[]} refs={{}} /><SelProbe /></>);
    fireEvent.click(screen.getByRole("button", { name: `View evidence for ${finding.label}` }));
    expect(screen.getByTestId("sel").textContent).toContain("TXN-0000001,TXN-0000002");
  });

  it("levels 2 and 3 are accessible disclosures with evidence and calculations", () => {
    wrap(<><FindingCard f={finding} ctx={ctx} claims={[]} refs={{}} /><SelProbe /></>);
    const details = screen.getByRole("button", { name: "Details" });
    expect(details).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(details);
    expect(details).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByText("What was measured")).not.toBeInTheDocument();   // method lives in Technical details
    expect(screen.queryByText(/not proof of wrongdoing/)).not.toBeInTheDocument(); // one reminder at the top instead
    expect(screen.getByText(/rewards card was scanned/)).toBeInTheDocument();      // limitations stay
    fireEvent.click(screen.getByRole("button", { name: /Open evidence EV-000040/ }));
    expect(screen.getByTestId("sel").textContent).toMatch(/^EV-000040\|/);

    fireEvent.click(screen.getByRole("button", { name: "Technical details" }));
    expect(screen.getByText("Timing anomaly", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByText("SNP-000009")).toBeInTheDocument();
    expect(screen.getByText("night_share_pct")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "How the points were calculated" })).toBeInTheDocument();
    // every evidence ID is listed at the technical level, none hidden behind "+N"
    expect(screen.getByRole("button", { name: /Open evidence EV-000020/ })).toBeInTheDocument();
  });
});
