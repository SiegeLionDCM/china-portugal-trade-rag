from __future__ import annotations

import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from trade_copilot.config import Settings
from trade_copilot.context_engine import ContextEngine
from trade_copilot.domain.models import (
    AnswerStatus,
    ContextPackage,
    EvidenceDecision,
    EvidenceLevel,
    QueryRequest,
    QueryResponse,
)
from trade_copilot.evidence import EvidenceVerifier
from trade_copilot.generation import AnswerComposer
from trade_copilot.retrieval import HybridRetriever


class GraphState(TypedDict, total=False):
    request: QueryRequest
    context: ContextPackage
    candidates: list
    decision: EvidenceDecision
    response: QueryResponse
    timings_ms: dict[str, float]


class QueryWorkflow:
    def __init__(
        self,
        settings: Settings,
        context_engine: ContextEngine,
        retriever: HybridRetriever,
        verifier: EvidenceVerifier,
        composer: AnswerComposer,
    ) -> None:
        self.settings = settings
        self.context_engine = context_engine
        self.retriever = retriever
        self.verifier = verifier
        self.composer = composer
        graph = StateGraph(GraphState)
        graph.add_node("context_builder", self._context_builder)
        graph.add_node("clarify", self._clarify)
        graph.add_node("retrieve", self._retrieve)
        graph.add_node("verify", self._verify)
        graph.add_node("compose", self._compose)
        graph.add_edge(START, "context_builder")
        graph.add_conditional_edges(
            "context_builder",
            lambda state: "clarify" if state["context"].needs_clarification else "retrieve",
        )
        graph.add_edge("clarify", END)
        graph.add_edge("retrieve", "verify")
        graph.add_edge("verify", "compose")
        graph.add_edge("compose", END)
        self.graph = graph.compile()

    async def _context_builder(self, state: GraphState) -> dict:
        started = time.perf_counter()
        context = self.context_engine.build(state["request"])
        return {"context": context, "timings_ms": {"context": (time.perf_counter() - started) * 1000}}

    async def _clarify(self, state: GraphState) -> dict:
        context = state["context"]
        response = QueryResponse(
            request_id=context.request_id,
            status=AnswerStatus.ABSTAINED,
            evidence_level=EvidenceLevel.INSUFFICIENT,
            answer=context.clarification_question or "请补充问题范围。",
            reasons=["缺少会改变答案的法域信息"],
            disclaimer="本回答仅用于信息检索，不构成法律、税务或投资意见。",
        )
        return {"response": response}

    async def _retrieve(self, state: GraphState) -> dict:
        started = time.perf_counter()
        candidates = await self.retriever.retrieve(state["context"])
        timings = dict(state.get("timings_ms", {}))
        timings["retrieval"] = (time.perf_counter() - started) * 1000
        return {"candidates": candidates, "timings_ms": timings}

    async def _verify(self, state: GraphState) -> dict:
        started = time.perf_counter()
        decision = self.verifier.verify(state["context"], state["candidates"])
        timings = dict(state.get("timings_ms", {}))
        timings["verification"] = (time.perf_counter() - started) * 1000
        return {"decision": decision, "timings_ms": timings}

    async def _compose(self, state: GraphState) -> dict:
        started = time.perf_counter()
        response = await self.composer.compose(state["context"], state["decision"])
        timings = dict(state.get("timings_ms", {}))
        timings["generation"] = (time.perf_counter() - started) * 1000
        if self.settings.debug_context:
            response.trace = {
                "context": state["context"].model_dump(mode="json"),
                "timings_ms": timings,
                "retrieval": [
                    {
                        "chunk_id": item.chunk.chunk_id,
                        "dense_rank": item.dense_rank,
                        "lexical_rank": item.lexical_rank,
                        "fused_score": item.fused_score,
                        "rerank_score": item.rerank_score,
                    }
                    for item in state["candidates"]
                ],
            }
        return {"response": response, "timings_ms": timings}

    async def invoke(self, request: QueryRequest) -> QueryResponse:
        state = await self.graph.ainvoke({"request": request})
        return state["response"]

