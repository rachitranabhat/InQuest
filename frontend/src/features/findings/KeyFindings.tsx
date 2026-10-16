import { CircleCheck, ShieldCheck, XCircle } from "lucide-react";
import { Disclosure } from "../../components/ui/Disclosure";
import { ErrorState, LoadingBlock } from "../../components/ui/Primitives";
import { useFindings } from "../../hooks/queries";
import type { Claim, Findings } from "../../types/api";
import { BookmarkButton } from "../workspace/BookmarkButton";
import { FindingCard, importanceOf } from "./FindingCard";

type Refs = Record<string, { type: string; title: string }>;
const ORDER = { high: 0, moderate: 1, low: 2 } as const;
/** Display grouping only; names, scores, evidence and detection are unchanged. */
const GROUPS: { title: string; keys: string[] }[] = [
  { title: "Spending behaviour", keys: ["value", "historical"] },
  { title: "Movement of funds", keys: ["playthrough"] },
  { title: "Transaction patterns", keys: ["frequency", "timing", "pattern", "location"] },
];
const groupOf = (key: string) => GROUPS.find((g) => g.keys.includes(key))?.title ?? "Transaction patterns";

/** Left panel of the workspace: scannable findings, most important first. */
export function FindingsPanel({ caseId, claims, refs }: { caseId: string; claims: Claim[]; refs: Refs }) {
  const { data, error, isLoading, refetch } = useFindings(caseId);
  return (
    <section aria-labelledby="findings-title" className="panel flex min-h-0 flex-col">
      <div className="panel-head py-2.5">
        <h2 id="findings-title" className="text-[14.5px]">Findings</h2>
        {data && <VerifiedSummary data={data} />}
      </div>
      <div className="relative min-h-0 flex-1 overflow-y-auto p-2.5">
        {error ? <ErrorState error={error} onRetry={() => refetch()} title="Could not load findings" />
          : isLoading || !data ? <LoadingBlock label="Loading findings" lines={6} />
          : <KeyFindings data={data} claims={claims} refs={refs} caseId={caseId} />}
      </div>
    </section>
  );
}

function VerifiedSummary({ data }: { data: Findings }) {
  const bad = data.findings.filter((f) => f.verification?.status === "unverified").length;
  return bad ? (
    <span className="inline-flex items-center gap-1 text-[12px] text-critical"><XCircle aria-hidden className="size-3.5" />{bad} unverified</span>
  ) : (
    <span className="inline-flex items-center gap-1 text-[12px] text-success"><ShieldCheck aria-hidden className="size-3.5" />Wording verified</span>
  );
}

export function KeyFindings({ data, claims, refs, caseId }: { data: Findings; claims: Claim[]; refs: Refs; caseId?: string }) {
  const byFinding = (evId: string) => claims.filter((c) => c.evidence_ids.includes(evId));
  const counted = data.findings.filter((f) => f.triggered).sort((a, b) => ORDER[importanceOf(a)] - ORDER[importanceOf(b)] || b.points - a.points);
  const normal = data.findings.filter((f) => !f.triggered);
  const bookmark = (evId: string, label: string) => caseId ? <BookmarkButton caseId={caseId} evidenceId={evId} label={`finding: ${label}`} /> : null;
  return (
    <div className="space-y-2">
      <p role="note" className="rounded-md border border-warning/50 bg-warning/5 px-2.5 py-1.5 text-[12.5px] text-text">
        Flagged patterns require review; they do not establish wrongdoing.
        <span className="block text-subtle">
          {counted.length === 0 ? "No indicator reached the level that counts toward an alert."
            : `${counted.length} of ${data.findings.length} indicators stood out. Related indicators often describe the same activity, so they are not independent proof.`}
        </span>
      </p>
      {GROUPS.map((g) => {
        const items = counted.filter((f) => groupOf(f.key) === g.title);
        return items.length ? (
          <section key={g.title} aria-label={g.title} className="space-y-2">
            <h3 className="eyebrow px-0.5 pt-1">{g.title}</h3>
            {items.map((f) => (
              <FindingCard key={f.key} f={f} ctx={data} claims={byFinding(f.evidence_id)} refs={refs} actions={bookmark(f.evidence_id, f.label)} />
            ))}
          </section>
        ) : null;
      })}
      {normal.length > 0 && (
        <Disclosure label="Also checked: within the normal range" count={normal.length} className="pt-1"
          icon={<CircleCheck aria-hidden className="size-4 text-success" />} buttonClassName="text-[13px] text-muted">
          <div className="mt-2 space-y-2">
            {normal.map((f) => (
              <FindingCard key={f.key} f={f} ctx={data} claims={byFinding(f.evidence_id)} refs={refs} actions={bookmark(f.evidence_id, f.label)} />
            ))}
          </div>
        </Disclosure>
      )}
    </div>
  );
}
