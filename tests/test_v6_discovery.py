"""V6 阶段 3 离线测试：关键词调度、候选队列、去重与状态机。

不联网、不启动浏览器；使用临时 SQLite。
"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from kato_engine.config.settings import load_settings
from kato_engine.core.state_machine import InvalidTransition, assert_transition, can_transition
from kato_engine.discovery.candidate_queue import CandidateQueue, SearchHit
from kato_engine.discovery.deduplication import canonical_url
from kato_engine.discovery.keyword_planner import (
    KeywordPlanner,
    build_combinations,
    load_keyword_library,
)
from kato_engine.storage.repository import EngineRepository

KEYWORD_LIBRARY = Path("tasks/employment/search_keywords.json")


class RepositoryTestCase(unittest.TestCase):
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
        self.repo, self.schema = EngineRepository.open(self.settings)
        self.addCleanup(self.repo.close)
        self.campaign_id = "employment-test"
        self.queue = CandidateQueue(self.repo)

    def _add(self, urls: list[str], *, platform: str = "xiaohongshu", dimension: str = "salary"):
        hits = [SearchHit(title=f"t{i}", canonical_url=url, raw_index=i) for i, url in enumerate(urls)]
        return self.queue.add(
            campaign_id=self.campaign_id,
            platform=platform,
            dimension=dimension,
            keyword="2026 工资",
            combined_query="26届 2026 工资",
            hits=hits,
        )


class KeywordLibraryTests(unittest.TestCase):
    def test_library_has_ten_dimensions(self) -> None:
        library = load_keyword_library(KEYWORD_LIBRARY)
        self.assertEqual(len(library.dimensions), 10)
        self.assertGreaterEqual(len(library.modifiers), 3)
        # V6.2：基础关键词 250（原有 100 + 新增 150），修饰词不计入。
        self.assertGreaterEqual(sum(len(d.keywords) for d in library.dimensions), 250)

    def test_combinations_use_modifier_when_no_year(self) -> None:
        self.assertEqual(
            build_combinations("到手工资", ["26届", "27届"]),
            ["26届 到手工资", "27届 到手工资"],
        )

    def test_combinations_keep_keyword_with_year(self) -> None:
        self.assertEqual(build_combinations("2026 工资", ["26届"]), ["2026 工资"])


class PlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.library = load_keyword_library(KEYWORD_LIBRARY)

    def test_first_plan_targets_largest_deficit(self) -> None:
        # salary 目标 160、layoff 100：都缺满额时 salary 优先。
        planner = KeywordPlanner(self.library)
        plan = planner.next_plan()
        self.assertIsNotNone(plan)
        self.assertEqual(plan.dimension, "salary")

    def test_plan_skips_executed_queries(self) -> None:
        planner = KeywordPlanner(self.library, executed_queries=["2026 工资"])
        plan = planner.next_plan()
        self.assertIsNotNone(plan)
        self.assertNotEqual(plan.combined_query, "2026 工资")

    def test_plan_returns_none_when_every_combination_executed(self) -> None:
        library = load_keyword_library(KEYWORD_LIBRARY)
        executed = [
            combo
            for dimension in library.dimensions
            for keyword in dimension.keywords
            for combo in build_combinations(keyword, library.modifiers)
        ]
        planner = KeywordPlanner(library, executed_queries=executed)
        self.assertIsNone(planner.next_plan())
        self.assertEqual(len(planner.exhausted_dimensions()), len(library.dimensions))

    def test_deficit_accounts_for_pipeline(self) -> None:
        planner = KeywordPlanner(
            self.library,
            accepted_by_dimension={"salary": 150},
            pipeline_by_dimension={"salary": 10},
        )
        plan = planner.next_plan()
        self.assertIsNotNone(plan)
        self.assertNotEqual(plan.dimension, "salary")

    def test_dimension_targets_override(self) -> None:
        planner = KeywordPlanner(
            self.library,
            accepted_by_dimension={d.id: d.target for d in self.library.dimensions},
            dimension_targets={"salary": 200},
        )
        plan = planner.next_plan()
        self.assertIsNotNone(plan)
        self.assertEqual(plan.dimension, "salary")


class CanonicalUrlTests(unittest.TestCase):
    def test_xiaohongshu_token_removed(self) -> None:
        url = "https://www.xiaohongshu.com/explore/65f0a1b2c3d4e5f60718293a?xsec_token=SECRET&xsec_source=pc"
        self.assertEqual(
            canonical_url("xiaohongshu", url),
            "https://www.xiaohongshu.com/explore/65f0a1b2c3d4e5f60718293a",
        )

    def test_xiaohongshu_discovery_path_normalized(self) -> None:
        self.assertEqual(
            canonical_url("xiaohongshu", "https://www.xiaohongshu.com/discovery/item/65f0a1b2c3d4e5f6"),
            "https://www.xiaohongshu.com/explore/65f0a1b2c3d4e5f6",
        )

    def test_zhihu_question_drops_answer_query(self) -> None:
        self.assertEqual(
            canonical_url("zhihu", "https://www.zhihu.com/question/123/answer/456?utm=x"),
            "https://www.zhihu.com/answer/456",
        )
        self.assertEqual(
            canonical_url("zhihu", "https://www.zhihu.com/question/123?sort=created"),
            "https://www.zhihu.com/question/123",
        )

    def test_zhihu_column_normalized(self) -> None:
        self.assertEqual(
            canonical_url("zhihu", "https://zhuanlan.zhihu.com/p/1928189769294288789/?utm=x"),
            "https://zhuanlan.zhihu.com/p/1928189769294288789",
        )

    def test_unknown_url_rejected(self) -> None:
        with self.assertRaises(ValueError):
            canonical_url("xiaohongshu", "https://www.xiaohongshu.com/search_result?keyword=x")
        with self.assertRaises(ValueError):
            canonical_url("zhihu", "https://www.zhihu.com/search?q=x")


class QueueTests(RepositoryTestCase):
    def test_enqueue_and_deduplicate(self) -> None:
        url = "https://www.xiaohongshu.com/explore/65f0a1b2c3d4e5f60718293a"
        result = self._add([url, url + "?xsec_token=A", url + "?xsec_token=B"])
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(result["duplicates"], 2)
        self.assertEqual(self.queue.stats(campaign_id=self.campaign_id)["queued"], 1)

    def test_invalid_urls_are_counted_not_enqueued(self) -> None:
        result = self._add(["https://www.xiaohongshu.com/search_result?keyword=x"])
        self.assertEqual(result["inserted"], 0)
        self.assertEqual(result["invalid"], 1)

    def test_reenqueue_is_idempotent(self) -> None:
        url = "https://www.xiaohongshu.com/explore/65f0a1b2c3d4e5f60718293a"
        self._add([url])
        second = self._add([url])
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(second["duplicates"], 1)
        self.assertEqual(self.queue.stats(campaign_id=self.campaign_id)["queued"], 1)

    def test_claim_leases_only_once(self) -> None:
        self._add(["https://www.xiaohongshu.com/explore/65f0a1b2c3d4e5f60718293a"])
        first = self.queue.claim(campaign_id=self.campaign_id, platform="xiaohongshu")
        self.assertIsNotNone(first)
        self.assertEqual(first["state"], "processing")
        self.assertEqual(first["attempts"], 1)
        self.assertIsNone(self.queue.claim(campaign_id=self.campaign_id, platform="xiaohongshu"))

    def test_expired_lease_is_recovered(self) -> None:
        self._add(["https://www.xiaohongshu.com/explore/65f0a1b2c3d4e5f60718293a"])
        claimed = self.queue.claim(campaign_id=self.campaign_id, platform="xiaohongshu")
        with self.repo.conn:
            self.repo.conn.execute(
                "UPDATE engine_candidates SET lease_until = ? WHERE candidate_id = ?",
                ("2020-01-01T00:00:00.000Z", claimed["candidate_id"]),
            )
        self.assertEqual(self.repo.recover_expired_leases(self.campaign_id), 1)
        again = self.queue.claim(campaign_id=self.campaign_id, platform="xiaohongshu")
        self.assertIsNotNone(again)
        self.assertEqual(again["attempts"], 2)

    def test_claim_stops_at_max_attempts(self) -> None:
        self._add(["https://www.xiaohongshu.com/explore/65f0a1b2c3d4e5f60718293a"])
        claimed = self.queue.claim(campaign_id=self.campaign_id, platform="xiaohongshu")
        with self.repo.conn:
            self.repo.conn.execute(
                "UPDATE engine_candidates SET state = 'retryable_failed', attempts = ?, "
                "lease_until = NULL WHERE candidate_id = ?",
                (self.settings.max_attempts, claimed["candidate_id"]),
            )
        self.assertIsNone(self.queue.claim(campaign_id=self.campaign_id, platform="xiaohongshu"))

    def test_state_transitions_are_recorded(self) -> None:
        self._add(["https://www.xiaohongshu.com/explore/65f0a1b2c3d4e5f60718293a"])
        claimed = self.queue.claim(campaign_id=self.campaign_id, platform="xiaohongshu")
        self.repo.mark_accepted(claimed["candidate_id"], "ri_test")
        self.repo.mark_completed(claimed["candidate_id"])
        row = self.repo.conn.execute(
            "SELECT state, item_id FROM engine_candidates WHERE candidate_id = ?",
            (claimed["candidate_id"],),
        ).fetchone()
        self.assertEqual(row["state"], "completed")
        self.assertEqual(row["item_id"], "ri_test")

    def test_illegal_transition_is_rejected(self) -> None:
        with self.assertRaises(InvalidTransition):
            assert_transition("completed", "queued")
        # rejected 不是永久事实：结果页重排后同一 URL 可能在后续批次重新遇到，
        # 未达重试上限时允许复活。
        self.assertTrue(can_transition("rejected", "processing"))
        self.assertFalse(can_transition("completed", "processing"))

    def test_requeue_blocked_after_human_fix(self) -> None:
        self._add(["https://www.xiaohongshu.com/explore/65f0a1b2c3d4e5f60718293a"])
        claimed = self.queue.claim(campaign_id=self.campaign_id, platform="xiaohongshu")
        self.repo.mark_blocked(
            claimed["candidate_id"], error_type="verification_required", reason="滑块"
        )
        self.assertEqual(
            self.queue.stats(campaign_id=self.campaign_id)["blocked"], 1
        )
        self.assertEqual(self.repo.requeue_blocked("xiaohongshu", campaign_id=self.campaign_id), 1)
        self.assertEqual(self.queue.pending(campaign_id=self.campaign_id, platform="xiaohongshu"), 1)

    def test_duplicate_already_collected_is_skipped(self) -> None:
        from scripts import db

        conn = self.repo.conn
        db.upsert_research_item(
            conn,
            platform="zhihu",
            canonical_url="https://zhuanlan.zhihu.com/p/111",
            title="已存在",
            source_type="ugc",
            topic="experience",
            cohort="2026",
            recruitment_stage="unknown",
        )
        result = self._add(["https://zhuanlan.zhihu.com/p/111?utm=x"], platform="zhihu")
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(result["skipped_existing"], 1)
        self.assertEqual(self.queue.stats(campaign_id=self.campaign_id)["skipped"], 1)

    def test_query_run_records_and_marks_executed(self) -> None:
        self.repo.record_query_run(
            campaign_id=self.campaign_id,
            platform="zhihu",
            dimension="salary",
            keyword="2026 工资",
            combined_query="2026 工资",
            candidates_found=12,
            duplicates=2,
            opened_details=3,
            accepted=2,
            duration_ms=1234,
        )
        self.assertIn("2026 工资", self.repo.executed_queries("zhihu"))
        stats = self.repo.dimension_query_stats(self.campaign_id, "zhihu")
        self.assertEqual(stats["salary"]["queries"], 1)
        self.assertEqual(stats["salary"]["accepted"], 2)


class SchemaTests(RepositoryTestCase):
    def test_schema_version_and_engine_tables(self) -> None:
        self.assertEqual(self.schema.to_version, 6)
        self.assertTrue(self.schema.integrity_ok)
        self.assertEqual(self.schema.foreign_key_violations, 0)
        tables = {
            row[0]
            for row in self.repo.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        for required in ("engine_candidates", "engine_query_runs", "engine_runs", "engine_metrics"):
            self.assertIn(required, tables)

    def test_migration_is_idempotent(self) -> None:
        again, report = EngineRepository.open(self.settings)
        try:
            self.assertEqual(report.applied, ())
            self.assertEqual(report.to_version, 6)
        finally:
            again.close()


if __name__ == "__main__":
    unittest.main()
