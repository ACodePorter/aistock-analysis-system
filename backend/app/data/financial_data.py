"""
财务数据采集模块

提供A股财务指标数据采集功能：
- PE/PB/PS/PCF 估值指标
- ROE/ROA/毛利率/净利率 盈利能力
- EPS/营收/净利润增长 成长性
- 资产负债率/流动比率 偿债能力
- 机构评级/目标价

数据源：AKShare (优先) / Tushare (备用)
"""

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from decimal import Decimal

import pandas as pd

logger = logging.getLogger(__name__)

# 尝试导入 akshare
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    ak = None
    logger.warning("akshare 不可用，财务数据采集功能受限")


@dataclass
class FinancialIndicators:
    """财务指标数据类"""
    symbol: str
    trade_date: date
    
    # 估值指标
    pe_ttm: Optional[float] = None          # 滚动市盈率
    pe_static: Optional[float] = None       # 静态市盈率
    pb: Optional[float] = None              # 市净率
    ps_ttm: Optional[float] = None          # 滚动市销率
    pcf_ttm: Optional[float] = None         # 滚动市现率
    market_cap: Optional[float] = None      # 总市值（亿元）
    circulating_cap: Optional[float] = None # 流通市值（亿元）
    
    # 盈利能力
    roe: Optional[float] = None             # 净资产收益率 %
    roa: Optional[float] = None             # 总资产收益率 %
    gross_margin: Optional[float] = None    # 毛利率 %
    net_margin: Optional[float] = None      # 净利率 %
    
    # 成长性
    eps: Optional[float] = None             # 每股收益
    eps_yoy: Optional[float] = None         # EPS同比增长 %
    revenue: Optional[float] = None         # 营收（亿元）
    revenue_yoy: Optional[float] = None     # 营收同比增长 %
    net_profit: Optional[float] = None      # 净利润（亿元）
    net_profit_yoy: Optional[float] = None  # 净利润同比增长 %
    
    # 偿债能力
    debt_ratio: Optional[float] = None      # 资产负债率 %
    current_ratio: Optional[float] = None   # 流动比率
    quick_ratio: Optional[float] = None     # 速动比率
    
    # 分红
    dividend_yield: Optional[float] = None  # 股息率 %
    
    # 数据时间戳
    report_period: Optional[str] = None     # 财报期（如 2025Q3）
    updated_at: Optional[datetime] = None
    
    def to_dict(self) -> dict:
        d = asdict(self)
        if d['trade_date']:
            d['trade_date'] = d['trade_date'].isoformat()
        if d['updated_at']:
            d['updated_at'] = d['updated_at'].isoformat()
        return d


@dataclass
class AnalystRating:
    """机构评级数据"""
    symbol: str
    rating_date: date
    
    institution: str                        # 机构名称
    analyst: Optional[str] = None           # 分析师
    rating: Optional[str] = None            # 评级（买入/增持/中性/减持/卖出）
    target_price: Optional[float] = None    # 目标价
    eps_forecast_1y: Optional[float] = None # 当年EPS预测
    eps_forecast_2y: Optional[float] = None # 明年EPS预测
    
    def to_dict(self) -> dict:
        d = asdict(self)
        if d['rating_date']:
            d['rating_date'] = d['rating_date'].isoformat()
        return d


class FinancialDataFetcher:
    """财务数据采集器"""
    
    def __init__(self):
        self.cache: Dict[str, Any] = {}
        self.cache_ttl = 3600  # 缓存1小时
    
    def _normalize_symbol(self, symbol: str) -> str:
        """标准化股票代码为akshare格式（纯数字）"""
        return symbol.split('.')[0]
    
    def _get_exchange(self, symbol: str) -> str:
        """获取交易所"""
        if '.SH' in symbol.upper():
            return 'SH'
        elif '.SZ' in symbol.upper():
            return 'SZ'
        else:
            code = symbol.split('.')[0]
            if code.startswith(('6', '9')):
                return 'SH'
            else:
                return 'SZ'
    
    def fetch_valuation_indicators(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取估值指标
        
        包含：PE/PB/PS/PCF/市值等
        """
        if not AKSHARE_AVAILABLE:
            logger.warning("akshare 不可用")
            return None
        
        code = self._normalize_symbol(symbol)
        
        try:
            # 使用 stock_a_lg_indicator_em 获取估值指标
            df = ak.stock_a_lg_indicator_em(symbol=code)
            
            if df.empty:
                logger.warning(f"未获取到 {symbol} 的估值数据")
                return None
            
            # 取最新一行
            latest = df.iloc[-1]
            
            return {
                'pe_ttm': self._safe_float(latest.get('pe_ttm') or latest.get('市盈率(TTM)')),
                'pb': self._safe_float(latest.get('pb') or latest.get('市净率')),
                'ps_ttm': self._safe_float(latest.get('ps_ttm') or latest.get('市销率(TTM)')),
                'pcf_ttm': self._safe_float(latest.get('pcf_ttm') or latest.get('市现率(TTM)')),
                'market_cap': self._safe_float(latest.get('总市值')) / 1e8 if latest.get('总市值') else None,
                'trade_date': pd.to_datetime(latest.get('trade_date') or latest.name).date() if hasattr(latest, 'name') else date.today()
            }
        except Exception as e:
            logger.error(f"获取 {symbol} 估值指标失败: {e}")
            return None
    
    def fetch_financial_report(self, symbol: str, period: str = None) -> Optional[Dict[str, Any]]:
        """获取财务报表数据
        
        Args:
            symbol: 股票代码
            period: 报告期，如 '2025Q3'，默认取最新
        
        Returns:
            财务指标字典
        """
        if not AKSHARE_AVAILABLE:
            return None
        
        code = self._normalize_symbol(symbol)
        
        try:
            # 获取主要财务指标
            df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
            
            if df.empty:
                # 尝试东方财富数据源
                df = ak.stock_financial_analysis_indicator(symbol=code)
            
            if df.empty:
                logger.warning(f"未获取到 {symbol} 的财务数据")
                return None
            
            # 取最新一期
            latest = df.iloc[0] if not df.empty else {}
            
            return {
                'roe': self._safe_float(latest.get('净资产收益率') or latest.get('roe')),
                'gross_margin': self._safe_float(latest.get('销售毛利率') or latest.get('毛利率')),
                'net_margin': self._safe_float(latest.get('销售净利率') or latest.get('净利率')),
                'debt_ratio': self._safe_float(latest.get('资产负债率')),
                'current_ratio': self._safe_float(latest.get('流动比率')),
                'eps': self._safe_float(latest.get('基本每股收益') or latest.get('eps')),
                'report_period': str(latest.get('报告期', '')),
            }
        except Exception as e:
            logger.error(f"获取 {symbol} 财报数据失败: {e}")
            return None
    
    def fetch_growth_indicators(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取成长性指标
        
        包含：营收增长、净利润增长、EPS增长等
        """
        if not AKSHARE_AVAILABLE:
            return None
        
        code = self._normalize_symbol(symbol)
        
        try:
            # 获取业绩报表
            df = ak.stock_yjbb_em(date="")  # 获取最新业绩报表
            
            if df.empty:
                return None
            
            # 筛选目标股票
            stock_data = df[df['股票代码'] == code]
            if stock_data.empty:
                return None
            
            latest = stock_data.iloc[0]
            
            return {
                'eps': self._safe_float(latest.get('每股收益')),
                'eps_yoy': self._safe_float(latest.get('每股收益同比增长')),
                'revenue': self._safe_float(latest.get('营业收入')) / 1e8 if latest.get('营业收入') else None,
                'revenue_yoy': self._safe_float(latest.get('营业收入同比增长')),
                'net_profit': self._safe_float(latest.get('净利润')) / 1e8 if latest.get('净利润') else None,
                'net_profit_yoy': self._safe_float(latest.get('净利润同比增长')),
            }
        except Exception as e:
            logger.error(f"获取 {symbol} 成长指标失败: {e}")
            return None
    
    def fetch_dividend_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取分红信息"""
        if not AKSHARE_AVAILABLE:
            return None
        
        code = self._normalize_symbol(symbol)
        
        try:
            # 获取分红配送
            df = ak.stock_fhps_em(symbol=code)
            
            if df.empty:
                return {'dividend_yield': None}
            
            # 计算近12个月股息率
            recent_dividends = df[df['除权除息日'].notna()].head(4)  # 最近4次
            total_dividend = recent_dividends['派息(税前)(元)'].sum() if '派息(税前)(元)' in recent_dividends.columns else 0
            
            return {
                'dividend_yield': self._safe_float(total_dividend),  # 需要除以股价计算真实股息率
                'last_dividend_date': recent_dividends.iloc[0]['除权除息日'] if not recent_dividends.empty else None
            }
        except Exception as e:
            logger.error(f"获取 {symbol} 分红信息失败: {e}")
            return None
    
    def fetch_analyst_ratings(self, symbol: str, days: int = 90) -> List[AnalystRating]:
        """获取机构评级
        
        Args:
            symbol: 股票代码
            days: 获取最近N天的评级
        
        Returns:
            评级列表
        """
        if not AKSHARE_AVAILABLE:
            return []
        
        code = self._normalize_symbol(symbol)
        ratings = []
        
        try:
            # 获取机构评级
            df = ak.stock_comment_em()
            
            if df.empty:
                return []
            
            # 筛选目标股票
            stock_data = df[df['代码'] == code]
            if stock_data.empty:
                return []
            
            latest = stock_data.iloc[0]
            
            # 解析综合评级
            rating_map = {
                '买入': 'buy',
                '增持': 'outperform', 
                '中性': 'neutral',
                '减持': 'underperform',
                '卖出': 'sell'
            }
            
            ratings.append(AnalystRating(
                symbol=symbol,
                rating_date=date.today(),
                institution='综合',
                rating=rating_map.get(latest.get('综合评级'), 'neutral'),
                target_price=self._safe_float(latest.get('目标价'))
            ))
            
        except Exception as e:
            logger.error(f"获取 {symbol} 机构评级失败: {e}")
        
        return ratings
    
    def fetch_all_indicators(self, symbol: str) -> FinancialIndicators:
        """获取所有财务指标（聚合）
        
        Args:
            symbol: 股票代码
        
        Returns:
            FinancialIndicators 数据类
        """
        indicators = FinancialIndicators(
            symbol=symbol,
            trade_date=date.today(),
            updated_at=datetime.now()
        )
        
        # 获取估值指标
        valuation = self.fetch_valuation_indicators(symbol)
        if valuation:
            indicators.pe_ttm = valuation.get('pe_ttm')
            indicators.pb = valuation.get('pb')
            indicators.ps_ttm = valuation.get('ps_ttm')
            indicators.pcf_ttm = valuation.get('pcf_ttm')
            indicators.market_cap = valuation.get('market_cap')
        
        # 获取财务报表
        financial = self.fetch_financial_report(symbol)
        if financial:
            indicators.roe = financial.get('roe')
            indicators.gross_margin = financial.get('gross_margin')
            indicators.net_margin = financial.get('net_margin')
            indicators.debt_ratio = financial.get('debt_ratio')
            indicators.current_ratio = financial.get('current_ratio')
            indicators.eps = financial.get('eps')
            indicators.report_period = financial.get('report_period')
        
        # 获取成长指标
        growth = self.fetch_growth_indicators(symbol)
        if growth:
            indicators.eps_yoy = growth.get('eps_yoy')
            indicators.revenue = growth.get('revenue')
            indicators.revenue_yoy = growth.get('revenue_yoy')
            indicators.net_profit = growth.get('net_profit')
            indicators.net_profit_yoy = growth.get('net_profit_yoy')
        
        # 获取分红信息
        dividend = self.fetch_dividend_info(symbol)
        if dividend:
            indicators.dividend_yield = dividend.get('dividend_yield')
        
        return indicators
    
    def _safe_float(self, value) -> Optional[float]:
        """安全转换为浮点数"""
        if value is None or pd.isna(value):
            return None
        try:
            if isinstance(value, str):
                value = value.replace('%', '').replace(',', '')
            return float(value)
        except (ValueError, TypeError):
            return None


class NorthboundFlowFetcher:
    """北向资金数据采集器"""
    
    def fetch_daily_flow(self, trade_date: date = None) -> Optional[Dict[str, Any]]:
        """获取北向资金每日流向
        
        Returns:
            {
                'date': 日期,
                'sh_net': 沪股通净流入（亿元）,
                'sz_net': 深股通净流入（亿元）,
                'total_net': 北向资金净流入合计（亿元）,
                'sh_buy': 沪股通买入,
                'sh_sell': 沪股通卖出,
                'sz_buy': 深股通买入,
                'sz_sell': 深股通卖出
            }
        """
        if not AKSHARE_AVAILABLE:
            return None
        
        try:
            # 获取北向资金数据
            df = ak.stock_hsgt_north_net_flow_in_em(symbol="北上")
            
            if df.empty:
                return None
            
            # 如果指定日期，筛选；否则取最新
            if trade_date:
                df['日期'] = pd.to_datetime(df['日期']).dt.date
                row = df[df['日期'] == trade_date]
                if row.empty:
                    return None
                row = row.iloc[0]
            else:
                row = df.iloc[-1]
            
            return {
                'date': pd.to_datetime(row['日期']).date() if '日期' in row.index else date.today(),
                'sh_net': float(row.get('沪股通净流入', 0) or 0),
                'sz_net': float(row.get('深股通净流入', 0) or 0),
                'total_net': float(row.get('北向资金净流入', 0) or 0),
            }
        except Exception as e:
            logger.error(f"获取北向资金数据失败: {e}")
            return None
    
    def fetch_stock_holding(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取个股北向持仓数据
        
        Args:
            symbol: 股票代码
        
        Returns:
            北向持仓信息
        """
        if not AKSHARE_AVAILABLE:
            return None
        
        code = symbol.split('.')[0]
        
        try:
            # 获取沪深港通持股
            df = ak.stock_hsgt_hold_stock_em(market="北向", indicator="今日排行")
            
            if df.empty:
                return None
            
            # 筛选目标股票
            stock_data = df[df['代码'] == code]
            if stock_data.empty:
                return None
            
            row = stock_data.iloc[0]
            
            return {
                'symbol': symbol,
                'holding_shares': float(row.get('持股数量', 0) or 0),
                'holding_value': float(row.get('持股市值', 0) or 0) / 1e8,  # 转为亿元
                'holding_ratio': float(row.get('持股占比', 0) or 0),
                'change_shares': float(row.get('日增持股数', 0) or 0),
            }
        except Exception as e:
            logger.error(f"获取 {symbol} 北向持仓失败: {e}")
            return None


class DragonTigerFetcher:
    """龙虎榜数据采集器"""
    
    def fetch_daily_list(self, trade_date: date = None) -> List[Dict[str, Any]]:
        """获取龙虎榜数据
        
        Args:
            trade_date: 交易日期，默认最新
        
        Returns:
            龙虎榜列表
        """
        if not AKSHARE_AVAILABLE:
            return []
        
        try:
            # 获取龙虎榜数据
            if trade_date:
                df = ak.stock_lhb_detail_em(
                    start_date=trade_date.strftime('%Y%m%d'),
                    end_date=trade_date.strftime('%Y%m%d')
                )
            else:
                df = ak.stock_lhb_detail_em()
            
            if df.empty:
                return []
            
            results = []
            for _, row in df.iterrows():
                results.append({
                    'symbol': row.get('代码', ''),
                    'name': row.get('名称', ''),
                    'trade_date': pd.to_datetime(row.get('上榜日', '')).date() if row.get('上榜日') else date.today(),
                    'close_price': float(row.get('收盘价', 0) or 0),
                    'pct_change': float(row.get('涨跌幅', 0) or 0),
                    'turnover_rate': float(row.get('换手率', 0) or 0),
                    'net_buy': float(row.get('净买额', 0) or 0) / 1e8,  # 转为亿元
                    'buy_amount': float(row.get('买入总额', 0) or 0) / 1e8,
                    'sell_amount': float(row.get('卖出总额', 0) or 0) / 1e8,
                    'reason': row.get('上榜原因', ''),
                })
            
            return results
        except Exception as e:
            logger.error(f"获取龙虎榜数据失败: {e}")
            return []
    
    def fetch_stock_lhb_history(self, symbol: str, days: int = 30) -> List[Dict[str, Any]]:
        """获取个股龙虎榜历史
        
        Args:
            symbol: 股票代码
            days: 最近N天
        
        Returns:
            龙虎榜历史记录
        """
        if not AKSHARE_AVAILABLE:
            return []
        
        code = symbol.split('.')[0]
        
        try:
            end_date = date.today()
            start_date = end_date - timedelta(days=days)
            
            df = ak.stock_lhb_detail_em(
                start_date=start_date.strftime('%Y%m%d'),
                end_date=end_date.strftime('%Y%m%d')
            )
            
            if df.empty:
                return []
            
            # 筛选目标股票
            stock_data = df[df['代码'] == code]
            
            results = []
            for _, row in stock_data.iterrows():
                results.append({
                    'trade_date': pd.to_datetime(row.get('上榜日', '')).date() if row.get('上榜日') else None,
                    'reason': row.get('上榜原因', ''),
                    'net_buy': float(row.get('净买额', 0) or 0) / 1e8,
                    'buy_amount': float(row.get('买入总额', 0) or 0) / 1e8,
                    'sell_amount': float(row.get('卖出总额', 0) or 0) / 1e8,
                })
            
            return results
        except Exception as e:
            logger.error(f"获取 {symbol} 龙虎榜历史失败: {e}")
            return []


# 全局实例
financial_fetcher = FinancialDataFetcher()
northbound_fetcher = NorthboundFlowFetcher()
dragon_tiger_fetcher = DragonTigerFetcher()
