"""浏览器执行层契约、规范化与 checkpoint 的离线测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.employment.browser import ArticleTask, normalize_payload
from scripts.employment.browser.runner import task_from_dict, write_checkpoint


def _item(index: int, content: str | None = None, children: list | None = None) -> dict:
    return {
        "platform_comment_id": f"c{index}",
        "content": content or f"评论 {index}",
        "like_text": str(100 - index),
        "time_displayed": "2天前",
        "comment_level": 1,
        "children": children or [],
    }


def _task(limit: int = 50) -> ArticleTask:
    return ArticleTask(
        case_id="case",
        platform="xiaohongshu",
        cohort="2027",
        recruitment_stage="autumn",
        topic="experience",
        comment_limit=limit,
    )


class BrowserLayerTests(unittest.TestCase):
    def test_task_from_dict(self) -> None:
        task = task_from_dict(
            {"case_id": "c", "platform": "zhihu", "cohort": "2026", "comment_limit": 50}
        )
        self.assertEqual(task.platform, "zhihu")
        self.assertEqual(task.comment_limit, 50)

    def test_under_limit_is_complete(self) -> None:
        payload = {
            "title": "标题 - 小红书",
            "url": "https://www.xiaohongshu.com/explore/1",
            "displayed_total": 12,
            "items": [_item(index) for index in range(10)]
            + [_item(100, children=[_item(101), _item(102)])],
        }
        result = normalize_payload(payload, _task())
        self.assertEqual(result.title, "标题")
        self.assertEqual(result.collected_top_level, 11)
        self.assertEqual(result.collected_replies, 2)
        self.assertEqual(result.coverage_status, "complete")
        self.assertEqual(result.sort_basis, "visible_order")

    def test_over_limit_caps_and_never_claims_latest(self) -> None:
        payload = {
            "title": "标题",
            "url": "https://www.xiaohongshu.com/explore/1",
            "displayed_total": 300,
            "items": [_item(index) for index in range(60)],
        }
        result = normalize_payload(payload, _task())
        self.assertEqual(result.collected_top_level, 50)
        self.assertEqual(result.sort_basis, "high_likes")
        self.assertEqual(result.coverage_status, "partial")
        self.assertIn("最新排序", result.reason or "")

    def test_latest_verified_marks_mixed_strategy(self) -> None:
        payload = {
            "title": "标题",
            "url": "https://www.xiaohongshu.com/explore/1",
            "displayed_total": 300,
            "items": [_item(index) for index in range(60)],
        }
        result = normalize_payload(payload, _task(), latest_verified=True)
        self.assertEqual(result.sort_basis, "high_likes_then_latest")

    def test_contacts_are_redacted(self) -> None:
        payload = {
            "title": "标题",
            "url": "https://www.xiaohongshu.com/explore/1",
            "displayed_total": 1,
            "items": [_item(1, content="联系我 13812345678 或 a@b.com")],
        }
        result = normalize_payload(payload, _task())
        content = result.comments[0].content
        self.assertNotIn("13812345678", content)
        self.assertNotIn("a@b.com", content)
        self.assertIn("已脱敏", content)

    def test_no_comments_is_not_available(self) -> None:
        payload = {
            "title": "标题",
            "url": "https://www.xiaohongshu.com/explore/1",
            "displayed_total": None,
            "items": [],
        }
        result = normalize_payload(payload, _task())
        self.assertEqual(result.coverage_status, "not_available")
        self.assertEqual(result.collected_top_level, 0)

    def test_checkpoint_roundtrip(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "checkpoints" / "case.json"
        result = normalize_payload(
            {
                "title": "标题",
                "url": "https://www.xiaohongshu.com/explore/1",
                "displayed_total": 1,
                "items": [_item(1)],
            },
            _task(),
        )
        checkpoint = write_checkpoint(path, result.task, result)
        self.assertEqual(checkpoint["case_id"], "case")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["coverage_status"], "complete")


if __name__ == "__main__":
    unittest.main()
