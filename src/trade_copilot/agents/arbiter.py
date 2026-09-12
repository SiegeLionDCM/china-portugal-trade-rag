from __future__ import annotations

from trade_copilot.domain.models import (
    CandidateEvidence,
    ContextPackage,
    EvidenceDecision,
    ResearchResult,
)
from trade_copilot.evidence import EvidenceVerifier


class EvidenceArbiterAgent:
    """Merge specialist findings and apply the existing fail-closed evidence policy."""

    def __init__(self, verifier: EvidenceVerifier) -> None:
        self.verifier = verifier

    def review(
        self,
        context: ContextPackage,
        results: list[ResearchResult],
    ) -> tuple[EvidenceDecision, list[CandidateEvidence]]:
        by_chunk: dict[str, CandidateEvidence] = {}
        for result in results:
            for candidate in result.candidates:
                current = by_chunk.get(candidate.chunk.chunk_id)
                if current is None or (candidate.rerank_score or 0) > (current.rerank_score or 0):
                    by_chunk[candidate.chunk.chunk_id] = candidate
        candidates = sorted(
            by_chunk.values(),
            key=lambda item: item.rerank_score or 0,
            reverse=True,
        )
        return self.verifier.verify(context, candidates), candidates
