"""V6.2 离线测试：250 关键词库、调度分层、修饰词轮换、辅助分类、动态词发现。"""

from __future__ import annotations

import unittest
from pathlib import Path

from kato_engine.agent.dynamic_keywords import extract_candidates
from kato_engine.collection.classification import classify
from kato_engine.discovery.keyword_planner import (
    KeywordPlanner,
    KeywordStat,
    build_combinations,
    load_keyword_library,
    rotate_modifier,
)

KEYWORDS = Path("tasks/employment/search_keywords.json")


class LibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.library = load_keyword_library(KEYWORDS)

    def test_base_keywords_at_least_250(self) -> None:
        self.assertGreaterEqual(self.library.base_keyword_total(), 250)

    def test_ten_dimensions_preserved(self) -> None:
        self.assertEqual(len(self.library.dimensions), 10)

    def test_fifteen_new_directions(self) -> None:
        self.assertEqual(len(self.library.directions), 15)
        dimensions = {item["dimension"] for item in self.library.directions}
        self.assertTrue(dimensions.issubset({d.id for d in self.library.dimensions}))

    def test_year_and_cohort_modifiers_present(self) -> None:
        for token in ("2023", "2026", "2028", "23届", "28届", "2023届", "2028届"):
            self.assertIn(token, self.library.modifiers)
        for token in ("应届生", "往届生", "毕业三年", "研究生", "实习生"):
            self.assertIn(token, self.library.modifiers)

    def test_no_duplicate_base_keywords(self) -> None:
        keywords = [kw for dim in self.library.dimensions for kw in dim.keywords]
        self.assertEqual(len(keywords), len(set(keywords)))

    def test_keyword_source_recorded(self) -> None:
        self.assertEqual(self.library.meta_for("2026 工资").get("source"), "v6.1")
        self.assertEqual(self.library.meta_for("劳动仲裁经历").get("source"), "v6.2")
        self.assertEqual(self.library.meta_for("劳动仲裁经历").get("direction"), "layoff_dispute")


class RotationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.library = load_keyword_library(KEYWORDS)

    def test_one_modifier_per_attempt(self) -> None:
        combos = rotate_modifier("劳动仲裁经历", self.library.modifiers, 0)
        self.assertEqual(len(combos), len(self.library.modifiers))
        # 每次只取第一个组合即一个修饰词，而不是笛卡尔积
        self.assertEqual(combos[0].count(" "), 1)

    def test_rotation_advances_with_attempt(self) -> None:
        first = rotate_modifier("劳动仲裁经历", self.library.modifiers, 0)[0]
        second = rotate_modifier("劳动仲裁经历", self.library.modifiers, 1)[0]
        self.assertNotEqual(first, second)

    def test_year_keyword_not_prefixed(self) -> None:
        self.assertEqual(build_combinations("2026 工资", self.library.modifiers), ["2026 工资"])


class PlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.library = load_keyword_library(KEYWORDS)

    def test_preview_returns_distinct_keywords(self) -> None:
        planner = KeywordPlanner(self.library)
        plans = planner.next_plans(8)
        self.assertEqual(len(plans), 8)
        self.assertEqual(len({plan.keyword for plan in plans}), 8)

    def test_explore_before_exploit(self) -> None:
        planner = KeywordPlanner(
            self.library,
            stats={"2026 工资": KeywordStat(searches=5, found=100, duplicates=90, accepted=1)},
        )
        plan = planner.next_plan()
        self.assertIsNotNone(plan)
        self.assertNotEqual(plan.keyword, "2026 工资")
        self.assertEqual(plan.reason, "explore")

    def test_high_yield_keyword_preferred_after_exploration(self) -> None:
        # 只剩一个维度有缺口，且该维度关键词全部搜索过时，按产出效率选择
        library = load_keyword_library(KEYWORDS)
        salary = library.dimension("salary")
        stats = {kw: KeywordStat(searches=2, accepted=0) for kw in salary.keywords}
        stats[salary.keywords[0]] = KeywordStat(searches=2, accepted=5)
        planner = KeywordPlanner(
            library,
            accepted_by_dimension={
                d.id: (d.target if d.id != "salary" else 0) for d in library.dimensions
            },
            stats=stats,
        )
        plan = planner.next_plan()
        self.assertIsNotNone(plan)
        self.assertEqual(plan.dimension, "salary")
        self.assertEqual(plan.keyword, salary.keywords[0])
        self.assertEqual(plan.reason, "exploit")

    def test_all_combinations_executed_returns_none(self) -> None:
        executed = [
            combined
            for dimension in self.library.dimensions
            for keyword in dimension.keywords
            for combined in build_combinations(keyword, self.library.modifiers)
        ]
        planner = KeywordPlanner(self.library, executed_queries=executed)
        self.assertIsNone(planner.next_plan())

    def test_approved_dynamic_keyword_enters_planning(self) -> None:
        planner = KeywordPlanner(
            self.library,
            accepted_by_dimension={
                d.id: (d.target if d.id != "factory" else 0) for d in self.library.dimensions
            },
            extra_keywords={"factory": ["新能源电池装配工资"]},
        )
        plans = planner.next_plans(200)
        self.assertTrue(any(plan.keyword == "新能源电池装配工资" for plan in plans))

    def test_plan_has_single_modifier(self) -> None:
        planner = KeywordPlanner(self.library)
        plan = planner.next_plan()
        self.assertIsNotNone(plan)
        if plan.modifier:
            self.assertEqual(plan.combined_query.count(" "), 1)


class AuxClassificationTests(unittest.TestCase):
    def test_labor_dispatch(self) -> None:
        result = classify("劳务派遣三年", "我是劳务派遣员工，和正式工待遇差很多，五险一金按最低基数交。")
        self.assertEqual(result.employment_type, "劳务派遣")
        self.assertIn("社保", result.benefits or "")
        self.assertIn("公积金", result.benefits or "")

    def test_outsourcing(self) -> None:
        result = classify("驻场外包", "软件外包驻场两年，工资比正式员工低。")
        self.assertEqual(result.employment_type, "外包")

    def test_internship(self) -> None:
        result = classify("暑期实习记录", "大学生暑期实习，实习工资一天一百。")
        self.assertEqual(result.employment_type, "实习")

    def test_benefits_tags(self) -> None:
        result = classify("offer对比", "这家包吃包住还有餐补，公积金按12%交。")
        self.assertIn("包吃住", result.benefits or "")
        self.assertIn("餐补", result.benefits or "")
        self.assertIn("公积金", result.benefits or "")


class DynamicKeywordTests(unittest.TestCase):
    def test_extract_filters_and_ranks(self) -> None:
        texts = [
            ("i1", "劳务派遣工资低，五险一金按最低基数"),
            ("i2", "劳务派遣工资低，转正也难"),
            ("i3", "今天天气不错"),
        ]
        candidates = extract_candidates(texts, existing=(), limit=10, min_occurrences=2)
        keywords = [item.keyword for item in candidates]
        self.assertTrue(any("劳务派遣" in kw for kw in keywords))
        self.assertFalse(any("天气" in kw for kw in keywords))

    def test_existing_keywords_excluded(self) -> None:
        texts = [("i1", "劳动仲裁经历分享"), ("i2", "劳动仲裁经历分享")]
        # 候选包含已有基础词时也视为近似重复，不进入候选池
        candidates = extract_candidates(
            texts, existing={"劳动仲裁经历"}, limit=10, min_occurrences=2
        )
        self.assertEqual(candidates, [])


if __name__ == "__main__":
    unittest.main()
