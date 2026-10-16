import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { EvidenceItem } from "../../types/api";
import { CitationChip, CitationList } from "./CitationChip";
import { SelectionProvider, useSelection } from "./selection";

function Probe() {
  const s = useSelection();
  return <output data-testid="sel">{`${s.evidenceId ?? ""}|${s.drawerOpen}|${s.originId ?? ""}`}</output>;
}

describe("CitationChip", () => {
  it("opens the cited evidence and remembers where it came from", () => {
    render(
      <SelectionProvider items={[] as EvidenceItem[]}>
        <CitationChip evidenceId="EV-000123" originId="cite-x" refInfo={{ type: "aggregate_retailer", title: "Maple Variety" }} />
        <Probe />
      </SelectionProvider>,
    );
    const chip = screen.getByRole("button", { name: /Open evidence EV-000123/ });
    expect(chip).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(chip);
    expect(screen.getByTestId("sel").textContent).toBe("EV-000123|true|cite-x");
    expect(chip).toHaveAttribute("aria-pressed", "true");
  });

  it("shows one citation inline and keeps the rest one click away", () => {
    render(
      <SelectionProvider items={[] as EvidenceItem[]}>
        <CitationList ids={["EV-000001", "EV-000002", "EV-000003"]} idBase="c1" refs={{}} />
      </SelectionProvider>,
    );
    expect(screen.getAllByRole("button", { name: /^Open evidence/ })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Show 2 more citations" }));
    expect(screen.getAllByRole("button", { name: /^Open evidence/ })).toHaveLength(3);
  });
});
