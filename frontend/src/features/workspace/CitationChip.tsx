import { FileText } from "lucide-react";
import { useState } from "react";
import { cx } from "../../lib/cx";
import { humanType } from "../../lib/format";
import { plainTitle } from "../../lib/terms";
import { useExplorerOptional } from "./explorer";
import { useSelection } from "./selection";

type RefInfo = { type: string; title: string };

/**
 * Clickable evidence citation. Opens the drawer, highlights linked records, brings the matching
 * Evidence Explorer tab forward, and remembers where it was so focus can return.
 */
export function CitationChip({ evidenceId, originId, refInfo }: {
  evidenceId: string;
  originId: string;
  refInfo?: RefInfo;
}) {
  const sel = useSelection();
  const explorer = useExplorerOptional();
  const active = sel.evidenceId === evidenceId && sel.drawerOpen;
  const label = refInfo ? `${humanType(refInfo.type)}: ${plainTitle(refInfo.type, refInfo.title)}` : evidenceId;
  return (
    <button
      id={originId}
      type="button"
      onClick={() => {
        sel.select(evidenceId, { originId });
        explorer?.revealType(refInfo?.type ?? sel.itemById(evidenceId)?.type);
      }}
      aria-label={`Open evidence ${evidenceId} — ${label}`}
      aria-pressed={active}
      title={label}
      className={cx(
        "mono inline-flex items-center gap-1 rounded border px-1.5 py-[1px] align-baseline text-[11.5px] leading-[18px]",
        "transition-[background-color,border-color,color,box-shadow] duration-150",
        active
          ? "border-accent bg-accent/15 text-accent glow-accent"
          : "border-border-strong bg-bg text-muted hover:border-accent hover:text-accent active:bg-accent/10",
      )}
    >
      <FileText aria-hidden className="size-3" />
      {evidenceId}
    </button>
  );
}

/**
 * Citations for one statement: the first `inline` chips are shown, the rest behind "+N".
 * All citations stay one keypress away; nothing is dropped.
 */
export function CitationList({ ids, idBase, refs, inline = 1 }: {
  ids: string[]; idBase: string; refs: Record<string, RefInfo>; inline?: number;
}) {
  const [all, setAll] = useState(false);
  const shown = all ? ids : ids.slice(0, inline);
  const rest = ids.length - shown.length;
  return (
    <span className="inline-flex flex-wrap items-baseline gap-1 align-baseline">
      {shown.map((e) => <CitationChip key={e} evidenceId={e} originId={`cite-${idBase}-${e}`} refInfo={refs[e]} />)}
      {rest > 0 && (
        <button type="button" onClick={() => setAll(true)} aria-label={`Show ${rest} more citation${rest === 1 ? "" : "s"}`}
          className="mono rounded border border-dashed border-border-strong px-1.5 text-[11.5px] leading-[18px] text-subtle hover:border-accent hover:text-accent">
          +{rest}
        </button>
      )}
    </span>
  );
}
