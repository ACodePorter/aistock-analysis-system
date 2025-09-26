import argparse
import json
from datetime import datetime
from typing import Optional, Dict, Any

# Third-party libs
import httpx


def fetch_eastmoney_eod(symbol: str, date: str) -> Dict[str, Any]:
    """Eastmoney EOD (historical) via push2his daykline funds flow"""
    sym = symbol.upper()
    base = sym.replace('.SH','').replace('.SZ','')
    mk = '1' if sym.endswith('.SH') else '0'
    url = 'https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get'
    params = {
        'secid': f'{mk}.{base}',
        'fields1': 'f1,f2,f3,f7',
        'fields2': 'f51,f52,f53,f54,f55,f56',  # date, main, super, large, medium, small
        'klt': '103',  # daily
        'lmt': '0',
    }
    out = {'source': 'eastmoney.push2his', 'ok': False}
    try:
        with httpx.Client(timeout=6.0) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            j = r.json()
            data = j.get('data') if isinstance(j, dict) else None
            klines = data.get('klines') if data else None
            if not isinstance(klines, list):
                out['error'] = 'no klines'
                return out
            target = None
            for item in klines:
                if isinstance(item, str) and item.startswith(date):
                    target = item
                    break
            if not target:
                out['error'] = 'date not found'
                return out
            parts = target.split(',')
            def _num(i):
                try:
                    return float(parts[i]) if len(parts) > i and parts[i] != '' else None
                except Exception:
                    return None
            out.update({
                'ok': True,
                'trade_date': parts[0],
                'main_net': _num(1),
                'super_net': _num(2),
                'large_net': _num(3),
                'medium_net': _num(4),
                'small_net': _num(5),
                'unit': 'yuan',
            })
            return out
    except Exception as e:
        out['error'] = str(e)
        return out


def fetch_sina_eod(symbol: str, date: str) -> Dict[str, Any]:
    """Sina daily moneyflow (assumed net amount in 10k yuan)"""
    sym = symbol.upper()
    base = sym.replace('.SH','').replace('.SZ','')
    pre = 'sh' if sym.endswith('.SH') else 'sz'
    sina_symbol = f'{pre}{base}'
    url = 'http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssi_sshd_by_day'
    params = {'symbol': sina_symbol, 'days': '90'}
    out = {'source': 'sina.moneyflow', 'ok': False}
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.get(url, params=params)
            if r.status_code != 200:
                out['error'] = f'HTTP {r.status_code}'
                return out
            try:
                arr = r.json()
            except Exception:
                import json as _json
                arr = _json.loads(r.text)
            if not isinstance(arr, list):
                out['error'] = 'unexpected payload'
                return out
            row = None
            for it in arr:
                d = str(it.get('date')) if isinstance(it, dict) else None
                if d == date:
                    row = it
                    break
            if not row:
                out['error'] = 'date not found'
                return out
            raw = row.get('netAmount')  # often in 10k yuan
            try:
                val_yuan = float(raw) * 1e4 if raw is not None else None
            except Exception:
                val_yuan = None
            out.update({
                'ok': True,
                'trade_date': date,
                'net_amount_assumed': val_yuan,
                'unit': 'yuan',
                'raw': raw,
                'raw_unit': '10k yuan (assumed)',
            })
            return out
    except Exception as e:
        out['error'] = str(e)
        return out


def fetch_akshare_history(symbol: str, date: str) -> Dict[str, Any]:
    out = {'source': 'akshare.history', 'ok': False}
    try:
        import akshare as ak
        sym = symbol.upper()
        base = sym.replace('.SH','').replace('.SZ','')
        df = ak.stock_individual_fund_flow(stock=base)
        if df is None or df.empty:
            out['error'] = 'empty'
            return out
        date_col = '日期' if '日期' in df.columns else ('date' if 'date' in df.columns else None)
        vcol = None
        for c in ['主力净流入-净额','今日主力净流入-净额','main_net']:
            if c in df.columns:
                vcol = c
                break
        if not date_col or not vcol:
            out['error'] = 'columns missing'
            return out
        row = df[df[date_col].astype(str) == date]
        if row is None or row.empty:
            out['error'] = 'date not found'
            return out
        raw = row.iloc[0][vcol]
        try:
            val_yuan = float(raw) * 1e4 if raw is not None else None
        except Exception:
            val_yuan = None
        out.update({
            'ok': True,
            'trade_date': date,
            'main_net': val_yuan,
            'unit': 'yuan',
            'raw': raw,
            'raw_unit': '10k yuan',
        })
        return out
    except Exception as e:
        out['error'] = str(e)
        return out


def fetch_api_diagnostics(base_url: str, symbol: str, date: str) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/fundflow/diagnostics"
    params = {'symbol': symbol, 'date': date}
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            return {'source': 'api.diagnostics', 'ok': True, 'data': r.json()}
    except Exception as e:
        return {'source': 'api.diagnostics', 'ok': False, 'error': str(e)}


def main():
    parser = argparse.ArgumentParser(description='Compare fund flow across multiple sources')
    parser.add_argument('--symbol', required=True, help='e.g., 300251.SZ')
    parser.add_argument('--date', required=True, help='YYYY-MM-DD (trading day)')
    parser.add_argument('--api', default='http://localhost:8000', help='Backend base URL to call diagnostics (optional)')
    args = parser.parse_args()

    sym = args.symbol.upper()
    date = args.date
    try:
        datetime.strptime(date, '%Y-%m-%d')
    except ValueError:
        raise SystemExit('date must be YYYY-MM-DD')

    results = {
        'symbol': sym,
        'date': date,
        'akshare_history': fetch_akshare_history(sym, date),
        'eastmoney_eod': fetch_eastmoney_eod(sym, date),
        'sina_eod': fetch_sina_eod(sym, date),
        'api_diagnostics': fetch_api_diagnostics(args.api, sym, date),
    }
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
