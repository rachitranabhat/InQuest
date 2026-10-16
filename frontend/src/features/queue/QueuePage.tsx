import { ArrowRight, GitCompareArrows, Search, X } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { useApp } from "../../app/AppContext";
import { CompletenessBadge, PriorityBadge, ScoreBand, StatusBadge } from "../../components/ui/Badges";
import { Button } from "../../components/ui/Button";
import { EmptyState, ErrorState, LoadingBlock } from "../../components/ui/Primitives";
import { useCases } from "../../hooks/queries";
import type { CaseFilters } from "../../lib/api";
import { cx } from "../../lib/cx";
import { relativeTime, utcToLocal } from "../../lib/format";
import type { CaseListItem } from "../../types/api";

const FILTER_KEYS = ["q", "status", "priority", "alert_type", "completeness", "reviewer", "date_from", "date_to", "sort"] as const;
const OPEN = ["New", "Analysis Ready", "Under Review", "Information Requested"];
const NEEDS_REVIEW = ["New", "Analysis Ready"];

const STATUS_CHIPS: [string, string][] = [
  ["New", "New"], ["Analysis Ready", "Ready"], ["Under Review", "Under review"],
  ["Information Requested", "Info requested"], ["Escalated", "Escalated"], ["Closed — No Further Action", "Closed"],
  ["Closed — Suspicion Substantiated", "Substantiated"],
];
const PRIORITY_CHIPS: [string, string][] = [
  ["Critical review priority", "Critical"], ["High review priority", "High"],
  ["Medium review priority", "Medium"], ["Lower review priority", "Lower"],
];
const EVIDENCE_CHIPS: [string, string][] = [["Complete", "Complete"], ["Partial", "Partial"], ["Limited", "Limited"]];

export function QueuePage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { session } = useApp();
  const filters: CaseFilters = useMemo(() => {
    const f: Record<string, string> = {};
    for (const k of FILTER_KEYS) {
      const v = params.get(k);
      if (v) f[k] = v;
    }
    return f;
  }, [params]);
  const [q, setQ] = useState(filters.q ?? "");
  const [picked, setPicked] = useState<string[]>([]);
  const { data, error, isLoading, isFetching, refetch } = useCases(filters);
  const all = useCases({});

  const setMany = (entries: Record<string, string>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(entries)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    setParams(next, { replace: true });
  };
  const set = (k: string, v: string) => setMany({ [k]: v });
  const listOf = (k: string) => (params.get(k) ?? "").split(",").filter(Boolean);
  const toggle = (k: string, v: string) => {
    const cur = listOf(k);
    set(k, (cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v]).join(","));
  };
  const active = FILTER_KEYS.filter((k) => k !== "sort" && params.get(k)).length;

  const stats = useMemo(() => {
    const cs = all.data?.cases ?? [];
    const open = cs.filter((c) => OPEN.includes(c.status));
    return {
      open: open.length,
      needs: open.filter((c) => NEEDS_REVIEW.includes(c.status)).length,
      urgent: open.filter((c) => /^(Critical|High)/.test(c.priority)).length,
      mine: session ? open.filter((c) => c.assigned_reviewer_id === session.reviewer.reviewer_id).length : null,
      escalated: cs.filter((c) => c.status === "Escalated").length,
    };
  }, [all.data, session]);

  const pick = (id: string) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p.slice(-1), id]));

  return (
    <div className="mx-auto max-w-[1480px] space-y-4 p-4 sm:p-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[22px] leading-tight">Investigation queue</h1>
          <p className="mt-0.5 text-[13.5px] text-muted">Simulated monitoring alerts. Scores are rule scores, not fraud probabilities.</p>
        </div>
      </header>

      <section aria-label="Queue summary" className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        <MetricTile label="Open cases" value={stats.open} onClick={() => setMany({ status: OPEN.join(",") })} />
        <MetricTile label="Need review" value={stats.needs} tone="accent" hint="New or analysis ready"
          onClick={() => setMany({ status: NEEDS_REVIEW.join(",") })} />
        <MetricTile label="Critical or high" value={stats.urgent} tone="critical" hint="Open cases"
          onClick={() => setMany({ status: OPEN.join(","), priority: PRIORITY_CHIPS.slice(0, 2).map(([v]) => v).join(",") })} />
        <MetricTile label="Assigned to me" value={stats.mine ?? "Sign in"} hint={stats.mine === null ? "Choose a reviewer" : "Open cases"}
          onClick={session ? () => setMany({ reviewer: session.reviewer.reviewer_id, status: OPEN.join(",") }) : undefined} />
        <MetricTile label="Escalated" value={stats.escalated} onClick={() => setMany({ status: "Escalated" })} />
      </section>

      <section aria-label="Filters" className="panel space-y-3 p-3">
        <div className="flex flex-wrap items-end gap-2.5">
          <form role="search" className="min-w-[220px] flex-[2]" onSubmit={(e) => { e.preventDefault(); set("q", q.trim()); }}>
            <label htmlFor="queue-search" className="label">Search</label>
            <div className="relative mt-1">
              <Search aria-hidden className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-subtle" />
              <input id="queue-search" className="field h-9 pl-8" placeholder="Case, player, account or alert type" value={q}
                onChange={(e) => setQ(e.target.value)} onBlur={() => set("q", q.trim())} />
            </div>
          </form>
          <Select id="f-type" label="Alert type" value={filters.alert_type} onChange={(v) => set("alert_type", v)}
            options={(data?.facets.alert_types ?? []).map((t) => [t, t])} />
          <div>
            <label htmlFor="f-from" className="label block">Alert from</label>
            <input id="f-from" type="date" className="field mt-1 h-9 w-[150px] py-0" value={filters.date_from ?? ""} onChange={(e) => set("date_from", e.target.value)} />
          </div>
          <div>
            <label htmlFor="f-to" className="label block">to</label>
            <input id="f-to" type="date" className="field mt-1 h-9 w-[150px] py-0" value={filters.date_to ?? ""} onChange={(e) => set("date_to", e.target.value)} />
          </div>
          <Select id="f-reviewer" label="Reviewer" value={filters.reviewer} onChange={(v) => set("reviewer", v)}
            options={[["unassigned", "Unassigned"], ...(data?.facets.reviewers ?? []).map((r) => [r.reviewer_id, r.display_name] as [string, string])]} />
          <Select id="f-sort" label="Sort by" value={filters.sort ?? "priority"} onChange={(v) => set("sort", v)} allowEmpty={false}
            options={[["priority", "Review priority"], ["score", "Alert score"], ["newest", "Newest alert"], ["updated", "Last updated"]]} />
        </div>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <ChipGroup label="Status" chips={STATUS_CHIPS} selected={listOf("status")} onToggle={(v) => toggle("status", v)} />
          <ChipGroup label="Priority" chips={PRIORITY_CHIPS} selected={listOf("priority")} onToggle={(v) => toggle("priority", v)} />
          <ChipGroup label="Evidence" chips={EVIDENCE_CHIPS} selected={listOf("completeness")} onToggle={(v) => toggle("completeness", v)} />
          {active > 0 && (
            <Button variant="ghost" size="sm" className="ml-auto" icon={<X aria-hidden className="size-4" />}
              onClick={() => { setQ(""); setParams(new URLSearchParams(), { replace: true }); }}>
              Clear {active} filter{active > 1 ? "s" : ""}
            </Button>
          )}
        </div>
      </section>

      <section aria-labelledby="queue-table-title" className="panel relative overflow-hidden">
        <div className="panel-head py-2.5">
          <h2 id="queue-table-title" className="text-[14.5px]">
            {data ? `${data.count} case${data.count === 1 ? "" : "s"}` : "Cases"}
            {isFetching && !isLoading && <span className="ml-2 text-[13px] font-normal text-subtle">Updating…</span>}
          </h2>
          <div className="flex items-center gap-2" aria-live="polite">
            {picked.length > 0 && <span className="text-[13px] text-muted">{picked.length} of 2 selected to compare</span>}
            <Button size="sm" variant={picked.length === 2 ? "primary" : "secondary"} disabled={picked.length !== 2}
              icon={<GitCompareArrows aria-hidden className="size-4" />}
              onClick={() => navigate(`/compare?a=${picked[0]}&b=${picked[1]}`)}>
              Compare cases
            </Button>
          </div>
        </div>
        {error ? (
          <ErrorState error={error} onRetry={() => refetch()} title="Could not load the queue" />
        ) : isLoading ? (
          <LoadingBlock label="Loading cases" lines={8} />
        ) : !data?.cases.length ? (
          <EmptyState title="No cases match these filters">Clear a filter or search for a different case.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1040px] text-left text-[13.5px]">
              <caption className="sr-only">Investigation cases. Select a case ID to open its workspace; tick two cases to compare them.</caption>
              <thead className="border-b border-border bg-bg/40 text-[12px] uppercase tracking-wide text-subtle">
                <tr>
                  <th scope="col" className="w-10 px-3 py-2"><span className="sr-only">Select to compare</span></th>
                  {["Case ID", "Alert type", "Priority", "Score band", "Evidence", "Status", "Last updated", "Reviewer"].map((h) => (
                    <th key={h} scope="col" className="whitespace-nowrap px-3 py-2 font-semibold">{h}</th>
                  ))}
                  <th scope="col" className="px-3 py-2"><span className="sr-only">Open</span></th>
                </tr>
              </thead>
              <tbody>
                {data.cases.map((c) => (
                  <Row key={c.case_id} c={c} picked={picked.includes(c.case_id)} onPick={() => pick(c.case_id)}
                    onOpen={() => navigate(`/cases/${c.case_id}`)} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function Row({ c, picked, onPick, onOpen }: { c: CaseListItem; picked: boolean; onPick: () => void; onOpen: () => void }) {
  return (
    <tr className={cx("row-interactive cursor-pointer border-b border-border/70 last:border-0", picked && "bg-accent/[0.06]")}
      onClick={(e) => { if (!(e.target as HTMLElement).closest("a,button,input,label")) onOpen(); }}>
      <td className="px-3 py-2">
        <input type="checkbox" className="size-4 accent-accent" checked={picked} onChange={onPick}
          aria-label={`Select ${c.case_id} to compare`} />
      </td>
      <td className="px-3 py-2">
        <Link to={`/cases/${c.case_id}`} className="mono whitespace-nowrap font-medium text-accent">{c.case_id}</Link>
        <div className="mono whitespace-nowrap text-[12px] text-subtle">{c.subject_id}</div>
      </td>
      <td className="max-w-[240px] px-3 py-2">
        <div className="truncate" title={c.alert_type}>{c.alert_type}</div>
        <div className="truncate text-[12px] text-subtle" title={c.scenario_title ?? c.primary_reason}>{c.scenario_title ?? c.primary_reason}</div>
      </td>
      <td className="px-3 py-2"><PriorityBadge priority={c.priority} short /></td>
      <td className="px-3 py-2"><ScoreBand band={c.score_band} score={c.alert_score} /></td>
      <td className="px-3 py-2"><CompletenessBadge value={c.evidence_completeness} short /></td>
      <td className="px-3 py-2"><StatusBadge status={c.status} /></td>
      <td className="whitespace-nowrap px-3 py-2 text-muted" title={utcToLocal(c.updated_at_utc)}>{relativeTime(c.updated_at_utc)}</td>
      <td className="whitespace-nowrap px-3 py-2 text-muted">{c.assigned_reviewer ?? <span className="text-subtle">Unassigned</span>}</td>
      <td className="px-3 py-2 text-right">
        <Link to={`/cases/${c.case_id}`} aria-label={`Open ${c.case_id}`}
          className="inline-flex items-center gap-1 rounded-md border border-border-strong px-2 py-0.5 text-[13px] text-text no-underline hover:border-accent hover:bg-hover hover:no-underline">
          Open <ArrowRight aria-hidden className="size-3.5" />
        </Link>
      </td>
    </tr>
  );
}

function MetricTile({ label, value, hint, tone, onClick }: {
  label: string; value: ReactNode; hint?: string; tone?: "accent" | "critical"; onClick?: () => void;
}) {
  const body = (
    <>
      <span className="block text-[12px] font-semibold uppercase tracking-wide text-subtle">{label}</span>
      <span className={cx("mt-0.5 block text-[24px] font-semibold leading-tight tabular-nums",
        tone === "accent" ? "text-accent" : tone === "critical" ? "text-critical" : "text-text")}>{value}</span>
      {hint && <span className="block text-[12px] text-subtle">{hint}</span>}
    </>
  );
  const cls = "panel w-full px-3.5 py-2.5 text-left";
  return onClick ? (
    <button type="button" onClick={onClick} className={cx(cls, "transition-colors duration-150 hover:border-border-strong hover:bg-hover")}
      aria-label={`${label}: ${value}. Show these cases`}>{body}</button>
  ) : <div className={cls}>{body}</div>;
}

function ChipGroup({ label, chips, selected, onToggle }: {
  label: string; chips: [string, string][]; selected: string[]; onToggle: (v: string) => void;
}) {
  return (
    <div role="group" aria-label={`${label} filter`} className="flex flex-wrap items-center gap-1.5">
      <span className="mr-0.5 text-[12px] font-semibold uppercase tracking-wide text-subtle">{label}</span>
      {chips.map(([v, l]) => {
        const on = selected.includes(v);
        return (
          <button key={v} type="button" aria-pressed={on} onClick={() => onToggle(v)}
            className={cx("rounded-full border px-2.5 py-0.5 text-[12.5px] font-medium transition-colors duration-150",
              on ? "border-accent bg-accent/15 text-accent" : "border-border-strong text-muted hover:border-muted hover:text-text")}>
            {l}
          </button>
        );
      })}
    </div>
  );
}

function Select({ id, label, value, onChange, options, allowEmpty = true }: {
  id: string; label: string; value: string | undefined; onChange: (v: string) => void; options: [string, string][]; allowEmpty?: boolean;
}) {
  return (
    <div>
      <label htmlFor={id} className="label block">{label}</label>
      <select id={id} className="field mt-1 h-9 w-auto min-w-[140px] py-0" value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        {allowEmpty && <option value="">All</option>}
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </div>
  );
}
