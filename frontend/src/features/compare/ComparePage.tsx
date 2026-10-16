import { ArrowRight, GitCompareArrows, Store } from "lucide-react";
import { useMemo, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CompletenessBadge, PriorityBadge, ScoreBand, StatusBadge } from "../../components/ui/Badges";
import { EmptyState, ErrorState, LoadingBlock } from "../../components/ui/Primitives";
import { useCase, useCases, useCompleteness, useEvidence, useFindings, useHistory, useTimeline } from "../../hooks/queries";
import { axisProps, C, cursorFill, tooltipStyle } from "../../lib/chartTheme";
import { cx } from "../../lib/cx";
import { channelLabel, localDate, money, num, shortDate } from "../../lib/format";
import type { CaseDetail, Completeness, CompletenessState, EvidenceItem, Finding, History, Timeline } from "../../types/api";
import { changeText, fmtHistory } from "../evidence/HistoryTab";
import { importanceOf, keyNumbers } from "../findings/FindingCard";

const SIDES = ["a", "b"] as const;
type Side = (typeof SIDES)[number];

/** Two cases side by side. Every value comes from each case's own endpoints; nothing is recomputed here. */
export default function ComparePage() {
  const [params, setParams] = useSearchParams();
  const ids: Record<Side, string> = { a: params.get("a") ?? "", b: params.get("b") ?? "" };
  const list = useCases({});
  const pick = (side: Side, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(side, v);
    else next.delete(side);
    setParams(next, { replace: true });
  };
  const ready = ids.a && ids.b && ids.a !== ids.b;
  return (
    <div className="mx-auto max-w-[1480px] space-y-4 p-4 sm:p-6">
      <header>
        <h1 className="flex items-center gap-2 text-[22px] leading-tight"><GitCompareArrows aria-hidden className="size-5 text-accent" /> Compare cases</h1>
        <p className="mt-0.5 text-[13.5px] text-muted">Indicators, activity, data coverage, timelines and retailers for two cases side by side.</p>
      </header>
      <section aria-label="Choose cases" className="panel grid gap-3 p-3 sm:grid-cols-2">
        {SIDES.map((s) => (
          <div key={s}>
            <label htmlFor={`cmp-${s}`} className="label">Case {s.toUpperCase()}</label>
            <select id={`cmp-${s}`} className="field mt-1 h-9 py-0" value={ids[s]} onChange={(e) => pick(s, e.target.value)}>
              <option value="">Choose a case…</option>
              {(list.data?.cases ?? []).map((c) => (
                <option key={c.case_id} value={c.case_id} disabled={c.case_id === ids[s === "a" ? "b" : "a"]}>
                  {c.case_id} · {c.alert_type} · {c.priority.split(" ")[0]}
                </option>
              ))}
            </select>
          </div>
        ))}
      </section>
      {ready ? <Comparison a={ids.a} b={ids.b} /> : (
        <div className="panel"><EmptyState title="Choose two different cases" icon={<GitCompareArrows aria-hidden className="size-7" />}>
          You can also tick two cases in the queue and select Compare cases.
        </EmptyState></div>
      )}
    </div>
  );
}

function useSide(id: string) {
  return {
    c: useCase(id), f: useFindings(id), h: useHistory(id), k: useCompleteness(id), t: useTimeline(id), e: useEvidence(id),
  };
}

function Comparison({ a, b }: { a: string; b: string }) {
  const A = useSide(a);
  const B = useSide(b);
  const err = A.c.error ?? B.c.error;
  if (err) return <ErrorState error={err} title="Could not load a case" />;
  if (!A.c.data || !B.c.data) return <LoadingBlock label="Loading cases" lines={8} />;
  const cases = { a: A.c.data, b: B.c.data };
  return (
    <div className="space-y-4">
      <Block title="Overview">
        <div className="grid gap-3 md:grid-cols-2">{SIDES.map((s) => <Overview key={s} side={s} c={cases[s]} />)}</div>
      </Block>
      <Block title="Indicators">
        {A.f.data && B.f.data ? <Indicators a={A.f.data.findings} b={B.f.data.findings} ids={{ a, b }} /> : <LoadingBlock lines={4} label="Loading indicators" />}
      </Block>
      <Block title="Activity patterns" note="Recent value, with the change from each case's own previous activity.">
        {A.h.data && B.h.data ? <Patterns a={A.h.data} b={B.h.data} ids={{ a, b }} /> : <LoadingBlock lines={4} label="Loading activity" />}
      </Block>
      <div className="grid gap-4 lg:grid-cols-2">
        <Block title="Evidence completeness">
          {A.k.data && B.k.data ? <CompletenessCompare a={A.k.data} b={B.k.data} ids={{ a, b }} /> : <LoadingBlock lines={4} label="Loading completeness" />}
        </Block>
        <Block title="Retailers & entities">
          {A.e.data && B.e.data ? <Retailers a={A.e.data} b={B.e.data} ids={{ a, b }} /> : <LoadingBlock lines={4} label="Loading retailers" />}
        </Block>
      </div>
      <Block title="Timelines" note="Transactions per day in each case's recent period, on the same scale.">
        {A.t.data && B.t.data ? <Timelines a={A.t.data} b={B.t.data} ids={{ a, b }} /> : <LoadingBlock lines={4} label="Loading timelines" />}
      </Block>
    </div>
  );
}

function Block({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="panel relative overflow-hidden">
      <div className="panel-head py-2.5">
        <h2 className="text-[14.5px]">{title}</h2>
        {note && <span className="text-[12px] text-subtle">{note}</span>}
      </div>
      <div className="p-3">{children}</div>
    </section>
  );
}

function SideTag({ side }: { side: Side }) {
  return <span aria-hidden className={cx("mono inline-grid size-5 place-items-center rounded text-[11.5px] font-semibold",
    side === "a" ? "bg-accent/20 text-accent" : "bg-analysis/20 text-analysis")}>{side.toUpperCase()}</span>;
}

function Overview({ side, c }: { side: Side; c: CaseDetail }) {
  return (
    <div className="rounded-md border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <SideTag side={side} />
        <Link to={`/cases/${c.case_id}`} className="mono text-[15px] font-semibold">{c.case_id}</Link>
        <PriorityBadge priority={c.priority} short />
        <StatusBadge status={c.status} />
        <Link to={`/cases/${c.case_id}`} className="ml-auto inline-flex items-center gap-1 text-[12.5px]" aria-label={`Open ${c.case_id} workspace`}>
          Open <ArrowRight aria-hidden className="size-3.5" />
        </Link>
      </div>
      <dl className="mt-2 grid grid-cols-[7rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-[13px]">
        <dt className="text-subtle">Alert type</dt><dd>{c.alert.alert_type}</dd>
        <dt className="text-subtle">Subject</dt><dd><span className="mono">{c.subject_id}</span> · {channelLabel(c.channel)}</dd>
        <dt className="text-subtle">Score</dt><dd><ScoreBand band={c.score_band} score={c.alert_score} /></dd>
        <dt className="text-subtle">Indicators</dt><dd>{c.triggered_count} counted</dd>
        <dt className="text-subtle">Evidence</dt><dd><CompletenessBadge value={c.evidence_completeness} short /></dd>
        <dt className="text-subtle">Recent period</dt><dd>{localDate(c.window_start_utc)} – {localDate(c.window_end_utc, true)}</dd>
      </dl>
    </div>
  );
}

function Indicators({ a, b, ids }: { a: Finding[]; b: Finding[]; ids: Record<Side, string> }) {
  const keys = Array.from(new Set([...a, ...b].map((f) => f.key)));
  const by = { a: new Map(a.map((f) => [f.key, f])), b: new Map(b.map((f) => [f.key, f])) };
  const label = (k: string) => (by.a.get(k) ?? by.b.get(k))!.label;
  keys.sort((x, y) => Number(!!by.b.get(y)?.triggered || !!by.a.get(y)?.triggered) - Number(!!by.b.get(x)?.triggered || !!by.a.get(x)?.triggered));
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-[13px]">
        <caption className="sr-only">Indicators for both cases</caption>
        <thead className="border-b border-border text-left text-[11.5px] uppercase tracking-wide text-subtle">
          <tr><th scope="col" className="py-1.5 pr-3 font-semibold">Indicator</th>
            {SIDES.map((s) => <th key={s} scope="col" className="py-1.5 pr-3 font-semibold"><span className="inline-flex items-center gap-1.5"><SideTag side={s} />{ids[s]}</span></th>)}</tr>
        </thead>
        <tbody>
          {keys.map((k) => (
            <tr key={k} className="border-b border-border/60 align-top">
              <th scope="row" className="py-2 pr-3 text-left font-medium">{label(k)}</th>
              {SIDES.map((s) => <td key={s} className="py-2 pr-3"><IndicatorCell f={by[s].get(k)} /></td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function IndicatorCell({ f }: { f: Finding | undefined }) {
  if (!f) return <span className="text-subtle">Not measured</span>;
  const imp = importanceOf(f);
  const n = keyNumbers(f);
  return (
    <div>
      <span className={cx("text-[12px] font-semibold", imp === "high" ? "text-critical" : imp === "moderate" ? "text-warning" : "text-subtle")}>
        {imp === "high" ? "High importance" : imp === "moderate" ? "Moderate" : "Normal range"}
      </span>
      <span className="mono ml-2 text-[12px] text-subtle">{num(f.points)}/{f.max_points} pts</span>
      {n.main && <p className="mono text-[12.5px] text-text">{n.main}</p>}
      {n.delta && <p className="text-[12px] text-muted">{n.delta}</p>}
    </div>
  );
}

function Patterns({ a, b, ids }: { a: History; b: History; ids: Record<Side, string> }) {
  const keys = Array.from(new Set([...a.rows, ...b.rows].map((r) => r.key)));
  const by = { a: new Map(a.rows.map((r) => [r.key, r])), b: new Map(b.rows.map((r) => [r.key, r])) };
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-[13px]">
        <caption className="sr-only">Recent activity and change from previous activity for both cases</caption>
        <thead className="border-b border-border text-left text-[11.5px] uppercase tracking-wide text-subtle">
          <tr><th scope="col" className="py-1.5 pr-3 font-semibold">Measure</th>
            {SIDES.map((s) => <th key={s} scope="col" className="py-1.5 pr-3 font-semibold"><span className="inline-flex items-center gap-1.5"><SideTag side={s} />{ids[s]}</span></th>)}</tr>
        </thead>
        <tbody>
          {keys.map((k) => {
            const label = (by.a.get(k) ?? by.b.get(k))!.label;
            return (
              <tr key={k} className="border-b border-border/60">
                <th scope="row" className="py-1.5 pr-3 text-left font-medium">{label}</th>
                {SIDES.map((s) => {
                  const r = by[s].get(k);
                  return (
                    <td key={s} className="py-1.5 pr-3">
                      {r ? <>
                        <span className="mono">{fmtHistory(r, r.current)}</span>
                        <span className={cx("ml-2 text-[12px]", r.reliability === "ok" ? "text-muted" : "text-warning")}>
                          {changeText(r)}{r.reliability !== "ok" && r.reliability !== "unavailable" ? ` (${r.reliability})` : ""}
                        </span>
                      </> : <span className="text-subtle">Not applicable</span>}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
      {SIDES.some((s) => !({ a, b }[s].sufficient)) && (
        <p className="mt-2 text-[12px] text-warning">One case has too little previous activity; its changes are shown for context only.</p>
      )}
    </div>
  );
}

const STATE_TONE: Record<CompletenessState, string> = {
  verified: "text-success", available: "text-success", partial: "text-warning", ambiguous: "text-warning", missing: "text-subtle",
};

function CompletenessCompare({ a, b, ids }: { a: Completeness; b: Completeness; ids: Record<Side, string> }) {
  const keys = Array.from(new Set([...a.items, ...b.items].map((i) => i.key)));
  const by = { a: new Map(a.items.map((i) => [i.key, i])), b: new Map(b.items.map((i) => [i.key, i])) };
  return (
    <table className="w-full text-[13px]">
      <caption className="sr-only">Data coverage for both cases</caption>
      <thead className="border-b border-border text-left text-[11.5px] uppercase tracking-wide text-subtle">
        <tr><th scope="col" className="py-1.5 pr-2 font-semibold">Data</th>
          {SIDES.map((s) => <th key={s} scope="col" className="py-1.5 pr-2 font-semibold"><span className="sr-only">{ids[s]}</span><SideTag side={s} /></th>)}</tr>
      </thead>
      <tbody>
        <tr className="border-b border-border/60"><th scope="row" className="py-1.5 pr-2 text-left font-medium">Overall</th>
          {SIDES.map((s) => <td key={s} className="py-1.5 pr-2"><CompletenessBadge value={{ a, b }[s].overall} short /></td>)}</tr>
        {keys.map((k) => (
          <tr key={k} className="border-b border-border/60">
            <th scope="row" className="py-1.5 pr-2 text-left font-normal">{(by.a.get(k) ?? by.b.get(k))!.label}</th>
            {SIDES.map((s) => {
              const i = by[s].get(k);
              return <td key={s} className={cx("py-1.5 pr-2 capitalize", i ? STATE_TONE[i.state] : "text-subtle")} title={i?.detail}>{i ? i.state : "Not applicable"}</td>;
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Retailers({ a, b, ids }: { a: EvidenceItem[]; b: EvidenceItem[]; ids: Record<Side, string> }) {
  const rets = { a: a.filter((i) => i.type === "aggregate_retailer"), b: b.filter((i) => i.type === "aggregate_retailer") };
  const rid = (i: EvidenceItem) => String(i.computed.retailer_id);
  const shared = new Set(rets.a.map(rid).filter((r) => rets.b.some((x) => rid(x) === r)));
  const others = { a: a.filter((i) => i.type === "co_presence"), b: b.filter((i) => i.type === "co_presence") };
  return (
    <div className="space-y-3">
      <p className="text-[13px]">
        <strong className="font-semibold">{shared.size}</strong> shared retailer{shared.size === 1 ? "" : "s"}
        {shared.size > 0 && <span className="text-muted"> (marked ●)</span>}. Shared places are context, not a link between subjects.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {SIDES.map((s) => (
          <div key={s}>
            <h3 className="mb-1 flex items-center gap-1.5 text-[12.5px] font-semibold text-muted"><SideTag side={s} />{ids[s]} · {rets[s].length} retailer{rets[s].length === 1 ? "" : "s"}</h3>
            {rets[s].length === 0 ? <p className="text-[12.5px] text-subtle">No retailer records (online account case).</p> : (
              <ul className="space-y-0.5 text-[12.5px]">
                {rets[s].slice(0, 8).map((r) => (
                  <li key={r.evidence_id} className="flex items-baseline gap-1.5">
                    <Store aria-hidden className="size-3 shrink-0 text-subtle" />
                    <span className={cx("min-w-0 flex-1 truncate", shared.has(rid(r)) ? "text-accent" : "text-text")}>
                      {shared.has(rid(r)) && <span aria-label="shared">● </span>}{String(r.computed.retailer_name)}
                    </span>
                    <span className="mono text-subtle">{String(r.computed.transaction_count)} · {money(r.computed.total_amount as number)}</span>
                  </li>
                ))}
                {rets[s].length > 8 && <li className="text-subtle">+{rets[s].length - 8} more</li>}
              </ul>
            )}
            {others[s].length > 0 && <p className="mt-1 text-[12px] text-muted">{others[s].length} other player(s) seen at the same place and time.</p>}
          </div>
        ))}
      </div>
    </div>
  );
}

function Timelines({ a, b, ids }: { a: Timeline; b: Timeline; ids: Record<Side, string> }) {
  const data = { a, b };
  const max = Math.max(1, ...a.days.map((d) => d.transaction_count), ...b.days.map((d) => d.transaction_count));
  const totals = useMemo(() => ({
    a: { n: a.transactions.length, amt: a.transactions.reduce((s, t) => s + t.amount, 0) },
    b: { n: b.transactions.length, amt: b.transactions.reduce((s, t) => s + t.amount, 0) },
  }), [a, b]);
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {SIDES.map((s) => (
        <figure key={s} aria-labelledby={`tlc-${s}`}>
          <figcaption id={`tlc-${s}`} className="mb-1 flex items-center gap-1.5 text-[12.5px] text-muted">
            <SideTag side={s} />{ids[s]} · {totals[s].n} transactions · <span className="mono">{money(totals[s].amt)}</span>
            <span className="text-subtle">· previous avg {data[s].baseline_daily_average}/day</span>
          </figcaption>
          <div className="h-[140px]" aria-hidden="true">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data[s].days} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid stroke={C.grid} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="date" {...axisProps} tickFormatter={(d) => (d as string).slice(5)} />
                <YAxis width={30} allowDecimals={false} domain={[0, max]} {...axisProps} />
                <Tooltip {...tooltipStyle} cursor={cursorFill} formatter={(v) => [v as number, "Transactions"]} labelFormatter={(d) => shortDate(d as string)} />
                <Bar dataKey="transaction_count" fill={s === "a" ? C.accent : C.baseline} radius={[3, 3, 0, 0]} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <table className="sr-only">
            <caption>{ids[s]} transactions per day</caption>
            <tbody>{data[s].days.map((d) => <tr key={d.date}><th scope="row">{d.date}</th><td>{d.transaction_count}</td></tr>)}</tbody>
          </table>
        </figure>
      ))}
    </div>
  );
}
