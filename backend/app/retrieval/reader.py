import os
import re
from typing import Optional

from bs4 import BeautifulSoup
import trafilatura

from .cache import TTLFileCache


class WebReader:
    def __init__(self):
        self.cache = TTLFileCache(
            root_dir=os.path.join(os.getenv("WEB_CACHE_DIR", "cache"), "articles"),
            default_ttl_seconds=int(os.getenv("WEB_READ_CACHE_TTL", "7200")),
        )

    def extract(self, url: str, html: str) -> Optional[str]:
        cache_key = f"{url}|{len(html or '')}"
        cached = self.cache.get("text", cache_key)
        if isinstance(cached, str) and cached:
            return cached

        text = trafilatura.extract(
            html or "",
            include_comments=False,
            include_tables=False,
            output_format="txt",
        )
        if not text:
            soup = BeautifulSoup(html or "", "lxml")
            for node in soup(["script", "style", "noscript"]):
                node.decompose()
            text = soup.get_text(" ", strip=True)

        if not text:
            return None
        cleaned = self._clean(text)
        if len(cleaned) < 20:
            return None
        self.cache.set("text", cache_key, cleaned)
        return cleaned

    def _clean(self, text: str) -> str:
        s = re.sub(r"\s+", " ", text or "").strip()
        return s[:12000]
