"""构建每日特征 (最小实现)。

背景：
    backend/app/main.py 在 Agent 日报成功后会尝试 `subprocess.Popen` 触发本脚本；
    在仓库之前的迭代中该脚本缺失，导致 `stock_daily_features` 表长期无新行入库。

职责（刻意保持最小）：
    - 取所有 `stock_pool_members.exit_date IS NULL` 的 symbol
    - 读取该 symbol 近 120 个交易日的 prices_daily（确保窗口覆盖 60 日均线等指标）
    - 复用 `prediction.framework.data_loader.build_features` 算出因子
    - 仅把最新一行写入 `stock_daily_features`，ON CONFLICT (symbol, trade_date) 跳过
    - 数值字段限制在 StockDailyFeature 已有的列；不回填未来收益标签（由后续训练阶段完成）

该脚本面向 `python backend/scripts/build_daily_features.py` 直接调用，因此需要自行把
`backend/` 加入 sys.path 后才能 `from app.xxx import ...`。
"""
from __future__ import annotations

import logging
import math
import os
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import pandas as pd  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.db import SessionLocal, engine  # type: ignore  # noqa: E402
from app.prediction.framework.data_loader import build_features  # type: ignore  # noqa: E402

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s build_daily_features %(message)s",
)
logger = logging.getLogger("build_daily_features")


_INSERT_SQL = text(
    """
    INSERT INTO stock_daily_features (
        symbol, trade_date,
        open, high, low, close, pct_chg, vol, amount,
        ret_1d_prev, ret_5d_prev, vol_5d_prev,
        realized_vol_5d, realized_vol_20d
    ) VALUES (
        :symbol, :trade_date,
        :open, :high, :low, :close, :pct_chg, :vol, :amount,
        :ret_1d_prev, :ret_5d_prev, :vol_5d_prev,
        :realized_vol_5d, :realized_vol_20d
    )
    ON CONFLICT (symbol, trade_date) DO NOTHING
    """
)


def _float_or_none(v) -> float | None:
    try:
        if v is None:
            return None
        if isinstance(v, float) and math.isnan(v):
            return None
        return float(v)
    except Exception:
        return None


def _fetch_pool_symbols() -> list[str]:
    with SessionLocal() as session:
        rows = session.execute(
            text(
                "SELECT DISTINCT symbol FROM stock_pool_members "
                "WHERE exit_date IS NULL ORDER BY symbol"
            )
        ).fetchall()
    return [r[0] for r in rows]


def _process_symbol(symbol: str) -> str:
    df = pd.read_sql_query(
        "SELECT trade_date, open, high, low, close, pct_chg, vol, amount "
        "FROM prices_daily WHERE symbol = %s ORDER BY trade_date DESC LIMIT 120",
        con=engine,
        params=(symbol,),
    )
    if df.empty or len(df) < 25:
        return "skipped:insufficient_prices"

    df = df.sort_values("trade_date")
    feat_df, _cols = build_features(df)
    if feat_df.empty:
        return "skipped:no_features"

    last = feat_df.iloc[-1]
    params = {
        "symbol": symbol,
        "trade_date": last["trade_date"],
        "open": _float_or_none(last.get("open")),
        "high": _float_or_none(last.get("high")),
        "low": _float_or_none(last.get("low")),
        "close": _float_or_none(last.get("close")),
        "pct_chg": _float_or_none(last.get("pct_chg")),
        "vol": _float_or_none(last.get("vol")),
        "amount": _float_or_none(last.get("amount")),
        "ret_1d_prev": _float_or_none(last.get("ret_1d")),
        "ret_5d_prev": _float_or_none(last.get("ret_5d")),
        "vol_5d_prev": _float_or_none(last.get("volatility_5d")),
        "realized_vol_5d": _float_or_none(last.get("volatility_5d")),
        "realized_vol_20d": _float_or_none(last.get("volatility_20d")),
    }

    with SessionLocal() as session:
        try:
            session.execute(_INSERT_SQL, params)
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.warning("persist failed for %s: %s", symbol, exc)
            return "failed"
    return "ok"


def main() -> int:
    symbols = _fetch_pool_symbols()
    if not symbols:
        logger.info("no active pool members, exit")
        return 0
    counts = {"ok": 0, "failed": 0}
    for s in symbols:
        try:
            state = _process_symbol(s)
        except Exception as exc:
            logger.warning("unexpected error for %s: %s", s, exc, exc_info=True)
            state = "failed"
        if state == "ok":
            counts["ok"] += 1
        elif state.startswith("skipped"):
            counts.setdefault(state, 0)
            counts[state] += 1
        else:
            counts["failed"] += 1
    logger.info("build_daily_features finished: %s (total=%d)", counts, len(symbols))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
