// Mirrors backend/schemas/api.py and the service payloads.

export type CaseStatus =
  | "New"
  | "Analysis Ready"
  | "Under Review"
  | "Information Requested"
  | "Closed — No Further Action"
  | "Escalated"
  | "Closed — Suspicion Substantiated";

export type Priority =
  | "Critical review priority"
  | "High review priority"
  | "Medium review priority"
  | "Lower review priority";

export type ActionKey = "start_review" | "add_note" | "request_info" | "close_no_action" | "escalate" | "reopen";
export type AiMode = "deterministic" | "llm";

export interface Branding {
  product_name: string;
  alt_name?: string;
  tagline: string;
  long_description?: string;
  logo_text?: string;
  organization_label?: string;
  display_timezone: string;
  currency?: string;
  locale?: string;
  disclaimer: string;
  report_disclaimer?: string;
}

export interface AppConfig {
  branding: Branding;
  llm_available: boolean;
  llm_model: string | null;
  statuses: CaseStatus[];
  open_statuses: CaseStatus[];
  action_labels: Record<ActionKey, string>;
  notes_required: ActionKey[];
  min_note_chars: number;
  disclaimer: string;
  project_notice: string;
  suggested_questions: string[];
  auth: string;
  access_code_required?: boolean;
  terms?: Record<string, { technical: string; definition: string }>;
  factor_labels?: Record<string, string>;
  senior_roles?: string[];
  guide_suggested_questions?: string[];
  dispositions?: DispositionOptions;
}

export interface Reviewer {
  reviewer_id: string;
  display_name: string;
  role: string;
  kind?: string;
}

export interface Session {
  token: string;
  kind: "simulated";
  reviewer: Reviewer;
  notice: string;
}

export interface CaseListItem {
  case_id: string;
  alert_id: string;
  alert_type: string;
  channel: "lottery_terminal" | "online_account";
  subject_type: "player" | "account";
  subject_id: string;
  player_id: string | null;
  status: CaseStatus;
  priority: Priority;
  alert_score: number;
  score_band: string;
  evidence_completeness: "Complete" | "Partial" | "Limited";
  urgency: string;
  primary_reason: string;
  triggered_count: number;
  created_at_utc: string;
  updated_at_utc: string;
  assigned_reviewer_id: string | null;
  assigned_reviewer: string | null;
  curated_key: string | null;
  scenario_title: string | null;
  origin: "monitoring" | "scenario_lab";
}

export interface CaseList {
  cases: CaseListItem[];
  count: number;
  facets: { statuses: CaseStatus[]; priorities: Priority[]; alert_types: string[]; reviewers: { reviewer_id: string; display_name: string }[] };
  totals: { all: number; open: number };
}

export interface Factor {
  key: string;
  label: string;
  points: number;
  max_points: number;
  share: number;
  triggered: boolean;
  measurement: string;
  rule: string;
  transaction_ids: string[];
}

export interface ReportSummary {
  report_id: string;
  case_id: string;
  version: number;
  mode: string;
  mode_label: string;
  status: "draft" | "locked";
  validation: { claims: number; verified: number; unverified: number };
  notes?: string | null;
  created_at_utc: string;
  locked_at_utc?: string | null;
  evidence_hash?: string;
}

export interface CaseDetail extends Omit<CaseListItem, "assigned_reviewer"> {
  assigned_reviewer: Reviewer | null;
  alert: {
    alert_id: string;
    source: string;
    alert_type: string;
    rules_fired: string[];
    triggered_at_utc: string;
    indicators: string[];
    transaction_ids: string[];
  };
  factors: Factor[];
  priority_rationale: string[];
  window_start_utc: string;
  window_end_utc: string;
  snapshot: { snapshot_id: string; evidence_hash: string; item_count: number; created_at_utc: string } | null;
  evidence_counts: Record<string, number>;
  allowed_actions: ActionKey[];
  latest_report: ReportSummary | null;
  reports: ReportSummary[];
  subject_label: string;
  anomaly_score: number | null;
}

export interface EvidenceItem {
  evidence_id: string;
  case_id: string;
  snapshot_id: string | null;
  type: string;
  title: string;
  summary: string;
  source_ids: string[];
  entities: string[];
  computed: Record<string, unknown>;
  provenance: Record<string, unknown>;
  created_at_utc?: string;
}

export interface Claim {
  claim_id?: string;
  section: string;
  kind: "fact" | "interpretation" | "recommendation" | "limitation" | "status";
  text: string;
  evidence_ids: string[];
  verification_status: "verified" | "unverified";
  failures: string[];
}

export interface Report extends ReportSummary {
  snapshot_id: string;
  model: string | null;
  prompt_version: string;
  sections: { key: string; label: string; technical_label?: string; claims: Claim[] }[];
  evidence_refs: Record<string, { type: string; title: string }>;
  disclaimer: string;
}

export interface TimelineTxn {
  evidence_id: string;
  transaction_id: string;
  amount: number;
  timestamp_local: string;
  date: string;
  time: string;
  hour: number;
  transaction_type: string;
  channel: string;
  attribution: string;
  retailer_id?: string;
  retailer_name?: string;
  city?: string;
  terminal_id?: string;
  account_id?: string;
  linked_factors: string[];
}

export interface Timeline {
  transactions: TimelineTxn[];
  days: { date: string; transaction_count: number; total_amount: number; evidence_id: string }[];
  baseline_daily_average: number;
  hour_profile: { baseline_per_day: number[]; window_total: number[]; window_days: number; baseline_days: number };
}

export interface ChatAnswer {
  message_id: string;
  mode: "deterministic" | "llm" | "llm_fallback";
  note: string | null;
  claims: Claim[];
  tool_calls: { tool: string; args: Record<string, unknown> }[];
  evidence_refs: Record<string, { type: string; title: string }>;
  created_at_utc: string;
  question: string;
}

export interface ChatMessage {
  message_id: string;
  role: "user" | "assistant";
  content: string;
  mode: string | null;
  payload: { claims?: Claim[]; tool_calls?: ChatAnswer["tool_calls"]; note?: string | null; reviewer_id?: string };
  created_at_utc: string;
}

export interface CaseAction {
  action_id: string;
  case_id: string;
  action: string;
  from_status: string;
  to_status: string;
  reviewer_id: string;
  reviewer_name?: string;
  session_kind: string;
  notes: string | null;
  report_id: string | null;
  report_version: number | null;
  evidence_hash: string | null;
  created_at_utc: string;
  duplicate?: boolean;
}

export interface GraphNode {
  id: string;
  type: string;
  label: string;
  evidence_ids: string[];
  data: Record<string, unknown>;
}
export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relation: string;
  meaning: string;
  evidence_ids: string[];
}
export interface CaseGraph {
  case_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  node_types: string[];
  edge_meanings: Record<string, string>;
}

export interface Analytics {
  status_counts: Record<CaseStatus, number>;
  priority_counts: Record<string, number>;
  open: number;
  reviewed: number;
  escalated: number;
  closed: number;
  substantiated?: number;
  review_minutes: { n: number; median: number | null; mean: number | null; definition: string };
  decisions_by_day: { date: string; count: number }[];
  reports_by_mode: Record<string, number>;
  claims: Record<string, number>;
  exports: number;
  copilot_questions: number;
  copilot_modes: Record<string, number>;
  actions_total: number;
}

export interface Scenario {
  key: string;
  title: string;
  description: string;
  scenario: string;
}

// ---------------------------------------------------------------- workspace views
export interface HistoryRow {
  key: string;
  label: string;
  unit: string;
  previous: number | null;
  current: number | null;
  difference: number | null;
  change: number | null;
  change_unit: "%" | "pp" | "none_before" | null;
  kind: "rate" | "money" | "count" | "share";
  reliability: "ok" | "caution" | "unreliable" | "unavailable";
  note: string | null;
  how: string;
  evidence_ids: string[];
}
export interface History {
  case_id: string;
  available: boolean;
  reason: string | null;
  scope: string;
  sufficient?: boolean;
  periods?: { previous_days: number; recent_days: number; previous_count: number; recent_count: number };
  snapshot_id?: string;
  rows: HistoryRow[];
}

export type CompletenessState = "verified" | "available" | "partial" | "ambiguous" | "missing";
export interface Completeness {
  case_id: string;
  overall: CaseListItem["evidence_completeness"];
  snapshot_id: string | null;
  items: { key: string; label: string; state: CompletenessState; detail: string; evidence_ids: string[] }[];
  counts: Record<CompletenessState, number>;
}

export interface Bookmark {
  bookmark_id: string;
  case_id: string;
  evidence_id: string;
  kind: "transaction" | "retailer" | "finding" | "evidence";
  label: string;
  note: string | null;
  reviewer_id: string;
  reviewer_name: string;
  created_at_utc: string;
  updated_at_utc: string;
}

// ---------------------------------------------------------------- findings (three levels)
export interface FindingRow {
  period: "previous" | "recent";
  label: string;
  value: number | null;
  display: string;
  unit: string;
  starts_at?: number;
  full_at?: number;
}
export interface FindingDelta {
  state: "observed" | "zero_observed" | "no_previous";
  text: string;
  direction: "up" | "down" | "same" | null;
  ratio?: number | null;
  difference?: number;
  difference_unit?: string;
}
export interface FindingComparison {
  kind: "previous_vs_recent" | "recent_only" | "flow";
  unit: string;
  rows: FindingRow[];
  delta: FindingDelta | null;
  scale_max?: number;
  note?: string | null;
}
export interface SubMeasure {
  name: string;
  field: string;
  value: number | null;
  starts_at: number;
  full_at: number;
  weight: number;
  normalized: number;
  note?: string;
}
export interface Finding {
  key: string;
  evidence_id: string;
  label: string;
  technical_label: string;
  triggered: boolean;
  scored: boolean;
  points: number;
  max_points: number;
  contribution: string;
  attention: string;
  headline: string;
  change: string;
  comparison: FindingComparison | null;
  explain: { measured: string; usual: string; changed: string; why: string };
  limitations: { text: string; evidence_id: string }[];
  supporting_transaction_ids: string[];
  evidence_ids: string[];
  verification?: { status: "verified" | "unverified"; failures: string[]; checked: number; method: string };
  technical: {
    technical_label: string;
    rule: string | null;
    engine: string | null;
    metrics: { label: string; field: string; value: unknown }[];
    sub_measures: SubMeasure[];
    normalized_share: number;
    points: number;
    max_points: number;
    trigger_at_share: number;
    definitions: string[];
    normalization: string | null;
  };
}
export interface Findings {
  case_id: string;
  snapshot_id: string | null;
  periods: { previous_days: number; recent_days: number; previous_start: string; previous_end: string; recent_start: string; recent_end: string };
  scope: string;
  previous_transaction_count: number;
  previous_sufficient: boolean;
  findings: Finding[];
}

// ---------------------------------------------------------------- dashboard help
export interface GuideAnswer {
  topic: string;
  scope: string;
  answer: string[];
  links: { label: string; to: string }[];
}

// ---------------------------------------------------------------- senior-only (role-based demo)
export interface RestrictedRecord {
  player_id: string;
  record_source: string;
  case_ids: string[];
  access_count: number;
  last_access_utc: string | null;
}
export interface RestrictedList { total: number; limit: number; offset: number; records: RestrictedRecord[]; notice: string }
export interface RevealedIdentity {
  player_id: string;
  case_id: string | null;
  full_name: string;
  email: string;
  phone: string;
  record_source: string;
  fictional: true;
  access_id: string;
  logged_at_utc: string;
  notice: string;
}
export interface IdentityAccess {
  access_id: string;
  player_id: string;
  case_id: string | null;
  reviewer_id: string;
  reviewer_name: string;
  reviewer_role: string;
  session_kind: string;
  reason: string;
  fields: string[];
  created_at_utc: string;
}
export interface DataSummary {
  engine: string;
  file: string;
  schema_version: number;
  dataset: { built_utc: string | null; seed: string | null; version: string | null };
  counts: Record<string, number>;
  tables: string[];
  notice: string;
}
export interface DataTable {
  table: string;
  total: number;
  limit: number;
  offset: number;
  columns: string[];
  filters: string[];
  rows: Record<string, string | number | null>[];
}

// ---------------------------------------------------------------- final investigation dispositions
export type DispositionKey = "substantiated" | "not_substantiated" | "inconclusive" | "escalate";
export type ConcernType = "fraud" | "aml" | "safer_gambling";
export type ApprovalState = "not_required" | "pending_senior" | "confirmed" | "returned" | "superseded";
export interface DispositionOptions {
  dispositions: { key: DispositionKey; label: string; help: string; needs_senior: boolean; status: string }[];
  concern_types: { key: ConcernType; label: string }[];
  labels: Record<ConcernType, Partial<Record<DispositionKey, string>>>;
  min_justification_chars: number;
  notice: string;
  senior_roles: string[];
}
export interface DispositionEntry {
  disposition_id: string;
  case_id: string;
  action_id: string;
  entry_type: "decision" | "confirmation" | "return";
  parent_id: string | null;
  disposition: DispositionKey;
  concern_type: ConcernType;
  label: string;
  justification: string;
  evidence_ids: string[];
  reviewer_id: string;
  reviewer_name?: string;
  reviewer_role: string;
  session_kind: string;
  report_id: string | null;
  report_version: number | null;
  snapshot_id: string | null;
  evidence_hash: string | null;
  approval_status: ApprovalState;
  current_approval?: ApprovalState;
  from_status: string;
  to_status: string;
  created_at_utc: string;
  duplicate?: boolean;
}
export interface DispositionHistory {
  case_id: string;
  status: string;
  current: DispositionEntry | null;
  entries: DispositionEntry[];
  pending_senior: boolean;
  can_record: boolean;
}

// ---------------------------------------------------------------- V2: Data & Methodology
export interface MethodologyOverview {
  dataset_version: string | null;
  seed: number | null;
  generator: string | null;
  generation_config: Record<string, unknown> | null;
  generated_counts: Record<string, number> | null;
  counts: Record<string, number>;
  time_range_utc: [string | null, string | null];
  transactions_by_channel: Record<string, number>;
  attribution: { attributed: number; anonymous: number };
  scenario_categories: { category: string; players: number; description: string }[];
  storage: string;
  schema_version: number;
  notes: string[];
}
export interface EvalMetrics {
  n: number; positives: number; precision: number | null; recall: number | null; f1: number | null;
  false_positive_rate: number | null; confusion_matrix: { tp: number; fp: number; fn: number; tn: number };
}
export interface EvalWorld {
  population: EvalMetrics;
  by_category: { category: string; players: number; alerted: number; alert_rate: number }[];
  curated_subjects: { curated_key: string; category: string; planted: number; alerted: number }[];
  seed?: number | null; dataset_version?: string | null; alerts?: number;
}
export interface MethodologyEvaluation {
  current_database: EvalWorld | null;
  heldout: { evaluated_at_utc: string; heldout_seeds: number[]; heldout_pooled: EvalMetrics; heldout: EvalWorld[];
    development: EvalWorld; method: string; caveat: string } | null;
  caveat: string;
  how_to_refresh: string;
}
export interface LabelRow {
  player_id: string; profile: string; scenario: string | null; scenario_category: string; curated_key: string | null;
  label_suspicious: number; dataset_version: string; monitoring_cases: number;
}

// ---------------------------------------------------------------- V2: multi-agent investigation
export type StageStatus = "live" | "live_repaired" | "fallback" | "not_requested";
export type AssessmentKey = "suspicion_supported" | "concern_reduced" | "inconclusive" | "insufficient_evidence";
export interface AgentFinding {
  finding_id: string;
  agent: "suspicion" | "alternative";
  kind: "observation" | "interpretation" | "counterevidence" | "missing_information";
  weight: "strong" | "weak";
  text: string;
  evidence_ids: string[];
  verification_status: "verified" | "unverified";
  failures?: string[];
  same_evidence_as?: string[];
  cross_checks?: string[];
}
export interface AgentRun {
  name: string;
  hypothesis: string;
  hypothesis_status_refers_to: string;
  conclusion: string;
  warnings: string[];
  mode: "llm" | "deterministic";
  stage_status: StageStatus;
  fallback_reason: string | null;
  hypothesis_status: string;
  summary: string;
  tool_calls: { tool: string; args: Record<string, unknown>; reason: string; evidence_ids: string[]; error: string | null }[];
  verified: number;
  rejected: number;
}
export interface Investigation {
  investigation_id: string;
  case_id: string;
  requested_mode: "deterministic" | "llm";
  mode: "deterministic" | "llm" | "llm_partial_fallback";
  mode_label: string;
  model: string | null;
  status: string;
  started_at_utc: string;
  finished_at_utc: string;
  agents: { suspicion: AgentRun; alternative: AgentRun };
  verified_findings: AgentFinding[];
  rejected_findings: AgentFinding[];
  lead: {
    mode: "llm" | "deterministic"; stage_status: StageStatus; fallback_reason: string | null; warnings: string[];
    assessment: AssessmentKey; rationale: string; recommended_next_step: string;
    strongest_supporting: AgentFinding[]; strongest_counterevidence: AgentFinding[]; missing_information: AgentFinding[];
  };
  notes: string[];
  notice: string;
  storage: string;
}

export interface InvestigationSummary {
  investigation_id: string;
  case_id: string;
  requested_mode: "deterministic" | "llm";
  mode: Investigation["mode"] | null;
  status: "running" | "completed" | "failed";
  assessment: AssessmentKey | null;
  requested_by: string;
  started_at_utc: string;
  finished_at_utc: string | null;
  error: string | null;
  already_running?: boolean;
}
