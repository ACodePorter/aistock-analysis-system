"""
交易信号生成引擎（Signal Engine）

将模型预测结果 + 技术指标 + 过滤条件 转化为可执行交易信号。

核心功能：
1. 信号生成  — 基于预测收益/概率 → Buy / Sell / Hold
2. 多股票筛选 — 全市场打分 → Top-N 推荐股票池
3. 信号过滤  — 成交量异常 / 波动率过高 / 黑天鹅新闻
4. 信号稳定  — 最小持仓周期 / 信号平滑
5. 每日输出  — 推荐买入 / 建议卖出 / 当前持仓建议
"""

from __future__ import annotations

import datetime
import json
import logging
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from ...core.models import (
    Forecast,
    PriceDaily,
    Signal,
    TradingSignal,
    PositionManagement,
    Watchlist,
)

logger = logging.getLogger(__name__)


# ===================================================================
# 数据结构
# ===================================================================

class Action(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class StockScore:
    """单只股票的综合评分"""
    symbol: str
    name: Optional[str] = None
    sector: Optional[str] = None

    # 预测信号
    predicted_return_1d: float = 0.0
    predicted_return_5d: float = 0.0
    up_probability: float = 0.5
    model_confidence: float = 0.0

    # 技术信号
    tech_signal_score: float = 0.0
    tech_action: str = "HOLD"
    rsi: float = 50.0
    macd_hist: float = 0.0

    # 综合评分
    composite_score: float = 0.0
    action: str = "hold"
    signal_strength: float = 0.0

    # 过滤标记
    volume_anomaly: bool = False
    high_volatility: bool = False
    news_blackswan: bool = False
    is_filtered: bool = False
    filter_reasons: List[str] = field(default_factory=list)

    # 稳定性
    holding_days: int = 0
    min_hold_not_met: bool = False
    smoothed_score: float = 0.0

    # 价格信息
    current_price: float = 0.0
    target_price: float = 0.0
    stop_loss_price: float = 0.0


@dataclass
class DailySignalReport:
    """每日信号报告"""
    report_date: datetime.date
    generated_at: datetime.datetime

    # 推荐列表
    buy_signals: List[StockScore] = field(default_factory=list)
    sell_signals: List[StockScore] = field(default_factory=list)
    hold_signals: List[StockScore] = field(default_factory=list)

    # 统计
    total_stocks_scored: int = 0
    total_filtered: int = 0
    top_n: int = 10

    # 元数据
    model_method: str = ""
    filters_applied: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"=== 每日交易信号报告 {self.report_date} ===",
            f"评估股票: {self.total_stocks_scored}  过滤: {self.total_filtered}",
            "",
            f"--- BUY ({len(self.buy_signals)}) ---",
        ]
        for s in self.buy_signals[:10]:
            lines.append(
                f"  {s.symbol:<10s} {s.name or '':<8s}  "
                f"score={s.composite_score:+.2f}  "
                f"ret5d={s.predicted_return_5d:+.2%}  "
                f"conf={s.model_confidence:.2f}  "
                f"price={s.current_price:.2f} → {s.target_price:.2f}"
            )
        lines.append(f"\n--- SELL ({len(self.sell_signals)}) ---")
        for s in self.sell_signals[:10]:
            lines.append(
                f"  {s.symbol:<10s} {s.name or '':<8s}  "
                f"score={s.composite_score:+.2f}  "
                f"ret5d={s.predicted_return_5d:+.2%}  "
                f"hold={s.holding_days}d"
            )
        lines.append(f"\n--- HOLD ({len(self.hold_signals)}) ---")
        for s in self.hold_signals[:10]:
            lines.append(
                f"  {s.symbol:<10s} score={s.composite_score:+.2f}  hold={s.holding_days}d"
            )
        return "\n".join(lines)


# ===================================================================
# 信号引擎
# ===================================================================

PORTFOLIO_ID = "signal_engine_default"


class SignalEngine:
    """交易信号生成引擎

    参数：
        session:             SQLAlchemy Session
        buy_threshold:       上涨概率 > 此值 → BUY   (default 0.65)
        sell_threshold:      下跌概率 > 此值 → SELL   (default 0.65, 即 up_prob < 0.35)
        top_n:               每日推荐的最优股票数
        min_holding_days:    最小持仓周期（天），避免频繁交易
        smoothing_window:    信号平滑窗口（天）
        vol_anomaly_z:       成交量 Z-score 异常阈值
        volatility_cap:      波动率上限（年化），超过则过滤
        stop_loss_pct:       止损比例（如 0.05 = 5%）
        take_profit_pct:     止盈比例
    """

    def __init__(
        self,
        session: Session,
        buy_threshold: float = 0.65,
        sell_threshold: float = 0.65,
        top_n: int = 10,
        min_holding_days: int = 3,
        smoothing_window: int = 3,
        vol_anomaly_z: float = 3.0,
        volatility_cap: float = 0.80,
        stop_loss_pct: float = 0.05,
        take_profit_pct: float = 0.10,
    ):
        self.session = session
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.top_n = top_n
        self.min_holding_days = min_holding_days
        self.smoothing_window = smoothing_window
        self.vol_anomaly_z = vol_anomaly_z
        self.volatility_cap = volatility_cap
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def generate_daily_signals(
        self,
        target_date: Optional[datetime.date] = None,
        symbols: Optional[List[str]] = None,
    ) -> DailySignalReport:
        """每日信号生成主流程

        1. 获取所有活跃股票
        2. 加载预测结果 + 技术信号 + 行情数据
        3. 综合评分
        4. 过滤降噪
        5. 信号稳定性处理
        6. 排名 → Top-N
        7. 持久化 + 生成报告
        """
        if target_date is None:
            target_date = datetime.date.today()

        now = datetime.datetime.utcnow()
        logger.info("SignalEngine: generating signals for %s", target_date)

        # 1. 获取股票列表
        stock_list = self._get_stock_universe(symbols)
        if not stock_list:
            logger.warning("No active stocks found")
            return DailySignalReport(
                report_date=target_date, generated_at=now,
            )

        # 2. 加载每只股票的数据并评分
        scores: List[StockScore] = []
        for sym, name, sector in stock_list:
            try:
                score = self._score_stock(sym, name, sector, target_date)
                if score is not None:
                    scores.append(score)
            except Exception as e:
                logger.debug("Failed to score %s: %s", sym, e)

        logger.info("Scored %d / %d stocks", len(scores), len(stock_list))

        # 3. 过滤
        filtered_count = 0
        for s in scores:
            self._apply_filters(s, target_date)
            if s.is_filtered:
                filtered_count += 1

        # 4. 信号稳定性
        self._apply_stability(scores, target_date)

        # 5. 生成最终信号
        buy_signals, sell_signals, hold_signals = self._classify_and_rank(scores)

        # 6. 持久化
        self._persist_signals(buy_signals + sell_signals + hold_signals, target_date)
        self._update_positions(buy_signals, sell_signals, hold_signals, target_date)

        report = DailySignalReport(
            report_date=target_date,
            generated_at=now,
            buy_signals=buy_signals,
            sell_signals=sell_signals,
            hold_signals=hold_signals,
            total_stocks_scored=len(scores),
            total_filtered=filtered_count,
            top_n=self.top_n,
            filters_applied=[
                f"vol_anomaly_z>{self.vol_anomaly_z}",
                f"volatility_cap>{self.volatility_cap}",
                f"min_holding_days={self.min_holding_days}",
            ],
        )

        logger.info(
            "SignalEngine done: buy=%d sell=%d hold=%d filtered=%d",
            len(buy_signals), len(sell_signals), len(hold_signals), filtered_count,
        )
        return report

    # ------------------------------------------------------------------
    # 1. 获取股票池
    # ------------------------------------------------------------------

    def _get_stock_universe(
        self, symbols: Optional[List[str]] = None,
    ) -> List[Tuple[str, Optional[str], Optional[str]]]:
        """获取活跃观察列表中的股票"""
        if symbols:
            rows = (
                self.session.query(Watchlist.symbol, Watchlist.name, Watchlist.sector)
                .filter(Watchlist.symbol.in_(symbols))
                .all()
            )
            if not rows:
                return [(s, None, None) for s in symbols]
            return [(r.symbol, r.name, r.sector) for r in rows]

        rows = (
            self.session.query(Watchlist.symbol, Watchlist.name, Watchlist.sector)
            .filter(Watchlist.status == "active")
            .order_by(Watchlist.symbol)
            .all()
        )
        return [(r.symbol, r.name, r.sector) for r in rows]

    # ------------------------------------------------------------------
    # 2. 单股评分
    # ------------------------------------------------------------------

    def _score_stock(
        self,
        symbol: str,
        name: Optional[str],
        sector: Optional[str],
        target_date: datetime.date,
    ) -> Optional[StockScore]:
        """综合评分单只股票"""
        score = StockScore(symbol=symbol, name=name, sector=sector)

        # --- 预测数据 ---
        self._load_forecast_data(score, target_date)

        # --- 技术信号 ---
        self._load_tech_signal(score, target_date)

        # --- 行情数据（最新价格 + 波动率 + 成交量） ---
        self._load_market_data(score, target_date)

        # --- 综合评分 ---
        self._compute_composite_score(score)

        return score

    def _load_forecast_data(self, score: StockScore, target_date: datetime.date):
        """从 Forecast 表加载模型预测"""
        lookback = target_date - datetime.timedelta(days=3)

        forecasts = (
            self.session.query(Forecast)
            .filter(
                Forecast.symbol == score.symbol,
                Forecast.run_at >= lookback,
            )
            .order_by(Forecast.run_at.desc())
            .limit(10)
            .all()
        )

        if not forecasts:
            return

        latest_run = forecasts[0].run_at

        current_price = score.current_price or 0
        if current_price <= 0:
            price_row = (
                self.session.query(PriceDaily.close)
                .filter(PriceDaily.symbol == score.symbol)
                .order_by(PriceDaily.trade_date.desc())
                .first()
            )
            if price_row and price_row.close:
                current_price = float(price_row.close)
                score.current_price = current_price

        if current_price <= 0:
            return

        # 提取 1d 和 5d 预测
        run_forecasts = [f for f in forecasts if f.run_at == latest_run]
        for fc in run_forecasts:
            yhat = float(fc.yhat) if fc.yhat else current_price
            ret = (yhat - current_price) / current_price
            days_ahead = (fc.target_date - target_date).days
            if days_ahead <= 1:
                score.predicted_return_1d = ret
            elif days_ahead <= 5:
                score.predicted_return_5d = ret

            score.target_price = max(score.target_price, yhat)

        # 估算上涨概率：基于预测收益 + 置信区间
        avg_return = (score.predicted_return_1d + score.predicted_return_5d) / 2
        # sigmoid 映射: return → probability
        score.up_probability = 1.0 / (1.0 + np.exp(-avg_return * 50))

        # 模型置信度：基于预测区间宽度
        if run_forecasts:
            fc = run_forecasts[0]
            if fc.yhat_upper and fc.yhat_lower and fc.yhat:
                spread = (float(fc.yhat_upper) - float(fc.yhat_lower)) / float(fc.yhat)
                score.model_confidence = max(0.1, min(0.95, 1.0 - spread * 2))
            else:
                score.model_confidence = 0.5

    def _load_tech_signal(self, score: StockScore, target_date: datetime.date):
        """从 Signal 表加载技术指标信号"""
        sig = (
            self.session.query(Signal)
            .filter(
                Signal.symbol == score.symbol,
                Signal.trade_date <= target_date,
            )
            .order_by(Signal.trade_date.desc())
            .first()
        )
        if sig is None:
            return

        score.tech_signal_score = float(sig.signal_score) if sig.signal_score else 0.0
        score.tech_action = sig.action or "HOLD"
        score.rsi = float(sig.rsi) if sig.rsi else 50.0
        score.macd_hist = float(sig.macd) if sig.macd else 0.0

    def _load_market_data(self, score: StockScore, target_date: datetime.date):
        """加载行情数据：最新价格、波动率、成交量异常"""
        prices = (
            self.session.query(PriceDaily)
            .filter(
                PriceDaily.symbol == score.symbol,
                PriceDaily.trade_date <= target_date,
            )
            .order_by(PriceDaily.trade_date.desc())
            .limit(60)
            .all()
        )
        if not prices:
            return

        latest = prices[0]
        if latest.close:
            score.current_price = float(latest.close)

        if len(prices) < 20:
            return

        closes = np.array([float(p.close) for p in reversed(prices) if p.close])
        if len(closes) < 20:
            return

        # 波动率（年化）
        rets = np.diff(np.log(closes))
        vol_annual = float(np.std(rets) * np.sqrt(252))
        if vol_annual > self.volatility_cap:
            score.high_volatility = True
            score.filter_reasons.append(f"volatility={vol_annual:.2%}>{self.volatility_cap:.0%}")

        # 成交量异常
        volumes = [float(p.vol) for p in reversed(prices) if p.vol and p.vol > 0]
        if len(volumes) >= 20:
            vol_mean = np.mean(volumes[-20:])
            vol_std = np.std(volumes[-20:])
            if vol_std > 0 and len(volumes) > 0:
                latest_vol = volumes[-1]
                z = (latest_vol - vol_mean) / (vol_std + 1e-9)
                if abs(z) > self.vol_anomaly_z:
                    score.volume_anomaly = True
                    score.filter_reasons.append(f"vol_z={z:.1f}")

        # 止损止盈价
        if score.current_price > 0:
            score.stop_loss_price = round(score.current_price * (1 - self.stop_loss_pct), 2)
            if score.target_price <= 0:
                score.target_price = round(score.current_price * (1 + self.take_profit_pct), 2)

    # ------------------------------------------------------------------
    # 3. 综合评分
    # ------------------------------------------------------------------

    def _compute_composite_score(self, score: StockScore):
        """综合评分 = 预测收益(40%) + 上涨概率(30%) + 技术信号(20%) + 置信度(10%)

        score 范围 [-100, +100]
        """
        # 预测收益分 → [-40, +40]
        ret_score = np.clip(score.predicted_return_5d * 400, -40, 40)

        # 上涨概率分 → [-30, +30]
        prob_score = (score.up_probability - 0.5) * 60

        # 技术信号分 → [-20, +20]（原始 signal_score 范围约 [-45, +45]）
        tech_score = np.clip(score.tech_signal_score * 0.44, -20, 20)

        # 置信度加成 → [0, +10]
        conf_score = score.model_confidence * 10

        composite = ret_score + prob_score + tech_score + conf_score
        score.composite_score = round(float(composite), 2)

        # 决定信号
        if score.up_probability > self.buy_threshold and composite > 10:
            score.action = Action.BUY.value
            score.signal_strength = min(100, max(0, composite))
        elif score.up_probability < (1 - self.sell_threshold) and composite < -10:
            score.action = Action.SELL.value
            score.signal_strength = min(100, max(0, -composite))
        else:
            score.action = Action.HOLD.value
            score.signal_strength = 0

    # ------------------------------------------------------------------
    # 4. 信号过滤
    # ------------------------------------------------------------------

    def _apply_filters(self, score: StockScore, target_date: datetime.date):
        """应用过滤条件，标记应被过滤的信号"""
        if score.volume_anomaly:
            score.is_filtered = True

        if score.high_volatility:
            score.is_filtered = True

        if score.news_blackswan:
            score.is_filtered = True
            score.filter_reasons.append("blackswan_news")

        # 检查黑天鹅新闻（如果有 NewsArticle 表）
        self._check_blackswan_news(score, target_date)

        # 被过滤的信号降级为 HOLD
        if score.is_filtered and score.action == Action.BUY.value:
            score.action = Action.HOLD.value
            score.signal_strength = 0

    def _check_blackswan_news(self, score: StockScore, target_date: datetime.date):
        """检查是否存在重大负面新闻"""
        try:
            from ...core.models import NewsArticle
            lookback = target_date - datetime.timedelta(days=3)
            negative_news = (
                self.session.query(func.count(NewsArticle.id))
                .filter(
                    NewsArticle.symbol == score.symbol,
                    NewsArticle.published_at >= lookback,
                    NewsArticle.sentiment_score < -0.5,
                )
                .scalar()
            )
            if negative_news and negative_news >= 3:
                score.news_blackswan = True
                score.is_filtered = True
                score.filter_reasons.append(f"negative_news={negative_news}")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 5. 信号稳定性
    # ------------------------------------------------------------------

    def _apply_stability(
        self, scores: List[StockScore], target_date: datetime.date,
    ):
        """信号稳定性处理：最小持仓周期 + 历史评分平滑"""
        # 加载当前持仓信息
        positions = self._get_current_positions()

        for s in scores:
            # 最小持仓周期
            if s.symbol in positions:
                pos = positions[s.symbol]
                s.holding_days = pos.get("holding_days", 0)
                if s.holding_days < self.min_holding_days and s.action == Action.SELL.value:
                    s.min_hold_not_met = True
                    s.action = Action.HOLD.value
                    s.filter_reasons.append(
                        f"min_hold: {s.holding_days}d < {self.min_holding_days}d"
                    )

            # 历史评分平滑
            self._smooth_score(s, target_date)

    def _smooth_score(self, score: StockScore, target_date: datetime.date):
        """用最近 N 天的信号做移动平均平滑"""
        lookback = target_date - datetime.timedelta(days=self.smoothing_window + 2)

        recent_signals = (
            self.session.query(TradingSignal.signal_strength, TradingSignal.signal_type)
            .filter(
                TradingSignal.symbol == score.symbol,
                TradingSignal.signal_date >= lookback,
                TradingSignal.signal_date < target_date,
            )
            .order_by(TradingSignal.signal_date.desc())
            .limit(self.smoothing_window)
            .all()
        )

        if not recent_signals:
            score.smoothed_score = score.composite_score
            return

        hist_scores = []
        for sig in recent_signals:
            strength = float(sig.signal_strength) if sig.signal_strength else 0
            if sig.signal_type == "sell":
                strength = -strength
            hist_scores.append(strength)

        # 当前分数权重最高（50%），历史分数平均占 50%
        hist_avg = np.mean(hist_scores) if hist_scores else 0
        score.smoothed_score = round(
            0.5 * score.composite_score + 0.5 * hist_avg, 2
        )

        # 如果平滑后分数与当前信号方向矛盾，降级为 HOLD
        if score.action == Action.BUY.value and score.smoothed_score < 5:
            score.action = Action.HOLD.value
            score.filter_reasons.append("smoothing_override")
        elif score.action == Action.SELL.value and score.smoothed_score > -5:
            score.action = Action.HOLD.value
            score.filter_reasons.append("smoothing_override")

    def _get_current_positions(self) -> Dict[str, dict]:
        """获取当前持仓"""
        rows = (
            self.session.query(PositionManagement)
            .filter(
                PositionManagement.portfolio_id == PORTFOLIO_ID,
                PositionManagement.quantity > 0,
            )
            .all()
        )
        result = {}
        for r in rows:
            result[r.symbol] = {
                "quantity": r.quantity,
                "avg_cost": float(r.avg_cost) if r.avg_cost else 0,
                "holding_days": r.holding_days or 0,
                "entry_date": r.entry_date,
            }
        return result

    # ------------------------------------------------------------------
    # 6. 排名与分类
    # ------------------------------------------------------------------

    def _classify_and_rank(
        self, scores: List[StockScore],
    ) -> Tuple[List[StockScore], List[StockScore], List[StockScore]]:
        """分类为 BUY/SELL/HOLD 并按综合评分排名"""
        buy_list = [s for s in scores if s.action == Action.BUY.value and not s.is_filtered]
        sell_list = [s for s in scores if s.action == Action.SELL.value]
        hold_list = [s for s in scores if s.action == Action.HOLD.value]

        # 按综合评分排序
        buy_list.sort(key=lambda x: x.composite_score, reverse=True)
        sell_list.sort(key=lambda x: x.composite_score)
        hold_list.sort(key=lambda x: x.composite_score, reverse=True)

        # 取 Top-N
        buy_list = buy_list[:self.top_n]

        return buy_list, sell_list, hold_list

    # ------------------------------------------------------------------
    # 7. 持久化
    # ------------------------------------------------------------------

    def _persist_signals(
        self, all_signals: List[StockScore], target_date: datetime.date,
    ):
        """将信号写入 TradingSignal 表"""
        now = datetime.datetime.utcnow()

        for s in all_signals:
            try:
                existing = (
                    self.session.query(TradingSignal)
                    .filter(
                        TradingSignal.symbol == s.symbol,
                        TradingSignal.signal_date == target_date,
                        TradingSignal.source == "signal_engine",
                    )
                    .first()
                )

                factors_json = json.dumps({
                    "predicted_return_1d": round(s.predicted_return_1d, 6),
                    "predicted_return_5d": round(s.predicted_return_5d, 6),
                    "up_probability": round(s.up_probability, 4),
                    "tech_signal_score": round(s.tech_signal_score, 2),
                    "rsi": round(s.rsi, 2),
                    "volume_anomaly": s.volume_anomaly,
                    "high_volatility": s.high_volatility,
                    "is_filtered": s.is_filtered,
                    "filter_reasons": s.filter_reasons,
                    "smoothed_score": s.smoothed_score,
                    "holding_days": s.holding_days,
                }, ensure_ascii=False)

                if existing:
                    existing.signal_type = s.action
                    existing.signal_strength = s.signal_strength
                    existing.confidence = s.model_confidence
                    existing.trigger_price = s.current_price
                    existing.target_price = s.target_price
                    existing.stop_loss_price = s.stop_loss_price
                    existing.factors = factors_json
                    existing.strategy = "composite_v1"
                else:
                    from sqlalchemy import insert
                    stmt = insert(TradingSignal).values(
                        symbol=s.symbol,
                        signal_date=target_date,
                        signal_time=now,
                        signal_type=s.action,
                        signal_strength=s.signal_strength,
                        confidence=s.model_confidence,
                        source="signal_engine",
                        strategy="composite_v1",
                        trigger_price=s.current_price,
                        target_price=s.target_price,
                        stop_loss_price=s.stop_loss_price,
                        factors=factors_json,
                        analysis=f"composite_score={s.composite_score:.2f}",
                        is_validated=False,
                        created_at=now,
                    )
                    self.session.execute(stmt)

            except Exception as e:
                logger.debug("Failed to persist signal for %s: %s", s.symbol, e)

        try:
            self.session.commit()
        except Exception as e:
            logger.error("Failed to commit signals: %s", e)
            self.session.rollback()

    def _update_positions(
        self,
        buy_signals: List[StockScore],
        sell_signals: List[StockScore],
        hold_signals: List[StockScore],
        target_date: datetime.date,
    ):
        """更新仓位管理表"""
        now = datetime.datetime.utcnow()

        for s in buy_signals:
            self._upsert_position(s, target_date, is_buy=True)

        for s in sell_signals:
            pos = (
                self.session.query(PositionManagement)
                .filter(
                    PositionManagement.portfolio_id == PORTFOLIO_ID,
                    PositionManagement.symbol == s.symbol,
                )
                .first()
            )
            if pos and pos.quantity > 0:
                if pos.avg_cost and s.current_price:
                    pos.unrealized_pnl = (s.current_price - float(pos.avg_cost)) * pos.quantity
                    pos.unrealized_pnl_pct = (s.current_price / float(pos.avg_cost) - 1) * 100
                    pos.realized_pnl = pos.unrealized_pnl
                pos.quantity = 0
                pos.current_price = s.current_price
                pos.last_trade_date = target_date
                pos.updated_at = now

        # 更新 HOLD 仓位的持仓天数和市值
        for s in hold_signals:
            pos = (
                self.session.query(PositionManagement)
                .filter(
                    PositionManagement.portfolio_id == PORTFOLIO_ID,
                    PositionManagement.symbol == s.symbol,
                    PositionManagement.quantity > 0,
                )
                .first()
            )
            if pos:
                pos.current_price = s.current_price
                if pos.avg_cost and s.current_price:
                    pos.unrealized_pnl = (s.current_price - float(pos.avg_cost)) * pos.quantity
                    pos.unrealized_pnl_pct = (s.current_price / float(pos.avg_cost) - 1) * 100
                pos.market_value = s.current_price * pos.quantity if s.current_price else None
                if pos.entry_date:
                    pos.holding_days = (target_date - pos.entry_date).days
                pos.stop_loss_price = s.stop_loss_price
                pos.take_profit_price = s.target_price
                pos.updated_at = now

        try:
            self.session.commit()
        except Exception as e:
            logger.error("Failed to update positions: %s", e)
            self.session.rollback()

    def _upsert_position(
        self, score: StockScore, target_date: datetime.date, is_buy: bool,
    ):
        """创建或更新持仓"""
        pos = (
            self.session.query(PositionManagement)
            .filter(
                PositionManagement.portfolio_id == PORTFOLIO_ID,
                PositionManagement.symbol == score.symbol,
            )
            .first()
        )

        if pos:
            if is_buy and pos.quantity == 0:
                pos.quantity = 100
                pos.avg_cost = score.current_price
                pos.entry_date = target_date
                pos.holding_days = 0
            pos.current_price = score.current_price
            pos.market_value = score.current_price * pos.quantity if score.current_price else None
            pos.stop_loss_price = score.stop_loss_price
            pos.take_profit_price = score.target_price
            pos.target_weight = round(score.signal_strength / 100 * 10, 2)
            pos.updated_at = datetime.datetime.utcnow()
        else:
            if is_buy:
                from sqlalchemy import insert
                stmt = insert(PositionManagement).values(
                    portfolio_id=PORTFOLIO_ID,
                    symbol=score.symbol,
                    quantity=100,
                    avg_cost=score.current_price,
                    current_price=score.current_price,
                    market_value=score.current_price * 100 if score.current_price else None,
                    entry_date=target_date,
                    holding_days=0,
                    stop_loss_price=score.stop_loss_price,
                    take_profit_price=score.target_price,
                    target_weight=round(score.signal_strength / 100 * 10, 2),
                    updated_at=datetime.datetime.utcnow(),
                )
                self.session.execute(stmt)


# ===================================================================
# 便捷入口
# ===================================================================

def generate_daily_signals(
    target_date: Optional[datetime.date] = None,
    symbols: Optional[List[str]] = None,
    top_n: int = 10,
    **kwargs,
) -> DailySignalReport:
    """便捷入口：自动创建 Session 并运行信号生成"""
    from ...core.database import SessionLocal

    session = SessionLocal()
    try:
        engine = SignalEngine(session=session, top_n=top_n, **kwargs)
        report = engine.generate_daily_signals(target_date, symbols)
        return report
    finally:
        session.close()


def run_daily_signal_generation() -> DailySignalReport:
    """供调度器调用的每日信号生成入口"""
    logger.info("Starting daily signal generation...")
    report = generate_daily_signals()
    logger.info(
        "Daily signal generation complete: buy=%d sell=%d hold=%d",
        len(report.buy_signals),
        len(report.sell_signals),
        len(report.hold_signals),
    )
    return report
