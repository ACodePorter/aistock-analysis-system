"""
PageCrawlAgent: 将网页爬虫封装为“Agent”，负责：
- 抓取指定页面的 HTML、正文、实体与关键词（复用 NewsContentCrawler）
- 从页面中提取超链接并进行打分分类（公告/研报/交易所/详情/媒体等）
- 识别可能的图表/K线/走势类图片（img/svg），可按需下载前 N 张到本地
- 可选对高分潜在链接进行轻探测（probe），将失败链接写入 Mongo 错误日志供人工审核
- 产出结构化报告，便于后续调度和人工复核

注意：本 Agent 不负责批量站点渲染（如 JS 动态生成的图表），仅做静态页面层面的尽力抽取。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from pathlib import Path
import os
import re
import logging
from datetime import datetime

from bs4 import BeautifulSoup

from ..news.news_crawler import NewsContentCrawler
from ..utils.mongo_storage import get_storage

logger = logging.getLogger(__name__)


def _ensure_dir(p: Path):
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _classify_link(url: str, text: str, symbol: Optional[str], company: Optional[str]) -> Tuple[str, int]:
    """根据 URL/锚文本的关键词进行粗分类和打分（越高越相关）。"""
    u = (url or "").lower()
    t = (text or "").lower()
    score = 0
    category = "other"
    def hit(s: str) -> bool:
        return (s in u) or (s in t)

    keywords = [
        ("announcement", ["公告", "通告", "临时公告", "披露", "停牌", "复牌", "annual report", "semi-annual", "seasonal", "财报"]),
        ("research", ["研报", "评级", "上调", "下调", "buy", "neutral", "sell", "研究"]),
        ("exchange", ["cninfo", "cninfo.com.cn", "shse", "szse", "深交所", "上交所", "交易所", "巨潮"]),
        ("detail", ["detail", "news", "article", "doc", "notice", "bulletin", "vcb_allbulletindetail", "finalpage"]),
        ("pdf", [".pdf"]),
        ("media", ["eastmoney", "sina", "xueqiu", "wallstreetcn", "yicai", "caixin", "thepaper", "ifeng"]) 
    ]

    for cat, ks in keywords:
        for k in ks:
            if hit(k):
                score += 2 if cat in ("announcement", "exchange", "detail", "pdf") else 1
                category = cat if score >= 2 else category
                break

    # 股票符号/公司名提升权重
    if symbol and symbol.lower().split(".")[0] in (u + t):
        score += 3
    if company and company.lower() in (u + t):
        score += 2
    # 锚文本长度适中也有帮助（太短多为导航）
    if 6 <= len(t) <= 60:
        score += 1
    return category, score


def _looks_like_chart(img_src: str, alt: str = "", title: str = "", width: Optional[int] = None, height: Optional[int] = None) -> bool:
    s = (img_src or "").lower() + (alt or "").lower() + (title or "").lower()
    if any(x in s for x in ["chart", "kline", "k-line", "line", "ohlc", "candlestick", "走势", "走势图", "k线", "分时", "行情"]):
        return True
    # 粗略根据尺寸判断（宽高中任一较大）
    try:
        if (width and width >= 300) or (height and height >= 200):
            return True
    except Exception:
        pass
    return False


@dataclass
class PageCrawlOptions:
    symbol: Optional[str] = None
    company_name: Optional[str] = None
    probe_top_k: int = 5  # 轻探测前 K 条候选链接
    download_charts: bool = True
    max_download_charts: int = 5
    assets_dir: str = "agent_assets/charts"


class PageCrawlAgent:
    def __init__(self, options: Optional[PageCrawlOptions] = None):
        self.options = options or PageCrawlOptions()

    async def run(self, url: str) -> Dict[str, Any]:
        """执行单页 Agent 爬取与分析，返回结构化报告。"""
        opts = self.options
        now_iso = datetime.utcnow().isoformat()
        report: Dict[str, Any] = {
            "agent": "page_crawl_agent",
            "version": 1,
            "url": url,
            "domain": urlparse(url).netloc,
            "crawled_at": now_iso,
            "symbol": (opts.symbol or "").upper() or None,
            "company_name": opts.company_name,
            "title": None,
            "summary": None,
            "content": None,
            "entities": [],
            "keywords": [],
            "links": [],
            "top_candidates": [],
            "images": [],
            "charts_saved": [],
            "probe_results": [],
            "errors": [],
        }

        async with NewsContentCrawler() as crawler:
            # 1) 主体内容抓取（允许重复，确保可解析）
            article = await crawler.crawl_article(url, skip_duplicate_check=True)
            if article.get("status") != "success":
                report["errors"].append({"stage": "fetch", "detail": article})
                # 尽量继续尝试获取原始 HTML 供链接发现
            report["title"] = article.get("title")
            report["summary"] = article.get("summary")
            report["content"] = article.get("content")
            report["entities"] = article.get("entities") or []
            report["keywords"] = article.get("keywords") or []

            # 2) 获取原始 HTML 并提取链接/图片
            html, fetch_debug = await crawler._fetch_content(url)
            if not html:
                report["errors"].append({"stage": "fetch_html", "detail": fetch_debug})
                return report
            soup = BeautifulSoup(html, "html.parser")

            # 提取链接
            links: List[Dict[str, Any]] = []
            base = url
            for a in soup.find_all("a", href=True):
                href = a.get("href")
                resolved = urljoin(base, href)
                text = (a.get_text(strip=True) or "")[:200]
                cat, score = _classify_link(resolved, text, opts.symbol, opts.company_name)
                links.append({
                    "url": resolved,
                    "text": text,
                    "category": cat,
                    "score": score
                })
            # 去重
            seen = set()
            uniq_links = []
            for l in sorted(links, key=lambda x: x["score"], reverse=True):
                key = (l["url"], l["text"])  # 保留相同 URL 不同锚文本的一个
                if l["url"] in seen:
                    continue
                seen.add(l["url"])
                uniq_links.append(l)
            report["links"] = uniq_links

            # 提取图片（含简单图表识别）
            images: List[Dict[str, Any]] = []
            for img in soup.find_all("img"):
                src = img.get("src") or ""
                if not src:
                    continue
                resolved = urljoin(base, src)
                alt = img.get("alt") or ""
                title = img.get("title") or ""
                w = None
                h = None
                try:
                    w = int(img.get("width")) if img.get("width") else None
                    h = int(img.get("height")) if img.get("height") else None
                except Exception:
                    w = h = None
                is_chart = _looks_like_chart(resolved, alt, title, w, h)
                images.append({
                    "url": resolved,
                    "alt": alt,
                    "title": title,
                    "width": w,
                    "height": h,
                    "is_chart_like": is_chart,
                })
            # inline svg
            for svg in soup.find_all("svg"):
                cls = " ".join(svg.get("class", []) or [])
                is_chart = any(k in cls.lower() for k in ["chart", "kline", "plot", "echarts", "highcharts"]) or len(svg.find_all("path")) >= 5
                images.append({
                    "inline_svg": True,
                    "class": cls,
                    "is_chart_like": is_chart,
                })
            report["images"] = images

            # 3) 候选链接筛选（按分数）
            top_candidates = uniq_links[: max(10, opts.probe_top_k)]
            report["top_candidates"] = top_candidates

            # 4) 可选下载图表图片
            charts_saved: List[str] = []
            if opts.download_charts:
                charts = [im for im in images if im.get("is_chart_like") and isinstance(im.get("url"), str)]
                charts = charts[: opts.max_download_charts]
                target_dir = Path(os.getcwd()) / opts.assets_dir
                _ensure_dir(target_dir)
                for im in charts:
                    try:
                        img_url = im["url"]
                        # 下载二进制
                        resp = await crawler.session.get(img_url)
                        resp.raise_for_status()
                        # 推断扩展名
                        ext = ""
                        ct = resp.headers.get("Content-Type", "")
                        if "png" in ct:
                            ext = ".png"
                        elif "jpeg" in ct or "jpg" in ct:
                            ext = ".jpg"
                        elif "svg" in ct:
                            ext = ".svg"
                        else:
                            # 从 URL 粗略取
                            m = re.search(r"\.(png|jpg|jpeg|svg)(?:\?|$)", img_url, re.I)
                            ext = f".{m.group(1).lower()}" if m else ".img"
                        fn = f"chart_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}" + ext
                        out_path = target_dir / fn
                        out_path.write_bytes(resp.content)
                        charts_saved.append(str(out_path))
                    except Exception as e:
                        report["errors"].append({"stage": "download_chart", "url": im.get("url"), "error": str(e)})
            report["charts_saved"] = charts_saved

            # 5) 轻探测前 K 条候选链接并记录失败
            probe_results: List[Dict[str, Any]] = []
            for cand in top_candidates[: opts.probe_top_k]:
                u = cand["url"]
                try:
                    r = await crawler.session.get(u, headers={"User-Agent": crawler.user_agents[0]}, timeout=crawler.timeout)
                    ok = (200 <= r.status_code < 400)
                    probe_results.append({"url": u, "status": r.status_code, "ok": ok})
                    if not ok:
                        try:
                            storage = await get_storage()
                            await storage.log_news_error("crawl", url=u, domain=urlparse(u).netloc, symbol=opts.symbol, message=f"probe status {r.status_code}")
                        except Exception:
                            pass
                except Exception as e:
                    probe_results.append({"url": u, "status": None, "ok": False, "error": str(e)})
                    try:
                        storage = await get_storage()
                        await storage.log_news_error("crawl", url=u, domain=urlparse(u).netloc, symbol=opts.symbol, message=str(e))
                    except Exception:
                        pass
            report["probe_results"] = probe_results

        return report
