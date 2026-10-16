import { AlertTriangle, ArrowRight, Calculator, ChevronsUp, Info, Minus } from "lucide-react";
import type { ReactNode } from "react";
import { VerificationBadge } from "../../components/ui/Badges";
import { Disclosure } from "../../components/ui/Disclosure";
import { Tip } from "../../components/ui/Primitives";
import { Term } from "../../components/ui/Term";
import { cx } from "../../lib/cx";
import { money, num } from "../../lib/format";
import type { Claim, Finding, Findings } from "../../types/api";
import { CitationChip, CitationList } from "../workspace/CitationChip";
import { ClaimRow } from "../workspace/ClaimRow";
import { useExplorerOptional } from "../workspace/explorer";
import { useSelection } from "../workspace/selection";
import { CompareBars } from "./CompareBars";

type Refs = Record<string, { type: string; title: string }>;

export type Importance = "high" | "moderate" | "low";

/** Importance comes from how much of the indicator's maximum it reached; it is a review aid, not a verdict. */
export function importanceOf(f: Finding): Importance {
  if (!f.triggered) return "low";
  return f.max_points && f.points / f.max_points >= 0.75 ? "high" : "moderate";
}

const IMPORTANCE: Record<Importance, { label: string; tone: string; icon: ReactNode }> = {
  high: { label: "High importance", tone: "border-critical/60 text-critical", icon: <ChevronsUp aria-hidden className="size-3.5" /> },
  moderate: { label: "Moderate", tone: "border-warning/60 text-warning", icon: <AlertTriangle aria-hidden className="size-3.5" /> },
  low: { label: "Normal range", tone: "border-border-strong text-subtle", icon: <Minus aria-hidden className="size-3.5" /> },
};

/** The numbers that carry the finding, e.g. "0% → 74.2%" and "+74.2 pp". Values come straight from the finding. */
export function keyNumbers(f: Finding): { main: string | null; delta: string | null } {
  const c = f.comparison;
  if (!c || !c.rows.length) return { main: null, delta: null };
  if (c.kind === "previous_vs_recent") {
    const prev = c.rows.find((r) => r.period === "previous");
    const rec = c.rows.find((r) => r.period === "recent");
    const noPrev = c.delta?.state === "no_previous";
    return {
      main: rec ? (prev && !noPrev ? `${prev.display} → ${rec.display}` : rec.display) : null,
      delta: c.delta && !noPrev ? c.delta.text : noPrev ? "No previous records" : null,
    };
  }
  return { main: c.rows.slice(0, 2).map((r) => `${r.label}: ${r.display}`).join(" · "), delta: null };
}

/**
 * One finding in three levels:
 *   1. title, one sentence, key numbers, importance, "View evidence" (always visible)
 *   2. "Details": only what the card does not show — limitations and the report statement
 *   3. "Technical details": metric names, rule ramp, raw and normalized values, evidence & snapshot IDs
 */
export function FindingCard({ f, ctx, claims, refs, actions, onViewEvidence }: {
  f: Finding;
  ctx: Findings;
  claims: Claim[];
  refs: Refs;
  actions?: ReactNode;
  onViewEvidence?: (f: Finding) => void;
}) {
  const sel = useSelection();
  const explorer = useExplorerOptional();
  const headId = `finding-${f.key}-title`;
  const bad = f.verification?.status === "unverified";
  const imp = IMPORTANCE[importanceOf(f)];
  const nums = keyNumbers(f);
  const focused = explorer?.focus?.key === f.key;
  const view = () => (onViewEvidence ? onViewEvidence(f) : explorer ? explorer.showFinding(f) : sel.highlightTransactions(f.supporting_transaction_ids));

  return (
    <article aria-labelledby={headId}
      className={cx("rounded-lg border bg-elevated/30 px-3 py-2.5 transition-colors duration-150",
        bad ? "border-critical/50" : focused ? "border-accent mark-selected" : "border-border")}>
      <div className="flex items-center gap-1.5">
        <span className={cx("inline-flex items-center gap-1 rounded-full border px-1.5 py-px text-[11.5px] font-semibold", imp.tone)}>
          {imp.icon}{imp.label}
        </span>
        {bad && <VerificationBadge status="unverified" />}
        <span className="ml-auto flex items-center">{actions}</span>
      </div>
      <h3 id={headId} className="mt-1 text-[14.5px] font-semibold leading-snug">
        <Tip content={<span>Technical name: <span className="mono">{f.technical_label}</span></span>}>
          <span tabIndex={0}>{f.label}</span>
        </Tip>
      </h3>
      <p className="mt-0.5 text-[13.5px] leading-snug text-muted">{f.headline}</p>

      {(nums.main || nums.delta) && (
        <p className="mt-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          {nums.main && <span className="mono text-[13.5px] font-medium text-text">{nums.main}</span>}
          {nums.delta && <span className="text-[12.5px] text-subtle">{nums.delta}</span>}
        </p>
      )}

      {bad && (
        <ul className="mt-1.5 list-disc pl-5 text-[12.5px] text-critical">
          {f.verification!.failures.map((x, i) => <li key={i}>{x}</li>)}
        </ul>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
        <button type="button" onClick={view} aria-label={`View evidence for ${f.label}`}
          className="inline-flex items-center gap-1 text-[13px] font-medium text-accent hover:text-text">
          View evidence <ArrowRight aria-hidden className="size-3.5" />
          {f.supporting_transaction_ids.length > 0 && <span className="text-[12px] font-normal text-subtle">({f.supporting_transaction_ids.length})</span>}
        </button>
        <Disclosure label="Details" buttonClassName="text-[13px] text-muted" className="contents" regionClassName="basis-full">
          <div>
            <DetailsLevel f={f} claims={claims} refs={refs} />
            <Disclosure label="Technical details" icon={<Calculator aria-hidden className="size-3.5" />}
              buttonClassName="mt-2 text-[12.5px] text-subtle">
              <TechnicalLevel f={f} ctx={ctx} refs={refs} />
            </Disclosure>
          </div>
        </Disclosure>
      </div>
    </article>
  );
}

function DetailsLevel({ f, claims, refs }: { f: Finding; claims: Claim[]; refs: Refs }) {
  // Only what the card does not already show: limitations, the report statement, then method (technical).
  const empty = !f.limitations.length && !claims.length;
  return (
    <div className="mt-2 space-y-2.5 border-t border-border pt-2.5">
      {empty && <p className="text-[12.5px] text-subtle">No limitations or report statement for this indicator. Method below.</p>}
      {f.limitations.length > 0 && (
        <section aria-label="Limitations">
          <h4 className="eyebrow mb-1">Keep in mind</h4>
          <ul className="space-y-1">
            {f.limitations.map((l, i) => (
              <li key={i} className="flex items-start gap-1.5 text-[12.5px] text-muted">
                <Info aria-hidden className="mt-0.5 size-3.5 shrink-0 text-subtle" />
                <span>{l.text} <CitationChip evidenceId={l.evidence_id} originId={`lim-${f.key}-${i}`} refInfo={refs[l.evidence_id]} /></span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {claims.length > 0 && (
        <section aria-label="Report statement">
          <h4 className="eyebrow mb-1">As written in the report</h4>
          <ul className="-mx-2.5 space-y-0.5">
            {claims.map((c, i) => <ClaimRow key={c.claim_id ?? i} claim={c} refs={refs} idBase={`frep-${f.key}-${i}`} />)}
          </ul>
        </section>
      )}
    </div>
  );
}

const MONEY_FIELD = /^(average_amount|baseline_average|max_amount|baseline_p95|window_total|typical_week_total|repeated_amount|deposits|wagers|withdrawals|payouts)$/;

function fmt(v: unknown, field = ""): string {
  if (v === null || v === undefined) return "Not recorded";
  if (typeof v === "number" && MONEY_FIELD.test(field)) return money(v);
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "None";
  return String(v);
}

export function TechnicalLevel({ f, ctx, refs }: { f: Finding; ctx: Findings; refs: Refs }) {
  const t = f.technical;
  const p = ctx.periods;
  const combine = f.key === "playthrough" ? "the two parts multiplied" : "the highest part";
  return (
    <div className="mt-2 space-y-3 rounded-md border border-border bg-bg/50 p-2.5 text-[12.5px]">
      {f.comparison && f.comparison.rows.length > 0 && <CompareBars cmp={f.comparison} emphasis={f.triggered} />}
      <dl className="space-y-1">
        <div><dt className="text-subtle">What was measured</dt><dd className="text-text">{f.explain.measured}</dd></div>
        <div><dt className="text-subtle">How it is scored</dt><dd className="text-text">{f.explain.why}</dd></div>
      </dl>
      <dl className="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-x-3 gap-y-1">
        <dt className="text-subtle">Technical name</dt><dd className="mono">{t.technical_label}</dd>
        <dt className="text-subtle">Rule</dt><dd className="mono break-words">{t.rule ?? "Not recorded"}</dd>
        <dt className="text-subtle"><Term term="Previous activity" /></dt>
        <dd><span className="mono">{p.previous_start} – {p.previous_end}</span> ({p.previous_days} days, {ctx.previous_transaction_count} {ctx.scope})</dd>
        <dt className="text-subtle"><Term term="Recent activity" /></dt>
        <dd><span className="mono">{p.recent_start} – {p.recent_end}</span> ({p.recent_days} days)</dd>
        {t.normalization && (<><dt className="text-subtle">Period lengths</dt><dd>{t.normalization}</dd></>)}
      </dl>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[300px]">
          <caption className="mb-1 text-left text-[11.5px] font-semibold uppercase tracking-wide text-subtle">Recorded values</caption>
          <thead className="text-subtle">
            <tr><th scope="col" className="py-0.5 pr-2 text-left font-medium">Measure</th><th scope="col" className="py-0.5 pr-2 text-left font-medium">Field</th><th scope="col" className="py-0.5 text-right font-medium">Value</th></tr>
          </thead>
          <tbody>
            {t.metrics.map((m) => (
              <tr key={m.field} className="border-t border-border/70">
                <td className="py-0.5 pr-2">{m.label}</td>
                <td className="mono py-0.5 pr-2 text-subtle">{m.field}</td>
                <td className="mono py-0.5 text-right">{fmt(m.value, m.field)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {t.sub_measures.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[340px]">
            <caption className="mb-1 text-left text-[11.5px] font-semibold uppercase tracking-wide text-subtle">How the points were calculated</caption>
            <thead className="text-subtle">
              <tr>
                <th scope="col" className="py-0.5 pr-2 text-left font-medium">Part</th>
                <th scope="col" className="py-0.5 pr-2 text-right font-medium">Raw</th>
                <th scope="col" className="py-0.5 pr-2 text-right font-medium">Starts</th>
                <th scope="col" className="py-0.5 pr-2 text-right font-medium">Full</th>
                <th scope="col" className="py-0.5 text-right font-medium">0–1</th>
              </tr>
            </thead>
            <tbody className="mono">
              {t.sub_measures.map((s) => (
                <tr key={s.name} className="border-t border-border/70">
                  <td className="py-0.5 pr-2 font-sans">{s.name}{s.weight !== 1 && <span className="text-subtle"> × {s.weight}</span>}{s.note && <span className="block text-subtle">{s.note}</span>}</td>
                  <td className="py-0.5 pr-2 text-right">{fmt(s.value)}</td>
                  <td className="py-0.5 pr-2 text-right">{s.starts_at}</td>
                  <td className="py-0.5 pr-2 text-right">{s.full_at}</td>
                  <td className="py-0.5 text-right">{s.normalized}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1 text-muted">
            Normalized share = {combine} = <span className="mono">{t.normalized_share}</span>. Points = {t.max_points} × share ={" "}
            <span className="mono">{num(t.points)}</span>. Counts toward the alert at a share of <span className="mono">{t.trigger_at_share}</span> or more.
            {!f.scored && " Not scored here because there is too little previous activity."}
          </p>
        </div>
      )}

      {t.definitions.length > 0 && (
        <ul aria-label="Definitions" className="list-disc space-y-0.5 pl-4 text-muted">{t.definitions.map((d) => <li key={d}>{d}</li>)}</ul>
      )}

      <dl className="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-x-3 gap-y-1">
        <dt className="text-subtle">Evidence IDs</dt>
        <dd><CitationList ids={f.evidence_ids} idBase={`tev-${f.key}`} refs={refs} inline={f.evidence_ids.length} /></dd>
        <dt className="text-subtle"><Term term="Evidence version" /></dt><dd className="mono">{ctx.snapshot_id ?? "Not recorded"}</dd>
        <dt className="text-subtle">Calculated by</dt><dd className="mono break-all">{t.engine ?? "Not recorded"}</dd>
        <dt className="text-subtle">Points</dt><dd className="mono">{num(f.points)} / {f.max_points}</dd>
        {f.verification && (<><dt className="text-subtle">Wording check</dt>
          <dd>{f.verification.checked} sentences checked with the {f.verification.method.toLowerCase()}: {f.verification.status}.</dd></>)}
      </dl>
    </div>
  );
}
