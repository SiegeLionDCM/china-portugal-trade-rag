from __future__ import annotations

import asyncio
from collections.abc import Sequence

import httpx

from trade_copilot.config import Settings


class ProviderConfigurationError(RuntimeError):
    pass


class SiliconFlowClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client

    def _headers(self) -> dict[str, str]:
        if not self.settings.siliconflow_api_key:
            raise ProviderConfigurationError("SILICONFLOW_API_KEY is not configured")
        return {
            "Authorization": f"Bearer {self.settings.siliconflow_api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }

    async def _post(self, path: str, payload: dict) -> dict:
        owned = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.settings.request_timeout_seconds)
        try:
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    response = await client.post(
                        f"{self.settings.siliconflow_base_url}{path}",
                        headers=self._headers(),
                        json=payload,
                    )
                except httpx.TransportError as exc:
                    last_error = exc
                    if attempt < 2:
                        await asyncio.sleep(0.5 * (2**attempt))
                        continue
                    raise RuntimeError("SiliconFlow transport failed after retries") from exc
                if response.status_code not in {429, 503, 504}:
                    response.raise_for_status()
                    return response.json()
                last_error = httpx.HTTPStatusError(
                    "Transient SiliconFlow response",
                    request=response.request,
                    response=response,
                )
                if attempt < 2:
                    await asyncio.sleep(0.5 * (2**attempt))
            raise RuntimeError("SiliconFlow request failed after retries") from last_error
        finally:
            if owned:
                await client.aclose()

    async def embed(self, texts: Sequence[str], batch_size: int = 32) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = list(texts[start : start + batch_size])
            payload = {"model": self.settings.embedding_model, "input": batch, "encoding_format": "float"}
            data = await self._post("/embeddings", payload)
            ordered = sorted(data["data"], key=lambda item: item["index"])
            vectors.extend(item["embedding"] for item in ordered)
        return vectors

    async def rerank(self, query: str, documents: Sequence[str], top_n: int) -> list[tuple[int, float]]:
        if not documents:
            return []
        payload = {
            "model": self.settings.rerank_model,
            "query": query,
            "documents": list(documents),
            "top_n": min(top_n, len(documents)),
            "return_documents": False,
        }
        if "Qwen3-Reranker" in self.settings.rerank_model:
            payload["instruction"] = (
                "Rank passages by whether they directly and currently support an answer to the "
                "trade-compliance question. Prefer jurisdiction-matched authoritative sources."
            )
        data = await self._post("/rerank", payload)
        return [(item["index"], float(item["relevance_score"])) for item in data["results"]]
