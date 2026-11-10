"""research_catalog CLI 的离线测试：导入、去重、过滤、核验约束与导出。"""

from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts import db, research_catalog

# 迁移版本以迁移目录为准，避免每次新增迁移都要改测试。
LATEST_VERSION = db.migration_files()[-1][0]


def _run(argv: list[str]) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = research_catalog.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


def _base_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "platform": "zhihu",
        "canonical_url": "https://www.zhihu.com/question/100",
        "title": "2027届秋招讨论",
        "summary": "讨论投递节奏；具体招聘情况未核实。",
        "source_type": "ugc",
        "topic": "experience",
        "cohort": "2027",
        "recruitment_stage": "autumn",
        "verification_status": "unverified",
    }
    record.update(overrides)
    return record


class ResearchCatalogCliTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db_path = self.root / "catalog" / "research.sqlite3"

    def _write(self, payload: object, name: str = "records.json") -> Path:
        target = self.root / name
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return target

    def _add(self, payload: object, *extra: str, name: str = "records.json") -> tuple[int, str, str]:
        path = self._write(payload, name)
        return _run(["add", "--db", str(self.db_path), "--json-file", str(path), *extra])

    def test_add_works_on_fresh_database(self) -> None:
        code, stdout, stderr = self._add(_base_record(), "--json")
        self.assertEqual(code, 0, stderr)
        self.assertTrue(self.db_path.is_file())
        results = json.loads(stdout)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["created"])
        self.assertTrue(results[0]["item_id"].startswith("ri_"))

        conn = sqlite3.connect(str(self.db_path))
        try:
            self.assertEqual(int(conn.execute("PRAGMA user_version").fetchone()[0]), LATEST_VERSION)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM research_items").fetchone()[0], 1)
        finally:
            conn.close()

    def test_duplicate_updates_and_cross_platform_is_separate(self) -> None:
        self._add(_base_record())
        code, stdout, _ = self._add(
            _base_record(title="2027届秋招讨论（更新）"), "--json", name="second.json"
        )
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(stdout)[0]["created"])

        self._add(_base_record(platform="xiaohongshu"), name="third.json")
        code, stdout, _ = _run(["list", "--db", str(self.db_path), "--json"])
        self.assertEqual(code, 0)
        rows = json.loads(stdout)
        self.assertEqual(len(rows), 2)
        zhihu = [row for row in rows if row["platform"] == "zhihu"][0]
        self.assertEqual(zhihu["title"], "2027届秋招讨论（更新）")

    def test_canonical_url_normalization_dedupes(self) -> None:
        self._add(_base_record(canonical_url="https://WWW.ZHIHU.COM/question/100#answer"))
        code, stdout, _ = self._add(
            _base_record(canonical_url="https://www.zhihu.com/question/100"), "--json",
            name="second.json",
        )
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(stdout)[0]["created"])
        code, stdout, _ = _run(["list", "--db", str(self.db_path), "--json"])
        rows = json.loads(stdout)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["canonical_url"], "https://www.zhihu.com/question/100")

    def test_verified_requires_evidence_url_and_time(self) -> None:
        code, _, stderr = self._add(_base_record(verification_status="verified"))
        self.assertEqual(code, 2)
        self.assertIn("verification_url", stderr)

        code, _, stderr = self._add(
            _base_record(
                verification_status="verified",
                verification_url="https://www.zhihu.com/question/100",
                verified_at="2026-11-09T01:00:00Z",
            ),
            name="valid.json",
        )
        self.assertEqual(code, 0, stderr)
        code, stdout, _ = _run(["list", "--db", str(self.db_path), "--json"])
        rows = json.loads(stdout)
        self.assertEqual(rows[0]["verification_status"], "verified")

    def test_list_filters(self) -> None:
        self._add(
            _base_record(
                canonical_url="https://www.zhihu.com/question/1",
                cohort="2026",
                topic="recruitment",
                recruitment_stage="makeup",
            )
        )
        self._add(
            _base_record(
                platform="xiaohongshu",
                canonical_url="https://www.xiaohongshu.com/explore/2",
                cohort="2027",
                topic="experience",
            ),
            name="second.json",
        )

        for args, expected in (
            (["--cohort", "2026"], 1),
            (["--platform", "xiaohongshu"], 1),
            (["--topic", "experience"], 1),
            (["--verification", "unverified"], 2),
            (["--verification", "verified"], 0),
        ):
            code, stdout, _ = _run(["list", "--db", str(self.db_path), *args, "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(len(json.loads(stdout)), expected, args)

    def test_export_json(self) -> None:
        self._add(_base_record())
        code, stdout, stderr = _run(
            ["export", "--db", str(self.db_path), "--format", "json"]
        )
        self.assertEqual(code, 0, stderr)
        rows = json.loads(stdout)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["platform"], "zhihu")

    def test_run_link_is_recorded(self) -> None:
        conn = db.connect_ready(self.db_path)
        try:
            task_id = db.ensure_task(
                conn,
                name="就业情报",
                source_path="tasks/EMPLOYMENT_2026_2027.md",
                content_sha256="c" * 64,
            )
            run_id = db.start_run(conn, task_id)
        finally:
            conn.close()

        code, _, stderr = self._add(_base_record(), "--run-id", run_id)
        self.assertEqual(code, 0, stderr)
        conn = sqlite3.connect(str(self.db_path))
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM run_research_items WHERE run_id = ?", (run_id,)
                ).fetchone()[0],
                1,
            )
        finally:
            conn.close()

    def test_invalid_enum_and_unknown_field_are_rejected(self) -> None:
        code, _, stderr = self._add(_base_record(cohort="2028"))
        self.assertEqual(code, 2)
        self.assertIn("cohort", stderr)

        code, _, stderr = self._add(
            _base_record(color="red"), name="unknown.json"
        )
        self.assertEqual(code, 2)
        self.assertIn("未知字段", stderr)

    def test_invalid_url_is_rejected(self) -> None:
        code, _, stderr = self._add(_base_record(canonical_url="not-a-url"))
        self.assertEqual(code, 2)
        self.assertIn("canonical_url", stderr)


if __name__ == "__main__":
    unittest.main()
