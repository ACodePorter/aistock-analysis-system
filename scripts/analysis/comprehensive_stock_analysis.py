#!/usr/bin/env python
"""
综合股票分析脚本

功能：
1. 获取过去3个月A股涨跌幅Top20股票
2. 整合新闻、profile、行业信息
3. 用LLM结构化提取信息并量化分析
4. 将有价值的股票加入观察列表
5. 生成综合分析报告

使用方法:
    python -m backend.app.scripts.comprehensive_stock_analysis
    python -m backend.app.scripts.comprehensive_stock_analysis --days 90 --top 20 --auto-add
"""

import os
import sys
import argparse
import logging
import json
from datetime import date, datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict

import akshare as ak
import pandas as pd
from sqlalchemy import select, and_, desc, text, func, or_

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from backend.app.core.db import SessionLocal, engine
from backend.app.core.models import (
    Watchlist, PriceDaily, NewsArticle, StockProfile,
    DailyAnalysis, DailyReport
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# A股交易日历（简化版 - 排除周末）
def is_trading_day(d: date) -> bool:
    """判断是否为A股交易日（简化版：排除周末和已知节假日）"""
    if d.weekday() >= 5:  # 周六周日
        return False
    
    # 已知节假日（可扩展）
    holidays_2026 = {
        date(2026, 1, 1),   # 元旦
        date(2026, 1, 26),  # 春节开始
        date(2026, 1, 27),
        date(2026, 1, 28),
        date(2026, 1, 29),
        date(2026, 1, 30),
        date(2026, 2, 2),
        # ... 可根据需要添加更多
    }
    
    if d in holidays_2026:
        return False
    
    return True


def get_last_trading_day(d: date = None) -> date:
    """获取最近的交易日"""
    if d is None:
        d = date.today()
    while not is_trading_day(d):
        d = d - timedelta(days=1)
    return d


@dataclass
class StockMoverInfo:
    """涨跌幅股票信息"""
    symbol: str
    name: str
    close: float
    pct_chg: float
    volume: int
    amount: float
    market: str  # 沪/深
    sector: Optional[str] = None
    pe: Optional[float] = None
    pb: Optional[float] = None
    market_cap: Optional[float] = None  # 市值（亿）


@dataclass
class ComprehensiveAnalysis:
    """综合分析结果"""
    symbol: str
    name: str
    analysis_date: date
    
    # 价格表现
    price_info: Dict[str, Any]
    
    # 新闻分析
    news_analysis: Dict[str, Any]
    
    # 基本面分析
    fundamental_analysis: Dict[str, Any]
    
    # 行业分析
    sector_analysis: Dict[str, Any]
    
    # LLM结构化提取
    llm_insights: Dict[str, Any]
    
    # 量化评分
    quantitative_score: float
    
    # 投资建议
    recommendation: str  # strong_buy/buy/hold/sell/strong_sell
    investment_value: float  # 0-100 投资价值评分
    
    # 是否建议加入观察列表
    should_add_to_watchlist: bool
    add_reason: str


class ComprehensiveStockAnalyzer:
    """综合股票分析器"""
    
    def __init__(self, session):
        self.session = session
        self.llm_enabled = os.getenv('OPENAI_API_KEY') or os.getenv('ANTHROPIC_API_KEY')
    
    def fetch_top_movers(self, days: int = 90, top_n: int = 20) -> Tuple[List[StockMoverInfo], List[StockMoverInfo]]:
        """获取指定时间段内涨跌幅Top N股票
        
        Returns:
            (gainers, losers) - 涨幅榜和跌幅榜
        """
        logger.info(f"Fetching top {top_n} movers for the last {days} days...")
        
        end_date = get_last_trading_day()
        start_date = end_date - timedelta(days=days)
        
        # 方法1: 从数据库获取已有数据
        gainers = self._fetch_from_db(start_date, end_date, top_n, ascending=False)
        losers = self._fetch_from_db(start_date, end_date, top_n, ascending=True)
        
        # 方法2: 如果数据库数据不足，从akshare获取实时数据
        if len(gainers) < top_n:
            logger.info("Database data insufficient, fetching from akshare...")
            ak_gainers, ak_losers = self._fetch_from_akshare(top_n)
            gainers = ak_gainers if ak_gainers else gainers
            losers = ak_losers if ak_losers else losers
        
        return gainers, losers
    
    def _fetch_from_db(self, start_date: date, end_date: date, top_n: int, ascending: bool) -> List[StockMoverInfo]:
        """从数据库获取涨跌幅数据"""
        order = "ASC" if ascending else "DESC"
        
        # 计算期间累计涨跌幅
        query = text(f"""
            WITH period_data AS (
                SELECT symbol,
                       FIRST_VALUE(close) OVER (PARTITION BY symbol ORDER BY trade_date ASC) as first_close,
                       LAST_VALUE(close) OVER (PARTITION BY symbol ORDER BY trade_date ASC 
                           ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) as last_close
                FROM prices_daily
                WHERE trade_date BETWEEN :start_date AND :end_date
            ),
            cumulative_change AS (
                SELECT DISTINCT symbol,
                       first_close,
                       last_close,
                       CASE WHEN first_close > 0 THEN (last_close - first_close) / first_close * 100 ELSE 0 END as cum_pct_chg
                FROM period_data
                WHERE first_close IS NOT NULL AND last_close IS NOT NULL
            )
            SELECT c.symbol, c.cum_pct_chg,
                   p.close, p.vol, p.amount,
                   COALESCE(w.name, s.name) as name,
                   w.sector
            FROM cumulative_change c
            LEFT JOIN prices_daily p ON c.symbol = p.symbol AND p.trade_date = :end_date
            LEFT JOIN watchlist w ON w.symbol = c.symbol
            LEFT JOIN stocks s ON s.symbol = c.symbol
            WHERE ABS(c.cum_pct_chg) > 1  -- 至少1%变化
            ORDER BY c.cum_pct_chg {order}
            LIMIT :limit
        """)
        
        try:
            rows = self.session.execute(query, {
                "start_date": start_date,
                "end_date": end_date,
                "limit": top_n
            }).fetchall()
            
            movers = []
            for row in rows:
                market = "SH" if row.symbol.endswith(".SH") else "SZ"
                movers.append(StockMoverInfo(
                    symbol=row.symbol,
                    name=row.name or row.symbol,
                    close=float(row.close) if row.close else 0,
                    pct_chg=float(row.cum_pct_chg),
                    volume=int(row.vol) if row.vol else 0,
                    amount=float(row.amount) if row.amount else 0,
                    market=market,
                    sector=row.sector
                ))
            return movers
        except Exception as e:
            logger.warning(f"Failed to fetch from DB: {e}")
            return []
    
    def _fetch_from_akshare(self, top_n: int) -> Tuple[List[StockMoverInfo], List[StockMoverInfo]]:
        """从akshare获取实时涨跌幅数据"""
        try:
            # 获取A股实时行情
            df = ak.stock_zh_a_spot_em()
            if df is None or df.empty:
                return [], []
            
            # 清理数据
            df = df.rename(columns={
                '代码': 'symbol',
                '名称': 'name', 
                '最新价': 'close',
                '涨跌幅': 'pct_chg',
                '成交量': 'volume',
                '成交额': 'amount',
                '市盈率-动态': 'pe',
                '市净率': 'pb',
                '总市值': 'market_cap'
            })
            
            # 过滤ST股和新股
            df = df[~df['name'].str.contains('ST|N|退', na=False)]
            
            # 转换数值
            for col in ['close', 'pct_chg', 'pe', 'pb']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 添加后缀
            df['symbol'] = df['symbol'].apply(
                lambda x: f"{x}.SH" if str(x).startswith(('6', '9')) else f"{x}.SZ"
            )
            
            # 排序获取涨跌幅
            gainers_df = df.nlargest(top_n, 'pct_chg')
            losers_df = df.nsmallest(top_n, 'pct_chg')
            
            def df_to_movers(df_part) -> List[StockMoverInfo]:
                movers = []
                for _, row in df_part.iterrows():
                    market = "SH" if row['symbol'].endswith(".SH") else "SZ"
                    movers.append(StockMoverInfo(
                        symbol=row['symbol'],
                        name=row['name'],
                        close=float(row['close']) if pd.notna(row['close']) else 0,
                        pct_chg=float(row['pct_chg']) if pd.notna(row['pct_chg']) else 0,
                        volume=int(row.get('volume', 0)) if pd.notna(row.get('volume')) else 0,
                        amount=float(row.get('amount', 0)) if pd.notna(row.get('amount')) else 0,
                        market=market,
                        pe=float(row.get('pe')) if pd.notna(row.get('pe')) else None,
                        pb=float(row.get('pb')) if pd.notna(row.get('pb')) else None,
                        market_cap=float(row.get('market_cap', 0)) / 1e8 if pd.notna(row.get('market_cap')) else None
                    ))
                return movers
            
            return df_to_movers(gainers_df), df_to_movers(losers_df)
            
        except Exception as e:
            logger.error(f"Failed to fetch from akshare: {e}")
            return [], []
    
    def fetch_stock_news(self, symbol: str, days: int = 30) -> List[Dict]:
        """获取股票相关新闻"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # 从PostgreSQL获取
        try:
            # 清理symbol格式以匹配不同格式
            code = symbol.replace(".SH", "").replace(".SZ", "")
            
            news_rows = self.session.execute(
                select(NewsArticle).where(
                    and_(
                        or_(
                            NewsArticle.related_stocks.contains([symbol]),
                            NewsArticle.related_stocks.contains([code])
                        ),
                        NewsArticle.published_at >= start_date
                    )
                ).order_by(desc(NewsArticle.published_at)).limit(50)
            ).scalars().all()
            
            return [{
                "title": n.title,
                "summary": n.summary,
                "sentiment": n.sentiment_score,
                "published_at": n.published_at,
                "source": n.source
            } for n in news_rows]
        except Exception as e:
            logger.warning(f"PostgreSQL news fetch failed for {symbol}: {e}")
            return []
    
    def fetch_stock_profile(self, symbol: str) -> Optional[Dict]:
        """获取股票profile信息"""
        try:
            profile = self.session.execute(
                select(StockProfile).where(StockProfile.symbol == symbol)
            ).scalar_one_or_none()
            
            if profile:
                return {
                    "symbol": profile.symbol,
                    "name": profile.company_name,  # StockProfile使用company_name
                    "industry": profile.industry,
                    "sector": profile.sub_industry,  # 使用sub_industry作为sector
                    "market": profile.market,
                    "pe_ratio": None,  # StockProfile没有pe_ratio
                    "pb_ratio": None,  # StockProfile没有pb_ratio
                    "roe": None,  # StockProfile没有roe
                    "market_cap": None,  # StockProfile没有market_cap
                    "description": profile.business_summary,  # 使用business_summary
                    "main_business": profile.core_products  # 使用core_products
                }
        except Exception as e:
            logger.warning(f"Profile fetch failed for {symbol}: {e}")
        
        return None
    
    def analyze_news_sentiment(self, news_list: List[Dict]) -> Dict[str, Any]:
        """分析新闻情感"""
        if not news_list:
            return {
                "count": 0,
                "avg_sentiment": 0.5,
                "sentiment_trend": "neutral",
                "key_themes": [],
                "risk_signals": []
            }
        
        sentiments = [n.get('sentiment', 0.5) for n in news_list if n.get('sentiment')]
        avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0.5
        
        # 简单主题提取
        titles = " ".join([n.get('title', '') for n in news_list])
        key_themes = []
        risk_signals = []
        
        positive_keywords = ['增长', '突破', '新高', '利好', '盈利', '创新', '合作']
        negative_keywords = ['下跌', '亏损', '风险', '调查', '处罚', '减持', '退市']
        
        for kw in positive_keywords:
            if kw in titles:
                key_themes.append(kw)
        
        for kw in negative_keywords:
            if kw in titles:
                risk_signals.append(kw)
        
        sentiment_trend = "bullish" if avg_sentiment > 0.6 else "bearish" if avg_sentiment < 0.4 else "neutral"
        
        return {
            "count": len(news_list),
            "avg_sentiment": round(avg_sentiment, 3),
            "sentiment_trend": sentiment_trend,
            "key_themes": key_themes[:5],
            "risk_signals": risk_signals[:5]
        }
    
    def calculate_quantitative_score(
        self,
        price_data: Dict,
        news_analysis: Dict,
        profile: Optional[Dict]
    ) -> Tuple[float, str]:
        """计算量化评分"""
        score = 50.0  # 基准分
        reasons = []
        
        # 价格动量 (30%)
        pct_chg = price_data.get('pct_chg', 0)
        if pct_chg > 5:
            score += 15
            reasons.append(f"强势上涨{pct_chg:.1f}%")
        elif pct_chg > 2:
            score += 8
            reasons.append(f"温和上涨{pct_chg:.1f}%")
        elif pct_chg < -5:
            score -= 15
            reasons.append(f"大幅下跌{pct_chg:.1f}%")
        elif pct_chg < -2:
            score -= 8
            reasons.append(f"下跌{pct_chg:.1f}%")
        
        # 新闻情感 (25%)
        sentiment = news_analysis.get('avg_sentiment', 0.5)
        if sentiment > 0.7:
            score += 12
            reasons.append("新闻情感极度乐观")
        elif sentiment > 0.6:
            score += 6
            reasons.append("新闻情感偏乐观")
        elif sentiment < 0.3:
            score -= 12
            reasons.append("新闻情感极度悲观")
        elif sentiment < 0.4:
            score -= 6
            reasons.append("新闻情感偏悲观")
        
        # 基本面 (25%)
        if profile:
            pe = profile.get('pe_ratio')
            roe = profile.get('roe')
            
            if pe and 0 < pe < 20:
                score += 8
                reasons.append(f"估值合理PE={pe:.1f}")
            elif pe and pe > 100:
                score -= 5
                reasons.append(f"估值偏高PE={pe:.1f}")
            
            if roe and roe > 15:
                score += 8
                reasons.append(f"盈利能力强ROE={roe:.1f}%")
            elif roe and roe < 5:
                score -= 5
                reasons.append(f"盈利能力弱ROE={roe:.1f}%")
        
        # 新闻覆盖度 (20%)
        news_count = news_analysis.get('count', 0)
        if news_count >= 10:
            score += 5
            reasons.append(f"关注度高(新闻{news_count}篇)")
        elif news_count == 0:
            score -= 5
            reasons.append("缺乏新闻覆盖")
        
        # 风险信号惩罚
        risk_signals = news_analysis.get('risk_signals', [])
        if len(risk_signals) >= 3:
            score -= 10
            reasons.append(f"多重风险信号: {', '.join(risk_signals[:3])}")
        elif len(risk_signals) >= 1:
            score -= 5
            reasons.append(f"风险信号: {', '.join(risk_signals)}")
        
        score = max(0, min(100, score))
        return score, "; ".join(reasons)
    
    def llm_analyze(self, stock_info: StockMoverInfo, news_analysis: Dict, profile: Optional[Dict]) -> Dict[str, Any]:
        """使用LLM进行深度分析"""
        if not self.llm_enabled:
            return {
                "enabled": False,
                "summary": "LLM分析未启用（未配置API密钥）",
                "key_insights": [],
                "risks": [],
                "opportunities": []
            }
        
        try:
            from backend.app.llm.llm_client import LLMClient
            llm = LLMClient()
            
            prompt = f"""
分析以下股票信息，提供结构化的投资分析：

股票信息:
- 代码: {stock_info.symbol}
- 名称: {stock_info.name}
- 当前价格: {stock_info.close}
- 涨跌幅: {stock_info.pct_chg:.2f}%
- 市盈率: {stock_info.pe or 'N/A'}
- 市净率: {stock_info.pb or 'N/A'}

新闻分析:
- 新闻数量: {news_analysis.get('count', 0)}
- 平均情感: {news_analysis.get('avg_sentiment', 0.5):.2f}
- 主要主题: {', '.join(news_analysis.get('key_themes', []))}
- 风险信号: {', '.join(news_analysis.get('risk_signals', []))}

基本面信息:
{json.dumps(profile, ensure_ascii=False, indent=2) if profile else '暂无'}

请以JSON格式返回分析结果，包含以下字段:
{{
    "summary": "简要分析总结(100字内)",
    "key_insights": ["洞察1", "洞察2", "洞察3"],
    "risks": ["风险1", "风险2"],
    "opportunities": ["机会1", "机会2"],
    "investment_rating": "strong_buy/buy/hold/sell/strong_sell",
    "confidence": 0.0-1.0
}}
"""
            
            response = llm.chat(prompt, temperature=0.3)
            
            # 解析JSON响应
            try:
                # 尝试提取JSON部分
                import re
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    result = json.loads(json_match.group())
                    result['enabled'] = True
                    return result
            except json.JSONDecodeError:
                pass
            
            return {
                "enabled": True,
                "summary": response[:200],
                "key_insights": [],
                "risks": [],
                "opportunities": [],
                "raw_response": response
            }
            
        except Exception as e:
            logger.warning(f"LLM analysis failed: {e}")
            return {
                "enabled": False,
                "error": str(e),
                "summary": "LLM分析失败"
            }
    
    def should_add_to_watchlist(self, analysis: ComprehensiveAnalysis) -> Tuple[bool, str]:
        """判断是否应该加入观察列表"""
        score = analysis.quantitative_score
        llm = analysis.llm_insights
        
        # 高分股票
        if score >= 70:
            return True, f"量化评分{score:.1f}分，投资价值较高"
        
        # LLM推荐
        if llm.get('enabled') and llm.get('investment_rating') in ['strong_buy', 'buy']:
            confidence = llm.get('confidence', 0.5)
            if confidence >= 0.7:
                return True, f"LLM推荐买入，置信度{confidence:.0%}"
        
        # 新闻情感极度乐观
        if analysis.news_analysis.get('avg_sentiment', 0.5) >= 0.75:
            return True, "新闻情感极度乐观"
        
        # 强势上涨但风险可控
        if analysis.price_info.get('pct_chg', 0) > 8 and len(analysis.news_analysis.get('risk_signals', [])) == 0:
            return True, "强势上涨且无明显风险信号"
        
        return False, ""
    
    def add_to_watchlist(self, stock: StockMoverInfo, reason: str) -> bool:
        """将股票加入观察列表"""
        try:
            # 检查是否已存在
            existing = self.session.execute(
                select(Watchlist).where(Watchlist.symbol == stock.symbol)
            ).scalar_one_or_none()
            
            if existing:
                logger.info(f"{stock.symbol} already in watchlist")
                return False
            
            new_item = Watchlist(
                symbol=stock.symbol,
                name=stock.name,
                sector=stock.sector,
                enabled=True,
                source='auto_analysis',
                score=stock.pct_chg,
                added_at=datetime.now()
            )
            self.session.add(new_item)
            self.session.commit()
            
            logger.info(f"Added {stock.symbol} ({stock.name}) to watchlist: {reason}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add {stock.symbol} to watchlist: {e}")
            self.session.rollback()
            return False
    
    def analyze_stock(self, stock: StockMoverInfo) -> ComprehensiveAnalysis:
        """对单只股票进行综合分析"""
        logger.info(f"Analyzing {stock.symbol} ({stock.name})...")
        
        # 获取新闻
        news_list = self.fetch_stock_news(stock.symbol)
        news_analysis = self.analyze_news_sentiment(news_list)
        
        # 获取profile
        profile = self.fetch_stock_profile(stock.symbol)
        
        # 价格信息
        price_info = {
            "close": stock.close,
            "pct_chg": stock.pct_chg,
            "volume": stock.volume,
            "amount": stock.amount,
            "market": stock.market,
            "pe": stock.pe,
            "pb": stock.pb,
            "market_cap": stock.market_cap
        }
        
        # 计算量化评分
        quant_score, quant_reason = self.calculate_quantitative_score(
            price_info, news_analysis, profile
        )
        
        # LLM分析
        llm_insights = self.llm_analyze(stock, news_analysis, profile)
        
        # 行业分析（简化）
        sector_analysis = {
            "sector": stock.sector or profile.get('sector') if profile else None,
            "industry": profile.get('industry') if profile else None
        }
        
        # 投资建议
        if quant_score >= 75:
            recommendation = "strong_buy"
        elif quant_score >= 60:
            recommendation = "buy"
        elif quant_score >= 40:
            recommendation = "hold"
        elif quant_score >= 25:
            recommendation = "sell"
        else:
            recommendation = "strong_sell"
        
        analysis = ComprehensiveAnalysis(
            symbol=stock.symbol,
            name=stock.name,
            analysis_date=date.today(),
            price_info=price_info,
            news_analysis=news_analysis,
            fundamental_analysis=profile or {},
            sector_analysis=sector_analysis,
            llm_insights=llm_insights,
            quantitative_score=quant_score,
            recommendation=recommendation,
            investment_value=quant_score,
            should_add_to_watchlist=False,
            add_reason=""
        )
        
        # 判断是否加入观察列表
        should_add, add_reason = self.should_add_to_watchlist(analysis)
        analysis.should_add_to_watchlist = should_add
        analysis.add_reason = add_reason
        
        return analysis
    
    def run_full_analysis(
        self, 
        days: int = 90, 
        top_n: int = 20, 
        auto_add: bool = False
    ) -> Dict[str, Any]:
        """运行完整分析流程"""
        
        # 检查是否为交易日
        today = date.today()
        if not is_trading_day(today):
            logger.warning(f"{today} is not a trading day, analysis will use last trading day data")
        
        # 获取涨跌幅Top N
        gainers, losers = self.fetch_top_movers(days, top_n)
        
        logger.info(f"Found {len(gainers)} gainers and {len(losers)} losers")
        
        # 分析所有股票
        all_analyses = []
        added_to_watchlist = []
        
        for stock in gainers + losers:
            try:
                analysis = self.analyze_stock(stock)
                all_analyses.append(analysis)
                
                # 自动加入观察列表
                if auto_add and analysis.should_add_to_watchlist:
                    if self.add_to_watchlist(stock, analysis.add_reason):
                        added_to_watchlist.append({
                            "symbol": stock.symbol,
                            "name": stock.name,
                            "reason": analysis.add_reason,
                            "score": analysis.quantitative_score
                        })
                        
            except Exception as e:
                logger.error(f"Failed to analyze {stock.symbol}: {e}")
        
        # 生成报告
        report = self._generate_report(all_analyses, added_to_watchlist)
        
        return report
    
    def _generate_report(
        self, 
        analyses: List[ComprehensiveAnalysis],
        added_to_watchlist: List[Dict]
    ) -> Dict[str, Any]:
        """生成综合报告"""
        
        # 按评分排序
        sorted_analyses = sorted(analyses, key=lambda x: x.quantitative_score, reverse=True)
        
        # 统计
        buy_count = sum(1 for a in analyses if a.recommendation in ['strong_buy', 'buy'])
        sell_count = sum(1 for a in analyses if a.recommendation in ['strong_sell', 'sell'])
        hold_count = len(analyses) - buy_count - sell_count
        
        avg_score = sum(a.quantitative_score for a in analyses) / len(analyses) if analyses else 0
        
        # 市场情绪
        if buy_count > sell_count * 2:
            market_sentiment = "bullish"
        elif sell_count > buy_count * 2:
            market_sentiment = "bearish"
        else:
            market_sentiment = "neutral"
        
        report = {
            "generated_at": datetime.now().isoformat(),
            "analysis_date": date.today().isoformat(),
            "summary": {
                "total_analyzed": len(analyses),
                "buy_recommendations": buy_count,
                "sell_recommendations": sell_count,
                "hold_recommendations": hold_count,
                "average_score": round(avg_score, 2),
                "market_sentiment": market_sentiment
            },
            "top_picks": [
                {
                    "symbol": a.symbol,
                    "name": a.name,
                    "score": a.quantitative_score,
                    "recommendation": a.recommendation,
                    "price_change": a.price_info.get('pct_chg', 0),
                    "key_reasons": a.add_reason or "量化分析推荐"
                }
                for a in sorted_analyses[:10]
            ],
            "risk_alerts": [
                {
                    "symbol": a.symbol,
                    "name": a.name,
                    "score": a.quantitative_score,
                    "risks": a.news_analysis.get('risk_signals', [])
                }
                for a in sorted_analyses if a.quantitative_score < 40
            ][:10],
            "added_to_watchlist": added_to_watchlist,
            "all_analyses": [
                {
                    "symbol": a.symbol,
                    "name": a.name,
                    "score": a.quantitative_score,
                    "recommendation": a.recommendation,
                    "news_sentiment": a.news_analysis.get('avg_sentiment'),
                    "news_count": a.news_analysis.get('count', 0)
                }
                for a in sorted_analyses
            ]
        }
        
        return report


def save_report_to_db(session, report: Dict):
    """将报告保存到数据库"""
    try:
        # 保存为DailyReport
        today = date.today()
        
        existing = session.execute(
            select(DailyReport).where(DailyReport.report_date == today)
        ).scalar_one_or_none()
        
        summary = report.get('summary', {})
        top_picks = report.get('top_picks', [])
        
        if existing:
            existing.total_stocks = summary.get('total_analyzed', 0)
            existing.buy_count = summary.get('buy_recommendations', 0)
            existing.sell_count = summary.get('sell_recommendations', 0)
            existing.hold_count = summary.get('hold_recommendations', 0)
            existing.market_sentiment = summary.get('market_sentiment', 'neutral')
            existing.comprehensive_analysis = json.dumps(report, ensure_ascii=False)
            existing.generated_at = datetime.now()
        else:
            new_report = DailyReport(
                report_date=today,
                total_stocks=summary.get('total_analyzed', 0),
                buy_count=summary.get('buy_recommendations', 0),
                sell_count=summary.get('sell_recommendations', 0),
                hold_count=summary.get('hold_recommendations', 0),
                market_sentiment=summary.get('market_sentiment', 'neutral'),
                market_summary=f"分析{summary.get('total_analyzed', 0)}只股票，平均评分{summary.get('average_score', 0):.1f}",
                buy_recommendations=top_picks[:5],
                hold_recommendations=[],
                sell_recommendations=report.get('risk_alerts', [])[:5],
                comprehensive_analysis=json.dumps(report, ensure_ascii=False),
                generated_at=datetime.now()
            )
            session.add(new_report)
        
        session.commit()
        logger.info("Report saved to database")
        
    except Exception as e:
        logger.error(f"Failed to save report: {e}")
        session.rollback()


def main():
    parser = argparse.ArgumentParser(description="综合股票分析脚本")
    parser.add_argument('--days', type=int, default=90, help='分析时间跨度（天）')
    parser.add_argument('--top', type=int, default=20, help='涨跌幅Top N')
    parser.add_argument('--auto-add', action='store_true', help='自动将优质股票加入观察列表')
    parser.add_argument('--save-report', action='store_true', help='保存报告到数据库')
    parser.add_argument('--output', type=str, help='输出JSON文件路径')
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("综合股票分析脚本启动")
    logger.info(f"参数: days={args.days}, top={args.top}, auto_add={args.auto_add}")
    logger.info("=" * 60)
    
    with SessionLocal() as session:
        analyzer = ComprehensiveStockAnalyzer(session)
        
        report = analyzer.run_full_analysis(
            days=args.days,
            top_n=args.top,
            auto_add=args.auto_add
        )
        
        # 打印摘要
        summary = report.get('summary', {})
        print("\n" + "=" * 60)
        print("📊 分析报告摘要")
        print("=" * 60)
        print(f"分析股票数: {summary.get('total_analyzed', 0)}")
        print(f"买入推荐: {summary.get('buy_recommendations', 0)}")
        print(f"持有推荐: {summary.get('hold_recommendations', 0)}")
        print(f"卖出推荐: {summary.get('sell_recommendations', 0)}")
        print(f"平均评分: {summary.get('average_score', 0):.2f}")
        print(f"市场情绪: {summary.get('market_sentiment', 'neutral')}")
        
        print("\n🏆 Top 10 推荐:")
        for i, pick in enumerate(report.get('top_picks', [])[:10], 1):
            print(f"  {i}. {pick['symbol']} ({pick['name']}) - 评分: {pick['score']:.1f}, 推荐: {pick['recommendation']}")
        
        if report.get('added_to_watchlist'):
            print(f"\n✅ 已加入观察列表 ({len(report['added_to_watchlist'])}只):")
            for item in report['added_to_watchlist']:
                print(f"  - {item['symbol']} ({item['name']}): {item['reason']}")
        
        # 保存报告
        if args.save_report:
            save_report_to_db(session, report)
        
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            print(f"\n📄 报告已保存到: {args.output}")
    
    logger.info("分析完成")


if __name__ == "__main__":
    main()
