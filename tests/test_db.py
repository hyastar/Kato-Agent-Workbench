"""SQLite 结构与 CRUD 的离线测试。"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts import db


class DatabaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db_path = Path(temporary.name) / "catalog" / "test.sqlite3"
        self.conn = db.connect(self.db_path)
        self.addCleanup(self.conn.close)
        db.apply_migrations(self.conn)

    def _make_task(self, content_hash: str = "a" * 64) -> str:
        return db.ensure_task(
            self.conn,
            name="测试任务",
            source_path="tasks/CURRENT_TASK.md",
            content_sha256=content_hash,
        )

    def test_migrations_create_required_tables(self) -> None:
        tables = {
            row["name"]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        self.assertTrue(set(db.REQUIRED_TABLES) <= tables)
        self.assertEqual(int(self.conn.execute("PRAGMA user_version").fetchone()[0]), 1)
        self.assertEqual(self.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_migrations_are_idempotent_and_keep_data(self) -> None:
        dataset_id, created = db.upsert_dataset(
            self.conn,
            name="示例",
            source="roboflow",
            source_url="https://example.invalid/ds",
            version="v1",
        )
        self.assertTrue(created)

        again = db.apply_migrations(self.conn)
        self.assertEqual(again.applied, ())
        self.assertEqual(again.to_version, 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0], 1)
        self.assertIsNotNone(db.get_dataset(self.conn, dataset_id))

    def test_foreign_keys_are_enforced(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO runs (run_id, task_id) VALUES ('run-missing', 'task-missing')"
            )

    def test_run_lifecycle(self) -> None:
        task_id = self._make_task()
        run_id = db.start_run(self.conn, task_id)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM runs WHERE run_id = ?", (run_id,)).fetchone()[0],
            1,
        )

        run = db.get_run(self.conn, run_id)
        self.assertEqual(run["status"], "pending")
        self.assertIsNone(run["finished_at"])

        db.set_run_status(self.conn, run_id, "running")
        self.assertEqual(db.get_run(self.conn, run_id)["status"], "running")

        db.set_run_status(
            self.conn, run_id, "completed", report_path=f"runs/{run_id}/report.md"
        )
        run = db.get_run(self.conn, run_id)
        self.assertEqual(run["status"], "completed")
        self.assertIsNotNone(run["finished_at"])
        self.assertEqual(run["report_path"], f"runs/{run_id}/report.md")

    def test_run_rejects_unknown_status(self) -> None:
        task_id = self._make_task()
        run_id = db.start_run(self.conn, task_id)
        with self.assertRaises(ValueError):
            db.set_run_status(self.conn, run_id, "done")

    def test_upsert_dataset_deduplicates_null_and_empty_version(self) -> None:
        first_id, created = db.upsert_dataset(
            self.conn,
            name="示例",
            source="roboflow",
            source_url="https://example.invalid/ds",
            version=None,
        )
        second_id, created_again = db.upsert_dataset(
            self.conn,
            name="示例（更新）",
            source="roboflow",
            source_url="https://example.invalid/ds",
            version="",
        )
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first_id, second_id)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0], 1)

    def test_upsert_dataset_updates_non_null_fields(self) -> None:
        dataset_id, _ = db.upsert_dataset(
            self.conn,
            name="示例",
            source="roboflow",
            source_url="https://example.invalid/ds",
            version="v1",
        )
        same_id, created = db.upsert_dataset(
            self.conn,
            name="示例",
            source="roboflow",
            source_url="https://example.invalid/ds",
            version="v1",
            status="downloaded",
            license_name="CC BY 4.0",
            image_count=10,
        )
        self.assertEqual(dataset_id, same_id)
        self.assertFalse(created)
        row = db.get_dataset(self.conn, dataset_id)
        self.assertEqual(row["status"], "downloaded")
        self.assertEqual(row["license_name"], "CC BY 4.0")
        self.assertEqual(row["image_count"], 10)

    def test_upsert_dataset_rejects_invalid_values(self) -> None:
        with self.assertRaises(ValueError):
            db.upsert_dataset(
                self.conn,
                name="示例",
                source="roboflow",
                source_url="https://example.invalid/ds",
                status="unknown",
            )
        with self.assertRaises(ValueError):
            db.upsert_dataset(
                self.conn,
                name="示例",
                source="roboflow",
                source_url="https://example.invalid/ds",
                image_count=-1,
            )

    def test_run_dataset_links_are_idempotent(self) -> None:
        task_id = self._make_task()
        run_id = db.start_run(self.conn, task_id)
        dataset_id, _ = db.upsert_dataset(
            self.conn,
            name="示例",
            source="roboflow",
            source_url="https://example.invalid/ds",
            version="v1",
        )
        db.link_run_dataset(self.conn, run_id, dataset_id, "discovered")
        db.link_run_dataset(self.conn, run_id, dataset_id, "discovered")
        count = self.conn.execute(
            "SELECT COUNT(*) FROM run_datasets WHERE run_id = ? AND dataset_id = ?",
            (run_id, dataset_id),
        ).fetchone()[0]
        self.assertEqual(count, 1)
        with self.assertRaises(ValueError):
            db.link_run_dataset(self.conn, run_id, dataset_id, "unknown-action")

    def test_task_identity_is_content_based(self) -> None:
        first = self._make_task("a" * 64)
        second = self._make_task("a" * 64)
        third = self._make_task("b" * 64)
        self.assertEqual(first, second)
        self.assertNotEqual(first, third)

    def test_list_datasets_filters(self) -> None:
        db.upsert_dataset(
            self.conn,
            name="候选",
            source="roboflow",
            source_url="https://example.invalid/a",
            status="candidate",
        )
        db.upsert_dataset(
            self.conn,
            name="已下载",
            source="other",
            source_url="https://example.invalid/b",
            status="downloaded",
        )
        self.assertEqual(len(db.list_datasets(self.conn)), 2)
        self.assertEqual(len(db.list_datasets(self.conn, status="candidate")), 1)
        self.assertEqual(len(db.list_datasets(self.conn, source="other")), 1)
        self.assertEqual(len(db.list_datasets(self.conn, limit=1)), 1)


if __name__ == "__main__":
    unittest.main()
