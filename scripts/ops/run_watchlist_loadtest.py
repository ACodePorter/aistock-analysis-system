import subprocess
import time
import sys
import statistics
import requests
import os

sys.path.insert(0, 'backend')
import app.main as m

env = os.environ.copy()
# Use fresh TTL=30 for this test run (overrides code default)
env['WATCHLIST_FRESH_TTL'] = env.get('WATCHLIST_FRESH_TTL', '30')
env['WATCHLIST_STALE_TTL'] = env.get('WATCHLIST_STALE_TTL', '300')
# Ensure backend package is importable by uvicorn subprocess
env['PYTHONPATH'] = env.get('PYTHONPATH', '')
if not env['PYTHONPATH']:
    env['PYTHONPATH'] = 'backend'
# Allow skipping server startup when running client-only against an existing server
skip_server = os.environ.get('SKIP_SERVER', '') == '1'
p = None
if not skip_server:
    p = subprocess.Popen(['uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8081'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    print('uvicorn pid', p.pid)
# wait for server to start (poll endpoint until ready)
print('waiting for server to be ready...')
ready = False
start_wait = time.time()
while time.time() - start_wait < 30:
    # if subprocess has exited, print its captured output for diagnosis
    if p is not None and p.poll() is not None:
        try:
            out = p.stdout.read().decode('utf-8', errors='replace')
            print('uvicorn process exited; output:\n', out)
        except Exception:
            pass
        break
    try:
        r = requests.get('http://127.0.0.1:8081/', timeout=2)
        if r.status_code in (200, 404):
            ready = True
            break
    except Exception:
        pass
    time.sleep(1)
if not ready:
    print('server did not become ready within 30s, continuing (may timeout)')

# Target server (allow overriding for tests)
TARGET_URL = os.environ.get('TARGET_URL', 'http://127.0.0.1:8081')
# warm-up requests to populate cache before the concurrent load
url = f"{TARGET_URL}/api/watchlist/snapshot?limit=50"
def warm_up(url, n=5):
    print('Warm-up requests to', url)
    for i in range(n):
        try:
            # First warm-up request forces recompute to populate fresh cache
            if i == 0 and '?' in url:
                sep = '&'
            else:
                sep = '?' if '?' not in url else '&'
            req_url = url if i != 0 else (url + sep + '_force_recompute=true')
            r = requests.get(req_url, timeout=10)
            print('warm', i, 'status', r.status_code, 'len', len(r.content))
        except Exception as e:
            print('warm', i, 'err', e)
        time.sleep(0.5)

warm_up(url, n=5)

from concurrent.futures import ThreadPoolExecutor, as_completed


def run_load(concurrency=30, total=200, path='/api/watchlist/snapshot?limit=50'):
    url = f"{TARGET_URL}{path}"
    times = []
    statuses = []

    def task(i):
        t0 = time.time()
        try:
            r = requests.get(url, timeout=10)
            dt = time.time() - t0
            return (dt, r.status_code, len(r.content))
        except Exception as e:
            return (None, 'err', str(e))

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = [ex.submit(task, i) for i in range(total)]
        for f in as_completed(futs):
            res = f.result()
            times.append(res[0])
            statuses.append(res[1])

    ok = sum(1 for s in statuses if s == 200)
    errs = sum(1 for s in statuses if s != 200 and s != 'err')
    fail = sum(1 for s in statuses if s == 'err')
    done_times = [t for t in times if t is not None]
    sorted_done = sorted(done_times) if done_times else []
    p95 = (sorted_done[int(len(sorted_done) * 0.95)] if sorted_done else None)
    p99 = (sorted_done[int(len(sorted_done) * 0.99)] if sorted_done else None)
    return {
        'total': total,
        'ok': ok,
        'fail': fail,
        'errs': errs,
        'min': min(done_times) if done_times else None,
        'p50': statistics.median(done_times) if done_times else None,
        'p95': p95,
        'p99': p99,
    }


print('Baseline LOCAL_CACHE_MAX=', getattr(m, '_LOCAL_CACHE_MAX', None))
res1 = run_load(concurrency=40, total=160)
print('baseline', res1)

# Query server-side internal metrics to get accurate cache stats
try:
    mm = requests.get('http://127.0.0.1:8081/internal/metrics', timeout=5).json()
    hits = mm.get('local_cache_hits', 0)
    misses = mm.get('local_cache_misses', 0)
    redis_hits = mm.get('redis_cache_hits', 0)
    redis_misses = mm.get('redis_cache_misses', 0)
    redis_sets = mm.get('redis_cache_sets', 0)
    miss_rate = misses / (hits + misses) if (hits + misses) > 0 else 0
    print('server metrics', mm)
    print('hits,misses,miss_rate', hits, misses, miss_rate)
except Exception as e:
    print('failed to fetch /internal/metrics', e)
    hits = getattr(m, '_local_cache_hits', 0)
    misses = getattr(m, '_local_cache_misses', 0)
    miss_rate = misses / (hits + misses) if (hits + misses) > 0 else 0
    print('parent process counts fallback', hits, misses, miss_rate)
if miss_rate > 0.05:
    print('Increasing LOCAL_CACHE_MAX to 2048 and retest')
    m._LOCAL_CACHE_MAX = 2048
    # clear local cache
    with m._local_cache_lock:
        m._local_cache.clear()
        m._local_cache_hits = 0
        m._local_cache_misses = 0
    res2 = run_load(concurrency=40, total=160)
    print('after increase', res2)
else:
    print('Miss rate low; skipping resize')

# Extended stress test: higher concurrency and more total requests to collect p95/p99
ext_con = int(os.getenv('EXT_CONC', '80'))
ext_total = int(os.getenv('EXT_TOTAL', '1000'))
print(f"\nStarting extended stress test (concurrency={ext_con}, total={ext_total})")
res_ext = run_load(concurrency=ext_con, total=ext_total)
print('extended', res_ext)
try:
    mm2 = requests.get('http://127.0.0.1:8081/internal/metrics', timeout=10).json()
    print('server metrics after extended test', mm2)
except Exception as e:
    print('failed to fetch /internal/metrics after extended test', e)

if p is not None:
    p.terminate()
    p.wait()
    print('server stopped')
