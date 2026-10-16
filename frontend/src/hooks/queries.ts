import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, newIdempotencyKey, type CaseFilters } from "../lib/api";
import type { ActionKey, AiMode } from "../types/api";

export const keys = {
  cases: (f: CaseFilters) => ["cases", f] as const,
  case: (id: string) => ["case", id] as const,
  evidence: (id: string) => ["evidence", id] as const,
  timeline: (id: string) => ["timeline", id] as const,
  graph: (id: string) => ["graph", id] as const,
  report: (rid: string) => ["report", rid] as const,
  chat: (id: string) => ["chat", id] as const,
  audit: (id: string) => ["audit", id] as const,
};

export const useCases = (f: CaseFilters) =>
  useQuery({ queryKey: keys.cases(f), queryFn: () => api.cases(f), placeholderData: (prev) => prev });
export const useCase = (id: string) => useQuery({ queryKey: keys.case(id), queryFn: () => api.case(id) });
export const useEvidence = (id: string) => useQuery({ queryKey: keys.evidence(id), queryFn: () => api.evidence(id) });
export const useFindings = (id: string) =>
  useQuery({ queryKey: ["findings", id] as const, queryFn: () => api.findings(id), staleTime: Infinity });
export const useTimeline = (id: string) => useQuery({ queryKey: keys.timeline(id), queryFn: () => api.timeline(id) });
export const useGraph = (id: string) => useQuery({ queryKey: keys.graph(id), queryFn: () => api.graph(id) });
export const useAudit = (id: string) => useQuery({ queryKey: keys.audit(id), queryFn: () => api.audit(id) });
export const useChat = (id: string) => useQuery({ queryKey: keys.chat(id), queryFn: () => api.chat(id) });
export const useHistory = (id: string) => useQuery({ queryKey: ["history", id] as const, queryFn: () => api.history(id), staleTime: Infinity });
export const useCompleteness = (id: string) =>
  useQuery({ queryKey: ["completeness", id] as const, queryFn: () => api.completeness(id), staleTime: Infinity });
export const useBookmarks = (id: string) => useQuery({ queryKey: ["bookmarks", id] as const, queryFn: () => api.bookmarks(id) });

export function useBookmarkMutations(caseId: string) {
  const qc = useQueryClient();
  const done = () => qc.invalidateQueries({ queryKey: ["bookmarks", caseId] });
  return {
    add: useMutation({ mutationFn: (b: { evidence_id: string; note?: string; label?: string }) => api.addBookmark(caseId, b), onSuccess: done }),
    note: useMutation({ mutationFn: (v: { id: string; note: string }) => api.bookmarkNote(caseId, v.id, v.note), onSuccess: done }),
    remove: useMutation({ mutationFn: (id: string) => api.removeBookmark(caseId, id), onSuccess: done }),
  };
}

export const useReport = (rid: string | null | undefined) =>
  useQuery({ queryKey: keys.report(rid ?? "none"), queryFn: () => api.report(rid as string), enabled: !!rid });

export function useGenerateReport(caseId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (mode: AiMode) => api.generateReport(caseId, mode),
    onSuccess: (rep) => {
      qc.setQueryData(keys.report(rep.report_id), rep);
      qc.invalidateQueries({ queryKey: keys.case(caseId) });
      qc.invalidateQueries({ queryKey: keys.audit(caseId) });
      qc.invalidateQueries({ queryKey: ["dispositions", caseId] });
      qc.invalidateQueries({ queryKey: ["cases"] });
    },
  });
}

export function useAsk(caseId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ question, mode }: { question: string; mode: AiMode }) => api.ask(caseId, question, mode),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.chat(caseId) });
      qc.invalidateQueries({ queryKey: keys.evidence(caseId) }); // copilot queries register new evidence
    },
  });
}

export const useDispositions = (id: string) => useQuery({ queryKey: ["dispositions", id] as const, queryFn: () => api.dispositions(id) });

/** Record or review a final investigation decision; refreshes the case, its audit trail and the queue. */
export function useDispositionMutations(caseId: string) {
  const qc = useQueryClient();
  const done = () => {
    for (const k of [keys.case(caseId), keys.audit(caseId), ["dispositions", caseId], ["cases"], ["report"]]) qc.invalidateQueries({ queryKey: k });
  };
  return {
    record: useMutation({ mutationFn: (b: Parameters<typeof api.recordDisposition>[1]) => api.recordDisposition(caseId, b), onSuccess: done }),
    review: useMutation({ mutationFn: (v: { id: string } & Parameters<typeof api.reviewDisposition>[2]) =>
      api.reviewDisposition(caseId, v.id, { decision: v.decision, notes: v.notes, idempotency_key: v.idempotency_key, expected_status: v.expected_status }),
      onSuccess: done }),
  };
}

export function useCaseAction(caseId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { action: ActionKey; notes?: string; expected_status?: string; report_id?: string; idempotency_key?: string }) =>
      api.act(caseId, { ...v, idempotency_key: v.idempotency_key ?? newIdempotencyKey() }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.case(caseId) });
      qc.invalidateQueries({ queryKey: keys.audit(caseId) });
      qc.invalidateQueries({ queryKey: ["dispositions", caseId] });
      qc.invalidateQueries({ queryKey: ["cases"] });
      qc.invalidateQueries({ queryKey: ["report"] });
    },
  });
}
