from datetime import date
from pathlib import Path
from types import SimpleNamespace
import sys


BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import retail_decision_service as svc


def _price(day: int, close: float):
    return SimpleNamespace(
        trade_date=date(2026, 4, day),
        close=close,
        high=close * 1.02,
        low=close * 0.98,
    )


def test_final_action_downgrades_high_risk_buy_signal():
    inputs = svc.RetailInputs(
        symbol="002460.SZ",
        latest_prediction=SimpleNamespace(direction_prob_up=0.68),
    )

    low_confidence_high_risk = {
        "signal": "buy",
        "risk_level": "high",
        "confidence": 0.55,
        "risk_score": 70,
        "expected_return": 0.05,
    }
    assert svc._decide_final_action(low_confidence_high_risk, 10.0, inputs) == "wait"

    stronger_high_risk = {**low_confidence_high_risk, "confidence": 0.66}
    assert svc._decide_final_action(stronger_high_risk, 10.0, inputs) == "small_position_watch"

    extreme_risk = {**stronger_high_risk, "risk_level": "extreme", "risk_score": 82}
    assert svc._decide_final_action(extreme_risk, 10.0, inputs) == "avoid"


def test_build_retail_response_returns_ui_contract(monkeypatch):
    trade_decision = {
        "stock_code": "002460.SZ",
        "signal": "buy",
        "signal_label": "买入",
        "confidence": 0.66,
        "risk_level": "medium",
        "risk_score": 38,
        "expected_return": 0.06,
        "expected_downside": -0.04,
        "risk_reward_ratio": 1.5,
        "suggested_position_pct": {"min": 0.08, "max": 0.18, "label": "8% - 18%"},
        "stop_loss_price": None,
        "take_profit_price": None,
        "invalidation_condition": "跌破关键价位",
        "applicable_horizon": "1-5个交易日",
        "reasons": [{"type": "technical", "label": "技术", "evidence": "模型上涨概率 62.0%", "weight": 1.0}],
        "source": "test",
        "generated_at": "2026-04-26T00:00:00Z",
        "disclaimer": svc.RETAIL_DISCLAIMER,
    }
    monkeypatch.setattr(svc, "build_trade_decision", lambda **kwargs: trade_decision)

    inputs = svc.RetailInputs(
        symbol="002460.SZ",
        profile=SimpleNamespace(company_name="测试股份", business_summary="公司覆盖新能源材料和电池回收业务。"),
        prices=[_price(24, 10.0), _price(23, 9.8), _price(22, 9.6), _price(21, 9.7), _price(20, 9.5)],
        latest_signal=SimpleNamespace(factors_json={"momentum": 1}),
        latest_prediction=SimpleNamespace(
            direction_prob_up=0.62,
            predicted_return=0.04,
            confidence=0.61,
            predict_date=date(2026, 4, 24),
            target_date=date(2026, 4, 27),
        ),
        latest_fundflow=SimpleNamespace(trade_date=date(2026, 4, 24), main_net=1_200_000, main_ratio=1.2),
        model_accuracy=61.0,
        factor_context={
            "macro": {"breadth_label": "中性", "breadth_ratio": 0.52},
            "news": {"article_count": 2, "sentiment_label": "偏积极", "headlines": [{"title": "测试新闻标题"}]},
        },
    )

    response = svc._build_retail_response(inputs)
    card = response["card"]

    assert response["symbol"] == "002460.SZ"
    assert card["finalAction"] == "can_buy"
    assert card["finalActionLabel"] == "可以小仓试买"
    assert card["disclaimer"] == svc.RETAIL_DISCLAIMER
    assert card["suggestedBuyRange"]["min"] is not None
    assert card["stopLossPrice"] < card["currentPrice"]
    assert card["takeProfitPrice1"] > card["currentPrice"]
    assert response["agentViews"]["riskControl"]["points"]

    candidate = svc._candidate_from_response(response)
    assert candidate["symbol"] == "002460.SZ"
    assert candidate["action"] == "can_buy"
    assert candidate["riskLabel"] == "中等"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__]))