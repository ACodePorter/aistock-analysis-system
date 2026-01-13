
"""
模块说明: news_strategy.py

概述:
    本模块提供基于关注股票和行业的智能新闻收集与调度能力。
    主要功能包括自动生成搜索策略、按策略调用新闻搜索与正文抽取、去重入库及记录执行日志，
    并支持将收集任务注册为后台任务。

主要类:
    - NewsStrategy:
        描述单个搜索策略的元信息（名称、关键词集合、频率、优先级、分类及搜索参数）。
    - IntelligentNewsCollector:
        智能收集器。负责从关注列表生成多种类型的策略（个股/行业/政策/市场），
        执行策略（搜索 -> 处理 -> 去重 -> 入库），以及记录执行日志和节流控制。
    - NewsStrategyScheduler:
        调度器。用于批量运行智能收集流程并将任务写入任务表（Task），可作为外部调度入口。

关键异步接口:
    - IntelligentNewsCollector.generate_strategies() -> List[NewsStrategy]
        根据 Watchlist 动态生成策略集合。
    - IntelligentNewsCollector.execute_strategy(strategy) -> Dict
        执行单条策略并返回执行结果统计。
    - NewsStrategyScheduler.run_intelligent_collection() -> Dict
        运行全部智能策略并返回汇总结果。
    - NewsStrategyScheduler.create_news_collection_task(priority=int) -> int
        在数据库中创建一个新闻收集任务记录并返回 task.id（同步 DB 写入）。

依赖项:
    - 外部服务: NewsSearchService（负责搜索）、NewsProcessor（负责正文抽取与结果标准化）。
    - 数据模型: Watchlist, NewsArticle, SearchLog, Task, TaskType, TaskStatus 等（通过本项目的 models 提供）。
    - 数据库会话: SessionLocal（用于短生命周期会话）。

可扩展点:
    - industry_keywords / policy_keywords 可按需扩充以覆盖更多行业与主题。
    - _build_search_query 可接入更复杂的查询构造器（例如多关键字组合、布尔搜索）。
    - 搜索与处理逻辑可替换为外部队列/分布式任务以提升吞吐。

示例:
    作为异步任务入口可调用:
        scheduler = NewsStrategyScheduler()
        await scheduler.run_intelligent_collection()

注意事项:
    - 所有与 DB 的交互使用短生命周期 SessionLocal，异步函数内部仍使用同步 DB 驱动；
      在高并发场景下建议改造为异步 DB 驱动或外部队列化处理。
    - 搜索频率与关键词截取限制用于控制第三方检索接口的调用配额，应根据实际 API 限制调整。
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, func, and_, or_

from ..core.models import (
    Watchlist, NewsKeyword, NewsArticle, SearchLog, 
    NewsCategory, TaskType, Task, TaskStatus
)
from ..core.db import get_session, SessionLocal
from ..news.news_service import NewsSearchService, NewsProcessor


class NewsStrategy:
    """新闻搜索策略定义（仅描述策略元信息，如频率/优先级/关键词集合）"""
    
    def __init__(
        self,
        name: str,
        keywords: List[str],
        search_frequency: int = 6,  # 小时
        priority: int = 5,
        category: str = "finance",
        search_params: Dict[str, Any] = None
    ):
        self.name = name
        self.keywords = keywords
        self.search_frequency = search_frequency
        self.priority = priority
        self.category = category
        self.search_params = search_params or {}


class IntelligentNewsCollector:
    """智能新闻收集器：根据策略批量搜索→正文抽取→去重→入库。"""
    
    def __init__(self):
        self.search_service = NewsSearchService()
        self.processor = NewsProcessor()
        
        # 预定义的行业关键词映射
        self.industry_keywords = {
            "新能源": ["新能源", "电动汽车", "锂电池", "充电桩", "光伏", "风能", "储能"],
            "医药": ["医药", "生物医药", "疫苗", "创新药", "医疗器械", "CRO"],
            "科技": ["芯片", "半导体", "人工智能", "云计算", "5G", "物联网"],
            "金融": ["银行", "保险", "证券", "基金", "金融科技", "数字货币"],
            "消费": ["白酒", "食品饮料", "零售", "电商", "品牌消费"],
            "制造": ["机械", "汽车", "家电", "建材", "化工", "钢铁"],
            "房地产": ["房地产", "物业管理", "建筑", "装修", "城市更新"],
            "能源": ["石油", "天然气", "煤炭", "新能源", "电力"]
        }
        
        # 政策关键词
        self.policy_keywords = [
            "央行", "货币政策", "财政政策", "降准", "降息", "监管",
            "国务院", "发改委", "工信部", "证监会", "银保监会",
            "十四五", "碳中和", "双碳", "数字经济", "内循环"
        ]
    
    async def generate_strategies(self) -> List[NewsStrategy]:
        """
        基于当前关注股票自动生成新闻搜索策略
        """
        strategies = []
        
        with SessionLocal() as session:
            # 获取所有启用的股票
            watchlist = session.execute(
                select(Watchlist).where(Watchlist.enabled == True)
            ).scalars().all()
            
            if not watchlist:
                return strategies
            
            # 1. 为每只股票生成个股策略
            for stock in watchlist:
                stock_strategy = await self._create_stock_strategy(stock)
                if stock_strategy:
                    strategies.append(stock_strategy)
            
            # 2. 生成行业策略
            industries = self._extract_industries(watchlist)
            for industry in industries:
                industry_strategy = self._create_industry_strategy(industry)
                if industry_strategy:
                    strategies.append(industry_strategy)
            
            # 3. 生成政策策略
            policy_strategy = self._create_policy_strategy()
            strategies.append(policy_strategy)
            
            # 4. 生成市场整体策略
            market_strategy = self._create_market_strategy()
            strategies.append(market_strategy)
        
        return strategies
    
    async def _create_stock_strategy(self, stock: Watchlist) -> Optional[NewsStrategy]:
        """为单只股票创建搜索策略"""
        keywords = [stock.symbol]
        
        # 添加公司名称
        if stock.name:
            keywords.append(stock.name)
            # 简化公司名称（去掉"股份有限公司"等后缀）
            simplified_name = stock.name.replace("股份有限公司", "").replace("有限公司", "").replace("集团", "")
            if simplified_name != stock.name:
                keywords.append(simplified_name)
        
        # 添加行业相关词
        if stock.sector:
            keywords.extend(self.industry_keywords.get(stock.sector, []))
        
        return NewsStrategy(
            name=f"个股-{stock.symbol}",
            keywords=keywords,
            search_frequency=4,  # 每4小时
            priority=8,  # 高优先级
            category="company",
            search_params={
                "time_range": "day",
                "max_results": 15,
                "related_symbol": stock.symbol
            }
        )
    
    def _extract_industries(self, watchlist: List[Watchlist]) -> List[str]:
        """从关注列表中提取行业"""
        industries = set()
        for stock in watchlist:
            if stock.sector and stock.sector in self.industry_keywords:
                industries.add(stock.sector)
        return list(industries)
    
    def _create_industry_strategy(self, industry: str) -> Optional[NewsStrategy]:
        """为行业创建搜索策略"""
        keywords = self.industry_keywords.get(industry, [])
        if not keywords:
            return None
        
        # 添加行业政策相关词
        policy_words = ["政策", "规划", "支持", "发展", "监管", "标准"]
        extended_keywords = []
        for keyword in keywords[:3]:  # 选择前3个主要关键词
            extended_keywords.append(keyword)
            for policy_word in policy_words:
                extended_keywords.append(f"{keyword} {policy_word}")
        
        return NewsStrategy(
            name=f"行业-{industry}",
            keywords=extended_keywords,
            search_frequency=6,  # 每6小时
            priority=6,
            category="industry",
            search_params={
                "time_range": "week",
                "max_results": 10
            }
        )
    
    def _create_policy_strategy(self) -> NewsStrategy:
        """创建政策新闻策略"""
        return NewsStrategy(
            name="政策导向",
            keywords=self.policy_keywords,
            search_frequency=8,  # 每8小时
            priority=7,
            category="policy",
            search_params={
                "time_range": "week",
                "max_results": 12
            }
        )
    
    def _create_market_strategy(self) -> NewsStrategy:
        """创建市场整体策略"""
        market_keywords = [
            "A股", "上证指数", "深证成指", "创业板", "科创板",
            "股市", "大盘", "市场行情", "资金流向", "北向资金",
            "机构调研", "基金持仓", "券商", "投资策略"
        ]
        
        return NewsStrategy(
            name="市场动态",
            keywords=market_keywords,
            search_frequency=12,  # 每12小时
            priority=5,
            category="market",
            search_params={
                "time_range": "day",
                "max_results": 8
            }
        )
    
    async def execute_strategy(self, strategy: NewsStrategy) -> Dict[str, Any]:
        """执行单个搜索策略"""
        collected_articles = []
        total_results = 0
        
        # 检查上次执行时间
        if not await self._should_execute_strategy(strategy):
            return {
                "strategy": strategy.name,
                "status": "skipped",
                "reason": "frequency_limit",
                "articles_collected": 0
            }
        
        try:
            # 为每个关键词组合执行搜索
            for i, keyword in enumerate(strategy.keywords):
                if i >= 5:  # 为控制外部调用频率，单策略最多取前5个关键词
                    break
                
                try:
                    # 构建搜索查询
                    query = self._build_search_query(keyword, strategy.category)
                    
                    # 执行搜索
                    results = await self.search_service.search_news(
                        query=query,
                        category="news",
                        time_range=strategy.search_params.get("time_range", "week"),
                        max_results=strategy.search_params.get("max_results", 10) // len(strategy.keywords[:5])
                    )
                    
                    # 处理结果
                    if results:
                        articles = await self.processor.process_search_results(
                            results, 
                            strategy.search_params.get("related_symbol")
                        )
                        collected_articles.extend(articles)
                        total_results += len(results)
                    
                    # 避免请求过于频繁
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    print(f"Error searching for keyword '{keyword}': {e}")
                    continue
            
            # 保存文章到数据库
            saved_count = await self._save_articles(collected_articles, strategy)
            
            # 更新策略执行记录
            await self._update_strategy_execution(strategy, True, saved_count)
            
            return {
                "strategy": strategy.name,
                "status": "success",
                "search_results": total_results,
                "articles_collected": saved_count,
                "execution_time": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            await self._update_strategy_execution(strategy, False, 0, str(e))
            return {
                "strategy": strategy.name,
                "status": "error",
                "error": str(e),
                "articles_collected": 0
            }
    
    def _build_search_query(self, keyword: str, category: str) -> str:
        """构建搜索查询"""
        base_query = keyword
        
        # 根据类别添加修饰词
        if category == "company":
            modifiers = ["股票", "公司", "业绩", "财报"]
        elif category == "industry":
            modifiers = ["行业", "发展", "趋势", "政策"]
        elif category == "policy":
            modifiers = ["政策", "监管", "新规"]
        elif category == "market":
            modifiers = ["市场", "行情", "分析"]
        else:
            modifiers = ["财经", "新闻"]
        
        # 随机选择一个修饰词
        import random
        modifier = random.choice(modifiers)
        
        return f"{base_query} {modifier}"
    
    async def _should_execute_strategy(self, strategy: NewsStrategy) -> bool:
        """检查策略是否应该执行"""
        session = SessionLocal()
        try:
            # 查找最近的执行记录
            recent_search = session.execute(
                select(SearchLog).where(
                    and_(
                        SearchLog.query.contains(strategy.name),
                        SearchLog.created_at >= datetime.utcnow() - timedelta(hours=strategy.search_frequency)
                    )
                ).order_by(SearchLog.created_at.desc()).limit(1)
            ).scalar_one_or_none()
            
            return recent_search is None
        finally:
            session.close()
    
    async def _save_articles(self, articles: List[NewsArticle], strategy: NewsStrategy) -> int:
        """保存文章到数据库"""
        saved_count = 0
        
        session = SessionLocal()
        try:
            for article in articles:
                try:
                    # 检查是否已存在
                    existing = session.execute(
                        select(NewsArticle).where(NewsArticle.url == article.url)
                    ).scalar_one_or_none()
                    
                    if not existing:
                        # 添加策略信息到关键词中
                        if not article.keywords:
                            article.keywords = []
                        article.keywords.append(f"strategy:{strategy.name}")
                        
                        session.add(article)
                        saved_count += 1
                        
                except Exception as e:
                    print(f"Error saving article {article.url}: {e}")
                    session.rollback()
                    continue
            
            if saved_count > 0:
                session.commit()
        finally:
            session.close()
        
        return saved_count
    
    async def _update_strategy_execution(
        self, 
        strategy: NewsStrategy, 
        success: bool, 
        results_count: int, 
        error_message: str = None
    ):
        """更新策略执行记录"""
        session = SessionLocal()
        try:
            search_log = SearchLog(
                query=f"Strategy: {strategy.name}",
                query_type="auto_strategy",
                source_engine="searxng",
                results_count=results_count,
                success=success,
                error_message=error_message
            )
            session.add(search_log)
            session.commit()
        finally:
            session.close()


class NewsStrategyScheduler:
    """新闻策略调度器"""
    
    def __init__(self):
        self.collector = IntelligentNewsCollector()
    
    async def run_intelligent_collection(self) -> Dict[str, Any]:
        """运行智能新闻收集"""
        print("🔍 开始智能新闻收集...")
        
        # 生成搜索策略
        strategies = await self.collector.generate_strategies()
        
        if not strategies:
            print("⚠️  没有生成任何搜索策略，请检查关注股票列表")
            return {
                "status": "no_strategies",
                "strategies_executed": 0,
                "total_articles": 0
            }
        
        print(f"📋 生成了 {len(strategies)} 个搜索策略")
        
        # 执行策略
        results = []
        total_articles = 0
        
        for strategy in strategies:
            print(f"🔍 执行策略: {strategy.name}")
            result = await self.collector.execute_strategy(strategy)
            results.append(result)
            
            if result["status"] == "success":
                total_articles += result["articles_collected"]
                print(f"✅ {strategy.name}: 收集了 {result['articles_collected']} 篇文章")
            elif result["status"] == "skipped":
                print(f"⏭️  {strategy.name}: 跳过执行（频率限制）")
            else:
                print(f"❌ {strategy.name}: 执行失败 - {result.get('error', '未知错误')}")
            
            # 策略间隔
            await asyncio.sleep(2)
        
        print(f"🎉 智能新闻收集完成！总共收集了 {total_articles} 篇文章")
        
        return {
            "status": "completed",
            "strategies_executed": len([r for r in results if r["status"] == "success"]),
            "strategies_skipped": len([r for r in results if r["status"] == "skipped"]),
            "strategies_failed": len([r for r in results if r["status"] == "error"]),
            "total_articles": total_articles,
            "strategy_results": results
        }
    
    async def create_news_collection_task(self, priority: int = 5) -> int:
        """创建新闻收集任务"""
        session = SessionLocal()
        try:
            task = Task(
                task_type=TaskType.FETCH_NEWS.value,
                symbol="ALL",  # 表示全局新闻收集
                status=TaskStatus.PENDING.value,
                priority=priority,
                task_metadata=json.dumps({
                    "strategy_type": "intelligent_collection",
                    "auto_generated": True,
                    "timestamp": datetime.utcnow().isoformat()
                })
            )
            session.add(task)
            session.commit()
            session.refresh(task)
            
            return task.id
        finally:
            session.close()
