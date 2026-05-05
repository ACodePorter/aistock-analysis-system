"""
量化引擎 v2 端到端集成测试

测试完整管道：双模型训练 → 信号生成（含市场环境）→ 回测
需要数据库连接。

运行：
    python backend/tests/integration/test_qe_v2_e2e.py
"""

import sys
import os
import json
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.core.db import SessionLocal


def main():
    session = SessionLocal()
    results = {}

    try:
        # 获取一个已有数据的股票
        from app.quant_engine.data_layer.market_data import get_watchlist_symbols
        symbols = get_watchlist_symbols(session, pinned_only=True)
        if not symbols:
            print("❌ 无活跃股票，跳过集成测试")
            return
        test_symbol = symbols[0]
        print(f"📌 测试股票: {test_symbol}")

        # ---- 1. 双模型训练 ----
        print("\n[1/4] 双模型训练...")
        from app.quant_engine.model_engine.trainer import TrainingOrchestrator
        orchestrator = TrainingOrchestrator(session)
        train_result = orchestrator.train_single(
            test_symbol, horizon="5d", dual_model=True
        )
        results["training"] = {
            "status": train_result.get("status"),
            "cls_version": train_result.get("version"),
            "cls_metrics": train_result.get("metrics"),
            "regression": train_result.get("regression"),
        }
        print(f"  分类模型: v{train_result.get('version')}, "
              f"metrics={json.dumps(train_result.get('metrics', {}), default=str)}")
        reg = train_result.get("regression", {})
        print(f"  回归模型: {json.dumps(reg, default=str)}")

        # ---- 2. 市场环境检测 ----
        print("\n[2/4] 市场环境检测...")
        from app.quant_engine.signal_engine.regime import RegimeDetector
        from app.quant_engine.data_layer.macro_data import load_index_daily
        detector = RegimeDetector()
        index_df = load_index_daily("上证指数")
        regime_result = detector.detect(index_df)
        results["regime"] = {
            "regime": regime_result.regime.value,
            "confidence": regime_result.confidence,
            "trend": regime_result.index_trend,
            "volatility": regime_result.market_volatility,
        }
        print(f"  环境: {regime_result.regime.value}, "
              f"置信度={regime_result.confidence:.2f}, "
              f"趋势={regime_result.index_trend:.4f}")

        # ---- 3. 信号生成 ----
        print("\n[3/4] 信号生成...")
        from app.quant_engine.signal_engine.generator import SignalGenerator
        gen = SignalGenerator(session)
        signal = gen.generate_signal(test_symbol, horizon="5d")
        if signal:
            results["signal"] = {
                "action": signal["action"],
                "score": signal["score"],
                "risk_score": signal["risk_score"],
                "direction_prob_up": signal.get("direction_prob_up"),
                "predicted_return": signal.get("predicted_return"),
                "factors": signal.get("factors_json"),
            }
            print(f"  信号: {signal['action']}, score={signal['score']:.1f}, "
                  f"risk={signal['risk_score']:.1f}")
            print(f"  方向概率: {signal.get('direction_prob_up'):.3f}")
            print(f"  预测收益: {signal.get('predicted_return')}")
            factors = signal.get("factors_json", {})
            print(f"  市场环境: {factors.get('market_regime', 'N/A')}")
        else:
            results["signal"] = {"status": "failed"}
            print("  ❌ 信号生成失败")

        # ---- 4. 验证评分范围 ----
        print("\n[4/4] 验证评分合理性...")
        checks = []
        if signal:
            s = signal["score"]
            r = signal["risk_score"]
            checks.append(("综合评分 0-100", 0 <= s <= 100))
            checks.append(("风险评分 0-100", 0 <= r <= 100))
            checks.append(("方向概率 0-1", 0 <= (signal.get("direction_prob_up") or 0) <= 1))
            factors = signal.get("factors_json", {})
            for k, v in factors.items():
                if k in ("market_regime", "regime_confidence"):
                    continue
                checks.append((f"因子 {k} ∈ [0,100]", 0 <= v <= 100))

        all_pass = True
        for name, passed in checks:
            status = "✅" if passed else "❌"
            if not passed:
                all_pass = False
            print(f"  {status} {name}")

        results["validation"] = {"all_pass": all_pass, "checks": len(checks)}

        # ---- 汇总 ----
        print(f"\n{'='*50}")
        print(f"集成测试{'通过 ✅' if all_pass else '失败 ❌'}")
        print(f"{'='*50}")

    except Exception as e:
        print(f"\n❌ 集成测试异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()


if __name__ == "__main__":
    main()
