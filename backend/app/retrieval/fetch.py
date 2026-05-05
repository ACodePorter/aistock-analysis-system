import asyncio
import os
from typing import Dict, Iterable, Optional

import httpx

from .cache import TTLFileCache


class WebFetchClient:
    def __init__(self):
        self.timeout = float(os.getenv("WEB_FETCH_TIMEOUT", "20"))
        self.retries = int(os.getenv("WEB_FETCH_RETRIES", "2"))
        self.cache = TTLFileCache(
            root_dir=os.path.join(os.getenv("WEB_CACHE_DIR", "cache"), "pages"),
            default_ttl_seconds=int(os.getenv("WEB_FETCH_CACHE_TTL", "3600")),
        )

    async def fetch(self, url: str) -> Optional[str]:
        cached = self.cache.get("html", url)
        if isinstance(cached, str) and cached:
            return cached

        headers = {"User-Agent": os.getenv("WEB_FETCH_USER_AGENT", "Mozilla/5.0")}
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            last_error = None
            for _ in range(max(1, self.retries + 1)):
                try:
                    resp = await client.get(url, headers=headers)
                    resp.raise_for_status()
                    text = resp.text
                    if text:
                        self.cache.set("html", url, text)
                        return text
                except Exception as exc:
                    last_error = exc
                    await asyncio.sleep(0.25)
            if last_error:
                return None
        return None

    async def fetch_many(self, urls: Iterable[str], concurrency: int = 4) -> Dict[str, Optional[str]]:
        sem = asyncio.Semaphore(max(1, concurrency))
        out: Dict[str, Optional[str]] = {}

        async def _run(u: str) -> None:
            async with sem:
                out[u] = await self.fetch(u)

        await asyncio.gather(*[_run(u) for u in urls], return_exceptions=False)
        return out
