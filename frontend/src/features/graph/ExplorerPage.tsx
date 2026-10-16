import { ArrowLeft } from "lucide-react";
import { Link, useParams } from "react-router";
import { ErrorState, LoadingBlock } from "../../components/ui/Primitives";
import { useCase, useEvidence } from "../../hooks/queries";
import { EvidenceDrawer } from "../workspace/EvidenceDrawer";
import { SelectionProvider } from "../workspace/selection";
import { CaseGraph } from "./CaseGraph";

export default function ExplorerPage() {
  const { caseId = "" } = useParams();
  const { data: c, error, isLoading } = useCase(caseId);
  const ev = useEvidence(caseId);
  if (error) return <ErrorState error={error} title={`Could not open ${caseId}`} />;
  if (isLoading || !c) return <LoadingBlock label="Loading case" />;
  return (
    <SelectionProvider items={ev.data}>
      <div className="flex h-[calc(100dvh-3.5rem)] flex-col p-3 sm:p-4">
        <header className="mb-3 flex flex-wrap items-center gap-3">
          <Link to={`/cases/${caseId}`} className="inline-flex items-center gap-1 text-[13px] text-muted no-underline hover:text-text hover:no-underline">
            <ArrowLeft aria-hidden className="size-4" /> Back to workspace
          </Link>
          <h1 className="text-[20px]">Relationship explorer · <span className="mono">{caseId}</span></h1>
          <p className="w-full text-[14px] text-muted">
            Recorded relationships between the case, its alert, indicators, transactions, retailers and locations. Select an entity to see its evidence.
          </p>
        </header>
        <div className="panel min-h-0 flex-1 overflow-hidden">
          <CaseGraph caseId={caseId} height={Math.max(420, (typeof window !== "undefined" ? window.innerHeight : 800) - 330)} />
        </div>
      </div>
      <EvidenceDrawer caseId={caseId} />
    </SelectionProvider>
  );
}
