"""V6.1 离线测试：浏览器任务契约、结果校验、批次入库。

不启动任何浏览器：输入是模拟 ZCode 内置浏览器返回的 batch.json。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from kato_engine.agent.contracts import (
    ArticleExtraction,
    BatchContractError,
    BatchResult,
    BatchTarget,
    BatchTask,
)
from kato_engine.agent.ingest import build_collected, ingest_batch
from kato_engine.collection.thread_tree import nodes_from_indentation, nodes_from_nested
from kato_engine.config.settings import load_settings
from kato_engine.core.lifecycle import ArticleService
from kato_engine.storage.repository import EngineRepository, candidate_id_for

XHS_URL = "https://www.xiaohongshu.com/explore/65f0a1b2c3d4e5f60718293a"
ZHIHU_URL = "https://www.zhihu.com/answer/1949491104618620284"


def xhs_batch() -> dict:
    return {
        "platform": "xiaohongshu",
        "query": "26届 到手工资",
        "search": {
            "raw": 2,
            "pageTitle": "26届 到手工资 - 小红书搜索",
            "loginWall": False,
            "cards": [
                {
                    "index": 0,
                    "note_id": "65f0a1b2c3d4e5f60718293a",
                    "title": "26届到手工资记录",
                    "href": "/search_result/65f0a1b2c3d4e5f60718293a?xsec_token=SECRET",
                },
                {
                    "index": 1,
                    "note_id": "65f0a1b2c3d4e5f60718293b",
                    "title": "另一篇",
                    "href": "/search_result/65f0a1b2c3d4e5f60718293b?xsec_token=SECRET2",
                },
            ],
        },
        "articles": [
            {
                "ok": True,
                "url": XHS_URL + "?xsec_token=SECRET",
                "title": "26届到手工资记录",
                "body": "26届应届生，试用期三个月，到手工资 5000，房租 1500，通勤一小时。",
                "published_text": "05-24河北",
                "displayed_total": 5,
                "comments": [
                    {
                        "id": "c1",
                        "content": "到手 5000 在二线算正常",
                        "like_text": "23",
                        "date_text": "05-24山东",
                        "children": [
                            {"id": "c1-1", "content": "楼中楼 A", "like_text": "2", "date_text": "05-25"},
                            {"id": "c1-2", "content": "楼中楼 B", "like_text": "1", "date_text": "05-25"},
                        ],
                    },
                    {"id": "c2", "content": "我们公司应届生 6000", "like_text": "8", "date_text": "05-26"},
                ],
            }
        ],
    }


def zhihu_batch() -> dict:
    return {
        "platform": "zhihu",
        "query": "2026 被裁",
        "search": {
            "raw": 1,
            "cards": [
                {
                    "index": 0,
                    "title": "被裁之后怎么办",
                    "href": "https://www.zhihu.com/question/1/answer/2",
                    "canonical_url": "https://www.zhihu.com/question/1/answer/2",
                }
            ],
        },
        "articles": [
            {
                "ok": True,
                "url": "https://www.zhihu.com/question/1/answer/2?utm=x",
                "title": "被裁之后怎么办",
                "body": "2026 年公司裁员，应届生被毁约，现在失业在家找工作。",
                "published_text": "发布于2025-09-11 15:14・湖北",
                "displayed_total": 3,
                "comments_flat": [
                    {"left": 342, "text": "一级评论 A", "time_text": "09-11"},
                    {"left": 376, "text": "回复 A-1", "time_text": "09-11"},
                    {"left": 342, "text": "一级评论 B", "time_text": "09-12"},
                ],
            }
        ],
    }


class ThreadTreeTests(unittest.TestCase):
    def test_nested_tree(self) -> None:
        nodes = nodes_from_nested(xhs_batch()["articles"][0]["comments"])
        self.assertEqual(len(nodes), 2)
        self.assertEqual(len(nodes[0].children), 2)
        self.assertEqual(nodes[0].children[0].level, 2)
        self.assertEqual(nodes[0].published_time_displayed, "05-24")

    def test_indentation_tree(self) -> None:
        nodes = nodes_from_indentation(zhihu_batch()["articles"][0]["comments_flat"])
        self.assertEqual([n.content for n in nodes], ["一级评论 A", "一级评论 B"])
        self.assertEqual(len(nodes[0].children), 1)


class ContractTests(unittest.TestCase):
    def test_task_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task = BatchTask(
                run_id="er_test",
                campaign_id="c1",
                platform="xiaohongshu",
                query="q",
                dimension="salary",
                keyword="k",
                combined_query="q",
                search_url="https://example.com/search?q=q",
                size=2,
                targets=[BatchTarget(candidate_id="cd_1", canonical_url=XHS_URL, note_id="n1")],
            )
            path = task.write(Path(tmp) / "task.json")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["platform"], "xiaohongshu")
            self.assertIn("workflow_js", payload)
            self.assertIn("scripts", payload)
            self.assertEqual(payload["targets"][0]["note_id"], "n1")

    def test_invalid_url_rejected(self) -> None:
        extraction = ArticleExtraction.from_dict(
            {"ok": True, "url": "https://www.xiaohongshu.com/search_result?keyword=x", "title": "t"},
            "xiaohongshu",
        )
        self.assertFalse(extraction.ok)
        self.assertEqual(extraction.error_type, "invalid_url")

    def test_missing_title_rejected(self) -> None:
        extraction = ArticleExtraction.from_dict(
            {"ok": True, "url": XHS_URL, "title": "  "}, "xiaohongshu"
        )
        self.assertFalse(extraction.ok)
        self.assertEqual(extraction.error_type, "empty_content")

    def test_platform_mismatch_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "batch.json"
            path.write_text(json.dumps({"platform": "zhihu", "articles": []}), encoding="utf-8")
            with self.assertRaises(BatchContractError):
                BatchResult.load(path, platform="xiaohongshu", run_id="r", query="q")

    def test_token_stripped_from_canonical(self) -> None:
        extraction = ArticleExtraction.from_dict(
            {"ok": True, "url": XHS_URL + "?xsec_token=SECRET", "title": "t"},
            "xiaohongshu",
        )
        self.assertEqual(extraction.canonical_url, XHS_URL)


class IngestTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name)
        self.settings = replace(
            load_settings(env={}),
            db_path=self.tmp / "catalog" / "test.sqlite3",
            data_dir=self.tmp / "data",
            runs_dir=self.tmp / "runs",
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
        self.run_id = self.repo.start_engine_run(
            self.campaign_id, target_xiaohongshu=2, target_zhihu=1
        )
        self.service = ArticleService(self.repo)

    def _task(self, platform: str, query: str) -> BatchTask:
        return BatchTask(
            run_id=self.run_id,
            campaign_id=self.campaign_id,
            platform=platform,
            query=query,
            dimension="salary",
            keyword="到手工资",
            combined_query=query,
            search_url="https://example.com/search",
            size=1,
        )

    def test_ingest_xhs_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "batch.json"
            path.write_text(json.dumps(xhs_batch(), ensure_ascii=False), encoding="utf-8")
            result = BatchResult.load(
                path, platform="xiaohongshu", run_id=self.run_id, query="26届 到手工资"
            )
        summary = ingest_batch(
            self.repo,
            self.service,
            result,
            self._task("xiaohongshu", "26届 到手工资"),
            engine_run_id=self.run_id,
        )
        self.assertEqual(summary.accepted, 1)
        self.assertEqual(summary.new_candidates, 2)
        counts = self.repo.campaign_article_counts(self.campaign_id)
        self.assertEqual(counts["xiaohongshu"], 1)
        item = self.repo.conn.execute("SELECT * FROM research_items").fetchone()
        self.assertEqual(item["employment_topic"], "salary")
        self.assertEqual(item["collected_top_level"], 2)
        self.assertEqual(item["collected_replies"], 2)
        self.assertEqual(item["displayed_comments_total"], 5)
        comments = self.repo.conn.execute(
            "SELECT comment_level, COUNT(*) n FROM research_comments GROUP BY 1"
        ).fetchall()
        self.assertEqual({row["comment_level"]: row["n"] for row in comments}, {1: 2, 2: 2})
        # 未处理候选留在队列里
        states = self.repo.candidate_state_counts(campaign_id=self.campaign_id, platform="xiaohongshu")
        self.assertEqual(states["queued"], 1)
        self.assertEqual(states["completed"], 1)
        # Markdown 已生成
        self.assertTrue(item["post_markdown_path"])
        self.assertTrue((self.settings.repo_root / item["post_markdown_path"]).exists())

    def test_ingest_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "batch.json"
            path.write_text(json.dumps(xhs_batch(), ensure_ascii=False), encoding="utf-8")
            result = BatchResult.load(
                path, platform="xiaohongshu", run_id=self.run_id, query="26届 到手工资"
            )
        task = self._task("xiaohongshu", "26届 到手工资")
        ingest_batch(self.repo, self.service, result, task, engine_run_id=self.run_id)
        second = ingest_batch(self.repo, self.service, result, task, engine_run_id=self.run_id)
        self.assertEqual(second.accepted, 0)
        self.assertTrue(any(item.get("skipped") for item in second.items))
        self.assertEqual(
            self.repo.conn.execute("SELECT COUNT(*) FROM research_items").fetchone()[0], 1
        )
        self.assertEqual(
            self.repo.conn.execute("SELECT COUNT(*) FROM research_comments").fetchone()[0], 4
        )

    def test_ingest_zhihu_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "batch.json"
            path.write_text(json.dumps(zhihu_batch(), ensure_ascii=False), encoding="utf-8")
            result = BatchResult.load(
                path, platform="zhihu", run_id=self.run_id, query="2026 被裁"
            )
        summary = ingest_batch(
            self.repo,
            self.service,
            result,
            self._task("zhihu", "2026 被裁"),
            engine_run_id=self.run_id,
        )
        self.assertEqual(summary.accepted, 1)
        item = self.repo.conn.execute("SELECT * FROM research_items").fetchone()
        self.assertEqual(item["employment_topic"], "layoff")
        self.assertEqual(item["published_at"], "2025-09-11T15:14:00")
        self.assertEqual(item["collected_top_level"], 2)
        self.assertEqual(item["collected_replies"], 1)

    def test_irrelevant_is_rejected(self) -> None:
        batch = xhs_batch()
        batch["articles"][0]["title"] = "今天做了番茄炒蛋"
        batch["articles"][0]["body"] = "先把鸡蛋打散，番茄切块，热锅下油，翻炒三分钟。"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "batch.json"
            path.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
            result = BatchResult.load(
                path, platform="xiaohongshu", run_id=self.run_id, query="26届 到手工资"
            )
        summary = ingest_batch(
            self.repo,
            self.service,
            result,
            self._task("xiaohongshu", "26届 到手工资"),
            engine_run_id=self.run_id,
        )
        self.assertEqual(summary.rejected, 1)
        self.assertEqual(
            self.repo.conn.execute("SELECT COUNT(*) FROM research_items").fetchone()[0], 0
        )

    def test_blocked_batch_is_reported(self) -> None:
        batch = xhs_batch()
        batch["articles"] = [
            {"ok": False, "error_type": "login_required", "message": "redirected_to_login"}
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "batch.json"
            path.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
            result = BatchResult.load(
                path, platform="xiaohongshu", run_id=self.run_id, query="26届 到手工资"
            )
        summary = ingest_batch(
            self.repo,
            self.service,
            result,
            self._task("xiaohongshu", "26届 到手工资"),
            engine_run_id=self.run_id,
        )
        self.assertTrue(summary.blocked)
        self.assertEqual(summary.accepted, 0)

    def test_candidate_id_matches_queue(self) -> None:
        candidate = candidate_id_for("xiaohongshu", XHS_URL)
        self.assertTrue(candidate.startswith("cd_"))


if __name__ == "__main__":
    unittest.main()
