import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { EvidenceItem } from "../../types/api";

/**
 * Evidence selection shared by the report, the evidence drawer, the timeline and the graph.
 * `originId` is the DOM id of the element that opened the drawer (a citation chip), so focus and
 * scroll can return to the exact spot in the report ("back to report").
 */
interface SelectionState {
  evidenceId: string | null;
  originId: string | null;
  highlightTxnIds: Set<string>;
  drawerOpen: boolean;
  select: (evidenceId: string, opts?: { originId?: string; openDrawer?: boolean }) => void;
  highlightTransactions: (ids: string[]) => void;
  closeDrawer: () => void;
  clear: () => void;
  itemById: (id: string) => EvidenceItem | undefined;
  evidenceIdForTxn: (txnId: string) => string | undefined;
}

const Ctx = createContext<SelectionState | null>(null);

export function SelectionProvider({ children, items }: { children: ReactNode; items: EvidenceItem[] | undefined }) {
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const [originId, setOriginId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [extra, setExtra] = useState<string[]>([]);
  const byId = useMemo(() => new Map((items ?? []).map((i) => [i.evidence_id, i])), [items]);
  const byTxn = useMemo(
    () => new Map((items ?? []).filter((i) => i.type === "transaction").map((i) => [i.source_ids[0], i.evidence_id])),
    [items],
  );

  const highlightTxnIds = useMemo(() => {
    const s = new Set<string>(extra);
    const it = evidenceId ? byId.get(evidenceId) : undefined;
    if (it) for (const id of it.source_ids) if (id.startsWith("TXN-")) s.add(id);
    return s;
  }, [evidenceId, byId, extra]);

  const select = useCallback((id: string, opts?: { originId?: string; openDrawer?: boolean }) => {
    setEvidenceId(id);
    setExtra([]);
    setOriginId(opts?.originId ?? null);
    if (opts?.openDrawer !== false) setDrawerOpen(true);
  }, []);

  const value = useMemo<SelectionState>(
    () => ({
      evidenceId,
      originId,
      highlightTxnIds,
      drawerOpen,
      select,
      highlightTransactions: (ids) => setExtra(ids),
      closeDrawer: () => setDrawerOpen(false),
      clear: () => {
        setEvidenceId(null);
        setExtra([]);
        setDrawerOpen(false);
      },
      itemById: (id) => byId.get(id),
      evidenceIdForTxn: (t) => byTxn.get(t),
    }),
    [evidenceId, originId, highlightTxnIds, drawerOpen, select, byId, byTxn],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSelection(): SelectionState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSelection outside SelectionProvider");
  return v;
}
