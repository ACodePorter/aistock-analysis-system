"""
特征工程管道（Feature Engineering Pipeline）

负责：
1. 从数据层加载行情 + 新闻 + 资金流 + 宏观数据
2. 合并对齐（按 trade_date 做 left join）
3. 调用因子引擎批量计算因子
4. 标准化处理
5. 生成标签（未来收益率/方向）
6. 输出训练就绪的特征矩阵

设计原则：
- 所有计算在 pandas 内完成，避免逐行循环
- 预留 sliding window 支持
- 因子标准化可选 z-score / min-max / rank
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from ..data_layer.market_data import load_price_daily, load_fund_flow
from ..data_layer.news_data import load_news_sentiment
from ..data_layer.macro_data import load_index_daily
from ..factor_engine.registry import FactorRegistry

# 确保因子模块中的 @register_factor 装饰器被执行
from ..factor_engine import technical as _tech_factors      # noqa: F401
from ..factor_engine import news_factors as _news_factors    # noqa: F401
from ..factor_engine import macro_factors as _macro_factors  # noqa: F401
from ..factor_engine import behavioral as _beh_factors       # noqa: F401

logger = logging.getLogger(__name__)

# 默认特征列表（用于模型训练的因子名）
DEFAULT_FEATURE_COLUMNS: list[str] = [
    # 技术类 —— 尺度无关因子
    "ma_5_diff", "ma_10_diff", "ma_20_diff", "ma_60_diff",
    "ema_12_diff", "ema_26_diff",
    "rsi_6", "rsi_14",
    "macd_norm",
    "bb_width", "bb_pctb",
    "atr_pct",
    "vol_ratio_5", "vol_ratio_20",
    "ret_1d", "ret_5d", "ret_20d", "ret_60d",
    "volatility_20d", "downside_vol_20d",
    "max_drawdown_60d",
    "candle_body", "upper_shadow", "lower_shadow", "amplitude",
    "price_position_20d",
    "vol_stability_20d",
    # 新闻类
    "news_sentiment_1d", "news_sentiment_3d", "news_sentiment_7d",
    "news_volume_1d", "news_volume_5d", "news_volume_spike",
    "news_pos_ratio", "news_neg_ratio",
    "news_sentiment_momentum", "has_major_event",
    # 宏观类
    "macro_index_ret_1d", "macro_index_ret_5d",
    "macro_index_ma20_diff", "macro_breadth_ratio",
    "macro_volatility_20d", "macro_trend_strength",
    # 行为类
    "turnover_rate", "turnover_change_5d",
    "fund_main_net_norm", "fund_main_net_5d",
    "fund_super_net_norm", "fund_flow_momentum",
    "vol_price_corr_10d", "price_vol_divergence",
]


class FeaturePipeline:
    """特征工程管道

    用法：
        pipeline = FeaturePipeline(session)
        X, y, feature_names = pipeline.build(symbol="600519.SH", horizon="5d")
    """

    def __init__(self, session: Session):
        self.session = session
        self.factor_registry = FactorRegistry()

    def build(
        self,
        symbol: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        horizon: str = "5d",
        normalize: str = "zscore",
        feature_columns: Optional[list[str]] = None,
        task_type: str = "classification",
    ) -> tuple[pd.DataFrame, pd.Series, list[str]]:
        """构建单股票特征矩阵

        Args:
            symbol:          股票代码
            start_date:      数据起始日期（默认近3年）
            end_date:        数据截止日期
            horizon:         标签周期（1d / 5d / 10d / 20d）
            normalize:       标准化方式：zscore / minmax / rank / none
            feature_columns: 使用的特征列（默认使用 DEFAULT_FEATURE_COLUMNS）
            task_type:       classification（方向分类） / regression（收益率回归）

        Returns:
            X:             特征矩阵 (n_samples, n_features)
            y:             标签 Series
            feature_names: 特征列名列表
        """
        if start_date is None:
            start_date = (date.today() - timedelta(days=365 * 3))

        feature_cols = feature_columns or DEFAULT_FEATURE_COLUMNS

        # 1) 加载原始数据
        df = self._load_and_merge(symbol, start_date, end_date)
        if df.empty or len(df) < 30:
            logger.warning("数据不足: symbol=%s, rows=%d", symbol, len(df))
            return pd.DataFrame(), pd.Series(dtype=float), []

        # 2) 计算因子
        df = self.factor_registry.compute_all(df, factor_names=feature_cols)

        # 3) 生成标签
        df = self._generate_labels(df, horizon)

        # 4) 清理 — 根据 task_type 选择标签列
        if task_type == "regression":
            label_col = f"fwd_ret_{horizon}"
        else:
            label_col = f"label_{horizon}"

        available_features = [c for c in feature_cols if c in df.columns]
        df_clean = df[available_features + [label_col, "trade_date"]].dropna(subset=[label_col])

        if df_clean.empty:
            logger.warning("清理后无有效样本: symbol=%s", symbol)
            return pd.DataFrame(), pd.Series(dtype=float), []

        # 5) 标准化
        X = df_clean[available_features].copy()
        X = X.fillna(0)
        X = self._normalize(X, method=normalize)

        y = df_clean[label_col]

        logger.info(
            "特征构建完成: symbol=%s, samples=%d, features=%d, horizon=%s",
            symbol, len(X), len(available_features), horizon
        )
        return X, y, available_features

    def build_latest(
        self,
        symbol: str,
        feature_columns: Optional[list[str]] = None,
        normalize: str = "zscore",
        lookback_days: int = 120,
    ) -> tuple[pd.DataFrame, list[str]]:
        """构建最新一天的特征向量（用于推理预测）

        Returns:
            X:             最后一行特征（DataFrame，1行）
            feature_names: 特征列名
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=lookback_days)
        feature_cols = feature_columns or DEFAULT_FEATURE_COLUMNS

        df = self._load_and_merge(symbol, start_date, end_date)
        if df.empty:
            return pd.DataFrame(), []

        df = self.factor_registry.compute_all(df, factor_names=feature_cols)
        available_features = [c for c in feature_cols if c in df.columns]

        X = df[available_features].iloc[[-1]].copy()
        X = X.fillna(0)
        X = self._normalize(X, method=normalize)
        return X, available_features

    def _load_and_merge(
        self,
        symbol: str,
        start_date: Optional[date],
        end_date: Optional[date],
    ) -> pd.DataFrame:
        """加载并合并多数据源"""
        # 行情数据（主表）
        df = load_price_daily(self.session, symbol, start_date, end_date)
        if df.empty:
            return df

        # 资金流
        fund_df = load_fund_flow(self.session, symbol, start_date, end_date)
        if not fund_df.empty:
            df = df.merge(fund_df, on="trade_date", how="left")

        # 新闻情绪
        news_df = load_news_sentiment(self.session, symbol, start_date, end_date)
        if not news_df.empty:
            df = df.merge(news_df, on="trade_date", how="left")

        # 宏观指数（上证指数）
        start_str = start_date.strftime("%Y%m%d") if start_date else None
        end_str = end_date.strftime("%Y%m%d") if end_date else None
        index_df = load_index_daily("上证指数", start_str, end_str)
        if not index_df.empty and "close" in index_df.columns:
            index_df = index_df[["trade_date", "close"]].rename(
                columns={"close": "macro_index_close"}
            )
            df = df.merge(index_df, on="trade_date", how="left")

        # 填充缺失值（数值列）
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        df[numeric_cols] = df[numeric_cols].fillna(method="ffill").fillna(0)

        return df.sort_values("trade_date").reset_index(drop=True)

    def _generate_labels(self, df: pd.DataFrame, horizon: str) -> pd.DataFrame:
        """生成未来收益率和方向标签

        Args:
            horizon: "1d" / "5d" / "10d" / "20d"
        """
        periods_map = {"1d": 1, "5d": 5, "10d": 10, "20d": 20}
        periods = periods_map.get(horizon, 5)

        # 未来收益率
        df[f"fwd_ret_{horizon}"] = df["close"].shift(-periods) / df["close"] - 1
        # 方向标签：1=上涨, 0=下跌
        df[f"fwd_dir_{horizon}"] = (df[f"fwd_ret_{horizon}"] > 0).astype(int)
        # 统一标签列名
        df[f"label_{horizon}"] = df[f"fwd_dir_{horizon}"]

        return df

    @staticmethod
    def _normalize(df: pd.DataFrame, method: str = "zscore") -> pd.DataFrame:
        """特征标准化"""
        if method == "zscore":
            mean = df.mean()
            std = df.std().replace(0, 1)
            return (df - mean) / std
        elif method == "minmax":
            min_val = df.min()
            max_val = df.max()
            rng = (max_val - min_val).replace(0, 1)
            return (df - min_val) / rng
        elif method == "rank":
            return df.rank(pct=True)
        else:
            return df
