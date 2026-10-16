import * as Tabs from "@radix-ui/react-tabs";
import { ArrowLeft, GitCompareArrows, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router";
import { CompletenessBadge, PriorityBadge, ScoreBand, StatusBadge } from "../../components/ui/Badges";
import { ErrorState, LoadingBlock, Tip } from "../../components/ui/Primitives";
import { useCase, useEvidence, useReport } from "../../hooks/queries";
import { useMediaQuery } from "../../hooks/useMediaQuery";
import { channelLabel, localDate, utcToLocal } from "../../lib/format";
import type { CaseDetail, EvidenceItem } from "../../types/api";
import { EvidenceExplorer } from "../evidence/EvidenceExplorer";
import { HistoryTab } from "../evidence/HistoryTab";
import { RetailersTab } from "../evidence/RetailersTab";
import { TimelineTab } from "../evidence/TimelineTab";
import { TransactionsTab } from "../evidence/TransactionsTab";
import { FindingsPanel } from "../findings/KeyFindings";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { ExplorerProvider, useExplorer, type View } from "./explorer";
import { ReportPanel } from "./ReportPanel";
import { SelectionProvider } from "./selection";
import { SidePanel } from "./SidePanel";
import { CopilotDock } from "./CopilotDock";
import { SummaryView } from "../summary/SummaryView";
import { cx } from "../../lib/cx";
import { AIInvestigationView } from "../investigation/AIInvestigationView";

export function WorkspacePage() {
  const { caseId = "" } = useParams();
  const { data: c, error, isLoading, refetch } = useCase(caseId);
  const ev = useEvidence(caseId);
  if (error) return <ErrorState error={error} onRetry={() => refetch()} title={`Could not open ${caseId}`} />;
  if (isLoading || !c) return <LoadingBlock label={`Opening ${caseId}`} lines={10} />;
  return (
    <SelectionProvider items={ev.data}>
      <ExplorerProvider key={c.case_id}>
        <Workspace c={c} items={ev.data ?? []} evLoading={ev.isLoading} />
        <EvidenceDrawer caseId={c.case_id} />
      </ExplorerProvider>
    </SelectionProvider>
  );
}

const VIEWS: [View, string][] = [["summary", "Summary"], ["ai", "AI Investigation"], ["evidence", "Evidence"], ["history", "Historical Comparison"], ["review", "Review"]];

function Workspace({ c, items, evLoading }: { c: CaseDetail; items: EvidenceItem[]; evLoading: boolean }) {
  const ex = useExplorer();
  const [reportId, setReportId] = useState<string | null>(c.latest_report?.report_id ?? null);
  useEffect(() => {
    // follow the newest version when one is generated
    if (c.latest_report && (!reportId || !c.reports.some((r) => r.report_id === reportId))) setReportId(c.latest_report.report_id);
  }, [c.latest_report, c.reports, reportId]);
  const wide = useMediaQuery("(min-width: 1280px)");
  const refs = useMemo(() => Object.fromEntries(items.map((i) => [i.evidence_id, { type: i.type, title: i.title }])), [items]);
  const report = useReport(reportId).data;
  const allRefs = useMemo(() => ({ ...refs, ...(report?.evidence_refs ?? {}) }), [refs, report]);
  const findingClaims = useMemo(() => report?.sections.find((s) => s.key === "triggering_indicators")?.claims ?? [], [report]);

  // Evidence: the original two-column layout — flagged activities on the left, supporting evidence on the right
  const evidence = (
    <div className={cx("grid min-h-0 flex-1 gap-2.5", wide ? "grid-cols-[minmax(300px,360px)_minmax(0,1fr)]" : "grid-cols-[minmax(280px,320px)_minmax(0,1fr)]")}>
      <FindingsPanel caseId={c.case_id} claims={findingClaims} refs={allRefs} />
      {evLoading ? <div className="panel"><LoadingBlock label="Loading evidence" /></div> : (
        <EvidenceExplorer c={c} items={items} panels={{
          transactions: <TransactionsTab c={c} />,
          retailers: <RetailersTab c={c} items={items} />,
          timeline: <TimelineTab c={c} items={items} part="records" />,
        }} />
      )}
    </div>
  );
  const views: Record<View, ReactNode> = {
    summary: <div className="relative min-h-0 flex-1 overflow-y-auto pt-1"><SummaryView c={c} items={items} refs={allRefs} reportId={reportId} /></div>,
    ai: <AIInvestigationView c={c} refs={allRefs} />,
    evidence,
    history: (
      // Historical Comparison: the original comparison table plus the previous-vs-recent charts
      <div className="panel relative min-h-0 flex-1 overflow-y-auto">
        <section aria-labelledby="hist-table-h">
          <h2 id="hist-table-h" className="px-3 pt-3 text-[14.5px] font-semibold">Previous vs. recent activity</h2>
          <HistoryTab caseId={c.case_id} refs={refs} />
        </section>
        <section aria-labelledby="hist-charts-h" className="border-t border-border">
          <h2 id="hist-charts-h" className="px-3 pt-3 text-[14.5px] font-semibold">Comparison charts</h2>
          <TimelineTab c={c} items={items} part="comparison" />
        </section>
        <div aria-hidden className="h-20" />
      </div>
    ),
    review: (
      <div className={cx("grid min-h-0 flex-1 gap-2.5", wide ? "grid-cols-[minmax(0,1fr)_minmax(320px,370px)]" : "grid-cols-[minmax(0,1fr)]")}>
        <div className="panel relative min-h-0 overflow-y-auto">
          <ReportPanel c={c} reportId={reportId} onReportId={setReportId} refs={refs} items={items} />
        </div>
        {wide ? <SidePanel c={c} reportId={reportId} onReportId={setReportId} refs={refs} />
          : <div className="order-first"><SidePanel c={c} reportId={reportId} onReportId={setReportId} refs={refs} /></div>}
      </div>
    ),
  };

  return (
    <div className="flex h-[calc(100dvh-3.5rem)] flex-col">
      <CaseHeader c={c} />
      <Tabs.Root value={ex.view} onValueChange={(v) => ex.setView(v as View)} className="flex min-h-0 flex-1 flex-col px-3 pb-3">
        <Tabs.List aria-label="Case views" className="flex gap-1 overflow-x-auto border-b border-border">
          {VIEWS.map(([v, l]) => (
            <Tabs.Trigger key={v} value={v}
              className="relative shrink-0 whitespace-nowrap px-3.5 py-2.5 text-[14px] font-medium text-muted transition-colors duration-150 hover:text-text data-[state=active]:text-text data-[state=active]:after:absolute data-[state=active]:after:inset-x-2.5 data-[state=active]:after:-bottom-px data-[state=active]:after:h-[2px] data-[state=active]:after:rounded-full data-[state=active]:after:bg-accent">
              {v === "ai" && <Sparkles aria-hidden className="mr-1.5 inline size-3.5 align-[-2px] text-analysis" />}{l}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
        {VIEWS.map(([v]) => (
          <Tabs.Content key={v} value={v} className="flex min-h-0 flex-1 flex-col pt-2.5 outline-none">{views[v]}</Tabs.Content>
        ))}
      </Tabs.Root>
      <CopilotDock key={c.case_id} caseId={c.case_id} refs={allRefs} clearRight={ex.view === "review" && wide ? "370px" : undefined} />
    </div>
  );
}

function CaseHeader({ c }: { c: CaseDetail }) {
  return (
    <header className="border-b border-border bg-surface/60 px-3 py-2 sm:px-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <Link to="/" className="inline-flex items-center gap-1 text-[13px] text-muted no-underline hover:text-text hover:no-underline">
          <ArrowLeft aria-hidden className="size-4" /> Queue
        </Link>
        <h1 className="mono text-[18px] font-semibold">{c.case_id}</h1>
        <PriorityBadge priority={c.priority} short />
        <StatusBadge status={c.status} />
        <CompletenessBadge value={c.evidence_completeness} />
        <div className="ml-auto flex items-center gap-1.5">
          <Link to={`/compare?a=${c.case_id}`} className="inline-flex items-center gap-1.5 rounded-md border border-border-strong px-2 py-1 text-[12.5px] text-text no-underline hover:border-accent hover:no-underline">
            <GitCompareArrows aria-hidden className="size-3.5" /> Compare
          </Link>
        </div>
      </div>
      <dl className="mt-1 flex flex-wrap gap-x-5 gap-y-0.5 text-[12.5px]">
        <Fact label="Alert">{c.alert.alert_type}</Fact>
        <Fact label="Subject"><span className="mono">{c.subject_id}</span> · {channelLabel(c.channel)}</Fact>
        <Fact label="Score">
          <Tip content="Rule score (0–100): how unusual the activity is for this subject. Not a probability of fraud.">
            <span tabIndex={0}><ScoreBand band={c.score_band} score={c.alert_score} /></span>
          </Tip>
        </Fact>
        <Fact label="Recent period">{localDate(c.window_start_utc)} – {localDate(c.window_end_utc, true)}</Fact>
        <Fact label="Alert time">{utcToLocal(c.alert.triggered_at_utc)}</Fact>
        <Fact label="Priority">
          <Tip content={<ul className="list-disc space-y-1 pl-4">{c.priority_rationale.map((r, i) => <li key={i}>{r}</li>)}</ul>}>
            <button className="text-accent underline-offset-2 hover:underline">{c.priority_rationale.length} reasons</button>
          </Tip>
        </Fact>
        {c.scenario_title && <Fact label="Scenario"><span className="text-analysis">{c.scenario_title}</span></Fact>}
      </dl>
    </header>
  );
}

function Fact({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="flex items-baseline gap-1">
      <dt className="text-subtle">{label}:</dt>
      <dd className="text-text">{children}</dd>
    </div>
  );
}
