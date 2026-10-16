/** Investigator-facing wording. Technical names stay available (tooltips, "Calculation & sources"). */

// detection/risk_scoring technical label -> plain label (mirrors backend config.PLAIN_FACTOR_LABELS)
export const PLAIN_FACTOR: Record<string, string> = {
  "Frequency anomaly": "Unusual transaction frequency",
  "Value anomaly": "Unusual spending amounts",
  "Location anomaly": "New or unusual locations",
  "Low play-through": "Money withdrawn with little play",
  "Timing anomaly": "Unusual transaction timing",
  "Historical deviation": "Change from previous activity",
  "Repeated-pattern anomaly": "Repeated or back-to-back transactions",
};

/** Short plain names for compact lists (factor key -> words). */
export const SHORT_FACTOR: Record<string, string> = {
  frequency: "frequency", value: "amount", location: "new place", timing: "overnight timing",
  historical: "spending level", pattern: "repeats", playthrough: "little play",
};

const TITLE_RULES: [RegExp, string | ((...m: string[]) => string)][] = [
  [/^Historical baseline \((\d+) days before the window\)$/, (_m, d) => `Previous activity (${d} days before)`],
  [/^Review-window totals \(attributed purchases\)$/, "Recent activity totals (linked purchases)"],
  [/^Review-window totals \((.+)\)$/, (_m, x) => `Recent activity totals (${x})`],
  [/^Account fund flow in the review window$/, "Account money in and out (recent period)"],
  [/: baseline vs\. review window$/, ": previous vs. recent"],
  [/^Historical baseline is too short$/, "Too little previous activity"],
  [/^Purchases linked to (\S+) by rewards-card scans$/, (_m, p) => `Purchases linked to ${p} (rewards card scanned)`],
];

/** Display title for a stored evidence title. The stored title is never changed. */
export function plainTitle(type: string, title: string): string {
  let t = title;
  if (type === "risk_factor") {
    const [name, rest] = t.split(" · ");
    return PLAIN_FACTOR[name] ? `${PLAIN_FACTOR[name]}${rest ? ` · ${rest}` : ""}` : t;
  }
  for (const [rx, rep] of TITLE_RULES) {
    if (rx.test(t)) t = typeof rep === "string" ? t.replace(rx, rep) : t.replace(rx, rep as (...a: string[]) => string);
  }
  return t;
}

/** Friendly names for recorded evidence fields. Unknown fields fall back to a tidied field name. */
const FIELD: Record<string, string> = {
  amount: "Amount", timestamp_local: "Time (local)", date: "Date", time: "Time", hour: "Hour",
  transaction_type: "Type", channel: "Channel", attribution: "Linked by", retailer_id: "Retailer ID",
  retailer_name: "Retailer", city: "City", terminal_id: "Terminal", ticket_id: "Ticket", account_id: "Account",
  alert_score: "Prototype score", score_band: "Score band", alert_type: "Alert type",
  triggered_at_local: "Alert time (local)", rules_fired: "Rules that fired", indicators_fired: "Indicators that counted",
  window_start: "Recent period starts", window_end: "Recent period ends", window_days: "Recent period (days)",
  baseline_days: "Previous period (days)", points: "Points", max_points: "Maximum points", share_pct: "Share of maximum (%)",
  triggered: "Counted toward the alert", transaction_count: "Transactions", total_amount: "Total",
  average_amount: "Average amount", max_amount: "Largest amount", days_active: "Days with activity",
  first_local: "First (local)", last_local: "Last (local)", night_transactions: "Overnight transactions (12–5 AM)",
  unique_retailers: "Retailers", unique_cities: "Cities", baseline_transaction_count: "Previous transactions",
  transactions_per_day: "Per day", p95_amount: "Usual high (95th percentile)", typical_week_total: "Typical 7-day total",
  busiest_hour_average: "Busiest hour (average)", night_share_pct: "Overnight share (%)", sufficient: "Enough previous activity",
  usual_cities: "Usual cities", metric: "Measure", baseline: "Previous", current: "Recent", ratio: "Recent ÷ previous",
  change_pct: "Change (%)", share_of_window: "Share of recent activity", new_for_subject: "Not used before",
  in_baseline: "Used before", location_id: "Location ID", terminal_count: "Terminals", first_time: "First time",
  last_time: "Last time", retailer_count: "Retailers", start_local: "Starts (local)", end_local: "Ends (local)",
  start_time: "Start time", end_time: "End time", minutes: "Minutes", relationship: "Relationship", verified: "Verified",
  attributed_count: "Linked purchases", other_player_id: "Other player", window_minutes: "Within (minutes)",
  verified_relationship: "Verified relationship", event_name: "Event", start: "Starts", end: "Ends",
  subject_transactions_during_event: "This subject's transactions during the event",
  subject_share_pct: "Share of this subject's activity (%)", network_daily_baseline: "All terminals per day, before",
  network_daily_during_event: "All terminals per day, during", network_ratio: "All terminals: during ÷ before",
  anonymous_nearby_count: "Anonymous purchases nearby", case_specific: "Specific to this case",
  absence_is_not_proof: "Missing data is not proof", peak_hour_transactions: "Busiest 60 minutes",
  baseline_busiest_hour: "Previous busiest hour (average)", peak_hour_ratio: "Busiest-hour ratio",
  baseline_per_day: "Previous per day", frequency_ratio: "Per-day ratio", baseline_average: "Previous average",
  baseline_p95: "Previous usual high (95th percentile)", avg_ratio: "Average ratio", max_vs_p95: "Largest ÷ usual high",
  new_city_count: "New cities", new_cities: "New city names", new_retailer_count: "New retailers",
  baseline_night_share_pct: "Previous overnight share (%)", window_total: "Recent total", spend_ratio: "Spend ratio",
  rapid_pairs: "Back-to-back pairs (< 2 min)", repeated_amount_count: "Repeated identical amounts",
  repeated_amount: "Repeated amount", deposits: "Deposits", wagers: "Wagers", withdrawals: "Withdrawals",
  payouts: "Payouts", wagered_pct: "Wagered (% of deposits)", withdrawn_pct: "Withdrawn (% of deposits)",
  wagered_pct_of_deposits: "Wagered (% of deposits)", withdrawn_pct_of_deposits: "Withdrawn (% of deposits)",
};

export function fieldLabel(k: string): string {
  if (FIELD[k]) return FIELD[k];
  return k.replace(/_/g, " ").replace(/\bpct\b/, "(%)").replace(/^\w/, (m) => m.toUpperCase());
}

/** Provenance keys -> plain labels ("Data sources"). */
export const SOURCE_FIELD: Record<string, string> = {
  table: "Table", record: "Record", rule: "Rule", engine: "Calculated by", period: "Period", scope: "Counts",
  note: "Note", source: "Source", rules: "Rules", group_by: "Grouped by", field: "Field", kind: "Kind",
  baseline_period_days: "Previous period (days)", window_days: "Recent period (days)",
};
