"""V6 浏览器层离线测试。

不启动浏览器、不联网：
- 配置解析与 Profile 安全约束；
- 稳定性判定；
- URL 规范化；
- Profile 占用检测的纯逻辑分支；
- 异常分类。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kato_engine.browser.errors import (
    AuthRequiredError,
    EngineError,
    ProfileInUseError,
    RateLimitedError,
    SelectorMissingError,
)
from kato_engine.browser.manager import profile_holders
from kato_engine.browser.navigation import StabilityTracker, strip_query
from kato_engine.config.settings import Settings, find_chrome_executable, load_settings


class SettingsTests(unittest.TestCase):
    def test_defaults_resolve_inside_repo(self) -> None:
        settings = load_settings(env={})
        self.assertEqual(settings.repo_root.name, "Kato-Agent-Workbench")
        self.assertEqual(settings.db_path.name, "workbench.sqlite3")
        self.assertFalse(settings.headless)
        self.assertEqual(settings.comment_limit, 50)
        self.assertEqual(settings.browser_channel, "chrome")

    def test_profile_inside_repo_is_rejected_by_loader(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            with self.assertRaises(ValueError):
                load_settings(
                    env={"KATO_BROWSER_PROFILE": str(repo / ".profile")}, repo_root=repo
                )

    def test_env_overrides_are_applied(self) -> None:
        settings = load_settings(
            env={
                "KATO_BROWSER_HEADLESS": "1",
                "KATO_COMMENT_LIMIT": "50",
                "KATO_NAV_TIMEOUT_MS": "45000",
                "KATO_BROWSER_CHANNEL": "chrome",
            }
        )
        self.assertTrue(settings.headless)
        self.assertEqual(settings.nav_timeout_ms, 45_000)

    def test_invalid_env_value_raises(self) -> None:
        with self.assertRaises(ValueError):
            load_settings(env={"KATO_COMMENT_LIMIT": "abc"})

    def test_settings_rejects_profile_inside_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            with self.assertRaises(ValueError):
                Settings(
                    repo_root=repo,
                    db_path=repo / "db.sqlite3",
                    data_dir=repo / "data",
                    profile_dir=repo / ".profile",
                    runs_dir=repo / "runs",
                    keyword_library_path=repo / "kw.json",
                )

    def test_find_chrome_executable_returns_path_or_none(self) -> None:
        found = find_chrome_executable()
        self.assertTrue(found is None or found.is_file())


class StabilityTests(unittest.TestCase):
    def test_stable_after_three_identical_observations(self) -> None:
        tracker = StabilityTracker(stable_rounds=3)
        self.assertFalse(tracker.observe(10))
        self.assertFalse(tracker.observe(10))
        self.assertFalse(tracker.observe(10))
        self.assertTrue(tracker.observe(10))

    def test_growth_resets_counter(self) -> None:
        tracker = StabilityTracker(stable_rounds=2)
        tracker.observe(5)
        tracker.observe(5)
        self.assertFalse(tracker.observe(9))
        self.assertFalse(tracker.observe(9))
        self.assertTrue(tracker.observe(9))


class UrlTests(unittest.TestCase):
    def test_strip_query_removes_token_and_fragment(self) -> None:
        url = "https://www.xiaohongshu.com/explore/abc123?xsec_token=SECRET&xsec_source=pc#top"
        self.assertEqual(strip_query(url), "https://www.xiaohongshu.com/explore/abc123")

    def test_strip_query_lowercases_host(self) -> None:
        self.assertEqual(
            strip_query("HTTPS://Zhuanlan.ZhiHu.com/p/1234?utm=x"),
            "https://zhuanlan.zhihu.com/p/1234",
        )

    def test_strip_query_keeps_bare_path(self) -> None:
        self.assertEqual(strip_query("https://www.zhihu.com/question/1"), "https://www.zhihu.com/question/1")


class ProfileLockTests(unittest.TestCase):
    def test_missing_profile_has_no_holders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(profile_holders(Path(tmp) / "nope"), [])

    def test_empty_profile_has_no_holders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            holders = profile_holders(Path(tmp))
            self.assertIn(holders, ([], None))


class ErrorTaxonomyTests(unittest.TestCase):
    def test_retryable_and_human_flags(self) -> None:
        self.assertTrue(SelectorMissingError("x").retryable)
        self.assertTrue(AuthRequiredError("x").needs_human)
        self.assertTrue(RateLimitedError("x").needs_human)
        self.assertTrue(ProfileInUseError("x").needs_human)

    def test_to_dict_contains_classification(self) -> None:
        payload = EngineError("boom", detail={"a": 1}).to_dict()
        self.assertEqual(payload["error_type"], "engine_error")
        self.assertFalse(payload["retryable"])
        self.assertEqual(payload["detail"], {"a": 1})


if __name__ == "__main__":
    unittest.main()
