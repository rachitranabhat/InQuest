import { VerificationBadge } from "../../components/ui/Badges";
import { cx } from "../../lib/cx";
import type { Claim } from "../../types/api";
import { CitationList } from "./CitationChip";

const KIND_LABEL: Record<Claim["kind"], string | null> = {
  fact: null,
  interpretation: "Interpretation",
  recommendation: "Suggested check",
  limitation: "Limitation",
  status: "System status",
};

export function ClaimRow({ claim, refs, idBase }: { claim: Claim; refs: Record<string, { type: string; title: string }>; idBase: string }) {
  const kind = KIND_LABEL[claim.kind];
  const bad = claim.verification_status === "unverified";
  return (
    <li className={cx("rounded-md px-2.5 py-1.5 text-[14px] leading-relaxed", bad ? "border border-critical/50 bg-critical/5" : "hover:bg-elevated/40")}>
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          {kind && <span className="mr-1.5 text-[11.5px] font-semibold uppercase tracking-wide text-analysis">{kind}</span>}
          <span className={cx(bad && "text-muted line-through decoration-critical/60")}>{claim.text}</span>{" "}
          <CitationList ids={claim.evidence_ids} idBase={idBase} refs={refs} />
        </div>
        {claim.kind !== "status" && <VerificationBadge status={claim.verification_status} compact={!bad} />}
      </div>
      {bad && (
        <ul className="mt-1.5 list-disc pl-5 text-[13px] text-critical">
          {claim.failures.map((f, i) => <li key={i}>{f}</li>)}
        </ul>
      )}
    </li>
  );
}
