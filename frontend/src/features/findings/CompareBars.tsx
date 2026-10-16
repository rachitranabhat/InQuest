import { ArrowDownRight, ArrowRight, ArrowUpRight, Info } from "lucide-react";
import { cx } from "../../lib/cx";
import type { FindingComparison } from "../../types/api";

/**
 * Compact comparison. Bars are decorative (aria-hidden); every value is also written out as text.
 * Previous = muted, recent = accent. Recent-only indicators are drawn against the rule's own range.
 */
export function CompareBars({ cmp, emphasis }: { cmp: FindingComparison; emphasis: boolean }) {
  const noPrevious = cmp.delta?.state === "no_previous";
  if (cmp.kind === "recent_only") return <RuleRange cmp={cmp} />;
  const max = cmp.scale_max ?? Math.max(...cmp.rows.map((r) => Math.abs(Number(r.value) || 0)), 1e-9);
  return (
    <div className="space-y-1.5">
      <ul className="space-y-2" aria-label={`Comparison: ${cmp.unit}`}>
        {cmp.rows.map((r, i) => {
          const isPrev = r.period === "previous" && cmp.kind !== "flow";
          const w = noPrevious && isPrev ? 0 : Math.max(0, Math.min(100, ((Number(r.value) || 0) / max) * 100));
          return (
            <li key={i}>
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[13px] text-muted">{r.label}</span>
                <span className="mono text-[13.5px] text-text">
                  {noPrevious && isPrev ? <span className="font-sans text-subtle">No previous records</span> : r.display}
                </span>
              </div>
              <div aria-hidden className="mt-0.5 h-2 overflow-hidden rounded-full bg-border/70">
                <div
                  className={cx("h-full rounded-full transition-[width] duration-200 motion-reduce:transition-none",
                    isPrev ? "bg-subtle/70" : emphasis ? "bg-accent" : "bg-accent/55")}
                  style={{ width: `${w > 0 ? Math.max(w, 1.5) : 0}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>
      {cmp.delta && <Delta d={cmp.delta} />}
      {cmp.note && <p className="text-[12.5px] text-subtle">{cmp.note}</p>}
    </div>
  );
}

function Delta({ d }: { d: NonNullable<FindingComparison["delta"]> }) {
  if (d.state === "no_previous") {
    return (
      <p className="flex items-start gap-1.5 text-[13px] text-warning">
        <Info aria-hidden className="mt-0.5 size-3.5 shrink-0" /> {d.text}
      </p>
    );
  }
  const Icon = d.direction === "up" ? ArrowUpRight : d.direction === "down" ? ArrowDownRight : ArrowRight;
  return (
    <p className="inline-flex items-center gap-1 rounded border border-border-strong px-1.5 py-0.5 text-[13px] text-text">
      <Icon aria-hidden className="size-3.5 text-subtle" /> {d.text}
    </p>
  );
}

function RuleRange({ cmp }: { cmp: FindingComparison }) {
  return (
    <div className="space-y-1.5">
      <ul className="space-y-1.5" aria-label={`Recent values against the rule: ${cmp.unit}`}>
        {cmp.rows.map((r, i) => {
          const full = r.full_at ?? 1;
          const top = Math.max(full * 1.25, Number(r.value) || 0);
          const pct = (v: number) => `${Math.min(100, (v / top) * 100)}%`;
          return (
            <li key={i}>
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[13px] text-muted">{r.label}</span>
                <span className="mono text-[13.5px]">
                  {r.display}
                  <span className="sr-only"> {r.unit}; counts from {r.starts_at}, full points at {r.full_at}</span>
                </span>
              </div>
              <div aria-hidden className="relative mt-0.5 h-2 rounded-full bg-border/70">
                <div className="absolute inset-y-0 left-0 rounded-full bg-accent/80" style={{ width: Number(r.value) ? pct(Number(r.value)) : 0 }} />
                {r.starts_at !== undefined && <span className="absolute -inset-y-0.5 w-px bg-warning" style={{ left: pct(r.starts_at) }} />}
                <span className="absolute -inset-y-0.5 w-px bg-critical" style={{ left: pct(full) }} />
              </div>
            </li>
          );
        })}
      </ul>
      <p className="flex flex-wrap gap-x-3 text-[12.5px] text-subtle" aria-hidden>
        <span><span className="mr-1 inline-block h-2.5 w-px bg-warning align-middle" />starts counting</span>
        <span><span className="mr-1 inline-block h-2.5 w-px bg-critical align-middle" />full points</span>
      </p>
      {cmp.note && <p className="text-[12.5px] text-subtle">{cmp.note}</p>}
    </div>
  );
}
