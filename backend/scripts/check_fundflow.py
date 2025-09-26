import os
import sys
from sqlalchemy import select, func
from datetime import date

# Ensure backend import path
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, repo_root)

from app.db import SessionLocal, init_database
from app.models import FundFlowDaily, Watchlist

def main():
    # Ensure DB schema is initialized (idempotent)
    try:
        init_database()
    except Exception as e:
        print(f"DB init failed before check: {e}")
    with SessionLocal() as session:
        latest = session.execute(select(func.max(FundFlowDaily.trade_date))).scalar()
        print(f"Latest fundflow trade_date: {latest}")
        watches = session.execute(select(Watchlist).where(Watchlist.enabled == True)).scalars().all()
        for w in watches:
            d = session.execute(select(func.max(FundFlowDaily.trade_date)).where(FundFlowDaily.symbol == w.symbol)).scalar()
            print(f"  {w.symbol}: {d}")
        print(f"Today: {date.today()}")

if __name__ == "__main__":
    sys.exit(main())
