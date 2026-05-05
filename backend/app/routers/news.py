from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import select, text, and_, or_, func
from typing import List, Optional, Dict, Any, Tuple
from pydantic import BaseModel, Field, validator
import asyncio
import time
from datetime import datetime, timedelta
import os
import re
import requests

# Import project internals
from ..core.db import SessionLocal
from ..core.models import NewsArticle, NewsSource, Watchlist, NewsQueryTemplate
from ..data.data_source import get_stock_info
from ..news.news_service import NewsSearchService, NewsProcessor
from ..news.news_crawler import NewsContentCrawler
from ..tasks.task_manager import Task, TaskStatus, TaskType
# NOTE: enhanced_news_scheduler instance does not exist in scheduler module; remove incorrect import.
# If scheduling functionality is needed here later, import and instantiate EnhancedNewsScheduler directly.
from ..reports.macro_report import generate_and_store_macro_report  # if needed elsewhere
from ..prediction.forecast import predict_stock_price  # placeholder if reused
from ..reports.report import generate_report_data  # placeholder if reused
from ..tasks.task_manager import TaskManager
from ..news.enhanced_news_scheduler import EnhancedNewsScheduler
from ..utils.mongo_storage import get_storage
from ..agents.page_crawl_agent import PageCrawlAgent, PageCrawlOptions
from urllib.parse import urlparse, urljoin
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

router = APIRouter(prefix="/api/news", tags=["news"])

# Dependency
def get_db():
    # 确保每次请求获取独立短生命周期的会话，避免持有时间过长导致连接池耗尽
    db = SessionLocal()
    try:
        yield db
    finally:
        try:
            db.close()
        except Exception:
            pass

# --------- Schemas ---------
class NewsSearchRequest(BaseModel):
    query: str
    category: Optional[str] = None
    time_range: Optional[str] = Field(None, description="e.g. '7d', '30d'")
    max_results: int = 50
    language: Optional[str] = Field(None, description="e.g. zh-CN|en")
    engines: Optional[str] = Field(None, description="Comma-separated searxng engines override")
    include_domains: Optional[List[str]] = Field(None, description="Only include results from these domains (host or suffix)")
    exclude_domains: Optional[List[str]] = Field(None, description="Exclude results from these domains (host or suffix)")
    since: Optional[str] = Field(None, description="Incremental: only results with published_at >= since (ISO or YYYY-MM-DD)")

class NewsResponse(BaseModel):
    articles: List[dict]
    total_count: int
    query: str
    processing_time: float

class NewsArticleUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    sentiment_type: Optional[str] = Field(None, description="positive|negative|neutral")
    sentiment_score: Optional[float] = None
    related_stocks: Optional[List[str]] = None

    @validator('sentiment_type')
    def validate_sentiment(cls, v):
        if v is None:
            return v
        if v not in {"positive", "negative", "neutral"}:
            raise ValueError("sentiment_type must be one of positive|negative|neutral")
        return v

# --------- Query Template (范式) 管理 ---------
class QueryTemplateIn(BaseModel):
    scope: str = Field("global", description="global|symbol|industry")
    target: Optional[str] = Field(None, description="作用对象，symbol 如 600519.SH 或行业名；global 可为空")
    template: str = Field(..., max_length=500)
    enabled: bool = True
    priority: int = Field(5, ge=0, le=100)
    notes: Optional[str] = None

    @validator('scope')
    def _scope_valid(cls, v):
        v2 = (v or '').lower()
        if v2 not in { 'global', 'symbol', 'industry' }:
            raise ValueError('scope must be global|symbol|industry')
        return v2

    @validator('template')
    def _template_reserved_placeholder(cls, v):
        s = (v or '').strip()
        if not s:
            raise ValueError('template must not be empty')
        # 至少包含一个保留占位符，避免完全固定文本导致泛化差
        placeholders = ("{symbol}", "{name}", "{industry}")
        if not any(p in s for p in placeholders):
            raise ValueError('模板需至少包含以下占位符之一: {symbol} / {name} / {industry}')
        return s

class QueryTemplateOut(BaseModel):
    id: int
    scope: str
    target: Optional[str]
    template: str
    enabled: bool
    priority: int
    notes: Optional[str]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class QueryTemplateList(BaseModel):
    total: int
    items: List[QueryTemplateOut]

@router.get('/query-templates')
def list_query_templates(
    scope: Optional[str] = Query(None),
    target: Optional[str] = Query(None),
    enabled: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
) -> QueryTemplateList:
    # 若表为空，写入一个默认全局模板作为示例/兜底
    # 注意：此处为轻量“种子”，不影响已有数据
    try:
        existing_cnt = db.execute(select(NewsQueryTemplate.id).limit(1)).first()
        if not existing_cnt:
            now = datetime.utcnow()
            default_tpl = NewsQueryTemplate(
                scope='global', target=None,
                template='{symbol} OR {name} (公告 OR 舆情 OR 经营 OR 订单 OR 投资 OR 产能 OR 签约 OR 报告)',
                enabled=True, priority=5,
                notes='系统默认模板：可在此基础上按需调整',
                created_at=now, updated_at=now,
            )
            db.add(default_tpl)
            db.commit()
    except Exception:
        # 种子写入失败不应影响查询
        db.rollback()

    q = select(NewsQueryTemplate)
    if scope:
        q = q.where(NewsQueryTemplate.scope == scope.lower())
    if target:
        q = q.where(NewsQueryTemplate.target == target)
    if enabled is not None:
        q = q.where(NewsQueryTemplate.enabled == enabled)
    q = q.order_by(NewsQueryTemplate.priority.desc(), NewsQueryTemplate.id.desc())
    rows = db.execute(q).scalars().all()
    def _to(o: NewsQueryTemplate) -> QueryTemplateOut:
        return QueryTemplateOut(
            id=o.id, scope=o.scope, target=o.target, template=o.template, enabled=o.enabled,
            priority=o.priority, notes=o.notes,
            created_at=(o.created_at.isoformat() if getattr(o, 'created_at', None) else None),
            updated_at=(o.updated_at.isoformat() if getattr(o, 'updated_at', None) else None),
        )
    return QueryTemplateList(total=len(rows), items=[_to(r) for r in rows])

@router.post('/query-templates')
def create_query_template(body: QueryTemplateIn, db: Session = Depends(get_db)) -> QueryTemplateOut:
    now = datetime.utcnow()
    row = NewsQueryTemplate(
        scope=body.scope.lower(), target=(body.target or None), template=body.template.strip(),
        enabled=body.enabled, priority=body.priority, notes=(body.notes or None),
        created_at=now, updated_at=now
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return QueryTemplateOut(
        id=row.id, scope=row.scope, target=row.target, template=row.template, enabled=row.enabled,
        priority=row.priority, notes=row.notes,
        created_at=(row.created_at.isoformat() if row.created_at else None),
        updated_at=(row.updated_at.isoformat() if row.updated_at else None),
    )

@router.patch('/query-templates/{tid}')
def update_query_template(tid: int, body: QueryTemplateIn, db: Session = Depends(get_db)) -> QueryTemplateOut:
    row = db.get(NewsQueryTemplate, tid)
    if not row:
        raise HTTPException(status_code=404, detail='template not found')
    row.scope = body.scope.lower()
    row.target = (body.target or None)
    row.template = body.template.strip()
    row.enabled = body.enabled
    row.priority = body.priority
    row.notes = (body.notes or None)
    row.updated_at = datetime.utcnow()
    db.add(row)
    db.commit()
    db.refresh(row)
    return QueryTemplateOut(
        id=row.id, scope=row.scope, target=row.target, template=row.template, enabled=row.enabled,
        priority=row.priority, notes=row.notes,
        created_at=(row.created_at.isoformat() if row.created_at else None),
        updated_at=(row.updated_at.isoformat() if row.updated_at else None),
    )

@router.delete('/query-templates/{tid}')
def delete_query_template(tid: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    row = db.get(NewsQueryTemplate, tid)
    if not row:
        raise HTTPException(status_code=404, detail='template not found')
    db.delete(row)
    db.commit()
    return {"status": "ok", "deleted_id": tid}

# --------- 模板测试（不保存，仅返回效果预览） ---------
class QueryTemplateTestIn(BaseModel):
    template: str = Field(..., max_length=500, description="包含占位符的模板，如 '{symbol} OR {name} 公告 舆情'")
    symbol: Optional[str] = Field(None, description="如 600519.SH；用于替换 {symbol}")
    name: Optional[str] = Field(None, description="公司名称；用于替换 {name}")
    industry: Optional[str] = Field(None, description="行业名；用于替换 {industry}")
    # 额外关键字，以空格/逗号分隔（前端也可传数组后端合并为字符串）
    extra_keywords: Optional[str] = Field(None, description="自定义关键字，空格或逗号分隔")
    # 可选搜索参数
    time_range: Optional[str] = Field(None, description="如 '7d'|'30d'")
    max_results: int = Field(20, ge=1, le=100)
    language: Optional[str] = Field(None, description="zh-CN|en 等")
    engines: Optional[str] = Field(None, description="覆盖 searxng 引擎列表")

class QueryTemplateTestOut(BaseModel):
    built_query: str
    total_count: int
    results: List[Dict[str, Any]]

def _build_query_from_template(tpl: str, symbol: Optional[str], name: Optional[str], industry: Optional[str], extra_keywords: Optional[str]) -> str:
    s = tpl or ''
    # 使用安全替换，避免 str.format KeyError
    if symbol:
        s = s.replace('{symbol}', symbol)
    if name:
        s = s.replace('{name}', name)
    if industry:
        s = s.replace('{industry}', industry)
    # 未提供的占位符替换为空，以避免残留花括号影响检索
    s = s.replace('{symbol}', '').replace('{name}', '').replace('{industry}', '')
    # 附加自定义关键字
    if extra_keywords:
        # 支持逗号/空格分隔
        parts = [p.strip() for p in extra_keywords.replace(',', ' ').split() if p.strip()]
        if parts:
            s = s + ' ' + ' '.join(parts)
    # 规整空白
    return ' '.join(s.split())

@router.post('/query-templates/test')
async def test_query_template(body: QueryTemplateTestIn, db: Session = Depends(get_db)) -> QueryTemplateTestOut:
    # 若 name/industry 缺失且提供了 symbol，可尝试从 Watchlist 或其他表补全名称
    symbol = body.symbol
    name = body.name
    industry = body.industry
    if symbol and not name:
        try:
            w = db.execute(select(Watchlist).where(Watchlist.symbol == symbol)).scalar_one_or_none()
            if w and getattr(w, 'name', None):
                name = w.name
            if w and getattr(w, 'sector', None) and not industry:
                industry = w.sector
        except Exception:
            pass

    # 校验模板包含至少一个占位符
    QueryTemplateIn(template=body.template, scope='global')  # 复用校验逻辑
    built = _build_query_from_template(body.template, symbol, name, industry, body.extra_keywords)

    svc = NewsSearchService()
    results = await svc.search_news(
        query=built,
        category='general',
        time_range=body.time_range,
        max_results=body.max_results,
        language=body.language or os.getenv("SEARXNG_LANGUAGE", None),
        engines=body.engines,
        include_domains=None,
        exclude_domains=None,
        since=None,
    )
    # 仅返回必要字段，避免前端渲染过重
    def _pick(x: Dict[str, Any]) -> Dict[str, Any]:
        return {
            'title': x.get('title'),
            'url': x.get('url'),
            'published': x.get('published') or x.get('publishedDate') or x.get('date') or x.get('published_at'),
            'source': x.get('source') or x.get('engine'),
        }
    return QueryTemplateTestOut(built_query=built, total_count=len(results), results=[_pick(r) for r in results])

# --------- 股票列表（按文章归档聚合） ---------
class StockListItem(BaseModel):
    symbol: str
    name: Optional[str] = None
    start_date: Optional[str] = None
    article_count: int

class StockListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[StockListItem]

@router.get('/stocks')
def list_stocks(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    q: Optional[str] = Query(None, description="按 symbol 或名称模糊过滤"),
) -> StockListResponse:
    """
    基于 news_articles.related_stocks 聚合出出现过的股票清单：
    - start_date：首次出现的发布时间/抓取时间（最早）
    - article_count：相关文章条数
    - name：优先取 watchlist.name，其次 stock_profiles.company_name（若存在）
    """
    # 先做聚合（distinct symbol + min date + count）
    sql_core = text(
        r"""
        WITH unnest AS (
            SELECT jsonb_array_elements_text(related_stocks) AS stock,
                   COALESCE(published_at, crawled_at) AS dt
            FROM news_articles
            WHERE related_stocks IS NOT NULL
        ), agg AS (
            SELECT stock AS symbol,
                   MIN(dt) AS start_dt,
                   COUNT(*) AS cnt
            FROM unnest
            GROUP BY stock
        ), named AS (
            SELECT a.symbol,
                   a.start_dt,
                   a.cnt,
                   COALESCE(w.name, sp.company_name, st.name) AS name
            FROM agg a
            LEFT JOIN watchlist w ON w.symbol = a.symbol
            LEFT JOIN stock_profiles sp ON sp.symbol = a.symbol
            LEFT JOIN stocks st ON st.symbol = a.symbol
        )
    SELECT * FROM named
    WHERE LENGTH(symbol) = 9 AND (symbol LIKE '%.SH' OR symbol LIKE '%.SZ') AND symbol NOT LIKE '% %'
        {and_more}
        ORDER BY start_dt ASC NULLS LAST, symbol ASC
        LIMIT :lim OFFSET :off
        """.replace("{and_more}", "AND (symbol ILIKE :pat OR name ILIKE :pat)" if q else "")
    )
    params = {"lim": page_size, "off": (page-1)*page_size}
    if q:
        params["pat"] = f"%{q}%"
    rows = db.execute(sql_core, params).all()
    items = []
    for r in rows:
        start_dt = None
        if hasattr(r, 'start_dt') and r.start_dt is not None:
            try:
                start_dt = r.start_dt.isoformat()
            except Exception:
                start_dt = None
        items.append(StockListItem(symbol=r.symbol, name=getattr(r, 'name', None), start_date=start_dt, article_count=int(r.cnt)))
    # 统计 total（可优化为物化视图；此处简单实现）
    sql_total = text(
        r"""
        WITH unnest AS (
            SELECT jsonb_array_elements_text(related_stocks) AS stock
            FROM news_articles
            WHERE related_stocks IS NOT NULL
        )
        SELECT COUNT(DISTINCT stock) AS total
        FROM unnest
        WHERE LENGTH(stock) = 9 AND (stock LIKE '%.SH' OR stock LIKE '%.SZ') AND stock NOT LIKE '% %'
        {and_more}
        """.replace("{and_more}", "AND stock ILIKE :pat" if q else "")
    )
    params2 = {}
    if q:
        params2["pat"] = f"%{q}%"
    total_row = db.execute(sql_total, params2).first()
    total = int(total_row.total) if total_row and hasattr(total_row, 'total') else 0
    return StockListResponse(total=total, page=page, page_size=page_size, items=items)

# --------- 爬虫反馈 ---------
class CrawlerFeedbackIn(BaseModel):
    url: str = Field(..., max_length=1000)
    symbol: Optional[str] = Field(None, description="相关股票代码")
    notes: Optional[str] = Field(None, max_length=1000, description="补充说明：未抓全、结构异常等")

class CrawlerFeedbackOut(BaseModel):
    status: str
    accepted: bool
    storage: str

@router.post('/crawler/feedback')
async def crawler_feedback(payload: CrawlerFeedbackIn) -> CrawlerFeedbackOut:
    u = (payload.url or '').strip()
    if not (u.startswith('http://') or u.startswith('https://')):
        raise HTTPException(status_code=400, detail='url must start with http/https')
    parsed = urlparse(u)
    domain = parsed.netloc
    try:
        storage = await get_storage()
        if storage is None or storage.db is None:
            # Mongo 不可用：接受反馈但仅记录日志
            return CrawlerFeedbackOut(status='accepted_no_storage', accepted=True, storage='disabled')
        doc = {
            'kind': 'feedback',
            'url': u,
            'url_hash': hash(u),
            'domain': domain,
            'symbol': payload.symbol,
            'notes': payload.notes,
            'created_at': datetime.utcnow().isoformat(),
            'status': 'new',
        }
        coll = storage.db[storage.collections['news_error_logs']]
        await coll.insert_one(doc)
        return CrawlerFeedbackOut(status='ok', accepted=True, storage='mongodb')
    except Exception as e:
        # 回退：接受但返回 degraded
        return CrawlerFeedbackOut(status=f'accepted_degraded:{str(e)}', accepted=True, storage='error')

# --------- Endpoints ---------

class RetrievalHealthResponse(BaseModel):
    ok: bool
    retrieval_mode: str
    q: Optional[str] = None
    engines: Optional[str] = None
    time_range: Optional[str] = None
    base_status: Optional[int] = None
    search_status: Optional[int] = None
    results_count: Optional[int] = None
    elapsed_ms: int
    error: Optional[str] = None


@router.get('/retrieval/health')
@router.get('/searxng/health')
async def retrieval_health(
    q: Optional[str] = Query(None, description="Test query override"),
) -> RetrievalHealthResponse:
    from ..agent.web_agent import AgenticWebRetriever
    started = time.time()
    error: Optional[str] = None
    results_count: Optional[int] = None
    readable_count: Optional[int] = None
    try:
        health = await AgenticWebRetriever().health_check(query=(q or 'A股 公司 新闻'))
        results_count = health.get('search_results')
        readable_count = health.get('readable_results')
        ok = bool(health.get('ok'))
    except Exception as e:
        ok = False
        error = f"{type(e).__name__}: {str(e)}"
    return RetrievalHealthResponse(
        ok=ok,
        retrieval_mode='openclaw_web',
        q=q,
        engines=None,
        time_range=None,
        base_status=200 if ok else None,
        search_status=200 if ok else None,
        results_count=results_count or readable_count,
        elapsed_ms=int((time.time() - started) * 1000),
        error=error,
    )


@router.post('/search')
async def search_news(request: NewsSearchRequest):
    try:
        start_time = time.time()
        news_search_service = NewsSearchService()
        category = request.category or "general"
        engines = request.engines
        if not (engines or '').strip():
            engines = (os.getenv('SEARXNG_ENGINES', '') or '').strip() or None

        # Special mode: engines='auto' will benchmark candidate engines by ingest dry_run rate
        # and return search results of the best engine. This is intentionally opt-in.
        chosen_engine = None
        if isinstance(engines, str) and engines.strip().lower() == 'auto':
            _, candidates = _parse_engine_candidates(None, None)
            eval_n = int(os.getenv('SEARXNG_AUTO_EVAL_MAX_ITEMS', '10') or '10')
            eval_n = max(1, min(eval_n, 50))
            best_score = None
            best_engine = None

            # Use a short-lived DB session for dry-run evaluation only
            with SessionLocal() as _db:
                for eng in candidates:
                    engine_str = (eng or '').strip()
                    if not engine_str:
                        continue
                    try:
                        sr = await news_search_service.search_news(
                            query=request.query,
                            category=category,
                            time_range=request.time_range,
                            max_results=min(int(request.max_results or 50), eval_n),
                            language=request.language,
                            engines=engine_str,
                            include_domains=request.include_domains,
                            exclude_domains=request.exclude_domains,
                            since=request.since,
                        )
                        ingest_items = _to_ingest_items_from_search_results(sr, max_items=eval_n)
                        ir = await _ingest_items_to_db(ingest_items, db=_db, dry_run=True, max_items=eval_n)
                        score = (ir.created, -ir.errors, -ir.skipped)
                        if best_score is None or score > best_score:
                            best_score = score
                            best_engine = engine_str
                    except Exception:
                        continue

            chosen_engine = best_engine or 'bing'
            engines = chosen_engine

        results = await news_search_service.search_news(
            query=request.query,
            category=category,
            time_range=request.time_range,
            max_results=request.max_results,
            language=request.language,
            engines=engines,
            include_domains=request.include_domains,
            exclude_domains=request.exclude_domains,
            since=request.since,
        )
        if chosen_engine and isinstance(results, list):
            for r in results:
                if isinstance(r, dict) and '_engine' not in r:
                    r['_engine'] = chosen_engine
        processing_time = time.time() - start_time
        return NewsResponse(
            articles=results,
            total_count=len(results),
            query=request.query,
            processing_time=processing_time
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"News search failed: {str(e)}")

class IncrementalSearchResponse(BaseModel):
    query: str
    total_count: int
    latest_published: Optional[str] = None
    articles: List[dict]

@router.post('/search_incremental')
async def search_news_incremental(request: NewsSearchRequest):
    """增量/按媒体源搜索：支持 include_domains/exclude_domains 与 since 过滤。

    - include_domains/exclude_domains: 通过后置过滤按域名筛选结果
    - since: 仅返回发布时间 >= since 的结果，便于增量拉取
    返回 latest_published 便于下一次调用作为 since 起点。
    """
    try:
        start_time = time.time()
        svc = NewsSearchService()
        category = request.category or "general"
        engines = request.engines
        if not (engines or '').strip():
            engines = (os.getenv('SEARXNG_ENGINES', '') or '').strip() or None

        chosen_engine = None
        if isinstance(engines, str) and engines.strip().lower() == 'auto':
            _, candidates = _parse_engine_candidates(None, None)
            eval_n = int(os.getenv('SEARXNG_AUTO_EVAL_MAX_ITEMS', '10') or '10')
            eval_n = max(1, min(eval_n, 50))
            best_score = None
            best_engine = None
            with SessionLocal() as _db:
                for eng in candidates:
                    engine_str = (eng or '').strip()
                    if not engine_str:
                        continue
                    try:
                        sr = await svc.search_news(
                            query=request.query,
                            category=category,
                            time_range=request.time_range,
                            max_results=min(int(request.max_results or 50), eval_n),
                            language=request.language or os.getenv("SEARXNG_LANGUAGE", None),
                            engines=engine_str,
                            include_domains=request.include_domains,
                            exclude_domains=request.exclude_domains,
                            since=request.since,
                        )
                        ingest_items = _to_ingest_items_from_search_results(sr, max_items=eval_n)
                        ir = await _ingest_items_to_db(ingest_items, db=_db, dry_run=True, max_items=eval_n)
                        score = (ir.created, -ir.errors, -ir.skipped)
                        if best_score is None or score > best_score:
                            best_score = score
                            best_engine = engine_str
                    except Exception:
                        continue
            chosen_engine = best_engine or 'bing'
            engines = chosen_engine

        results = await svc.search_news(
            query=request.query,
            category=category,
            time_range=request.time_range,
            max_results=request.max_results,
            language=request.language or os.getenv("SEARXNG_LANGUAGE", None),
            engines=engines,
            include_domains=request.include_domains,
            exclude_domains=request.exclude_domains,
            since=request.since,
        )
        if chosen_engine and isinstance(results, list):
            for r in results:
                if isinstance(r, dict) and '_engine' not in r:
                    r['_engine'] = chosen_engine
        # compute latest published for next since
        latest_dt = None
        for r in results:
            # reuse extraction via service helper by instantiating temporary service or duplicating simple parse
            pass
        # Simple inline parse to avoid extra coupling
        from datetime import datetime as _dt
        def _parse_pub(x):
            v = None
            for k in ("published", "publishedDate", "date", "published_at", "published_ts"):
                if k in x and x[k] is not None:
                    v = x[k]; break
            if v is None: return None
            if isinstance(v, (int, float)):
                try: return _dt.utcfromtimestamp(int(v))
                except Exception: return None
            if isinstance(v, str):
                s=v.strip()
                try: return _dt.fromisoformat(s.replace("Z","+00:00")).replace(tzinfo=None)
                except Exception: pass
                for fmt in ("%Y-%m-%d %H:%M:%S","%Y/%m/%d %H:%M","%Y-%m-%d"):
                    try: return _dt.strptime(s, fmt)
                    except Exception: continue
            return None
        for r in results:
            d = _parse_pub(r)
            if d and (latest_dt is None or d > latest_dt):
                latest_dt = d
        latest_str = latest_dt.isoformat() if latest_dt else None
        processing_time = time.time() - start_time
        return IncrementalSearchResponse(
            query=request.query,
            total_count=len(results),
            latest_published=latest_str,
            articles=results,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Incremental news search failed: {str(e)}")


# --------- Ingest (external crawler -> SQL) ---------
class NewsIngestItem(BaseModel):
    url: str = Field(..., max_length=2000)
    title: Optional[str] = Field(None, max_length=500)
    symbol: Optional[str] = Field(None, description="相关股票代码，如 300750 或 300750.SZ")
    company_name: Optional[str] = Field(None, max_length=200)
    published_at: Optional[str] = Field(None, description="ISO datetime or YYYY-MM-DD")

    @validator('url')
    def _url_http(cls, v: str):
        u = (v or '').strip()
        if not (u.startswith('http://') or u.startswith('https://')):
            raise ValueError('url must start with http/https')
        return u

    @validator('title')
    def _title_strip(cls, v: Optional[str]):
        if v is None:
            return None
        s = v.strip()
        return s if s else None

    @validator('symbol')
    def _symbol_strip(cls, v: Optional[str]):
        if v is None:
            return None
        s = str(v).strip().upper()
        return s if s else None


class NewsIngestRequest(BaseModel):
    items: List[NewsIngestItem] = Field(..., description="要入库的公告/新闻 URL 列表")
    dry_run: bool = Field(False, description="仅执行抓取/解析/过滤，不写入数据库")
    max_items: int = Field(50, ge=1, le=200)


class NewsIngestResult(BaseModel):
    url: str
    status: str  # created|duplicate|skipped|error
    article_id: Optional[int] = None
    reason: Optional[str] = None
    title_used: Optional[str] = None


class NewsIngestResponse(BaseModel):
    total: int
    created: int
    duplicates: int
    skipped: int
    errors: int
    created_ids: List[int]
    results: List[NewsIngestResult]


async def _ingest_items_to_db(
    items: List[NewsIngestItem],
    *,
    db: Session,
    dry_run: bool,
    max_items: int,
) -> NewsIngestResponse:
    if not items:
        return NewsIngestResponse(total=0, created=0, duplicates=0, skipped=0, errors=0, created_ids=[], results=[])

    safe_max = max(1, int(max_items or 50))
    safe_max = min(safe_max, 200)
    sliced = items[:safe_max]

    processor = NewsProcessor()

    created = 0
    duplicates = 0
    skipped = 0
    errors = 0
    created_ids: List[int] = []
    results: List[NewsIngestResult] = []

    for it in sliced:
        url = (it.url or '').strip()
        title = (it.title or '').strip()
        if not title:
            title = url
        sym = (it.symbol or None)

        try:
            existing = db.execute(select(NewsArticle).where(NewsArticle.url == url)).scalar_one_or_none()
            if existing is not None and getattr(existing, 'id', None):
                duplicates += 1
                results.append(NewsIngestResult(url=url, status='duplicate', article_id=int(existing.id), title_used=title))
                continue

            result_row: Dict[str, Any] = {
                'url': url,
                'title': title,
            }
            if it.published_at:
                result_row['published_at'] = it.published_at
            if it.company_name:
                result_row['company_name'] = it.company_name

            article = await processor._process_single_result(result_row, related_symbol=sym)
            if article is None:
                skipped += 1
                results.append(NewsIngestResult(url=url, status='skipped', reason='filtered_or_failed', title_used=title))
                continue

            if getattr(article, 'id', None):
                duplicates += 1
                results.append(NewsIngestResult(url=url, status='duplicate', article_id=int(article.id), title_used=title))
                continue

            if dry_run:
                created += 1
                results.append(NewsIngestResult(url=url, status='created', article_id=None, reason='dry_run', title_used=title))
                continue

            db.add(article)
            db.commit()
            db.refresh(article)
            created += 1
            created_ids.append(int(article.id))
            results.append(NewsIngestResult(url=url, status='created', article_id=int(article.id), title_used=title))
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            errors += 1
            results.append(NewsIngestResult(url=url, status='error', reason=str(e), title_used=title))

    return NewsIngestResponse(
        total=len(sliced),
        created=created,
        duplicates=duplicates,
        skipped=skipped,
        errors=errors,
        created_ids=created_ids,
        results=results,
    )


@router.post('/ingest')
async def ingest_news(payload: NewsIngestRequest, db: Session = Depends(get_db)) -> NewsIngestResponse:
    """外部爬虫/公告采集入口：将给定 URL 列表抓取并入库到 SQL(news_articles)。

    设计目标：最小闭环（发现 URL -> 调用 API -> 日报可用）。
    - 使用 NewsProcessor 进行抓取/正文抽取/去重/语言与相关性过滤（可复用已有风控逻辑）。
    - 入库目标为 SQL 的 news_articles（与现有 UI/日报共用）。
    """
    return await _ingest_items_to_db(
        payload.items,
        db=db,
        dry_run=bool(payload.dry_run),
        max_items=int(payload.max_items or 50),
    )


class NewsSearchAndIngestRequest(BaseModel):
    query: str
    category: Optional[str] = None
    time_range: Optional[str] = Field(None, description="e.g. '7d', '30d'")
    language: Optional[str] = Field(None, description="e.g. zh-CN|en")
    # If provided, do a single-engine run (comma-separated as searxng expects)
    engines: Optional[str] = Field(None, description="Comma-separated searxng engines override")
    # If engines is empty, auto-try candidates (defaults to env SEARXNG_AUTO_ENGINES or 'bing,baidu')
    auto_engines: Optional[List[str]] = Field(None, description="Candidate engines to benchmark, e.g. ['bing','baidu']")
    include_domains: Optional[List[str]] = Field(None)
    exclude_domains: Optional[List[str]] = Field(None)
    since: Optional[str] = Field(None, description="Incremental: only results with published_at >= since")

    # Search/ingest sizing
    search_max_results: int = Field(10, ge=1, le=50)
    eval_max_items: int = Field(10, ge=1, le=50, description='For auto mode: ingest dry_run evaluation size per engine')
    ingest_max_items: int = Field(20, ge=1, le=200)

    # Persist
    dry_run: bool = Field(True, description='If false, writes selected articles to DB')


class NewsSearchAndIngestEngineEval(BaseModel):
    engine: str
    search_count: int
    ingest_created: int
    ingest_duplicates: int
    ingest_skipped: int
    ingest_errors: int


class NewsSearchAndIngestResponse(BaseModel):
    query: str
    chosen_engine: Optional[str] = None
    candidates: List[NewsSearchAndIngestEngineEval]
    search_articles: List[dict]
    ingest: NewsIngestResponse


def _parse_engine_candidates(engines: Optional[str], auto_engines: Optional[List[str]]) -> Tuple[Optional[str], List[str]]:
    single = (engines or '').strip()
    if single:
        return single, []
    if auto_engines:
        cands = [str(x).strip() for x in auto_engines if str(x).strip()]
        return None, cands
    env = (os.getenv('SEARXNG_AUTO_ENGINES', '') or '').strip()
    if env:
        cands = [x.strip() for x in env.split(',') if x.strip()]
    else:
        cands = ['bing', 'baidu']
    return None, cands


def _to_ingest_items_from_search_results(results: List[dict], *, max_items: int) -> List[NewsIngestItem]:
    out: List[NewsIngestItem] = []
    limit = max(1, int(max_items or 10))
    for r in (results or []):
        if len(out) >= limit:
            break
        if not isinstance(r, dict):
            continue
        url = (r.get('url') or '').strip()
        if not url:
            continue
        title = (r.get('title') or '').strip() or url
        published_at = r.get('published_at') or r.get('published') or r.get('publishedDate')
        company_name = r.get('company_name')
        try:
            out.append(NewsIngestItem(url=url, title=title, published_at=published_at, company_name=company_name))
        except Exception:
            # Skip malformed URLs to keep endpoint robust
            continue
    return out


@router.post('/search_and_ingest')
async def search_and_ingest(payload: NewsSearchAndIngestRequest, db: Session = Depends(get_db)) -> NewsSearchAndIngestResponse:
    """一键：SearXNG 搜索 -> 传入真实 title -> ingest(dry_run 可选) -> (auto 模式下)选入库率更高的引擎。

    设计目的：解决“search 有结果但 ingest 大量 skipped”的问题；并支持“都试一下，哪个好用用哪个”。
    """

    single_engines, candidates = _parse_engine_candidates(payload.engines, payload.auto_engines)
    category = payload.category or 'general'
    language = payload.language
    svc = NewsSearchService()

    eval_rows: List[NewsSearchAndIngestEngineEval] = []
    chosen_engine: Optional[str] = None
    chosen_search_results: List[dict] = []
    chosen_ingest_items: List[NewsIngestItem] = []

    async def _run_one(engine_str: str, *, eval_only: bool) -> Tuple[List[dict], NewsIngestResponse]:
        search_results = await svc.search_news(
            query=payload.query,
            category=category,
            time_range=payload.time_range,
            max_results=int(payload.search_max_results or 10),
            language=language,
            engines=engine_str,
            include_domains=payload.include_domains,
            exclude_domains=payload.exclude_domains,
            since=payload.since,
        )
        ingest_items = _to_ingest_items_from_search_results(
            search_results,
            max_items=int(payload.eval_max_items if eval_only else payload.ingest_max_items),
        )
        ingest_res = await _ingest_items_to_db(
            ingest_items,
            db=db,
            dry_run=True if eval_only else bool(payload.dry_run),
            max_items=int(payload.eval_max_items if eval_only else payload.ingest_max_items),
        )
        return search_results, ingest_res

    if single_engines:
        chosen_engine = single_engines
        chosen_search_results, chosen_ingest_res = await _run_one(single_engines, eval_only=False)
        chosen_ingest_items = _to_ingest_items_from_search_results(chosen_search_results, max_items=int(payload.ingest_max_items))
        eval_rows.append(
            NewsSearchAndIngestEngineEval(
                engine=single_engines,
                search_count=len(chosen_search_results or []),
                ingest_created=chosen_ingest_res.created,
                ingest_duplicates=chosen_ingest_res.duplicates,
                ingest_skipped=chosen_ingest_res.skipped,
                ingest_errors=chosen_ingest_res.errors,
            )
        )
        return NewsSearchAndIngestResponse(
            query=payload.query,
            chosen_engine=chosen_engine,
            candidates=eval_rows,
            search_articles=chosen_search_results,
            ingest=chosen_ingest_res,
        )

    # Auto mode: benchmark each engine by dry_run on eval_max_items, then rerun chosen engine for actual dry_run/commit.
    if not candidates:
        candidates = ['bing']

    best_score = None
    best_engine = None
    best_search_results: List[dict] = []

    for eng in candidates:
        engine_str = (eng or '').strip()
        if not engine_str:
            continue
        try:
            sr, ir = await _run_one(engine_str, eval_only=True)
            eval_rows.append(
                NewsSearchAndIngestEngineEval(
                    engine=engine_str,
                    search_count=len(sr or []),
                    ingest_created=ir.created,
                    ingest_duplicates=ir.duplicates,
                    ingest_skipped=ir.skipped,
                    ingest_errors=ir.errors,
                )
            )
            score = (ir.created, -ir.errors, -ir.skipped)
            if best_score is None or score > best_score:
                best_score = score
                best_engine = engine_str
                best_search_results = sr or []
        except Exception:
            eval_rows.append(
                NewsSearchAndIngestEngineEval(
                    engine=engine_str,
                    search_count=0,
                    ingest_created=0,
                    ingest_duplicates=0,
                    ingest_skipped=0,
                    ingest_errors=1,
                )
            )
            continue

    # Fallback: bing
    chosen_engine = best_engine or 'bing'
    chosen_search_results, chosen_ingest_res = await _run_one(chosen_engine, eval_only=False)
    chosen_ingest_items = _to_ingest_items_from_search_results(chosen_search_results, max_items=int(payload.ingest_max_items))

    return NewsSearchAndIngestResponse(
        query=payload.query,
        chosen_engine=chosen_engine,
        candidates=eval_rows,
        search_articles=chosen_search_results,
        ingest=chosen_ingest_res,
    )


# --------- Source Registry (inventory) ---------
class NewsSourceRegistryItem(BaseModel):
    kind: str  # official|media|community|search|crawler
    name: str
    domain: Optional[str] = None
    notes: Optional[str] = None


class NewsSourceRegistryResponse(BaseModel):
    total: int
    items: List[NewsSourceRegistryItem]


@router.get('/source-registry')
async def get_source_registry() -> NewsSourceRegistryResponse:
    """返回当前系统“可用/已内置适配”的信源清单（面向运维/配置）。

    说明：这里的“扩展信源”分两类：
    - 搜索聚合：通过 SearXNG + engines/domain filters 做召回
    - 直连采集：通过 /api/news/ingest 或 /api/news/ingest/rss 将外部发现的 URL 入库到 SQL
    """
    items: List[NewsSourceRegistryItem] = []

    # A股官方披露/公告（入口型，需你提供 RSS/API/列表页提取到 URL 再 ingest）
    items.extend([
        NewsSourceRegistryItem(kind='official', name='上交所（SSE）公告/披露', domain='sse.com.cn', notes='推荐通过 RSS/栏目列表提取 URL 后调用 /api/news/ingest 或 /api/news/ingest/rss'),
        NewsSourceRegistryItem(kind='official', name='深交所（SZSE）公告/披露', domain='szse.cn', notes='推荐通过 RSS/栏目列表提取 URL 后调用 /api/news/ingest 或 /api/news/ingest/rss'),
        NewsSourceRegistryItem(kind='official', name='巨潮资讯（CNINFO）公告', domain='cninfo.com.cn', notes='可通过官方查询/列表提取 PDF/HTML URL，再 ingest 入库'),
        NewsSourceRegistryItem(kind='official', name='证监会/监管披露', domain='csrc.gov.cn', notes='适合 RSS/栏目列表增量抓取'),
    ])

    # 搜索聚合入口
    items.append(NewsSourceRegistryItem(kind='search', name='SearXNG 聚合搜索', domain=None, notes='通过 engines + include/exclude domain 控制信源面'))

    # 已内置正文抽取/选择器适配（站点解析能力，不等于白名单）
    # 来自 NewsContentCrawler.content_selectors 的站点别名
    items.extend([
        NewsSourceRegistryItem(kind='crawler', name='新浪财经', domain='finance.sina.com.cn'),
        NewsSourceRegistryItem(kind='crawler', name='证券之星', domain='stockstar.com'),
        NewsSourceRegistryItem(kind='crawler', name='雪球', domain='xueqiu.com'),
        NewsSourceRegistryItem(kind='crawler', name='东方财富/股吧', domain='eastmoney.com'),
        NewsSourceRegistryItem(kind='crawler', name='华尔街见闻', domain='wallstreetcn.com'),
        NewsSourceRegistryItem(kind='crawler', name='财联社', domain='cls.cn'),
        NewsSourceRegistryItem(kind='crawler', name='第一财经', domain='yicai.com'),
        NewsSourceRegistryItem(kind='crawler', name='澎湃新闻', domain='thepaper.cn'),
        NewsSourceRegistryItem(kind='crawler', name='财新', domain='caixin.com'),
        NewsSourceRegistryItem(kind='crawler', name='凤凰财经', domain='ifeng.com'),
        NewsSourceRegistryItem(kind='crawler', name='和讯', domain='hexun.com'),
        NewsSourceRegistryItem(kind='crawler', name='金融界', domain='jrj.com.cn'),
        NewsSourceRegistryItem(kind='crawler', name='Reuters', domain='reuters.com'),
        NewsSourceRegistryItem(kind='crawler', name='Bloomberg', domain='bloomberg.com'),
        NewsSourceRegistryItem(kind='crawler', name='CNBC', domain='cnbc.com'),
        NewsSourceRegistryItem(kind='crawler', name='FT 中文网', domain='ftchinese.com'),
    ])

    return NewsSourceRegistryResponse(total=len(items), items=items)


# --------- RSS/Atom -> Ingest ---------
class NewsIngestRssRequest(BaseModel):
    feed_url: str = Field(..., max_length=2000, description='RSS 或 Atom feed URL')
    symbol: Optional[str] = Field(None, description='相关股票代码（可选）')
    max_items: int = Field(30, ge=1, le=200)
    dry_run: bool = Field(False)

    @validator('feed_url')
    def _feed_url_http(cls, v: str):
        u = (v or '').strip()
        if not (u.startswith('http://') or u.startswith('https://')):
            raise ValueError('feed_url must start with http/https')
        return u

    @validator('symbol')
    def _symbol_norm(cls, v: Optional[str]):
        if v is None:
            return None
        s = str(v).strip().upper()
        return s if s else None


def _et_text(el: Optional[ET.Element]) -> str:
    if el is None:
        return ''
    return ''.join(el.itertext()).strip()


def _parse_feed_items(xml_text: str, *, limit: int = 30) -> List[Dict[str, Any]]:
    """Parse RSS 2.0 / Atom feed to a normalized list of {url,title,published_at}."""
    out: List[Dict[str, Any]] = []
    if not xml_text:
        return out
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return out

    tag = (root.tag or '').lower()
    is_atom = tag.endswith('feed')

    if is_atom:
        entries = root.findall('.//{*}entry')
        for e in entries:
            if len(out) >= limit:
                break
            title = _et_text(e.find('{*}title'))
            pub = _et_text(e.find('{*}published')) or _et_text(e.find('{*}updated'))
            url = ''
            links = e.findall('{*}link')
            if links:
                # Prefer rel=alternate
                pick = None
                for lk in links:
                    if (lk.get('rel') or '').lower() == 'alternate' and lk.get('href'):
                        pick = lk
                        break
                if pick is None:
                    pick = links[0]
                url = (pick.get('href') or '').strip()
            if url:
                out.append({'url': url, 'title': title or url, 'published_at': pub or None})
    else:
        items = root.findall('.//item')
        for it in items:
            if len(out) >= limit:
                break
            title = _et_text(it.find('title'))
            url = _et_text(it.find('link'))
            pub = _et_text(it.find('pubDate')) or _et_text(it.find('date'))
            if url:
                out.append({'url': url, 'title': title or url, 'published_at': pub or None})

    # Normalize published_at to ISO if possible
    normed: List[Dict[str, Any]] = []
    for x in out:
        pub = x.get('published_at')
        if isinstance(pub, str) and pub.strip():
            s = pub.strip()
            iso = None
            try:
                # RFC 2822 (RSS pubDate)
                dt = parsedate_to_datetime(s)
                iso = dt.isoformat()
            except Exception:
                # ISO passthrough
                try:
                    dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
                    iso = dt.isoformat()
                except Exception:
                    iso = s
            x['published_at'] = iso
        normed.append(x)
    return normed


@router.post('/ingest/rss')
async def ingest_from_rss(payload: NewsIngestRssRequest, db: Session = Depends(get_db)) -> NewsIngestResponse:
    """从 RSS/Atom 抓取链接并入库到 SQL(news_articles)。

    用途：A股官方公告/披露经常有栏目/RSS；只要 feed 给到，就能自动发现 URL 并走现有解析/去重/过滤链路。
    """
    import httpx as _httpx
    feed_url = payload.feed_url
    try:
        async with _httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
        }) as client:
            resp = await client.get(feed_url)
            resp.raise_for_status()
            xml_text = resp.text
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"fetch rss failed: {str(e)}")

    rows = _parse_feed_items(xml_text, limit=int(payload.max_items or 30))
    ingest_items: List[NewsIngestItem] = []
    for r in rows:
        ingest_items.append(NewsIngestItem(
            url=r.get('url'),
            title=r.get('title'),
            symbol=payload.symbol,
            published_at=r.get('published_at'),
        ))

    return await ingest_news(NewsIngestRequest(items=ingest_items, dry_run=payload.dry_run, max_items=len(ingest_items)), db=db)


# --------- CNINFO Announcements API -> Ingest ---------
class CninfoAnnouncementIngestRequest(BaseModel):
    """通过巨潮资讯（CNINFO）公告查询 API 拉取公告列表，并将附件 URL 入库。

    说明：CNINFO 返回的正文通常是 PDF/HTML 附件链接（adjunctUrl）。
    - 选 1：使用 searchkey（公司名/关键字）
    - 选 2：使用 stock（精确到单公司），格式通常为 "secCode,orgId"，例如 "300750,GD165627"。
    """

    searchkey: Optional[str] = Field(None, description='选 1：关键字（如 公司名/代码/主题）')
    stock: Optional[str] = Field(None, description='选 2：精确锁定，格式一般为 "secCode,orgId"')
    symbol: Optional[str] = Field(None, description='相关股票代码（可选，用于入库关联）')
    se_date: Optional[str] = Field(None, description='日期范围（可选），如 2025-01-01~2025-01-31')

    page_num: int = Field(1, ge=1, le=1000)
    page_size: int = Field(20, ge=1, le=200, description='默认 20 条')

    # CNINFO 查询参数（一般无需修改；保留以便未来调优）
    tab_name: str = Field('fulltext', description='CNINFO tabName')
    column: str = Field('', description='CNINFO column，如 szse/sse；留空表示不限制')
    plate: str = Field('', description='CNINFO plate，如 szse/sse；留空表示不限制')

    dry_run: bool = Field(False, description='仅抓取/解析/过滤，不写库')

    @validator('searchkey')
    def _searchkey_strip(cls, v: Optional[str]):
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    @validator('stock')
    def _stock_strip(cls, v: Optional[str]):
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    @validator('symbol')
    def _symbol_norm(cls, v: Optional[str]):
        if v is None:
            return None
        s = str(v).strip().upper()
        return s if s else None


def _cninfo_announcement_to_item(a: Dict[str, Any], *, symbol: Optional[str]) -> Optional[NewsIngestItem]:
    try:
        adjunct = (a.get('adjunctUrl') or '').strip()
        title = (a.get('announcementTitle') or '').strip()
        sec_name = (a.get('secName') or '').strip()
        ts = a.get('announcementTime')
        if not adjunct:
            return None
        url = urljoin('https://static.cninfo.com.cn/', adjunct.lstrip('/'))
        published_at = None
        if ts is not None:
            try:
                published_at = (datetime.utcfromtimestamp(int(ts) / 1000.0).isoformat() + 'Z')
            except Exception:
                published_at = None
        return NewsIngestItem(
            url=url,
            title=(title or url),
            symbol=symbol,
            company_name=(sec_name or None),
            published_at=published_at,
        )
    except Exception:
        return None


@router.post('/ingest/cninfo')
async def ingest_from_cninfo(payload: CninfoAnnouncementIngestRequest, db: Session = Depends(get_db)) -> NewsIngestResponse:
    """CNINFO 公告查询 API -> 入库 SQL(news_articles)。

    你可以不提供任何 RSS/列表 URL：后端会先从 CNINFO 拉取公告列表，再将附件链接批量喂给 /api/news/ingest。
    """
    if not payload.searchkey and not payload.stock:
        raise HTTPException(status_code=400, detail='either searchkey or stock is required')

    # If using stock, encourage the observed stable format: "secCode,orgId"
    if payload.stock and ',' not in payload.stock:
        raise HTTPException(status_code=400, detail='stock format should be like "secCode,orgId" (e.g., "300750,GD165627")')

    import httpx as _httpx

    api_url = 'https://www.cninfo.com.cn/new/hisAnnouncement/query'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
        'Referer': 'https://www.cninfo.com.cn/',
        'Accept': 'application/json, text/plain, */*',
    }

    data = {
        'pageNum': int(payload.page_num or 1),
        'pageSize': int(payload.page_size or 20),
        'tabName': (payload.tab_name or 'fulltext'),
        'column': (payload.column or ''),
        'plate': (payload.plate or ''),
        'searchkey': (payload.searchkey or ''),
        'stock': (payload.stock or ''),
        'category': '',
        'trade': '',
        'seDate': (payload.se_date or ''),
    }

    try:
        async with _httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
            resp = await client.post(api_url, data=data)
            resp.raise_for_status()
            j = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f'cninfo query failed: {str(e)}')

    anns = j.get('announcements') or []
    ingest_items: List[NewsIngestItem] = []
    for a in anns:
        if len(ingest_items) >= int(payload.page_size or 20):
            break
        it = _cninfo_announcement_to_item(a, symbol=payload.symbol)
        if it is not None:
            ingest_items.append(it)

    return await ingest_news(
        NewsIngestRequest(
            items=ingest_items,
            dry_run=bool(payload.dry_run),
            max_items=len(ingest_items),
        ),
        db=db,
    )


# --------- RSS/Atom Discovery (helper) ---------
class RssDiscoverRequest(BaseModel):
    base_url: str = Field(..., max_length=2000, description='站点根地址，如 https://www.sse.com.cn')
    timeout_seconds: float = Field(12.0, ge=3.0, le=60.0)
    max_candidates: int = Field(30, ge=5, le=200)

    @validator('base_url')
    def _base_url_http(cls, v: str):
        u = (v or '').strip()
        if not (u.startswith('http://') or u.startswith('https://')):
            raise ValueError('base_url must start with http/https')
        return u.rstrip('/')


class RssDiscoverResponse(BaseModel):
    base_url: str
    robots_url: str
    sitemap_urls: List[str]
    candidates: List[str]
    notes: List[str]


def _dedup_keep_order(xs: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in xs:
        k = (x or '').strip()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def _extract_sitemaps_from_robots(robots_txt: str) -> List[str]:
    out: List[str] = []
    if not robots_txt:
        return out
    for line in robots_txt.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.lower().startswith('sitemap:'):
            url = s.split(':', 1)[1].strip()
            if url:
                out.append(url)
        # 有些站点会写 RSS/Feed
        if 'rss' in s.lower() or 'atom' in s.lower() or 'feed' in s.lower():
            # Try to grab an URL in the line
            m = re.search(r'(https?://\S+)', s)
            if m:
                out.append(m.group(1).strip())
    return _dedup_keep_order(out)


def _extract_feed_like_from_sitemap(xml_text: str, *, base_url: str) -> List[str]:
    out: List[str] = []
    if not xml_text:
        return out
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return out
    # Sitemap can be <urlset> or <sitemapindex>
    for loc in root.findall('.//{*}loc'):
        u = (_et_text(loc) or '').strip()
        if not u:
            continue
        low = u.lower()
        if any(k in low for k in ('rss', 'atom', 'feed')):
            out.append(u)
    # Also keep conventional sitemap urls that may contain feeds inside
    return _dedup_keep_order(out)


def _extract_feed_links_from_html(html_text: str, *, base_url: str) -> List[str]:
    """Best-effort extract RSS/Atom/feed links from homepage HTML without extra dependencies."""
    if not html_text:
        return []
    text = html_text
    out: List[str] = []

    # <link rel="alternate" type="application/rss+xml" href="...">
    for m in re.finditer(r"<link[^>]+>", text, flags=re.I):
        tag = m.group(0)
        if not re.search(r"rel\s*=\s*['\"]?alternate['\"]?", tag, flags=re.I):
            continue
        if not re.search(r"type\s*=\s*['\"]application/(rss\+xml|atom\+xml)['\"]", tag, flags=re.I):
            continue
        hm = re.search(r"href\s*=\s*['\"]([^'\"]+)['\"]", tag, flags=re.I)
        if hm:
            href = hm.group(1).strip()
            if href:
                out.append(urljoin(base_url + '/', href))

    # Anchor tags that look like feeds
    for hm in re.finditer(r"href\s*=\s*['\"]([^'\"]+)['\"]", text, flags=re.I):
        href = (hm.group(1) or '').strip()
        if not href:
            continue
        low = href.lower()
        if any(k in low for k in ('rss', 'atom', 'feed')) or low.endswith('.xml'):
            out.append(urljoin(base_url + '/', href))

    return _dedup_keep_order(out)


async def _discover_rss_candidates(
    *,
    base_url: str,
    timeout_seconds: float,
    max_candidates: int,
) -> Tuple[str, List[str], List[str], List[str]]:
    """Shared implementation for RSS discovery.

    Returns: robots_url, sitemap_urls, candidates, notes
    """
    import httpx as _httpx

    base = (base_url or '').rstrip('/')
    timeout = float(timeout_seconds or 12.0)
    notes: List[str] = []

    robots_url = f"{base}/robots.txt"
    sitemap_urls: List[str] = []
    candidates: List[str] = []

    common_paths = [
        '/rss', '/rss.xml', '/feed', '/feed.xml', '/atom.xml', '/index.xml', '/rss/index.xml',
        '/news/rss', '/news/rss.xml',
    ]

    async with _httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
    }) as client:
        # 0) homepage hints
        try:
            r0 = await client.get(base + '/')
            if r0.status_code == 200 and (r0.text or '').strip():
                hints = _extract_feed_links_from_html(r0.text, base_url=base)
                if hints:
                    candidates.extend(hints)
                    notes.append(f"home_ok: found {len(hints)} feed-like links")
        except Exception as e:
            notes.append(f"home_err: {str(e)}")

        # 1) robots.txt
        try:
            r = await client.get(robots_url)
            if r.status_code == 200 and (r.text or '').strip():
                sitemap_urls = _extract_sitemaps_from_robots(r.text)
                notes.append(f"robots_ok: found {len(sitemap_urls)} sitemap/feed hints")
            else:
                notes.append(f"robots_no: status={r.status_code}")
        except Exception as e:
            notes.append(f"robots_err: {str(e)}")

        # 2) probe a default sitemap.xml if none
        if not sitemap_urls:
            sitemap_urls = [f"{base}/sitemap.xml"]

        # 3) pull a few sitemaps and extract feed-like URLs
        for sm in sitemap_urls[:5]:
            try:
                rr = await client.get(sm)
                if rr.status_code != 200:
                    continue
                feed_like = _extract_feed_like_from_sitemap(rr.text, base_url=base)
                if feed_like:
                    candidates.extend(feed_like)
            except Exception:
                continue

        # 4) probe common feed endpoints
        for p in common_paths:
            if len(candidates) >= int(max_candidates or 30):
                break
            u = f"{base}{p}"
            try:
                rr = await client.get(u)
                if rr.status_code != 200:
                    continue
                ct = (rr.headers.get('Content-Type') or '').lower()
                body = (rr.text or '')[:300].lower()
                if ('xml' in ct) or ('rss' in body) or ('<rss' in body) or ('<feed' in body):
                    candidates.append(u)
            except Exception:
                continue

    candidates = _dedup_keep_order(candidates)[: int(max_candidates or 30)]
    return robots_url, _dedup_keep_order(sitemap_urls)[:10], candidates, notes


@router.post('/discover/rss')
async def discover_rss(payload: RssDiscoverRequest) -> RssDiscoverResponse:
    """帮助发现站点 RSS/Atom 入口：自动探测 robots.txt、sitemap，以及常见 feed 路径。

    说明：很多“官方公告”站点不一定有标准 RSS；该接口返回“候选入口”，你可以挑一个 feed_url 直接喂给 /api/news/ingest/rss。
    """
    base = payload.base_url.rstrip('/')
    robots_url, sitemap_urls, candidates, notes = await _discover_rss_candidates(
        base_url=base,
        timeout_seconds=float(payload.timeout_seconds or 12.0),
        max_candidates=int(payload.max_candidates or 30),
    )
    return RssDiscoverResponse(
        base_url=base,
        robots_url=robots_url,
        sitemap_urls=sitemap_urls,
        candidates=candidates,
        notes=notes,
    )


# --------- Official Presets (A-share) ---------
OFFICIAL_A_PRESETS: Dict[str, Dict[str, str]] = {
    'sse': {'name': '上交所（SSE）公告/披露', 'base_url': 'https://www.sse.com.cn'},
    'szse': {'name': '深交所（SZSE）公告/披露', 'base_url': 'https://www.szse.cn'},
    'cninfo': {'name': '巨潮资讯（CNINFO）公告', 'base_url': 'https://www.cninfo.com.cn'},
    'csrc': {'name': '证监会/监管披露', 'base_url': 'http://www.csrc.gov.cn'},
}


class OfficialPresetIngestRequest(BaseModel):
    preset: str = Field(..., description='sse|szse|cninfo|csrc')
    symbol: Optional[str] = Field(None, description='相关股票代码（可选）')
    dry_run: bool = Field(True, description='默认 dry-run，确认无误后再置 false')
    max_feeds_to_try: int = Field(5, ge=1, le=50)
    max_items_per_feed: int = Field(30, ge=1, le=200)

    @validator('preset')
    def _preset_norm(cls, v: str):
        s = (v or '').strip().lower()
        if not s:
            raise ValueError('preset required')
        return s

    @validator('symbol')
    def _symbol_norm(cls, v: Optional[str]):
        if v is None:
            return None
        s = str(v).strip().upper()
        return s if s else None


class OfficialPresetIngestResponse(BaseModel):
    preset: str
    name: str
    base_url: str
    discovered_candidates: int
    tried_feeds: List[str]
    feed_results: List[Dict[str, Any]]


@router.post('/ingest/official-a')
async def ingest_official_a(payload: OfficialPresetIngestRequest, db: Session = Depends(get_db)) -> OfficialPresetIngestResponse:
    """A股官方公告一键：自动发现 RSS 候选并逐个尝试 ingest/rss。"""
    meta = OFFICIAL_A_PRESETS.get(payload.preset)
    if not meta:
        raise HTTPException(status_code=400, detail=f"unknown preset: {payload.preset}")

    robots_url, sitemap_urls, candidates, notes = await _discover_rss_candidates(
        base_url=meta['base_url'],
        timeout_seconds=15.0,
        max_candidates=30,
    )
    # Try top N feeds
    tried: List[str] = []
    feed_results: List[Dict[str, Any]] = []
    for feed in candidates[: int(payload.max_feeds_to_try or 5)]:
        tried.append(feed)
        try:
            res = await ingest_from_rss(
                NewsIngestRssRequest(
                    feed_url=feed,
                    symbol=payload.symbol,
                    max_items=int(payload.max_items_per_feed or 30),
                    dry_run=bool(payload.dry_run),
                ),
                db=db,
            )
            feed_results.append({
                'feed_url': feed,
                'created': res.created,
                'duplicates': res.duplicates,
                'skipped': res.skipped,
                'errors': res.errors,
                'total': res.total,
            })
        except Exception as e:
            feed_results.append({'feed_url': feed, 'error': str(e)})

    return OfficialPresetIngestResponse(
        preset=payload.preset,
        name=meta['name'],
        base_url=meta['base_url'],
        discovered_candidates=len(candidates),
        tried_feeds=tried,
        feed_results=feed_results,
    )

# --------- Error Logs for dedicated panel ---------
class ErrorItem(BaseModel):
    kind: str
    url: Optional[str] = None
    domain: Optional[str] = None
    symbol: Optional[str] = None
    message: Optional[str] = None
    detail: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None

class ErrorListResponse(BaseModel):
    total: int
    items: List[ErrorItem]

@router.get('/errors')
async def list_news_errors(
    kind: Optional[str] = Query(None, description="search|crawl"),
    domain: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    since_minutes: int = Query(1440, ge=1, le=60*24*30),
    limit: int = Query(200, ge=1, le=1000),
):
    """列出新闻错误日志，用于前端‘错误面板’。
    支持按种类/域名/股票过滤，并限制时间窗口与数量。"""
    try:
        storage = await get_storage()
        rows = await storage.list_news_errors(kind=kind, domain=domain, symbol=symbol, since_minutes=since_minutes, limit=limit)
        items = []
        for r in rows:
            items.append(ErrorItem(
                kind=r.get('kind'),
                url=r.get('url'),
                domain=r.get('domain'),
                symbol=r.get('symbol'),
                message=r.get('message'),
                detail=r.get('detail'),
                created_at=(r.get('created_at').isoformat() if r.get('created_at') else None)
            ))
        return ErrorListResponse(total=len(items), items=items)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"List errors failed: {str(e)}")

class ErrorSummaryItem(BaseModel):
    key: str
    count: int

class ErrorSummaryResponse(BaseModel):
    by_kind: List[ErrorSummaryItem]
    by_domain: List[ErrorSummaryItem]
    by_symbol: List[ErrorSummaryItem]

@router.get('/errors/summary')
async def news_errors_summary(
    since_minutes: int = Query(1440, ge=1, le=60*24*30),
):
    """错误摘要统计：按 kind、domain、symbol 进行分组计数，用于面板概览。"""
    try:
        storage = await get_storage()
        rows = await storage.list_news_errors(since_minutes=since_minutes, limit=10000)
        from collections import Counter
        c_kind = Counter((r.get('kind') or 'unknown') for r in rows)
        c_domain = Counter((r.get('domain') or 'unknown') for r in rows)
        c_symbol = Counter((r.get('symbol') or 'unknown') for r in rows)
        def to_items(cnt: Counter) -> List[ErrorSummaryItem]:
            return [ErrorSummaryItem(key=k, count=v) for k, v in cnt.most_common(100)]
        return ErrorSummaryResponse(
            by_kind=to_items(c_kind),
            by_domain=to_items(c_domain),
            by_symbol=to_items(c_symbol),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errors summary failed: {str(e)}")

# --------- Page Crawl Agent (single page) ---------
class PageCrawlAgentRequest(BaseModel):
    url: str
    symbol: Optional[str] = None
    company_name: Optional[str] = None
    probe_top_k: int = Field(5, ge=0, le=20)
    download_charts: bool = True
    max_download_charts: int = Field(5, ge=0, le=20)

@router.post('/agent/crawl_page')
async def agent_crawl_page(req: PageCrawlAgentRequest):
    """以 Agent 方式抓取单个页面：解析正文、提取超链接、识别图表并可选下载，返回结构化报告。

    适合人工复核：失败的探测会被记入 /api/news/errors，便于跟进站点适配。
    """
    try:
        opts = PageCrawlOptions(
            symbol=(req.symbol or None),
            company_name=(req.company_name or None),
            probe_top_k=req.probe_top_k,
            download_charts=req.download_charts,
            max_download_charts=req.max_download_charts,
        )
        agent = PageCrawlAgent(options=opts)
        report = await agent.run(req.url)
        # 持久化到 Mongo（最佳努力，不影响主流程）
        try:
            storage = await get_storage()
            if storage:
                await storage.save_page_crawl_report(report)
        except Exception:
            pass
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent crawl failed: {str(e)}")

# --------- Agent Page Reports (Mongo) ---------
class PageReportListResponse(BaseModel):
    total: int
    items: List[Dict[str, Any]]

@router.get('/agent/page-reports')
async def list_agent_page_reports(
    symbol: Optional[str] = Query(None),
    domain: Optional[str] = Query(None),
    since_minutes: int = Query(1440, ge=1, le=60*24*30),
    limit: int = Query(50, ge=1, le=500)
):
    try:
        storage = await get_storage()
        if not storage:
            return PageReportListResponse(total=0, items=[])
        rows = await storage.list_page_crawl_reports(symbol=symbol, domain=domain, since_minutes=since_minutes, limit=limit)
        return PageReportListResponse(total=len(rows), items=rows)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"list page reports failed: {str(e)}")

@router.get('/agent/page-reports/{report_id}')
async def get_agent_page_report(report_id: str):
    try:
        storage = await get_storage()
        if not storage:
            raise HTTPException(status_code=404, detail='no mongo storage')
        doc = await storage.get_page_crawl_report(report_id=report_id)
        if not doc:
            raise HTTPException(status_code=404, detail='report not found')
        return doc
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"get page report failed: {str(e)}")

# --------- Batch ensure counts ---------
class EnsureCountsRequest(BaseModel):
    symbols: List[str]
    ensure_min: int = Field(5, ge=0, le=50)
    days: int = Field(7, ge=1, le=365, description="Primary window for related_stocks match")
    fallback_days: int = Field(60, ge=1, le=365)
    min_content: int = Field(0, ge=0, le=10000)
    limit: int = Field(20, ge=1, le=100)
    wait_seconds: int = Field(2, ge=0, le=30)
    trigger_topup: bool = True
    allow_placeholder: bool = True
    extra_keywords: Optional[str] = None
    parallelism: int = Field(4, ge=1, le=16)

class EnsureCountsItem(BaseModel):
    symbol: str
    total_count: int
    below_min: bool

class EnsureCountsResponse(BaseModel):
    ensure_min: int
    results: List[EnsureCountsItem]

@router.post('/ensure_counts')
async def ensure_news_counts(req: EnsureCountsRequest) -> EnsureCountsResponse:
    """For a batch of symbols, ensure at least ensure_min news items by triggering top-up if needed,
    then return the latest counts. This helps the UI avoid showing 0/information-insufficient states.
    """
    if not req.symbols:
        return EnsureCountsResponse(ensure_min=req.ensure_min, results=[])
    symbols = [str(s or '').upper().strip() for s in req.symbols if str(s or '').strip()]
    symbols = symbols[:100]  # hard cap to protect backend

    import asyncio as _aio
    sem = _aio.Semaphore(req.parallelism)

    async def _one(sym: str) -> EnsureCountsItem:
        async with sem:
            try:
                res = await get_stock_news(
                    symbol=sym,
                    limit=req.limit,
                    days=req.days,
                    ensure_min=max(0, req.ensure_min),
                    fallback_days=req.fallback_days,
                    include_content=False,
                    min_content=req.min_content,
                    trigger_topup=req.trigger_topup,
                    wait_seconds=req.wait_seconds,
                    extra_keywords=req.extra_keywords,
                    allow_placeholder=req.allow_placeholder,
                )
                cnt = int((res or {}).get('total_count', 0) or 0)
                return EnsureCountsItem(symbol=sym, total_count=cnt, below_min=(req.ensure_min > 0 and cnt < req.ensure_min))
            except Exception:
                # On error, return 0 to signal below_min
                return EnsureCountsItem(symbol=sym, total_count=0, below_min=(req.ensure_min > 0))

    results = await _aio.gather(*[_one(s) for s in symbols])
    return EnsureCountsResponse(ensure_min=req.ensure_min, results=list(results))

# --- Orchestrate: ensure_min -> wait -> targeted backfill -> enriched read ---
@router.post('/ensure_and_backfill/{symbol}')
async def ensure_and_backfill(
    symbol: str,
    ensure_min: int = Query(5, ge=1, le=50),
    wait_seconds: int = Query(6, ge=0, le=60),
    days: int = Query(7, ge=1, le=365),
    limit: int = Query(5, ge=1, le=50),
    allow_placeholder: bool = Query(False),
    include_content: bool = Query(False),
    min_content: int = Query(0, ge=0, le=10000),
    extra_keywords: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """为单只股票执行：补齐新闻数 -> 短等待 -> 回填缺失内容/摘要 -> 返回富集新闻结果。

    用于前端“一键补齐并刷新”场景，尽量保证 allow_placeholder=false 也能拿到 ≥ ensure_min 条有效新闻。
    """
    sym = symbol.upper()
    # 1) 触发补齐并短等
    try:
        scheduler = EnhancedNewsScheduler()
        await scheduler.run_topup_for_symbol(sym, min_required=ensure_min)
    except Exception:
        # 补齐失败时不中断，继续尝试回读与回填
        pass
    if wait_seconds > 0:
        import asyncio as _aio
        await _aio.sleep(wait_seconds)

    # 2) 选择性回填（仅处理最近 days 天、该标的且内容/摘要缺失或过短的文章）
    from datetime import datetime, timedelta
    cutoff = datetime.now() - timedelta(days=days)
    q = (
        select(NewsArticle)
        .join(NewsSource, isouter=True)
        .where(NewsArticle.related_stocks.contains([sym]))
        .where(
            or_(
                and_(NewsArticle.published_at.isnot(None), NewsArticle.published_at >= cutoff),
                and_(NewsArticle.crawled_at.isnot(None), NewsArticle.crawled_at >= cutoff),
            )
        )
        .order_by(NewsArticle.published_at.desc().nullslast())
        .limit(60)
    )
    rows = db.execute(q).scalars().all()

    # 回填逻辑：缺内容则抓取正文；缺摘要则生成摘要（使用内置摘要，避免 LLM 耗时）
    processor = NewsProcessor()
    updated_content = 0
    updated_summary = 0
    short_threshold = 60
    for a in rows:
        try:
            need_content = (not a.content or not a.content.strip() or len(a.content.strip()) < max(short_threshold, min_content))
            if need_content:
                try:
                    soup = await processor._fetch_soup(a.url)
                    content = await processor._extract_content(a.url, soup)
                    if content and len(content.strip()) >= 20:
                        try:
                            content = processor._maybe_fix_mojibake(content)
                        except Exception:
                            pass
                        a.content = content
                        updated_content += 1
                except Exception:
                    pass
            need_summary = (not a.summary or not a.summary.strip())
            if need_summary and isinstance(a.content, str) and len(a.content.strip()) >= 30:
                try:
                    a.summary = processor._generate_summary(a.content)
                    updated_summary += 1
                except Exception:
                    pass
        except Exception:
            continue
    if (updated_content + updated_summary) > 0:
        try:
            db.commit()
        except Exception:
            db.rollback()

    # 3) 回读富集结果（不再触发 topup，以免循环）
    enriched = await get_company_enriched_news(
        symbol=sym,
        limit=limit,
        days=days,
        ensure_min=ensure_min,
        fallback_days=max(days, 60),
        include_content=include_content,
        min_content=min_content,
        trigger_topup=False,
        wait_seconds=0,
        extra_keywords=extra_keywords,
        allow_placeholder=allow_placeholder,
        db=db,
    )
    # 附加回填统计
    if isinstance(enriched, dict):
        enriched["backfill_stats"] = {
            "updated_content": updated_content,
            "updated_summary": updated_summary,
        }
    return enriched

@router.get('/company_enriched/{symbol}')
async def get_company_enriched_news(
    symbol: str,
    limit: int = Query(30, ge=1, le=200),
    days: int = Query(7, ge=1, le=365, description="Primary window for related_stocks match"),
    ensure_min: int = Query(5, ge=0, le=50),
    fallback_days: int = Query(180, ge=1, le=365, description="Keyword/window for extended name-based search"),
    include_content: bool = Query(False),
    min_content: int = Query(0, ge=0, le=10000),
    trigger_topup: bool = Query(False),
    wait_seconds: int = Query(0, ge=0, le=30),
    extra_keywords: Optional[str] = Query(None, description="Comma-separated extra keywords to expand company/industry queries"),
    allow_placeholder: bool = Query(False, description="If true, synthesize placeholder items to reach ensure_min when sources are scarce"),
    db: Session = Depends(get_db),
):
    """富集查询：基于公司名称/别名/代码与行业相关后缀进行更广泛检索，尽量避免 0 新闻。

    返回 articles 去重合并：related_stocks 命中 + 名称/简名/代码 + 行业后缀扩展（如 公告/产业链/供应商/客户/回购/扩产/产能/合作/投资/研发/评级/中标/利好/风险 等）。
    可选触发即时补齐并短等，再回读。
    """
    try:
        sym = symbol.upper()
        # 获取公司名（若有）
        stock_info = None
        company_name = None
        try:
            stock_info = get_stock_info(sym)
            company_name = (stock_info or {}).get('name')
        except Exception:
            try:
                w = db.execute(select(Watchlist).where(Watchlist.symbol == sym)).scalar_one_or_none()
                if w and getattr(w, 'name', None):
                    company_name = w.name
            except Exception:
                company_name = None

        # 1) 基础 related_stocks 检索
        articles: List[dict] = []
        seen_urls = set()

        def push(a):
            url_key = a.get('url') if isinstance(a, dict) else getattr(a, 'url', None)
            if not url_key or url_key in seen_urls:
                return
            if min_content > 0:
                text_len = len((a.get('content') if isinstance(a, dict) else getattr(a, 'content', None))
                               or (a.get('summary') if isinstance(a, dict) else getattr(a, 'summary', None)) or "")
                if text_len < min_content:
                    return
            seen_urls.add(url_key)
            if isinstance(a, dict):
                articles.append(a)
            else:
                articles.append({
                    "id": a.id,
                    "title": a.title,
                    "url": a.url,
                    "summary": a.summary,
                    **({"content": a.content} if include_content else {}),
                    "published_at": a.published_at.isoformat() if a.published_at else None,
                    "crawled_at": a.crawled_at.isoformat() if getattr(a, 'crawled_at', None) else None,
                    "source": a.source.name if getattr(a, 'source', None) else None,
                    "category": a.category,
                    "sentiment_type": a.sentiment_type,
                    "sentiment_score": a.sentiment_score,
                    "relevance_score": a.relevance_score,
                    "related_stocks": a.related_stocks,
                    "keywords": a.keywords,
                })

        cutoff_primary = datetime.now() - timedelta(days=days)
        q_rel = (
            select(NewsArticle)
            .join(NewsSource, isouter=True)
            .where(NewsArticle.related_stocks.contains([sym]))
            .where(
                or_(
                    and_(NewsArticle.published_at.isnot(None), NewsArticle.published_at >= cutoff_primary),
                    and_(NewsArticle.crawled_at.isnot(None), NewsArticle.crawled_at >= cutoff_primary),
                )
            )
            # 新增：只返回有有效摘要的文章
            .where(and_(NewsArticle.summary.isnot(None), NewsArticle.summary != ''))
            .order_by(NewsArticle.published_at.desc().nullslast())
            .limit(limit)
        )
        rows_rel = db.execute(q_rel).scalars().all()
        for r in rows_rel:
            push(r)

        # 2) 构建名称/别名/代码 + 行业后缀的关键词集
        base_tokens: List[str] = []
        if sym:
            base_tokens.append(sym)
            try:
                base_code = sym.split('.')[0]
                if base_code:
                    base_tokens.append(base_code)
            except Exception:
                pass
        if company_name:
            base_tokens.append(company_name)
            cn = company_name
            for suf in ["股份有限公司", "有限公司", "股份", "科技", "集团", "控股", "实业", "有限", "公司"]:
                if cn.endswith(suf):
                    cn = cn[: -len(suf)]
                    break
            cn = cn.strip()
            if cn and cn != company_name:
                base_tokens.append(cn)
            if len(company_name) >= 2:
                base_tokens.append(company_name[:2])
            if len(company_name) >= 3:
                base_tokens.append(company_name[:3])
        # User-provided extra keywords
        if extra_keywords:
            for tok in [t.strip() for t in extra_keywords.split(',') if t.strip()]:
                if tok not in base_tokens:
                    base_tokens.append(tok)
        # 行业/主题拓展后缀
        suffixes = [" 行业"," 产业链"," 公告"," 供应商"," 客户"," 订单"," 回购"," 融资"," 扩产"," 产能"," 合作"," 投资"," 研发"," 评级"," 中标"," 利好"," 风险"]
        queries: List[str] = []
        seen_q = set()
        for t in base_tokens:
            t = (t or '').strip()
            if not t:
                continue
            for suf in ([""] + suffixes):
                q = (t + suf).strip()
                if q and q not in seen_q:
                    seen_q.add(q)
                    queries.append(q)
        # 限制查询数量，避免过多扫描
        queries = queries[:20]

        # 3) 针对每个关键词执行 DB 搜索（近 fallback_days）
        cutoff_fb = datetime.now() - timedelta(days=fallback_days)
        sql = text(
            """
            SELECT id, title, url, summary, content, published_at, crawled_at, category,
                   sentiment_type, sentiment_score, relevance_score, related_stocks, keywords
            FROM news_articles
            WHERE (
                (title ILIKE :pat)
                OR (summary ILIKE :pat)
                OR (content ILIKE :pat)
            )
            AND (summary IS NOT NULL AND summary != '')
            AND (
                (published_at IS NOT NULL AND published_at >= :cutoff)
                OR (crawled_at IS NOT NULL AND crawled_at >= :cutoff)
            )
            ORDER BY COALESCE(published_at, crawled_at) DESC NULLS LAST
            LIMIT :lim
            """
        )
        for q in queries:
            params = {"pat": f"%{q}%", "cutoff": cutoff_fb, "lim": min(12, max(1, limit))}
            rows = db.execute(sql, params).mappings().all()
            for r in rows:
                push(dict(r))

        # 4) 如不足且允许，触发补齐并短等，再重查 related + 关键字若干条
        if trigger_topup and ensure_min and len(articles) < ensure_min:
            try:
                scheduler = EnhancedNewsScheduler()
                await scheduler.run_topup_for_symbol(sym, min_required=ensure_min)
                if wait_seconds > 0:
                    import asyncio as _aio
                    await _aio.sleep(wait_seconds)
                # 再查一次 related
                rows_rel2 = db.execute(q_rel).scalars().all()
                for r in rows_rel2:
                    push(r)
                # 再查部分关键词（前5个）
                for q in queries[:5]:
                    params = {"pat": f"%{q}%", "cutoff": cutoff_fb, "lim": min(12, max(1, limit))}
                    rows = db.execute(sql, params).mappings().all()
                    for r in rows:
                        push(dict(r))
            except Exception:
                pass

        # 5) 如仍不足且允许，合成占位以消除“信息不足”提示
        if allow_placeholder and ensure_min and len(articles) < ensure_min:
            from datetime import datetime as _dt
            to_add = max(0, min(ensure_min, limit) - len(articles))
            for i in range(to_add):
                articles.append({
                    "id": None,
                    "title": f"占位：基础资料/行业综述 {i+1}",
                    "url": f"about:placeholder:{sym}:{i}",
                    "summary": f"为避免0新闻/信息不足，添加占位条目。建议查看‘基础资料’或扩大时间窗以获取更多上下文。",
                    **({"content": None} if include_content else {}),
                    "published_at": _dt.utcnow().isoformat(),
                    "crawled_at": _dt.utcnow().isoformat(),
                    "source": "placeholder",
                    "category": "general",
                    "sentiment_type": "neutral",
                    "sentiment_score": 0.0,
                    "relevance_score": 0.0,
                    "related_stocks": [sym],
                    "keywords": [sym, company_name] if company_name else [sym],
                    "is_placeholder": True,
                })

        # 6) 排序与裁剪
        def sort_key(x):
            ts = x.get("published_at") or x.get("crawled_at")
            try:
                return datetime.fromisoformat(ts) if isinstance(ts, str) else (ts or datetime.min)
            except Exception:
                return datetime.min
        articles.sort(key=sort_key, reverse=True)
        articles = articles[:limit]

        placeholder_count = sum(1 for a in articles if isinstance(a, dict) and a.get("is_placeholder") is True)
        real_count = len(articles) - placeholder_count
        return {
            "symbol": sym,
            "company_name": company_name,
            "tokens_used": queries,
            "total_count": len(articles),
            "real_count": real_count,
            "placeholder_count": placeholder_count,
            "articles": articles,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching company enriched news: {str(e)}")

@router.get('/stock/{symbol}')
async def get_stock_news(
    symbol: str,
    limit: int = Query(20, ge=1, le=100),
    days: int = Query(7, ge=1, le=365, description="Primary window for related_stocks match"),
    ensure_min: int = Query(5, ge=0, le=50, description="Ensure at least N articles are returned using keyword fallback"),
    fallback_days: int = Query(60, ge=1, le=365, description="Fallback window for keyword search when ensure_min not met"),
    include_content: bool = Query(False),
    min_content: int = Query(0, ge=0, le=10000, description="Minimum length of content/summary when filtering") ,
    trigger_topup: bool = Query(False, description="If true and results < ensure_min, trigger immediate top-up and short wait"),
    wait_seconds: int = Query(0, ge=0, le=30, description="Optional short wait after triggering top-up"),
    extra_keywords: Optional[str] = Query(None, description="Comma-separated extra keywords to expand keyword fallback"),
    allow_placeholder: bool = Query(False, description="If true, synthesize placeholder items to reach ensure_min when sources are scarce"),
    db: Session = Depends(get_db),
):
    """
    获取某只股票的新闻，尽量避免返回空列表：

    1) 首选在最近 `days` 天内，按 related_stocks 包含该股票代码检索；
    2) 如不足 `ensure_min`，在 `fallback_days` 内对标题/摘要/正文进行关键词检索（股票代码 + 公司名）；
    3) 结果按时间倒序去重返回，最多 `limit` 条；可选返回 content 并进行最小长度过滤。
    """
    try:
        sym = symbol.upper()
        # 获取公司名（若有）
        stock_info = None
        company_name = None
        try:
            stock_info = get_stock_info(sym)
            company_name = (stock_info or {}).get('name')
        except Exception:
            # 回退到自选股名称
            try:
                w = db.execute(select(Watchlist).where(Watchlist.symbol == sym)).scalar_one_or_none()
                if w and getattr(w, 'name', None):
                    company_name = w.name
            except Exception:
                company_name = None

        results: List[dict] = []
        seen_urls = set()

        def push_articles(rows):
            for a in rows:
                url_key = getattr(a, 'url', None) if not isinstance(a, dict) else a.get('url')
                if url_key and url_key in seen_urls:
                    continue
                if min_content > 0:
                    text_len = len((getattr(a, 'content', None) if not isinstance(a, dict) else a.get('content')) or (getattr(a, 'summary', None) if not isinstance(a, dict) else a.get('summary')) or "")
                    if text_len < min_content:
                        continue
                seen_urls.add(url_key)
                if isinstance(a, dict):
                    item = a
                else:
                    item = {
                        "id": a.id,
                        "title": a.title,
                        "url": a.url,
                        "summary": a.summary,
                        **({"content": a.content} if include_content else {}),
                        "published_at": a.published_at.isoformat() if a.published_at else None,
                        "crawled_at": a.crawled_at.isoformat() if getattr(a, 'crawled_at', None) else None,
                        "source": a.source.name if getattr(a, 'source', None) else None,
                        "category": a.category,
                        "sentiment_type": a.sentiment_type,
                        "sentiment_score": a.sentiment_score,
                        "relevance_score": a.relevance_score,
                        "related_stocks": a.related_stocks,
                        "keywords": a.keywords,
                    }
                results.append(item)

        # Step 1: related_stocks 命中（近 days 天）
        cutoff_primary = datetime.now() - timedelta(days=days)
        q1 = (
            select(NewsArticle)
            .join(NewsSource, isouter=True)
            .where(NewsArticle.related_stocks.contains([sym]))
            .where(
                or_(
                    and_(NewsArticle.published_at.isnot(None), NewsArticle.published_at >= cutoff_primary),
                    and_(NewsArticle.crawled_at.isnot(None), NewsArticle.crawled_at >= cutoff_primary),
                )
            )
            # 新增：只返回有有效摘要的文章
            .where(and_(NewsArticle.summary.isnot(None), NewsArticle.summary != ''))
            .order_by(NewsArticle.published_at.desc().nullslast())
            .limit(limit)
        )
        rows1 = db.execute(q1).scalars().all()
        push_articles(rows1)

        # Step 2: 关键词兜底（近 fallback_days 天，使用 symbol + 公司名）
        need = max(0, ensure_min - len(results)) if ensure_min else 0
        if need > 0 and len(results) < limit:
            cutoff_fb = datetime.now() - timedelta(days=fallback_days)
            pats = [f"%{sym}%"]
            # also try plain 6-digit code without suffix (e.g., 300877)
            try:
                base_code = sym.split('.')[0]
                if base_code and base_code not in sym:
                    pats.append(f"%{base_code}%")
            except Exception:
                base_code = None
            # Company name + simplified tokens (strip common suffixes like 股份/有限公司/科技/集团)
            extra_tokens: List[str] = []
            if company_name:
                pats.append(f"%{company_name}%")
                cn = company_name
                for suf in ["股份有限公司", "有限公司", "股份", "科技", "集团", "股份公司", "控股", "实业", "有限", "公司"]:
                    if cn.endswith(suf):
                        cn = cn[: -len(suf)]
                        break
                cn = cn.strip()
                # If shortened name differs and length >=2, include as token
                if cn and cn != company_name and len(cn) >= 2:
                    extra_tokens.append(cn)
                # Also include first 2-4 chars token for very short matches
                if len(company_name) >= 2:
                    extra_tokens.append(company_name[:2])
                if len(company_name) >= 3:
                    extra_tokens.append(company_name[:3])
            # User-provided extra keywords
            if extra_keywords:
                for tok in [t.strip() for t in extra_keywords.split(',') if t.strip()]:
                    if tok not in extra_tokens and (not company_name or tok != company_name):
                        extra_tokens.append(tok)
            # Deduplicate while preserving order and cap to avoid too many params
            seen_t = set()
            tok_final: List[str] = []
            for t in extra_tokens:
                if t and t not in seen_t and t not in (company_name or ""):
                    seen_t.add(t)
                    tok_final.append(t)
            tok_final = tok_final[:2]
            for t in tok_final:
                pats.append(f"%{t}%")

            # Build dynamic extra OR clauses for additional patterns p2..pN
            extra = ""
            for i in range(2, len(pats) + 1):
                extra += f" OR (title ILIKE :p{i}) OR (summary ILIKE :p{i}) OR (content ILIKE :p{i})"
            sql_kw = text(
                f"""
                SELECT id, title, url, summary, content, published_at, crawled_at, category,
                       sentiment_type, sentiment_score, relevance_score, related_stocks, keywords
                FROM news_articles
                WHERE (
                    (published_at IS NOT NULL AND published_at >= :cutoff)
                    OR (crawled_at IS NOT NULL AND crawled_at >= :cutoff)
                )
                AND (summary IS NOT NULL AND summary != '')
                AND (
                    (title ILIKE :p1) OR (summary ILIKE :p1) OR (content ILIKE :p1)
                    {extra}
                )
                ORDER BY COALESCE(published_at, crawled_at) DESC NULLS LAST
                LIMIT :lim
                """
            )
            params = {"cutoff": cutoff_fb, "p1": pats[0], "lim": max(need, min(limit - len(results), ensure_min or 0) or (limit - len(results)))}
            for i in range(2, len(pats) + 1):
                params[f"p{i}"] = pats[i - 1]
            rows2 = db.execute(sql_kw, params).mappings().all()
            # convert RowMapping to dict
            dict_rows2 = [dict(r) for r in rows2]
            push_articles(dict_rows2)

        # 若仍不足并且允许触发补齐，则尝试立即补齐并短暂等待后重查
        if trigger_topup and ensure_min and len(results) < ensure_min:
            try:
                scheduler = EnhancedNewsScheduler()
                await scheduler.run_topup_for_symbol(sym, min_required=ensure_min)
                if wait_seconds > 0:
                    import asyncio as _aio
                    await _aio.sleep(wait_seconds)
                # 重新查一次（仅 related 匹配 + 关键词兜底）
                results = []
                seen_urls = set()
                rows1 = db.execute(q1).scalars().all()
                push_articles(rows1)
                need = max(0, ensure_min - len(results)) if ensure_min else 0
                if need > 0 and len(results) < limit:
                    rows2 = db.execute(sql_kw, params).mappings().all() if 'sql_kw' in locals() else []
                    dict_rows2 = [dict(r) for r in rows2]
                    push_articles(dict_rows2)
            except Exception:
                pass

        # 如仍不足且允许，合成占位以消除“信息不足”提示
        if allow_placeholder and ensure_min and len(results) < ensure_min:
            from datetime import datetime as _dt
            to_add = max(0, min(ensure_min, limit) - len(results))
            for i in range(to_add):
                results.append({
                    "id": None,
                    "title": f"占位：基础资料/行业综述 {i+1}",
                    "url": f"about:placeholder:{sym}:{i}",
                    "summary": f"为避免0新闻/信息不足，添加占位条目。建议查看‘基础资料’或扩大时间窗以获取更多上下文。",
                    **({"content": None} if include_content else {}),
                    "published_at": _dt.utcnow().isoformat(),
                    "crawled_at": _dt.utcnow().isoformat(),
                    "source": "placeholder",
                    "category": "general",
                    "sentiment_type": "neutral",
                    "sentiment_score": 0.0,
                    "relevance_score": 0.0,
                    "related_stocks": [sym],
                    "keywords": [sym, company_name] if company_name else [sym],
                    "is_placeholder": True,
                })

        # 排序并裁剪至 limit
        def sort_key(x):
            ts = x.get("published_at") or x.get("crawled_at")
            try:
                return datetime.fromisoformat(ts) if isinstance(ts, str) else (ts or datetime.min)
            except Exception:
                return datetime.min
        results.sort(key=sort_key, reverse=True)
        results = results[:limit]

        return {
            "symbol": sym,
            "company_name": company_name,
            "articles": results,
            "total_count": len(results),
            "diagnostics": {
                "related_primary_days": days,
                "ensure_min": ensure_min,
                "fallback_days": fallback_days,
                "min_content": min_content,
                "from_related_primary": len(rows1),
                "after_keyword_fallback": len(results)
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching stock news: {str(e)}")

@router.get('/basic_profile/{symbol}')
async def get_basic_profile(
    symbol: str,
    max_results: int = Query(8, ge=1, le=20),
    include_crawl: bool = Query(False, description="If true, attempt to crawl the first 1-2 pages for summary snippets"),
    db: Session = Depends(get_db),
):
    """基于公司名称的搜索引擎汇总，返回基础资料线索（标题+链接+可选简要摘要）。

    - 优先从数据源/自选股获取公司名；
    - 使用 SearXNG 检索 ‘公司名 公司简介/主营/概况’ 等组合；
    - 可选抓取前1-2条页面提取100~200字摘要（尽量避免开销）。
    """
    sym = symbol.upper()
    # 公司名获取
    company_name = None
    try:
        stock_info = get_stock_info(sym)
        company_name = (stock_info or {}).get('name')
    except Exception:
        try:
            w = db.execute(select(Watchlist).where(Watchlist.symbol == sym)).scalar_one_or_none()
            if w and getattr(w, 'name', None):
                company_name = w.name
        except Exception:
            company_name = None

    if not company_name:
        company_name = sym

    queries = [
        f"{company_name} 公司简介",
        f"{company_name} 主营 业务",
        f"{company_name} 公司 概况",
    ]
    svc = NewsSearchService()
    results = []
    for q in queries:
        try:
            rs = await svc.search_news(query=q, category="general", time_range="month", max_results=max_results, language=os.getenv("SEARXNG_LANGUAGE", "zh-CN"))
            for r in rs:
                item = {"title": r.get("title"), "url": r.get("url"), "engines": r.get("engines")}
                if item not in results:
                    results.append(item)
        except Exception:
            continue
        if len(results) >= max_results:
            break
    results = results[:max_results]

    crawled = []
    if include_crawl and results:
        try:
            async with NewsContentCrawler() as crawler:
                for r in results[:2]:
                    try:
                        cr = await crawler.crawl_article(r["url"])  # type: ignore[index]
                        if cr.get("status") == "success":
                            # Take a short snippet
                            content = (cr.get("content") or "").strip()
                            snippet = content[:200] + ("..." if len(content) > 200 else "")
                            crawled.append({
                                "url": r["url"],
                                "title": r["title"],
                                "snippet": snippet,
                                "domain": cr.get("domain"),
                            })
                    except Exception:
                        continue
        except Exception:
            pass

    # 读取 DB 内已有画像（若存在）
    prof_row = None
    try:
        from ..core.models import StockProfile
        prof_row = db.query(StockProfile).filter(StockProfile.symbol == sym).first()
    except Exception:
        prof_row = None

    profile_db = None
    if prof_row:
        profile_db = {
            "symbol": prof_row.symbol,
            "company_name": prof_row.company_name,
            "industry": prof_row.industry,
            "sub_industry": prof_row.sub_industry,
            "business_summary": prof_row.business_summary,
            "last_refreshed": prof_row.last_refreshed.isoformat() if getattr(prof_row, 'last_refreshed', None) else None,
        }

    return {
        "symbol": sym,
        "company_name": company_name,
        "search_queries": queries,
        "search_results": results,
        "crawled_snippets": crawled,
        "profile_db": profile_db,
    }

@router.get('/articles')
async def get_news_articles(
    db: Session = Depends(get_db),
    category: Optional[str] = Query(None, description="新闻类别"),
    sentiment: Optional[str] = Query(None, description="情绪类型: positive/negative/neutral"),
    symbol: Optional[str] = Query(None, description="关联股票代码"),
    sector: Optional[str] = Query(None, description="行业筛选"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_content: bool = Query(False),
    days: Optional[int] = Query(None, ge=1, le=365, description="过去N天内的新闻"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    sort_by: str = Query("time", description="排序方式: time/relevance/sentiment"),
    sort_order: str = Query("desc", description="排序顺序: asc/desc")
):
    """获取新闻文章列表
    
    支持多种筛选条件：
    - category: 新闻类别
    - sentiment: 情绪类型 (positive/negative/neutral)
    - symbol: 关联股票代码
    - sector: 行业筛选（通过关联股票的行业）
    - keyword: 标题或摘要中的关键词
    - days: 过去N天内的新闻
    - start_date/end_date: 指定日期范围
    
    排序方式：
    - time: 按发布时间
    - relevance: 按相关性评分
    - sentiment: 按情绪评分
    """
    # 防御性限制，避免超大查询长时间占用连接
    limit = min(max(1, limit), 200)
    # 仅选择必要字段，避免 ORM 关系触发额外查询
    query = select(
        NewsArticle.id,
        NewsArticle.title,
        NewsArticle.url,
        NewsArticle.summary,
        NewsArticle.content,
        NewsArticle.published_at,
        NewsArticle.crawled_at,
        NewsArticle.category,
        NewsArticle.sentiment_type,
        NewsArticle.sentiment_score,
        NewsArticle.relevance_score,
        NewsArticle.related_stocks,
        NewsArticle.keywords,
        NewsSource.name,
    ).join(NewsSource, isouter=True)
    if category:
        query = query.where(NewsArticle.category == category)
    if sentiment:
        query = query.where(NewsArticle.sentiment_type == sentiment)
    if symbol:
        query = query.where(NewsArticle.related_stocks.contains([symbol]))
    
    # 行业筛选：通过关联股票的行业
    if sector:
        # 先获取该行业的所有股票
        sector_symbols = db.execute(
            select(Watchlist.symbol).where(Watchlist.sector == sector)
        ).scalars().all()
        if sector_symbols:
            # 筛选关联了这些股票的新闻
            sector_conditions = [NewsArticle.related_stocks.contains([s]) for s in sector_symbols]
            query = query.where(or_(*sector_conditions))
    
    # 关键词搜索
    if keyword:
        keyword_pattern = f"%{keyword}%"
        query = query.where(
            or_(
                NewsArticle.title.ilike(keyword_pattern),
                NewsArticle.summary.ilike(keyword_pattern)
            )
        )
    
    # 新增：只返回有有效摘要的文章
    query = query.where(and_(NewsArticle.summary.isnot(None), NewsArticle.summary != ''))
    
    # 日期范围筛选
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date)
            query = query.where(
                or_(
                    NewsArticle.published_at >= start_dt,
                    and_(NewsArticle.published_at.is_(None), NewsArticle.crawled_at >= start_dt)
                )
            )
        except ValueError:
            pass
    
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date) + timedelta(days=1)  # 包含结束日
            query = query.where(
                or_(
                    NewsArticle.published_at < end_dt,
                    and_(NewsArticle.published_at.is_(None), NewsArticle.crawled_at < end_dt)
                )
            )
        except ValueError:
            pass
    
    if days is not None and not start_date:
        cutoff = datetime.now() - timedelta(days=days)
        query = query.where(
            or_(
                and_(NewsArticle.published_at.isnot(None), NewsArticle.published_at >= cutoff),
                and_(NewsArticle.crawled_at.isnot(None), NewsArticle.crawled_at >= cutoff),
            )
        )
    
    # 排序
    if sort_by == "relevance":
        order_col = NewsArticle.relevance_score
    elif sort_by == "sentiment":
        order_col = NewsArticle.sentiment_score
    else:
        order_col = NewsArticle.published_at
    
    if sort_order == "asc":
        query = query.order_by(order_col.asc().nullslast())
    else:
        query = query.order_by(order_col.desc().nullslast())
    
    query = query.offset(offset).limit(limit)
    rows = db.execute(query).all()
    
    # 计算总数（用于分页）
    count_query = select(func.count(NewsArticle.id))
    # 应用相同的筛选条件（简化版）
    if category:
        count_query = count_query.where(NewsArticle.category == category)
    if sentiment:
        count_query = count_query.where(NewsArticle.sentiment_type == sentiment)
    if symbol:
        count_query = count_query.where(NewsArticle.related_stocks.contains([symbol]))
    count_query = count_query.where(and_(NewsArticle.summary.isnot(None), NewsArticle.summary != ''))
    total_count = db.execute(count_query).scalar() or 0
    
    articles = []
    for r in rows:
        (
            id_, title, url, summary, content, published_at, crawled_at, category,
            sentiment_type, sentiment_score, relevance_score, related_stocks, keywords, source_name
        ) = r
        item = {
            "id": id_,
            "title": title,
            "url": url,
            "summary": summary,
            **({"content": content} if include_content else {}),
            "published_at": published_at.isoformat() if published_at else None,
            "published_dt": published_at.isoformat() if published_at else None,
            "source": source_name,
            "category": category,
            "sentiment_type": sentiment_type,
            "sentiment_score": sentiment_score,
            "relevance_score": relevance_score,
            "related_stocks": related_stocks,
            "keywords": keywords,
        }
        articles.append(item)
    return {
        "articles": articles,
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(articles) < total_count
    }


# ==================== 新闻行业/主题统计 ====================

@router.get('/sectors')
async def get_news_sectors(
    days: int = Query(7, ge=1, le=90, description="统计过去N天的新闻"),
    db: Session = Depends(get_db)
):
    """获取新闻按行业分布的统计
    
    返回各行业的新闻数量和情绪分布，用于行业筛选器。
    """
    cutoff = datetime.now() - timedelta(days=days)
    
    # 获取所有行业
    sectors = db.execute(
        select(Watchlist.sector, func.count(Watchlist.symbol).label('stock_count'))
        .where(and_(Watchlist.enabled == True, Watchlist.sector.isnot(None)))
        .group_by(Watchlist.sector)
    ).all()
    
    result = []
    for sector, stock_count in sectors:
        if not sector:
            continue
            
        # 获取该行业的股票
        symbols = db.execute(
            select(Watchlist.symbol).where(
                and_(Watchlist.sector == sector, Watchlist.enabled == True)
            )
        ).scalars().all()
        
        # 统计该行业相关的新闻数量
        news_count = 0
        sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}
        
        for symbol in symbols:
            # 统计该股票的新闻
            count_result = db.execute(
                select(
                    func.count(NewsArticle.id),
                    NewsArticle.sentiment_type
                )
                .where(
                    and_(
                        NewsArticle.related_stocks.contains([symbol]),
                        or_(
                            NewsArticle.published_at >= cutoff,
                            and_(NewsArticle.published_at.is_(None), NewsArticle.crawled_at >= cutoff)
                        )
                    )
                )
                .group_by(NewsArticle.sentiment_type)
            ).all()
            
            for cnt, sent in count_result:
                news_count += cnt
                if sent in sentiment_counts:
                    sentiment_counts[sent] += cnt
        
        if news_count > 0:
            result.append({
                "sector": sector,
                "stock_count": stock_count,
                "news_count": news_count,
                "sentiment_distribution": sentiment_counts,
                "dominant_sentiment": max(sentiment_counts, key=sentiment_counts.get)
            })
    
    # 按新闻数量排序
    result.sort(key=lambda x: x["news_count"], reverse=True)
    
    return {
        "period_days": days,
        "sectors": result,
        "total_sectors": len(result)
    }


@router.get('/stats')
async def get_news_stats(db: Session = Depends(get_db)):
    try:
        total_articles = db.execute(text("SELECT COUNT(*) as count FROM news_articles")).first().count
        today = datetime.now().date()
        today_articles = db.execute(text("SELECT COUNT(*) as count FROM news_articles WHERE DATE(crawled_at) = :today"), {"today": today}).first().count
        sentiment_result = db.execute(text("""
            SELECT sentiment_type, COUNT(*) as count
            FROM news_articles
            WHERE sentiment_type IS NOT NULL
            GROUP BY sentiment_type
        """)).all()
        pos = neg = neu = 0
        for r in sentiment_result:
            if r.sentiment_type == 'positive': pos = r.count
            elif r.sentiment_type == 'negative': neg = r.count
            elif r.sentiment_type == 'neutral': neu = r.count
        total_sentiment = pos + neg + neu
        if total_sentiment:
            pos = round(pos/total_sentiment*100)
            neg = round(neg/total_sentiment*100)
            neu = round(neu/total_sentiment*100)
        sources_result = db.execute(text("""
            SELECT ns.name as source, COUNT(*) as count
            FROM news_articles na
            JOIN news_sources ns ON na.source_id = ns.id
            WHERE na.source_id IS NOT NULL
            GROUP BY ns.name
            ORDER BY count DESC
            LIMIT 10
        """)).all()
        top_sources = [{"source": r.source, "count": r.count} for r in sources_result]
        stocks_result = db.execute(text(r"""
            SELECT stock, COUNT(*) as count
            FROM (
                SELECT jsonb_array_elements_text(related_stocks) AS stock
                FROM news_articles
                WHERE COALESCE(
                    CASE
                        WHEN related_stocks IS NOT NULL AND jsonb_typeof(related_stocks) = 'array'
                        THEN jsonb_array_length(related_stocks)
                    END,
                    0
                ) > 0
            ) t
            WHERE stock ~ '^[0-9]{6}\\.(SH|SZ)$'
            GROUP BY stock
            ORDER BY count DESC
            LIMIT 10
        """)).all()
        top_stocks = [{"stock": r.stock, "count": r.count} for r in stocks_result]
        return {"total_articles": total_articles, "today_articles": today_articles, "positive_sentiment": pos, "negative_sentiment": neg, "neutral_sentiment": neu, "top_sources": top_sources, "top_stocks": top_stocks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting news stats: {str(e)}")

@router.get('/search_db')
async def search_db(
    query: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=200),
    days: int = Query(60, ge=1, le=365),
    include_content: bool = Query(False),
    db: Session = Depends(get_db)
):
    """
    搜索数据库中的新闻（按关键词），用于 Agent 的 DB-first 融合/回退。

    - 在 title/summary/content 上进行 ILIKE 关键词匹配
    - 限定近 N 天（默认 60 天）
    - 返回按 published_at DESC（为空则按 crawled_at DESC）
    """
    try:
        cutoff = datetime.now() - timedelta(days=days)
        # 使用原生 SQL 以便同时按 title/summary/content 模糊匹配
        sql = text(
            """
            SELECT id, title, url, summary, content, published_at, crawled_at, source_id, category,
                   sentiment_type, sentiment_score, relevance_score, related_stocks, keywords
            FROM news_articles
            WHERE (
                (title ILIKE :pat)
                OR (summary ILIKE :pat)
                OR (content ILIKE :pat)
            )
            AND (
                (published_at IS NOT NULL AND published_at >= :cutoff)
                OR (crawled_at IS NOT NULL AND crawled_at >= :cutoff)
            )
            ORDER BY COALESCE(published_at, crawled_at) DESC NULLS LAST
            LIMIT :lim
            """
        )
        pat = f"%{query}%"
        rows = db.execute(sql, {"pat": pat, "cutoff": cutoff, "lim": limit}).all()
        out = []
        for r in rows:
            item = {
                "id": r.id,
                "title": r.title,
                "url": r.url,
                "summary": r.summary,
                **({"content": r.content} if include_content else {}),
                "published_at": r.published_at.isoformat() if r.published_at else None,
                "crawled_at": r.crawled_at.isoformat() if r.crawled_at else None,
                "category": r.category,
                "sentiment_type": r.sentiment_type,
                "sentiment_score": r.sentiment_score,
                "relevance_score": r.relevance_score,
                "related_stocks": r.related_stocks,
                "keywords": r.keywords,
            }
            out.append(item)
        return {"query": query, "count": len(out), "articles": out}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error searching DB: {str(e)}")

@router.get('/counts')
async def get_news_counts(
    db: Session = Depends(get_db),
    symbols: Optional[List[str]] = Query(None, description="List of symbols, repeatable: ?symbols=600519.SH&symbols=300750.SZ"),
    days: int = Query(7, ge=1, le=365),
    min_content: int = Query(0, ge=0, le=10000),
    mode: str = Query('related', description="Count mode: 'related' (by related_stocks array) or 'keyword' (by ILIKE keyword search using symbol and stock name)")
):
    """
    返回过去 N 天内每个股票代码的新闻数量统计（按 related_stocks 关联）。

    - 若提供 symbols，则仅统计这些代码；未命中者返回 0。
    - 仅统计 published_at 或 crawled_at 在窗口内的文章。
    - 可选按内容长度进行最小过滤（min_content）。
    """
    try:
        cutoff = datetime.now() - timedelta(days=days)
        if mode == 'keyword' and symbols:
            results = []
            for s in symbols:
                name = None
                try:
                    info = get_stock_info(s)
                    name = (info or {}).get('name')
                except Exception:
                    name = None
                pats = [f"%{s}%"]
                if name and name not in s:
                    pats.append(f"%{name}%")
                # 统计匹配 title/summary/content 的条数（近 N 天 + 最小内容长度）
                sql_kw = text(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM news_articles
                    WHERE (
                        (published_at IS NOT NULL AND published_at >= :cutoff)
                        OR (crawled_at IS NOT NULL AND crawled_at >= :cutoff)
                    )
                    AND (
                        (title ILIKE :p1) OR (summary ILIKE :p1) OR (content ILIKE :p1)
                        {extra}
                    )
                    AND (CASE WHEN :minlen > 0 THEN LENGTH(COALESCE(content, summary, '')) >= :minlen ELSE 1=1 END)
                    """.replace("{extra}", " OR (title ILIKE :p2) OR (summary ILIKE :p2) OR (content ILIKE :p2)" if len(pats) > 1 else "")
                )
                params = {"cutoff": cutoff, "minlen": min_content, "p1": pats[0]}
                if len(pats) > 1:
                    params["p2"] = pats[1]
                row = db.execute(sql_kw, params).first()
                cnt = int(row.cnt) if row and hasattr(row, 'cnt') else 0
                results.append({"symbol": s, "count": cnt})
            return {"days": days, "min_content": min_content, "mode": mode, "total_symbols": len(results), "counts": results}
        # related mode（展开 related_stocks 统计全部，再按需过滤）
        sql = text(
            r"""
            SELECT t.stock AS symbol, COUNT(*) AS cnt
            FROM (
                SELECT jsonb_array_elements_text(related_stocks) AS stock, content, summary, published_at, crawled_at
                FROM news_articles
                WHERE (
                    (published_at IS NOT NULL AND published_at >= :cutoff)
                    OR (crawled_at IS NOT NULL AND crawled_at >= :cutoff)
                )
            ) t
            WHERE (CASE WHEN :minlen > 0 THEN LENGTH(COALESCE(t.content, t.summary, '')) >= :minlen ELSE 1=1 END)
            GROUP BY t.stock
            ORDER BY cnt DESC
            """
        )
        rows = db.execute(sql, {"cutoff": cutoff, "minlen": min_content}).all()
        counts_map = {r.symbol: r.cnt for r in rows}
        if symbols:
            out = [{"symbol": s, "count": int(counts_map.get(s, 0))} for s in symbols]
        else:
            out = [{"symbol": k, "count": int(v)} for k, v in counts_map.items()]
        return {"days": days, "min_content": min_content, "mode": mode, "total_symbols": len(out), "counts": out}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting news counts: {str(e)}")

@router.post('/{article_id}/bookmark')
async def toggle_bookmark(article_id: int, db: Session = Depends(get_db)):
    try:
        article = db.execute(text("SELECT id, is_bookmarked FROM news_articles WHERE id = :article_id"), {"article_id": article_id}).first()
        if not article:
            raise HTTPException(status_code=404, detail="Article not found")
        new_status = not article.is_bookmarked
        db.execute(text("UPDATE news_articles SET is_bookmarked = :status WHERE id = :article_id"), {"status": new_status, "article_id": article_id})
        db.commit()
        return {"status": "success", "article_id": article_id, "is_bookmarked": new_status}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback(); raise HTTPException(status_code=500, detail=f"Error toggling bookmark: {str(e)}")

@router.post('/{article_id}/read')
async def toggle_read(article_id: int, db: Session = Depends(get_db)):
    try:
        article = db.execute(text("SELECT id, is_read FROM news_articles WHERE id = :article_id"), {"article_id": article_id}).first()
        if not article:
            raise HTTPException(status_code=404, detail="Article not found")
        new_status = not article.is_read
        db.execute(text("UPDATE news_articles SET is_read = :status WHERE id = :article_id"), {"status": new_status, "article_id": article_id})
        db.commit()
        return {"status": "success", "article_id": article_id, "is_read": new_status}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback(); raise HTTPException(status_code=500, detail=f"Error toggling read status: {str(e)}")

@router.post('/batch-update')
async def batch_update_news(article_ids: List[int], action: str = Query(...), db: Session = Depends(get_db)):
    try:
        if not article_ids:
            raise HTTPException(status_code=400, detail="No article IDs provided")
        if action not in ['bookmark','unbookmark','mark_read','mark_unread']:
            raise HTTPException(status_code=400, detail="Invalid action")
        if action == 'bookmark': sql = "UPDATE news_articles SET is_bookmarked = true WHERE id = ANY(:ids)"
        elif action == 'unbookmark': sql = "UPDATE news_articles SET is_bookmarked = false WHERE id = ANY(:ids)"
        elif action == 'mark_read': sql = "UPDATE news_articles SET is_read = true WHERE id = ANY(:ids)"
        else: sql = "UPDATE news_articles SET is_read = false WHERE id = ANY(:ids)"
        db.execute(text(sql), {"ids": article_ids}); db.commit()
        return {"status": "success", "updated_count": len(article_ids), "action": action}
    except HTTPException: raise
    except Exception as e:
        db.rollback(); raise HTTPException(status_code=500, detail=f"Error batch updating news: {str(e)}")

@router.delete('/{article_id}')
async def delete_news_article(article_id: int, db: Session = Depends(get_db)):
    try:
        article = db.execute(text("SELECT id FROM news_articles WHERE id = :article_id"), {"article_id": article_id}).first()
        if not article:
            raise HTTPException(status_code=404, detail="Article not found")
        db.execute(text("DELETE FROM news_articles WHERE id = :article_id"), {"article_id": article_id})
        db.commit()
        return {"status": "success", "deleted_article_id": article_id}
    except HTTPException: raise
    except Exception as e:
        db.rollback(); raise HTTPException(status_code=500, detail=f"Error deleting article: {str(e)}")

@router.patch('/{article_id}')
async def update_news_article(article_id: int, payload: NewsArticleUpdate, db: Session = Depends(get_db)):
    try:
        article = db.get(NewsArticle, article_id)
        if not article:
            raise HTTPException(status_code=404, detail="Article not found")
        updated = {}
        if payload.title is not None:
            article.title = payload.title.strip(); updated['title'] = article.title
        if payload.summary is not None:
            article.summary = payload.summary.strip(); updated['summary'] = article.summary
        if payload.sentiment_type is not None:
            article.sentiment_type = payload.sentiment_type; updated['sentiment_type'] = article.sentiment_type
        if payload.sentiment_score is not None:
            article.sentiment_score = payload.sentiment_score; updated['sentiment_score'] = article.sentiment_score
        if payload.related_stocks is not None:
            dedup = []
            for s in payload.related_stocks:
                if s and s not in dedup: dedup.append(s)
            article.related_stocks = dedup; updated['related_stocks'] = article.related_stocks
        if not updated:
            return {"status": "noop", "message": "No fields updated"}
        db.add(article); db.commit(); db.refresh(article)
        return {"status": "success", "article": {"id": article.id, "title": article.title, "summary": article.summary, "sentiment_type": article.sentiment_type, "sentiment_score": article.sentiment_score, "related_stocks": article.related_stocks or []}, "updated_fields": list(updated.keys())}
    except HTTPException: raise
    except Exception as e:
        db.rollback(); raise HTTPException(status_code=500, detail=f"Error updating article: {str(e)}")


