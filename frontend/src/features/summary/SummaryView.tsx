import { ArrowRight, FileSearch, Info } from "lucide-react";
import type { ReactNode } from "react";
import { PriorityBadge } from "../../components/ui/Badges";
import { ErrorState, LoadingBlock } from "../../components/ui/Primitives";
import { useCompleteness, useFindings, useHistory, useReport } from "../../hooks/queries";
import { money, num } from "../../lib/format";
import type { CaseDetail, EvidenceItem, Finding } from "../../types/api";
import { importanceOf, keyNumbers } from "../findings/FindingCard";
import { CitationChip } from "../workspace/CitationChip";
import { useExplorer } from "../workspace/explorer";

type Refs = Record<string, { type: string; title: string }>;
const ORDER = { high: 0, moderate: 1, low: 2 } as const;

/**
 * Plain-language case summary: what happened, why it was flagged, how it compares, what to check next.
 * Every value is read from existing verified API data (findings, history, stored evidence, completeness,
 * the report's cited statements). Nothing here is a conclusion about wrongdoing.
 */
export function SummaryView({ c, items, refs, reportId }: { c: CaseDetail; items: EvidenceItem[]; refs: Refs; reportId: string | null }) {
  const ex = useExplorer();
  const f = useFindings(c.case_id);
  const hist = useHistory(c.case_id).data;
  const cmpl = useCompleteness(c.case_id).data;
  const report = useReport(reportId).data;
  if (f.error) return <ErrorState error={f.error} onRetry={() => f.refetch()} title="Could not load the summary" />;
  if (f.isLoading || !f.data) return <LoadingBlock label="Preparing the summary" lines={6} />;

  const counted = f.data.findings.filter((x) => x.triggered)
    .sort((a, b) => ORDER[importanceOf(a)] - ORDER[importanceOf(b)] || b.points - a.points);
  const top = counted.slice(0, 3);
  const lead = top[0];

  // What happened: the stored "recent activity totals" evidence
  const metric = items.find((i) => i.type === "metric" && (i.provenance as { key?: string }).key === "metric:window");
  const m = metric?.computed as Record<string, number | string | null> | undefined;
  const scope = c.channel === "online_account" ? "deposits" : "linked purchases";

  // How it compares: up to three reliable history rows with the biggest relative change
  const rows = (hist?.available ? hist.rows : [])
    .filter((r) => r.reliability === "ok" || r.reliability === "caution")
    .filter((r) => r.previous !== null && r.current !== null)
    .sort((a, b) => Math.abs((b.change ?? 0)) - Math.abs((a.change ?? 0)))
    .slice(0, 3);

  // Caveat: the first gap in the evidence, plus the finding's own first limitation
  const gap = cmpl?.items.find((i) => i.state === "missing" || i.state === "partial" || i.state === "ambiguous");
  const limit = lead?.limitations[0];

  // Next: the report's verified suggested checks, otherwise the records behind each finding
  const checks = report?.sections.find((s) => s.key === "recommended_checks")?.claims
    .filter((cl) => cl.verification_status === "verified").slice(0, 3) ?? [];

  return (
    <div className="mx-auto max-w-[920px] space-y-5 px-1 pb-24">
      <header className="space-y-1.5">
        <p className="flex flex-wrap items-center gap-2 text-[13px] text-muted">
          <span className="mono text-text">{c.case_id}</span>
          <PriorityBadge priority={c.priority} short />
          <span>· {c.alert.alert_type}</span>
        </p>
        <h2 className="text-[21px] font-semibold leading-snug text-text">
          {lead ? lead.headline : "No single indicator stood out"}
        </h2>
        <p className="text-[14px] text-muted">
          {counted.length
            ? `${counted.length} of ${f.data.findings.length} indicators stood out. These are reasons to review, not proof of wrongdoing.`
            : "The alert was raised by a simple volume rule; activity is close to this subject's own history."}
        </p>
        {lead && (
          <button type="button" onClick={() => ex.showFinding(lead)}
            className="mt-1 inline-flex items-center gap-1.5 rounded-md border border-accent/60 bg-accent/10 px-3 py-1.5 text-[14px] font-medium text-accent transition-colors duration-150 hover:bg-accent/20">
            <FileSearch aria-hidden className="size-4" /> View evidence
          </button>
        )}
      </header>

      <Q n={1} title="What happened?">
        {m ? (
          <p className="text-[14.5px] text-text">
            {num(Number(m.transaction_count))} {scope} totalling {money(Number(m.total_amount))} on {num(Number(m.days_active))} of
            the last {num(Number(m.window_days))} days{m.first_local && m.last_local ? ` (${m.first_local} to ${m.last_local})` : ""}.
            {metric && <> <CitationChip evidenceId={metric.evidence_id} originId="sum-what" refInfo={refs[metric.evidence_id]} /></>}
          </p>
        ) : <p className="text-[14px] text-muted">Recent totals are not available for this case.</p>}
      </Q>

      <Q n={2} title="Why was the case flagged?">
        <ul className="space-y-1 text-[14px]">
          {c.alert.rules_fired.map((r) => (
            <li key={r} className="flex items-start gap-2"><ArrowRight aria-hidden className="mt-1 size-3.5 shrink-0 text-subtle" /><span className="text-text">{r}</span></li>
          ))}
          {c.priority_rationale.slice(0, 2).map((r) => (
            <li key={r} className="flex items-start gap-2"><ArrowRight aria-hidden className="mt-1 size-3.5 shrink-0 text-subtle" /><span className="text-muted">{r}</span></li>
          ))}
        </ul>
      </Q>

      <Q n={3} title="What are the main unusual activities?">
        {top.length ? (
          <ul className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(min(100%,15rem),1fr))]">
            {top.map((x) => <FindingTile key={x.key} f={x} onView={() => ex.showFinding(x)} />)}
          </ul>
        ) : <p className="text-[14px] text-muted">No indicator reached the level that counts toward an alert.</p>}
        <p className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[13px]">
          <button type="button" onClick={() => ex.setView("evidence")} className="text-accent hover:text-text">
            All {f.data.findings.length} findings and their evidence
          </button>
          {rows.length > 0 && (
            <button type="button" onClick={() => ex.setView("history")} className="text-accent hover:text-text">
              Historical comparison
            </button>
          )}
        </p>
      </Q>

      <Q n={4} title="What should be checked next?">
        <ul className="space-y-1.5 text-[14px]">
          {checks.length ? checks.map((cl, i) => (
            <li key={cl.claim_id ?? i} className="flex items-start gap-2">
              <ArrowRight aria-hidden className="mt-1 size-3.5 shrink-0 text-subtle" />
              <span className="text-text">{cl.text}</span>
            </li>
          )) : top.filter((x) => x.supporting_transaction_ids.length).map((x) => (
            <li key={x.key} className="flex items-start gap-2">
              <ArrowRight aria-hidden className="mt-1 size-3.5 shrink-0 text-subtle" />
              <span className="text-text">Check the {x.supporting_transaction_ids.length} records behind “{x.label.toLowerCase()}”.{" "}
                <button type="button" onClick={() => ex.showFinding(x)} className="text-accent hover:text-text">Open records</button></span>
            </li>
          ))}
          {!checks.length && (
            <li className="flex items-start gap-2 text-muted">
              <ArrowRight aria-hidden className="mt-1 size-3.5 shrink-0 text-subtle" />
              <span>Generate the report in <button type="button" onClick={() => ex.setView("review")} className="text-accent hover:text-text">Review</button> for cited suggested checks.</span>
            </li>
          )}
        </ul>
      </Q>

      {(gap || limit) && (
        <p role="note" className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/5 px-3 py-2 text-[13.5px]">
          <Info aria-hidden className="mt-0.5 size-4 shrink-0 text-warning" />
          <span>
            <span className="font-medium text-text">Keep in mind: </span>
            <span className="text-muted">{gap ? `${gap.label} — ${gap.detail}` : limit!.text}</span>
          </span>
        </p>
      )}
    </div>
  );
}

function Q({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={`sum-q${n}`} className="space-y-2">
      <h3 id={`sum-q${n}`} className="flex items-center gap-2 text-[15px] font-semibold text-text">
        <span aria-hidden className="mono flex size-5 items-center justify-center rounded-full border border-border-strong text-[11.5px] text-muted">{n}</span>
        {title}
      </h3>
      {children}
    </section>
  );
}

function FindingTile({ f, onView }: { f: Finding; onView: () => void }) {
  const k = keyNumbers(f);
  return (
    <li className="flex flex-col rounded-lg border border-border bg-elevated/35 px-3 py-2.5">
      <span className="text-[14.5px] font-semibold leading-snug text-text">{f.label}</span>
      {k.main && <span className="mono mt-1 text-[13.5px] text-text">{k.main}</span>}
      {k.delta && <span className="text-[13px] text-muted">{k.delta}</span>}
      <button type="button" onClick={onView} className="mt-auto self-start pt-2 text-[13px] font-medium text-accent hover:text-text">
        View evidence<span className="sr-only"> for {f.label}</span>
      </button>
    </li>
  );
}
