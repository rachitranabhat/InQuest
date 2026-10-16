import type {
  ActionKey, AiMode, Analytics, AppConfig, Bookmark, CaseAction, CaseDetail, CaseGraph, CaseList, ChatAnswer, ChatMessage,
  Completeness, ConcernType, Investigation, InvestigationSummary, LabelRow, MethodologyEvaluation, MethodologyOverview, DataSummary, DispositionEntry, DispositionHistory, DispositionKey, DataTable, EvidenceItem, GuideAnswer, History, IdentityAccess, Report, ReportSummary, RestrictedList,
  RevealedIdentity, Reviewer, Scenario, Session, Timeline, Findings } from "../types/api";

const SESSION_KEY = "prism.session";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function storedSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function storeSession(s: Session | null) {
  try {
    if (s) sessionStorage.setItem(SESSION_KEY, JSON.stringify(s));
    else sessionStorage.removeItem(SESSION_KEY);
  } catch {
    /* storage unavailable: session lasts for this page only */
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const s = storedSession();
  if (s) headers.set("X-Reviewer-Session", s.token);
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Cannot reach the INQUEST API. Is the backend running on port 8100?");
  }
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") msg = body.detail;
      else if (Array.isArray(body.detail)) msg = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, msg);
  }
  const ct = res.headers.get("Content-Type") ?? "";
  return (ct.includes("application/json") ? res.json() : res.blob()) as Promise<T>;
}

export interface CaseFilters {
  q?: string;
  status?: string;
  priority?: string;
  alert_type?: string;
  channel?: string;
  reviewer?: string;
  date_from?: string;
  date_to?: string;
  completeness?: string;
  sort?: "priority" | "score" | "newest" | "updated";
}

function qs(params: object): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
}

export const api = {
  config: () => request<AppConfig>("/config"),
  reviewers: () => request<Reviewer[]>("/reviewers"),
  startSession: (reviewer_id: string, access_code?: string) =>
    request<Session>("/session", { method: "POST", body: JSON.stringify(access_code ? { reviewer_id, access_code } : { reviewer_id }) }),
  cases: (f: CaseFilters) => request<CaseList>(`/cases${qs(f)}`),
  case: (id: string) => request<CaseDetail>(`/cases/${id}`),
  evidence: (id: string) => request<EvidenceItem[]>(`/cases/${id}/evidence`),
  evidenceItem: (id: string, ev: string) => request<EvidenceItem>(`/cases/${id}/evidence/${ev}`),
  timeline: (id: string) => request<Timeline>(`/cases/${id}/timeline`),
  findings: (id: string) => request<Findings>(`/cases/${id}/findings`),
  graph: (id: string) => request<CaseGraph>(`/cases/${id}/graph`),
  history: (id: string) => request<History>(`/cases/${id}/history`),
  completeness: (id: string) => request<Completeness>(`/cases/${id}/completeness`),
  bookmarks: (id: string) => request<Bookmark[]>(`/cases/${id}/bookmarks`),
  addBookmark: (id: string, body: { evidence_id: string; note?: string; label?: string }) =>
    request<Bookmark>(`/cases/${id}/bookmarks`, { method: "POST", body: JSON.stringify(body) }),
  bookmarkNote: (id: string, bid: string, note: string) =>
    request<Bookmark>(`/cases/${id}/bookmarks/${bid}/note`, { method: "POST", body: JSON.stringify({ note }) }),
  removeBookmark: (id: string, bid: string) => request<Bookmark>(`/cases/${id}/bookmarks/${bid}/remove`, { method: "POST" }),
  audit: (id: string) => request<CaseAction[]>(`/cases/${id}/audit`),
  allAudit: () => request<CaseAction[]>("/audit"),
  reports: (id: string) => request<ReportSummary[]>(`/cases/${id}/reports`),
  report: (rid: string) => request<Report>(`/reports/${rid}`),
  generateReport: (id: string, mode: AiMode) =>
    request<Report>(`/cases/${id}/reports`, { method: "POST", body: JSON.stringify({ mode }) }),
  chat: (id: string) => request<ChatMessage[]>(`/cases/${id}/chat`),
  ask: (id: string, question: string, mode: AiMode) =>
    request<ChatAnswer>(`/cases/${id}/chat`, { method: "POST", body: JSON.stringify({ question, mode }) }),
  act: (id: string, body: { action: ActionKey; notes?: string; idempotency_key: string; expected_status?: string; report_id?: string }) =>
    request<CaseAction>(`/cases/${id}/actions`, { method: "POST", body: JSON.stringify(body) }),
  dispositions: (id: string) => request<DispositionHistory>(`/cases/${id}/dispositions`),
  recordDisposition: (id: string, body: { disposition: DispositionKey; concern_type: ConcernType; justification: string; evidence_ids: string[];
    idempotency_key: string; expected_status?: string; report_id?: string }) =>
    request<DispositionEntry>(`/cases/${id}/dispositions`, { method: "POST", body: JSON.stringify(body) }),
  reviewDisposition: (id: string, did: string, body: { decision: "confirm" | "return"; notes: string; idempotency_key: string; expected_status?: string }) =>
    request<DispositionEntry>(`/cases/${id}/dispositions/${did}/review`, { method: "POST", body: JSON.stringify(body) }),
  methodology: () => request<MethodologyOverview>("/methodology"),
  methodologyLabels: (params: Record<string, string | number | undefined>) =>
    request<{ total: number; limit: number; offset: number; rows: LabelRow[]; notice: string }>(`/methodology/labels${qs(params)}`),
  methodologyEvaluation: () => request<MethodologyEvaluation>("/methodology/evaluation"),
  startInvestigation: (id: string, mode: AiMode) =>
    request<InvestigationSummary>(`/cases/${id}/investigations`, { method: "POST", body: JSON.stringify({ mode }) }),
  investigation: (invId: string) => request<Investigation | InvestigationSummary>(`/investigations/${invId}`),
  investigations: (id: string) => request<InvestigationSummary[]>(`/cases/${id}/investigations`),
  analytics: () => request<Analytics>("/analytics"),
  scenarios: () => request<Scenario[]>("/scenarios"),
  runScenario: (key: string) =>
    request<{ case_id: string; run: number; rules_fired: string[]; alert_score: number }>(`/scenarios/${key}/run`, { method: "POST" }),
  guide: (question: string) => request<GuideAnswer>("/guide", { method: "POST", body: JSON.stringify({ question }) }),
  // senior-only: the server checks the session's role on every call
  dataSummary: () => request<DataSummary>("/admin/summary"),
  dataTable: (table: string, params: Record<string, string | number | undefined>) => request<DataTable>(`/admin/tables/${table}${qs(params)}`),
  restrictedRecords: (q?: string, offset = 0) => request<RestrictedList>(`/restricted/records${qs({ q, offset })}`),
  revealIdentity: (playerId: string, reason: string, caseId?: string) =>
    request<RevealedIdentity>(`/restricted/players/${playerId}/reveal`, { method: "POST", body: JSON.stringify({ reason, case_id: caseId || undefined }) }),
  identityAccessLog: (playerId?: string) => request<IdentityAccess[]>(`/restricted/access-log${qs({ player_id: playerId })}`),
  pdfUrl: (rid: string) => `/api/reports/${rid}/pdf`,
  downloadPdf: async (rid: string): Promise<{ blob: Blob; fileName: string; sha256: string | null }> => {
    const s = storedSession();
    const res = await fetch(`/api/reports/${rid}/pdf`, { headers: s ? { "X-Reviewer-Session": s.token } : {} });
    if (!res.ok) throw new ApiError(res.status, "PDF export failed");
    const cd = res.headers.get("Content-Disposition") ?? "";
    const m = /filename="([^"]+)"/.exec(cd);
    return { blob: await res.blob(), fileName: m ? m[1] : `${rid}.pdf`, sha256: res.headers.get("X-Content-SHA256") };
  },
};

export function newIdempotencyKey(): string {
  const r = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
  return `ui-${r}`.replace(/[^A-Za-z0-9_\-:.]/g, "");
}
