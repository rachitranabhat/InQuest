import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Play } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { useApp } from "../../app/AppContext";
import { Button } from "../../components/ui/Button";
import { ErrorState, LoadingBlock } from "../../components/ui/Primitives";
import { useToast } from "../../components/ui/Toast";
import { api } from "../../lib/api";

export default function ScenarioLabPage() {
  const { session } = useApp();
  const toast = useToast();
  const nav = useNavigate();
  const qc = useQueryClient();
  const { data, error, isLoading, refetch } = useQuery({ queryKey: ["scenarios"], queryFn: api.scenarios, staleTime: Infinity });
  const [running, setRunning] = useState<string | null>(null);
  const run = useMutation({
    mutationFn: (key: string) => api.runScenario(key),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["cases"] });
      toast.push({ tone: "success", title: `Case ${r.case_id} created`, body: r.rules_fired.join("; ") });
      nav(`/cases/${r.case_id}`);
    },
    onError: (e) => toast.push({ tone: "error", title: "Scenario failed", body: (e as Error).message }),
    onSettled: () => setRunning(null),
  });
  return (
    <div className="mx-auto max-w-[1100px] space-y-4 p-4 sm:p-6">
      <header>
        <h1 className="flex items-center gap-2 text-[22px]"><FlaskConical aria-hidden className="size-5 text-analysis" />Scenario lab</h1>
        <p className="mt-0.5 max-w-3xl text-[14px] text-muted">
          Each run generates a new fictional subject with fresh synthetic records, runs the simulated monitoring rules on it, and opens the
          resulting case. Existing records are never changed.
        </p>
        {!session && <p className="mt-2 text-[13.5px] text-warning">Choose a simulated reviewer in the top bar to run scenarios.</p>}
      </header>
      {error ? <ErrorState error={error} onRetry={() => refetch()} /> : isLoading ? <LoadingBlock lines={6} /> : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {data?.map((s) => (
            <li key={s.key} className="panel flex flex-col p-4">
              <h2 className="text-[16px]">{s.title}</h2>
              <p className="mt-1 flex-1 text-[14px] text-muted">{s.description}</p>
              <Button className="mt-3 self-start" variant="primary" size="sm" disabled={!session || (run.isPending && running !== s.key)}
                loading={running === s.key} icon={<Play aria-hidden className="size-4" />}
                onClick={() => { setRunning(s.key); run.mutate(s.key); }}>
                Run scenario
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
