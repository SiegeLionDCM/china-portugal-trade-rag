from __future__ import annotations

from typing import ClassVar

from trade_copilot.domain.models import AgentTask, ContextPackage, ExecutionPlan, Jurisdiction


class SupervisorAgent:
    """Build a bounded execution plan from the normalized context package."""

    _AGENT_BY_JURISDICTION: ClassVar = {
        Jurisdiction.BRAZIL: "brazil_researcher",
        Jurisdiction.PORTUGAL: "portugal_researcher",
    }

    def plan(self, context: ContextPackage) -> ExecutionPlan:
        tasks = [
            AgentTask(
                agent=self._AGENT_BY_JURISDICTION[jurisdiction],
                jurisdiction=jurisdiction,
                objective=(
                    f"Find directly supporting {jurisdiction.value} evidence for: "
                    f"{context.normalized_query}"
                ),
            )
            for jurisdiction in context.jurisdictions
        ]
        return ExecutionPlan(
            mode="parallel" if len(tasks) > 1 else "single",
            tasks=tasks,
        )
