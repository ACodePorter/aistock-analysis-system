import sys
import os
from sqlalchemy import select, func
from datetime import date

# Ensure backend import path
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, repo_root)

from app.db import SessionLocal
from app.models import PriceDaily, Watchlist


def main():
    latest = {}
    with SessionLocal() as session:
        watches = session.execute(select(Watchlist).where(Watchlist.enabled == True)).scalars().all()
        for w in watches:
            d = session.execute(
                select(func.max(PriceDaily.trade_date)).where(PriceDaily.symbol == w.symbol)
            ).scalar()
            latest[w.symbol] = d

    print("Latest trade_date per symbol:")
    for sym, d in latest.items():
        print(f"  {sym}: {d}")
    mx = max([d for d in latest.values() if d is not None], default=None)
    print(f"Max latest date: {mx}")
    print(f"Today: {date.today()}")


if __name__ == "__main__":
    sys.exit(main())
