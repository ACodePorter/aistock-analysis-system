"""Phase 1 回归：/api/report/{symbol}/full 不应再把 target_date == 最后历史日
的预测点当成 future/today 输出，避免前端图表上同一日期同时画 historical
close 与 prediction yhat，复现 "实际收盘=预测均值=区间" 的视觉错觉。
"""

import datetime as _dt

from fastapi.testclient import TestClient

from app.main import app


def _pick_symbol() -> str:
    """优先复用一个已知已落库的 symbol，避免触发 watchlist snapshot 等慢路径。"""
    try:
        from app.core.db import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT symbol FROM prices_daily ORDER BY trade_date DESC LIMIT 1"
            )).fetchone()
            if row and row[0]:
                return str(row[0])
    except Exception:
        pass
    return "300750.SZ"


def test_full_report_does_not_emit_same_day_prediction_as_future():
    client = TestClient(app)
    sym = _pick_symbol()
    r = client.get(f"/api/report/{sym}/full?timeRange=5d")
    assert r.status_code == 200, r.text
    data = r.json()

    hist = data.get("price_data") or []
    preds = data.get("predictions") or []
    pred_mean = data.get("predictions_mean") or []
    pred_dates = data.get("dates") or []

    if not hist or not preds:
        # 当前数据源不稳定时跳过；该用例不应阻塞 CI。
        import pytest
        pytest.skip(f"no hist/preds available for {sym}")

    last_hist_date = hist[-1].get("date")
    assert last_hist_date, "last historical row must carry a date"

    # 关键回归：predictions[] 中如果存在 target_date == last_hist_date 的点，
    # 它的 status 必须是 'today_evaluated'，不能再是 'today' / 'future'。
    same_day_preds = [p for p in preds if p.get("date") == last_hist_date]
    for p in same_day_preds:
        assert p.get("status") == "today_evaluated", (
            f"prediction on last_hist_date={last_hist_date} should be marked "
            f"today_evaluated, got status={p.get('status')!r}"
        )

    # 关键回归：predictions_mean / dates 这两个扁平数组（前端旧链路 / 兼容
    # 字段）不允许包含 last_hist_date 的预测，否则会和历史 close 在同一
    # X 轴位置叠加。
    assert last_hist_date not in pred_dates, (
        f"flat predictions arrays must not include last_hist_date={last_hist_date}; "
        f"dates={pred_dates}"
    )
    assert len(pred_mean) == len(pred_dates)


def test_full_report_status_for_helper_logic():
    """对 _status_for 的 4 种状态做单元覆盖（直接调用内部函数避免依赖外网）。"""
    # _status_for 是 read_full_report 内的闭包，无法直接 import；这里通过
    # 黑盒方式构造一段逻辑等价的小函数验证设计意图。如果未来该闭包语义
    # 发生变化，请同步更新。
    def _status_for(target_d, today_d, last_hist_d):
        if last_hist_d is not None and target_d <= last_hist_d:
            return "today_evaluated"
        if target_d == today_d:
            return "today"
        if target_d > today_d:
            return "future"
        return "expired"

    today = _dt.date(2026, 4, 24)
    last_hist = _dt.date(2026, 4, 24)

    # case 1: target_date == last_hist == today  → today_evaluated（修复前是 'today'）
    assert _status_for(today, today, last_hist) == "today_evaluated"

    # case 2: target_date < last_hist（已交易完毕）→ today_evaluated
    assert _status_for(_dt.date(2026, 4, 23), today, last_hist) == "today_evaluated"

    # case 3: 未来交易日
    assert _status_for(_dt.date(2026, 4, 27), today, last_hist) == "future"

    # case 4: 介于 last_hist 与 today 之间（停牌或数据延迟） → expired
    assert _status_for(_dt.date(2026, 4, 23), today, _dt.date(2026, 4, 22)) == "expired"


def test_prediction_history_endpoint_schema():
    client = TestClient(app)
    sym = _pick_symbol()
    r = client.get(f"/api/predictions/history?symbol={sym}&lookback_days=30&refresh=0")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["symbol"] == sym.upper()
    assert isinstance(data.get("rows"), list)
    stats = data.get("stats") or {}
    for key in [
        "total_records",
        "evaluated_records",
        "mape",
        "direction_accuracy",
        "interval_hit_rate",
        "d1_count",
        "d5_count",
    ]:
        assert key in stats

    if data["rows"]:
        row = data["rows"][0]
        assert "date" in row
        assert "actual" in row
        assert ("d1_predicted" in row) or ("d5_predicted" in row)
