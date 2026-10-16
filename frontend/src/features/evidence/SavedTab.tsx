import { Bookmark as BookmarkIcon, MessageSquareText, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import { useApp } from "../../app/AppContext";
import { Button } from "../../components/ui/Button";
import { EmptyState, ErrorState, LoadingBlock } from "../../components/ui/Primitives";
import { useToast } from "../../components/ui/Toast";
import { useAudit, useBookmarkMutations, useBookmarks } from "../../hooks/queries";
import { utcToLocal } from "../../lib/format";
import { plainTitle } from "../../lib/terms";
import type { Bookmark } from "../../types/api";
import { CitationChip } from "../workspace/CitationChip";

type Refs = Record<string, { type: string; title: string }>;
const GROUPS: [Bookmark["kind"], string][] = [["finding", "Findings"], ["transaction", "Transactions"], ["retailer", "Retailers & entities"], ["evidence", "Other evidence"]];

/** Everything the investigator saved in one place: bookmarks with their notes, then case notes from the audit trail. */
export function SavedTab({ caseId, refs }: { caseId: string; refs: Refs }) {
  const { data, error, isLoading, refetch } = useBookmarks(caseId);
  const audit = useAudit(caseId);
  const notes = (audit.data ?? []).filter((a) => a.notes);
  if (error) return <ErrorState error={error} onRetry={() => refetch()} title="Could not load bookmarks" />;
  if (isLoading || !data) return <LoadingBlock label="Loading bookmarks" />;
  return (
    <div className="space-y-5 p-3">
      {data.length === 0 ? (
        <EmptyState title="Nothing saved yet" icon={<BookmarkIcon aria-hidden className="size-6" />}>
          Use the bookmark icon on a finding, transaction, retailer or evidence record to keep it here with a note.
        </EmptyState>
      ) : GROUPS.map(([k, label]) => {
        const xs = data.filter((b) => b.kind === k);
        if (!xs.length) return null;
        return (
          <section key={k} aria-labelledby={`saved-${k}`}>
            <h3 id={`saved-${k}`} className="mb-1.5 text-[12px] font-semibold uppercase tracking-wide text-subtle">{label} ({xs.length})</h3>
            <ul className="space-y-1.5">{xs.map((b) => <SavedItem key={b.bookmark_id} b={b} caseId={caseId} refs={refs} />)}</ul>
          </section>
        );
      })}
      <section aria-labelledby="saved-notes" className="border-t border-border pt-3">
        <h3 id="saved-notes" className="mb-1.5 flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide text-subtle">
          <MessageSquareText aria-hidden className="size-3.5" /> Case notes and decision notes ({notes.length})
        </h3>
        {notes.length === 0 ? <p className="text-[13px] text-muted">No notes recorded on this case yet.</p> : (
          <ul className="space-y-1.5">
            {notes.map((n) => (
              <li key={n.action_id} className="rounded-md border border-border px-2.5 py-1.5 text-[13px]">
                <p className="whitespace-pre-wrap text-text">{n.notes}</p>
                <p className="mt-0.5 text-[12px] text-subtle">{n.reviewer_name ?? n.reviewer_id} · {n.action.replace(/_/g, " ")} · {utcToLocal(n.created_at_utc)}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function SavedItem({ b, caseId, refs }: { b: Bookmark; caseId: string; refs: Refs }) {
  const { session } = useApp();
  const toast = useToast();
  const m = useBookmarkMutations(caseId);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(b.note ?? "");
  const ref = refs[b.evidence_id];
  const save = async () => {
    try {
      await m.note.mutateAsync({ id: b.bookmark_id, note: text });
      setEditing(false);
    } catch (e) {
      toast.push({ tone: "error", title: "Note not saved", body: (e as Error).message });
    }
  };
  const fieldId = `note-${b.bookmark_id}`;
  return (
    <li className="rounded-md border border-border px-2.5 py-2">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-[13.5px] text-text">{ref ? plainTitle(ref.type, ref.title) : b.label}</p>
          <p className="text-[12px] text-subtle">Saved by {b.reviewer_name} · {utcToLocal(b.updated_at_utc)}</p>
        </div>
        <CitationChip evidenceId={b.evidence_id} originId={`saved-${b.bookmark_id}`} refInfo={ref} />
        <Button size="sm" variant="ghost" aria-label={`Edit note on ${b.label}`} disabled={!session} className="h-7 px-1.5"
          icon={<Pencil aria-hidden className="size-3.5" />} onClick={() => setEditing((x) => !x)} />
        <Button size="sm" variant="ghost" aria-label={`Remove bookmark ${b.label}`} disabled={!session || m.remove.isPending} className="h-7 px-1.5"
          icon={<Trash2 aria-hidden className="size-3.5" />} onClick={() => m.remove.mutate(b.bookmark_id)} />
      </div>
      {editing ? (
        <form className="mt-2 space-y-1.5" onSubmit={(e) => { e.preventDefault(); save(); }}>
          <label htmlFor={fieldId} className="sr-only">Note for {b.label}</label>
          <textarea id={fieldId} rows={2} maxLength={2000} className="field text-[13px]" value={text} onChange={(e) => setText(e.target.value)}
            placeholder="Why this matters, what to check next…" />
          <div className="flex gap-2">
            <Button size="sm" variant="primary" type="submit" loading={m.note.isPending}>Save note</Button>
            <Button size="sm" variant="ghost" onClick={() => { setEditing(false); setText(b.note ?? ""); }}>Cancel</Button>
          </div>
        </form>
      ) : b.note ? (
        <p className="mt-1.5 whitespace-pre-wrap border-l-2 border-warning/60 pl-2 text-[13px] text-muted">{b.note}</p>
      ) : null}
    </li>
  );
}
