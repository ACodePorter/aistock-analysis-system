"""
投资组合优化模块（Portfolio Optimization）

将交易信号转化为带有风控约束的仓位分配方案。

核心功能：
1. 三种分配策略 — 等权重 / 风险平价 / 预测收益加权
2. 风险控制     — 单只上限 / 行业集中度 / 最大回撤
3. 动态再平衡   — 每日/每周，根据预测变化调整
4. 组合风险指标 — 波动率 / 最大回撤 / 夏普比率
"""

from __future__ import annotations

import datetime
import json
import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from ...core.models import (
    Portfolio,
    PositionManagement,
    PriceDaily,
    Watchlist,
)

logger = logging.getLogger(__name__)

PORTFOLIO_ID = "signal_engine_default"


# ===================================================================
# 数据结构
# ===================================================================

class AllocationMethod(str, Enum):
    EQUAL_WEIGHT = "equal_weight"
    RISK_PARITY = "risk_parity"
    RETURN_WEIGHTED = "return_weighted"


@dataclass
class AssetInfo:
    """单只资产用于优化的数据"""
    symbol: str
    name: Optional[str] = None
    sector: Optional[str] = None
    current_price: float = 0.0
    predicted_return: float = 0.0
    signal_strength: float = 0.0
    annual_volatility: float = 0.0
    daily_returns: Optional[np.ndarray] = None
    # 优化结果
    raw_weight: float = 0.0
    target_weight: float = 0.0
    current_weight: float = 0.0
    quantity: int = 0
    market_value: float = 0.0


@dataclass
class RiskMetrics:
    """组合风险指标"""
    portfolio_volatility: float = 0.0
    portfolio_annual_vol: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    diversification_ratio: float = 0.0
    max_single_weight: float = 0.0
    max_sector_weight: float = 0.0
    hhi: float = 0.0  # Herfindahl-Hirschman Index


@dataclass
class RebalanceAction:
    """单只股票的再平衡操作"""
    symbol: str
    name: Optional[str] = None
    action: str = "hold"  # buy / sell / hold
    current_weight: float = 0.0
    target_weight: float = 0.0
    weight_delta: float = 0.0
    current_quantity: int = 0
    target_quantity: int = 0
    quantity_delta: int = 0
    current_price: float = 0.0
    trade_value: float = 0.0


@dataclass
class PortfolioResult:
    """组合优化结果"""
    portfolio_id: str
    optimization_date: datetime.date
    method: str
    total_capital: float

    # 资产配置
    assets: List[AssetInfo] = field(default_factory=list)
    cash_weight: float = 0.0
    cash_amount: float = 0.0

    # 风险指标
    risk: RiskMetrics = field(default_factory=RiskMetrics)

    # 再平衡操作
    rebalance_actions: List[RebalanceAction] = field(default_factory=list)
    needs_rebalance: bool = False

    def summary(self) -> str:
        lines = [
            f"=== 投资组合优化报告 {self.optimization_date} ===",
            f"策略: {self.method}  总资金: {self.total_capital:,.0f}",
            f"现金: {self.cash_amount:,.0f} ({self.cash_weight:.1%})",
            "",
            f"{'Symbol':<10s} {'Name':<8s} {'Weight':>8s} {'Price':>8s} "
            f"{'Qty':>6s} {'Value':>10s} {'Ret5d':>8s} {'Vol':>7s} {'Sector':<8s}",
            "-" * 80,
        ]
        for a in sorted(self.assets, key=lambda x: x.target_weight, reverse=True):
            if a.target_weight < 0.001:
                continue
            lines.append(
                f"{a.symbol:<10s} {(a.name or ''):<8s} {a.target_weight:>7.1%} "
                f"{a.current_price:>8.2f} {a.quantity:>6d} "
                f"{a.market_value:>10,.0f} {a.predicted_return:>+7.2%} "
                f"{a.annual_volatility:>6.1%} {(a.sector or ''):<8s}"
            )
        lines.extend([
            "",
            "--- 风险指标 ---",
            f"  组合波动率(年化): {self.risk.portfolio_annual_vol:.2%}",
            f"  最大回撤:         {self.risk.max_drawdown:.2%}",
            f"  夏普比率:         {self.risk.sharpe_ratio:.2f}",
            f"  分散化比率:       {self.risk.diversification_ratio:.2f}",
            f"  最大单只仓位:     {self.risk.max_single_weight:.1%}",
            f"  最大行业仓位:     {self.risk.max_sector_weight:.1%}",
            f"  HHI:              {self.risk.hhi:.4f}",
        ])

        if self.rebalance_actions:
            lines.extend(["", "--- 再平衡操作 ---"])
            for ra in self.rebalance_actions:
                if ra.action == "hold":
                    continue
                lines.append(
                    f"  {ra.action.upper():<5s} {ra.symbol:<10s} "
                    f"{ra.current_weight:>6.1%} → {ra.target_weight:>6.1%} "
                    f"Δ{ra.quantity_delta:+d}股 ≈ {ra.trade_value:+,.0f}元"
                )

        return "\n".join(lines)


# ===================================================================
# 投资组合优化器
# ===================================================================

class PortfolioOptimizer:
    """投资组合优化引擎

    参数：
        session:              SQLAlchemy Session
        total_capital:        总资金
        method:               分配策略
        max_single_weight:    单只最大仓位（如 0.20 = 20%）
        max_sector_weight:    行业最大仓位
        max_total_position:   最大总仓位（留部分现金）
        min_position_weight:  最小仓位（低于此值则不持有）
        max_drawdown_limit:   最大回撤限制
        rebalance_threshold:  权重偏离阈值，超过才触发再平衡
        risk_free_rate:       无风险利率（年化）
        lookback_days:        波动率/相关性计算回溯期
    """

    def __init__(
        self,
        session: Session,
        total_capital: float = 100_000.0,
        method: str = "risk_parity",
        max_single_weight: float = 0.20,
        max_sector_weight: float = 0.40,
        max_total_position: float = 0.90,
        min_position_weight: float = 0.02,
        max_drawdown_limit: float = 0.15,
        rebalance_threshold: float = 0.05,
        risk_free_rate: float = 0.02,
        lookback_days: int = 60,
    ):
        self.session = session
        self.total_capital = total_capital
        self.method = AllocationMethod(method)
        self.max_single_weight = max_single_weight
        self.max_sector_weight = max_sector_weight
        self.max_total_position = max_total_position
        self.min_position_weight = min_position_weight
        self.max_drawdown_limit = max_drawdown_limit
        self.rebalance_threshold = rebalance_threshold
        self.risk_free_rate = risk_free_rate
        self.lookback_days = lookback_days

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def optimize(
        self,
        buy_symbols: List[str],
        sell_symbols: Optional[List[str]] = None,
        target_date: Optional[datetime.date] = None,
        predicted_returns: Optional[Dict[str, float]] = None,
        signal_strengths: Optional[Dict[str, float]] = None,
    ) -> PortfolioResult:
        """组合优化主流程

        Args:
            buy_symbols:       推荐买入股票列表
            sell_symbols:      推荐卖出股票列表
            target_date:       优化日期
            predicted_returns: {symbol: predicted_5d_return}
            signal_strengths:  {symbol: signal_strength_0_100}
        """
        if target_date is None:
            target_date = datetime.date.today()

        predicted_returns = predicted_returns or {}
        signal_strengths = signal_strengths or {}
        sell_symbols = sell_symbols or []

        logger.info(
            "PortfolioOptimizer: method=%s, buy=%d, sell=%d, capital=%.0f",
            self.method.value, len(buy_symbols), len(sell_symbols), self.total_capital,
        )

        # 1. 构建资产信息
        assets = self._build_asset_info(
            buy_symbols, target_date, predicted_returns, signal_strengths,
        )
        if not assets:
            return PortfolioResult(
                portfolio_id=PORTFOLIO_ID,
                optimization_date=target_date,
                method=self.method.value,
                total_capital=self.total_capital,
                cash_weight=1.0,
                cash_amount=self.total_capital,
            )

        # 2. 计算原始权重
        self._compute_raw_weights(assets)

        # 3. 施加风控约束
        self._apply_risk_constraints(assets)

        # 4. 计算股数和市值
        investable = self.total_capital * self.max_total_position
        self._compute_quantities(assets, investable)

        # 5. 计算组合风险指标
        risk = self._compute_risk_metrics(assets)

        # 6. 检查最大回撤约束 → 如超限则缩减
        if risk.max_drawdown > self.max_drawdown_limit:
            self._apply_drawdown_constraint(assets, risk)
            self._compute_quantities(assets, investable)
            risk = self._compute_risk_metrics(assets)

        # 7. 生成再平衡操作
        rebalance_actions, needs_rebalance = self._compute_rebalance(
            assets, sell_symbols, target_date,
        )

        # 8. 汇总
        total_invested = sum(a.market_value for a in assets)
        cash_amount = self.total_capital - total_invested
        cash_weight = cash_amount / self.total_capital if self.total_capital > 0 else 1.0

        result = PortfolioResult(
            portfolio_id=PORTFOLIO_ID,
            optimization_date=target_date,
            method=self.method.value,
            total_capital=self.total_capital,
            assets=assets,
            cash_weight=cash_weight,
            cash_amount=cash_amount,
            risk=risk,
            rebalance_actions=rebalance_actions,
            needs_rebalance=needs_rebalance,
        )

        # 9. 持久化
        self._persist(result, target_date)

        logger.info(
            "Portfolio optimized: %d assets, invested=%.0f, cash=%.0f, vol=%.2f%%",
            len([a for a in assets if a.target_weight > 0]),
            total_invested, cash_amount, risk.portfolio_annual_vol * 100,
        )
        return result

    # ------------------------------------------------------------------
    # 1. 资产信息
    # ------------------------------------------------------------------

    def _build_asset_info(
        self,
        symbols: List[str],
        target_date: datetime.date,
        predicted_returns: Dict[str, float],
        signal_strengths: Dict[str, float],
    ) -> List[AssetInfo]:
        assets = []
        for sym in symbols:
            info = self._load_single_asset(sym, target_date)
            if info is None:
                continue
            info.predicted_return = predicted_returns.get(sym, info.predicted_return)
            info.signal_strength = signal_strengths.get(sym, info.signal_strength)
            assets.append(info)
        return assets

    def _load_single_asset(
        self, symbol: str, target_date: datetime.date,
    ) -> Optional[AssetInfo]:
        # 基本信息
        wl = (
            self.session.query(Watchlist.name, Watchlist.sector)
            .filter(Watchlist.symbol == symbol)
            .first()
        )
        name = wl.name if wl else None
        sector = wl.sector if wl else None

        # 价格历史
        prices = (
            self.session.query(PriceDaily.close, PriceDaily.trade_date)
            .filter(
                PriceDaily.symbol == symbol,
                PriceDaily.trade_date <= target_date,
            )
            .order_by(PriceDaily.trade_date.desc())
            .limit(self.lookback_days)
            .all()
        )
        if not prices or len(prices) < 20:
            return None

        closes = np.array([float(p.close) for p in reversed(prices) if p.close])
        if len(closes) < 20:
            return None

        daily_rets = np.diff(np.log(closes))
        annual_vol = float(np.std(daily_rets) * np.sqrt(252))

        # 从 PositionManagement 加载当前信号强度和预测收益
        pos = (
            self.session.query(PositionManagement)
            .filter(
                PositionManagement.portfolio_id == PORTFOLIO_ID,
                PositionManagement.symbol == symbol,
            )
            .first()
        )

        predicted_ret = 0.0
        sig_strength = 0.0
        if pos:
            if pos.take_profit_price and pos.current_price and pos.current_price > 0:
                predicted_ret = (float(pos.take_profit_price) / float(pos.current_price)) - 1
            sig_strength = float(pos.target_weight or 0) * 10

        return AssetInfo(
            symbol=symbol,
            name=name,
            sector=sector,
            current_price=float(closes[-1]),
            predicted_return=predicted_ret,
            signal_strength=sig_strength,
            annual_volatility=max(annual_vol, 0.01),
            daily_returns=daily_rets,
        )

    # ------------------------------------------------------------------
    # 2. 原始权重计算
    # ------------------------------------------------------------------

    def _compute_raw_weights(self, assets: List[AssetInfo]):
        n = len(assets)
        if n == 0:
            return

        if self.method == AllocationMethod.EQUAL_WEIGHT:
            self._equal_weight(assets)
        elif self.method == AllocationMethod.RISK_PARITY:
            self._risk_parity(assets)
        elif self.method == AllocationMethod.RETURN_WEIGHTED:
            self._return_weighted(assets)
        else:
            self._equal_weight(assets)

    def _equal_weight(self, assets: List[AssetInfo]):
        n = len(assets)
        w = 1.0 / n if n > 0 else 0
        for a in assets:
            a.raw_weight = w

    def _risk_parity(self, assets: List[AssetInfo]):
        """风险平价：每只股票贡献相等的组合波动率"""
        inv_vols = []
        for a in assets:
            inv_vols.append(1.0 / a.annual_volatility)

        total_inv = sum(inv_vols)
        if total_inv <= 0:
            self._equal_weight(assets)
            return

        for a, iv in zip(assets, inv_vols):
            a.raw_weight = iv / total_inv

    def _return_weighted(self, assets: List[AssetInfo]):
        """基于预测收益加权：正收益按比例分配，负收益置零"""
        positive_rets = []
        for a in assets:
            score = max(0, a.predicted_return) + max(0, a.signal_strength / 200)
            positive_rets.append(score)

        total = sum(positive_rets)
        if total <= 0:
            self._equal_weight(assets)
            return

        for a, pr in zip(assets, positive_rets):
            a.raw_weight = pr / total

    # ------------------------------------------------------------------
    # 3. 风控约束
    # ------------------------------------------------------------------

    def _apply_risk_constraints(self, assets: List[AssetInfo]):
        """施加风控约束后的目标权重"""
        for a in assets:
            a.target_weight = a.raw_weight

        # 3a. 单只上限
        self._clip_single_weight(assets)

        # 3b. 行业集中度
        self._clip_sector_weight(assets)

        # 3c. 最小持仓过滤
        for a in assets:
            if a.target_weight < self.min_position_weight:
                a.target_weight = 0.0

        # 3d. 重新归一化（只在仓位范围内）
        self._renormalize(assets)

    def _clip_single_weight(self, assets: List[AssetInfo]):
        """裁剪超过 max_single_weight 的仓位，多余部分按比例分配给其余"""
        for _ in range(5):
            excess = 0.0
            free_count = 0
            for a in assets:
                if a.target_weight > self.max_single_weight:
                    excess += a.target_weight - self.max_single_weight
                    a.target_weight = self.max_single_weight
                elif a.target_weight > 0:
                    free_count += 1

            if excess <= 1e-9 or free_count == 0:
                break

            add_each = excess / free_count
            for a in assets:
                if 0 < a.target_weight < self.max_single_weight:
                    a.target_weight = min(self.max_single_weight, a.target_weight + add_each)

    def _clip_sector_weight(self, assets: List[AssetInfo]):
        """裁剪行业总权重到 max_sector_weight"""
        sector_map: Dict[str, List[AssetInfo]] = {}
        for a in assets:
            key = a.sector or "unknown"
            sector_map.setdefault(key, []).append(a)

        for sector, group in sector_map.items():
            sector_total = sum(a.target_weight for a in group)
            if sector_total > self.max_sector_weight:
                scale = self.max_sector_weight / sector_total
                for a in group:
                    a.target_weight *= scale

    def _renormalize(self, assets: List[AssetInfo]):
        """归一化权重使总和 = max_total_position"""
        total = sum(a.target_weight for a in assets)
        if total <= 0:
            return
        target_total = min(total, self.max_total_position)
        scale = target_total / total
        for a in assets:
            a.target_weight *= scale

    # ------------------------------------------------------------------
    # 4. 计算股数与市值
    # ------------------------------------------------------------------

    def _compute_quantities(self, assets: List[AssetInfo], investable: float):
        for a in assets:
            if a.target_weight <= 0 or a.current_price <= 0:
                a.quantity = 0
                a.market_value = 0
                continue
            target_value = investable * a.target_weight / self.max_total_position
            raw_qty = target_value / a.current_price
            # A 股 100 股整手
            a.quantity = max(0, int(raw_qty // 100) * 100)
            a.market_value = a.quantity * a.current_price

        # 重算实际权重
        total_value = sum(a.market_value for a in assets)
        if total_value > 0:
            for a in assets:
                a.current_weight = a.market_value / self.total_capital

    # ------------------------------------------------------------------
    # 5. 组合风险指标
    # ------------------------------------------------------------------

    def _compute_risk_metrics(self, assets: List[AssetInfo]) -> RiskMetrics:
        active = [a for a in assets if a.target_weight > 0 and a.daily_returns is not None]
        if not active:
            return RiskMetrics()

        # 构建收益矩阵
        min_len = min(len(a.daily_returns) for a in active)
        if min_len < 10:
            return RiskMetrics()

        returns_matrix = np.column_stack([
            a.daily_returns[-min_len:] for a in active
        ])
        weights = np.array([a.target_weight for a in active])
        w_sum = weights.sum()
        if w_sum > 0:
            weights = weights / w_sum

        # 协方差矩阵
        cov_matrix = np.cov(returns_matrix, rowvar=False)
        if cov_matrix.ndim == 0:
            cov_matrix = np.array([[float(cov_matrix)]])

        # 组合日波动率
        port_var = float(weights @ cov_matrix @ weights)
        port_daily_vol = math.sqrt(max(port_var, 0))
        port_annual_vol = port_daily_vol * math.sqrt(252)

        # 组合日收益序列
        port_returns = returns_matrix @ weights
        cum_returns = np.cumsum(port_returns)
        running_max = np.maximum.accumulate(cum_returns)
        drawdowns = cum_returns - running_max
        max_dd = float(abs(np.min(drawdowns))) if len(drawdowns) > 0 else 0

        # 夏普比率
        ann_ret = float(np.mean(port_returns) * 252)
        sharpe = (ann_ret - self.risk_free_rate) / port_annual_vol if port_annual_vol > 0 else 0

        # 分散化比率 = 加权平均个股波动率 / 组合波动率
        weighted_avg_vol = sum(
            a.annual_volatility * a.target_weight / w_sum
            for a in active
        ) if w_sum > 0 else 0
        div_ratio = weighted_avg_vol / port_annual_vol if port_annual_vol > 0 else 1

        # 行业集中度
        sector_weights: Dict[str, float] = {}
        for a in active:
            key = a.sector or "unknown"
            sector_weights[key] = sector_weights.get(key, 0) + a.target_weight
        max_sector = max(sector_weights.values()) if sector_weights else 0

        all_weights = [a.target_weight for a in assets if a.target_weight > 0]
        hhi = sum(w ** 2 for w in all_weights)

        return RiskMetrics(
            portfolio_volatility=port_daily_vol,
            portfolio_annual_vol=port_annual_vol,
            max_drawdown=max_dd,
            sharpe_ratio=round(sharpe, 3),
            diversification_ratio=round(div_ratio, 3),
            max_single_weight=max(all_weights) if all_weights else 0,
            max_sector_weight=max_sector,
            hhi=round(hhi, 6),
        )

    # ------------------------------------------------------------------
    # 6. 最大回撤约束
    # ------------------------------------------------------------------

    def _apply_drawdown_constraint(
        self, assets: List[AssetInfo], risk: RiskMetrics,
    ):
        """如果预期回撤超限，按比例缩减仓位"""
        if risk.max_drawdown <= 0:
            return
        scale = self.max_drawdown_limit / risk.max_drawdown
        scale = min(scale, 1.0)
        logger.info(
            "Drawdown constraint: %.2f%% > %.2f%% → scaling weights by %.2f",
            risk.max_drawdown * 100, self.max_drawdown_limit * 100, scale,
        )
        for a in assets:
            a.target_weight *= scale

    # ------------------------------------------------------------------
    # 7. 再平衡
    # ------------------------------------------------------------------

    def _compute_rebalance(
        self,
        assets: List[AssetInfo],
        sell_symbols: List[str],
        target_date: datetime.date,
    ) -> Tuple[List[RebalanceAction], bool]:
        """计算再平衡操作"""
        current_positions = self._load_current_positions()
        target_map = {a.symbol: a for a in assets}

        actions: List[RebalanceAction] = []
        needs_rebalance = False

        all_symbols = set(list(target_map.keys()) + list(current_positions.keys()) + sell_symbols)

        for sym in sorted(all_symbols):
            cur = current_positions.get(sym, {})
            cur_qty = cur.get("quantity", 0)
            cur_price = cur.get("current_price", 0)
            cur_weight = (cur_qty * cur_price / self.total_capital) if cur_price > 0 else 0

            target_asset = target_map.get(sym)
            target_qty = target_asset.quantity if target_asset else 0
            target_weight = target_asset.target_weight if target_asset else 0.0
            price = target_asset.current_price if target_asset else cur_price

            # 强制卖出信号
            if sym in sell_symbols:
                target_qty = 0
                target_weight = 0.0

            delta_qty = target_qty - cur_qty
            delta_weight = target_weight - cur_weight

            if abs(delta_weight) < self.rebalance_threshold and abs(delta_qty) < 100:
                action_type = "hold"
            elif delta_qty > 0:
                action_type = "buy"
                needs_rebalance = True
            elif delta_qty < 0:
                action_type = "sell"
                needs_rebalance = True
            else:
                action_type = "hold"

            wl = self.session.query(Watchlist.name).filter(Watchlist.symbol == sym).first()

            actions.append(RebalanceAction(
                symbol=sym,
                name=wl.name if wl else None,
                action=action_type,
                current_weight=round(cur_weight, 4),
                target_weight=round(target_weight, 4),
                weight_delta=round(delta_weight, 4),
                current_quantity=cur_qty,
                target_quantity=target_qty,
                quantity_delta=delta_qty,
                current_price=price,
                trade_value=round(delta_qty * price, 2) if price else 0,
            ))

        return actions, needs_rebalance

    def _load_current_positions(self) -> Dict[str, dict]:
        rows = (
            self.session.query(PositionManagement)
            .filter(
                PositionManagement.portfolio_id == PORTFOLIO_ID,
                PositionManagement.quantity > 0,
            )
            .all()
        )
        return {
            r.symbol: {
                "quantity": r.quantity,
                "avg_cost": float(r.avg_cost) if r.avg_cost else 0,
                "current_price": float(r.current_price) if r.current_price else 0,
                "holding_days": r.holding_days or 0,
            }
            for r in rows
        }

    # ------------------------------------------------------------------
    # 8. 持久化
    # ------------------------------------------------------------------

    def _persist(self, result: PortfolioResult, target_date: datetime.date):
        """将优化结果写入 Portfolio 和 PositionManagement 表"""
        now = datetime.datetime.utcnow()

        # 更新或创建 Portfolio
        portfolio = (
            self.session.query(Portfolio)
            .filter(Portfolio.portfolio_id == PORTFOLIO_ID)
            .first()
        )
        if portfolio:
            portfolio.total_value = self.total_capital - result.cash_amount + sum(
                a.market_value for a in result.assets
            )
            portfolio.cash = result.cash_amount
            portfolio.cash_ratio = result.cash_weight * 100
            portfolio.position_count = len([a for a in result.assets if a.quantity > 0])
            portfolio.max_drawdown = result.risk.max_drawdown * 100
            portfolio.sharpe_ratio = result.risk.sharpe_ratio
            portfolio.strategy = result.method
            portfolio.max_single_position = self.max_single_weight * 100
            portfolio.max_sector_position = self.max_sector_weight * 100
            portfolio.updated_at = now
        else:
            try:
                stmt = insert(Portfolio).values(
                    portfolio_id=PORTFOLIO_ID,
                    name="Signal Engine Portfolio",
                    initial_capital=self.total_capital,
                    cash=result.cash_amount,
                    total_value=self.total_capital,
                    cash_ratio=result.cash_weight * 100,
                    position_count=len([a for a in result.assets if a.quantity > 0]),
                    max_drawdown=result.risk.max_drawdown * 100,
                    sharpe_ratio=result.risk.sharpe_ratio,
                    strategy=result.method,
                    max_single_position=self.max_single_weight * 100,
                    max_total_position=self.max_total_position * 100,
                    max_sector_position=self.max_sector_weight * 100,
                    rebalance_frequency="daily",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                self.session.execute(stmt)
            except Exception as e:
                logger.warning("Failed to create portfolio record: %s", e)

        # 更新 PositionManagement
        for a in result.assets:
            pos = (
                self.session.query(PositionManagement)
                .filter(
                    PositionManagement.portfolio_id == PORTFOLIO_ID,
                    PositionManagement.symbol == a.symbol,
                )
                .first()
            )
            if pos:
                pos.quantity = a.quantity
                pos.current_price = a.current_price
                pos.market_value = a.market_value
                pos.weight = a.current_weight * 100
                pos.target_weight = a.target_weight * 100
                pos.updated_at = now
            elif a.quantity > 0:
                try:
                    stmt = insert(PositionManagement).values(
                        portfolio_id=PORTFOLIO_ID,
                        symbol=a.symbol,
                        quantity=a.quantity,
                        avg_cost=a.current_price,
                        current_price=a.current_price,
                        market_value=a.market_value,
                        weight=a.current_weight * 100,
                        target_weight=a.target_weight * 100,
                        entry_date=target_date,
                        holding_days=0,
                        updated_at=now,
                    )
                    self.session.execute(stmt)
                except Exception as e:
                    logger.debug("Failed to insert position for %s: %s", a.symbol, e)

        try:
            self.session.commit()
        except Exception as e:
            logger.error("Failed to persist portfolio: %s", e)
            self.session.rollback()


# ===================================================================
# 便捷入口
# ===================================================================

def optimize_portfolio(
    buy_symbols: List[str],
    sell_symbols: Optional[List[str]] = None,
    method: str = "risk_parity",
    total_capital: float = 100_000.0,
    max_single_weight: float = 0.20,
    **kwargs,
) -> PortfolioResult:
    """便捷入口：自动创建 Session 并运行组合优化"""
    from ...core.database import SessionLocal

    session = SessionLocal()
    try:
        optimizer = PortfolioOptimizer(
            session=session,
            total_capital=total_capital,
            method=method,
            max_single_weight=max_single_weight,
            **kwargs,
        )
        return optimizer.optimize(buy_symbols, sell_symbols)
    finally:
        session.close()


def run_daily_portfolio_optimization() -> PortfolioResult:
    """供调度器调用：从最新信号自动优化组合"""
    from ...core.database import SessionLocal
    from .signal_engine import PORTFOLIO_ID as SIG_PORT_ID

    session = SessionLocal()
    try:
        from ...core.models import TradingSignal
        today = datetime.date.today()
        lookback = today - datetime.timedelta(days=3)

        buy_rows = (
            session.query(TradingSignal.symbol)
            .filter(
                TradingSignal.source == "signal_engine",
                TradingSignal.signal_type == "buy",
                TradingSignal.signal_date >= lookback,
            )
            .order_by(TradingSignal.signal_strength.desc())
            .limit(20)
            .all()
        )
        sell_rows = (
            session.query(TradingSignal.symbol)
            .filter(
                TradingSignal.source == "signal_engine",
                TradingSignal.signal_type == "sell",
                TradingSignal.signal_date >= lookback,
            )
            .all()
        )

        buy_syms = [r.symbol for r in buy_rows]
        sell_syms = [r.symbol for r in sell_rows]

        # 读取预测收益
        pred_rets = {}
        sig_strengths = {}
        for row in buy_rows:
            sig = (
                session.query(TradingSignal)
                .filter(
                    TradingSignal.symbol == row.symbol,
                    TradingSignal.source == "signal_engine",
                    TradingSignal.signal_date >= lookback,
                )
                .order_by(TradingSignal.signal_date.desc())
                .first()
            )
            if sig and sig.factors:
                try:
                    factors = json.loads(sig.factors)
                    pred_rets[row.symbol] = factors.get("predicted_return_5d", 0)
                    sig_strengths[row.symbol] = float(sig.signal_strength or 0)
                except Exception:
                    pass

        # 读取组合资本
        portfolio = session.query(Portfolio).filter(
            Portfolio.portfolio_id == PORTFOLIO_ID
        ).first()
        capital = float(portfolio.initial_capital) if portfolio else 100_000.0

        optimizer = PortfolioOptimizer(
            session=session,
            total_capital=capital,
            method="risk_parity",
        )
        result = optimizer.optimize(
            buy_syms, sell_syms,
            predicted_returns=pred_rets,
            signal_strengths=sig_strengths,
        )

        logger.info(
            "Daily portfolio optimization: %d positions, vol=%.2f%%, dd=%.2f%%",
            len([a for a in result.assets if a.quantity > 0]),
            result.risk.portfolio_annual_vol * 100,
            result.risk.max_drawdown * 100,
        )
        return result
    finally:
        session.close()
