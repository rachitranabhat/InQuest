import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { Finding } from "../../types/api";
import { useSelection } from "./selection";

export type ExplorerTab = "transactions" | "retailers" | "timeline" | "history" | "graph" | "saved" | "report";
/** Top-level investigation views (the workspace tabs). */
export type View = "summary" | "ai" | "evidence" | "history" | "review";

/** Which view each explorer tab lives in. */
export const VIEW_FOR_TAB: Record<ExplorerTab, View> = {
  transactions: "evidence", retailers: "evidence", timeline: "evidence", graph: "evidence", saved: "evidence",
  history: "history", report: "review",
};

export interface FindingFocus {
  key: string;
  label: string;
  evidenceId: string;
  txnIds: string[];
}

/** Things the investigator has done in this visit; the checklist reads them. */
export type Activity = "finding" | "evidence" | "history" | "saved";

interface ExplorerState {
  tab: ExplorerTab;
  setTab: (t: ExplorerTab) => void;
  view: View;
  setView: (v: View) => void;
  focus: FindingFocus | null;
  clearFocus: () => void;
  /** "View evidence" on a finding: open the right tab, filter to its records and highlight them. */
  showFinding: (f: Finding) => void;
  /** A citation was opened: bring the matching explorer tab forward. */
  revealType: (evidenceType: string | undefined) => void;
  activity: Set<Activity>;
  mark: (a: Activity) => void;
}

const Ctx = createContext<ExplorerState | null>(null);

const TAB_FOR_TYPE: Record<string, ExplorerTab> = {
  transaction: "transactions", aggregate_day: "timeline", sequence: "timeline", aggregate_retailer: "retailers",
  retailer: "retailers", location: "retailers", baseline: "history", comparison: "history", metric: "history",
};

export function ExplorerProvider({ children }: { children: ReactNode }) {
  const sel = useSelection();
  const [tab, setTabState] = useState<ExplorerTab>("transactions");
  const [view, setViewState] = useState<View>("summary");
  const [focus, setFocus] = useState<FindingFocus | null>(null);
  const [activity, setActivity] = useState<Set<Activity>>(() => new Set());

  const mark = useCallback((a: Activity) => setActivity((s) => (s.has(a) ? s : new Set(s).add(a))), []);
  const setView = useCallback((v: View) => {
    setViewState(v);
    if (v === "history") mark("history"); // the checklist counts opening the historical comparison
  }, [mark]);

  /** Explicit navigation (a button, a checklist "Go"): switch the tab and bring its view forward. */
  const setTab = useCallback((t: ExplorerTab) => {
    setTabState(t);
    setView(VIEW_FOR_TAB[t]);
    if (t === "history") mark("history");
    if (t === "saved") mark("saved");
  }, [mark, setView]);

  const { highlightTransactions } = sel;
  const showFinding = useCallback((f: Finding) => {
    const txnIds = f.supporting_transaction_ids;
    setFocus({ key: f.key, label: f.label, evidenceId: f.evidence_id, txnIds });
    highlightTransactions(txnIds);
    mark("finding");
    setTab(f.key === "location" ? "retailers" : txnIds.length ? "transactions" : "history");
    requestAnimationFrame(() => document.getElementById("explorer-title")?.focus());
  }, [highlightTransactions, mark, setTab]);

  const revealType = useCallback((type: string | undefined) => {
    mark("evidence");
    // Only line up the matching sub-tab; the current view stays put so focus can return to the citation.
    const t = type ? TAB_FOR_TYPE[type] : undefined;
    if (t) setTabState(t);
  }, [mark]);

  const value = useMemo<ExplorerState>(() => ({
    tab, setTab, view, setView, focus, clearFocus: () => { setFocus(null); highlightTransactions([]); },
    showFinding, revealType, activity, mark,
  }), [tab, setTab, view, setView, focus, showFinding, revealType, activity, mark, highlightTransactions]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** Optional: components such as citation chips also render outside the workspace (e.g. the explorer page, tests). */
export function useExplorerOptional(): ExplorerState | null {
  return useContext(Ctx);
}

export function useExplorer(): ExplorerState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useExplorer outside ExplorerProvider");
  return v;
}
