import * as RDialog from "@radix-ui/react-dialog";
import { ArrowLeft, Calculator, Link2, X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "../../components/ui/Button";
import { ErrorState, LoadingBlock } from "../../components/ui/Primitives";
import { api } from "../../lib/api";
import { Disclosure } from "../../components/ui/Disclosure";
import { Term } from "../../components/ui/Term";
import { humanType, money } from "../../lib/format";
import { fieldLabel, plainTitle, SOURCE_FIELD } from "../../lib/terms";
import type { EvidenceItem } from "../../types/api";
import { BookmarkButton } from "./BookmarkButton";
import { useSelection } from "./selection";

const MONEY_KEYS = /amount|total|deposit|wager|payout|withdraw|p95|average/i;

function fmtValue(k: string, v: unknown): string {
  if (v === null || v === undefined) return "Not recorded";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "number") return MONEY_KEYS.test(k) && !/count|pct|ratio|share/i.test(k) ? money(v) : String(v);
  if (Array.isArray(v)) return v.length ? v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(", ") : "None";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}


/**
 * Non-modal side drawer: the timeline and graph stay visible and interactive while evidence is open.
 * Closing returns focus to the citation that opened it ("back to report").
 */
export function EvidenceDrawer({ caseId }: { caseId: string }) {
  const sel = useSelection();
  const local = sel.evidenceId ? sel.itemById(sel.evidenceId) : undefined;
  const { data: fetched, error, isLoading } = useQuery({
    queryKey: ["evidence-item", caseId, sel.evidenceId],
    queryFn: () => api.evidenceItem(caseId, sel.evidenceId as string),
    enabled: !!sel.evidenceId && !local,
  });
  const item: EvidenceItem | undefined = local ?? fetched;

  const backToOrigin = () => {
    const id = sel.originId;
    sel.closeDrawer();
    if (id) {
      requestAnimationFrame(() => {
        const el = document.getElementById(id);
        el?.scrollIntoView({ block: "center" });
        el?.focus();
      });
    }
  };

  return (
    <RDialog.Root open={sel.drawerOpen} onOpenChange={(o) => !o && backToOrigin()} modal={false}>
      <RDialog.Portal>
        <RDialog.Content
          onInteractOutside={(e) => e.preventDefault()}
          onCloseAutoFocus={(e) => e.preventDefault()}
          aria-describedby={undefined}
          className="fixed bottom-0 right-0 top-14 z-40 flex w-full max-w-[460px] flex-col border-l border-border-strong bg-surface shadow-2xl animate-drawer-in sm:bottom-3 sm:right-3 sm:top-[4.25rem] sm:rounded-lg sm:border"
        >
          <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
            <div className="min-w-0">
              <p className="eyebrow">{item ? humanType(item.type) : "Evidence"}</p>
              <RDialog.Title className="mt-0.5 text-[16px] font-semibold leading-snug">
                {item ? plainTitle(item.type, item.title) : sel.evidenceId}
              </RDialog.Title>
              <p className="mono mt-0.5 text-[12.5px] text-subtle">{sel.evidenceId}</p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              {item?.snapshot_id && (
                <BookmarkButton caseId={caseId} evidenceId={item.evidence_id} label={plainTitle(item.type, item.title)} withText
                  className="rounded-md border border-border-strong px-2 py-1" />
              )}
              <RDialog.Close asChild>
                <Button variant="ghost" size="sm" aria-label="Close evidence" icon={<X aria-hidden className="size-4" />} />
              </RDialog.Close>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
            {error ? <ErrorState error={error} /> : isLoading || !item ? <LoadingBlock label="Loading evidence" /> : <Body item={item} />}
          </div>
          <div className="flex items-center justify-between gap-2 border-t border-border px-4 py-3">
            {sel.originId ? (
              <Button size="sm" onClick={backToOrigin} icon={<ArrowLeft aria-hidden className="size-4" />}
                aria-label="Back to where this evidence was opened">Back</Button>
            ) : <span />}
            <span className="text-[12.5px] text-subtle">Esc closes · records stay highlighted</span>
          </div>
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  );
}

function Body({ item }: { item: EvidenceItem }) {
  const sel = useSelection();
  const entries = Object.entries(item.computed).filter(([k]) => !["groups", "filters"].includes(k));
  const groups = (item.computed.groups as Record<string, unknown>[] | undefined) ?? null;
  const txnSources = item.source_ids.filter((s) => s.startsWith("TXN-"));
  return (
    <div className="space-y-4">
      <p className="text-[14.5px] leading-relaxed">{item.summary}</p>
      {item.type === "limitation" && (
        <p className="rounded-md border border-warning/50 bg-warning/5 px-3 py-2 text-[13.5px]">
          Missing data is a limitation, not proof that something did or did not happen.
        </p>
      )}
      {item.type === "co_presence" && (
        <p className="rounded-md border border-warning/50 bg-warning/5 px-3 py-2 text-[13.5px]">
          Co-location only. The records contain no verified relationship between these players.
        </p>
      )}
      <section aria-labelledby="ev-values">
        <h3 id="ev-values" className="eyebrow mb-1.5">Values</h3>
        <dl className="divide-y divide-border/70 rounded-md border border-border">
          {entries.map(([k, v]) => (
            <div key={k} className="grid grid-cols-[minmax(0,44%)_1fr] gap-3 px-3 py-1.5 text-[13.5px]">
              <dt className="text-muted">{fieldLabel(k)}</dt>
              <dd className="mono break-words text-text">{fmtValue(k, v)}</dd>
            </div>
          ))}
        </dl>
      </section>
      {groups && groups.length > 0 && (
        <section aria-labelledby="ev-groups">
          <h3 id="ev-groups" className="eyebrow mb-1.5">Groups</h3>
          <table className="w-full text-[13px]">
            <thead className="text-subtle"><tr><th scope="col" className="py-1 text-left font-medium">Group</th><th scope="col" className="py-1 text-right font-medium">Count</th><th scope="col" className="py-1 text-right font-medium">Total</th></tr></thead>
            <tbody className="mono">
              {groups.map((g) => (
                <tr key={String(g.key)} className="border-t border-border/70">
                  <td className="py-1">{String(g.retailer_name ?? g.key)}</td>
                  <td className="py-1 text-right">{String(g.transaction_count)}</td>
                  <td className="py-1 text-right">{money(g.total_amount as number)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      {txnSources.length > 0 && (
        <section aria-labelledby="ev-sources">
          <h3 id="ev-sources" className="eyebrow mb-1.5 flex items-center gap-1.5">
            <Link2 aria-hidden className="size-3.5" /> Source records ({txnSources.length})
          </h3>
          <p className="mb-2 text-[13px] text-muted">Highlighted in Transactions and the timeline. Select one to open the original record.</p>
          <ul className="flex flex-wrap gap-1.5">
            {txnSources.slice(0, 80).map((t) => (
              <li key={t}>
                <SourceButton txnId={t} />
              </li>
            ))}
          </ul>
          {txnSources.length > 80 && <p className="mt-1 text-[12.5px] text-subtle">+{txnSources.length - 80} more</p>}
        </section>
      )}
      <section aria-labelledby="ev-prov">
        <h3 id="ev-prov" className="eyebrow mb-1.5"><Term term="Data sources" /></h3>
        <dl className="space-y-1 text-[13.5px]">
          {Object.entries(item.provenance).filter(([k]) => k !== "key").map(([k, v]) => (
            <div key={k} className="flex gap-2"><dt className="shrink-0 text-subtle">{SOURCE_FIELD[k] ?? fieldLabel(k)}:</dt><dd className="break-words text-muted">{fmtValue(k, v)}</dd></div>
          ))}
          <div className="flex gap-2"><dt className="text-subtle"><Term term="Evidence version" />:</dt><dd className="mono text-muted">{item.snapshot_id ?? "Created by a copilot question (not part of a version)"}</dd></div>
        </dl>
      </section>
      <Disclosure label="Technical details" icon={<Calculator aria-hidden className="size-4" />} buttonClassName="text-muted">
        <div className="mt-2 space-y-2 text-[13px]">
          <table className="w-full">
            <caption className="sr-only">Stored field names and raw values</caption>
            <thead className="text-[12.5px] text-subtle"><tr><th scope="col" className="py-1 pr-3 text-left font-medium">Field</th><th scope="col" className="py-1 text-left font-medium">Raw value</th></tr></thead>
            <tbody className="mono">
              {Object.entries(item.computed).map(([k, v]) => (
                <tr key={k} className="border-t border-border/70 align-top"><td className="py-1 pr-3 text-subtle">{k}</td><td className="break-all py-1">{JSON.stringify(v)}</td></tr>
              ))}
            </tbody>
          </table>
          <dl className="mono space-y-0.5 text-[12.5px] text-muted">
            <div>evidence_id: {item.evidence_id}</div>
            <div>type: {item.type}</div>
            <div>stored title: {item.title}</div>
            <div>snapshot_id: {item.snapshot_id ?? "null"}</div>
            {Object.entries(item.provenance).map(([k, v]) => <div key={k}>provenance.{k}: {JSON.stringify(v)}</div>)}
            {item.entities.length > 0 && <div>entities: {item.entities.join(", ")}</div>}
          </dl>
        </div>
      </Disclosure>
      <SelectionNote count={sel.highlightTxnIds.size} />
    </div>
  );
}

function SourceButton({ txnId }: { txnId: string }) {
  const sel = useSelection();
  const ev = sel.evidenceIdForTxn(txnId);
  return (
    <button type="button"
      className="mono rounded border border-border-strong px-1.5 py-0.5 text-[12px] text-muted transition-colors hover:border-accent hover:text-accent"
      onClick={() => (ev ? sel.select(ev, { originId: sel.originId ?? undefined }) : sel.highlightTransactions([txnId]))}
      aria-label={ev ? `Open original record ${txnId}` : `Highlight ${txnId} in the timeline`}>
      {txnId}
    </button>
  );
}

function SelectionNote({ count }: { count: number }) {
  if (!count) return null;
  return <p className="text-[12.5px] text-accent" aria-live="polite">{count} record{count === 1 ? "" : "s"} highlighted in the timeline and graph.</p>;
}
