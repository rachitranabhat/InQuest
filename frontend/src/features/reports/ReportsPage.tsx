import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { StatusBadge } from "../../components/ui/Badges";
import { EmptyState, ErrorState, LoadingBlock } from "../../components/ui/Primitives";
import { api } from "../../lib/api";
import { utcToLocal } from "../../lib/format";

const LABEL: Record<string, string> = {
  report_generated: "Report generated",
  start_review: "Start review",
  add_note: "Add note",
  request_info: "Request more information",
  close_no_action: "Close — no further action",
  escalate: "Escalate",
  reopen: "Reopen",
};

export default function ReportsPage() {
  const { data, error, isLoading, refetch } = useQuery({ queryKey: ["audit-all"], queryFn: api.allAudit });
  return (
    <div className="mx-auto max-w-[1300px] space-y-4 p-4 sm:p-6">
      <header>
        <h1 className="text-[22px]">Reports & review history</h1>
        <p className="mt-0.5 text-[14px] text-muted">
          Append-only audit trail. Every reviewer action records the report version and evidence hash on screen at the time.
        </p>
      </header>
      <section className="panel overflow-hidden" aria-labelledby="audit-title">
        <div className="panel-head"><h2 id="audit-title" className="text-[15px]">Recent activity</h2></div>
        {error ? <ErrorState error={error} onRetry={() => refetch()} /> : isLoading ? <LoadingBlock lines={8} /> : !data?.length ? (
          <EmptyState title="No activity yet">Open a case, generate a report and record a decision.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[960px] text-left text-[14px]">
              <caption className="sr-only">Audit trail of report generation and reviewer actions</caption>
              <thead className="border-b border-border text-[12.5px] text-subtle">
                <tr>{["Time (Toronto)", "Case", "Action", "Status change", "By", "Report", "Evidence hash", "Notes"].map((h) => (
                  <th key={h} scope="col" className="px-3 py-2.5 font-medium">{h}</th>))}</tr>
              </thead>
              <tbody>
                {data.map((a) => (
                  <tr key={a.action_id} className="row-interactive border-b border-border/70 align-top last:border-0">
                    <td className="mono whitespace-nowrap px-3 py-2 text-[13px] text-muted">{utcToLocal(a.created_at_utc)}</td>
                    <td className="px-3 py-2"><Link className="mono" to={`/cases/${a.case_id}`}>{a.case_id}</Link></td>
                    <td className="px-3 py-2">{LABEL[a.action] ?? a.action}</td>
                    <td className="px-3 py-2">
                      {a.from_status === a.to_status ? <StatusBadge status={a.to_status} /> : (
                        <span className="flex flex-wrap items-center gap-1"><StatusBadge status={a.from_status} /><span aria-label="to">→</span><StatusBadge status={a.to_status} /></span>
                      )}
                    </td>
                    <td className="px-3 py-2">{a.reviewer_name}{a.session_kind === "simulated" && <span className="block text-[12px] text-warning">simulated session</span>}</td>
                    <td className="px-3 py-2">{a.report_version ? (
                      <a href={api.pdfUrl(a.report_id as string)} className="mono text-[13px]" download>v{a.report_version} PDF</a>
                    ) : "No report"}</td>
                    <td className="mono px-3 py-2 text-[12.5px] text-subtle" title={a.evidence_hash ?? ""}>{a.evidence_hash ? `${a.evidence_hash.slice(0, 12)}…` : "No report"}</td>
                    <td className="max-w-[320px] px-3 py-2 text-[13.5px] text-muted">{a.notes ?? "No notes"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
