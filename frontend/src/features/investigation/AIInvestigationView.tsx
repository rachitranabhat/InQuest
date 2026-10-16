import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, BadgeCheck, Bot, ChevronDown, Compass, Play, Scale, SearchCheck, ShieldQuestion, Sparkles } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useApp } from "../../app/AppContext";
import { Button } from "../../components/ui/Button";
import { ErrorState, LoadingBlock } from "../../components/ui/Primitives";
import { api } from "../../lib/api";
import { cx } from "../../lib/cx";
import { utcToLocal } from "../../lib/format";
import type { AgentFinding, AgentRun, AssessmentKey, CaseDetail, Investigation, InvestigationSummary, StageStatus } from "../../types/api";
import { CitationList } from "../workspace/CitationChip";

type Refs = Record<string, { type: string; title: string }>;

const ASSESSMENT: Record<AssessmentKey, { label: string; tone: string; border: string }> = {
  suspicion_supported: { label: "Suspicion supported", tone: "border-critical/60 bg-critical/5 text-critical", border: "border-critical/60" },
  concern_reduced: { label: "Concern reduced", tone: "border-success/60 bg-success/5 text-success", border: "border-success/60" },
  inconclusive: { label: "Inconclusive", tone: "border-warning/60 bg-warning/5 text-warning", border: "border-warning/60" },
  insufficient_evidence: { label: "Insufficient evidence", tone: "border-border-strong bg-elevated/40 text-muted", border: "border-border-strong" },
};
const STAGE: Record<StageStatus, { label: string; tone: string }> = {
  live: { label: "Live AI", tone: "border-analysis/60 text-analysis" },
  live_repaired: { label: "Live AI · schema repaired once", tone: "border-analysis/60 text-analysis" },
  fallback: { label: "Fell back to simulated", tone: "border-warning/60 text-warning" },
  not_requested: { label: "Simulated", tone: "border-border-strong text-muted" },
};
const KIND: Record<AgentFinding["kind"], string> = {
  observation: "Observation", interpretation: "Interpretation", counterevidence: "Counterevidence", missing_information: "Missing information",
};

/** Run-level label. Never implies every stage used live AI when one fell back. */
function runLabel(r: { mode: Investigation["mode"] | null; requested_mode: string; status: string }): { label: string; tone: string } {
  if (r.status === "running") return { label: "Running", tone: "border-accent/60 text-accent" };
  if (r.status === "failed") return { label: "Failed investigation", tone: "border-critical/60 text-critical" };
  if (r.mode === "llm") return { label: "Live AI", tone: "border-analysis/60 bg-analysis/10 text-analysis" };
  if (r.mode === "llm_partial_fallback") return { label: "Partial fallback", tone: "border-warning/60 bg-warning/10 text-warning" };
  if (r.requested_mode === "llm") return { label: "Live AI unavailable — simulated analysis", tone: "border-warning/60 bg-warning/10 text-warning" };
  return { label: "Simulated analysis", tone: "border-border-strong bg-elevated text-muted" };
}
const firstSentence = (t: string) => (t.match(/^.*?[.!?](\s|$)/)?.[0] ?? t).trim();
const SEL = (caseId: string) => `prism.investigation.${caseId}`;

/**
 * AI Investigation tab. State lives on the server (runs are saved in the V2 database and keep running in the
 * background), so switching tabs or reloading never interrupts or restarts a run. Read-only for the case.
 */
export function AIInvestigationView({ c, refs }: { c: CaseDetail; refs: Refs }) {
  const { session, aiMode, config } = useApp();
  const qc = useQueryClient();
  const [selected, setSelectedState] = useState<string | null>(() => { try { return sessionStorage.getItem(SEL(c.case_id)); } catch { return null; } });
  const setSelected = (id: string) => { setSelectedState(id); try { sessionStorage.setItem(SEL(c.case_id), id); } catch { /* ignore */ } };

  const hist = useQuery({
    queryKey: ["investigations", c.case_id], queryFn: () => api.investigations(c.case_id), enabled: !!session,
    refetchInterval: (q) => ((q.state.data ?? []).some((r) => r.status === "running") ? 2000 : false),
  });
  const runs = hist.data ?? [];
  const current = runs.find((r) => r.investigation_id === selected) ?? runs[0];
  const detail = useQuery({
    queryKey: ["investigation", current?.investigation_id], queryFn: () => api.investigation(current!.investigation_id),
    enabled: !!session && !!current && current.status === "completed", staleTime: Infinity,
  });
  const running = runs.some((r) => r.status === "running");
  useEffect(() => {   // a run just finished: refresh evidence so citations to new query results resolve
    if (current?.status === "completed") qc.invalidateQueries({ queryKey: ["evidence", c.case_id] });
  }, [current?.status, current?.investigation_id, c.case_id, qc]);

  const start = useMutation({
    mutationFn: () => api.startInvestigation(c.case_id, aiMode),
    onSuccess: (r) => { setSelected(r.investigation_id); qc.invalidateQueries({ queryKey: ["investigations", c.case_id] }); },
  });

  return (
    <div className="relative min-h-0 flex-1 overflow-y-auto pb-24 pt-1">
      <div className="mx-auto max-w-[1100px] space-y-3">
        <section aria-labelledby="ai-inv-title" className="panel flex flex-wrap items-center gap-3 p-3">
          <div className="min-w-0 flex-1">
            <h2 id="ai-inv-title" className="flex items-center gap-2 text-[16px]"><Sparkles aria-hidden className="size-4 text-analysis" />AI Investigation</h2>
            <p className="text-[12.5px] text-muted">Two agents test opposite explanations; only verified findings reach the Lead. Provisional — you decide.</p>
          </div>
          {runs.length > 1 && (
            <label className="flex items-center gap-1.5 text-[12.5px] text-muted">
              <span>Run</span>
              <select className="field h-8 w-auto py-0 text-[12.5px]" value={current?.investigation_id} onChange={(e) => setSelected(e.target.value)}
                aria-label="Investigation run">
                {runs.map((r, i) => (
                  <option key={r.investigation_id} value={r.investigation_id}>
                    {i === 0 ? "Latest · " : ""}{utcToLocal(r.started_at_utc)} · {runLabel(r).label}{r.assessment ? ` · ${ASSESSMENT[r.assessment].label}` : ""}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="flex flex-col items-end gap-0.5">
            <Button variant="primary" onClick={() => start.mutate()} loading={start.isPending} disabled={!session || running || start.isPending}
              icon={<Play aria-hidden className="size-4" />}>{runs.length ? "Run again" : "Run AI Investigation"}</Button>
            <span className="text-[11.5px] text-subtle">
              {!session ? "Choose a reviewer first" : running ? "A run is in progress"
                : aiMode === "llm" ? (config?.llm_available ? "Live AI" : "Live AI requested · no key, will fall back") : "Simulated (Demo mode)"}
            </span>
          </div>
        </section>

        {start.error && <ErrorState error={start.error} onRetry={() => start.mutate()} title="Could not start the investigation" />}
        {hist.error ? <ErrorState error={hist.error} onRetry={() => hist.refetch()} title="Could not load investigations" />
          : session && hist.isLoading ? <LoadingBlock lines={3} label="Loading investigations" />
          : !current ? (
            <p className="rounded-lg border border-dashed border-border-strong p-6 text-center text-[13.5px] text-muted">
              {session ? `No investigation yet for ${c.case_id}.` : "Choose a reviewer to run or view investigations."}
            </p>
          ) : current.status === "running" ? (
            <div role="status" className="panel flex items-center gap-2.5 p-4 text-[13.5px] text-muted">
              <Bot aria-hidden className="size-4 animate-pulse text-analysis" />
              <span>Investigation running ({current.requested_mode === "llm" ? "live AI, may take a minute" : "simulated"}). You can switch tabs; it keeps going.</span>
            </div>
          ) : current.status === "failed" ? (
            <div role="alert" className="panel border-critical/50 p-4 text-[13.5px]">
              <p className="font-medium text-critical">Failed investigation</p>
              <p className="mt-0.5 text-muted">{current.error}</p>
            </div>
          ) : detail.error ? <ErrorState error={detail.error} onRetry={() => detail.refetch()} title="Could not load this run" />
          : !detail.data || !("lead" in detail.data) ? <LoadingBlock lines={4} label="Loading result" />
          : <Result inv={detail.data} refs={refs} />}
      </div>
    </div>
  );
}

function Result({ inv, refs }: { inv: Investigation; refs: Refs }) {
  const o = runLabel(inv);
  const a = ASSESSMENT[inv.lead.assessment];
  const lead = inv.lead;
  const missing = lead.missing_information.length ? lead.missing_information : inv.verified_findings.filter((f) => f.kind === "missing_information");
  const warnings = [...lead.warnings, ...inv.agents.suspicion.warnings, ...inv.agents.alternative.warnings, ...inv.notes];
  return (
    <div className="space-y-3">
      <p className="flex flex-wrap items-center gap-2 text-[12px] text-subtle">
        <span className={cx("rounded border px-2 py-0.5 font-semibold", o.tone)} data-testid="run-label">{o.label}</span>
        {inv.model && <span>{inv.model}</span>}
        <span>{utcToLocal(inv.finished_at_utc)} · {inv.investigation_id}</span>
      </p>

      {/* Lead: the most prominent element */}
      <section aria-labelledby="lead-h" className={cx("rounded-xl border-2 bg-surface p-4", a.border)}>
        <h3 id="lead-h" className="flex flex-wrap items-center gap-2 text-[12.5px] font-semibold text-muted">
          <BadgeCheck aria-hidden className="size-4" />Lead investigator · provisional<StageBadge s={lead.stage_status} />
        </h3>
        <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <p className={cx("rounded-md border px-3 py-0.5 text-[19px] font-semibold", a.tone)} data-testid="lead-assessment">{a.label}</p>
          <p className="min-w-0 flex-1 text-[14.5px] text-text" data-testid="lead-summary">{firstSentence(lead.rationale)}</p>
        </div>
        <p className="mt-2.5 flex items-start gap-1.5 text-[14px]"><Compass aria-hidden className="mt-0.5 size-4 shrink-0 text-accent" />
          <span><span className="font-medium">Next step: </span>{lead.recommended_next_step}</span></p>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <Points title="Points toward suspicion" icon={<SearchCheck aria-hidden className="size-3.5 text-critical" />} items={lead.strongest_supporting} refs={refs} idBase="sup" />
          <Points title="Possible ordinary explanations" icon={<ShieldQuestion aria-hidden className="size-3.5 text-success" />} items={lead.strongest_counterevidence} refs={refs} idBase="ctr" />
        </div>
        <div className="mt-3">
          <Points title="Missing information" icon={<AlertTriangle aria-hidden className="size-3.5 text-warning" />} items={missing} refs={refs} idBase="miss" />
        </div>
      </section>

      <Expand title="Agent details" hint={`${inv.agents.suspicion.conclusion} · ${inv.agents.alternative.conclusion}`}>
        <div className="grid gap-3 lg:grid-cols-2">
          <AgentCard a={inv.agents.suspicion} findings={inv.verified_findings.filter((f) => f.agent === "suspicion")} refs={refs} id="sus" />
          <AgentCard a={inv.agents.alternative} findings={inv.verified_findings.filter((f) => f.agent === "alternative")} refs={refs} id="alt" />
        </div>
      </Expand>
      <Expand title="Validation & warnings" hint={`${inv.verified_findings.length} verified · ${inv.rejected_findings.length} rejected${warnings.length ? ` · ${warnings.length} warning${warnings.length > 1 ? "s" : ""}` : ""}`}>
        <Validation inv={inv} warnings={warnings} refs={refs} />
      </Expand>
      <Expand title="Full Lead rationale" hint="">
        <p className="text-[13.5px] text-text">{lead.rationale}</p>
        <p className="mt-2 text-[11.5px] text-subtle">{inv.notice}</p>
      </Expand>
    </div>
  );
}

function Expand({ title, hint, children }: { title: string; hint: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="panel" aria-label={title}>
      <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3.5 py-2.5 text-left">
        <ChevronDown aria-hidden className={cx("size-4 shrink-0 text-subtle transition-transform motion-reduce:transition-none", open && "rotate-180")} />
        <span className="text-[14px] font-semibold">{title}</span>
        {hint && <span className="min-w-0 truncate text-[12.5px] text-subtle">{hint}</span>}
      </button>
      {open && <div className="border-t border-border p-3.5">{children}</div>}
    </section>
  );
}

function Points({ title, icon, items, refs, idBase }: { title: string; icon: ReactNode; items: AgentFinding[]; refs: Refs; idBase: string }) {
  const shown = items.slice(0, 3);
  return (
    <div>
      <h4 className="flex items-center gap-1.5 text-[12.5px] font-semibold text-muted">{icon}{title}</h4>
      {shown.length ? (
        <ul className="mt-1 space-y-1">
          {shown.map((f) => (
            <li key={f.finding_id} className="text-[13.5px]" data-finding={f.finding_id}>
              <span className="line-clamp-2 text-text" title={f.text}>{f.text}</span>
              <CitationList ids={f.evidence_ids} idBase={`${idBase}-${f.finding_id}`} refs={refs} inline={2} />
              <Checks f={f} />
            </li>
          ))}
        </ul>
      ) : <p className="mt-1 text-[13px] text-subtle">None verified.</p>}
    </div>
  );
}

function Checks({ f }: { f: AgentFinding }) {
  if (!f.cross_checks?.length) return null;
  return <ul className="mt-0.5 space-y-0.5" data-testid="cross-checks">{f.cross_checks.map((n) => (
    <li key={n} className="flex gap-1.5 text-[12px] text-warning"><AlertTriangle aria-hidden className="mt-0.5 size-3 shrink-0" />{n}</li>))}</ul>;
}

function StageBadge({ s }: { s: StageStatus }) {
  return <span className={cx("rounded border px-1.5 py-0.5 text-[11px] font-medium", STAGE[s].tone)} data-testid="stage-badge">{STAGE[s].label}</span>;
}

function AgentCard({ a, findings, refs, id }: { a: AgentRun; findings: AgentFinding[]; refs: Refs; id: string }) {
  return (
    <section aria-labelledby={`${id}-h`} className="rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h4 id={`${id}-h`} className="text-[14px] font-semibold">{a.name}</h4>
        <StageBadge s={a.stage_status} />
      </div>
      <p className="mt-1 text-[13.5px] font-medium">{a.conclusion}</p>
      <p className="text-[13px] text-muted">{a.summary}</p>
      {a.warnings.map((w) => <p key={w} className="mt-1 flex gap-1.5 text-[12.5px] text-warning"><AlertTriangle aria-hidden className="mt-0.5 size-3.5 shrink-0" />{w}</p>)}
      {a.fallback_reason && <p className="mt-1 text-[12px] text-warning">Live run failed: {a.fallback_reason}</p>}
      <ul className="mt-2 space-y-1.5">
        {findings.map((f) => (
          <li key={f.finding_id} className="border-l-2 border-border-strong pl-2 text-[13px]" data-finding={f.finding_id}>
            <p className="text-[11px] text-subtle"><span className="mono">{f.finding_id}</span> · {KIND[f.kind]}{f.weight === "strong" ? " · strong" : ""}
              {f.same_evidence_as?.length ? <> · same record as {f.same_evidence_as.join(", ")}</> : null}</p>
            <p>{f.text} <CitationList ids={f.evidence_ids} idBase={`${id}-${f.finding_id}`} refs={refs} inline={2} /></p>
            <Checks f={f} />
          </li>
        ))}
      </ul>
      <details className="mt-2 text-[12px]">
        <summary className="cursor-pointer text-muted">{a.tool_calls.length} tool calls · {a.verified} verified · {a.rejected} rejected</summary>
        <ol className="mt-1 list-decimal space-y-0.5 pl-5 text-subtle">
          {a.tool_calls.map((t, i) => (
            <li key={i}><span className="mono text-text">{t.tool}</span>{Object.keys(t.args).length ? <span className="mono"> {JSON.stringify(t.args)}</span> : null}
              {" "}→ {t.evidence_ids.length} items{t.error && <span className="text-warning"> · refused</span>}</li>
          ))}
        </ol>
      </details>
    </section>
  );
}

function Validation({ inv, warnings, refs }: { inv: Investigation; warnings: string[]; refs: Refs }) {
  return (
    <div className="space-y-2 text-[13px]">
      <p className="flex items-center gap-1.5 text-muted"><Scale aria-hidden className="size-4 text-accent" />
        Every finding is checked against the evidence it cites; rejected findings never reach the Lead.</p>
      {warnings.length > 0 && (
        <ul className="space-y-1">{warnings.map((w) => <li key={w} className="flex gap-1.5 text-[12.5px] text-warning"><AlertTriangle aria-hidden className="mt-0.5 size-3.5 shrink-0" />{w}</li>)}</ul>
      )}
      {inv.rejected_findings.length > 0 && (
        <ul className="space-y-1.5">
          {inv.rejected_findings.map((f) => (
            <li key={f.finding_id} className="border-l-2 border-warning/60 pl-2">
              <p className="text-muted line-through decoration-subtle/60">{f.text}</p>
              <p className="text-[12px] text-warning">{(f.failures ?? []).join(" ")}</p>
              {f.evidence_ids.some((e) => refs[e]) && <CitationList ids={f.evidence_ids.filter((e) => refs[e])} idBase={`rej-${f.finding_id}`} refs={refs} inline={2} />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export type { InvestigationSummary };
