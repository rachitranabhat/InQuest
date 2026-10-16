const TZ = "America/Toronto";
let displayTz = TZ;

export function setDisplayTimezone(tz: string | undefined) {
  if (tz) displayTz = tz;
}

export function money(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "Not recorded";
  return new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD", currencyDisplay: "narrowSymbol" }).format(n);
}

export function num(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "Not recorded";
  return Number.isInteger(n) ? String(n) : n.toFixed(digits).replace(/\.0+$/, "");
}

/** UTC ISO → "Oct 14, 2026, 13:26" in the display timezone. */
export function utcToLocal(iso: string | null | undefined, withDate = true): string {
  if (!iso) return "Not recorded";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: displayTz,
    ...(withDate ? { month: "short", day: "numeric", year: "numeric" } : {}),
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(d);
}

/** UTC ISO → "Oct 14" (or with year) in the display timezone. */
export function localDate(iso: string | null | undefined, withYear = false): string {
  if (!iso) return "Not recorded";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("en-CA", { timeZone: displayTz, month: "short", day: "numeric", ...(withYear ? { year: "numeric" } : {}) }).format(d);
}

/** "3 min ago", "5 h ago", "2 d ago"; older dates fall back to the short local date. */
export function relativeTime(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "Not recorded";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return "Just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 14) return `${Math.floor(s / 86400)} d ago`;
  return new Intl.DateTimeFormat("en-CA", { timeZone: displayTz, month: "short", day: "numeric", year: "numeric" }).format(new Date(t));
}

/** Evidence already carries local "YYYY-MM-DD HH:MM" strings; parse for charts (minutes since epoch, local). */
export function localToMs(s: string): number {
  const [d, t = "00:00"] = s.split(" ");
  const [y, m, day] = d.split("-").map(Number);
  const [hh, mm] = t.split(":").map(Number);
  return Date.UTC(y, m - 1, day, hh, mm);
}

export function msToLocalLabel(ms: number): string {
  const d = new Date(ms);
  const mo = d.toLocaleString("en-CA", { month: "short", timeZone: "UTC" });
  return `${mo} ${d.getUTCDate()} ${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

export function shortDate(ymd: string): string {
  const [y, m, d] = ymd.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-CA", { month: "short", day: "numeric", weekday: "short", timeZone: "UTC" });
}

export function humanType(t: string): string {
  return (
    {
      transaction: "Transaction",
      alert: "Alert",
      risk_factor: "Indicator",
      metric: "Recent totals",
      baseline: "Previous activity",
      comparison: "Previous vs. recent",
      aggregate_retailer: "Retailer total",
      aggregate_day: "Daily total",
      retailer: "Retailer",
      location: "City",
      sequence: "Busiest hour",
      relationship: "Link to player",
      co_presence: "Same place, same time",
      context_event: "Context event",
      limitation: "Missing information",
      query_result: "Copilot query",
    } as Record<string, string>
  )[t] ?? t.replace(/_/g, " ");
}

export function channelLabel(c: string): string {
  return c === "online_account" ? "Online account" : "Lottery terminal";
}
