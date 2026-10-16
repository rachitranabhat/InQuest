import { AlertTriangle, ArrowDownRight, ArrowRight, ArrowUpRight, Ban, Calculator, Info } from "lucide-react";
import { Disclosure } from "../../components/ui/Disclosure";
import { EmptyState, ErrorState, LoadingBlock } from "../../components/ui/Primitives";
import { Term } from "../../components/ui/Term";
import { useHistory } from "../../hooks/queries";
import { cx } from "../../lib/cx";
import { money, num } from "../../lib/format";
import type { History, HistoryRow } from "../../types/api";
import { CitationList } from "../workspace/CitationChip";

type Refs = Record<string, { type: string; title: string }>;

export function fmtHistory(r: HistoryRow, v: number | null): string {
  if (v === null || v === undefined) return "Not recorded";
  if (r.kind === "money") return money(v);
  if (r.kind === "share") return `${num(v)}%`;
  return num(v, 2);
}

export function changeText(r: HistoryRow): string {
  if (r.reliability === "unavailable" || r.previous === null || r.current === null) return "Not comparable";
  if (r.change_unit === "none_before") return r.current ? "None before" : "No change";
  if (r.change === null) return "Not comparable";
  const sign = r.change > 0 ? "+" : "";
  return r.change_unit === "pp" ? `${sign}${num(r.change)} pp` : `${sign}${Math.round(r.change).toLocaleString("en-CA")}%`;
}

function diffText(r: HistoryRow): string {
  if (r.difference === null) return "Not comparable";
  const sign = r.difference > 0 ? "+" : r.difference < 0 ? "−" : "";
  const abs = Math.abs(r.difference);
  return `${sign}${r.kind === "money" ? money(abs) : r.kind === "share" ? `${num(abs)} pp` : num(abs, 2)}`;
}

export function HistoryTab({ caseId, refs }: { caseId: string; refs: Refs }) {
  const { data, error, isLoading, refetch } = useHistory(caseId);
  if (error) return <ErrorState error={error} onRetry={() => refetch()} title="Could not load the comparison" />;
  if (isLoading || !data) return <LoadingBlock label="Loading comparison" lines={6} />;
  if (!data.available) return <EmptyState title="Comparison unavailable">{data.reason}</EmptyState>;
  return <HistoryView data={data} refs={refs} />;
}

export function HistoryView({ data, refs }: { data: History; refs: Refs }) {
  const p = data.periods!;
  return (
    <div className="space-y-3 p-3">
      <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1 text-[13px]">
        <span><span className="mr-1.5 inline-block size-2.5 rounded-sm bg-analysis align-middle" aria-hidden />
          <Term term="Previous activity" />: <strong className="font-semibold">{p.previous_days} days</strong>, {p.previous_count} {data.scope}</span>
        <span><span className="mr-1.5 inline-block size-2.5 rounded-sm bg-accent align-middle" aria-hidden />
          <Term term="Recent activity" />: <strong className="font-semibold">{p.recent_days} days</strong>, {p.recent_count} {data.scope}</span>
      </div>
      {!data.sufficient && (
        <p role="note" className="flex items-start gap-2 rounded-md border border-warning/50 bg-warning/5 px-3 py-2 text-[13px]">
          <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0 text-warning" />
          {data.reason} Comparisons below are shown for context only.
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-[13px]">
          <caption className="sr-only">Previous and recent activity on normalized measures, with the difference and change.</caption>
          <thead className="border-b border-border text-left text-[11.5px] uppercase tracking-wide text-subtle">
            <tr>
              <th scope="col" className="w-[36%] py-1.5 pr-2 font-semibold">Measure</th>
              <th scope="col" className="py-1.5 pr-2 text-right font-semibold">Previous</th>
              <th scope="col" className="py-1.5 pr-2 text-right font-semibold">Recent</th>
              <th scope="col" className="w-[22%] py-1.5 pr-2 font-semibold"><span className="sr-only">Visual comparison</span></th>
              <th scope="col" className="py-1.5 pr-2 text-right font-semibold">Difference</th>
              <th scope="col" className="py-1.5 text-right font-semibold">Change</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => <Row key={r.key} r={r} />)}
          </tbody>
        </table>
      </div>
      <p className="flex items-start gap-1.5 text-[12px] text-subtle">
        <Info aria-hidden className="mt-0.5 size-3.5 shrink-0" />
        Rates are per day so periods of different length compare fairly. Shares change in percentage points (pp). A change is a reason to look closer, not a conclusion.
      </p>
      <Disclosure label="How these are calculated" icon={<Calculator aria-hidden className="size-3.5" />} buttonClassName="text-[12.5px] text-subtle">
        <dl className="mt-2 space-y-2 rounded-md border border-border bg-bg/50 p-2.5 text-[12.5px]">
          {data.rows.map((r) => (
            <div key={r.key}>
              <dt className="font-medium text-text">{r.label} <span className="mono text-subtle">({r.key})</span></dt>
              <dd className="text-muted">{r.how} <CitationList ids={r.evidence_ids} idBase={`hist-${r.key}`} refs={refs} inline={r.evidence_ids.length} /></dd>
            </div>
          ))}
          <div><dt className="font-medium text-text"><Term term="Evidence version" /></dt><dd className="mono text-muted">{data.snapshot_id}</dd></div>
        </dl>
      </Disclosure>
    </div>
  );
}

function Row({ r }: { r: HistoryRow }) {
  const max = Math.max(Math.abs(r.previous ?? 0), Math.abs(r.current ?? 0), 1e-9);
  const w = (v: number | null) => (v === null ? 0 : Math.max(v ? 2 : 0, (Math.abs(v) / max) * 100));
  const Dir = r.difference === null || r.difference === 0 ? ArrowRight : r.difference > 0 ? ArrowUpRight : ArrowDownRight;
  const dim = r.reliability === "unavailable";
  return (
    <tr className="border-b border-border/60 align-top">
      <th scope="row" className="py-2 pr-2 text-left font-normal">
        <span className="font-medium text-text">{r.label}</span> <span className="text-[12px] text-subtle">{r.unit}</span>
        {r.reliability !== "ok" && (
          <span className={cx("mt-0.5 flex items-start gap-1 text-[12px]", r.reliability === "caution" ? "text-warning" : r.reliability === "unreliable" ? "text-critical" : "text-subtle")}>
            {r.reliability === "unavailable" ? <Ban aria-hidden className="mt-0.5 size-3 shrink-0" /> : <AlertTriangle aria-hidden className="mt-0.5 size-3 shrink-0" />}
            <span><span className="font-semibold capitalize">{r.reliability}:</span> {r.note}</span>
          </span>
        )}
      </th>
      <td className={cx("mono py-2 pr-2 text-right", r.previous === null && "font-sans text-subtle")}>{fmtHistory(r, r.previous)}</td>
      <td className="mono py-2 pr-2 text-right font-medium">{fmtHistory(r, r.current)}</td>
      <td className="py-2 pr-2" aria-hidden="true">
        <div className="space-y-1 pt-1">
          <div className="h-1.5 overflow-hidden rounded-full bg-border/60"><div className="h-full rounded-full bg-analysis/80" style={{ width: `${w(r.previous)}%` }} /></div>
          <div className="h-1.5 overflow-hidden rounded-full bg-border/60"><div className={cx("h-full rounded-full", dim ? "bg-subtle" : "bg-accent")} style={{ width: `${w(r.current)}%` }} /></div>
        </div>
      </td>
      <td className="mono whitespace-nowrap py-2 pr-2 text-right">{diffText(r)}</td>
      <td className="whitespace-nowrap py-2 text-right">
        <span className={cx("inline-flex items-center gap-0.5", r.change === null && r.change_unit !== "none_before" ? "text-subtle" : "text-text")}>
          <Dir aria-hidden className="size-3.5 text-subtle" />{changeText(r)}
        </span>
      </td>
    </tr>
  );
}
