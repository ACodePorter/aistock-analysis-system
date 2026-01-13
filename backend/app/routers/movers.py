from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple
import json
from decimal import Decimal, InvalidOperation
import logging

from ..core.db import SessionLocal, engine
from ..core.models import NewsArticle, Watchlist, Stock
from ..news.llm_processor import LLMNewsProcessor

router = APIRouter(prefix="/api/movers", tags=["movers"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _run_query(db: Session, sql: str, params: Dict[str, Any]):
    return db.execute(text(sql), params).mappings().all()

# =====================  纯实时（无数据库依赖）接口  ===================== #
_live_insight_cache = {"ts": 0.0, "ttl": 10, "data": None}

def _fetch_live_insight_snapshot(limit: int, exchange: str, provider: str, allow_mock: bool = True):
    """执行一次实时全市场抓取 + 解析（不缓存）。

    回退策略：akshare(重试1次)->eastmoney(分页)->mock 占位
    返回：包含 gainers/losers 及 all_valid（按涨幅降序全量）以便缓存派生不同 limit/exchange。
    """
    import time as _time
    ak_error: str | None = None
    df = None
    last_provider = None
    provider_chain: list[dict] = []
    import os as _os
    if _os.getenv('DISABLE_LIVE_MOCK', '').lower() in ('1','true','yes','y'):  # 全局禁用 mock
        allow_mock = False
    disable_tencent = _os.getenv('DISABLE_TENCENT_LIVE','').lower() in ('1','true','yes','y')

    # 0) 直接 Top/Bottom 快速源 (Sina) - 仅在 limit<=120 时尝试，可快速返回真实涨跌幅榜
    if provider in ("auto", "sina", "sina_top") and limit <= 120:
        try:
            import requests as _rq
            base_url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
            # 涨幅榜 asc=0, 跌幅榜 asc=1 (按 changepercent 排序)
            params_up = {"node":"hs_a","sort":"changepercent","asc":0,"num":limit,"page":1}
            params_dn = {"node":"hs_a","sort":"changepercent","asc":1,"num":limit,"page":1}
            headers = {"User-Agent":"Mozilla/5.0"}
            up_r = _rq.get(base_url, params=params_up, timeout=8, headers=headers)
            dn_r = _rq.get(base_url, params=params_dn, timeout=8, headers=headers)
            if up_r.status_code == 200 and dn_r.status_code == 200:
                # 新浪返回可能是 JS 风格 JSON，需要 eval 风险；但多数情况下是标准 JSON 数组字符串
                import json as _json
                try:
                    up_list = up_r.json()
                except Exception:
                    # fallback simple parse
                    up_list = _json.loads(up_r.text.replace("'", '"')) if up_r.text.startswith('[') else []
                try:
                    dn_list = dn_r.json()
                except Exception:
                    dn_list = _json.loads(dn_r.text.replace("'", '"')) if dn_r.text.startswith('[') else []
                def _norm(lst):
                    out = []
                    abnormal_records = []
                    for it in lst or []:
                        if not isinstance(it, dict):
                            continue
                        code = it.get('code') or it.get('symbol') or ''
                        if not code:
                            continue
                        # 形如 sh600000 / sz000001
                        if code.startswith('sh') or code.startswith('sz'):
                            raw = code[2:]
                        else:
                            raw = code
                        suffix = '.SH' if raw.startswith(('6','5','9')) else '.SZ'
                        sym = raw + suffix
                        if exchange and exchange.upper() in ('SH','SZ') and not sym.endswith('.'+exchange.upper()):
                            continue
                        try:
                            pct = float(it.get('changepercent'))
                        except Exception:
                            pct = None
                        try:
                            price = float(it.get('trade')) if it.get('trade') not in (None,'') else None
                        except Exception:
                            price = None
                        try:
                            change_v = float(it.get('pricechange')) if it.get('pricechange') not in (None,'') else None
                        except Exception:
                            change_v = None
                        nm = it.get('name') or it.get('symbol') or sym
                        is_new_stock = isinstance(nm, str) and nm.startswith('N')
                        abnormal = pct is not None and abs(pct) > 22
                        if abnormal:
                            abnormal_records.append({
                                'symbol': sym,
                                'name': nm,
                                'pct_chg': pct,
                                'provider': 'sina_top',
                                'raw_row': it
                            })
                        out.append({
                            'symbol': sym,
                            'name': nm,
                            'pct_chg': pct,
                            'change': change_v,
                            'price': price,
                            'abnormal_pct': abnormal
                        })
                    return out, abnormal_records
                up_norm, up_abnormal_records = _norm(up_list)
                dn_norm, dn_abnormal_records = _norm(dn_list)
                abnormal_total = up_abnormal_records + dn_abnormal_records
                if up_norm and dn_norm:
                    provider_chain.append({'provider':'sina_top','status':'ok','up_rows':len(up_norm),'down_rows':len(dn_norm),'abnormal_pct_count': len(abnormal_total)})
                    all_valid = up_norm + dn_norm
                    uniq = {}
                    for r in all_valid:
                        if isinstance(r.get('pct_chg'), (int,float)):
                            uniq[r['symbol']] = r
                    uniq_list = list(uniq.values())
                    uniq_list.sort(key=lambda x: x['pct_chg'], reverse=True)
                    return {
                        'source':'live',
                        'generated_at': datetime.utcnow().isoformat(),
                        'universe_size': len(uniq_list),
                        'parsed_rows': len(uniq_list),
                        'valid_rows': len(uniq_list),
                        'filtered_rows': len(uniq_list),
                        'gainers': up_norm[:limit],
                        'losers': dn_norm[:limit],
                        'provider': 'sina_top',
                        'ak_error': None,
                        'mock': False,
                        'all_valid': uniq_list,
                        'provider_chain': provider_chain,
                        'quality': 'top_only',
                        'partial_reason': 'top_lists_only',
                        'diagnostics': {
                            'abnormal_pct_records': abnormal_total
                        }
                    }
                else:
                    provider_chain.append({'provider':'sina_top','status':'empty'})
        except Exception as _se:  # noqa: BLE001
            provider_chain.append({'provider':'sina_top','status':'error','error': str(_se)})

    # 1) akshare 重试
    if provider in ("auto", "akshare"):
        for _attempt in range(2):
            try:
                import akshare as ak  # type: ignore
                df = ak.stock_zh_a_spot_em()
                last_provider = "akshare"
                if df is not None and not df.empty:
                    provider_chain.append({'provider':'akshare','attempt':_attempt+1,'status':'ok','rows': int(df.shape[0])})
                    break
            except Exception as e:  # noqa: BLE001
                ak_error = str(e)
                df = None
                provider_chain.append({'provider':'akshare','attempt':_attempt+1,'status':'error','error': ak_error})
            _time.sleep(0.4)

    # 2) eastmoney fallback
    if (df is None or (hasattr(df, "empty") and df.empty)) and provider in ("auto", "eastmoney", "eastmoney_only"):
        import requests
        import random as _rnd
        all_rows: list[dict] = []
        page = 1
        east_errors: list[str] = []
        east_pages: list[dict] = []
        try:
            while page <= 8:  # 提升最多分页
                url = "https://push2.eastmoney.com/api/qt/clist/get"
                params = {
                    "pn": page,
                    "pz": 500,
                    "po": 1,
                    "np": 1,
                    "fltt": 2,
                    "invt": 2,
                    "fid": "f3",
                    # 注意: fs 参数必须用 + 号连接, 否则可能返回空
                    "fs": "m:0+t:6,m:0+t:80,m:1+t:2",
                    "fields": "f12,f14,f2,f3,f4",
                }
                _uas = [
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36',
                    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15'
                ]
                headers = {
                    "User-Agent": _rnd.choice(_uas),
                    "Accept": "application/json, text/plain, */*",
                    "Referer": "https://quote.eastmoney.com/",
                    "Accept-Language": "zh-CN,zh;q=0.9"
                }
                try:
                    r = requests.get(url, params=params, timeout=8, headers=headers)
                    if r.status_code != 200:
                        east_pages.append({'page': page, 'status_code': r.status_code})
                        break
                    j = r.json()
                    diff = (((j or {}).get("data") or {}).get("diff")) or []
                    east_pages.append({'page': page, 'rows': len(diff)})
                    if not diff:
                        break
                    all_rows.extend(diff)
                    if len(diff) < 500:
                        break
                    page += 1
                except Exception as _ee:  # noqa: BLE001
                    east_errors.append(str(_ee))
                    break
        except Exception as _eee:  # noqa: BLE001
            east_errors.append(str(_eee))
        if all_rows:
            import pandas as _pd
            df = _pd.DataFrame(all_rows).rename(
                columns={"f12": "代码", "f14": "名称", "f3": "涨跌幅", "f4": "涨跌额", "f2": "最新价"}
            )
            # eastmoney 有时字符串，需要转 float
            for col in ["涨跌幅","涨跌额","最新价"]:
                if col in df.columns:
                    try:
                        df[col] = _pd.to_numeric(df[col], errors='coerce')
                    except Exception:
                        pass
            last_provider = "eastmoney"
            provider_chain.append({'provider':'eastmoney','status':'ok','rows': int(df.shape[0]), 'pages': east_pages})
        else:
            provider_chain.append({'provider':'eastmoney','status':'empty','errors': east_errors, 'pages': east_pages})

    # 2b) tencent fallback (batch quotes) - 仅在 eastmoney & akshare 均空且 provider=auto 或 tencent
    if (df is None or (hasattr(df, "empty") and df.empty)) and (not disable_tencent) and provider in ("auto", "tencent"):
        try:
            import math as _math
            import requests as _rq
            import pandas as _pd
            # 基础代码列表获取策略: 先尝试从环境或一个简短内置列表开始
            base_codes_env = None
            import os as _os
            if 'TENCENT_CODES' in _os.environ:
                base_codes_env = [c.strip() for c in _os.environ['TENCENT_CODES'].split(',') if c.strip()]
            # 内置示例（可扩展, 这里只是确保有真实数据回显）
            base_codes = base_codes_env or [
                'sh600000','sz000001','sh600519','sz000333','sh601318','sz300750','sh601988','sh600036','sz000858','sh601166',
                'sh600104','sh601988','sh601211','sz000651','sh601398','sh601939','sh600028','sh601857','sh600050','sz002415'
            ]
            # 批量请求（腾讯接口单次上限 ~800，这里用少量验证, 后续可扩展）
            batch_size = 50
            lines: list[str] = []
            for i in range(0, len(base_codes), batch_size):
                sub = base_codes[i:i+batch_size]
                url = "https://qt.gtimg.cn/q=" + ",".join(sub)
                r = _rq.get(url, timeout=6, headers={'User-Agent':'Mozilla/5.0'})
                if r.status_code != 200:
                    provider_chain.append({'provider':'tencent','status':'error','http':r.status_code})
                    lines = []
                    break
                # 返回内容按分号或换行分隔
                txt = r.text.strip()
                for ln in txt.split(';'):
                    ln = ln.strip()
                    if ln:
                        lines.append(ln)
            recs: list[dict] = []
            for ln in lines:
                # 形如: v_sh600000="1~浦发银行~600000~10.23~10.26~10.27~..."
                if '=' not in ln:
                    continue
                try:
                    _, right = ln.split('=',1)
                    if right.startswith('"') and right.endswith('"'):
                        right = right[1:-1]
                    parts = right.split('~')
                    if len(parts) < 6:
                        continue
                    name = parts[1]
                    code = parts[2]
                    # 当前价 / 昨收
                    try:
                        price = float(parts[3]) if parts[3] else None
                        prev_close = float(parts[4]) if parts[4] else None
                    except Exception:  # noqa: BLE001
                        price = None
                        prev_close = None
                    pct = None
                    chg = None
                    if price is not None and prev_close not in (None,0):
                        pct = (price - prev_close) / prev_close * 100
                        chg = price - prev_close
                    # symbol 后缀判断: 代码首位 6/5/9 -> SH 其余 SZ （简化）
                    suffix = '.SH' if code.startswith(('6','5','9')) else '.SZ'
                    recs.append({
                        '代码': code,
                        '名称': name,
                        '最新价': price,
                        '涨跌幅': pct,
                        '涨跌额': chg
                    })
                except Exception:
                    continue
            if recs:
                import pandas as _pd
                df = _pd.DataFrame(recs)
                last_provider = 'tencent'
                provider_chain.append({'provider':'tencent','status':'partial','rows': len(df)})
            else:
                provider_chain.append({'provider':'tencent','status':'empty'})
        except Exception as _te:  # noqa: BLE001
            provider_chain.append({'provider':'tencent','status':'error','error': str(_te)})

    # 3) mock 占位
    if df is None or (hasattr(df, "empty") and df.empty):
        import random as _rnd
        if not allow_mock:
            return {
                "source": "live",
                "error": "empty snapshot (mock disabled)",
                "reason": "providers returned empty" if provider_chain else "no providers tried",
                "ak_error": ak_error,
                "gainers": [],
                "losers": [],
                "universe_size": 0,
                "parsed_rows": 0,
                "valid_rows": 0,
                "filtered_rows": 0,
                "provider": last_provider or provider,
                "mock": False,
                "all_valid": [],
                "provider_chain": provider_chain,
                "quality": "empty"
            }
        mock_records: list[dict] = []
        for i in range(1, 31):
            code = f"MOCK{i:04d}"
            suffix = ".SH" if i % 2 == 0 else ".SZ"
            pct = round(_rnd.uniform(-5, 5), 2)
            mock_records.append(
                {
                    "symbol": code + suffix,
                    "name": f"占位{code}",
                    "pct_chg": pct,
                    "change": round(pct * 0.1, 2),
                    "price": round(10 + pct * 0.2, 2),
                }
            )
        mock_sorted = sorted(mock_records, key=lambda x: x["pct_chg"], reverse=True)
        return {
            "source": "live",
            "error": "empty snapshot",
            "mock_reason": "all providers empty or errored",
            "ak_error": ak_error,
            "gainers": mock_sorted[:limit],
            "losers": list(reversed(mock_sorted))[:limit],
            "universe_size": len(mock_records),
            "parsed_rows": len(mock_records),
            "valid_rows": len(mock_records),
            "filtered_rows": len(mock_sorted),
            "provider": last_provider or provider,
            "mock": True,
            "all_valid": mock_sorted,
            "provider_chain": provider_chain,
            "quality": "mock"
        }

    # 4) 解析真实 df
    code_col = "代码" if "代码" in df.columns else ("symbol" if "symbol" in df.columns else None)
    name_col = "名称" if "名称" in df.columns else ("name" if "name" in df.columns else None)
    pct_cols = ["涨跌幅", "涨跌幅(%)", "涨幅", "涨幅(%)"]
    chg_cols = ["涨跌额", "涨跌"]
    price_cols = ["最新价", "最新", "price", "现价"]
    if not code_col or not name_col:
        return {
            "source": "live",
            "error": "columns missing",
            "gainers": [],
            "losers": [],
            "universe_size": 0,
            "parsed_rows": 0,
            "valid_rows": 0,
            "filtered_rows": 0,
            "provider": last_provider or provider,
            "provider_chain": provider_chain
        }

    def pick(row: dict, cols: list[str]):
        for c in cols:
            if c in row and row[c] not in (None, "", "-", "--"):
                return row[c]
        return None

    records: list[dict] = []
    for _, _row in df.iterrows():
        try:
            code = str(_row[code_col])
            if not code or len(code) < 6:
                continue
            suffix = ".SH" if code.startswith("6") else ".SZ"
            sym = f"{code}{suffix}"
            nm = _row[name_col]
            pct_raw = pick(_row, pct_cols)
            chg_raw = pick(_row, chg_cols)
            price_raw = pick(_row, price_cols)
            try:
                pct_f = float(pct_raw)
            except Exception:  # noqa: BLE001
                pct_f = None
            try:
                chg_f = float(chg_raw)
            except Exception:  # noqa: BLE001
                chg_f = None
            try:
                price_f = float(price_raw)
            except Exception:  # noqa: BLE001
                price_f = None
            records.append({"symbol": sym, "name": nm, "pct_chg": pct_f, "change": chg_f, "price": price_f})
        except Exception:  # noqa: BLE001
            continue

    if exchange and exchange.upper() in ("SH", "SZ"):
        suf = f".{exchange.upper()}"
        records = [r for r in records if r["symbol"].endswith(suf)]

    valid = [r for r in records if isinstance(r.get("pct_chg"), (int, float))]
    valid.sort(key=lambda x: x["pct_chg"], reverse=True)
    gainers = valid[:limit]
    losers = list(reversed(valid))[:limit]

    # 质量评估
    universe_size = len(records)
    quality = 'full'
    partial_reason = None
    if universe_size < 300:  # 明显不全市场
        quality = 'partial'
        partial_reason = 'too_small'
    elif last_provider == 'tencent':
        quality = 'partial'
        partial_reason = 'tencent_subset'
    # 若所有 pct_chg 都在极小范围且接近均匀, 标记疑似异常
    try:
        import math as _math
        pct_vals = [v['pct_chg'] for v in valid if isinstance(v.get('pct_chg'), (int,float))]
        if pct_vals:
            mean_v = sum(pct_vals)/len(pct_vals)
            var_v = sum((x-mean_v)**2 for x in pct_vals)/len(pct_vals)
            std_v = _math.sqrt(var_v)
            if std_v < 0.15 and max(pct_vals) < 1 and min(pct_vals) > -1 and universe_size>50:
                quality = 'suspect'
                partial_reason = 'very_low_volatility'
    except Exception:
        pass

    return {
        "source": "live",
        "generated_at": datetime.utcnow().isoformat(),
        "universe_size": universe_size,
        "parsed_rows": universe_size,
        "valid_rows": len(valid),
        "filtered_rows": len(valid),
        "gainers": gainers,
        "losers": losers,
        "provider": last_provider or provider,
        "ak_error": ak_error,
        "mock": False,
        "all_valid": valid,
        "provider_chain": provider_chain,
        "quality": quality,
        "partial_reason": partial_reason
    }

def warm_live_insight_cache():
    """后台预热 live_insight 缓存（捕获所有异常）。"""
    import time as _time
    logger = logging.getLogger(__name__)
    try:
        res = _fetch_live_insight_snapshot(limit=50, exchange='ALL', provider='auto', allow_mock=True)
        if res and res.get('gainers'):
            _live_insight_cache['data'] = res
            _live_insight_cache['ts'] = _time.time()
            logger.info("warm_live_insight_cache success provider_chain=%s universe=%s mock=%s", res.get('provider_chain'), res.get('universe_size'), res.get('mock'))
        else:
            logger.warning("warm_live_insight_cache empty provider_chain=%s error=%s", res.get('provider_chain') if isinstance(res, dict) else None, res.get('error') if isinstance(res, dict) else None)
    except Exception as e:  # noqa: BLE001
        logger.exception("warm_live_insight_cache failed: %s", e)

@router.get("/live_insight")
def live_insight(limit: int = 20, exchange: str = "ALL", provider: str = "auto", refresh: int = 0, allow_mock: int = 0):
    """实时全市场涨跌榜（带缓存 + 多源回退 + 最小重试）。

    参数：
      - limit: TOP 数量 (<=100)
      - exchange: ALL|SH|SZ
      - provider: auto|akshare|eastmoney
      - refresh: 1 强制忽略缓存重新抓取
    说明：
      - 内置 10 秒缓存，失败时尝试使用缓存旧数据（加上 'stale': true 标记）
      - akshare 连续失败后自动回退 eastmoney
    """
    import time as _time
    if limit > 100:
        limit = 100
    now = _time.time()
    cached = _live_insight_cache['data']
    use_cache = (refresh == 0 and cached is not None and (now - _live_insight_cache['ts'] <= _live_insight_cache['ttl']) and ((cached.get('gainers') or cached.get('all_valid'))))
    if use_cache:
        # 基于 all_valid 派生不同 exchange/limit
        base = dict(cached)
        all_valid = base.get('all_valid') or base.get('gainers') or []
        if exchange and exchange.upper() in ("SH","SZ"):
            suf = f".{exchange.upper()}"
            derived = [r for r in all_valid if r['symbol'].endswith(suf)]
        else:
            derived = all_valid
        base['gainers'] = derived[:limit]
        base['losers'] = list(reversed(derived))[:limit]
        base['cache'] = True
        base['cache_age_sec'] = round(now - _live_insight_cache['ts'], 2)
        return base
    # fresh fetch
    res = _fetch_live_insight_snapshot(limit=limit, exchange=exchange, provider=provider, allow_mock=bool(allow_mock))
    if res.get('gainers'):
        _live_insight_cache['data'] = {**res, 'cache': True}
        _live_insight_cache['ts'] = now
        res['cache'] = False
        return res
    # 如果失败且存在旧缓存，返回旧缓存并标记 stale
    if _live_insight_cache['data'] is not None:
        stale = dict(_live_insight_cache['data'])
        stale['stale'] = True
        stale['cache_age_sec'] = round(now - _live_insight_cache['ts'],2)
        # 按新 limit 裁剪
        stale['gainers'] = stale.get('gainers', [])[:limit]
        stale['losers'] = stale.get('losers', [])[:limit]
        return stale
    return res

@router.get("/live_insight/providers")
def live_insight_providers():
    """返回最近一次缓存或即时抓取的 provider_chain 及关键信息，用于前端展示来源状态。"""
    if _live_insight_cache['data']:
        d = _live_insight_cache['data']
        return {
            'cached': True,
            'cache_age_sec': round(datetime.utcnow().timestamp() - _live_insight_cache['ts'],2),
            'provider_chain': d.get('provider_chain'),
            'mock': d.get('mock'),
            'universe_size': d.get('universe_size'),
            'ak_error': d.get('ak_error'),
            'error': d.get('error'),
            'reason': d.get('reason'),
            'mock_reason': d.get('mock_reason')
        }
    # 若无缓存，做一次快速无 mock 抓取（limit=1 减少耗时）
    snap = _fetch_live_insight_snapshot(limit=1, exchange='ALL', provider='auto', allow_mock=False)
    return {'cached': False, 'provider_chain': snap.get('provider_chain'), 'mock': snap.get('mock'), 'error': snap.get('error'), 'ak_error': snap.get('ak_error'), 'reason': snap.get('reason')}

@router.post("/live_insight/force_refresh")
def force_refresh_live_insight(exchange: str = "ALL"):
    """手动强制刷新一次 live_insight 缓存（方便运维）。"""
    warm_live_insight_cache()
    data = _live_insight_cache['data'] or {'message':'refresh attempted but still empty'}
    return {'ok': True, 'cached': bool(_live_insight_cache['data']), 'size': data.get('universe_size',0), 'provider': data.get('provider'), 'sample_gainers': data.get('gainers', [])[:3]}

@router.get("/live_insight_debug")
def live_insight_debug(provider: str = "auto", sample: int = 5):
    """调试端点：返回实时抓取的原始前若干行（不走缓存），用于排查列名/数据为空问题。

    返回：
      provider_used, columns, raw_sample, error, ak_error
    """
    import traceback, time as _time
    started = _time.time()
    raw_cols = []
    raw_sample = []
    provider_used = None
    ak_error = None
    error = None
    try:
        import akshare as ak
        if provider in ("auto","akshare"):
            try:
                df = ak.stock_zh_a_spot_em()
                provider_used = 'akshare'
                if df is not None and not df.empty:
                    raw_cols = list(df.columns)[:50]
                    head_df = df.head(sample)
                    raw_sample = head_df.to_dict(orient='records')
                else:
                    ak_error = 'empty akshare df'
            except Exception as e:
                ak_error = str(e)
    except Exception:
        pass
    if (not raw_sample) and provider in ("auto","eastmoney"):
        # eastmoney fallback raw
        import requests
        try:
            url = "https://push2.eastmoney.com/api/qt/clist/get"
            params = {"pn":1,"pz": sample,"po":1,"np":1,"fltt":2,"invt":2,"fid":"f3","fs":"m:1 t:2,m:0 t:6,m:0 t:80","fields":"f12,f14,f2,f3,f4"}
            r = requests.get(url, params=params, timeout=8, headers={"User-Agent":"Mozilla/5.0"})
            if r.status_code == 200:
                j = r.json()
                diff = (((j or {}).get('data') or {}).get('diff')) or []
                raw_sample = diff[:sample]
                raw_cols = list(diff[0].keys()) if diff else []
                provider_used = provider_used or 'eastmoney'
        except Exception as e:
            error = str(e)
    duration = round((_time.time() - started)*1000,2)
    return {
        'provider_requested': provider,
        'provider_used': provider_used,
        'columns': raw_cols,
        'raw_sample': raw_sample,
        'ak_error': ak_error,
        'error': error,
        'duration_ms': duration
    }

@router.get("/live_series/{symbol}")
def live_series(symbol: str, days: int = 30):
    """获取指定股票近 N 日（日 K）基础数据（直接通过 akshare，不访问本地 DB）。
    返回: symbol, rows=[{trade_date, open, high, low, close, pct_chg}]
    """
    if days > 180:
        days = 180
    try:
        import akshare as ak
        import pandas as pd  # 修复缺失引用
        std = symbol.upper().strip()
        base = std.replace('.SH','').replace('.SZ','')
        df = ak.stock_zh_a_hist(symbol=base, period='daily', adjust='qfq')
        if df is None or df.empty:
            return {"symbol": std, "rows": []}
        rename = {"日期":"trade_date","开盘":"open","收盘":"close","最高":"high","最低":"low","涨跌幅":"pct_chg"}
        df = df.rename(columns=rename)
        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')
        cols = ['trade_date','open','high','low','close','pct_chg']
        out_df = df[cols].tail(days)
        rows = []
        for _, r in out_df.iterrows():
            row = {c: (None if pd.isna(r[c]) else float(r[c]) if c != 'trade_date' else r[c]) for c in cols}
            rows.append(row)
        return {"symbol": std, "rows": rows}
    except Exception as e:
        return {"symbol": symbol, "error": str(e), "rows": []}

# =====================  日终 / 历史区间 全量分析接口 (依赖数据库与摄取状态)  ===================== #
@router.get("/full/daily")
def full_daily(limit: int = 50, exchange: str = "ALL", db: Session = Depends(get_db)):
    """最近一个交易日(已摄取) 的全市场涨跌分布与 Top 列表。

    返回：
      trade_date, universe_size, coverage_rows, gainers, losers, stats
    说明：
      - 依赖 ingest_state_daily 获取最近成功摄取的 trade_date
      - 如无摄取成功记录，返回空并提示
    """
    # 1. 查找最近成功的 trade_date
    row = db.execute(text("SELECT trade_date FROM ingest_state_daily WHERE status='success' ORDER BY trade_date DESC LIMIT 1")).first()
    if not row:
        return {"error": "no successful ingestion", "gainers": [], "losers": [], "stats": {}}
    trade_date = row[0]
    if limit > 200:
        limit = 200
    exch_clause = ""
    params = {"td": trade_date, "lim": limit}
    if exchange and exchange.upper() in ("SH","SZ"):
        exch_clause = " AND symbol ILIKE :exsuf"
        params['exsuf'] = f"%.{exchange.upper()}"
    # universe size & coverage
    universe_size = db.execute(text(f"SELECT COUNT(*) FROM prices_daily WHERE trade_date=:td{exch_clause}"), params).scalar() or 0
    # top gainers / losers
    gainers = _run_query(db, f"""
        SELECT symbol, close, pct_chg FROM prices_daily
        WHERE trade_date=:td AND pct_chg IS NOT NULL {exch_clause}
        ORDER BY pct_chg DESC LIMIT :lim
    """, params)
    losers = _run_query(db, f"""
        SELECT symbol, close, pct_chg FROM prices_daily
        WHERE trade_date=:td AND pct_chg IS NOT NULL {exch_clause}
        ORDER BY pct_chg ASC LIMIT :lim
    """, params)
    # 简单统计（后续可丰富）
    stats_row = db.execute(text(f"SELECT AVG(pct_chg) AS avg_chg, PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY pct_chg) AS median_chg FROM prices_daily WHERE trade_date=:td AND pct_chg IS NOT NULL {exch_clause}"), params).mappings().first()
    def _norm(arr):
        out = []
        for r in arr:
            d = dict(r)
            if d.get('pct_chg') is not None:
                try: d['pct_chg'] = float(d['pct_chg'])
                except Exception: pass
            out.append(d)
        return out
    return {
        'trade_date': trade_date.isoformat(),
        'universe_size': universe_size,
        'gainers': _norm(gainers),
        'losers': _norm(losers),
        'stats': {
            'avg_pct_chg': float(stats_row['avg_chg']) if stats_row and stats_row.get('avg_chg') is not None else None,
            'median_pct_chg': float(stats_row['median_chg']) if stats_row and stats_row.get('median_chg') is not None else None
        }
    }

@router.get("/full/range")
def full_range(period: str = Query("1m", description="1m=近1月,1y=近1年"), exchange: str = "ALL", limit: int = 50, db: Session = Depends(get_db)):
    """计算给定区间的累计涨跌幅 (收盘价区间首末) 并返回 Top & Bottom。

    简化实现：
      - 取最近成功摄取日 T 作为区间末端
      - period=1m -> T 往前 35 自然日; period=1y -> 380 自然日 (粗略包含交易日)
      - 对每个 symbol 取该窗口内最早与最晚有效 close
      - cum_return = (last/first - 1)*100
    """
    # 末端日期
    row = db.execute(text("SELECT trade_date FROM ingest_state_daily WHERE status='success' ORDER BY trade_date DESC LIMIT 1")).first()
    if not row:
        return {"error": "no successful ingestion", "gainers": [], "losers": []}
    end_date = row[0]
    span_days = 35 if period == '1m' else 380
    start_date = end_date - timedelta(days=span_days)
    exch_clause = ""
    params = {"start": start_date, "end": end_date}
    if exchange and exchange.upper() in ("SH","SZ"):
        exch_clause = " AND symbol ILIKE :exsuf"
        params['exsuf'] = f"%.{exchange.upper()}"
    rows = _run_query(db, f"""
        SELECT symbol, trade_date, close
        FROM prices_daily
        WHERE trade_date BETWEEN :start AND :end {exch_clause}
        ORDER BY symbol, trade_date
    """, params)
    from collections import defaultdict
    groups = defaultdict(list)
    for r in rows:
        groups[r['symbol']].append(r)
    results = []
    for sym, arr in groups.items():
        if len(arr) < 5:
            continue
        first = None
        for rec in arr:
            v = rec.get('close')
            if v is not None:
                first = float(v)
                break
        last = None
        for rec in reversed(arr):
            v = rec.get('close')
            if v is not None:
                last = float(v)
                break
        if not first or not last or first == 0:
            continue
        ret = (last/first - 1.0) * 100.0
        results.append({'symbol': sym, 'cum_return': ret})
    results.sort(key=lambda x: x['cum_return'], reverse=True)
    gainers = results[:limit]
    losers = list(reversed(results))[:limit]
    return {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'period': period,
        'gainers': gainers,
        'losers': losers,
        'universe_size': len(results)
    }

@router.get("/full/stats")
def full_stats(db: Session = Depends(get_db)):
    """截面统计 (最近成功交易日) ：均值、中位数、标准差、正/负收益占比。"""
    row = db.execute(text("SELECT trade_date FROM ingest_state_daily WHERE status='success' ORDER BY trade_date DESC LIMIT 1")).first()
    if not row:
        return {"error": "no successful ingestion"}
    td = row[0]
    stats = db.execute(text("""
        SELECT
          AVG(pct_chg) AS avg_chg,
          PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY pct_chg) AS median_chg,
          STDDEV_POP(pct_chg) AS std_chg,
          SUM(CASE WHEN pct_chg > 0 THEN 1 ELSE 0 END)::float / COUNT(*) AS positive_ratio,
          SUM(CASE WHEN pct_chg < 0 THEN 1 ELSE 0 END)::float / COUNT(*) AS negative_ratio
        FROM prices_daily
        WHERE trade_date=:td AND pct_chg IS NOT NULL
    """), {"td": td}).mappings().first()
    out = {k: (float(v) if v is not None else None) for k,v in (stats or {}).items()}
    out['trade_date'] = td.isoformat()
    return out

@router.get("/full/distribution")
def full_distribution(bins: int = 20, db: Session = Depends(get_db)):
    """返回最近成功交易日 pct_chg 直方图分桶 (等宽)。"""
    if bins < 5: bins = 5
    if bins > 100: bins = 100
    row = db.execute(text("SELECT trade_date FROM ingest_state_daily WHERE status='success' ORDER BY trade_date DESC LIMIT 1")).first()
    if not row:
        return {"error": "no successful ingestion", "bins": []}
    td = row[0]
    # 获取所有 pct_chg
    vals = db.execute(text("SELECT pct_chg FROM prices_daily WHERE trade_date=:td AND pct_chg IS NOT NULL"), {"td": td}).scalars().all()
    floats = []
    for v in vals:
        try:
            floats.append(float(v))
        except Exception:
            continue
    if not floats:
        return {"trade_date": td.isoformat(), "bins": []}
    mn, mx = min(floats), max(floats)
    if mx - mn < 1e-9:
        return {"trade_date": td.isoformat(), "bins": [{"range": [mn, mx], "count": len(floats)}]}
    width = (mx - mn) / bins
    counters = [0]*bins
    for v in floats:
        idx = int((v - mn) / width)
        if idx >= bins:
            idx = bins - 1
        counters[idx] += 1
    bucket_list = []
    for i,c in enumerate(counters):
        lo = mn + i*width
        hi = lo + width
        bucket_list.append({"range": [round(lo,4), round(hi,4)], "count": c})
    return {"trade_date": td.isoformat(), "min": mn, "max": mx, "bins": bucket_list}

_live_cache = {"ts": 0.0, "data": None, "ttl": 15}  # 15 秒缓存实时全市场快照（避免频繁外部请求）

def _fetch_live_movers(exchange: str, limit: int) -> Dict[str, Any]:
    """使用 data_source 的全市场批量快照获取实时涨跌幅 TOP。

    逻辑：
    1. 若缓存未过期直接使用
    2. 否则调用 akshare 全市场快照（data_source.get_spot_snapshot 已含多级回退）
    3. 过滤交易所（后缀）
    4. 计算排序，截取涨幅/跌幅前 N
    返回: {gainers: [...], losers: [...], source: 'live', cached: bool}
    """
    import time
    from ..data import data_source
    now = time.time()
    cached_flag = False
    if _live_cache["data"] is not None and (now - _live_cache["ts"] <= _live_cache["ttl"]):
        items = _live_cache["data"]
        cached_flag = True
    else:
        # 为避免获取全部上千标的反复构造列表，直接调用 akshare spot 表一次
        try:
            import akshare as ak  # noqa
            df = ak.stock_zh_a_spot_em()
        except Exception:
            df = None
        records = []
        if df is not None and not df.empty:
            # 兼容列名
            code_col = '代码' if '代码' in df.columns else ('symbol' if 'symbol' in df.columns else None)
            name_col = '名称' if '名称' in df.columns else ('name' if 'name' in df.columns else None)
            pct_col_candidates = ['涨跌幅', '涨跌幅(%)', '涨幅', '涨幅(%)']
            change_col_candidates = ['涨跌额', '涨跌']
            price_col_candidates = ['最新价','最新','price','现价']
            if code_col and name_col:
                for _, row in df.iterrows():
                    try:
                        code = str(row[code_col])
                        if not code or len(code) < 6:
                            continue
                        suffix = '.SH' if code.startswith('6') else '.SZ'
                        symbol = f"{code}{suffix}"
                        name = row[name_col]
                        def pick(cols):
                            for c in cols:
                                if c in df.columns and row.get(c) not in (None, '', '-', '--'):
                                    return row.get(c)
                            return None
                        pct = pick(pct_col_candidates)
                        change = pick(change_col_candidates)
                        price = pick(price_col_candidates)
                        try:
                            pct_f = float(pct)
                        except Exception:
                            pct_f = None
                        try:
                            change_f = float(change)
                        except Exception:
                            change_f = None
                        try:
                            price_f = float(price)
                        except Exception:
                            price_f = None
                        records.append({
                            'symbol': symbol,
                            'name': name,
                            'pct_chg': pct_f,
                            'change': change_f,
                            'close': price_f,
                        })
                    except Exception:
                        continue
        # 若主路径失败则回退使用 data_source.get_spot_snapshot (两步：获取所有代码列表 -> snapshot)
        if not records:
            try:
                import akshare as ak
                code_df = ak.stock_info_a_code_name()
                codes = code_df['code'].astype(str).tolist() if code_df is not None and not code_df.empty else []
                # 分批获取，避免一次性巨大列表；此处仅做最小回退，获取涨跌幅仍以 snapshot 字段 pct_change
                all_items = []
                batch = 400
                for i in range(0, len(codes), batch):
                    part = codes[i:i+batch]
                    symbols = [ (c + ('.SH' if c.startswith('6') else '.SZ')) for c in part ]
                    snap = data_source.get_spot_snapshot(symbols)
                    for symb, v in snap.items():
                        all_items.append({
                            'symbol': symb,
                            'name': v.get('name'),
                            'pct_chg': v.get('pct_change'),
                            'change': v.get('change'),
                            'close': v.get('price'),
                        })
                records = all_items
            except Exception:
                records = []
        _live_cache['data'] = records
        _live_cache['ts'] = now
        items = records
    # 过滤交易所
    if exchange and exchange.upper() in ('SH','SZ'):
        suf = f".{exchange.upper()}"
        items = [r for r in items if r['symbol'].endswith(suf)]
    # 排序
    gainers = [r for r in items if isinstance(r.get('pct_chg'), (int,float))]
    gainers.sort(key=lambda x: x.get('pct_chg') or 0, reverse=True)
    losers = list(reversed(gainers))
    return {
        'gainers': gainers[:limit],
        'losers': losers[:limit],
        'source': 'live',
        'cached': cached_flag,
        'universe_size': len(items)
    }

@router.get("/daily")
def top_daily(limit: int = 20, exchange: str = "ALL", source: str = Query("db", description="数据来源: db=数据库最新日线, live=实时快照"), db: Session = Depends(get_db)):
    """全市场（日最新交易日）涨幅/跌幅 TOP。

    说明：
    - 不再仅限 watchlist；使用 prices_daily 全部记录。
    - 名称优先顺序：watchlist.name -> stocks.name -> None
    - 行业（sector）仅 watchlist 里有（后续可扩展行业映射表）。
    """
    if source == 'live':
        return _fetch_live_movers(exchange=exchange, limit=limit)
    # DB 模式（收盘后/静态分析使用）
    if limit > 50:
        limit = 50
    exch_clause = ""
    params = {"lim": limit}
    if exchange and exchange.upper() in ("SH","SZ"):
        exch_clause = " AND p.symbol ILIKE :exsuf"
        params["exsuf"] = f"%.{exchange.upper()}"
    rows = _run_query(db, f"""
        SELECT p.symbol, p.trade_date, p.close, p.pct_chg,
               COALESCE(w.name, s.name) AS name, w.sector
        FROM prices_daily p
        LEFT JOIN watchlist w ON w.symbol = p.symbol
        LEFT JOIN stocks s ON s.symbol = p.symbol
        WHERE p.trade_date = (SELECT max(trade_date) FROM prices_daily)
          AND p.pct_chg IS NOT NULL
          {exch_clause}
        ORDER BY p.pct_chg DESC
        LIMIT :lim
    """, params)
    losers = _run_query(db, f"""
        SELECT p.symbol, p.trade_date, p.close, p.pct_chg,
               COALESCE(w.name, s.name) AS name, w.sector
        FROM prices_daily p
        LEFT JOIN watchlist w ON w.symbol = p.symbol
        LEFT JOIN stocks s ON s.symbol = p.symbol
        WHERE p.trade_date = (SELECT max(trade_date) FROM prices_daily)
          AND p.pct_chg IS NOT NULL
          {exch_clause}
        ORDER BY p.pct_chg ASC
        LIMIT :lim
    """, params)
    def _normalize(arr):
        out = []
        for r in arr:
            d = dict(r)
            if d.get('pct_chg') is not None:
                try:
                    d['pct_chg'] = float(d['pct_chg'])
                except Exception:
                    pass
            out.append(d)
        return out
    return {"gainers": _normalize(rows), "losers": _normalize(losers), "source": "db"}

@router.get("/daily_flat")
def top_daily_flat(limit: int = 20, exchange: str = "ALL", source: str = Query("db"), db: Session = Depends(get_db)):
    """返回单一列表：按当日涨幅降序的前 N 名（可选交易所过滤）。支持 source=live|db"""
    if source == 'live':
        live = _fetch_live_movers(exchange=exchange, limit=limit)
        return {"gainers": live['gainers'], "count": len(live['gainers']), "source": "live", "cached": live.get('cached'), "universe_size": live.get('universe_size')}
    if limit > 100:
        limit = 100
    exch_clause = ""
    params = {"lim": limit}
    if exchange and exchange.upper() in ("SH","SZ"):
        exch_clause = " AND p.symbol ILIKE :exsuf"
        params['exsuf'] = f"%.{exchange.upper()}"
    rows = _run_query(db, f"""
        SELECT p.symbol, p.trade_date, p.close, p.pct_chg,
               COALESCE(w.name, s.name) AS name, w.sector
        FROM prices_daily p
        LEFT JOIN watchlist w ON w.symbol = p.symbol
        LEFT JOIN stocks s ON s.symbol = p.symbol
        WHERE p.trade_date = (SELECT max(trade_date) FROM prices_daily)
          AND p.pct_chg IS NOT NULL
          {exch_clause}
        ORDER BY p.pct_chg DESC
        LIMIT :lim
    """, params)
    out = []
    for r in rows:
        d = dict(r)
        if d.get('pct_chg') is not None:
            try:
                d['pct_chg'] = float(d['pct_chg'])
            except Exception:
                pass
        out.append(d)
    return {"gainers": out, "count": len(out), "source": "db"}

@router.get("/weekly")
def top_weekly(limit: int = 20, db: Session = Depends(get_db)):
    """Top weekly movers by 5 trading day change (close vs ~5 sessions ago).

    修复: 原先直接 (last / first - 1.0) * 100.0 在 close 为 Decimal 时与 float 混合计算抛出 TypeError。
    处理: 统一转 float；忽略异常或无效数据；保障 first>0。
    """
    if limit > 50:
        limit = 50

    latest = db.execute(text("SELECT max(trade_date) AS d FROM prices_daily")).scalar()
    if not latest:
        return {"gainers": [], "losers": []}

    # 取 10 自然日窗口以保证至少包含 5 个交易日
    start_date = latest - timedelta(days=10)
    data = _run_query(db, """
        SELECT p.symbol, p.trade_date, p.close,
               COALESCE(w.name, s.name) AS name, w.sector
        FROM prices_daily p
        LEFT JOIN watchlist w ON w.symbol = p.symbol
        LEFT JOIN stocks s ON s.symbol = p.symbol
        WHERE p.trade_date BETWEEN :start AND :end
    """, {"start": start_date, "end": latest})

    from collections import defaultdict
    by_symbol = defaultdict(list)
    for r in data:
        sym = r.get("symbol")
        if not sym:
            continue
        if isinstance(sym, str):
            sym_key = sym.strip()
        else:
            sym_key = str(sym)
        by_symbol[sym_key].append(r)

    def _to_float(v):
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, Decimal):
            try:
                return float(v)
            except (ValueError, InvalidOperation):
                return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    weekly = []
    for sym, arr in by_symbol.items():
        arr.sort(key=lambda x: x["trade_date"])
        if len(arr) < 5:
            continue
        first_raw = arr[-5].get("close")
        last_raw = arr[-1].get("close")
        first = _to_float(first_raw)
        last = _to_float(last_raw)
        if first is None or last is None or first == 0:
            continue
        try:
            pct = (last / first - 1.0) * 100.0
        except Exception:
            continue
        # 取该 symbol 最新记录的 name/sector（最后一条）
        name = None
        sector = None
        for item in reversed(arr):
            name = item.get('name') or name
            sector = item.get('sector') or sector
            if name or sector:
                break
        weekly.append({
            "symbol": sym,
            "pct_week": pct,
            "close": last,
            "name": name,
            "sector": sector
        })

    weekly.sort(key=lambda x: x["pct_week"], reverse=True)
    gainers = weekly[:limit]
    losers = sorted(weekly, key=lambda x: x["pct_week"])[:limit]
    return {"gainers": gainers, "losers": losers}

@router.get("/series/{symbol}")
def price_series(symbol: str, days: int = 30, db: Session = Depends(get_db)):
    if days > 120:
        days = 120
    latest = db.execute(text("SELECT max(trade_date) FROM prices_daily WHERE symbol=:s"), {"s": symbol}).scalar()
    if not latest:
        raise HTTPException(status_code=404, detail="symbol not found")
    start = latest - timedelta(days=days + 5)
    rows = _run_query(db, """
        SELECT trade_date, open, high, low, close, pct_chg
        FROM prices_daily
        WHERE symbol = :s AND trade_date BETWEEN :start AND :end
        ORDER BY trade_date
    """, {"s": symbol, "start": start, "end": latest})
    return {"symbol": symbol, "rows": rows}

@router.get("/analyze")
def analyze(limit: int = 10, news_days: int = 3, per_symbol_news: int = 3, db: Session = Depends(get_db)):
    """真实分析链（轻量版）

    步骤：
    1. 取得日度与周度涨幅前列股票（裁到 limit）
    2. 汇总 symbol 列表去重，截取前 2*limit（控制成本）
    3. 对每个 symbol 在最近 news_days 天内抽取相关新闻（最多 per_symbol_news 条）
    4. 使用 LLM 对每条新闻进行摘要（缓存/节流由 LLMNewsProcessor 自己控制）
    5. 聚合生成：highlights / themes / recommendations（启发式）
    6. 若 LLM 不可用或报错，回退到简易 stub
    """

    started = datetime.utcnow()
    try:
        # 1. Gather symbols
        daily = top_daily(limit=limit, db=db)
        weekly = top_weekly(limit=limit, db=db)
        symbols: List[str] = []
        for r in daily.get("gainers", []) + daily.get("losers", []):
            s = r.get("symbol")
            if s and s not in symbols:
                symbols.append(s)
        for r in weekly.get("gainers", []) + weekly.get("losers", []):
            s = r.get("symbol")
            if s and s not in symbols:
                symbols.append(s)
        symbols = symbols[: 2 * limit]

        # 2. Sector mapping
        # 行业映射：目前仍依赖 watchlist，后续可接入行业全量表
        watch_rows = db.execute(text("SELECT symbol, sector, name FROM watchlist WHERE enabled = true")).mappings().all()
        sector_map = {r["symbol"]: (r.get("sector") or "未知") for r in watch_rows}
        # 名称补全映射：stocks + watchlist
        stock_rows = db.execute(text("SELECT symbol, name FROM stocks")).mappings().all()
        name_map = {}
        for r in stock_rows:
            if r.get('symbol') and r.get('name'):
                name_map[r['symbol']] = r['name']
        # 优先 watchlist 覆盖
        for r in watch_rows:
            if r.get('symbol') and r.get('name'):
                name_map[r['symbol']] = r['name']

        # 3. Fetch recent news per symbol
        since = datetime.utcnow() - timedelta(days=news_days)
        symbol_news: Dict[str, List[Dict[str, Any]]] = {s: [] for s in symbols}
        for sym in symbols:
            rows = db.execute(text(
                """
                SELECT id, title, content, summary, sentiment_type, sentiment_score, related_stocks, published_at,
                       summary_from_llm, keywords, relevance_score
                FROM news_articles
                WHERE published_at >= :since
                  AND (related_stocks::text ILIKE :sym_like OR title ILIKE :sym_like)
                ORDER BY published_at DESC
                LIMIT :lim
                """
            ), {"since": since, "sym_like": f"%{sym.split('.')[0]}%", "lim": per_symbol_news}).mappings().all()
            symbol_news[sym] = [dict(r) for r in rows]

        # 4. LLM Summaries with caching
        processor = LLMNewsProcessor()
        llm_enabled = processor.llm_service != "none"
        summaries: Dict[str, List[Dict[str, Any]]] = {}
        if llm_enabled:
            import asyncio
            async def _run():
                out: Dict[str, List[Dict[str, Any]]] = {}
                for sym, arts in symbol_news.items():
                    cur: List[Dict[str, Any]] = []
                    for art in arts:
                        title = art.get("title") or "(无标题)"
                        content = art.get("content") or (art.get("summary") or "")
                        if not content:
                            continue
                        if art.get("summary") and art.get("summary_from_llm"):
                            fake = {
                                "summary": art.get("summary"),
                                "sentiment_type": art.get("sentiment_type"),
                                "sentiment_score": art.get("sentiment_score"),
                                "keywords": art.get("keywords") or [],
                                "relevance_score": art.get("relevance_score") or 0.5,
                            }
                            res_obj = type("Tmp", (), fake)
                        else:
                            res_obj = await processor.analyze_news(title=title, content=content, url=None)
                            if res_obj and not (art.get("summary") and art.get("summary_from_llm")):
                                try:
                                    db.execute(text(
                                        """
                                        UPDATE news_articles
                                        SET summary = :summary, summary_from_llm = true,
                                            sentiment_type = COALESCE(:stype, sentiment_type),
                                            sentiment_score = COALESCE(:sscore, sentiment_score),
                                            keywords = CASE WHEN :kjson IS NOT NULL THEN :kjson ELSE keywords END
                                        WHERE id = :id
                                        """
                                    ), {
                                        "summary": res_obj.summary,
                                        "stype": getattr(res_obj, 'sentiment_type', None),
                                        "sscore": getattr(res_obj, 'sentiment_score', None),
                                        "kjson": json.dumps(getattr(res_obj, 'keywords', [])),
                                        "id": art.get("id")
                                    })
                                    db.commit()
                                except Exception:
                                    db.rollback()
                        if res_obj:
                            cur.append({
                                "symbol": sym,
                                "title": title,
                                "summary": getattr(res_obj, 'summary', None),
                                "sentiment_type": getattr(res_obj, 'sentiment_type', None),
                                "sentiment_score": getattr(res_obj, 'sentiment_score', None),
                                "keywords": getattr(res_obj, 'keywords', [])[:8],
                                "relevance": getattr(res_obj, 'relevance_score', None),
                                "sector": sector_map.get(sym, "未知")
                            })
                    out[sym] = cur
                return out
            summaries = asyncio.run(_run())
        else:
            summaries = symbol_news

        # 5. Highlights & Themes
        highlights: List[str] = []
        if daily.get("gainers"):
            g0 = daily["gainers"][0]
            highlights.append(f"当日领涨: {g0['symbol']} 涨幅 ~{g0['pct_chg']:.2f}%")
        if weekly.get("gainers"):
            w0 = weekly["gainers"][0]
            highlights.append(f"周动能最强: {w0['symbol']} 周涨幅 ~{w0['pct_week']:.2f}%")
        if daily.get("losers"):
            l0 = daily["losers"][0]
            highlights.append(f"当日领跌: {l0['symbol']} 跌幅 ~{l0['pct_chg']:.2f}%")

        from collections import Counter
        kw_counter = Counter()
        for arr in summaries.values():
            for a in arr:
                for kw in (a.get("keywords") or []):
                    if isinstance(kw, str) and 1 < len(kw) <= 12:
                        kw_counter[kw.lower()] += 1
        themes = [{"name": kw, "signals": [f"出现 {cnt} 次"], "risk": "待评估"} for kw, cnt in kw_counter.most_common(6)][:4]

        # 6. Sector stats
        weekly_index = {r['symbol']: r for r in weekly.get('gainers', []) + weekly.get('losers', [])}
        daily_index = {r['symbol']: r for r in daily.get('gainers', []) + daily.get('losers', [])}
        sector_acc: Dict[str, Dict[str, Any]] = {}
        for sym in symbols:
            sector = sector_map.get(sym, '未知') or '未知'
            wrow = weekly_index.get(sym, {})
            drow = daily_index.get(sym, {})
            week_raw = wrow.get('pct_week') if wrow else 0.0
            day_raw = drow.get('pct_chg') if drow else 0.0
            try:
                week_pct = float(week_raw or 0.0)
            except Exception:
                week_pct = 0.0
            try:
                day_pct = float(day_raw or 0.0)
            except Exception:
                day_pct = 0.0
            bucket = sector_acc.setdefault(sector, {"week_pcts": [], "day_pcts": [], "symbols": [], "sentiments": [], "news_count":0})
            bucket['week_pcts'].append(week_pct)
            bucket['day_pcts'].append(day_pct)
            bucket['symbols'].append(sym)
            for s in summaries.get(sym, []):
                if s.get('sentiment_score') is not None:
                    try:
                        bucket['sentiments'].append(float(s['sentiment_score']))
                    except Exception:
                        pass
            bucket['news_count'] += len(summaries.get(sym, []))

        sector_stats = []
        for sec, v in sector_acc.items():
            if not v['week_pcts']:
                continue
            avg_week = sum(v['week_pcts'])/len(v['week_pcts'])
            avg_sent = sum(v['sentiments'])/len(v['sentiments']) if v['sentiments'] else 0
            sector_stats.append({
                'sector': sec,
                'count': len(v['symbols']),
                'avg_week_pct': avg_week,
                'avg_sentiment': avg_sent,
                'news_density': v['news_count']/max(1,len(v['symbols']))
            })
        if sector_stats:
            w_vals = [s['avg_week_pct'] for s in sector_stats]
            n_vals = [s['news_density'] for s in sector_stats]
            def _norm(vals):
                mn, mx = min(vals), max(vals)
                if mx - mn < 1e-6:
                    return {i:0.5 for i,_ in enumerate(vals)}
                return {i:(vals[i]-mn)/(mx-mn) for i,_ in enumerate(vals)}
            w_norm = _norm(w_vals)
            n_norm = _norm(n_vals)
            for i, s in enumerate(sector_stats):
                s['heat'] = round(w_norm[i]*0.6 + n_norm[i]*0.4,4)
            sector_stats.sort(key=lambda x: x['heat'], reverse=True)
            for rk, s in enumerate(sector_stats, start=1):
                s['heat_rank'] = rk

        # 7. Recommendations
        recommendations = []
        sector_strength_map = {}
        if sector_stats:
            max_w = max(s['avg_week_pct'] for s in sector_stats) or 1
            for s in sector_stats:
                sector_strength_map[s['sector']] = min(1.0, max(0.0, s['avg_week_pct']/max_w))
        for sym in symbols:
            wrow = weekly_index.get(sym)
            drow = daily_index.get(sym)
            if not wrow:
                continue
            week_pct = float(wrow.get('pct_week') or 0.0)
            if week_pct <= 0:
                continue
            day_pct = float((daily_index.get(sym) or {}).get('pct_chg') or 0.0)
            sent_scores = [a.get('sentiment_score') for a in summaries.get(sym, []) if a.get('sentiment_score') is not None]
            avg_sent = sum(sent_scores)/len(sent_scores) if sent_scores else 0.0
            sentiment_norm = (avg_sent + 1)/2
            news_density = len(summaries.get(sym, [])) / float(per_symbol_news or 1)
            sector = sector_map.get(sym, '未知')
            sector_strength = sector_strength_map.get(sector, 0.4)
            week_momentum = min(1.0, max(0.0, week_pct/20.0))
            day_momentum = min(1.0, max(0.0, day_pct/8.0))
            score = (week_momentum*0.32 + day_momentum*0.18 + sentiment_norm*0.18 + news_density*0.12 + sector_strength*0.20)
            recommendations.append({
                'symbol': sym,
                'name': (wrow.get('name') if wrow else None) or (drow.get('name') if drow else None) or name_map.get(sym),
                'sector': sector,
                'reason': f"周动能 {week_pct:.1f}% / 日 {day_pct:.1f}% / 行业 {sector}",
                'score': round(score*100,2),
                'components': {
                    'week_momentum': round(week_momentum,4),
                    'day_momentum': round(day_momentum,4),
                    'sentiment': round(sentiment_norm,4),
                    'news_density': round(news_density,4),
                    'sector_strength': round(sector_strength,4)
                },
                'raw': {'week_pct': week_pct, 'day_pct': day_pct, 'avg_sent': avg_sent}
            })
        recommendations.sort(key=lambda x: x['score'], reverse=True)
        recommendations = recommendations[:10]

        elapsed = (datetime.utcnow() - started).total_seconds()
        return {
            'generated_at': datetime.utcnow().isoformat(),
            'elapsed_sec': elapsed,
            'daily': daily,
            'weekly': weekly,
            'summaries': summaries,
            'highlights': highlights,
            'themes': themes,
            'recommendations': recommendations,
            'sector_stats': sector_stats,
            'keyword_expansion_supported': llm_enabled,
            'methodology': {
                'steps': ['提取日/周涨跌幅前列股票','抓取近期相关新闻 (symbol 匹配)','LLM 摘要（或降级原文）','关键词频次 -> 初步主题','启发式动能推荐 (周>5% 且 日>0%)'],
                'llm': processor.llm_service,
                'limits': {'symbols': len(symbols), 'per_symbol_news': per_symbol_news},
                'status': 'ok' if llm_enabled else 'fallback-no-llm'
            }
        }
    except Exception as e:
        return {
            'generated_at': datetime.utcnow().isoformat(),
            'error': str(e),
            'highlights': ['分析失败，返回占位结果'],
            'themes': [],
            'recommendations': [],
            'sector_stats': [],
            'methodology': {'status': 'error', 'detail': 'exception in analyze'}
        }

@router.get("/expand_keywords")
def expand_keywords(limit: int = 20, db: Session = Depends(get_db)):
    """第二轮关键词扩散：基于当前 analyze() 逻辑得到的 summaries + themes 简化生成扩展关键词。
    为避免再次重复 LLM 调用，这里仅做启发式演示；若 LLM 可用则调用一次小提示词做真正扩展。
    """
    # 先拿到 analyze 基础结果（不重复 LLM 摘要，因为 analyze 已缓存/更新）
    base = analyze(limit=limit, db=db)
    base_keywords = []
    for sym, arr in (base.get('summaries') or {}).items():
        for a in arr:
            for kw in (a.get('keywords') or []):
                if isinstance(kw, str) and kw not in base_keywords and len(base_keywords) < 80:
                    base_keywords.append(kw)
    # 频次分组
    from collections import Counter
    freq = Counter([k.lower() for k in base_keywords])
    common = [k for k,_ in freq.most_common(30)]

    processor = LLMNewsProcessor()
    expanded = []
    raw_resp = None
    if processor.llm_service != 'none' and common:
        import asyncio
        prompt = (
            '你是金融分析助手。根据这些基础关键词生成 3-5 个主题，每个主题再给 5-8 个更细的检索扩展关键词，避免重复：\n' + ', '.join(common[:25]) +
            '\n请输出 JSON: [{"theme": "主题", "keywords": ["k1", "k2"]}]'
        )
        async def _call():
            res = await processor._call_azure_openai_responses(prompt) if processor.llm_service=='azure' else None
            return res
        try:
            raw_resp = asyncio.run(_call())
            # 解析 JSON（宽松）
            import json as _json
            try:
                expanded = _json.loads(raw_resp)
            except Exception:
                expanded = []
        except Exception:
            pass
    if not expanded:
        # fallback：按频次拆成 3 组
        g1, g2, g3 = common[:10], common[10:20], common[20:30]
        if g1: expanded.append({"theme": "高频主题", "keywords": g1})
        if g2: expanded.append({"theme": "次级主题", "keywords": g2})
        if g3: expanded.append({"theme": "长尾主题", "keywords": g3})
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "base_keywords": base_keywords,
        "expanded": expanded,
        "raw": raw_resp,
        "llm": processor.llm_service
    }
