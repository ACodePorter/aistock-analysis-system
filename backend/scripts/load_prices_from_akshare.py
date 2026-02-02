"""Fetch recent daily prices via akshare and insert into Postgres prices_daily table.
Run from repository root in same environment as backend.
"""
import sys
sys.path.insert(0, r'd:/workspace/mpj/aistock-full-project/backend')
from app.data.data_source import fetch_daily, ak
from app.core.db import engine
from sqlalchemy import text
import pandas as pd

SYMBOLS = ['600519.SH','300750.SZ','601318.SH']

def upsert_prices_for_symbol(sym: str, days: int = 180):
    print('Fetching', sym)
    # Use ak.stock_zh_a_hist directly to avoid DATA_SOURCE fallback issues
    base = sym.replace('.SH','').replace('.SZ','')
    try:
        df = ak.stock_zh_a_hist(symbol=base, period='daily', adjust='qfq')
    except Exception as e:
        print('akshare fetch failed for', sym, e)
        df = None
    # normalize columns similar to fetch_daily_akshare
    if df is not None and not df.empty:
        df.columns = [str(c).strip().replace('\n','').replace('\r','') for c in df.columns]
        rename_map = {
            '日期': 'trade_date',
            '开盘': 'open',
            '收盘': 'close',
            '最高': 'high',
            '最低': 'low',
            '成交量': 'vol',
            '成交额': 'amount',
            '涨跌幅': 'pct_chg',
        }
        df = df.rename(columns=rename_map)
        if 'trade_date' in df.columns:
            df['trade_date'] = pd.to_datetime(df['trade_date'], errors='coerce').dt.date
        for col in ['open','high','low','close','pct_chg','amount']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            else:
                df[col] = None
        df['symbol'] = sym
        df = df[['symbol','trade_date','open','high','low','close','pct_chg','vol','amount']]
    if df is None or df.empty:
        print('No data fetched for', sym)
        return 0
    # ensure trade_date is datetime.date
    df = df.sort_values('trade_date')
    tail = df.tail(days)
    # load existing dates
    start = tail['trade_date'].min()
    with engine.begin() as conn:
        existing = conn.execute(text("SELECT trade_date FROM prices_daily WHERE symbol=:sym AND trade_date >= :start"), {"sym": sym, "start": start}).fetchall()
        existing_dates = set(r[0] for r in existing)
        to_insert = []
        for r in tail.itertuples():
            if r.trade_date in existing_dates:
                continue
            to_insert.append({
                'symbol': sym,
                'trade_date': r.trade_date,
                'open': float(r.open) if getattr(r, 'open', None) is not None else None,
                'high': float(r.high) if getattr(r, 'high', None) is not None else None,
                'low': float(r.low) if getattr(r, 'low', None) is not None else None,
                'close': float(r.close) if getattr(r, 'close', None) is not None else None,
                'pct_chg': float(r.pct_chg) if getattr(r, 'pct_chg', None) is not None else None,
                'vol': int(r.vol) if getattr(r, 'vol', None) is not None else None,
                'amount': float(r.amount) if getattr(r, 'amount', None) is not None else None,
            })
        if to_insert:
            conn.execute(text(
                "INSERT INTO prices_daily (symbol, trade_date, open, high, low, close, pct_chg, vol, amount) VALUES (:symbol, :trade_date, :open, :high, :low, :close, :pct_chg, :vol, :amount)"
            ), to_insert)
        return len(to_insert)

if __name__ == '__main__':
    total = 0
    for s in SYMBOLS:
        n = upsert_prices_for_symbol(s, days=180)
        print(f'Inserted {n} rows for {s}')
        total += n
    print('Total inserted:', total)
