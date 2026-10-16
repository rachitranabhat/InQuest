import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { FlaskConical, Info, LockKeyhole, Search } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { useApp } from "../../app/AppContext";
import { Button } from "../../components/ui/Button";
import { EmptyState, ErrorState, LoadingBlock, Stat } from "../../components/ui/Primitives";
import { api } from "../../lib/api";
import { num, utcToLocal } from "../../lib/format";
import type { EvalMetrics, EvalWorld } from "../../types/api";

const COUNTS: [string, string][] = [
  ["players", "Synthetic players"], ["transactions", "Transactions"], ["retailers", "Retailers"], ["terminals", "Terminals"],
  ["alerts", "Alerts"], ["cases", "Cases"],
];
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "n/a" : `${(v * 100).toFixed(1)}%`);
const label = (c: string) => c.replace(/_/g, " ");

/** Secondary page: what the synthetic dataset is, where it is stored, and (senior) how detection scores on it. */
export default function DataMethodologyPage() {
  const { session, isSenior } = useApp();
  const ov = useQuery({ queryKey: ["methodology", session?.reviewer.reviewer_id], queryFn: api.methodology, enabled: !!session });
  return (
    <div className="mx-auto max-w-[1300px] space-y-4 p-4 sm:p-6">
      <header className="space-y-1.5">
        <h1 className="text-[22px]">Data & Methodology</h1>
        <p className="text-[14px] text-muted">What the synthetic dataset contains, how it was generated and where it is stored. Every record is synthetic.</p>
      </header>
      {!session ? (
        <p role="alert" className="panel p-4 text-[14px] text-muted">Choose a reviewer to view the dataset.</p>
      ) : ov.error ? <ErrorState error={ov.error} onRetry={() => ov.refetch()} title="Could not load the dataset summary" />
        : !ov.data ? <LoadingBlock lines={6} />
        : (
          <>
            <section className="panel p-4" aria-labelledby="dm-ds">
              <h2 id="dm-ds" className="text-[15px]">Dataset</h2>
              <p className="mt-1 text-[13px] text-muted">
                Version <span className="mono text-text">{ov.data.dataset_version ?? "not recorded"}</span> · seed{" "}
                <span className="mono">{ov.data.seed ?? "?"}</span> · stored in {ov.data.storage} (schema v{ov.data.schema_version})
              </p>
              <dl className="mt-3 grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(9.5rem,1fr))]">
                {COUNTS.map(([k, l]) => <Stat key={k} label={l} value={num(ov.data.counts[k] ?? 0)} />)}
              </dl>
              <p className="mt-3 text-[12.5px] text-subtle">
                Generated time range: {utcToLocal(ov.data.time_range_utc[0])} – {utcToLocal(ov.data.time_range_utc[1])} ·{" "}
                {num(ov.data.attribution.attributed)} attributed and {num(ov.data.attribution.anonymous)} anonymous transactions ·{" "}
                {num(ov.data.counts.scenario_lab_cases ?? 0)} Scenario Lab cases
              </p>
            </section>

            <section className="panel overflow-hidden" aria-labelledby="dm-cat">
              <div className="panel-head"><h2 id="dm-cat" className="text-[15px]">Scenario composition</h2>
                <span className="text-[12px] text-subtle">What the simulator planted — not investigator findings</span></div>
              {!ov.data.scenario_categories.length ? <EmptyState title="No scenario labels recorded" /> : (
                <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Scenario categories">
                  <table className="w-full text-[13.5px]">
                    <thead className="text-left text-[12.5px] text-subtle"><tr>
                      <th scope="col" className="px-4 py-2 font-medium">Category</th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">Players</th>
                      <th scope="col" className="px-4 py-2 font-medium">Meaning</th></tr></thead>
                    <tbody>
                      {ov.data.scenario_categories.map((c) => (
                        <tr key={c.category} className="border-t border-border/60">
                          <td className="px-4 py-1.5 capitalize">{label(c.category)}</td>
                          <td className="mono px-3 py-1.5 text-right">{num(c.players)}</td>
                          <td className="px-4 py-1.5 text-muted">{c.description}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="flex gap-1.5 border-t border-border px-4 py-2 text-[12px] text-subtle">
                <Info aria-hidden className="mt-0.5 size-3.5 shrink-0" />{ov.data.notes.join(" ")}
              </p>
            </section>

            <details className="panel p-4">
              <summary className="cursor-pointer text-[14px] font-semibold">Generation configuration</summary>
              <p className="mt-2 text-[12.5px] text-muted">{ov.data.generator}. Same version, seed and configuration reproduce identical rows.</p>
              <pre className="mono mt-2 max-h-72 overflow-auto rounded-md bg-elevated p-3 text-[12px]">{JSON.stringify(ov.data.generation_config, null, 2)}</pre>
            </details>

            <section className="panel p-4" aria-labelledby="dm-rec">
              <h2 id="dm-rec" className="text-[15px]">Browse records</h2>
              <p className="mt-1 text-[13.5px] text-muted">
                {isSenior ? <>Search, filter and page through players, transactions, retailers, alerts, cases and audit records in{" "}
                  <Link to="/data" className="underline">Data Management</Link>. Identity details stay in Restricted Records.</>
                  : "Record browsing is available to the Senior investigator role. Identity details are never shown here."}
              </p>
            </section>

            {isSenior ? <TechnicalView /> : (
              <p className="flex items-center gap-1.5 text-[12.5px] text-subtle"><LockKeyhole aria-hidden className="size-3.5" />
                Scenario labels and detection evaluation are a senior-only development view.</p>
            )}
          </>
        )}
    </div>
  );
}

function TechnicalView() {
  return (
    <section aria-labelledby="dm-tech" className="space-y-3 rounded-lg border border-dashed border-analysis/60 p-4">
      <div>
        <h2 id="dm-tech" className="flex items-center gap-1.5 text-[15px]"><FlaskConical aria-hidden className="size-4 text-analysis" />
          Technical view: scenario labels & detection evaluation</h2>
        <p className="mt-1 text-[12.5px] text-muted">For development and demo evaluation only. Labels are the simulator's answer key; they are never used by detection or shown on investigation screens.</p>
      </div>
      <Evaluation />
      <Labels />
    </section>
  );
}

function MetricsRow({ name, m }: { name: string; m: EvalMetrics }) {
  const cm = m.confusion_matrix;
  return (
    <tr className="border-t border-border/60">
      <th scope="row" className="px-3 py-1.5 text-left font-medium">{name}</th>
      <td className="mono px-3 py-1.5 text-right">{num(m.n)}</td>
      <td className="mono px-3 py-1.5 text-right">{pct(m.precision)}</td>
      <td className="mono px-3 py-1.5 text-right">{pct(m.recall)}</td>
      <td className="mono px-3 py-1.5 text-right">{m.f1 === null ? "n/a" : m.f1.toFixed(3)}</td>
      <td className="mono px-3 py-1.5 text-right">{pct(m.false_positive_rate)}</td>
      <td className="mono px-3 py-1.5 text-right">{cm.tp} / {cm.fp} / {cm.fn} / {cm.tn}</td>
    </tr>
  );
}

function Evaluation() {
  const q = useQuery({ queryKey: ["methodology", "evaluation"], queryFn: api.methodologyEvaluation });
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} title="Could not load the evaluation" />;
  if (!q.data) return <LoadingBlock lines={3} />;
  const { current_database: db, heldout: h } = q.data;
  return (
    <div className="panel overflow-hidden">
      <div className="panel-head"><h3 className="text-[14px] font-semibold">Detection vs planted labels (population, per player)</h3></div>
      <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Detection metrics">
        <table className="w-full text-[13px]">
          <thead className="text-[12px] text-subtle"><tr>
            {["Set", "Players", "Precision", "Recall", "F1", "False-positive rate", "TP / FP / FN / TN"].map((c, i) =>
              <th key={c} scope="col" className={i ? "px-3 py-2 text-right font-medium" : "px-3 py-2 text-left font-medium"}>{c}</th>)}
          </tr></thead>
          <tbody>
            {db && <MetricsRow name={`This database (development, seed ${db.seed ?? "?"})`} m={db.population} />}
            {h && <MetricsRow name={`Held-out seeds ${h.heldout_seeds.join(", ")} (pooled)`} m={h.heldout_pooled} />}
            {h?.heldout.map((w: EvalWorld) => <MetricsRow key={w.seed} name={`Held-out seed ${w.seed}`} m={w.population} />)}
          </tbody>
        </table>
      </div>
      <p className="border-t border-border px-3 py-2 text-[12px] text-subtle">
        {q.data.caveat} {h ? `${h.method} Evaluated ${utcToLocal(h.evaluated_at_utc)}.` : `Held-out results not computed yet: ${q.data.how_to_refresh}.`}
      </p>
    </div>
  );
}

function Labels() {
  const [f, setF] = useState<{ category?: string; planted?: string; q?: string }>({});
  const [offset, setOffset] = useState(0);
  const params = { ...f, limit: 25, offset };
  const q = useQuery({ queryKey: ["methodology", "labels", params], queryFn: () => api.methodologyLabels(params), placeholderData: keepPreviousData });
  const cats = useQuery({ queryKey: ["methodology", "cats"], queryFn: api.methodology }).data?.scenario_categories ?? [];
  const set = (k: keyof typeof f, v: string) => { setF((x) => ({ ...x, [k]: v || undefined })); setOffset(0); };
  return (
    <div className="panel overflow-hidden">
      <div className="flex flex-wrap items-end gap-2 border-b border-border px-3 py-2.5">
        <h3 className="mr-auto self-center text-[14px] font-semibold">Scenario labels</h3>
        <div className="relative">
          <label htmlFor="lb-q" className="label">Player ID</label>
          <Search aria-hidden className="pointer-events-none absolute bottom-2 left-2 size-3.5 text-subtle" />
          <input id="lb-q" className="field mt-1 h-8 w-[150px] pl-7 text-[13px]" maxLength={20} value={f.q ?? ""}
            onChange={(e) => set("q", e.target.value.replace(/[^A-Za-z0-9-]/g, ""))} />
        </div>
        <div>
          <label htmlFor="lb-cat" className="label">Category</label>
          <select id="lb-cat" className="field mt-1 h-8 py-0 text-[13px]" value={f.category ?? ""} onChange={(e) => set("category", e.target.value)}>
            <option value="">All</option>
            {cats.map((c) => <option key={c.category} value={c.category}>{label(c.category)}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="lb-planted" className="label">Planted pattern</label>
          <select id="lb-planted" className="field mt-1 h-8 py-0 text-[13px]" value={f.planted ?? ""} onChange={(e) => set("planted", e.target.value)}>
            <option value="">All</option><option value="1">Yes</option><option value="0">No</option>
          </select>
        </div>
      </div>
      {q.error ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !q.data ? <LoadingBlock lines={4} />
        : !q.data.rows.length ? <EmptyState title="No labels match" /> : (
          <>
            <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Scenario labels table">
              <table className="w-full text-[13px]">
                <thead className="text-left text-[12px] text-subtle"><tr>
                  {["Player", "Profile", "Scenario", "Category", "Planted", "Monitoring cases"].map((c) =>
                    <th key={c} scope="col" className="px-3 py-2 font-medium">{c}</th>)}
                </tr></thead>
                <tbody>
                  {q.data.rows.map((r) => (
                    <tr key={r.player_id} className="border-t border-border/60">
                      <td className="mono px-3 py-1.5">{r.player_id}</td>
                      <td className="px-3 py-1.5">{label(r.profile)}</td>
                      <td className="px-3 py-1.5 text-muted">{r.scenario ? label(r.scenario) : "None"}</td>
                      <td className="px-3 py-1.5">{label(r.scenario_category)}</td>
                      <td className="px-3 py-1.5">{r.label_suspicious ? "Yes" : "No"}</td>
                      <td className="mono px-3 py-1.5">{r.monitoring_cases}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-end gap-2 border-t border-border px-3 py-2 text-[13px] text-subtle">
              <span>{num(offset + 1)}–{num(Math.min(offset + 25, q.data.total))} of {num(q.data.total)}</span>
              <Button size="sm" variant="ghost" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - 25))}>Previous</Button>
              <Button size="sm" variant="ghost" disabled={offset + 25 >= q.data.total} onClick={() => setOffset((o) => o + 25)}>Next</Button>
            </div>
          </>
        )}
    </div>
  );
}
