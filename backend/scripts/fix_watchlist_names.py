#!/usr/bin/env python3
"""
Fix mojibake in watchlist names by refreshing from Akshare code->name mapping.
- Uses stock_zh_a_spot_em first; falls back to stock_info_a_code_name.
- Updates watchlist.name when different or empty.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import SessionLocal, init_database
from app.models import Watchlist
from sqlalchemy import select


def load_code_name_map():
    import akshare as ak
    mapping = {}
    try:
        df = ak.stock_zh_a_spot_em()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                code = str(row.get('代码') or '').strip()
                name = str(row.get('名称') or '').strip()
                if code and name:
                    mapping[code] = name
    except Exception as e:
        print(f"Primary mapping failed: {e}")
    # Fallback
    if not mapping:
        try:
            df2 = ak.stock_info_a_code_name()
            if df2 is not None and not df2.empty:
                code_col = 'code' if 'code' in df2.columns else '证券代码'
                name_col = 'name' if 'name' in df2.columns else '证券简称'
                for _, row in df2.iterrows():
                    code = str(row.get(code_col) or '').strip()
                    name = str(row.get(name_col) or '').strip()
                    if code and name:
                        mapping[code] = name
        except Exception as e:
            print(f"Fallback mapping failed: {e}")
    return mapping


def main():
    init_database()
    mapping = load_code_name_map()
    if not mapping:
        print("No mapping available; aborting.")
        return
    updated = 0
    with SessionLocal() as session:
        watches = session.execute(select(Watchlist)).scalars().all()
        for w in watches:
            base = w.symbol.replace('.SH','').replace('.SZ','')
            new_name = mapping.get(base)
            if new_name and new_name != w.name:
                print(f"Update {w.symbol}: '{w.name}' -> '{new_name}'")
                w.name = new_name
                updated += 1
        session.commit()
    print(f"Done. Updated {updated} watchlist names.")


if __name__ == '__main__':
    main()
