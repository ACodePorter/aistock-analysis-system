import json
import time
import traceback

def check_redis():
    try:
        import redis
        r = redis.Redis(host='127.0.0.1', port=6379, db=0, decode_responses=True)
        ok = r.ping()
        return True, r
    except Exception as e:
        return False, str(e)


def check_endpoint(limit=200, fundflow='auto'):
    try:
        import requests
        url = f'http://127.0.0.1:8081/api/watchlist/snapshot?limit={limit}&fundflow_prefer={fundflow}'
        start = time.time()
        resp = requests.get(url, timeout=15)
        elapsed = time.time()-start
        try:
            j = resp.json()
            rows = j.get('rows') if isinstance(j, dict) else None
            count = len(rows) if isinstance(rows, list) else None
        except Exception:
            j = resp.text[:1000]
            count = None
        return {'status_code': resp.status_code, 'elapsed': elapsed, 'json_preview': j if isinstance(j, (dict,list)) else str(j)[:1000], 'count': count}
    except Exception as e:
        return {'error': str(e), 'trace': traceback.format_exc()}


if __name__ == '__main__':
    ok, r = check_redis()
    if ok:
        print('Redis: reachable')
        # inspect cache key
        key = 'watchlist_snapshot:200:auto'
        try:
            val = r.get(key)
            ttl = r.ttl(key)
            print('Cache key', key, 'exists' if val else 'not found', 'ttl=', ttl)
            if val:
                print('cached len', len(val))
        except Exception as e:
            print('Redis get error:', e)
    else:
        print('Redis: not reachable:', r)

    print('\nCalling snapshot endpoint once...')
    out = check_endpoint()
    print(json.dumps(out, ensure_ascii=False, indent=2))
