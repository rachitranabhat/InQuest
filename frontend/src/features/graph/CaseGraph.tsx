import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import { Maximize2, Minus, Plus, RotateCcw, Search, Table2, Network } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "../../components/ui/Button";
import { EmptyState, ErrorState, LoadingBlock } from "../../components/ui/Primitives";
import { useGraph } from "../../hooks/queries";
import { cx } from "../../lib/cx";
import { money } from "../../lib/format";
import type { CaseGraph as G, GraphNode } from "../../types/api";
import { useSelection } from "../workspace/selection";
import { useTheme } from "../../app/theme";
import { cssVar } from "../../lib/chartTheme";

// Node colours are theme tokens, resolved to concrete values when the graph is drawn (Cytoscape draws on canvas).
const TYPE_STYLE: Record<string, { label: string; token: string; shape: cytoscape.Css.NodeShape; size: number }> = {
  case: { label: "Case", token: "--color-accent", shape: "round-rectangle", size: 34 },
  alert: { label: "Alert", token: "--color-critical", shape: "diamond", size: 32 },
  indicator: { label: "Indicator", token: "--color-warning", shape: "hexagon", size: 28 },
  player: { label: "Player", token: "--color-analysis", shape: "round-rectangle", size: 30 },
  account: { label: "Account", token: "--color-analysis", shape: "round-rectangle", size: 30 },
  transaction: { label: "Transaction", token: "--color-subtle", shape: "ellipse", size: 14 },
  retailer: { label: "Retailer", token: "--color-muted", shape: "rectangle", size: 26 },
  location: { label: "Location", token: "--color-success", shape: "tag", size: 24 },
  anonymous_group: { label: "Anonymous sales", token: "--color-border-strong", shape: "ellipse", size: 22 },
  event: { label: "Context event", token: "--color-analysis", shape: "star", size: 26 },
};

function elements(g: G, hidden: Set<string>): ElementDefinition[] {
  const nodes = g.nodes.filter((n) => !hidden.has(n.type));
  const ids = new Set(nodes.map((n) => n.id));
  return [
    ...nodes.map((n) => ({
      data: { id: n.id, label: n.type === "transaction" ? "" : n.label, full: n.label, type: n.type,
        linked: ((n.data.linked_factors as string[] | undefined) ?? []).length > 0 ? 1 : 0 },
    })),
    ...g.edges.filter((e) => ids.has(e.source) && ids.has(e.target)).map((e) => ({
      data: { id: e.id, source: e.source, target: e.target, relation: e.relation },
    })),
  ];
}

function graphStyle(): cytoscape.StylesheetJson {
  const v = (n: string) => cssVar(n);
  const colors = Object.fromEntries(Object.entries(TYPE_STYLE).map(([k, t]) => [k, v(t.token)]));
  const [text, bg, warning, muted, edge, strongB, support, accent] =
    ["--color-text", "--color-bg", "--color-warning", "--color-muted", "--color-edge", "--color-border-strong", "--color-edge-support", "--color-accent"].map(v);
  return [
    { selector: "node", style: {
      "background-color": (e: cytoscape.NodeSingular) => colors[e.data("type")] ?? colors.transaction,
      shape: (e: cytoscape.NodeSingular) => TYPE_STYLE[e.data("type")]?.shape ?? "ellipse",
      width: (e: cytoscape.NodeSingular) => TYPE_STYLE[e.data("type")]?.size ?? 18,
      height: (e: cytoscape.NodeSingular) => TYPE_STYLE[e.data("type")]?.size ?? 18,
      label: "data(label)", color: text, "font-size": 10, "font-family": "Inter, sans-serif",
      "text-valign": "bottom", "text-margin-y": 4, "text-wrap": "ellipsis", "text-max-width": "110px",
      "border-width": 1.5, "border-color": bg, "transition-property": "border-width, border-color, opacity", "transition-duration": 150,
    } as never },
    { selector: "node[type = 'transaction'][linked = 1]", style: { "background-color": warning, shape: "diamond" } },
    { selector: "node[type = 'anonymous_group']", style: { "border-style": "dashed", "border-color": muted, "background-opacity": 0.5 } },
    { selector: "edge", style: { width: 1.2, "line-color": edge, "target-arrow-color": edge, "target-arrow-shape": "triangle",
      "arrow-scale": 0.7, "curve-style": "bezier", opacity: 0.85 } },
    { selector: "edge[relation = 'co_located']", style: { "line-style": "dashed", "line-color": warning, "target-arrow-color": warning } },
    { selector: "edge[relation = 'anonymous_at']", style: { "line-style": "dotted", "line-color": strongB, "target-arrow-color": strongB } },
    { selector: "edge[relation = 'supported_by']", style: { "line-color": support, "target-arrow-color": support } },
    { selector: ".hl", style: { "border-width": 4, "border-color": accent, "z-index": 10 } },
    { selector: ".dim", style: { opacity: 0.25 } },
    { selector: "node:selected", style: { "border-width": 4, "border-color": text } },
  ];
}

export function CaseGraph({ caseId, height = 420 }: { caseId: string; height?: number }) {
  const { data, error, isLoading, refetch } = useGraph(caseId);
  const sel = useSelection();
  const { theme } = useTheme();
  const box = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<GraphNode | null>(null);
  const [asTable, setAsTable] = useState(false);
  const els = useMemo(() => (data ? elements(data, hidden) : []), [data, hidden]);
  const reduced = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

  useEffect(() => {
    if (!box.current || !data || asTable) return;
    const inst = cytoscape({ container: box.current, elements: els, style: graphStyle(), minZoom: 0.2, maxZoom: 3,
      wheelSensitivity: 0.25, layout: { name: "cose", animate: false, padding: 20, nodeRepulsion: () => 9000, idealEdgeLength: () => 70 } as never });
    inst.on("tap", "node", (e) => {
      const n = data.nodes.find((x) => x.id === e.target.id()) ?? null;
      setPicked(n);
      if (n?.evidence_ids[0]) sel.select(n.evidence_ids[0], { openDrawer: false });
    });
    inst.on("tap", (e) => { if (e.target === inst) setPicked(null); });
    cy.current = inst;
    return () => { inst.destroy(); cy.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [els, asTable]);

  // re-colour (no re-layout) when the theme changes
  useEffect(() => { cy.current?.style(graphStyle()); }, [theme]);

  // sync highlight with the shared evidence selection
  useEffect(() => {
    const inst = cy.current;
    if (!inst || !data) return;
    inst.elements().removeClass("hl dim");
    const ev = sel.evidenceId;
    const hits = data.nodes.filter((n) => sel.highlightTxnIds.has(n.id) || (ev && n.evidence_ids.includes(ev))).map((n) => n.id);
    if (hits.length) {
      let col = inst.collection();
      for (const id of hits) { const el = inst.getElementById(id); if (el.nonempty()) col = col.union(el); }
      col.addClass("hl");
      inst.elements().not(col.closedNeighborhood()).addClass("dim");
    }
  }, [sel.evidenceId, sel.highlightTxnIds, data, els]);

  useEffect(() => {
    const inst = cy.current;
    if (!inst) return;
    inst.nodes().removeClass("hl");
    const ql = query.trim().toLowerCase();
    if (ql.length < 2) return;
    const m = inst.nodes().filter((n) => `${n.id()} ${n.data("full")}`.toLowerCase().includes(ql));
    m.addClass("hl");
    if (m.nonempty()) inst.animate({ fit: { eles: m, padding: 60 } }, { duration: reduced ? 0 : 200 });
  }, [query, reduced]);

  if (error) return <ErrorState error={error} onRetry={() => refetch()} title="Could not load relationships" />;
  if (isLoading || !data) return <LoadingBlock label="Loading relationship graph" />;
  if (!data.nodes.length) return <EmptyState title="No relationships recorded" />;

  const zoom = (f: number) => cy.current?.zoom({ level: (cy.current.zoom() || 1) * f, renderedPosition: { x: (box.current?.clientWidth ?? 0) / 2, y: height / 2 } });
  const types = data.node_types;

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border p-2">
        <div className="relative">
          <label htmlFor={`g-search-${caseId}`} className="sr-only">Search entities</label>
          <Search aria-hidden className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-subtle" />
          <input id={`g-search-${caseId}`} className="field h-8 w-[170px] pl-7 text-[13px]" placeholder="Find ID or name" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        {!asTable && (
          <div className="flex gap-1" role="group" aria-label="Graph view controls">
            <Button size="sm" variant="ghost" aria-label="Zoom in" onClick={() => zoom(1.25)} icon={<Plus aria-hidden className="size-4" />} />
            <Button size="sm" variant="ghost" aria-label="Zoom out" onClick={() => zoom(0.8)} icon={<Minus aria-hidden className="size-4" />} />
            <Button size="sm" variant="ghost" aria-label="Fit to view" onClick={() => cy.current?.fit(undefined, 20)} icon={<Maximize2 aria-hidden className="size-4" />} />
            <Button size="sm" variant="ghost" aria-label="Reset layout" onClick={() => cy.current?.layout({ name: "cose", animate: !reduced, padding: 20 } as never).run()} icon={<RotateCcw aria-hidden className="size-4" />} />
          </div>
        )}
        <Button size="sm" variant="secondary" className="ml-auto" aria-pressed={asTable} onClick={() => setAsTable((t) => !t)}
          icon={asTable ? <Network aria-hidden className="size-4" /> : <Table2 aria-hidden className="size-4" />}>
          {asTable ? "Graph view" : "Table view"}
        </Button>
      </div>
      <fieldset className="flex flex-wrap gap-1.5 border-b border-border px-2 py-2">
        <legend className="sr-only">Show node types</legend>
        {types.map((t) => {
          const on = !hidden.has(t);
          const st = TYPE_STYLE[t];
          return (
            <label key={t} className={cx("flex cursor-pointer items-center gap-1.5 rounded-full border px-2 py-0.5 text-[12.5px] transition-colors",
              on ? "border-border-strong text-text" : "border-border text-subtle line-through")}>
              <input type="checkbox" className="sr-only" checked={on}
                onChange={() => setHidden((h) => { const n = new Set(h); if (n.has(t)) n.delete(t); else n.add(t); return n; })} />
              <span aria-hidden className="size-2.5 rounded-sm" style={{ background: st ? `var(${st.token})` : undefined }} />
              {st?.label ?? t} <span className="text-subtle">{data.nodes.filter((n) => n.type === t).length}</span>
            </label>
          );
        })}
      </fieldset>
      {asTable ? (
        <GraphTable g={data} hidden={hidden} query={query} />
      ) : (
        <div className="relative min-h-0 flex-1">
          <div ref={box} style={{ height }} className="w-full" role="img"
            aria-label={`Relationship graph with ${data.nodes.length} entities and ${data.edges.length} links. Use Table view for a keyboard-accessible list.`} />
          {picked && <NodeCard n={picked} g={data} onClose={() => setPicked(null)} />}
        </div>
      )}
      <p className="border-t border-border px-2 py-1.5 text-[12px] text-subtle">
        Edges are recorded relationships only. Dashed amber = co-location at a retailer (not a relationship); dotted = anonymous sales, buyer unknown.
      </p>
    </div>
  );
}

function NodeCard({ n, g, onClose }: { n: GraphNode; g: G; onClose: () => void }) {
  const sel = useSelection();
  const edges = g.edges.filter((e) => e.source === n.id || e.target === n.id);
  return (
    <div className="absolute right-2 top-2 w-[260px] rounded-lg border border-border-strong bg-elevated p-3 text-[13px] shadow-xl animate-fade-in" role="dialog" aria-label={`Details for ${n.label}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="eyebrow">{TYPE_STYLE[n.type]?.label ?? n.type}</p>
          <p className="mono mt-0.5 break-words text-text">{n.label}</p>
        </div>
        <button className="rounded p-0.5 text-subtle hover:text-text" aria-label="Close details" onClick={onClose}>×</button>
      </div>
      {"amount" in n.data && <p className="mt-1">{money(n.data.amount as number)} · <span className="mono">{String(n.data.timestamp_local)}</span></p>}
      <p className="mt-1 text-muted">{edges.length} link{edges.length === 1 ? "" : "s"}: {Array.from(new Set(edges.map((e) => e.meaning.split(" — ")[0]))).slice(0, 3).join("; ")}</p>
      {n.evidence_ids[0] && (
        <Button size="sm" variant="primary" className="mt-2" onClick={() => sel.select(n.evidence_ids[0])}>Open evidence {n.evidence_ids[0]}</Button>
      )}
    </div>
  );
}

function GraphTable({ g, hidden, query }: { g: G; hidden: Set<string>; query: string }) {
  const sel = useSelection();
  const ql = query.trim().toLowerCase();
  const nodes = new Map(g.nodes.map((n) => [n.id, n]));
  const edges = g.edges.filter((e) => !hidden.has(nodes.get(e.source)?.type ?? "") && !hidden.has(nodes.get(e.target)?.type ?? "")
    && (!ql || `${e.source} ${e.target} ${nodes.get(e.source)?.label} ${nodes.get(e.target)?.label}`.toLowerCase().includes(ql)));
  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <table className="w-full text-left text-[13px]">
        <caption className="sr-only">Relationships in this case</caption>
        <thead className="sticky top-0 bg-surface text-subtle">
          <tr><th scope="col" className="px-2 py-1.5 font-medium">From</th><th scope="col" className="px-2 py-1.5 font-medium">Relationship</th><th scope="col" className="px-2 py-1.5 font-medium">To</th><th scope="col" className="px-2 py-1.5 font-medium">Evidence</th></tr>
        </thead>
        <tbody>
          {edges.slice(0, 400).map((e) => (
            <tr key={e.id} className="border-t border-border/70">
              <td className="mono px-2 py-1.5">{nodes.get(e.source)?.label}</td>
              <td className="px-2 py-1.5 text-muted">{e.meaning}</td>
              <td className="mono px-2 py-1.5">{nodes.get(e.target)?.label}</td>
              <td className="px-2 py-1.5">
                {e.evidence_ids[0] && (
                  <button className="mono rounded border border-border-strong px-1.5 text-[12px] text-muted hover:border-accent hover:text-accent"
                    onClick={() => sel.select(e.evidence_ids[0])}>{e.evidence_ids[0]}</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
