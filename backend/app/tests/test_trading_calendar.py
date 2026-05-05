from datetime import date

from app.core.trading_calendar import (
    get_next_n_trading_days,
    is_trading_day,
    last_trading_day_on_or_before,
    next_trading_day,
)


def test_weekend_is_not_trading_day():
    assert is_trading_day(date(2026, 4, 19)) is False  # Sunday


def test_known_2026_holiday_is_not_trading_day():
    assert is_trading_day(date(2026, 1, 1)) is False


def test_next_trading_day_skips_weekend():
    assert next_trading_day(date(2026, 4, 17)) == date(2026, 4, 20)  # Fri -> Mon


def test_last_trading_day_on_or_before_holiday():
    assert last_trading_day_on_or_before(date(2026, 1, 1)) == date(2025, 12, 31)


def test_get_next_n_trading_days_from_friday():
    days = get_next_n_trading_days(date(2026, 4, 17), 3)
    assert days == [date(2026, 4, 20), date(2026, 4, 21), date(2026, 4, 22)]
