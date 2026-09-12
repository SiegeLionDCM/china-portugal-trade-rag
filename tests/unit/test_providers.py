import json

import httpx
import pytest

from trade_copilot.config import Settings
from trade_copilot.providers import DeepSeekClient, SiliconFlowClient


@pytest.mark.asyncio
async def test_siliconflow_embedding_and_rerank_contract() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]})
        assert payload["instruction"]
        return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.8}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = Settings(siliconflow_api_key="test-secret")
    provider = SiliconFlowClient(settings, client)
    assert await provider.embed(["texto"]) == [[0.1, 0.2]]
    assert await provider.rerank("query", ["document"], 1) == [(0, 0.8)]
    assert all(request.headers["authorization"] == "Bearer test-secret" for request in requests)
    await client.aclose()


@pytest.mark.asyncio
async def test_siliconflow_retries_transport_timeout() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("temporary timeout", request=request)
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1]}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = SiliconFlowClient(Settings(siliconflow_api_key="test-secret"), client)
    assert await provider.embed(["texto"]) == [[0.1]]
    assert attempts == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_deepseek_json_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-v4-flash"
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"answer":"ok [1]"}'}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = DeepSeekClient(Settings(deepseek_api_key="test-secret"), client)
    assert await provider.generate_json("system", "user") == {"answer": "ok [1]"}
    await client.aclose()
