from __future__ import annotations

from trade_copilot.domain.models import ContextPackage, EvidenceDecision, QueryResponse
from trade_copilot.generation import AnswerComposer


class SynthesisAgent:
    """Generate only from evidence approved by the arbiter."""

    def __init__(self, composer: AnswerComposer) -> None:
        self.composer = composer

    async def synthesize(
        self,
        context: ContextPackage,
        decision: EvidenceDecision,
    ) -> QueryResponse:
        return await self.composer.compose(context, decision)
