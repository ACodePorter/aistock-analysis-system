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
        confidence = self._calculate_confidence(prices, news_stats)
        
        # 收集关键因素
        key_factors = [f for f in tech_factors + fund_factors + sent_factors + flow_factors + cycle_factors if '利好' in f or '突破' in f or '强' in f]
        risk_factors = [f for f in tech_factors + fund_factors + sent_factors + flow_factors + cycle_factors if '风险' in f or '弱' in f or '流出' in f]
        
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
        - 趋势：MA5 vs MA20
        - 动量：近期涨跌幅
        - 波动：振幅
        - 成交量变化
        """
        if len(prices) < 20:
            return 50.0, ["数据不足"]
        
        factors = []
        score = 50.0
        
        closes = [p.close for p in prices if p.close]
        if len(closes) < 20:
            return 50.0, ["价格数据不足"]
        
        # MA5 vs MA20 趋势
        ma5 = sum(closes[:5]) / 5
        ma20 = sum(closes[:20]) / 20
        
        if ma5 > ma20 * 1.02:
            score += 15
            factors.append("MA5上穿MA20，短期趋势强")
        elif ma5 < ma20 * 0.98:
            score -= 10
            factors.append("MA5下穿MA20，短期趋势弱")
        
        # 近5日涨幅
        if len(closes) >= 6:
            recent_return = (closes[0] - closes[5]) / closes[5] * 100
            if recent_return > 5:
                score += 10
                factors.append(f"近5日涨幅{recent_return:.1f}%，动量强")
            elif recent_return < -5:
                score -= 10
                factors.append(f"近5日跌幅{abs(recent_return):.1f}%，动量弱")
        
        # 相对位置（当前价格在20日高低点的位置）
        high_20 = max(closes[:20])
        low_20 = min(closes[:20])
        if high_20 > low_20:
            position = (closes[0] - low_20) / (high_20 - low_20)
            if position > 0.8:
                score += 5
                factors.append("接近20日高点，突破可能性大")
            elif position < 0.2:
                score -= 5
                factors.append("接近20日低点，存在下跌风险")
        
        # 成交量分析
        vols = [p.vol for p in prices[:20] if p.vol]
        if len(vols) >= 5:
            avg_vol = sum(vols) / len(vols)
            recent_vol = sum(vols[:5]) / 5
            if recent_vol > avg_vol * 1.5:
                score += 5
                factors.append("成交量放大，关注度提升")
            elif recent_vol < avg_vol * 0.5:
                score -= 5
                factors.append("成交量萎缩")
        
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
        """计算新闻情感评分"""
        factors = []
        score = 50.0
        stats = {'count': 0, 'sentiment_avg': None}
        
        # 获取最近7天的相关新闻
        start_date = analysis_date - timedelta(days=7)
        
        articles = self.session.execute(
            select(NewsArticle).where(
                and_(
                    NewsArticle.related_stocks.contains([symbol]),
                    NewsArticle.published_at >= start_date,
                    NewsArticle.published_at <= analysis_date
                )
            )
        ).scalars().all()
        
        stats['count'] = len(articles)
        
        if not articles:
            return 50.0, ["近期无相关新闻"], stats
        
        # 计算情感分数
        sentiments = [a.sentiment_score for a in articles if a.sentiment_score is not None]
        if sentiments:
            avg_sentiment = sum(sentiments) / len(sentiments)
            stats['sentiment_avg'] = avg_sentiment
            
            # 情感分数范围 -1 到 1，转换为 0-100
            score = 50 + avg_sentiment * 50
            
            if avg_sentiment > 0.3:
                factors.append(f"新闻情感偏正面({avg_sentiment:.2f})")
            elif avg_sentiment < -0.3:
                factors.append(f"新闻情感偏负面({avg_sentiment:.2f})")
            else:
                factors.append("新闻情感中性")
        
        # 新闻数量因素
        if len(articles) > 10:
            score += 5
            factors.append(f"近期热度高({len(articles)}篇新闻)")
        
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
        
        分析价格的周期性模式
        """
        factors = []
        score = 50.0
        
        if len(prices) < 30:
            return 50.0, ["数据不足以分析周期"]
        
        closes = [p.close for p in prices if p.close]
        
        # 简单周期分析：检查是否在历史支撑/阻力位附近
        if len(closes) >= 30:
            current = closes[0]
            high_30 = max(closes[:30])
            low_30 = min(closes[:30])
            
            # 接近支撑位（潜在反弹）
            if current < low_30 * 1.05:
                score += 10
                factors.append("接近30日支撑位，可能反弹")
            
            # 突破阻力位
            if current > high_30 * 0.98:
                score += 10
                factors.append("接近30日阻力位，突破可期")
        
        # 波动率分析
        if len(closes) >= 20:
            returns = [(closes[i] - closes[i+1]) / closes[i+1] for i in range(min(19, len(closes)-1))]
            volatility = (sum(r**2 for r in returns) / len(returns)) ** 0.5
            
            if volatility > 0.03:  # 日均波动>3%
                factors.append(f"波动率较高({volatility*100:.1f}%)")
            elif volatility < 0.01:
                factors.append("波动率较低，趋势稳定")
        
        return max(0, min(100, score)), factors
    
    def _determine_recommendation(self, score: float, factors: List[str]) -> str:
        """确定推荐等级"""
        if score >= self.THRESHOLDS['buy']:
            return 'buy'
        elif score < self.THRESHOLDS['sell']:
            return 'sell'
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
    
    def _calculate_confidence(self, prices: List[PriceDaily], news_stats: Dict) -> float:
        """计算置信度"""
        confidence = 0.5
        
        # 数据充足性
        if len(prices) >= 30:
            confidence += 0.2
        elif len(prices) >= 20:
            confidence += 0.1
        
        # 新闻数据
        if news_stats.get('count', 0) > 5:
            confidence += 0.1
        
        # 情感一致性
        if news_stats.get('sentiment_avg') is not None:
            if abs(news_stats['sentiment_avg']) > 0.3:
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
