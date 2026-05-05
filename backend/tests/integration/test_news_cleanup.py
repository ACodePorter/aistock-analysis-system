#!/usr/bin/env python3
"""
News cleanup API smoke test: run dry-run cleanup with minimal scope.
"""
import os
import sys
import json
import requests

BASE_URL = os.environ.get("API_URL", "http://localhost:8081")


def _print(msg: str):
    print(msg, flush=True)


def test_cleanup_dry_run():
    url = f"{BASE_URL}/api/news/cleanup"
    payload = {
        "symbol": "300251.SZ",
        "company_name": "光线传媒",
        "dry_run": True,
        "limit": 5,
        "offset": 0,
        "blacklist_non_cn": True,
        "blacklist_unrelated": True,
        "delete_blacklisted": False,
        "refresh_relevant": False,
        "check_summary_match": True,
        "max_concurrency": 3,
    }
    _print(f"POST {url} {json.dumps(payload, ensure_ascii=False)}")
    r = requests.post(url, json=payload, timeout=60)
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
    data = r.json()
    assert isinstance(data, dict)
    assert data.get("status") == "ok"
    for k in ("processed", "blacklisted", "deleted", "refreshed"):
        assert k in data


if __name__ == "__main__":
    test_cleanup_dry_run()
    print("OK")
