"""V6.1 离线测试：就业生态分类与时间清洗（与浏览器无关）。"""

from __future__ import annotations

import unittest

from kato_engine.collection.classification import classify
from kato_engine.collection.thread_tree import clean_date_text


class ClassificationTests(unittest.TestCase):
    def test_salary_article(self) -> None:
        result = classify("26届毕业生到手工资5000", "试用期三个月，工资到手 5000，房租 1500。")
        self.assertEqual(result.employment_topic, "salary")
        self.assertEqual(result.graduation_cohort, "2026")
        self.assertEqual(result.event_year, 2026)
        self.assertEqual(result.employment_status, "probation")

    def test_layoff_article(self) -> None:
        result = classify("27届还没入职就被裁了", "公司裁员，应届生被毁约，现在失业在家。")
        self.assertEqual(result.employment_topic, "layoff")
        self.assertEqual(result.graduation_cohort, "2027")

    def test_computer_article_uses_db_topic(self) -> None:
        result = classify("程序员的2026", "计算机专业毕业，进了互联网大厂做后端开发。")
        self.assertEqual(result.employment_topic, "computer")

    def test_work_life_article_uses_db_topic(self) -> None:
        result = classify("大小周真的顶不住", "单休、加班、通勤两小时，房租还涨了。")
        self.assertEqual(result.employment_topic, "work_life")

    def test_irrelevant_text_is_unmatched(self) -> None:
        result = classify("今天做了番茄炒蛋", "先把鸡蛋打散，番茄切块，热锅下油。")
        self.assertFalse(result.matched_topic)
        self.assertIsNone(result.employment_topic)
        self.assertEqual(result.legacy_topic, "other")

    def test_recruitment_ad_detection(self) -> None:
        result = classify(
            "招聘｜机械设计岗位",
            "岗位职责：负责设备设计；任职要求：本科以上；简历投递邮箱。",
        )
        self.assertEqual(result.experience_type, "recruitment_ad")

    def test_recruitment_stage(self) -> None:
        result = classify("2027届秋招记录", "面试了五家公司，最后签了三方。")
        self.assertEqual(result.recruitment_stage, "autumn")
        self.assertEqual(result.legacy_topic, "recruitment")


class DateCleaningTests(unittest.TestCase):
    def test_region_suffix_is_dropped(self) -> None:
        self.assertEqual(clean_date_text("05-24河北"), "05-24")
        self.assertEqual(clean_date_text("3天前 上海"), "3天前")

    def test_edit_prefix_is_dropped(self) -> None:
        self.assertEqual(clean_date_text("编辑于 04-15"), "04-15")

    def test_unknown_text_returns_none(self) -> None:
        self.assertIsNone(clean_date_text("刚刚"))
        self.assertIsNone(clean_date_text(None))


if __name__ == "__main__":
    unittest.main()
