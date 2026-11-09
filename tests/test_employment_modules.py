"""就业情报模块化组件的离线测试（V4 阶段 2）。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import db
from scripts.employment import artifacts, deduplicate, markdown_export, repository, validate
from scripts.employment.analytics import article_summary, comment_summary
from scripts.employment.normalize import normalize_url, redact_contacts
from scripts.employment.validate import ValidationError


class NormalizeTests(unittest.TestCase):
    def test_url_normalization(self) -> None:
        self.assertEqual(
            normalize_url("HTTPS://Example.COM/Path?q=1#frag"),
            "https://example.com/Path?q=1",
        )
        with self.assertRaises(ValueError):
            normalize_url("not-a-url")

    def test_article_identity_matches_db(self) -> None:
        url = "https://www.zhihu.com/question/1#answer"
        self.assertEqual(
            deduplicate.article_identity("zhihu", url),
            db.research_item_identity("zhihu", url),
        )

    def test_contact_redaction(self) -> None:
        text, changed = redact_contacts("联系 13812345678 或 a@b.com，微信 abc12345")
        self.assertTrue(changed)
        for raw in ("13812345678", "a@b.com", "abc12345"):
            self.assertNotIn(raw, text)
        self.assertIn("已脱敏", text)


class CommentDedupeTests(unittest.TestCase):
    def test_platform_id_is_primary_key(self) -> None:
        first = deduplicate.comment_dedupe_key("ri_a", platform_comment_id="c1")
        second = deduplicate.comment_dedupe_key("ri_a", platform_comment_id="c1", content="不同")
        self.assertEqual(first, second)

    def test_same_text_different_parents_not_merged(self) -> None:
        first = deduplicate.comment_dedupe_key(
            "ri_a", parent_comment_id="p1", content="同样的话", comment_level=2
        )
        second = deduplicate.comment_dedupe_key(
            "ri_a", parent_comment_id="p2", content="同样的话", comment_level=2
        )
        self.assertNotEqual(first, second)

    def test_top_level_and_reply_not_merged(self) -> None:
        top = deduplicate.comment_dedupe_key("ri_a", content="同样的话", comment_level=1)
        reply = deduplicate.comment_dedupe_key(
            "ri_a", parent_comment_id="p1", content="同样的话", comment_level=2
        )
        self.assertNotEqual(top, reply)


class CommentSelectionTests(unittest.TestCase):
    def _candidates(self, count: int) -> list[dict[str, object]]:
        return [
            {"id": index, "like_count": index % 7, "order": index} for index in range(count)
        ]

    def test_under_limit_collects_all(self) -> None:
        selected, basis = validate.select_comments(self._candidates(12), 12)
        self.assertEqual(len(selected), 12)
        self.assertEqual(basis, "visible_order")

    def test_exactly_fifty(self) -> None:
        selected, basis = validate.select_comments(self._candidates(50), 50)
        self.assertEqual(len(selected), 50)
        self.assertEqual(basis, "visible_order")

    def test_over_limit_uses_30_high_likes_plus_20_latest(self) -> None:
        candidates = self._candidates(300)
        selected, basis = validate.select_comments(candidates, 300)
        self.assertEqual(len(selected), 50)
        self.assertEqual(basis, "high_likes_then_latest")
        ids = [item["id"] for item in selected]
        self.assertEqual(len(set(ids)), 50)

        high_ids = {
            item["id"]
            for item in sorted(
                candidates, key=lambda row: (-int(row["like_count"]), int(row["order"]))
            )[:30]
        }
        latest_ids = {
            item["id"]
            for item in sorted(candidates, key=lambda row: int(row["order"]), reverse=True)[:20]
        }
        self.assertTrue(high_ids <= set(ids))
        self.assertTrue(latest_ids <= set(ids))

    def test_missing_like_counts_fall_back_to_visible_order(self) -> None:
        candidates = [{"id": index, "like_count": None, "order": index} for index in range(80)]
        selected, basis = validate.select_comments(candidates, 80)
        self.assertEqual(len(selected), 50)
        self.assertEqual(basis, "visible_order")


class ValidationTests(unittest.TestCase):
    def test_relative_time_is_not_converted(self) -> None:
        row = validate.validate_comment(
            {
                "research_item_id": "ri_a",
                "content": "评论",
                "published_time_displayed": "2天前",
            }
        )
        self.assertIsNone(row["published_at"])
        self.assertEqual(row["published_time_displayed"], "2天前")

    def test_author_fields_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            validate.validate_comment(
                {"research_item_id": "ri_a", "content": "评论", "nickname": "某人"}
            )

    def test_verified_requires_evidence(self) -> None:
        base = {
            "platform": "zhihu",
            "canonical_url": "https://www.zhihu.com/question/1",
            "title": "标题",
            "source_type": "ugc",
            "topic": "experience",
            "cohort": "2027",
            "recruitment_stage": "autumn",
        }
        with self.assertRaises(ValidationError):
            validate.validate_article({**base, "verification_status": "verified"})
        row = validate.validate_article(
            {
                **base,
                "verification_status": "verified",
                "verification_url": "https://www.zhihu.com/question/1",
                "verified_at": "2026-11-09T00:00:00Z",
            }
        )
        self.assertEqual(row["verification_status"], "verified")

    def test_comment_tree(self) -> None:
        validate.validate_comment_tree(
            [
                {"comment_id": "c1", "comment_level": 1, "parent_comment_id": None, "root_comment_id": "c1"},
                {"comment_id": "c2", "comment_level": 2, "parent_comment_id": "c1", "root_comment_id": "c1"},
                {"comment_id": "c3", "comment_level": 3, "parent_comment_id": "c2", "root_comment_id": "c1"},
            ]
        )
        with self.assertRaises(ValidationError):
            validate.validate_comment_tree(
                [
                    {"comment_id": "c1", "comment_level": 1},
                    {"comment_id": "c2", "comment_level": 2, "parent_comment_id": "missing", "root_comment_id": "c1"},
                ]
            )


class MarkdownTests(unittest.TestCase):
    def _article(self) -> dict[str, object]:
        return {
            "title": "示例文章",
            "platform": "zhihu",
            "canonical_url": "https://www.zhihu.com/question/1",
            "cohort": "2027",
            "recruitment_stage": "autumn",
            "topic": "experience",
            "source_type": "ugc",
            "published_at": None,
            "created_at": "2026-11-09T00:00:00Z",
            "verification_status": "unverified",
            "summary": "摘要",
        }

    def test_comments_markdown_has_no_author_and_keeps_tree(self) -> None:
        text = markdown_export.render_comments_markdown(
            self._article(),
            [
                {"comment_id": "c1", "comment_level": 1, "parent_comment_id": None, "content": "一级", "collection_order": 1},
                {"comment_id": "c2", "comment_level": 2, "parent_comment_id": "c1", "content": "回复", "collection_order": 2},
            ],
            {"coverage_status": "complete", "collected_top_level": 1, "collected_replies": 1},
        )
        self.assertIn("一级", text)
        self.assertIn("回复", text)
        self.assertNotIn("nickname", text.lower())

    def test_author_fields_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            markdown_export.render_comments_markdown(
                self._article(),
                [{"comment_id": "c1", "comment_level": 1, "content": "x", "nickname": "某人"}],
                {"coverage_status": "complete"},
            )


class ArtifactTests(unittest.TestCase):
    def test_write_text_artifact_returns_sha(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        target = Path(temporary.name) / "a.md"
        metadata = artifacts.write_text_artifact(target, "内容\n第二行")
        self.assertTrue(target.is_file())
        self.assertEqual(metadata["sha256"], artifacts.sha256_file(target))
        self.assertEqual(metadata["size_bytes"], target.stat().st_size)


class AnalyticsAndRepositoryTests(unittest.TestCase):
    def test_analytics_counts(self) -> None:
        summary = article_summary(
            [
                {"platform": "zhihu", "cohort": "2026", "topic": "experience", "verification_status": "unverified"},
                {"platform": "xiaohongshu", "cohort": "2027", "topic": "recruitment", "verification_status": "verified"},
            ]
        )
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["by_platform"]["zhihu"], 1)
        self.assertEqual(comment_summary([
            {"comment_level": 1},
            {"comment_level": 2},
        ])["nested"], 1)

    def test_repository_saves_article_idempotently(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "catalog" / "test.sqlite3"
        conn = db.connect_ready(path)
        self.addCleanup(conn.close)
        payload = {
            "platform": "zhihu",
            "canonical_url": "https://www.zhihu.com/question/1",
            "title": "标题",
            "source_type": "ugc",
            "topic": "experience",
            "cohort": "2027",
            "recruitment_stage": "autumn",
        }
        item_id, created = repository.save_article(conn, payload)
        self.assertTrue(created)
        same_id, created_again = repository.save_article(conn, payload)
        self.assertFalse(created_again)
        self.assertEqual(item_id, same_id)
        self.assertEqual(len(repository.list_articles(conn)), 1)


if __name__ == "__main__":
    unittest.main()
