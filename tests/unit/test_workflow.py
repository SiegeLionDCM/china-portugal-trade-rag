from trade_copilot.config import Settings
from trade_copilot.context_engine import ContextEngine
from trade_copilot.domain.models import AnswerStatus, QueryRequest
from trade_copilot.workflows import QueryWorkflow


class MustNotRun:
    async def retrieve(self, _context):
        raise AssertionError("retrieval should not run for an ambiguous query")

    def verify(self, _context, _candidates):
        raise AssertionError("verification should not run for an ambiguous query")

    async def compose(self, _context, _decision):
        raise AssertionError("generation should not run for an ambiguous query")


async def test_clarification_branch_never_calls_models() -> None:
    never = MustNotRun()
    workflow = QueryWorkflow(Settings(), ContextEngine(), never, never, never)
    response = await workflow.invoke(QueryRequest(query="企业税率是多少？"))
    assert response.status == AnswerStatus.ABSTAINED
    assert "巴西还是葡萄牙" in response.answer
