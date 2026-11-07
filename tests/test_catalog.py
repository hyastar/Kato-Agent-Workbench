"""catalog CLI 的离线测试：新建库自动建表、去重与查询。"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts import catalog


def _run(argv: list[str]) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = catalog.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


class CatalogCliTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db_path = Path(temporary.name) / "catalog" / "cli.sqlite3"

    def _add(self, *extra: str) -> tuple[int, str, str]:
        return _run(
            [
                "add",
                "--db",
                str(self.db_path),
                "--name",
                "示例数据集",
                "--source",
                "roboflow",
                "--source-url",
                "https://example.invalid/ds",
                "--version",
                "v1",
                *extra,
            ]
        )

    def test_add_works_on_fresh_database(self) -> None:
        code, stdout, stderr = self._add("--json")
        self.assertEqual(code, 0, stderr)
        self.assertTrue(self.db_path.is_file())
        payload = json.loads(stdout)
        self.assertTrue(payload["created"])
        self.assertTrue(payload["dataset_id"].startswith("ds_"))

    def test_duplicate_add_updates_instead_of_duplicating(self) -> None:
        self._add()
        code, stdout, _ = self._add("--status", "downloaded", "--json")
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(stdout)["created"])

        code, stdout, _ = _run(["list", "--db", str(self.db_path), "--json"])
        self.assertEqual(code, 0)
        rows = json.loads(stdout)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "downloaded")

    def test_list_filters_by_status(self) -> None:
        self._add()
        code, stdout, _ = _run(
            ["list", "--db", str(self.db_path), "--status", "candidate", "--json"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(stdout)), 1)

        code, stdout, _ = _run(
            ["list", "--db", str(self.db_path), "--status", "failed", "--json"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout), [])

    def test_missing_required_field_returns_usage_error(self) -> None:
        code, _, stderr = _run(["add", "--db", str(self.db_path), "--source", "roboflow"])
        self.assertEqual(code, 2)
        self.assertIn("name", stderr)


if __name__ == "__main__":
    unittest.main()
