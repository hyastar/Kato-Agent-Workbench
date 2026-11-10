"""V6 阶段 5 离线测试：入库、评论树、Markdown 幂等、checkpoint。"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from kato_engine.collection.article import Collected
from kato_engine.collection.classification import classify
from kato_engine.collection.comments import select_comment_nodes
from kato_engine.config.settings import load_settings
from kato_engine.core.lifecycle import ArticleService
from kato_engine.platforms.base import ArticleData, CommentBundle, CommentNode, SearchHit
from kato_engine.storage.checkpoints import read_checkpoint, write_checkpoint
from kato_engine.storage.markdown import verify_artifacts
from kato_engine.storage.repository import EngineRepository


def make_collected() -> Collected:
    parent = CommentNode(
        content="到手 5000 在二线算正常",
        platform_comment_id="c1",
        like_count=23,
        published_time_displayed="05-24",
    )
    parent.children = [
        CommentNode(content=f"楼中楼 {i}", platform_comment_id=f"c1-{i}", level=2)
        for i in range(3)
    ]
    second = CommentNode(
        content="我们公司应届生 6000",
        platform_comment_id="c2",
        like_count=8,
        published_time_displayed="05-25",
    )
    bundle = CommentBundle(
        nodes=[parent, second],
        displayed_total=5,
        sort_basis="visible_order",
    )
    selection = select_comment_nodes(bundle, limit=50)
    article = ArticleData(
        platform="xiaohongshu",
        canonical_url="https://www.xiaohongshu.com/explore/65f0a1b2c3d4e5f60718293a",
        title="26届到手工资记录",
        body_text="26届应届生，试用期三个月，到手工资 5000，房租 1500，通勤一小时。",
        published_text="05-24",
    )
    return Collected(
        article=article,
        canonical_url=article.canonical_url,
        selection=selection,
        classification=classify(article.title, article.body_text),
        metrics={"open_detail_ms": 100},
    )


class StorageTestCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name)
        self.settings = replace(
            load_settings(env={}),
            db_path=self.tmp / "catalog" / "test.sqlite3",
            data_dir=self.tmp / "data",
            runs_dir=self.tmp / "runs",
            profile_dir=self.tmp / "profile",
        )
        self.repo, _ = EngineRepository.open(self.settings)
        self.addCleanup(self.repo.close)
        self.campaign_id = "employment-test"
        from scripts.employment import repository as legacy

        legacy.create_campaign(
            self.repo.conn,
            self.campaign_id,
            "测试 Campaign",
            target_total=1000,
            target_xiaohongshu=800,
            target_zhihu=200,
        )
        self.service = ArticleService(self.repo)
        self.queue_added = self.repo.enqueue_candidates(
            [
                {
                    "campaign_id": self.campaign_id,
                    "platform": "xiaohongshu",
                    "canonical_url": "https://www.xiaohongshu.com/explore/65f0a1b2c3d4e5f60718293a",
                    "title_hint": "26届到手工资记录",
                    "dimension": "salary",
                    "keyword": "到手工资",
                    "combined_query": "26届 到手工资",
                }
            ]
        )
        claimed = self.repo.claim_next(
            self.campaign_id,
            "xiaohongshu",
            owner="test",
            lease_seconds=600,
            max_attempts=3,
        )
        assert claimed is not None
        self.candidate_id = str(claimed["candidate_id"])

    def test_persist_creates_item_comments_and_markdown(self) -> None:
        result = self.service.persist(
            make_collected(), campaign_id=self.campaign_id, candidate_id=self.candidate_id
        )
        self.assertTrue(result.created)
        self.assertEqual(result.comments_inserted, 5)
        self.assertEqual(result.stats["collected_top_level"], 2)
        self.assertEqual(result.stats["collected_replies"], 3)
        self.assertEqual(result.stats["coverage_status"], "complete")

        post = self.settings.repo_root / (result.export.post_path or "")
        comments = self.settings.repo_root / (result.export.comments_path or "")
        self.assertTrue(post.exists())
        self.assertTrue(comments.exists())
        body = comments.read_text(encoding="utf-8")
        self.assertIn("楼中楼 2", body)
        for forbidden in ("author", "nickname", "用户ID"):
            self.assertNotIn(forbidden, body)

    def test_candidate_completes(self) -> None:
        self.service.persist(
            make_collected(), campaign_id=self.campaign_id, candidate_id=self.candidate_id
        )
        row = self.repo.conn.execute(
            "SELECT state, item_id FROM engine_candidates WHERE candidate_id = ?",
            (self.candidate_id,),
        ).fetchone()
        self.assertEqual(row["state"], "completed")
        self.assertTrue(row["item_id"].startswith("ri_"))

    def test_classification_is_written(self) -> None:
        result = self.service.persist(
            make_collected(), campaign_id=self.campaign_id, candidate_id=self.candidate_id
        )
        item = self.repo.get_item(result.item_id)
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item["employment_topic"], "salary")
        self.assertEqual(item["graduation_cohort"], "2026")
        self.assertEqual(item["campaign_id"], self.campaign_id)

    def test_repeat_persist_is_idempotent(self) -> None:
        first = self.service.persist(
            make_collected(), campaign_id=self.campaign_id, candidate_id=self.candidate_id
        )
        # 再入库一次同样内容（模拟重复采集/重跑）
        self.repo.enqueue_candidates(
            [
                {
                    "campaign_id": self.campaign_id,
                    "platform": "xiaohongshu",
                    "canonical_url": make_collected().canonical_url,
                    "dimension": "salary",
                    "keyword": "到手工资",
                    "combined_query": "26届 到手工资",
                }
            ]
        )
        row = self.repo.conn.execute(
            "SELECT candidate_id, state FROM engine_candidates WHERE canonical_url = ?",
            (make_collected().canonical_url,),
        ).fetchone()
        self.assertEqual(row["state"], "completed")
        second = self.service.persist(
            make_collected(), campaign_id=self.campaign_id, candidate_id=str(row["candidate_id"])
        )
        self.assertEqual(first.item_id, second.item_id)
        self.assertFalse(second.created)
        self.assertEqual(second.comments_inserted, 0)
        self.assertEqual(second.comments_existing, 5)
        self.assertFalse(second.export.post_changed)
        self.assertFalse(second.export.comments_changed)
        total_items = self.repo.conn.execute(
            "SELECT COUNT(*) FROM research_items"
        ).fetchone()[0]
        total_comments = self.repo.conn.execute(
            "SELECT COUNT(*) FROM research_comments"
        ).fetchone()[0]
        self.assertEqual(total_items, 1)
        self.assertEqual(total_comments, 5)

    def test_artifact_hashes_match_disk(self) -> None:
        result = self.service.persist(
            make_collected(), campaign_id=self.campaign_id, candidate_id=self.candidate_id
        )
        report = verify_artifacts(self.settings, self.repo)
        self.assertGreaterEqual(report["checked"], 2)
        self.assertEqual(report["missing_count"], 0)
        self.assertEqual(report["mismatched_count"], 0)
        # 手工改动文件后应被检出
        post = self.settings.repo_root / (result.export.post_path or "")
        post.write_text(post.read_text(encoding="utf-8") + "\n篡改\n", encoding="utf-8")
        report = verify_artifacts(self.settings, self.repo)
        self.assertEqual(report["mismatched_count"], 1)

    def test_checkpoint_roundtrip(self) -> None:
        path = write_checkpoint(
            self.settings,
            "er_test",
            self.campaign_id,
            {"platform": "xiaohongshu", "accepted": 1, "last_candidate": self.candidate_id},
        )
        payload = read_checkpoint(path)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["engine_run_id"], "er_test")
        self.assertEqual(payload["accepted"], 1)

    def test_report_counts_real_rows(self) -> None:
        from kato_engine.observability.reporting import build_report, render_report_markdown

        self.service.persist(
            make_collected(), campaign_id=self.campaign_id, candidate_id=self.candidate_id
        )
        report = build_report(self.repo, self.settings, self.campaign_id)
        self.assertEqual(report["articles"]["total"], 1)
        self.assertEqual(report["articles"]["by_platform"]["xiaohongshu"], 1)
        self.assertEqual(report["comments"]["total"], 5)
        self.assertEqual(report["comments"]["top_level"], 2)
        self.assertEqual(report["comments"]["nested"], 3)
        self.assertEqual(report["articles"]["by_dimension"]["salary"], 1)
        self.assertEqual(report["artifacts"]["mismatched_count"], 0)
        markdown = render_report_markdown(report)
        self.assertIn("就业情报 V6 采集报告", markdown)
        self.assertIn("一级评论：2", markdown)


if __name__ == "__main__":
    unittest.main()
