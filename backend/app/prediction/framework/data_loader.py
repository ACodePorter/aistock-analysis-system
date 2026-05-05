"""
时间序列数据加载与特征工程

职责：
1. 从原始 OHLCV DataFrame 构建技术因子特征（scale-free）
2. 通过 FactorEngine 扩展多源因子（市场/情绪/宏观/衍生）
3. 通过 FeatureSelector 自动筛选 Top-N 最重要因子
4. 可选合并新闻情绪数据
5. 生成前瞻标签（forward return / direction）
6. 提供严格的时间序列 CV 分割（禁止未来数据泄露）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Generator, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据容器
# ---------------------------------------------------------------------------

@dataclass
class TimeSeriesDataset:
    """标准化训练数据集"""
    X: np.ndarray                     # (n_samples, n_features)
    y: np.ndarray                     # (n_samples,)
    feature_names: List[str]
    dates: np.ndarray                 # 对应的交易日期
    last_close: float                 # 最后一个收盘价（用于 return→price 换算）
    task_type: str                    # classification / regression
    horizon: str                      # 1d / 5d / 10d / 20d
    metadata: Dict = field(default_factory=dict)


@dataclass
class SplitIndex:
    """单个 CV fold 的索引"""
    fold: int
    train_idx: np.ndarray
    val_idx: np.ndarray


# ---------------------------------------------------------------------------
# 特征工程
# ---------------------------------------------------------------------------

def build_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    """从 OHLCV 构建全部技术因子特征

    所有特征均为比率 / 差值形式（scale-free），避免目标泄露。
    """
    df = df.sort_values("trade_date").copy()
    close = df["close"].astype(float)
    high = df["high"].astype(float) if "high" in df.columns else close
    low = df["low"].astype(float) if "low" in df.columns else close
    vol = df["vol"].astype(float) if "vol" in df.columns else pd.Series(1.0, index=df.index)
    opn = df["open"].astype(float) if "open" in df.columns else close

    # ---------- 收益率 ----------
    for p in (1, 2, 3, 5, 10, 20):
        df[f"ret_{p}d"] = close.pct_change(p)

    # ---------- 均线偏离率 ----------
    for w in (5, 10, 20, 60):
        ma = close.rolling(w, min_periods=w).mean()
        df[f"ma{w}_bias"] = (close - ma) / (ma + 1e-9)

    # ---------- EMA 偏离 ----------
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["ema12_bias"] = (close - ema12) / (ema12 + 1e-9)
    df["ema26_bias"] = (close - ema26) / (ema26 + 1e-9)

    # ---------- MACD ----------
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    df["macd_norm"] = macd_line / (close + 1e-9)
    df["macd_signal_norm"] = signal_line / (close + 1e-9)
    df["macd_hist_norm"] = (macd_line - signal_line) / (close + 1e-9)

    # ---------- RSI ----------
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss_s = (-delta).where(delta < 0, 0.0)
    for period in (6, 14):
        avg_gain = gain.rolling(period, min_periods=period).mean()
        avg_loss = loss_s.rolling(period, min_periods=period).mean()
        rs = avg_gain / (avg_loss + 1e-9)
        df[f"rsi_{period}"] = 100.0 - 100.0 / (1.0 + rs)

    # ---------- 布林带 ----------
    bb_ma = close.rolling(20, min_periods=20).mean()
    bb_std = close.rolling(20, min_periods=20).std()
    df["bb_width"] = 2 * bb_std / (bb_ma + 1e-9)
    df["bb_position"] = (close - (bb_ma - 2 * bb_std)) / (4 * bb_std + 1e-9)

    # ---------- ATR ----------
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr_pct"] = tr.rolling(14, min_periods=14).mean() / (close + 1e-9)

    # ---------- 波动率 ----------
    for w in (5, 10, 20):
        df[f"volatility_{w}d"] = df["ret_1d"].rolling(w, min_periods=w).std()

    # ---------- 成交量因子 ----------
    vol_ma5 = vol.rolling(5, min_periods=5).mean()
    vol_ma20 = vol.rolling(20, min_periods=20).mean()
    df["vol_ratio_5"] = vol / (vol_ma5 + 1e-9)
    df["vol_ratio_20"] = vol / (vol_ma20 + 1e-9)
    df["vol_trend"] = (vol_ma5 - vol_ma20) / (vol_ma20 + 1e-9)

    # ---------- K 线形态 ----------
    df["candle_body"] = (close - opn) / (close + 1e-9)
    df["amplitude"] = (high - low) / (close + 1e-9)
    df["upper_shadow"] = (high - pd.concat([close, opn], axis=1).max(axis=1)) / (close + 1e-9)
    df["lower_shadow"] = (pd.concat([close, opn], axis=1).min(axis=1) - low) / (close + 1e-9)

    # ---------- 动量 ----------
    df["momentum_5_10"] = df["ret_5d"] - df["ret_10d"]
    df["momentum_10_20"] = df["ret_10d"] - df["ret_20d"]

    # ---------- 价格在区间内的位置 ----------
    roll_high = high.rolling(20, min_periods=20).max()
    roll_low = low.rolling(20, min_periods=20).min()
    df["price_position_20d"] = (close - roll_low) / (roll_high - roll_low + 1e-9)

    # ---------- 滞后收益率 ----------
    for lag in range(1, 6):
        df[f"ret_lag_{lag}"] = df["ret_1d"].shift(lag)

    feature_cols = [
        "ret_1d", "ret_2d", "ret_3d", "ret_5d", "ret_10d", "ret_20d",
        "ma5_bias", "ma10_bias", "ma20_bias", "ma60_bias",
        "ema12_bias", "ema26_bias",
        "macd_norm", "macd_signal_norm", "macd_hist_norm",
        "rsi_6", "rsi_14",
        "bb_width", "bb_position",
        "atr_pct",
        "volatility_5d", "volatility_10d", "volatility_20d",
        "vol_ratio_5", "vol_ratio_20", "vol_trend",
        "candle_body", "amplitude", "upper_shadow", "lower_shadow",
        "momentum_5_10", "momentum_10_20",
        "price_position_20d",
        "ret_lag_1", "ret_lag_2", "ret_lag_3", "ret_lag_4", "ret_lag_5",
    ]
    feature_cols = [c for c in feature_cols if c in df.columns]
    return df, feature_cols


def merge_news_sentiment(
    df: pd.DataFrame,
    news_df: pd.DataFrame,
) -> Tuple[pd.DataFrame, List[str]]:
    """合并新闻情绪特征（可选）

    news_df 需包含 trade_date 列和至少一个情绪列。
    """
    news_cols = [c for c in news_df.columns if c != "trade_date"]
    if not news_cols:
        return df, []

    df = df.merge(news_df, on="trade_date", how="left")
    for c in news_cols:
        df[c] = df[c].fillna(0)
    return df, news_cols


# ---------------------------------------------------------------------------
# 标签生成
# ---------------------------------------------------------------------------

HORIZON_MAP = {"1d": 1, "5d": 5, "10d": 10, "20d": 20}


def generate_labels(
    df: pd.DataFrame,
    horizon: str = "5d",
    task_type: str = "regression",
) -> Tuple[pd.DataFrame, str]:
    """生成前瞻标签

    regression:     forward log return
    classification: 1 if forward return > 0 else 0

    Returns:
        df:         带标签列的 DataFrame
        label_col:  标签列名
    """
    periods = HORIZON_MAP.get(horizon, 5)
    close = df["close"].astype(float)

    ret_col = f"fwd_ret_{horizon}"
    df[ret_col] = np.log(close.shift(-periods) / close)

    if task_type == "classification":
        label_col = f"label_{horizon}"
        df[label_col] = (df[ret_col] > 0).astype(int)
    else:
        label_col = ret_col

    return df, label_col


# ---------------------------------------------------------------------------
# 统一数据准备入口
# ---------------------------------------------------------------------------

class TimeSeriesDataLoader:
    """统一的数据加载与预处理管道

    用法：
        loader = TimeSeriesDataLoader()
        dataset = loader.prepare(df, horizon="5d", task_type="classification")
        for split in loader.get_cv_splits(dataset, n_splits=5):
            X_train, y_train = dataset.X[split.train_idx], dataset.y[split.train_idx]
            X_val, y_val = dataset.X[split.val_idx], dataset.y[split.val_idx]
    """

    def prepare(
        self,
        df: pd.DataFrame,
        horizon: str = "5d",
        task_type: str = "regression",
        news_df: Optional[pd.DataFrame] = None,
        extra_feature_cols: Optional[List[str]] = None,
    ) -> TimeSeriesDataset:
        """主入口：原始 OHLCV → 训练就绪数据集

        Args:
            df:           必须包含 trade_date, close；可选 open, high, low, vol
            horizon:      预测周期 1d / 5d / 10d / 20d
            task_type:    classification / regression
            news_df:      新闻情绪 DataFrame（可选）
            extra_feature_cols: 额外特征列名（已存在于 df 中）
        """
        if df is None or df.empty:
            raise ValueError("输入 DataFrame 不能为空")

        df = df.sort_values("trade_date").reset_index(drop=True)

        # 1. 特征工程
        df, feature_cols = build_features(df)

        # 2. 合并新闻情绪
        if news_df is not None and not news_df.empty:
            df, news_cols = merge_news_sentiment(df, news_df)
            feature_cols.extend(news_cols)

        # 3. 额外特征
        if extra_feature_cols:
            for c in extra_feature_cols:
                if c in df.columns and c not in feature_cols:
                    feature_cols.append(c)

        # 4. 生成标签
        df, label_col = generate_labels(df, horizon, task_type)

        # 5. 清理缺失值
        required = feature_cols + [label_col, "trade_date", "close"]
        df_clean = df.dropna(subset=[label_col]).copy()
        # 特征中的 NaN 填 0（前面的 rolling 窗口期）
        df_clean[feature_cols] = df_clean[feature_cols].fillna(0)

        if len(df_clean) < 30:
            raise ValueError(f"清理后样本不足: {len(df_clean)} < 30")

        X = df_clean[feature_cols].values.astype(np.float64)
        y = df_clean[label_col].values.astype(np.float64)
        dates = df_clean["trade_date"].values
        last_close = float(df_clean["close"].iloc[-1])

        logger.info(
            "数据准备完成: samples=%d, features=%d, horizon=%s, task=%s",
            len(X), len(feature_cols), horizon, task_type,
        )

        return TimeSeriesDataset(
            X=X,
            y=y,
            feature_names=feature_cols,
            dates=dates,
            last_close=last_close,
            task_type=task_type,
            horizon=horizon,
            metadata={"label_col": label_col, "raw_samples": len(df)},
        )

    # ------------------------------------------------------------------
    # 进阶入口：FactorEngine + FeatureSelector
    # ------------------------------------------------------------------

    def prepare_advanced(
        self,
        df: pd.DataFrame,
        horizon: str = "5d",
        task_type: str = "regression",
        news_df: Optional[pd.DataFrame] = None,
        macro_df: Optional[pd.DataFrame] = None,
        event_df: Optional[pd.DataFrame] = None,
        top_n_features: int = 40,
        enable_derived: bool = True,
        redundancy_threshold: float = 0.95,
        feature_selector_method: str = "auto",
        selection_cutoff_ratio: float = 0.8,
    ) -> Tuple[TimeSeriesDataset, "SelectionResult"]:
        """进阶数据准备：FactorEngine 全因子 → FeatureSelector 自动筛选

        Anti-leakage: 特征筛选仅使用前 selection_cutoff_ratio 的数据，
        确保筛选过程不会看到验证期的标签。

        Args:
            df:                   OHLCV DataFrame
            horizon:              预测周期
            task_type:            classification / regression
            news_df:              新闻情绪数据
            macro_df:             宏观经济数据
            event_df:             事件驱动因子数据
            top_n_features:       筛选后保留的特征数
            enable_derived:       是否生成衍生特征
            redundancy_threshold: 冗余特征相关性阈值
            feature_selector_method: 筛选方法
            selection_cutoff_ratio: 用于特征筛选的数据比例（防止未来泄露）

        Returns:
            dataset:          筛选后的 TimeSeriesDataset
            selection_result: 特征筛选结果（含排名、相关矩阵等）
        """
        from .factor_engine import FactorEngine
        from .feature_selector import FeatureSelector

        if df is None or df.empty:
            raise ValueError("输入 DataFrame 不能为空")

        df = df.sort_values("trade_date").reset_index(drop=True)

        # 1. FactorEngine 计算全部因子
        engine = FactorEngine(enable_derived=enable_derived)
        df, all_factors, factor_groups = engine.compute(
            df, news_df=news_df, macro_df=macro_df, event_df=event_df,
        )

        # 2. 生成标签
        df, label_col = generate_labels(df, horizon, task_type)

        # 3. 清理
        df_clean = df.dropna(subset=[label_col]).copy()
        existing_factors = [c for c in all_factors if c in df_clean.columns]
        df_clean[existing_factors] = df_clean[existing_factors].fillna(0)

        if len(df_clean) < 60:
            raise ValueError(f"清理后样本不足: {len(df_clean)} < 60")

        X_raw = df_clean[existing_factors].values.astype(np.float64)
        y = df_clean[label_col].values.astype(np.float64)

        # 处理非有限值
        X_raw = np.nan_to_num(X_raw, nan=0.0, posinf=0.0, neginf=0.0)

        # 4. FeatureSelector — 仅在前 selection_cutoff_ratio 的数据上筛选
        #    防止特征筛选过程看到验证期的标签（anti look-ahead bias）
        n_total = len(X_raw)
        n_select = max(60, int(n_total * selection_cutoff_ratio))
        X_for_selection = X_raw[:n_select]
        y_for_selection = y[:n_select]

        logger.info(
            "特征筛选使用前 %d/%d 样本（%.0f%%），隔离后 %d 样本防止未来泄露",
            n_select, n_total, selection_cutoff_ratio * 100,
            n_total - n_select,
        )

        selector = FeatureSelector(
            top_n=top_n_features,
            redundancy_threshold=redundancy_threshold,
        )
        _, selected_names, selection_result = selector.fit_transform(
            X_for_selection, y_for_selection, existing_factors, task_type, factor_groups,
        )

        # 用筛选出的特征列从完整数据中提取
        X_selected = selector.transform(X_raw)

        dates = df_clean["trade_date"].values
        last_close = float(df_clean["close"].iloc[-1])

        logger.info(
            "进阶数据准备完成: samples=%d, raw_features=%d → selected=%d, horizon=%s",
            len(X_selected), len(existing_factors), len(selected_names), horizon,
        )

        dataset = TimeSeriesDataset(
            X=X_selected,
            y=y,
            feature_names=selected_names,
            dates=dates,
            last_close=last_close,
            task_type=task_type,
            horizon=horizon,
            metadata={
                "label_col": label_col,
                "raw_samples": len(df),
                "raw_features": len(existing_factors),
                "selected_features": len(selected_names),
                "factor_groups": {k: len(v.names) for k, v in factor_groups.items()},
            },
        )
        return dataset, selection_result

    # ------------------------------------------------------------------
    # 时间序列交叉验证
    # ------------------------------------------------------------------

    @staticmethod
    def get_cv_splits(
        dataset: TimeSeriesDataset,
        n_splits: int = 5,
        min_train_size: int = 120,
        val_ratio: float = 0.15,
    ) -> List[SplitIndex]:
        """严格时间序列 CV：训练集始终在验证集之前

        采用 expanding window 策略：
        - Fold 1: [0 ... T1-1] train, [T1 ... T1+V] val
        - Fold 2: [0 ... T2-1] train, [T2 ... T2+V] val
        - ...
        """
        n = len(dataset.X)
        val_size = max(20, int(n * val_ratio / n_splits))

        splits = []
        for i in range(n_splits):
            val_end = n - i * val_size
            val_start = val_end - val_size
            train_end = val_start

            if train_end < min_train_size or val_start < 0:
                break

            splits.append(SplitIndex(
                fold=len(splits),
                train_idx=np.arange(0, train_end),
                val_idx=np.arange(val_start, val_end),
            ))

        splits.reverse()  # fold 0 使用最少训练数据，fold N 使用最多
        for i, s in enumerate(splits):
            s.fold = i

        if not splits:
            raise ValueError(
                f"样本不足以进行 {n_splits} 折时间序列 CV "
                f"(n={n}, min_train={min_train_size})"
            )

        logger.info(
            "CV 分割: %d folds, train=%d~%d, val=%d",
            len(splits),
            len(splits[0].train_idx),
            len(splits[-1].train_idx),
            val_size,
        )
        return splits

    # ------------------------------------------------------------------
    # LSTM 专用：序列化数据
    # ------------------------------------------------------------------

    @staticmethod
    def to_sequences(
        X: np.ndarray,
        y: np.ndarray,
        seq_len: int = 20,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """将 2D 特征矩阵转换为 3D 序列 (n_seq, seq_len, n_features)"""
        sequences, targets = [], []
        for i in range(seq_len, len(X)):
            sequences.append(X[i - seq_len : i])
            targets.append(y[i])
        return np.array(sequences), np.array(targets)
