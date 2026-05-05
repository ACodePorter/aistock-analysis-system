import asyncio
import os
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests
from bs4 import BeautifulSoup

from .cache import TTLFileCache


class WebSearchClient:
    def __init__(self):
        self.timeout = int(os.getenv("WEB_SEARCH_TIMEOUT", "20"))
        self.provider_order = [
            p.strip() for p in os.getenv(
                "WEB_SEARCH_PROVIDER_ORDER",
                "duckduckgo_html,duckduckgo_lite"
            ).split(",") if p.strip()
        ]
        cache_dir = os.getenv("WEB_CACHE_DIR", "cache")
        self.cache = TTLFileCache(
            root_dir=os.path.join(cache_dir, "search"),
            default_ttl_seconds=int(os.getenv("WEB_SEARCH_CACHE_TTL", "900")),
        )

    async def search(
        self,
        query: str,
        top_k: int = 8,
        category: str = "general",
        time_range: Optional[str] = None,
        language: Optional[str] = None,
        engines: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.search_sync(
                query=query,
                top_k=top_k,
                category=category,
                time_range=time_range,
                language=language,
                engines=engines,
            ),
        )

    def search_sync(
        self,
        query: str,
        top_k: int = 8,
        category: str = "general",
        time_range: Optional[str] = None,
        language: Optional[str] = None,
        engines: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        cache_key = f"{query}|{top_k}|{category}|{time_range}|{language}|{engines}"
        cached = self.cache.get("query", cache_key)
        if isinstance(cached, list):
            return cached[:top_k]

        last_error: Optional[Exception] = None
        for provider in self.provider_order:
            try:
                if provider == "duckduckgo_html":
                    results = self._search_duckduckgo_html(query, top_k)
                elif provider == "duckduckgo_lite":
                    results = self._search_duckduckgo_lite(query, top_k)
                else:
                    continue
                if results:
                    self.cache.set("query", cache_key, results)
                    return results[:top_k]
            except Exception as exc:
                last_error = exc
                continue

        if last_error:
            raise last_error
        return []

    def _search_duckduckgo_html(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        response = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        out: List[Dict[str, Any]] = []
        for item in soup.select(".result")[: max(top_k * 2, 10)]:
            link = item.select_one(".result__a")
            if not link:
                continue
            raw_url = link.get("href")
            url = self._normalize_result_url(raw_url)
            title = link.get_text(" ", strip=True)
            if not url or not title:
                continue
            snippet_node = item.select_one(".result__snippet")
            snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
            out.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "source": "duckduckgo_html",
                    "published": None,
                }
            )
            if len(out) >= top_k:
                break
        return out

    def _search_duckduckgo_lite(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        response = requests.get(
            f"https://lite.duckduckgo.com/lite/?q={quote_plus(query)}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        out: List[Dict[str, Any]] = []
        for link in soup.select("a"):
            href = (link.get("href") or "").strip()
            url = self._normalize_result_url(href)
            title = link.get_text(" ", strip=True)
            if not url or not title:
                continue
            if any(x in url for x in ("duckduckgo.com/lite", "/lite/")):
                continue
            out.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": "",
                    "source": "duckduckgo_lite",
                    "published": None,
                }
            )
            if len(out) >= top_k:
                break
        return out

    def _normalize_result_url(self, url: Optional[str]) -> Optional[str]:
        """Normalize provider URLs and unpack DuckDuckGo redirect links."""
        if not url:
            return None

        normalized = url.strip()
        if not normalized:
            return None

        if normalized.startswith("//"):
            normalized = f"https:{normalized}"

        parsed = urlparse(normalized)
        host = (parsed.netloc or "").lower()
        path = parsed.path or ""

        # DuckDuckGo redirect links usually carry the target URL in `uddg`.
        if "duckduckgo.com" in host and path.startswith("/l/"):
            query = parse_qs(parsed.query)
            uddg_values = query.get("uddg")
            if uddg_values:
                target = unquote(uddg_values[0]).strip()
                if target.startswith("//"):
                    target = f"https:{target}"
                if target.startswith(("http://", "https://")):
                    return target

        if normalized.startswith(("http://", "https://")):
            return normalized
        return None
