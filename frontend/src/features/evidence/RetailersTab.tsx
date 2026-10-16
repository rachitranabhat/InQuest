import { Link2, MapPin, Store, Users } from "lucide-react";
import { useMemo, type ReactNode } from "react";
import { EmptyState } from "../../components/ui/Primitives";
import { cx } from "../../lib/cx";
import { money } from "../../lib/format";
import { fieldLabel, plainTitle } from "../../lib/terms";
import type { CaseDetail, EvidenceItem } from "../../types/api";
import { BookmarkButton, BOOKMARKS_IN_CASE_UI } from "../workspace/BookmarkButton";
import { CitationChip } from "../workspace/CitationChip";
import { useExplorer } from "../workspace/explorer";
import { useSelection } from "../workspace/selection";

const n = (v: unknown) => (typeof v === "number" ? v : 0);

export function RetailersTab({ c, items }: { c: CaseDetail; items: EvidenceItem[] }) {
  const sel = useSelection();
  const ex = useExplorer();
  const focus = useMemo(() => new Set(ex.focus?.txnIds ?? []), [ex.focus]);
  const refs = useMemo(() => Object.fromEntries(items.map((i) => [i.evidence_id, { type: i.type, title: i.title }])), [items]);
  const retailers = items.filter((i) => i.type === "aggregate_retailer").sort((a, b) => n(b.computed.transaction_count) - n(a.computed.transaction_count));
  const cities = items.filter((i) => i.type === "location");
  const entities = items.filter((i) => i.type === "relationship" || i.type === "co_presence");
  const flow = items.find((i) => i.type === "metric" && i.provenance.key === "metric:fundflow");
  const maxShare = Math.max(...retailers.map((r) => n(r.computed.share_pct)), 1);
  const open = (id: string, origin: string) => { sel.select(id, { originId: origin }); ex.mark("evidence"); };

  return (
    <div className="space-y-5 p-3">
      {c.channel === "online_account" ? (
        <Section icon={<Store aria-hidden className="size-4" />} title="Account money in and out">
          {flow ? (
            <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {(["deposit", "wager", "payout", "withdrawal"] as const).map((k) => (
                <div key={k} className="rounded-md border border-border px-2.5 py-1.5">
                  <dt className="text-[12px] text-subtle">{fieldLabel(`${k}s`)}</dt>
                  <dd className="mono text-[14px]">{money(n(flow.computed[`${k}_total`]))} <span className="text-[12px] text-subtle">({String(flow.computed[`${k}_count`])})</span></dd>
                </div>
              ))}
            </dl>
          ) : <p className="text-[13px] text-muted">No account money-flow summary in this evidence version.</p>}
          {flow && <p className="mt-2"><CitationChip evidenceId={flow.evidence_id} originId={`flow-${flow.evidence_id}`} refInfo={refs[flow.evidence_id]} /></p>}
        </Section>
      ) : (
        <Section icon={<Store aria-hidden className="size-4" />} title={`Retailers (${retailers.length})`}
          aside={<span className="text-[12px] text-subtle">Recent period · share of transactions</span>}>
          {retailers.length === 0 ? <EmptyState title="No retailer records in this case" /> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-[13px]">
                <caption className="sr-only">Retailers used in the recent period with transaction counts, totals and share.</caption>
                <thead className="text-left text-[11.5px] uppercase tracking-wide text-subtle">
                  <tr>
                    {BOOKMARKS_IN_CASE_UI && <th scope="col" className="w-8 py-1.5"><span className="sr-only">Bookmark</span></th>}
                    <th scope="col" className="py-1.5 pr-2 font-semibold">Retailer</th>
                    <th scope="col" className="py-1.5 pr-2 text-right font-semibold">Txns</th>
                    <th scope="col" className="py-1.5 pr-2 text-right font-semibold">Total</th>
                    <th scope="col" className="w-[28%] py-1.5 pr-2 font-semibold">Share</th>
                    <th scope="col" className="py-1.5 font-semibold">Active</th>
                  </tr>
                </thead>
                <tbody>
                  {retailers.map((r) => {
                    const k = r.computed;
                    const hits = r.source_ids.filter((s) => focus.has(s)).length;
                    const hl = hits > 0 || sel.evidenceId === r.evidence_id;
                    return (
                      <tr key={r.evidence_id} className={cx("border-t border-border/60", hl && "bg-accent/10 mark-selected")}>
                        {BOOKMARKS_IN_CASE_UI && <td className="py-1.5"><BookmarkButton caseId={c.case_id} evidenceId={r.evidence_id} label={`retailer ${String(k.retailer_name)}`} /></td>}
                        <td className="py-1.5 pr-2">
                          <button id={`ret-${r.evidence_id}`} type="button" onClick={() => open(r.evidence_id, `ret-${r.evidence_id}`)}
                            className="text-left text-accent hover:underline">{String(k.retailer_name)}</button>
                          <div className="text-[12px] text-subtle">
                            {String(k.city)}{k.new_for_subject ? <span className="ml-1.5 rounded border border-warning/60 px-1 text-warning">New for subject</span> : null}
                            {hits > 0 && <span className="ml-1.5 text-accent">{hits} focus record{hits === 1 ? "" : "s"}</span>}
                          </div>
                        </td>
                        <td className="mono py-1.5 pr-2 text-right">{String(k.transaction_count)}</td>
                        <td className="mono py-1.5 pr-2 text-right">{money(n(k.total_amount))}</td>
                        <td className="py-1.5 pr-2">
                          <div className="flex items-center gap-2">
                            <div aria-hidden className="h-1.5 flex-1 overflow-hidden rounded-full bg-border/70">
                              <div className="h-full rounded-full bg-accent/80" style={{ width: `${(n(k.share_pct) / maxShare) * 100}%` }} />
                            </div>
                            <span className="mono w-12 text-right text-[12.5px]">{String(k.share_pct)}%</span>
                          </div>
                        </td>
                        <td className="mono whitespace-nowrap py-1.5 text-[12px] text-muted">{String(k.first_local).slice(5)} – {String(k.last_local).slice(5)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      )}

      {cities.length > 0 && (
        <Section icon={<MapPin aria-hidden className="size-4" />} title={`Cities (${cities.length})`}>
          <ul className="flex flex-wrap gap-1.5">
            {cities.map((l) => (
              <li key={l.evidence_id}>
                <button id={`loc-${l.evidence_id}`} type="button" onClick={() => open(l.evidence_id, `loc-${l.evidence_id}`)}
                  className={cx("rounded-md border px-2 py-1 text-[12.5px] hover:border-accent",
                    l.computed.in_baseline ? "border-border-strong text-muted" : "border-warning/60 text-text")}>
                  {String(l.computed.city)} · <span className="mono">{String(l.computed.transaction_count)}</span>
                  <span className={cx("ml-1.5", l.computed.in_baseline ? "text-subtle" : "text-warning")}>{l.computed.in_baseline ? "usual" : "new"}</span>
                </button>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {entities.length > 0 && (
        <Section icon={<Users aria-hidden className="size-4" />} title="Linked people & accounts">
          <ul className="space-y-1.5">
            {entities.map((e) => (
              <li key={e.evidence_id} className="flex items-start gap-2 rounded-md border border-border px-2.5 py-1.5 text-[13px]">
                <Link2 aria-hidden className="mt-0.5 size-3.5 shrink-0 text-subtle" />
                <div className="min-w-0 flex-1">
                  <p className="text-text">{plainTitle(e.type, e.title)}</p>
                  {e.type === "co_presence" && <p className="text-[12px] text-warning">Same place and time only; no verified relationship.</p>}
                </div>
                <BookmarkButton caseId={c.case_id} evidenceId={e.evidence_id} label={plainTitle(e.type, e.title)} />
                <CitationChip evidenceId={e.evidence_id} originId={`ent-${e.evidence_id}`} refInfo={refs[e.evidence_id]} />
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

function Section({ icon, title, aside, children }: { icon: ReactNode; title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 text-[13px] font-semibold text-muted">{icon}{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}
