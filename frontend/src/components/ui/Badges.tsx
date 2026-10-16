import { AlertOctagon, AlertTriangle, ArrowDown, CheckCircle2, CircleDashed, Clock, FileSearch, HelpCircle, Send, ShieldAlert, ShieldCheck, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { cx } from "../../lib/cx";
import type { CaseStatus, Priority } from "../../types/api";

function Pill({ tone, icon, children, title }: { tone: string; icon?: ReactNode; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[12.5px] font-medium", tone)}
    >
      {icon}
      {children}
    </span>
  );
}

const ICON = "size-3.5 shrink-0";

export function PriorityBadge({ priority, short = false }: { priority: Priority | string; short?: boolean }) {
  const level = priority.split(" ")[0];
  const map: Record<string, [string, ReactNode]> = {
    Critical: ["border-critical/60 bg-critical/10 text-critical", <AlertOctagon aria-hidden className={ICON} />],
    High: ["border-warning/60 bg-warning/10 text-warning", <AlertTriangle aria-hidden className={ICON} />],
    Medium: ["border-analysis/60 bg-analysis/10 text-analysis", <CircleDashed aria-hidden className={ICON} />],
    Lower: ["border-border-strong bg-elevated text-muted", <ArrowDown aria-hidden className={ICON} />],
  };
  const [tone, icon] = map[level] ?? map.Lower;
  return (
    <Pill tone={tone} icon={icon} title={priority}>
      {short ? level : priority}
    </Pill>
  );
}

export function StatusBadge({ status }: { status: CaseStatus | string }) {
  const map: Record<string, [string, ReactNode]> = {
    New: ["border-border-strong text-text", <CircleDashed aria-hidden className={ICON} />],
    "Analysis Ready": ["border-analysis/60 text-analysis", <FileSearch aria-hidden className={ICON} />],
    "Under Review": ["border-accent/60 text-accent", <Clock aria-hidden className={ICON} />],
    "Information Requested": ["border-warning/60 text-warning", <Send aria-hidden className={ICON} />],
    "Closed — No Further Action": ["border-success/60 text-success", <CheckCircle2 aria-hidden className={ICON} />],
    Escalated: ["border-critical/60 text-critical", <AlertOctagon aria-hidden className={ICON} />],
    "Closed — Suspicion Substantiated": ["border-critical/60 text-critical", <ShieldAlert aria-hidden className={ICON} />],
  };
  const [tone, icon] = map[status] ?? map.New;
  return <Pill tone={cx(tone, "bg-transparent")} icon={icon}>{status}</Pill>;
}

export function VerificationBadge({ status, compact = false }: { status: "verified" | "unverified"; compact?: boolean }) {
  return status === "verified" ? (
    <Pill tone="border-success/50 text-success bg-success/5" icon={<ShieldCheck aria-hidden className={ICON} />}>
      {compact ? <span className="sr-only">Verified</span> : "Verified"}
    </Pill>
  ) : (
    <Pill tone="border-critical/60 text-critical bg-critical/10" icon={<XCircle aria-hidden className={ICON} />}>
      Unverified
    </Pill>
  );
}

export function CompletenessBadge({ value, short = false }: { value: string; short?: boolean }) {
  const tone = value === "Complete" ? "border-success/50 text-success" : value === "Partial" ? "border-warning/60 text-warning" : "border-critical/60 text-critical";
  const icon = value === "Complete" ? <CheckCircle2 aria-hidden className={ICON} /> : <HelpCircle aria-hidden className={ICON} />;
  return (
    <Pill tone={tone} icon={icon} title={`Evidence completeness: ${value}`}>
      {value}{short ? <span className="sr-only"> evidence</span> : " evidence"}
    </Pill>
  );
}

/** Score band in words plus the prototype score; the band never relies on colour alone. */
export function ScoreBand({ band, score }: { band: string; score: number }) {
  const tone: Record<string, string> = { Critical: "bg-critical", High: "bg-warning", Medium: "bg-analysis", Low: "bg-subtle" };
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap" title="Rule score (0–100), not a fraud probability">
      <span aria-hidden className={cx("size-2 rounded-full", tone[band] ?? "bg-subtle")} />
      <span className="text-text">{band}</span>
      <span className="mono text-[12.5px] text-subtle">{Number.isInteger(score) ? score : score.toFixed(1)}</span>
    </span>
  );
}

export function ModeBadge({ mode }: { mode: string }) {
  const label = mode === "llm" ? "LLM · validated" : mode === "llm_fallback" ? "Deterministic fallback" : "Deterministic";
  const tone = mode === "llm" ? "border-analysis/60 text-analysis" : mode === "llm_fallback" ? "border-warning/60 text-warning" : "border-border-strong text-muted";
  return <Pill tone={tone}>{label}</Pill>;
}
