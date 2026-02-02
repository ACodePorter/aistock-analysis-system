"""
Web 数据查询 API 路由

提供统一的 REST API 接口，供前端和 Agent 调用各类互联网数据查询功能。

端点：
- GET /api/webdata/weather?location=Beijing  - 查询天气
- GET /api/webdata/stock?symbol=002594.SZ    - 查询股票行情
- GET /api/webdata/encyclopedia?keyword=比亚迪 - 查询百科
- GET /api/webdata/news?keyword=A股           - 查询新闻
- GET /api/webdata/search?q=关键词            - 通用搜索
- GET /api/webdata/health                     - 健康检查

作者：AI Stock Analysis Enhancement
日期：2026-01
"""

import logging
from typing import Optional, List
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field

from ..utils.web_data_providers import (
    get_web_data_manager,
    query_weather,
    query_stock,
    query_encyclopedia,
    query_news,
    query_search,
    DataCategory,
    ProviderResult,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webdata", tags=["Web Data"])


# ============== 响应模型 ==============

class WeatherResponse(BaseModel):
    """天气响应"""
    success: bool
    source: str
    latency_ms: int
    cached: bool = False
    data: Optional[dict] = None
    error: Optional[str] = None


class StockResponse(BaseModel):
    """股票响应"""
    success: bool
    source: str
    latency_ms: int
    cached: bool = False
    data: Optional[dict] = None
    error: Optional[str] = None


class EncyclopediaResponse(BaseModel):
    """百科响应"""
    success: bool
    source: str
    latency_ms: int
    cached: bool = False
    data: Optional[dict] = None
    error: Optional[str] = None


class NewsResponse(BaseModel):
    """新闻响应"""
    success: bool
    source: str
    latency_ms: int
    cached: bool = False
    data: Optional[dict] = None
    error: Optional[str] = None


class SearchResponse(BaseModel):
    """搜索响应"""
    success: bool
    source: str
    latency_ms: int
    cached: bool = False
    data: Optional[dict] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    providers: dict


class MultiQueryRequest(BaseModel):
    """批量查询请求"""
    queries: List[dict] = Field(..., description="查询列表，每个查询包含 type 和对应参数")


class MultiQueryResponse(BaseModel):
    """批量查询响应"""
    results: List[dict]


# ============== API 端点 ==============

@router.get("/weather", response_model=WeatherResponse)
async def get_weather(
    location: str = Query(..., description="地点名称，如 Beijing, Shanghai, Tokyo"),
    lang: str = Query("zh", description="语言代码"),
    use_cache: bool = Query(True, description="是否使用缓存"),
):
    """
    查询指定地点的天气信息
    
    返回温度、体感温度、湿度、天气描述、风速等信息。
    数据来源：wttr.in (主), OpenWeatherMap (备)
    """
    try:
        result = query_weather(location, lang=lang, use_cache=use_cache)
        return WeatherResponse(
            success=result.success,
            source=result.source,
            latency_ms=result.latency_ms,
            cached=result.cached,
            data=result.data if result.success else None,
            error=result.error if not result.success else None,
        )
    except Exception as e:
        logger.error(f"[weather] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stock", response_model=StockResponse)
async def get_stock(
    symbol: str = Query(..., description="股票代码，如 002594.SZ, 1211.HK, AAPL"),
    use_cache: bool = Query(True, description="是否使用缓存"),
):
    """
    查询股票实时行情
    
    支持 A 股、港股、美股等多市场。
    返回价格、涨跌、涨跌幅、成交量等信息。
    数据来源：Yahoo Finance (主), 新浪财经 (备)
    """
    try:
        result = query_stock(symbol, use_cache=use_cache)
        return StockResponse(
            success=result.success,
            source=result.source,
            latency_ms=result.latency_ms,
            cached=result.cached,
            data=result.data if result.success else None,
            error=result.error if not result.success else None,
        )
    except Exception as e:
        logger.error(f"[stock] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stock/batch")
async def get_stock_batch(
    symbols: str = Query(..., description="股票代码列表，逗号分隔，如 002594.SZ,1211.HK,AAPL"),
    use_cache: bool = Query(True, description="是否使用缓存"),
):
    """
    批量查询股票行情
    
    一次查询多只股票，返回结果字典。
    """
    try:
        symbol_list = [s.strip() for s in symbols.split(',') if s.strip()]
        results = {}
        
        for symbol in symbol_list[:20]:  # 限制最多20只
            result = query_stock(symbol, use_cache=use_cache)
            results[symbol] = {
                'success': result.success,
                'source': result.source,
                'data': result.data if result.success else None,
                'error': result.error if not result.success else None,
            }
        
        return {'results': results}
    except Exception as e:
        logger.error(f"[stock/batch] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/encyclopedia", response_model=EncyclopediaResponse)
async def get_encyclopedia(
    keyword: str = Query(..., description="搜索关键词"),
    lang: str = Query("zh", description="语言代码 (zh, en, ja 等)"),
    use_cache: bool = Query(True, description="是否使用缓存"),
):
    """
    查询百科全书信息
    
    返回标题、摘要、URL、基本信息等。
    数据来源：Wikipedia (主), 百度百科 (备)
    """
    try:
        result = query_encyclopedia(keyword, lang=lang, use_cache=use_cache)
        return EncyclopediaResponse(
            success=result.success,
            source=result.source,
            latency_ms=result.latency_ms,
            cached=result.cached,
            data=result.data if result.success else None,
            error=result.error if not result.success else None,
        )
    except Exception as e:
        logger.error(f"[encyclopedia] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/news", response_model=NewsResponse)
async def get_news(
    keyword: str = Query(..., description="搜索关键词"),
    limit: int = Query(10, ge=1, le=50, description="返回数量"),
    language: str = Query("zh-CN", description="语言代码"),
    use_cache: bool = Query(True, description="是否使用缓存"),
):
    """
    搜索相关新闻
    
    返回新闻标题、描述、URL、来源、发布时间等。
    数据来源：NewsAPI (需配置 key), Google News RSS (免费)
    """
    try:
        result = query_news(keyword, limit=limit, language=language, use_cache=use_cache)
        return NewsResponse(
            success=result.success,
            source=result.source,
            latency_ms=result.latency_ms,
            cached=result.cached,
            data=result.data if result.success else None,
            error=result.error if not result.success else None,
        )
    except Exception as e:
        logger.error(f"[news] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/news/aggregated", response_model=NewsResponse)
async def get_news_aggregated(
    keyword: str = Query(..., description="搜索关键词"),
    min_articles: int = Query(20, ge=5, le=50, description="最小新闻数量"),
    max_articles: int = Query(50, ge=10, le=100, description="最大新闻数量"),
    timeout: float = Query(15.0, ge=5, le=30, description="聚合超时时间(秒)"),
    use_cache: bool = Query(True, description="是否使用缓存"),
):
    """
    聚合多源新闻搜索（目标获取20-50条高质量新闻）
    
    从多个新闻源并发查询并聚合去重，适用于深度分析场景。
    数据来源：
    - NewsAPI (国际新闻)
    - Google News RSS (国际新闻)
    - 财联社 (中国财经)
    - 华尔街见闻 (中国财经)
    - 金十数据 (财经快讯)
    - 东方财富 (A股新闻)
    - 新浪财经 (综合财经)
    - 腾讯财经 (综合财经)
    
    返回聚合后的新闻列表，包含去重统计和来源信息。
    """
    try:
        manager = get_web_data_manager()
        result = manager.query_news_aggregated(
            keyword=keyword,
            min_articles=min_articles,
            max_articles=max_articles,
            timeout=timeout,
            use_cache=use_cache
        )
        return NewsResponse(
            success=result.success,
            source=result.source,
            latency_ms=result.latency_ms,
            cached=result.cached,
            data=result.data if result.success else None,
            error=result.error if not result.success else None,
        )
    except Exception as e:
        logger.error(f"[news/aggregated] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search", response_model=SearchResponse)
async def get_search(
    q: str = Query(..., description="搜索关键词"),
    categories: str = Query("general", description="搜索分类 (general, news, images, videos)"),
    limit: int = Query(10, ge=1, le=50, description="返回数量"),
    time_range: str = Query("", description="时间范围 (day, week, month, year)"),
    use_cache: bool = Query(True, description="是否使用缓存"),
):
    """
    通用搜索
    
    使用 SearXNG 或 DuckDuckGo 进行搜索。
    返回标题、URL、摘要、来源引擎等。
    """
    try:
        result = query_search(
            q, 
            categories=categories, 
            limit=limit, 
            time_range=time_range,
            use_cache=use_cache
        )
        return SearchResponse(
            success=result.success,
            source=result.source,
            latency_ms=result.latency_ms,
            cached=result.cached,
            data=result.data if result.success else None,
            error=result.error if not result.success else None,
        )
    except Exception as e:
        logger.error(f"[search] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health", response_model=HealthResponse)
async def get_health():
    """
    获取所有数据提供器的健康状态
    
    返回每个提供器的状态、错误计数、成功计数等信息。
    """
    try:
        manager = get_web_data_manager()
        status = manager.get_health_status()
        
        # 计算总体状态
        all_healthy = True
        for providers in status.values():
            for p in providers:
                if p['status'] != 'healthy':
                    all_healthy = False
                    break
        
        return HealthResponse(
            status="healthy" if all_healthy else "degraded",
            providers=status,
        )
    except Exception as e:
        logger.error(f"[health] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reset/{provider_name}")
async def reset_provider(provider_name: str):
    """
    重置指定提供器的状态
    
    将提供器状态重置为健康，清除错误计数。
    """
    try:
        manager = get_web_data_manager()
        manager.reset_provider(provider_name)
        return {"success": True, "message": f"Provider {provider_name} reset"}
    except Exception as e:
        logger.error(f"[reset] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cache/clear")
async def clear_cache():
    """
    清空所有缓存
    """
    try:
        manager = get_web_data_manager()
        manager.clear_cache()
        return {"success": True, "message": "Cache cleared"}
    except Exception as e:
        logger.error(f"[cache/clear] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/multi", response_model=MultiQueryResponse)
async def multi_query(request: MultiQueryRequest):
    """
    批量执行多个查询
    
    请求体格式：
    ```json
    {
        "queries": [
            {"type": "weather", "location": "Beijing"},
            {"type": "stock", "symbol": "002594.SZ"},
            {"type": "encyclopedia", "keyword": "比亚迪"}
        ]
    }
    ```
    """
    try:
        manager = get_web_data_manager()
        results = []
        
        for query in request.queries[:10]:  # 限制最多10个查询
            query_type = query.get('type', '')
            result_data = {'type': query_type, 'success': False, 'error': 'Unknown type'}
            
            try:
                if query_type == 'weather':
                    result = manager.query_weather(query.get('location', ''))
                elif query_type == 'stock':
                    result = manager.query_stock(query.get('symbol', ''))
                elif query_type == 'encyclopedia':
                    result = manager.query_encyclopedia(
                        query.get('keyword', ''),
                        lang=query.get('lang', 'zh')
                    )
                elif query_type == 'news':
                    result = manager.query_news(
                        query.get('keyword', ''),
                        limit=query.get('limit', 10)
                    )
                elif query_type == 'search':
                    result = manager.query_search(
                        query.get('keyword', '') or query.get('q', ''),
                        categories=query.get('categories', 'general'),
                        limit=query.get('limit', 10)
                    )
                else:
                    result = None
                
                if result:
                    result_data = {
                        'type': query_type,
                        'success': result.success,
                        'source': result.source,
                        'latency_ms': result.latency_ms,
                        'data': result.data if result.success else None,
                        'error': result.error if not result.success else None,
                    }
            except Exception as e:
                result_data = {'type': query_type, 'success': False, 'error': str(e)}
            
            results.append(result_data)
        
        return MultiQueryResponse(results=results)
    except Exception as e:
        logger.error(f"[multi] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== 便捷的智能查询端点 ==============

@router.get("/smart")
async def smart_query(
    q: str = Query(..., description="自然语言查询，如 '北京天气' '比亚迪股价' '特斯拉是什么公司'"),
):
    """
    智能查询 - 自动识别查询类型并返回结果
    
    支持的查询模式：
    - 天气：包含"天气"、"weather"、"温度"等关键词
    - 股票：包含"股票"、"股价"、"行情"或股票代码格式
    - 百科：包含"是什么"、"介绍"、"简介"等关键词
    - 新闻：包含"新闻"、"最新"、"消息"等关键词
    - 其他：使用通用搜索
    """
    import re
    
    q_lower = q.lower()
    manager = get_web_data_manager()
    
    # 天气查询模式
    weather_patterns = ['天气', '气温', '温度', 'weather', '下雨', '下雪', '晴', '阴']
    for pattern in weather_patterns:
        if pattern in q_lower:
            # 提取地点
            location = q.replace(pattern, '').strip()
            location = re.sub(r'[的今天明天]', '', location).strip()
            if not location:
                location = 'Beijing'
            result = manager.query_weather(location)
            return {
                'query_type': 'weather',
                'query': q,
                'result': result.to_dict()
            }
    
    # 股票查询模式
    stock_patterns = ['股票', '股价', '行情', '涨跌', 'stock', '股']
    stock_code_pattern = r'[0-9]{6}\.(SZ|SH|HK|SS)|[0-9]{5}\.HK|[A-Z]{1,5}'
    
    code_match = re.search(stock_code_pattern, q.upper())
    if code_match:
        result = manager.query_stock(code_match.group())
        return {
            'query_type': 'stock',
            'query': q,
            'result': result.to_dict()
        }
    
    for pattern in stock_patterns:
        if pattern in q_lower:
            # 尝试提取股票名称并搜索
            name = q.replace(pattern, '').strip()
            # 这里可以添加股票名称到代码的映射
            result = manager.query_search(f"{name} 股票 行情", categories="news")
            return {
                'query_type': 'stock_search',
                'query': q,
                'result': result.to_dict()
            }
    
    # 百科查询模式
    wiki_patterns = ['是什么', '什么是', '介绍', '简介', '百科', 'wiki', '公司']
    for pattern in wiki_patterns:
        if pattern in q_lower:
            keyword = q.replace(pattern, '').strip()
            keyword = re.sub(r'[的？?]', '', keyword).strip()
            if keyword:
                result = manager.query_encyclopedia(keyword)
                return {
                    'query_type': 'encyclopedia',
                    'query': q,
                    'result': result.to_dict()
                }
    
    # 新闻查询模式
    news_patterns = ['新闻', '消息', '最新', '资讯', 'news']
    for pattern in news_patterns:
        if pattern in q_lower:
            keyword = q.replace(pattern, '').strip()
            if keyword:
                result = manager.query_news(keyword)
                return {
                    'query_type': 'news',
                    'query': q,
                    'result': result.to_dict()
                }
    
    # 默认：通用搜索
    result = manager.query_search(q)
    return {
        'query_type': 'search',
        'query': q,
        'result': result.to_dict()
    }
