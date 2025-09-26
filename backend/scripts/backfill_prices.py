import os
import sys
from datetime import date, timedelta
import pandas as pd
from sqlalchemy import select, func

# Ensure backend import path
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, repo_root)

from app.db import SessionLocal, engine
from app.models import Watchlist, PriceDaily
from app.data_source import fetch_daily


def get_last_trade_date(session, symbol: str):
    row = session.execute(
        select(func.max(PriceDaily.trade_date)).where(PriceDaily.symbol == symbol)
    ).scalar()
    return row


def backfill_symbol(session, symbol: str, days_back: int = 365*3):
    # decide start date: last date + 1, or days_back
    last = get_last_trade_date(session, symbol)
    if last:
        start_date = (last + timedelta(days=1)).strftime("%Y%m%d")
    else:
        start_date = (date.today() - timedelta(days=days_back)).strftime("%Y%m%d")

    df = fetch_daily(symbol, start_date=start_date)
    if df.empty:
        print(f"- {symbol}: no new rows")
        return 0
    upserts = 0
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    for _, row in df.iterrows():
        stmt = pg_insert(PriceDaily).values(
            symbol=row["symbol"],
            trade_date=row["trade_date"],
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            pct_chg=row.get("pct_chg"),
            vol=(int(row["vol"]) if pd.notna(row["vol"]) else None),
            amount=row.get("amount"),
        ).on_conflict_do_nothing(index_elements=["symbol", "trade_date"])
        session.execute(stmt)
        upserts += 1
    session.commit()
    print(f"- {symbol}: upserted {upserts} rows (from {start_date})")
    return upserts


def main():
    # Optional: filter specific symbols via env
    only = os.getenv("ONLY", "").strip()
    only_syms = [s.strip() for s in only.split(",") if s.strip()] if only else None

    with SessionLocal() as session:
        watches = session.execute(select(Watchlist).where(Watchlist.enabled == True)).scalars().all()
        total = 0
        for w in watches:
            if only_syms and w.symbol not in only_syms:
                continue
            total += backfill_symbol(session, w.symbol)
        print(f"Done. Total new rows attempted: {total}")


if __name__ == "__main__":
    sys.exit(main())
