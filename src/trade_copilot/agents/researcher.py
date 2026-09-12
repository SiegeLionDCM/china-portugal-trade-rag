from __future__ import annotations

import time

from trade_copilot.domain.models import AgentTask, ContextPackage, ResearchResult
from trade_copilot.retrieval import HybridRetriever


class JurisdictionResearchAgent:
    """Run retrieval inside one jurisdiction boundary and return evidence, not prose."""

    def __init__(self, retriever: HybridRetriever) -> None:
        self.retriever = retriever

    async def research(self, context: ContextPackage, task: AgentTask) -> ResearchResult:
        started = time.perf_counter()
        scoped_context = context.model_copy(
            update={
                "jurisdictions": [task.jurisdiction],
                "metadata_filters": {
                    **context.metadata_filters,
                    "jurisdictions": [task.jurisdiction.value],
                },
            }
        )
        try:
            candidates = await self.retriever.retrieve(scoped_context)
            return ResearchResult(
                agent=task.agent,
                jurisdiction=task.jurisdiction,
                candidates=candidates,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        # One jurisdiction may fail without cancelling its peers.
        except Exception as exc:  # noqa: BLE001
            return ResearchResult(
                agent=task.agent,
                jurisdiction=task.jurisdiction,
                duration_ms=(time.perf_counter() - started) * 1000,
                error=type(exc).__name__,
            )
