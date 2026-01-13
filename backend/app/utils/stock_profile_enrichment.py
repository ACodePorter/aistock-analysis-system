"""
股票画像数据富化模块

用途：
- 通过 SearXNG 搜索获取公司相关新闻/信息
- 使用 LLM 对信息进行分析和结构化
- 生成企业画像数据存入 StockProfile 表

依赖：
- NewsSearchService: 搜索引擎集成
- LLMNewsProcessor: LLM 分析
- StockProfile 模型
"""

import json
import logging
import os
import asyncio
import atexit
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from ..core.models import StockProfile
from ..news.news_service import NewsSearchService
from ..news.llm_processor import LLMNewsProcessor


logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=2)


def _cleanup_executor():
    """应用关闭时清理executor"""
    global _executor
    try:
        if _executor is not None and not _executor._shutdown:
            logger.info("Shutting down ThreadPoolExecutor...")
            _executor.shutdown(wait=True)
    except Exception as e:
        logger.warning(f"Error during executor cleanup: {e}")


# 注册应用退出时的清理函数
atexit.register(_cleanup_executor)


class StockProfileEnricher:
    """股票画像富化器"""
    
    def __init__(self):
        self.news_service = NewsSearchService()
        self.llm_processor_instance = None
        # 缓存 LLM 提示词
        self._profile_prompt_template = """
你是专业的财经分析师。基于以下关于公司 {company_name} ({symbol}) 的新闻和信息，生成结构化的企业画像分析。

【公司基本信息】
- 名称: {company_name}
- 代码: {symbol}

【相关新闻摘要】
{news_summary}

请按以下 JSON 格式返回分析结果：
{{
    "industry": "所属行业",
    "sub_industry": "细分行业",
    "business_summary": "业务概述（200字以内）",
    "core_products": "核心产品或服务，逗号分隔",
    "competitive_position": "市场地位或竞争优势",
    "competitors": "主要竞争对手，逗号分隔",
    "risk_factors": "主要风险因素，逗号分隔",
    "strategic_keywords": "战略关键词，逗号分隔",
    "market_position": "市场表现评价"
}}

要求：
- 基于提供的新闻信息进行分析，避免编造
- 如果某个字段信息不足，可用"暂无"或"待补充"
- 确保输出为有效 JSON 格式
"""
    
    def enrich_stock_profile_sync(
        self,
        symbol: str,
        company_name: str,
        db: Session,
        force_refresh: bool = False
    ) -> Optional[StockProfile]:
        """
        同步包装器：在单独线程中执行异步的 enrich_stock_profile
        
        这是为了支持在非异步环境（如任务调度器）中调用异步方法
        """
        global _executor
        
        try:
            # 检查executor是否已关闭，如果关闭则重新创建
            if _executor._shutdown:
                logger.warning(f"Executor was shutdown, creating a new one for {symbol}")
                _executor = ThreadPoolExecutor(max_workers=2)
            
            # 使用 ThreadPoolExecutor 在单独线程中运行 asyncio
            def run_async():
                return asyncio.run(
                    self.enrich_stock_profile(
                        symbol=symbol,
                        company_name=company_name,
                        db=db,
                        force_refresh=force_refresh
                    )
                )
            
            # 在 executor 中运行并等待完成
            future = _executor.submit(run_async)
            result = future.result(timeout=60)  # 60 秒超时
            return result
        except Exception as e:
            logger.error(f"Error in sync wrapper for {symbol}: {e}", exc_info=True)
            return None
    
    async def get_llm_processor(self) -> LLMNewsProcessor:
        """获取 LLM 处理器实例"""
        if self.llm_processor_instance is None:
            self.llm_processor_instance = LLMNewsProcessor()
        return self.llm_processor_instance
    
    async def search_company_news(self, symbol: str, company_name: str, max_results: int = 10) -> str:
        """
        通过 SearXNG 搜索公司相关新闻
        
        Args:
            symbol: 股票代码
            company_name: 公司名称
            max_results: 最大结果数
        
        Returns:
            新闻摘要文本
        """
        try:
            # 构造搜索查询
            query = f"{company_name} {symbol}"
            
            # 调用 SearXNG 搜索
            results = await self.news_service.search_news(
                query=query,
                category="news",
                time_range="month",  # 最近一个月
                max_results=max_results
            )
            
            if not results:
                logger.warning(f"No news found for {company_name} ({symbol})")
                return "未找到相关新闻"
            
            # 提取并组织新闻内容
            news_items = []
            for idx, result in enumerate(results[:5], 1):  # 只取前 5 条
                title = result.get("title", "")
                summary = result.get("content", "")[:200]  # 限制长度
                
                news_items.append(f"{idx}. [{title}] {summary}")
            
            return "\n".join(news_items)
        
        except Exception as e:
            logger.error(f"Failed to search news for {symbol}: {e}")
            return "搜索新闻失败"
    
    async def enrich_profile_with_llm(
        self,
        symbol: str,
        company_name: str,
        news_summary: str
    ) -> Optional[Dict[str, Any]]:
        """
        使用 LLM 分析新闻并生成企业画像
        
        Args:
            symbol: 股票代码
            company_name: 公司名称
            news_summary: 新闻摘要
        
        Returns:
            结构化的企业画像数据
        """
        try:
            llm = await self.get_llm_processor()
            
            # 构造提示词
            prompt = self._profile_prompt_template.format(
                company_name=company_name,
                symbol=symbol,
                news_summary=news_summary
            )
            
            # 调用 LLM（使用项目现有的 Azure OpenAI Responses API）
            if llm.llm_service == "azure":
                response = await llm._call_azure_openai_responses(prompt)
            elif llm.llm_service == "local":
                response = await llm._call_local_llm(prompt)
            else:
                logger.warning("No LLM service available")
                return None
            
            if not response:
                logger.warning(f"LLM returned empty response for {symbol}")
                return None
            
            # 解析 JSON 响应
            analysis = llm._parse_llm_response(response)
            return analysis
        
        except Exception as e:
            logger.error(f"Failed to analyze profile for {symbol}: {e}")
            return None
    
    async def enrich_stock_profile(
        self,
        symbol: str,
        company_name: str,
        db: Session,
        force_refresh: bool = False
    ) -> Optional[StockProfile]:
        """
        富化单只股票的画像数据
        
        Args:
            symbol: 股票代码
            company_name: 公司名称
            db: 数据库 Session
            force_refresh: 是否强制刷新（忽略缓存）
        
        Returns:
            更新后的 StockProfile 对象
        """
        try:
            # 检查是否已有有效缓存
            profile = db.query(StockProfile).filter_by(symbol=symbol).first()
            
            if profile and profile.business_summary and not force_refresh:
                # 检查是否在 24 小时内已刷新
                if profile.last_refreshed:
                    age = datetime.utcnow() - profile.last_refreshed
                    if age < timedelta(hours=24):
                        logger.info(f"Profile for {symbol} is fresh (age: {age})")
                        return profile
            
            logger.info(f"Enriching profile for {symbol} ({company_name})...")
            
            # 第一步：搜索相关新闻
            news_summary = await self.search_company_news(symbol, company_name)
            
            # 第二步：使用 LLM 分析
            analysis = await self.enrich_profile_with_llm(symbol, company_name, news_summary)
            
            # 第三步：存入数据库
            if not profile:
                profile = StockProfile(symbol=symbol, company_name=company_name)
            
            if analysis:
                # 更新各字段
                profile.company_name = company_name
                profile.industry = analysis.get("industry")
                profile.sub_industry = analysis.get("sub_industry")
                profile.business_summary = analysis.get("business_summary")
                profile.core_products = analysis.get("core_products")
                profile.competitive_position = analysis.get("competitive_position")
                profile.competitors = analysis.get("competitors")
                profile.risk_factors = analysis.get("risk_factors")
                profile.strategic_keywords = analysis.get("strategic_keywords")
                profile.profile_json = json.dumps(analysis, ensure_ascii=False)
            else:
                # LLM 失败时，至少保存公司名称和搜索结果摘要
                profile.company_name = company_name
                profile.business_summary = f"(未获得LLM分析) 相关新闻: {news_summary[:200]}"
            
            profile.last_refreshed = datetime.utcnow()
            profile.updated_at = datetime.utcnow()
            
            db.add(profile)
            db.commit()
            db.refresh(profile)
            
            logger.info(f"Successfully enriched profile for {symbol}")
            return profile
        
        except Exception as e:
            db.rollback()
            logger.error(f"Error enriching profile for {symbol}: {e}")
            return None
