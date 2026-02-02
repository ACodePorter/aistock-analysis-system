"""
采集服务 - 统一多源新闻/公告采集入口

职责：
1. 聚合东财/新浪/L1公告/L3官方信源
2. 应用限速/熔断/重试策略
3. 落库原始数据到MongoDB和MinIO
4. 记录采集元数据和失败原因
"""

import asyncio
import hashlib
import logging
import random
import time
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

import httpx

from ..core.constants import COLLECTOR_CONFIG, SourceLevelEnum

logger = logging.getLogger(__name__)


class RateLimiter:
    """域名级限速器"""
    
    def __init__(self):
        self._last_request: Dict[str, float] = {}
        self._request_counts: Dict[str, List[float]] = {}
    
    def get_config(self, domain: str) -> dict:
        """获取域名限速配置"""
        rate_config = COLLECTOR_CONFIG.get("rate_limit", {})
        if domain in rate_config:
            return rate_config[domain]
        return rate_config.get("default", {"requests_per_minute": 20, "burst_size": 10})
    
    async def wait_if_needed(self, domain: str) -> None:
        """等待直到可以发送请求"""
        config = self.get_config(domain)
        rpm = config["requests_per_minute"]
        min_interval = 60.0 / rpm
        
        now = time.time()
        last = self._last_request.get(domain, 0)
        elapsed = now - last
        
        if elapsed < min_interval:
            wait_time = min_interval - elapsed + random.uniform(0.1, 0.5)
            logger.debug(f"Rate limiting {domain}: waiting {wait_time:.2f}s")
            await asyncio.sleep(wait_time)
        
        self._last_request[domain] = time.time()


class CircuitBreaker:
    """断路器"""
    
    def __init__(self):
        self._failure_counts: Dict[str, int] = {}
        self._open_until: Dict[str, float] = {}
        self._half_open_requests: Dict[str, int] = {}
    
    def is_open(self, domain: str) -> bool:
        """检查断路器是否打开"""
        if domain not in self._open_until:
            return False
        
        if time.time() >= self._open_until[domain]:
            # 进入半开状态
            return False
        
        return True
    
    def record_success(self, domain: str) -> None:
        """记录成功"""
        self._failure_counts[domain] = 0
        if domain in self._open_until:
            del self._open_until[domain]
        if domain in self._half_open_requests:
            del self._half_open_requests[domain]
    
    def record_failure(self, domain: str) -> None:
        """记录失败"""
        config = COLLECTOR_CONFIG.get("circuit_breaker", {})
        threshold = config.get("failure_threshold", 5)
        timeout_minutes = config.get("timeout_minutes", 30)
        
        self._failure_counts[domain] = self._failure_counts.get(domain, 0) + 1
        
        if self._failure_counts[domain] >= threshold:
            self._open_until[domain] = time.time() + (timeout_minutes * 60)
            logger.warning(f"Circuit breaker OPEN for {domain}: {timeout_minutes} minutes")


class CollectorService:
    """采集服务入口"""
    
    def __init__(self):
        """初始化采集器"""
        self.rate_limiter = RateLimiter()
        self.circuit_breaker = CircuitBreaker()
        self.timeout = COLLECTOR_CONFIG.get("timeout_seconds", 30)
    
    def _extract_domain(self, url: str) -> str:
        """从URL提取域名"""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc
    
    async def fetch_url(self, url: str, headers: Optional[dict] = None) -> Optional[dict]:
        """
        获取单个URL内容（带限速和熔断）
        
        Returns:
            {
                "url": "...",
                "status_code": 200,
                "content": "...",
                "fetched_at": "...",
                "error": None
            }
        """
        domain = self._extract_domain(url)
        
        # 检查断路器
        if self.circuit_breaker.is_open(domain):
            logger.warning(f"Circuit breaker open for {domain}, skipping {url}")
            return {
                "url": url,
                "status_code": None,
                "content": None,
                "fetched_at": datetime.utcnow().isoformat(),
                "error": "circuit_breaker_open"
            }
        
        # 限速等待
        await self.rate_limiter.wait_if_needed(domain)
        
        # 重试配置
        retry_config = COLLECTOR_CONFIG.get("retry", {})
        max_retries = retry_config.get("max_retries", 3)
        backoff_base = retry_config.get("backoff_base", 2)
        jitter_factor = retry_config.get("jitter_factor", 0.1)
        
        default_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        if headers:
            default_headers.update(headers)
        
        last_error = None
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                    response = await client.get(url, headers=default_headers)
                    
                    if response.status_code == 200:
                        self.circuit_breaker.record_success(domain)
                        return {
                            "url": url,
                            "status_code": 200,
                            "content": response.text,
                            "fetched_at": datetime.utcnow().isoformat(),
                            "error": None
                        }
                    elif response.status_code in (429, 503):
                        # 需要重试
                        last_error = f"http_{response.status_code}"
                        logger.warning(f"Rate limited {url}: {response.status_code}")
                    elif response.status_code in (403, 404):
                        # 不重试
                        self.circuit_breaker.record_failure(domain)
                        return {
                            "url": url,
                            "status_code": response.status_code,
                            "content": None,
                            "fetched_at": datetime.utcnow().isoformat(),
                            "error": f"http_{response.status_code}"
                        }
                    else:
                        last_error = f"http_{response.status_code}"
                        
            except httpx.TimeoutException:
                last_error = "timeout"
                logger.warning(f"Timeout fetching {url}")
            except httpx.RequestError as e:
                last_error = f"request_error: {str(e)}"
                logger.warning(f"Request error fetching {url}: {e}")
            except Exception as e:
                last_error = f"unknown_error: {str(e)}"
                logger.error(f"Unexpected error fetching {url}: {e}")
            
            # 指数退避 + 抖动
            if attempt < max_retries - 1:
                wait_time = (backoff_base ** attempt) + random.uniform(0, jitter_factor * (backoff_base ** attempt))
                logger.debug(f"Retry {attempt + 1}/{max_retries} for {url}, waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
        
        # 所有重试失败
        self.circuit_breaker.record_failure(domain)
        return {
            "url": url,
            "status_code": None,
            "content": None,
            "fetched_at": datetime.utcnow().isoformat(),
            "error": last_error
        }
    
    async def collect_for_symbol(self, symbol: str) -> dict:
        """
        为指定股票采集最新新闻
        
        Args:
            symbol: 股票代码（如 600519.SH）
            
        Returns:
            采集结果字典：
            {
                "symbol": "600519.SH",
                "articles": [...],
                "errors": [...],
                "meta": {}
            }
        """
        logger.info(f"Collecting news for {symbol}")
        
        # 构建搜索URL列表
        urls = self._build_search_urls(symbol)
        
        articles = []
        errors = []
        
        for url_info in urls:
            result = await self.fetch_url(url_info["url"])
            if result["error"]:
                errors.append({
                    "url": url_info["url"],
                    "source": url_info["source"],
                    "error": result["error"]
                })
            elif result["content"]:
                # 解析内容
                parsed = self._parse_response(result["content"], url_info["source"])
                articles.extend(parsed)
        
        return {
            "symbol": symbol,
            "articles": articles,
            "errors": errors,
            "meta": {
                "collected_at": datetime.utcnow().isoformat(),
                "total_urls": len(urls),
                "success_count": len(urls) - len(errors),
                "article_count": len(articles)
            }
        }
    
    def _build_search_urls(self, symbol: str) -> List[dict]:
        """构建搜索URL列表"""
        # 股票代码处理
        code = symbol.split('.')[0]
        
        urls = []
        
        # 东方财富
        urls.append({
            "url": f"https://so.eastmoney.com/news/s?keyword={code}",
            "source": "eastmoney",
            "source_level": "L2"
        })
        
        # 新浪财经
        urls.append({
            "url": f"https://search.sina.com.cn/?q={code}&c=news&ie=utf-8",
            "source": "sina",
            "source_level": "L2"
        })
        
        return urls
    
    def _parse_response(self, content: str, source: str) -> List[dict]:
        """解析响应内容（简化实现，实际需要按源定制）"""
        # TODO: 实现具体的解析逻辑
        return []
    
    async def collect_batch(self, symbols: List[str]) -> dict:
        """批量采集"""
        results = []
        for symbol in symbols:
            result = await self.collect_for_symbol(symbol)
            results.append(result)
            # 批量间歇
            await asyncio.sleep(0.5)
        
        return {
            "total_symbols": len(symbols),
            "results": results,
            "collected_at": datetime.utcnow().isoformat()
        }

