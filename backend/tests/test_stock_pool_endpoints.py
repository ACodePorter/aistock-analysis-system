"""
股票池功能端到端测试脚本

运行方式: ENABLE_SCHEDULER=0 STOCK_POOL_BACKFILL=0 python tests/test_stock_pool_endpoints.py
"""

import os
import sys
import time
import json
import subprocess
import urllib.request
import urllib.error

PORT = int(os.environ.get("TEST_PORT", "8097"))
BASE = f"http://127.0.0.1:{PORT}"

def request(method, path, body=None, timeout=30):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read()) if e.readable() else {"detail": str(e)}
    except Exception as e:
        return 0, {"error": str(e)}

def test_all():
    results = []

    def check(name, ok, detail=""):
        status = "PASS" if ok else "FAIL"
        results.append((name, status, detail))
        print(f"  [{status}] {name}" + (f" -- {detail}" if detail else ""))

    print("\n=== 股票池端到端测试 ===\n")

    # 1) GET /api/stock-pool/stats
    code, data = request("GET", "/api/stock-pool/stats")
    check("GET /stats", code == 200, f"status={code}, total_active={data.get('total_active')}")

    # 2) GET /api/stock-pool (list)
    code, data = request("GET", "/api/stock-pool?limit=5&offset=0")
    check("GET /list", code == 200, f"status={code}, count={data.get('count')}")

    # 3) POST /api/stock-pool/add
    code, data = request("POST", "/api/stock-pool/add", {"symbol": "600519", "name": "贵州茅台"})
    check("POST /add (600519)", code == 200, f"status={code}, action={data.get('action')}")

    # 4) POST /api/stock-pool/add (duplicate -> update)
    code, data = request("POST", "/api/stock-pool/add", {"symbol": "600519"})
    check("POST /add dup", code == 200 and data.get("action") == "updated", f"status={code}, action={data.get('action')}")

    # 5) POST /api/stock-pool/add (another stock)
    code, data = request("POST", "/api/stock-pool/add", {"symbol": "000858", "name": "五粮液"})
    check("POST /add (000858)", code == 200, f"status={code}, action={data.get('action')}")

    # 6) GET /api/stock-pool (verify added)
    code, data = request("GET", "/api/stock-pool?limit=10")
    symbols = [r["symbol"] for r in data.get("rows", [])]
    check("GET /list has 600519", "600519.SH" in symbols, f"symbols={symbols}")
    check("GET /list has 000858", "000858.SZ" in symbols, f"symbols={symbols}")

    # 7) GET /api/stock-pool/stats (updated)
    code, data = request("GET", "/api/stock-pool/stats")
    check("GET /stats updated", code == 200 and data.get("total_active", 0) >= 2, f"total_active={data.get('total_active')}")

    # 8) GET /api/stock-pool/search
    code, data = request("GET", "/api/stock-pool/search?q=600519", timeout=20)
    check("GET /search (600519)", code == 200, f"count={data.get('count')}")
    if data.get("results"):
        first = data["results"][0]
        check("search result has in_pool", first.get("in_pool") is True or first.get("in_pool") is False, f"in_pool={first.get('in_pool')}")

    # 9) DELETE /api/stock-pool/000858.SZ
    code, data = request("DELETE", "/api/stock-pool/000858.SZ")
    check("DELETE (000858)", code == 200 and data.get("ok"), f"status={code}")

    # 10) DELETE again -> 404
    code, data = request("DELETE", "/api/stock-pool/000858.SZ")
    check("DELETE dup -> 404", code == 404, f"status={code}")

    # 11) GET /api/stock-pool/backfill/status
    code, data = request("GET", "/api/stock-pool/backfill/status")
    check("GET /backfill/status", code == 200, f"running={data.get('running')}")

    # 12) POST /api/stock-pool/backfill
    code, data = request("POST", "/api/stock-pool/backfill", {"months": 1})
    check("POST /backfill", code == 200, f"message={data.get('message')}")

    # 13) GET /api/stock-pool?source=manual filter
    code, data = request("GET", "/api/stock-pool?source=manual")
    check("GET /list source=manual", code == 200, f"count={data.get('count')}")

    # Cleanup: remove test stock
    request("DELETE", "/api/stock-pool/600519.SH")

    # Summary
    print("\n=== 测试结果汇总 ===")
    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"  通过: {passed}, 失败: {failed}, 总计: {len(results)}")
    if failed:
        print("\n  失败项:")
        for name, s, detail in results:
            if s == "FAIL":
                print(f"    - {name}: {detail}")
    return failed == 0

if __name__ == "__main__":
    success = test_all()
    sys.exit(0 if success else 1)
