import os
import sys
from datetime import date, timedelta
import pandas as pd
from sqlalchemy import select

# Ensure backend import path
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, repo_root)

from app.db import SessionLocal, init_database
from app.models import Watchlist, FundFlowDaily
from app.data_source import fetch_fund_flow_daily
from sqlalchemy.dialects.postgresql import insert as pg_insert

def backfill_symbol(session, symbol: str, days_back: int = 365*3):
    start_date = (date.today() - timedelta(days=days_back)).strftime("%Y%m%d")
    df = fetch_fund_flow_daily(symbol, start_date=start_date)
    if df.empty:
        print(f"- {symbol}: no fund flow rows")
        return 0
    n = 0
    for _, r in df.iterrows():
        stmt = pg_insert(FundFlowDaily).values(
            symbol=r["symbol"],
            trade_date=r["trade_date"],
            main_net=r.get("main_net"),
            main_ratio=r.get("main_ratio"),
            super_net=r.get("super_net"),
            super_ratio=r.get("super_ratio"),
            large_net=r.get("large_net"),
            large_ratio=r.get("large_ratio"),
            medium_net=r.get("medium_net"),
            medium_ratio=r.get("medium_ratio"),
            small_net=r.get("small_net"),
            small_ratio=r.get("small_ratio"),
        ).on_conflict_do_nothing(index_elements=["symbol","trade_date"])
        session.execute(stmt)
        n += 1
    session.commit()
    print(f"- {symbol}: upserted {n} fundflow rows")
    return n

def main():
    only = os.getenv("ONLY", "").strip()
    only_syms = [s.strip() for s in only.split(",") if s.strip()] if only else None
    # Ensure DB schema is initialized (idempotent)
    try:
        init_database()
    except Exception as e:
        print(f"DB init failed before backfill: {e}")
    with SessionLocal() as session:
        watches = session.execute(select(Watchlist).where(Watchlist.enabled == True)).scalars().all()
        total = 0
        for w in watches:
            if only_syms and w.symbol not in only_syms:
                continue
            total += backfill_symbol(session, w.symbol)
        print(f"Done. Total fundflow rows attempted: {total}")

if __name__ == "__main__":
    sys.exit(main())
