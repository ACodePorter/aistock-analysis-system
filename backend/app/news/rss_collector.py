"""
RSS 财经新闻采集器 - 使用 feedparser 并返回标准化条目
"""
import asyncio
import os
from typing import List, Dict, Any
import feedparser

# RSSHub base URL (use container DNS 'rsshub:1200' when running inside docker-compose,
# otherwise default to localhost for local runs). Allow override via env var.
DEFAULT_RSSHUB = os.getenv("RSSHUB_URL", os.getenv("RSSHUB_BASE", "http://localhost:1200"))


class RSSNewsCollector:
    """RSS 财经新闻采集器"""

    FEEDS = {
        "caixin": f"{DEFAULT_RSSHUB}/caixin/article/latest",
        "yicai": f"{DEFAULT_RSSHUB}/yicai/brief",
        "cls": f"{DEFAULT_RSSHUB}/cls/telegraph",
        "wallstreetcn": f"{DEFAULT_RSSHUB}/wallstreetcn/live/global",
        "eastmoney_report": f"{DEFAULT_RSSHUB}/eastmoney/report",
        "xueqiu_hot": f"{DEFAULT_RSSHUB}/xueqiu/hots",
        "sina_finance": "https://feedx.net/rss/sinafinance.xml",
    }

    async def collect_all(self) -> List[Dict[str, Any]]:
        tasks = [self._fetch_feed(name, url) for name, url in self.FEEDS.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        articles = []
        for result in results:
            if isinstance(result, list):
                articles.extend(result)
        return articles

    async def _fetch_feed(self, name: str, url: str) -> List[Dict[str, Any]]:
        try:
            loop = asyncio.get_running_loop()
            # feedparser is blocking; run in thread
            feed = await loop.run_in_executor(None, feedparser.parse, url)
            entries = []
            for entry in feed.entries[:30]:
                entries.append({
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "summary": entry.get("summary", ""),
                    "published": entry.get("published", entry.get("updated", "")),
                    "source": name,
                })
            return entries
        except Exception:
            return []
