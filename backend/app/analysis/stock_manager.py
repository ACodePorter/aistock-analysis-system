"""
模块说明
--------
stock_manager.py 提供对股票监控列表（Watchlist）及相关新闻关键词（NewsKeyword）、
新闻抓取任务（Task）等实体的管理能力。对外以异步方法（async def）暴露接口，
但内部使用同步的 SQLAlchemy Session 进行数据库操作。该模块负责：
- 增删改查监控股票；
- 为股票自动创建或更新新闻关键词；
- 批量操作（批量添加、批量启用/禁用）；
- 生成与监控相关的统计信息；
- 为单只股票创建新闻收集任务。
主要类
--------
StockListManager
    监控股票列表管理器，封装了与 Watchlist/NewsKeyword/NewsArticle/Task 相关的常用操作。
    初始化时使用 SessionLocal 作为 session_factory。
主要方法（摘要）
----------------
add_stock(symbol, name=None, sector=None, enabled=True) -> Watchlist
    验证股票代码（通过 get_stock_info），若存在则创建或更新 Watchlist 记录，
    并调用内部方法创建相关的新闻关键词。失败会抛出 ValueError（无效代码）或其他 DB 异常。
remove_stock(symbol) -> bool
    删除指定股票及其相关的 NewsKeyword。返回是否删除了任何记录。
update_stock(symbol, **kwargs) -> Optional[Watchlist]
    更新 Watchlist 的字段（仅更新存在的属性），并返回更新后的对象；找不到则返回 None。
enable_stock(symbol) / disable_stock(symbol) -> bool
    启用或禁用指定股票监控（基于 update_stock），返回操作是否成功。
get_stock(symbol) -> Optional[Watchlist]
    获取单只股票信息，找不到返回 None。
list_stocks(enabled_only=False, sector=None, limit=None, offset=0) -> List[Watchlist]
    列表查询，支持按启用状态、行业过滤，以及分页（limit/offset）。
get_stock_count(enabled_only=False) -> int
    返回监控股票总数或仅启用的数量。
get_sectors() -> List[str]
    返回非空的行业名称列表（去重）。
batch_add_stocks(stocks: List[Dict]) -> List[Watchlist]
    批量添加股票，忽略单条失败并打印错误信息，返回成功添加或更新的对象列表。
batch_update_enabled(symbols: List[str], enabled: bool) -> int
    批量更新一组股票的 enabled 字段，返回受影响行数。
get_stock_statistics() -> Dict[str, Any]
    返回统计信息字典，包括总数、启用/禁用数量、按行业分布、最近 7 天新闻数量等。
_create_news_keywords(stock, session)
    内部方法。为单只股票生成若干关键词（代码、公司名、简化公司名、行业）并写入 NewsKeyword。
    需要传入已打开的 Session；不会创建重复关键词。
create_news_collection_task(symbol) -> Optional[int]
    为指定股票创建新闻抓取任务（TaskType.FETCH_NEWS），若已有待处理/运行中的相同任务则返回该任务 ID，
    否则新建并返回新任务 ID。
异常与错误处理
----------------
- 无效股票代码会在 add_stock 中通过 ValueError 抛出。
- 数据库层面的错误（如约束违例、连接失败等）会沿链上抛出，调用方应在上层捕获处理。
- batch_add_stocks 会捕获并打印单条添加失败的异常，但不会回滚已成功的条目。
并发与事务
------------
- 所有公开方法均为 async 定义，但内部使用同步 SQLAlchemy Session（通过 SessionLocal() 获取）。
  因此在真正的异步服务器中使用时，建议将这些方法放到线程池（如 asyncio.to_thread）或确保
  使用的数据库驱动/Session 实例支持并发调用。
- 每个操作方法在内部新建并关闭 Session，方法内对数据库的多次修改通过显式 session.commit() 提交，
  保证事务性的基本边界，但复杂多步操作若需原子性应在外部显式扩展事务管理。
使用示例（概念性）
-------------------
manager = StockListManager()
await manager.add_stock("000001", name="示例公司", sector="金融")
stocks = await manager.list_stocks(enabled_only=True, limit=100)
注意事项
--------
- 假定模块中引用的模型（Watchlist, NewsKeyword, NewsArticle, Task, TaskType, TaskStatus）
  与数据库映射定义正确且已导入。
- 假定 get_stock_info 提供同步的股票信息校验接口；若改为异步实现需相应调整调用方式。
- _create_news_keywords 为内部方法并依赖于传入的 session；外部调用请确保 session 的生命周期。
- 方法返回的 ORM 实例为绑定到被创建的 session；在 session 关闭后访问延迟加载字段可能引发错误，
  因此建议在返回数据前将必要字段读取或转换为纯数据结构（如 dict）供外部使用。

"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import select, func, and_, or_, delete

from ..core.models import (
    Watchlist, NewsKeyword, NewsArticle, Task, TaskType, TaskStatus
)
from ..core.db import get_session, SessionLocal
from ..data.data_source import get_stock_info, normalize_symbol
from ..core.models import StockProfile

# 获取日志记录器
logger = logging.getLogger(__name__)


class StockListManager:
    """监控股票列表管理器"""
    
    def __init__(self):
        self.session_factory = SessionLocal
    
    async def add_stock(self, symbol: str, name: str = None, sector: str = None, enabled: bool = True) -> Watchlist:
        """
        添加股票到监控列表
        """
        # 归一化并验证股票代码有效性
        symbol = normalize_symbol(symbol)
        stock_info = get_stock_info(symbol)
        if not stock_info:
            raise ValueError(f"Invalid stock symbol: {symbol}")
        
        # 如果没有提供名称，使用从股票信息中获取的名称
        if not name:
            name = stock_info.get('name', '')
        if not sector:
            sector = stock_info.get('sector', '')
        
        session = self.session_factory()
        try:
            # 检查是否已存在
            existing = session.execute(
                select(Watchlist).where(Watchlist.symbol == symbol)
            ).scalar_one_or_none()
            
            if existing:
                # 更新现有记录
                existing.name = name
                existing.sector = sector
                existing.enabled = enabled
                session.commit()
                session.refresh(existing)
                
                # 创建新闻关键词
                await self._create_news_keywords(existing, session)
                
                return existing
            else:
                # 创建新记录
                watchlist_item = Watchlist(
                    symbol=symbol,
                    name=name,
                    sector=sector,
                    enabled=enabled
                )
                session.add(watchlist_item)
                session.commit()
                session.refresh(watchlist_item)
                
                # 创建新闻关键词
                await self._create_news_keywords(watchlist_item, session)
                
                return watchlist_item
                
        finally:
            session.close()
    
    async def remove_stock(self, symbol: str) -> bool:
        """
        从监控列表中移除股票
        """
        session = self.session_factory()
        try:
            # 删除相关的新闻关键词
            session.execute(
                delete(NewsKeyword).where(NewsKeyword.related_symbol == symbol)
            )
            
            # 删除监控记录
            result = session.execute(
                delete(Watchlist).where(Watchlist.symbol == symbol)
            )
            
            session.commit()
            return result.rowcount > 0
            
        finally:
            session.close()
    
    async def update_stock(self, symbol: str, **kwargs) -> Optional[Watchlist]:
        """
        更新股票信息
        """
        session = self.session_factory()
        try:
            stock = session.execute(
                select(Watchlist).where(Watchlist.symbol == symbol)
            ).scalar_one_or_none()
            
            if not stock:
                return None
            
            # 更新字段
            for key, value in kwargs.items():
                if hasattr(stock, key):
                    setattr(stock, key, value)
            
            session.commit()
            session.refresh(stock)
            
            return stock
            
        finally:
            session.close()
    
    async def enable_stock(self, symbol: str) -> bool:
        """
        启用股票监控
        """
        return await self.update_stock(symbol, enabled=True) is not None
    
    async def disable_stock(self, symbol: str) -> bool:
        """
        禁用股票监控
        """
        return await self.update_stock(symbol, enabled=False) is not None
    
    async def get_stock(self, symbol: str) -> Optional[Watchlist]:
        """
        获取单只股票信息
        """
        session = self.session_factory()
        try:
            return session.execute(
                select(Watchlist).where(Watchlist.symbol == symbol)
            ).scalar_one_or_none()
        finally:
            session.close()
    
    async def list_stocks(
        self, 
        enabled_only: bool = False, 
        sector: str = None,
        limit: int = None,
        offset: int = 0
    ) -> List[Watchlist]:
        """
        获取股票列表
        """
        session = self.session_factory()
        try:
            query = select(Watchlist)
            
            if enabled_only:
                query = query.where(Watchlist.enabled == True)
            
            if sector:
                query = query.where(Watchlist.sector == sector)
            
            query = query.offset(offset)
            if limit:
                query = query.limit(limit)
            
            return session.execute(query).scalars().all()
            
        finally:
            session.close()
    
    async def get_stock_count(self, enabled_only: bool = False) -> int:
        """
        获取股票数量
        """
        session = self.session_factory()
        try:
            query = select(func.count(Watchlist.id))
            
            if enabled_only:
                query = query.where(Watchlist.enabled == True)
            
            return session.execute(query).scalar()
            
        finally:
            session.close()
    
    async def get_sectors(self) -> List[str]:
        """
        获取所有行业分类
        """
        session = self.session_factory()
        try:
            result = session.execute(
                select(Watchlist.sector).distinct().where(Watchlist.sector.isnot(None))
            ).scalars().all()
            
            return [sector for sector in result if sector]
            
        finally:
            session.close()
    
    async def batch_add_stocks(self, stocks: List[Dict[str, Any]]) -> List[Watchlist]:
        """
        批量添加股票
        """
        results = []
        for stock_data in stocks:
            try:
                result = await self.add_stock(**stock_data)
                results.append(result)
            except Exception as e:
                print(f"Failed to add stock {stock_data.get('symbol', 'unknown')}: {e}")
        
        return results
    
    async def batch_update_enabled(self, symbols: List[str], enabled: bool) -> int:
        """
        批量更新启用状态
        """
        session = self.session_factory()
        try:
            result = session.execute(
                Watchlist.__table__.update()
                .where(Watchlist.symbol.in_(symbols))
                .values(enabled=enabled)
            )
            
            session.commit()
            return result.rowcount
            
        finally:
            session.close()
    
    async def get_stock_statistics(self) -> Dict[str, Any]:
        """
        获取股票监控统计信息
        """
        session = self.session_factory()
        try:
            total_stocks = session.execute(select(func.count(Watchlist.id))).scalar()
            enabled_stocks = session.execute(
                select(func.count(Watchlist.id)).where(Watchlist.enabled == True)
            ).scalar()
            
            # 按行业统计
            sector_stats = session.execute(
                select(Watchlist.sector, func.count(Watchlist.id))
                .where(Watchlist.sector.isnot(None))
                .group_by(Watchlist.sector)
            ).all()
            
            # 最近新闻统计
            recent_news_count = session.execute(
                select(func.count(NewsArticle.id))
                .where(NewsArticle.crawled_at >= datetime.utcnow() - timedelta(days=7))
            ).scalar()
            
            return {
                "total_stocks": total_stocks,
                "enabled_stocks": enabled_stocks,
                "disabled_stocks": total_stocks - enabled_stocks,
                "sector_distribution": dict(sector_stats),
                "recent_news_count": recent_news_count,
                "last_updated": datetime.utcnow().isoformat()
            }
            
        finally:
            session.close()
    
    async def _create_news_keywords(self, stock: Watchlist, session: Session):
        """
        为股票创建新闻关键词
        """
        keywords_to_create = []
        
        # 股票代码关键词
        keywords_to_create.append({
            "keyword": stock.symbol,
            "keyword_type": "stock_symbol",
            "related_symbol": stock.symbol,
            "search_priority": 10  # 最高优先级
        })
        
        # 公司名称关键词
        if stock.name:
            keywords_to_create.append({
                "keyword": stock.name,
                "keyword_type": "company_name", 
                "related_symbol": stock.symbol,
                "search_priority": 9
            })
            
            # 如果公司名称包含"股份"、"有限公司"等，也创建简化版本
            simplified_name = stock.name
            for suffix in ["股份有限公司", "有限公司", "股份公司", "集团", "控股"]:
                simplified_name = simplified_name.replace(suffix, "")
            
            if simplified_name != stock.name and len(simplified_name) >= 2:
                keywords_to_create.append({
                    "keyword": simplified_name,
                    "keyword_type": "company_name",
                    "related_symbol": stock.symbol,
                    "search_priority": 8
                })
        
        # 行业关键词
        if stock.sector:
            keywords_to_create.append({
                "keyword": stock.sector,
                "keyword_type": "industry",
                "related_symbol": stock.symbol,
                "search_priority": 5
            })
        
        # 批量创建关键词
        for keyword_data in keywords_to_create:
            existing = session.execute(
                select(NewsKeyword).where(
                    and_(
                        NewsKeyword.keyword == keyword_data["keyword"],
                        NewsKeyword.related_symbol == keyword_data["related_symbol"]
                    )
                )
            ).scalar_one_or_none()
            
            if not existing:
                keyword = NewsKeyword(**keyword_data)
                session.add(keyword)
        
        session.commit()
    
    async def create_news_collection_task(self, symbol: str) -> Optional[int]:
        """
        为特定股票创建新闻收集任务
        """
        session = self.session_factory()
        try:
            # 检查是否已有待处理的任务
            existing_task = session.execute(
                select(Task).where(
                    and_(
                        Task.symbol == symbol,
                        Task.task_type == TaskType.FETCH_NEWS,
                        Task.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING])
                    )
                )
            ).scalar_one_or_none()
            
            if existing_task:
                return existing_task.id
            
            # 创建新任务
            task = Task(
                symbol=symbol,
                task_type=TaskType.FETCH_NEWS,
                status=TaskStatus.PENDING,
                priority=5,
                task_metadata=f'{{"symbol": "{symbol}", "created_by": "stock_manager"}}'
            )
            
            session.add(task)
            session.commit()
            session.refresh(task)
            
            # ✅ 新增：确保存在对应的 StockProfile 且带 company_name
            try:
                prof = session.query(StockProfile).filter(StockProfile.symbol == symbol).first()
                if not prof:
                    # 获取股票信息来填充 company_name
                    stock_info = get_stock_info(symbol)
                    company_name = stock_info.get('name', '') if stock_info else ''
                    
                    prof = StockProfile(
                        symbol=symbol, 
                        company_name=company_name or symbol,
                        market=stock_info.get('market', 'A股') if stock_info else 'A股'
                    )
                    session.add(prof)
                    session.commit()
                    logger.info(f"✅ 创建 StockProfile: {symbol} -> {company_name}")
                    
                elif not prof.company_name or prof.company_name == symbol:
                    # 如果 company_name 为空或为符号，尝试更新
                    stock_info = get_stock_info(symbol)
                    if stock_info:
                        company_name = stock_info.get('name', '')
                        if company_name:
                            prof.company_name = company_name
                            prof.updated_at = datetime.utcnow()
                            session.add(prof)
                            session.commit()
                            logger.info(f"✅ 更新 StockProfile company_name: {symbol} -> {company_name}")
                    else:
                        logger.warning(f"⚠️ 无法获取 {symbol} 的股票信息")
            except Exception as e:
                logger.warning(f"⚠️ 更新 StockProfile 失败 ({symbol}): {e}")
                # 不中断主流程，仅记录警告
            
            return task.id
            
        finally:
            session.close()