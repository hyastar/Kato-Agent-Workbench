"""discovery queue CLI 的离线测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.employment.browser import runner


class DiscoveryCliTests(unittest.TestCase):
    def test_queue_cli_filters_known(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        payload = {
            "items": [
                {"href": "https://www.zhihu.com/question/1", "text": "旧"},
                {"href": "https://www.zhihu.com/question/2", "text": "新"},
            ]
        }
        (root / "payload.json").write_text(json.dumps(payload), encoding="utf-8")
        (root / "known.json").write_text(
            json.dumps(["https://www.zhihu.com/question/1"]), encoding="utf-8"
        )
        code = runner.main(
            [
                "queue",
                "--platform",
                "zhihu",
                "--keyword",
                "秋招",
                "--payload",
                str(root / "payload.json"),
                "--known-json",
                str(root / "known.json"),
                "--output",
                str(root / "queue.json"),
            ]
        )
        self.assertEqual(code, 0)
        queue = json.loads((root / "queue.json").read_text(encoding="utf-8"))
        self.assertEqual(queue["new_count"], 1)
        self.assertEqual(queue["duplicate_count"], 1)
        self.assertEqual(queue["queue"][0]["canonical_url"], "https://www.zhihu.com/question/2")


if __name__ == "__main__":
    unittest.main()
