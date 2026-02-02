"""Extended AKShare / Tushare probe

Runs a set of AKShare functions (news/notice/daily) across a list of symbols,
attempts Tushare pro endpoints when `TUSHARE_TOKEN` is available, and saves
raw responses and errors to `temp/akshare_probe_results.json`.

Usage: python backend/scripts/akshare_probe_extended.py
"""
import os
import json
import traceback
from datetime import datetime

import akshare as ak


def safe_to_serial(obj):
    # convert common numpy / pandas types to serializable; otherwise use repr
    try:
        import pandas as pd
        if isinstance(obj, pd.DataFrame):
            return obj.to_dict('records')
    except Exception:
        pass
    try:
        import numpy as np
        if isinstance(obj, (np.integer, np.floating)):
            return obj.item()
    except Exception:
        pass
    # fallback
    return repr(obj)


def probe_symbol(symbol, results, tushare_pro=None):
    entry = {'symbol': symbol, 'ts': datetime.utcnow().isoformat() + 'Z', 'results': {}}

    funcs = {
        'stock_news_em': getattr(ak, 'stock_news_em', None),
        'stock_notice_report': getattr(ak, 'stock_notice_report', None),
        'stock_notice_cninfo': getattr(ak, 'stock_notice_cninfo', None),
        'stock_zh_a_daily': getattr(ak, 'stock_zh_a_daily', None),
    }

    for name, fn in funcs.items():
        try:
            if fn is None:
                entry['results'][name] = {'status': 'missing'}
                continue
            # many ak functions expect different parameter names; try common variants
            try:
                res = fn(symbol)
            except TypeError:
                try:
                    res = fn(symbol, adjust=None)
                except Exception:
                    res = fn(symbol)

            entry['results'][name] = {'status': 'ok', 'value': safe_to_serial(res)}
        except Exception as e:
            entry['results'][name] = {'status': 'error', 'error': repr(e), 'trace': traceback.format_exc()}

    # try tushare pro endpoints if available
    if tushare_pro is not None:
        ts_entry = {}
        pro_names = ['announcement', 'announcements', 'query_announcement', 'query_ann', 'news']
        for pname in pro_names:
            try:
                if hasattr(tushare_pro, pname):
                    method = getattr(tushare_pro, pname)
                    try:
                        df = method(ts_code=symbol)
                    except TypeError:
                        try:
                            df = method(code=symbol)
                        except TypeError:
                            df = method(symbol)
                    ts_entry[pname] = {'status': 'ok', 'value': safe_to_serial(df)}
            except Exception as e:
                ts_entry[pname] = {'status': 'error', 'error': repr(e), 'trace': traceback.format_exc()}
        entry['results']['tushare_pro'] = ts_entry

    results.append(entry)


def main():
    symbols = [
        '600519', '000001', '000002', '300750', '002594', '600036', '601318', '601166', '000333',
        '002475', '002714', '600276', '000651', '601888', '002714.SZ', '600519.SH', 'sh600519', 'sz000001',
        '600000', '300015', '000858', '600887', '601229', '601288', '601939', '601699', '601869', '601988',
        '603259', '603019', '002230', '002142', '300122', '300760', '000725', '600104', '600900', '600690',
        '600703', '002460', '000725.SZ', 'sz000725', '300496', '300015.SZ', '600036.SH', 'sh600036',
        '002230.SZ', '000333.SZ', '600519.SHA', '002792', '300059'
    ]

    results = []

    tushare_pro = None
    token = os.getenv('TUSHARE_TOKEN')
    if token:
        try:
            import tushare as ts
            tushare_pro = ts.pro_api(token)
        except Exception:
            tushare_pro = None

    for s in symbols:
        print('Probing', s)
        probe_symbol(s, results, tushare_pro=tushare_pro)

    os.makedirs('temp', exist_ok=True)
    out_path = os.path.join('temp', 'akshare_probe_results.json')

    def default_serializer(o):
        # datetimes, dates, numpy types
        try:
            import numpy as np
            if isinstance(o, (np.integer, np.floating)):
                return o.item()
        except Exception:
            pass
        if hasattr(o, 'isoformat'):
            return o.isoformat()
        try:
            return str(o)
        except Exception:
            return repr(o)

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({'generated': datetime.utcnow().isoformat() + 'Z', 'results': results}, f, ensure_ascii=False, indent=2, default=default_serializer)

    print('Saved probe results to', out_path)


if __name__ == '__main__':
    main()
