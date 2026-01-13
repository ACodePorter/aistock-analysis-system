#!/usr/bin/env python3
"""
Unit tests for content quality helpers: mojibake repair, chinese ratio, relevance filter
"""
import sys
import os
import unittest

backend_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, backend_root)

from app.news.news_service import NewsProcessor  # type: ignore


class TestContentQuality(unittest.TestCase):
    def setUp(self):
        self.p = NewsProcessor()

    def test_chinese_ratio(self):
        cn = "这是中文内容，包含A股与上证指数。"
        en = "This is english text."
        self.assertGreater(self.p._chinese_ratio(cn), 0.3)
        self.assertLess(self.p._chinese_ratio(en), 0.05)

    def test_mojibake_repair(self):
        # Typical UTF-8 -> Latin1 mojibake of "测试中文"
        broken = "æµè¯ä¸­æ"
        fixed = self.p._maybe_fix_mojibake(broken)
        # After repair, chinese ratio should increase
        self.assertGreaterEqual(self.p._chinese_ratio(fixed), self.p._chinese_ratio(broken))

    def test_relevance_a_share(self):
        title = "天齐锂业公告：上半年业绩预增"
        content = "公司公告显示，预计净利润同比增长。A股市场反应积极。"
        url = "https://finance.sina.com.cn/stock/2025-09-19/doc-xxxx.shtml"
        self.assertTrue(self.p._is_relevant_to_a_share(title, content, url, "002466.SZ"))


if __name__ == "__main__":
    unittest.main()
