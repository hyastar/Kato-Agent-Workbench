"""搜索结果发现片段的离线测试。"""

from __future__ import annotations

import unittest

from scripts.employment.browser.discovery import (
    build_queue,
    canonicalize_candidate,
    normalize_candidates,
)


class DiscoveryTests(unittest.TestCase):
    def test_xiaohongshu_search_result_url_is_canonicalized(self) -> None:
        href = "https://www.xiaohongshu.com/search_result/6af096e70000000023007175?xsec_token=ABC&xsec_source=pc_search"
        self.assertEqual(
            canonicalize_candidate("xiaohongshu", href),
            "https://www.xiaohongshu.com/explore/6af096e70000000023007175",
        )
        self.assertEqual(
            canonicalize_candidate(
                "xiaohongshu", "https://www.xiaohongshu.com/explore/6af096e70000000023007175?x=1"
            ),
            "https://www.xiaohongshu.com/explore/6af096e70000000023007175",
        )

    def test_zhihu_urls_strip_query_and_fragment(self) -> None:
        self.assertEqual(
            canonicalize_candidate(
                "zhihu", "https://www.zhihu.com/question/2098/answer/2100?share=1#x"
            ),
            "https://www.zhihu.com/question/2098/answer/2100",
        )
        self.assertEqual(
            canonicalize_candidate("zhihu", "https://zhuanlan.zhihu.com/p/12345?utm=1"),
            "https://zhuanlan.zhihu.com/p/12345",
        )

    def test_invalid_or_foreign_urls_are_rejected(self) -> None:
        self.assertIsNone(canonicalize_candidate("xiaohongshu", "https://example.com/explore/123"))
        self.assertIsNone(canonicalize_candidate("zhihu", "https://www.zhihu.com/search?q=x"))
        self.assertIsNone(canonicalize_candidate("zhihu", "https://evil.example/p/1"))

    def test_duplicate_candidates_are_collapsed(self) -> None:
        raw = [
            {"href": "https://www.xiaohongshu.com/search_result/6af096e70000000023007175?token=1", "text": "A"},
            {"href": "https://www.xiaohongshu.com/explore/6af096e70000000023007175?token=2", "text": "A again"},
            {"href": "https://www.xiaohongshu.com/explore/6ae767a10000000018027976", "text": "B"},
        ]
        candidates = normalize_candidates("xiaohongshu", raw)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["text"], "A")

    def test_queue_filters_known_urls(self) -> None:
        raw = [
            {"href": "https://www.zhihu.com/question/1", "text": "旧"},
            {"href": "https://www.zhihu.com/question/2", "text": "新"},
        ]
        queue = build_queue("zhihu", "秋招", raw, {"https://www.zhihu.com/question/1"})
        self.assertEqual(queue["unique_count"], 2)
        self.assertEqual(queue["new_count"], 1)
        self.assertEqual(queue["duplicate_count"], 1)
        self.assertEqual(queue["queue"][0]["canonical_url"], "https://www.zhihu.com/question/2")


if __name__ == "__main__":
    unittest.main()
