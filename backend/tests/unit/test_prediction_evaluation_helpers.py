from datetime import date, datetime, timedelta
from types import SimpleNamespace

from app.prediction.services.prediction_service import (
    build_deviation_cases,
    build_evaluation_availability,
    build_prediction_quality,
    classify_deviation_level,
)


def forecast(target_date, yhat=100.0, run_at=None):
    return SimpleNamespace(
        target_date=target_date,
        yhat=yhat,
        yhat_lower=95.0,
        yhat_upper=105.0,
        run_at=run_at or datetime(2026, 4, 24, 16, 0),
        model="TEST",
    )


def evaluation(target_date, actual_price=None, predicted_price=100.0, error_pct=None, direction_correct=None):
    return SimpleNamespace(
        symbol="300750.SZ",
        prediction_date=date(2026, 4, 24),
        target_date=target_date,
        model_name="TEST",
        predicted_price=predicted_price,
        actual_price=actual_price,
        error_pct=error_pct,
        direction_correct=direction_correct,
        evaluated_at=datetime(2026, 4, 27, 18, 0) if actual_price is not None else None,
    )


def price_row(trade_date, close=100.0):
    return SimpleNamespace(trade_date=trade_date, close=close)


def test_availability_reports_no_prediction_snapshot():
    availability = build_evaluation_availability(
        "300750.SZ",
        [],
        [],
        [],
        today=date(2026, 4, 26),
        supported_record_count=0,
    )

    assert availability["available"] is False
    assert availability["status"] == "no_prediction_snapshot"
    assert availability["evaluated_records"] == 0


def test_availability_reports_pending_target_date():
    availability = build_evaluation_availability(
        "300750.SZ",
        [],
        [forecast(date(2026, 4, 27))],
        [price_row(date(2026, 4, 24))],
        today=date(2026, 4, 26),
        supported_record_count=0,
    )

    assert availability["available"] is False
    assert availability["status"] == "pending_target_date"
    assert availability["next_evaluable_date"] == "2026-04-27"


def test_availability_reports_missing_actual_price_for_due_prediction():
    availability = build_evaluation_availability(
        "300750.SZ",
        [evaluation(date(2026, 4, 24), actual_price=None)],
        [forecast(date(2026, 4, 24))],
        [],
        today=date(2026, 4, 26),
        supported_record_count=0,
    )

    assert availability["available"] is False
    assert availability["status"] == "missing_actual_price"
    assert availability["missing_actual_records"] >= 1


def test_deviation_cases_include_signed_error_and_level():
    target = date(2026, 4, 27)
    pe = evaluation(target, actual_price=90.0, predicted_price=110.0, error_pct=22.22, direction_correct=False)
    fc = forecast(target, yhat=110.0)
    lookup = {(pe.prediction_date, pe.target_date, pe.model_name): fc}

    cases = build_deviation_cases([pe], lookup, horizon_resolver=lambda _pred, _target: 1)

    assert len(cases) == 1
    assert cases[0]["signed_error_pct"] == 22.22
    assert cases[0]["deviation_level"] == "critical"
    assert cases[0]["interval_hit"] is False
    assert cases[0]["horizon_days"] == 1


def test_classify_deviation_level_uses_direction_and_interval():
    assert classify_deviation_level(1.2, True, True) == "low"
    assert classify_deviation_level(4.0, True, True) == "medium"
    assert classify_deviation_level(2.0, False, True) == "high"
    assert classify_deviation_level(9.0, False, False) == "critical"


def test_prediction_quality_grades_usable_history():
    summary = {
        "evaluated_records": 12,
        "mape": 2.4,
        "signed_bias_pct": -0.8,
        "direction_accuracy": 66.7,
        "interval_hit_rate": 75.0,
        "high_deviation_count": 0,
        "latest_evaluated_at": "2026-04-27T18:00:00",
    }
    availability = {
        "status": "available",
        "available": True,
        "min_samples": 3,
        "next_action": "继续按日评估。",
    }

    quality = build_prediction_quality("300750.SZ", summary, availability, [])

    assert quality["quality_grade"] in {"excellent", "good"}
    assert quality["quality_score"] > 65
    assert quality["confidence_level"] == "medium"
    assert quality["warnings"] == []


def test_prediction_quality_warns_for_sparse_and_biased_history():
    summary = {
        "evaluated_records": 1,
        "mape": 9.5,
        "signed_bias_pct": 7.2,
        "direction_accuracy": 0.0,
        "interval_hit_rate": 0.0,
        "high_deviation_count": 1,
    }
    availability = {
        "status": "insufficient_samples",
        "available": True,
        "min_samples": 3,
        "next_action": "继续累积样本。",
    }

    quality = build_prediction_quality("300750.SZ", summary, availability, [])

    assert quality["quality_grade"] == "risk"
    assert quality["confidence_level"] == "low"
    assert any("样本数偏少" in warning for warning in quality["warnings"])
    assert any("高估" in warning for warning in quality["warnings"])