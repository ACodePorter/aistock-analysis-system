#!/usr/bin/env python3
"""
URL filtering unit tests for NewsProcessor._is_article_like_url
"""
import sys
import os
import unittest

# Add the backend directory to the path
backend_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, backend_root)

from app.news_service import NewsProcessor  # type: ignore


class TestURLFiltering(unittest.TestCase):
    def setUp(self):
        self.processor = NewsProcessor()

    def assertKeeps(self, url: str, msg: str = ""):
        self.assertTrue(self.processor._is_article_like_url(url), msg or f"should keep: {url}")

    def assertDrops(self, url: str, msg: str = ""):
        self.assertFalse(self.processor._is_article_like_url(url), msg or f"should drop: {url}")

    def test_drop_common_non_article_pages(self):
        cases = [
            "https://finance.sina.com.cn/roll/index.d.html",
            "https://www.eastmoney.com/quote/000001.SZ.html",
            "https://moomoo.com/stock/TSLA-US/financials-income-statement",
            "https://www.investing.com/equities/apple-computer-inc",
            "https://money.163.com/keywords/1/7/7b2c8d85/1.html",
            "https://example.com/category/markets/",
            "https://example.com/search?q=stock",
        ]
        for url in cases:
            with self.subTest(url=url):
                self.assertDrops(url)

    def test_keep_article_like_pages(self):
        cases = [
            "https://finance.sina.com.cn/stock/observational/2025-09-01/doc-ikfxyz1234567.shtml",
            "https://www.reuters.com/world/china/china-stocks-rebound-on-policy-hopes-2025-09-01/",
            "https://www.ft.com/content/abcdef12-3456-7890-abcd-ef1234567890",
            "https://example.com/news/company-earnings-soar-in-q3-12345678.html",
        ]
        for url in cases:
            with self.subTest(url=url):
                self.assertKeeps(url)

    def test_yahoo_tw_rule(self):
        # Only /news/ should be kept for tw.stock.yahoo.com
        keep = "https://tw.stock.yahoo.com/news/%E5%8F%B0%E7%A9%8D%E9%9B%BB-%E7%9B%B8%E9%97%9C-20250901-123456"
        drop = "https://tw.stock.yahoo.com/quote/2330.TW"
        self.assertKeeps(keep)
        self.assertDrops(drop)


if __name__ == "__main__":
    unittest.main()
