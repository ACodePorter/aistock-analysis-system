from types import SimpleNamespace

from app.prediction.services.trade_decision_service import DISCLAIMER, build_trade_decision


def test_build_trade_decision_from_signal_and_prediction():
    signal = SimpleNamespace(
        action="buy",
        score=68,
        risk_score=42,
        stop_loss=None,
        take_profit=None,
    )
    prediction = SimpleNamespace(
        predicted_return=0.055,
        direction_prob_up=0.64,
        confidence=0.72,
        horizon="5d",
    )

    decision = build_trade_decision(
        symbol="600519.SH",
        signal=signal,
        prediction=prediction,
        current_price=100.0,
        factors={"momentum_score": 72, "sentiment_score": 61},
        model_accuracy=63.3,
    )

    assert decision["stock_code"] == "600519.SH"
    assert decision["signal"] == "buy"
    assert decision["risk_level"] == "medium"
    assert decision["expected_return"] == 0.055
    assert decision["stop_loss_price"] < 100
    assert decision["take_profit_price"] > 100
    assert decision["suggested_position_pct"]["max"] > 0
    assert decision["risk_reward_ratio"] is not None
    assert decision["disclaimer"] == DISCLAIMER
    assert any(reason["type"] == "news_sentiment" for reason in decision["reasons"])


def test_build_trade_decision_falls_back_to_hold_when_data_missing():
    decision = build_trade_decision(symbol="000001.SZ")

    assert decision["signal"] == "hold"
    assert decision["risk_level"] == "medium"
    assert decision["source"] == "fallback_hold"
    assert decision["stop_loss_price"] is None
    assert decision["take_profit_price"] is None
    assert decision["disclaimer"] == DISCLAIMER
    assert decision["reasons"]