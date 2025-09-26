"""
新闻采集与处理服务模块说明
概述
本模块实现了一个面向财经/股票新闻的异步搜索、抓取、正文抽取、语义分析与入库流程。设计目标是：
- 从 SearXNG 等聚合搜索引擎获取原始新闻结果；
- 对候选 URL 做启发式过滤与去重，避免抓取列表页、行情页与 JS 门户；
- 对 HTML/PDF 做稳健的正文抽取（支持 readability、选择器回退、域名定制解析）；
- 支持 LLM 驱动的深度分析（分类、关键字、实体、情感、关联股票），并能回退到本地简单分析器；
- 将最终生成的 NewsArticle 实例交由上层保存到数据库；
- 支持调度器按 watchlist 周期拉取并存储新闻。
主要类与职责
- NewsSearchService
    - 与 SearXNG（或兼容 API）通信以检索新闻条目；
    - 提供 search_news、search_stock_news、search_industry_news 等便捷接口；
    - 将检索操作记录到 SearchLog（若 DB 不可用则回退到控制台打印）。
- NewsProcessor
    - 负责从搜索结果到 NewsArticle 对象的完整处理流程：
        - URL 合法性/文章性判别（_is_article_like_url）
        - HTML/PDF 抓取与解码（_http_get、_decode_html）
        - 正文抽取（readability、CSS selector、body fallback），以及域名定制解析（如新浪 VIP）
        - 文本清洗、占位符/噪声识别与修复（_clean_text、_strip_placeholders、_looks_like_placeholder）
        - 编码修复（处理常见的 mojibake、latin1→utf8 修复和 GBK/GB18030 回退）
        - 发布时间解析（结果字段、meta/time 元素、JSON-LD、URL 模式）
        - 去重检测（依赖 NewsDeduplicator）
        - LLM 分析集成（LLMNewsProcessor，可选；失败或禁用时使用 _analyze_content）
        - 摘要生成（保证非空、长度限制）和关联股票提取
    - 提供多层次的后备策略，以提高在复杂站点/不规范页面上的鲁棒性。
- NewsScheduler
    - 定期遍历数据库 Watchlist，调用检索与处理流程，并将新增文章保存到 DB。
辅助与策略
- URL 过滤与动态规则
    - 模块内置大量针对财经门户的非文章子串（_default_non_article_substrings）以减少噪声；
    - 支持从 DB 加载动态允许/阻断子串（NewsURLPattern），具有 TTL 缓存（reload_url_filters）；
    - 支持基于环境变量的全局 allowlist/blocklist（NEWS_URL_ALLOWLIST, NEWS_URL_BLOCKLIST）。
- 抓取与网络鲁棒性
    - 带重试、User-Agent 轮换、Referer、可选代理、退避策略；
    - 对常见 HTTP 失败（403/429/5xx）做重试；
    - SSL/TLS 兼容性回退：可尝试降低 OpenSSL seclevel、允许不安全证书或回退到 HTTP（通过环境变量配置）。
- 正文抽取细节
    - 优先使用 readability（若可用），再尝试常见 CSS 选择器，最后回退到 body 文本；
    - 针对 PDF 自动识别并使用 pdfminer 或 pypdf 提取文本；
    - 对特定域（如新浪 VIP）提供专门解析器以抓取公告/表格摘要。
- 语义分析与 LLM
    - 可通过环境变量切换是否启用 LLM（NEWS_USE_LLM）；
    - LLM 返回结果映射到内部结构（category, keywords, entities, sentiment 等）；
    - 若 LLM 不可用或失败，将调用本地的 _analyze_content 做简单的关键词与情感估算。
配置（主要环境变量）
- SEARXNG_URL：SearXNG 服务地址（默认 http://localhost:10000）
- SEARXNG_TIMEOUT：SearXNG 请求超时（秒）
- NEWS_HTTP_PROXY：可选 HTTP 代理
- NEWS_FETCH_RETRIES / NEWS_FETCH_BACKOFF：抓取重试次数与回退间隔
- NEWS_USE_LLM：是否启用 LLM 分析（true/false）
- NEWS_URL_ALLOWLIST / NEWS_URL_BLOCKLIST：逗号分隔的 URL 子串白/黑名单
- NEWS_URL_FILTER_TTL：动态 URL 规则缓存 TTL（秒）
- NEWS_MIN_CN_RATIO / NEWS_ALLOW_NON_CN：中文比例与是否强制允许非中文
- NEWS_SSL_ALLOW_INSECURE / NEWS_SSL_FORCE_SECLEVEL1 / NEWS_SSL_HTTP_FALLBACK_HOSTS：SSL/TLS 回退与不安全选项
持久化与依赖模型
模块与下列 ORM 模型交互：NewsArticle、NewsSource、NewsKeyword、SearchLog、NewsCategory、SentimentType、Watchlist、NewsURLPattern。数据库会话通过 .db.SessionLocal 提供。去重逻辑委托给新闻去重器 NewsDeduplicator。
错误处理与可观测性
- 使用 NewsMetrics 打点关键事件（过滤、抽取失败、LLM 成功/失败、去重等）；
- 搜索/抓取/解析错误尽量降级处理（打印日志并跳过），避免整个任务失败；
- DB 不可用时，搜索记录回退到控制台输出而不抛异常。
注意事项与限制
- 本模块对中文财经内容做了大量启发式优化，但并非针对所有域名完美适配；对于高度 JS 渲染页面（需浏览器执行）效果有限；
- 为兼顾可用性，提供了 SSL 降级与不安全模式，这些选项在生产环境应谨慎开启；
- LLM 分析的使用依赖外部实现 LLMNewsProcessor，需配置相应凭据与实现；
- 摘要与正文均有长度上限（如内容截断到 8000 字），以避免存储/传输过大。
示例流程（简要）
1. NewsScheduler 查询 Watchlist 获取股票列表；
2. 对每个股票调用 NewsSearchService.search_stock_news 获取候选结果；
3. NewsProcessor.process_search_results 对结果进行过滤、抓取并生成 NewsArticle；
4. 去重并将新文章写入数据库。

"""

import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from urllib.parse import urljoin, urlparse

import httpx
import ssl
from bs4 import BeautifulSoup
try:
    from readability import Document
    READABILITY_AVAILABLE = True
except ImportError:
    READABILITY_AVAILABLE = False
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from .models import (
    NewsArticle, NewsSource, NewsKeyword, SearchLog, 
    NewsCategory, SentimentType, Watchlist
)
from .db import get_session
from .metrics import NewsMetrics
from .models import NewsURLPattern
from .llm_processor import LLMNewsProcessor, NewsAnalysisResult
from .news_deduplication import NewsDeduplicator


class NewsSearchService:
    def __init__(self, searxng_url: str = None):
        self.searxng_url = searxng_url or os.getenv("SEARXNG_URL", "http://localhost:10000")
        self.timeout = int(os.getenv("SEARXNG_TIMEOUT", "30"))
        
    async def search_news(
        self, 
        query: str, 
        category: str = "general",
        time_range: Optional[str] = None,
        max_results: int = 20
    ) -> List[Dict[str, Any]]:
        """
        使用 SearXNG 搜索新闻

        Args:
            query: 查询词（建议包含股票/行业/政策等关键词组合）
            category: SearXNG 分类（默认 general）
            time_range: 时间窗（day/week/month）
            max_results: 限制返回条数（默认20）

        Returns:
            List[Dict]: 原始搜索结果列表（不改动字段，保留来源链接）
        """
        search_params = {
            "q": query,
            "categories": category,
            "format": "json",
            "language": "zh-CN",
            "time_range": time_range or "week",
            "engines": "bing news,google news,baidu news"
        }
        
        start_time = datetime.utcnow()
        success = True
        error_message = None
        results = []
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.searxng_url}/search",
                    data=search_params
                )
            response.raise_for_status()
            
            data = response.json()
            results = data.get("results", [])[:max_results]
            
            # Log search
            await self._log_search(
                query=query,
                query_type="api",
                source_engine="searxng",
                results_count=len(results),
                processing_time=(datetime.utcnow() - start_time).total_seconds(),
                success=True
            )
            
            return results
            
        except Exception as e:
            error_message = str(e)
            success = False
            
            # Log failed search
            await self._log_search(
                query=query,
                query_type="api",
                source_engine="searxng",
                results_count=0,
                processing_time=(datetime.utcnow() - start_time).total_seconds(),
                success=False,
                error_message=error_message
            )
            
            raise Exception(f"News search failed: {error_message}")
    
    async def search_stock_news(self, symbol: str, company_name: str = None) -> List[Dict[str, Any]]:
        """
        针对单个股票进行新闻搜索（包含股票代码与公司名双关键字）

        - 会优先查询“股票+财经”等组合，提升命中财经新闻的概率；
        - 返回的结果仍为原始结构，后续由处理器做正文抽取、去重与摘要。
        """
        queries = [symbol]
        if company_name:
            queries.append(company_name)
            
        all_results = []
        for query in queries:
            try:
                results = await self.search_news(
                    query=f"{query} 股票 财经",
                    category="general",
                    time_range="week",
                    max_results=10
                )
                all_results.extend(results)
            except Exception as e:
                print(f"Failed to search news for {query}: {e}")
                
        # Remove duplicates by URL
        seen_urls = set()
        unique_results = []
        for result in all_results:
            url = result.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_results.append(result)
                
        return unique_results[:20]
    
    async def search_industry_news(self, industry: str, keywords: List[str] = None) -> List[Dict[str, Any]]:
        """
        Search news for industry and policy keywords
        """
        query_parts = [industry]
        if keywords:
            query_parts.extend(keywords)
            
        query = " ".join(query_parts) + " 行业 政策 新闻"
        
        return await self.search_news(
            query=query,
            category="general",
            time_range="week",
            max_results=15
        )
    
    async def _log_search(
        self,
        query: str,
        query_type: str,
        source_engine: str,
        results_count: int,
        processing_time: float,
        success: bool,
        error_message: str = None
    ):
        """Log search operation - safe fallback when database unavailable"""
        try:
            from .db import SessionLocal
            session = SessionLocal()
            try:
                search_log = SearchLog(
                    query=query,
                    query_type=query_type,
                    source_engine=source_engine,
                    results_count=results_count,
                    processing_time=processing_time,
                    success=success,
                    error_message=error_message
                )
                session.add(search_log)
                session.commit()
            finally:
                session.close()
        except Exception as db_error:
            # Database unavailable - log to console instead
            print(f"🔍 Search Log (DB unavailable): query='{query}', results={results_count}, success={success}")
            if error_message:
                print(f"   Error: {error_message}")
            # Don't raise exception - continue without database logging


class NewsProcessor:
    def __init__(self):
        # Default headers to reduce 403/anti-bot blocks
        self._http_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
            "Accept-Encoding": "gzip, deflate, br"
        }
        # Rotate user-agents across retries
        self._ua_pool = [
            # Desktop Chrome variants
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
            # Mobile Safari
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
        ]
        # Optional HTTP proxy (e.g., http://127.0.0.1:7890). Can be set via NEWS_HTTP_PROXY env
        self._proxies = os.getenv("NEWS_HTTP_PROXY") or None
        # Retry policy
        self._retry_attempts = int(os.getenv("NEWS_FETCH_RETRIES", "3"))
        self._retry_backoff = float(os.getenv("NEWS_FETCH_BACKOFF", "0.6"))
        # LLM usage toggle via env (default true)
        self._use_llm = os.getenv("NEWS_USE_LLM", "true").lower() in ("1", "true", "yes")
        # Optional domain/path allowlist and blocklist (comma-separated substrings)
        # Example: NEWS_URL_ALLOWLIST="tw.stock.yahoo.com/news/,finance.yahoo.com/news/" 
        #          NEWS_URL_BLOCKLIST="/quote/,/keywords/,/tag/"
        allow_raw = os.getenv("NEWS_URL_ALLOWLIST", "").strip()
        block_raw = os.getenv("NEWS_URL_BLOCKLIST", "").strip()
        self._url_allowlist = [s.strip().lower() for s in allow_raw.split(",") if s.strip()] if allow_raw else []
        self._url_blocklist = [s.strip().lower() for s in block_raw.split(",") if s.strip()] if block_raw else []
        # Built-in default non-article URL substrings (listing/quote/company-hub/JS-gated) to be dropped pre-ingest
        # Derived from observed noise families (Sina corp lists, Moomoo/Futunn quote pages, Eastmoney UGC, calendars, etc.)
        self._default_non_article_substrings = [
            # Sina corp listing/bulletin/company hubs
            "vip.stock.finance.sina.com.cn/corp/go.php/vcb_bulletin/",
            "vip.stock.finance.sina.com.cn/corp/go.php/vcb_allbulletin/",
            "vip.stock.finance.sina.com.cn/corp/view/vcb_allnews",
            "vip.stock.finance.sina.com.cn/corp/go.php/vcb_allnews/",
            "vip.stock.finance.sina.com.cn/corp/go.php/vci_corpmanager/",
            "money.finance.sina.com.cn/corp/go.php/vci_corpmanager/",
            "money.finance.sina.com.cn/corp/go.php/vcb_bulletin/",
            "money.finance.sina.com.cn/corp/go.php/vcb_allbulletin/",
            "finance.sina.com.cn/realstock/company/",
            # NOTE: We keep generic corp hubs blocked by default to avoid noise,
            # but will special-case allow concrete symbol pages via _is_article_like_url
            # and handle content via a domain-specific extractor.
            "vip.stock.finance.sina.com.cn/corp/go.php/vCB_FinManDiv/",
            "vip.stock.finance.sina.com.cn/corp/go.php/",
            # Moomoo/Futunn stock hubs (JS-gated)
            "moomoo.com/stock/",  # combined with /financials- later
            "moomoo.com/hant/stock/",
            "moomoo.com/hans/stock/",
            "www.futunn.com/stock/",
            # Eastmoney quote/UGC/data hubs
            "quote.eastmoney.com/unify/r/",
            "quote.eastmoney.com/concept/",
            "guba.eastmoney.com/",
            "caifuhao.eastmoney.com/",
            "emdata.eastmoney.com/",
            # AASTOCKS topic stub
            "aastocks.com/news/china-hot-topic-content.aspx",
            # Obvious list/calendar hubs
            "www.cls.cn/investkalendar",
            "money.163.com/latest/",
            "rili.jin10.com",
            "www.cs.com.cn/xwzx/hg/",
            "xuangutong.com.cn/live",
            "xiaoyuzhoufm.com/podcast/",
            "www.globalxetfs.com.hk/funds/",
            # Reuters company profile/hub
            "www.reuters.com/markets/companies/",
            # Tencent quote hub
            "gu.qq.com/",
            # JRJ summary hubs
            "summary.jrj.com.cn/",
        ]
        # Deduplicator
        self._deduplicator = NewsDeduplicator()
        # Dynamic URL filters (loaded from DB with TTL)
        self._dynamic_loaded_at: Optional[datetime] = None
        self._dynamic_ttl_secs: int = int(os.getenv("NEWS_URL_FILTER_TTL", "300"))
        self._dynamic_block_substrings: List[str] = []
        self._dynamic_allow_substrings: List[str] = []
        try:
            self.reload_url_filters(force=True)
        except Exception:
            # Safe: continue with built-ins only
            pass
        # Language and relevance thresholds
        self._min_cn_ratio = float(os.getenv("NEWS_MIN_CN_RATIO", "0.15"))
        self._force_allow_non_cn = os.getenv("NEWS_ALLOW_NON_CN", "false").lower() in ("1", "true", "yes")
        # SSL/TLS fallback options
        # Allow insecure certificate verification on fallback (NOT recommended in production)
        self._ssl_allow_insecure = os.getenv("NEWS_SSL_ALLOW_INSECURE", "false").lower() in ("1", "true", "yes")
        # Force OpenSSL seclevel=1 on fallback to interop with legacy/odd servers
        self._ssl_force_seclevel1 = os.getenv("NEWS_SSL_FORCE_SECLEVEL1", "true").lower() in ("1", "true", "yes")
        # Hosts to allow HTTP (non-TLS) fallback, comma separated (e.g., "sz.gov.cn,www.example.com")
        raw_hosts = os.getenv("NEWS_SSL_HTTP_FALLBACK_HOSTS", "").strip()
        self._ssl_http_fallback_hosts = [h.strip().lower() for h in raw_hosts.split(",") if h.strip()] if raw_hosts else []
    
    async def process_search_results(self, results: List[Dict[str, Any]], related_symbol: str = None) -> List[NewsArticle]:
        """
        Process search results and create NewsArticle objects
        """
        articles = []
        
        for result in results:
            try:
                # Skip non-article URLs (listings, tags, quote pages, etc.)
                url = result.get("url", "")
                if not self._is_article_like_url(url):
                    NewsMetrics.inc("filter.url_non_article")
                    continue
                article = await self._process_single_result(result, related_symbol)
                if article:
                    NewsMetrics.inc("ingest.article_created")
                    articles.append(article)
            except Exception as e:
                print(f"Failed to process article {result.get('url', '')}: {e}")
                
        return articles
    
    async def _process_single_result(self, result: Dict[str, Any], related_symbol: str = None) -> Optional[NewsArticle]:
        """
        Process a single search result
        """
        url = result.get("url", "")
        title = result.get("title", "")
        
        if not url or not title:
            return None
            
        # Check if article already exists
        from .db import SessionLocal
        session = SessionLocal()
        try:
            existing = session.execute(
                select(NewsArticle).where(NewsArticle.url == url)
            ).scalar_one_or_none()
            
            if existing:
                return existing
        finally:
            session.close()
        # Fetch HTML once for content/date extraction
        soup = await self._fetch_soup(url)
        content = await self._extract_content(url, soup)
        if not content:
            NewsMetrics.inc("extract.content_empty")
        else:
            # Try fix mojibake if detected (e.g., "å··" patterns)
            fixed = self._maybe_fix_mojibake(content)
            if fixed != content:
                content = fixed

        # Deduplication: skip if URL/title/content considered duplicate of recent article
        try:
            dup_result = await self._deduplicator.check_duplicate(url=url, title=title or "", content=content or "")
            if dup_result and getattr(dup_result, "is_duplicate", False):
                # Skip saving duplicates to reduce noise and cost
                NewsMetrics.inc("dedup.skipped")
                return None
        except Exception as _e:
            # Non-fatal: continue without dedup
            pass

        # Language and A-share relevance filtering to remove garbled or foreign news
        if content:
            cn_ratio = self._chinese_ratio(title + " " + content)
            is_relevant = self._is_relevant_to_a_share(title=title, content=content, url=url, hint_symbol=related_symbol)
            if cn_ratio < self._min_cn_ratio and not is_relevant and not self._force_allow_non_cn:
                NewsMetrics.inc("filter.language_non_cn")
                return None

        # Get or create news source
        source = await self._get_or_create_source(url)

        # Analyze content (LLM first, fallback to simple analysis)
        analysis: Dict[str, Any]
        llm_summary: Optional[str] = None
        llm_keywords: List[str] = []
        llm_entities: Dict[str, Any] = {}
        llm_sentiment: Dict[str, Any] = {}
        llm_stock_symbols: List[str] = []

        if self._use_llm:
            try:
                async with LLMNewsProcessor() as llm:
                    llm_result: Optional[NewsAnalysisResult] = await llm.analyze_news(title=title, content=content or "", url=url)
                if llm_result:
                    NewsMetrics.inc("llm.analyze_ok")
                    # Map LLM result to internal analysis dict
                    analysis = {
                        "category": llm_result.category or NewsCategory.FINANCE.value,
                        "keywords": (llm_result.keywords or [])[:15],
                        "entities": {
                            "companies": llm_result.companies or [],
                            "people": llm_result.people or [],
                            "locations": llm_result.locations or [],
                            # extended analysis stored under entities for now
                            "financial_metrics": llm_result.financial_metrics or {},
                            "main_topics": (llm_result.main_topics or [])[:5],
                            "time_references": llm_result.time_references or [],
                            "reliability_assessment": llm_result.reliability_assessment or None,
                            "market_impact": llm_result.market_impact or None,
                        },
                        "sentiment_type": llm_result.sentiment_type or None,
                        "sentiment_score": llm_result.sentiment_score or None,
                        "sentiment_confidence": llm_result.sentiment_confidence or None,
                        "relevance_score": llm_result.relevance_score or 0.5,
                        "content_quality": llm_result.content_quality or 0.5
                    }
                    llm_summary = llm_result.summary or None
                    llm_keywords = llm_result.keywords or []
                    llm_entities = analysis.get("entities", {})
                    llm_sentiment = {
                        "type": llm_result.sentiment_type,
                        "score": llm_result.sentiment_score,
                        "confidence": llm_result.sentiment_confidence,
                    }
                    llm_stock_symbols = llm_result.stock_symbols or []
                else:
                    analysis = await self._analyze_content(title, content)
            except Exception as e:
                print(f"LLM analysis failed for {url}: {e}")
                NewsMetrics.inc("llm.analyze_fail")
                analysis = await self._analyze_content(title, content)
        else:
            analysis = await self._analyze_content(title, content)

        # Determine published time from result fields or HTML metadata
        published_dt = self._extract_published_from_result(result)
        if not published_dt:
            published_dt = self._extract_published_from_soup(soup)
        if not published_dt:
            published_dt = self._extract_published_from_url(url)

        # Prepare a guaranteed non-empty summary
        effective_summary: str = ""
        if llm_summary and llm_summary.strip():
            effective_summary = llm_summary.strip()
        else:
            # Try content-based summary
            effective_summary = self._generate_summary(content or "")
            if not effective_summary:
                # Try combining title + content
                effective_summary = self._generate_summary(f"{title} {content or ''}")
            if not effective_summary:
                # Final fallback to title itself
                t = (title or "").strip()
                if len(t) > 200:
                    effective_summary = t[:199] + "…"
                else:
                    effective_summary = t or "新闻简要：暂无可提取正文，标题提示该条与市场相关。"
        # Enforce DB column length limit (1000)
        if effective_summary and len(effective_summary) > 1000:
            effective_summary = effective_summary[:997] + "…"

        # Create article (use computed effective_summary and mark LLM flag accordingly)
        article = NewsArticle(
            title=title,
            url=url,
            content=content,
            summary=effective_summary,
            summary_from_llm=bool(llm_summary and len(llm_summary) > 0),
            published_at=published_dt,
            source_id=source.id,
            category=analysis.get("category", NewsCategory.FINANCE.value),
            keywords=analysis.get("keywords", []) or llm_keywords,
            entities=analysis.get("entities", {}),
            sentiment_type=analysis.get("sentiment_type"),
            sentiment_score=analysis.get("sentiment_score"),
            sentiment_confidence=analysis.get("sentiment_confidence"),
            # Merge related stocks from heuristic extractor and LLM symbols
            related_stocks=list({
                *(self._extract_related_stocks(title, content, related_symbol) or []),
                *llm_stock_symbols
            }) or None,
            relevance_score=analysis.get("relevance_score", 0.5),
            content_quality=analysis.get("content_quality", 0.5)
        )

        return article
    
    async def _fetch_soup(self, url: str) -> Optional[BeautifulSoup]:
        """
        Fetch HTML and return BeautifulSoup
        """
        try:
            resp = await self._http_get(url)
            if resp is None:
                print(f"Failed to fetch HTML from {url}: exceeded retry attempts")
                return None
            # Use robust decoding to avoid mojibake before parsing
            try:
                html_text = self._decode_html(resp, resp.content)
                return BeautifulSoup(html_text, 'lxml')
            except Exception:
                return BeautifulSoup(resp.content, 'lxml')
        except Exception as e:
            print(f"Failed to fetch HTML from {url}: {e}")
            return None

    async def _extract_content(self, url: str, soup: Optional[BeautifulSoup] = None) -> Optional[str]:
        """
        Extract article content from URL with readability and robust cleaning
        """
        try:
            # Fast-path: handle PDF documents by extracting text directly
            if url.lower().endswith(".pdf"):
                try:
                    resp = await self._http_get(url)
                    if resp is None:
                        return None
                    ct = (resp.headers.get("Content-Type", "").lower() if hasattr(resp, "headers") else "")
                    if ("application/pdf" in ct) or url.lower().endswith(".pdf"):
                        pdf_text = self._extract_pdf_text(resp.content)
                        if pdf_text:
                            return pdf_text
                        # Avoid passing raw PDF to HTML parser; return a clean placeholder
                        from os.path import basename
                        name = basename(url)
                        return self._clean_text(f"PDF文档（{name}）：当前无法直接提取文字，请在原文查看。")
                except Exception:
                    # fall through to generic extractor
                    pass
            # Domain-specific fast path: Sina VIP corp pages often render content differently
            if url.lower().startswith("https://vip.stock.finance.sina.com.cn/corp/go.php") or url.lower().startswith("http://vip.stock.finance.sina.com.cn/corp/go.php"):
                try:
                    txt = await self._extract_sina_vip_content(url, soup=soup)
                    if txt and len(txt) >= 40:
                        return txt[:8000]
                except Exception:
                    # fall through to generic extractor
                    pass
            raw_html: Optional[bytes] = None
            html_text: Optional[str] = None
            if soup is None:
                resp = await self._http_get(url)
                if resp is None:
                    print(f"Failed to extract content from {url}: exceeded retry attempts")
                    return None
                # If content-type indicates PDF, extract via pdf parser
                try:
                    ct = (resp.headers.get("Content-Type", "").lower() if hasattr(resp, "headers") else "")
                except Exception:
                    ct = ""
                if ("application/pdf" in ct) or url.lower().endswith(".pdf"):
                    pdf_text = self._extract_pdf_text(resp.content)
                    if pdf_text:
                        return pdf_text
                    # Avoid parsing as HTML; return a clean placeholder
                    from os.path import basename
                    name = basename(url)
                    return self._clean_text(f"PDF文档（{name}）：当前无法直接提取文字，请在原文查看。")
                raw_html = resp.content
                # Decode with best-effort to avoid mojibake
                html_text = self._decode_html(resp, raw_html)
                soup = BeautifulSoup(html_text, 'lxml')
            else:
                raw_html = soup.encode() if hasattr(soup, 'encode') else None
                html_text = str(soup)
            
            # Remove script/style/nav/header/footer/aside
            for n in soup(["script", "style", "nav", "header", "footer", "aside"]):
                n.decompose()
            
            # Try readability first for main content extraction
            main_text = ""
            try:
                print(" ================================== ")
                if html_text and READABILITY_AVAILABLE:
                    print(" Using readability ")
                    doc = Document(html_text)
                    readable_html = doc.summary(html_partial=True)
                    cleaned = BeautifulSoup(readable_html, 'lxml')
                    # remove figures/asides again in readable block
                    for n in cleaned(["script", "style", "nav", "header", "footer", "aside", "figure"]):
                        n.decompose()
                    main_text = cleaned.get_text(separator=" ", strip=True)
                    print(f" Readability extracted {len(main_text)} text: {main_text}... ")

                
            except Exception:
                main_text = ""

            

            # Fallback selectors
            content_selectors = [
                "article", 
                ".content", 
                ".article-content",
                ".post-content",
                "#content",
                "main"
            ]
            
            content = main_text or ""
            for selector in content_selectors:
                element = soup.select_one(selector)
                if element:
                    text = element.get_text(separator=" ", strip=True)
                    # Prefer the longer between readability and selector text
                    if len(text) > len(content):
                        content = text
                    break
            
            if not content:
                # Fallback to body content
                content = soup.get_text(separator=" ", strip=True)
            
            print(f" Final extracted content length: {len(content)} ")
            print(f" ================================== ")

            print(f"Content start with {content[:100]}...")

            print(f" ================================== ")

            print(f"Content end with {content[-100:]}...")


            print(f" ================================== ")
            # Clean up content and remove placeholders
            content = self._clean_text(content)
            if self._looks_like_placeholder(content):
                # As a last resort use meta description if available
                meta_desc = soup.find('meta', attrs={'name': 'description'})
                if meta_desc and meta_desc.get('content'):
                    content = self._clean_text(meta_desc.get('content'))
            
            print(f" Cleaned content length: {len(content)} ")
            # Enforce minimal length; otherwise return None
            if not content or len(content) < 10:
                # Try OpenGraph description as a final fallback
                try:
                    og_desc = soup.find('meta', attrs={'property': 'og:description'})
                    if og_desc and og_desc.get('content'):
                        alt = self._clean_text(og_desc.get('content'))
                        if alt and len(alt) >= 40:
                            return alt[:8000]
                except Exception:
                    pass

                print(f" Extracted content too short from {url}: length {len(content)} ")
                return None
            
            print(f" Extracted content length: {len(content)} ")
            # Limit content length to avoid oversized rows
            return content[:8000]
            
        except Exception as e:
            print(f"Failed to extract content from {url}: {e}")
            return None

    def _extract_pdf_text(self, raw: bytes) -> Optional[str]:
        """Extract text from PDF bytes using pdfminer.six; return cleaned text.

        Falls back gracefully if pdfminer isn't available or parsing fails.
        """
        if not raw:
            return None
        try:
            from io import BytesIO
            # Try pdfminer first
            try:
                from pdfminer.high_level import extract_text as _pdfminer_extract
                with BytesIO(raw) as bio:
                    text = _pdfminer_extract(bio)
                t = self._clean_text(text or "")
                if t and len(t) >= 40 and not self._looks_like_placeholder(t):
                    return t[:8000]
            except Exception as e_pdfminer:
                print(f"PDF extraction via pdfminer failed: {e_pdfminer}")
                # Fallback to pypdf
                try:
                    from pypdf import PdfReader
                    reader = PdfReader(BytesIO(raw))
                    parts = []
                    for page in reader.pages:
                        try:
                            parts.append(page.extract_text() or "")
                        except Exception:
                            continue
                    text = "\n".join(p for p in parts if p)
                    t = self._clean_text(text or "")
                    if t and len(t) >= 40 and not self._looks_like_placeholder(t):
                        return t[:8000]
                except Exception as e_pypdf:
                    print(f"PDF extraction via pypdf failed: {e_pypdf}")
            return None
        except Exception as e:
            print(f"PDF extraction failed: {e}")
            return None

    async def _extract_sina_vip_content(self, url: str, soup: Optional[BeautifulSoup] = None) -> Optional[str]:
        """Best-effort extractor for Sina VIP corp/go.php pages.

        These pages are not classic news articles but contain valuable company info,
        announcements links and summaries. We try to extract:
        - page title/company name
        - the main right-side info blocks (资讯与公告 / 公司公告 / 行业资讯等)
        - any visible table rows with announcements and brief descriptions
        """
        try:
            if soup is None:
                resp = await self._http_get(url)
                if not resp:
                    return None
                html_text = self._decode_html(resp, resp.content)
                soup = BeautifulSoup(html_text, 'lxml')
            # Remove noise
            for n in soup(["script", "style", "nav", "header", "footer", "aside"]):
                n.decompose()

            pieces: List[str] = []
            # Title / company name
            title = soup.find('title')
            if title and title.get_text(strip=True):
                pieces.append(self._clean_text(title.get_text(strip=True)))

            # Attempt to parse stock symbol from URL for auxiliary fetches
            sym = None
            try:
                m = re.search(r"/symbol/((?:sh|sz)\d{6})\.phtml", url.lower())
                if m:
                    sym = m.group(1)
            except Exception:
                sym = None

            # Common content containers on these pages
            # Try to grab center area text; many blocks use id or classes with 'content', 'wrap', etc.
            selectors = [
                '#con02', '#con02-1', '#con02-2', '#con02-3', '#content', '.content', '.main', '#right', '#center',
                '.cwrap', '.wrap', '.m_box', '.m_right', '.m_content'
            ]
            extracted = ""
            for sel in selectors:
                node = soup.select_one(sel)
                if node:
                    t = node.get_text(separator=' ', strip=True)
                    t = self._clean_text(t)
                    if len(t) > len(extracted):
                        extracted = t
            if extracted:
                pieces.append(extracted)

            # Tabular announcements: try common tables
            tables = soup.select('table')
            ann_lines: List[str] = []
            for tb in tables:
                # Extract up to first 8 non-empty rows
                rows = []
                for tr in tb.select('tr'):
                    cells = [self._clean_text(td.get_text(' ', strip=True)) for td in tr.select('td')]
                    line = ' | '.join([c for c in cells if c])
                    if line and not self._looks_like_placeholder(line):
                        rows.append(line)
                    if len(rows) >= 8:
                        break
                # Heuristic: include tables that look like announcements (contain keywords)
                if rows and any(any(k in r for k in ["公告", "临时", "董事会", "股东大会", "财报", "年报", "季报"]) for r in rows):
                    ann_lines.extend(rows)
                if len(ann_lines) >= 20:
                    break
            if ann_lines:
                pieces.append("公告摘要：" + "；".join(ann_lines))

            # Auxiliary pages to enrich content when main page is sparse
            if sym:
                aux_urls = [
                    f"https://finance.sina.com.cn/realstock/company/{sym}/nc.shtml",
                    f"https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletin.php?stockid={sym}",
                    f"https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletin.php?symbol={sym}",
                ]
                for aurl in aux_urls:
                    try:
                        r = await self._http_get(aurl)
                        if not r:
                            continue
                        html2 = self._decode_html(r, r.content)
                        s2 = BeautifulSoup(html2, 'lxml')
                        for n in s2(["script", "style", "nav", "header", "footer", "aside"]):
                            n.decompose()
                        # Prefer article-like sections or list blocks
                        blk = ""
                        cand = s2.select_one('#con02') or s2.select_one('.content') or s2.select_one('#content') or s2.select_one('.m_main') or s2.body
                        if cand:
                            blk = self._clean_text(cand.get_text(' ', strip=True))
                        if blk and len(blk) > 60 and not self._looks_like_placeholder(blk):
                            pieces.append(blk[:2000])
                    except Exception:
                        continue

            text = self._clean_text(" ".join(pieces))
            # Strip placeholders and indicator spam one more time
            text = self._strip_placeholders(text)
            # Final sanity check
            if text and len(text) >= 40 and not self._looks_like_placeholder(text):
                return text
            return None
        except Exception:
            return None

    async def _http_get(self, url: str) -> Optional[httpx.Response]:
        """HTTP GET with retries, rotated headers, optional proxy, and basic backoff.

        Retries on 403/429 and transient network errors.
        """
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}/"
        last_error: Optional[Exception] = None
        for attempt in range(self._retry_attempts):
            headers = dict(self._http_headers)
            headers["User-Agent"] = self._ua_pool[attempt % len(self._ua_pool)]
            headers["Referer"] = origin
            try:
                async with httpx.AsyncClient(
                    timeout=30.0,
                    follow_redirects=True,
                    headers=headers,
                    proxies=self._proxies
                ) as client:
                    resp = await client.get(url)
                    # Handle anti-bot soft failures
                    if resp.status_code in (403, 429):
                        await asyncio.sleep(self._retry_backoff * (2 ** attempt))
                        continue
                    resp.raise_for_status()
                    return resp
            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
                last_error = e
                await asyncio.sleep(self._retry_backoff * (2 ** attempt))
                continue
            except httpx.HTTPStatusError as e:
                last_error = e
                status = e.response.status_code if e.response is not None else None
                if status in (403, 429, 500, 502, 503, 504):
                    await asyncio.sleep(self._retry_backoff * (2 ** attempt))
                    continue
                # Non-retryable HTTP error
                break
            except Exception as e:
                last_error = e
                await asyncio.sleep(self._retry_backoff * (2 ** attempt))
                continue
        # If reached here, normal attempts failed. Try SSL/TLS-specific fallbacks when applicable.
        try:
            host = urlparse(url).netloc.lower()
            is_https = url.lower().startswith("https://")
            msg = str(last_error or "")
            low = msg.lower()
            # Detect SSL-layer errors by message signature to avoid dependency on httpx internals
            bad_ecpoint = ("bad ecpoint" in low) or ("ssl:" in low and "ecpoint" in low)
            ssl_error = bad_ecpoint or ("ssl" in low and "error" in low)
        except Exception:
            host = parsed.netloc.lower()
            is_https = url.lower().startswith("https://")
            ssl_error = False

        if ssl_error and is_https:
            # Build a permissive SSLContext (seclevel=1, legacy connect) to interop with legacy endpoints
            try:
                context = ssl.create_default_context()
                if self._ssl_force_seclevel1:
                    try:
                        context.set_ciphers("DEFAULT:@SECLEVEL=1")
                    except Exception:
                        pass
                    if hasattr(ssl, "OP_LEGACY_SERVER_CONNECT"):
                        try:
                            context.options |= ssl.OP_LEGACY_SERVER_CONNECT  # type: ignore[attr-defined]
                        except Exception:
                            pass
                if self._ssl_allow_insecure:
                    # Disable certificate verification as a last-resort fallback
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE  # type: ignore[assignment]

                headers = dict(self._http_headers)
                headers["User-Agent"] = self._ua_pool[0]
                headers["Referer"] = origin
                print(f"[SSL Fallback] Trying seclevel=1{' + insecure' if self._ssl_allow_insecure else ''} for {url}")
                async with httpx.AsyncClient(
                    timeout=30.0,
                    follow_redirects=True,
                    headers=headers,
                    proxies=self._proxies,
                    verify=(False if self._ssl_allow_insecure else context),
                    http2=False,  # Some legacy servers break with HTTP/2
                ) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    return resp
            except Exception as e2:
                last_error = e2
                # proceed to HTTP (non-TLS) fallback if allowed

        # Optional: try HTTP (non-TLS) fallback for listed hosts
        if is_https and host and any(host.endswith(h) or host == h for h in self._ssl_http_fallback_hosts):
            try:
                alt_url = "http://" + url[len("https://"):]
                headers = dict(self._http_headers)
                headers["User-Agent"] = self._ua_pool[0]
                headers["Referer"] = f"http://{host}/"
                print(f"[SSL Fallback] Trying HTTP fallback for host {host}: {alt_url}")
                async with httpx.AsyncClient(
                    timeout=30.0,
                    follow_redirects=True,
                    headers=headers,
                    proxies=self._proxies,
                    http2=False,
                ) as client:
                    resp = await client.get(alt_url)
                    resp.raise_for_status()
                    return resp
            except Exception as e3:
                last_error = e3

        if last_error:
            print(f"Failed to fetch HTML from {url}: {last_error}")
        return None

    def _clean_text(self, text: Optional[str]) -> str:
        """Normalize whitespace, remove boilerplate, unify punctuation spacing."""
        if not text:
            return ""
        t = text
        # Remove common invisible/garbage characters: zero-width, replacement char, control chars, private use
        t = re.sub(r"[\u200B-\u200D\uFEFF]", " ", t)  # zero-width spaces
        t = t.replace("\ufffd", " ")  # replacement char
        t = re.sub(r"[\x00-\x1F\x7F]", " ", t)  # ASCII control chars
        t = re.sub(r"[\uE000-\uF8FF]", " ", t)  # private-use area (icon fonts)
        # Remove common JS-disabled placeholders and cookie walls markers first
        patterns = [
            r"请启用\s*JavaScript", r"启用\s*JavaScript后查看", r"Enable\s+JavaScript",
            r"cookie(同意|政策|policy)", r"隐私(政策|声明)", r"同意使用Cookie",
        ]
        for p in patterns:
            t = re.sub(p, " ", t, flags=re.IGNORECASE)
        # Remove Sina placeholder tokens like @open@, @volume@, etc.
        t = re.sub(r"@\w+@", " ", t)
        # Collapse whitespace
        t = re.sub(r"\s+", " ", t, flags=re.UNICODE).strip()
        # Remove repeated punctuation spacing
        t = re.sub(r"\s*([，。！？；:,:;])\s*", r"\1", t)
        return t

    def _strip_placeholders(self, text: str) -> str:
        """Additional cleanup to cut indicator spam and page boilerplate on finance portals."""
        if not text:
            return ""
        t = text
        # Remove @tokens@
        t = re.sub(r"@\w+@", " ", t)
        # Replace long indicator blocks with a short tag
        indicator_block = (
            r"(?:MACD|TRIX|DMI|EXPMA|BRAR|CR|VR|PSY|OBV|ASI|EMV|WVAD|RSI|W%R|KDJ|ROC|MIKE|DMA|BOLL|BIAS|CCI)"
        )
        t = re.sub(rf"(?:{indicator_block}(?:\s+|，|,))+{indicator_block}", " 技术指标列表 ", t, flags=re.IGNORECASE)
        # Remove excessive punctuation blocks
        t = re.sub(r"[·•]{3,}", " ", t)
        # Re-clean
        return self._clean_text(t)

    def _decode_html(self, resp: httpx.Response, raw: bytes) -> str:
        """Best-effort HTML decoding with charset hints and fallback repairs.

        - Prefer response.encoding if provided
        - Try to detect from <meta charset> when missing
        - Fallback to utf-8; if garbled, try GB18030/GBK; and if text looks like UTF-8-under-Latin1 mojibake, try latin1->utf8 repair
        """
        text: Optional[str] = None
        try:
            enc = resp.encoding
            if enc:
                text = raw.decode(enc, errors='replace')
        except Exception:
            text = None
        if not text:
            # Detect from meta charset
            try:
                head_look = raw[:2048].decode('ascii', errors='ignore').lower()
                m = re.search(r'charset=([\w\-]+)', head_look)
                if m:
                    enc2 = m.group(1)
                    text = raw.decode(enc2, errors='replace')
            except Exception:
                text = None
        if not text:
            try:
                text = raw.decode('utf-8', errors='replace')
            except Exception:
                text = raw.decode('latin-1', errors='replace')
        # If many replacement chars and low Chinese ratio, try GB18030/GBK re-decode
        try:
            def _repl_count(s: str) -> int:
                return s.count('\ufffd')
            if text and (_repl_count(text) >= 10) and (self._chinese_ratio(text) < 0.2):
                alt = None
                try:
                    alt = raw.decode('gb18030', errors='replace')
                except Exception:
                    try:
                        alt = raw.decode('gbk', errors='replace')
                    except Exception:
                        alt = None
                if alt and self._chinese_ratio(alt) > self._chinese_ratio(text):
                    text = alt
        except Exception:
            pass
        # Try fix mojibake if necessary
        if self._looks_like_mojibake(text):
            repaired = self._repair_latin1_utf8(text)
            if repaired and self._chinese_ratio(repaired) > self._chinese_ratio(text):
                text = repaired
        return text

    def _looks_like_mojibake(self, text: str) -> bool:
        if not text:
            return False
        # Typical sequences when UTF-8 decoded as Latin-1
        markers = ["å", "æ", "ç", "é", "ï¼", "Â", "ã"]
        bad = sum(text.count(m) for m in markers)
        return bad >= 5

    def _repair_latin1_utf8(self, text: str) -> str:
        try:
            return text.encode('latin-1', errors='ignore').decode('utf-8', errors='ignore')
        except Exception:
            return text

    def _maybe_fix_mojibake(self, text: str) -> str:
        if self._looks_like_mojibake(text):
            repaired = self._repair_latin1_utf8(text)
            if self._chinese_ratio(repaired) >= max(self._min_cn_ratio, 0.1):
                return repaired
        return text

    def _chinese_ratio(self, text: Optional[str]) -> float:
        if not text:
            return 0.0
        total = len(text)
        if total == 0:
            return 0.0
        cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        return cn / max(total, 1)

    def _is_relevant_to_a_share(self, title: str, content: str, url: str, hint_symbol: Optional[str]) -> bool:
        text = f"{title} {content} {url}".lower()
        # Explicit A股 markers or SH/SZ symbols
        if re.search(r"\b\d{6}\.(sh|sz)\b", text):
            return True
        keywords = ["a股", "沪深", "上证", "深证", "科创板", "创业板", "沪股通", "深股通", "北向资金", "中国股市"]
        if any(k.lower() in text for k in keywords):
            return True
        if hint_symbol and hint_symbol.lower() in text:
            return True
        # Known CN finance domains heuristic
        host = urlparse(url).netloc.lower()
        cn_fin = ["sina.com.cn", "eastmoney.com", "10jqka.com.cn", "cs.com.cn", "finance.qq.com", "xueqiu.com", "yicai.com", "caixin.com", "stcn.com", "cls.cn", "jrj.com.cn"]
        if any(h in host for h in cn_fin) and self._chinese_ratio(title + content) > 0.08:
            return True
        return False

    def _looks_like_placeholder(self, text: Optional[str]) -> bool:
        """Detect if extracted text is likely a placeholder or boilerplate."""
        if not text:
            return True
        t = text.strip()
        if len(t) < 40:
            return True
        lower = t.lower()
        bad_markers = [
            "document", "javascript", "cookie", "privacy", "enable js", "请启用javascript", "验证码",
            "正在跳转", "安全验证", "访问过于频繁", "登录", "请登录", "登录后查看", "暂无数据", "暂时没有数据"
        ]
        if any(m in lower for m in bad_markers):
            return True
        # Heuristic: too high punctuation/word ratio might indicate nav/footer junk
        punct_ratio = sum(1 for c in t if c in ",，。.!！？；;:") / max(len(t), 1)
        if punct_ratio > 0.2 and len(t) < 120:
            return True
        return False

    def _extract_published_from_result(self, result: Dict[str, Any]) -> Optional[datetime]:
        """
        Try to parse published date from various fields in the search result
        """
        if not result:
            return None
        # Common field names from different engines
        candidate_keys = [
            "publishedDate", "published", "date", "published_at", "publishedAt",
            "pubDate", "time", "timestamp", "ts", "updated", "updated_at", "updatedAt"
        ]
        for key in candidate_keys:
            if key in result and result[key]:
                dt = self._parse_published_date_value(result[key])
                if dt:
                    return dt
        return None

    def _extract_published_from_soup(self, soup: Optional[BeautifulSoup]) -> Optional[datetime]:
        """
        Parse published date from HTML meta tags, time elements, or JSON-LD
        """
        if soup is None:
            return None

        # Meta tags
        meta_selectors = [
            ('meta', {"property": "article:published_time"}),
            ('meta', {"name": "article:published_time"}),
            ('meta', {"name": "pubdate"}),
            ('meta', {"name": "publishdate"}),
            ('meta', {"name": "publish_date"}),
            ('meta', {"itemprop": "datePublished"}),
            ('meta', {"name": "date"}),
            ('meta', {"property": "og:pubdate"}),
            ('meta', {"property": "og:updated_time"}),
        ]
        for tag, attrs in meta_selectors:
            el = soup.find(tag, attrs=attrs)
            if el and el.get('content'):
                dt = self._parse_published_date_value(el.get('content'))
                if dt:
                    return dt

        # time[datetime]
        time_el = soup.find('time')
        if time_el:
            dt_attr = time_el.get('datetime') or time_el.get('content') or time_el.get_text(strip=True)
            if dt_attr:
                dt = self._parse_published_date_value(dt_attr)
                if dt:
                    return dt

        # JSON-LD
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or script.text or '{}')
                # Could be an array
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    for key in ("datePublished", "dateCreated", "uploadDate"):
                        if key in item and item[key]:
                            dt = self._parse_published_date_value(item[key])
                            if dt:
                                return dt
            except Exception:
                continue

        return None

    def _extract_published_from_url(self, url: str) -> Optional[datetime]:
        """
        Try to parse a publish date from common URL patterns when HTML/result lacks it.
        Examples:
        - .../2025/09/19/...
        - .../2025-09-19/...
        - ...RB20250914.... or .../20250914/...
        """
        if not url:
            return None
        try:
            # YYYY-MM-DD or YYYY/MM/DD
            m = re.search(r"/(20\d{2})[\-/](0?[1-9]|1[0-2])[\-/](0?[1-9]|[12]\d|3[01])", url)
            if m:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                return datetime(y, mo, d)

            # YYYYMMDD contiguous digits (e.g., RB20250914, /20250919/)
            m = re.search(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)", url)
            if m:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                return datetime(y, mo, d)

            # Date present in query parameters like ?date=2025-09-19
            m = re.search(r"(20\d{2})[\-](0?[1-9]|1[0-2])[\-](0?[1-9]|[12]\d|3[01])", url)
            if m:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                return datetime(y, mo, d)
        except Exception:
            return None
        return None
    
    async def _get_or_create_source(self, url: str) -> NewsSource:
        """
        Get or create news source from URL
        """
        domain = urlparse(url).netloc
        
        from .db import SessionLocal
        session = SessionLocal()
        try:
            source = session.execute(
                select(NewsSource).where(NewsSource.domain == domain)
            ).scalar_one_or_none()
            
            if not source:
                # Create new source
                source = NewsSource(
                    name=domain,
                    domain=domain,
                    category=self._categorize_domain(domain),
                    reliability_score=self._assess_reliability(domain),
                    language="zh-CN" if any(x in domain for x in ["cn", "com.cn", "sina", "163", "qq", "sohu"]) else "en"
                )
                session.add(source)
                session.commit()
                session.refresh(source)
            
            return source
        finally:
            session.close()
    
    def _categorize_domain(self, domain: str) -> str:
        """
        Categorize domain based on known patterns
        """
        finance_domains = ["finance", "money", "economic", "stock", "投资", "财经"]
        if any(keyword in domain.lower() for keyword in finance_domains):
            return NewsCategory.FINANCE.value
        return NewsCategory.FINANCE.value  # Default to finance
    
    def _assess_reliability(self, domain: str) -> float:
        """
        Assess domain reliability score
        """
        reliable_domains = {
            "reuters.com": 0.9,
            "bloomberg.com": 0.9,
            "finance.sina.com.cn": 0.8,
            "eastmoney.com": 0.85,
            "cnbc.com": 0.85,
            "ft.com": 0.9
        }
        return reliable_domains.get(domain, 0.6)
    
    async def _analyze_content(self, title: str, content: str) -> Dict[str, Any]:
        """
        Analyze content for sentiment, keywords, etc.
        """
        # Simple keyword extraction
        finance_keywords = ["股票", "投资", "市场", "交易", "涨跌", "利润", "财报", "业绩"]
        
        text = f"{title} {content or ''}"
        found_keywords = [kw for kw in finance_keywords if kw in text]
        
        # Simple sentiment analysis
        positive_words = ["上涨", "增长", "利好", "盈利", "突破", "看好"]
        negative_words = ["下跌", "亏损", "利空", "风险", "暴跌", "看空"]
        
        positive_count = sum(1 for word in positive_words if word in text)
        negative_count = sum(1 for word in negative_words if word in text)
        
        if positive_count > negative_count:
            sentiment_type = SentimentType.POSITIVE.value
            sentiment_score = min(0.8, 0.1 + positive_count * 0.1)
        elif negative_count > positive_count:
            sentiment_type = SentimentType.NEGATIVE.value
            sentiment_score = max(-0.8, -0.1 - negative_count * 0.1)
        else:
            sentiment_type = SentimentType.NEUTRAL.value
            sentiment_score = 0.0
        
        return {
            "category": NewsCategory.FINANCE.value,
            "keywords": found_keywords,
            "entities": [],  # TODO: Implement NER
            "sentiment_type": sentiment_type,
            "sentiment_score": sentiment_score,
            "sentiment_confidence": 0.7,
            "relevance_score": min(1.0, len(found_keywords) * 0.2),
            "content_quality": 0.8 if content and len(content) > 100 else 0.3
        }
    
    def _extract_related_stocks(self, title: str, content: str, hint_symbol: str = None) -> List[str]:
        """
        Extract related stock symbols from content
        """
        stocks = []
        text = f"{title} {content or ''}"
        
        # Pattern for Chinese stock codes, capture code and market (e.g., 000001.SZ)
        stock_pattern = r"\b(\d{6})\.(SH|SZ)\b"
        matches = re.findall(stock_pattern, text, re.IGNORECASE)
        for code, market in matches:
            stocks.append(f"{code}.{market.upper()}")
        
        if hint_symbol:
            stocks.append(hint_symbol)
        
        return list(set(stocks))  # Remove duplicates

    def _is_article_like_url(self, url: str) -> bool:
        """Heuristic filter to keep likely article pages and drop listings/quote/tag pages.

        - Keep: paths containing /news/, /article/, /story/ with an id-like suffix
        - Drop: /quote/, /quotes/, /keywords/, /tag/, /category/, /search/, /sitemap/, /index,
                list pages, and obvious stock quote/equity pages
        - Special cases:
            - tw.stock.yahoo.com: keep only URLs starting with /news/
        """
        try:
            if not url:
                return False
            u = urlparse(url)
            host = (u.netloc or "").lower()
            path = (u.path or "").lower()
            full = (u.geturl() or "").lower()

            # Apply explicit blocklist first
            if self._url_blocklist and any(b in full or b in path for b in self._url_blocklist):
                return False
            # Apply built-in non-article substrings
            if any(substr in full for substr in self._default_non_article_substrings):
                # Allow Sina VIP corp/go.php pages through for symbol-specific sections
                if host.endswith('vip.stock.finance.sina.com.cn') and '/corp/go.php/' in path:
                    return True
                # Special-case: allow actual article paths under moomoo when clearly news-like (rare)
                # Default to drop since most matched are non-articles/JS hubs
                return False
            # Apply dynamic patterns from DB
            self.reload_url_filters()
            if self._dynamic_block_substrings and any(b in full for b in self._dynamic_block_substrings):
                return False
            # If allowlist is provided, require at least one match
            allowlists = list(self._url_allowlist)
            if self._dynamic_allow_substrings:
                allowlists.extend(self._dynamic_allow_substrings)
            if allowlists and not any(a in full or a in path for a in allowlists):
                return False
            # Drop common non-article paths
            drop_markers = [
                "/quote/", "/quotes/", "/keywords/", "/tag/", "/category/", "/search",
                "/sitemap", "/index", "/topic", "/list", "/equities/", "/stocks/",
            ]
            if any(m in path for m in drop_markers):
                return False
            # Additional moomoo financials pages pattern
            if "moomoo.com/stock/" in full and "/financials-" in full:
                return False
            # Host-specific allow rules
            if host.endswith("tw.stock.yahoo.com"):
                return path.startswith("/news/")
            if host.endswith("finance.yahoo.com"):
                # U.S. Yahoo Finance articles often under /news/
                return "/news/" in path
            if host.endswith("investing.com") or host.endswith("cn.investing.com"):
                # Avoid equities and quote-like pages
                if "/equities/" in path:
                    return False
            if host.endswith("163.com"):
                if "/keywords/" in path:
                    return False
            # Generic positive markers
            keep_markers = ["/news/", "/article/", "/story/"]
            if any(m in path for m in keep_markers):
                return True
            # If URL ends with numeric-id-like slug
            import re as _re
            if _re.search(r"-\d{6,}(?:\.html)?$", path):
                return True
            # Default: keep if path has multiple segments and not too short
            return path.count('/') >= 2 and len(path) > 12
        except Exception:
            return True

    def reload_url_filters(self, force: bool = False) -> None:
        """Load dynamic URL filters from DB with simple TTL caching."""
        now = datetime.utcnow()
        if not force and self._dynamic_loaded_at and (now - self._dynamic_loaded_at).total_seconds() < self._dynamic_ttl_secs:
            return
        try:
            from .db import SessionLocal
            session = SessionLocal()
            try:
                blocks = session.execute(select(NewsURLPattern).where(
                    (NewsURLPattern.enabled == True) & (NewsURLPattern.kind == 'block')
                )).scalars().all()
                allows = session.execute(select(NewsURLPattern).where(
                    (NewsURLPattern.enabled == True) & (NewsURLPattern.kind == 'allow')
                )).scalars().all()
                def _to_substrings(rows):
                    out = []
                    for r in rows:
                        if r.scope != 'substring':
                            continue  # regex not yet supported here
                        p = (r.pattern or '').strip().lower()
                        if not p:
                            continue
                        if r.host:
                            out.append(f"{r.host.lower()}{p}")
                        else:
                            out.append(p)
                    return list({*out})
                self._dynamic_block_substrings = _to_substrings(blocks)
                self._dynamic_allow_substrings = _to_substrings(allows)
                self._dynamic_loaded_at = now
            finally:
                session.close()
        except Exception:
            # Ignore errors; continue with previously loaded or empty sets
            pass
    
    def _generate_summary(self, content: str, max_length: int = 200) -> str:
        """
        Generate article summary
        """
        if not content:
            return ""
        
        text = self._clean_text(content)
        if not text:
            return ""

        # Split into sentences using common Chinese and English punctuation
        parts = re.split(r"[。！？!?.]\s*", text)
        # Filter out boilerplate-like or too-short parts
        def ok(s: str) -> bool:
            s2 = s.strip()
            if len(s2) < 12:
                return False
            if self._looks_like_placeholder(s2):
                return False
            # skip obvious disclaimers
            if re.search(r"(免责声明|版权|转载|责任编辑|来源：|作者：)", s2):
                return False
            return True

        candidates = [p for p in parts if ok(p)]
        if not candidates:
            candidates = [p.strip() for p in parts if p.strip()]

        summary = ""
        for s in candidates:
            if len(summary) + len(s) + 1 <= max_length:
                summary += s + "。"
            else:
                # Try to truncate the last piece to fit
                remain = max_length - len(summary)
                if remain > 6:
                    summary += s[:remain] + "…"
                break
        return summary.strip(" 。")
    
    def _parse_published_date_value(self, value: Any) -> Optional[datetime]:
        """
        Robustly parse a datetime from diverse value types and formats
        """
        if value is None:
            return None
        try:
            # Numeric epoch seconds/milliseconds
            if isinstance(value, (int, float)):
                num = int(value)
                if num < 1e12:  # seconds
                    return datetime.utcfromtimestamp(num)
                else:  # milliseconds
                    return datetime.utcfromtimestamp(num / 1000)

            s = str(value).strip()
            if not s:
                return None

            # ISO 8601
            try:
                s2 = s.replace('Z', '+00:00')
                return datetime.fromisoformat(s2)
            except Exception:
                pass

            # RFC 2822 / RFC 1123
            for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
                try:
                    return datetime.strptime(s, fmt)
                except Exception:
                    continue

            # Common formats
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%d",
                "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d %H:%M",
                "%Y/%m/%d",
                "%Y.%m.%d %H:%M",
                "%Y.%m.%d",
            ):
                try:
                    return datetime.strptime(s, fmt)
                except Exception:
                    continue
        except Exception:
            return None

        return None


class NewsScheduler:
    def __init__(self):
        self.search_service = NewsSearchService()
        self.processor = NewsProcessor()
    
    async def run_scheduled_news_collection(self):
        """
        Run scheduled news collection for all watchlist stocks
        """
        from .db import SessionLocal
        session = SessionLocal()
        try:
            # Get all enabled stocks
            stocks = session.execute(
                select(Watchlist).where(Watchlist.enabled == True)
            ).scalars().all()
            
            for stock in stocks:
                try:
                    await self._collect_news_for_stock(stock.symbol, stock.name)
                    await asyncio.sleep(1)  # Rate limiting
                except Exception as e:
                    print(f"Failed to collect news for {stock.symbol}: {e}")
        finally:
            session.close()
    
    async def _collect_news_for_stock(self, symbol: str, company_name: str = None):
        """
        Collect news for a specific stock
        """
        # Search for news
        results = await self.search_service.search_stock_news(symbol, company_name)
        
        # Process results
        articles = await self.processor.process_search_results(results, symbol)
        
        # Save to database
        from .db import SessionLocal
        session = SessionLocal()
        try:
            for article in articles:
                try:
                    # Check for duplicates
                    existing = session.execute(
                        select(NewsArticle).where(NewsArticle.url == article.url)
                    ).scalar_one_or_none()
                    
                    if not existing:
                        session.add(article)
                except Exception as e:
                    print(f"Failed to save article {article.url}: {e}")
            
            session.commit()
        finally:
            session.close()
