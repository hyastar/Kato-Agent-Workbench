"""V4 阶段 3：SQLite V3、评论层级、Campaign/Batch 与 Markdown 档案测试。"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts import db
from scripts.employment import exporter, repository
from scripts.employment.validate import ValidationError


def _create_v2_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        for version, name in ((1, "001_init.sql"), (2, "002_research_items.sql")):
            sql = (db.MIGRATIONS_DIR / name).read_text(encoding="utf-8")
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;")
        with conn:
            conn.execute(
                "INSERT INTO tasks (task_id, name, source_path, content_sha256) "
                "VALUES ('task_v2', '旧任务', 'tasks/EMPLOYMENT_2026_2027.md', ?)",
                ("a" * 64,),
            )
            conn.execute(
                "INSERT INTO runs (run_id, task_id, status) VALUES ('run_v2', 'task_v2', 'completed')"
            )
            conn.execute(
                "INSERT INTO research_items (item_id, platform, canonical_url, title, source_type, "
                "topic, cohort, recruitment_stage, collected_at) "
                "VALUES ('ri_old', 'zhihu', 'https://www.zhihu.com/question/1', '旧文章', "
                "'ugc', 'experience', '2027', 'autumn', '2026-11-09T00:00:00Z')"
            )
            conn.execute(
                "INSERT INTO run_research_items (run_id, item_id, action) "
                "VALUES ('run_v2', 'ri_old', 'imported')"
            )
    finally:
        conn.close()


class V3MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db_path = self.root / "catalog" / "v3.sqlite3"

    def test_v2_to_v3_preserves_items_and_links(self) -> None:
        _create_v2_database(self.db_path)
        conn = db.connect_ready(self.db_path)
        self.addCleanup(conn.close)

        self.assertEqual(int(conn.execute("PRAGMA user_version").fetchone()[0]), 4)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM research_items").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM run_research_items").fetchone()[0], 1)
        self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")

        row = conn.execute("SELECT * FROM research_items WHERE item_id = 'ri_old'").fetchone()
        self.assertEqual(row["title"], "旧文章")
        self.assertEqual(row["collected_top_level"], 0)
        self.assertEqual(row["collected_replies"], 0)
        self.assertEqual(row["comment_coverage_status"], "not_available")

        tables = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        for table in ("research_comments", "research_campaigns", "research_batches", "research_artifacts"):
            self.assertIn(table, tables)

        backups = sorted((self.db_path.parent / "backups").glob("*.bak"))
        self.assertEqual(len(backups), 1)
        backup = sqlite3.connect(str(backups[0]))
        try:
            self.assertEqual(int(backup.execute("PRAGMA user_version").fetchone()[0]), 2)
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM research_items").fetchone()[0], 1)
        finally:
            backup.close()

    def test_v3_accepts_new_verification_statuses(self) -> None:
        conn = db.connect_ready(self.db_path)
        self.addCleanup(conn.close)
        item_id, _ = db.upsert_research_item(
            conn,
            platform="zhihu",
            canonical_url="https://www.zhihu.com/question/2",
            title="状态测试",
            source_type="ugc",
            topic="experience",
            cohort="2027",
            recruitment_stage="autumn",
        )
        with conn:
            conn.execute(
                "UPDATE research_items SET verification_status = 'partially_verified' "
                "WHERE item_id = ?",
                (item_id,),
            )
        self.assertEqual(
            conn.execute(
                "SELECT verification_status FROM research_items WHERE item_id = ?", (item_id,)
            ).fetchone()[0],
            "partially_verified",
        )


class CommentRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db_path = self.root / "catalog" / "comments.sqlite3"
        self.conn = db.connect_ready(self.db_path)
        self.addCleanup(self.conn.close)
        self.item_id, _ = repository.save_article(
            self.conn,
            {
                "platform": "zhihu",
                "canonical_url": "https://www.zhihu.com/question/10",
                "title": "评论测试",
                "source_type": "ugc",
                "topic": "experience",
                "cohort": "2027",
                "recruitment_stage": "autumn",
            },
        )

    def _nodes(self) -> list[dict[str, object]]:
        return [
            {
                "platform_comment_id": "t1",
                "content": "一级 A",
                "like_count": 10,
                "reply_count_displayed": 2,
                "children": [
                    {"platform_comment_id": "r1", "content": "回复 1"},
                    {
                        "platform_comment_id": "r2",
                        "content": "回复 2",
                        "children": [{"platform_comment_id": "s1", "content": "子回复"}],
                    },
                ],
            },
            {"platform_comment_id": "t2", "content": "一级 B"},
        ]

    def test_import_thread_and_idempotency(self) -> None:
        counts = repository.import_comment_thread(self.conn, self.item_id, self._nodes())
        self.assertEqual(counts["inserted"], 5)
        self.assertEqual(counts["top_level"], 2)
        self.assertEqual(counts["nested"], 3)

        rows = [dict(row) for row in repository.list_comments(self.conn, self.item_id)]
        by_platform = {row["platform_comment_id"]: row for row in rows}
        self.assertEqual(len(rows), 5)
        self.assertEqual(by_platform["t1"]["comment_level"], 1)
        self.assertEqual(by_platform["r1"]["parent_comment_id"], by_platform["t1"]["comment_id"])
        self.assertEqual(by_platform["r1"]["root_comment_id"], by_platform["t1"]["comment_id"])
        self.assertEqual(by_platform["s1"]["comment_level"], 3)
        self.assertEqual(by_platform["s1"]["parent_comment_id"], by_platform["r2"]["comment_id"])
        self.assertEqual(by_platform["s1"]["root_comment_id"], by_platform["t1"]["comment_id"])

        again = repository.import_comment_thread(self.conn, self.item_id, self._nodes())
        self.assertEqual(again["inserted"], 0)
        self.assertEqual(again["existing"], 5)
        self.assertEqual(len(repository.list_comments(self.conn, self.item_id)), 5)

    def test_same_text_different_parents_not_merged(self) -> None:
        nodes = [
            {"content": "一级 1", "children": [{"content": "相同内容"}]},
            {"content": "一级 2", "children": [{"content": "相同内容"}]},
        ]
        counts = repository.import_comment_thread(self.conn, self.item_id, nodes)
        self.assertEqual(counts["inserted"], 4)
        replies = [
            row
            for row in repository.list_comments(self.conn, self.item_id)
            if row["comment_level"] == 2
        ]
        self.assertEqual(len(replies), 2)
        self.assertNotEqual(replies[0]["parent_comment_id"], replies[1]["parent_comment_id"])

    def test_author_fields_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            repository.import_comment_thread(
                self.conn,
                self.item_id,
                [{"content": "评论", "nickname": "某人"}],
            )

    def test_update_stats_and_validation(self) -> None:
        repository.update_article_stats(
            self.conn,
            self.item_id,
            {
                "displayed_total": 100,
                "displayed_top_level": 60,
                "collected_top_level": 50,
                "displayed_replies": 30,
                "collected_replies": 12,
                "coverage_status": "partial",
                "sort_basis": "high_likes_then_latest",
                "reason": "回复展开中断",
            },
        )
        row = repository.get_article(self.conn, self.item_id)
        self.assertEqual(row["collected_top_level"], 50)
        self.assertEqual(row["comment_coverage_status"], "partial")
        self.assertEqual(row["comment_sort_basis"], "high_likes_then_latest")

        with self.assertRaises(ValidationError):
            repository.update_article_stats(
                self.conn, self.item_id, {"coverage_status": "unknown"}
            )


class CampaignBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.conn = db.connect_ready(Path(temporary.name) / "catalog" / "campaign.sqlite3")
        self.addCleanup(self.conn.close)

    def test_campaign_and_batch_lifecycle(self) -> None:
        repository.create_campaign(
            self.conn,
            "camp_1",
            "测试 Campaign",
            target_total=1000,
            target_xiaohongshu=800,
            target_zhihu=200,
            target_2026=400,
            target_2027=600,
        )
        self.assertEqual(repository.get_campaign(self.conn, "camp_1")["status"], "pending")
        repository.set_campaign_status(self.conn, "camp_1", "running")
        self.assertEqual(repository.get_campaign(self.conn, "camp_1")["status"], "running")

        repository.create_batch(
            self.conn,
            "batch_1",
            "camp_1",
            platform="xiaohongshu",
            cohort="2027",
            keyword="2027届 秋招",
            target_articles=20,
        )
        repository.update_batch(
            self.conn,
            "batch_1",
            discovered=25,
            succeeded=18,
            failed=7,
            top_level_comments=600,
            nested_replies=1200,
            status="partial",
            error_summary="2 篇详情不可用",
        )
        batch = repository.get_batch(self.conn, "batch_1")
        self.assertEqual(batch["succeeded"], 18)
        self.assertEqual(batch["top_level_comments"], 600)
        self.assertEqual(batch["status"], "partial")
        self.assertIsNotNone(batch["finished_at"])

        with self.assertRaises(ValueError):
            repository.set_campaign_status(self.conn, "camp_1", "done")
        with self.assertRaises(sqlite3.IntegrityError):
            repository.create_batch(
                self.conn, "batch_bad", "missing_campaign", platform="zhihu", cohort="2026"
            )


class ExportTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.conn = db.connect_ready(self.root / "catalog" / "export.sqlite3")
        self.addCleanup(self.conn.close)
        self.item_id, _ = repository.save_article(
            self.conn,
            {
                "platform": "xiaohongshu",
                "canonical_url": "https://www.xiaohongshu.com/explore/1",
                "title": "导出测试",
                "source_type": "ugc",
                "topic": "experience",
                "cohort": "2026",
                "recruitment_stage": "autumn",
                "summary": "摘要",
            },
        )
        repository.import_comment_thread(
            self.conn,
            self.item_id,
            [{"content": "一级评论", "like_count": 3, "children": [{"content": "回复"}]}],
        )
        repository.update_article_stats(
            self.conn,
            self.item_id,
            {
                "displayed_total": 2,
                "displayed_top_level": 1,
                "collected_top_level": 1,
                "displayed_replies": 1,
                "collected_replies": 1,
                "coverage_status": "complete",
                "sort_basis": "visible_order",
            },
        )

    def test_export_article_and_indexes(self) -> None:
        result = exporter.export_article_artifacts(
            self.conn, self.item_id, root=self.root / "employment"
        )
        post_path = Path(str(result["post"]["relative_path"]))
        comments_path = Path(str(result["comments"]["relative_path"]))
        self.assertTrue(post_path.is_file())
        self.assertTrue(comments_path.is_file())
        self.assertIn("一级评论", comments_path.read_text(encoding="utf-8"))

        row = repository.get_article(self.conn, self.item_id)
        self.assertEqual(row["post_markdown_path"], str(result["post"]["relative_path"]))
        artifacts_count = self.conn.execute(
            "SELECT COUNT(*) FROM research_artifacts WHERE research_item_id = ?", (self.item_id,)
        ).fetchone()[0]
        self.assertEqual(artifacts_count, 2)

        for cohort in ("all", "2026", "2027"):
            exporter.export_platform_index(
                self.conn, "xiaohongshu", cohort=None if cohort == "all" else cohort,
                root=self.root / "employment",
            )
        index_count = self.conn.execute(
            "SELECT COUNT(*) FROM research_artifacts WHERE artifact_type = 'index'"
        ).fetchone()[0]
        self.assertEqual(index_count, 3)


if __name__ == "__main__":
    unittest.main()
