import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ErrorState, LoadingBlock, Stat } from "../../components/ui/Primitives";
import { api } from "../../lib/api";
import { axisProps, C, cursorFill, tooltipStyle } from "../../lib/chartTheme";

const STATUS_COLOR: Record<string, string> = {
  New: C.subtle, "Analysis Ready": C.baseline, "Under Review": C.accent, "Information Requested": C.warning,
  "Closed — No Further Action": C.success, Escalated: C.critical, "Closed — Suspicion Substantiated": C.warning,
};

export default function AnalyticsPage() {
  const { data, error, isLoading, refetch } = useQuery({ queryKey: ["analytics"], queryFn: api.analytics });
  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (isLoading || !data) return <LoadingBlock lines={8} />;
  const statusRows = Object.entries(data.status_counts).map(([status, count]) => ({ status, count }));
  const claimsTotal = (data.claims.verified ?? 0) + (data.claims.unverified ?? 0);
  return (
    <div className="mx-auto max-w-[1200px] space-y-4 p-4 sm:p-6">
      <header>
        <h1 className="text-[22px]">Investigation analytics</h1>
        <p className="mt-0.5 text-[14px] text-muted">Computed from records in this application. No efficiency figures are estimated or simulated.</p>
      </header>
      <dl className="panel grid grid-cols-2 gap-4 p-4 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Open cases" value={data.open} />
        <Stat label="Reviewed" value={data.reviewed} hint="with a reviewer decision" />
        <Stat label="Escalated" value={data.escalated} />
        <Stat label="Closed" value={data.closed} />
        <Stat label="Substantiated" value={data.substantiated ?? 0} hint="Investigator assessment, not a legal finding" />
        <Stat label="Median review" value={data.review_minutes.median !== null ? `${data.review_minutes.median} min` : "No reviews yet"} hint={`n = ${data.review_minutes.n}`} />
        <Stat label="Claims verified" value={claimsTotal ? `${data.claims.verified ?? 0}/${claimsTotal}` : "No reports yet"} hint="across saved reports" />
      </dl>
      <p className="text-[13px] text-subtle">{data.review_minutes.definition}</p>
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="panel p-4" aria-labelledby="st-title">
          <h2 id="st-title" className="text-[15px]">Cases by status</h2>
          <p className="sr-only">Bar chart of cases by status; values in the table below.</p>
          <div className="mt-3 h-[260px]" aria-hidden="true">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={statusRows} layout="vertical" margin={{ left: 20, right: 16 }}>
                <CartesianGrid stroke={C.grid} strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" allowDecimals={false} {...axisProps} />
                <YAxis type="category" dataKey="status" width={170} {...axisProps} tick={{ ...axisProps.tick, fontFamily: "Inter, sans-serif" }} />
                <Tooltip {...tooltipStyle} cursor={cursorFill} />
                <Bar dataKey="count" isAnimationActive={false} radius={[0, 3, 3, 0]}
                  shape={(p: { x?: number; y?: number; width?: number; height?: number; payload?: { status: string } }) => (
                    <rect x={p.x} y={p.y} width={p.width} height={p.height} rx={3} fill={STATUS_COLOR[p.payload?.status ?? ""] ?? C.accent} />
                  )} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <table className="mt-3 w-full text-[13.5px]">
            <caption className="sr-only">Cases by status</caption>
            <tbody>{statusRows.map((r) => <tr key={r.status} className="border-t border-border/70"><th scope="row" className="py-1 text-left font-normal text-muted">{r.status}</th><td className="mono py-1 text-right">{r.count}</td></tr>)}</tbody>
          </table>
        </section>
        <section className="panel p-4" aria-labelledby="dec-title">
          <h2 id="dec-title" className="text-[15px]">Reviewer decisions per day</h2>
          {data.decisions_by_day.length === 0 ? <p className="mt-3 text-[14px] text-muted">No decisions recorded yet.</p> : (<>
            <ul className="sr-only" aria-label="Reviewer decisions per day">
              {data.decisions_by_day.map((d) => <li key={d.date}>{d.date}: {d.count}</li>)}
            </ul>
            <div className="mt-3 h-[260px]" aria-hidden="true">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.decisions_by_day}>
                  <CartesianGrid stroke={C.grid} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" {...axisProps} />
                  <YAxis allowDecimals={false} width={30} {...axisProps} />
                  <Tooltip {...tooltipStyle} />
                  <Bar dataKey="count" fill={C.accent} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </>)}
          <dl className="mt-4 grid grid-cols-2 gap-3 text-[13.5px]">
            <div><dt className="text-subtle">Reports by mode</dt><dd className="mono">{Object.entries(data.reports_by_mode).map(([k, v]) => `${k}: ${v}`).join(" · ") || "none"}</dd></div>
            <div><dt className="text-subtle">PDF exports</dt><dd className="mono">{data.exports}</dd></div>
            <div><dt className="text-subtle">Copilot questions</dt><dd className="mono">{data.copilot_questions}</dd></div>
            <div><dt className="text-subtle">Reviewer actions</dt><dd className="mono">{data.actions_total}</dd></div>
          </dl>
        </section>
      </div>
    </div>
  );
}
