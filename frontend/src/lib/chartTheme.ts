// One visual language for every chart. Colour meaning matches the badges:
// accent = selected · warning = linked to a fired indicator · subtle = other records · analysis = baseline/reference.
// Values are CSS custom properties, so Recharts (SVG attributes and inline styles) follows the active theme.
export const C = {
  grid: "var(--color-border)",
  axis: "var(--color-subtle)",
  text: "var(--color-muted)",
  accent: "var(--color-accent)",
  warning: "var(--color-warning)",
  subtle: "var(--color-subtle)",
  baseline: "var(--color-analysis)",
  surface: "var(--color-surface)",
  elevated: "var(--color-elevated)",
  critical: "var(--color-critical)",
  success: "var(--color-success)",
};

export const axisProps = {
  stroke: C.grid,
  tick: { fill: C.axis, fontSize: 12, fontFamily: "IBM Plex Mono, monospace" },
  tickLine: { stroke: C.grid },
};

export const tooltipStyle = {
  contentStyle: { background: C.elevated, border: "1px solid var(--color-border-strong)", borderRadius: 6, color: "var(--color-text)", fontSize: 13 },
  labelStyle: { color: "var(--color-muted)" },
  itemStyle: { color: "var(--color-text)" },
};

export const cursorFill = { fill: "color-mix(in srgb, var(--color-accent) 8%, transparent)" };

/** Resolve a CSS custom property to a concrete colour (for canvas renderers such as Cytoscape). */
export function cssVar(name: string, fallback = "#8fa3ba"): string {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}
