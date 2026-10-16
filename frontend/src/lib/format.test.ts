import { describe, expect, it } from "vitest";
import { localToMs, money, num, utcToLocal } from "./format";

describe("format", () => {
  it("formats CAD money and blanks", () => {
    expect(money(1234.5)).toBe("$1,234.50");
    expect(money(null)).toBe("Not recorded");
  });
  it("trims trailing zeros", () => {
    expect(num(55.2)).toBe("55.2");
    expect(num(40)).toBe("40");
  });
  it("shows UTC timestamps in Toronto time", () => {
    // 2026-10-14 23:15Z is 19:15 EDT
    expect(utcToLocal("2026-10-14T23:15:00Z")).toContain("19:15");
  });
  it("parses local evidence timestamps", () => {
    expect(localToMs("2026-10-08 15:41")).toBe(Date.UTC(2026, 9, 8, 15, 41));
  });
});
