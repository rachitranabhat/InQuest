import { Bookmark as BookmarkIcon, BookmarkCheck } from "lucide-react";
import { useAppOptional } from "../../app/AppContext";
import { useToast } from "../../components/ui/Toast";
import { useBookmarkMutations, useBookmarks } from "../../hooks/queries";
import { cx } from "../../lib/cx";

/**
 * Bookmarks are hidden from the case workflow for now (the backend data and API stay untouched).
 * Set to true to bring the buttons back; the Saved view would also need re-adding to the Evidence Explorer.
 */
export const BOOKMARKS_IN_CASE_UI = false;

/** Save / unsave one evidence item. */
export function BookmarkButton({ caseId, evidenceId, label, className, withText = false }: {
  caseId: string; evidenceId: string; label: string; className?: string; withText?: boolean;
}) {
  if (!BOOKMARKS_IN_CASE_UI) return null;
  return <BookmarkToggle caseId={caseId} evidenceId={evidenceId} label={label} className={className} withText={withText} />;
}

function BookmarkToggle({ caseId, evidenceId, label, className, withText = false }: {
  caseId: string; evidenceId: string; label: string; className?: string; withText?: boolean;
}) {
  const session = useAppOptional()?.session;
  const toast = useToast();
  const { data } = useBookmarks(caseId);
  const m = useBookmarkMutations(caseId);
  const saved = data?.find((b) => b.evidence_id === evidenceId);
  const busy = m.add.isPending || m.remove.isPending;
  const disabled = !session || busy;

  const toggle = async () => {
    try {
      if (saved) await m.remove.mutateAsync(saved.bookmark_id);
      else await m.add.mutateAsync({ evidence_id: evidenceId, label });
    } catch (e) {
      toast.push({ tone: "error", title: "Bookmark not saved", body: (e as Error).message });
    }
  };

  const name = !session ? `Choose a reviewer to bookmark ${label}` : saved ? `Remove bookmark: ${label}` : `Bookmark ${label}`;
  return (
    <button type="button" onClick={toggle} disabled={disabled} aria-pressed={!!saved} aria-label={name} title={name}
      className={cx(
        "inline-flex shrink-0 items-center gap-1 rounded p-1 text-[12.5px] transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50",
        saved ? "text-warning hover:text-text" : "text-subtle hover:text-accent",
        className,
      )}>
      {saved ? <BookmarkCheck aria-hidden className="size-4" /> : <BookmarkIcon aria-hidden className="size-4" />}
      {withText && <span>{saved ? "Saved" : "Save"}</span>}
    </button>
  );
}
