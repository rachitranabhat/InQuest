import { ChevronDown, Download, FileCheck2, ListTree, Lock, RefreshCw, Search, ShieldAlert, Sparkles } from "lucide-react";
import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import { useApp } from "../../app/AppContext";
import { ModeBadge } from "../../components/ui/Badges";
import { Button } from "../../components/ui/Button";
import { Disclosure } from "../../components/ui/Disclosure";
import { EmptyState, ErrorState, LoadingBlock, Tip } from "../../components/ui/Primitives";
import { useToast } from "../../components/ui/Toast";
import { useGenerateReport, useReport } from "../../hooks/queries";
import { api } from "../../lib/api";
import { cx } from "../../lib/cx";
import { humanType, utcToLocal } from "../../lib/format";
import { plainTitle } from "../../lib/terms";
import type { CaseDetail, Claim, EvidenceItem, Report } from "../../types/api";
import { ClaimRow } from "./ClaimRow";
import { useExplorerOptional } from "./explorer";
import { useSelection } from "./selection";

type Refs = Record<string, { type: string; title: string }>;

/** Read first; everything else is reference material and starts collapsed. */
const OPEN_BY_DEFAULT = new Set(["case_overview", "initial_alert", "recommended_checks"]);

export function useReportActions(c: CaseDetail, onReportId: (id: string) => void) {
  const { aiMode } = useApp();
  const toast = useToast();
  const gen = useGenerateReport(c.case_id);
  const [exporting, setExporting] = useState(false);
  const generate = async () => {
    try {
      const r = await gen.mutateAsync(aiMode);
      onReportId(r.report_id);
      const msg = `${r.validation.verified} of ${r.validation.claims} statements verified against cited evidence.`;
      if (r.mode === "llm_fallback") toast.push({ tone: "error", title: `Version ${r.version}: LLM unavailable — deterministic report shown`, body: r.notes ?? msg });
      else toast.push({ tone: "success", title: `Report version ${r.version} generated`, body: msg });
    } catch (e) {
      toast.push({ tone: "error", title: "Report generation failed", body: (e as Error).message });
    }
  };
  const exportPdf = async (rid: string, version: number) => {
    setExporting(true);
    try {
      const { blob, fileName } = await api.downloadPdf(rid);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = fileName;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      toast.push({ tone: "success", title: "PDF downloaded", body: `${fileName} · report version ${version}` });
    } catch (e) {
      toast.push({ tone: "error", title: "Export failed", body: (e as Error).message });
    } finally {
      setExporting(false);
    }
  };
  return { generate, generating: gen.isPending, exportPdf, exporting, aiMode };
}

export function ReportPanel({ c, reportId, onReportId, refs = {}, items = [] }: {
  c: CaseDetail; reportId: string | null; onReportId: (id: string) => void; refs?: Refs; items?: EvidenceItem[];
}) {
  const { data: report, error, isLoading, refetch } = useReport(reportId);
  const act = useReportActions(c, onReportId);

  if (!reportId) {
    return (
      <div className="p-3">
        <EmptyState title="No report generated yet" icon={<FileCheck2 aria-hidden className="size-7" />}>
          <p>Each statement is tied to evidence IDs and checked against the records it cites.</p>
          <Button variant="primary" className="mt-3" loading={act.generating} onClick={act.generate}
            icon={act.aiMode === "llm" ? <Sparkles aria-hidden className="size-4" /> : <FileCheck2 aria-hidden className="size-4" />}>
            Generate report ({act.aiMode === "llm" ? "LLM" : "Demo"} mode)
          </Button>
        </EmptyState>
        <EvidenceIndex items={items} />
      </div>
    );
  }

  return (
    <div className="px-3 pb-4">
      <div className="sticky top-0 z-10 -mx-3 flex flex-wrap items-center gap-2 border-b border-border bg-surface px-3 py-2">
        <h3 id="report-title" className="text-[14px] font-semibold">Investigation report</h3>
        {report && (
          <span className="flex flex-wrap items-center gap-1.5 text-[12.5px] text-muted">
            v{report.version} <ModeBadge mode={report.mode} />
            {report.status === "locked" && <span className="inline-flex items-center gap-1 text-subtle"><Lock aria-hidden className="size-3.5" />Locked</span>}
            <span className="text-subtle">{utcToLocal(report.created_at_utc)}</span>
          </span>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          {c.reports.length > 1 && (
            <>
              <label htmlFor="report-version" className="sr-only">Report version</label>
              <select id="report-version" className="field h-8 w-auto py-0 text-[12.5px]" value={reportId} onChange={(e) => onReportId(e.target.value)}>
                {c.reports.map((r) => <option key={r.report_id} value={r.report_id}>v{r.version} · {r.mode_label}</option>)}
              </select>
            </>
          )}
          <Button size="sm" loading={act.generating} onClick={act.generate} icon={<RefreshCw aria-hidden className="size-4" />}>New version</Button>
          {report && (
            <Button size="sm" variant="primary" loading={act.exporting} onClick={() => act.exportPdf(report.report_id, report.version)}
              icon={<Download aria-hidden className="size-4" />}>Export PDF</Button>
          )}
        </div>
      </div>
      {error ? <ErrorState error={error} onRetry={() => refetch()} title="Could not load the report" />
        : isLoading || !report ? <LoadingBlock label="Loading report" lines={10} />
        : <ReportBody report={report} refs={{ ...refs, ...report.evidence_refs }} />}
      <EvidenceIndex items={items} />
    </div>
  );
}

function ReportBody({ report, refs }: { report: Report; refs: Refs }) {
  const v = report.validation;
  const [showUnverified, setShowUnverified] = useState(true);
  useEffect(() => setShowUnverified(true), [report.report_id]);
  const visible = (cl: Claim) => showUnverified || cl.verification_status === "verified";
  return (
    <div>
      <div role="status" className={cx("mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border px-2.5 py-1.5 text-[13px]",
        v.unverified ? "border-critical/50 bg-critical/5" : "border-success/40 bg-success/5")}>
        {v.unverified ? <ShieldAlert aria-hidden className="size-4 text-critical" /> : <FileCheck2 aria-hidden className="size-4 text-success" />}
        <span>
          <strong className="tabular-nums">{v.verified}</strong> of <strong className="tabular-nums">{v.claims}</strong> statements checked against the evidence they cite
          {v.unverified ? <> · <strong className="text-critical">{v.unverified} could not be verified</strong> (not findings)</> : null}
        </span>
        {v.unverified > 0 && (
          <button className="ml-auto text-[12.5px] text-accent underline-offset-2 hover:underline" onClick={() => setShowUnverified((s) => !s)}>
            {showUnverified ? "Hide" : "Show"} unverified
          </button>
        )}
      </div>
      {report.notes && <p className="mt-2 rounded-md border border-warning/50 bg-warning/5 px-2.5 py-1.5 text-[13px]">{report.notes}</p>}
      {report.sections.map((s) => {
        const claims = s.claims.filter(visible);
        const unverified = s.claims.filter((cl) => cl.verification_status === "unverified").length;
        return (
          <ReportSection key={s.key} sKey={s.key} label={s.label} technical={s.technical_label}
            defaultOpen={OPEN_BY_DEFAULT.has(s.key) || unverified > 0} count={s.claims.length} unverified={unverified}
            hint={s.key === "triggering_indicators" ? "Each indicator also appears as a card in Findings." : undefined}>
            <ul className="-mx-2.5 space-y-0.5">
              {claims.map((cl, j) => <ClaimRow key={cl.claim_id ?? `${s.key}-${j}`} claim={cl} refs={refs} idBase={cl.claim_id ?? `${s.key}-${j}`} />)}
            </ul>
          </ReportSection>
        );
      })}
      <p className="mt-5 border-t border-border pt-2.5 text-[12px] text-subtle">{report.disclaimer}</p>
    </div>
  );
}

function ReportSection({ sKey, label, technical, defaultOpen, count, unverified = 0, hint, children }: {
  sKey: string; label: string; technical?: string; defaultOpen: boolean; count: number; unverified?: number; hint?: string; children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const regionId = useId();
  const heading = (
    <button type="button" aria-expanded={open} aria-controls={regionId} onClick={() => setOpen((o) => !o)} className="group flex w-full items-center gap-2 py-1 text-left">
      <span className="text-[13.5px] font-semibold text-text group-hover:text-accent">{label}</span>
      <span className="text-[12px] font-normal text-subtle">{count}{unverified ? ` · ${unverified} unverified` : ""}</span>
      <ChevronDown aria-hidden className={cx("ml-auto size-4 text-subtle transition-transform duration-150 motion-reduce:transition-none", open && "rotate-180")} />
    </button>
  );
  return (
    <section aria-labelledby={`sec-${sKey}`} className="mt-2 border-t border-border/60 pt-1.5">
      <h4 id={`sec-${sKey}`}>{technical && technical !== label ? <Tip content={`Report section: ${technical}`}>{heading}</Tip> : heading}</h4>
      <div id={regionId} hidden={!open}>
        {open && <>{hint && <p className="mb-1 text-[12px] text-subtle">{hint}</p>}{children}</>}
      </div>
    </section>
  );
}

// ------------------------------------------------------------------------ evidence index
const TYPE_ORDER = ["alert", "risk_factor", "metric", "sequence", "comparison", "baseline", "aggregate_day", "aggregate_retailer",
  "retailer", "location", "relationship", "co_presence", "context_event", "limitation", "query_result", "transaction"];

/** Every evidence item in the case, searchable. Reference material, so it sits at the end of the report. */
function EvidenceIndex({ items }: { items: EvidenceItem[] }) {
  return (
    <Disclosure label="Evidence index" count={items.length} icon={<ListTree aria-hidden className="size-4" />}
      className="mt-4 border-t border-border pt-2" buttonClassName="text-[13px] text-muted">
      <EvidenceBrowser items={items} />
    </Disclosure>
  );
}

function EvidenceBrowser({ items }: { items: EvidenceItem[] }) {
  const sel = useSelection();
  const ex = useExplorerOptional();
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const shown = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return items
      .filter((i) => (!type || i.type === type) && (!ql || `${i.evidence_id} ${i.title} ${plainTitle(i.type, i.title)} ${i.summary} ${i.entities.join(" ")}`.toLowerCase().includes(ql)))
      .sort((a, b) => TYPE_ORDER.indexOf(a.type) - TYPE_ORDER.indexOf(b.type) || a.evidence_id.localeCompare(b.evidence_id));
  }, [items, q, type]);
  const types = TYPE_ORDER.filter((t) => items.some((i) => i.type === t));
  return (
    <div className="mt-2 space-y-2">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <label htmlFor="ev-search" className="sr-only">Search evidence</label>
          <Search aria-hidden className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-subtle" />
          <input id="ev-search" className="field h-8 py-0 pl-7 text-[13px]" placeholder="ID, retailer, city, amount…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <label htmlFor="ev-type" className="sr-only">Evidence type</label>
        <select id="ev-type" className="field h-8 w-auto py-0 text-[13px]" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">All types</option>
          {types.map((t) => <option key={t} value={t}>{humanType(t)}</option>)}
        </select>
      </div>
      <p className="text-[12px] text-subtle" aria-live="polite">{shown.length} item{shown.length === 1 ? "" : "s"}</p>
      <ul className="relative max-h-[420px] divide-y divide-border/60 overflow-y-auto rounded-md border border-border">
        {shown.map((i) => (
          <li key={i.evidence_id}>
            <button type="button" id={`idx-${i.evidence_id}`} onClick={() => { sel.select(i.evidence_id, { originId: `idx-${i.evidence_id}` }); ex?.mark("evidence"); }}
              className={cx("flex w-full items-baseline gap-2 px-2.5 py-1.5 text-left text-[13px] hover:bg-hover", sel.evidenceId === i.evidence_id && "bg-accent/10")}>
              <span className="mono w-[5.5rem] shrink-0 text-[12px] text-muted">{i.evidence_id}</span>
              <span className="min-w-0 flex-1 truncate text-text">{plainTitle(i.type, i.title)}</span>
              <span className={cx("shrink-0 text-[11.5px]", i.type === "limitation" ? "text-warning" : i.type === "query_result" ? "text-analysis" : "text-subtle")}>{humanType(i.type)}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
