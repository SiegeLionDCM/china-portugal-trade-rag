from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from trade_copilot.domain.models import IngestResult, QueryRequest, QueryResponse
from trade_copilot.service import ApplicationServices, get_services


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    if get_services.cache_info().currsize:
        await get_services().aclose()
        get_services.cache_clear()


app = FastAPI(
    title="中葡经贸合规智能体 API",
    version="0.1.0",
    description="Auditable Chinese-Portuguese compliance RAG; informational use only.",
    lifespan=lifespan,
)
ServiceDep = Annotated[ApplicationServices, Depends(get_services)]


class FeedbackRequest(BaseModel):
    request_id: str
    category: Literal["helpful", "unhelpful", "citation_error", "outdated", "wrong_abstention"]
    note: str | None = Field(default=None, max_length=2000)


@app.get("/health")
async def health(services: ServiceDep) -> dict:
    return {
        "status": "ok",
        "index": services.repository.stats(),
        "models": {
            "embedding": services.settings.embedding_model,
            "reranker": services.settings.rerank_model,
            "llm": services.settings.llm_model,
        },
        "credentials_configured": {
            "siliconflow": bool(services.settings.siliconflow_api_key),
            "deepseek": bool(services.settings.deepseek_api_key),
        },
    }


@app.post("/v1/query", response_model=QueryResponse)
async def query(
    request: QueryRequest, services: ServiceDep
) -> QueryResponse:
    if services.repository.stats()["chunks"] == 0:
        raise HTTPException(status_code=409, detail="Knowledge base is empty; run ingestion first")
    try:
        return await services.workflow.invoke(request)
    except Exception as exc:
        # Provider payloads and credentials are intentionally not included in the error.
        raise HTTPException(status_code=502, detail=f"Upstream model request failed: {type(exc).__name__}") from exc


@app.post("/v1/ingest", response_model=IngestResult)
async def ingest(services: ServiceDep) -> IngestResult:
    try:
        return await services.ingestion.run()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {type(exc).__name__}") from exc


@app.post("/v1/feedback", status_code=204)
async def feedback(
    payload: FeedbackRequest, services: ServiceDep
) -> None:
    services.repository.add_feedback(payload.request_id, payload.category, payload.note)
