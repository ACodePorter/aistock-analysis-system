#!/usr/bin/env python3
"""
Unit tests for NewsDeduplicator core behavior
"""
import sys
import os
import unittest
import asyncio

# Add the backend directory to the path
backend_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, backend_root)

from app.news.news_deduplication import NewsDeduplicator  # type: ignore


class TestDedup(unittest.TestCase):
    def setUp(self):
        self.d = NewsDeduplicator()

    def test_url_hash_normalization(self):
        h1 = self.d._generate_url_hash("https://example.com/News/Article?id=123#frag")
        h2 = self.d._generate_url_hash("https://example.com/news/article?id=123")
        self.assertEqual(h1, h2, "URL hash should ignore case, query, and fragment")

    def test_text_hash_stability(self):
        t1 = self.d._generate_text_hash("  Hello   World ")
        t2 = self.d._generate_text_hash("hello world")
        self.assertEqual(t1, t2, "Text hash should be whitespace and case insensitive")

    def test_content_similarity(self):
        c1 = "公司2025年Q3业绩大增，营收同比增长25%，净利润率提升。产品结构优化，成本下降。"
        c2 = "2025年第三季度，公司营收同比提升25%，净利率改善。产品结构优化并带动成本下行。"
        sim = self.d._calculate_content_similarity(c1, c2)
        self.assertGreater(sim, 0.1, f"Expected some similarity, got {sim}")

    def test_async_check_url_duplicate_new(self):
        async def run():
            res = await self.d._check_url_duplicate("https://example.com/a/b/c")
            self.assertFalse(res.is_duplicate)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
