"""
事件驱动因子验证模块（Event Validator）

验证事件对股价的实际影响，评估事件模型预测准确性。

核心功能：
1. 事件前后股价变化分析（event study）
2. 事件窗口内预测 vs 实际对比
3. 分类别/分情绪统计命中率
4. 生成验证报告
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class EventImpactRecord:
    """单次事件的影响记录"""
    symbol: str
    event_date: datetime.date
    category: str
    sentiment: str
    impact_score: float
    # 价格变化（事件日前后）
    ret_pre_3d: float = 0.0   # 事件前 3 天收益
    ret_day0: float = 0.0     # 事件当天收益
    ret_post_1d: float = 0.0  # 事件后 1 天
    ret_post_3d: float = 0.0  # 事件后 3 天
    ret_post_5d: float = 0.0  # 事件后 5 天
    # 预测准确性
    predicted_direction: int = 0
    actual_direction: int = 0
    direction_correct: bool = False
    predicted_return: float = 0.0
    actual_return: float = 0.0


@dataclass
class CategoryStats:
    """某一事件类别的统计"""
    category: str
    count: int = 0
    avg_impact_score: float = 0.0
    # 平均收益
    avg_ret_day0: float = 0.0
    avg_ret_post_1d: float = 0.0
    avg_ret_post_3d: float = 0.0
    avg_ret_post_5d: float = 0.0
    # 方向准确率
    direction_accuracy: float = 0.0
    # 按情绪分
    positive_avg_ret_5d: float = 0.0
    negative_avg_ret_5d: float = 0.0
    # 显著性
    significant_positive: int = 0  # 事后5天涨幅 > 1%
    significant_negative: int = 0  # 事后5天跌幅 > 1%


@dataclass
class ValidationReport:
    """事件验证综合报告"""
    start_date: datetime.date
    end_date: datetime.date
    total_events: int = 0
    total_symbols: int = 0
    # 总体指标
    overall_direction_accuracy: float = 0.0
    avg_post_5d_return: float = 0.0
    # 分类别统计
    category_stats: Dict[str, CategoryStats] = field(default_factory=dict)
    # 按情绪分组
    positive_events_correct_pct: float = 0.0
    negative_events_correct_pct: float = 0.0
    # 细节
    records: List[EventImpactRecord] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"=== 事件驱动因子验证报告 ===",
            f"期间: {self.start_date} → {self.end_date}",
            f"事件总数: {self.total_events}  涉及股票: {self.total_symbols}",
            f"整体方向准确率: {self.overall_direction_accuracy:.1%}",
            f"平均事后5日收益: {self.avg_post_5d_return:+.2%}",
            f"正面事件命中率: {self.positive_events_correct_pct:.1%}",
            f"负面事件命中率: {self.negative_events_correct_pct:.1%}",
            "",
            f"{'Category':<12s} {'Count':>5s} {'Dir%':>6s} {'Day0':>7s} "
            f"{'Post1d':>7s} {'Post3d':>7s} {'Post5d':>7s} {'SigPos':>6s} {'SigNeg':>6s}",
            "-" * 70,
        ]
        for cat, stats in sorted(self.category_stats.items()):
            lines.append(
                f"{cat:<12s} {stats.count:>5d} {stats.direction_accuracy:>5.1%} "
                f"{stats.avg_ret_day0:>+6.2%} {stats.avg_ret_post_1d:>+6.2%} "
                f"{stats.avg_ret_post_3d:>+6.2%} {stats.avg_ret_post_5d:>+6.2%} "
                f"{stats.significant_positive:>6d} {stats.significant_negative:>6d}"
            )
        return "\n".join(lines)


class EventValidator:
    """事件影响验证器

    Args:
        pre_window:   事件前观察窗口（天）
        post_windows: 事件后观察窗口列表
        significance_threshold: 显著收益阈值
    """

    def __init__(
        self,
        pre_window: int = 3,
        post_windows: Tuple[int, ...] = (1, 3, 5),
        significance_threshold: float = 0.01,
    ):
        self.pre_window = pre_window
        self.post_windows = post_windows
        self.significance_threshold = significance_threshold

    def validate(
        self,
        events_df: pd.DataFrame,
        prices_df: pd.DataFrame,
        predictions_df: Optional[pd.DataFrame] = None,
    ) -> ValidationReport:
        """执行事件验证

        Args:
            events_df:      事件数据，需包含 symbol, trade_date, category, sentiment, impact_score
            prices_df:      价格数据，需包含 symbol, trade_date, close
            predictions_df: 预测数据（可选），symbol, trade_date, predicted_direction, predicted_return
        """
        if events_df.empty:
            return ValidationReport(
                start_date=datetime.date.today(),
                end_date=datetime.date.today(),
            )

        start_date = events_df["trade_date"].min()
        end_date = events_df["trade_date"].max()

        records: List[EventImpactRecord] = []

        # 按 symbol 分组处理
        for symbol in events_df["symbol"].unique():
            sym_events = events_df[events_df["symbol"] == symbol]
            sym_prices = prices_df[prices_df["symbol"] == symbol].sort_values("trade_date")

            if sym_prices.empty or len(sym_prices) < 10:
                continue

            sym_prices = sym_prices.set_index("trade_date")
            closes = sym_prices["close"].astype(float)

            sym_preds = None
            if predictions_df is not None:
                sym_preds = predictions_df[predictions_df["symbol"] == symbol]

            for _, event in sym_events.iterrows():
                record = self._analyze_single_event(
                    symbol=symbol,
                    event_date=event["trade_date"],
                    category=event.get("category", "unknown"),
                    sentiment=event.get("sentiment", "neutral"),
                    impact_score=float(event.get("impact_score", 0)),
                    closes=closes,
                    predictions=sym_preds,
                )
                if record is not None:
                    records.append(record)

        report = self._build_report(records, start_date, end_date)
        return report

    def _analyze_single_event(
        self,
        symbol: str,
        event_date: datetime.date,
        category: str,
        sentiment: str,
        impact_score: float,
        closes: pd.Series,
        predictions: Optional[pd.DataFrame],
    ) -> Optional[EventImpactRecord]:
        """分析单次事件"""
        if event_date not in closes.index:
            avail = closes.index[closes.index <= event_date]
            if avail.empty:
                return None
            event_date = avail[-1]

        idx = closes.index.get_loc(event_date)
        if isinstance(idx, slice):
            idx = idx.start

        event_price = float(closes.iloc[idx])
        if event_price <= 0:
            return None

        record = EventImpactRecord(
            symbol=symbol,
            event_date=event_date,
            category=category,
            sentiment=sentiment,
            impact_score=impact_score,
        )

        # 事件前收益
        if idx >= self.pre_window:
            pre_price = float(closes.iloc[idx - self.pre_window])
            record.ret_pre_3d = (event_price / pre_price - 1) if pre_price > 0 else 0

        # 当天收益
        if idx >= 1:
            prev_price = float(closes.iloc[idx - 1])
            record.ret_day0 = (event_price / prev_price - 1) if prev_price > 0 else 0

        # 事后收益
        n = len(closes)
        for days in self.post_windows:
            post_idx = idx + days
            if post_idx < n:
                post_price = float(closes.iloc[post_idx])
                ret = (post_price / event_price - 1) if event_price > 0 else 0
                if days == 1:
                    record.ret_post_1d = ret
                elif days == 3:
                    record.ret_post_3d = ret
                elif days == 5:
                    record.ret_post_5d = ret

        # 实际方向
        record.actual_return = record.ret_post_5d
        record.actual_direction = 1 if record.ret_post_5d > 0.002 else (-1 if record.ret_post_5d < -0.002 else 0)

        # 预测方向（来自事件模型或基于情绪推断）
        if predictions is not None and not predictions.empty:
            pred_row = predictions[predictions["trade_date"] == event_date]
            if not pred_row.empty:
                record.predicted_direction = int(pred_row.iloc[0].get("predicted_direction", 0))
                record.predicted_return = float(pred_row.iloc[0].get("predicted_return", 0))
        else:
            if sentiment == "positive":
                record.predicted_direction = 1
            elif sentiment == "negative":
                record.predicted_direction = -1
            else:
                record.predicted_direction = 0

        record.direction_correct = (
            record.predicted_direction == record.actual_direction
            or (record.predicted_direction != 0 and
                np.sign(record.predicted_direction) == np.sign(record.actual_direction))
        )

        return record

    def _build_report(
        self,
        records: List[EventImpactRecord],
        start_date,
        end_date,
    ) -> ValidationReport:
        """构建验证报告"""
        if not records:
            return ValidationReport(start_date=start_date, end_date=end_date)

        symbols = set(r.symbol for r in records)
        n_correct = sum(1 for r in records if r.direction_correct)

        # 按类别统计
        cat_groups: Dict[str, List[EventImpactRecord]] = {}
        for r in records:
            cat_groups.setdefault(r.category, []).append(r)

        category_stats = {}
        for cat, group in cat_groups.items():
            n = len(group)
            pos_group = [r for r in group if r.sentiment == "positive"]
            neg_group = [r for r in group if r.sentiment == "negative"]

            category_stats[cat] = CategoryStats(
                category=cat,
                count=n,
                avg_impact_score=np.mean([r.impact_score for r in group]),
                avg_ret_day0=np.mean([r.ret_day0 for r in group]),
                avg_ret_post_1d=np.mean([r.ret_post_1d for r in group]),
                avg_ret_post_3d=np.mean([r.ret_post_3d for r in group]),
                avg_ret_post_5d=np.mean([r.ret_post_5d for r in group]),
                direction_accuracy=sum(1 for r in group if r.direction_correct) / n if n > 0 else 0,
                positive_avg_ret_5d=np.mean([r.ret_post_5d for r in pos_group]) if pos_group else 0,
                negative_avg_ret_5d=np.mean([r.ret_post_5d for r in neg_group]) if neg_group else 0,
                significant_positive=sum(1 for r in group if r.ret_post_5d > self.significance_threshold),
                significant_negative=sum(1 for r in group if r.ret_post_5d < -self.significance_threshold),
            )

        # 按情绪命中率
        pos_events = [r for r in records if r.sentiment == "positive"]
        neg_events = [r for r in records if r.sentiment == "negative"]
        pos_correct = sum(1 for r in pos_events if r.direction_correct) / len(pos_events) if pos_events else 0
        neg_correct = sum(1 for r in neg_events if r.direction_correct) / len(neg_events) if neg_events else 0

        return ValidationReport(
            start_date=start_date,
            end_date=end_date,
            total_events=len(records),
            total_symbols=len(symbols),
            overall_direction_accuracy=n_correct / len(records) if records else 0,
            avg_post_5d_return=np.mean([r.ret_post_5d for r in records]),
            category_stats=category_stats,
            positive_events_correct_pct=pos_correct,
            negative_events_correct_pct=neg_correct,
            records=records,
        )


def validate_events_from_db(
    session,
    symbols: List[str],
    start_date: datetime.date,
    end_date: datetime.date,
) -> ValidationReport:
    """从数据库加载事件和价格并执行验证"""
    from .event_alpha import extract_events_from_db, EventFeatureBuilder

    all_events, event_df = extract_events_from_db(
        session, symbols, start_date, end_date,
    )

    if not all_events:
        logger.info("No events found for validation")
        return ValidationReport(start_date=start_date, end_date=end_date)

    # 构建 events_df
    event_records = []
    for e in all_events:
        event_records.append({
            "symbol": e.symbol,
            "trade_date": e.event_date,
            "category": e.category,
            "sentiment": e.sentiment,
            "impact_score": e.impact_score,
        })
    events_df = pd.DataFrame(event_records)

    # 加载价格
    from ...core.models import PriceDaily
    buffer_start = start_date - datetime.timedelta(days=10)
    buffer_end = end_date + datetime.timedelta(days=10)

    prices = (
        session.query(PriceDaily.symbol, PriceDaily.trade_date, PriceDaily.close)
        .filter(
            PriceDaily.symbol.in_(symbols),
            PriceDaily.trade_date >= buffer_start,
            PriceDaily.trade_date <= buffer_end,
        )
        .all()
    )
    prices_df = pd.DataFrame([
        {"symbol": p.symbol, "trade_date": p.trade_date, "close": float(p.close)}
        for p in prices if p.close
    ])

    if prices_df.empty:
        return ValidationReport(start_date=start_date, end_date=end_date)

    validator = EventValidator()
    return validator.validate(events_df, prices_df)
