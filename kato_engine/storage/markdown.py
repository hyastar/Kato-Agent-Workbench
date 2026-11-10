"""文章与评论的 Markdown 导出（幂等 + 哈希）。

复用 V4 的渲染函数，保证 41 篇历史档案与新档案格式一致。
写入前比较内容哈希：内容未变则不改写文件，避免无意义的时间戳抖动。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from scripts import db
from scripts.employment.markdown_export import (
    render_comments_markdown,
    render_post_markdown,
)

from kato_engine.config.settings import Settings


@dataclass
class ExportResult:
    post_path: str | None
    comments_path: str | None
    post_sha: str | None
    comments_sha: str | None
    post_changed: bool
    comments_changed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "post_path": self.post_path,
            "comments_path": self.comments_path,
            "post_sha": self.post_sha,
            "comments_sha": self.comments_sha,
            "post_changed": self.post_changed,
            "comments_changed": self.comments_changed,
        }


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_if_changed(path: Path, text: str) -> bool:
    """内容相同则不写；返回是否发生写入。"""
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing == text:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return True


def platform_dir(settings: Settings, platform: str) -> Path:
    return settings.employment_data_dir / platform


def export_article(
    settings: Settings,
    item: dict[str, Any],
    comments: Iterable[dict[str, Any]],
    stats: dict[str, Any],
) -> ExportResult:
    """导出单篇文章与评论档案；返回仓库相对路径与哈希。"""
    platform = str(item["platform"])
    item_id = str(item["item_id"])
    base = platform_dir(settings, platform)

    post_text = render_post_markdown(item, stats)
    comments_text = render_comments_markdown(item, comments, stats)

    post_file = base / "posts" / f"{item_id}.md"
    comments_file = base / "comments" / f"{item_id}.comments.md"

    post_changed = _write_if_changed(post_file, post_text)
    comments_changed = _write_if_changed(comments_file, comments_text)

    return ExportResult(
        post_path=db.to_repo_relative(post_file),
        comments_path=db.to_repo_relative(comments_file),
        post_sha=sha256_text(post_text),
        comments_sha=sha256_text(comments_text),
        post_changed=post_changed,
        comments_changed=comments_changed,
    )


def verify_artifacts(settings: Settings, repo) -> dict[str, Any]:  # noqa: ANN001
    """核对 research_artifacts 中记录的哈希与磁盘文件是否一致。"""
    rows = repo.conn.execute(
        "SELECT relative_path, sha256 FROM research_artifacts "
        "WHERE artifact_type IN ('post_markdown', 'comments_markdown')"
    ).fetchall()
    missing: list[str] = []
    mismatched: list[str] = []
    checked = 0
    for row in rows:
        path = settings.repo_root / str(row["relative_path"])
        checked += 1
        if not path.exists():
            missing.append(str(row["relative_path"]))
            continue
        actual = sha256_text(path.read_text(encoding="utf-8"))
        if actual != str(row["sha256"]):
            mismatched.append(str(row["relative_path"]))
    return {
        "checked": checked,
        "missing": missing[:50],
        "missing_count": len(missing),
        "mismatched": mismatched[:50],
        "mismatched_count": len(mismatched),
    }
