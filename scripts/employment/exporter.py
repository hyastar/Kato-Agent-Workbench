"""文章/评论 Markdown 与索引导出，并登记产物。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.employment import artifacts, markdown_export, repository


def _stats_from_row(row: sqlite3.Row) -> dict[str, object]:
    return {
        "displayed_total": row["displayed_comments_total"],
        "displayed_top_level": row["displayed_top_level"],
        "collected_top_level": row["collected_top_level"],
        "displayed_replies": row["displayed_replies_total"],
        "collected_replies": row["collected_replies"],
        "coverage_status": row["comment_coverage_status"],
        "sort_basis": row["comment_sort_basis"],
    }


def export_article_artifacts(
    conn: sqlite3.Connection,
    item_id: str,
    *,
    root: str | Path | None = None,
) -> dict[str, dict[str, object]]:
    """生成单篇文章与评论 Markdown，登记产物并回写路径。"""
    row = repository.get_article(conn, item_id)
    if row is None:
        raise KeyError(f"研究条目不存在：{item_id}")
    article = dict(row)
    stats = _stats_from_row(row)
    comments = [dict(item) for item in repository.list_comments(conn, item_id)]

    post_text = markdown_export.render_post_markdown(article, stats)
    post_path = artifacts.artifact_path(
        article["platform"], item_id, "post_markdown", root=root
    )
    post_meta = artifacts.write_text_artifact(post_path, post_text)
    repository.upsert_artifact(
        conn,
        item_id=item_id,
        artifact_type="post_markdown",
        relative_path=str(post_meta["relative_path"]),
        sha256=str(post_meta["sha256"]),
    )

    comments_text = markdown_export.render_comments_markdown(article, comments, stats)
    comments_path = artifacts.artifact_path(
        article["platform"], item_id, "comments_markdown", root=root
    )
    comments_meta = artifacts.write_text_artifact(comments_path, comments_text)
    repository.upsert_artifact(
        conn,
        item_id=item_id,
        artifact_type="comments_markdown",
        relative_path=str(comments_meta["relative_path"]),
        sha256=str(comments_meta["sha256"]),
    )

    repository.set_article_markdown_paths(
        conn,
        item_id,
        post_path=str(post_meta["relative_path"]),
        comments_path=str(comments_meta["relative_path"]),
    )
    return {"post": post_meta, "comments": comments_meta}


def export_platform_index(
    conn: sqlite3.Connection,
    platform: str,
    *,
    cohort: str | None = None,
    root: str | Path | None = None,
) -> dict[str, object]:
    """生成平台 all / 2026 / 2027 索引 Markdown。"""
    rows = repository.list_articles(conn, platform=platform, cohort=cohort)
    title = f"{platform} 就业情报索引"
    if cohort:
        title += f" — {cohort} 届"
    name = cohort or "all"
    text = markdown_export.render_index([dict(row) for row in rows], title)
    path = artifacts.artifact_path(platform, name, "index", root=root)
    meta = artifacts.write_text_artifact(path, text)
    repository.upsert_artifact(
        conn,
        item_id=None,
        artifact_type="index",
        relative_path=str(meta["relative_path"]),
        sha256=str(meta["sha256"]),
    )
    return meta
