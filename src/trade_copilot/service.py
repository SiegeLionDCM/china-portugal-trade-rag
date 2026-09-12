from __future__ import annotations

from functools import lru_cache

import httpx

from trade_copilot.config import get_settings
from trade_copilot.context_engine import ContextEngine
from trade_copilot.evidence import EvidenceVerifier
from trade_copilot.generation import AnswerComposer
from trade_copilot.ingestion import IngestionPipeline
from trade_copilot.providers import DeepSeekClient, SiliconFlowClient
from trade_copilot.retrieval import HybridRetriever
from trade_copilot.storage import Repository
from trade_copilot.workflows import QueryWorkflow


class ApplicationServices:
    def __init__(self) -> None:
        settings = get_settings()
        repository = Repository(settings)
        self._siliconflow_http = httpx.AsyncClient(timeout=settings.request_timeout_seconds)
        self._deepseek_http = httpx.AsyncClient(timeout=settings.request_timeout_seconds)
        siliconflow = SiliconFlowClient(settings, self._siliconflow_http)
        deepseek = DeepSeekClient(settings, self._deepseek_http)
        self.settings = settings
        self.repository = repository
        self.ingestion = IngestionPipeline(settings, repository, siliconflow)
        self.workflow = QueryWorkflow(
            settings,
            ContextEngine(),
            HybridRetriever(settings, repository, siliconflow),
            EvidenceVerifier(settings),
            AnswerComposer(deepseek),
        )

    def close(self) -> None:
        self.repository.close()

    async def aclose(self) -> None:
        await self._siliconflow_http.aclose()
        await self._deepseek_http.aclose()
        self.repository.close()


@lru_cache
def get_services() -> ApplicationServices:
    return ApplicationServices()
