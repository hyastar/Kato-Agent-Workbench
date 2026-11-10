"""V6 阶段 4 离线测试：时间清洗、评论树、50 条规则、内容分类。

不启动浏览器：只验证纯逻辑（真实页面验证见 docs/acceptance）。
"""

from __future__ import annotations

import unittest

from kato_engine.collection.classification import classify
from kato_engine.collection.comments import select_comment_nodes
from kato_engine.platforms.base import CommentBundle, CommentNode
from kato_engine.platforms.xiaohongshu import clean_date_text
from kato_engine.platforms.zhihu import ZhihuAdapter, clean_published_text, published_iso


class XhsDateTests(unittest.TestCase):
    def test_region_suffix_is_dropped(self) -> None:
        self.assertEqual(clean_date_text("05-24河北"), "05-24")
        self.assertEqual(clean_date_text("3天前 上海"), "3天前")

    def test_edit_prefix_is_dropped(self) -> None:
        self.assertEqual(clean_date_text("编辑于 04-15"), "04-15")

    def test_unknown_text_returns_none(self) -> None:
        self.assertIsNone(clean_date_text("刚刚"))
        self.assertIsNone(clean_date_text(None))


class ZhihuTimeTests(unittest.TestCase):
    def test_location_is_removed(self) -> None:
        cleaned = clean_published_text("发布于2025-09-11 15:14\n・湖北")
        self.assertEqual(cleaned, "2025-09-11 15:14")
        self.assertNotIn("湖北", cleaned or "")

    def test_iso_only_when_absolute(self) -> None:
        self.assertEqual(published_iso("2025-09-11 15:14"), "2025-09-11T15:14:00")
        self.assertEqual(published_iso("2025-09-11"), "2025-09-11")
        self.assertIsNone(published_iso("3 天前"))

    def test_relative_time_kept_as_displayed(self) -> None:
        self.assertEqual(clean_published_text("3 天前"), "3 天前")


class ThreadTreeTests(unittest.TestCase):
    def test_indent_builds_parent_child(self) -> None:
        adapter = ZhihuAdapter()
        raw = [
            {"left": 342, "text": "一级 A"},
            {"left": 376, "text": "回复 A-1"},
            {"left": 376, "text": "回复 A-2"},
            {"left": 342, "text": "一级 B"},
            {"left": 410, "text": "二级回复 B-1-1"},
        ]
        roots = adapter._build_tree(raw)
        self.assertEqual([node.content for node in roots], ["一级 A", "一级 B"])
        self.assertEqual(len(roots[0].children), 2)
        self.assertEqual(roots[0].children[0].level, 2)
        self.assertEqual(len(roots[1].children), 1)
        self.assertEqual(roots[1].children[0].level, 2)

    def test_same_indent_is_not_nested(self) -> None:
        adapter = ZhihuAdapter()
        raw = [{"left": 100, "text": "A"}, {"left": 110, "text": "B"}]
        roots = adapter._build_tree(raw)
        self.assertEqual(len(roots), 2)


class SelectionTests(unittest.TestCase):
    def _nodes(self, count: int, likes: list[int] | None = None) -> list[CommentNode]:
        return [
            CommentNode(
                content=f"评论 {index}",
                platform_comment_id=f"c{index}",
                like_count=(likes[index] if likes else index),
            )
            for index in range(count)
        ]

    def test_all_taken_when_under_limit(self) -> None:
        bundle = CommentBundle(nodes=self._nodes(10), displayed_total=10)
        selection = select_comment_nodes(bundle, limit=50)
        self.assertEqual(selection.collected_top_level, 10)
        self.assertEqual(selection.coverage_status, "complete")
        self.assertEqual(selection.sort_basis, "visible_order")

    def test_over_limit_selects_high_likes_first(self) -> None:
        likes = list(range(60))
        bundle = CommentBundle(nodes=self._nodes(60, likes), displayed_total=60)
        selection = select_comment_nodes(bundle, limit=50)
        self.assertEqual(selection.collected_top_level, 50)
        self.assertEqual(selection.coverage_status, "partial")
        self.assertEqual(selection.sort_basis, "high_likes")
        self.assertEqual(selection.nodes[0].like_count, 59)

    def test_replies_do_not_consume_quota(self) -> None:
        parent = CommentNode(content="父", platform_comment_id="p1", like_count=1)
        parent.children = [
            CommentNode(content=f"子{index}", platform_comment_id=f"c{index}", level=2)
            for index in range(30)
        ]
        bundle = CommentBundle(nodes=[parent], displayed_total=31)
        selection = select_comment_nodes(bundle, limit=50)
        self.assertEqual(selection.collected_top_level, 1)
        self.assertEqual(selection.collected_replies, 30)
        self.assertEqual(selection.coverage_status, "complete")

    def test_missing_displayed_total_is_partial(self) -> None:
        bundle = CommentBundle(nodes=self._nodes(3), displayed_total=None)
        selection = select_comment_nodes(bundle, limit=50)
        self.assertEqual(selection.coverage_status, "partial")
        self.assertIn("未显示评论总数", selection.reason or "")

    def test_payload_has_no_author_fields(self) -> None:
        node = CommentNode(content="内容", platform_comment_id="c1", like_count=3)
        payload = node.to_payload()
        for forbidden in ("author", "nickname", "avatar", "user_id", "ip_location"):
            self.assertNotIn(forbidden, payload)


class ClassificationTests(unittest.TestCase):
    def test_salary_article(self) -> None:
        result = classify("26届毕业生到手工资5000", "试用期三个月，工资到手 5000，房租 1500。")
        self.assertEqual(result.employment_topic, "salary")
        self.assertEqual(result.graduation_cohort, "2026")
        self.assertEqual(result.event_year, 2026)
        self.assertEqual(result.employment_status, "probation")

    def test_layoff_article(self) -> None:
        result = classify("27届还没入职就被裁了", "公司裁员，应届生被毁约，现在失业在家。")
        self.assertEqual(result.employment_topic, "layoff")
        self.assertEqual(result.graduation_cohort, "2027")

    def test_irrelevant_text_is_unmatched(self) -> None:
        result = classify("今天做了番茄炒蛋", "先把鸡蛋打散，番茄切块，热锅下油。")
        self.assertFalse(result.matched_topic)
        self.assertIsNone(result.employment_topic)
        self.assertEqual(result.legacy_topic, "other")

    def test_recruitment_ad_detection(self) -> None:
        result = classify(
            "招聘｜机械设计岗位",
            "岗位职责：负责设备设计；任职要求：本科以上；简历投递邮箱。",
        )
        self.assertEqual(result.experience_type, "recruitment_ad")

    def test_recruitment_stage(self) -> None:
        result = classify("2027届秋招记录", "面试了五家公司，最后签了三方。")
        self.assertEqual(result.recruitment_stage, "autumn")
        self.assertEqual(result.legacy_topic, "recruitment")


if __name__ == "__main__":
    unittest.main()
