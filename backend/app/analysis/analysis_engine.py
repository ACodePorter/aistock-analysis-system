"""
每日分析引擎 - 综合评分、周期分析、投资潜力评估

评分模型:
    综合评分 = 技术面评分×0.3 + 基本面评分×0.2 + 新闻情感评分×0.2 + 资金流向评分×0.15 + 周期规律评分×0.15
"""

import logging
import json
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, asdict

from sqlalchemy import select, func, and_, desc
from sqlalchemy.orm import Session

from app.core.models import (
    Watchlist, PriceDaily, Signal, Forecast, FundFlowDaily,
    NewsArticle, DailyAnalysis, DailyReport, SimulatedTrade,
    AnalysisHistory, StockProfile
)

logger = logging.getLogger(__name__)


@dataclass
class ScoreBreakdown:
    """评分分解"""
    technical: float = 50.0
    fundamental: float = 50.0
    sentiment: float = 50.0
    fund_flow: float = 50.0
    cycle: float = 50.0
    total: float = 50.0
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AnalysisResult:
    """单只股票分析结果"""
    symbol: str
    name: Optional[str]
    sector: Optional[str]
    analysis_date: date
    scores: ScoreBreakdown
    recommendation: str  # buy/hold/sell/watch
    risk_level: str  # low/medium/high
    confidence: float  # 0-1
    
    # 价格快照
    close_price: Optional[float] = None
    pct_change: Optional[float] = None
    volume: Optional[int] = None
    
    # 技术指标
    ma5: Optional[float] = None
    ma20: Optional[float] = None
    rsi: Optional[float] = None
    macd: Optional[float] = None
    
    # 新闻情感
    news_count: int = 0
    news_sentiment_avg: Optional[float] = None
    
    # 分析内容
    analysis_summary: str = ""
    key_factors: List[str] = None
    risk_factors: List[str] = None
    
    def __post_init__(self):
        if self.key_factors is None:
            self.key_factors = []
        if self.risk_factors is None:
            self.risk_factors = []
    
    def to_dict(self) -> dict:
        d = asdict(self)
        d['scores'] = self.scores.to_dict()
        return d


class AnalysisEngine:
    """每日分析引擎"""
    
    # 评分权重配置
    WEIGHTS = {
        'technical': 0.30,
        'fundamental': 0.20,
        'sentiment': 0.20,
        'fund_flow': 0.15,
        'cycle': 0.15
    }
    
    # 推荐阈值
    THRESHOLDS = {
        'buy': 70,      # 评分>=70 推荐买入
        'sell': 40,     # 评分<40 建议卖出
        'high_risk': 30,
        'low_risk': 70
    }
    
    def __init__(self, session: Session):
        self.session = session
    
    def analyze_stock(self, symbol: str, analysis_date: date = None) -> Optional[AnalysisResult]:
        """分析单只股票
        
        Args:
            symbol: 股票代码
            analysis_date: 分析日期，默认今天
            
        Returns:
            AnalysisResult 或 None（数据不足）
        """
        if analysis_date is None:
            analysis_date = date.today()
        
        # 获取基础信息
        watchlist = self.session.execute(
            select(Watchlist).where(Watchlist.symbol == symbol)
        ).scalar_one_or_none()
        
        name = watchlist.name if watchlist else None
        sector = watchlist.sector if watchlist else None
        
        # 如果名称为空，尝试从 AKShare 获取并回填
        if not name:
            name = self._resolve_stock_name(symbol)
            if name and watchlist:
                try:
                    watchlist.name = name
                    self.session.flush()
                except Exception:
                    pass
        
        # 获取价格数据（最近60天）
        prices = self._get_price_history(symbol, analysis_date, days=60)
        if not prices or len(prices) < 5:
            logger.warning(f"Insufficient price data for {symbol}")
            return None
        
        latest_price = prices[0]
        
        # 计算各项评分
        technical_score, tech_factors = self._calculate_technical_score(prices)
        fundamental_score, fund_factors = self._calculate_fundamental_score(symbol)
        sentiment_score, sent_factors, news_stats = self._calculate_sentiment_score(symbol, analysis_date)
        fund_flow_score, flow_factors = self._calculate_fund_flow_score(symbol, analysis_date)
        cycle_score, cycle_factors = self._calculate_cycle_score(prices)
        
        # 计算综合评分
        # 检测哪些维度有真实数据（默认分=50.0 表示无数据）
        has_real_data = {
            'technical': abs(technical_score - 50.0) > 0.01,
            'fundamental': abs(fundamental_score - 50.0) > 0.01,
            'sentiment': abs(sentiment_score - 50.0) > 0.01,
            'fund_flow': abs(fund_flow_score - 50.0) > 0.01,
            'cycle': abs(cycle_score - 50.0) > 0.01,
        }
        real_data_count = sum(1 for v in has_real_data.values() if v)
        
        total_score = (
            technical_score * self.WEIGHTS['technical'] +
            fundamental_score * self.WEIGHTS['fundamental'] +
            sentiment_score * self.WEIGHTS['sentiment'] +
            fund_flow_score * self.WEIGHTS['fund_flow'] +
            cycle_score * self.WEIGHTS['cycle']
        )
        
        scores = ScoreBreakdown(
            technical=technical_score,
            fundamental=fundamental_score,
            sentiment=sentiment_score,
            fund_flow=fund_flow_score,
            cycle=cycle_score,
            total=total_score
        )
        
        # 确定推荐和风险等级
        recommendation = self._determine_recommendation(total_score, tech_factors)
        risk_level = self._determine_risk_level(scores, tech_factors + flow_factors)
        confidence = self._calculate_confidence(prices, news_stats, real_data_count)
        
        # 收集关键因素（更全面的关键词匹配）
        positive_keywords = ['利好', '突破', '强', '金叉', '多头', '反弹', '增长', '优秀', '稳健', '放量上涨', '正面', '流入']
        negative_keywords = ['风险', '弱', '流出', '死叉', '空头', '下跌', '负面', '超买', '承压', '下滑', '抛压']
        
        all_factors = tech_factors + fund_factors + sent_factors + flow_factors + cycle_factors
        key_factors = [f for f in all_factors if any(k in f for k in positive_keywords)]
        risk_factors = [f for f in all_factors if any(k in f for k in negative_keywords)]
        
        # 标注数据缺失维度
        dim_names = {'technical': '技术面', 'fundamental': '基本面', 'sentiment': '舆情', 'fund_flow': '资金流', 'cycle': '周期'}
        missing_dims = [dim_names[k] for k, v in has_real_data.items() if not v]
        if missing_dims:
            risk_factors.append(f"数据不足: {'/'.join(missing_dims)}维度使用默认值")
        
        # 生成分析摘要
        analysis_summary = self._generate_summary(symbol, name, scores, recommendation, risk_level, key_factors, risk_factors)
        
        # 计算技术指标
        ma5 = sum(p.close for p in prices[:5]) / 5 if len(prices) >= 5 else None
        ma20 = sum(p.close for p in prices[:20]) / 20 if len(prices) >= 20 else None
        
        # 获取已有信号数据
        signal = self.session.execute(
            select(Signal).where(
                and_(Signal.symbol == symbol, Signal.trade_date <= analysis_date)
            ).order_by(desc(Signal.trade_date)).limit(1)
        ).scalar_one_or_none()
        
        return AnalysisResult(
            symbol=symbol,
            name=name,
            sector=sector,
            analysis_date=analysis_date,
            scores=scores,
            recommendation=recommendation,
            risk_level=risk_level,
            confidence=confidence,
            close_price=latest_price.close,
            pct_change=latest_price.pct_chg,
            volume=latest_price.vol,
            ma5=ma5,
            ma20=ma20,
            rsi=float(signal.rsi) if signal and signal.rsi else None,
            macd=float(signal.macd) if signal and signal.macd else None,
            news_count=news_stats.get('count', 0),
            news_sentiment_avg=news_stats.get('sentiment_avg'),
            analysis_summary=analysis_summary,
            key_factors=key_factors[:5],  # 最多5个
            risk_factors=risk_factors[:5]
        )
    
    # ── 股票名称解析 ──────────────────────────
    _stock_name_cache: dict = {}
    
    def _resolve_stock_name(self, symbol: str) -> Optional[str]:
        """通过 AKShare 查找股票中文名称"""
        if symbol in self._stock_name_cache:
            return self._stock_name_cache[symbol]
        try:
            # 懒加载全量映射（只加载一次）
            if not self._stock_name_cache:
                from app.data.data_source import search_stocks
                import akshare as _ak
                df = _ak.stock_info_a_code_name()
                for _, row in df.iterrows():
                    code = str(row['code'])
                    nm = str(row['name'])
                    if code.startswith('6') or code.startswith('9'):
                        self._stock_name_cache[f"{code}.SH"] = nm
                    if code.startswith(('0', '1', '2', '3')):
                        self._stock_name_cache[f"{code}.SZ"] = nm
                    self._stock_name_cache[code] = nm
                logger.info(f"Stock name cache loaded: {len(self._stock_name_cache)} entries")
            return self._stock_name_cache.get(symbol)
        except Exception as e:
            logger.warning(f"Failed to resolve stock name for {symbol}: {e}")
            return None
    
    def _get_price_history(self, symbol: str, end_date: date, days: int = 60) -> List[PriceDaily]:
        """获取价格历史"""
        start_date = end_date - timedelta(days=days * 2)  # 扩大范围以确保足够交易日
        
        prices = self.session.execute(
            select(PriceDaily).where(
                and_(
                    PriceDaily.symbol == symbol,
                    PriceDaily.trade_date <= end_date,
                    PriceDaily.trade_date >= start_date
                )
            ).order_by(desc(PriceDaily.trade_date)).limit(days)
        ).scalars().all()
        
        return list(prices)
    
    def _calculate_technical_score(self, prices: List[PriceDaily]) -> Tuple[float, List[str]]:
        """计算技术面评分
        
        考虑因素:
        - 趋势：MA5 vs MA20, MA10 vs MA30
        - RSI: 超买超卖信号
        - MACD: 金叉死叉及柱体变化
        - 布林带: 价格相对位置
        - 成交量: 量价配合分析
        - 动量：近期涨跌幅
        """
        if len(prices) < 20:
            return 50.0, ["数据不足"]
        
        factors = []
        score = 50.0
        
        closes = [p.close for p in prices if p.close]
        if len(closes) < 20:
            return 50.0, ["价格数据不足"]
        
        # ---- MA均线系统（含多层趋势） ----
        ma5 = sum(closes[:5]) / 5
        ma10 = sum(closes[:10]) / 10 if len(closes) >= 10 else ma5
        ma20 = sum(closes[:20]) / 20
        ma30 = sum(closes[:30]) / 30 if len(closes) >= 30 else ma20
        
        # 短期趋势（MA5 vs MA20）
        if ma5 > ma20 * 1.02:
            score += 12
            factors.append("MA5上穿MA20，短期趋势强")
        elif ma5 < ma20 * 0.98:
            score -= 8
            factors.append("MA5下穿MA20，短期趋势弱")
        
        # 中期趋势（MA10 vs MA30）
        if len(closes) >= 30:
            if ma10 > ma30 * 1.01:
                score += 8
                factors.append("MA10站上MA30，中期趋势向好")
            elif ma10 < ma30 * 0.99:
                score -= 6
                factors.append("MA10跌破MA30，中期趋势偏弱")
        
        # 均线多头/空头排列
        if ma5 > ma10 > ma20:
            score += 5
            factors.append("均线多头排列(利好)")
        elif ma5 < ma10 < ma20:
            score -= 5
            factors.append("均线空头排列(风险)")
        
        # ---- RSI 分析 ----
        try:
            import pandas as pd
            from app.analysis.signals import rsi as calc_rsi
            close_series = pd.Series(list(reversed(closes)))
            rsi_series = calc_rsi(close_series, period=14)
            current_rsi = rsi_series.iloc[-1] if not rsi_series.empty else None
            
            if current_rsi is not None and not pd.isna(current_rsi):
                if current_rsi > 80:
                    score -= 10
                    factors.append(f"RSI={current_rsi:.1f}，严重超买(风险)")
                elif current_rsi > 70:
                    score -= 5
                    factors.append(f"RSI={current_rsi:.1f}，超买区域")
                elif current_rsi < 20:
                    score += 10
                    factors.append(f"RSI={current_rsi:.1f}，严重超卖(利好)")
                elif current_rsi < 30:
                    score += 5
                    factors.append(f"RSI={current_rsi:.1f}，超卖区域，反弹可期")
                elif 40 <= current_rsi <= 60:
                    factors.append(f"RSI={current_rsi:.1f}，中性区间")
        except Exception:
            pass
        
        # ---- MACD 分析 ----
        try:
            from app.analysis.signals import macd as calc_macd
            close_series = pd.Series(list(reversed(closes)))
            macd_line, signal_line, hist = calc_macd(close_series)
            
            if len(hist) >= 2:
                curr_hist = hist.iloc[-1]
                prev_hist = hist.iloc[-2]
                curr_macd = macd_line.iloc[-1]
                curr_signal = signal_line.iloc[-1]
                
                if not pd.isna(curr_hist) and not pd.isna(prev_hist):
                    # MACD金叉
                    if curr_macd > curr_signal and macd_line.iloc[-2] <= signal_line.iloc[-2]:
                        score += 8
                        factors.append("MACD金叉，买入信号")
                    # MACD死叉
                    elif curr_macd < curr_signal and macd_line.iloc[-2] >= signal_line.iloc[-2]:
                        score -= 8
                        factors.append("MACD死叉，卖出信号")
                    
                    # MACD柱体变化趋势
                    if curr_hist > 0 and curr_hist > prev_hist:
                        score += 3
                        factors.append("MACD柱体放大，动能增强")
                    elif curr_hist < 0 and curr_hist < prev_hist:
                        score -= 3
                        factors.append("MACD柱体扩大负值，动能减弱")
        except Exception:
            pass
        
        # ---- 布林带分析 ----
        if len(closes) >= 20:
            import math
            ma20_val = sum(closes[:20]) / 20
            std20 = math.sqrt(sum((c - ma20_val) ** 2 for c in closes[:20]) / 20)
            upper_band = ma20_val + 2 * std20
            lower_band = ma20_val - 2 * std20
            
            current = closes[0]
            if std20 > 0:
                bb_position = (current - lower_band) / (upper_band - lower_band)
                if current > upper_band:
                    score -= 5
                    factors.append(f"突破布林带上轨，短期超买")
                elif current < lower_band:
                    score += 5
                    factors.append(f"跌破布林带下轨，短期超卖")
                
                # 布林带收窄 → 变盘信号
                band_width = (upper_band - lower_band) / ma20_val
                if band_width < 0.04:
                    factors.append("布林带收窄，变盘在即")
        
        # ---- 近5日涨幅 ----
        if len(closes) >= 6:
            recent_return = (closes[0] - closes[5]) / closes[5] * 100
            if recent_return > 5:
                score += 8
                factors.append(f"近5日涨幅{recent_return:.1f}%，动量强")
            elif recent_return > 10:
                score += 5  # 涨太多反而减少加分（追高风险）
                factors.append(f"近5日涨幅{recent_return:.1f}%，注意追高风险")
            elif recent_return < -5:
                score -= 8
                factors.append(f"近5日跌幅{abs(recent_return):.1f}%，动量弱")
        
        # ---- 相对位置（20日高低点） ----
        high_20 = max(closes[:20])
        low_20 = min(closes[:20])
        if high_20 > low_20:
            position = (closes[0] - low_20) / (high_20 - low_20)
            if position > 0.8:
                score += 3
                factors.append("接近20日高点，突破可能性大")
            elif position < 0.2:
                score -= 3
                factors.append("接近20日低点，存在下跌风险")
        
        # ---- 成交量分析（量价配合） ----
        vols = [p.vol for p in prices[:20] if p.vol]
        if len(vols) >= 5:
            avg_vol = sum(vols) / len(vols)
            recent_vol = sum(vols[:5]) / 5
            price_up = closes[0] > closes[4] if len(closes) > 4 else False
            
            if recent_vol > avg_vol * 1.5:
                if price_up:
                    score += 8
                    factors.append("放量上涨，量价配合良好(利好)")
                else:
                    score -= 5
                    factors.append("放量下跌，抛压较大(风险)")
            elif recent_vol < avg_vol * 0.5:
                if price_up:
                    factors.append("缩量上涨，持续性存疑")
                else:
                    score -= 3
                    factors.append("缩量阴跌")
        
        return max(0, min(100, score)), factors
    
    def _calculate_fundamental_score(self, symbol: str) -> Tuple[float, List[str]]:
        """计算基本面评分
        
        基于 StockProfile 和财务指标数据
        考虑因素:
        - 估值水平：PE/PB与行业比较
        - 盈利能力：ROE/毛利率
        - 成长性：营收/净利润增长
        - 财务健康：资产负债率
        """
        factors = []
        score = 50.0
        
        # 获取公司画像
        profile = self.session.execute(
            select(StockProfile).where(StockProfile.symbol == symbol)
        ).scalar_one_or_none()
        
        if profile:
            # 检查有效性
            if not profile.is_valid:
                score -= 20
                factors.append(f"公司状态异常: {profile.validation_status}")
            
            if profile.industry:
                factors.append(f"所属行业: {profile.industry}")
        
        # 尝试获取财务指标
        try:
            from app.data.financial_data import financial_fetcher
            
            # 获取估值指标
            valuation = financial_fetcher.fetch_valuation_indicators(symbol)
            if valuation:
                pe = valuation.get('pe_ttm')
                pb = valuation.get('pb')
                
                # PE评估
                if pe is not None:
                    if 0 < pe < 15:
                        score += 10
                        factors.append(f"PE={pe:.1f}，估值较低(利好)")
                    elif 15 <= pe < 30:
                        factors.append(f"PE={pe:.1f}，估值合理")
                    elif pe >= 50:
                        score -= 10
                        factors.append(f"PE={pe:.1f}，估值偏高(风险)")
                
                # PB评估
                if pb is not None:
                    if 0 < pb < 2:
                        score += 5
                        factors.append(f"PB={pb:.1f}，资产价值合理")
                    elif pb >= 5:
                        score -= 5
                        factors.append(f"PB={pb:.1f}，资产溢价较高")
            
            # 获取财务指标
            financial = financial_fetcher.fetch_financial_report(symbol)
            if financial:
                roe = financial.get('roe')
                debt_ratio = financial.get('debt_ratio')
                
                # ROE评估
                if roe is not None:
                    if roe >= 15:
                        score += 10
                        factors.append(f"ROE={roe:.1f}%，盈利能力强")
                    elif roe >= 10:
                        score += 5
                        factors.append(f"ROE={roe:.1f}%，盈利能力较好")
                    elif roe < 5:
                        score -= 5
                        factors.append(f"ROE={roe:.1f}%，盈利能力较弱")
                
                # 资产负债率评估
                if debt_ratio is not None:
                    if debt_ratio > 70:
                        score -= 10
                        factors.append(f"资产负债率{debt_ratio:.1f}%，财务风险较高")
                    elif debt_ratio < 30:
                        score += 5
                        factors.append(f"资产负债率{debt_ratio:.1f}%，财务稳健")
            
            # 获取成长性指标
            growth = financial_fetcher.fetch_growth_indicators(symbol)
            if growth:
                revenue_yoy = growth.get('revenue_yoy')
                profit_yoy = growth.get('net_profit_yoy')
                
                # 营收增长评估
                if revenue_yoy is not None:
                    if revenue_yoy >= 20:
                        score += 10
                        factors.append(f"营收同比+{revenue_yoy:.1f}%，高成长")
                    elif revenue_yoy >= 10:
                        score += 5
                        factors.append(f"营收同比+{revenue_yoy:.1f}%，稳健增长")
                    elif revenue_yoy < -10:
                        score -= 10
                        factors.append(f"营收同比{revenue_yoy:.1f}%，下滑明显")
                
                # 净利润增长评估
                if profit_yoy is not None:
                    if profit_yoy >= 30:
                        score += 10
                        factors.append(f"净利润同比+{profit_yoy:.1f}%，业绩优秀")
                    elif profit_yoy < -20:
                        score -= 10
                        factors.append(f"净利润同比{profit_yoy:.1f}%，业绩承压")
        
        except Exception as e:
            logger.warning(f"获取{symbol}财务数据失败: {e}")
            factors.append("财务数据获取失败")
        
        # 风险因素
        if profile and profile.risk_factors:
            risk_count = len(profile.risk_factors.split(',')) if isinstance(profile.risk_factors, str) else 0
            if risk_count > 3:
                score -= 10
                factors.append(f"存在{risk_count}个风险因素")
        
        return max(0, min(100, score)), factors
    
    def _calculate_sentiment_score(self, symbol: str, analysis_date: date) -> Tuple[float, List[str], Dict]:
        """计算新闻情感评分
        
        增强版：
        - 时间衰减加权（越近的新闻权重越高）
        - 区分正面/负面/中性新闻数量
        - 检测舆情突变
        - 新闻数量不足时明确标注
        - 当 related_stocks 查询无结果时，根据股票名称在标题中搜索
        """
        factors = []
        score = 50.0
        stats = {'count': 0, 'sentiment_avg': None, 'positive': 0, 'negative': 0, 'neutral': 0}
        
        # 获取最近7天的相关新闻
        start_date = analysis_date - timedelta(days=7)
        # analysis_date 是 date 类型，需要包含当天全天的文章
        end_dt = datetime.combine(analysis_date, datetime.max.time()) if hasattr(datetime, 'combine') else analysis_date
        
        articles = self.session.execute(
            select(NewsArticle).where(
                and_(
                    NewsArticle.related_stocks.contains([symbol]),
                    NewsArticle.published_at >= start_date,
                    NewsArticle.published_at <= end_dt
                )
            )
        ).scalars().all()
        
        # 回退：如果 related_stocks 查询无结果，尝试按股票名称搜索标题
        if not articles:
            stock_name = self._resolve_stock_name(symbol)
            # 也尝试纯数字代码搜索
            code_only = symbol.split('.')[0] if '.' in symbol else symbol
            if stock_name:
                articles = self.session.execute(
                    select(NewsArticle).where(
                        and_(
                            NewsArticle.published_at >= start_date,
                            NewsArticle.published_at <= end_dt,
                            NewsArticle.title.ilike(f'%{stock_name}%')
                        )
                    ).limit(20)
                ).scalars().all()
            if not articles and code_only:
                articles = self.session.execute(
                    select(NewsArticle).where(
                        and_(
                            NewsArticle.published_at >= start_date,
                            NewsArticle.published_at <= end_dt,
                            NewsArticle.title.ilike(f'%{code_only}%')
                        )
                    ).limit(20)
                ).scalars().all()
        
        stats['count'] = len(articles)
        
        if not articles:
            return 50.0, ["近期无相关新闻，情感评分按中性处理"], stats
        
        # 时间衰减加权情感分数
        weighted_sum = 0.0
        weight_total = 0.0
        
        for a in articles:
            if a.sentiment_score is None:
                continue
            
            # 时间衰减：发布越近权重越高
            days_ago = (analysis_date - a.published_at.date()).days if hasattr(a.published_at, 'date') else 3
            decay = 1.0 / (1 + days_ago * 0.3)
            
            weighted_sum += a.sentiment_score * decay
            weight_total += decay
            
            # 分类统计
            if a.sentiment_score > 0.2:
                stats['positive'] += 1
            elif a.sentiment_score < -0.2:
                stats['negative'] += 1
            else:
                stats['neutral'] += 1
        
        # 如果没有文章有 sentiment_score，尝试标题关键词分析
        if weight_total == 0 and articles:
            pos_kw = ['利好', '上涨', '增长', '突破', '大涨', '盈利', '反弹', '创新高', '利润']
            neg_kw = ['利空', '下跌', '下滑', '亏损', '风险', '暴跌', '减持', '处罚', '退市']
            pos_count = 0
            neg_count = 0
            for a in articles:
                title = a.title or ''
                pos_count += sum(1 for k in pos_kw if k in title)
                neg_count += sum(1 for k in neg_kw if k in title)
            total_kw = pos_count + neg_count
            if total_kw > 0:
                sentiment_ratio = (pos_count - neg_count) / total_kw
                avg_sentiment = sentiment_ratio * 0.5  # 标题分析可信度较低，缩小范围
                stats['sentiment_avg'] = avg_sentiment
                score = 50 + avg_sentiment * 50
                weight_total = 1  # 标记已有结果
                factors.append(f"基于{len(articles)}篇新闻标题关键词分析(可信度较低)")
                if pos_count > neg_count:
                    stats['positive'] = pos_count
                    stats['negative'] = neg_count
                elif neg_count > pos_count:
                    stats['positive'] = pos_count
                    stats['negative'] = neg_count
            else:
                factors.append(f"找到{len(articles)}篇相关新闻，但无情感评分数据")
        
        if weight_total > 0:
            avg_sentiment = weighted_sum / weight_total
            stats['sentiment_avg'] = avg_sentiment
            
            # 情感分数范围 -1 到 1，转换为 0-100
            score = 50 + avg_sentiment * 50
            
            if avg_sentiment > 0.5:
                factors.append(f"新闻情感强烈正面({avg_sentiment:.2f})，舆论利好")
            elif avg_sentiment > 0.3:
                factors.append(f"新闻情感偏正面({avg_sentiment:.2f})")
            elif avg_sentiment < -0.5:
                factors.append(f"新闻情感强烈负面({avg_sentiment:.2f})，舆论风险")
            elif avg_sentiment < -0.3:
                factors.append(f"新闻情感偏负面({avg_sentiment:.2f})")
            else:
                factors.append("新闻情感中性")
        
        # 舆情热度分析
        if len(articles) > 15:
            score += 5
            factors.append(f"近期热度极高({len(articles)}篇新闻)")
        elif len(articles) > 10:
            score += 3
            factors.append(f"近期热度较高({len(articles)}篇新闻)")
        elif len(articles) < 3:
            factors.append(f"新闻覆盖较少({len(articles)}篇)，情感参考价值有限")
        
        # 正负面对比
        if stats['positive'] > 0 and stats['negative'] > 0:
            ratio = stats['positive'] / (stats['positive'] + stats['negative'])
            if ratio > 0.7:
                score += 5
                factors.append(f"正面新闻占比{ratio:.0%}，舆论环境良好")
            elif ratio < 0.3:
                score -= 5
                factors.append(f"负面新闻占比{1-ratio:.0%}，需关注负面舆情")
        
        return max(0, min(100, score)), factors, stats
    
    def _calculate_fund_flow_score(self, symbol: str, analysis_date: date) -> Tuple[float, List[str]]:
        """计算资金流向评分"""
        factors = []
        score = 50.0
        
        # 获取最近5天的资金流向
        start_date = analysis_date - timedelta(days=10)
        
        flows = self.session.execute(
            select(FundFlowDaily).where(
                and_(
                    FundFlowDaily.symbol == symbol,
                    FundFlowDaily.trade_date <= analysis_date,
                    FundFlowDaily.trade_date >= start_date
                )
            ).order_by(desc(FundFlowDaily.trade_date)).limit(5)
        ).scalars().all()
        
        if not flows:
            return 50.0, ["无资金流向数据"]
        
        # 计算主力净流入总和 (转换 Decimal 为 float)
        main_net_sum = float(sum(f.main_net or 0 for f in flows))
        
        if main_net_sum > 0:
            score += min(30, main_net_sum / 1e8 * 10)  # 每亿加10分，最多30分
            factors.append(f"近期主力净流入{main_net_sum/1e8:.2f}亿")
        else:
            score -= min(30, abs(main_net_sum) / 1e8 * 10)
            factors.append(f"近期主力净流出{abs(main_net_sum)/1e8:.2f}亿")
        
        # 检查连续流入/流出
        consecutive_in = sum(1 for f in flows if (f.main_net or 0) > 0)
        if consecutive_in >= 4:
            score += 10
            factors.append("主力连续流入")
        elif consecutive_in <= 1:
            score -= 10
            factors.append("主力持续流出风险")
        
        return max(0, min(100, score)), factors
    
    def _calculate_cycle_score(self, prices: List[PriceDaily]) -> Tuple[float, List[str]]:
        """计算周期规律评分
        
        增强版：
        - 支撑/阻力位分析（30日&60日）
        - 趋势强度分析
        - 波动率分析（ATR方式）
        - 价格动量连续性
        """
        factors = []
        score = 50.0
        
        if len(prices) < 30:
            return 50.0, ["数据不足以分析周期"]
        
        closes = [p.close for p in prices if p.close]
        
        # ---- 支撑/阻力位分析 ----
        if len(closes) >= 30:
            current = closes[0]
            high_30 = max(closes[:30])
            low_30 = min(closes[:30])
            
            # 接近支撑位（潜在反弹）
            if current < low_30 * 1.03:
                score += 8
                factors.append(f"接近30日支撑位{low_30:.2f}，可能反弹")
            
            # 突破阻力位
            if current > high_30 * 0.98:
                score += 8
                factors.append(f"接近30日阻力位{high_30:.2f}，突破可期")
        
        # 60日支撑/阻力
        if len(closes) >= 60:
            high_60 = max(closes[:60])
            low_60 = min(closes[:60])
            if current > high_60 * 0.95:
                score += 5
                factors.append("接近60日新高")
            elif current < low_60 * 1.05:
                score -= 5
                factors.append("接近60日新低(风险)")
        
        # ---- 趋势强度（ADX简化版） ----
        if len(closes) >= 20:
            # 用连续上涨/下跌天数衡量趋势
            up_days = 0
            down_days = 0
            for i in range(min(10, len(closes) - 1)):
                if closes[i] > closes[i + 1]:
                    up_days += 1
                elif closes[i] < closes[i + 1]:
                    down_days += 1
            
            if up_days >= 7:
                score += 8
                factors.append(f"近10日{up_days}天上涨，趋势强劲")
            elif down_days >= 7:
                score -= 8
                factors.append(f"近10日{down_days}天下跌，下跌趋势明显(风险)")
        
        # ---- 波动率分析（ATR思路） ----
        if len(prices) >= 20:
            # 使用价格变动幅度（模拟ATR）
            daily_ranges = []
            for i in range(min(20, len(prices))):
                p = prices[i]
                if p.high and p.low and p.close:
                    tr = p.high - p.low
                    daily_ranges.append(tr / p.close)  # 相对波动率
            
            if daily_ranges:
                avg_volatility = sum(daily_ranges) / len(daily_ranges) * 100
                
                if avg_volatility > 4:
                    score -= 3
                    factors.append(f"波动率较高({avg_volatility:.1f}%)，风险加大")
                elif avg_volatility > 3:
                    factors.append(f"波动率偏高({avg_volatility:.1f}%)")
                elif avg_volatility < 1:
                    factors.append(f"波动率极低({avg_volatility:.1f}%)，趋势可能延续")
        
        # ---- 价格动量连续性 ----
        if len(closes) >= 5:
            returns = [(closes[i] - closes[i+1]) / closes[i+1] for i in range(min(4, len(closes)-1))]
            positive_returns = sum(1 for r in returns if r > 0)
            
            if positive_returns == len(returns):
                score += 5
                factors.append("连续上涨，动量持续")
            elif positive_returns == 0:
                score -= 5
                factors.append("连续下跌，动量衰竭")
        
        return max(0, min(100, score)), factors
    
    def _determine_recommendation(self, score: float, factors: List[str]) -> str:
        """确定推荐等级
        
        增强版：综合评分 + 一致性检查
        """
        if score >= self.THRESHOLDS['buy']:
            # 额外检查：如果有明显风险因素，降级为hold
            risk_signals = sum(1 for f in factors if '风险' in f or '死叉' in f or '超买' in f)
            if risk_signals >= 2:
                return 'hold'
            return 'buy'
        elif score < self.THRESHOLDS['sell']:
            return 'sell'
        elif score >= 60:
            # 60-70分区间：检查是否有明显利好因素
            bullish_signals = sum(1 for f in factors if '利好' in f or '金叉' in f or '突破' in f or '反弹' in f)
            if bullish_signals >= 2:
                return 'buy'
            return 'hold'
        else:
            return 'hold'
    
    def _determine_risk_level(self, scores: ScoreBreakdown, factors: List[str]) -> str:
        """确定风险等级"""
        risk_keywords = ['风险', '流出', '弱', '下跌', '负面']
        risk_count = sum(1 for f in factors if any(k in f for k in risk_keywords))
        
        if scores.total < self.THRESHOLDS['high_risk'] or risk_count >= 3:
            return 'high'
        elif scores.total > self.THRESHOLDS['low_risk'] and risk_count <= 1:
            return 'low'
        else:
            return 'medium'
    
    def _calculate_confidence(self, prices: List[PriceDaily], news_stats: Dict, real_data_count: int = 5) -> float:
        """计算置信度
        
        增强版：基于数据完整性、一致性、新鲜度、维度覆盖
        """
        confidence = 0.3
        
        # 维度数据覆盖（最高+0.2）
        # 5维全有真实数据 → +0.2, 4维 → +0.15 ... 0维 → 0
        confidence += real_data_count * 0.04
        
        # 数据充足性（最高+0.25）
        if len(prices) >= 60:
            confidence += 0.25
        elif len(prices) >= 30:
            confidence += 0.15
        elif len(prices) >= 20:
            confidence += 0.1
        
        # 新闻数据覆盖（最高+0.15）
        news_count = news_stats.get('count', 0)
        if news_count >= 10:
            confidence += 0.15
        elif news_count >= 5:
            confidence += 0.1
        elif news_count >= 1:
            confidence += 0.05
        
        # 情感一致性（最高+0.1）
        if news_stats.get('sentiment_avg') is not None:
            if abs(news_stats['sentiment_avg']) > 0.3:
                confidence += 0.1
        
        # 数据新鲜度（最高+0.15）
        if prices:
            latest_trade = prices[0].trade_date
            from app.tasks.scheduler import get_last_trading_day
            expected = get_last_trading_day()
            days_stale = (expected - latest_trade).days if latest_trade else 30
            if days_stale <= 1:
                confidence += 0.15
            elif days_stale <= 3:
                confidence += 0.08
            # 超过3天没更新的数据，置信度不增加
        
        # 多维度一致性检查（最高+0.1）
        # 如果资金流/新闻/技术面方向一致，增加置信度
        positive_count = news_stats.get('positive', 0)
        negative_count = news_stats.get('negative', 0)
        if positive_count > 0 or negative_count > 0:
            dominance = abs(positive_count - negative_count) / (positive_count + negative_count)
            if dominance > 0.6:
                confidence += 0.1
        
        return min(1.0, confidence)
    
    def _generate_summary(self, symbol: str, name: str, scores: ScoreBreakdown, 
                          recommendation: str, risk_level: str,
                          key_factors: List[str], risk_factors: List[str]) -> str:
        """生成分析摘要"""
        name_str = f"{name}({symbol})" if name else symbol
        rec_map = {'buy': '买入', 'hold': '持有', 'sell': '卖出', 'watch': '观望'}
        risk_map = {'low': '低', 'medium': '中', 'high': '高'}
        
        summary = f"{name_str} 综合评分 {scores.total:.1f} 分，建议{rec_map.get(recommendation, '观望')}，风险等级{risk_map.get(risk_level, '中')}。"
        
        if key_factors:
            summary += f" 利好因素：{'、'.join(key_factors[:3])}。"
        
        if risk_factors:
            summary += f" 风险提示：{'、'.join(risk_factors[:3])}。"
        
        return summary
    
    def analyze_watchlist(self, analysis_date: date = None) -> List[AnalysisResult]:
        """分析整个观察列表"""
        if analysis_date is None:
            analysis_date = date.today()
        
        # 获取启用的观察列表
        watchlist = self.session.execute(
            select(Watchlist).where(Watchlist.enabled == True)
        ).scalars().all()
        
        results = []
        for item in watchlist:
            try:
                result = self.analyze_stock(item.symbol, analysis_date)
                if result:
                    results.append(result)
            except Exception as e:
                logger.error(f"Error analyzing {item.symbol}: {e}")
        
        # 按评分排序
        results.sort(key=lambda x: x.scores.total, reverse=True)
        
        return results
    
    def save_analysis_results(self, results: List[AnalysisResult]) -> int:
        """保存分析结果到数据库"""
        saved_count = 0
        
        for result in results:
            try:
                # 检查是否已存在
                existing = self.session.execute(
                    select(DailyAnalysis).where(
                        and_(
                            DailyAnalysis.symbol == result.symbol,
                            DailyAnalysis.analysis_date == result.analysis_date
                        )
                    )
                ).scalar_one_or_none()
                
                if existing:
                    # 更新
                    existing.total_score = result.scores.total
                    existing.technical_score = result.scores.technical
                    existing.fundamental_score = result.scores.fundamental
                    existing.sentiment_score = result.scores.sentiment
                    existing.fund_flow_score = result.scores.fund_flow
                    existing.cycle_score = result.scores.cycle
                    existing.recommendation = result.recommendation
                    existing.risk_level = result.risk_level
                    existing.confidence = result.confidence
                    existing.close_price = result.close_price
                    existing.pct_change = result.pct_change
                    existing.volume = result.volume
                    existing.ma5 = result.ma5
                    existing.ma20 = result.ma20
                    existing.rsi = result.rsi
                    existing.macd = result.macd
                    existing.news_count = result.news_count
                    existing.news_sentiment_avg = result.news_sentiment_avg
                    existing.analysis_summary = result.analysis_summary
                    existing.key_factors = json.dumps(result.key_factors, ensure_ascii=False)
                    existing.risk_factors = json.dumps(result.risk_factors, ensure_ascii=False)
                else:
                    # 插入新记录
                    analysis = DailyAnalysis(
                        symbol=result.symbol,
                        analysis_date=result.analysis_date,
                        total_score=result.scores.total,
                        technical_score=result.scores.technical,
                        fundamental_score=result.scores.fundamental,
                        sentiment_score=result.scores.sentiment,
                        fund_flow_score=result.scores.fund_flow,
                        cycle_score=result.scores.cycle,
                        recommendation=result.recommendation,
                        risk_level=result.risk_level,
                        confidence=result.confidence,
                        close_price=result.close_price,
                        pct_change=result.pct_change,
                        volume=result.volume,
                        ma5=result.ma5,
                        ma20=result.ma20,
                        rsi=result.rsi,
                        macd=result.macd,
                        news_count=result.news_count,
                        news_sentiment_avg=result.news_sentiment_avg,
                        analysis_summary=result.analysis_summary,
                        key_factors=json.dumps(result.key_factors, ensure_ascii=False),
                        risk_factors=json.dumps(result.risk_factors, ensure_ascii=False)
                    )
                    self.session.add(analysis)
                
                # 同时更新 Watchlist 的评分
                watchlist_item = self.session.execute(
                    select(Watchlist).where(Watchlist.symbol == result.symbol)
                ).scalar_one_or_none()
                
                if watchlist_item:
                    watchlist_item.score = result.scores.total
                    watchlist_item.last_analysis_at = datetime.utcnow()
                
                saved_count += 1
                
            except Exception as e:
                logger.error(f"Error saving analysis for {result.symbol}: {e}")
        
        self.session.commit()
        return saved_count
    
    def evaluate_investment_potential(self, symbol: str, lookback_days: int = 90) -> Dict[str, Any]:
        """评估投资潜力
        
        基于历史分析和模拟交易评估股票的投资潜力
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=lookback_days)
        
        # 获取历史分析记录
        analyses = self.session.execute(
            select(DailyAnalysis).where(
                and_(
                    DailyAnalysis.symbol == symbol,
                    DailyAnalysis.analysis_date >= start_date,
                    DailyAnalysis.analysis_date <= end_date
                )
            ).order_by(DailyAnalysis.analysis_date)
        ).scalars().all()
        
        # 获取模拟交易记录
        trades = self.session.execute(
            select(SimulatedTrade).where(
                and_(
                    SimulatedTrade.symbol == symbol,
                    SimulatedTrade.trade_date >= start_date
                )
            ).order_by(SimulatedTrade.trade_date)
        ).scalars().all()
        
        result = {
            'symbol': symbol,
            'evaluation_date': end_date.isoformat(),
            'lookback_days': lookback_days,
            'analysis_count': len(analyses),
            'trade_count': len(trades),
            'avg_score': 0,
            'score_trend': 'stable',
            'total_profit_loss': 0,
            'win_rate': 0,
            'investment_potential': 50,  # 0-100
            'should_remove': False,
            'remove_reason': None
        }
        
        if analyses:
            scores = [a.total_score for a in analyses if a.total_score]
            if scores:
                result['avg_score'] = sum(scores) / len(scores)
                
                # 评分趋势
                if len(scores) >= 5:
                    early_avg = sum(scores[:len(scores)//2]) / (len(scores)//2)
                    late_avg = sum(scores[len(scores)//2:]) / (len(scores) - len(scores)//2)
                    if late_avg > early_avg * 1.1:
                        result['score_trend'] = 'improving'
                    elif late_avg < early_avg * 0.9:
                        result['score_trend'] = 'declining'
        
        if trades:
            # 计算交易盈亏
            sell_trades = [t for t in trades if t.trade_type == 'sell' and t.profit_loss is not None]
            if sell_trades:
                result['total_profit_loss'] = sum(t.profit_loss for t in sell_trades)
                wins = sum(1 for t in sell_trades if t.profit_loss > 0)
                result['win_rate'] = wins / len(sell_trades) * 100
        
        # 计算投资潜力评分
        potential = 50
        
        # 基于平均评分
        if result['avg_score'] >= 70:
            potential += 20
        elif result['avg_score'] < 40:
            potential -= 20
        
        # 基于评分趋势
        if result['score_trend'] == 'improving':
            potential += 10
        elif result['score_trend'] == 'declining':
            potential -= 15
        
        # 基于交易胜率
        if result['win_rate'] >= 60:
            potential += 15
        elif result['win_rate'] < 30 and result['trade_count'] >= 3:
            potential -= 20
        
        result['investment_potential'] = max(0, min(100, potential))
        
        # 判断是否建议移除
        if result['investment_potential'] < 30 and result['analysis_count'] >= 20:
            result['should_remove'] = True
            reasons = []
            if result['avg_score'] < 40:
                reasons.append(f"平均评分仅{result['avg_score']:.1f}分")
            if result['score_trend'] == 'declining':
                reasons.append("评分持续下降")
            if result['win_rate'] < 30 and result['trade_count'] >= 3:
                reasons.append(f"模拟交易胜率仅{result['win_rate']:.1f}%")
            result['remove_reason'] = '，'.join(reasons)
        
        return result

    def generate_enhanced_summary(self, symbol: str, analysis_date: date, result: 'AnalysisResult') -> str:
        """生成增强版分析摘要，整合多维度信息
        
        Args:
            symbol: 股票代码
            analysis_date: 分析日期
            result: 分析结果
        
        Returns:
            增强的分析摘要文本
        """
        parts = []
        
        # 股票基本信息
        name = result.name or symbol
        parts.append(f"{name}({symbol}) 综合评分 {result.scores.total:.1f} 分，")
        
        # 推荐建议
        rec_text = {'buy': '建议买入', 'hold': '建议持有', 'sell': '建议卖出', 'watch': '建议观望'}
        parts.append(f"{rec_text.get(result.recommendation, '持有观望')}。")
        
        # 风险等级
        risk_text = {'low': '低', 'medium': '中', 'high': '高'}
        parts.append(f"风险等级{risk_text.get(result.risk_level, '中')}。")
        
        # 关键利好因素
        if result.key_factors:
            parts.append(f"利好因素：{', '.join(result.key_factors[:3])}。")
        
        # 风险提示
        if result.risk_factors:
            parts.append(f"风险提示：{', '.join(result.risk_factors[:3])}。")
        
        # 新闻情况
        if result.news_count > 0:
            sentiment_desc = ""
            if result.news_sentiment_avg is not None:
                if result.news_sentiment_avg > 0.3:
                    sentiment_desc = "，情感偏正面"
                elif result.news_sentiment_avg < -0.3:
                    sentiment_desc = "，情感偏负面"
            parts.append(f"近期有{result.news_count}篇相关新闻{sentiment_desc}。")
        
        # 技术面简评
        if result.ma5 and result.ma20:
            if result.ma5 > result.ma20:
                parts.append("短期均线上穿长期均线，技术面偏强。")
            else:
                parts.append("短期均线在长期均线下方，技术面偏弱。")
        
        return ''.join(parts)
