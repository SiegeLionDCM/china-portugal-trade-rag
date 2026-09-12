from __future__ import annotations

import asyncio
import json

import httpx

from trade_copilot.config import Settings


class DeepSeekClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client

    async def generate_json(self, system: str, user: str) -> dict:
        if not self.settings.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured")
        owned = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.settings.request_timeout_seconds)
        try:
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    response = await client.post(
                        f"{self.settings.deepseek_base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.settings.deepseek_api_key.get_secret_value()}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self.settings.llm_model,
                            "messages": [
                                {"role": "system", "content": system},
                                {"role": "user", "content": user},
                            ],
                            "temperature": 0.1,
                            "max_tokens": self.settings.llm_max_tokens,
                            "response_format": {"type": "json_object"},
                            "stream": False,
                        },
                    )
                    if response.status_code in {429, 500, 502, 503, 504}:
                        response.raise_for_status()
                    response.raise_for_status()
                    content = response.json()["choices"][0]["message"]["content"]
                    if not content:
                        raise ValueError("DeepSeek returned empty JSON content")
                    return json.loads(content)
                except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    last_error = exc
                    if attempt < 2:
                        await asyncio.sleep(0.5 * (2**attempt))
            raise RuntimeError("DeepSeek did not return valid JSON after retries") from last_error
        finally:
            if owned:
                await client.aclose()
