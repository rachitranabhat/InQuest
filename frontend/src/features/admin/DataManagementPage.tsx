import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Database, Search } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { useApp } from "../../app/AppContext";
import { Button } from "../../components/ui/Button";
import { EmptyState, ErrorState, LoadingBlock, Stat } from "../../components/ui/Primitives";
import { api } from "../../lib/api";
import { cx } from "../../lib/cx";
import { money, num, utcToLocal } from "../../lib/format";
import { DemoAuthNotice, SeniorGate } from "../restricted/SeniorGate";

const COUNT_LABELS: [string, string][] = [
  ["players", "Players"], ["transactions", "Transactions"], ["retailers", "Retailers"], ["cases", "Cases"],
  ["alerts", "Alerts"], ["audit_records", "Audit records"], ["evidence_items", "Evidence items"], ["reports", "Reports"],
];
const TABLES: [string, string][] = [
  ["cases", "Cases"], ["alerts", "Alerts"], ["players", "Players"], ["transactions", "Transactions"], ["retailers", "Retailers"], ["audit", "Audit records"],
];
const FILTERS: Record<string, { key: string; label: string; options: string[] }[]> = {
  cases: [
    { key: "priority", label: "Priority", options: ["Critical review priority", "High review priority", "Medium review priority", "Lower review priority"] },
    { key: "channel", label: "Channel", options: ["lottery_terminal", "online_account"] },
  ],
  transactions: [
    { key: "channel", label: "Channel", options: ["lottery_terminal", "online_account"] },
    { key: "attribution", label: "Attribution", options: ["rewards_card_scan", "account_holder", "none"] },
  ],
  audit: [{ key: "action", label: "Action", options: ["start_review", "add_note", "request_info", "close_no_action", "escalate", "reopen"] }],
};
const PAGE = 25;

export default function DataManagementPage() {
  return <SeniorGate title="Data Management"><DataManagement /></SeniorGate>;
}

function DataManagement() {
  const { config } = useApp();
  const sum = useQuery({ queryKey: ["admin", "summary"], queryFn: api.dataSummary });
  const [table, setTable] = useState("cases");
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [offset, setOffset] = useState(0);
  const params = { q: q || undefined, ...filters, limit: PAGE, offset };
  const rows = useQuery({ queryKey: ["admin", "table", table, params], queryFn: () => api.dataTable(table, params), placeholderData: keepPreviousData });
  const pick = (t: string) => { setTable(t); setFilters({}); setOffset(0); setQ(""); };

  return (
    <div className="mx-auto max-w-[1300px] space-y-4 p-4 sm:p-6">
      <header className="space-y-2">
        <h1 className="flex items-center gap-2 text-[22px]"><Database aria-hidden className="size-5 text-accent" /> Data Management</h1>
        <p className="text-[14px] text-muted">
          Read-only view of the SQLite database. Search and filters use fixed, server-defined columns; nothing here can
          change or delete records, and identity details are only available in <Link to="/restricted" className="underline">Restricted Records</Link>.
        </p>
        <DemoAuthNotice />
      </header>

      <section className="panel p-4" aria-labelledby="dm-counts">
        <h2 id="dm-counts" className="sr-only">Record counts</h2>
        {sum.error ? <ErrorState error={sum.error} onRetry={() => sum.refetch()} title="Could not load the summary" />
          : !sum.data ? <LoadingBlock lines={2} />
          : (
            <>
              <dl className="grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(9.5rem,1fr))]">
                {COUNT_LABELS.map(([k, l]) => <Stat key={k} label={l} value={num(sum.data.counts[k] ?? 0)} />)}
              </dl>
              <p className="mt-3 text-[12.5px] text-subtle">
                {sum.data.engine} · <span className="mono">{sum.data.file}</span> · schema v{sum.data.schema_version} · dataset v{sum.data.dataset.version ?? "?"}
                {" "}(seed {sum.data.dataset.seed ?? "?"}, built {utcToLocal(sum.data.dataset.built_utc)}) · {num(sum.data.counts.identity_records ?? 0)} fictional
                identity records · {num(sum.data.counts.identity_access_records ?? 0)} identity accesses logged
              </p>
            </>
          )}
      </section>

      <section className="panel overflow-hidden" aria-labelledby="dm-browse">
        <div className="panel-head flex-wrap">
          <h2 id="dm-browse" className="text-[15px]">Browse records</h2>
          <div role="tablist" aria-label="Table" className="flex flex-wrap gap-1">
            {TABLES.map(([t, l]) => (
              <button key={t} type="button" role="tab" aria-selected={table === t} onClick={() => pick(t)}
                className={cx("rounded-md px-2.5 py-1 text-[13px] font-medium transition-colors", table === t ? "bg-elevated text-text" : "text-muted hover:bg-hover hover:text-text")}>
                {l}
              </button>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap items-end gap-2 border-b border-border px-4 py-2.5">
          <div className="relative">
            <label htmlFor="dm-q" className="label">Search IDs{table === "retailers" ? ", names or cities" : ""}</label>
            <Search aria-hidden className="pointer-events-none absolute bottom-2 left-2 size-3.5 text-subtle" />
            <input id="dm-q" className="field mt-1 h-8 w-[220px] pl-7 text-[13px]" value={q} maxLength={60}
              onChange={(e) => { setQ(e.target.value); setOffset(0); }} />
          </div>
          {(FILTERS[table] ?? []).map((f) => (
            <div key={f.key}>
              <label htmlFor={`dm-f-${f.key}`} className="label">{f.label}</label>
              <select id={`dm-f-${f.key}`} className="field mt-1 h-8 py-0 text-[13px]" value={filters[f.key] ?? ""}
                onChange={(e) => { setFilters((m) => ({ ...m, [f.key]: e.target.value })); setOffset(0); }}>
                <option value="">All</option>
                {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            </div>
          ))}
          {table === "cases" && (
            <div>
              <label htmlFor="dm-f-status" className="label">Status</label>
              <select id="dm-f-status" className="field mt-1 h-8 py-0 text-[13px]" value={filters.status ?? ""}
                onChange={(e) => { setFilters((m) => ({ ...m, status: e.target.value })); setOffset(0); }}>
                <option value="">All</option>
                {(config?.statuses ?? []).map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
          )}
        </div>
        {rows.error ? <ErrorState error={rows.error} onRetry={() => rows.refetch()} />
          : !rows.data ? <LoadingBlock lines={6} />
          : !rows.data.rows.length ? <EmptyState title="No records match" />
          : (
            <>
              <div className="overflow-x-auto" tabIndex={0} role="region" aria-label={`${table} records`}>
                <table className="w-full text-[13px]">
                  <thead className="text-left text-[12px] text-subtle">
                    <tr>{rows.data.columns.map((c) => <th key={c} scope="col" className="whitespace-nowrap px-3 py-2 font-medium">{c.replace(/_/g, " ")}</th>)}</tr>
                  </thead>
                  <tbody>
                    {rows.data.rows.map((r, i) => (
                      <tr key={i} className="border-t border-border/60">
                        {rows.data.columns.map((c) => <td key={c} className="whitespace-nowrap px-3 py-1.5">{cell(c, r[c])}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex items-center justify-end gap-2 border-t border-border px-4 py-2 text-[13px] text-subtle">
                <span>{num(offset + 1)}–{num(Math.min(offset + PAGE, rows.data.total))} of {num(rows.data.total)}</span>
                <Button size="sm" variant="ghost" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - PAGE))}>Previous</Button>
                <Button size="sm" variant="ghost" disabled={offset + PAGE >= rows.data.total} onClick={() => setOffset((o) => o + PAGE)}>Next</Button>
              </div>
            </>
          )}
      </section>
    </div>
  );
}

function cell(col: string, v: string | number | null) {
  if (v === null || v === "") return <span className="text-subtle">Not recorded</span>;
  if (col === "case_id") return <Link to={`/cases/${v}`} className="mono">{v}</Link>;
  if (col.startsWith("has_")) return v ? "Yes" : "No";
  if (col === "amount") return <span className="mono">{money(Number(v))}</span>;
  if (col.endsWith("_utc")) return <span className="text-muted">{utcToLocal(String(v))}</span>;
  if (/_id$/.test(col)) return <span className="mono">{v}</span>;
  if (typeof v === "number") return <span className="mono">{num(v)}</span>;
  return v;
}
