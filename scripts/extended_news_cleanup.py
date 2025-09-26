#!/usr/bin/env python3
"""
Extended cleanup and backfill helper for the news dataset.

- Runs dry-run cleanup for a set of non-article URL patterns and prints match counts.
- Optionally executes deletions for matched patterns.
- Triggers a targeted backfill for missing content/summaries while skipping non-articles.
- Prints a concise validation summary of the latest items.

Usage examples:
  python scripts/extended_news_cleanup.py --base http://localhost:8080 --dry-run
  python scripts/extended_news_cleanup.py --base http://localhost:8080 --execute
  python scripts/extended_news_cleanup.py --execute --skip-validation

You can also pass extra patterns via repeated --extra-pattern flags.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from typing import Any, Dict, Iterable, List, Tuple

import requests


DEFAULT_PATTERNS: Tuple[str, ...] = (
    # Sina corp bulletins (non-article listings)
    "%vip.stock.finance.sina.com.cn/corp/go.php/vCB_Bulletin/%",
    "%vip.stock.finance.sina.com.cn/corp/go.php/vCB_AllBulletin/%",
    # Sina corp all-news listing (non-article list hub)
    "%vip.stock.finance.sina.com.cn/corp/view/vCB_AllNews%",
    "%vip.stock.finance.sina.com.cn/corp/go.php/vCB_AllNews/%",
    # Sina corp manager pages (non-article company profile listings)
    "%vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpManager/%",
    "%money.finance.sina.com.cn/corp/go.php/vCI_CorpManager/%",
    # Sina bulletins on money.finance subdomain
    "%money.finance.sina.com.cn/corp/go.php/vCB_Bulletin/%",
    "%money.finance.sina.com.cn/corp/go.php/vCB_AllBulletin/%",
    # Moomoo JS-gated financials pages (not article content)
    "%moomoo.com%/stock/%/financials-%",
    # Moomoo generic stock pages (JS-gated, not articles)
    "%moomoo.com%/hant/stock/%",
    "%moomoo.com%/hans/stock/%",
    # Futu NiuNiu generic stock pages (not articles)
    "%www.futunn.com%/stock/%",
    # Eastmoney quote/concept pages (symbol pages, not articles)
    "%quote.eastmoney.com/unify/r/%",
    "%quote.eastmoney.com/concept/%",
    # Eastmoney UGC/community (not editorial articles)
    "%guba.eastmoney.com/%",
    "%caifuhao.eastmoney.com/%",
    "%emdata.eastmoney.com/%",
    # AASTOCKS hot topic content stub page
    "%aastocks.com%/news/china-hot-topic-content.aspx%",
    # Obvious list/calendar hubs (not articles)
    "%www.cls.cn/investKalendar%",
    "%money.163.com/latest/%",
    "%rili.jin10.com%",
    "%www.cs.com.cn/xwzx/hg/%",
    "%xuangutong.com.cn/live%",
    "%xiaoyuzhoufm.com/podcast/%",
    "%www.globalxetfs.com.hk%/funds/%",
    # Reuters company pages (profiles/quote hubs)
    "%www.reuters.com/markets/companies/%/profile%",
    "%www.reuters.com/markets/companies/%",
    # Sina realstock company hubs
    "%finance.sina.com.cn/realstock/company/%",
    # Tencent quote hub
    "%gu.qq.com/%",
    # JRJ summary hubs
    "%summary.jrj.com.cn/%",
)


def http_delete(base: str, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{base}{path}"
    r = requests.delete(url, params=params, timeout=120)
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return {"raw": r.text}


def http_post(base: str, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{base}{path}"
    r = requests.post(url, params=params, timeout=120)
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return {"raw": r.text}


def http_get(base: str, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{base}{path}"
    r = requests.get(url, params=params, timeout=120)
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return {"raw": r.text}


def summarize_cleanup_result(result: Dict[str, Any]) -> str:
    # Try to normalize a couple of expected fields; otherwise fall back to raw
    keys = result.keys()
    parts = []
    for field in ("matched", "deleted", "skipped", "limit", "dry_run"):
        if field in keys:
            parts.append(f"{field}={result[field]}")
    # Show a tiny sample if provided
    sample = result.get("sample") or result.get("samples")
    if isinstance(sample, list) and sample:
        show = sample[:3]
        parts.append(f"sample={show}...")
    if parts:
        return ", ".join(parts)
    # Fallback: compact raw
    raw = result.get("raw") or result
    s = str(raw)
    if len(s) > 200:
        s = s[:200] + "..."
    return s


def run_cleanup(base: str, patterns: Iterable[str], execute: bool, limit: int) -> List[Tuple[str, Dict[str, Any], Dict[str, Any] | None]]:
    results: List[Tuple[str, Dict[str, Any], Dict[str, Any] | None]] = []
    for p in patterns:
        # Dry-run first
        dry = http_delete(base, "/api/news/cleanup/non-articles", {
            "pattern": p,
            "dry_run": "true",
            "limit": str(limit),
        })
        print(f"- DRY-RUN for pattern: {p}\n  {summarize_cleanup_result(dry)}")

        post_res: Dict[str, Any] | None = None
        # Decide whether to execute based on a non-zero match if available
        matched = dry.get("matched")
        should_execute = execute and (matched is None or (isinstance(matched, int) and matched > 0))
        if should_execute:
            post_res = http_delete(base, "/api/news/cleanup/non-articles", {
                "pattern": p,
                "dry_run": "false",
                "limit": str(limit),
            })
            print(f"  EXECUTED delete: {summarize_cleanup_result(post_res)}")
        results.append((p, dry, post_res))
    return results


def run_backfill(base: str, limit: int, concurrency: int) -> Dict[str, Any]:
    params = {
        "limit": str(limit),
        "only_missing_summary": "true",
        "only_missing_content": "true",
        "skip_non_article": "true",
        "concurrency": str(concurrency),
    }
    res = http_post(base, "/api/news/backfill", params)
    return res


def validate_latest(base: str, limit: int = 30) -> List[Dict[str, Any]]:
    data = http_get(base, "/api/news/articles", {
        "limit": str(limit),
        "offset": "0",
        "include_content": "true",
    })
    # Accept either a bare list or an object with an 'articles' array
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        articles = data.get("articles") or data.get("data")
        if isinstance(articles, list):
            return articles
    print("Validation returned a non-list payload:", data)
    return []


def print_validation_summary(items: List[Dict[str, Any]], max_rows: int = 30) -> None:
    def trunc(s: Any, n: int) -> str:
        t = str(s) if s is not None else ""
        t = t.replace("\n", " ").strip()
        return t if len(t) <= n else t[: n - 1] + "…"

    print("\nValidation sample (latest items):")
    header = f"{'id':>5}  {'source':<18} {'title':<44} {'url':<60}"
    print(header)
    print("-" * len(header))
    for i, it in enumerate(items[:max_rows]):
        _id = it.get("id") or it.get("_id")
        source = trunc(it.get("source", ""), 18)
        title = trunc(it.get("title", ""), 44)
        url = trunc(it.get("url", ""), 60)
        print(f"{str(_id):>5}  {source:<18} {title:<44} {url:<60}")


def parse_args(argv: List[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Extended cleanup and backfill for news dataset",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              python scripts/extended_news_cleanup.py --base http://localhost:8080 --dry-run
              python scripts/extended_news_cleanup.py --execute --limit 5000 --backfill-limit 200 --concurrency 5
              python scripts/extended_news_cleanup.py --execute --skip-validation 
            """
        ),
    )
    ap.add_argument("--base", default="http://localhost:8080", help="Base URL of the service (default: %(default)s)")
    ap.add_argument("--dry-run", action="store_true", help="Only perform dry-run cleanup (no deletions)")
    ap.add_argument("--execute", action="store_true", help="Execute deletions after dry-run if matches found")
    ap.add_argument("--limit", type=int, default=5000, help="Max items to consider per pattern (default: %(default)s)")
    ap.add_argument("--backfill-limit", type=int, default=200, help="Backfill limit (only_missing_* true) (default: %(default)s)")
    ap.add_argument("--concurrency", type=int, default=5, help="Backfill concurrency (default: %(default)s)")
    ap.add_argument("--skip-validation", action="store_true", help="Skip validation fetch at the end")
    ap.add_argument(
        "--extra-pattern",
        action="append",
        default=[],
        help="Additional LIKE patterns to include (use %% wildcards). Can be repeated.",
    )
    return ap.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    if not (args.dry_run or args.execute):
        print("Please specify either --dry-run or --execute (or both).", file=sys.stderr)
        return 2

    patterns: List[str] = list(DEFAULT_PATTERNS)
    if args.extra_pattern:
        patterns.extend(args.extra_pattern)

    print(f"Base: {args.base}")
    print("Patterns to check:")
    for p in patterns:
        print(f"  - {p}")

    results = run_cleanup(args.base, patterns, execute=args.execute, limit=args.limit)

    # Backfill after execution phase
    if args.execute:
        print("\nRunning backfill (only_missing_* and skip_non_article=true)...")
        bf = run_backfill(args.base, limit=args.backfill_limit, concurrency=args.concurrency)
        print("Backfill result:", bf)

    # Validation
    if not args.skip_validation:
        items = validate_latest(args.base, limit=30)
        print_validation_summary(items)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
