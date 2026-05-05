"""A 股交易日历统一工具。

集中管理节假日集合与交易日推导逻辑，供调度器（tasks/scheduler.py）、
报告接口（main.py get_full_report）、TaskManager 等共同调用，避免两侧
"仅跳周末 vs 含节假日"的不一致。

设计原则：
- 零外部依赖，只依赖标准库 datetime
- 节假日表按年份分桶维护；缺年份时退化为"仅跳周末"
- 函数签名稳定：传入 date，返回 date 或 bool；不做时区转换，上游负责
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable


_HOLIDAYS_2026: frozenset[date] = frozenset({
    date(2026, 1, 1),
    date(2026, 1, 26), date(2026, 1, 27), date(2026, 1, 28),
    date(2026, 1, 29), date(2026, 1, 30), date(2026, 2, 2),
})


_HOLIDAYS_BY_YEAR: dict[int, frozenset[date]] = {
    2026: _HOLIDAYS_2026,
}


def get_holidays(year: int) -> frozenset[date]:
    """返回指定年份的已知休市日集合（不含周末）。

    未登记年份返回空集合；上游仍会以周末判断兜底。
    """
    return _HOLIDAYS_BY_YEAR.get(year, frozenset())


def is_trading_day(d: date | None = None) -> bool:
    """判断给定日期是否为 A 股交易日。

    规则：
    1. 周末（周六/周日）= 非交易日
    2. 已登记节假日 = 非交易日
    3. 其它工作日 = 交易日
    """
    if d is None:
        d = date.today()
    if d.weekday() >= 5:
        return False
    if d in get_holidays(d.year):
        return False
    return True


def next_trading_day(d: date) -> date:
    """返回 d 之后第一个交易日（不含 d 自身）。"""
    cursor = d + timedelta(days=1)
    while not is_trading_day(cursor):
        cursor += timedelta(days=1)
    return cursor


def last_trading_day_on_or_before(d: date | None = None) -> date:
    """返回不晚于 d 的最近一个交易日（含 d）。"""
    if d is None:
        d = date.today()
    cursor = d
    while not is_trading_day(cursor):
        cursor -= timedelta(days=1)
    return cursor


def get_next_n_trading_days(start: date, n: int) -> list[date]:
    """从 start 之后（不含 start）开始取连续 n 个交易日。"""
    if n <= 0:
        return []
    out: list[date] = []
    cursor = start
    while len(out) < n:
        cursor += timedelta(days=1)
        if is_trading_day(cursor):
            out.append(cursor)
    return out


def iter_trading_days(start: date, end: date) -> Iterable[date]:
    """遍历 [start, end] 区间内的交易日（包含端点）。"""
    if start > end:
        return
    cursor = start
    while cursor <= end:
        if is_trading_day(cursor):
            yield cursor
        cursor += timedelta(days=1)


def trading_days_between(start: date, end: date) -> int:
    """计算 (start, end] 区间包含的交易日数（不含 start，含 end）。"""
    if end <= start:
        return 0
    return sum(1 for _ in iter_trading_days(start + timedelta(days=1), end))


__all__ = [
    "get_holidays",
    "is_trading_day",
    "next_trading_day",
    "last_trading_day_on_or_before",
    "get_next_n_trading_days",
    "iter_trading_days",
    "trading_days_between",
]
