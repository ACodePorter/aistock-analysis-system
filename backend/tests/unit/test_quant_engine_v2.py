"""
量化引擎单元测试 —— 新增因子、风险模型、信号生成、市场环境检测

运行方式：
    python -m pytest backend/tests/unit/test_quant_engine_v2.py -v
    或
    python backend/tests/unit/test_quant_engine_v2.py
"""

import sys
import os
import unittest

import numpy as np
import pandas as pd

# 确保 backend 在路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class TestScaleInvariantFactors(unittest.TestCase):
    """测试新增的尺度无关因子"""

    def _make_price_df(self, base_price=100.0, n=120):
        """生成模拟行情数据"""
        np.random.seed(42)
        close = base_price * np.cumprod(1 + np.random.randn(n) * 0.02)
        high = close * (1 + np.abs(np.random.randn(n) * 0.01))
        low = close * (1 - np.abs(np.random.randn(n) * 0.01))
        open_ = close * (1 + np.random.randn(n) * 0.005)
        vol = np.random.randint(10000, 100000, n).astype(float)
        return pd.DataFrame({
            "open": open_, "high": high, "low": low, "close": close,
            "vol": vol, "amount": vol * close,
        })

    def test_atr_pct_scale_invariant(self):
        """ATR% 应与价格量级无关"""
        from app.quant_engine.factor_engine.technical import compute_atr_pct
        df_low = self._make_price_df(base_price=10.0)
        df_high = self._make_price_df(base_price=1500.0)

        atr_pct_low = compute_atr_pct(df_low).dropna()
        atr_pct_high = compute_atr_pct(df_high).dropna()

        # 两者均值应在同一数量级（< 2x 差距）
        ratio = atr_pct_low.mean() / atr_pct_high.mean()
        self.assertGreater(ratio, 0.3, "ATR% 应尺度无关")
        self.assertLess(ratio, 3.0, "ATR% 应尺度无关")

    def test_macd_norm_scale_invariant(self):
        """MACD_norm 应与价格量级无关"""
        from app.quant_engine.factor_engine.technical import compute_macd_norm
        df_low = self._make_price_df(base_price=10.0)
        df_high = self._make_price_df(base_price=1500.0)

        mn_low = compute_macd_norm(df_low).dropna()
        mn_high = compute_macd_norm(df_high).dropna()

        ratio = mn_low.std() / mn_high.std()
        self.assertGreater(ratio, 0.3)
        self.assertLess(ratio, 3.0)

    def test_ma_diff_range(self):
        """MA 偏离度应为合理的百分比范围"""
        from app.quant_engine.factor_engine.technical import compute_ma_5_diff
        df = self._make_price_df()
        diff = compute_ma_5_diff(df).dropna()

        # 偏离度应为小百分比（不应超过 ±50%）
        self.assertLess(diff.abs().max(), 0.5)
        # 均值应接近 0
        self.assertAlmostEqual(diff.mean(), 0, delta=0.05)

    def test_downside_vol_nonnegative(self):
        """下行波动率应非负"""
        from app.quant_engine.factor_engine.technical import compute_downside_vol
        df = self._make_price_df()
        dsvol = compute_downside_vol(df).dropna()
        self.assertTrue((dsvol >= 0).all())

    def test_max_drawdown_nonpositive(self):
        """最大回撤应 <= 0"""
        from app.quant_engine.factor_engine.technical import compute_max_drawdown_60d
        df = self._make_price_df()
        mdd = compute_max_drawdown_60d(df).dropna()
        self.assertTrue((mdd <= 0).all())

    def test_ret_60d(self):
        """60日收益率应有值"""
        from app.quant_engine.factor_engine.technical import compute_ret_60d
        df = self._make_price_df()
        ret = compute_ret_60d(df).dropna()
        self.assertGreater(len(ret), 0)

    def test_vol_stability(self):
        """成交量稳定性应非负"""
        from app.quant_engine.factor_engine.technical import compute_vol_stability
        df = self._make_price_df()
        stab = compute_vol_stability(df).dropna()
        self.assertTrue((stab >= 0).all())


class TestSignalGeneratorScoring(unittest.TestCase):
    """测试信号生成器的评分逻辑"""

    def test_tanh_normalize_center(self):
        """tanh 归一化：中心值 → 50"""
        from app.quant_engine.signal_engine.generator import SignalGenerator
        score = SignalGenerator._tanh_normalize(0, center=0, scale=1)
        self.assertAlmostEqual(score, 50.0, places=1)

    def test_tanh_normalize_high(self):
        """tanh 归一化：大正值 → ~100"""
        from app.quant_engine.signal_engine.generator import SignalGenerator
        score = SignalGenerator._tanh_normalize(5.0, center=0, scale=1)
        self.assertGreater(score, 95)
        self.assertLessEqual(score, 100)

    def test_tanh_normalize_low(self):
        """tanh 归一化：大负值 → ~0"""
        from app.quant_engine.signal_engine.generator import SignalGenerator
        score = SignalGenerator._tanh_normalize(-5.0, center=0, scale=1)
        self.assertLess(score, 5)
        self.assertGreaterEqual(score, 0)

    def test_score_ranges(self):
        """所有评分应在 0-100"""
        from app.quant_engine.signal_engine.generator import SignalGenerator
        for val in [-10, -1, -0.1, 0, 0.1, 1, 10]:
            score = SignalGenerator._tanh_normalize(val, center=0, scale=1)
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)


class TestRegimeDetector(unittest.TestCase):
    """测试市场环境检测"""

    def _make_index_df(self, trend="up", n=150):
        """生成模拟指数"""
        np.random.seed(42)
        if trend == "up":
            close = 3000 * np.cumprod(1 + np.abs(np.random.randn(n) * 0.003) + 0.001)
        elif trend == "down":
            close = 3000 * np.cumprod(1 - np.abs(np.random.randn(n) * 0.003) - 0.001)
        else:
            close = 3000 + np.random.randn(n).cumsum() * 5
        return pd.DataFrame({"close": close})

    def test_bull_detection(self):
        """上行趋势应检测为牛市或震荡"""
        from app.quant_engine.signal_engine.regime import RegimeDetector, MarketRegime
        detector = RegimeDetector()
        result = detector.detect(self._make_index_df("up"))
        self.assertIn(result.regime, [MarketRegime.BULL, MarketRegime.SIDEWAYS])
        self.assertGreater(result.confidence, 0)

    def test_bear_detection(self):
        """下行趋势应检测为熊市或震荡"""
        from app.quant_engine.signal_engine.regime import RegimeDetector, MarketRegime
        detector = RegimeDetector()
        result = detector.detect(self._make_index_df("down"))
        self.assertIn(result.regime, [MarketRegime.BEAR, MarketRegime.SIDEWAYS])

    def test_empty_data(self):
        """空数据应返回震荡"""
        from app.quant_engine.signal_engine.regime import RegimeDetector, MarketRegime
        detector = RegimeDetector()
        result = detector.detect(pd.DataFrame())
        self.assertEqual(result.regime, MarketRegime.SIDEWAYS)

    def test_adjustments(self):
        """获取调整参数不应异常"""
        from app.quant_engine.signal_engine.regime import RegimeDetector, MarketRegime
        for regime in MarketRegime:
            adj = RegimeDetector.get_adjustments(regime)
            self.assertIn("score_bias", adj)
            self.assertIn("risk_discount", adj)


class TestPnLMetrics(unittest.TestCase):
    """测试增强的PnL指标"""

    def test_calmar_ratio(self):
        """Calmar ratio 应有值"""
        from app.quant_engine.evaluation_engine.metrics import compute_pnl_metrics
        np.random.seed(42)
        returns = pd.Series(np.random.randn(100) * 0.01 + 0.001)
        metrics = compute_pnl_metrics(returns)
        self.assertIn("calmar_ratio", metrics)
        self.assertIn("sortino_ratio", metrics)

    def test_empty_returns(self):
        """空收益率序列不应崩溃"""
        from app.quant_engine.evaluation_engine.metrics import compute_pnl_metrics
        metrics = compute_pnl_metrics(pd.Series(dtype=float))
        self.assertEqual(metrics["total_pnl"], 0.0)


if __name__ == "__main__":
    unittest.main()
