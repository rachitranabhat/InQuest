import * as RTooltip from "@radix-ui/react-tooltip";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { History, HistoryRow } from "../../types/api";
import { SelectionProvider } from "../workspace/selection";
import { changeText, fmtHistory, HistoryView } from "./HistoryTab";

const row = (o: Partial<HistoryRow>): HistoryRow => ({
  key: "per_day", label: "Transactions per day", unit: "per day", previous: 0.22, current: 4.43, difference: 4.21,
  change: 1913.6, change_unit: "%", kind: "rate", reliability: "ok", note: null, how: "Count ÷ days.", evidence_ids: ["EV-000575"], ...o,
});

describe("historical comparison", () => {
  it("formats shares in percentage points and rates as percentages", () => {
    expect(changeText(row({}))).toBe("+1,914%");
    expect(changeText(row({ kind: "share", change: 74.2, change_unit: "pp" }))).toBe("+74.2 pp");
    expect(fmtHistory(row({ kind: "money" }), 12.5)).toBe("$12.50");
  });
  it("never shows a percentage over a zero previous value", () => {
    expect(changeText(row({ previous: 0, change: null, change_unit: "none_before" }))).toBe("None before");
  });
  it("labels unavailable and cautioned comparisons in words", () => {
    const data: History = {
      case_id: "CASE-1", available: true, reason: null, scope: "linked purchases", sufficient: true, snapshot_id: "SNP-000001",
      periods: { previous_days: 23, recent_days: 7, previous_count: 5, recent_count: 31 },
      rows: [
        row({}),
        row({ key: "active_days", label: "Active days", previous: null, current: 3, difference: null, change: null, change_unit: null,
          reliability: "unavailable", note: "Previous active days are not stored in this evidence version, so no comparison is shown." }),
        row({ key: "retailers", label: "Retailers used", reliability: "caution", note: "Counted over periods of different length." }),
      ],
    };
    render(<RTooltip.Provider><SelectionProvider items={[]}><HistoryView data={data} refs={{}} /></SelectionProvider></RTooltip.Provider>);
    expect(screen.getByText("unavailable:")).toBeInTheDocument();
    expect(screen.getByText("caution:")).toBeInTheDocument();
    expect(screen.getAllByText("Not comparable").length).toBeGreaterThan(0);
    expect(document.body.textContent).not.toMatch(/∞|Infinity|NaN/);
  });
});
