"""
TradeSignal 数据结构定义 — Task T1

业务层数据对象（dataclass + Pydantic），不涉及 ORM 映射。
供事件桥梁、风控引擎、仓位管理、策略层使用。
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# =========================
# 枚举
# =========================

class SignalDirection(str, Enum):
    """交易方向（A股 T+1 制度下无做空）"""
    LONG = "long"   # 做多
    FLAT = "flat"   # 空仓 / 强制清仓


class SignalSource(str, Enum):
    """信号来源（影响优先级与权重计算）"""
    EVENT_L1         = "event_l1"          # L1 法定披露（公告/回购/处罚）
    EVENT_L2         = "event_l2"          # L2 专业财经媒体事件
    EVENT_L3         = "event_l3"          # L3 官方政策 / 行业机构
    FACTOR_TECHNICAL = "factor_technical"  # 纯技术因子触发
    FACTOR_BREAKOUT  = "factor_breakout"   # 放量突破特征触发
    HYBRID           = "hybrid"            # 事件 + 因子联合触发（最高优先级）


# =========================
# 业务层数据对象
# =========================

@dataclass
class TradeSignal:
    """标准交易信号（业务层，非 ORM）

    字段约束（由下游 T6 风控引擎校验，不在此处强制）：
    - 多单方向：stop_loss < trigger_price < take_profit
    - holding_period 范围 1–5（A股短线定义）
    - confidence 范围 0.0–1.0

    来源关系：
    - EVENT_* 信号由 quant_engine/events/bridge.py（T10）生成
    - FACTOR_* 信号由 quant_engine/signal_engine/generator.py 升级后生成
    - HYBRID 信号由 quant_engine/strategy_engine/（T15）合并生成
    """

    # 核心标识
    symbol: str
    signal_date: datetime.date

    # 价格三要素（绝对价，非百分比）
    trigger_price: float
    stop_loss: float
    take_profit: float

    # 信号来源（必填）
    source: SignalSource

    # 可选字段（有默认值）
    direction: SignalDirection = SignalDirection.LONG
    strength: float = 50.0          # 0–100，复用 QESignal.score 量纲
    holding_period: int = 3         # 预计持仓天数，1–5
    confidence: float = 0.5         # 0–1
    regime: str = "unknown"         # 生成时市场状态（复用 MarketRegime.value）

    # 关联 ID（可选，落库 / 事件溯源用）
    event_id: Optional[str] = None       # 触发事件的 MongoDB _id
    qe_signal_id: Optional[int] = None  # 关联 qe_signals.id（信号落库后回填）

    # 因子明细透传（sequences safe）
    metadata: dict = field(default_factory=dict)


@dataclass
class TradeDecision:
    """交易决策（仓位管理层输出，对 TradeSignal 的包装）

    由 T8 position_manager/sizer.py 生成。
    由 T6 risk_engine/guard.py 赋值 approved / rejection_reason。
    """

    signal: TradeSignal

    # 仓位计算结果
    position_size: int = 0          # 建议买入股数（100 的整数倍）
    estimated_cost: float = 0.0     # 预估资金占用（含手续费估算，元）
    max_loss_yuan: float = 0.0      # 本笔最大亏损金额（元）
    risk_reward_ratio: float = 0.0  # 盈亏比 = (take_profit - trigger) / (trigger - stop_loss)
    position_ratio: float = 0.0     # 占账户总资产比例（0–1）

    # 风控结果
    approved: bool = False
    rejection_reason: Optional[str] = None

    # 时间戳
    decided_at: datetime.datetime = field(default_factory=datetime.datetime.utcnow)


# =========================
# Pydantic API 响应模型
# =========================

class TradeSignalResponse(BaseModel):
    """TradeSignal 的 API 响应序列化模型

    signal_date 使用 str（与现有 SignalResponse.signal_date: str 保持一致）。
    """

    symbol: str = Field(..., description="股票代码")
    signal_date: str = Field(..., description="信号日期 YYYY-MM-DD")
    direction: str = Field(..., description="long 或 flat")
    strength: float = Field(..., description="综合强度 0-100")
    trigger_price: float = Field(..., description="建议入场价（元）")
    stop_loss: float = Field(..., description="止损价（元）")
    take_profit: float = Field(..., description="止盈价（元）")
    holding_period: int = Field(..., description="预计持仓天数 1-5")
    source: str = Field(..., description="信号来源")
    confidence: float = Field(..., description="置信度 0-1")
    regime: str = Field(..., description="生成时市场状态")
    event_id: Optional[str] = Field(None, description="触发事件 MongoDB ID")
    metadata: dict = Field(default_factory=dict, description="因子明细 JSON")


class TradeDecisionResponse(BaseModel):
    """TradeDecision 的 API 响应序列化模型"""

    signal: TradeSignalResponse = Field(..., description="原始交易信号")
    position_size: int = Field(..., description="建议买入股数（100 的倍数）")
    estimated_cost: float = Field(..., description="预估资金占用（元）")
    max_loss_yuan: float = Field(..., description="最大亏损金额（元）")
    risk_reward_ratio: float = Field(..., description="盈亏比")
    position_ratio: float = Field(..., description="占账户资产比例 0-1")
    approved: bool = Field(..., description="是否通过风控")
    rejection_reason: Optional[str] = Field(None, description="拒绝原因")
