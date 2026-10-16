import { CalendarClock, Zap } from "lucide-react";
import { useMemo } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { ErrorState, LoadingBlock } from "../../components/ui/Primitives";
import { useTimeline } from "../../hooks/queries";
import { axisProps, C, cursorFill, tooltipStyle } from "../../lib/chartTheme";
import { localToMs, money, msToLocalLabel, shortDate } from "../../lib/format";
import type { CaseDetail, EvidenceItem, TimelineTxn } from "../../types/api";
import { CitationChip } from "../workspace/CitationChip";
import { useExplorer } from "../workspace/explorer";
import { useSelection } from "../workspace/selection";

/**
 * part: "records"    the context notes and the scatter of every transaction (Evidence tab)
 *       "comparison" the previous-vs-recent charts: per day vs. previous average, hour of day (Historical Comparison)
 *       "all"        both (default)
 */
export function TimelineTab({ c, items, part = "all" }: { c: CaseDetail; items: EvidenceItem[]; part?: "all" | "records" | "comparison" }) {
  const { data, error, isLoading, refetch } = useTimeline(c.case_id);
  const sel = useSelection();
  const ex = useExplorer();
  const isAcct = c.channel === "online_account";
  const burst = items.find((i) => i.type === "sequence");
  const events = items.filter((i) => i.type === "context_event");
  const refs = useMemo(() => Object.fromEntries(items.map((i) => [i.evidence_id, { type: i.type, title: i.title }])), [items]);

  if (error) return <ErrorState error={error} onRetry={() => refetch()} title="Could not load the timeline" />;
  if (isLoading || !data) return <LoadingBlock label="Loading timeline" lines={6} />;

  const points = data.transactions.map((t) => ({
    x: localToMs(t.timestamp_local), y: t.amount, t,
    kind: sel.highlightTxnIds.has(t.transaction_id) ? "selected" : t.linked_factors.length ? "linked" : "other",
  }));
  const hp = data.hour_profile;
  const hours = Array.from({ length: 24 }, (_, h) => ({
    hour: h,
    previous: hp.baseline_per_day[h] ?? 0,
    recent: Math.round(((hp.window_total[h] ?? 0) / Math.max(1, hp.window_days)) * 100) / 100,
  }));
  const open = (t: TimelineTxn) => { sel.select(t.evidence_id); ex.mark("evidence"); };

  return (
    <div className="space-y-5 p-3">
      {part !== "comparison" && (burst || events.length > 0) && (
        <ul className="grid gap-2 sm:grid-cols-2">
          {burst && (
            <li className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/5 px-2.5 py-2 text-[13px]">
              <Zap aria-hidden className="mt-0.5 size-4 shrink-0 text-warning" />
              <span className="min-w-0 flex-1">
                <strong className="font-semibold">Busiest 60 minutes:</strong> {String(burst.computed.transaction_count)} transactions,{" "}
                <span className="mono">{money(burst.computed.total_amount as number)}</span>, {String(burst.computed.start_local)}–{String(burst.computed.end_time)}{" "}
                <CitationChip evidenceId={burst.evidence_id} originId={`tl-${burst.evidence_id}`} refInfo={refs[burst.evidence_id]} />
              </span>
            </li>
          )}
          {events.map((e) => (
            <li key={e.evidence_id} className="flex items-start gap-2 rounded-md border border-analysis/40 bg-analysis/5 px-2.5 py-2 text-[13px]">
              <CalendarClock aria-hidden className="mt-0.5 size-4 shrink-0 text-analysis" />
              <span className="min-w-0 flex-1">
                <strong className="font-semibold">Context:</strong> {String(e.computed.event_name)} ({String(e.computed.start)} to {String(e.computed.end)})
                {e.computed.network_ratio ? <>; network-wide sales <span className="mono">{String(e.computed.network_ratio)}×</span> usual</> : null}{" "}
                <CitationChip evidenceId={e.evidence_id} originId={`tl-${e.evidence_id}`} refInfo={refs[e.evidence_id]} />
              </span>
            </li>
          ))}
        </ul>
      )}

      {part !== "comparison" && <figure aria-labelledby="tl-cap">
        <figcaption id="tl-cap" className="mb-1 text-[12.5px] font-semibold uppercase tracking-wide text-subtle">Every transaction by time and amount</figcaption>
        <p className="sr-only">{`Scatter chart of ${data.transactions.length} transactions; the Transactions tab lists the same data.`}</p>
        <div className="h-[210px]" aria-hidden="true">
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ top: 6, right: 8, bottom: 2, left: 0 }}>
              <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
              <XAxis dataKey="x" type="number" domain={["dataMin", "dataMax"]} {...axisProps} tickFormatter={(v) => msToLocalLabel(v as number).slice(0, 6)} />
              <YAxis dataKey="y" type="number" width={52} {...axisProps} tickFormatter={(v) => `$${v}`} />
              <ZAxis range={[36, 36]} />
              <Tooltip {...tooltipStyle} cursor={{ stroke: C.grid }}
                formatter={(v, nm) => (nm === "y" ? [money(v as number), "Amount"] : [msToLocalLabel(v as number), "Time"])} />
              {(["other", "linked", "selected"] as const).map((k) => (
                <Scatter key={k} data={points.filter((p) => p.kind === k)} isAnimationActive={false}
                  fill={k === "selected" ? C.accent : k === "linked" ? C.warning : C.subtle} shape={k === "linked" ? "diamond" : "circle"}
                  onClick={(p: { t?: TimelineTxn }) => p?.t && open(p.t)} className="cursor-pointer" />
              ))}
            </ScatterChart>
          </ResponsiveContainer>
        </div>
        <ul className="mt-1 flex flex-wrap gap-3 text-[12px] text-muted" aria-label="Chart legend">
          <li className="flex items-center gap-1.5"><span aria-hidden className="size-2.5 rotate-45 bg-warning" />Supports a finding</li>
          <li className="flex items-center gap-1.5"><span aria-hidden className="size-2.5 rounded-full bg-subtle" />Other {isAcct ? "account records" : "linked purchases"}</li>
          <li className="flex items-center gap-1.5"><span aria-hidden className="size-2.5 rounded-full bg-accent" />Highlighted</li>
        </ul>
      </figure>}

      {part !== "records" && <div className="grid gap-5 lg:grid-cols-2">
        <figure aria-labelledby="days-cap">
          <figcaption id="days-cap" className="mb-1 text-[12.5px] font-semibold uppercase tracking-wide text-subtle">
            {isAcct ? "Deposits" : "Purchases"} per day <span className="font-normal normal-case tracking-normal">· dashed = previous average ({data.baseline_daily_average}/day)</span>
          </figcaption>
          <div className="h-[150px]" aria-hidden="true">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.days} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid stroke={C.grid} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="date" {...axisProps} tickFormatter={(d) => (d as string).slice(5)} />
                <YAxis width={30} allowDecimals={false} {...axisProps} />
                <Tooltip {...tooltipStyle} cursor={cursorFill} formatter={(v) => [v as number, "Transactions"]} labelFormatter={(d) => shortDate(d as string)} />
                <ReferenceLine y={data.baseline_daily_average} stroke={C.baseline} strokeDasharray="4 4" />
                <Bar dataKey="transaction_count" fill={C.accent} radius={[3, 3, 0, 0]} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <table className="sr-only">
            <caption>Transactions per day</caption>
            <tbody>{data.days.map((d) => <tr key={d.date}><th scope="row">{d.date}</th><td>{d.transaction_count}</td><td>{money(d.total_amount)}</td></tr>)}</tbody>
          </table>
          <ul className="mt-1 flex flex-wrap gap-1">
            {data.days.map((d) => (
              <li key={d.date}><CitationChip evidenceId={d.evidence_id} originId={`day-${d.evidence_id}`} refInfo={refs[d.evidence_id]} /></li>
            ))}
          </ul>
        </figure>

        <figure aria-labelledby="hours-cap">
          <figcaption id="hours-cap" className="mb-1 text-[12.5px] font-semibold uppercase tracking-wide text-subtle">
            Hour of day <span className="font-normal normal-case tracking-normal">· average per day, previous vs. recent</span>
          </figcaption>
          <div className="h-[150px]" aria-hidden="true">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={hours} margin={{ top: 4, right: 8, bottom: 0, left: 0 }} barGap={0}>
                <CartesianGrid stroke={C.grid} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="hour" {...axisProps} interval={3} tickFormatter={(h) => `${String(h).padStart(2, "0")}h`} />
                <YAxis width={38} {...axisProps} />
                <Tooltip {...tooltipStyle} cursor={cursorFill} labelFormatter={(h) => `${String(h).padStart(2, "0")}:00`} />
                <Legend wrapperStyle={{ fontSize: 12, color: C.text }} />
                <Bar dataKey="previous" name="Previous" fill={C.baseline} isAnimationActive={false} />
                <Bar dataKey="recent" name="Recent" fill={C.accent} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <table className="sr-only">
            <caption>Average transactions per day by hour, previous and recent periods</caption>
            <thead><tr><th scope="col">Hour</th><th scope="col">Previous</th><th scope="col">Recent</th></tr></thead>
            <tbody>{hours.filter((h) => h.previous || h.recent).map((h) => <tr key={h.hour}><th scope="row">{h.hour}:00</th><td>{h.previous}</td><td>{h.recent}</td></tr>)}</tbody>
          </table>
          <p className="mt-1 text-[12px] text-subtle">Recent = count ÷ {hp.window_days} days; previous = count ÷ {hp.baseline_days} days.</p>
        </figure>
      </div>}
    </div>
  );
}
