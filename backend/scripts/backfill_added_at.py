#!/usr/bin/env python3
"""
Backfill watchlist.added_at using the earliest available price trade_date per symbol.
- If no price history found, keep current added_at.
"""
import sys
from datetime import datetime
from sqlalchemy import select, text

# Ensure app import path
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import SessionLocal, init_database
from app.models import Watchlist


def main():
    init_database()
    updated = 0
    with SessionLocal() as session:
        watches = session.execute(select(Watchlist)).scalars().all()
        for w in watches:
            # Find earliest price date
            row = session.execute(
                text(
                    "SELECT trade_date FROM prices_daily WHERE symbol=:s ORDER BY trade_date ASC LIMIT 1"
                ),
                {"s": w.symbol},
            ).first()
            if row and row[0]:
                # Only update if added_at is None or after earliest date
                td = row[0]
                if not getattr(w, 'added_at', None) or (w.added_at and w.added_at.date() > td):
                    w.added_at = datetime.combine(td, datetime.min.time())
                    updated += 1
        session.commit()
    print(f"Backfill done. Updated {updated} rows.")


if __name__ == "__main__":
    main()
