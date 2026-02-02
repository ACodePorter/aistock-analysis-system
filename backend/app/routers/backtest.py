"""
回测系统 API 路由

提供回测相关的 REST API
"""

import logging
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.backtest import BacktestEngine, BacktestConfig, BacktestResult
from app.backtest.strategies import MACrossStrategy, RSIStrategy, SignalStrategy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/backtest", tags=["回测系统"])


# ============ 请求/响应模型 ============

class BacktestRequest(BaseModel):
    """回测请求"""
    symbols: List[str] = Field(..., description="股票代码列表")
    start_date: date = Field(..., description="开始日期")
    end_date: date = Field(..., description="结束日期")
    strategy: str = Field("ma_cross", description="策略类型: ma_cross/rsi/signal")
    
    # 策略参数
    fast_period: int = Field(5, description="快线周期")
    slow_period: int = Field(20, description="慢线周期")
    rsi_period: int = Field(14, description="RSI周期")
    rsi_oversold: float = Field(30, description="RSI超卖阈值")
    rsi_overbought: float = Field(70, description="RSI超买阈值")
    
    # 回测配置
    initial_capital: float = Field(100000, description="初始资金")
    commission_rate: float = Field(0.0003, description="手续费率")
    slippage: float = Field(0.001, description="滑点")
    max_single_position: float = Field(0.2, description="单只最大仓位")
    stop_loss_pct: Optional[float] = Field(None, description="止损比例")
    take_profit_pct: Optional[float] = Field(None, description="止盈比例")
    trailing_stop_pct: Optional[float] = Field(None, description="追踪止损比例")


class BacktestResponse(BaseModel):
    """回测响应"""
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None


# ============ API 端点 ============

@router.post("/run", response_model=BacktestResponse)
async def run_backtest(request: BacktestRequest):
    """运行回测
    
    支持的策略：
    - ma_cross: 均线交叉策略
    - rsi: RSI超买超卖策略
    - signal: 基于分析系统信号的策略
    """
    try:
        # 创建配置
        config = BacktestConfig(
            initial_capital=request.initial_capital,
            commission_rate=request.commission_rate,
            slippage=request.slippage,
            max_single_position=request.max_single_position,
            stop_loss_pct=request.stop_loss_pct,
            take_profit_pct=request.take_profit_pct,
            trailing_stop_pct=request.trailing_stop_pct,
        )
        
        # 创建策略
        if request.strategy == "ma_cross":
            strategy = MACrossStrategy(
                fast_period=request.fast_period,
                slow_period=request.slow_period,
            )
        elif request.strategy == "rsi":
            strategy = RSIStrategy(
                period=request.rsi_period,
                oversold=request.rsi_oversold,
                overbought=request.rsi_overbought,
            )
        elif request.strategy == "signal":
            # 从数据库加载信号数据
            # TODO: 实现信号数据加载
            signals = {}
            strategy = SignalStrategy(signals=signals)
        else:
            raise HTTPException(status_code=400, detail=f"未知策略类型: {request.strategy}")
        
        # 创建引擎并运行
        engine = BacktestEngine(config)
        result = engine.run(
            strategy=strategy,
            symbols=request.symbols,
            start_date=request.start_date,
            end_date=request.end_date,
        )
        
        return BacktestResponse(
            success=True,
            data=result.to_dict(),
        )
        
    except Exception as e:
        logger.error(f"回测失败: {e}", exc_info=True)
        return BacktestResponse(
            success=False,
            error=str(e),
        )


@router.get("/strategies")
async def get_available_strategies():
    """获取可用策略列表"""
    return {
        "strategies": [
            {
                "id": "ma_cross",
                "name": "均线交叉策略",
                "description": "金叉买入，死叉卖出",
                "params": [
                    {"name": "fast_period", "type": "int", "default": 5, "description": "快线周期"},
                    {"name": "slow_period", "type": "int", "default": 20, "description": "慢线周期"},
                ]
            },
            {
                "id": "rsi",
                "name": "RSI超买超卖策略",
                "description": "RSI低于超卖线买入，高于超买线卖出",
                "params": [
                    {"name": "rsi_period", "type": "int", "default": 14, "description": "RSI周期"},
                    {"name": "rsi_oversold", "type": "float", "default": 30, "description": "超卖阈值"},
                    {"name": "rsi_overbought", "type": "float", "default": 70, "description": "超买阈值"},
                ]
            },
            {
                "id": "signal",
                "name": "分析信号策略",
                "description": "基于系统分析评分和推荐进行交易",
                "params": [
                    {"name": "buy_threshold", "type": "float", "default": 70, "description": "买入阈值"},
                    {"name": "sell_threshold", "type": "float", "default": 40, "description": "卖出阈值"},
                ]
            },
        ]
    }


@router.get("/history")
async def get_backtest_history(
    limit: int = Query(20, ge=1, le=100),
    strategy: Optional[str] = None,
):
    """获取回测历史记录"""
    from sqlalchemy import select, desc
    from app.core.db import get_session
    from app.core.models import BacktestResult as BacktestResultModel
    
    async with get_session() as session:
        query = select(BacktestResultModel).order_by(desc(BacktestResultModel.created_at))
        
        if strategy:
            query = query.where(BacktestResultModel.strategy_name == strategy)
        
        query = query.limit(limit)
        result = await session.execute(query)
        records = result.scalars().all()
        
        return {
            "total": len(records),
            "records": [
                {
                    "id": r.id,
                    "strategy_name": r.strategy_name,
                    "start_date": r.start_date.isoformat(),
                    "end_date": r.end_date.isoformat(),
                    "total_return": r.total_return,
                    "annual_return": r.annual_return,
                    "max_drawdown": r.max_drawdown,
                    "sharpe_ratio": r.sharpe_ratio,
                    "win_rate": r.win_rate,
                    "total_trades": r.total_trades,
                    "created_at": r.created_at.isoformat(),
                }
                for r in records
            ]
        }


@router.get("/result/{backtest_id}")
async def get_backtest_result(backtest_id: int):
    """获取回测详细结果"""
    from sqlalchemy import select
    from app.core.db import get_session
    from app.core.models import BacktestResult as BacktestResultModel
    import json
    
    async with get_session() as session:
        result = await session.execute(
            select(BacktestResultModel).where(BacktestResultModel.id == backtest_id)
        )
        record = result.scalar_one_or_none()
        
        if not record:
            raise HTTPException(status_code=404, detail="回测记录不存在")
        
        return {
            "id": record.id,
            "strategy_name": record.strategy_name,
            "strategy_params": json.loads(record.strategy_params) if record.strategy_params else None,
            "start_date": record.start_date.isoformat(),
            "end_date": record.end_date.isoformat(),
            "initial_capital": record.initial_capital,
            "final_value": record.final_value,
            "total_return": record.total_return,
            "annual_return": record.annual_return,
            "max_drawdown": record.max_drawdown,
            "sharpe_ratio": record.sharpe_ratio,
            "sortino_ratio": record.sortino_ratio,
            "calmar_ratio": record.calmar_ratio,
            "volatility": record.volatility,
            "total_trades": record.total_trades,
            "winning_trades": record.winning_trades,
            "losing_trades": record.losing_trades,
            "win_rate": record.win_rate,
            "avg_profit": record.avg_profit,
            "avg_loss": record.avg_loss,
            "profit_factor": record.profit_factor,
            "benchmark_return": record.benchmark_return,
            "alpha": record.alpha,
            "beta": record.beta,
            "equity_curve": json.loads(record.equity_curve) if record.equity_curve else [],
            "trades_detail": json.loads(record.trades_detail) if record.trades_detail else [],
            "monthly_returns": json.loads(record.monthly_returns) if record.monthly_returns else [],
        }
