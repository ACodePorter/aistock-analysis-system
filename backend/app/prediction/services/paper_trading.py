"""
模拟实盘交易系统（Paper Trading System）

在真实时间流中验证模型预测 → 交易信号 → 组合优化的完整闭环。

核心流程（每日收盘后自动执行）：
1. 获取最新交易信号（from SignalEngine）
2. 执行组合优化（from PortfolioOptimizer）
3. 按优化结果模拟买卖
4. 更新持仓、计算盈亏
5. 记录每日净值快照
6. 对比基准（沪深300）

关键设计：
- 手续费模拟（买入万3，卖出万3+千1印花税）
- 整手交易（100 股）
- 涨跌停限制检测
- 严格时间序列：仅使用当日收盘价，次日开盘执行
"""

from __future__ import annotations

import datetime
import json
import logging
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sqlalchemy import insert, text, desc
from sqlalchemy.orm import Session

from ...core.models import (
    PaperTradeLog,
    PaperTradingSnapshot,
    Portfolio,
    PositionManagement,
    PriceDaily,
    TradingSignal,
    Watchlist,
)

logger = logging.getLogger(__name__)

PAPER_PORTFOLIO_ID = "paper_trading_main"
DEFAULT_INITIAL_CAPITAL = 1_000_000.0
BUY_COMMISSION_RATE = 0.0003    # 万3
SELL_COMMISSION_RATE = 0.0003   # 万3
STAMP_TAX_RATE = 0.001          # 千1 印花税（卖出）
MIN_COMMISSION = 5.0            # 最低手续费
BENCHMARK_SYMBOL = "000300.SH"  # 沪深300


# ===================================================================
# 数据结构
# ===================================================================

@dataclass
class TradeOrder:
    """一笔模拟交易"""
    symbol: str
    action: str        # buy / sell
    quantity: int
    price: float
    amount: float      # quantity * price
    commission: float
    net_amount: float  # 买入: amount+commission, 卖出: amount-commission
    reason: str = ""
    signal_strength: float = 0.0


@dataclass
class DailySnapshot:
    """每日快照"""
    date: datetime.date
    cash: float
    market_value: float
    total_value: float
    nav: float
    daily_return: float
    total_return: float
    drawdown: float
    max_drawdown: float
    benchmark_value: float
    benchmark_return: float
    excess_return: float
    position_count: int
    trades_today: int
    positions: Dict[str, dict] = field(default_factory=dict)


@dataclass
class PaperTradingReport:
    """模拟盘运行报告"""
    portfolio_id: str
    run_date: datetime.date
    # 交易
    orders_executed: List[TradeOrder] = field(default_factory=list)
    buy_count: int = 0
    sell_count: int = 0
    total_commission: float = 0.0
    # 当日快照
    snapshot: Optional[DailySnapshot] = None
    # 状态
    success: bool = True
    error_message: str = ""

    def summary(self) -> str:
        lines = [
            f"=== 模拟实盘报告 {self.run_date} ===",
            f"交易: 买入{self.buy_count}笔 卖出{self.sell_count}笔 佣金{self.total_commission:.2f}",
        ]
        if self.snapshot:
            s = self.snapshot
            lines.extend([
                f"资产: 总值{s.total_value:,.0f} 现金{s.cash:,.0f} 持仓{s.market_value:,.0f}",
                f"净值: {s.nav:.4f}  日收益: {s.daily_return:+.2%}  累计: {s.total_return:+.2%}",
                f"回撤: {s.drawdown:.2%}  最大回撤: {s.max_drawdown:.2%}",
                f"基准: {s.benchmark_return:+.2%}  超额: {s.excess_return:+.2%}",
                f"持仓: {s.position_count}只",
            ])
        for o in self.orders_executed[:20]:
            lines.append(
                f"  {o.action.upper():<5s} {o.symbol:<10s} {o.quantity:>6d}股 "
                f"@ {o.price:.2f}  金额{o.amount:,.0f}  佣金{o.commission:.2f}  "
                f"{o.reason}"
            )
        return "\n".join(lines)


# ===================================================================
# 模拟盘引擎
# ===================================================================

class PaperTradingEngine:
    """模拟实盘交易引擎

    Args:
        session:          SQLAlchemy Session
        portfolio_id:     组合ID
        initial_capital:  初始资金
        benchmark:        基准指数代码
    """

    def __init__(
        self,
        session: Session,
        portfolio_id: str = PAPER_PORTFOLIO_ID,
        initial_capital: float = DEFAULT_INITIAL_CAPITAL,
        benchmark: str = BENCHMARK_SYMBOL,
    ):
        self.session = session
        self.portfolio_id = portfolio_id
        self.initial_capital = initial_capital
        self.benchmark = benchmark

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def run_daily(
        self,
        target_date: Optional[datetime.date] = None,
    ) -> PaperTradingReport:
        """每日收盘后执行的完整流程"""
        if target_date is None:
            target_date = datetime.date.today()

        report = PaperTradingReport(
            portfolio_id=self.portfolio_id,
            run_date=target_date,
        )

        try:
            # 0. 确保组合已初始化
            self._ensure_portfolio()

            # 1. 更新持仓的当前价格
            self._update_position_prices(target_date)

            # 2. 获取交易信号 → 生成交易订单
            orders = self._generate_orders(target_date)

            # 3. 执行交易
            for order in orders:
                self._execute_order(order, target_date)
                report.orders_executed.append(order)
                if order.action == "buy":
                    report.buy_count += 1
                else:
                    report.sell_count += 1
                report.total_commission += order.commission

            # 4. 再次更新价格（交易后）
            self._update_position_prices(target_date)

            # 5. 生成每日快照
            snapshot = self._take_snapshot(target_date)
            report.snapshot = snapshot

            # 6. 持久化快照
            self._persist_snapshot(snapshot)

            # 7. 更新 Portfolio 表
            self._update_portfolio_record(snapshot)

            logger.info(
                "Paper trading %s: NAV=%.4f, return=%+.2f%%, dd=%.2f%%, "
                "buys=%d, sells=%d, positions=%d",
                target_date, snapshot.nav, snapshot.total_return * 100,
                snapshot.max_drawdown * 100,
                report.buy_count, report.sell_count, snapshot.position_count,
            )

        except Exception as e:
            report.success = False
            report.error_message = str(e)
            logger.error("Paper trading failed for %s: %s", target_date, e, exc_info=True)

        return report

    # ------------------------------------------------------------------
    # 0. 初始化
    # ------------------------------------------------------------------

    def _ensure_portfolio(self):
        """确保 Portfolio 记录存在"""
        portfolio = (
            self.session.query(Portfolio)
            .filter(Portfolio.portfolio_id == self.portfolio_id)
            .first()
        )
        if not portfolio:
            now = datetime.datetime.utcnow()
            try:
                stmt = insert(Portfolio).values(
                    portfolio_id=self.portfolio_id,
                    name="Paper Trading Main",
                    initial_capital=self.initial_capital,
                    cash=self.initial_capital,
                    total_value=self.initial_capital,
                    total_return=0,
                    max_drawdown=0,
                    position_count=0,
                    cash_ratio=100.0,
                    strategy="paper_trading",
                    rebalance_frequency="daily",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                self.session.execute(stmt)
                self.session.commit()
            except Exception:
                self.session.rollback()

    # ------------------------------------------------------------------
    # 1. 更新价格
    # ------------------------------------------------------------------

    def _update_position_prices(self, target_date: datetime.date):
        """从 PriceDaily 获取最新价格更新持仓"""
        positions = (
            self.session.query(PositionManagement)
            .filter(
                PositionManagement.portfolio_id == self.portfolio_id,
                PositionManagement.quantity > 0,
            )
            .all()
        )

        for pos in positions:
            price_row = (
                self.session.query(PriceDaily.close)
                .filter(
                    PriceDaily.symbol == pos.symbol,
                    PriceDaily.trade_date <= target_date,
                )
                .order_by(PriceDaily.trade_date.desc())
                .first()
            )
            if price_row and price_row.close:
                price = float(price_row.close)
                pos.current_price = price
                pos.market_value = price * pos.quantity
                if pos.avg_cost and pos.avg_cost > 0:
                    pos.unrealized_pnl = (price - float(pos.avg_cost)) * pos.quantity
                    pos.unrealized_pnl_pct = (price / float(pos.avg_cost) - 1) * 100
                if pos.entry_date:
                    pos.holding_days = (target_date - pos.entry_date).days

        try:
            self.session.commit()
        except Exception:
            self.session.rollback()

    # ------------------------------------------------------------------
    # 2. 生成交易订单
    # ------------------------------------------------------------------

    def _generate_orders(self, target_date: datetime.date) -> List[TradeOrder]:
        """从最新交易信号生成交易订单"""
        orders: List[TradeOrder] = []

        lookback = target_date - datetime.timedelta(days=3)

        # 卖出信号
        sell_signals = (
            self.session.query(TradingSignal)
            .filter(
                TradingSignal.source == "signal_engine",
                TradingSignal.signal_type == "sell",
                TradingSignal.signal_date >= lookback,
                TradingSignal.signal_date <= target_date,
            )
            .all()
        )

        for sig in sell_signals:
            pos = (
                self.session.query(PositionManagement)
                .filter(
                    PositionManagement.portfolio_id == self.portfolio_id,
                    PositionManagement.symbol == sig.symbol,
                    PositionManagement.quantity > 0,
                )
                .first()
            )
            if not pos:
                continue

            price = self._get_execution_price(sig.symbol, target_date)
            if price <= 0:
                continue

            qty = pos.quantity
            amount = qty * price
            commission = self._calc_sell_commission(amount)

            orders.append(TradeOrder(
                symbol=sig.symbol,
                action="sell",
                quantity=qty,
                price=price,
                amount=amount,
                commission=commission,
                net_amount=amount - commission,
                reason=f"signal_sell: strength={sig.signal_strength or 0:.0f}",
                signal_strength=float(sig.signal_strength or 0),
            ))

        # 买入信号
        buy_signals = (
            self.session.query(TradingSignal)
            .filter(
                TradingSignal.source == "signal_engine",
                TradingSignal.signal_type == "buy",
                TradingSignal.signal_date >= lookback,
                TradingSignal.signal_date <= target_date,
            )
            .order_by(TradingSignal.signal_strength.desc())
            .limit(10)
            .all()
        )

        # 计算可用资金
        portfolio = self._get_portfolio()
        available_cash = float(portfolio.cash) if portfolio and portfolio.cash else self.initial_capital
        # 先扣除卖出佣金、加上卖出回款
        for o in orders:
            if o.action == "sell":
                available_cash += o.net_amount

        # 每只最多投入可用资金的 20%
        max_per_stock = available_cash * 0.20

        for sig in buy_signals:
            existing = (
                self.session.query(PositionManagement)
                .filter(
                    PositionManagement.portfolio_id == self.portfolio_id,
                    PositionManagement.symbol == sig.symbol,
                    PositionManagement.quantity > 0,
                )
                .first()
            )
            if existing:
                continue

            price = self._get_execution_price(sig.symbol, target_date)
            if price <= 0:
                continue

            budget = min(max_per_stock, available_cash * 0.90)
            if budget < price * 100:
                continue

            qty = int(budget / price // 100) * 100
            if qty <= 0:
                continue

            amount = qty * price
            commission = self._calc_buy_commission(amount)
            total_cost = amount + commission

            if total_cost > available_cash:
                qty = int((available_cash - MIN_COMMISSION) / price // 100) * 100
                if qty <= 0:
                    continue
                amount = qty * price
                commission = self._calc_buy_commission(amount)
                total_cost = amount + commission

            available_cash -= total_cost

            orders.append(TradeOrder(
                symbol=sig.symbol,
                action="buy",
                quantity=qty,
                price=price,
                amount=amount,
                commission=commission,
                net_amount=total_cost,
                reason=f"signal_buy: strength={sig.signal_strength or 0:.0f}",
                signal_strength=float(sig.signal_strength or 0),
            ))

        # 止损检查
        stop_loss_orders = self._check_stop_loss(target_date)
        orders.extend(stop_loss_orders)

        return orders

    def _check_stop_loss(self, target_date: datetime.date) -> List[TradeOrder]:
        """止损检查：持仓亏损超过 10% 自动卖出"""
        orders = []
        positions = (
            self.session.query(PositionManagement)
            .filter(
                PositionManagement.portfolio_id == self.portfolio_id,
                PositionManagement.quantity > 0,
            )
            .all()
        )

        for pos in positions:
            if pos.unrealized_pnl_pct is not None and pos.unrealized_pnl_pct < -10:
                price = float(pos.current_price) if pos.current_price else 0
                if price <= 0:
                    continue
                qty = pos.quantity
                amount = qty * price
                commission = self._calc_sell_commission(amount)
                orders.append(TradeOrder(
                    symbol=pos.symbol,
                    action="sell",
                    quantity=qty,
                    price=price,
                    amount=amount,
                    commission=commission,
                    net_amount=amount - commission,
                    reason=f"stop_loss: pnl={pos.unrealized_pnl_pct:.1f}%",
                ))

            # 止损价触发
            if pos.stop_loss_price and pos.current_price:
                if float(pos.current_price) <= float(pos.stop_loss_price):
                    price = float(pos.current_price)
                    qty = pos.quantity
                    amount = qty * price
                    commission = self._calc_sell_commission(amount)
                    already = any(o.symbol == pos.symbol and o.action == "sell" for o in orders)
                    if not already:
                        orders.append(TradeOrder(
                            symbol=pos.symbol,
                            action="sell",
                            quantity=qty,
                            price=price,
                            amount=amount,
                            commission=commission,
                            net_amount=amount - commission,
                            reason=f"stop_loss_price: {pos.stop_loss_price:.2f}",
                        ))

        return orders

    # ------------------------------------------------------------------
    # 3. 执行交易
    # ------------------------------------------------------------------

    def _execute_order(self, order: TradeOrder, target_date: datetime.date):
        """执行单笔交易：更新持仓 + 现金 + 记录日志"""
        now = datetime.datetime.utcnow()

        portfolio = self._get_portfolio()
        if not portfolio:
            return

        if order.action == "buy":
            self._execute_buy(order, portfolio, target_date, now)
        else:
            self._execute_sell(order, portfolio, target_date, now)

        # 记录交易日志
        self._log_trade(order, target_date, now)

        try:
            self.session.commit()
        except Exception:
            self.session.rollback()

    def _execute_buy(
        self, order: TradeOrder, portfolio: Portfolio,
        target_date: datetime.date, now: datetime.datetime,
    ):
        portfolio.cash = (float(portfolio.cash) if portfolio.cash else 0) - order.net_amount

        pos = (
            self.session.query(PositionManagement)
            .filter(
                PositionManagement.portfolio_id == self.portfolio_id,
                PositionManagement.symbol == order.symbol,
            )
            .first()
        )

        if pos:
            old_value = float(pos.avg_cost or 0) * pos.quantity
            new_value = old_value + order.amount
            new_qty = pos.quantity + order.quantity
            pos.avg_cost = new_value / new_qty if new_qty > 0 else order.price
            pos.quantity = new_qty
            pos.current_price = order.price
            pos.market_value = new_qty * order.price
            pos.entry_date = pos.entry_date or target_date
            pos.holding_days = 0
            pos.updated_at = now
        else:
            try:
                stmt = insert(PositionManagement).values(
                    portfolio_id=self.portfolio_id,
                    symbol=order.symbol,
                    quantity=order.quantity,
                    avg_cost=order.price,
                    current_price=order.price,
                    market_value=order.amount,
                    entry_date=target_date,
                    holding_days=0,
                    updated_at=now,
                )
                self.session.execute(stmt)
            except Exception as e:
                logger.debug("Insert position failed for %s: %s", order.symbol, e)

    def _execute_sell(
        self, order: TradeOrder, portfolio: Portfolio,
        target_date: datetime.date, now: datetime.datetime,
    ):
        portfolio.cash = (float(portfolio.cash) if portfolio.cash else 0) + order.net_amount

        pos = (
            self.session.query(PositionManagement)
            .filter(
                PositionManagement.portfolio_id == self.portfolio_id,
                PositionManagement.symbol == order.symbol,
            )
            .first()
        )

        if pos:
            avg_cost = float(pos.avg_cost) if pos.avg_cost else order.price
            realized = (order.price - avg_cost) * order.quantity - order.commission
            pos.realized_pnl = (float(pos.realized_pnl) if pos.realized_pnl else 0) + realized
            pos.quantity = max(0, pos.quantity - order.quantity)
            pos.current_price = order.price
            pos.market_value = pos.quantity * order.price
            pos.last_trade_date = target_date
            pos.updated_at = now

            order.avg_cost = avg_cost
            order.realized_pnl = realized
            order.realized_pnl_pct = (order.price / avg_cost - 1) * 100 if avg_cost > 0 else 0

    def _log_trade(
        self, order: TradeOrder, target_date: datetime.date, now: datetime.datetime,
    ):
        """写入 PaperTradeLog"""
        try:
            stmt = insert(PaperTradeLog).values(
                portfolio_id=self.portfolio_id,
                trade_date=target_date,
                trade_time=now,
                symbol=order.symbol,
                action=order.action,
                quantity=order.quantity,
                price=order.price,
                amount=order.amount,
                commission=order.commission,
                signal_source="signal_engine",
                signal_strength=order.signal_strength,
                avg_cost=getattr(order, "avg_cost", None),
                realized_pnl=getattr(order, "realized_pnl", None),
                realized_pnl_pct=getattr(order, "realized_pnl_pct", None),
                holding_days=None,
                reason=order.reason,
                created_at=now,
            )
            self.session.execute(stmt)
        except Exception as e:
            logger.debug("Failed to log trade: %s", e)

    # ------------------------------------------------------------------
    # 4. 每日快照
    # ------------------------------------------------------------------

    def _take_snapshot(self, target_date: datetime.date) -> DailySnapshot:
        """计算当日快照"""
        portfolio = self._get_portfolio()
        cash = float(portfolio.cash) if portfolio and portfolio.cash else self.initial_capital

        # 持仓
        positions = (
            self.session.query(PositionManagement)
            .filter(
                PositionManagement.portfolio_id == self.portfolio_id,
                PositionManagement.quantity > 0,
            )
            .all()
        )

        market_value = sum(
            float(p.current_price or 0) * p.quantity for p in positions
        )
        total_value = cash + market_value
        nav = total_value / self.initial_capital

        # 前一日快照
        prev = (
            self.session.query(PaperTradingSnapshot)
            .filter(
                PaperTradingSnapshot.portfolio_id == self.portfolio_id,
                PaperTradingSnapshot.snapshot_date < target_date,
            )
            .order_by(PaperTradingSnapshot.snapshot_date.desc())
            .first()
        )

        prev_total = float(prev.total_value) if prev else self.initial_capital
        daily_return = (total_value / prev_total - 1) if prev_total > 0 else 0
        total_return = (total_value / self.initial_capital - 1)

        # 最大净值 → 回撤
        all_snapshots = (
            self.session.query(PaperTradingSnapshot.nav)
            .filter(PaperTradingSnapshot.portfolio_id == self.portfolio_id)
            .order_by(PaperTradingSnapshot.snapshot_date)
            .all()
        )
        all_navs = [float(s.nav) for s in all_snapshots] + [nav]
        peak_nav = max(all_navs) if all_navs else nav
        drawdown = (nav / peak_nav - 1) if peak_nav > 0 else 0

        prev_max_dd = float(prev.max_drawdown) if prev and prev.max_drawdown else 0
        max_drawdown = min(drawdown, prev_max_dd)

        # 基准
        benchmark_value, benchmark_return = self._get_benchmark(target_date)
        excess_return = total_return - benchmark_return

        # 当日交易数
        trades_today = (
            self.session.query(PaperTradeLog)
            .filter(
                PaperTradeLog.portfolio_id == self.portfolio_id,
                PaperTradeLog.trade_date == target_date,
            )
            .count()
        )

        # 持仓快照
        pos_dict = {}
        for p in positions:
            pos_dict[p.symbol] = {
                "qty": p.quantity,
                "price": float(p.current_price) if p.current_price else 0,
                "cost": float(p.avg_cost) if p.avg_cost else 0,
                "pnl_pct": float(p.unrealized_pnl_pct) if p.unrealized_pnl_pct else 0,
            }

        return DailySnapshot(
            date=target_date,
            cash=cash,
            market_value=market_value,
            total_value=total_value,
            nav=round(nav, 6),
            daily_return=round(daily_return, 6),
            total_return=round(total_return, 6),
            drawdown=round(drawdown, 6),
            max_drawdown=round(max_drawdown, 6),
            benchmark_value=benchmark_value,
            benchmark_return=round(benchmark_return, 6),
            excess_return=round(excess_return, 6),
            position_count=len(positions),
            trades_today=trades_today,
            positions=pos_dict,
        )

    # ------------------------------------------------------------------
    # 5. 基准
    # ------------------------------------------------------------------

    def _get_benchmark(self, target_date: datetime.date) -> Tuple[float, float]:
        """获取基准指数收益率"""
        # 找第一个快照日的基准
        first = (
            self.session.query(PaperTradingSnapshot.benchmark_value)
            .filter(
                PaperTradingSnapshot.portfolio_id == self.portfolio_id,
                PaperTradingSnapshot.benchmark_value.isnot(None),
            )
            .order_by(PaperTradingSnapshot.snapshot_date)
            .first()
        )
        initial_bench = float(first.benchmark_value) if first and first.benchmark_value else None

        # 当前基准值
        bench_row = (
            self.session.query(PriceDaily.close)
            .filter(
                PriceDaily.symbol == self.benchmark,
                PriceDaily.trade_date <= target_date,
            )
            .order_by(PriceDaily.trade_date.desc())
            .first()
        )

        if not bench_row or not bench_row.close:
            return 0.0, 0.0

        current_bench = float(bench_row.close)

        if initial_bench is None:
            initial_bench = current_bench

        bench_return = (current_bench / initial_bench - 1) if initial_bench > 0 else 0

        return current_bench, bench_return

    # ------------------------------------------------------------------
    # 6. 持久化
    # ------------------------------------------------------------------

    def _persist_snapshot(self, snapshot: DailySnapshot):
        """写入 PaperTradingSnapshot"""
        existing = (
            self.session.query(PaperTradingSnapshot)
            .filter(
                PaperTradingSnapshot.portfolio_id == self.portfolio_id,
                PaperTradingSnapshot.snapshot_date == snapshot.date,
            )
            .first()
        )

        pos_json = json.dumps(snapshot.positions, ensure_ascii=False, default=str)

        if existing:
            existing.cash = snapshot.cash
            existing.market_value = snapshot.market_value
            existing.total_value = snapshot.total_value
            existing.nav = snapshot.nav
            existing.daily_return = snapshot.daily_return
            existing.total_return = snapshot.total_return
            existing.drawdown = snapshot.drawdown
            existing.max_drawdown = snapshot.max_drawdown
            existing.benchmark_value = snapshot.benchmark_value
            existing.benchmark_return = snapshot.benchmark_return
            existing.excess_return = snapshot.excess_return
            existing.position_count = snapshot.position_count
            existing.positions_json = pos_json
            existing.trades_today = snapshot.trades_today
        else:
            try:
                stmt = insert(PaperTradingSnapshot).values(
                    portfolio_id=self.portfolio_id,
                    snapshot_date=snapshot.date,
                    cash=snapshot.cash,
                    market_value=snapshot.market_value,
                    total_value=snapshot.total_value,
                    nav=snapshot.nav,
                    daily_return=snapshot.daily_return,
                    total_return=snapshot.total_return,
                    drawdown=snapshot.drawdown,
                    max_drawdown=snapshot.max_drawdown,
                    benchmark_value=snapshot.benchmark_value,
                    benchmark_return=snapshot.benchmark_return,
                    excess_return=snapshot.excess_return,
                    position_count=snapshot.position_count,
                    positions_json=pos_json,
                    trades_today=snapshot.trades_today,
                    created_at=datetime.datetime.utcnow(),
                )
                self.session.execute(stmt)
            except Exception as e:
                logger.debug("Failed to persist snapshot: %s", e)

        try:
            self.session.commit()
        except Exception:
            self.session.rollback()

    def _update_portfolio_record(self, snapshot: DailySnapshot):
        """更新 Portfolio 表"""
        portfolio = self._get_portfolio()
        if not portfolio:
            return

        portfolio.cash = snapshot.cash
        portfolio.total_value = snapshot.total_value
        portfolio.total_return = snapshot.total_return * 100
        portfolio.daily_return = snapshot.daily_return * 100
        portfolio.max_drawdown = snapshot.max_drawdown * 100
        portfolio.position_count = snapshot.position_count
        portfolio.cash_ratio = (snapshot.cash / snapshot.total_value * 100) if snapshot.total_value > 0 else 100
        portfolio.updated_at = datetime.datetime.utcnow()

        # 夏普比率（需要历史数据）
        daily_rets = (
            self.session.query(PaperTradingSnapshot.daily_return)
            .filter(PaperTradingSnapshot.portfolio_id == self.portfolio_id)
            .order_by(PaperTradingSnapshot.snapshot_date)
            .all()
        )
        if len(daily_rets) >= 10:
            rets = [float(r.daily_return or 0) for r in daily_rets]
            avg_ret = np.mean(rets) * 252
            std_ret = np.std(rets) * np.sqrt(252)
            portfolio.sharpe_ratio = round((avg_ret - 0.02) / std_ret, 3) if std_ret > 0 else 0

        try:
            self.session.commit()
        except Exception:
            self.session.rollback()

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _get_portfolio(self) -> Optional[Portfolio]:
        return (
            self.session.query(Portfolio)
            .filter(Portfolio.portfolio_id == self.portfolio_id)
            .first()
        )

    def _get_execution_price(self, symbol: str, target_date: datetime.date) -> float:
        """获取执行价格（使用收盘价模拟）"""
        row = (
            self.session.query(PriceDaily.close)
            .filter(
                PriceDaily.symbol == symbol,
                PriceDaily.trade_date <= target_date,
            )
            .order_by(PriceDaily.trade_date.desc())
            .first()
        )
        return float(row.close) if row and row.close else 0.0

    @staticmethod
    def _calc_buy_commission(amount: float) -> float:
        return max(MIN_COMMISSION, amount * BUY_COMMISSION_RATE)

    @staticmethod
    def _calc_sell_commission(amount: float) -> float:
        broker = max(MIN_COMMISSION, amount * SELL_COMMISSION_RATE)
        stamp = amount * STAMP_TAX_RATE
        return broker + stamp


# ===================================================================
# 便捷入口
# ===================================================================

def run_daily_paper_trading(
    target_date: Optional[datetime.date] = None,
) -> PaperTradingReport:
    """供调度器调用的每日模拟盘入口"""
    from ...core.database import SessionLocal

    session = SessionLocal()
    try:
        engine = PaperTradingEngine(session=session)
        report = engine.run_daily(target_date)
        return report
    finally:
        session.close()


# ===================================================================
# 查询接口
# ===================================================================

def get_nav_history(
    portfolio_id: str = PAPER_PORTFOLIO_ID,
    days: int = 365,
) -> List[dict]:
    """获取净值曲线"""
    from ...core.database import SessionLocal

    session = SessionLocal()
    try:
        cutoff = datetime.date.today() - datetime.timedelta(days=days)
        rows = (
            session.query(PaperTradingSnapshot)
            .filter(
                PaperTradingSnapshot.portfolio_id == portfolio_id,
                PaperTradingSnapshot.snapshot_date >= cutoff,
            )
            .order_by(PaperTradingSnapshot.snapshot_date)
            .all()
        )
        return [
            {
                "date": r.snapshot_date.isoformat(),
                "nav": float(r.nav),
                "total_return": float(r.total_return) if r.total_return else 0,
                "drawdown": float(r.drawdown) if r.drawdown else 0,
                "max_drawdown": float(r.max_drawdown) if r.max_drawdown else 0,
                "benchmark_return": float(r.benchmark_return) if r.benchmark_return else 0,
                "excess_return": float(r.excess_return) if r.excess_return else 0,
                "position_count": r.position_count,
                "daily_return": float(r.daily_return) if r.daily_return else 0,
            }
            for r in rows
        ]
    finally:
        session.close()


def get_trade_history(
    portfolio_id: str = PAPER_PORTFOLIO_ID,
    days: int = 90,
    symbol: Optional[str] = None,
) -> List[dict]:
    """获取交易记录"""
    from ...core.database import SessionLocal

    session = SessionLocal()
    try:
        cutoff = datetime.date.today() - datetime.timedelta(days=days)
        q = (
            session.query(PaperTradeLog)
            .filter(
                PaperTradeLog.portfolio_id == portfolio_id,
                PaperTradeLog.trade_date >= cutoff,
            )
        )
        if symbol:
            q = q.filter(PaperTradeLog.symbol == symbol.upper())

        rows = q.order_by(PaperTradeLog.trade_date.desc()).limit(500).all()
        return [
            {
                "date": r.trade_date.isoformat(),
                "symbol": r.symbol,
                "action": r.action,
                "quantity": r.quantity,
                "price": float(r.price),
                "amount": float(r.amount),
                "commission": float(r.commission) if r.commission else 0,
                "realized_pnl": float(r.realized_pnl) if r.realized_pnl else None,
                "realized_pnl_pct": round(float(r.realized_pnl_pct), 2) if r.realized_pnl_pct else None,
                "reason": r.reason,
            }
            for r in rows
        ]
    finally:
        session.close()
