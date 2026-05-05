"""
增强新闻调度模块说明
模块概述
本模块实现了一个异步、可扩展的“增强新闻调度”系统（EnhancedNewsScheduler），用于：
- 针对股票/行业定期搜索与抓取新闻；
- 使用 LLM 进行文章分析（分类、关键词、实体、情感等）；
- 去重检测并将结果保存到关系型数据库（PostgreSQL）和文档存储（MongoDB）；
- 支持并发爬取、批量处理与策略化采集。
主要类
- EnhancedNewsScheduler
    - 负责调度、并发控制、统计与工作流编排。
    - 内部使用若干协程工具（asyncio.Semaphore、async with 等）来控制并发和资源生命周期。
关键方法（异步）
- run_daily_news_collection() -> Dict[str, Any]
    - 执行每日新闻收集流程：获取启用股票，按股票并发触发抓取、处理与保存。
    - 返回包含状态、时间区间与统计信息的字典。
- _collect_news_for_stock(stock: Watchlist) -> Dict[str, Any]
    - 为单只股票执行从搜索、去重、爬取、LLM 分析到保存的完整流水线。
    - 采用 rate_limit_delay 控制调度速率。
- _crawl_articles_batch(crawler: NewsContentCrawler, search_results: List[Dict], symbol: str) -> List[Dict]
    - 对 URL 列表按 crawl_batch_size 分批爬取，并合并搜索元信息与爬取结果。
- _process_and_save_articles(crawl_results: List[Dict], symbol: str) -> int
    - 对爬取到的文章做去重检测（NewsDeduplicator）、LLM 分析（LLMNewsProcessor）并调用 _save_article_to_db 保存。
- _save_article_to_db(article_data: Dict, analysis_result: Any, symbol: str) -> bool
    - 将文章保存到 PostgreSQL（NewsArticle、NewsSource 等模型）并写入 MongoDB 主集合与分析/归档集合。
    - 如果未初始化，会异步初始化 MongoDB 存储（get_storage）。
    - 在出错时回滚事务并记录日志。
- _get_or_create_source(domain: str, session: Session)
    - 根据域名查找或创建新闻源记录（NewsSource）。
- _cleanup_old_data()
    - 清理旧（例如 30 天前）文章数据以释放存储。
- run_intelligent_news_collection() -> Dict[str, Any]
    - 基于策略（IntelligentNewsCollector）生成并执行行业/关键词驱动的新闻收集策略。
- _execute_news_strategy(strategy) -> Dict[str, Any]
    - 执行具体策略的搜索与简化处理逻辑（可扩展）。
- get_collection_status() -> Dict[str, Any]
    - 返回统计信息：今日/本周/总文章数、待处理任务数以及最近一次收集的统计摘要。
配置项（实例属性）
- session_factory: SQLAlchemy 会话工厂（SessionLocal）
- stock_manager: 管理监控股票列表（StockListManager）
- news_search_service: 搜索服务（NewsSearchService）
- news_crawler: 爬虫（NewsContentCrawler）
- llm_processor: LLM 分析器（LLMNewsProcessor）
- deduplicator: 去重器（NewsDeduplicator）
- storage: MongoDB 存储客户端（lazy async 初始化）
- max_concurrent_crawls: 最大并发爬取数量（Semaphore 控制）
- max_articles_per_stock / crawl_batch_size / rate_limit_delay: 控制抓取规模与节流
- stats: 运行时统计计数器（collections_started、articles_found、articles_crawled、articles_processed、articles_saved、duplicates_skipped、errors）
依赖与交互
- 依赖本项目内的模块：models（SQLAlchemy ORM 模型）、db（SessionLocal）、stock_manager、news_search_service、news_crawler、llm_processor、news_deduplication、mongo_storage、news_service、news_strategy 等。
- 持久化：关系型数据库（PostgreSQL）存储结构化文章记录，MongoDB 存储主文档、分析结果与归档索引。
- LLM 与爬虫均以上下文管理器（async with）方式使用以确保资源正确释放。
错误处理与可观测性
- 通过 logging 记录关键流程与错误。
- 对异常进行捕获并在统计中记录 errors。
- 对每篇文章的处理包含独立的错误保护以避免整体失败。
扩展与注意事项
- 日期解析（_parse_published_date）目前为占位，建议集成 dateutil 或更丰富的解析逻辑以支持多种时间格式。
- 去重逻辑依赖 NewsDeduplicator 的外部实现与存储，确保其生成的 content_hash/fingerprint 与 Mongo 存储保持一致。
- 数据保留策略（如 30 天）可参数化以满足不同场景需求。
- run_intelligent_news_collection 与策略执行提供了可插拔的扩展点，用于实现更复杂的行业/主题监控。
示例（使用提示）
- 在 asyncio 事件循环中调用：await EnhancedNewsScheduler().run_daily_news_collection()
- 在生产环境中推荐将任务放到定时调度器（cron、Celery beat、Kubernetes CronJob 等）中执行，并监控日志与统计。

"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import os
from sqlalchemy.orm import Session
from sqlalchemy import select, func, and_, or_

from ..core.models import (
    Watchlist, NewsArticle, NewsKeyword, Task, TaskType, TaskStatus,
    NewsCategory, SentimentType
)
from ..core.db import SessionLocal
from ..analysis.stock_manager import StockListManager
from ..news.news_crawler import NewsContentCrawler
from ..news.llm_processor import LLMNewsProcessor
from ..news.news_deduplication import NewsDeduplicator
from ..utils.mongo_storage import get_storage
from ..news.news_deduplication import NewsDeduplicator
from ..news.llm_processor import LLMNewsProcessor
from ..news.news_service import NewsSearchService, NewsProcessor
from .rss_collector import RSSNewsCollector
from .akshare_collector import AKShareCollector
from .multi_source_collector import MultiSourceCollector
from .pdf_parser import extract_text_from_pdf
from .document_manager import UnifiedDocumentManager, UnifiedDocument


class EnhancedNewsScheduler:
    """增强的新闻调度系统"""
    
    def __init__(self):
        self.session_factory = SessionLocal
        
        # 初始化组件
        self.stock_manager = StockListManager()
        self.news_search_service = NewsSearchService()
        self.rss_collector = RSSNewsCollector()
        self.ak_collector = AKShareCollector()
        self.multi_source_collector = MultiSourceCollector()
        self.news_crawler = NewsContentCrawler()
        self.llm_processor = LLMNewsProcessor()
        self.deduplicator = NewsDeduplicator()
        
        # 统一文档管理器（处理 PDF 完整流水线）
        self.doc_manager = UnifiedDocumentManager()
        self.storage = None  # Will be initialized async
        
        # 调度配置
        self.max_concurrent_crawls = 5
        self.max_articles_per_stock = 20
        self.crawl_batch_size = 10
        self.rate_limit_delay = 1.0  # seconds
        # 每日最低篇数（去重后，按股票）
        try:
            self.daily_min_per_stock = int(os.getenv("NEWS_DAILY_MIN_PER_STOCK", "5"))
        except Exception:
            self.daily_min_per_stock = 5
        
        # 统计信息
        self.stats = {
            "collections_started": 0,
            "articles_found": 0,
            "articles_crawled": 0,
            "articles_processed": 0,
            "articles_saved": 0,
            "duplicates_skipped": 0,
            "errors": 0
        }

    # --- Deduplicator compatibility helpers ---
    def _dedup_generate_content_hash(self, content: Optional[str]) -> Optional[str]:
        """
        Safely generate content hash using the deduplicator instance.
        Falls back to a simple sha256-truncated hash if the deduplicator method is missing.
        """
        if not content:
            return None

        # prefer a public or private implementation if available
        func = getattr(self.deduplicator, 'generate_content_hash', None) or getattr(self.deduplicator, '_generate_content_hash', None)
        if callable(func):
            try:
                return func(content)
            except Exception:
                pass

        # fallback: stable sha256 truncated to 64 chars (matches existing length config)
        try:
            import hashlib
            return hashlib.sha256(content.encode('utf-8')).hexdigest()[:64]
        except Exception:
            return None

    def _dedup_generate_fingerprint(self, title: Optional[str], content: Optional[str], *, content_hash: Optional[str] = None) -> str:
        """
        Safely generate a fingerprint using the deduplicator instance.
        Tries several method names and falls back to a deterministic sha256 of title+content_hash.
        """
        func = getattr(self.deduplicator, 'generate_fingerprint', None) or getattr(self.deduplicator, '_generate_fingerprint', None)
        if callable(func):
            try:
                # some implementations accept content_hash as kwarg
                try:
                    return func(title, content, content_hash=content_hash)
                except TypeError:
                    return func(title, content)
            except Exception:
                pass

        # fallback deterministic fingerprint
        try:
            import hashlib
            components: List[str] = []
            # try to use text-hash helper if present
            gen_text = getattr(self.deduplicator, 'generate_text_hash', None) or getattr(self.deduplicator, '_generate_text_hash', None)
            if title and callable(gen_text):
                try:
                    components.append(gen_text(title))
                except Exception:
                    components.append(hashlib.sha256(title.encode('utf-8')).hexdigest())

            if content_hash is None and content:
                content_hash = self._dedup_generate_content_hash(content)

            if content_hash:
                components.append(content_hash)

            if not components:
                return hashlib.sha256(b"news-dedup-empty").hexdigest()[:64]

            fingerprint_source = '::'.join(components)
            return hashlib.sha256(fingerprint_source.encode('utf-8')).hexdigest()[:64]
        except Exception:
            # extreme fallback
            return ""  

    async def run_rss_collection_once(self, related_symbol: str = None) -> Dict[str, Any]:
        """
        Run a one-off RSS collection using the configured RSSNewsCollector
        and process the results via NewsProcessor.process_search_results.
        Returns a result dict with basic stats.
        """
        start_time = datetime.utcnow()
        try:
            # collect entries from RSS sources (may use RSSHub)
            entries = await self.rss_collector.collect_all()
            count = len(entries or [])
            logging.info(f"RSS collector returned {count} entries")

            # Normalize to expected search-result dicts
            normalized = []
            for e in entries or []:
                normalized.append({
                    "title": e.get("title") or "",
                    "url": e.get("url") or e.get("link") or "",
                    "summary": e.get("summary") or e.get("description") or "",
                    # keep published under common keys so NewsProcessor can parse it
                    "published": e.get("published") or e.get("pubDate") or e.get("updated") or None,
                    # preserve source name from feed if present
                    "source": e.get("source") or e.get("site") or None,
                })

            # Process via NewsProcessor
            processor = NewsProcessor()
            processed = await processor.process_search_results(normalized, related_symbol)
            processed_count = len(processed or [])

            # update stats
            self.stats["articles_found"] += count
            self.stats["articles_processed"] += processed_count
            self.stats["articles_saved"] += processed_count

            end_time = datetime.utcnow()
            return self._create_result("success", start_time, f"RSS collected {count}, processed {processed_count}", end_time)
        except Exception as e:
            logging.error(f"RSS collection run failed: {e}")
            self.stats["errors"] += 1
            return self._create_result("error", start_time, str(e))

    async def run_multi_source_collection(self, related_symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Run multi-source news collection (东方财富、新浪、同花顺等)
        This is more reliable than AKShare for getting stock-specific news.
        """
        start_time = datetime.utcnow()
        try:
            if related_symbol:
                # 单只股票的采集
                results = await self.multi_source_collector.collect_stock_news(
                    related_symbol, 
                    limit_per_source=10
                )
            else:
                # 批量采集所有启用的股票
                enabled_stocks = await self.stock_manager.list_stocks(enabled_only=True)
                if not enabled_stocks:
                    return self._create_result("no_stocks", start_time, "No enabled stocks")
                
                symbols = [s.symbol for s in enabled_stocks]
                results_dict = await self.multi_source_collector.batch_collect(symbols, limit_per_source=8)
                results = []
                for sym, items in results_dict.items():
                    results.extend(items)
            
            count = len(results or [])
            logging.info(f"MultiSource collector returned {count} entries")

            # Normalize to expected search-result dicts
            normalized = []
            for e in results or []:
                url = e.get("url") or ""
                # Skip items without URL (like flash news)
                if not url:
                    continue
                normalized.append({
                    "title": e.get("title") or "",
                    "url": url,
                    "summary": e.get("summary") or "",
                    "published": e.get("published") or None,
                    "source": e.get("source") or "multi_source",
                    "symbol": e.get("symbol"),
                    "is_pdf": e.get("is_pdf", False),
                })

            # Process via NewsProcessor
            processor = NewsProcessor()
            processed = await processor.process_search_results(normalized, related_symbol)
            processed_count = len(processed or [])

            # update stats
            self.stats["articles_found"] += count
            self.stats["articles_processed"] += processed_count
            self.stats["articles_saved"] += processed_count

            end_time = datetime.utcnow()
            return self._create_result(
                "success", 
                start_time, 
                f"MultiSource collected {count}, processed {processed_count}",
                end_time
            )
        except Exception as e:
            logging.error(f"MultiSource collection run failed: {e}")
            self.stats["errors"] += 1
            return self._create_result("error", start_time, str(e))
    
    async def run_daily_news_collection(self) -> Dict[str, Any]:
        """
        执行每日新闻收集任务
        """
        start_time = datetime.utcnow()
        logging.info("Starting daily news collection...")
        
        try:
            # 重置统计
            self.stats = {key: 0 for key in self.stats.keys()}
            
            # 获取启用的股票列表
            enabled_stocks = await self.stock_manager.list_stocks(enabled_only=True)
            if not enabled_stocks:
                return self._create_result("no_stocks", start_time, "No enabled stocks found")
            
            logging.info(f"Found {len(enabled_stocks)} enabled stocks for news collection")
            
            # 并发收集各股票新闻
            tasks = []
            semaphore = asyncio.Semaphore(self.max_concurrent_crawls)
            
            for stock in enabled_stocks:
                task = self._collect_news_for_stock_with_semaphore(semaphore, stock)
                tasks.append(task)
            
            # 等待所有任务完成（总超时 30 分钟防止无限挂起）
            news_timeout = int(os.getenv("NEWS_COLLECTION_TIMEOUT_SECONDS", "1800"))
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=news_timeout,
                )
            except asyncio.TimeoutError:
                logging.warning(f"Daily news collection timed out after {news_timeout}s, partial results only")
                results = []
            except asyncio.CancelledError:
                logging.warning("Daily news collection cancelled (server shutting down?)")
                return self._create_result("cancelled", start_time, "Cancelled")
            
            # 处理结果
            success_count = 0
            for i, result in enumerate(results):
                if isinstance(result, (Exception, BaseException)):
                    sym = enabled_stocks[i].symbol if i < len(enabled_stocks) else "?"
                    logging.error(f"Failed to collect news for {sym}: {result}")
                    self.stats["errors"] += 1
                else:
                    success_count += 1
            
            # 清理旧数据
            await self._cleanup_old_data()
            
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()
            
            logging.info(f"Daily news collection completed in {duration:.2f}s")
            logging.info(f"Statistics: {self.stats}")
            
            return self._create_result("success", start_time, f"Processed {success_count}/{len(enabled_stocks)} stocks", end_time)
            
        except Exception as e:
            logging.error(f"Daily news collection failed: {e}")
            return self._create_result("error", start_time, str(e))
    
    async def _collect_news_for_stock_with_semaphore(self, semaphore: asyncio.Semaphore, stock: Watchlist):
        """
        带信号量控制的股票新闻收集
        """
        try:
            async with semaphore:
                return await self._collect_news_for_stock(stock)
        except asyncio.CancelledError:
            logging.debug(f"News collection for {stock.symbol} was cancelled")
            raise  # let gather handle it
    
    async def _collect_news_for_stock(self, stock: Watchlist) -> Dict[str, Any]:
        """
        为单只股票收集新闻 - 使用多源采集器优先
        """
        try:
            logging.info(f"Collecting news for {stock.symbol} - {stock.name}")
            self.stats["collections_started"] += 1
            
            all_results = []
            
            # 1. 首先使用多源采集器（更可靠）
            try:
                multi_results = await self.multi_source_collector.collect_stock_news(
                    stock.symbol, 
                    limit_per_source=8
                )
                if multi_results:
                    logging.info(f"MultiSource found {len(multi_results)} articles for {stock.symbol}")
                    for item in multi_results:
                        if item.get("url"):  # 只保留有 URL 的
                            all_results.append({
                                "title": item.get("title", ""),
                                "url": item.get("url", ""),
                                "summary": item.get("summary", ""),
                                "published": item.get("published"),
                                "source": item.get("source", "multi_source"),
                            })
            except Exception as e:
                logging.warning(f"MultiSource collector error for {stock.symbol}: {e}")
            
            # 2. 如果多源采集结果不足，补充使用搜索引擎
            if len(all_results) < 5:
                try:
                    search_results = await self.news_search_service.search_stock_news(
                        symbol=stock.symbol,
                        company_name=stock.name
                    )
                    if search_results:
                        logging.info(f"Search found {len(search_results)} additional articles for {stock.symbol}")
                        all_results.extend(search_results)
                except Exception as e:
                    logging.warning(f"Search service error for {stock.symbol}: {e}")
            
            if not all_results:
                logging.warning(f"No results found for {stock.symbol} from any source")
                return {"status": "no_results", "symbol": stock.symbol}
            
            self.stats["articles_found"] += len(all_results)
            logging.info(f"Total found {len(all_results)} articles for {stock.symbol}")
            
            # 3. 限制数量并去重URL
            unique_results = self._deduplicate_urls(all_results[:self.max_articles_per_stock])
            
            # 4. 爬取文章内容
            async with NewsContentCrawler() as crawler:
                crawl_results = await self._crawl_articles_batch(crawler, unique_results, stock.symbol)
            
            # 5. 处理和保存文章
            saved_count = await self._process_and_save_articles(crawl_results, stock.symbol)
            
            # 添加延迟
            await asyncio.sleep(self.rate_limit_delay)
            
            return {
                "status": "success",
                "symbol": stock.symbol,
                "found": len(all_results),
                "crawled": len(crawl_results),
                "saved": saved_count
            }
            
        except Exception as e:
            logging.error(f"Failed to collect news for {stock.symbol}: {e}")
            self.stats["errors"] += 1
            return {"status": "error", "symbol": stock.symbol, "error": str(e)}

    async def _get_today_saved_count(self, stock_symbol: str) -> int:
        """从 Mongo 存档集合统计该股票“今天”的已收集文章数。"""
        try:
            if not self.storage:
                self.storage = await get_storage()
            coll = self.storage.db[self.storage.collections['stock_news_archive']]
            today = datetime.utcnow().date().isoformat()
            # date 存为 ISO 日期字符串（YYYY-MM-DD）
            return await coll.count_documents({
                'stock_symbol': stock_symbol.upper(),
                'date': today
            })
        except Exception:
            return 0

    async def run_rolling_topup_collection(self) -> Dict[str, Any]:
        """
        在一天中周期性运行的“补齐”任务：当搜索引擎可用时，为每只股票尽量补齐到每日最少 self.daily_min_per_stock 篇。
        - 统计当日已存档数量（Mongo stock_news_archive）
        - 若少于阈值，发起精简抓取，仅抓取缺口数量的候选文章
        返回整体统计和每只股票的补齐结果。
        """
        start_time = datetime.utcnow()
        summary: Dict[str, Any] = {
            'status': 'success',
            'started_at': start_time.isoformat(),
            'daily_min_per_stock': self.daily_min_per_stock,
            'stocks': [],
            'total_needed': 0,
            'total_saved': 0,
            'errors': 0,
        }

        try:
            enabled_stocks = await self.stock_manager.list_stocks(enabled_only=True)
            if not enabled_stocks:
                summary['status'] = 'no_stocks'
                return summary

            semaphore = asyncio.Semaphore(self.max_concurrent_crawls)

            async def _topup_one(stock: Watchlist) -> Dict[str, Any]:
                async with semaphore:
                    try:
                        current = await self._get_today_saved_count(stock.symbol)
                        need = max(0, self.daily_min_per_stock - current)
                        if need <= 0:
                            return {'symbol': stock.symbol, 'status': 'enough', 'today_saved': current, 'needed': 0, 'attempted': 0, 'saved': 0}

                        # 搜索候选（尽量多拿一些，去重后再截取）
                        results = await self.news_search_service.search_stock_news(symbol=stock.symbol, company_name=stock.name)
                        if not results:
                            return {'symbol': stock.symbol, 'status': 'no_search_results', 'today_saved': current, 'needed': need, 'attempted': 0, 'saved': 0}

                        unique = self._deduplicate_urls(results)
                        unique = unique[: max(need * 2, need)]  # 取缺口的 1-2 倍以防爬取失败

                        saved = 0
                        async with NewsContentCrawler() as crawler:
                            # 仅抓取到缺口数量
                            to_crawl = unique[: need]
                            crawled = await self._crawl_articles_batch(crawler, to_crawl, stock.symbol)
                            saved = await self._process_and_save_articles(crawled, stock.symbol)

                        return {'symbol': stock.symbol, 'status': 'topped_up', 'today_saved': current, 'needed': need, 'attempted': len(unique), 'saved': saved}
                    except Exception as e:
                        logging.error(f"Top-up failed for {stock.symbol}: {e}")
                        return {'symbol': stock.symbol, 'status': 'error', 'error': str(e)}

            tasks = [_topup_one(s) for s in enabled_stocks]
            results = await asyncio.gather(*tasks, return_exceptions=False)

            for r in results:
                if isinstance(r, dict):
                    summary['stocks'].append(r)
                    summary['total_saved'] += int(r.get('saved', 0) or 0)
                    summary['total_needed'] += int(r.get('needed', 0) or 0)
                    if r.get('status') == 'error':
                        summary['errors'] += 1

            summary['finished_at'] = datetime.utcnow().isoformat()
            return summary
        except Exception as e:
            summary['status'] = 'error'
            summary['error'] = str(e)
            summary['finished_at'] = datetime.utcnow().isoformat()
            return summary

    async def run_topup_for_symbol(self, symbol: str, *, min_required: Optional[int] = None, max_attempts: int = 2) -> Dict[str, Any]:
        """对单只股票执行补齐，确保当天至少 min_required 篇（默认使用 self.daily_min_per_stock）。
        - 读取今天已保存数量（Mongo 存档）
        - 若不足，则按缺口搜索、抓取并保存，最多尝试 max_attempts 轮（以防首次因去重/抓取失败未达标）
        返回：{"symbol","status","today_saved","needed","saved_total"}
        """
        sym = (symbol or '').upper()
        if not sym:
            return {"symbol": symbol, "status": "invalid_symbol"}
        try:
            target = int(min_required) if (min_required is not None) else int(self.daily_min_per_stock)
        except Exception:
            target = self.daily_min_per_stock

        try:
            # 尝试获取公司名以增强搜索
            company_name: Optional[str] = None
            try:
                from ..core.db import SessionLocal as _SL
                from ..core.models import Watchlist as _W
                _s = _SL()
                try:
                    w = _s.execute(select(_W).where(_W.symbol == sym)).scalar_one_or_none()
                    if w and getattr(w, 'name', None):
                        company_name = w.name
                finally:
                    _s.close()
            except Exception:
                company_name = None

            saved_total = 0
            for attempt in range(max(1, max_attempts)):
                current = await self._get_today_saved_count(sym)
                need = max(0, target - current)
                if need <= 0:
                    return {"symbol": sym, "status": "enough", "today_saved": current, "needed": 0, "saved_total": saved_total}

                # 搜索候选
                results = await self.news_search_service.search_stock_news(symbol=sym, company_name=company_name)
                if not results:
                    # 尝试一次宽松：无公司名限制
                    try:
                        results = await self.news_search_service.search_stock_news(symbol=sym, company_name=None)
                    except Exception as _se:
                        # 记录搜索失败
                        try:
                            if not self.storage:
                                self.storage = await get_storage()
                            await self.storage.log_news_error('search', symbol=sym, message=str(_se))
                        except Exception:
                            pass
                        results = []
                if not results:
                    # 记录一次“搜索为空”的事件，便于前端错误面板观察
                    try:
                        if not self.storage:
                            self.storage = await get_storage()
                        await self.storage.log_news_error('search', symbol=sym, message='no_results')
                    except Exception:
                        pass
                    # 搜索引擎不可用或无结果时：使用已知公告页作为兜底候选
                    try:
                        base_code = sym.split('.')[0]
                    except Exception:
                        base_code = sym
                    fallback_urls = [
                        f"https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletin.php?stockid={base_code}",
                        f"http://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletin.php?stockid={base_code}",
                        # 东方财富-公告（公司代码需适配 sz/sh 前缀，尽量尝试 SZ/SZ 格式列表页）
                        f"https://data.eastmoney.com/notice/stock/{base_code}.html",
                    ]
                    results = [{"url": u, "title": f"公告页 {base_code}"} for u in fallback_urls]

                unique = self._deduplicate_urls(results)
                unique = unique[: max(need * 2, need)]

                async with NewsContentCrawler() as crawler:
                    to_crawl = unique[: need]
                    crawled = await self._crawl_articles_batch(crawler, to_crawl, sym)
                    saved = await self._process_and_save_articles(crawled, sym)
                    saved_total += int(saved or 0)

            # 最终检查
            current = await self._get_today_saved_count(sym)
            need = max(0, target - current)
            status = "topped_up" if need <= 0 else "partial"
            return {"symbol": sym, "status": status, "today_saved": current, "needed": need, "saved_total": saved_total}
        except Exception as e:
            logging.getLogger(__name__).warning("run_topup_for_symbol failed for %s: %s", sym, e, exc_info=True)
            return {"symbol": sym, "status": "error", "error": str(e)}
    
    def _deduplicate_urls(self, search_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        基于URL去重搜索结果
        """
        seen_urls = set()
        unique_results = []
        
        for result in search_results:
            url = result.get('url', '')
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_results.append(result)
        
        return unique_results
    
    async def _crawl_articles_batch(
        self, 
        crawler: NewsContentCrawler, 
        search_results: List[Dict[str, Any]], 
        symbol: str
    ) -> List[Dict[str, Any]]:
        """
        批量爬取文章内容
        """
        crawl_results = []
        
        # 分批处理
        for i in range(0, len(search_results), self.crawl_batch_size):
            batch = search_results[i:i + self.crawl_batch_size]
            batch_urls = [result.get('url', '') for result in batch if result.get('url')]
            
            if batch_urls:
                logging.info(f"Crawling batch {i//self.crawl_batch_size + 1} for {symbol}: {len(batch_urls)} URLs")
                
                # Skip duplicate check at crawl stage so that list pages already seen can still be parsed to extract deep links.
                batch_results = await crawler.batch_crawl_articles(batch_urls, skip_duplicate_check=True)
                
                # 合并搜索结果和爬取结果
                deep_candidates: List[str] = []
                for search_result, crawl_result in zip(batch, batch_results):
                    if crawl_result.get('status') == 'success':
                        merged_result = {**search_result, **crawl_result}
                        crawl_results.append(merged_result)
                        self.stats["articles_crawled"] += 1
                        # 收集深度链接候选（仅一层）
                        for dl in crawl_result.get('deep_links', []) or []:
                            if isinstance(dl, str) and dl.startswith('http'):
                                deep_candidates.append(dl)
                    else:
                        detail = crawl_result.get('error_detail')
                        if isinstance(detail, dict) and detail:
                            logging.warning(
                                "Failed to crawl %s: %s | detail=%s",
                                crawl_result.get('url', 'unknown'),
                                crawl_result.get('error', 'unknown error'),
                                detail,
                            )
                            # 记录抓取失败
                            try:
                                if not self.storage:
                                    self.storage = await get_storage()
                                await self.storage.log_news_error(
                                    'crawl',
                                    url=crawl_result.get('url'),
                                    domain=crawl_result.get('domain'),
                                    symbol=symbol,
                                    message=crawl_result.get('error'),
                                    detail=detail,
                                )
                            except Exception:
                                pass
                        else:
                            logging.warning(
                                "Failed to crawl %s: %s",
                                crawl_result.get('url', 'unknown'),
                                crawl_result.get('error', 'unknown error')
                            )
                            # 记录抓取失败（无明细）
                            try:
                                if not self.storage:
                                    self.storage = await get_storage()
                                await self.storage.log_news_error(
                                    'crawl',
                                    url=crawl_result.get('url'),
                                    domain=crawl_result.get('domain'),
                                    symbol=symbol,
                                    message=crawl_result.get('error'),
                                    detail=None,
                                )
                            except Exception:
                                pass

                # 一层深度抓取（限制数量防止放大），优先新浪VIP公告详情、东方财富“原文/来源”
                if deep_candidates:
                    # 去重并限制
                    seen = set()
                    filtered = []
                    for u in deep_candidates:
                        if u not in seen:
                            seen.add(u)
                            filtered.append(u)
                    # 排序：优先包含 'Bulletin','notice','doc','view','原文','阅读'
                    def _prio(u: str) -> int:
                        l = u.lower()
                        score = 0
                        for k in ['bulletin', 'notice', 'doc', 'view']:
                            if k in l:
                                score += 2
                        for k in ['原文', '阅读', '来源']:
                            if k in u:
                                score += 1
                        return -score
                    filtered.sort(key=_prio)
                    # 限制每批的深度抓取数量
                    max_deep = max(2, min(6, len(filtered)))
                    deep_to_crawl = filtered[:max_deep]
                    try:
                        deep_results = await crawler.batch_crawl_articles(deep_to_crawl, skip_duplicate_check=True)
                        for deep_url, deep_res in zip(deep_to_crawl, deep_results):
                            if deep_res.get('status') == 'success':
                                merged = {"url": deep_url, **deep_res}
                                crawl_results.append(merged)
                                self.stats["articles_crawled"] += 1
                            else:
                                d2 = deep_res.get('error_detail')
                                if isinstance(d2, dict) and d2:
                                    logging.warning("Failed deep-crawl %s: %s | detail=%s", deep_url, deep_res.get('error', 'unknown error'), d2)
                                else:
                                    logging.warning("Failed deep-crawl %s: %s", deep_url, deep_res.get('error', 'unknown error'))
                    except Exception as e:
                        logging.warning(f"Deep crawl batch failed: {e}")
                        try:
                            if not self.storage:
                                self.storage = await get_storage()
                            await self.storage.log_news_error('crawl', url=None, domain=None, symbol=symbol, message=f"deep-batch: {e}")
                        except Exception:
                            pass
        
        return crawl_results
    
    async def _process_and_save_articles(self, crawl_results: List[Dict[str, Any]], symbol: str) -> int:
        """
        处理并保存文章
        """
        saved_count = 0
        
        async with LLMNewsProcessor() as llm_processor:
            for article_data in crawl_results:
                t_article_start = time.perf_counter()
                url_short = (article_data.get('url') or '')[:160]
                try:
                    # 去重检查
                    duplicate_result = await self.deduplicator.check_duplicate(
                        url=article_data.get('url', ''),
                        title=article_data.get('title', ''),
                        content=article_data.get('content', '')
                    )
                    
                    if duplicate_result.is_duplicate:
                        self.stats["duplicates_skipped"] += 1
                        logging.debug(f"Skipping duplicate article: {article_data.get('url', 'unknown')}")
                        continue
                    
                    # 准备分析内容：如果 content 为空或太短，使用 title + summary
                    title = article_data.get('title', '')
                    content = article_data.get('content', '')
                    summary = article_data.get('summary', '')
                    
                    # 对于 PDF 公告尝试下载并解析正文优先作为分析内容
                    analysis_content = content
                    source_type = article_data.get('source', '')
                    is_pdf = article_data.get('is_pdf', False) or (source_type in ('eastmoney_ann', 'cninfo') and article_data.get('url', '').lower().endswith('.pdf'))

                    # 使用统一文档管理器处理 PDF（对象存储 + 结构化标签）
                    pdf_processed_doc = None
                    if is_pdf:
                        try:
                            logging.info(f"Processing PDF via UnifiedDocumentManager: {article_data.get('url', '')}")
                            doc = UnifiedDocument(
                                title=title,
                                url=article_data.get('url', ''),
                                source=source_type or 'unknown',
                                symbol=symbol,
                                published_at=article_data.get('published'),
                                is_pdf=True,
                                content_type='pdf',
                                raw_content=summary or ''
                            )
                            pdf_processed_doc = await self.doc_manager.pipeline.process_document(doc)
                            
                            # 使用提取的文本作为分析内容
                            if pdf_processed_doc.extracted_text and len(pdf_processed_doc.extracted_text) > 120:
                                analysis_content = pdf_processed_doc.extracted_text
                                logging.info(f"PDF extracted text length: {len(analysis_content)}")
                            else:
                                # fallback to title+summary
                                analysis_content = title
                                if summary and summary != title:
                                    analysis_content = f"{title}\n\n{summary}"
                                if source_type in ('eastmoney_ann', 'cninfo'):
                                    analysis_content = f"[公司公告] {analysis_content}"
                                logging.info(f"PDF extract empty/short; using title for analysis: {title[:50]}...")
                            
                            # 同时入库到 MongoDB documents 集合
                            await self.doc_manager.ingester.ingest_document(pdf_processed_doc)
                            
                        except Exception as e:
                            logging.warning(f"PDF pipeline failed, fallback to simple extraction: {e}")
                            # 降级：使用原有的简单提取
                            try:
                                extracted = await extract_text_from_pdf(article_data.get('url', ''))
                                if extracted and len(extracted) > 120:
                                    analysis_content = extracted
                            except Exception:
                                pass
                            if not analysis_content or len(analysis_content) < 100:
                                analysis_content = title if not summary else f"{title}\n\n{summary}"
                    else:
                        if not content or len(content) < 100:
                            # 非 PDF 且过短，使用标题+摘要
                            analysis_content = title
                            if summary and summary != title:
                                analysis_content = f"{title}\n\n{summary}"
                            if source_type in ('eastmoney_ann', 'cninfo'):
                                analysis_content = f"[公司公告] {analysis_content}"
                            logging.info(f"Using title as content for analysis: {title[:50]}...")
                    
                    # LLM分析（如果 PDF 已通过统一流水线分析，可跳过重复分析）
                    analysis_result = None
                    if pdf_processed_doc and pdf_processed_doc.llm_analyzed and pdf_processed_doc.tags:
                        # 使用 PDF 流水线的分析结果
                        logging.info(f"Using PDF pipeline analysis result for: {title[:50]}")
                        # 将 StructuredTags 转为 LLM 分析结果格式
                        from dataclasses import dataclass
                        @dataclass
                        class PDFAnalysisResult:
                            category: str = ''
                            keywords: list = None
                            entities: dict = None
                            sentiment_type: str = 'neutral'
                            sentiment_score: float = 0.0
                            stock_symbols: list = None
                            summary: str = ''
                            relevance_score: float = 0.5
                        
                        analysis_result = PDFAnalysisResult(
                            category=pdf_processed_doc.tags.document_type or 'announcement',
                            keywords=pdf_processed_doc.tags.keywords,
                            entities=pdf_processed_doc.tags.entities,
                            sentiment_type=pdf_processed_doc.tags.sentiment,
                            sentiment_score=pdf_processed_doc.tags.sentiment_score,
                            stock_symbols=[symbol],
                            summary=pdf_processed_doc.tags.summary,
                            relevance_score=0.8 if pdf_processed_doc.tags.importance == 'high' else 0.5
                        )
                    else:
                        # 使用传统 LLM 分析
                            t_llm0 = time.perf_counter()
                            analysis_result = await llm_processor.analyze_news(
                                title=title,
                                content=analysis_content,
                                url=article_data.get('url', '')
                            )
                            t_llm1 = time.perf_counter()
                            logging.info("[PERF] llm_analyze url=%s symbol=%s duration=%.3f", url_short, symbol, (t_llm1 - t_llm0))
                    
                    # 保存到数据库（附带 PDF 元数据）
                    pdf_meta = None
                    if pdf_processed_doc and pdf_processed_doc.pdf_meta:
                        pdf_meta = {
                            'storage_path': pdf_processed_doc.pdf_meta.storage_path,
                            'file_hash': pdf_processed_doc.pdf_meta.file_hash,
                            'file_size': pdf_processed_doc.pdf_meta.file_size,
                            'page_count': pdf_processed_doc.pdf_meta.page_count,
                            'extraction_status': pdf_processed_doc.pdf_meta.extraction_status,
                        }
                        article_data['pdf_meta'] = pdf_meta
                        article_data['extracted_text'] = pdf_processed_doc.extracted_text
                    
                    t_save0 = time.perf_counter()
                    saved = await self._save_article_to_db(article_data, analysis_result, symbol)
                    t_save1 = time.perf_counter()
                    if saved:
                        saved_count += 1
                        self.stats["articles_processed"] += 1
                        self.stats["articles_saved"] += 1
                    logging.info("[PERF] save_article url=%s symbol=%s saved=%s db_duration=%.3f total_article_duration=%.3f", url_short, symbol, saved, (t_save1 - t_save0), (time.perf_counter() - t_article_start))
                
                except Exception as e:
                    logging.error(f"Failed to process article {article_data.get('url', 'unknown')}: {e}")
                    self.stats["errors"] += 1
        
        return saved_count
    
    async def _save_article_to_db(
        self, 
        article_data: Dict[str, Any], 
        analysis_result: Optional[Any], 
        symbol: str
    ) -> bool:
        """
        保存文章到数据库和MongoDB
        """
        session = self.session_factory()
        try:
            # 确保MongoDB存储已初始化
            if not self.storage:
                self.storage = await get_storage()
            
            # 获取或创建新闻源
            source = await self._get_or_create_source(article_data.get('domain', ''), session)
            
            # 构建相关股票列表
            related_stocks = [symbol]
            if analysis_result and analysis_result.stock_symbols:
                related_stocks.extend(analysis_result.stock_symbols)
            related_stocks = list(set(related_stocks))  # 去重
            
            # 创建PostgreSQL文章记录
            article = NewsArticle(
                title=article_data.get('title', ''),
                url=article_data.get('url', ''),
                content=article_data.get('content', ''),
                summary=analysis_result.summary if analysis_result else article_data.get('summary', ''),
                author=article_data.get('author'),
                published_at=self._parse_published_date(article_data.get('published_date')),
                crawled_at=datetime.utcnow(),
                source_id=source.id,
                category=analysis_result.category if analysis_result else NewsCategory.FINANCE.value,
                keywords=analysis_result.keywords if analysis_result else article_data.get('keywords', []),
                entities=analysis_result.companies + analysis_result.people + analysis_result.locations if analysis_result else article_data.get('entities', []),
                sentiment_type=analysis_result.sentiment_type if analysis_result else None,
                sentiment_score=analysis_result.sentiment_score if analysis_result else None,
                sentiment_confidence=analysis_result.sentiment_confidence if analysis_result else None,
                related_stocks=related_stocks,
                relevance_score=analysis_result.relevance_score if analysis_result else article_data.get('content_quality', 0.5),
                content_quality=analysis_result.content_quality if analysis_result else article_data.get('content_quality', 0.5),
                is_duplicate=False
            )
            
            session.add(article)
            t_commit0 = time.perf_counter()
            session.commit()
            t_commit1 = time.perf_counter()
            logging.info("[PERF] db_commit article=%s symbol=%s commit_duration=%.3f", (article.title or '')[:60], symbol, (t_commit1 - t_commit0))
            
            # 保存到MongoDB主集合
            mongo_article_data = {
                'url': article_data.get('url', ''),
                'title': article_data.get('title', ''),
                'content': article_data.get('content', ''),
                'summary': analysis_result.summary if analysis_result else article_data.get('summary', ''),
                'author': article_data.get('author'),
                'published_at': self._parse_published_date(article_data.get('published_date')),
                'source': article_data.get('domain', ''),
                'category': analysis_result.category if analysis_result else 'finance',
                'keywords': analysis_result.keywords if analysis_result else article_data.get('keywords', []),
                'entities': analysis_result.companies + analysis_result.people + analysis_result.locations if analysis_result else [],
                'sentiment_score': analysis_result.sentiment_score if analysis_result else None,
                'related_stocks': related_stocks,
                'relevance_score': analysis_result.relevance_score if analysis_result else 0.5,
                'content_quality': analysis_result.content_quality if analysis_result else 0.5
            }
            
            article_id = await self.storage.save_news_article(mongo_article_data)
            
            if article_id:
                # 为每个相关股票创建存档条目
                for stock_symbol in related_stocks:
                    await self.storage.archive_stock_news(
                        stock_symbol=stock_symbol,
                        article_id=article_id,
                        relevance_score=analysis_result.relevance_score if analysis_result else 0.5,
                        sentiment_score=analysis_result.sentiment_score if analysis_result else 0.0,
                        article_summary={
                            'title': article_data.get('title', ''),
                            'summary': analysis_result.summary if analysis_result else '',
                            'keywords': analysis_result.keywords if analysis_result else [],
                            'entities': analysis_result.companies if analysis_result else []
                        }
                    )
                
                # 保存LLM分析结果
                if analysis_result:
                    await self.storage.save_news_analytics(
                        article_id=article_id,
                        analysis_type='sentiment',
                        analysis_result={
                            'sentiment_type': analysis_result.sentiment_type,
                            'sentiment_score': analysis_result.sentiment_score,
                            'sentiment_confidence': analysis_result.sentiment_confidence,
                            'category': analysis_result.category,
                            'keywords': analysis_result.keywords,
                            'entities': {
                                'companies': analysis_result.companies,
                                'people': analysis_result.people,
                                'locations': analysis_result.locations
                            }
                        },
                        confidence_score=analysis_result.sentiment_confidence or 0.0
                    )
                
                # 保存去重信息（通过兼容包装器，避免直接访问私有方法导致 AttributeError）
                content_hash = self._dedup_generate_content_hash(article_data.get('content', ''))
                fingerprint = self._dedup_generate_fingerprint(
                    article_data.get('title', ''),
                    article_data.get('content', ''),
                    content_hash=content_hash
                )

                await self.storage.save_duplicate_detection(
                    url=article_data.get('url', ''),
                    content_hash=content_hash,
                    fingerprint=fingerprint
                )
            
            logging.debug(f"✓ Saved article to PostgreSQL and MongoDB: {article.title[:50]}...")
            return True
            
        except Exception as e:
            session.rollback()
            logging.error(f"Failed to save article to database: {e}")
            return False
        finally:
            session.close()
    
    async def _get_or_create_source(self, domain: str, session: Session):
        """
        获取或创建新闻源
        """
        from ..core.models import NewsSource
        
        if not domain:
            domain = "unknown"
        
        # 查找现有源
        source = session.execute(
            select(NewsSource).where(NewsSource.domain == domain)
        ).scalar_one_or_none()
        
        if not source:
            # 创建新源
            source = NewsSource(
                name=domain,
                domain=domain,
                category=NewsCategory.FINANCE.value,
                reliability_score=0.6,
                language="zh-CN",
                enabled=True
            )
            session.add(source)
            session.commit()
            session.refresh(source)
        
        return source
    
    def _parse_published_date(self, date_str: Any) -> Optional[datetime]:
        """
        解析发布日期
        """
        if isinstance(date_str, datetime):
            return date_str
        
        if not date_str:
            return None
        
        # 这里可以添加更复杂的日期解析逻辑
        return None
    
    async def _cleanup_old_data(self):
        """
        清理旧数据
        """
        try:
            session = self.session_factory()
            
            # 删除30天前的新闻文章
            cutoff_date = datetime.utcnow() - timedelta(days=30)
            
            deleted_count = session.execute(
                NewsArticle.__table__.delete().where(
                    NewsArticle.crawled_at < cutoff_date
                )
            ).rowcount
            
            session.commit()
            
            if deleted_count > 0:
                logging.info(f"Cleaned up {deleted_count} old articles")
            
        except Exception as e:
            logging.error(f"Failed to cleanup old data: {e}")
        finally:
            session.close()
    
    def _create_result(
        self, 
        status: str, 
        start_time: datetime, 
        message: str = "", 
        end_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        创建结果字典
        """
        if not end_time:
            end_time = datetime.utcnow()
        
        duration = (end_time - start_time).total_seconds()
        
        return {
            "status": status,
            "message": message,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": duration,
            "statistics": self.stats.copy()
        }
    
    async def run_intelligent_news_collection(self) -> Dict[str, Any]:
        """
        运行智能新闻收集（基于策略）
        """
        from ..news.news_strategy import IntelligentNewsCollector
        
        try:
            intelligent_collector = IntelligentNewsCollector()
            
            # 生成策略
            strategies = await intelligent_collector.generate_strategies()
            logging.info(f"Generated {len(strategies)} news collection strategies")
            
            # 执行策略
            results = []
            for strategy in strategies:
                try:
                    result = await self._execute_news_strategy(strategy)
                    results.append(result)
                except Exception as e:
                    logging.error(f"Failed to execute strategy {strategy.name}: {e}")
                    results.append({"status": "error", "strategy": strategy.name, "error": str(e)})
            
            return {
                "status": "success",
                "strategies_executed": len(results),
                "results": results
            }
            
        except Exception as e:
            logging.error(f"Intelligent news collection failed: {e}")
            return {"status": "error", "error": str(e)}
    
    async def _execute_news_strategy(self, strategy) -> Dict[str, Any]:
        """
        执行新闻策略
        """
        try:
            # 基于策略关键词搜索新闻
            query = " ".join(strategy.keywords[:3])  # 使用前3个关键词
            
            search_results = await self.news_search_service.search_industry_news(
                industry=strategy.name,
                keywords=strategy.keywords
            )
            
            if not search_results:
                return {"status": "no_results", "strategy": strategy.name}
            
            # 处理搜索结果（简化版本）
            processed_count = 0
            for result in search_results[:10]:  # 限制数量
                # 这里可以添加更详细的处理逻辑
                processed_count += 1
            
            return {
                "status": "success",
                "strategy": strategy.name,
                "found": len(search_results),
                "processed": processed_count
            }
            
        except Exception as e:
            logging.error(f"Failed to execute strategy {strategy.name}: {e}")
            return {"status": "error", "strategy": strategy.name, "error": str(e)}
    
    async def get_collection_status(self) -> Dict[str, Any]:
        """
        获取收集状态
        """
        session = self.session_factory()
        try:
            # 今日统计
            today = datetime.utcnow().date()
            today_start = datetime.combine(today, datetime.min.time())
            
            today_articles = session.execute(
                select(func.count(NewsArticle.id)).where(
                    NewsArticle.crawled_at >= today_start
                )
            ).scalar()
            
            # 本周统计
            week_start = today_start - timedelta(days=today.weekday())
            week_articles = session.execute(
                select(func.count(NewsArticle.id)).where(
                    NewsArticle.crawled_at >= week_start
                )
            ).scalar()
            
            # 总统计
            total_articles = session.execute(
                select(func.count(NewsArticle.id))
            ).scalar()
            
            # 待处理任务
            pending_tasks = session.execute(
                select(func.count(Task.id)).where(
                    and_(
                        Task.task_type == TaskType.FETCH_NEWS,
                        Task.status == TaskStatus.PENDING
                    )
                )
            ).scalar()
            
            return {
                "today_articles": today_articles,
                "week_articles": week_articles,
                "total_articles": total_articles,
                "pending_tasks": pending_tasks,
                "last_collection": self.stats,
                "status": "ready"
            }
            
        finally:
            session.close()
