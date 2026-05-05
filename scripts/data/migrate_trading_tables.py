"""
数据库迁移脚本 - 添加交易系统相关表

包含：
- financial_metrics: 财务指标
- northbound_flow: 北向资金流向
- northbound_holding: 北向资金持仓
- dragon_tiger: 龙虎榜
- analyst_ratings: 机构评级
- backtest_results: 回测结果
- trading_signals: 交易信号
- position_management: 仓位管理
- portfolios: 投资组合
"""

from sqlalchemy import text
from app.core.db import engine

# 新表创建 SQL
CREATE_TABLES_SQL = """
-- 财务指标表
CREATE TABLE IF NOT EXISTS financial_metrics (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL,
    trade_date DATE NOT NULL,
    pe_ttm FLOAT,
    pe_static FLOAT,
    pb FLOAT,
    ps_ttm FLOAT,
    pcf_ttm FLOAT,
    market_cap FLOAT,
    circulating_cap FLOAT,
    roe FLOAT,
    roa FLOAT,
    gross_margin FLOAT,
    net_margin FLOAT,
    eps FLOAT,
    eps_yoy FLOAT,
    revenue FLOAT,
    revenue_yoy FLOAT,
    net_profit FLOAT,
    net_profit_yoy FLOAT,
    debt_ratio FLOAT,
    current_ratio FLOAT,
    quick_ratio FLOAT,
    dividend_yield FLOAT,
    report_period VARCHAR(20),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_financial_metrics_symbol_date ON financial_metrics(symbol, trade_date);
CREATE INDEX IF NOT EXISTS idx_financial_metrics_date ON financial_metrics(trade_date);
CREATE INDEX IF NOT EXISTS idx_financial_metrics_pe ON financial_metrics(pe_ttm);
CREATE INDEX IF NOT EXISTS idx_financial_metrics_roe ON financial_metrics(roe);

-- 北向资金流向表
CREATE TABLE IF NOT EXISTS northbound_flow (
    id BIGSERIAL PRIMARY KEY,
    trade_date DATE UNIQUE NOT NULL,
    sh_net FLOAT,
    sh_buy FLOAT,
    sh_sell FLOAT,
    sz_net FLOAT,
    sz_buy FLOAT,
    sz_sell FLOAT,
    total_net FLOAT,
    sh_cumulative FLOAT,
    sz_cumulative FLOAT,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_northbound_flow_date ON northbound_flow(trade_date);

-- 北向资金持仓表
CREATE TABLE IF NOT EXISTS northbound_holding (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL,
    trade_date DATE NOT NULL,
    holding_shares FLOAT,
    holding_value FLOAT,
    holding_ratio FLOAT,
    free_float_ratio FLOAT,
    change_shares FLOAT,
    change_value FLOAT,
    change_ratio FLOAT,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_northbound_holding_symbol_date ON northbound_holding(symbol, trade_date);
CREATE INDEX IF NOT EXISTS idx_northbound_holding_date ON northbound_holding(trade_date);
CREATE INDEX IF NOT EXISTS idx_northbound_holding_ratio ON northbound_holding(holding_ratio);

-- 龙虎榜数据表
CREATE TABLE IF NOT EXISTS dragon_tiger (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL,
    name VARCHAR(64),
    trade_date DATE NOT NULL,
    reason VARCHAR(200),
    close_price FLOAT,
    pct_change FLOAT,
    turnover_rate FLOAT,
    net_buy FLOAT,
    buy_amount FLOAT,
    sell_amount FLOAT,
    buy_seats TEXT,
    sell_seats TEXT,
    institution_buy FLOAT,
    institution_sell FLOAT,
    institution_net FLOAT,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dragon_tiger_symbol_date ON dragon_tiger(symbol, trade_date);
CREATE INDEX IF NOT EXISTS idx_dragon_tiger_date ON dragon_tiger(trade_date);
CREATE INDEX IF NOT EXISTS idx_dragon_tiger_net_buy ON dragon_tiger(net_buy);

-- 机构评级表
CREATE TABLE IF NOT EXISTS analyst_ratings (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL,
    rating_date DATE NOT NULL,
    institution VARCHAR(100) NOT NULL,
    analyst VARCHAR(64),
    rating VARCHAR(20),
    rating_change VARCHAR(20),
    target_price FLOAT,
    target_price_low FLOAT,
    target_price_high FLOAT,
    eps_forecast_1y FLOAT,
    eps_forecast_2y FLOAT,
    pe_forecast FLOAT,
    report_title VARCHAR(500),
    report_url VARCHAR(500),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analyst_rating_symbol_date ON analyst_ratings(symbol, rating_date);
CREATE INDEX IF NOT EXISTS idx_analyst_rating_date ON analyst_ratings(rating_date);
CREATE INDEX IF NOT EXISTS idx_analyst_rating_institution ON analyst_ratings(institution);

-- 回测结果表
CREATE TABLE IF NOT EXISTS backtest_results (
    id BIGSERIAL PRIMARY KEY,
    strategy_name VARCHAR(100) NOT NULL,
    strategy_params TEXT,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    symbols TEXT,
    symbol_count INTEGER DEFAULT 1,
    initial_capital FLOAT DEFAULT 100000,
    final_value FLOAT,
    total_return FLOAT,
    annual_return FLOAT,
    max_drawdown FLOAT,
    sharpe_ratio FLOAT,
    sortino_ratio FLOAT,
    calmar_ratio FLOAT,
    volatility FLOAT,
    total_trades INTEGER,
    winning_trades INTEGER,
    losing_trades INTEGER,
    win_rate FLOAT,
    avg_profit FLOAT,
    avg_loss FLOAT,
    profit_factor FLOAT,
    benchmark VARCHAR(20),
    benchmark_return FLOAT,
    alpha FLOAT,
    beta FLOAT,
    equity_curve TEXT,
    trades_detail TEXT,
    monthly_returns TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    run_time_seconds FLOAT
);

CREATE INDEX IF NOT EXISTS idx_backtest_strategy ON backtest_results(strategy_name);
CREATE INDEX IF NOT EXISTS idx_backtest_dates ON backtest_results(start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_backtest_return ON backtest_results(annual_return);

-- 交易信号表
CREATE TABLE IF NOT EXISTS trading_signals (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL,
    signal_date DATE NOT NULL,
    signal_time TIMESTAMP,
    signal_type VARCHAR(20) NOT NULL,
    signal_strength FLOAT,
    confidence FLOAT,
    source VARCHAR(50) NOT NULL,
    strategy VARCHAR(100),
    trigger_price FLOAT,
    target_price FLOAT,
    stop_loss_price FLOAT,
    factors TEXT,
    analysis TEXT,
    is_validated BOOLEAN DEFAULT FALSE,
    validation_result VARCHAR(20),
    actual_return FLOAT,
    validation_date DATE,
    validation_notes TEXT,
    confirm_1d BOOLEAN,
    confirm_1w BOOLEAN,
    confirm_1m BOOLEAN,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trading_signal_symbol_date ON trading_signals(symbol, signal_date);
CREATE INDEX IF NOT EXISTS idx_trading_signal_date ON trading_signals(signal_date);
CREATE INDEX IF NOT EXISTS idx_trading_signal_type ON trading_signals(signal_type);
CREATE INDEX IF NOT EXISTS idx_trading_signal_validated ON trading_signals(is_validated);

-- 仓位管理表
CREATE TABLE IF NOT EXISTS position_management (
    id BIGSERIAL PRIMARY KEY,
    portfolio_id VARCHAR(50) NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    quantity INTEGER DEFAULT 0,
    avg_cost FLOAT,
    current_price FLOAT,
    market_value FLOAT,
    unrealized_pnl FLOAT,
    unrealized_pnl_pct FLOAT,
    realized_pnl FLOAT,
    weight FLOAT,
    target_weight FLOAT,
    stop_loss_price FLOAT,
    take_profit_price FLOAT,
    trailing_stop_pct FLOAT,
    max_loss_pct FLOAT,
    entry_date DATE,
    holding_days INTEGER,
    last_trade_date DATE,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_position_portfolio_symbol ON position_management(portfolio_id, symbol);
CREATE INDEX IF NOT EXISTS idx_position_portfolio ON position_management(portfolio_id);

-- 投资组合表
CREATE TABLE IF NOT EXISTS portfolios (
    id BIGSERIAL PRIMARY KEY,
    portfolio_id VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    initial_capital FLOAT DEFAULT 100000,
    cash FLOAT,
    total_value FLOAT,
    total_return FLOAT,
    daily_return FLOAT,
    max_drawdown FLOAT,
    sharpe_ratio FLOAT,
    position_count INTEGER,
    cash_ratio FLOAT,
    max_single_position FLOAT,
    max_total_position FLOAT,
    max_sector_position FLOAT,
    strategy VARCHAR(100),
    rebalance_frequency VARCHAR(20),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_portfolio_active ON portfolios(is_active);
"""


def run_migration():
    """运行数据库迁移"""
    with engine.connect() as conn:
        # 分割SQL语句并逐个执行
        statements = CREATE_TABLES_SQL.split(';')
        
        for stmt in statements:
            stmt = stmt.strip()
            if stmt:
                try:
                    conn.execute(text(stmt))
                    print(f"✓ 执行成功: {stmt[:60]}...")
                except Exception as e:
                    print(f"✗ 执行失败: {stmt[:60]}... - {e}")
        
        conn.commit()
    
    print("\n数据库迁移完成!")


if __name__ == "__main__":
    run_migration()
