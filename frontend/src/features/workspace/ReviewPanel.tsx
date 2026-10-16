import { AlertOctagon, CheckCircle2, FileCheck2, MessageSquarePlus, PlayCircle, RotateCcw, Send, ShieldCheck } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { useApp } from "../../app/AppContext";
import { StatusBadge } from "../../components/ui/Badges";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Primitives";
import { useToast } from "../../components/ui/Toast";
import { useCaseAction } from "../../hooks/queries";
import { newIdempotencyKey } from "../../lib/api";
import type { ActionKey, CaseDetail } from "../../types/api";
import { useReportActions } from "./ReportPanel";

const META: Record<ActionKey, { icon: ReactNode; variant: "primary" | "secondary" | "danger" | "warning"; confirm: string }> = {
  start_review: { icon: <PlayCircle aria-hidden className="size-4" />, variant: "primary", confirm: "You'll be recorded as the assigned reviewer." },
  add_note: { icon: <MessageSquarePlus aria-hidden className="size-4" />, variant: "secondary", confirm: "The note is added to the audit trail. Status does not change." },
  request_info: { icon: <Send aria-hidden className="size-4" />, variant: "warning", confirm: "The case moves to Information Requested until you resume the review." },
  close_no_action: { icon: <CheckCircle2 aria-hidden className="size-4" />, variant: "secondary", confirm: "The case is closed with no further action. It can be reopened." },
  escalate: { icon: <AlertOctagon aria-hidden className="size-4" />, variant: "danger", confirm: "The case is sent for specialist review. This records your judgement, not a finding of fraud." },
  reopen: { icon: <RotateCcw aria-hidden className="size-4" />, variant: "secondary", confirm: "The case returns to Under Review." },
};

/**
 * Workflow actions (start / reopen). Final outcomes are recorded in the Investigation decision section below,
 * which needs a justification and cited evidence. Reviewer notes have their own section.
 */
export function ReviewPanel({ c, reportId, onReportId }: { c: CaseDetail; reportId: string | null; onReportId: (id: string) => void }) {
  const { config, session } = useApp();
  const toast = useToast();
  const mut = useCaseAction(c.case_id);
  const rep = useReportActions(c, onReportId);
  const [action, setAction] = useState<ActionKey | null>(null);
  const [notes, setNotes] = useState("");
  const [touched, setTouched] = useState(false);
  const [key, setKey] = useState(newIdempotencyKey);

  const needsNotes = action ? (config?.notes_required ?? []).includes(action) : false;
  const min = config?.min_note_chars ?? 10;
  const noteError = needsNotes && notes.trim().length < min ? `Notes of at least ${min} characters are required.` : null;
  const labels = config?.action_labels ?? ({} as Record<ActionKey, string>);
  const decisionNeedsReport = (a: ActionKey) => ["request_info", "close_no_action", "escalate"].includes(a) && !c.latest_report;

  const actions = useMemo(() => {
    const order: ActionKey[] = ["start_review", "reopen"];
    return order.filter((a) => c.allowed_actions.includes(a));
  }, [c.allowed_actions]);

  const open = (a: ActionKey) => {
    setAction(a);
    setNotes("");
    setTouched(false);
    setKey(newIdempotencyKey());
  };

  const submit = async () => {
    if (!action) return;
    setTouched(true);
    if (noteError) return;
    try {
      const out = await mut.mutateAsync({ action, notes: notes.trim() || undefined, expected_status: c.status,
        report_id: reportId ?? undefined, idempotency_key: key });
      toast.push({ tone: "success", title: out.duplicate ? "Already recorded" : `${labels[action] ?? action} recorded`,
        body: `${out.from_status} → ${out.to_status}${out.report_version ? ` · report v${out.report_version}` : ""}` });
      setAction(null);
    } catch (e) {
      toast.push({ tone: "error", title: "Action not recorded", body: (e as Error).message });
    }
  };

  return (
    <section aria-labelledby="review-title" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="review-title" className="flex items-center gap-1.5 text-[14px]"><ShieldCheck aria-hidden className="size-4 text-accent" />Review workflow</h2>
        <StatusBadge status={c.status} />
        <span className="ml-auto text-[12px] text-subtle">{c.assigned_reviewer?.display_name ?? "Unassigned"}</span>
      </div>
      {!session && (
        <p className="rounded-md border border-warning/50 bg-warning/5 px-2.5 py-1.5 text-[12.5px]">Choose a simulated reviewer in the top bar to record actions.</p>
      )}
      {!c.latest_report && (
        <div className="flex items-center gap-2 rounded-md border border-border bg-bg/40 px-2.5 py-1.5 text-[12.5px] text-muted">
          <span className="flex-1">An investigation decision needs a generated report.</span>
          <Button size="sm" variant="secondary" loading={rep.generating} onClick={rep.generate} icon={<FileCheck2 aria-hidden className="size-4" />}>
            Generate report
          </Button>
        </div>
      )}
      <div className="flex flex-wrap gap-1.5">
        {actions.map((a) => (
          <Button key={a} size="sm" variant={META[a].variant} icon={META[a].icon} disabled={!session || decisionNeedsReport(a)}
            title={decisionNeedsReport(a) ? "Generate a report first" : undefined} onClick={() => open(a)}>
            {labels[a] ?? a}
          </Button>
        ))}
      </div>

      <Modal open={!!action} onOpenChange={(o) => !o && setAction(null)} title={action ? (labels[action] ?? action) : ""}
        description={action ? META[action].confirm : undefined}
        footer={
          <>
            <Button variant="ghost" onClick={() => setAction(null)}>Cancel</Button>
            <Button variant={action ? META[action].variant : "primary"} loading={mut.isPending} onClick={submit} disabled={!!noteError && touched}>
              Confirm {action ? (labels[action] ?? "").toLowerCase() : ""}
            </Button>
          </>
        }>
        <form onSubmit={(e) => { e.preventDefault(); submit(); }} noValidate>
          <label htmlFor="review-notes" className="label">
            Reviewer notes {needsNotes ? <span className="text-warning">(required)</span> : <span className="text-subtle">(optional)</span>}
          </label>
          <textarea id="review-notes" rows={5} maxLength={4000} className="field mt-1" aria-invalid={!!(noteError && touched)}
            aria-describedby="review-notes-help" value={notes} onChange={(e) => setNotes(e.target.value)} onBlur={() => setTouched(true)}
            placeholder="What did you check, and what led to this decision?" />
          <p id="review-notes-help" className={noteError && touched ? "mt-1 text-[13px] text-critical" : "mt-1 text-[13px] text-subtle"}>
            {noteError && touched ? noteError : `Recorded with case ${c.case_id}, status "${c.status}", ${reportId ? "the report version on screen" : "no report"}, and the evidence hash.`}
          </p>
        </form>
      </Modal>
    </section>
  );
}
