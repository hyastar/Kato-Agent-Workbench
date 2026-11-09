"""V1 -> V2 迁移、研究条目 CRUD 的离线测试。"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts import db


def _create_v1_database(path: Path) -> None:
    """构造一个带既有数据的 V1 库，模拟真实升级场景。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        sql = (db.MIGRATIONS_DIR / "001_init.sql").read_text(encoding="utf-8")
        conn.executescript("BEGIN;\n" + sql + "\nPRAGMA user_version = 1;\nCOMMIT;")
        with conn:
            conn.execute(
                "INSERT INTO tasks (task_id, name, source_path, content_sha256, created_at) "
                "VALUES ('task_v1', '旧任务', 'tasks/CURRENT_TASK.md', ?, "
                "'2026-11-01T00:00:00.000Z')",
                ("a" * 64,),
            )
            conn.execute(
                "INSERT INTO runs (run_id, task_id, status, started_at) "
                "VALUES ('run_v1', 'task_v1', 'completed', '2026-11-01T00:00:00.000Z')"
            )
            conn.execute(
                "INSERT INTO datasets (dataset_id, name, source, source_url, version, status) "
                "VALUES ('ds_v1', '旧数据集', 'roboflow', 'https://example.invalid/old', 'v1', "
                "'candidate')"
            )
    finally:
        conn.close()


class ResearchDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db_path = self.root / "catalog" / "research.sqlite3"

    def _open(self, path: Path | None = None) -> sqlite3.Connection:
        conn = db.connect_ready(path or self.db_path)
        self.addCleanup(conn.close)
        return conn

    def test_fresh_database_reaches_v3(self) -> None:
        conn = self._open()
        self.assertEqual(int(conn.execute("PRAGMA user_version").fetchone()[0]), 3)
        self.assertEqual(db.missing_tables(conn), [])
        self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_v1_to_latest_keeps_existing_data_and_creates_backup(self) -> None:
        _create_v1_database(self.db_path)
        conn = self._open()

        self.assertEqual(int(conn.execute("PRAGMA user_version").fetchone()[0]), 3)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)
        self.assertIsNotNone(db.get_dataset(conn, "ds_v1"))

        backups = sorted((self.db_path.parent / "backups").glob("*.bak"))
        self.assertEqual(len(backups), 1)
        backup = sqlite3.connect(str(backups[0]))
        try:
            self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM datasets").fetchone()[0], 1)
            self.assertEqual(int(backup.execute("PRAGMA user_version").fetchone()[0]), 1)
        finally:
            backup.close()

    def test_connect_ready_applies_pending_even_when_base_tables_exist(self) -> None:
        _create_v1_database(self.db_path)
        # 基础表齐全：若仍按“缺表才迁移”的旧逻辑，002 会被跳过。
        raw = sqlite3.connect(str(self.db_path))
        try:
            self.assertEqual(
                raw.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' "
                    "AND name = 'research_items'"
                ).fetchone()[0],
                0,
            )
        finally:
            raw.close()

        conn = self._open()
        self.assertEqual(int(conn.execute("PRAGMA user_version").fetchone()[0]), 3)
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' "
                "AND name = 'research_items'"
            ).fetchone()[0],
            1,
        )

    def test_up_to_date_database_is_not_rebacked_up(self) -> None:
        _create_v1_database(self.db_path)
        conn = self._open()
        conn.close()
        backups_after_upgrade = sorted((self.db_path.parent / "backups").glob("*.bak"))
        self.assertEqual(len(backups_after_upgrade), 1)

        conn = db.connect_ready(self.db_path)
        try:
            self.assertEqual(int(conn.execute("PRAGMA user_version").fetchone()[0]), 3)
        finally:
            conn.close()
        self.assertEqual(
            sorted((self.db_path.parent / "backups").glob("*.bak")),
            backups_after_upgrade,
        )

    def test_verified_requires_evidence(self) -> None:
        conn = self._open()
        with self.assertRaises(ValueError):
            db.upsert_research_item(
                conn,
                platform="zhihu",
                canonical_url="https://www.zhihu.com/question/1",
                title="示例",
                source_type="ugc",
                topic="experience",
                cohort="2027",
                recruitment_stage="autumn",
                verification_status="verified",
            )
        with self.assertRaises(ValueError):
            db.upsert_research_item(
                conn,
                platform="zhihu",
                canonical_url="https://www.zhihu.com/question/1",
                title="示例",
                source_type="ugc",
                topic="experience",
                cohort="2027",
                recruitment_stage="autumn",
                verification_status="verified",
                verification_url="https://www.zhihu.com/question/1",
            )

    def test_research_item_dedupe_and_platform_separation(self) -> None:
        conn = self._open()
        item_id, created = db.upsert_research_item(
            conn,
            platform="zhihu",
            canonical_url="https://www.zhihu.com/question/1#answer",
            title="标题",
            source_type="ugc",
            topic="experience",
            cohort="2027",
            recruitment_stage="autumn",
            summary="摘要",
        )
        self.assertTrue(created)
        same_id, created_again = db.upsert_research_item(
            conn,
            platform="zhihu",
            canonical_url="https://WWW.ZHIHU.COM/question/1",
            title="标题（更新）",
            source_type="ugc",
            topic="experience",
            cohort="2027",
            recruitment_stage="autumn",
        )
        self.assertFalse(created_again)
        self.assertEqual(item_id, same_id)
        row = db.get_research_item(conn, item_id)
        self.assertEqual(row["title"], "标题（更新）")
        self.assertEqual(row["canonical_url"], "https://www.zhihu.com/question/1")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM research_items").fetchone()[0], 1)

        other_id, other_created = db.upsert_research_item(
            conn,
            platform="xiaohongshu",
            canonical_url="https://www.zhihu.com/question/1",
            title="另一平台",
            source_type="ugc",
            topic="experience",
            cohort="2027",
            recruitment_stage="autumn",
        )
        self.assertTrue(other_created)
        self.assertNotEqual(item_id, other_id)

    def test_research_run_links_are_idempotent(self) -> None:
        conn = self._open()
        task_id = db.ensure_task(
            conn,
            name="就业任务",
            source_path="tasks/EMPLOYMENT_2026_2027.md",
            content_sha256="b" * 64,
        )
        run_id = db.start_run(conn, task_id)
        item_id, _ = db.upsert_research_item(
            conn,
            platform="xiaohongshu",
            canonical_url="https://www.xiaohongshu.com/explore/1",
            title="示例",
            source_type="ugc",
            topic="recruitment",
            cohort="2026",
            recruitment_stage="makeup",
        )
        db.link_run_research_item(conn, run_id, item_id, "imported")
        db.link_run_research_item(conn, run_id, item_id, "imported")
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM run_research_items WHERE run_id = ? AND item_id = ?",
                (run_id, item_id),
            ).fetchone()[0],
            1,
        )
        with self.assertRaises(ValueError):
            db.link_run_research_item(conn, run_id, item_id, "unknown")

    def test_list_filters_and_limit(self) -> None:
        conn = self._open()
        common = dict(source_type="ugc", recruitment_stage="autumn")
        db.upsert_research_item(
            conn, platform="zhihu", canonical_url="https://www.zhihu.com/q/1",
            title="A", topic="experience", cohort="2027", **common,
        )
        db.upsert_research_item(
            conn, platform="xiaohongshu", canonical_url="https://www.xiaohongshu.com/n/1",
            title="B", topic="recruitment", cohort="2026", **common,
        )
        self.assertEqual(len(db.list_research_items(conn)), 2)
        self.assertEqual(len(db.list_research_items(conn, cohort="2027")), 1)
        self.assertEqual(len(db.list_research_items(conn, platform="xiaohongshu")), 1)
        self.assertEqual(len(db.list_research_items(conn, topic="recruitment")), 1)
        self.assertEqual(len(db.list_research_items(conn, verification="unverified")), 2)
        self.assertEqual(len(db.list_research_items(conn, limit=1)), 1)


if __name__ == "__main__":
    unittest.main()
