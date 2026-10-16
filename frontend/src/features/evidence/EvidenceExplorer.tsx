import * as Tabs from "@radix-ui/react-tabs";
import { Crosshair, X } from "lucide-react";
import type { ReactNode } from "react";
import { useBookmarks } from "../../hooks/queries";
import type { CaseDetail, EvidenceItem } from "../../types/api";
import { useExplorer, type ExplorerTab } from "../workspace/explorer";

/**
 * Center panel. Every supporting record lives here once; findings, citations and the copilot point into it.
 * Tab content is passed in so the workspace decides what each tab renders.
 */
export function EvidenceExplorer({ c, items, panels }: {
  c: CaseDetail; items: EvidenceItem[]; panels: Partial<Record<ExplorerTab, ReactNode>>;
}) {
  const ex = useExplorer();
  const saved = useBookmarks(c.case_id).data?.length ?? 0;
  const isAcct = c.channel === "online_account";
  const txns = items.filter((i) => i.type === "transaction" && i.snapshot_id).length;
  const rets = items.filter((i) => i.type === "aggregate_retailer").length;
  const all: [ExplorerTab, string, number | null][] = [
    ["transactions", "Transactions", txns],
    ["retailers", isAcct ? "Account" : "Retailers", isAcct ? null : rets],
    ["timeline", "Timeline", null],
    ["history", "Historical comparison", null],
    ["graph", "Relationships", null],
    ["saved", "Saved", saved || null],
    ["report", "Report", null],
  ];
  const tabs = all.filter(([v]) => v in panels);
  const value = tabs.some(([v]) => v === ex.tab) ? ex.tab : tabs[0][0];
  return (
    <section aria-labelledby="explorer-title" className="panel relative flex min-h-0 min-w-0 max-w-full flex-1 flex-col overflow-hidden">
      <div className="flex items-center justify-between gap-3 px-3 pt-2.5">
        <h2 id="explorer-title" tabIndex={-1} className="text-[14.5px] outline-none">Evidence Explorer</h2>
        {ex.focus && (
          <p role="status" className="flex min-w-0 items-center gap-1.5 rounded-md border border-accent/50 bg-accent/10 py-0.5 pl-2 pr-0.5 text-[12.5px]">
            <Crosshair aria-hidden className="size-3.5 shrink-0 text-accent" />
            <span className="truncate">Evidence for <strong className="font-semibold">{ex.focus.label}</strong>
              {ex.focus.txnIds.length > 0 && <span className="text-muted"> · {ex.focus.txnIds.length} records</span>}</span>
            <button type="button" onClick={ex.clearFocus} aria-label="Clear evidence focus"
              className="rounded p-0.5 text-muted hover:bg-hover hover:text-text"><X aria-hidden className="size-3.5" /></button>
          </p>
        )}
      </div>
      <Tabs.Root value={value} onValueChange={(v) => ex.setTab(v as ExplorerTab)} className="flex min-h-0 min-w-0 flex-1 flex-col">
        <Tabs.List aria-label="Evidence views" className="flex gap-0.5 overflow-x-auto border-b border-border px-1.5 pt-1">
          {tabs.map(([v, l, n]) => (
            <Tabs.Trigger key={v} value={v}
              className="relative shrink-0 whitespace-nowrap rounded-t-md px-2.5 py-2 text-[13px] font-medium text-muted transition-colors hover:text-text data-[state=active]:text-text data-[state=active]:after:absolute data-[state=active]:after:inset-x-2 data-[state=active]:after:-bottom-px data-[state=active]:after:h-[2px] data-[state=active]:after:bg-accent">
              {l}{n !== null && <span className="ml-1 text-[12px] font-normal text-subtle">{n}</span>}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
        {tabs.map(([v]) => (
          <Tabs.Content key={v} value={v} className={v === "graph" ? "relative min-h-0 flex-1" : "relative min-h-0 flex-1 overflow-y-auto"}>
            {panels[v]}
          </Tabs.Content>
        ))}
      </Tabs.Root>
    </section>
  );
}
