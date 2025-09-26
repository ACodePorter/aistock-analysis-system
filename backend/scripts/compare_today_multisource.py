import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import httpx


def _now_cn_date_str() -> str:
    # Asia/Shanghai or Asia/Taipei share the same clock; default to China for A-share
    return datetime.utcnow().astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d')


def _em_parts(symbol: str) -> Dict[str, str]:
    sym = symbol.upper()
    base = sym.replace('.SH', '').replace('.SZ', '')
    mk = '1' if sym.endswith('.SH') else '0'
    return {'secid': f'{mk}.{base}', 'code': base}


def fetch_eastmoney_push2_realtime(symbol: str) -> Dict[str, Any]:
    """Eastmoney push2 realtime snapshot with fund flow fields.
    f62: 主力净流入; f66: 超大单净流入; f69: 大单净流入; f72: 中单净流入; f75: 小单净流入; f48: 成交额(元)
    """
    p = _em_parts(symbol)
    url = 'https://push2.eastmoney.com/api/qt/stock/get'
    fields = [
        'f58',  # 名称
        'f57',  # 代码
        'f48',  # 成交额(元)
        'f62',  # 主力净流入
        'f66',  # 超大单净流入
        'f69',  # 大单净流入
        'f72',  # 中单净流入
        'f75',  # 小单净流入
        'f184', # 主力净占比
    ]
    params = {
        'fltt': '2',
        'invt': '2',
        'fields': ','.join(fields),
        'secid': p['secid'],
    }
    headers = {
        'Referer': 'https://quote.eastmoney.com/',
        'User-Agent': 'Mozilla/5.0',
    }
    out = {'source': 'eastmoney.push2.realtime', 'ok': False}
    try:
        with httpx.Client(timeout=8.0, headers=headers) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            j = r.json()
            data = j.get('data') if isinstance(j, dict) else None
            if not isinstance(data, dict):
                out['error'] = 'no data'
                return out
            def g(k):
                v = data.get(k)
                try:
                    return float(v) if v is not None else None
                except Exception:
                    return None
            out.update({
                'ok': True,
                'name': data.get('f58'),
                'code': data.get('f57'),
                'turnover_yuan': g('f48'),
                'main_net_yuan': g('f62'),
                'super_net_yuan': g('f66'),
                'large_net_yuan': g('f69'),
                'medium_net_yuan': g('f72'),
                'small_net_yuan': g('f75'),
                'main_ratio_pct': g('f184'),
                'unit': 'yuan',
                'ts': datetime.utcnow().isoformat() + 'Z',
            })
            return out
    except Exception as e:
        out['error'] = str(e)
        return out


def fetch_eastmoney_trends2_latest(symbol: str) -> Dict[str, Any]:
    """Eastmoney minute-level fund flow trends (latest point).
    Note: field mapping may change; we attempt best-effort parse.
    """
    p = _em_parts(symbol)
    url = 'https://push2his.eastmoney.com/api/qt/stock/fflow/trends2/get'
    params = {
        'secid': p['secid'],
        'fields1': 'f1,f2,f3,f7',
        'fields2': 'f51,f52,f53,f54,f55,f56',
    }
    headers = {
        'Referer': 'https://data.eastmoney.com/',
        'User-Agent': 'Mozilla/5.0',
    }
    out = {'source': 'eastmoney.push2his.trends2', 'ok': False}
    try:
        with httpx.Client(timeout=8.0, headers=headers) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            j = r.json()
            data = (j or {}).get('data')
            trends = (data or {}).get('trends')
            if not isinstance(trends, list) or not trends:
                out['error'] = 'no trends'
                return out
            last = trends[-1]
            if not isinstance(last, str):
                out['error'] = 'bad last'
                return out
            parts = last.split(',')
            # Heuristic mapping: f51: time, f52: 主力净流入, f53: 超大, f54: 大, f55: 中, f56: 小
            def num(i):
                try:
                    return float(parts[i]) if len(parts) > i and parts[i] != '' else None
                except Exception:
                    return None
            out.update({
                'ok': True,
                'time': parts[0] if parts else None,
                'main_net_yuan': num(1),
                'super_net_yuan': num(2),
                'large_net_yuan': num(3),
                'medium_net_yuan': num(4),
                'small_net_yuan': num(5),
                'unit': 'yuan',
            })
            return out
    except Exception as e:
        out['error'] = str(e)
        return out


def fetch_akshare_today_rank(symbol: str) -> Dict[str, Any]:
    """Akshare: today's per-stock fund flow rank table, filter by code.
    Returns values in 10k yuan; convert to yuan.
    """
    out = {'source': 'akshare.today_rank', 'ok': False}
    try:
        import akshare as ak
        df = ak.stock_individual_fund_flow_rank(indicator='今日')
        if df is None or df.empty:
            out['error'] = 'empty'
            return out
        # Columns commonly include: 代码, 名称, 今日主力净流入-净额, 今日超大单净流入-净额, 今日大单净流入-净额, 今日中单净流入-净额, 今日小单净流入-净额
        # Units are 10k yuan
        code_col = '代码' if '代码' in df.columns else 'code'
        row = df[df[code_col].astype(str) == symbol.replace('.SH','').replace('.SZ','')]
        if row is None or row.empty:
            out['error'] = 'symbol not found'
            return out
        def get_col(*names):
            for n in names:
                if n in df.columns:
                    return row.iloc[0].get(n)
            return None
        def to_yuan(v):
            try:
                return float(v) * 1e4 if v is not None else None
            except Exception:
                return None
        out.update({
            'ok': True,
            'name': get_col('名称','name'),
            'code': row.iloc[0].get(code_col),
            'main_net_yuan': to_yuan(get_col('今日主力净流入-净额','主力净流入-净额','main_net')),
            'super_net_yuan': to_yuan(get_col('今日超大单净流入-净额','超大单净流入-净额','super_net')),
            'large_net_yuan': to_yuan(get_col('今日大单净流入-净额','大单净流入-净额','large_net')),
            'medium_net_yuan': to_yuan(get_col('今日中单净流入-净额','中单净流入-净额','medium_net')),
            'small_net_yuan': to_yuan(get_col('今日小单净流入-净额','小单净流入-净额','small_net')),
            'unit': 'yuan',
        })
        return out
    except Exception as e:
        out['error'] = str(e)
        return out


def fetch_sina_realtime_quote(symbol: str) -> Dict[str, Any]:
    """Sina hq realtime: provides成交量(股) & 成交金额(元)."""
    sym = symbol.upper()
    base = sym.replace('.SH','').replace('.SZ','')
    pre = 'sh' if sym.endswith('.SH') else 'sz'
    url = f'http://hq.sinajs.cn/list={pre}{base}'
    headers = {
        'Referer': 'https://finance.sina.com.cn/',
        'User-Agent': 'Mozilla/5.0',
    }
    out = {'source': 'sina.hq.realtime', 'ok': False}
    try:
        with httpx.Client(timeout=6.0, headers=headers) as client:
            r = client.get(url)
            if r.status_code != 200:
                out['error'] = f'HTTP {r.status_code}'
                return out
            text = r.content.decode('gbk', errors='ignore')
            # var hq_str_sz300251="光线传媒,开盘,昨收,当前价,最高,最低,竞买价,竞卖价,成交量(股),成交金额(元),...";
            if '="' not in text:
                out['error'] = 'unexpected payload'
                return out
            s = text.split('="',1)[1]
            s = s.split('";',1)[0]
            parts = s.split(',')
            name = parts[0] if parts else None
            def num(i):
                try:
                    return float(parts[i]) if len(parts)>i and parts[i] not in ('','-') else None
                except Exception:
                    return None
            out.update({
                'ok': True,
                'name': name,
                'turnover_yuan': num(9),  # 成交金额(元)
                'volume_shares': num(8),  # 成交量(股)
                'unit': 'yuan',
            })
            return out
    except Exception as e:
        out['error'] = str(e)
        return out


def fetch_sina_moneyflow_eod(symbol: str, date: str) -> Dict[str, Any]:
    """Sina daily moneyflow JSONP tolerant parser; returns today's row if present.
    netAmount usually in 10k yuan -> convert to yuan.
    """
    sym = symbol.upper()
    base = sym.replace('.SH','').replace('.SZ','')
    pre = 'sh' if sym.endswith('.SH') else 'sz'
    url = 'http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssi_sshd_by_day'
    params = {'symbol': f'{pre}{base}', 'days': '90'}
    headers = {
        'Referer': 'https://vip.stock.finance.sina.com.cn/',
        'User-Agent': 'Mozilla/5.0',
    }
    out = {'source': 'sina.moneyflow.eod', 'ok': False}
    try:
        with httpx.Client(timeout=8.0, headers=headers) as client:
            r = client.get(url, params=params)
            if r.status_code != 200:
                out['error'] = f'HTTP {r.status_code}'
                return out
            text = r.text.strip()
            arr: Optional[List[Dict[str, Any]]] = None
            # Try JSON
            try:
                arr = r.json()
            except Exception:
                # Try to extract a JSON-like array from text
                l = text.find('[')
                rpos = text.rfind(']')
                if l != -1 and rpos != -1 and rpos > l:
                    blob = text[l:rpos+1]
                    try:
                        arr = json.loads(blob)
                    except Exception:
                        arr = None
            if not isinstance(arr, list):
                out['error'] = 'unexpected payload'
                return out
            row = None
            for it in arr:
                if isinstance(it, dict) and str(it.get('date')) == date:
                    row = it
                    break
            if not row:
                out['error'] = 'date not found'
                return out
            raw = row.get('netAmount')
            try:
                val_yuan = float(raw) * 1e4 if raw is not None else None
            except Exception:
                val_yuan = None
            out.update({
                'ok': True,
                'trade_date': date,
                'main_net_yuan': val_yuan,
                'unit': 'yuan',
                'raw': raw,
                'raw_unit': '10k yuan (assumed)',
            })
            return out
    except Exception as e:
        out['error'] = str(e)
        return out


def fmt_num(v: Optional[float]) -> str:
    if v is None:
        return ''
    # format to 2 decimals in 1e8 (亿)
    return f"{v/1e8:.2f}"


def print_table(rows: List[Dict[str, Any]]):
    cols = [
        'source', 'time/date', 'main_net(亿)', 'super(亿)', 'large(亿)', 'medium(亿)', 'small(亿)', 'turnover(亿)', 'notes'
    ]
    # Print as markdown table
    print('| ' + ' | '.join(cols) + ' |')
    print('|' + '|'.join(['---']*len(cols)) + '|')
    for r in rows:
        print('| ' + ' | '.join([
            str(r.get('source','')),
            str(r.get('time/date','')),
            fmt_num(r.get('main_net_yuan')),
            fmt_num(r.get('super_net_yuan')),
            fmt_num(r.get('large_net_yuan')),
            fmt_num(r.get('medium_net_yuan')),
            fmt_num(r.get('small_net_yuan')),
            fmt_num(r.get('turnover_yuan')),
            str(r.get('notes','')),
        ]) + ' |')


def main():
    parser = argparse.ArgumentParser(description='Compare TODAY intraday fund flow across multiple third-party sources')
    parser.add_argument('--symbol', default='300251.SZ', help='e.g., 300251.SZ')
    parser.add_argument('--date', default=_now_cn_date_str(), help='YYYY-MM-DD (default: today CN)')
    args = parser.parse_args()

    symbol = args.symbol.upper()
    date = args.date

    rows: List[Dict[str, Any]] = []

    em_rt = fetch_eastmoney_push2_realtime(symbol)
    rows.append({
        'source': em_rt.get('source'),
        'time/date': 'now',
        'main_net_yuan': em_rt.get('main_net_yuan'),
        'super_net_yuan': em_rt.get('super_net_yuan'),
        'large_net_yuan': em_rt.get('large_net_yuan'),
        'medium_net_yuan': em_rt.get('medium_net_yuan'),
        'small_net_yuan': em_rt.get('small_net_yuan'),
        'turnover_yuan': em_rt.get('turnover_yuan'),
        'notes': 'unit=yuan; f62/f66/f69/f72/f75 from push2' if em_rt.get('ok') else f"error: {em_rt.get('error')}",
    })

    em_tr = fetch_eastmoney_trends2_latest(symbol)
    rows.append({
        'source': em_tr.get('source'),
        'time/date': em_tr.get('time'),
        'main_net_yuan': em_tr.get('main_net_yuan'),
        'super_net_yuan': em_tr.get('super_net_yuan'),
        'large_net_yuan': em_tr.get('large_net_yuan'),
        'medium_net_yuan': em_tr.get('medium_net_yuan'),
        'small_net_yuan': em_tr.get('small_net_yuan'),
        'turnover_yuan': None,
        'notes': 'unit=yuan; minute-level cumulative' if em_tr.get('ok') else f"error: {em_tr.get('error')}",
    })

    ak_today = fetch_akshare_today_rank(symbol)
    rows.append({
        'source': ak_today.get('source'),
        'time/date': date,
        'main_net_yuan': ak_today.get('main_net_yuan'),
        'super_net_yuan': ak_today.get('super_net_yuan'),
        'large_net_yuan': ak_today.get('large_net_yuan'),
        'medium_net_yuan': ak_today.get('medium_net_yuan'),
        'small_net_yuan': ak_today.get('small_net_yuan'),
        'turnover_yuan': None,
        'notes': 'unit=yuan; Akshare 今日排行(10k->yuan)' if ak_today.get('ok') else f"error: {ak_today.get('error')}",
    })

    sina_rt = fetch_sina_realtime_quote(symbol)
    rows.append({
        'source': sina_rt.get('source'),
        'time/date': 'now',
        'main_net_yuan': None,
        'super_net_yuan': None,
        'large_net_yuan': None,
        'medium_net_yuan': None,
        'small_net_yuan': None,
        'turnover_yuan': sina_rt.get('turnover_yuan'),
        'notes': 'unit=yuan; quote turnover' if sina_rt.get('ok') else f"error: {sina_rt.get('error')}",
    })

    # Try to get today EOD from Sina if already published (may not be available intraday)
    sina_eod = fetch_sina_moneyflow_eod(symbol, date)
    rows.append({
        'source': sina_eod.get('source'),
        'time/date': date,
        'main_net_yuan': sina_eod.get('main_net_yuan'),
        'super_net_yuan': None,
        'large_net_yuan': None,
        'medium_net_yuan': None,
        'small_net_yuan': None,
        'turnover_yuan': None,
        'notes': 'unit=yuan; JSONP parsed' if sina_eod.get('ok') else f"error: {sina_eod.get('error')}",
    })

    print(f"Symbol: {symbol}  Date: {date}")
    print_table(rows)


if __name__ == '__main__':
    main()
