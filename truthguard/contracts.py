"""Shared Pydantic models — contract frozen; see §5.2 of AGENTS.md."""
from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel


class User(BaseModel):
    user_id: str               # OIDC 'sub' (or fake id when ENABLE_SSO=false)
    name: str | None = None
    role: str                  # 'employee' | 'admin'
    access_levels: list[str]   # e.g. ['all'] or ['all', 'compliance']; from IdP groups via GROUP_TO_ACCESS


class Clause(BaseModel):       # mirrors the clauses table
    clause_id: str
    doc_id: str
    source_text: str
    language: str | None = None
    text_en: str | None = None
    concept_id: str | None = None
    subject: str | None = None
    clause_type: str | None = None
    value_num: float | None = None
    value_unit: str | None = None
    value_text: str | None = None
    condition_text: str | None = None
    scope: str = "*"
    issuer: str | None = None
    authority_rank: int | None = None
    effective_date: date | None = None
    supersedes: str | None = None
    access_level: str = "all"
    extract_conf: float | None = None
    status: str = "active"


class RetrievedClause(BaseModel):
    clause: Clause
    score: float               # final rerank score
    via: str                   # 'search' | 'family_expansion'


class RetrievalResult(BaseModel):
    concept_id: str | None
    question_scope: str = "*"  # scope tags inferred from the question
    candidates: list[RetrievedClause]   # top-k after rerank
    family: list[RetrievedClause]       # every active version for the concept (after filters)
    restricted_conflict: bool = False   # a hidden clause disagrees; never include its text


class Claim(BaseModel):
    claim_id: str
    text: str
    clause_ids: list[str]      # must be non-empty and refer to retrieved clauses


class Draft(BaseModel):
    answer_text: str
    claims: list[Claim]


class FindingType(str, Enum):  # noqa: UP042
    CONTRADICTION = "contradiction"
    STALE = "stale"
    UNSUPPORTED = "unsupported"


class Finding(BaseModel):
    type: FindingType
    claim_id: str | None
    clause_ids: list[str]      # clauses involved
    detail: str                # human-readable, e.g. 'A1#4.2 supersedes P1#4.2'
    evidence: dict = {}        # e.g. {'nli_contradiction': 0.93} or SQL rows


class Status(str, Enum):  # noqa: UP042
    SUPPORTED = "SUPPORTED"
    CONFLICT_RESOLVED = "CONFLICT_RESOLVED"
    RESOLVED_BY_SCOPE = "RESOLVED_BY_SCOPE"
    UNRESOLVED = "UNRESOLVED"


class Decision(BaseModel):
    winner: str | None         # clause_id, None if abstained
    losers: list[str]
    rule: str                  # 'scope' | 'supersedes' | 'authority' | 'specificity' | 'recency' | 'abstain_tie' | 'abstain_missing'
    explanation: str


class Verdict(BaseModel):
    status: Status
    answer_text: str
    applies: list[str]         # clause_ids that apply
    shown_sources: list[str]   # every clause shown to the user (winners AND losers)
    decisions: list[Decision]
    review_item_ids: list[str] = []


class TGState(BaseModel):      # LangGraph state; also stored in audit_log.trace_json
    question: str
    question_language: str = "en"   # en | hi | mixed; the final answer is written in this language
    user: User
    as_of: date | None = None
    rewrites: list[str] = []
    retrieval: RetrievalResult | None = None
    draft: Draft | None = None
    findings: list[Finding] = []
    verdict: Verdict | None = None
