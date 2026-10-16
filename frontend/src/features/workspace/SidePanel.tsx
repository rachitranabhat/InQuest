import { CheckCircle2, ChevronDown, CircleDot, HelpCircle, History, ListChecks, MessageSquarePlus, MinusCircle, ShieldCheck, Database } from "lucide-react";
import { useEffect, useId, useState, type ReactNode } from "react";
import { useApp } from "../../app/AppContext";
import { CompletenessBadge } from "../../components/ui/Badges";
import { Button } from "../../components/ui/Button";
import { ErrorState, LoadingBlock } from "../../components/ui/Primitives";
import { useToast } from "../../components/ui/Toast";
import { useAudit, useBookmarks, useCaseAction, useChat, useCompleteness } from "../../hooks/queries";
import { newIdempotencyKey } from "../../lib/api";
import { cx } from "../../lib/cx";
import { utcToLocal } from "../../lib/format";
import type { CaseDetail, CompletenessState } from "../../types/api";
import { CitationList } from "./CitationChip";
import { useExplorer, type ExplorerTab } from "./explorer";
import { InvestigationDecision } from "./InvestigationDecision";
import { ReviewPanel } from "./ReviewPanel";

type Refs = Record<string, { type: string; title: string }>;

/** Review side panel: decision first, then supporting tools that stay compact until opened. The copilot floats separately. */
export function SidePanel({ c, reportId, onReportId, refs }: { c: CaseDetail; reportId: string | null; onReportId: (id: string) => void; refs: Refs }) {
  return (
    <div className="panel relative flex min-h-0 flex-col divide-y divide-border overflow-y-auto">
      <div className="p-3"><ReviewPanel c={c} reportId={reportId} onReportId={onReportId} /></div>
      <InvestigationDecision c={c} reportId={reportId} refs={refs} />
      <CompletenessSection caseId={c.case_id} refs={refs} />
      <ChecklistSection c={c} />
      <NotesSection c={c} />
      <AuditSection caseId={c.case_id} />
    </div>
  );
}

function Section({ title, icon, summary, defaultOpen = false, children }: {
  title: string; icon: ReactNode; summary?: ReactNode; defaultOpen?: boolean; children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <section aria-labelledby={`${id}-h`} className="px-3 py-2">
      <h2 id={`${id}-h`}>
        <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}
          className="group flex w-full items-center gap-1.5 py-1 text-left text-[14px] font-semibold">
          <span className="text-subtle group-hover:text-text">{icon}</span>
          <span className="group-hover:text-accent">{title}</span>
          <span className="ml-auto flex items-center gap-1.5 text-[12px] font-normal">{summary}</span>
          <ChevronDown aria-hidden className={cx("size-4 shrink-0 text-subtle transition-transform duration-150 motion-reduce:transition-none", open && "rotate-180")} />
        </button>
      </h2>
      <div id={id} hidden={!open} className="pb-1.5 pt-1">{open && children}</div>
    </section>
  );
}

// ------------------------------------------------------------------ completeness
const STATE: Record<CompletenessState, { label: string; icon: ReactNode; tone: string }> = {
  verified: { label: "Verified", icon: <ShieldCheck aria-hidden className="size-3.5" />, tone: "text-success" },
  available: { label: "Available", icon: <CheckCircle2 aria-hidden className="size-3.5" />, tone: "text-success" },
  partial: { label: "Partial", icon: <CircleDot aria-hidden className="size-3.5" />, tone: "text-warning" },
  ambiguous: { label: "Ambiguous", icon: <HelpCircle aria-hidden className="size-3.5" />, tone: "text-warning" },
  missing: { label: "Missing", icon: <MinusCircle aria-hidden className="size-3.5" />, tone: "text-subtle" },
};

function CompletenessSection({ caseId, refs }: { caseId: string; refs: Refs }) {
  const { data, error, isLoading, refetch } = useCompleteness(caseId);
  const [details, setDetails] = useState(false);
  return (
    <Section title="Evidence completeness" icon={<Database aria-hidden className="size-4" />} defaultOpen
      summary={data && <CompletenessBadge value={data.overall} short />}>
      {error ? <ErrorState error={error} onRetry={() => refetch()} title="Could not load completeness" />
        : isLoading || !data ? <LoadingBlock lines={3} label="Loading completeness" />
        : (
          <>
            <ul className="space-y-1" aria-label="Data coverage">
              {data.items.map((i) => {
                const s = STATE[i.state];
                return (
                  <li key={i.key} className="text-[13px]">
                    <div className="flex items-center gap-2">
                      <span className="min-w-0 flex-1 truncate text-text">{i.label}</span>
                      <span className={cx("inline-flex shrink-0 items-center gap-1 text-[12px] font-medium", s.tone)}>{s.icon}{s.label}</span>
                    </div>
                    {details && (
                      <p className="mb-1 text-[12px] text-muted">{i.detail}{" "}
                        {i.evidence_ids.length > 0 && <CitationList ids={i.evidence_ids} idBase={`cmpl-${i.key}`} refs={refs} />}
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
            <button type="button" aria-expanded={details} onClick={() => setDetails((d) => !d)}
              className="mt-1.5 text-[12px] text-accent hover:text-text">{details ? "Hide details" : "Show details & sources"}</button>
          </>
        )}
    </Section>
  );
}

// --------------------------------------------------------------------- checklist
const DECISIONS = new Set(["request_info", "close_no_action", "escalate", "record_disposition"]);
const STEPS: { key: string; label: string; go?: ExplorerTab; hint: string }[] = [
  { key: "anomaly", label: "Review the anomaly", hint: "Open a finding's evidence" },
  { key: "evidence", label: "Verify evidence", go: "transactions", hint: "Open at least one record or citation" },
  { key: "history", label: "Compare historical context", go: "history", hint: "Open the historical comparison" },
  { key: "uncertainty", label: "Note uncertainties", hint: "Add a reviewer note" },
  { key: "questions", label: "Ask follow-up questions", hint: "Ask the copilot something" },
  { key: "decision", label: "Record decision", hint: "Record an investigation decision" },
];

function loadChecks(caseId: string): Record<string, boolean> {
  try { return JSON.parse(localStorage.getItem(`prism.checklist.${caseId}`) ?? "{}"); } catch { return {}; }
}

function ChecklistSection({ c }: { c: CaseDetail }) {
  const ex = useExplorer();
  const chat = useChat(c.case_id).data ?? [];
  const audit = useAudit(c.case_id).data ?? [];
  const marks = useBookmarks(c.case_id).data ?? [];
  const [manual, setManual] = useState<Record<string, boolean>>(() => loadChecks(c.case_id));
  useEffect(() => {
    try { localStorage.setItem(`prism.checklist.${c.case_id}`, JSON.stringify(manual)); } catch { /* per-visit only */ }
  }, [manual, c.case_id]);

  const auto: Record<string, boolean> = {
    anomaly: ex.activity.has("finding"),
    evidence: ex.activity.has("evidence"),
    history: ex.activity.has("history"),
    uncertainty: marks.some((b) => b.note) || audit.some((a) => a.action === "add_note"),
    questions: chat.some((m) => m.role === "user"),
    decision: audit.some((a) => DECISIONS.has(a.action)),
  };
  const done = (k: string) => manual[k] ?? auto[k];
  const count = STEPS.filter((s) => done(s.key)).length;

  return (
    <Section title="Investigation checklist" icon={<ListChecks aria-hidden className="size-4" />}
      summary={<span className={cx("mono", count === STEPS.length ? "text-success" : "text-subtle")}>{count}/{STEPS.length}</span>}>
      <p className="mb-1.5 text-[11.5px] text-subtle">Optional. Steps tick themselves as you work; you can also tick them.</p>
      <ul className="space-y-1">
        {STEPS.map((s) => {
          const id = `chk-${s.key}`;
          return (
            <li key={s.key} className="flex items-center gap-2 text-[13px]">
              <input id={id} type="checkbox" className="size-4 accent-success" checked={!!done(s.key)}
                onChange={(e) => setManual((m) => ({ ...m, [s.key]: e.target.checked }))} aria-describedby={`${id}-hint`} />
              <label htmlFor={id} className={cx("min-w-0 flex-1", done(s.key) ? "text-muted line-through decoration-subtle/60" : "text-text")}>{s.label}</label>
              <span id={`${id}-hint`} className="sr-only">{s.hint}</span>
              {s.go && !done(s.key) && (
                <button type="button" onClick={() => ex.setTab(s.go!)} className="text-[12px] text-accent hover:text-text">Go</button>
              )}
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

// ------------------------------------------------------------------------ notes
function NotesSection({ c }: { c: CaseDetail }) {
  const { session, config } = useApp();
  const toast = useToast();
  const ex = useExplorer();
  const audit = useAudit(c.case_id).data ?? [];
  const mut = useCaseAction(c.case_id);
  const [text, setText] = useState("");
  const [touched, setTouched] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const notes = audit.filter((a) => a.notes).reverse().slice(0, showAll ? undefined : 3);
  const min = config?.min_note_chars ?? 10;
  const err = text.trim().length < min ? `At least ${min} characters.` : null;
  const total = audit.filter((a) => a.notes).length;

  const add = async () => {
    setTouched(true);
    if (err) return;
    try {
      await mut.mutateAsync({ action: "add_note", notes: text.trim(), expected_status: c.status, idempotency_key: newIdempotencyKey() });
      setText("");
      setTouched(false);
      ex.mark("saved");
      toast.push({ tone: "success", title: "Note added to the audit trail" });
    } catch (e) {
      toast.push({ tone: "error", title: "Note not saved", body: (e as Error).message });
    }
  };

  return (
    <Section title="Reviewer notes" icon={<MessageSquarePlus aria-hidden className="size-4" />}
      summary={<span className="mono text-subtle">{total}</span>}>
      <form onSubmit={(e) => { e.preventDefault(); add(); }} noValidate className="space-y-1.5">
        <label htmlFor="case-note" className="sr-only">Add a case note</label>
        <textarea id="case-note" rows={2} maxLength={4000} className="field py-1.5 text-[13px]" disabled={!session}
          placeholder={session ? "Uncertainties, follow-ups, what you checked…" : "Choose a reviewer to add notes"}
          value={text} onChange={(e) => setText(e.target.value)} aria-invalid={!!(err && touched)} aria-describedby="case-note-help" />
        <div className="flex items-center gap-2">
          <p id="case-note-help" className={cx("flex-1 text-[11.5px]", err && touched ? "text-critical" : "text-subtle")}>
            {err && touched ? err : "Saved to the audit trail; status does not change."}
          </p>
          <Button size="sm" type="submit" loading={mut.isPending} disabled={!session}>Add note</Button>
        </div>
      </form>
      {notes.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {notes.map((n) => (
            <li key={n.action_id} className="border-l-2 border-border-strong pl-2 text-[12.5px]">
              <p className="line-clamp-3 whitespace-pre-wrap text-text">{n.notes}</p>
              <p className="text-[11.5px] text-subtle">{n.reviewer_name ?? n.reviewer_id} · {utcToLocal(n.created_at_utc)}</p>
            </li>
          ))}
        </ul>
      )}
      {total > notes.length && (
        <button type="button" onClick={() => setShowAll(true)} className="mt-1.5 text-[12px] text-accent hover:text-text">All {total} notes</button>
      )}
    </Section>
  );
}

// ------------------------------------------------------------------- audit trail
const ACTION: Record<string, string> = {
  report_generated: "Report generated", start_review: "Review started", add_note: "Note added",
  request_info: "Information requested", close_no_action: "Closed — no further action", escalate: "Escalated", reopen: "Reopened",
  record_disposition: "Investigation decision", confirm_disposition: "Senior confirmation", return_disposition: "Returned by senior reviewer",
};

/** The case's append-only audit trail: who did what, when, on which report version. */
function AuditSection({ caseId }: { caseId: string }) {
  const { data, error, isLoading, refetch } = useAudit(caseId);
  const rows = [...(data ?? [])].reverse();
  return (
    <Section title="Audit trail" icon={<History aria-hidden className="size-4" />}
      summary={<span className="mono text-subtle">{data?.length ?? 0}</span>}>
      {error ? <ErrorState error={error} onRetry={() => refetch()} title="Could not load the audit trail" />
        : isLoading ? <LoadingBlock lines={3} label="Loading audit trail" />
        : !rows.length ? <p className="text-[12.5px] text-muted">No actions recorded yet.</p>
        : (
          <ol className="space-y-1.5" aria-label="Recorded actions, newest first">
            {rows.map((a) => (
              <li key={a.action_id} className="border-l-2 border-border-strong pl-2 text-[12.5px]">
                <p className="text-text">
                  <span className="font-medium">{ACTION[a.action] ?? a.action}</span>
                  {a.from_status !== a.to_status && <span className="text-muted"> · {a.from_status} → {a.to_status}</span>}
                </p>
                <p className="text-[11.5px] text-subtle">
                  {a.reviewer_name ?? a.reviewer_id} · {utcToLocal(a.created_at_utc)}
                  {a.report_version ? <> · report v{a.report_version}</> : null}
                  {a.evidence_hash ? <> · <span className="mono" title={a.evidence_hash}>{a.evidence_hash.slice(0, 10)}…</span></> : null}
                </p>
              </li>
            ))}
          </ol>
        )}
    </Section>
  );
}
