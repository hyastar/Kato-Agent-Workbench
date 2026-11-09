"""就业情报的 SQLite 数据访问层。

文章复用 V2 的 research_items；评论、Campaign、Batch、Artifact 在 V3 迁移后
由本模块提供事务写入。所有 SQL 均参数化。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from scripts import db
from scripts.employment.validate import validate_article


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
