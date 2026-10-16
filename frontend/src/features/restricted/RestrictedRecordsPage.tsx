import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { EyeOff, KeyRound, Search } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { useApp } from "../../app/AppContext";
import { Button } from "../../components/ui/Button";
import { EmptyState, ErrorState, LoadingBlock, Modal } from "../../components/ui/Primitives";
import { api } from "../../lib/api";
import { utcToLocal } from "../../lib/format";
import type { RestrictedRecord, RevealedIdentity } from "../../types/api";
import { DemoAuthNotice, SeniorGate } from "./SeniorGate";

const MIN_REASON = 15;
const PAGE = 50;

export default function RestrictedRecordsPage() {
  const { session } = useApp();
  return (
    <SeniorGate title="Restricted Records">
      {/* keyed by reviewer: switching reviewer drops any revealed details */}
      <Restricted key={session?.reviewer.reviewer_id} />
    </SeniorGate>
  );
}

function Restricted() {
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [revealed, setRevealed] = useState<Record<string, RevealedIdentity>>({});   // memory only, never cached
  const [asking, setAsking] = useState<RestrictedRecord | null>(null);
  const list = useQuery({ queryKey: ["restricted", "records", q, offset], queryFn: () => api.restrictedRecords(q || undefined, offset),
    placeholderData: keepPreviousData, staleTime: 0, gcTime: 0 });
  const log = useQuery({ queryKey: ["restricted", "log"], queryFn: () => api.identityAccessLog(), staleTime: 0, gcTime: 0 });

  return (
    <div className="mx-auto max-w-[1300px] space-y-4 p-4 sm:p-6">
      <header className="space-y-2">
        <h1 className="text-[22px]">Restricted Records</h1>
        <p className="text-[14px] text-muted">
          Fictional identity records linked to synthetic player IDs. Details stay hidden until you give a reason; every reveal is
          recorded with your reviewer ID, the player and case, the time and the reason. These details are never sent to the copilot
          or shown in case pages.
        </p>
        <DemoAuthNotice />
      </header>

      <section className="panel overflow-hidden" aria-labelledby="rr-title">
        <div className="panel-head flex-wrap">
          <h2 id="rr-title" className="text-[15px]">Identity records {list.data && <span className="font-normal text-subtle">· {list.data.total}</span>}</h2>
          <form role="search" className="relative" onSubmit={(e) => e.preventDefault()}>
            <label htmlFor="rr-search" className="sr-only">Search by player or case ID</label>
            <Search aria-hidden className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-subtle" />
            <input id="rr-search" className="field h-8 w-[220px] pl-7 text-[13px]" placeholder="Player or case ID" value={q} maxLength={40}
              onChange={(e) => { setQ(e.target.value.replace(/[^A-Za-z0-9-]/g, "")); setOffset(0); }} />
          </form>
        </div>
        {list.error ? <ErrorState error={list.error} onRetry={() => list.refetch()} title="Could not load restricted records" />
          : list.isLoading || !list.data ? <LoadingBlock lines={6} />
          : !list.data.records.length ? <EmptyState title="No identity records match" />
          : (
            <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Identity records table">
              <table className="w-full text-[13.5px]">
                <thead className="text-left text-[12.5px] text-subtle">
                  <tr>
                    <th scope="col" className="px-4 py-2 font-medium">Player</th>
                    <th scope="col" className="px-3 py-2 font-medium">Linked cases</th>
                    <th scope="col" className="px-3 py-2 font-medium">Record from</th>
                    <th scope="col" className="px-3 py-2 font-medium">Identity details</th>
                    <th scope="col" className="px-3 py-2 font-medium">Accesses</th>
                  </tr>
                </thead>
                <tbody>
                  {list.data.records.map((r) => {
                    const id = revealed[r.player_id];
                    return (
                      <tr key={r.player_id} className="border-t border-border/60 align-top">
                        <td className="mono px-4 py-2">{r.player_id}</td>
                        <td className="px-3 py-2">
                          {r.case_ids.length ? r.case_ids.map((c) => <Link key={c} to={`/cases/${c}`} className="mono mr-2">{c}</Link>)
                            : <span className="text-subtle">None</span>}
                        </td>
                        <td className="px-3 py-2 text-muted">{r.record_source}</td>
                        <td className="px-3 py-2">
                          {id ? (
                            <div className="space-y-0.5" aria-live="polite">
                              <p className="font-medium">{id.full_name} <span className="rounded border border-warning/50 px-1 text-[11px] font-normal text-warning">Fictional</span></p>
                              <p className="mono text-[12.5px] text-muted">{id.email} · {id.phone}</p>
                              <p className="text-[12px] text-subtle">Access recorded as <span className="mono">{id.access_id}</span>.{" "}
                                <button type="button" className="text-accent hover:text-text" onClick={() => setRevealed(({ [r.player_id]: _, ...rest }) => rest)}>
                                  <EyeOff aria-hidden className="mr-0.5 inline size-3.5" />Hide
                                </button>
                              </p>
                            </div>
                          ) : (
                            <Button size="sm" variant="secondary" icon={<KeyRound aria-hidden className="size-3.5" />} onClick={() => setAsking(r)}>
                              Reveal<span className="sr-only"> identity for {r.player_id}</span>
                            </Button>
                          )}
                        </td>
                        <td className="px-3 py-2 text-muted">{r.access_count ? `${r.access_count} · last ${utcToLocal(r.last_access_utc)}` : "None"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div className="flex items-center justify-end gap-2 border-t border-border px-4 py-2 text-[13px] text-subtle">
                <span>{offset + 1}–{Math.min(offset + PAGE, list.data.total)} of {list.data.total}</span>
                <Button size="sm" variant="ghost" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - PAGE))}>Previous</Button>
                <Button size="sm" variant="ghost" disabled={offset + PAGE >= list.data.total} onClick={() => setOffset((o) => o + PAGE)}>Next</Button>
              </div>
            </div>
          )}
      </section>

      <section className="panel overflow-hidden" aria-labelledby="rr-log">
        <div className="panel-head"><h2 id="rr-log" className="text-[15px]">Identity access log</h2>
          <span className="text-[12.5px] text-subtle">Append-only</span></div>
        {log.error ? <ErrorState error={log.error} onRetry={() => log.refetch()} />
          : log.isLoading || !log.data ? <LoadingBlock lines={3} />
          : !log.data.length ? <p className="px-4 py-3 text-[13.5px] text-muted">No identity details have been revealed yet.</p>
          : (
            <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Access log table">
              <table className="w-full text-[13.5px]">
                <thead className="text-left text-[12.5px] text-subtle">
                  <tr>{["When", "Reviewer", "Player", "Case", "Reason", "Record"].map((h) => <th key={h} scope="col" className="px-4 py-2 font-medium">{h}</th>)}</tr>
                </thead>
                <tbody>
                  {log.data.map((a) => (
                    <tr key={a.access_id} className="border-t border-border/60 align-top">
                      <td className="whitespace-nowrap px-4 py-2 text-muted">{utcToLocal(a.created_at_utc)}</td>
                      <td className="px-4 py-2">{a.reviewer_name} <span className="text-subtle">· {a.reviewer_role}</span></td>
                      <td className="mono px-4 py-2">{a.player_id}</td>
                      <td className="mono px-4 py-2">{a.case_id ?? <span className="font-sans text-subtle">Not given</span>}</td>
                      <td className="px-4 py-2">{a.reason}</td>
                      <td className="mono px-4 py-2 text-subtle">{a.access_id}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </section>

      {asking && (
        <RevealDialog record={asking} onClose={() => setAsking(null)}
          onRevealed={(r) => { setRevealed((m) => ({ ...m, [r.player_id]: r })); setAsking(null); }} />
      )}
    </div>
  );
}

function RevealDialog({ record, onClose, onRevealed }: { record: RestrictedRecord; onClose: () => void; onRevealed: (r: RevealedIdentity) => void }) {
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const [caseId, setCaseId] = useState(record.case_ids[0] ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const ok = reason.trim().length >= MIN_REASON;
  const submit = async () => {
    if (!ok || busy) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await api.revealIdentity(record.player_id, reason.trim(), caseId || undefined);
      qc.invalidateQueries({ queryKey: ["restricted"] });
      onRevealed(r);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Reveal identity for ${record.player_id}`}
      description="Your reviewer ID, the player, the case, the time and this reason are written to the append-only access log."
      footer={<>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!ok} onClick={submit}>Reveal and record access</Button>
      </>}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        {record.case_ids.length > 0 && (
          <div>
            <label htmlFor="rv-case" className="label">Case</label>
            <select id="rv-case" className="field mt-1" value={caseId} onChange={(e) => setCaseId(e.target.value)}>
              {record.case_ids.map((c) => <option key={c} value={c}>{c}</option>)}
              <option value="">No specific case</option>
            </select>
          </div>
        )}
        <div>
          <label htmlFor="rv-reason" className="label">Reason for access (required)</label>
          <textarea id="rv-reason" rows={3} maxLength={500} className="field mt-1" value={reason} onChange={(e) => setReason(e.target.value)}
            aria-describedby="rv-help" placeholder="e.g. Confirming the account holder before escalating the case" />
          <p id="rv-help" className="mt-1 text-[12.5px] text-subtle">
            At least {MIN_REASON} characters{reason.trim().length > 0 && reason.trim().length < MIN_REASON ? ` (${MIN_REASON - reason.trim().length} more)` : ""}.
          </p>
        </div>
        {err && <p role="alert" className="text-[13px] text-critical">{err}</p>}
      </form>
    </Modal>
  );
}
