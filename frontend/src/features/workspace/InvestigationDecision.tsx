import { ClipboardCheck, Scale, Search, ShieldAlert, UserCheck, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useApp } from "../../app/AppContext";
import { Button } from "../../components/ui/Button";
import { ErrorState, LoadingBlock, Modal } from "../../components/ui/Primitives";
import { useToast } from "../../components/ui/Toast";
import { useDispositionMutations, useDispositions, useEvidence } from "../../hooks/queries";
import { newIdempotencyKey } from "../../lib/api";
import { cx } from "../../lib/cx";
import { utcToLocal } from "../../lib/format";
import type { ApprovalState, CaseDetail, ConcernType, DispositionEntry, DispositionKey, DispositionOptions } from "../../types/api";
import { CitationList } from "./CitationChip";

// mirrors config.DISPOSITION_FROM on the server, which enforces it
const OPEN_FOR_DECISION = ["Under Review", "Information Requested"];

type Refs = Record<string, { type: string; title: string }>;

const APPROVAL: Record<ApprovalState, { text: string; tone: string }> = {
  not_required: { text: "Recorded", tone: "border-border-strong text-muted" },
  pending_senior: { text: "Awaiting senior confirmation", tone: "border-warning/60 text-warning" },
  confirmed: { text: "Confirmed by senior investigator", tone: "border-success/60 text-success" },
  returned: { text: "Returned by senior investigator", tone: "border-warning/60 text-warning" },
  superseded: { text: "Superseded", tone: "border-border text-subtle" },
};
const ENTRY: Record<DispositionEntry["entry_type"], string> = { decision: "Decision", confirmation: "Senior confirmation", return: "Returned" };

function labelFor(o: DispositionOptions | undefined, d: DispositionKey, concern: ConcernType) {
  return o?.labels[concern]?.[d] ?? o?.dispositions.find((x) => x.key === d)?.label ?? d;
}

/**
 * Final investigation decision: the reviewer's documented conclusion, with a justification and cited evidence.
 * Only a person can record it — the copilot can summarise evidence and suggest questions, nothing more.
 * Permissions are enforced by the API; this panel only explains them.
 */
export function InvestigationDecision({ c, reportId, refs }: { c: CaseDetail; reportId: string | null; refs: Refs }) {
  const { config, session, isSenior } = useApp();
  const opts = config?.dispositions;
  const { data, error, isLoading, refetch } = useDispositions(c.case_id);
  const cur = data?.current ?? null;

  return (
    <section aria-labelledby="decision-title" className="space-y-2.5 px-3 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="decision-title" className="flex items-center gap-1.5 text-[14px]"><Scale aria-hidden className="size-4 text-accent" />Investigation decision</h2>
      </div>
      {error ? <ErrorState error={error} onRetry={() => refetch()} title="Could not load decisions" />
        : isLoading || !data ? <LoadingBlock lines={2} label="Loading decisions" />
        : (
          <>
            <CurrentDecision cur={cur} caseId={c.case_id} status={c.status} canReview={isSenior && !!cur && cur.reviewer_id !== session?.reviewer.reviewer_id} refs={refs} />
            {(config?.dispositions ? OPEN_FOR_DECISION.includes(c.status) : data.can_record) && session ? (
              <DecisionForm c={c} reportId={reportId} refs={refs} opts={opts} senior={isSenior} />
            ) : (
              <p className="rounded-md border border-border bg-bg/40 px-2.5 py-1.5 text-[12.5px] text-muted">
                {!session ? "Choose a reviewer to record a decision."
                  : ["New", "Analysis Ready"].includes(c.status) ? "Start the review to record a decision."
                  : "The case is closed or escalated. Reopen it to record a new decision."}
              </p>
            )}
            <p className="flex gap-1.5 text-[11.5px] text-subtle">
              <ShieldAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
              <span>A substantiated finding is the investigator's assessment, not a legal determination of guilt; the AI never selects or submits a decision.</span>
            </p>
            <DecisionHistory entries={data.entries} refs={refs} />
          </>
        )}
    </section>
  );
}

function CurrentDecision({ cur, caseId, status, canReview, refs }: { cur: DispositionEntry | null; caseId: string; status: string; canReview: boolean; refs: Refs }) {
  const [mode, setMode] = useState<"confirm" | "return" | null>(null);
  if (!cur) return <p className="text-[12.5px] text-muted">No investigation decision recorded yet.</p>;
  const a = APPROVAL[cur.current_approval ?? cur.approval_status];
  const pending = cur.current_approval === "pending_senior";
  return (
    <div className="rounded-md border border-border bg-elevated/35 px-2.5 py-2" aria-label="Current decision">
      <p className="text-[13.5px] font-semibold text-text">{cur.label}</p>
      <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[11.5px]">
        <span className={cx("rounded border px-1.5 py-0.5 font-medium", a.tone)}>{a.text}</span>
        <span className="text-subtle">{cur.reviewer_name ?? cur.reviewer_id} · {utcToLocal(cur.created_at_utc)} · report v{cur.report_version}</span>
      </p>
      {pending && (
        canReview ? (
          <div className="mt-2 flex gap-1.5">
            <Button size="sm" variant="primary" icon={<UserCheck aria-hidden className="size-4" />} onClick={() => setMode("confirm")}>Confirm finding</Button>
            <Button size="sm" variant="secondary" onClick={() => setMode("return")}>Return to reviewer</Button>
          </div>
        ) : <p className="mt-1.5 text-[12px] text-muted">A senior investigator (other than the recommending reviewer) must confirm this before the case closes.</p>
      )}
      {mode && <ReviewDialog mode={mode} entry={cur} caseId={caseId} status={status} refs={refs} onClose={() => setMode(null)} />}
    </div>
  );
}

function ReviewDialog({ mode, entry, caseId, status, refs, onClose }: {
  mode: "confirm" | "return"; entry: DispositionEntry; caseId: string; status: string; refs: Refs; onClose: () => void;
}) {
  const { config } = useApp();
  const toast = useToast();
  const mut = useDispositionMutations(caseId).review;
  const [notes, setNotes] = useState("");
  const [key] = useState(newIdempotencyKey);
  const min = config?.min_note_chars ?? 10;
  const ok = notes.trim().length >= min;
  const submit = async () => {
    if (!ok) return;
    try {
      await mut.mutateAsync({ id: entry.disposition_id, decision: mode, notes: notes.trim(), idempotency_key: key, expected_status: status });
      toast.push({ tone: "success", title: mode === "confirm" ? "Finding confirmed" : "Returned to reviewer" });
      onClose();
    } catch (e) {
      toast.push({ tone: "error", title: "Not recorded", body: (e as Error).message });
    }
  };
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={mode === "confirm" ? "Confirm substantiated finding" : "Return recommendation"}
      description={mode === "confirm" ? "The case closes as substantiated. This is recorded with your name in the audit trail." : "The case stays under review."}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant={mode === "confirm" ? "primary" : "secondary"} loading={mut.isPending} disabled={!ok} onClick={submit}>
          {mode === "confirm" ? "Confirm finding" : "Return"}
        </Button></>}>
      <div className="space-y-2.5 text-[13.5px]">
        <p><span className="font-medium">{entry.label}</span> — {entry.reviewer_name ?? entry.reviewer_id}</p>
        <p className="line-clamp-4 whitespace-pre-wrap text-muted">{entry.justification}</p>
        <p className="text-[12.5px]">Cited: <CitationList ids={entry.evidence_ids} idBase={`rv-${entry.disposition_id}`} refs={refs} inline={4} /></p>
        <div>
          <label htmlFor="dsp-review-notes" className="label">Your notes (required)</label>
          <textarea id="dsp-review-notes" rows={3} maxLength={4000} className="field mt-1" value={notes} onChange={(e) => setNotes(e.target.value)}
            placeholder={mode === "confirm" ? "What you checked before confirming" : "What is missing or needs another look"} />
          <p className="mt-1 text-[12px] text-subtle">At least {min} characters.</p>
        </div>
      </div>
    </Modal>
  );
}

function DecisionForm({ c, reportId, refs, opts, senior }: { c: CaseDetail; reportId: string | null; refs: Refs; opts?: DispositionOptions; senior: boolean }) {
  const toast = useToast();
  const mut = useDispositionMutations(c.case_id).record;
  const ev = useEvidence(c.case_id).data ?? [];
  const [disposition, setDisposition] = useState<DispositionKey | null>(null);
  const [concern, setConcern] = useState<ConcernType>("fraud");
  const [why, setWhy] = useState("");
  const [cited, setCited] = useState<string[]>([]);
  const [find, setFind] = useState("");
  const [picking, setPicking] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [touched, setTouched] = useState(false);
  const [key, setKey] = useState(newIdempotencyKey);
  const min = opts?.min_justification_chars ?? 30;
  const snap = c.snapshot?.snapshot_id ?? null;

  const candidates = useMemo(() => {
    const q = find.trim().toLowerCase();
    return ev.filter((e) => !e.snapshot_id || e.snapshot_id === snap)
      .filter((e) => !q || `${e.evidence_id} ${e.type} ${e.title}`.toLowerCase().includes(q))
      .sort((a, b) => Number(a.type === "transaction") - Number(b.type === "transaction") || a.evidence_id.localeCompare(b.evidence_id))
      .slice(0, 60);
  }, [ev, find, snap]);

  const errors = {
    disposition: !disposition ? "Choose a decision." : null,
    why: why.trim().length < min ? `At least ${min} characters (${Math.max(0, min - why.trim().length)} more).` : null,
    cited: !cited.length ? "Cite at least one evidence item." : null,
  };
  const valid = !errors.disposition && !errors.why && !errors.cited;
  const spec = opts?.dispositions.find((d) => d.key === disposition);
  const pendingOnly = !!spec?.needs_senior && !senior;
  const toggle = (id: string) => setCited((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  const submit = async () => {
    if (!disposition) return;
    try {
      const out = await mut.mutateAsync({ disposition, concern_type: concern, justification: why.trim(), evidence_ids: cited,
        idempotency_key: key, expected_status: c.status, report_id: reportId ?? undefined });
      toast.push({ tone: "success", title: out.approval_status === "pending_senior" ? "Recommendation recorded" : "Decision recorded",
        body: out.approval_status === "pending_senior" ? "Awaiting senior confirmation." : `${out.from_status} → ${out.to_status}` });
      setConfirming(false); setDisposition(null); setWhy(""); setCited([]); setTouched(false); setKey(newIdempotencyKey());
    } catch (e) {
      toast.push({ tone: "error", title: "Decision not recorded", body: (e as Error).message });
    }
  };

  return (
    <form className="space-y-2.5" noValidate onSubmit={(e) => { e.preventDefault(); setTouched(true); if (valid) setConfirming(true); }}>
      <div>
        <label htmlFor="dsp-concern" className="label">Type of concern</label>
        <select id="dsp-concern" className="field mt-1 h-8 py-0 text-[13px]" value={concern} onChange={(e) => setConcern(e.target.value as ConcernType)}>
          {(opts?.concern_types ?? []).map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
        </select>
      </div>
      <fieldset>
        <legend className="label">Decision</legend>
        <div className="mt-1 space-y-1" role="radiogroup" aria-describedby={touched && errors.disposition ? "dsp-d-err" : undefined}>
          {(opts?.dispositions ?? []).map((d) => {
            const id = `dsp-${d.key}`;
            return (
              <label key={d.key} htmlFor={id} className={cx("flex cursor-pointer gap-2 rounded-md border px-2 py-1.5 text-[13px] transition-colors",
                disposition === d.key ? "border-accent bg-accent/10" : "border-border hover:bg-hover")}>
                <input id={id} type="radio" name="disposition" className="mt-0.5 accent-accent" checked={disposition === d.key} onChange={() => setDisposition(d.key)} />
                <span className="min-w-0">
                  <span className="block font-medium text-text">{labelFor(opts, d.key, concern)}</span>
                  <span className="block text-[12px] text-muted">
                    {d.needs_senior && !senior ? "Recorded as a recommendation; a senior investigator confirms." : d.help}
                  </span>
                </span>
              </label>
            );
          })}
        </div>
        {touched && errors.disposition && <p id="dsp-d-err" className="mt-1 text-[12px] text-critical">{errors.disposition}</p>}
      </fieldset>
      <div>
        <label htmlFor="dsp-why" className="label">Justification <span className="text-warning">(required)</span></label>
        <textarea id="dsp-why" rows={3} maxLength={4000} className="field mt-1 py-1.5 text-[13px]" value={why} onChange={(e) => setWhy(e.target.value)}
          aria-invalid={!!(touched && errors.why)} aria-describedby="dsp-why-help" placeholder="What the evidence shows and why it leads to this decision" />
        <p id="dsp-why-help" className={cx("mt-0.5 text-[11.5px]", touched && errors.why ? "text-critical" : "text-subtle")}>
          {errors.why ?? "Saved word for word in the audit trail."}
        </p>
      </div>
      <div>
        <p className="label" id="dsp-ev-label">Supporting evidence <span className="text-warning">(required)</span></p>
        {cited.length > 0 ? (
          <ul className="mt-1 flex flex-wrap gap-1" aria-labelledby="dsp-ev-label">
            {cited.map((id) => (
              <li key={id} className="inline-flex items-center gap-0.5">
                <CitationList ids={[id]} idBase={`dsp-${id}`} refs={refs} />
                <button type="button" onClick={() => toggle(id)} aria-label={`Remove ${id}`} className="rounded p-0.5 text-subtle hover:text-text"><X aria-hidden className="size-3.5" /></button>
              </li>
            ))}
          </ul>
        ) : <p className={cx("mt-0.5 text-[11.5px]", touched ? "text-critical" : "text-subtle")}>{errors.cited}</p>}
        <Button size="sm" variant="ghost" className="mt-1" aria-expanded={picking} aria-controls="dsp-picker" onClick={() => setPicking((p) => !p)}>
          {picking ? "Done choosing" : "Choose evidence"}
        </Button>
        {picking && (
          <div id="dsp-picker" className="mt-1 rounded-md border border-border">
            <div className="relative border-b border-border p-1.5">
              <label htmlFor="dsp-find" className="sr-only">Find evidence</label>
              <Search aria-hidden className="pointer-events-none absolute left-3.5 top-1/2 size-3.5 -translate-y-1/2 text-subtle" />
              <input id="dsp-find" className="field h-7 pl-7 text-[12.5px]" placeholder="ID, type or title" value={find} onChange={(e) => setFind(e.target.value)} />
            </div>
            <ul className="relative max-h-48 overflow-y-auto p-1" aria-label="Evidence to cite">
              {candidates.map((e) => (
                <li key={e.evidence_id}>
                  <label className="flex cursor-pointer items-start gap-2 rounded px-1.5 py-1 text-[12.5px] hover:bg-hover">
                    <input type="checkbox" className="mt-0.5 accent-accent" checked={cited.includes(e.evidence_id)} onChange={() => toggle(e.evidence_id)} />
                    <span className="min-w-0"><span className="mono text-text">{e.evidence_id}</span> <span className="text-subtle">· {e.type.replace(/_/g, " ")}</span>
                      <span className="block truncate text-muted">{e.title}</span></span>
                  </label>
                </li>
              ))}
              {!candidates.length && <li className="px-1.5 py-1 text-[12.5px] text-muted">No matching evidence.</li>}
            </ul>
          </div>
        )}
      </div>
      <Button type="submit" variant="primary" size="sm" icon={<ClipboardCheck aria-hidden className="size-4" />}>Review and submit</Button>

      <Modal open={confirming} onOpenChange={(o) => !o && setConfirming(false)} title="Confirm investigation decision"
        description="Check the summary. Once recorded, the decision cannot be edited; a later decision is added to the history."
        footer={<><Button variant="ghost" onClick={() => setConfirming(false)}>Back</Button>
          <Button variant="primary" loading={mut.isPending} onClick={submit}>{pendingOnly ? "Record recommendation" : "Record decision"}</Button></>}>
        {disposition && (
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[13.5px]">
            <dt className="text-subtle">Decision</dt><dd className="font-medium">{labelFor(opts, disposition, concern)}</dd>
            <dt className="text-subtle">Concern</dt><dd>{opts?.concern_types.find((t) => t.key === concern)?.label}</dd>
            <dt className="text-subtle">Case status</dt>
            <dd>{pendingOnly ? `Stays ${c.status} until a senior investigator confirms` : `${c.status} → ${spec?.status}`}</dd>
            <dt className="text-subtle">Evidence</dt><dd>{cited.length} item{cited.length === 1 ? "" : "s"} cited</dd>
            <dt className="text-subtle">Report</dt><dd>{reportId ? "The version on screen" : "Latest version"}, with its evidence fingerprint</dd>
            <dt className="text-subtle">Justification</dt><dd className="line-clamp-4 whitespace-pre-wrap text-muted">{why.trim()}</dd>
          </dl>
        )}
        {disposition === "substantiated" && (
          <p role="note" className="mt-3 rounded-md border border-warning/50 bg-warning/5 px-2.5 py-1.5 text-[12.5px]">{opts?.notice}</p>
        )}
      </Modal>
    </form>
  );
}

function DecisionHistory({ entries, refs }: { entries: DispositionEntry[]; refs: Refs }) {
  const [all, setAll] = useState(false);
  if (!entries.length) return null;
  const rows = [...entries].reverse();
  const shown = all ? rows : rows.slice(0, 3);
  return (
    <div>
      <h3 className="text-[12.5px] font-semibold text-muted">Decision history</h3>
      <ol className="mt-1 space-y-1.5" aria-label="Decision history, newest first">
        {shown.map((e) => (
          <li key={e.disposition_id} className="border-l-2 border-border-strong pl-2 text-[12.5px]">
            <p className="text-text"><span className="font-medium">{ENTRY[e.entry_type]}:</span> {e.label}
              {e.entry_type === "decision" && e.current_approval && e.current_approval !== "not_required" && (
                <span className="text-subtle"> · {APPROVAL[e.current_approval].text.toLowerCase()}</span>)}
            </p>
            <p className="line-clamp-2 whitespace-pre-wrap text-muted">{e.justification}</p>
            <p className="text-[11.5px] text-subtle">
              {e.reviewer_name ?? e.reviewer_id} ({e.reviewer_role}) · {utcToLocal(e.created_at_utc)} · report v{e.report_version ?? "–"}
              {e.evidence_hash && <> · <span className="mono" title={e.evidence_hash}>{e.evidence_hash.slice(0, 10)}…</span></>}
            </p>
            {e.entry_type === "decision" && <p className="text-[11.5px]"><CitationList ids={e.evidence_ids} idBase={`hist-${e.disposition_id}`} refs={refs} inline={3} /></p>}
          </li>
        ))}
      </ol>
      {rows.length > 3 && (
        <button type="button" onClick={() => setAll((a) => !a)} className="mt-1 text-[12px] text-accent hover:text-text">{all ? "Show fewer" : `All ${rows.length} entries`}</button>
      )}
    </div>
  );
}
