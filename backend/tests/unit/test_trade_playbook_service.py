from datetime import date
from pathlib import Path
from types import SimpleNamespace
import sys


BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import trade_playbook_service as svc


def _price(day: int, close: float):
    return SimpleNamespace(
        trade_date=date(2026, 4, day),
        open=close * 0.99,
        high=close * 1.02,
        low=close * 0.98,
        close=close,
    )


def _trade_decision(**overrides):
    payload = {
        "signal": "buy",
        "confidence": 0.68,
        "risk_level": "medium",
        "risk_score": 42,
        "expected_return": 0.06,
        "expected_downside": -0.04,
        "risk_reward_ratio": 1.5,
        "suggested_position_pct": {"min": 0.08, "max": 0.18, "label": "8% - 18%"},
        "stop_loss_price": None,
        "take_profit_price": None,
        "applicable_horizon": "1-5个交易日",
        "reasons": [{"type": "technical", "evidence": "模型上涨概率 62.0%"}],
    }
    payload.update(overrides)
    return payload


def test_trade_playbook_returns_executable_contract(monkeypatch):
    monkeypatch.setattr(svc, "build_trade_decision", lambda **kwargs: _trade_decision())
    inputs = svc.RetailInputs(
        symbol="002460.SZ",
        profile=SimpleNamespace(company_name="测试股份", business_summary="公司覆盖新能源材料业务。"),
        prices=[_price(24, 10.0), _price(23, 9.8), _price(22, 9.7), _price(21, 9.6), _price(20, 9.5)],
        latest_signal=SimpleNamespace(factors_json={"momentum": 1}, signal_date=date(2026, 4, 24), action="buy", score=72, risk_score=42),
        latest_prediction=SimpleNamespace(direction_prob_up=0.62, predicted_return=0.05, confidence=0.66, horizon="D3", predict_date=date(2026, 4, 24), target_date=date(2026, 4, 27)),
        latest_fundflow=SimpleNamespace(trade_date=date(2026, 4, 24), main_net=1_000_000, main_ratio=1.3),
        model_accuracy=63.0,
        factor_context={"macro": {"breadth_label": "中性", "breadth_ratio": 0.52}, "news": {"article_count": 2, "sentiment_label": "偏积极"}},
    )

    playbook = svc._build_trade_playbook(inputs)

    assert playbook["stockCode"] == "002460.SZ"
    assert playbook["actionCategory"] == "executable_now"
    assert playbook["buyPlan"]["idealBuyRange"]
    assert playbook["sellPlan"]["stopLossPrice"] < playbook["currentPrice"]
    assert playbook["sellPlan"]["takeProfitPrice1"] > playbook["currentPrice"]
    assert playbook["scenarioPlan"]["ifBreakdown"]
    assert playbook["holdingPlan"]["ifAlreadyHolding"]
    assert playbook["disclaimer"] == svc.RETAIL_DISCLAIMER


def test_action_category_handles_high_risk_and_sell_signal():
    stats = {"recent_high": 10.3, "recent_low": 9.3, "volatility": 0.025, "ma5": 9.9, "ma20": 9.7}
    price_plan = {"suggestedBuyRange": {"min": 9.8, "max": 10.1}, "doNotChaseAbove": 10.4}

    assert svc._decide_action_category(_trade_decision(risk_level="extreme", risk_score=88), price_plan, 10.0, stats) == "avoid"
    assert svc._decide_action_category(_trade_decision(signal="sell"), price_plan, 10.0, stats) == "reduce"
    assert svc._decide_action_category(_trade_decision(signal="strong_sell"), price_plan, 10.0, stats) == "sell"


def test_plan_review_marks_stop_loss_failure():
    playbook = {
        "stockCode": "002460.SZ",
        "stockName": "测试股份",
        "asOfDate": "2026-04-24",
        "targetTradeDate": "2026-04-27",
        "actionCategory": "wait_for_pullback",
        "currentPrice": 9.4,
        "buyPlan": {"idealBuyRange": [9.7, 10.0]},
        "sellPlan": {"stopLossPrice": 9.5, "takeProfitPrice1": 10.5, "takeProfitPrice2": 10.9},
    }

    review = svc._plan_review_from_playbook(playbook)

    assert review["stopLossTriggered"] is True
    assert review["planResult"] == "failed"
    assert review["lessons"]


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__]))