"""就业情报的数据结构、枚举与常量。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PLATFORMS: tuple[str, ...] = ("zhihu", "xiaohongshu", "official", "media", "other")
SOURCE_TYPES: tuple[str, ...] = ("official", "reported", "ugc", "search_lead")
TOPICS: tuple[str, ...] = (
    "recruitment",
    "experience",
    "policy",
    "industry",
    "salary",
    "warning",
    "other",
)
COHORTS: tuple[str, ...] = ("2026", "2027", "unknown")
RECRUITMENT_STAGES: tuple[str, ...] = (
    "autumn",
    "spring",
    "makeup",
    "early",
    "internship",
    "other",
    "unknown",
)
VERIFICATION_STATUSES: tuple[str, ...] = (
    "unverified",
    "partially_verified",
    "verified",
    "contradicted",
    "expired",
)
SORT_BASES: tuple[str, ...] = (
    "high_likes",
    "latest",
    "high_likes_then_latest",
    "visible_order",
)
COVERAGE_STATUSES: tuple[str, ...] = ("complete", "partial", "blocked", "not_available")
CAMPAIGN_STATUSES: tuple[str, ...] = (
    "pending",
    "running",
    "partial",
    "completed",
    "blocked",
    "failed",
)
BATCH_STATUSES: tuple[str, ...] = CAMPAIGN_STATUSES
ARTIFACT_TYPES: tuple[str, ...] = (
    "post_markdown",
    "comments_markdown",
    "index",
    "report",
)

# 评论作者身份字段：任何进入入库路径的结构都必须拒绝这些键。
AUTHOR_FIELDS: frozenset[str] = frozenset(
    {
        "author",
        "author_name",
        "author_id",
        "nickname",
        "avatar",
        "avatar_url",
        "user_id",
        "user_url",
        "profile_url",
        "homepage",
        "bio",
        "signature",
        "location",
        "ip_location",
        "contact",
        "phone",
        "email",
        "wechat",
        "weixin",
        "qq",
    }
)


@dataclass
class ArticleRecord:
    platform: str
    canonical_url: str
    title: str
    source_type: str = "ugc"
    topic: str = "other"
    cohort: str = "unknown"
    recruitment_stage: str = "unknown"
    summary: str | None = None
    company: str | None = None
    city: str | None = None
    published_at: str | None = None
    verification_status: str = "unverified"
    verification_url: str | None = None
    verified_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class CommentRecord:
    research_item_id: str
    content: str
    comment_level: int = 1
    platform_comment_id: str | None = None
    parent_comment_id: str | None = None
    root_comment_id: str | None = None
    like_count: int | None = None
    reply_count_displayed: int | None = None
    published_at: str | None = None
    published_time_displayed: str | None = None
    collected_at: str | None = None
    collection_order: int = 0
    sort_basis: str = "visible_order"
    redaction_status: str = "clean"
    content_hash: str | None = None


@dataclass
class CommentStats:
    displayed_total: int | None = None
    displayed_top_level: int | None = None
    collected_top_level: int = 0
    displayed_replies: int | None = None
    collected_replies: int = 0
    sort_basis: str = "visible_order"
    coverage_status: str = "not_available"
    reason: str | None = None
