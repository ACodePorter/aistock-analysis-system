"""
每日报告生成器 - 使用 LLM 生成综合分析报告
"""

import logging
import json
import os
from datetime import date, datetime
from typing import List, Dict, Any, Optional

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.core.models import DailyAnalysis, DailyReport, Watchlist
from app.analysis.analysis_engine import AnalysisResult

logger = logging.getLogger(__name__)


class DailyReportGenerator:
    """每日报告生成器"""
    
    def __init__(self, session: Session):
        self.session = session
        self.llm_client = None
        self._init_llm_client()
    
    def _init_llm_client(self):
        """初始化 LLM 客户端"""
        try:
            from openai import AzureOpenAI
            
            endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
            api_key = os.getenv("AZURE_OPENAI_API_KEY")
            
            if endpoint and api_key:
                self.llm_client = AzureOpenAI(
                    azure_endpoint=endpoint,
                    api_key=api_key,
                    api_version="2024-02-15-preview"
                )
                logger.info("LLM client initialized successfully")
            else:
                logger.warning("Azure OpenAI credentials not configured")
        except Exception as e:
            logger.error(f"Failed to initialize LLM client: {e}")
    
    def generate_report(self, report_date: date, results: List[AnalysisResult] = None) -> Optional[DailyReport]:
        """生成每日综合报告
        
        Args:
            report_date: 报告日期
            results: 分析结果列表（如果为空则从数据库获取）
            
        Returns:
            DailyReport 对象
        """
        # 如果没有传入结果，从数据库获取
        if results is None:
            analyses = self.session.execute(
                select(DailyAnalysis).where(DailyAnalysis.analysis_date == report_date)
            ).scalars().all()
            
            if not analyses:
                logger.warning(f"No analysis data for {report_date}")
                return None
            
            # 转换为结果格式
            results = self._analyses_to_results(analyses)
        
        # 分类推荐
        buy_list = [r for r in results if r.recommendation == 'buy']
        hold_list = [r for r in results if r.recommendation == 'hold']
        sell_list = [r for r in results if r.recommendation == 'sell']
        
        # 生成 LLM 综合分析
        comprehensive_analysis = self._generate_llm_analysis(results, buy_list, hold_list, sell_list)
        
        # 判断市场情绪
        avg_score = sum(r.scores.total for r in results) / len(results) if results else 50
        if avg_score >= 65:
            market_sentiment = 'bullish'
        elif avg_score <= 45:
            market_sentiment = 'bearish'
        else:
            market_sentiment = 'neutral'
        
        # 生成市场摘要
        market_summary = self._generate_market_summary(results, market_sentiment)
        
        # 收集风险预警
        risk_warnings = self._collect_risk_warnings(results)
        
        # 收集机会提示
        opportunities = self._collect_opportunities(buy_list)
        
        # 行业分析
        sector_analysis = self._analyze_sectors(results)
        
        # 创建或更新报告
        existing = self.session.execute(
            select(DailyReport).where(DailyReport.report_date == report_date)
        ).scalar_one_or_none()
        
        if existing:
            report = existing
        else:
            report = DailyReport(report_date=report_date)
            self.session.add(report)
        
        # 填充数据
        report.total_stocks = len(results)
        report.buy_count = len(buy_list)
        report.hold_count = len(hold_list)
        report.sell_count = len(sell_list)
        report.market_sentiment = market_sentiment
        report.market_summary = market_summary
        report.buy_recommendations = json.dumps(
            [self._result_to_recommendation(r) for r in buy_list], 
            ensure_ascii=False
        )
        report.hold_recommendations = json.dumps(
            [self._result_to_recommendation(r) for r in hold_list],
            ensure_ascii=False
        )
        report.sell_recommendations = json.dumps(
            [self._result_to_recommendation(r) for r in sell_list],
            ensure_ascii=False
        )
        report.comprehensive_analysis = comprehensive_analysis
        report.risk_warnings = json.dumps(risk_warnings, ensure_ascii=False)
        report.opportunities = json.dumps(opportunities, ensure_ascii=False)
        report.sector_analysis = json.dumps(sector_analysis, ensure_ascii=False)
        report.generated_at = datetime.utcnow()
        report.generation_model = "gpt-4o" if self.llm_client else "rule-based"
        
        self.session.commit()
        
        logger.info(f"Generated daily report for {report_date}: {len(results)} stocks analyzed")
        
        return report
    
    def _analyses_to_results(self, analyses: List[DailyAnalysis]) -> List[AnalysisResult]:
        """将数据库分析记录转换为 AnalysisResult"""
        from app.analysis.analysis_engine import ScoreBreakdown
        
        results = []
        for a in analyses:
            # 获取股票名称
            watchlist = self.session.execute(
                select(Watchlist).where(Watchlist.symbol == a.symbol)
            ).scalar_one_or_none()
            
            scores = ScoreBreakdown(
                technical=a.technical_score or 50,
                fundamental=a.fundamental_score or 50,
                sentiment=a.sentiment_score or 50,
                fund_flow=a.fund_flow_score or 50,
                cycle=a.cycle_score or 50,
                total=a.total_score or 50
            )
            
            key_factors = json.loads(a.key_factors) if a.key_factors else []
            risk_factors = json.loads(a.risk_factors) if a.risk_factors else []
            
            result = AnalysisResult(
                symbol=a.symbol,
                name=watchlist.name if watchlist else None,
                sector=watchlist.sector if watchlist else None,
                analysis_date=a.analysis_date,
                scores=scores,
                recommendation=a.recommendation or 'hold',
                risk_level=a.risk_level or 'medium',
                confidence=a.confidence or 0.5,
                close_price=a.close_price,
                pct_change=a.pct_change,
                volume=a.volume,
                ma5=a.ma5,
                ma20=a.ma20,
                rsi=a.rsi,
                macd=a.macd,
                news_count=a.news_count or 0,
                news_sentiment_avg=a.news_sentiment_avg,
                analysis_summary=a.analysis_summary or '',
                key_factors=key_factors,
                risk_factors=risk_factors
            )
            results.append(result)
        
        return results
    
    def _result_to_recommendation(self, r: AnalysisResult) -> Dict[str, Any]:
        """将分析结果转换为推荐格式"""
        return {
            'symbol': r.symbol,
            'name': r.name,
            'sector': r.sector,
            'score': r.scores.total,
            'risk_level': r.risk_level,
            'confidence': r.confidence,
            'close_price': r.close_price,
            'pct_change': r.pct_change,
            'summary': r.analysis_summary,
            'key_factors': r.key_factors[:3]
        }
    
    def _generate_market_summary(self, results: List[AnalysisResult], sentiment: str) -> str:
        """生成市场摘要"""
        total = len(results)
        buy_count = sum(1 for r in results if r.recommendation == 'buy')
        sell_count = sum(1 for r in results if r.recommendation == 'sell')
        avg_score = sum(r.scores.total for r in results) / total if total else 50
        
        sentiment_text = {'bullish': '偏多', 'bearish': '偏空', 'neutral': '中性'}
        
        summary = f"今日分析了{total}只观察列表股票，市场情绪{sentiment_text.get(sentiment, '中性')}。"
        summary += f"平均评分{avg_score:.1f}分，其中{buy_count}只建议买入，{sell_count}只建议卖出。"
        
        # 找出表现最好的股票
        if results:
            top = max(results, key=lambda x: x.scores.total)
            summary += f"评分最高的是{top.name or top.symbol}（{top.scores.total:.1f}分）。"
        
        return summary
    
    def _collect_risk_warnings(self, results: List[AnalysisResult]) -> List[Dict[str, Any]]:
        """收集风险预警"""
        warnings = []
        
        for r in results:
            if r.risk_level == 'high':
                warnings.append({
                    'symbol': r.symbol,
                    'name': r.name,
                    'level': 'high',
                    'factors': r.risk_factors
                })
        
        return warnings
    
    def _collect_opportunities(self, buy_list: List[AnalysisResult]) -> List[Dict[str, Any]]:
        """收集机会提示"""
        opportunities = []
        
        for r in sorted(buy_list, key=lambda x: x.scores.total, reverse=True)[:5]:
            opportunities.append({
                'symbol': r.symbol,
                'name': r.name,
                'score': r.scores.total,
                'confidence': r.confidence,
                'key_factors': r.key_factors
            })
        
        return opportunities
    
    def _analyze_sectors(self, results: List[AnalysisResult]) -> Dict[str, Any]:
        """分析行业表现"""
        sector_data = {}
        
        for r in results:
            sector = r.sector or '未分类'
            if sector not in sector_data:
                sector_data[sector] = {
                    'stocks': [],
                    'total_score': 0,
                    'count': 0
                }
            sector_data[sector]['stocks'].append(r.symbol)
            sector_data[sector]['total_score'] += r.scores.total
            sector_data[sector]['count'] += 1
        
        # 计算平均分并排序
        for sector in sector_data:
            sector_data[sector]['avg_score'] = (
                sector_data[sector]['total_score'] / sector_data[sector]['count']
            )
        
        return sector_data
    
    def _generate_llm_analysis(self, results: List[AnalysisResult],
                               buy_list: List[AnalysisResult],
                               hold_list: List[AnalysisResult],
                               sell_list: List[AnalysisResult]) -> str:
        """使用 LLM 生成综合分析"""
        
        if not self.llm_client:
            return self._generate_rule_based_analysis(results, buy_list, hold_list, sell_list)
        
        try:
            # 构建提示
            prompt = self._build_analysis_prompt(results, buy_list, hold_list, sell_list)
            
            response = self.llm_client.chat.completions.create(
                model=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
                messages=[
                    {
                        "role": "system",
                        "content": "你是一位资深A股投资分析师，擅长技术分析和基本面研究。你的报告以数据为驱动，给出明确的买卖建议、参考价位和仓位管理策略。你始终提醒投资者注意风险，但不回避给出明确的操作建议。你的目标是帮助投资者做出可执行的投资决策。"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=2000,
                temperature=0.7
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"LLM analysis generation failed: {e}")
            return self._generate_rule_based_analysis(results, buy_list, hold_list, sell_list)
    
    def _build_analysis_prompt(self, results: List[AnalysisResult],
                               buy_list: List[AnalysisResult],
                               hold_list: List[AnalysisResult],
                               sell_list: List[AnalysisResult]) -> str:
        """构建 LLM 分析提示"""
        avg_score = sum(r.scores.total for r in results) / len(results) if results else 50
        
        prompt = f"""请根据以下A股股票分析数据，生成一份专业、可操作的每日投资分析报告。报告须具有明确的买卖指导价值。

## 今日分析概况
- 分析股票数：{len(results)}只
- 推荐买入：{len(buy_list)}只 | 建议持有：{len(hold_list)}只 | 建议卖出：{len(sell_list)}只
- 平均评分：{avg_score:.1f}分

## 推荐买入股票详细数据
"""
        for r in sorted(buy_list, key=lambda x: x.scores.total, reverse=True)[:5]:
            tech_detail = f"技术{r.scores.technical:.0f}/基本面{r.scores.fundamental:.0f}/情绪{r.scores.sentiment:.0f}/资金{r.scores.fund_flow:.0f}/周期{r.scores.cycle:.0f}"
            prompt += f"""- **{r.name or r.symbol}**({r.symbol}): 综合{r.scores.total:.1f}分, 置信度{r.confidence:.0%}
  收盘¥{r.close_price or 0:.2f}, 涨跌{r.pct_change or 0:+.2f}%, MA5={r.ma5 or 0:.2f}, MA20={r.ma20 or 0:.2f}, RSI={r.rsi or 0:.1f}
  五维评分: {tech_detail}
  利好因素: {', '.join(r.key_factors[:3]) or '无'}
  风险因素: {', '.join(r.risk_factors[:2]) or '无'}
  新闻情报: {r.news_count}篇, 情感均值{r.news_sentiment_avg or 0.5:.2f}
"""
        
        prompt += "\n## 建议卖出/高风险股票\n"
        for r in sorted(sell_list, key=lambda x: x.scores.total)[:5]:
            prompt += f"""- **{r.name or r.symbol}**({r.symbol}): 综合{r.scores.total:.1f}分, 收盘¥{r.close_price or 0:.2f}, 涨跌{r.pct_change or 0:+.2f}%
  风险因素: {', '.join(r.risk_factors[:3]) or '无'}
"""
        
        prompt += f"""
## 报告要求（严格按以下结构输出）

### 一、市场整体研判
- 用2-3句话概括今日A股市场走势和资金动向
- 明确给出短期（1-3天）市场方向判断

### 二、重点推荐股票分析（选2-3只评分最高的详细分析）
对每只股票须包含：
- **买入逻辑**：为什么现在值得买入（技术面+基本面+消息面综合判断）
- **参考介入价位**：基于MA和支撑位给出合理买入区间
- **目标价位**：基于阻力位和趋势给出短期目标
- **止损位**：给出明确的止损参考价位
- **仓位建议**：建议占总仓位的百分比

### 三、风险警示
- 对高风险/建议卖出的股票给出明确的操作建议
- 如持有则给出减仓/止损建议

### 四、今日操作策略
- 给出2-3条具体可执行的操作建议
- 整体仓位建议（轻仓/半仓/重仓）

请用中文输出，专业客观，控制在800字以内。数据驱动，不说空话。
"""
        return prompt
    
    def _generate_rule_based_analysis(self, results: List[AnalysisResult],
                                      buy_list: List[AnalysisResult],
                                      hold_list: List[AnalysisResult],
                                      sell_list: List[AnalysisResult]) -> str:
        """基于规则生成分析（LLM 不可用时的降级方案）"""
        
        total = len(results)
        avg_score = sum(r.scores.total for r in results) / total if total else 50
        
        report = f"## 每日分析报告\n\n"
        report += f"### 一、市场整体研判\n"
        report += f"今日共分析{total}只观察列表股票，平均评分{avg_score:.1f}分。"
        
        if avg_score >= 65:
            report += "整体市场情绪偏多，短期看涨概率较大，建议适度加仓至六到七成。\n\n"
        elif avg_score <= 45:
            report += "整体市场情绪偏空，短期回调风险较大，建议降低仓位至三成以下。\n\n"
        else:
            report += "整体市场处于震荡格局，建议维持半仓，精选个股操作。\n\n"
        
        if buy_list:
            sorted_buys = sorted(buy_list, key=lambda x: x.scores.total, reverse=True)
            report += f"### 二、重点推荐（{len(buy_list)}只）\n"
            for r in sorted_buys[:3]:
                report += f"\n**{r.name or r.symbol}**（{r.symbol}）— 综合评分{r.scores.total:.1f}分，置信度{r.confidence:.0%}\n"
                report += f"- 收盘价：¥{r.close_price or 0:.2f}，涨跌幅：{r.pct_change or 0:+.2f}%\n"
                if r.ma5 and r.ma20 and r.close_price:
                    if r.close_price > r.ma5 > r.ma20:
                        report += f"- 技术面：多头排列（价>{r.ma5:.2f}>{r.ma20:.2f}），趋势良好\n"
                    elif r.close_price > r.ma20:
                        report += f"- 技术面：站上20日均线{r.ma20:.2f}，短期支撑有效\n"
                    else:
                        report += f"- 技术面：均线{r.ma5:.2f}/{r.ma20:.2f}附近，关注突破方向\n"
                if r.key_factors:
                    report += f"- 买入逻辑：{', '.join(r.key_factors[:3])}\n"
                if r.risk_factors:
                    report += f"- 注意风险：{', '.join(r.risk_factors[:2])}\n"
                # 参考价位
                if r.close_price and r.ma20:
                    report += f"- 参考介入区间：¥{min(r.close_price, r.ma20) * 0.98:.2f} - ¥{r.close_price:.2f}\n"
                    report += f"- 建议止损位：¥{r.ma20 * 0.95:.2f}\n"
            report += "\n"
        
        if sell_list:
            report += f"### 三、风险警示（{len(sell_list)}只）\n"
            for r in sell_list[:3]:
                report += f"- **{r.name or r.symbol}**（{r.symbol}）：评分{r.scores.total:.1f}分，风险等级{r.risk_level}\n"
                if r.risk_factors:
                    report += f"  风险因素：{', '.join(r.risk_factors[:3])}\n"
                if r.close_price and r.ma20:
                    report += f"  当前价¥{r.close_price:.2f}，建议在¥{r.close_price * 1.02:.2f}以上减仓\n"
            report += "\n"
        
        report += "### 四、操作策略\n"
        if avg_score >= 65:
            report += "1. 推荐股票可逢低分批建仓，单只不超过总仓位15%\n"
            report += "2. 整体仓位可维持在六到七成\n"
        elif avg_score <= 45:
            report += "1. 控制仓位在三成以下，以防守为主\n"
            report += "2. 高风险股票果断止损，不抱侥幸心理\n"
        else:
            report += "1. 精选高评分个股轻仓试探，单只不超过10%\n"
            report += "2. 维持半仓操作，保留足够现金应对变化\n"
        report += "3. 严格执行止损纪律，亏损超过5%坚决离场\n"
        
        return report
    
    def get_report(self, report_date: date) -> Optional[Dict[str, Any]]:
        """获取指定日期的报告"""
        report = self.session.execute(
            select(DailyReport).where(DailyReport.report_date == report_date)
        ).scalar_one_or_none()
        
        if not report:
            return None
        
        return {
            'report_date': report.report_date.isoformat(),
            'total_stocks': report.total_stocks,
            'buy_count': report.buy_count,
            'hold_count': report.hold_count,
            'sell_count': report.sell_count,
            'market_sentiment': report.market_sentiment,
            'market_summary': report.market_summary,
            'buy_recommendations': json.loads(report.buy_recommendations) if report.buy_recommendations else [],
            'hold_recommendations': json.loads(report.hold_recommendations) if report.hold_recommendations else [],
            'sell_recommendations': json.loads(report.sell_recommendations) if report.sell_recommendations else [],
            'comprehensive_analysis': report.comprehensive_analysis,
            'risk_warnings': json.loads(report.risk_warnings) if report.risk_warnings else [],
            'opportunities': json.loads(report.opportunities) if report.opportunities else [],
            'sector_analysis': json.loads(report.sector_analysis) if report.sector_analysis else {},
            'generated_at': report.generated_at.isoformat() if report.generated_at else None,
            'generation_model': report.generation_model
        }
