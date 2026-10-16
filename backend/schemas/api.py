"""Typed API contracts (Pydantic v2). Request models are strict; response models
declare the fields the frontend relies on and allow extra detail."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

CASE_ID = r"^CASE-\d{5}$"
REPORT_ID = r"^RPT-\d{6}$"
EVIDENCE_ID = r"^EV-\d{6}$"


class Open(BaseModel):
    model_config = ConfigDict(extra="allow")


# ------------------------------------------------------------------ requests
class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer_id: str = Field(pattern=r"^REV-\d{2}$")
    access_code: str | None = Field(default=None, max_length=128)


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["deterministic", "llm"] = "deterministic"


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=1000)
    mode: Literal["deterministic", "llm"] = "deterministic"


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["start_review", "add_note", "request_info", "close_no_action", "escalate", "reopen"]
    notes: Optional[str] = Field(None, max_length=4000)
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_\-:.]+$")
    expected_status: Optional[str] = Field(None, max_length=40)
    report_id: Optional[str] = Field(None, pattern=REPORT_ID)


BOOKMARK_ID = r"^BMK-\d{6}$"


class BookmarkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str = Field(pattern=EVIDENCE_ID)
    note: Optional[str] = Field(None, max_length=2000)
    label: Optional[str] = Field(None, max_length=200)


class BookmarkNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: Optional[str] = Field(None, max_length=2000)


# ----------------------------------------------------------------- responses
class Reviewer(Open):
    reviewer_id: str
    display_name: str
    role: str


class SessionOut(Open):
    token: str
    kind: Literal["simulated"]
    reviewer: Reviewer
    notice: str


class CaseListItem(Open):
    case_id: str
    alert_id: str
    alert_type: str
    channel: str
    subject_id: str
    status: str
    priority: str
    alert_score: float
    evidence_completeness: str
    created_at_utc: str
    assigned_reviewer: Optional[str] = None


class CaseList(Open):
    cases: list[CaseListItem]
    count: int
    facets: dict[str, Any]
    totals: dict[str, int]


class EvidenceItem(Open):
    evidence_id: str
    case_id: str
    snapshot_id: Optional[str]
    type: str
    title: str
    summary: str
    source_ids: list[str]
    entities: list[str]
    computed: dict[str, Any]
    provenance: dict[str, Any]


class Claim(Open):
    claim_id: Optional[str] = None
    section: str
    kind: str
    text: str
    evidence_ids: list[str]
    verification_status: Literal["verified", "unverified"]
    failures: list[str]


class ReportSection(Open):
    key: str
    label: str
    claims: list[Claim]


class Report(Open):
    report_id: str
    case_id: str
    version: int
    mode: str
    mode_label: str
    status: Literal["draft", "locked"]
    evidence_hash: str
    created_at_utc: str
    validation: dict[str, int]
    sections: list[ReportSection]
    evidence_refs: dict[str, dict[str, str]]
    disclaimer: str


class ChatAnswer(Open):
    message_id: str
    mode: str
    note: Optional[str]
    claims: list[Claim]
    evidence_refs: dict[str, dict[str, str]]
    question: str


class ActionOut(Open):
    action_id: str
    case_id: str
    action: str
    from_status: str
    to_status: str
    reviewer_id: str
    report_version: Optional[int]
    evidence_hash: Optional[str]
    duplicate: bool


class ErrorOut(BaseModel):
    detail: str


PLAYER_ID = r"^PLY-[A-Z0-9]{2,8}$"


class RevealRequest(BaseModel):
    """Senior-only reveal of a fictional identity record. The reason is stored in the access log."""
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=500)
    case_id: Optional[str] = Field(None, pattern=CASE_ID)


class GuideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=1000)


DISPOSITION_ID = r"^DSP-\d{6}$"


class DispositionRequest(BaseModel):
    """A human reviewer's final investigation decision. Never created by the AI."""
    model_config = ConfigDict(extra="forbid")
    disposition: Literal["substantiated", "not_substantiated", "inconclusive", "escalate"]
    concern_type: Literal["fraud", "aml", "safer_gambling"] = "fraud"
    justification: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[str] = Field(min_length=1, max_length=50)
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_\-:.]+$")
    expected_status: Optional[str] = Field(None, max_length=60)
    report_id: Optional[str] = Field(None, pattern=REPORT_ID)


class DispositionReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["confirm", "return"]
    notes: str = Field(min_length=1, max_length=4000)
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_\-:.]+$")
    expected_status: Optional[str] = Field(None, max_length=60)


INVESTIGATION_ID = r"^INV-[0-9a-f]{10}$"


class InvestigationRequest(BaseModel):
    """Start the multi-agent investigation for one case. Never changes the case or any reviewer decision."""
    model_config = ConfigDict(extra="forbid")
    mode: Literal["deterministic", "llm"] = "deterministic"
