"""就业情报的 SQLite 数据访问层。

文章复用 V2 的 research_items；评论、Campaign、Batch、Artifact 使用 V3 迁移
新增的表。所有 SQL 均参数化，写操作使用事务。
"""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Any, Iterable

from scripts import db
from scripts.employment.models import (
    ARTIFACT_TYPES,
    BATCH_STATUSES,
    CAMPAIGN_STATUSES,
)
from scripts.employment.validate import validate_article, validate_comment, validate_stats


def save_article(conn: sqlite3.Connection, payload: dict[str, Any]) -> tuple[str, bool]:
    """校验并幂等写入一篇文章；返回 (item_id, created)。"""
    cleaned = validate_article(payload)
    return db.upsert_research_item(conn, **cleaned)


def link_run(conn: sqlite3.Connection, run_id: str, item_id: str, action: str = "imported") -> None:
    db.link_run_research_item(conn, run_id, item_id, action)


def list_articles(
    conn: sqlite3.Connection,
    *,
    cohort: str | None = None,
    platform: str | None = None,
    topic: str | None = None,
    verification: str | None = None,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    return db.list_research_items(
        conn,
        cohort=cohort,
        platform=platform,
        topic=topic,
        verification=verification,
        limit=limit,
    )


def get_article(conn: sqlite3.Connection, item_id: str) -> sqlite3.Row | None:
    return db.get_research_item(conn, item_id)


def attach_article(
    conn: sqlite3.Connection,
    item_id: str,
    *,
    campaign_id: str | None = None,
    batch_id: str | None = None,
) -> None:
    with conn:
        conn.execute(
            "UPDATE research_items SET campaign_id = COALESCE(?, campaign_id), "
            "batch_id = COALESCE(?, batch_id), updated_at = ? WHERE item_id = ?",
            (campaign_id, batch_id, db.utc_now(), item_id),
        )


def _comment_id(item_id: str, external_id: str | None, parent_id: str | None, digest: str) -> str:
    basis = f"{item_id}\n{external_id or ''}\n{parent_id or ''}\n{digest}"
    return "cm_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def _find_comment(
    conn: sqlite3.Connection,
    item_id: str,
    cleaned: dict[str, Any],
) -> sqlite3.Row | None:
    external = cleaned["platform_comment_id"]
    if external:
        row = conn.execute(
            "SELECT comment_id FROM research_comments "
            "WHERE research_item_id = ? AND platform_comment_id = ?",
            (item_id, external),
        ).fetchone()
        if row:
            return row
    return conn.execute(
        "SELECT comment_id FROM research_comments "
        "WHERE research_item_id = ? "
        "AND COALESCE(parent_comment_id, '') = COALESCE(?, '') "
        "AND content_hash = ? AND comment_level = ? "
        "AND COALESCE(published_time_displayed, '') = COALESCE(?, '')",
        (
            item_id,
            cleaned["parent_comment_id"],
            cleaned["content_hash"],
            cleaned["comment_level"],
            cleaned["published_time_displayed"],
        ),
    ).fetchone()


def _insert_thread(
    conn: sqlite3.Connection,
    item_id: str,
    node: dict[str, Any],
    *,
    parent_id: str | None,
    root_id: str | None,
    level: int,
    collected_at: str,
    counter: list[int],
    counts: dict[str, int],
) -> None:
    counter[0] += 1
    cleaned = validate_comment(
        {
            **node,
            "research_item_id": item_id,
            "parent_comment_id": parent_id if level > 1 else None,
            "root_comment_id": root_id if level > 1 else None,
            "comment_level": level,
            "collected_at": collected_at,
            "collection_order": counter[0],
        }
    )
    existing = _find_comment(conn, item_id, cleaned)
    if existing is None:
        comment_id = _comment_id(
            item_id,
            cleaned["platform_comment_id"],
            parent_id,
            cleaned["content_hash"],
        )
        conn.execute(
            "INSERT INTO research_comments (comment_id, research_item_id, platform_comment_id, "
            "parent_comment_id, root_comment_id, comment_level, content, content_hash, "
            "like_count, reply_count_displayed, published_at, published_time_displayed, "
            "collected_at, collection_order, sort_basis, redaction_status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                comment_id,
                item_id,
                cleaned["platform_comment_id"],
                cleaned["parent_comment_id"],
                cleaned["root_comment_id"],
                cleaned["comment_level"],
                cleaned["content"],
                cleaned["content_hash"],
                cleaned["like_count"],
                cleaned["reply_count_displayed"],
                cleaned["published_at"],
                cleaned["published_time_displayed"],
                cleaned["collected_at"],
                cleaned["collection_order"],
                cleaned["sort_basis"],
                cleaned["redaction_status"],
            ),
        )
        counts["inserted"] += 1
        if level == 1:
            counts["top_level"] += 1
        else:
            counts["nested"] += 1
    else:
        comment_id = str(existing["comment_id"])
        counts["existing"] += 1

    for child in node.get("children") or []:
        _insert_thread(
            conn,
            item_id,
            child,
            parent_id=comment_id,
            root_id=comment_id if level == 1 else root_id,
            level=level + 1,
            collected_at=collected_at,
            counter=counter,
            counts=counts,
        )


def import_comment_thread(
    conn: sqlite3.Connection,
    item_id: str,
    nodes: Iterable[dict[str, Any]],
    *,
    collected_at: str | None = None,
) -> dict[str, int]:
    """导入一级评论及其嵌套回复；返回插入/已存在计数。"""
    collected_at = collected_at or db.utc_now()
    counts = {"inserted": 0, "existing": 0, "top_level": 0, "nested": 0}
    counter = [0]
    with conn:
        for node in nodes:
            _insert_thread(
                conn,
                item_id,
                node,
                parent_id=None,
                root_id=None,
                level=1,
                collected_at=collected_at,
                counter=counter,
                counts=counts,
            )
    return counts


def list_comments(conn: sqlite3.Connection, item_id: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM research_comments WHERE research_item_id = ? "
            "ORDER BY comment_level, collection_order",
            (item_id,),
        )
    )


def update_article_stats(
    conn: sqlite3.Connection,
    item_id: str,
    stats: dict[str, Any],
) -> dict[str, Any]:
    cleaned = validate_stats(stats)
    with conn:
        cursor = conn.execute(
            "UPDATE research_items SET displayed_comments_total = ?, displayed_top_level = ?, "
            "collected_top_level = ?, displayed_replies_total = ?, collected_replies = ?, "
            "comment_coverage_status = ?, comment_sort_basis = ?, updated_at = ? "
            "WHERE item_id = ?",
            (
                cleaned.get("displayed_total"),
                cleaned.get("displayed_top_level"),
                cleaned.get("collected_top_level", 0),
                cleaned.get("displayed_replies"),
                cleaned.get("collected_replies", 0),
                cleaned["coverage_status"],
                cleaned.get("sort_basis"),
                db.utc_now(),
                item_id,
            ),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"研究条目不存在：{item_id}")
    return cleaned


def set_article_markdown_paths(
    conn: sqlite3.Connection,
    item_id: str,
    *,
    post_path: str | None = None,
    comments_path: str | None = None,
) -> None:
    with conn:
        conn.execute(
            "UPDATE research_items SET post_markdown_path = COALESCE(?, post_markdown_path), "
            "comments_markdown_path = COALESCE(?, comments_markdown_path), updated_at = ? "
            "WHERE item_id = ?",
            (post_path, comments_path, db.utc_now(), item_id),
        )


def upsert_artifact(
    conn: sqlite3.Connection,
    *,
    item_id: str | None,
    artifact_type: str,
    relative_path: str,
    sha256: str,
    status: str = "present",
) -> str:
    if artifact_type not in ARTIFACT_TYPES:
        raise ValueError(f"不支持的产物类型：{artifact_type}")
    artifact_id = "ar_" + hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:16]
    now = db.utc_now()
    with conn:
        conn.execute(
            "INSERT INTO research_artifacts (artifact_id, research_item_id, artifact_type, "
            "relative_path, sha256, generated_at, status) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(relative_path) DO UPDATE SET research_item_id = excluded.research_item_id, "
            "artifact_type = excluded.artifact_type, sha256 = excluded.sha256, "
            "generated_at = excluded.generated_at, status = excluded.status",
            (artifact_id, item_id, artifact_type, relative_path, sha256, now, status),
        )
    return artifact_id


def create_campaign(
    conn: sqlite3.Connection,
    campaign_id: str,
    name: str,
    *,
    target_total: int = 0,
    target_xiaohongshu: int = 0,
    target_zhihu: int = 0,
    target_2026: int = 0,
    target_2027: int = 0,
    notes: str | None = None,
) -> None:
    with conn:
        conn.execute(
            "INSERT INTO research_campaigns (campaign_id, name, status, target_total, "
            "target_xiaohongshu, target_zhihu, target_2026, target_2027, notes) "
            "VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?)",
            (
                campaign_id,
                name,
                target_total,
                target_xiaohongshu,
                target_zhihu,
                target_2026,
                target_2027,
                notes,
            ),
        )


def set_campaign_status(
    conn: sqlite3.Connection,
    campaign_id: str,
    status: str,
    *,
    actual_total: int | None = None,
    notes: str | None = None,
) -> None:
    if status not in CAMPAIGN_STATUSES:
        raise ValueError(f"不支持的 Campaign 状态：{status}")
    terminal = status in {"completed", "partial", "blocked", "failed"}
    now = db.utc_now()
    with conn:
        conn.execute(
            "UPDATE research_campaigns SET status = ?, actual_total = COALESCE(?, actual_total), "
            "notes = COALESCE(?, notes), started_at = COALESCE(started_at, ?), "
            "finished_at = CASE WHEN ? THEN ? ELSE finished_at END WHERE campaign_id = ?",
            (status, actual_total, notes, now, 1 if terminal else 0, now, campaign_id),
        )


def get_campaign(conn: sqlite3.Connection, campaign_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM research_campaigns WHERE campaign_id = ?", (campaign_id,)
    ).fetchone()


def create_batch(
    conn: sqlite3.Connection,
    batch_id: str,
    campaign_id: str,
    *,
    platform: str,
    cohort: str,
    keyword: str | None = None,
    target_articles: int = 0,
    checkpoint_path: str | None = None,
) -> None:
    with conn:
        conn.execute(
            "INSERT INTO research_batches (batch_id, campaign_id, platform, cohort, keyword, "
            "target_articles, checkpoint_path, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')",
            (batch_id, campaign_id, platform, cohort, keyword, target_articles, checkpoint_path),
        )


def update_batch(
    conn: sqlite3.Connection,
    batch_id: str,
    *,
    discovered: int | None = None,
    succeeded: int | None = None,
    failed: int | None = None,
    top_level_comments: int | None = None,
    nested_replies: int | None = None,
    status: str | None = None,
    checkpoint_path: str | None = None,
    error_summary: str | None = None,
) -> None:
    if status is not None and status not in BATCH_STATUSES:
        raise ValueError(f"不支持的批次状态：{status}")
    terminal = status in {"completed", "partial", "blocked", "failed"}
    now = db.utc_now()
    with conn:
        conn.execute(
            "UPDATE research_batches SET discovered = COALESCE(?, discovered), "
            "succeeded = COALESCE(?, succeeded), failed = COALESCE(?, failed), "
            "top_level_comments = COALESCE(?, top_level_comments), "
            "nested_replies = COALESCE(?, nested_replies), status = COALESCE(?, status), "
            "checkpoint_path = COALESCE(?, checkpoint_path), "
            "error_summary = COALESCE(?, error_summary), "
            "started_at = COALESCE(started_at, ?), "
            "finished_at = CASE WHEN ? THEN ? ELSE finished_at END WHERE batch_id = ?",
            (
                discovered,
                succeeded,
                failed,
                top_level_comments,
                nested_replies,
                status,
                checkpoint_path,
                error_summary,
                now,
                1 if terminal else 0,
                now,
                batch_id,
            ),
        )


def get_batch(conn: sqlite3.Connection, batch_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM research_batches WHERE batch_id = ?", (batch_id,)
    ).fetchone()

def set_article_classification(
    conn: sqlite3.Connection,
    item_id: str,
    *,
    employment_topic: str | None = None,
    employment_status: str | None = None,
    industry: str | None = None,
    graduation_cohort: str | None = None,
    event_year: int | None = None,
    salary_reported: bool | None = None,
    experience_type: str | None = None,
) -> None:
    """写入就业生态分类字段；枚举非法时拒绝。"""
    if employment_topic is not None and employment_topic not in db.EMPLOYMENT_TOPICS:
        raise ValueError(f"不支持的 employment_topic：{employment_topic}")
    if employment_status is not None and employment_status not in db.EMPLOYMENT_STATUSES:
        raise ValueError(f"不支持的 employment_status：{employment_status}")
    if experience_type is not None and experience_type not in db.EXPERIENCE_TYPES:
        raise ValueError(f"不支持的 experience_type：{experience_type}")
    if graduation_cohort is not None and graduation_cohort not in {"2026", "2027", "other", "unknown"}:
        raise ValueError(f"不支持的 graduation_cohort：{graduation_cohort}")
    if event_year is not None and not (2000 <= int(event_year) <= 2100):
        raise ValueError("event_year 必须在 2000–2100")
    with conn:
        cursor = conn.execute(
            "UPDATE research_items SET employment_topic = COALESCE(?, employment_topic), "
            "employment_status = COALESCE(?, employment_status), industry = COALESCE(?, industry), "
            "graduation_cohort = COALESCE(?, graduation_cohort), event_year = COALESCE(?, event_year), "
            "salary_reported = COALESCE(?, salary_reported), experience_type = COALESCE(?, experience_type), "
            "updated_at = ? WHERE item_id = ?",
            (
                employment_topic, employment_status, industry, graduation_cohort,
                event_year, 1 if salary_reported is True else (0 if salary_reported is False else None),
                experience_type, db.utc_now(), item_id,
            ),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"研究条目不存在：{item_id}")


def record_search_query(
    conn: sqlite3.Connection,
    *,
    query_id: str,
    platform: str,
    dimension: str,
    keyword: str,
    raw_count: int,
    unique_count: int,
    new_count: int,
    duplicate_count: int,
    batch_id: str | None = None,
) -> None:
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO research_search_queries (query_id, batch_id, platform, "
            "dimension, keyword, raw_count, unique_count, new_count, duplicate_count, executed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (query_id, batch_id, platform, dimension, keyword, raw_count, unique_count,
             new_count, duplicate_count, db.utc_now()),
        )


def add_keyword_candidate(
    conn: sqlite3.Connection,
    *,
    keyword: str,
    dimension: str,
    source_batch: str | None = None,
    notes: str | None = None,
    status: str = "candidate",
) -> None:
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO research_keyword_candidates "
            "(keyword, dimension, source_batch, status, notes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (keyword, dimension, source_batch, status, notes, db.utc_now()),
        )
