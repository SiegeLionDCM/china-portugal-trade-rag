from __future__ import annotations

import operator
import time
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from trade_copilot.agents import (
    EvidenceArbiterAgent,
    JurisdictionResearchAgent,
    SupervisorAgent,
    SynthesisAgent,
)
from trade_copilot.config import Settings
from trade_copilot.context_engine import ContextEngine
from trade_copilot.domain.models import (
    AgentTask,
    AgentTraceStep,
    AnswerStatus,
    CandidateEvidence,
    ContextPackage,
    EvidenceDecision,
    EvidenceLevel,
    ExecutionPlan,
    QueryRequest,
    QueryResponse,
    ResearchResult,
)
from trade_copilot.evidence import EvidenceVerifier
from trade_copilot.generation import AnswerComposer
from trade_copilot.retrieval import HybridRetriever


class GraphState(TypedDict, total=False):
    request: QueryRequest
    context: ContextPackage
    plan: ExecutionPlan
    research_task: AgentTask
    research_results: Annotated[list[ResearchResult], operator.add]
    candidates: list[CandidateEvidence]
    decision: EvidenceDecision
    response: QueryResponse
    timings_ms: dict[str, float]
    agent_trace: Annotated[list[AgentTraceStep], operator.add]


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
        # Kept as a public evaluation hook; production execution uses the
        # jurisdiction-isolated Research Agent below.
        self.retriever = retriever
        self.supervisor = SupervisorAgent()
        self.researcher = JurisdictionResearchAgent(retriever)
        self.arbiter = EvidenceArbiterAgent(verifier)
        self.synthesizer = SynthesisAgent(composer)

        graph = StateGraph(GraphState)
        graph.add_node("context_engine", self._context_engine)
        graph.add_node("clarification_agent", self._clarify)
        graph.add_node("supervisor_agent", self._supervise)
        graph.add_node("research_agent", self._research)
        graph.add_node("evidence_arbiter", self._arbitrate)
        graph.add_node("synthesis_agent", self._synthesize)
        graph.add_edge(START, "context_engine")
        graph.add_conditional_edges(
            "context_engine",
            lambda state: (
                "clarification_agent"
                if state["context"].needs_clarification
                else "supervisor_agent"
            ),
        )
        graph.add_edge("clarification_agent", END)
        graph.add_conditional_edges("supervisor_agent", self._dispatch_research)
        graph.add_edge("research_agent", "evidence_arbiter")
        graph.add_edge("evidence_arbiter", "synthesis_agent")
        graph.add_edge("synthesis_agent", END)
        self.graph = graph.compile()

    async def _context_engine(self, state: GraphState) -> dict:
        started = time.perf_counter()
        context = self.context_engine.build(state["request"])
        elapsed = (time.perf_counter() - started) * 1000
        jurisdiction_label = ", ".join(item.value for item in context.jurisdictions) or "待澄清"
        return {
            "context": context,
            "timings_ms": {"context": elapsed},
            "agent_trace": [
                AgentTraceStep(
                    agent="context_engine",
                    status="completed",
                    summary=f"识别法域：{jurisdiction_label}；意图：{context.intent}。",
                    duration_ms=elapsed,
                )
            ],
        }

    async def _clarify(self, state: GraphState) -> dict:
        context = state["context"]
        response = QueryResponse(
            request_id=context.request_id,
            status=AnswerStatus.ABSTAINED,
            evidence_level=EvidenceLevel.INSUFFICIENT,
            answer=context.clarification_question or "请补充问题范围。",
            reasons=["缺少会改变答案的法域信息"],
            disclaimer="本回答仅用于信息检索，不构成法律、税务或投资意见。",
            agent_trace=state.get("agent_trace", [])
            + [
                AgentTraceStep(
                    agent="clarification_agent",
                    status="completed",
                    summary="问题缺少法域信息，已请求用户澄清。",
                )
            ],
        )
        return {"response": response}

    async def _supervise(self, state: GraphState) -> dict:
        started = time.perf_counter()
        plan = self.supervisor.plan(state["context"])
        elapsed = (time.perf_counter() - started) * 1000
        timings = dict(state.get("timings_ms", {}))
        timings["supervision"] = elapsed
        return {
            "plan": plan,
            "timings_ms": timings,
            "agent_trace": [
                AgentTraceStep(
                    agent="supervisor_agent",
                    status="completed",
                    summary=f"生成 {len(plan.tasks)} 个{plan.mode}研究任务。",
                    duration_ms=elapsed,
                )
            ],
        }

    @staticmethod
    def _dispatch_research(state: GraphState) -> list[Send]:
        return [
            Send(
                "research_agent",
                {"context": state["context"], "research_task": task},
            )
            for task in state["plan"].tasks
        ]

    async def _research(self, state: GraphState) -> dict:
        result = await self.researcher.research(state["context"], state["research_task"])
        if result.error:
            trace = AgentTraceStep(
                agent=result.agent,
                status="failed",
                summary=f"{result.jurisdiction.value} 研究失败：{result.error}",
                duration_ms=result.duration_ms,
            )
        else:
            trace = AgentTraceStep(
                agent=result.agent,
                status="completed",
                summary=f"{result.jurisdiction.value} 返回 {len(result.candidates)} 条候选证据。",
                duration_ms=result.duration_ms,
            )
        return {"research_results": [result], "agent_trace": [trace]}

    async def _arbitrate(self, state: GraphState) -> dict:
        started = time.perf_counter()
        decision, candidates = self.arbiter.review(
            state["context"], state.get("research_results", [])
        )
        elapsed = (time.perf_counter() - started) * 1000
        timings = dict(state.get("timings_ms", {}))
        timings["arbitration"] = elapsed
        return {
            "decision": decision,
            "candidates": candidates,
            "timings_ms": timings,
            "agent_trace": [
                AgentTraceStep(
                    agent="evidence_arbiter",
                    status="completed",
                    summary=(
                        f"审核 {len(candidates)} 条候选证据，批准 {len(decision.evidence)} 条；"
                        f"结论：{decision.status.value}。"
                    ),
                    duration_ms=elapsed,
                )
            ],
        }

    async def _synthesize(self, state: GraphState) -> dict:
        started = time.perf_counter()
        response = await self.synthesizer.synthesize(state["context"], state["decision"])
        elapsed = (time.perf_counter() - started) * 1000
        timings = dict(state.get("timings_ms", {}))
        timings["synthesis"] = elapsed
        citation_failed = any("引用校验" in reason for reason in response.reasons)
        if citation_failed:
            citation_status = "failed"
            citation_summary = "回答没有通过引用校验，已关闭式拒答。"
        elif response.status == AnswerStatus.ABSTAINED:
            citation_status = "skipped"
            citation_summary = "证据门控已拒答，无需生成事实性引用。"
        else:
            citation_status = "completed" if response.citations else "failed"
            citation_summary = "引用校验通过。" if response.citations else "回答缺少有效引用。"
        response.agent_trace = state.get("agent_trace", []) + [
            AgentTraceStep(
                agent="synthesis_agent",
                status="completed",
                summary=(
                    f"生成 {response.status.value} 回答，并保留 {len(response.citations)} 条引用。"
                ),
                duration_ms=elapsed,
            ),
            AgentTraceStep(
                agent="citation_validator",
                status=citation_status,
                summary=citation_summary,
            ),
        ]
        if self.settings.debug_context:
            response.trace = {
                "context": state["context"].model_dump(mode="json"),
                "plan": state["plan"].model_dump(mode="json"),
                "timings_ms": timings,
                "retrieval": [
                    {
                        "chunk_id": item.chunk.chunk_id,
                        "dense_rank": item.dense_rank,
                        "lexical_rank": item.lexical_rank,
                        "fused_score": item.fused_score,
                        "rerank_score": item.rerank_score,
                    }
                    for item in state.get("candidates", [])
                ],
            }
        return {"response": response, "timings_ms": timings}

    async def invoke(self, request: QueryRequest) -> QueryResponse:
        state = await self.graph.ainvoke(
            {"request": request, "research_results": [], "agent_trace": []}
        )
        return state["response"]
