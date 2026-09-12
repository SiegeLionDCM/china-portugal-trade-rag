from __future__ import annotations

import asyncio
import json

from trade_copilot.service import get_services


async def run() -> None:
    services = get_services()
    try:
        result = await services.ingestion.run()
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
        if result.errors:
            raise SystemExit(1)
    finally:
        await services.aclose()
        get_services.cache_clear()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
