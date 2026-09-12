from datetime import UTC, date, datetime, timedelta

from trade_copilot.config import Settings
from trade_copilot.domain.models import (
    AnswerStatus,
    CandidateEvidence,
    Chunk,
    ContextPackage,
    Jurisdiction,
    SourceTier,
)
from trade_copilot.evidence import EvidenceVerifier


def make_context(*jurisdictions: Jurisdiction) -> ContextPackage:
    return ContextPackage(
        request_id="request",
        user_query_original="question",
        query_language="zh",
        normalized_query="question",
        intent="fact",
        jurisdictions=list(jurisdictions),
        topics=[],
        retrieval_queries=["question"],
    )


def make_candidate(
    jurisdiction: Jurisdiction = Jurisdiction.BRAZIL,
    score: float = 0.9,
    expires: date | None = None,
) -> CandidateEvidence:
    chunk = Chunk(
        chunk_id="chunk",
        document_id="doc",
        text="official evidence",
        jurisdiction=jurisdiction,
        language="pt",
        topics=["tax"],
        title="Title",
        publisher="Government",
        source_url="https://example.gov",
        source_tier=SourceTier.GOVERNMENT,
        expires_date=expires,
        content_hash="hash",
    )
    return CandidateEvidence(chunk=chunk, rerank_score=score)


def test_abstains_below_threshold() -> None:
    verifier = EvidenceVerifier(Settings(min_rerank_score=0.5))
    decision = verifier.verify(make_context(Jurisdiction.BRAZIL), [make_candidate(score=0.2)])
    assert decision.status == AnswerStatus.ABSTAINED


def test_answers_with_authoritative_matching_evidence() -> None:
    verifier = EvidenceVerifier(Settings(min_rerank_score=0.5))
    decision = verifier.verify(make_context(Jurisdiction.BRAZIL), [make_candidate()])
    assert decision.status == AnswerStatus.ANSWERED


def test_partial_when_comparison_missing_one_jurisdiction() -> None:
    verifier = EvidenceVerifier(Settings(min_rerank_score=0.5))
    decision = verifier.verify(
        make_context(Jurisdiction.BRAZIL, Jurisdiction.PORTUGAL), [make_candidate()]
    )
    assert decision.status == AnswerStatus.PARTIAL


def test_abstains_if_all_evidence_expired() -> None:
    verifier = EvidenceVerifier(Settings(min_rerank_score=0.5))
    decision = verifier.verify(
        make_context(Jurisdiction.BRAZIL),
        [make_candidate(expires=datetime.now(UTC).date() - timedelta(days=1))],
    )
    assert decision.status == AnswerStatus.ABSTAINED


def test_blocking_context_risk_abstains_before_scoring() -> None:
    verifier = EvidenceVerifier(Settings(min_rerank_score=0.1))
    context = make_context(Jurisdiction.PORTUGAL)
    context.risk_flags = ["unsupported_future_prediction"]
    decision = verifier.verify(context, [make_candidate(jurisdiction=Jurisdiction.PORTUGAL)])
    assert decision.status == AnswerStatus.ABSTAINED
    assert decision.evidence == []
