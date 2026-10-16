import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PriorityBadge, VerificationBadge } from "./Badges";

describe("badges never rely on colour alone", () => {
  it("priority badge names the priority in text", () => {
    render(<PriorityBadge priority="Critical review priority" />);
    expect(screen.getByText(/Critical/)).toBeInTheDocument();
  });
  it("unverified claims are labelled as such", () => {
    render(<VerificationBadge status="unverified" />);
    expect(screen.getByText("Unverified")).toBeInTheDocument();
  });
  it("compact verified badge keeps a screen-reader label", () => {
    render(<VerificationBadge status="verified" compact />);
    expect(screen.getByText("Verified")).toHaveClass("sr-only");
  });
});
