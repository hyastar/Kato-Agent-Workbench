"""Campaign 报告生成的离线测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import db
from scripts.employment import report, repository


class ReportTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.conn = db.connect_ready(self.root / "catalog" / "report.sqlite3")
        self.addCleanup(self.conn.close)
        repository.create_campaign(
            self.conn, "camp", "测试 Campaign", target_total=10, target_xiaohongshu=5, target_zhihu=5
        )
        self.xhs, _ = repository.save_article(
            self.conn,
            {
                "platform": "xiaohongshu",
                "canonical_url": "https://www.xiaohongshu.com/explore/1",
                "title": "简历经验",
                "summary": "关于简历与面试的经验。",
                "source_type": "ugc",
                "topic": "experience",
                "cohort": "2027",
                "recruitment_stage": "autumn",
            },
        )
        self.zhihu, _ = repository.save_article(
            self.conn,
            {
                "platform": "zhihu",
                "canonical_url": "https://www.zhihu.com/question/1",
                "title": "薪资讨论",
                "summary": "关于薪资的讨论。",
                "source_type": "ugc",
                "topic": "salary",
                "cohort": "2026",
                "recruitment_stage": "autumn",
            },
        )
        for item_id in (self.xhs, self.zhihu):
            repository.attach_article(self.conn, item_id, campaign_id="camp", batch_id="b1")
            repository.import_comment_thread(
                self.conn,
                item_id,
                [{"content": "简历面试都很重要", "like_count": 9, "children": [{"content": "同意"}]}],
            )
            repository.update_article_stats(
                self.conn,
                item_id,
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

    def test_summary_counts(self) -> None:
        summary = report.build_summary(self.conn, "camp")
        self.assertEqual(len(summary["items"]), 2)
        self.assertEqual(summary["comments_total"], 4)
        self.assertEqual(summary["top_level"], 2)
        self.assertEqual(summary["nested"], 2)
        self.assertEqual(summary["by_platform"]["zhihu"], 1)
        self.assertEqual(summary["keyword_counts"]["简历"], 2)

    def test_reports_have_no_author_fields(self) -> None:
        summary = report.build_summary(self.conn, "camp")
        text = report.render_campaign_report(summary)
        self.assertIn("Campaign 报告", text)
        self.assertNotIn("nickname", text)
        self.assertNotIn("user_id", text)
        self.assertNotIn("主页", text)

    def test_write_reports(self) -> None:
        written = report.write_reports(
            self.conn, "camp", root=self.root / "employment"
        )
        self.assertEqual(len(written), 5)
        for relative in written.values():
            self.assertTrue(Path(relative).is_file())
        count = self.conn.execute(
            "SELECT COUNT(*) FROM research_artifacts WHERE artifact_type = 'report'"
        ).fetchone()[0]
        self.assertEqual(count, 5)


if __name__ == "__main__":
    unittest.main()
