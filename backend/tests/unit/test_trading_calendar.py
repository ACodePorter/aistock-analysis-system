"""单元测试：backend/app/core/trading_calendar.py

覆盖点：
- is_trading_day：工作日、周末、节假日
- next_trading_day / last_trading_day_on_or_before：跨周末、跨节假日
- get_next_n_trading_days / trading_days_between：计数与区间
"""
from __future__ import annotations

from datetime import date

import pytest

from app.core.trading_calendar import (
    get_next_n_trading_days,
    is_trading_day,
    last_trading_day_on_or_before,
    next_trading_day,
    trading_days_between,
)


class TestIsTradingDay:
    def test_weekday_is_trading_day(self):
        # 2026-04-17 是周五
        assert is_trading_day(date(2026, 4, 17)) is True

    def test_weekend_is_not_trading(self):
        assert is_trading_day(date(2026, 4, 18)) is False  # Sat
        assert is_trading_day(date(2026, 4, 19)) is False  # Sun

    def test_registered_holiday_is_not_trading(self):
        # 2026 元旦在内置表中
        assert is_trading_day(date(2026, 1, 1)) is False
        # 2026 春节假期区间样例
        assert is_trading_day(date(2026, 1, 27)) is False


class TestNextTradingDay:
    def test_advances_by_one_on_weekday(self):
        # Fri -> Mon
        assert next_trading_day(date(2026, 4, 17)) == date(2026, 4, 20)

    def test_skips_weekend(self):
        # Sat -> Mon
        assert next_trading_day(date(2026, 4, 18)) == date(2026, 4, 20)

    def test_skips_holiday(self):
        # 2026-01-30 周五是春节假期（假期表内），下一个交易日应跳过 2/1 周末到 2/2
        # 2/2 也是假期 -> 2/3
        nxt = next_trading_day(date(2026, 1, 29))
        assert nxt.weekday() < 5
        assert is_trading_day(nxt) is True


class TestLastTradingDayOnOrBefore:
    def test_today_is_trading(self):
        assert last_trading_day_on_or_before(date(2026, 4, 17)) == date(2026, 4, 17)

    def test_today_is_weekend(self):
        # Sat -> Fri
        assert last_trading_day_on_or_before(date(2026, 4, 18)) == date(2026, 4, 17)
        # Sun -> Fri
        assert last_trading_day_on_or_before(date(2026, 4, 19)) == date(2026, 4, 17)

    def test_today_is_holiday(self):
        # 元旦当天 -> 2025-12-31（若非周末）
        result = last_trading_day_on_or_before(date(2026, 1, 1))
        assert result < date(2026, 1, 1)
        assert is_trading_day(result) is True


class TestGetNextNTradingDays:
    def test_basic_five_days(self):
        # 从 2026-04-17（Fri）起，后 5 个交易日应为 04-20 至 04-24
        days = get_next_n_trading_days(date(2026, 4, 17), 5)
        assert days == [
            date(2026, 4, 20),
            date(2026, 4, 21),
            date(2026, 4, 22),
            date(2026, 4, 23),
            date(2026, 4, 24),
        ]

    def test_zero_days(self):
        assert get_next_n_trading_days(date(2026, 4, 17), 0) == []


class TestTradingDaysBetween:
    def test_count_excluding_start(self):
        # trading_days_between(start, end) 返回 (start, end] 内的交易日数。
        # 04-17 (Fri) → 04-24 (Fri)：排除 04-17，包含 04-20..04-24 = 5 个交易日
        assert trading_days_between(date(2026, 4, 17), date(2026, 4, 24)) == 5

    def test_reverse_is_zero(self):
        assert trading_days_between(date(2026, 4, 24), date(2026, 4, 17)) == 0


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
