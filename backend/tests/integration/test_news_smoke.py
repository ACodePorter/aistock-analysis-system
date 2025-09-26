#!/usr/bin/env python3
"""
News API smoke test: validate core endpoints respond and return basic structure.
"""
import os
import sys
import json
import requests
from datetime import datetime


BASE_URL = os.environ.get("API_URL", "http://localhost:8080")


def _print(msg: str):
    print(msg, flush=True)


def test_articles_list():
    url = f"{BASE_URL}/api/news/articles?limit=3"
    _print(f"GET {url}")
    r = requests.get(url, timeout=10)
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
    data = r.json()
    assert isinstance(data, dict)
    # Endpoint returns 'articles' list with pagination fields
    assert "articles" in data and isinstance(data["articles"], list)
    _print(f"articles={len(data['articles'])}")


def test_metrics_endpoint():
    url = f"{BASE_URL}/api/news/metrics"
    _print(f"GET {url}")
    r = requests.get(url, timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert "totals" in data and isinstance(data["totals"], dict)
    totals = data["totals"]
    # basic shape checks
    for k in ("articles_total", "articles_with_content", "articles_with_summary"):
        assert k in totals
    _print(f"totals={json.dumps(totals)}")


def test_backfill_dry_run():
    # conservative backfill to avoid side effects; ok if processed=0
    url = (
        f"{BASE_URL}/api/news/backfill?limit=3&only_missing_content=true&only_missing_summary=true&skip_non_article=true"
    )
    _print(f"POST {url}")
    r = requests.post(url, timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, dict)
    assert "status" in data
    _print(f"backfill.status={data.get('status')}, processed={data.get('processed')}")


if __name__ == "__main__":
    # Allow running standalone
    test_articles_list()
    test_metrics_endpoint()
    test_backfill_dry_run()
    print("OK")
