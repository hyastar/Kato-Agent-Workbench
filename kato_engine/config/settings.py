"""V6 引擎配置。

原则：
- 路径一律相对仓库根目录推导，不硬编码盘符或用户名；
- 浏览器 Profile 必须位于仓库之外（防止 Cookie/登录态进入版本库）；
- 所有可调参数都能用环境变量覆盖，便于在不同机器与阶段复现。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE_DIR = REPO_ROOT.parent / ".kato-playwright-profile"
DEFAULT_CHROME_PATHS: tuple[Path, ...] = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "Application" / "chrome.exe",
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/usr/bin/google-chrome"),
    Path("/usr/bin/chromium"),
)


def _env_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(env: Mapping[str, str], name: str, default: int, *, minimum: int = 0) -> int:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"环境变量 {name} 必须是整数：{raw!r}") from exc
    if value < minimum:
        raise ValueError(f"环境变量 {name} 不能小于 {minimum}：{value}")
    return value


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


@dataclass(frozen=True)
class Settings:
    """一次引擎运行的静态配置。"""

    repo_root: Path
    db_path: Path
    data_dir: Path
    profile_dir: Path
    runs_dir: Path
    keyword_library_path: Path
    browser_channel: str = "chrome"
    headless: bool = False
    nav_timeout_ms: int = 30_000
    action_timeout_ms: int = 10_000
    settle_ms: int = 1_200
    comment_limit: int = 50
    max_attempts: int = 3
    lease_seconds: int = 900
    pause_between_articles_ms: int = 2_500
    pause_between_queries_ms: int = 4_000
    metrics_dir: Path = field(default_factory=lambda: REPO_ROOT / "runs")

    def __post_init__(self) -> None:
        if _is_inside(self.profile_dir, self.repo_root):
            raise ValueError(
                "浏览器 Profile 不能位于仓库内（会泄露 Cookie 与登录态）："
                f"{self.profile_dir}"
            )

    # -- 派生路径 ---------------------------------------------------------
    @property
    def employment_data_dir(self) -> Path:
        return self.data_dir / "employment"

    def platform_data_dir(self, platform: str) -> Path:
        return self.employment_data_dir / platform

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.runs_dir, self.db_path.parent):
            path.mkdir(parents=True, exist_ok=True)


def load_settings(
    env: Mapping[str, str] | None = None,
    *,
    repo_root: Path | None = None,
) -> Settings:
    """从环境变量构造配置。未提供的项使用仓库默认值。"""
    source = os.environ if env is None else env
    root = Path(repo_root) if repo_root is not None else REPO_ROOT

    db_path = Path(source.get("KATO_DB_PATH") or root / "data" / "catalog" / "workbench.sqlite3")
    data_dir = Path(source.get("KATO_DATA_DIR") or root / "data")
    runs_dir = Path(source.get("KATO_RUNS_DIR") or root / "runs")
    profile_raw = source.get("KATO_BROWSER_PROFILE")
    profile_dir = Path(profile_raw) if profile_raw else root.parent / ".kato-playwright-profile"
    keywords = Path(
        source.get("KATO_KEYWORD_LIBRARY") or root / "tasks" / "employment" / "search_keywords.json"
    )

    return Settings(
        repo_root=root,
        db_path=db_path,
        data_dir=data_dir,
        profile_dir=profile_dir,
        runs_dir=runs_dir,
        keyword_library_path=keywords,
        metrics_dir=runs_dir,
        browser_channel=(source.get("KATO_BROWSER_CHANNEL") or "chrome").strip(),
        headless=_env_bool(source, "KATO_BROWSER_HEADLESS", False),
        nav_timeout_ms=_env_int(source, "KATO_NAV_TIMEOUT_MS", 30_000, minimum=1_000),
        action_timeout_ms=_env_int(source, "KATO_ACTION_TIMEOUT_MS", 10_000, minimum=500),
        settle_ms=_env_int(source, "KATO_SETTLE_MS", 1_200, minimum=0),
        comment_limit=_env_int(source, "KATO_COMMENT_LIMIT", 50, minimum=1),
        max_attempts=_env_int(source, "KATO_MAX_ATTEMPTS", 3, minimum=1),
        lease_seconds=_env_int(source, "KATO_LEASE_SECONDS", 900, minimum=60),
        pause_between_articles_ms=_env_int(source, "KATO_PAUSE_ARTICLE_MS", 2_500, minimum=0),
        pause_between_queries_ms=_env_int(source, "KATO_PAUSE_QUERY_MS", 4_000, minimum=0),
    )


def find_chrome_executable(paths: tuple[Path, ...] = DEFAULT_CHROME_PATHS) -> Path | None:
    """返回本机可用的 Chrome 可执行文件；找不到返回 None。"""
    for path in paths:
        if path.is_file():
            return path
    return None
