"""V6.1 引擎配置。

原则：
- 路径一律相对仓库根目录推导，不硬编码盘符或用户名；
- 不含任何浏览器、Profile 或焦点管理配置：浏览器由 ZCode 内置 Browser Use 持有；
- 所有可调参数都能用环境变量覆盖。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]


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


@dataclass(frozen=True)
class Settings:
    """一次引擎运行的静态配置。"""

    repo_root: Path
    db_path: Path
    data_dir: Path
    runs_dir: Path
    keyword_library_path: Path
    comment_limit: int = 50
    max_attempts: int = 3
    lease_seconds: int = 900
    metrics_dir: Path = field(default_factory=lambda: REPO_ROOT / "runs")

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
    keywords = Path(
        source.get("KATO_KEYWORD_LIBRARY") or root / "tasks" / "employment" / "search_keywords.json"
    )

    return Settings(
        repo_root=root,
        db_path=db_path,
        data_dir=data_dir,
        runs_dir=runs_dir,
        keyword_library_path=keywords,
        metrics_dir=runs_dir,
        comment_limit=_env_int(source, "KATO_COMMENT_LIMIT", 50, minimum=1),
        max_attempts=_env_int(source, "KATO_MAX_ATTEMPTS", 3, minimum=1),
        lease_seconds=_env_int(source, "KATO_LEASE_SECONDS", 900, minimum=60),
    )
