from trade_copilot.agents import SupervisorAgent
from trade_copilot.config import Settings
from trade_copilot.context_engine import ContextEngine
from trade_copilot.domain.models import (
    AnswerStatus,
    EvidenceDecision,
    EvidenceLevel,
    Jurisdiction,
    QueryRequest,
    QueryResponse,
)
from trade_copilot.workflows import QueryWorkflow


def test_supervisor_creates_parallel_jurisdiction_plan() -> None:
    context = ContextEngine().build(
        QueryRequest(
            query="比较巴西和葡萄牙设立公司的区别",
            jurisdictions=[Jurisdiction.BRAZIL, Jurisdiction.PORTUGAL],
        )
    )
    plan = SupervisorAgent().plan(context)
    assert plan.mode == "parallel"
    assert {task.jurisdiction for task in plan.tasks} == {
        Jurisdiction.BRAZIL,
        Jurisdiction.PORTUGAL,
    }


class RecordingRetriever:
    def __init__(self) -> None:
        self.jurisdictions: list[tuple[Jurisdiction, ...]] = []

    async def retrieve(self, context):
        self.jurisdictions.append(tuple(context.jurisdictions))
        return []


class AbstainingVerifier:
    def verify(self, _context, _candidates):
        return EvidenceDecision(
            status=AnswerStatus.ABSTAINED,
            level=EvidenceLevel.INSUFFICIENT,
            reasons=["test"],
        )


class StaticComposer:
    async def compose(self, context, decision):
        return QueryResponse(
            request_id=context.request_id,
            status=decision.status,
            evidence_level=decision.level,
            answer="test",
            reasons=decision.reasons,
            disclaimer="test",
        )


async def test_workflow_dispatches_isolated_research_agents() -> None:
    retriever = RecordingRetriever()
    workflow = QueryWorkflow(
        Settings(),
        ContextEngine(),
        retriever,
        AbstainingVerifier(),
        StaticComposer(),
    )
    assert workflow.retriever is retriever
    response = await workflow.invoke(
        QueryRequest(
            query="比较巴西和葡萄牙设立公司的区别",
            jurisdictions=[Jurisdiction.BRAZIL, Jurisdiction.PORTUGAL],
        )
    )
    assert set(retriever.jurisdictions) == {
        (Jurisdiction.BRAZIL,),
        (Jurisdiction.PORTUGAL,),
    }
    assert {step.agent for step in response.agent_trace} >= {
        "supervisor_agent",
        "brazil_researcher",
        "portugal_researcher",
        "evidence_arbiter",
        "synthesis_agent",
        "citation_validator",
    }
