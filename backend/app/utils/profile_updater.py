"""
Stock Profile 自动更新任务

定时扫描所有未完成Profile的股票，使用LLM自动生成和更新Profile数据
"""

import logging
import asyncio
from datetime import datetime
from typing import Optional, List
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from ..core.models import StockProfile, Watchlist, NewsArticle
from .database import SessionLocal
from ..news.llm_processor import LLMNewsProcessor

logger = logging.getLogger(__name__)


class ProfileUpdater:
    """Stock Profile 自动更新器"""
    
    def __init__(self):
        self.profile_fields = [
            'industry', 'business_summary', 'core_products', 'competitive_position',
            'competitors', 'strategic_keywords', 'risk_factors', 'history_highlights', 'profile_json'
        ]
        self.total_fields = len(self.profile_fields)
        self.completion_threshold = 0.5  # 50% 为已完成
        
    async def get_incomplete_profiles(self, db: Session, limit: int = 10) -> List[tuple]:
        """获取未完成的Profile股票列表 (按完成度升序，优先完成最急需的)
        
        从所有有资讯的股票中获取，而非仅限 Watchlist
        返回: [(symbol, name, completion_pct, profile), ...]
        """
        try:
            # 第一步：从 NewsArticle 中提取所有股票符号
            all_articles = db.query(NewsArticle.related_stocks).filter(
                NewsArticle.related_stocks.isnot(None)
            ).all()
            
            all_symbols = set()
            for row in all_articles:
                if row[0] and isinstance(row[0], list):
                    all_symbols.update(row[0])
            
            all_symbols_list = sorted(list(all_symbols))
            logger.info(f"📊 从资讯中找到 {len(all_symbols_list)} 个不同的股票")
            
            incomplete_stocks = []
            
            # 第二步：计算每个股票的完成度
            for symbol in all_symbols_list:
                profile = db.query(StockProfile).filter(
                    StockProfile.symbol == symbol
                ).first()
                
                # 计算完成度（排除占位文本）
                filled_count = 0
                if profile:
                    from ..services.stock_pool_service import _is_meaningful_field
                    for field in self.profile_fields:
                        value = getattr(profile, field, None)
                        if _is_meaningful_field(field, value):
                            filled_count += 1
                
                completion_pct = (filled_count / self.total_fields)
                
                # 找出未完成的 (< 50%)
                if completion_pct < self.completion_threshold:
                    # 尝试获取股票名称
                    stock_name = symbol
                    if profile and profile.company_name:
                        stock_name = profile.company_name
                    else:
                        watchlist = db.query(Watchlist).filter(
                            Watchlist.symbol == symbol
                        ).first()
                        if watchlist:
                            stock_name = watchlist.name or symbol
                    
                    incomplete_stocks.append((
                        symbol,
                        stock_name,
                        completion_pct,
                        profile  # 返回profile对象
                    ))
            
            # 按完成度升序排列（最不完整的优先）
            incomplete_stocks.sort(key=lambda x: x[2])
            
            logger.info(f"🎯 需要更新的 Profile: {len(incomplete_stocks)} 个")
            return incomplete_stocks[:limit]
            
        except Exception as e:
            logger.error(f"❌ 获取未完成Profile失败: {e}")
            return []
    
    async def get_stock_articles_for_context(self, db: Session, symbol: str, limit: int = 3) -> str:
        """获取该股票的最新文章摘要作为LLM的上下文"""
        try:
            articles = db.query(NewsArticle).filter(
                NewsArticle.related_stocks.contains([symbol])
            ).order_by(
                NewsArticle.published_at.desc()
            ).limit(limit).all()
            
            if not articles:
                return ""
            
            context = "最近资讯摘要:\n"
            for i, article in enumerate(articles, 1):
                context += f"{i}. [{article.published_at.strftime('%Y-%m-%d')}] {article.title}\n"
                if article.summary:
                    context += f"   摘要: {article.summary[:100]}...\n"
            
            return context
            
        except Exception as e:
            logger.warning(f"⚠️ 获取文章上下文失败: {e}")
            return ""
    
    async def update_single_profile(self, db: Session, symbol: str, company_name: str) -> bool:
        """使用LLM为单个股票更新Profile
        
        返回: 是否成功更新
        """
        try:
            logger.info(f"🔄 开始更新 Profile: {symbol} ({company_name})")
            
            # 获取该股票的文章上下文
            article_context = await self.get_stock_articles_for_context(db, symbol)
            
            # 查询或创建Profile记录
            profile = db.query(StockProfile).filter(
                StockProfile.symbol == symbol
            ).first()
            
            if not profile:
                profile = StockProfile(symbol=symbol, company_name=company_name)
                db.add(profile)
                db.flush()
            
            # 调用LLM生成Profile数据
            logger.info(f"📝 调用LLM生成 {symbol} 的Profile数据...")
            
            async with LLMNewsProcessor() as llm:
                # 构建提示词
                prompt = f"""
请为以下上市公司生成完整的Profile数据（JSON格式）：

公司代码: {symbol}
公司名称: {company_name}

{article_context}

请生成包含以下字段的JSON:
{{
    "industry": "所属行业（如：汽车制造业-新能源车）",
    "business_summary": "业务概述（100-200字）",
    "core_products": "核心产品/服务",
    "competitive_position": "竞争地位（市场份额、行业排名等）",
    "competitors": "主要竞争对手",
    "strategic_keywords": "战略关键词（逗号分隔）",
    "risk_factors": "主要风险因素",
    "history_highlights": "企业历程亮点"
}}

要求：
1. 数据应基于客观事实
2. 如果信息不确定，请说明
3. 返回有效的JSON格式
"""
                
                # 调用LLM（使用 analyze_news 的类似逻辑，但改为生成profile）
                try:
                    # 这里简化实现，使用文本补全
                    response = await llm.client.chat.completions.create(
                        model=llm.model,
                        messages=[
                            {"role": "system", "content": "You are a financial analyst. Generate accurate company profile data in JSON format."},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.3,
                        max_tokens=1000
                    )
                    
                    content = response.choices[0].message.content
                    
                    # 解析JSON
                    import json
                    import re
                    
                    # 尝试提取JSON
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        data = json.loads(json_match.group())
                        
                        # 更新Profile字段
                        profile.industry = data.get("industry", "")
                        profile.business_summary = data.get("business_summary", "")
                        profile.core_products = data.get("core_products", "")
                        profile.competitive_position = data.get("competitive_position", "")
                        profile.competitors = data.get("competitors", "")
                        profile.strategic_keywords = data.get("strategic_keywords", "")
                        profile.risk_factors = data.get("risk_factors", "")
                        profile.history_highlights = data.get("history_highlights", "")
                        profile.profile_json = data  # 保存完整JSON
                        profile.last_refreshed = datetime.utcnow()
                        
                        db.commit()
                        
                        # 计算新的完成度
                        filled_count = sum(1 for field in self.profile_fields 
                                         if getattr(profile, field, None) and 
                                         (isinstance(getattr(profile, field), str) and 
                                          getattr(profile, field).strip() or 
                                          isinstance(getattr(profile, field), dict)))
                        completion_pct = (filled_count / self.total_fields) * 100
                        
                        logger.info(f"✅ 成功更新 {symbol} Profile，完成度：{completion_pct:.1f}%")
                        return True
                    else:
                        logger.warning(f"⚠️ LLM返回的内容中未找到JSON: {content[:100]}")
                        return False
                        
                except Exception as e:
                    logger.error(f"❌ LLM调用失败: {e}")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ 更新 {symbol} Profile失败: {e}")
            return False
    
    async def run_batch_update(self, batch_size: int = 3, wait_between_updates: float = 5.0):
        """批量更新未完成的Profile
        
        参数:
            batch_size: 每批更新的股票数
            wait_between_updates: 更新之间的等待时间（秒），防止请求过快
        """
        db = SessionLocal()
        try:
            logger.info(f"🚀 开始 Profile 批量更新，批次大小：{batch_size}")
            
            # 获取未完成的Profile列表
            incomplete = await self.get_incomplete_profiles(db, limit=batch_size)
            
            if not incomplete:
                logger.info("✅ 所有股票Profile都已完成！")
                return {
                    "status": "success",
                    "message": "所有股票Profile都已完成",
                    "updated_count": 0,
                    "updated_stocks": []
                }
            
            logger.info(f"📊 发现 {len(incomplete)} 个未完成的Profile")
            
            updated_stocks = []
            success_count = 0
            
            for symbol, name, completion_pct, profile in incomplete:
                try:
                    logger.info(f"\n处理中... [{symbol}] {name} (当前完成度: {completion_pct*100:.1f}%)")
                    
                    success = await self.update_single_profile(db, symbol, name)
                    
                    if success:
                        success_count += 1
                        updated_stocks.append({
                            "symbol": symbol,
                            "name": name,
                            "previous_completion": f"{completion_pct*100:.1f}%"
                        })
                    
                    # 等待一段时间后再请求下一个
                    if symbol != incomplete[-1][0]:  # 不是最后一个
                        logger.info(f"⏳ 等待 {wait_between_updates}s 后继续...")
                        await asyncio.sleep(wait_between_updates)
                        
                except Exception as e:
                    logger.error(f"❌ 处理 {symbol} 时出错: {e}")
                    continue
            
            logger.info(f"\n✅ 批量更新完成！成功更新 {success_count}/{len(incomplete)} 个股票")
            
            return {
                "status": "success",
                "message": f"已更新 {success_count} 个股票Profile",
                "updated_count": success_count,
                "updated_stocks": updated_stocks,
                "total_processed": len(incomplete)
            }
            
        except Exception as e:
            logger.error(f"❌ 批量更新失败: {e}")
            return {
                "status": "error",
                "message": str(e),
                "updated_count": 0
            }
        finally:
            db.close()


# 全局实例
profile_updater = ProfileUpdater()


async def run_profile_update_task(batch_size: int = 3):
    """后端定时任务 - 运行Profile更新
    
    可从任务调度器定期调用（如每小时一次）
    """
    return await profile_updater.run_batch_update(batch_size=batch_size)
