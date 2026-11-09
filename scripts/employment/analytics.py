"""文章与评论的统计聚合。"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable


def article_summary(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(items)
    platform = Counter(row["platform"] for row in rows)
    cohort = Counter(row["cohort"] for row in rows)
    topic = Counter(row["topic"] for row in rows)
    verification = Counter(row["verification_status"] for row in rows)
    return {
        "total": len(rows),
        "by_platform": dict(platform),
        "by_cohort": dict(cohort),
        "by_topic": dict(topic),
        "by_verification": dict(verification),
    }


def comment_summary(comments: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(comments)
    top_level = sum(1 for row in rows if int(row.get("comment_level", 1)) == 1)
    nested = len(rows) - top_level
    redacted = sum(1 for row in rows if row.get("redaction_status") == "redacted")
    return {
        "total": len(rows),
        "top_level": top_level,
        "nested": nested,
        "redacted": redacted,
    }


def coverage_summary(stats_rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(stats_rows)
    coverage = Counter(row.get("coverage_status", "not_available") for row in rows)
    return {
        "articles": len(rows),
        "by_coverage": dict(coverage),
        "top_level_collected": sum(int(row.get("collected_top_level", 0)) for row in rows),
        "nested_collected": sum(int(row.get("collected_replies", 0)) for row in rows),
    }
