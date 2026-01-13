import os
import types
import pandas as pd


def test_fund_flow_fallback_graceful(monkeypatch):
    """Simulate akshare failures to ensure fetch_fund_flow_daily returns empty dataframe (not exception)."""
    from app import data_source as ds

    # Force disable real network by mocking akshare functions to raise
    class DummyAk:
        def stock_individual_fund_flow(self, stock: str):  # type: ignore
            raise RuntimeError("simulated primary failure")
        def stock_individual_fund_flow_rank(self, indicator: str = "今日"):
            raise RuntimeError("simulated rank failure")
    dummy = DummyAk()
    monkeypatch.setitem(os.environ, "FUND_FLOW_DISABLE", "false")

    # monkeypatch import inside function scope: replace akshare module attributes via sys.modules injection
    import sys
    ak_mod = types.ModuleType("akshare")
    ak_mod.stock_individual_fund_flow = dummy.stock_individual_fund_flow  # type: ignore
    ak_mod.stock_individual_fund_flow_rank = dummy.stock_individual_fund_flow_rank  # type: ignore
    sys.modules['akshare'] = ak_mod

    df = ds.fetch_fund_flow_daily("300251.SZ", include_today_rank=True)
    # Should not raise and should be a DataFrame with defined columns
    assert isinstance(df, pd.DataFrame)
    assert set(df.columns) == {
        'symbol','trade_date','main_net','main_ratio','super_net','super_ratio',
        'large_net','large_ratio','medium_net','medium_ratio','small_net','small_ratio'
    }
    # Since all fallbacks failed, expect empty dataframe
    assert df.empty
