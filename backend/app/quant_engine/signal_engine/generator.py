"""
信号生成器（Signal Generator）— Production Alpha Engine

将模型预测结果 + 因子综合分析 → 交易信号

信号生成逻辑（v2 升级版）：
1. 获取分类模型预测（方向概率）+ 回归模型预测（预测收益率）
2. 统一因子归一化：score = 50 + 50 * tanh(zscore)
3. 多因子风险模型：波动率 + 下行风险 + 最大回撤 + 量能不稳定 + RSI极值
4. 综合评分：w1*方向概率 + w2*预期收益标准化 - w3*风险分
5. 存储至 qe_signals 表
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import select, and_
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..models import QESignal, QESignalAction, QEPrediction
from ..feature_engineering.pipeline import FeaturePipeline
from ..model_engine.registry import ModelManager
from ..data_layer.market_data import get_watchlist_symbols
from ..data_layer.macro_data import load_index_daily
from .regime import RegimeDetector, MarketRegime

logger = logging.getLogger(__name__)

# 信号阈值配置
SIGNAL_THRESHOLDS = {
    "strong_buy": 75,
    "buy": 62,
    "hold_upper": 55,
    "hold_lower": 45,
    "sell": 38,
    "strong_sell": 25,
}

# 综合评分权重 —— 模型驱动为主
SCORING_WEIGHTS = {
    "direction_prob": 0.30,      # 分类模型: 方向概率
    "expected_return": 0.25,     # 回归模型: 预期收益
    "risk_penalty": 0.20,        # 风险惩罚（取负）
    "momentum_score": 0.10,      # 动量因子
    "fund_flow_score": 0.08,     # 资金流向
    "sentiment_score": 0.07,     # 新闻情绪
}


class SignalGenerator:
    """信号生成器（v2 — 双模型驱动 + 多因子风险）

    用法：
        gen = SignalGenerator(session)
        signal = gen.generate_signal("600519.SH")
        signals = gen.generate_all_signals()
    """

    def __init__(self, session: Session):
        self.session = session
        self.pipeline = FeaturePipeline(session)
        self.model_manager = ModelManager(session)
        self.regime_detector = RegimeDetector()
        self._cached_regime = None

    def generate_signal(
        self,
        symbol: str,
        task: str = "next_day_direction",
        algo: str = "lightgbm",
        horizon: str = "5d",
        signal_date: Optional[date] = None,
    ) -> Optional[dict]:
        """为单只股票生成交易信号

        Returns:
            {'symbol': ..., 'action': ..., 'score': ..., 'risk_score': ..., ...}
        """
        signal_date = signal_date or date.today()

        try:
            # 归一化特征供模型推理
            features_df, _feat_names = self.pipeline.build_latest(symbol=symbol, normalize="zscore")
            if features_df is None or features_df.empty:
                logger.warning("信号生成失败: %s 特征数据不足", symbol)
                return None

            # 原始（未归一化）特征供因子评分 & 风险评分
            try:
                raw_features_df, _ = self.pipeline.build_latest(symbol=symbol, normalize="none")
            except Exception:
                raw_features_df = features_df

            # ---- 分类模型（方向预测） ----
            model_cls, db_model_cls = self.model_manager.get_or_create_model(symbol, task, algo)
            if model_cls._model is None:
                logger.warning("信号生成失败: %s 无可用分类模型", symbol)
                return None

            pred_result = model_cls.get_prediction_result(
                features_df, symbol=symbol, predict_date=signal_date.isoformat(), horizon=horizon
            )

            # ---- 回归模型（收益率预测） ----
            reg_task = task.replace("direction", "return")
            try:
                model_reg, _ = self.model_manager.get_or_create_model(symbol, reg_task, algo)
                if model_reg._model is not None:
                    model_cls.merge_regression_result(pred_result, model_reg, features_df)
            except Exception:
                pass  # 回归模型可选，不影响信号生成

            # ---- 计算各维度评分 ----
            factor_scores = self._compute_factor_scores(raw_features_df, pred_result)
            risk_score = self._compute_risk_score(raw_features_df)

            # ---- 市场环境调整 ----
            regime_result = self._detect_regime()
            adjustments = RegimeDetector.get_adjustments(regime_result.regime)
            risk_score = risk_score * adjustments["risk_discount"]
            risk_score = min(max(risk_score, 0), 100)

            composite_score = self._composite_score(factor_scores, risk_score)
            composite_score += adjustments["score_bias"]
            composite_score = min(max(composite_score, 0), 100)

            action = self._score_to_action(composite_score, adjustments)

            # 存储信号（含环境信息）
            factor_scores["market_regime"] = regime_result.regime.value
            factor_scores["regime_confidence"] = regime_result.confidence

            # 存储信号
            signal_data = {
                "symbol": symbol,
                "signal_date": signal_date,
                "action": action,
                "score": round(composite_score, 2),
                "risk_score": round(risk_score, 2),
                "direction_prob_up": pred_result.direction_prob_up,
                "predicted_return": pred_result.predicted_return,
                "factors_json": factor_scores,
            }

            stmt = pg_insert(QESignal).values(**signal_data)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_qe_signal_sd",
                set_={
                    "action": stmt.excluded.action,
                    "score": stmt.excluded.score,
                    "risk_score": stmt.excluded.risk_score,
                    "direction_prob_up": stmt.excluded.direction_prob_up,
                    "predicted_return": stmt.excluded.predicted_return,
                    "factors_json": stmt.excluded.factors_json,
                },
            )
            self.session.execute(stmt)

            # 同时存储预测记录
            pred_data = {
                "symbol": symbol,
                "predict_date": signal_date,
                "target_date": signal_date,
                "horizon": horizon,
                "direction_prob_up": pred_result.direction_prob_up,
                "direction_prob_down": pred_result.direction_prob_down,
                "predicted_return": pred_result.predicted_return,
                "confidence": pred_result.confidence,
                "explanation_json": pred_result.feature_importance,
            }
            pred_stmt = pg_insert(QEPrediction).values(**pred_data)
            pred_stmt = pred_stmt.on_conflict_do_update(
                constraint="uq_qe_pred_sphm",
                set_={
                    "direction_prob_up": pred_stmt.excluded.direction_prob_up,
                    "predicted_return": pred_stmt.excluded.predicted_return,
                    "confidence": pred_stmt.excluded.confidence,
                },
            )
            self.session.execute(pred_stmt)
            self.session.commit()

            logger.info(
                "信号生成: %s -> %s (score=%.1f, risk=%.1f, pred_ret=%.4f)",
                symbol, action, composite_score, risk_score,
                pred_result.predicted_return or 0,
            )
            return signal_data

        except Exception as e:
            self.session.rollback()
            logger.error("信号生成异常: %s, error=%s", symbol, e, exc_info=True)
            return None

    def generate_all_signals(
        self,
        task: str = "next_day_direction",
        algo: str = "lightgbm",
        horizon: str = "5d",
        pinned_only: bool = True,
    ) -> list[dict]:
        """批量生成所有观察列表股票的信号"""
        symbols = get_watchlist_symbols(self.session, pinned_only=pinned_only)
        if not symbols:
            logger.warning("无可生成信号的股票")
            return []

        signals = []
        for sym in symbols:
            sig = self.generate_signal(sym, task, algo, horizon)
            if sig:
                signals.append(sig)

        if signals:
            self._update_rankings(signals)

        logger.info("批量信号生成: 成功=%d/%d", len(signals), len(symbols))
        return signals

    # -------------------------------------------------------
    # 因子评分 — 统一使用 tanh(zscore) 归一化到 0-100
    # -------------------------------------------------------
    @staticmethod
    def _tanh_normalize(value: float, center: float = 0, scale: float = 1) -> float:
        """将原始值通过 tanh 映射到 0-100 区间

        score = 50 + 50 * tanh((value - center) / scale)
        """
        z = (value - center) / scale if scale != 0 else 0
        return 50.0 + 50.0 * float(np.tanh(z))

    def _compute_factor_scores(self, features: pd.DataFrame, pred_result) -> dict:
        """各维度评分（0-100），统一 tanh 归一化"""
        row = features.iloc[0] if len(features) > 0 else pd.Series(dtype=float)
        scores = {}

        # -- 模型输出 --
        prob_up = self._safe_number(pred_result.direction_prob_up, 0.5)
        scores["direction_prob"] = prob_up * 100

        pred_ret = self._safe_number(pred_result.predicted_return, 0.0)
        # 预期收益: 日收益 0.01 对应 ~65分, 0.05 对应 ~90分
        scores["expected_return"] = self._tanh_normalize(pred_ret, center=0, scale=0.03)

        # -- 动量因子 --
        ret_5d = self._safe_number(row.get("ret_5d", 0), 0)
        ret_20d = self._safe_number(row.get("ret_20d", 0), 0)
        rsi = self._safe_number(row.get("rsi_14", 50), 50)
        # RSI: 30=超卖→高分(反转逻辑), 70=超买→低分
        rsi_score = self._tanh_normalize(50 - abs(rsi - 50), center=0, scale=20)
        momentum_raw = ret_5d * 0.6 + ret_20d * 0.4
        scores["momentum_score"] = self._tanh_normalize(momentum_raw, center=0, scale=0.05)
        scores["rsi_score"] = rsi_score

        # -- MACD（标准化值） --
        macd_norm = self._safe_number(row.get("macd_norm", 0), 0)
        scores["macd_score"] = self._tanh_normalize(macd_norm, center=0, scale=0.005)

        # -- 资金流向 --
        fund_net = self._safe_number(row.get("fund_main_net_norm", 0), 0)
        fund_momentum = self._safe_number(row.get("fund_flow_momentum", 0), 0)
        scores["fund_flow_score"] = self._tanh_normalize(
            fund_net * 0.6 + fund_momentum * 0.4, center=0, scale=0.5
        )

        # -- 新闻情绪 --
        sentiment_3d = self._safe_number(row.get("news_sentiment_3d", 0), 0)
        sentiment_mom = self._safe_number(row.get("news_sentiment_momentum", 0), 0)
        scores["sentiment_score"] = self._tanh_normalize(
            sentiment_3d * 0.7 + sentiment_mom * 0.3, center=0, scale=0.3
        )

        # -- 成交量活跃度 --
        vol_ratio = self._safe_number(row.get("vol_ratio_5", 1), 1)
        scores["volume_score"] = self._tanh_normalize(vol_ratio, center=1.0, scale=0.5)

        return {k: round(self._safe_number(v, 50.0), 1) for k, v in scores.items()}

    def _composite_score(self, factor_scores: dict, risk_score: float) -> float:
        """综合评分 = 加权因子得分 - 风险惩罚

        评分范围 0-100
        """
        # 加权多头信号
        signal = 0.0
        signal += self._safe_number(factor_scores.get("direction_prob", 50), 50) * SCORING_WEIGHTS["direction_prob"]
        signal += self._safe_number(factor_scores.get("expected_return", 50), 50) * SCORING_WEIGHTS["expected_return"]
        signal += self._safe_number(factor_scores.get("momentum_score", 50), 50) * SCORING_WEIGHTS["momentum_score"]
        signal += self._safe_number(factor_scores.get("fund_flow_score", 50), 50) * SCORING_WEIGHTS["fund_flow_score"]
        signal += self._safe_number(factor_scores.get("sentiment_score", 50), 50) * SCORING_WEIGHTS["sentiment_score"]

        # 风险惩罚：risk_score 50 为中性，>50 惩罚
        risk_penalty = max(risk_score - 50, 0) * SCORING_WEIGHTS["risk_penalty"]

        composite = signal - risk_penalty
        return min(max(composite, 0), 100)

    # -------------------------------------------------------
    # 多因子风险模型
    # -------------------------------------------------------
    def _compute_risk_score(self, features: pd.DataFrame) -> float:
        """多因子风险评分（0-100，越高越危险）

        因子及权重：
        - 波动率 (volatility_20d): 权重 25%
        - 下行波动 (downside_vol_20d): 权重 20%
        - 最大回撤 (max_drawdown_60d): 权重 20%
        - 量能不稳定 (vol_stability_20d): 权重 15%
        - RSI 极值: 权重 10%
        - 量比异常 (vol_ratio_5): 权重 10%
        """
        row = features.iloc[0] if len(features) > 0 else pd.Series(dtype=float)

        # 波动率 → 0-100 (典型 0.15-0.50, center=0.30)
        vol = self._safe_number(row.get("volatility_20d", 0.25), 0.25)
        vol_risk = self._tanh_normalize(vol, center=0.25, scale=0.12) * 0.25

        # 下行波动 → 0-100 (典型 0.10-0.40)
        dsvol = self._safe_number(row.get("downside_vol_20d", 0.15), 0.15)
        dsvol_risk = self._tanh_normalize(dsvol, center=0.15, scale=0.10) * 0.20

        # 最大回撤 → 0-100 (值为负数, -0.10 表示 10% 回撤)
        mdd = self._safe_number(row.get("max_drawdown_60d", -0.05), -0.05)
        mdd_risk = self._tanh_normalize(-mdd, center=0.05, scale=0.08) * 0.20

        # 量能不稳定 → 0-100 (std of vol_ratio, 典型 0.2-1.0)
        vol_stab = self._safe_number(row.get("vol_stability_20d", 0.3), 0.3)
        vol_stab_risk = self._tanh_normalize(vol_stab, center=0.3, scale=0.3) * 0.15

        # RSI 极值风险
        rsi = self._safe_number(row.get("rsi_14", 50), 50)
        rsi_extreme = abs(rsi - 50) / 50  # 0=中性, 1=极端
        rsi_risk = rsi_extreme * 100 * 0.10

        # 量比异常
        vol_ratio = self._safe_number(row.get("vol_ratio_5", 1), 1)
        vol_ratio_risk = self._tanh_normalize(abs(vol_ratio - 1), center=0, scale=0.8) * 0.10

        risk = vol_risk + dsvol_risk + mdd_risk + vol_stab_risk + rsi_risk + vol_ratio_risk
        return min(max(risk, 0), 100)

    @staticmethod
    def _safe_number(value, default: float = 0.0) -> float:
        """将 NaN/inf/None 安全转换为 float"""
        if value is None:
            return default
        try:
            v = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(v):
            return default
        return v

    def _score_to_action(self, score: float, adjustments: Optional[dict] = None) -> str:
        """评分 → 信号动作（支持市场环境阈值调整）"""
        buy_adj = adjustments.get("buy_threshold", 0) if adjustments else 0
        sell_adj = adjustments.get("sell_threshold", 0) if adjustments else 0

        if score >= SIGNAL_THRESHOLDS["strong_buy"] + buy_adj:
            return QESignalAction.STRONG_BUY.value
        elif score >= SIGNAL_THRESHOLDS["buy"] + buy_adj:
            return QESignalAction.BUY.value
        elif score >= SIGNAL_THRESHOLDS["hold_lower"] + sell_adj:
            return QESignalAction.HOLD.value
        elif score >= SIGNAL_THRESHOLDS["sell"] + sell_adj:
            return QESignalAction.SELL.value
        else:
            return QESignalAction.STRONG_SELL.value

    def _detect_regime(self):
        """获取当前市场环境（缓存，一次批量生成中只检测一次）"""
        if self._cached_regime is not None:
            return self._cached_regime
        try:
            index_df = load_index_daily("上证指数")
            if index_df is not None and not index_df.empty:
                self._cached_regime = self.regime_detector.detect(index_df)
            else:
                from .regime import RegimeResult
                self._cached_regime = RegimeResult(
                    regime=MarketRegime.SIDEWAYS, confidence=0.3,
                    index_trend=0, market_volatility=0.2, breadth=0.5,
                    details={"reason": "no_index_data"},
                )
        except Exception as e:
            logger.warning("市场环境检测失败: %s", e)
            from .regime import RegimeResult
            self._cached_regime = RegimeResult(
                regime=MarketRegime.SIDEWAYS, confidence=0.3,
                index_trend=0, market_volatility=0.2, breadth=0.5,
                details={"reason": str(e)},
            )
        return self._cached_regime

    def _update_rankings(self, signals: list[dict]) -> None:
        """更新当日排名"""
        sorted_sigs = sorted(signals, key=lambda s: s.get("score", 0), reverse=True)
        for rank, sig in enumerate(sorted_sigs, 1):
            self.session.execute(
                QESignal.__table__.update()
                .where(
                    and_(
                        QESignal.symbol == sig["symbol"],
                        QESignal.signal_date == sig["signal_date"],
                    )
                )
                .values(rank=rank)
            )
        self.session.commit()
