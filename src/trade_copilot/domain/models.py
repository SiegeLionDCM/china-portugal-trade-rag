from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


class Jurisdiction(StrEnum):
    BRAZIL = "BR"
    PORTUGAL = "PT"


class AnswerStatus(StrEnum):
    ANSWERED = "ANSWERED"
    PARTIAL = "PARTIAL"
    CONFLICTED = "CONFLICTED"
    ABSTAINED = "ABSTAINED"


class EvidenceLevel(StrEnum):
    SUFFICIENT = "充分"
    LIMITED = "有限"
    CONFLICTED = "冲突"
    INSUFFICIENT = "不足"


class SourceTier(StrEnum):
    OFFICIAL_LAW = "official_law"
    GOVERNMENT = "government"
    OFFICIAL_GUIDE = "official_guide"
    INTERNATIONAL_ORG = "international_org"
    AUTHORITY = "authority"


class DocumentManifest(BaseModel):
    document_id: str
    file: str
    title: str
    publisher: str
    source_url: HttpUrl
    jurisdiction: Jurisdiction
    language: Literal["zh", "pt", "en"]
    topics: list[str]
    source_tier: SourceTier
    published_date: date | None = None
    effective_date: date | None = None
    expires_date: date | None = None
    notes: str | None = None


class Chunk(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    page: int | None = None
    section: str | None = None
    parent_id: str | None = None
    jurisdiction: Jurisdiction
    language: str
    topics: list[str]
    title: str
    publisher: str
    source_url: str
    source_tier: SourceTier
    published_date: date | None = None
    effective_date: date | None = None
    expires_date: date | None = None
    content_hash: str


class ConversationTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class QueryRequest(BaseModel):
    query: str = Field(min_length=2, max_length=4000)
    answer_language: Literal["zh", "pt"] = "zh"
    conversation: list[ConversationTurn] = Field(default_factory=list, max_length=12)
    enterprise_profile: dict[str, str] = Field(default_factory=dict)
    jurisdictions: list[Jurisdiction] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)


class ContextPackage(BaseModel):
    request_id: str
    user_query_original: str
    query_language: Literal["zh", "pt", "unknown"]
    normalized_query: str
    intent: Literal["fact", "compare", "summarize", "follow_up"]
    jurisdictions: list[Jurisdiction]
    topics: list[str]
    time_scope: str | None = None
    enterprise_profile: dict[str, str] = Field(default_factory=dict)
    conversation_summary: str = ""
    retrieval_queries: list[str]
    metadata_filters: dict[str, Any] = Field(default_factory=dict)
    evidence_budget: int = 5
    answer_language: Literal["zh", "pt"] = "zh"
    risk_flags: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None


class CandidateEvidence(BaseModel):
    chunk: Chunk
    dense_rank: int | None = None
    lexical_rank: int | None = None
    fused_score: float = 0.0
    rerank_score: float | None = None
    matched_query: str = ""


class Citation(BaseModel):
    id: int
    document_id: str
    title: str
    publisher: str
    source_url: str
    page: int | None = None
    section: str | None = None
    quote: str
    language: str
    published_date: date | None = None
    effective_date: date | None = None
    content_hash: str


class EvidenceDecision(BaseModel):
    status: AnswerStatus
    level: EvidenceLevel
    reasons: list[str]
    evidence: list[CandidateEvidence] = Field(default_factory=list)


class AgentTask(BaseModel):
    agent: Literal["brazil_researcher", "portugal_researcher"]
    jurisdiction: Jurisdiction
    objective: str


class ExecutionPlan(BaseModel):
    mode: Literal["single", "parallel"]
    tasks: list[AgentTask]


class ResearchResult(BaseModel):
    agent: Literal["brazil_researcher", "portugal_researcher"]
    jurisdiction: Jurisdiction
    candidates: list[CandidateEvidence] = Field(default_factory=list)
    duration_ms: float = 0.0
    error: str | None = None


class AgentTraceStep(BaseModel):
    agent: str
    status: Literal["completed", "failed", "skipped"]
    summary: str
    duration_ms: float | None = None


class QueryResponse(BaseModel):
    request_id: str
    status: AnswerStatus
    evidence_level: EvidenceLevel
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    information_as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))
    disclaimer: str
    agent_trace: list[AgentTraceStep] = Field(default_factory=list)
    trace: dict[str, Any] | None = None


class IngestResult(BaseModel):
    documents_seen: int = 0
    documents_indexed: int = 0
    documents_skipped: int = 0
    chunks_indexed: int = 0
    errors: list[str] = Field(default_factory=list)
