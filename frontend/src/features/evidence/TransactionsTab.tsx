import { ArrowDown, ArrowUp, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { EmptyState, ErrorState, LoadingBlock } from "../../components/ui/Primitives";
import { useTimeline } from "../../hooks/queries";
import { cx } from "../../lib/cx";
import { money, shortDate } from "../../lib/format";
import { SHORT_FACTOR } from "../../lib/terms";
import type { CaseDetail, TimelineTxn } from "../../types/api";
import { BookmarkButton, BOOKMARKS_IN_CASE_UI } from "../workspace/BookmarkButton";
import { useExplorer } from "../workspace/explorer";
import { useSelection } from "../workspace/selection";

type SortKey = "time" | "amount";

export function TransactionsTab({ c }: { c: CaseDetail }) {
  const { data, error, isLoading, refetch } = useTimeline(c.case_id);
  const sel = useSelection();
  const ex = useExplorer();
  const [q, setQ] = useState("");
  const [onlyLinked, setOnlyLinked] = useState(false);
  const [day, setDay] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "time", dir: 1 });
  const bodyRef = useRef<HTMLTableSectionElement>(null);
  const isAcct = c.channel === "online_account";
  const focusIds = useMemo(() => (ex.focus?.txnIds.length ? new Set(ex.focus.txnIds) : null), [ex.focus]);

  const rows = useMemo(() => {
    let t = data?.transactions ?? [];
    if (focusIds) t = t.filter((x) => focusIds.has(x.transaction_id));
    if (onlyLinked) t = t.filter((x) => x.linked_factors.length);
    if (day) t = t.filter((x) => x.date === day);
    const ql = q.trim().toLowerCase();
    if (ql) t = t.filter((x) => `${x.transaction_id} ${x.retailer_name ?? ""} ${x.city ?? ""} ${x.account_id ?? ""} ${x.transaction_type} ${x.amount}`.toLowerCase().includes(ql));
    const k = sort.key;
    return [...t].sort((a, b) => sort.dir * (k === "amount" ? a.amount - b.amount : a.timestamp_local.localeCompare(b.timestamp_local)));
  }, [data, focusIds, onlyLinked, day, q, sort]);

  useEffect(() => {
    if (!sel.highlightTxnIds.size || !bodyRef.current) return;
    const first = bodyRef.current.querySelector<HTMLElement>("[data-highlighted='true']");
    first?.scrollIntoView({ block: "nearest", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }, [sel.highlightTxnIds, rows]);

  if (error) return <ErrorState error={error} onRetry={() => refetch()} title="Could not load transactions" />;
  if (isLoading || !data) return <LoadingBlock label="Loading transactions" lines={8} />;

  const total = rows.reduce((s, r) => s + r.amount, 0);
  const header = (key: SortKey, label: string, cls = "") => {
    const on = sort.key === key;
    return (
      <th scope="col" aria-sort={on ? (sort.dir === 1 ? "ascending" : "descending") : "none"} className={cx("px-2 py-1.5 font-semibold", cls)}>
        <button type="button" onClick={() => setSort((s) => ({ key, dir: s.key === key ? (s.dir === 1 ? -1 : 1) : key === "amount" ? -1 : 1 }))}
          className="inline-flex items-center gap-0.5 uppercase hover:text-text">
          {label}{on && (sort.dir === 1 ? <ArrowUp aria-hidden className="size-3" /> : <ArrowDown aria-hidden className="size-3" />)}
        </button>
      </th>
    );
  };

  return (
    <div className="flex min-h-full flex-col">
      <div className="sticky top-0 z-10 flex flex-wrap items-center gap-2 border-b border-border bg-surface px-3 py-2">
        <div className="relative min-w-[160px] flex-1">
          <label htmlFor="txn-search" className="sr-only">Search transactions</label>
          <Search aria-hidden className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-subtle" />
          <input id="txn-search" className="field h-8 py-0 pl-7 text-[13px]" placeholder={isAcct ? "ID, type, amount…" : "ID, retailer, city, amount…"}
            value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <label htmlFor="day-filter" className="sr-only">Filter by day</label>
        <select id="day-filter" className="field h-8 w-auto py-0 text-[13px]" value={day} onChange={(e) => setDay(e.target.value)}>
          <option value="">All days</option>
          {data.days.map((d) => <option key={d.date} value={d.date}>{shortDate(d.date)} · {d.transaction_count}</option>)}
        </select>
        <label className="flex items-center gap-1.5 text-[13px] text-muted">
          <input type="checkbox" className="size-4 accent-accent" checked={onlyLinked} onChange={(e) => setOnlyLinked(e.target.checked)} />
          Supports a finding
        </label>
        <span className="ml-auto text-[12.5px] text-subtle" aria-live="polite">
          {rows.length} of {data.transactions.length} · <span className="mono">{money(total)}</span>
        </span>
      </div>

      {rows.length === 0 ? <EmptyState title="No records match these filters" /> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-[13px]">
            <caption className="sr-only">Transactions in the recent period. Select a transaction ID to open its record.</caption>
            <thead className="border-b border-border text-left text-[11.5px] tracking-wide text-subtle">
              <tr>
                {BOOKMARKS_IN_CASE_UI && <th scope="col" className="w-8 px-2 py-1.5"><span className="sr-only">Bookmark</span></th>}
                <th scope="col" className="px-2 py-1.5 font-semibold uppercase">Record</th>
                {header("time", "Time")}
                {header("amount", "Amount", "text-right")}
                <th scope="col" className="px-2 py-1.5 font-semibold uppercase">Type</th>
                <th scope="col" className="px-2 py-1.5 font-semibold uppercase">{isAcct ? "Account" : "Retailer · city"}</th>
                <th scope="col" className="px-2 py-1.5 font-semibold uppercase">Supports</th>
              </tr>
            </thead>
            <tbody ref={bodyRef}>
              {rows.map((t) => <TxnRow key={t.transaction_id} t={t} caseId={c.case_id} isAcct={isAcct} />)}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function TxnRow({ t, caseId, isAcct }: { t: TimelineTxn; caseId: string; isAcct: boolean }) {
  const sel = useSelection();
  const ex = useExplorer();
  const hl = sel.highlightTxnIds.has(t.transaction_id);
  const open = () => { sel.select(t.evidence_id, { originId: `txn-${t.transaction_id}` }); ex.mark("evidence"); };
  return (
    <tr data-highlighted={hl} className={cx("border-b border-border/60 transition-colors duration-150 hover:bg-hover",
      hl && "bg-accent/10 mark-selected")}>
      {BOOKMARKS_IN_CASE_UI && <td className="px-2 py-1"><BookmarkButton caseId={caseId} evidenceId={t.evidence_id} label={`transaction ${t.transaction_id}`} /></td>}
      <td className="px-2 py-1">
        <button id={`txn-${t.transaction_id}`} type="button" onClick={open} aria-current={hl || undefined}
          aria-label={`Open record ${t.transaction_id}, ${money(t.amount)}, ${t.timestamp_local}`}
          className="mono whitespace-nowrap text-[12.5px] text-accent hover:underline">{t.transaction_id}</button>
      </td>
      <td className="mono whitespace-nowrap px-2 py-1 text-[12.5px] text-muted">{t.timestamp_local}</td>
      <td className="mono whitespace-nowrap px-2 py-1 text-right tabular-nums">{money(t.amount)}</td>
      <td className="whitespace-nowrap px-2 py-1 text-muted">{t.transaction_type}</td>
      <td className="max-w-[200px] truncate px-2 py-1 text-muted" title={t.retailer_name ? `${t.retailer_name} · ${t.city}` : t.account_id}>
        {isAcct ? <span className="mono text-[12.5px]">{t.account_id}</span> : t.retailer_name ? <>{t.retailer_name} <span className="text-subtle">· {t.city}</span></> : "Not recorded"}
      </td>
      <td className="whitespace-nowrap px-2 py-1">
        {t.linked_factors.length > 0 ? (() => {
          const names = t.linked_factors.map((k) => SHORT_FACTOR[k] ?? k);
          return (
            <span className="text-[12px] text-warning" title={names.join(", ")}>
              <span aria-hidden>◆ </span>{names[0]}
              {names.length > 1 && <><span aria-hidden className="text-subtle"> +{names.length - 1}</span><span className="sr-only">, {names.slice(1).join(", ")}</span></>}
            </span>
          );
        })() : <span className="text-[12px] text-subtle">None</span>}
      </td>
    </tr>
  );
}
